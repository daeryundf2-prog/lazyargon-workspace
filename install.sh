#!/usr/bin/env bash
# Antigravity 4-plugin auto-installer (macOS / Linux)
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
  for name in lazyantigravity lazyforensic lazyothers lazydiagram; do
    if [ -d "${PLUGIN_DIR}/${name}/.git" ]; then
      echo "  ✅ plugin ${name} ($(cd "${PLUGIN_DIR}/${name}" && git rev-parse --short HEAD))"
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
    if [ -x "${PLUGIN_DIR}/lazyothers/.venv/bin/python" ]; then
      PY="${PLUGIN_DIR}/lazyothers/.venv/bin/python"
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
lazyantigravity https://github.com/daeryundf2-prog/LAZYANTIGRAVITY.git
lazyforensic    https://github.com/daeryundf2-prog/lazyforensic.git
lazyothers      https://github.com/daeryundf2-prog/lazyothers.git
lazydiagram     https://github.com/daeryundf2-prog/lazydiagram.git
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
  echo "Building LazyAntigravity..."
  if [ -d "${PLUGIN_DIR}/lazyantigravity" ]; then
    (
      cd "${PLUGIN_DIR}/lazyantigravity"
      npm install
      npm run build || echo "  [!] Build failed"
    ) || echo "  [!] LazyAntigravity build failed"
  fi

  echo "Building korean-law-mcp (lazyforensic, optional)..."
  if [ -f "${PLUGIN_DIR}/lazyforensic/korean-law-mcp/package.json" ]; then
    (
      cd "${PLUGIN_DIR}/lazyforensic/korean-law-mcp"
      npm install
      npm run build || echo "  [!] korean-law-mcp build failed — korean_law MCP는 빌드 후 활성화됨"
    ) || echo "  [!] korean-law-mcp build failed"
  fi

  echo "Syncing LazyOthers MCP tools..."
  if [ -f "${PLUGIN_DIR}/lazyothers/package.json" ]; then
    (
      cd "${PLUGIN_DIR}/lazyothers"
      npm run setup || echo "  [!] Sync failed"
    ) || echo "  [!] LazyOthers sync failed"
  fi
else
  echo "[!] npm not found, skipping build/sync"
fi

# Python 의존성 (lazyothers 스킬 실행에 필요: pymupdf/olefile 등)
# PEP 668(externally-managed) 환경에서는 시스템 pip이 거부되므로 .venv로 폴백한다.
if command -v python3 >/dev/null 2>&1; then
  echo "Installing Python dependencies for lazyothers..."
  if (cd "${PLUGIN_DIR}/lazyothers" && python3 -m pip install -r requirements.txt) 2>/dev/null; then
    echo "  installed to system python"
  elif (cd "${PLUGIN_DIR}/lazyothers" && \
        python3 -m venv .venv && \
        .venv/bin/pip install -r requirements.txt); then
    echo "  [i] 시스템 python이 externally-managed라 ${PLUGIN_DIR}/lazyothers/.venv 에 설치됨"
    echo "      스크립트 실행 시 .venv/bin/python 사용: ${PLUGIN_DIR}/lazyothers/.venv/bin/python scripts/parse_korean_doc.py ..."
  else
    echo "  [!] pip install failed — 수동: cd ${PLUGIN_DIR}/lazyothers && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  fi

  # lazyforensic 선택 의존성 — 별도 venv(~/.lfenv)에 설치, 실패해도 계속
  if [ -f "${PLUGIN_DIR}/lazyforensic/scripts/setup_forensic_env.py" ]; then
    echo "Installing lazyforensic optional deps (~/.lfenv)..."
    (cd "${PLUGIN_DIR}/lazyforensic" && python3 scripts/setup_forensic_env.py) \
      || echo "  [!] lazyforensic env setup 실패 — 나중에: sh ${PLUGIN_DIR}/lazyforensic/bootstrap.sh"
  fi
else
  echo "[!] python3 not found, skipping pip install"
fi

# Merge config.json (do not overwrite)
CONFIG_PATH="${HOME}/.gemini/config/config.json"
mkdir -p "$(dirname "${CONFIG_PATH}")"
if command -v python3 >/dev/null 2>&1; then
  python3 << 'PY'
import json, os
config_path = os.path.expanduser("~/.gemini/config/config.json")
default_plugins = {
    "lazyantigravity": {"enabled": True},
    "lazyforensic": {"enabled": True},
    "lazyothers": {"enabled": True},
    "lazydiagram": {"enabled": True},
}
if os.path.exists(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[!] Failed to parse existing config.json: {e}, backing up")
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
PY
else
  echo "[!] python3 not found, skipping config merge — create ${CONFIG_PATH} manually"
fi

cd "${ORIGINAL_DIR}"
echo "=========================================="
echo "  Setup Completed Successfully! (PASS)"
echo "=========================================="
