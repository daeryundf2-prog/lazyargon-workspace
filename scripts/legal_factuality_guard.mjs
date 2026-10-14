#!/usr/bin/env node
/**
 * legal_factuality_guard.mjs — PostToolUse Legal and Precedent Hallucination Guard
 * Inspects newly written legal drafts, ruling analyses, and legal texts for
 * fabricated statute article numbers (e.g. 민법 제1500조) and fake precedents.
 */
import fs from "fs";
import path from "path";
import { spawnSync } from "child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { stdin } from "node:process";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function readStdin(limitMs) {
	return new Promise((resolve) => {
		if (stdin.isTTY) {
			resolve("");
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
		const timer = setTimeout(() => finish(Buffer.concat(chunks).toString("utf8")), limitMs);
		stdin.on("data", (chunk) => chunks.push(chunk));
		stdin.on("end", () => finish(Buffer.concat(chunks).toString("utf8")));
		stdin.on("error", () => finish(""));
	});
}

function tryParseJson(text) {
	if (!text) return undefined;
	const t = text.trim();
	if (!t.startsWith("{") && !t.startsWith("[")) return undefined;
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
	for (const k of ["ANTIGRAVITY_TOOL_INPUT", "TOOL_INPUT", "ANTIGRAVITY_TARGET_FILE", "TARGET_FILE"]) {
		if (process.env[k]) push(process.env[k], `env:${k}`);
	}
	push(await readStdin(1500), "stdin");
	for (const arg of process.argv.slice(2)) push(arg, "argv");
	return sources;
}

