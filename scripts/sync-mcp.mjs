import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const pluginRoot = path.resolve(__dirname, "..");
const sourceMcpDir = path.join(pluginRoot, "mcp");

// Antigravity spec: plugin's own mcp/ + mcp_config.json is authoritative.
// This sync is OPTIONAL legacy helper — mirrors definitions to the
// global Antigravity MCP directory for older runtimes that expect
// ~/.gemini/antigravity/mcp. It does NOT replace mcp_config.json.
const legacyTarget = fs.existsSync(path.join(pluginRoot, "..", "..", "..", "antigravity", "mcp"))
  ? path.join(pluginRoot, "..", "..", "..", "antigravity", "mcp")
  : path.join(pluginRoot, "..", "..", "antigravity", "mcp");

console.log(`[lazyothers:sync] Source: ${sourceMcpDir}`);
console.log(`[lazyothers:sync] plugin.json mcpServers -> ./mcp_config.json (primary)`);
console.log(`[lazyothers:sync] Legacy mirror target (optional): ${legacyTarget}`);

if (!fs.existsSync(sourceMcpDir)) {
  console.error(`[lazyothers:sync] Error: Source directory does not exist: ${sourceMcpDir}`);
  process.exit(1);
}

function copyRecursive(src, dest) {
  const stats = fs.statSync(src);
  if (stats.isDirectory()) {
    if (!fs.existsSync(dest)) {
      fs.mkdirSync(dest, { recursive: true });
    }
    const entries = fs.readdirSync(src);
    for (const entry of entries) {
      copyRecursive(path.join(src, entry), path.join(dest, entry));
    }
  } else {
    fs.copyFileSync(src, dest);
  }
}

// Validate mcp_config.json covers all bundled tools
try {
  const mcpConfigPath = path.join(pluginRoot, "mcp_config.json");
  const mcpConfig = JSON.parse(fs.readFileSync(mcpConfigPath, "utf-8"));
  const bundledTools = fs.readdirSync(sourceMcpDir).filter((d) => fs.statSync(path.join(sourceMcpDir, d)).isDirectory());
  const registeredServers = Object.keys(mcpConfig.mcpServers || {});
  console.log(`[lazyothers:sync] Bundled tools: ${bundledTools.join(", ")}`);
  console.log(`[lazyothers:sync] Registered servers: ${registeredServers.join(", ")}`);
  for (const tool of bundledTools) {
    if (!registeredServers.includes(tool)) {
      console.warn(`[lazyothers:sync] WARN: bundled tool '${tool}' not in mcp_config.json`);
    }
  }
} catch (e) {
  console.warn(`[lazyothers:sync] Could not validate mcp_config.json: ${e.message}`);
}

// Validate package.json / plugin.json version consistency — 두 파일이 중복 관리되므로
// 어느 한쪽만 bump되어 배포되는 사고를 설치 시점에 잡는다.
try {
  const pkg = JSON.parse(fs.readFileSync(path.join(pluginRoot, "package.json"), "utf-8"));
  const plugin = JSON.parse(fs.readFileSync(path.join(pluginRoot, "plugin.json"), "utf-8"));
  if (pkg.version !== plugin.version) {
    console.warn(
      `[lazyothers:sync] WARN: version mismatch — package.json=${pkg.version}, plugin.json=${plugin.version}. 두 파일을 함께 bump하세요.`
    );
  } else {
    console.log(`[lazyothers:sync] Version check OK: ${pkg.version}`);
  }
} catch (e) {
  console.warn(`[lazyothers:sync] Could not validate version consistency: ${e.message}`);
}

// Python deps: install.sh가 PEP 668로 .venv 폴백을 쓴 경우 venv python을
// 우선 사용한다 — uv가 있으면 uv pip, 없으면 python -m pip을 사용한다.
try {
  const venvPy = path.join(
    pluginRoot, ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  if (fs.existsSync(venvPy)) {
    try {
      execSync(`uv pip install -r requirements.txt --python "${venvPy}"`, { cwd: pluginRoot, stdio: "inherit", timeout: 30000 });
    } catch {
      execSync(`"${venvPy}" -m pip install -r requirements.txt`, { cwd: pluginRoot, stdio: "inherit", timeout: 30000 });
    }
  } else {
    try {
      execSync(`uv pip install -r requirements.txt`, { cwd: pluginRoot, stdio: "inherit", timeout: 30000 });
    } catch {
      execSync(`python3 -m pip install -r requirements.txt`, { cwd: pluginRoot, stdio: "inherit", timeout: 30000 });
    }
  }
} catch {
  console.warn("[lazyothers:sync] WARN: pip install skipped/failed — run 'pip install -r requirements.txt' manually (미설치 시 파싱 시점에 늦게 발현될 수 있음)");
}

// Optional legacy mirror — skip if target parent does not exist
try {
  if (fs.existsSync(path.dirname(legacyTarget))) {
    if (!fs.existsSync(legacyTarget)) {
      fs.mkdirSync(legacyTarget, { recursive: true });
    }
    const toolDirs = fs.readdirSync(sourceMcpDir);
    for (const tool of toolDirs) {
      const srcTool = path.join(sourceMcpDir, tool);
      const destTool = path.join(legacyTarget, tool);
      copyRecursive(srcTool, destTool);
      console.log(`  ✓ Mirrored (legacy): ${tool}`);
    }
  } else {
    console.log("[lazyothers:sync] Legacy target parent not found — skipping mirror (primary is mcp_config.json)");
  }
  console.log("[lazyothers:sync] Done. Primary MCP registration is via plugin.json -> mcp_config.json");
} catch (err) {
  console.error("[lazyothers:sync] Failed:", err);
  process.exit(1);
}
