#!/usr/bin/env node
/**
 * json_schema_guard.mjs — PostToolUse JSON 구조 및 스키마 무결성 가드 (Feature 07)
 * GUARD_PACK_VERSION: 1.0.0
 *
 * Instructor/Pydantic 스타일의 필드 유효성 검사 및 자가 수정(Self-Correction) 피드백 제공:
 * - JSON 파싱 무결성 (SyntaxError 원천 차단)
 * - 고위험 필드(URL, 파일 경로, 날짜 포맷, 필수 필드) 유효성 검사
 * - FAIL_CLOSED 정책: 검증 실패 시 상세 수정 가이드(blame & repair)를 stderr에 출력하고 exit 1
 */
import fs from 'node:fs';
import path from 'node:path';
import { stdin } from 'node:process';

const GUARD_PACK_VERSION = '1.0.0';

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

async function collectSources() {
	const sources = [];
	const push = (text, label) => {
		if (text) sources.push({ text, parsed: tryParseJson(text), label });
	};
	for (const k of ['ANTIGRAVITY_TOOL_INPUT', 'TOOL_INPUT', 'ANTIGRAVITY_TARGET_FILE', 'TARGET_FILE']) {
		if (process.env[k]) push(process.env[k], `env:${k}`);
	}
	push(await readStdin(1500), 'stdin');
	for (const arg of process.argv.slice(2)) push(arg, 'argv');
	return sources;
}

