#!/usr/bin/env node
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const entrypoint = join(root, "korean-law-mcp", "build", "index.js");
const apiKey = process.env.LAW_OC || process.env.KOREAN_LAW_API_KEY;

if (!existsSync(entrypoint)) {
	process.stderr.write(
		"[lazyforensic] korean_law disabled (빌드없음): build/index.js is missing. Run node scripts/setup_korean_law.mjs\n",
	);
	process.exit(78);
}

if (!apiKey) {
	process.stderr.write(
		"[lazyforensic] korean_law disabled (키없음: LAW_OC): set LAW_OC or KOREAN_LAW_API_KEY (see .env.example). Statutes must not be fabricated.\n",
	);
	process.exit(79);
}

const child = spawn(process.execPath, [entrypoint], {
	cwd: root,
	env: process.env,
	stdio: "inherit",
	windowsHide: true,
});

child.on("error", (error) => {
	process.stderr.write(`[lazyforensic] korean_law failed to start: ${error.message}\n`);
	process.exit(1);
});

child.on("exit", (code, signal) => {
	if (signal) {
		process.kill(process.pid, signal);
		return;
	}
	process.exit(code ?? 1);
});
