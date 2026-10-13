#!/usr/bin/env node
/**
 * evidence_guard.mjs - PreToolUse 증거 무결성 보호(Write-Lock) 및 PostToolUse 해시 체크포인트 훅
 * Antigravity 호환: stdin JSON (tool_input) + 환경변수 + CLI 인자를 각각 독립 수집.
 *
 * stdin 규약: 호스트가 JSON을 쓰고 파이프를 닫는다고 가정하고 1.5초 데드라인으로 비동기 읽는다.
 * (fstat().size 는 POSIX 파이프에서 정의되지 않아 Linux/Windows 에서 항상 0이므로 유무 판정에 쓰지 않는다)
 *
 * exit 규약: 차단=1, 통과=0. 이 훅이 실제로 차단하려면 호스트가 hooks.json 의
 * failurePolicy: FAIL_CLOSED 로 exit 1 을 쓰기 차단으로 해석해야 한다 (미해석 시 best-effort).
 *
 * 한계 (docs/GAPS.md 참고): 실제 파일시스템 강제 잠금이 아니며, 호스트가 훅 stdin 을 주지
 * 않거나 매칭되지 않는 도구/우회 경로는 막을 수 없다. 증거 디렉토리는 OS 수준 읽기전용 병행.
 */

import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { stdin } from 'node:process';

const hookType = (process.argv[2] || 'pre-tool-use').replace(/_/g, '-');

// ---------------------------------------------------------------------------
// 입력 수집: 각 소스를 독립 보관 (JSON.parse 는 소스별로 따로 시도한다 —
// 서로 다른 소스를 '\n'으로 합쳐 파싱하면 어느 한쪽만 있어도 파싱이 깨진다)
// ---------------------------------------------------------------------------

function readStdin(limitMs) {
	return new Promise((resolve) => {
		if (stdin.isTTY) {
			resolve('');
			return;
		}
		const chunks = [];
		let settled = false;
		const finish = (value) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			stdin.removeAllListeners();
			resolve(value);
		};
		const timer = setTimeout(() => finish(Buffer.concat(chunks).toString('utf8')), limitMs);
		stdin.on('data', (chunk) => chunks.push(chunk));
		stdin.on('end', () => finish(Buffer.concat(chunks).toString('utf8')));
		stdin.on('error', () => finish(''));
	});
}

function tryParseJson(text) {
	if (!text) return undefined;
	const t = text.trim();
	if (!t.startsWith('{') && !t.startsWith('[')) return undefined;
	try {
		return JSON.parse(t);
	} catch {
		return undefined;
	}
}

// tool_input 에서 경로/명령에 해당하는 키의 문자열 값만 수집한다.
// content/쓰기 본문은 스캔하지 않는다 — 보고서 본문에 "evidence/", "image.raw" 가
// 언급되는 것만으로 쓰기가 차단되는 과차단을 막기 위함이다.
const PATHISH_KEY_RE = /^(file_path|filepath|file|filename|target|target_file|targetfile|target_path|targetpath|output|path|command|cmd|command_line|commandline|script|args)$/i;

function deepCollectPathish(node, out) {
	if (Array.isArray(node)) {
		for (const item of node) deepCollectPathish(item, out);
		return;
	}
	if (!node || typeof node !== 'object') return;
	for (const [key, value] of Object.entries(node)) {
		if (typeof value === 'string') {
			if (PATHISH_KEY_RE.test(key)) out.push(value);
		} else if (value && typeof value === 'object') {
			deepCollectPathish(value, out);
		}
	}
}

async function collectSources() {
	const sources = [];
	const push = (text, label) => {
		if (text) sources.push({ text, parsed: tryParseJson(text), label });
	};
	// 1) 환경변수 (레거시/테스트 호환)
	for (const k of ['ANTIGRAVITY_TOOL_INPUT', 'TOOL_INPUT', 'ANTIGRAVITY_TARGET_FILE', 'TARGET_FILE']) {
		if (process.env[k]) push(process.env[k], `env:${k}`);
	}
	// 2) stdin JSON (Antigravity 실제 경로)
	push(await readStdin(1500), 'stdin');
	// 3) CLI 인자로 전달된 JSON/경로 (일부 호스트)
	for (const arg of process.argv.slice(3)) push(arg, 'argv');
	return sources;
}

