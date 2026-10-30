#!/usr/bin/env node
/**
 * stop_claim_guard.mjs — Stop/SubagentStop 자기완료 선언 게이트
 * GUARD_PACK_VERSION: 1.0.0 (캐노니컬: lazyforensic/scripts — 수정 시 3레포 동기화)
 *
 * 임무: 모델의 최종 메시지가 "완료/전수/100%/무결점/모두 통과" 류의 완료 선언을 하면서
 * 반증 가능한 증거(실행 명령, 테스트 수, 산출물 경로, 커밋 SHA)를 제시하지 않으면
 * stop 을 block 해 증거 첨부를 요구한다. "검증 완료" 보고가 사실과 다르던 사례
 * (순환 감사 "100% PASS", 문서화만 된 --plot-fft, 라우팅 미등록)의 재발 방지.
 *
 * 페이로드 규약 (start-work-continuation codex-hook.js 와 동일):
 *   { hook_event_name: "Stop"|"SubagentStop", stop_hook_active: bool,
 *     last_assistant_message?: string, ... }
 * 차단 규약: stdout 에 {"decision":"block","reason":"..."} 출력 + exit 0.
 *
 * 정직한 동작 규약:
 * - stop_hook_active=true (이미 재개된 턴)면 개입하지 않는다 — 무한 루프 방지.
 * - 최종 메시지를 못 읽거나 파싱에 실패하면 개입하지 않는다 (exit 0).
 * - 증거가 있는 선언은 통과시킨다. 이 가드는 완료 자체가 아니라 무근거 완료 선언만 막는다.
 */
const GUARD_PACK_VERSION = '1.0.0';

const CLAIM_RE = new RegExp(
	[
		'완료', '완성', '다\\s*(했|끝냈)', '전부\\s*(했|완료|수정|추가)', '전수', '무결점', '완벽',
		'100\\s*%', '모두\\s*(통과|반영|수정|추가|검증)', '검증\\s*(완료|끝|했)', '통과\\s*(했습니다|했다)',
		'all\\s*(tests?\\s*)?(pass|passed|done|complete|finished)', 'fully\\s*(verified|tested|implemented|reviewed)',
		'100%\\s*(pass|coverage|complete)', 'complete\\s*and\\s*verified', 'zero\\s*(issues|failures)',
	].join('|'),
	'i',
);

const EVIDENCE_RE = new RegExp(
	[
		'```', // 명령 원문/출력 코드블록
		'\\b\\d+\\s*(passed|failed|skipped|pass|fail)', // 테스트 수치
		'테스트\\s*\\d+', '(pytest|unittest|vitest|npm\\s+test|npx\\s+vitest|go\\s+test)',
		'exit\\s*0', '--json', '--check',
		'(^|\\s)(python3?|node|git|uv|ffmpeg)\\s+\\S', // 실행한 명령줄
		'[\\w./가-힣-]+\\.(md|json|png|txt|html|csv|yml|yaml|ts|js|mjs|py|go|rs)\\b', // 산출물 경로
		'\\b(commit|커밋)\\b',
		'\\b[0-9a-f]{7,40}\\b', // 커밋 SHA
		'미확인|미측정|수정 전', // 정직 선언 어휘도 증거로 인정
		'\\[INSUFFICIENT_DATA', '\\[UNVERIFIED', // Feature 09: Strict Abstention 규약 준수 인정
	].join('|'),
	'i',
);

import fs from 'node:fs';
import path from 'node:path';

