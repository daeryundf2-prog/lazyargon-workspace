// npm test 진입점. 시스템 python에는 olefile 등 requirements가 없을 수 있어 repo .venv를 우선한다.
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";

const win = process.platform === "win32";
const venvPython = win ? ".venv/Scripts/python.exe" : ".venv/bin/python";
const python = existsSync(venvPython) ? venvPython : win ? "python" : "python3";
const result = spawnSync(python, ["-m", "pytest", "tests", ...process.argv.slice(2)], { stdio: "inherit" });
process.exit(result.status ?? 1);