// 패턴 검사 대상 문자열: 경로/명령 성격의 값들 + JSON이 아닌 원문 (env 단순 경로 등)
function scanStrings(sources) {
	const out = [];
	for (const s of sources) {
		if (s.parsed !== undefined) {
			deepCollectPathish(s.parsed, out);
			// JSON 파싱에 성공하면 원문은 재검사하지 않는다 (content 과차단 방지)
		} else {
			out.push(s.text);
		}
	}
	return out;
}

// 확장자 검사용 토큰: 공백/인용부호로 끊고 뒤에 붙은 문장부호를 제거
function pathTokens(texts) {
	const tokens = [];
	for (const text of texts) {
		for (const raw of String(text).split(/[\s"'`]+/)) {
			const token = raw.replace(/[,;:)\]]+$/, '');
			if (token) tokens.push(token);
		}
	}
	return tokens;
}

// ---------------------------------------------------------------------------
// 읽기전용 검사 명령 판별 — 증거 '읽기'(해시 감사·ls·파서 실행)는 쓰기가 아니므로
// 차단하지 않는다. 이 가드가 evidence/ 관례를 권하면서 읽기까지 막으면 자체
// 감사 워크플로(sha256sum evidence/x.raw)가 스스로 막히는 모순이 생긴다.
// 판단이 불가능한 형태(멀티라인, python -c 인라인 코드, 쓰기 신호 포함)는
// 전부 차단으로 간다 — best-effort 가드의 실패폐쇄 방향.
// ---------------------------------------------------------------------------
const READ_ONLY_VERBS = /^(sha256sum|md5sum|sha1sum|shasum|sha256deep|cat|ls|dir|file|stat|head|tail|wc|strings|exiftool|fls|ils|icat|img_stat|fsstat|jpeg_extract|python3?|py|node)\b/i;
const WRITE_SIGNS_RE = /(>|>>|\btee\b|\bdd\b|\bcp\b|\bmv\b|\brm\b|\bshred\b|\btruncate\b|\bchmod\b|\bchown\b|\bchattr\b|\bmkfs\b|\bsponge\b|\binstall\b|\btouch\b|\bmktemp\b|\bsed\b[^\n]*\s-i\b)/i;

