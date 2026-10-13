#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_fingerprint.py — 오디오 내용 지문·중복 탐지 (chromaprint fpcalc BYO)

같은 녹음이 다른 파일명/포맷/비트레이트로 섞여 들어오는 경우를 잡는다.
dedup_files.py의 SHA-256은 바이트 단위라 재인코딩본을 못 잡고,
이 도구는 '소리 내용'의 지문(chromaprint)을 비교한다.

- fpcalc -raw 로 int32 지문 배열 추출
- 두 지문의 해밍 유사도로 유사 쌍 판정
- fpcalc 없으면 exit 3 (지어내지 않음)

사용:
    python scripts/audio_fingerprint.py audio/
    python scripts/audio_fingerprint.py a.mp3 --compare b.wav
    python scripts/audio_fingerprint.py audio/ --json

설치:
    brew install chromaprint     # fpcalc 포함
    apt install libchromaprint-tools

알려진 한계:
- 재인코딩·포맷 변환은 잡지만, 편집(앞뒤 자름)된 구간 일치는 못 잡는다.
- 유사도는 '내용 근접' 신호다 — 동일 녹취 판정은 사람이 원본 대조로 한다.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from itertools import combinations
from pathlib import Path

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac",
              ".mp4", ".mkv", ".mov", ".webm"}
DEFAULT_THRESHOLD = 0.85


def _require_fpcalc() -> bool:
    return shutil.which("fpcalc") is not None


def fingerprint(path: Path) -> dict:
    """fpcalc -raw로 정수 지문 배열을 추출한다."""
    try:
        r = subprocess.run(
            ["fpcalc", "-raw", "-json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"fpcalc 실패: {e}") from e
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300] or "fpcalc nonzero exit")
    data = json.loads(r.stdout)
    return {"file": str(path), "duration": data.get("duration", 0),
            "fingerprint": data.get("fingerprint", [])}


def hamming_similarity(a: list[int], b: list[int]) -> float:
    """int32 지문 배열의 비트 해밍 유사도 (길이가 다르면 짧은 쪽 기준)."""
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    same = sum(1 for i in range(n) if bin(a[i] ^ b[i]).count("1") <= 8)
    # 지문은 프레임 단위 int32 — 프레임 단위 근사 일치율로 환산
    return same / n


def find_pairs(records: list[dict], threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    pairs = []
    for x, y in combinations(records, 2):
        sim = hamming_similarity(x["fingerprint"], y["fingerprint"])
        if sim >= threshold:
            pairs.append({"a": x["file"], "b": y["file"],
                          "similarity": round(sim, 3),
                          "duration_diff": round(abs(x["duration"] - y["duration"]), 2)})
    return pairs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="오디오 내용 지문 비교 (fpcalc 필요)")
    ap.add_argument("target", help="오디오 파일 또는 디렉터리")
    ap.add_argument("--compare", default=None, help="대상 파일과 비교할 파일")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args(argv)

    if not _require_fpcalc():
        print("fpcalc(chromaprint)를 찾을 수 없습니다. "
              "brew install chromaprint 후 재시도하세요.", file=sys.stderr)
        return 3

    target = Path(args.target)
    if target.is_dir():
        files = sorted(p for p in target.rglob("*")
                       if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
    elif target.is_file():
        files = [target]
    else:
        print(f"대상을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2

    records = []
    for f in files:
        try:
            records.append(fingerprint(f))
        except RuntimeError as e:
            print(f"[FAIL] {f}: {e}", file=sys.stderr)

    if args.compare:
        other = fingerprint(Path(args.compare))
        sims = [{"file": r["file"], "similarity": round(hamming_similarity(
            r["fingerprint"], other["fingerprint"]), 3)} for r in records]
        if args.json:
            print(json.dumps({"against": args.compare, "results": sims},
                             ensure_ascii=False, indent=2))
        else:
            for s in sorted(sims, key=lambda x: -x["similarity"]):
                print(f"{s['similarity']:.3f}  {s['file']}")
        return 0

    pairs = find_pairs(records, args.threshold)
    if args.json:
        print(json.dumps({"files": len(records), "similar_pairs": pairs},
                         ensure_ascii=False, indent=2))
    else:
        print(f"{len(records)}개 오디오, 유사 쌍 {len(pairs)}건 (임계 {args.threshold})")
        for p in pairs:
            print(f"  {p['similarity']:.3f}  {p['a']}  ↔  {p['b']}  (길이차 {p['duration_diff']}s)")
    return 1 if pairs else 0


if __name__ == "__main__":
    sys.exit(main())
