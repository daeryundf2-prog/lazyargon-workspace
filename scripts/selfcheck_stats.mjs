#!/usr/bin/env node
/**
 * selfcheck_stats.mjs — stop_claim_guard 되묻기가 실제로 답을 고쳤는지 종류별로 센다.
 *
 * 되묻기를 줄일지 정하려면 '되묻기 수'가 아니라 '되물었을 때 답이 고쳐진 비율'이 필요하다(2026-11-03 합의).
 * Antigravity 대화 기록(~/.gemini/antigravity/brain/<대화>/.system_generated/logs/transcript_full.jsonl)에서
 * 'Stop hook blocked termination: [SELF-CHECK' 단계를 찾아, 점검 문장의 종류와 바로 다음 모델 답을 본다.
 *   그대로: 다음 답이 '점검: 근거 있음' 줄뿐이다(내용을 고치지 않았다).
 *   고쳐짐: 그 밖의 답(문장을 고쳐 다시 말했다).
 * 출력에는 대화 ID·단계 번호·종류만 담는다. 대화 내용은 담지 않으므로 다른 PC 결과와 합쳐도 된다.
 *
 * 사용법:
 *   node scripts/selfcheck_stats.mjs [--since 2026-11-03] [--brain <dir>] [--out <file.json>]
 *     기본 출력: ~/.lazyargon/selfcheck-stats-<호스트>.json
 *   node scripts/selfcheck_stats.mjs --merge a.json b.json ...   (여러 PC 결과를 합쳐 표로 보여 준다)
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const BLOCK_RE = /Stop hook blocked termination:\s*\[SELF-CHECK/;
const KIND_LINE_RE = /^\s*\d+\.\s*\[([^\]]+)\]/gm;
const PASS_LINE_RE = /^\s*점검\s*:\s*근거\s*있음/;
const CORRECTION_RE = /정정|수정합니다|다시\s*확인|아닙니다|오류였/;

function arg(name) {
	const i = process.argv.indexOf(name);
	return i >= 0 ? process.argv[i + 1] : undefined;
}

export function outcomeOf(answer) {
	const lines = String(answer || '').split('\n').map((l) => l.trim()).filter(Boolean);
	if (!lines.length) return 'unknown';
	if (lines.every((l) => PASS_LINE_RE.test(l))) return 'passed';
	if (PASS_LINE_RE.test(lines[0]) && !lines.slice(1).some((l) => CORRECTION_RE.test(l))) return 'passed';
	return 'corrected';
}

function collect(brainDir, since = '') {
	const reasks = [];
	const convs = fs.existsSync(brainDir) ? fs.readdirSync(brainDir) : [];
	for (const conv of convs) {
		const f = path.join(brainDir, conv, '.system_generated', 'logs', 'transcript_full.jsonl');
		if (!fs.existsSync(f)) continue;
		const steps = fs.readFileSync(f, 'utf8').split('\n').filter(Boolean).map((l) => {
			try {
				return JSON.parse(l);
			} catch {
				return null;
			}
		}).filter(Boolean);
		steps.forEach((s, i) => {
			const text = String(s.content || '');
			if (s.type !== 'SYSTEM_MESSAGE' || !BLOCK_RE.test(text)) return;
			const ts = String(s.created_at || '');
			if (since && ts && ts < since) return;
			const kinds = [...new Set([...text.matchAll(KIND_LINE_RE)].map((m) => m[1].split('(')[0].trim()))];
			const next = steps.slice(i + 1).find((n) => n.type === 'PLANNER_RESPONSE' && typeof n.content === 'string' && n.content.trim());
			reasks.push({ conv, step: s.step_index ?? i, ts, kinds, outcome: next ? outcomeOf(next.content) : 'unknown' });
		});
	}
	return reasks;
}

export function byKind(reasks) {
	const table = {};
	for (const r of reasks) {
		for (const k of r.kinds.length ? r.kinds : ['(종류 없음)']) {
			const row = (table[k] ??= { total: 0, corrected: 0, passed: 0, unknown: 0 });
			row.total += 1;
			row[r.outcome] += 1;
		}
	}
	return table;
}

function printTable(table, label) {
	console.log(`# 되묻기 종류별 결과 (${label})`);
	console.log('종류 | 되묻기 | 고쳐짐 | 그대로 | 알 수 없음 | 고쳐진 비율');
	for (const [k, r] of Object.entries(table).sort((a, b) => b[1].total - a[1].total)) {
		const judged = r.corrected + r.passed;
		const rate = judged ? `${Math.round((r.corrected / judged) * 100)}%` : '-';
		console.log(`${k} | ${r.total} | ${r.corrected} | ${r.passed} | ${r.unknown} | ${rate}`);
	}
}

const USAGE = 'usage: node scripts/selfcheck_stats.mjs [--since YYYY-MM-DD] [--brain <dir>] [--out <file.json>] | --merge <a.json ...>\n';

function validateArgs(argv) {
	const mergeIdx = argv.indexOf('--merge');
	if (mergeIdx >= 0) {
		if (mergeIdx > 0 || argv.length <= mergeIdx + 1) {
			process.stderr.write(USAGE);
			process.exit(2);
		}
		return;
	}
	for (let i = 0; i < argv.length; i += 1) {
		if (argv[i] === '--since' || argv[i] === '--brain' || argv[i] === '--out') {
			if (i + 1 >= argv.length || argv[i + 1].startsWith('--')) {
				process.stderr.write(`missing value for ${argv[i]}\n${USAGE}`);
				process.exit(2);
			}
			i += 1;
			continue;
		}
		process.stderr.write(`unknown argument: ${argv[i]}\n${USAGE}`);
		process.exit(2);
	}
}

function main() {
	const argv = process.argv.slice(2);
	validateArgs(argv);
	if (argv.includes('--merge')) {
		const files = argv.slice(argv.indexOf('--merge') + 1);
		const all = [];
		const seen = new Set();
		for (const f of files) {
			for (const r of JSON.parse(fs.readFileSync(f, 'utf8')).reasks || []) {
				const key = `${r.conv}#${r.step}`;
				if (seen.has(key)) continue; // 같은 결과 파일을 두 번 넣어도 한 번만 센다
				seen.add(key);
				all.push(r);
			}
		}
		printTable(byKind(all), `${files.length}개 파일, 되묻기 ${all.length}건`);
		return;
	}
	const brain = arg('--brain') || path.join(os.homedir(), '.gemini', 'antigravity', 'brain');
	const since = arg('--since') || '';
	const host = os.hostname();
	const reasks = collect(brain, since);
	const out = arg('--out') || path.join(os.homedir(), '.lazyargon', `selfcheck-stats-${host}.json`);
	fs.mkdirSync(path.dirname(out), { recursive: true });
	fs.writeFileSync(out, `${JSON.stringify({ host, generated_at: new Date().toISOString(), since: since || null, reasks, by_kind: byKind(reasks) }, null, 1)}\n`);
	printTable(byKind(reasks), `${host}, 되묻기 ${reasks.length}건`);
	console.log(`저장: ${out}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	main();
}
