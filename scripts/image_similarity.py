#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
image_similarity.py — 지각 해시(pHash/aHash/dHash) 기반 유사 이미지 검색

"해당 사진이 있는가"를 파일명이 아니라 내용으로 찾는다.
리사이즈·재압축·가벼운 크롭이 가해진 같은 사진도 해밍 거리로 잡는다.
Pillow가 없으면 실행하지 않고 exit 3 + 안내로 종료한다(fail-closed).

사용:
    python scripts/image_similarity.py evidence/                      # 전수 유사쌍 스캔
    python scripts/image_similarity.py evidence/ --query suspect.jpg  # 쿼리 이미지 매칭
    python scripts/image_similarity.py evidence/ --threshold 10 --json

거리 해석 (64비트 해시 기준):
    0       = 동일 이미지
    <= 5    = 사실상 동일 (재인코딩 수준 차이)
    <= 10   = 높은 유사 (리사이즈·가벼운 편집)
    > 10    = 다른 이미지로 간주

매칭은 pHash 거리와 색 히스토그램 거리를 함께 요구한다 — 단색 이미지처럼
지각 해시가 퇴화(전부 같은 비트열)하는 케이스는 색 분포로 구분한다.

알려진 한계:
- 지각 해시는 강한 크롭·회전·색반전에는 약하다. 매칭 실패는 '없음'이 아니라
  '해시 근접 없음'으로만 보고할 것.
