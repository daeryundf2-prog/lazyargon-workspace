#!/usr/bin/env node
/**
 * case_mode.mjs — Case mode: sandbox-isolated evidence workspace for Antigravity / LazyArgon Workspace
 *
 * Usage:
 *   node scripts/case_mode.mjs init <evidence-path> [--out <case-work-dir>]
 *   node scripts/case_mode.mjs close [--case <case-work-dir>]
 *
 * Or via the bin wrapper:
 *   bin/case-mode init /path/to/evidence --out /path/to/case
 *   bin/case-mode close --case /path/to/case
 *
 * What 'init' does:
 *   1. Creates the case work directory (<cwd>/case-<evidence-basename>-<date> unless --out given).
 *   2. Writes <work>/.agents/case-settings.json — Antigravity sandbox settings:
 *        enableTerminalSandbox, proceed-in-sandbox, evidence read_file only, deny write_file,
 *        deny download_url/execute_url, allow the research allowlist (other hosts fall back to Ask).
 *   3. Hashes every file in the evidence (SHA-256; E01 segments: each segment file).
 *      Writes <work>/custody/hashes-start.json and appends to <work>/custody/log.jsonl.
 *   4. Prints the exact 'agy --sandbox --settings <file>' command and App preset steps.
 *
 * What 'close' does:
 *   Re-hashes all evidence files recorded at init, fails loudly on any change, missing file,
 *   or unexpected new file. Appends a close event to custody/log.jsonl.
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// ---------------------------------------------------------------------------
// Research URL allowlist: config/case-mode-research-allowlist.json (owner-editable)
// ---------------------------------------------------------------------------
const ALLOWLIST_FILE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'config', 'case-mode-research-allowlist.json');
const RESEARCH_URL_ALLOWLIST = JSON.parse(fs.readFileSync(ALLOWLIST_FILE, 'utf8')).hosts;

// ---------------------------------------------------------------------------
// SHA-256 streaming (avoids loading large evidence files into memory)
// ---------------------------------------------------------------------------
function sha256File(filePath) {
	return new Promise((resolve, reject) => {
		const hash = crypto.createHash('sha256');
		const stream = fs.createReadStream(filePath);
		stream.on('data', (chunk) => hash.update(chunk));
		stream.on('end', () => resolve(hash.digest('hex')));
		stream.on('error', reject);
	});
}

// ---------------------------------------------------------------------------
// Evidence discovery: folder → all files; E01 → segment set (E01, E02, …)
// ---------------------------------------------------------------------------
function collectEvidenceFiles(evidencePath) {
	const stat = fs.statSync(evidencePath);
	if (stat.isDirectory()) {
		// Recursively collect all files under the directory
		const files = [];
		function walk(dir) {
			for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
				const full = path.join(dir, entry.name);
				if (entry.isDirectory()) walk(full);
				else if (entry.isFile()) files.push(full);
			}
		}
		walk(evidencePath);
		return files.sort();
	}
	// Single file: if it's an E01 (or similar split image), collect all segments
	const ext = path.extname(evidencePath).toLowerCase();
	if (['.e01', '.ex01', '.l01', '.ad1'].includes(ext)) {
		return collectE01Segments(evidencePath);
	}
	return [evidencePath];
}

/**
 * Given disk.E01, finds disk.E01, disk.E02, … disk.E99 (up to EAA if needed)
 * that exist in the same directory.
 */
function collectE01Segments(firstSegment) {
	const dir = path.dirname(firstSegment);
	const base = path.basename(firstSegment);
	const dotIdx = base.lastIndexOf('.');
	const stem = base.slice(0, dotIdx);
	const ext = base.slice(dotIdx + 1); // e.g. 'E01'
	const prefix = ext[0].toUpperCase(); // 'E', 'L', 'A'
	const segments = [firstSegment];
	// Try numeric suffixes: E02 … E99
	const numStr = ext.slice(1); // '01'
	let n = parseInt(numStr, 10);
	for (let i = 1; i <= 999; i++) {
		n++;
		const nextSuffix = prefix + String(n).padStart(numStr.length, '0');
		const candidate = path.join(dir, `${stem}.${nextSuffix}`);
		if (!fs.existsSync(candidate)) break;
		segments.push(candidate);
	}
	return segments;
}

