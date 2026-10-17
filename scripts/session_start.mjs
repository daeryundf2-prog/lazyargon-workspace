#!/usr/bin/env node
// session_start.mjs — SessionStart 훅. GEMINI.md(정적, 캐시 안정)를 앞에, 런타임 상태를 맨 뒤에 붙인다.
// 런타임 상태: korean_law MCP 준비 상태, 호스트가 보고한 세션 모델(없으면 unknown — 추정하지 않는다),
// 진행 중인 /ulw 범위 잠금(.lazyargon/ulw-scope.md, 컴팩션 뒤 복구용), 가드 팩 버전.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { stdin } from "node:process";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const SCOPE_FILE = join(process.cwd(), ".lazyargon", "ulw-scope.md");
const SCOPE_MAX_LINES = 12;
const PINS_FILE = join(process.cwd(), ".lazyargon", "pins.md");
const PINS_MAX_LINES = 20;

function readStdin(limitMs) {
	return new Promise((resolve) => {
		if (stdin.isTTY) {
			resolve("");
			return;
		}
		const chunks = [];
		const finish = () => {
			clearTimeout(timer);
			stdin.removeAllListeners();
			resolve(Buffer.concat(chunks).toString("utf8"));
		};
		const timer = setTimeout(finish, limitMs);
		stdin.on("data", (chunk) => {
			chunks.push(chunk);
		});
		stdin.on("end", finish);
		stdin.on("error", () => {
			clearTimeout(timer);
			resolve("");
		});
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

function hookEventName(payload) {
	return typeof payload.hook_event_name === "string" && payload.hook_event_name ? payload.hook_event_name : "SessionStart";
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

const scopeLock = () => headOf(SCOPE_FILE, SCOPE_MAX_LINES);
const pins = () => headOf(PINS_FILE, PINS_MAX_LINES);

function guardPackVersion() {
	try {
		const src = readFileSync(join(root, "scripts", "markdown_structure_guard.mjs"), "utf8");
		const m = src.match(/const GUARD_PACK_VERSION = '([^']+)'/);
		return m ? m[1] : "unknown";
	} catch {
		return "unknown";
	}
}

function additionalContext(payload) {
	try {
		const gemini = readFileSync(join(root, "GEMINI.md"), "utf8").replace(/\r\n/g, "\n").trim();
		const model = sessionModel(payload);
		const runtime = [
			"## 런타임",
			"",
			`korean_law: ${koreanLawStatus()}`,
			`세션 모델: ${model}${model === "unknown" ? " (호스트 미보고 — Argon이라고 가정하지 말 것)" : ""}`,
			`가드 팩: ${guardPackVersion()}`,
			"",
			"### 범위 잠금 (.lazyargon/ulw-scope.md)",
			"",
			scopeLock(),
			"",
			"### 고정 식별자 (.lazyargon/pins.md — 해시·경로·사건번호는 기억 대신 이 값과 원본을 쓴다)",
			"",
			pins(),
		].join("\n");
		return `${gemini}\n\n${runtime}`;
	} catch {
		return "";
	}
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
	const raw = await readStdin(250);
	const payload = parsePayload(raw);
	const context = additionalContext(payload);
	if (context) {
		process.stdout.write(
			`${JSON.stringify({
				injectSteps: [{ systemMessage: { systemMessage: context } }],
				additionalContext: context,
				hookSpecificOutput: {
					hookEventName: hookEventName(payload),
					additionalContext: context,
				},
			})}\n`,
		);
	} else {
		process.stdout.write("{}\n");
	}
	process.exit(0);
}
