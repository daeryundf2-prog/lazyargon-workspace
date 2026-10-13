#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dedup_files.py — 중복 파일 탐지 (정확 중복 + 유사 이미지 그룹)

같은 증거가 여러 경로에 존재하는 패턴을 잡는다.
- 1단계: SHA-256 정확 중복 (내용이 바이트 단위로 같음)
- 2단계: Pillow가 있으면 이미지끼리 지각 해시 근접 그룹 (재압축·리사이즈본)

사용:
    python scripts/dedup_files.py evidence/
    python scripts/dedup_files.py evidence/ --json
    python scripts/dedup_files.py evidence/ --no-similar   # 정확 중복만

알려진 한계:
- 유사 그룹은 이미지만다. 문서 근사 중복(내용 일부 수정)은 못 잡는다.
- '어느 쪽이 원본인가'는 판정하지 않는다 — 그룹만 묶는다.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def exact_dups(files: list[Path]) -> list[dict]:
    by_size = {}
    for f in files:
        try:
            if f.is_file():
                by_size.setdefault(f.stat().st_size, []).append(f)
        except OSError as exc:
            print(f"[SKIP] {f}: {exc}", file=sys.stderr)
    by_hash: dict[str, list[str]] = {}
    for candidates in by_size.values():
        if len(candidates) < 2:
            continue
        for f in candidates:
            try:
                by_hash.setdefault(sha256_file(f), []).append(str(f))
            except OSError as exc:
                print(f"[SKIP] {f}: {exc}", file=sys.stderr)
    return [{"sha256": h, "files": paths} for h, paths in by_hash.items() if len(paths) > 1]


def similar_image_groups(root: Path) -> list[dict]:
    """image_similarity.py가 있고 Pillow가 있을 때만 동작."""
    spec = importlib.util.spec_from_file_location(
        "image_similarity", Path(__file__).resolve().parent / "image_similarity.py")
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    Image = mod._require_pillow()
    if Image is None:
        return []
    records = mod.scan_dir(root, Image)
    pairs = mod.find_pairs(records, 10)
    # 유사 쌍을 그룹으로 묶는다 (union-find 없이 단순 연결)
    groups: list[set[str]] = []
    for p in pairs:
        joined = False
        for g in groups:
            if p["a"] in g or p["b"] in g:
                g.update([p["a"], p["b"]])
                joined = True
                break
        if not joined:
            groups.append({p["a"], p["b"]})
    return [{"files": sorted(g)} for g in groups]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="중복 파일 탐지 (정확 중복 + 유사 이미지)")
    ap.add_argument("target", help="스캔할 디렉터리")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("--no-similar", action="store_true", help="유사 이미지 그룹 생략")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if not target.is_dir():
        print(f"디렉터리를 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2

    files = [p for p in sorted(target.rglob("*")) if p.is_file()
             and "__pycache__" not in p.parts]
    exact = exact_dups(files)
    similar = [] if args.no_similar else similar_image_groups(target)

    report = {
        "files_scanned": len(files),
        "exact_duplicate_groups": len(exact),
        "exact_duplicates": exact,
        "similar_image_groups": len(similar),
        "similar_images": similar,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{len(files)}개 파일: 정확 중복 {len(exact)}그룹, 유사 이미지 {len(similar)}그룹")
        for g in exact:
            print(f"  [중복 sha256:{g['sha256'][:12]}…] " + "  ↔  ".join(g["files"]))
        for g in similar:
            print("  [유사] " + "  ↔  ".join(g["files"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
