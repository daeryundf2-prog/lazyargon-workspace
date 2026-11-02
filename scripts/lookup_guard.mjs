#!/usr/bin/env node
/**
 * lookup_guard.mjs — PostToolUse: 조회(읽기·검색·목록·import 확인)가 실패했거나 0건이면 즉시 경고한다.
 * GUARD_PACK canonical: lazyargon-workspace/scripts.
 *
 * 실제 사례(2026-11-01): import 경로를 잘못 짚은 조회 실패를 "기능이 없다"로 보고했다.
 * 실패한 조회는 <workspace>/.lazyargon/lookups.jsonl 에 남고, stderr 의 "[LOOKUP GUARD] WARN" 을
 * post_tool_feedback.mjs wrap 이 다음 모델 호출 전에 주입한다. 항상 exit 0 · stdout {} (PostToolUse 계약).
 * Stop 에서는 stop_claim_guard.mjs 가 이 가드를 한 번 더 부른다: 도구 하나가 실패하고 바로 답하며 끝난 턴은
 * PostToolUse 시점에 그 출력이 아직 transcript 에 없어 기록이 빠졌다(Windows 실기 2026-11-03). 같은 step 은 한 번만 기록한다.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const LOOKUP_CMD_RE = /(^|[\s;&|(])(grep|rg|ag|find|fd|ls|cat|head|tail|stat|test\s+-[edf]|which|command\s+-v|type|mdfind|locate|sqlite3|pip3?\s+show|python3?\s+-c\s+["']?\s*import|curl|wget|git\s+(show|log|grep|ls-files)|dir|Test-Path|Get-ChildItem|Get-Item|Get-Content|Select-String|Get-Command|Resolve-Path|gci|gc|sls|where(?:\.exe)?|findstr)\b/i;
const LOOKUP_TOOL_RE = /^(read_file|ReadFile|Read|view_file|view_file_outline|list_dir|grep_search|find_by_name|search_web|read_url_content|codebase_search|view_code_item)$/i;
const FAILED_RE = /No such file or directory|cannot (?:find|access|open)|not found|ModuleNotFoundError|No module named|ImportError|Permission denied|Operation not permitted|does not exist|could not be found|No results found|\b0 results\b|Found 0\b|no matches|exited with code [12]\b|exit (?:code|status) [12]\b|HTTP (?:403|404|410)|404 Not Found|ObjectNotFound|ItemNotFoundException|PathNotFound|CommandNotFoundException|경로를 찾을 수 없|찾을 수 없습니다|지정된 파일을 찾을 수 없|인식되지 않습니다/i;
// PowerShell Test-Path 는 없는 경로에 오류 대신 exit 0 + 'False' 한 줄을 낸다(Windows 실측 보고, 2026-11-02).
const TEST_PATH_FALSE_RE = /(?:^|\n)\s*False\s*(?:\r?\n|$)/;
// 파일·문서 본문을 돌려주는 도구는 본문에 'not found' 같은 말이 있어도 성공이다. 실패는 단계 status=ERROR 나
// 'Encountered error in step execution' 으로만 남는다(실제 transcript 177개 전수 확인, 2026-11-02).
const CONTENT_TOOL_RE = /^(read_file|ReadFile|Read|view_file|view_file_outline|view_code_item|read_url_content)$/i;
const TOOL_ERROR_RE = /Encountered error in (?:step|tool) execution|^\s*Error:/;
// 파일 하나를 읽기만 하는 명령(Get-Content · cat 등)도 출력이 곧 파일 본문이다. 실패는 명령 자신의 오류 줄이나
// 0 아닌 종료 코드로만 본다. 실세션(2026-11-02): lookups.jsonl 을 열어 보기만 해도 그 안의 실패 문구가 다시 기록됐다.
const READ_CMD_RE = /^\s*(?:\[Console\]::OutputEncoding\s*=[^;\n]*[;\n]\s*)?(?:cat|head|tail|type|more|Get-Content|gc)\s[^;&|\n]*(?:\|\s*(?:Select-Object|select|head|tail|more)\b[^;&|\n]*)*$/i;
// python -c "import os ..." 같은 스크립트 실행은 종료 코드 1 이 대부분 문법·로직 오류다(실제 기록 336건 중 import 실패 5건).
// 스크립트는 종료 코드만으로 조회 실패로 보지 않고, 출력에 남은 실패 문구(No module named · No such file 등)로만 본다.
const SCRIPT_RUN_RE = /^\s*(?:\$env:[^;\n]+;\s*)*(?:python3?|py|node)(?:\.exe)?\s/i;
const EXIT_CODE_RE = /exited with code \d+|exit (?:code|status) \d+/gi;
const READ_FAIL_RE = /^(?:cat|head|tail|type|more|Get-Content|gc)\s*:.*|ItemNotFoundException|PathNotFound|ObjectNotFound|cannot find the (?:file|path) specified|지정된 (?:파일을|경로를) 찾을 수 없|exited with code [12]\b/im;

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
		// 한 응답에 도구를 여러 개 부르면 출력 단계도 그 순서대로 나온다. k 번째 출력은 k 번째 호출의 것이다
		// (이전에는 전부 첫 호출에 붙여 read_file 뒤 run_command 출력을 read_file 실패로 읽었다).
		// 호출보다 출력 단계가 많으면(실행 중 스냅샷 + 완료 출력) 남는 출력은 마지막 호출의 것이다(실제 기록 15건, 적대적 리뷰 2026-11-03).
		let pending = [];
		let lastCall = null;
		for (const s of steps.slice(start)) {
			if (s.type === 'PLANNER_RESPONSE' && Array.isArray(s.tool_calls) && s.tool_calls.length) pending = [...s.tool_calls];
			if (s.type !== 'GENERIC') continue;
			if (pending.length) lastCall = pending.shift();
			if (!lastCall) continue;
			const name = String(lastCall.name || '');
			const cmd = String(lastCall.args?.CommandLine || lastCall.args?.command || '');
			if (!(LOOKUP_TOOL_RE.test(name) || (/run_command|bash|shell/i.test(name) && LOOKUP_CMD_RE.test(cmd)))) continue;
			const body = String(s.content || '');
			const errText = `${s.error || ''}\n${body}`;
			let m;
			// 단계 status 가 있으면 그것만 믿는다: 본문 첫머리에 'Encountered error …' 를 담은 파일(대화 기록 등)을 열어도 성공이다.
			if (CONTENT_TOOL_RE.test(name)) m = (s.status ? s.status === 'ERROR' : TOOL_ERROR_RE.test(body.slice(0, 300))) ? errText.match(FAILED_RE) || ['tool error'] : null;
			else if (READ_CMD_RE.test(cmd)) m = body.match(READ_FAIL_RE);
			else if (SCRIPT_RUN_RE.test(cmd)) m = body.replace(EXIT_CODE_RE, '').match(FAILED_RE);
			else m = body.match(FAILED_RE) || (/Test-Path/i.test(cmd) && TEST_PATH_FALSE_RE.test(body) ? ['Test-Path False'] : null);
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
