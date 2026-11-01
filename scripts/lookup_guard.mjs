#!/usr/bin/env node
/**
 * lookup_guard.mjs — PostToolUse: 조회(읽기·검색·목록·import 확인)가 실패했거나 0건이면 즉시 경고한다.
 * GUARD_PACK canonical: lazyargon-workspace/scripts.
 *
 * 실제 사례(2026-11-01): import 경로를 잘못 짚은 조회 실패를 "기능이 없다"로 보고했다.
 * 실패한 조회는 <workspace>/.lazyargon/lookups.jsonl 에 남고, stderr 의 "[LOOKUP GUARD] WARN" 을
 * post_tool_feedback.mjs wrap 이 다음 모델 호출 전에 주입한다. 항상 exit 0 · stdout {} (PostToolUse 계약).
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const LOOKUP_CMD_RE = /(^|[\s;&|(])(grep|rg|ag|find|fd|ls|cat|head|tail|stat|test\s+-[edf]|which|command\s+-v|type|mdfind|locate|sqlite3|pip3?\s+show|python3?\s+-c\s+["']?\s*import|curl|wget|git\s+(show|log|grep|ls-files)|dir|Test-Path|Get-ChildItem|Get-Item|Get-Content|Select-String|Get-Command|Resolve-Path|gci|gc|sls|where(?:\.exe)?|findstr)\b/i;
const LOOKUP_TOOL_RE = /^(view_file|view_file_outline|list_dir|grep_search|find_by_name|search_web|read_url_content|codebase_search|view_code_item)$/i;
const FAILED_RE = /No such file or directory|cannot (?:find|access|open)|not found|ModuleNotFoundError|No module named|ImportError|Permission denied|Operation not permitted|does not exist|could not be found|No results found|\b0 results\b|Found 0\b|no matches|exited with code [12]\b|exit (?:code|status) [12]\b|HTTP (?:403|404|410)|404 Not Found|ObjectNotFound|ItemNotFoundException|PathNotFound|CommandNotFoundException|경로를 찾을 수 없|찾을 수 없습니다|지정된 파일을 찾을 수 없|인식되지 않습니다/i;
// PowerShell Test-Path 는 없는 경로에 오류 대신 exit 0 + 'False' 한 줄을 낸다(Windows 실측 보고, 2026-11-02).
const TEST_PATH_FALSE_RE = /(?:^|\n)\s*False\s*(?:\r?\n|$)/;

function readStdin() {
	try {
		return fs.readFileSync(0, 'utf8');
	} catch {
		return '';
	}
}

function transcriptPath(p) {
	const cands = [];
	if (typeof p.transcriptPath === 'string') cands.push(p.transcriptPath.replace(/transcript\.jsonl$/i, 'transcript_full.jsonl'), p.transcriptPath);
	if (typeof p.artifactDirectoryPath === 'string') cands.push(path.join(p.artifactDirectoryPath, '.system_generated', 'logs', 'transcript_full.jsonl'));
	return cands.find((c) => c && fs.existsSync(c));
}

// PostToolUse 시점에는 방금 호출한 도구의 출력이 아직 transcript 에 없을 수 있다(실세션 2026-11-01).
// 그래서 '출력 단계 + 그 직전 PLANNER_RESPONSE 의 명령'을 짝지어, 아직 경고하지 않은 실패 출력을 그 명령 이름으로 보고한다.
function failedSteps(p) {
	const tp = transcriptPath(p);
	if (!tp) return [];
	const fd = fs.openSync(tp, 'r');
	try {
		const size = fs.fstatSync(fd).size;
		const len = Math.min(size, 512 * 1024);
		const buf = Buffer.alloc(len);
		fs.readSync(fd, buf, 0, len, size - len);
		const steps = buf.toString('utf8').split('\n').filter(Boolean).map((l) => {
			try {
				return JSON.parse(l);
			} catch {
				return null;
			}
		}).filter(Boolean);
		let start = 0;
		for (let i = steps.length - 1; i >= 0; i--) if (steps[i].type === 'USER_INPUT') { start = i; break; }
		const out = [];
		let lastCall = null;
		for (const s of steps.slice(start)) {
			if (s.type === 'PLANNER_RESPONSE' && Array.isArray(s.tool_calls) && s.tool_calls.length) lastCall = s.tool_calls[0];
			if (s.type !== 'GENERIC' || !lastCall) continue;
			const name = String(lastCall.name || '');
			const cmd = String(lastCall.args?.CommandLine || lastCall.args?.command || '');
			const isLookup = LOOKUP_TOOL_RE.test(name) || (/run_command|bash|shell/i.test(name) && LOOKUP_CMD_RE.test(cmd));
			const body = String(s.content || '');
			const m = isLookup && (body.match(FAILED_RE) || (/Test-Path/i.test(cmd) && TEST_PATH_FALSE_RE.test(body) ? ['Test-Path False'] : null));
			if (m) out.push({ step: Number(s.step_index), tool: name, what: (cmd || JSON.stringify(lastCall.args || {})).replace(/\s+/g, ' ').slice(0, 160), failure: m[0] });
		}
		return out;
	} finally {
		fs.closeSync(fd);
	}
}

function main() {
	let p = {};
	try {
		p = JSON.parse(readStdin() || '{}');
	} catch {
		p = {};
	}
	const ws = [p.cwd, Array.isArray(p.workspacePaths) ? p.workspacePaths[0] : null].find((c) => typeof c === 'string' && path.isAbsolute(c)) || os.homedir();
	const ledger = path.join(ws, '.lazyargon', 'lookups.jsonl');
	const conv = p.conversationId || null;
	let seen = new Set();
	try {
		seen = new Set(fs.readFileSync(ledger, 'utf8').split('\n').filter(Boolean).map((l) => {
			try {
				const e = JSON.parse(l);
				return `${e.conversationId}#${e.step}`;
			} catch {
				return '';
			}
		}));
	} catch {
		// 첫 기록
	}
	const fresh = failedSteps(p).filter((f) => !seen.has(`${conv}#${f.step}`));
	if (!fresh.length) return;
	try {
		fs.mkdirSync(path.dirname(ledger), { recursive: true });
		for (const f of fresh) fs.appendFileSync(ledger, `${JSON.stringify({ ts: new Date().toISOString(), conversationId: conv, ...f })}\n`);
	} catch {
		// 기록 실패는 경고 자체를 막지 않는다
	}
	const lines = fresh.map((f) => `- ${f.what} → ${f.failure}`).join('\n');
	process.stderr.write(`[LOOKUP GUARD] WARN — 실패하거나 0건이었던 조회:\n${lines}\n이 조회가 본 범위(그 경로·이름·검색어)에 대해서만 말할 수 있다. 예: '그 경로에 파일 없음'은 되지만 '기능이 없다'로 넓히지 말 것. 더 넓게 말하려면 다른 방법으로 확인하거나 '확인하지 못함'으로 적는다.\n`);
}

main();
process.stdout.write('{}\n');