// ---------------------------------------------------------------------------
// Hash all evidence files → array of {path, sha256, sizeBytes}
// ---------------------------------------------------------------------------
async function hashEvidence(files) {
	const results = [];
	for (const f of files) {
		const stat = fs.statSync(f);
		const sha256 = await sha256File(f);
		results.push({ path: f, sha256, sizeBytes: stat.size });
	}
	return results;
}

// ---------------------------------------------------------------------------
// Settings JSON builder
// ---------------------------------------------------------------------------
function buildCaseSettings(evidencePaths) {
	// evidencePaths: array of resolved paths that need read_file allow + write_file deny
	const allow = evidencePaths.flatMap((p) => [`read_file(${p})`]);
	const deny = [
		...evidencePaths.flatMap((p) => [`write_file(${p})`]),
		'download_url(*)',
		'execute_url(*)',
	];
	// Research allowlist
	for (const host of RESEARCH_URL_ALLOWLIST) {
		allow.push(`read_url(${host})`);
	}
	return {
		enableTerminalSandbox: true,
		toolPermission: 'proceed-in-sandbox',
		allowNonWorkspaceAccess: false,
		// No ask rule for read_url(*): Antigravity evaluates Deny > Ask > Allow, so an ask(*) would override
		// every allowlisted host. Unlisted hosts already fall back to Ask by default.
		permissions: {
			allow,
			deny,
		},
	};
}

// ---------------------------------------------------------------------------
// Print the agy command and App steps
// ---------------------------------------------------------------------------
function printLaunchInstructions(settingsFile, caseDir) {
	const rel = path.relative(process.cwd(), settingsFile);
	console.log('');
	console.log('═══════════════════════════════════════════════════════════════');
	console.log('  CASE MODE — 세션 시작 방법');
	console.log('═══════════════════════════════════════════════════════════════');
	console.log('');
	console.log('  [CLI — 권장]');
	console.log(`  agy --sandbox --settings '${settingsFile}' --workspace '${caseDir}'`);
	console.log('');
	console.log('  [App — Settings > Projects > preset override]');
	console.log(`  1. Settings 열기 → Projects 탭`);
	console.log(`  2. 케이스 작업 폴더를 프로젝트로 추가: ${caseDir}`);
	console.log(`  3. "Terminal Sandbox" 활성화`);
	console.log(`  4. "Settings file" 경로 입력: ${settingsFile}`);
	console.log(`  5. "Workspace": ${caseDir}`);
	console.log('');
	console.log(`  설정 파일: ${rel}`);
	console.log('');
	console.log('  증거 파일에 대해 허용: read_file (해시 감사·strings·조사)');
	console.log('  차단: write_file (증거 쓰기), download_url, execute_url');
	console.log('  기본값(물어봄): 허용 목록에 없는 사이트');
	console.log('═══════════════════════════════════════════════════════════════');
	console.log('');
}

// ---------------------------------------------------------------------------
// Custody log append (append-only JSONL)
// ---------------------------------------------------------------------------
function appendCustodyLog(logPath, entry) {
	fs.appendFileSync(logPath, JSON.stringify(entry) + '\n', 'utf8');
}

