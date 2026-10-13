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

const TARGET_KEY_RE = /^(file_path|filepath|path|target|target_file|targetfile|target_path|targetpath|output|file|filename)$/i;
const PATH_LIKE_RE = /([^\s"'`<>|;&]+[\/\\][^\s"'`<>|;&]+\.(?:md|html|txt|json))/i;

function extractTargetFromNode(node, out) {
	if (Array.isArray(node)) {
		for (const item of node) extractTargetFromNode(item, out);
		return;
	}
	if (!node || typeof node !== "object") return;
	for (const [key, value] of Object.entries(node)) {
		if (typeof value === "string" && value) {
			if (TARGET_KEY_RE.test(key)) out.push(value);
		} else if (value && typeof value === "object") {
			extractTargetFromNode(value, out);
		}
	}
}

function extractTarget(sources) {
	const env = process.env.ANTIGRAVITY_TARGET_FILE || process.env.TARGET_FILE || "";
	if (env) return env;
	for (const s of sources) {
		if (s.parsed !== undefined) {
			const found = [];
			extractTargetFromNode(s.parsed, found);
			if (found.length > 0) return found[0];
		}
	}
	for (const s of sources) {
		const m = s.text.match(PATH_LIKE_RE);
		if (m) return m[1];
	}
	return "";
}

const LEGAL_TRIGGER_RE = /소장|준비서면|고소장|내용증명|판결|판례|조문|민법|형법|법률|legal|draft|court/i;

function shouldAudit(filePath) {
	if (!/\.(md|txt)$/i.test(filePath)) return false;
	if (LEGAL_TRIGGER_RE.test(filePath)) return true;
	if (fs.existsSync(filePath)) {
		try {
			const head = fs.readFileSync(filePath, "utf8").slice(0, 2000);
			if (LEGAL_TRIGGER_RE.test(head)) return true;
		} catch {}
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
		process.exit(0);
	}
	if (!shouldAudit(targetFile)) {
		process.exit(0);
	}

	const verifyScript = join(root, "scripts", "verify_legal_factuality.py");
	if (!fs.existsSync(verifyScript)) {
		console.error(`[LEGAL FACTUALITY GUARD] NOT_CHECKED: verifier 스크립트 없음 (${verifyScript}) — 법률 사실관계 검증이 수행되지 않았습니다.`);
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

	const pyCandidates = process.platform === "win32" ? ["python", "py", "python3"] : ["python3", "python"];
	let res = null;
	for (const py of pyCandidates) {
		res = spawnSync(py, verifyArgs, {
			cwd: root,
			encoding: "utf-8",
			windowsHide: true,
		});
		if (!res.error && res.status !== 9009) break;
	}

	if (!res || res.error) {
		console.error(`[LEGAL FACTUALITY GUARD] UNAVAILABLE: python 실행 불가 — 검증이 수행되지 않았습니다 (무자격 통과 아님).`);
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
		process.exit(1);
	}

	process.exit(0);
}

main();