- pHash는 DCT 기반이라 aHash/dHash보다 느리지만 편집 내성이 높다.
"""
from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".tif"}


def _require_pillow():
    try:
        from PIL import Image  # type: ignore
        return Image
    except ImportError:
        print(
            "Pillow가 없어 지각 해시를 계산할 수 없습니다.\n"
            "  pip install 'pillow>=10.0,<12'",
            file=sys.stderr,
        )
        return None


def _pixels(img):
    if hasattr(img, "get_flattened_data"):
        return img.get_flattened_data()
    return img.getdata()


def _to_gray64(img) -> list:
    """8x8 그레이스케일 픽셀 리스트."""
    small = img.convert("L").resize((8, 8))
    return list(_pixels(small))


def ahash(img) -> int:
    px = _to_gray64(img)
    avg = sum(px) / len(px)
    bits = 0
    for v in px:
        bits = (bits << 1) | (1 if v > avg else 0)
    return bits


def dhash(img) -> int:
    """인접 픽셀 밝기 비교 (9x8로 리사이즈 후 행별 비교)."""
    small = img.convert("L").resize((9, 8))
    px = list(_pixels(small))
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
    return bits


def phash(img) -> int:
    """32x32 그레이스케일 → DCT → 저주파 8x8의 중앙값 비교. numpy 없으면 aHash 폴백."""
    try:
        import numpy as np  # type: ignore
        from scipy.fftpack import dct  # type: ignore
    except ImportError:
        try:
            import numpy as np  # type: ignore
        except ImportError:
            return ahash(img)
        # numpy만 있으면 DCT를 직접 계산한다
        arr = np.asarray(img.convert("L").resize((32, 32)), dtype=float)
        d = _dct2d(arr)
        return _dct_hash(d)
    arr = np.asarray(img.convert("L").resize((32, 32)), dtype=float)
    d = dct(dct(arr, axis=0), axis=1)
    return _dct_hash(d)


def _dct2d(arr):
    """numpy만으로 2D DCT-II를 계산한다 (scipy 없을 때)."""
    import numpy as np

    n = arr.shape[0]
    k = np.arange(n)
    basis = np.cos(np.pi * (k[:, None] + 0.5) * k[None, :] / n)
    return basis.T @ arr @ basis


def _dct_hash(d):
    import numpy as np

    low = d[:8, :8]
    med = np.median(low)
    bits = 0
    for v in low.flatten():
        bits = (bits << 1) | (1 if v > med else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def colorhist(img) -> list[float]:
    """4x4x4 = 64bin 정규화 RGB 히스토그램. 단색 이미지 구분용 보조 신호."""
    small = img.convert("RGB").resize((16, 16))
    hist = [0.0] * 64
    for r, g, b in _pixels(small):
        hist[(r >> 6) * 16 + (g >> 6) * 4 + (b >> 6)] += 1.0
    total = sum(hist) or 1.0
    return [v / total for v in hist]


def hist_distance(a: list[float], b: list[float]) -> float:
    """L1 거리/2 → 0(동일)..1(완전 상이)."""
    return sum(abs(x - y) for x, y in zip(a, b)) / 2.0


def hash_file(path: Path, Image) -> dict | None:
    try:
        with Image.open(path) as img:
            return {
                "file": str(path),
                "ahash": ahash(img),
                "dhash": dhash(img),
                "phash": phash(img),
                "colorhist": colorhist(img),
            }
    except Exception as e:  # noqa: BLE001 — 손상 이미지는 건너뛰고 기록
        print(f"[SKIP] {path}: {e}", file=sys.stderr)
        return None


def scan_dir(target: Path, Image) -> list[dict]:
    files = sorted(p for p in target.rglob("*") if p.suffix.lower() in IMG_EXTS)
    records = []
    for f in files:
        r = hash_file(f, Image)
        if r:
            records.append(r)
    return records


COLORHIST_MAX = 0.25  # 색 분포가 이 이상 다르면 pHash가 가까워도 다른 이미지로 본다


def _candidate_pairs(records: list[dict], threshold: int):
    if type(threshold) is not int or not 0 <= threshold <= 64:
        raise ValueError("threshold must be an integer in 0..64")
    if any(type(r["phash"]) is not int or not 0 <= r["phash"] < (1 << 64) for r in records):
        raise ValueError("Expected unsigned 64-bit perceptual hashes")
    if threshold >= 16:
        yield from combinations(range(len(records)), 2)
        return
    blocks = threshold + 1
    bounds = [(64 * b // blocks, 64 * (b + 1) // blocks) for b in range(blocks)]
    buckets = [{} for _ in bounds]
    for i in range(len(records) - 1, -1, -1):
        value = records[i]["phash"]
        candidates = set()
        for bucket, (lo, hi) in zip(buckets, bounds):
            part = (value >> lo) & ((1 << (hi - lo)) - 1)
            candidates.update(bucket.get(part, ()))
            bucket.setdefault(part, []).append(i)
        for j in sorted(candidates):
            yield i, j


def find_pairs(records: list[dict], threshold: int) -> list[dict]:
    pairs = []
    for a, b in _candidate_pairs(records, threshold):
        ra, rb = records[a], records[b]
        dist = hamming(ra["phash"], rb["phash"])
        if dist > threshold:
            continue
        hdist = hist_distance(ra["colorhist"], rb["colorhist"])
        if hdist <= COLORHIST_MAX:
            pairs.append({
                "a": ra["file"], "b": rb["file"], "phash_dist": dist,
                "ahash_dist": hamming(ra["ahash"], rb["ahash"]),
                "dhash_dist": hamming(ra["dhash"], rb["dhash"]),
                "color_dist": round(hdist, 3),
            })
    return sorted(pairs, key=lambda x: x["phash_dist"])


def find_matches(query: dict, records: list[dict], threshold: int) -> list[dict]:
    matches = []
    for r in records:
        dist = hamming(query["phash"], r["phash"])
        hdist = hist_distance(query["colorhist"], r["colorhist"])
        if dist <= threshold and hdist <= COLORHIST_MAX:
            matches.append({
                "file": r["file"], "phash_dist": dist,
                "ahash_dist": hamming(query["ahash"], r["ahash"]),
                "dhash_dist": hamming(query["dhash"], r["dhash"]),
                "color_dist": round(hdist, 3),
            })
    return sorted(matches, key=lambda x: x["phash_dist"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="지각 해시 기반 유사 이미지 검색 (로컬 전용)")
    ap.add_argument("target", help="스캔할 디렉터리")
    ap.add_argument("--query", default=None, help="찾을 기준 이미지 경로")
    ap.add_argument("--threshold", type=int, default=10, help="pHash 해밍 거리 임계값 (기본 10)")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args(argv)

    Image = _require_pillow()
    if Image is None:
        return 3

    target = Path(args.target)
    if not target.is_dir():
        print(f"디렉터리를 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2

    records = scan_dir(target, Image)
    if not records:
        print(f"이미지 파일이 없습니다: {target}", file=sys.stderr)
        return 2

    result: dict = {"image_count": len(records), "threshold": args.threshold}
    if args.query:
        q = hash_file(Path(args.query), Image)
        if q is None:
            print(f"쿼리 이미지를 읽을 수 없습니다: {args.query}", file=sys.stderr)
            return 2
        matches = [m for m in find_matches(q, records, args.threshold) if m["file"] != str(Path(args.query))]
        result["query"] = args.query
        result["matches"] = matches
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if matches:
                for m in matches:
                    print(f"pHash dist={m['phash_dist']:2d}  {m['file']}")
            else:
                print(f"유사 이미지 없음 (pHash 거리 ≤ {args.threshold} 기준, {len(records)}개 스캔)")
        return 0

    pairs = find_pairs(records, args.threshold)
    result["similar_pairs"] = pairs
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{len(records)}개 이미지 스캔, 유사 쌍 {len(pairs)}건 (pHash 거리 ≤ {args.threshold})")
        for p in pairs:
            print(f"  dist={p['phash_dist']:2d}  {p['a']}  ↔  {p['b']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