// ---------------------------------------------------------------------------
// 'init' command
// ---------------------------------------------------------------------------
async function cmdInit(argv) {
	// Parse args: case_mode.mjs init <evidence-path> [--out <dir>]
	let evidencePath = null;
	let outDir = null;
	for (let i = 0; i < argv.length; i++) {
		if (argv[i] === '--out' && argv[i + 1]) {
			outDir = argv[++i];
		} else if (!argv[i].startsWith('--')) {
			evidencePath = argv[i];
		}
	}
	if (!evidencePath) {
		console.error('Usage: case_mode.mjs init <evidence-path> [--out <case-work-dir>]');
		process.exit(2);
	}

	const absEvidence = path.resolve(evidencePath);
	if (!fs.existsSync(absEvidence)) {
		console.error(`Error: evidence path not found: ${absEvidence}`);
		process.exit(1);
	}

	// Determine case work dir
	const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
	const evidenceName = path.basename(absEvidence).replace(/\.[^.]+$/, '');
	const defaultOut = path.join(process.cwd(), `case-${evidenceName}-${stamp}`);
	const caseDir = path.resolve(outDir || defaultOut);

	console.log(`[case-mode] Initializing case...`);
	console.log(`  Evidence : ${absEvidence}`);
	console.log(`  Case dir : ${caseDir}`);

	// Create directory structure
	const agentsDir = path.join(caseDir, '.agents');
	const custodyDir = path.join(caseDir, 'custody');
	fs.mkdirSync(agentsDir, { recursive: true });
	fs.mkdirSync(custodyDir, { recursive: true });

	// Collect evidence files
	console.log(`[case-mode] Collecting evidence files...`);
	const evidenceFiles = collectEvidenceFiles(absEvidence);
	console.log(`  Found ${evidenceFiles.length} file(s)`);

	// Hash all evidence files
	console.log(`[case-mode] Computing SHA-256 hashes...`);
	const hashes = await hashEvidence(evidenceFiles);

	// Write hashes-start.json
	const hashesStart = {
		caseDir,
		evidencePath: absEvidence,
		timestamp: new Date().toISOString(),
		tool: 'case_mode.mjs init',
		note: 'SHA-256 hashes at case open — reference baseline for close verification',
		files: hashes,
	};
	const hashesFile = path.join(custodyDir, 'hashes-start.json');
	fs.writeFileSync(hashesFile, JSON.stringify(hashesStart, null, 2) + '\n', 'utf8');
	console.log(`[case-mode] Custody hashes written: ${path.relative(process.cwd(), hashesFile)}`);

	// Append to custody log
	const logFile = path.join(custodyDir, 'log.jsonl');
	appendCustodyLog(logFile, {
		type: 'init',
		timestamp: new Date().toISOString(),
		caseDir,
		evidencePath: absEvidence,
		fileCount: hashes.length,
		files: hashes,
	});

	// Build and write case-settings.json
	// Determine what paths to protect: the evidence path itself (and its parent dir if file)
	const protectedPaths = fs.statSync(absEvidence).isDirectory()
		? [absEvidence]
		: [absEvidence, path.dirname(absEvidence)];
	const settings = buildCaseSettings(protectedPaths);
	const settingsFile = path.join(agentsDir, 'case-settings.json');
	fs.writeFileSync(settingsFile, JSON.stringify(settings, null, 2) + '\n', 'utf8');
	console.log(`[case-mode] Settings written  : ${path.relative(process.cwd(), settingsFile)}`);

	// Print launch instructions
	printLaunchInstructions(settingsFile, caseDir);

	// Summary
	console.log(`[case-mode] Case initialized.`);
	for (const { path: p, sha256, sizeBytes } of hashes) {
		const rel = path.relative(absEvidence, p);
		const display = rel === '' ? path.basename(p) : rel;
		console.log(`  ${sha256.slice(0, 16)}…  ${display}  (${(sizeBytes / 1024 / 1024).toFixed(2)} MiB)`);
	}
	console.log('');
	console.log(`  case close --case '${caseDir}' を실행하면 증거 무결성을 재검증합니다.`);
}

