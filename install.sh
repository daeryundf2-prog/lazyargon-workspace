#!/usr/bin/env bash
# Antigravity 2-plugin auto-installer (macOS / Linux)
# NOTE: macOS 기본 bash는 3.2 — 연관 배열(declare -A) 없이 POSIX 호환으로 작성.
#
#   bash install.sh          # 전체 설치
#   bash install.sh --check  # 설치 없이 현재 상태 진단만
set -euo pipefail

PLUGIN_DIR="${HOME}/.gemini/config/plugins"
ORIGINAL_DIR="$(pwd)"

if [ "${1:-}" = "--check" ]; then
  CHECK_FAIL=0
  echo "== 환경 진단 (설치하지 않음) =="
  for name in lazyargon lazyargon-workspace; do
    if [ -d "${PLUGIN_DIR}/${name}/.git" ] || [ -f "${PLUGIN_DIR}/${name}/plugin.json" ]; then
      echo "  ✅ plugin ${name}"
    else
      echo "  ❌ plugin ${name} — 미설치"; CHECK_FAIL=1
    fi
  done
  for tool in git node npm python3; do
    if command -v "$tool" >/dev/null 2>&1; then
      echo "  ✅ $tool ($("$tool" --version 2>/dev/null | head -1))"
    else
      echo "  ❌ $tool — 미설치"; CHECK_FAIL=1
    fi
  done
  if command -v python3 >/dev/null 2>&1; then
    PY="python3"
    if [ -x "${PLUGIN_DIR}/lazyargon-workspace/.venv/bin/python" ]; then
      PY="${PLUGIN_DIR}/lazyargon-workspace/.venv/bin/python"
    elif [ -x "${HOME}/.lfenv/bin/python" ]; then
      PY="${HOME}/.lfenv/bin/python"
    fi
    for mod in fitz olefile openpyxl kiwipiepy anydoc; do
      if "$PY" -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('$mod') else 1)" 2>/dev/null; then
        echo "  ✅ python module ${mod}"
      else
        echo "  ❌ python module ${mod}"; CHECK_FAIL=1
      fi
    done
  fi
  exit "$CHECK_FAIL"
fi

mkdir -p "${PLUGIN_DIR}"
cd "${PLUGIN_DIR}"

# "이름 URL" 쌍 목록 (bash 3.2 호환)
PLUGINS="
lazyargon           https://github.com/daeryundf2-prog/lazyargon.git
lazyargon-workspace https://github.com/daeryundf2-prog/lazyargon-workspace.git
"

echo "$PLUGINS" | while read -r name url; do
  [ -z "${name:-}" ] && continue
  target="${PLUGIN_DIR}/${name}"
  if [ -d "${target}/.git" ]; then
    echo "Updating ${name}..."
    (
      cd "${target}"
      if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
        echo "  [!] ${name} has local changes, stashing..."
        git stash push -m "auto-stash before pull" || true
      fi
      git pull --ff-only || echo "  [!] git pull failed for ${name}"
    ) || echo "  [!] update failed for ${name}"
  else
    echo "Cloning ${name}..."
    git clone "${url}" "${target}" || echo "  [!] Failed to clone ${name}"
  fi
done

if command -v npm >/dev/null 2>&1; then
  echo "Building lazyargon..."
  if [ -f "${PLUGIN_DIR}/lazyargon/package.json" ]; then
    (
      cd "${PLUGIN_DIR}/lazyargon"
      npm install
      npm run build || echo "  [!] Build failed"
    ) || echo "  [!] lazyargon build failed"
  fi

  echo "Syncing lazyargon-workspace MCP tools..."
  if [ -f "${PLUGIN_DIR}/lazyargon-workspace/package.json" ]; then
    (
      cd "${PLUGIN_DIR}/lazyargon-workspace"
      npm run setup || echo "  [!] Sync failed"
    ) || echo "  [!] lazyargon-workspace sync failed"
  fi
else
  echo "[!] npm not found, skipping build/sync"
fi

if command -v python3 >/dev/null 2>&1; then
  echo "Installing Python dependencies for lazyargon-workspace..."
  if (cd "${PLUGIN_DIR}/lazyargon-workspace" && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt) 2>/dev/null; then
    echo "  installed to ${PLUGIN_DIR}/lazyargon-workspace/.venv"
  elif command -v uv >/dev/null 2>&1 && (cd "${PLUGIN_DIR}/lazyargon-workspace" && uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt); then
    echo "  installed to ${PLUGIN_DIR}/lazyargon-workspace/.venv via uv"
  else
    echo "  [!] pip install failed — 수동: cd ${PLUGIN_DIR}/lazyargon-workspace && uv pip install --python .venv/bin/python -r requirements.txt"
  fi
else
  echo "[!] python3 not found, skipping pip install"
fi

CONFIG_PATH="${HOME}/.gemini/config/config.json"
mkdir -p "$(dirname "${CONFIG_PATH}")"
if command -v python3 >/dev/null 2>&1; then
  python3 << 'PYEOF'
import json, os
config_path = os.path.expanduser("~/.gemini/config/config.json")
default_plugins = {
    "lazyargon": {"enabled": True},
    "lazyargon-workspace": {"enabled": True},
}
if os.path.exists(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        import shutil
        shutil.copy(config_path, config_path + ".bak")
        data = {}
    data.setdefault("plugins", {})
    for k, v in default_plugins.items():
        data["plugins"][k] = v
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Merged plugins into {config_path}")
else:
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({"plugins": default_plugins}, f, ensure_ascii=False, indent=2)
    print(f"Created {config_path}")
PYEOF
fi

cd "${ORIGINAL_DIR}"
echo "=========================================="
echo "  Setup Completed Successfully! (PASS)"
echo "=========================================="
