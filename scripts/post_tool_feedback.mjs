#!/usr/bin/env node
/**
 * post_tool_feedback.mjs — relay PostToolUse guard failures to the model.
 * GUARD_PACK canonical: lazyargon-workspace/scripts (sync to lazyargon with scripts/sync_guard_pack.sh).
 *
 * Antigravity's PostToolUse contract only accepts `{}`: a guard that exits 1 there is never shown
 * to the model (verified live 2026-10-31: unclosed code fence written, no warning reached the model).
 *   wrap <cmd> [args...]  PostToolUse: run the guard with the hook stdin; on a non-zero exit queue its
 *                         message under the conversation id (also a passing guard's "<GUARD> WARN"
 *                         stderr, as a warning); always print {} and exit 0.
 *   batch <g1.mjs> [...]  PostToolUse: read stdin once, skip guards whose target extension does not match
 *                         an inline targetFile, and run matching guards sequentially in one dispatcher.
 *   inject [--if-no-lazyargon]  PreInvocation: consume this conversation's queue and inject it as an
 *                         ephemeral message before the next model call.
 * Queue dir: $LAZYARGON_FEEDBACK_DIR or ~/.lazyargon/feedback/<conversationId>.jsonl
 */
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { stdin } from 'node:process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAX_MESSAGE_CHARS = 4000;
const PASSING_WARN_RE = /\[[A-Z ]*GUARD\] WARN/;
const TARGET_KEY_RE = /^(file_path|filepath|path|target|target_file|targetfile|target_path|targetpath|output|file|filename)$/i;
const INLINE_REDIRECT_RE = /(?:>|>>)\s*([^\s|&;"'`]+\.[a-z0-9]{1,10})\b/i;

// Sibling lazyargon installed AND not disabled in Antigravity config.json (unreadable config = installed only).
// Inlined, not imported: this file is GUARD_PACK and is copied verbatim into lazyargon/scripts.
function lazyargonActive(pluginRoot, marker) {
	const pluginsDir = path.resolve(pluginRoot, '..');
	if (!fs.existsSync(path.join(pluginsDir, 'lazyargon', marker))) return false;
	const configPath = process.env.LAZYARGON_GEMINI_CONFIG || path.join(pluginsDir, '..', 'config.json');
	try {
		return JSON.parse(fs.readFileSync(configPath, 'utf8'))?.plugins?.lazyargon?.enabled !== false;
	} catch {
		return true;
	}
}

const feedbackDir = () => process.env.LAZYARGON_FEEDBACK_DIR || path.join(os.homedir(), '.lazyargon', 'feedback');
const queuePath = (id) => path.join(feedbackDir(), `${id}.jsonl`);

function print(obj) {
	process.stdout.write(`${JSON.stringify(obj)}\n`);
	process.exit(0);
}

function readStdin(limitMs = 1500) {
	return new Promise((resolve) => {
		if (stdin.isTTY) return resolve('');
		const chunks = [];
		let settled = false;
		const finish = (value) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			try { stdin.pause(); } catch {}
			stdin.removeAllListeners();
			resolve(value);
		};
		const timer = setTimeout(() => finish(Buffer.concat(chunks).toString('utf8')), limitMs);
		if (typeof timer.unref === 'function') timer.unref();
		stdin.on('data', (chunk) => {
			chunks.push(chunk);
			const acc = Buffer.concat(chunks).toString('utf8').trim();
			if ((acc.startsWith('{') && acc.endsWith('}')) || (acc.startsWith('[') && acc.endsWith(']'))) {
				try { JSON.parse(acc); finish(acc); } catch {}
			}
		});
		stdin.on('end', () => finish(Buffer.concat(chunks).toString('utf8')));
		stdin.on('error', () => finish(''));
	});
}

function conversationIdOf(raw) {
	try {
		const id = JSON.parse(raw)?.conversationId;
		return typeof id === 'string' && /^[\w-]+$/.test(id) ? id : '';
	} catch {
		return '';
	}
}

function unquoteVal(val) {
	if (typeof val !== 'string') return '';
	const t = val.trim();
	if (t.length >= 2 && t.startsWith('"') && t.endsWith('"')) {
		try {
			const parsed = JSON.parse(t);
			if (typeof parsed === 'string') return parsed;
		} catch {
			return t.slice(1, -1);
		}
	}
	return val;
}

function collectInlineTargets(node, out) {
	if (Array.isArray(node)) {
		for (const item of node) collectInlineTargets(item, out);
		return;
	}
	if (!node || typeof node !== 'object') return;
	for (const [key, value] of Object.entries(node)) {
		if (typeof value === 'string' && value) {
			if (key === 'Target' && ('Path' in node || 'Replacement' in node)) continue;
			if (TARGET_KEY_RE.test(key)) out.push({ value: unquoteVal(value), isCmd: false });
			else if (/^(command|cmd|command_line|commandline|script)$/i.test(key)) out.push({ value: unquoteVal(value), isCmd: true });
		} else if (value && typeof value === 'object') {
			collectInlineTargets(value, out);
		}
	}
}

function extractInlineTarget(raw) {
	const envTarget = process.env.ANTIGRAVITY_TARGET_FILE || process.env.TARGET_FILE || '';
	if (envTarget) return envTarget;
	for (const src of [process.env.ANTIGRAVITY_TOOL_INPUT, process.env.TOOL_INPUT, raw]) {
		if (!src) continue;
		try {
			const parsed = JSON.parse(src);
			const found = [];
			collectInlineTargets(parsed, found);
			for (const { value, isCmd } of found) {
				if (!isCmd && value) return value;
				if (isCmd && value) {
					const m = value.match(INLINE_REDIRECT_RE);
					if (m) return m[1];
				}
			}
		} catch {}
	}
	return '';
}

function shouldSkipGuard(guardPath, inlineTarget) {
	if (!inlineTarget || !/\.[a-z0-9]{1,10}$/i.test(inlineTarget)) return false;
	const base = path.basename(guardPath);
	if (base === 'markdown_structure_guard.mjs') return !/\.md$/i.test(inlineTarget);
	if (base === 'json_schema_guard.mjs') return !/\.json$/i.test(inlineTarget);
	if (base === 'hallucination_guard.mjs' || base === 'legal_factuality_guard.mjs' || base === 'slop_guard.mjs') {
		return !/\.(?:md|html|txt)$/i.test(inlineTarget);
	}
	return false;
}

function queueResult(res, guard, raw) {
	const warnOnly = res.status === 0 && PASSING_WARN_RE.test(res.stderr || '');
	if (res.status === 0 && !warnOnly) return;
	process.stderr.write(res.stderr || '');
	const message =
		[res.stderr, warnOnly ? '' : res.stdout]
			.map((s) => (s || '').trim())
			.filter((s) => s && s !== '{}')
			.join('\n') || `${guard} exited ${res.status ?? res.signal ?? res.error?.message}`;
	const id = conversationIdOf(raw);
	if (!id) {
		process.stderr.write('post_tool_feedback: no conversationId in payload; guard failure not queued\n');
		return;
	}
	try {
		fs.mkdirSync(feedbackDir(), { recursive: true });
		const entry = { ts: new Date().toISOString(), guard, kind: warnOnly ? 'warn' : 'fail', message: message.slice(0, MAX_MESSAGE_CHARS) };
		fs.appendFileSync(queuePath(id), `${JSON.stringify(entry)}\n`);
	} catch (err) {
		process.stderr.write(`post_tool_feedback: queue write failed: ${err.message}\n`);
	}
}

async function wrap(argv) {
	const raw = await readStdin(1500);
	const [cmd, ...args] = argv;
	if (!cmd) print({});
	const res = spawnSync(cmd, args, { input: raw, encoding: 'utf8' });
	const guard = path.basename([...args].reverse().find((a) => /\.(mjs|js|py)$/.test(a)) || cmd);
	queueResult(res, guard, raw);
	print({});
}

async function batch(argv) {
	const raw = await readStdin(1500);
	const guards = argv.filter((a) => a && a !== 'node');
	if (!guards.length) print({});
	const inlineTarget = extractInlineTarget(raw);
	for (const guardPath of guards) {
		if (shouldSkipGuard(guardPath, inlineTarget)) continue;
		const res = spawnSync(process.execPath, [guardPath], { input: raw, encoding: 'utf8' });
		queueResult(res, path.basename(guardPath), raw);
	}
	print({});
}

async function inject(argv = []) {
	const raw = await readStdin(1500);
	if (
		argv.includes('--if-no-lazyargon') &&
		path.basename(path.resolve(HERE, '..')) !== 'lazyargon' &&
		lazyargonActive(path.resolve(HERE, '..'), 'hooks.json')
	) {
		print({});
	}
	const id = conversationIdOf(raw);
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
	const fails = entries.filter((e) => e.kind !== 'warn');
	const warns = entries.filter((e) => e.kind === 'warn');
	const text = [
		...(fails.length
			? [
					'[LAZYARGON POST-TOOL GUARD] 직전 도구 호출 뒤 가드가 실패를 보고했다. 해당 파일을 다시 열어 아래 문제를 고친 뒤 계속하라.',
					...fails.map((e) => `- ${e.guard}: ${e.message}`),
				]
			: []),
		...(warns.length
			? [
					'[LAZYARGON POST-TOOL GUARD] 가드는 통과했지만 경고를 남겼다. 각 항목이 본문에서 유보(미확인)로 분명히 밝혀져 있는지 확인하고, 사실처럼 읽히면 고쳐라.',
					...warns.map((e) => `- ${e.guard}: ${e.message}`),
				]
			: []),
	].join('\n');
	print({ injectSteps: [{ ephemeralMessage: text }] });
}

const [mode, ...rest] = process.argv.slice(2);
if (mode === 'wrap') await wrap(rest);
else if (mode === 'batch') await batch(rest);
else if (mode === 'inject') await inject(rest);
else {
	process.stderr.write('usage: post_tool_feedback.mjs wrap <cmd> [args...] | batch <guard.mjs...> | inject [--if-no-lazyargon]\n');
	process.exit(2);
}
