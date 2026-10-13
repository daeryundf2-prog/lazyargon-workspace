#!/usr/bin/env node
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { stdin } from "node:process";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

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

function hookEventName(raw) {
	try {
		const parsed = JSON.parse(raw.trim());
		if (parsed && typeof parsed.hook_event_name === "string" && parsed.hook_event_name) {
			return parsed.hook_event_name;
		}
	} catch {
		// fail open
	}
	return "SessionStart";
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

function additionalContext() {
	try {
		const gemini = readFileSync(join(root, "GEMINI.md"), "utf8").replace(/\r\n/g, "\n").trim();
		return `${gemini}\n\n## 런타임\n\nkorean_law: ${koreanLawStatus()}`;
	} catch {
		return "";
	}
}

const raw = await readStdin(250);
const context = additionalContext();
if (context) {
	process.stdout.write(
		`${JSON.stringify({
			hookSpecificOutput: {
				hookEventName: hookEventName(raw),
				additionalContext: context,
			},
		})}\n`,
	);
}
process.exit(0);
