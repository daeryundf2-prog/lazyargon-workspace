#!/usr/bin/env node
// session_start.mjs — SessionStart 훅. GEMINI.md(정적, 캐시 안정)를 앞에, 런타임 상태를 맨 뒤에 붙인다.
// 런타임 상태: korean_law MCP 준비 상태, 호스트가 보고한 세션 모델(없으면 unknown — 추정하지 않는다),
// 진행 중인 /ulw 범위 잠금(.lazyargon/ulw-scope.md, 컴팩션 뒤 복구용), 가드 팩 버전.
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { stdin } from "node:process";
import { fileURLToPath } from "node:url";
import { lazyargonActive } from "./lazyargon_active.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const SIX_HOURS_MS = 6 * 60 * 60 * 1000;
const SCOPE_MAX_LINES = 12;
const PINS_MAX_LINES = 20;

function readStdin(limitMs = 1500) {
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
			try {
				stdin.pause();
			} catch {}
			stdin.removeAllListeners();
			resolve(value);
		};
		const timer = setTimeout(() => finish(Buffer.concat(chunks).toString("utf8")), limitMs);
		if (typeof timer.unref === "function") timer.unref();
		stdin.on("data", (chunk) => {
			chunks.push(chunk);
			const acc = Buffer.concat(chunks).toString("utf8").trim();
			if ((acc.startsWith("{") && acc.endsWith("}")) || (acc.startsWith("[") && acc.endsWith("]"))) {
				try {
					JSON.parse(acc);
					finish(acc);
				} catch {}
			}
		});
		stdin.on("end", () => finish(Buffer.concat(chunks).toString("utf8")));
		stdin.on("error", () => finish(""));
	});
}

function parsePayload(raw) {
	try {
		const parsed = JSON.parse(raw.trim());
		return parsed && typeof parsed === "object" ? parsed : {};
	} catch {
		return {};
	}
}

export function resolveWorkspaceCwd(payload = {}) {
	return (
		(Array.isArray(payload?.workspacePaths) && typeof payload.workspacePaths[0] === "string" && payload.workspacePaths[0].trim()) ||
		(typeof payload?.cwd === "string" && payload.cwd.trim()) ||
		process.cwd()
	);
}

// 호스트가 주는 모델명만 쓴다. 키 이름은 호스트 버전마다 달라 후보를 넓게 본다.
export function sessionModel(payload, env = process.env) {
	const candidates = [
		payload.modelName,
		payload.model_name,
		payload.sessionModel,
		payload.session_model,
		payload.model,
		payload.session?.modelName,
		payload.session?.model,
		env.ANTIGRAVITY_MODEL_NAME,
		env.ANTIGRAVITY_MODEL,
	];
	for (const c of candidates) {
		if (typeof c === "string" && c.trim()) return c.trim();
	}
	return "unknown";
}

function koreanLawStatus() {
	const built = existsSync(join(root, "korean-law-mcp", "build", "index.js"));
	const hasKey = Boolean(process.env.LAW_OC || process.env.KOREAN_LAW_API_KEY);
	if (!built) {
		return "missing-build";
	}
	if (!hasKey) {
		return "missing-LAW_OC";
	}
	return "ready";
}

function headOf(file, maxLines) {
	try {
		if (!existsSync(file)) return "없음";
		const lines = readFileSync(file, "utf8").replace(/\r\n/g, "\n").split("\n").filter((l) => l.trim());
		const head = lines.slice(0, maxLines).join("\n");
		return lines.length > maxLines ? `${head}\n…(${lines.length - maxLines}줄 생략 — 파일을 직접 읽을 것)` : head;
	} catch {
		return "읽기 실패";
	}
}

function tailOf(file, maxLines) {
	try {
		if (!existsSync(file)) return "없음";
		const lines = readFileSync(file, "utf8").replace(/\r\n/g, "\n").split("\n").filter((l) => l.trim());
		const tail = lines.slice(-maxLines).join("\n");
		return lines.length > maxLines ? `${tail}\n…(${lines.length - maxLines}줄 생략 — 파일을 직접 읽을 것)` : tail;
	} catch {
		return "읽기 실패";
	}
}