// ---------------------------------------------------------------------------
// 'close' command
// ---------------------------------------------------------------------------
async function cmdClose(argv) {
	let caseDir = null;
	for (let i = 0; i < argv.length; i++) {
		if (argv[i] === '--case' && argv[i + 1]) {
			caseDir = argv[++i];
		} else if (!argv[i].startsWith('--')) {
			caseDir = argv[i];
		}
	}

	// If not given, try CWD
	if (!caseDir) {
		caseDir = process.cwd();
	}

	const absCaseDir = path.resolve(caseDir);
	const hashesFile = path.join(absCaseDir, 'custody', 'hashes-start.json');

	if (!fs.existsSync(hashesFile)) {
		console.error(`Error: no hashes-start.json found in ${absCaseDir}/custody/`);
		console.error('  Run "case init <evidence>" first.');
		process.exit(1);
	}

	const baseline = JSON.parse(fs.readFileSync(hashesFile, 'utf8'));
	console.log(`[case-mode] Closing case...`);
	console.log(`  Case dir : ${absCaseDir}`);
	console.log(`  Evidence : ${baseline.evidencePath}`);
	console.log(`  Opened   : ${baseline.timestamp}`);
	console.log(`  Verifying ${baseline.files.length} file(s)...`);

	const changed = [];
	const missing = [];
	const baselineMap = new Map(baseline.files.map((f) => [f.path, f]));

	for (const orig of baseline.files) {
		if (!fs.existsSync(orig.path)) {
			missing.push(orig.path);
			continue;
		}
		const currentHash = await sha256File(orig.path);
		if (currentHash !== orig.sha256) {
			changed.push({
				path: orig.path,
				originalSha256: orig.sha256,
				currentSha256: currentHash,
			});
		}
	}

	// Check for unexpected new files (if evidence is a directory)
	const unexpected = [];
	if (fs.existsSync(baseline.evidencePath) && fs.statSync(baseline.evidencePath).isDirectory()) {
		const currentFiles = collectEvidenceFiles(baseline.evidencePath);
		for (const f of currentFiles) {
			if (!baselineMap.has(f)) {
				unexpected.push(f);
			}
		}
	}

	const hasProblems = changed.length > 0 || missing.length > 0 || unexpected.length > 0;

	// Append close event to custody log
	const logFile = path.join(absCaseDir, 'custody', 'log.jsonl');
	appendCustodyLog(logFile, {
		type: 'close',
		timestamp: new Date().toISOString(),
		caseDir: absCaseDir,
		evidencePath: baseline.evidencePath,
		status: hasProblems ? 'INTEGRITY_FAIL' : 'ok',
		changed,
		missing,
		unexpected,
	});

	if (hasProblems) {
		console.error('');
		console.error('╔══════════════════════════════════════════════════════════╗');
		console.error('║  [CASE-MODE] 증거 무결성 검증 실패 — INTEGRITY FAIL     ║');
		console.error('╚══════════════════════════════════════════════════════════╝');
		if (changed.length > 0) {
			console.error(`\n  변조된 파일 (${changed.length}개):`);
			for (const c of changed) {
				console.error(`    CHANGED  ${c.path}`);
				console.error(`             원본: ${c.originalSha256}`);
				console.error(`             현재: ${c.currentSha256}`);
			}
		}
		if (missing.length > 0) {
			console.error(`\n  삭제된 파일 (${missing.length}개):`);
			for (const m of missing) {
				console.error(`    MISSING  ${m}`);
			}
		}
		if (unexpected.length > 0) {
			console.error(`\n  예상치 못한 신규 파일 (${unexpected.length}개):`);
			for (const u of unexpected) {
				console.error(`    NEW      ${u}`);
			}
		}
		console.error('');
		console.error('  증거 훼손 가능성이 있습니다. 보관 담당자에게 즉시 보고하세요.');
		console.error('');
		process.exit(1);
	} else {
		console.log('');
		console.log('  ✓ 증거 무결성 검증 완료 — 모든 파일 해시 일치');
		console.log(`    검증 파일 수: ${baseline.files.length}`);
		console.log('');
		process.exit(0);
	}
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------
const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
	const sub = process.argv[2];
	const rest = process.argv.slice(3);
	if (sub === 'init') {
		cmdInit(rest).catch((e) => { console.error(e.message); process.exit(1); });
	} else if (sub === 'close') {
		cmdClose(rest).catch((e) => { console.error(e.message); process.exit(1); });
	} else {
		console.error('Usage:');
		console.error('  node scripts/case_mode.mjs init <evidence-path> [--out <case-dir>]');
		console.error('  node scripts/case_mode.mjs close [--case <case-dir>]');
		process.exit(2);
	}
}

export { buildCaseSettings, collectE01Segments, collectEvidenceFiles, hashEvidence, RESEARCH_URL_ALLOWLIST };