function readStdin(limitMs) {
	return new Promise((resolve) => {
		const { stdin } = process;
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

function resolveTranscriptPaths(payload) {
	if (!payload || typeof payload !== 'object') return [];
	const candidates = [];
	const add = (p) => {
		if (typeof p === 'string' && p.trim() && !candidates.includes(p.trim())) {
			candidates.push(p.trim());
		}
	};
	const tp = payload.transcriptPath || payload.transcript_path || '';
	if (typeof tp === 'string' && tp.trim()) {
		add(tp);
		if (/transcript\.jsonl$/i.test(tp) && !/transcript_full\.jsonl$/i.test(tp)) {
			add(tp.replace(/transcript\.jsonl$/i, 'transcript_full.jsonl'));
		} else if (/transcript_full\.jsonl$/i.test(tp)) {
			add(tp.replace(/transcript_full\.jsonl$/i, 'transcript.jsonl'));
		}
	}
	const adp = payload.artifactDirectoryPath || payload.artifact_directory_path || '';
	if (typeof adp === 'string' && adp.trim()) {
		add(path.join(adp, '.system_generated', 'logs', 'transcript_full.jsonl'));
		add(path.join(adp, '.system_generated', 'logs', 'transcript.jsonl'));
		add(path.join(adp, 'transcript_full.jsonl'));
		add(path.join(adp, 'transcript.jsonl'));
	}
	return candidates.filter((p) => {
		try {
			return fs.existsSync(p) && fs.statSync(p).isFile();
		} catch {
			return false;
		}
	});
}

function extractLastAssistantMessageFromTranscript(transcriptContent) {
	if (!transcriptContent) return '';
	const lines = transcriptContent.split(/\r?\n/).filter((l) => l.trim().length > 0).slice(-30).reverse();
	for (const line of lines) {
		try {
			const step = JSON.parse(line);
			if (!step || typeof step !== 'object') continue;
			if ((step.type === 'PLANNER_RESPONSE' || step.source === 'MODEL') && typeof step.content === 'string' && step.content.trim()) {
				return step.content;
			}
		} catch {
			// ignore malformed line
		}
	}
	return '';
}

async function main() {
	let payload;
	try {
		const raw = await readStdin(2000);
		payload = JSON.parse(raw);
	} catch {
		process.stdout.write('{}\n');
		process.exit(0); // 판단 불가 — 개입하지 않음
	}
	if (!payload || typeof payload !== 'object') {
		process.stdout.write('{}\n');
		process.exit(0);
	}
	if (payload.stop_hook_active === true) {
		process.stdout.write('{}\n');
		process.exit(0);
	}

	let transcriptContent = '';
	const transcriptPaths = resolveTranscriptPaths(payload);
	for (const tp of transcriptPaths) {
		try {
			transcriptContent = fs.readFileSync(tp, 'utf8');
			if (transcriptContent) break;
		} catch {
			// continue
		}
	}

	const message =
		typeof payload.last_assistant_message === 'string' && payload.last_assistant_message
			? payload.last_assistant_message
			: typeof payload.finalModelOutput === 'string' && payload.finalModelOutput
				? payload.finalModelOutput
				: extractLastAssistantMessageFromTranscript(transcriptContent);
	if (!message || !CLAIM_RE.test(message)) {
		process.stdout.write('{}\n');
		process.exit(0);
	}
	if (EVIDENCE_RE.test(message)) {
		// Feature 15: Fact-Retracing Gate (v2) + OMH 4-Stage DAG Completion Integrity
		// Verify high-risk claimed file paths against disk and transcript
		const baseCwd =
			payload.cwd ||
			(Array.isArray(payload.workspacePaths) && typeof payload.workspacePaths[0] === 'string' ? payload.workspacePaths[0] : '') ||
			process.cwd();

		const dagPath = path.join(baseCwd, '.lazyargon', 'ulw-dag.json');
		if (fs.existsSync(dagPath)) {
			try {
				const dag = JSON.parse(fs.readFileSync(dagPath, 'utf8'));
				const unverifiedNodes = (Array.isArray(dag.nodes) ? dag.nodes : []).filter((n) => n && n.state === 'reported_done');
				if (unverifiedNodes.length > 0) {
					const ids = unverifiedNodes.map((n) => n.id).join(', ');
					const reason = `[STOP CLAIM GUARD v${GUARD_PACK_VERSION}] 4단계 증거 등급 위반(reported_done != verified): .lazyargon/ulw-dag.json 노드 [${ids}]가 아직 'verified' 상태가 아닙니다. 검증 명령을 실행해 settle 한 뒤 완료를 선언하십시오.`;
					process.stdout.write(`${JSON.stringify({ decision: 'block', reason })}\n`);
					process.exit(0);
				}
			} catch {
				// ignore malformed dag file
			}
		}

		const claimedFileMatches = message.matchAll(/(?:(?:생성|작성|수정|추가|산출물)(?:은|는|이|가|로|으로)?|(?:created|written|generated|file|path))\s*[:=]?\s*[`"']?([a-zA-Z0-9_.:/\\가-힣-]+\.(?:ts|js|mjs|py|go|rs|json|md))[`"']?/gi);
		for (const match of claimedFileMatches) {
			const claimedPath = match[1];
			const fullPath = path.isAbsolute(claimedPath)
				? path.normalize(claimedPath)
				: path.resolve(baseCwd, claimedPath);
			const existsOnDisk = fs.existsSync(fullPath);
			const existsInTranscript = transcriptContent ? transcriptContent.includes(claimedPath) : false;

			if (!existsOnDisk && !existsInTranscript) {
				const reason = `[STOP CLAIM GUARD v${GUARD_PACK_VERSION}] 사실 역추적(Fact-Retracing) 실패: 메시지에 완료 산출물로 주장된 파일 "${claimedPath}"이 디스크 또는 트랜스크립트에 존재하지 않습니다. 허위 파일 경로 생성을 차단합니다.`;
				process.stdout.write(`${JSON.stringify({ decision: 'block', reason })}\n`);
				process.exit(0);
			}
		}

		process.stdout.write('{}\n'); // 증거 있는 선언 — 통과
		process.exit(0);
	}

	const reason = [
		`[STOP CLAIM GUARD v${GUARD_PACK_VERSION}] 완료 선언에 반증 가능한 증거가 없다.`,
		'메시지에 완료/전수/100% 류의 선언이 있지만 실행 명령·테스트 수·산출물 경로·커밋 SHA 중 어느 것도 제시하지 않았다.',
		'다음 중 해당하는 증거를 메시지에 덧붙여라:',
		'  1. 실제로 실행한 검증 명령 원문과 요약 출력 (예: pytest ... → "N passed")',
		'  2. 생성/수정한 산출물의 경로',
		'  3. 커밋/푸시했다면 커밋 SHA',
		'증거를 제시할 수 없는 항목은 "완료"라고 쓰지 말고 현재 상태를 사실대로 서술하라 (미확인/미측정 표기).',
		'이 선언이 단순 상태 보고라면 과장 표현을 빼고 사실만 쓰면 통과한다.',
	].join('\n');
	process.stdout.write(`${JSON.stringify({ decision: 'block', reason })}\n`);
	process.exit(0);
}

main().catch(() => {
	process.stdout.write('{}\n');
	process.exit(0); // 어떤 경우에도 세션을 가두지 않는다
});