function isReadOnlyInspection(text) {
	const t = String(text).trim();
	if (!t || t.includes('\n')) return false;              // 멀티라인 스크립트는 판단 불가
	if (!READ_ONLY_VERBS.test(t.split(/[\s"'`]+/)[0] || '')) return false;
	if (WRITE_SIGNS_RE.test(t)) return false;
	// 인터프리터 인라인 코드(-c/-m)는 쓰기를 숨길 수 있다 — 판단 불가로 차단 유지
	if (/\b(python3?|py|node)\b/i.test(t) && /\s-[cm]\b/.test(t)) return false;
	return true;
}

// ---------------------------------------------------------------------------
// 보호 패턴
// ---------------------------------------------------------------------------

const PROTECTED_EXTENSIONS = /\.(raw|dd|dmp|mem|vmem|img|l01|ad1|e01|ex01|aff|aff4|vmdk|vhd|evtx|evtxc)$/i;
// evidence 를 경로 세그먼트로 포함하는 토큰 (cp x evidence/ 같은 상대 경로 쓰기 포함).
// evidence_note.md 처럼 evidence 로 시작하는 다른 이름은 세그먼트가 아니므로 통과.
const EVIDENCE_SEGMENT_RE = /^(?:.*[\/\\])?evidence(?:[\/\\].*)?$/i;
const PROTECTED_PATTERNS = [
	{ re: /(^|\/|\\)evidence(\/|\\|$)/i, label: 'evidence directory' },
	{ re: /\$mft/i, label: '$MFT' },
	{ re: /\$logfile/i, label: '$Logfile' },
	{ re: /\$usnjrnl/i, label: '$UsnJrnl' },
	{ re: /\/dev\/.*(sda|nvme|rdisk)/i, label: 'raw block device' },
];
// 인라인 코드 실행 우회 벡터: 인터프리터 한 줄 실행은 쓰기를 숨길 수 있어
// 읽기전용 판정과 무관하게 차단한다 (python -c/-m 계열은 기존 검사 유지).
const INLINE_EXEC_RES = [
	/\bperl\b[^|&;\n]*\s-e\b/i,
	/\bruby\b[^|&;\n]*\s-e\b/i,
	/\bpowershell\b[^|&;\n]*\s-enc(odedcommand)?\b/i,
];

function findViolation(texts) {
	for (const text of texts) {
		for (const re of INLINE_EXEC_RES) {
			if (re.test(text)) return 'inline code execution (use a script file + audit instead)';
		}
		// 읽기전용 검사 명령은 증거 경로·확장자 언급을 허용한다($MFT·로우 디바이스
		// 패턴은 읽기라도 직접 접근 위험이 남아 차단 유지). 판정은 토큰이 아니라
		// 명령(텍스트) 단위로 한다 — "sha256sum evidence/x.raw"의 경로 토큰만
		// 떼어 보면 명령이 읽기인지 알 수 없다.
		const readOnly = isReadOnlyInspection(text);
		for (const { re, label } of PROTECTED_PATTERNS) {
			if (readOnly && label === 'evidence directory') continue;
			if (re.test(text)) return `pattern ${label}`;
		}
		if (readOnly) continue;
		for (const token of pathTokens([text])) {
			if (PROTECTED_EXTENSIONS.test(token)) return `protected extension: ${path.basename(token)}`;
			if (EVIDENCE_SEGMENT_RE.test(token)) return 'evidence directory';
		}
	}
	return null;
}

// ---------------------------------------------------------------------------
// PostToolUse: 대상 파일 추정 (환경변수 > JSON 경로 키 > 유니코드 경로 정규식 > argv)
// ---------------------------------------------------------------------------

const TARGET_KEY_RE = /^(file_path|filepath|path|target|target_file|targetfile|target_path|targetpath|output)$/i;
// \S 기반이므로 한글/공백 포함 경로도 매칭된다 (구버전 [\w\-\.] 은 ASCII 한정이었다)
const PATH_LIKE_RE = /([^\s"'`<>|;&]+[\/\\][^\s"'`<>|;&]+\.(?:md|html|txt|json|csv|png|mp4))/i;
const REDIRECT_RE = /(?:>|>>)\s*([^\s|&;]+(?:\.(?:md|html|txt|json)))/i;

function extractTargetFromNode(node, out) {
	if (Array.isArray(node)) {
		for (const item of node) extractTargetFromNode(item, out);
		return;
	}
	if (!node || typeof node !== 'object') return;
	for (const [key, value] of Object.entries(node)) {
		if (typeof value === 'string' && TARGET_KEY_RE.test(key) && value) out.push(value);
		else if (value && typeof value === 'object') extractTargetFromNode(value, out);
	}
}

function extractTarget(sources) {
	for (const s of sources) {
		if (s.parsed !== undefined) {
			const found = [];
			extractTargetFromNode(s.parsed, found);
			if (found.length > 0) return found[0];
		}
	}
	// JSON 이 아닌 원문: 리다이렉트(bash) 우선, 그 다음 일반 경로
	for (const s of sources) {
		if (s.parsed !== undefined) continue;
		const red = s.text.match(REDIRECT_RE);
		if (red) return red[1];
		const m = s.text.match(PATH_LIKE_RE);
		if (m) return m[1];
	}
	return '';
}

// ---------------------------------------------------------------------------
// SHA-256 (스트리밍 — 큰 파일을 통째로 메모리에 올리지 않는다)
// ---------------------------------------------------------------------------

function calculateSha256(filePath) {
	return new Promise((resolve) => {
		const hash = crypto.createHash('sha256');
		const stream = fs.createReadStream(filePath, { highWaterMark: 1024 * 1024 });
		stream.on('data', (chunk) => hash.update(chunk));
		stream.on('end', () => resolve(hash.digest('hex')));
		stream.on('error', () => resolve(null));
	});
}

const MAX_AUDIT_BYTES = 2 * 1024 * 1024 * 1024; // 2GiB 초과는 해시 대신 skip 기록

// ---------------------------------------------------------------------------

async function main() {
	const sources = await collectSources();

	if (hookType === 'pre-tool-use') {
		const texts = scanStrings(sources);
		const violation = findViolation(texts);
		if (violation) {
			console.error(`[FORENSIC INTEGRITY GUARD] Write operation BLOCKED — ${violation}`);
			console.error('[HINT] Evidence files are read-only. 사본도 같은 확장자(.raw/.E01 등)면 차단된다 —');
			console.error('       사본은 확장자를 바꿔 보관(예: img.raw → img.raw.analysis.txt)하거나 증거 디렉토리 밖에서 작업.');
			console.error('       이것은 best-effort 가드다. 증거 디렉토리는 OS 읽기전용(chmod 444)을 병행할 것.');
			process.exit(1);
		}
		process.exit(0);
	}

	if (hookType === 'post-tool-use') {
		const targetFile = extractTarget(sources);
		if (!targetFile || !fs.existsSync(targetFile)) {
			process.exit(0);
		}

		// 감사 로그는 케이스 격리: <cwd>/.lazyforensic/audit_trail.jsonl 단일 파일.
		// (구버전이 만든 cwd 루트 audit_trail.jsonl 미러는 두 체인 로그가 갈라지므로 폐지)
		const resolvedTarget = path.resolve(targetFile);
		let auditLogPath = null;
		try {
			const auditDir = path.resolve(process.cwd(), '.lazyforensic');
			fs.mkdirSync(auditDir, { recursive: true });
			auditLogPath = path.join(auditDir, 'audit_trail.jsonl');
		} catch {
			process.exit(0); // 로그를 못 만들면 감사 기록도 없다 — 조용히 통과(FAIL_OPEN 훅)
		}

		let stat = null;
		try {
			stat = fs.statSync(resolvedTarget);
		} catch {
			process.exit(0);
		}

		const entry = {
			timestamp: new Date().toISOString(),
			file: resolvedTarget,
			sha256: null,
			sizeBytes: stat.size,
			hook: 'post-tool-use',
			note: 'best-effort SHA-256 checkpoint; not a chain-of-custody proof',
		};
		if (stat.size > MAX_AUDIT_BYTES) {
			entry.note = 'hash skipped: file exceeds 2GiB audit limit (absence of a hash here is a deliberate skip, not a failure)';
		} else {
			entry.sha256 = await calculateSha256(resolvedTarget);
			if (entry.sha256 === null) {
				// 해시 실패를 무기록으로 숨기지 않는다 — sha256:null + error 필드가
				// 체인에 남아야 '쓰기 없음'과 구별되는 갭이 된다 (tamper-evident).
				entry.note = 'hash FAILED: file could not be read for SHA-256 (recorded failure, not a deliberate skip)';
				entry.error = 'sha256_read_failed';
			}
		}
		if (entry.sha256 || entry.error || stat.size > MAX_AUDIT_BYTES) {
			try {
				// 해시체인(위변조 탐지용, HMAC 아님): 이전행 원문의 sha256을
				// 다음행 prev_hash로 연결한다. 단일 파일(audit_trail.jsonl) 유지.
				let prev_hash = null;
				try {
					if (fs.existsSync(auditLogPath)) {
						const lines = fs.readFileSync(auditLogPath, 'utf8').split('\n').filter(Boolean);
						if (lines.length > 0) prev_hash = crypto.createHash('sha256').update(lines[lines.length - 1], 'utf8').digest('hex');
					}
				} catch {}
				entry.prev_hash = prev_hash;
				// B2-2: LAZYFORENSIC_HMAC_KEY 있을 때만 HMAC-SHA256 서명 추가, 없으면 기존 체인 유지.
				try {
					const hmacKey = process.env.LAZYFORENSIC_HMAC_KEY;
					if (hmacKey) entry.hmac = crypto.createHmac('sha256', hmacKey).update([entry.timestamp, entry.file, entry.sha256 || '', entry.prev_hash || ''].join('|'), 'utf8').digest('hex');
				} catch {}
				fs.appendFileSync(auditLogPath, JSON.stringify(entry) + '\n', 'utf8');
			} catch {}
		}
		process.exit(0);
	}

	process.exit(0);
}

main();