const scopeLock = (cwd = process.cwd()) => headOf(join(cwd, ".lazyargon", "ulw-scope.md"), SCOPE_MAX_LINES);
const pins = (cwd = process.cwd()) => tailOf(join(cwd, ".lazyargon", "pins.md"), PINS_MAX_LINES);

function guardPackVersion() {
	try {
		const src = readFileSync(join(root, "scripts", "markdown_structure_guard.mjs"), "utf8");
		const m = src.match(/const GUARD_PACK_VERSION = '([^']+)'/);
		return m ? m[1] : "unknown";
	} catch {
		return "unknown";
	}
}

export function additionalContext(payload = {}) {
	try {
		const cwd = resolveWorkspaceCwd(payload);
		const model = sessionModel(payload);
		return [
			"# LazyForensic — 런타임 요약 (상세 규칙은 rules/GEMINI.md 로더 주입)",
			"불변식 요약: 실패 폐쇄 · 호스트 `Read` · `invoke_subagent` · 증거 오디오 외부 전송 금지",
			"",
			"## 런타임",
			"",
			`워크스페이스: ${cwd}`,
			`korean_law: ${koreanLawStatus()}`,
			`세션 모델: ${model}${model === "unknown" ? " (호스트 미보고 — Argon이라고 가정하지 말 것)" : ""}`,
			`가드 팩: ${guardPackVersion()}`,
			"",
			"### 범위 잠금 (.lazyargon/ulw-scope.md)",
			"",
			scopeLock(cwd),
			"",
			"### 고정 식별자 (.lazyargon/pins.md — 해시·경로·사건번호는 기억 대신 이 값과 원본을 쓴다)",
			"",
			pins(cwd),
		].join("\n");
	} catch {
		return "";
	}
}

export function minimalContext() {
	return `# LazyForensic — 런타임 요약\nkorean_law: ${koreanLawStatus()}\n가드 팩: ${guardPackVersion()}`;
}

// ---------------------------------------------------------------------------
// Self-update (SessionStart): pull from origin/main when safe to do so.
// ---------------------------------------------------------------------------

/** Run git in dir; return stdout string on success, null on any error/timeout. */
function git(dir, args, timeoutMs = 5000) {
	const r = spawnSync("git", ["-C", dir, ...args], { encoding: "utf8", timeout: timeoutMs });
	if (r.error || r.signal != null || r.status !== 0) return null;
	return r.stdout;
}

/**
 * Attempt a safe fast-forward self-update of the plugin from origin/main.
 * Guards: must be on branch main with an origin remote; throttled to once per 6 h;
 * respects LAZYARGON_WORKSPACE_NO_AUTO_UPDATE=1; never stashes, resets, or touches dirty trees.
 * Writes one line to errOut (default process.stderr) on update or when behind+blocked.
 * Never throws; never causes a non-zero exit.
 *
 * @param {string}   pluginRoot  Absolute path to the plugin checkout (default: root).
 * @param {object}   env         Process environment (default: process.env).
 * @param {object}   errOut      Writable stream for notices (default: process.stderr).
 */