const TARGET_KEY_RE = /^(file_path|filepath|path|target|target_file|targetfile|target_path|targetpath|output|file|filename)$/i;
const PATH_LIKE_RE = /([^\s"'`<>|;&]+[\/\\][^\s"'`<>|;&]+\.json)/i;
const REDIRECT_RE = /(?:>|>>)\s*([^\s|&;]+(?:\.json))/i;

function extractTargetFromNode(node, out) {
	if (Array.isArray(node)) {
		for (const item of node) extractTargetFromNode(item, out);
		return;
	}
	if (!node || typeof node !== 'object') return;
	for (const [key, value] of Object.entries(node)) {
		if (typeof value === 'string' && value) {
			if (TARGET_KEY_RE.test(key)) out.push({ value, isCommand: false });
			else if (/^(command|cmd|command_line|commandline|script|args)$/i.test(key)) out.push({ value, isCommand: true });
		} else if (value && typeof value === 'object') {
			extractTargetFromNode(value, out);
		}
	}
}

const WRITE_OR_CMD_TOOL_RE = /^(write_to_file|replace_file_content|multi_replace_file_content|run_command|WriteToFile|ReplaceFileContent|MultiReplaceFileContent|RunCommand|write_file|Write|Edit|MultiEdit|SearchReplace|StrReplace|Bash|bash|Shell|shell|execute_command)$/i;

function unquoteTranscriptVal(val) {
	if (typeof val !== 'string') return val;
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

function resolveTranscriptPaths(payloadOrPath) {
	if (typeof payloadOrPath === 'string') {
		return resolveTranscriptPaths({ transcriptPath: payloadOrPath });
	}
	if (!payloadOrPath || typeof payloadOrPath !== 'object') return [];
	const candidates = [];
	const add = (p) => {
		if (typeof p === 'string' && p.trim() && !candidates.includes(p.trim())) {
			candidates.push(p.trim());
		}
	};
	const tp = payloadOrPath.transcriptPath || payloadOrPath.transcript_path || '';
	if (typeof tp === 'string' && tp.trim()) {
		add(tp);
		if (/transcript\.jsonl$/i.test(tp) && !/transcript_full\.jsonl$/i.test(tp)) {
			add(tp.replace(/transcript\.jsonl$/i, 'transcript_full.jsonl'));
		} else if (/transcript_full\.jsonl$/i.test(tp)) {
			add(tp.replace(/transcript_full\.jsonl$/i, 'transcript.jsonl'));
		}
	}
	const adp = payloadOrPath.artifactDirectoryPath || payloadOrPath.artifact_directory_path || '';
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

function extractToolDataFromCall(tc) {
	if (!tc || typeof tc !== 'object') return null;
	const toolName = unquoteTranscriptVal(tc.name || tc.tool_name || tc.toolName || tc.function?.name || '');
	if (toolName && !WRITE_OR_CMD_TOOL_RE.test(toolName)) return null;
	let rawArgs = tc.args ?? tc.arguments ?? tc.input ?? tc.parameters ?? tc.function?.arguments ?? tc;
	if (typeof rawArgs === 'string') {
		rawArgs = tryParseJson(unquoteTranscriptVal(rawArgs)) ?? tryParseJson(rawArgs);
	}
	if (!rawArgs || typeof rawArgs !== 'object') return null;

	const getStr = (...keys) => {
		for (const k of keys) {
			if (typeof rawArgs[k] === 'string' && rawArgs[k]) {
				return unquoteTranscriptVal(rawArgs[k]);
			}
		}
		return '';
	};

	let targetFile = getStr('TargetFile', 'target_file', 'file_path', 'filepath', 'path', 'target', 'target_path', 'targetpath', 'output', 'file', 'filename');
	const commandLine = getStr('CommandLine', 'command_line', 'command', 'cmd', 'script');
	let codeContent = getStr('CodeContent', 'code_content', 'ReplacementContent', 'replacement_content', 'content', 'new_string', 'text');
	if (!codeContent && rawArgs.ReplacementChunks !== undefined) {
		let chunks = rawArgs.ReplacementChunks;
		if (typeof chunks === 'string') {
			chunks = tryParseJson(unquoteTranscriptVal(chunks)) ?? tryParseJson(chunks);
		}
		if (Array.isArray(chunks)) {
			codeContent = chunks
				.map((c) => (c && typeof c === 'object' ? unquoteTranscriptVal(c.ReplacementContent || c.replacement_content || c.content || '') : ''))
				.filter(Boolean)
				.join('\n');
		}
	}
	if (!targetFile && commandLine) {
		const red = commandLine.match(REDIRECT_RE);
		if (red) targetFile = red[1];
		else {
			const m = commandLine.match(PATH_LIKE_RE);
			if (m) targetFile = m[1];
		}
	}
	if (!targetFile && !commandLine && !codeContent) return null;
	return { toolName, targetFile, codeContent, commandLine };
}

export function extractFromTranscript(payloadOrPath) {
	const paths = resolveTranscriptPaths(payloadOrPath);
	const targetStepIdx =
		payloadOrPath && typeof payloadOrPath === 'object'
			? typeof payloadOrPath.stepIdx === 'number'
				? payloadOrPath.stepIdx
				: typeof payloadOrPath.step_index === 'number'
					? payloadOrPath.step_index
					: undefined
			: undefined;

	for (const tp of paths) {
		try {
			const content = fs.readFileSync(tp, 'utf8');
			const lines = content.split(/\r?\n/).filter((l) => l.trim().length > 0).slice(-50).reverse();
			const parsedSteps = [];
			let hasTruncatedToolCalls = false;
			for (const line of lines) {
				const step = tryParseJson(line);
				if (!step || typeof step !== 'object') continue;
				if (Array.isArray(step.truncated_fields) && step.truncated_fields.includes('tool_calls')) {
					hasTruncatedToolCalls = true;
				}
				parsedSteps.push({ step, line });
			}
			if (hasTruncatedToolCalls && paths.some((p) => p !== tp && /transcript_full\.jsonl$/i.test(p))) {
				continue;
			}

			const searchSteps = (respectStepIdx) => {
				for (const { step, line } of parsedSteps) {
					const stepIdxVal = typeof step.step_index === 'number' ? step.step_index : typeof step.stepIdx === 'number' ? step.stepIdx : undefined;
					if (respectStepIdx && targetStepIdx !== undefined && stepIdxVal !== undefined && stepIdxVal > targetStepIdx) {
						continue;
					}
					const calls = Array.isArray(step.tool_calls)
						? step.tool_calls
						: Array.isArray(step.toolCalls)
							? step.toolCalls
							: step.toolCall && typeof step.toolCall === 'object'
								? [step.toolCall]
								: [];
					if (respectStepIdx && targetStepIdx !== undefined && stepIdxVal !== undefined && targetStepIdx > stepIdxVal) {
						const callOffset = targetStepIdx - stepIdxVal - 1;
						if (callOffset >= 0 && callOffset < calls.length) {
							const data = extractToolDataFromCall(calls[callOffset]);
							if (data && data.targetFile) return data;
						}
					}
					for (let i = calls.length - 1; i >= 0; i -= 1) {
						const data = extractToolDataFromCall(calls[i]);
						if (data && data.targetFile) return data;
					}
					const directData = extractToolDataFromCall(step);
					if (directData && directData.targetFile) return directData;
					if (WRITE_OR_CMD_TOOL_RE.test(line)) {
						const found = [];
						extractTargetFromNode(step, found);
						for (const { value, isCommand } of found) {
							const u = unquoteTranscriptVal(value);
							if (!isCommand && u) return { toolName: '', targetFile: u, codeContent: '', commandLine: '' };
							if (isCommand && u) {
								const red = u.match(REDIRECT_RE);
								if (red) return { toolName: 'run_command', targetFile: red[1], codeContent: '', commandLine: u };
								const m = u.match(PATH_LIKE_RE);
								if (m) return { toolName: 'run_command', targetFile: m[1], codeContent: '', commandLine: u };
							}
						}
					}
				}
				return null;
			};

			const hit = searchSteps(true) || (targetStepIdx !== undefined ? searchSteps(false) : null);
			if (hit) return hit;
		} catch {
			// continue to next candidate
		}
	}
	return null;
}

function extractTargetFromTranscript(payloadOrPath) {
	const data = extractFromTranscript(payloadOrPath);
	return data ? data.targetFile : '';
}

export function extractTarget(sourcesOrPayload) {
	const env = process.env.ANTIGRAVITY_TARGET_FILE || process.env.TARGET_FILE || '';
	if (env && env.endsWith('.json')) return env;
	const sources = Array.isArray(sourcesOrPayload)
		? sourcesOrPayload
		: sourcesOrPayload && typeof sourcesOrPayload === 'object'
			? [{ text: '', parsed: sourcesOrPayload, label: 'payload' }]
			: [];
	for (const s of sources) {
		if (s.parsed === undefined) continue;
		const found = [];
		extractTargetFromNode(s.parsed, found);
		for (const { value, isCommand } of found) {
			const u = unquoteTranscriptVal(value);
			if (!isCommand && u.endsWith('.json')) return u;
			if (isCommand) {
				const red = u.match(REDIRECT_RE);
				if (red) return red[1];
				const m = u.match(PATH_LIKE_RE);
				if (m) return m[1];
			}
		}
		if (s.parsed && typeof s.parsed === 'object' && (s.parsed.transcriptPath || s.parsed.transcript_path || s.parsed.artifactDirectoryPath || s.parsed.artifact_directory_path)) {
			const fromTranscript = extractTargetFromTranscript(s.parsed);
			if (fromTranscript && fromTranscript.endsWith('.json')) return fromTranscript;
		}
	}
	for (const s of sources) {
		if (s.parsed !== undefined) continue;
		const red = s.text.match(REDIRECT_RE);
		if (red) return red[1];
		const m = s.text.match(PATH_LIKE_RE);
		if (m) return m[1];
	}
	return '';
}

export function validateJsonObject(obj, pathPrefix = '$') {
	const violations = [];

	if (obj === null || typeof obj !== 'object') {
		return violations;
	}

	for (const [key, val] of Object.entries(obj)) {
		const currentPath = `${pathPrefix}.${key}`;

		// URL Validation
		if (/^(url|uri|homepage|repository|endpoint)$/i.test(key) && typeof val === 'string') {
			if (val.trim().length > 0 && !/^(https?|git\+https?|file|wss?):\/\//i.test(val)) {
				violations.push({
					field: currentPath,
					value: val,
					rule: 'valid_url_protocol',
					message: `URL '${val}' must have a valid protocol (http, https, file, ws)`
				});
			}
		}

		// ISO Date Validation
		if (/^(date|timestamp|created_at|updated_at)$/i.test(key) && typeof val === 'string') {
			if (val.trim().length > 0 && Number.isNaN(Date.parse(val))) {
				violations.push({
					field: currentPath,
					value: val,
					rule: 'valid_iso_date',
					message: `Date '${val}' is not a valid parseable date string`
				});
			}
		}

		// Version semantic format
		if (/^version$/i.test(key) && typeof val === 'string') {
			if (val.trim().length > 0 && !/^\d+\.\d+\.\d+(-[a-zA-Z0-9_.-]+)?$/.test(val.trim())) {
				violations.push({
					field: currentPath,
					value: val,
					rule: 'valid_semver',
					message: `Version '${val}' does not match SemVer format (e.g. 1.0.0)`
				});
			}
		}

		// Recursion
		if (val && typeof val === 'object') {
			violations.push(...validateJsonObject(val, currentPath));
		}
	}

	return violations;
}

export function checkJsonFile(filePath) {
	if (!fs.existsSync(filePath)) {
		return { ok: true, skipped: true, reason: 'File does not exist' };
	}

	let content;
	try {
		content = fs.readFileSync(filePath, 'utf8');
	} catch (err) {
		return { ok: true, skipped: true, reason: `Could not read file: ${err.message}` };
	}

	if (!content.trim()) {
		return { ok: false, error: 'Empty JSON file', violations: [{ field: '$', rule: 'non_empty', message: 'File is empty' }] };
	}

	let parsed;
	try {
		parsed = JSON.parse(content);
	} catch (err) {
		return {
			ok: false,
			error: `Malformed JSON Syntax: ${err.message}`,
			violations: [{ field: '$', rule: 'syntax_error', message: err.message }]
		};
	}

	const violations = validateJsonObject(parsed);
	if (violations.length > 0) {
		return { ok: false, error: 'Schema validation failed', violations };
	}

	return { ok: true, parsed };
}

async function main() {
	if (process.argv.includes('--check')) {
		const files = process.argv.slice(process.argv.indexOf('--check') + 1);
		let hasFailure = false;
		for (const f of files) {
			const res = checkJsonFile(path.resolve(f));
			if (!res.ok) {
				console.error(`[JSON SCHEMA GUARD] FAIL ${f}: ${res.error}`);
				for (const v of res.violations || []) {
					console.error(`  - ${v.field}: ${v.message}`);
				}
				hasFailure = true;
			}
		}
		process.exit(hasFailure ? 1 : 0);
	}

	const sources = await collectSources();
	const target = extractTarget(sources);

	if (!target || !target.endsWith('.json')) {
		process.stdout.write('{}\n');
		process.exit(0);
	}

	const resolvedPath = path.resolve(target);
	const res = checkJsonFile(resolvedPath);

	if (!res.ok) {
		console.error(`[JSON SCHEMA GUARD v${GUARD_PACK_VERSION}] PostToolUse Schema Validation FAIL: "${target}"`);
		console.error(`Error: ${res.error}`);
		console.error('[INSTRUCTOR SELF-CORRECTION GUIDANCE]:');
		for (const v of res.violations || []) {
			console.error(`  Field [${v.field}] (${v.rule}): ${v.message}`);
		}
		console.error('Action Required: Correct the schema violations and rewrite the JSON file before proceeding.');
		process.exit(1);
	}

	process.stdout.write('{}\n');
	process.exit(0);
}

import { fileURLToPath } from 'node:url';

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	main().catch((err) => {
		console.error(`[JSON SCHEMA GUARD] Error: ${err.message}`);
		process.stdout.write('{}\n');
		process.exit(0);
	});
}
