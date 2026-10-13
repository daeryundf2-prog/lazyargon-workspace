// npm test 진입점. ./scripts/py 리졸버를 통해 test/ 및 tests/ 전체를 실행한다.
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";

const win = process.platform === "win32";
if (!win && existsSync("./scripts/py")) {
  const result = spawnSync("./scripts/py", ["-m", "pytest", "test", "tests", ...process.argv.slice(2)], { stdio: "inherit" });
  process.exit(result.status ?? 1);
}
const venvPython = win ? ".venv/Scripts/python.exe" : ".venv/bin/python";
const python = existsSync(venvPython) ? venvPython : win ? "python" : "python3";
const result = spawnSync(python, ["-m", "pytest", "test", "tests", ...process.argv.slice(2)], { stdio: "inherit" });
process.exit(result.status ?? 1);
