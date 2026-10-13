#!/bin/sh
# lock_evidence.sh — 증거 디렉토리 원클릭 읽기전용 잠금 (chmod 444).
# 가드(best-effort)를 OS 수준 잠금으로 보강한다. 사용: sh scripts/lock_evidence.sh [evidence_dir]
# 되돌리기: chmod -R u+w <dir>
set -eu
target="${1:-evidence}"
if [ ! -d "$target" ]; then
  echo "[lazyforensic] not a directory: $target" >&2
  exit 2
fi
chmod -R a-w "$target"
echo "[lazyforensic] locked (read-only): $target — 되돌리기: chmod -R u+w $target"
