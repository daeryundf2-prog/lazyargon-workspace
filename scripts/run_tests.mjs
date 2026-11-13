// npm test 진입점. ./scripts/py 리졸버를 통해 test/ 및 tests/ 전체(pytest)를 실행하고, 이어서 test/*.test.mjs(node --test)를 실행한다.
import { existsSync, readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";

const win = process.platform === "win32";
let pytest;
if (!win && existsSync("./scripts/py")) {
  pytest = spawnSync("./scripts/py", ["-m", "pytest", "test", "tests", ...process.argv.slice(2)], { stdio: "inherit" });
} else {
  const venvPython = win ? ".venv/Scripts/python.exe" : ".venv/bin/python";
  const python = existsSync(venvPython) ? venvPython : win ? "python" : "python3";
  pytest = spawnSync(python, ["-m", "pytest", "test", "tests", ...process.argv.slice(2)], { stdio: "inherit" });
}
const nodeTests = existsSync("test") ? readdirSync("test").filter((f) => f.endsWith(".test.mjs")).map((f) => `test/${f}`) : [];
const node = nodeTests.length ? spawnSync(process.execPath, ["--test", ...nodeTests], { stdio: "inherit" }) : { status: 0 };
process.exit((pytest.status ?? 1) || (node.status ?? 1));