export function autoUpdate(pluginRoot = root, env = process.env, errOut = process.stderr) {
	try {
		// Opt-out env var.
		if (env.LAZYARGON_WORKSPACE_NO_AUTO_UPDATE === "1") return;

		// Must be a git checkout on branch main.
		const branch = git(pluginRoot, ["symbolic-ref", "--short", "HEAD"]);
		if (!branch || branch.trim() !== "main") return;

		// Must have an origin remote.
		const remotes = git(pluginRoot, ["remote"]);
		if (!remotes || !remotes.split("\n").map((s) => s.trim()).includes("origin")) return;

		// Throttle: at most once every 6 hours. The stamp lives inside .git so it never dirties the tree.
		const gitDirOut = git(pluginRoot, ["rev-parse", "--absolute-git-dir"]);
		if (!gitDirOut) return;
		const stateDir = gitDirOut.trim();
		const stateFile = join(stateDir, "lazyargon-workspace-last-update-check");
		try {
			if (existsSync(stateFile)) {
				const ts = parseInt(readFileSync(stateFile, "utf8").trim(), 10);
				if (!isNaN(ts) && Date.now() - ts < SIX_HOURS_MS) return;
			}
		} catch { /* ignore */ }

		// Record the check time before the fetch (prevents hammering on network errors).
		try {
			mkdirSync(stateDir, { recursive: true });
			writeFileSync(stateFile, String(Date.now()), "utf8");
		} catch { /* ignore */ }

		// Snapshot HEAD before fetch.
		const headOut = git(pluginRoot, ["rev-parse", "HEAD"]);
		if (!headOut) return;
		const beforeSha = headOut.trim();

		// Fetch with hard <=8 s timeout; any failure stays silent.
		const fetchResult = spawnSync("git", ["-C", pluginRoot, "fetch", "origin", "main"], {
			encoding: "utf8",
			timeout: 8000,
		});
		if (fetchResult.error || fetchResult.signal != null || fetchResult.status !== 0) return;

		// What did origin/main land on?
		const fetchOut = git(pluginRoot, ["rev-parse", "FETCH_HEAD"]);
		if (!fetchOut) return;
		const fetchSha = fetchOut.trim();

		// Count commits we're behind; none (up to date or only local commits ahead) stays silent.
		const countOut = git(pluginRoot, ["rev-list", "--count", `${beforeSha}..${fetchSha}`]);
		if (countOut === null) return;
		const n = countOut.trim();
		if (n === "0") return;

		// Check working-tree cleanliness (porcelain is empty iff no changes and no untracked).
		const statusOut = git(pluginRoot, ["status", "--porcelain"]);
		if (statusOut === null) return;
		const dirty = statusOut.trim().length > 0;

		if (!dirty) {
			// Try fast-forward merge.
			const merge = spawnSync("git", ["-C", pluginRoot, "merge", "--ff-only", fetchSha], {
				encoding: "utf8",
				timeout: 8000,
			});
			if (merge.status === 0 && merge.signal == null && !merge.error) {
				const old7 = beforeSha.slice(0, 7);
				const new7 = fetchSha.slice(0, 7);
				errOut.write(`LazyArgon Workspace updated ${old7}..${new7} (${n} commits)\n`);
			} else {
				// History diverged (local commits) — cannot fast-forward.
				errOut.write(
					`LazyArgon Workspace: ${n} updates on origin/main; local commits differ, not auto-updated. Run: git -C ${pluginRoot} pull --rebase origin main\n`,
				);
			}
		} else {
			// Dirty working tree — leave everything alone.
			errOut.write(
				`LazyArgon Workspace: ${n} updates on origin/main; local changes present, not auto-updated. Run: git -C ${pluginRoot} stash && git -C ${pluginRoot} pull --ff-only\n`,
			);
		}
	} catch { /* never propagate */ }
}


/** Notices from the background updater go to <git-dir>/lazyargon-workspace-update.log (the hook's stdout is reserved). */
function updateLog(pluginRoot) {
	const gitDir = git(pluginRoot, ["rev-parse", "--absolute-git-dir"]);
	const path = gitDir ? join(gitDir.trim(), "lazyargon-workspace-update.log") : null;
	return { write: (line) => { try { if (path) appendFileSync(path, `${new Date().toISOString()} ${line}`); } catch { /* ignore */ } } };
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain && process.argv.includes("--self-update")) {
	autoUpdate(root, process.env, updateLog(root));
	process.exit(0);
}
if (isMain) {
	// The SessionStart hook has a 5 s budget, so the update check runs in a detached child after this one exits.
	try {
		if (process.env.LAZYARGON_WORKSPACE_NO_AUTO_UPDATE !== "1")
			spawn(process.execPath, [fileURLToPath(import.meta.url), "--self-update"], { detached: true, stdio: "ignore" }).unref();
	} catch { /* never block the session */ }
	const raw = await readStdin(1500);
	const payload = parsePayload(raw);
	const useMinimal = process.argv.includes("--minimal") && lazyargonActive(root, "plugin.json");
	const context = useMinimal ? minimalContext() : additionalContext(payload);
	if (context) {
		// Antigravity drops the whole SessionStart output when it carries keys beyond injectSteps
		// (verified live 2026-10-30: extra additionalContext/hookSpecificOutput -> nothing injected).
		process.stdout.write(`${JSON.stringify({ injectSteps: [{ systemMessage: { systemMessage: context } }] })}\n`);
	} else {
		process.stdout.write("{}\n");
	}
	process.exit(0);
}
