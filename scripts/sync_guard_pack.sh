#!/usr/bin/env bash
# sync_guard_pack.sh — 가드 팩(GUARD_PACK_VERSION 1.0.0)을 캐노니컬(lazyforensic)에서
# 자매 플러그인 레포로 동기화한다. 3레포가 같은 디렉터리에 클론되어 있을 때만 동작한다.
#
# 사용법: bash scripts/sync_guard_pack.sh
# 캐노니컬: lazyforensic/scripts/{markdown_structure_guard,stop_claim_guard,coverage_audit}.mjs
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
PARENT="$(dirname "$ROOT")"

GUARDS="markdown_structure_guard.mjs stop_claim_guard.mjs coverage_audit.mjs"

for repo in lazyantigravity lazyothers; do
  target="$PARENT/$repo/scripts"
  if [ ! -d "$target" ]; then
    echo "[skip] $PARENT/$repo 가 없다 — 인접 클론이 아니다"
    continue
  fi
  for guard in $GUARDS; do
    if [ ! -f "$ROOT/scripts/$guard" ]; then
      echo "[skip] 캐노니컬에 $guard 없음"
      continue
    fi
    if cmp -s "$ROOT/scripts/$guard" "$target/$guard"; then
      echo "[ok] $repo/scripts/$guard 이미 동일"
    else
      cp "$ROOT/scripts/$guard" "$target/$guard"
      echo "[sync] $repo/scripts/$guard 갱신"
    fi
  done
done

echo "완료. 각 레포에서 node --check 와 테스트를 실행해 확인할 것."
