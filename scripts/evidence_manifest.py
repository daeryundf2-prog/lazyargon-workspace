#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evidence_manifest.py — 증거 매니페스트 생성기 (chain-of-custody 초안)

증거 디렉터리를 통째로 해시하고, 각 파일의 표면 메타데이터와 함께
도구 버전·생성 시각을 하나의 매니페스트로 고정한다.
이후 감사에서 같은 명령을 다시 돌려 파일 집합·해시가 그대로인지 대조한다.

사용:
    python scripts/evidence_manifest.py evidence/ -o manifest.json
    python scripts/evidence_manifest.py evidence/ --verify manifest.json

출력 필드:
    - file / sha256 / size / mtime (표면값 — $MFT 수준 검증 아님)
    - tool: 스크립트 버전, python 버전, 생성 시각(KST)

알려진 한계:
- os.stat 표면 메타데이터만 기록한다. 타임스탬핑 위조(timestomping)는
  이 도구로 판정할 수 없다.
- '무결성 보장'이 아니라 '변경 탐지'다. 원본 보존은 별도 읽기전용
  조치(scripts/lock_evidence.sh)와 병행할 것.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
TOOL_VERSION = "1.0.4"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root: Path) -> dict:
    files = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        st = f.stat()
        files.append({
            "path": str(f.relative_to(root)),
            "sha256": sha256_file(f),
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, KST).isoformat(),
        })
    return {
        "manifest_version": 1,
        "tool": f"evidence_manifest.py v{TOOL_VERSION}",
        "python": platform.python_version(),
        "generated_at": datetime.now(KST).isoformat(),
        "root": str(root.resolve()),
        "file_count": len(files),
        "files": files,
    }


def verify_manifest(root: Path, manifest: dict) -> list[str]:
    problems = []
    recorded_root = manifest.get("root")
    if recorded_root and str(Path(recorded_root)) != str(root.resolve()):
        # 불일치로 세지 않고 경고만 — 다른 경로로 옮긴 사본을 대조하는 정상 사용도 있다.
        print(f"경고: 매니페스트 기록 루트({recorded_root})가 검증 대상({root.resolve()})과 "
              "다릅니다 — 다른 위치로 옮겨졌거나 다른 디렉터리의 매니페스트일 수 있습니다",
              file=sys.stderr)
    recorded = {e["path"]: e for e in manifest.get("files", [])}
    current = {str(f.relative_to(root)): f for f in root.rglob("*")
               if f.is_file() and "__pycache__" not in f.parts}

    for path in sorted(set(recorded) - set(current)):
        problems.append(f"MISSING: {path}")
    for path in sorted(set(current) - set(recorded)):
        problems.append(f"NEW: {path}")
    for path in sorted(set(recorded) & set(current)):
        digest = sha256_file(current[path])
        if digest != recorded[path]["sha256"]:
            problems.append(f"CHANGED: {path}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="증거 매니페스트 생성·대조 (로컬 전용)")
    ap.add_argument("root", help="증거 디렉터리")
    ap.add_argument("-o", "--output", default=None, help="매니페스트 출력 경로")
    ap.add_argument("--verify", metavar="MANIFEST", default=None,
                    help="기존 매니페스트와 대조")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"디렉터리를 찾을 수 없습니다: {root}", file=sys.stderr)
        return 2

    if args.verify:
        try:
            manifest = json.loads(Path(args.verify).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"매니페스트를 읽을 수 없습니다: {e}", file=sys.stderr)
            return 2
        problems = verify_manifest(root, manifest)
        if problems:
            print(f"불일치 {len(problems)}건:")
            for p in problems:
                print(f"  {p}")
            return 1
        print(f"일치 — {manifest.get('file_count', '?')}개 파일 모두 해시 동일")
        return 0

    manifest = build_manifest(root)
    out = json.dumps(manifest, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"매니페스트 → {args.output} ({manifest['file_count']}개 파일)")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
