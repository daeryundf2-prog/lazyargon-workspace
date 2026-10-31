#!/usr/bin/env node
/**
 * post_tool_feedback.mjs — relay PostToolUse guard failures to the model.
 * GUARD_PACK canonical: lazyargon-workspace/scripts (sync to lazyargon with scripts/sync_guard_pack.sh).
 *
 * Antigravity's PostToolUse contract only accepts `{}`: a guard that exits 1 there is never shown
 * to the model (verified live 2026-10-31: unclosed code fence written, no warning reached the model).
 *   wrap <cmd> [args...]  PostToolUse: run the guard with the hook stdin; on a non-zero exit queue its
 *                         message under the conversation id; always print {} and exit 0.
 *   inject                PreInvocation: consume this conversation's queue and inject it as an
 *                         ephemeral message before the next model call.
 * Queue dir: $LAZYARGON_FEEDBACK_DIR or ~/.lazyargon/feedback/<conversationId>.jsonl
 */
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const MAX_MESSAGE_CHARS = 4000;

function feedbackDir() {
	return process.env.LAZYARGON_FEEDBACK_DIR || path.join(os.homedir(), '.lazyargon', 'feedback');
}

function readStdin() {
	try {
		return fs.readFileSync(0, 'utf8');
	} catch {
		return '';
	}
}

function conversationIdOf(raw) {
	try {
		const id = JSON.parse(raw)?.conversationId;
		return typeof id === 'string' && /^[\w-]+$/.test(id) ? id : '';
	} catch {
		return '';
	}
}

function queuePath(id) {
	return path.join(feedbackDir(), `${id}.jsonl`);
}

function print(obj) {
	process.stdout.write(`${JSON.stringify(obj)}\n`);
	process.exit(0);
}

function wrap(argv) {
	const raw = readStdin();
	const [cmd, ...args] = argv;
	if (!cmd) print({});
	const res = spawnSync(cmd, args, { input: raw, encoding: 'utf8' });
	if (res.status === 0) print({});
	process.stderr.write(res.stderr || '');
	const guard = path.basename([...args].reverse().find((a) => /\.(mjs|js|py)$/.test(a)) || cmd);
	const message =
		[res.stderr, res.stdout]
			.map((s) => (s || '').trim())
			.filter((s) => s && s !== '{}')
			.join('\n') || `${guard} exited ${res.status ?? res.signal ?? res.error?.message}`;
	const id = conversationIdOf(raw);
	if (!id) {
		process.stderr.write('post_tool_feedback: no conversationId in payload; guard failure not queued\n');
		print({});
	}
	try {
		fs.mkdirSync(feedbackDir(), { recursive: true });
		const entry = { ts: new Date().toISOString(), guard, message: message.slice(0, MAX_MESSAGE_CHARS) };
		fs.appendFileSync(queuePath(id), `${JSON.stringify(entry)}\n`);
	} catch (err) {
		process.stderr.write(`post_tool_feedback: queue write failed: ${err.message}\n`);
	}
	print({});
}

function inject() {
	const id = conversationIdOf(readStdin());
	if (!id) print({});
	const queue = queuePath(id);
	const taken = `${queue}.${process.pid}.taking`;
	try {
		fs.renameSync(queue, taken); // atomic claim: a concurrent inject sees ENOENT
	} catch (err) {
		if (err.code !== 'ENOENT') process.stderr.write(`post_tool_feedback: queue claim failed: ${err.message}\n`);
		print({});
	}
	const entries = fs
		.readFileSync(taken, 'utf8')
		.split('\n')
		.filter(Boolean)
		.map((line) => {
			try {
				return JSON.parse(line);
			} catch {
				return { guard: 'unknown', message: line };
			}
		});
	fs.rmSync(taken, { force: true });
	if (!entries.length) print({});
	const text = [
		'[LAZYARGON POST-TOOL GUARD] 직전 도구 호출 뒤 가드가 실패를 보고했다. 해당 파일을 다시 열어 아래 문제를 고친 뒤 계속하라.',
		...entries.map((e) => `- ${e.guard}: ${e.message}`),
	].join('\n');
	print({ injectSteps: [{ ephemeralMessage: text }] });
}

const [mode, ...rest] = process.argv.slice(2);
if (mode === 'wrap') wrap(rest);
else if (mode === 'inject') inject();
else {
	process.stderr.write('usage: post_tool_feedback.mjs wrap <cmd> [args...] | inject\n');
	process.exit(2);
}
