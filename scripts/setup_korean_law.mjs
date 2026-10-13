#!/usr/bin/env node
import { appendFileSync, existsSync, mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pkg = join(root, "korean-law-mcp");

function getLogFileArg(argv) {
	for (let i = 0; i < argv.length; i++) {
		if (argv[i] === "--log-file" && argv[i + 1] && !argv[i + 1].startsWith("--")) return argv[i + 1];
		if (argv[i].startsWith("--log-file=")) {
			const v = argv[i].slice("--log-file=".length);
			if (v) return v;
		}
	}
	return null;
}

// --check: 빌드/키 상태만 출력하고 설치하지 않는다 (README 용량 안내용 진단).
if (process.argv.includes("--check")) {
	const built = existsSync(join(pkg, "build", "index.js"));
	const hasKey = Boolean(process.env.LAW_OC || process.env.KOREAN_LAW_API_KEY);
	process.stdout.write(
		`[lazyforensic] korean-law check: build=${built ? "ok" : "missing (≈680MB node_modules + build 필요)"} ` +
		`key=${hasKey ? "set" : "missing (LAW_OC 미설정)"}\n`,
	);
	if (!built) process.stdout.write("[hint] node scripts/setup_korean_law.mjs (최초 1회, 네트워크에 따라 수 분)\n");
	if (!hasKey) process.stdout.write("[hint] cp .env.example .env 후 LAW_OC 기입\n");
	// A3-1: ToS 판정 1줄 기록 — --log-file 지정 시 파일에 append, 없으면 stderr만. 기존 stdout/exit 불변.
	try {
		const tosAck = process.env.LAW_TOS_ACK === "1";
		const tosLine = `[${new Date().toISOString()}] LAW_TOS_ACK=${tosAck ? "1 (ack, bypass=enabled)" : "0 (missing, bypass=disabled)"} terms=2026.09\n`;
		const logFile = getLogFileArg(process.argv.slice(2));
		if (logFile) {
			try {
				const dir = dirname(logFile);
				if (dir && dir !== "." && dir !== "") mkdirSync(dir, { recursive: true });
			} catch {}
			appendFileSync(logFile, tosLine, "utf8");
		} else {
			process.stderr.write(tosLine);
		}
	} catch {}
	process.exit(built && hasKey ? 0 : 78);
}

if (!existsSync(join(pkg, "package.json"))) {
	// korean-law-mcp lives in its own repo; clone it into place on first setup.
	// Pinned to a commit so installs are reproducible — bump deliberately.
	// Override with KOREAN_LAW_MCP_REF=<sha|tag|branch> if a newer ref is wanted.
	const KOREAN_LAW_MCP_REF = process.env.KOREAN_LAW_MCP_REF || "44ff16ec884395a3e7424ca8ff76caa081c9390c";
	process.stdout.write(`[lazyforensic] cloning korean-law-mcp @ ${KOREAN_LAW_MCP_REF} …\n`);
	mkdirSync(pkg, { recursive: true });
	const steps = [
		["init"],
		["remote", "add", "origin", "https://github.com/daeryundf2-prog/korean-law-mcp.git"],
		["fetch", "--depth", "1", "origin", KOREAN_LAW_MCP_REF],
		["checkout", "--detach", "FETCH_HEAD"],
	];
	for (const args of steps) {
		const res = spawnSync("git", args, {
			cwd: pkg, stdio: "inherit", shell: process.platform === "win32", windowsHide: true,
		});
		if (res.error || res.status !== 0) {
			process.stderr.write(
				"[lazyforensic] korean-law-mcp clone failed — clone https://github.com/daeryundf2-prog/korean-law-mcp into ./korean-law-mcp manually.\n",
			);
			process.exit(1);
		}
	}
}

function run(command, args) {
	const result = spawnSync(command, args, {
		cwd: pkg,
		stdio: "inherit",
		shell: process.platform === "win32",
		windowsHide: true,
	});
	if (result.error) {
		process.stderr.write(`[lazyforensic] ${command} failed: ${result.error.message}\n`);
		process.exit(1);
	}
	if (result.status !== 0) {
		process.stderr.write(
			`[lazyforensic] ${command} ${args.join(" ")} exited ${result.status ?? 1}\n`,
		);
		process.exit(result.status ?? 1);
	}
}

run("npm", ["install", "--ignore-scripts"]);
run("npm", ["run", "build"]);

if (!existsSync(join(pkg, "build", "index.js"))) {
	process.stderr.write("[lazyforensic] build finished but korean-law-mcp/build/index.js is missing.\n");
	process.exit(1);
}

process.stdout.write(
	"[lazyforensic] korean-law-mcp build ready. Set LAW_OC or KOREAN_LAW_API_KEY before starting MCP. Do not fly deploy from this repo.\n",
);