const WRITE_OR_CMD_TOOL_RE = /^(write_to_file|replace_file_content|multi_replace_file_content|run_command|WriteToFile|ReplaceFileContent|MultiReplaceFileContent|RunCommand|write_file|Write|Edit|MultiEdit|SearchReplace|StrReplace|Bash|bash|Shell|shell|execute_command)$/i;
const TARGET_KEY_RE = /^(file_path|filepath|path|target|target_file|targetfile|target_path|targetpath|output|file|filename)$/i;
const PATH_LIKE_RE = /([^\s"'`<>|;&]+[\/\\][^\s"'`<>|;&]+\.(?:md|html|txt|json))/i;
const REDIRECT_RE = /(?:>|>>)\s*([^\s|&;]+(?:\.(?:md|html|txt|json)))/i;

function unquoteTranscriptVal(val) {
	if (typeof val !== "string") return val;
	const t = val.trim();
	if (t.length >= 2 && t.startsWith('"') && t.endsWith('"')) {
		try {
			const parsed = JSON.parse(t);
			if (typeof parsed === "string") return parsed;
		} catch {
			return t.slice(1, -1);
		}
	}
	return val;
}

function resolveTranscriptPaths(payloadOrPath) {
	if (typeof payloadOrPath === "string") {
		return resolveTranscriptPaths({ transcriptPath: payloadOrPath });
	}
	if (!payloadOrPath || typeof payloadOrPath !== "object") return [];
	const candidates = [];
	const add = (p) => {
		if (typeof p === "string" && p.trim() && !candidates.includes(p.trim())) {
			candidates.push(p.trim());
		}
	};
	const tp = payloadOrPath.transcriptPath || payloadOrPath.transcript_path || "";
	if (typeof tp === "string" && tp.trim()) {
		add(tp);
		if (/transcript\.jsonl$/i.test(tp) && !/transcript_full\.jsonl$/i.test(tp)) {
			add(tp.replace(/transcript\.jsonl$/i, "transcript_full.jsonl"));
		} else if (/transcript_full\.jsonl$/i.test(tp)) {
			add(tp.replace(/transcript_full\.jsonl$/i, "transcript.jsonl"));
		}
	}
	const adp = payloadOrPath.artifactDirectoryPath || payloadOrPath.artifact_directory_path || "";
	if (typeof adp === "string" && adp.trim()) {
		add(path.join(adp, ".system_generated", "logs", "transcript_full.jsonl"));
		add(path.join(adp, ".system_generated", "logs", "transcript.jsonl"));
		add(path.join(adp, "transcript_full.jsonl"));
		add(path.join(adp, "transcript.jsonl"));
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
	if (!tc || typeof tc !== "object") return null;
	const toolName = unquoteTranscriptVal(tc.name || tc.tool_name || tc.toolName || tc.function?.name || "");
	if (toolName && !WRITE_OR_CMD_TOOL_RE.test(toolName)) return null;
	let rawArgs = tc.args ?? tc.arguments ?? tc.input ?? tc.parameters ?? tc.function?.arguments ?? tc;
	if (typeof rawArgs === "string") {
		rawArgs = tryParseJson(unquoteTranscriptVal(rawArgs)) ?? tryParseJson(rawArgs);
	}
	if (!rawArgs || typeof rawArgs !== "object") return null;

	const getStr = (...keys) => {
		for (const k of keys) {
			if (typeof rawArgs[k] === "string" && rawArgs[k]) {
				return unquoteTranscriptVal(rawArgs[k]);
			}
		}
		return "";
	};

	let targetFile = getStr("TargetFile", "target_file", "file_path", "filepath", "path", "target", "target_path", "targetpath", "output", "file", "filename");
	const commandLine = getStr("CommandLine", "command_line", "command", "cmd", "script");
	let codeContent = getStr("CodeContent", "code_content", "ReplacementContent", "replacement_content", "content", "new_string", "text");
	if (!codeContent && rawArgs.ReplacementChunks !== undefined) {
		let chunks = rawArgs.ReplacementChunks;
		if (typeof chunks === "string") {
			chunks = tryParseJson(unquoteTranscriptVal(chunks)) ?? tryParseJson(chunks);
		}
		if (Array.isArray(chunks)) {
			codeContent = chunks
				.map((c) => (c && typeof c === "object" ? unquoteTranscriptVal(c.ReplacementContent || c.replacement_content || c.content || "") : ""))
				.filter(Boolean)
				.join("\n");
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

function extractTargetFromNode(node, out) {
	if (Array.isArray(node)) {
		for (const item of node) extractTargetFromNode(item, out);
		return;
	}
	if (!node || typeof node !== "object") return;
	for (const [key, value] of Object.entries(node)) {
		if (typeof value === "string" && value) {
			if (TARGET_KEY_RE.test(key)) out.push({ value, isCommand: false });
			else if (/^(command|cmd|command_line|commandline|script|args)$/i.test(key)) out.push({ value, isCommand: true });
		} else if (value && typeof value === "object") {
			extractTargetFromNode(value, out);
		}
	}
}

function extractFromTranscript(payloadOrPath) {
	const paths = resolveTranscriptPaths(payloadOrPath);
	const targetStepIdx =
		payloadOrPath && typeof payloadOrPath === "object"
			? typeof payloadOrPath.stepIdx === "number"
				? payloadOrPath.stepIdx
				: typeof payloadOrPath.step_index === "number"
					? payloadOrPath.step_index
					: undefined
			: undefined;

	for (const tp of paths) {
		try {
			const content = fs.readFileSync(tp, "utf8");
			const lines = content.split(/\r?\n/).filter((l) => l.trim().length > 0).slice(-50).reverse();
			const parsedSteps = [];
			let hasTruncatedToolCalls = false;
			for (const line of lines) {
				const step = tryParseJson(line);
				if (!step || typeof step !== "object") continue;
				if (Array.isArray(step.truncated_fields) && step.truncated_fields.includes("tool_calls")) {
					hasTruncatedToolCalls = true;
				}
				parsedSteps.push({ step, line });
			}
			if (hasTruncatedToolCalls && paths.some((p) => p !== tp && /transcript_full\.jsonl$/i.test(p))) {
				continue;
			}

			const searchSteps = (respectStepIdx) => {
				for (const { step, line } of parsedSteps) {
					const stepIdxVal = typeof step.step_index === "number" ? step.step_index : typeof step.stepIdx === "number" ? step.stepIdx : undefined;
					if (respectStepIdx && targetStepIdx !== undefined && stepIdxVal !== undefined && stepIdxVal > targetStepIdx) {
						continue;
					}
					const calls = Array.isArray(step.tool_calls)
						? step.tool_calls
						: Array.isArray(step.toolCalls)
							? step.toolCalls
							: step.toolCall && typeof step.toolCall === "object"
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
							if (!isCommand && u) return { toolName: "", targetFile: u, codeContent: "", commandLine: "" };
							if (isCommand && u) {
								const red = u.match(REDIRECT_RE);
								if (red) return { toolName: "run_command", targetFile: red[1], codeContent: "", commandLine: u };
								const m = u.match(PATH_LIKE_RE);
								if (m) return { toolName: "run_command", targetFile: m[1], codeContent: "", commandLine: u };
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

function extractTarget(sources) {
	const env = process.env.ANTIGRAVITY_TARGET_FILE || process.env.TARGET_FILE || "";
	if (env) return env;
	for (const s of sources) {
		if (s.parsed !== undefined) {
			if (s.parsed?.toolCall?.args?.TargetFile) return unquoteTranscriptVal(String(s.parsed.toolCall.args.TargetFile));
			const found = [];
			extractTargetFromNode(s.parsed, found);
			for (const { value, isCommand } of found) {
				const u = unquoteTranscriptVal(value);
				if (!isCommand) return u;
				const red = u.match(REDIRECT_RE);
				if (red) return red[1];
				const m = u.match(PATH_LIKE_RE);
				if (m) return m[1];
			}
			if (
				s.parsed &&
				typeof s.parsed === "object" &&
				(s.parsed.transcriptPath || s.parsed.transcript_path || s.parsed.artifactDirectoryPath || s.parsed.artifact_directory_path)
			) {
				const fromTranscript = extractFromTranscript(s.parsed);
				if (fromTranscript && fromTranscript.targetFile) return fromTranscript.targetFile;
			}
		}
	}
	for (const s of sources) {
		if (s.parsed !== undefined) continue;
		const red = s.text.match(REDIRECT_RE);
		if (red) return red[1];
		const m = s.text.match(PATH_LIKE_RE);
		if (m) return m[1];
	}
	return "";
}

const LEGAL_TRIGGER_RE = /소장|준비서면|고소장|내용증명|판결|판례|조문|민법|형법|법률|legal|draft|court/i;

function isPluginInternalDoc(targetFile) {
	try {
		const abs = path.resolve(targetFile);
		const rootAbs = path.resolve(root);
		if (!abs.startsWith(rootAbs + path.sep)) return false;
		const rel = path.relative(rootAbs, abs).replace(/\\/g, "/");
		return /^(GEMINI\.md|README\.md|CLAUDE\.md|CHARTER\.md|NOTICE|rules\/|docs\/|skills\/|agents\/|templates\/|contracts\/)/.test(rel);
	} catch {
		return false;
	}
}

const READ_CAP_BYTES = 2 * 1024 * 1024;
const TAIL_BYTES = 512 * 1024;

function readSamples(filePath) {
	try {
		const stat = fs.statSync(filePath);
		if (stat.size <= READ_CAP_BYTES) {
			return [fs.readFileSync(filePath, "utf8")];
		}
		const fd = fs.openSync(filePath, "r");
		try {
			const headBuf = Buffer.alloc(READ_CAP_BYTES);
			fs.readSync(fd, headBuf, 0, READ_CAP_BYTES, 0);
			const tailLen = Math.min(TAIL_BYTES, stat.size - READ_CAP_BYTES);
			const tailBuf = Buffer.alloc(tailLen);
			fs.readSync(fd, tailBuf, 0, tailLen, stat.size - tailLen);
			return [headBuf.toString("utf8"), tailBuf.toString("utf8")];
		} finally {
			fs.closeSync(fd);
		}
	} catch {
		return [];
	}
}

function shouldAudit(filePath) {
	if (isPluginInternalDoc(filePath)) return false;
	if (!/\.(md|html|txt)$/i.test(filePath)) return false;
	if (LEGAL_TRIGGER_RE.test(filePath)) return true;
	if (fs.existsSync(filePath)) {
		for (const chunk of readSamples(filePath)) {
			if (LEGAL_TRIGGER_RE.test(chunk)) return true;
		}
	}
	return false;
}

function sourceCandidate(targetFile) {
	const dir = path.dirname(path.resolve(targetFile));
	const candidates = [
		join(dir, "facts.json"),
		join(dir, "facts.md"),
		join(dir, "facts.txt"),
		join(dir, "evidence.json"),
		join(dir, "evidence.txt"),
		join(dir, "evidence.md"),
		join(dir, "source.md"),
		join(dir, "source.txt"),
	];
	return candidates.find((p) => fs.existsSync(p));
}

function ledgerCandidate(targetFile) {
	const dir = path.dirname(path.resolve(targetFile));
	const candidates = [
		join(dir, "claim-ledger.md"),
		join(dir, "claim_ledger.md"),
		join(process.cwd(), "claim-ledger.md"),
		join(process.cwd(), "claim_ledger.md"),
	];
	return candidates.find((p) => fs.existsSync(p));
}

async function main() {
	const sources = await collectSources();
	const targetFile = extractTarget(sources);

	if (!targetFile || !fs.existsSync(targetFile)) {
		process.stdout.write("{}\n");
		process.exit(0);
	}
	if (!shouldAudit(targetFile)) {
		process.stdout.write("{}\n");
		process.exit(0);
	}

	const verifyScript = join(root, "scripts", "verify_legal_factuality.py");
	if (!fs.existsSync(verifyScript)) {
		console.error(`[LEGAL FACTUALITY GUARD] NOT_CHECKED: verifier 스크립트 없음 (${verifyScript}) — 법률 사실관계 검증이 수행되지 않았습니다.`);
		process.stdout.write("{}\n");
		process.exit(0);
	}

	const srcFile = sourceCandidate(targetFile);
	const ledgerFile = ledgerCandidate(targetFile);
	const verifyArgs = [verifyScript, targetFile, "--json"];
	if (srcFile) {
		verifyArgs.push("--source", srcFile);
	}
	if (ledgerFile) {
		verifyArgs.push("--claim-ledger", ledgerFile);
	}

	const venvPy = join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
	const pyCandidates = [
		...(fs.existsSync(venvPy) ? [{ cmd: venvPy, pre: [] }] : []),
		...(process.platform === "win32"
			? [
					{ cmd: "python", pre: [] },
					{ cmd: "py", pre: ["-3"] },
					{ cmd: "python3", pre: [] },
				]
			: [
					{ cmd: "python3", pre: [] },
					{ cmd: "python", pre: [] },
				]),
	];
	let res = null;
	for (const { cmd, pre } of pyCandidates) {
		const candidateRes = spawnSync(cmd, [...pre, ...verifyArgs], {
			cwd: root,
			encoding: "utf-8",
			windowsHide: true,
		});
		const isWinStoreAlias =
			candidateRes.status === 9009 ||
			(candidateRes.stderr && /Microsoft Store|WindowsApps|AppExecutionAlias/i.test(candidateRes.stderr));
		if (!candidateRes.error && !isWinStoreAlias) {
			res = candidateRes;
			break;
		}
	}

	if (!res || res.error) {
		console.error(`[LEGAL FACTUALITY GUARD] UNAVAILABLE: python 실행 불가 — 검증이 수행되지 않았습니다 (무자격 통과 아님).`);
		process.stdout.write("{}\n");
		process.exit(0);
	}

	if (res.status !== 0) {
		let reason = "법률 사실관계 및 조문/판례 검증 실패";
		try {
			const data = JSON.parse(res.stdout);
			if (data.errors && data.errors.length > 0) {
				reason = data.errors.join("; ");
			}
		} catch {
			reason = res.stderr || res.stdout || reason;
		}
		console.error(`[LEGAL FACTUALITY GUARD] FAIL_CLOSED: ${reason}`);
		console.error(`[HINT] 허위 조문 번호(예: 민법 1118조 초과) 및 가짜 판례 번호를 수정하십시오.`);
		process.stdout.write(JSON.stringify({ decision: "block", reason }) + "\n");
		process.exit(1);
	}

	process.stdout.write("{}\n");
	process.exit(0);
}

main();
