#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
video_fingerprint.py — 프레임 해시 기반 영상 지문(fingerprint) 매칭

"해당 영상이 있는가"를 파일명·메타데이터가 아니라 내용으로 찾는다.
영상을 균등 간격으로 샘플링해 각 프레임의 지각 해시를 만들고,
두 영상의 해시 시퀀스 유사도로 동일/재인코딩/부분 일치를 판정한다.
모든 처리는 로컬에서만 일어난다. ffmpeg/ffprobe가 없으면 exit 3(fail-closed).

사용:
    python scripts/video_fingerprint.py clip.mp4                      # 지문 출력
    python scripts/video_fingerprint.py a.mp4 --compare b.mp4         # 두 영상 비교
    python scripts/video_fingerprint.py query.mp4 --scan evidence/    # 디렉터리에서 매칭
    python scripts/video_fingerprint.py query.mp4 --scan dir/ --json

유사도 해석:
    >= 0.90 = 사실상 동일 (재인코딩·해상도 차이 수준)
    >= 0.70 = 높은 유사 (일부 편집·재업로드 가능성)
    >= 0.40 = 부분 일치 가능 (인간 검토 권장)
    <  0.40 = 다른 영상으로 간주

알려진 한계:
- 강한 크롭·속도 변경·편집된 영상은 프레임 정렬이 어긋나 유사도가 낮아진다.
  낮은 유사도는 '없음'이 아니라 '지문 불일치'로만 보고할 것.
- 오디오 지문(chromaprint 등)은 비교하지 않는다. 화면 내용 기준이다.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v", ".ts", ".mts"}
DEFAULT_SAMPLES = 16


def _require_ffmpeg() -> bool:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print(
            "ffmpeg/ffprobe가 없어 영상 지문을 만들 수 없습니다.\n"
            "  macOS: brew install ffmpeg\n"
            "  Windows: winget install Gyan.FFmpeg",
            file=sys.stderr,
        )
        return False
    return True


def probe(path: Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,size:stream=codec_name,width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr.strip()[:200]}")
    data = json.loads(proc.stdout or "{}")
    fmt = data.get("format", {})
    stream = next((s for s in data.get("streams", []) if s.get("width")), {})
    return {
        "duration": float(fmt.get("duration", 0) or 0),
        "size": int(fmt.get("size", 0) or 0),
        "codec": stream.get("codec_name", "unknown"),
        "width": stream.get("width", 0),
        "height": stream.get("height", 0),
    }


def _frame_ahash(gray8x8: bytes) -> int:
    px = list(gray8x8)
    avg = sum(px) / len(px)
    bits = 0
    for v in px:
        bits = (bits << 1) | (1 if v > avg else 0)
    return bits


def fingerprint(path: Path, samples: int = DEFAULT_SAMPLES) -> dict:
    """균등 간격 프레임의 aHash 시퀀스 + 컨테이너 메타데이터."""
    meta = probe(path)
    duration = meta["duration"]
    if duration <= 0:
        raise RuntimeError("duration을 읽을 수 없습니다")

    hashes = []
    with tempfile.TemporaryDirectory() as tmp:
        # 균등 간격으로 fps = samples/duration 셈플링 후 8x8 그레이 raw로 읽는다
        fps = samples / duration
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path),
             "-vf", f"fps={fps},scale=8:8,format=gray",
             "-f", "rawvideo", "-"],
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg frame extraction failed: {proc.stderr.decode(errors='replace')[:200]}")
        raw = proc.stdout
        frame_len = 64
        for i in range(0, len(raw) - frame_len + 1, frame_len):
            hashes.append(_frame_ahash(raw[i:i + frame_len]))

    if not hashes:
        raise RuntimeError("샘플 프레임을 추출하지 못했습니다 (영상 스트림 없음?)")

    return {
        "file": str(path),
        "duration": round(duration, 2),
        "codec": meta["codec"],
        "width": meta["width"],
        "height": meta["height"],
        "frame_hashes": hashes,
        "sample_count": len(hashes),
    }


def similarity(fp_a: dict, fp_b: dict) -> dict:
    """해시 시퀀스의 위치별 해밍 거리 → 유사도 0..1."""
    ha, hb = fp_a["frame_hashes"], fp_b["frame_hashes"]
    n = min(len(ha), len(hb))
    if n == 0:
        return {"similarity": 0.0, "matched_frames": 0, "compared_frames": 0}
    matched = sum(1 for i in range(n) if bin(ha[i] ^ hb[i]).count("1") <= 5)
    sim = matched / n
    return {
        "similarity": round(sim, 3),
        "matched_frames": matched,
        "compared_frames": n,
        "duration_a": fp_a["duration"],
        "duration_b": fp_b["duration"],
        "duration_diff": round(abs(fp_a["duration"] - fp_b["duration"]), 2),
    }


def verdict(sim: float) -> str:
    if sim >= 0.90:
        return "사실상 동일 (재인코딩 수준)"
    if sim >= 0.70:
        return "높은 유사 (편집·재업로드 가능)"
    if sim >= 0.40:
        return "부분 일치 가능 (인간 검토 권장)"
    return "지문 불일치"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="프레임 해시 기반 영상 지문 매칭 (로컬 전용)")
    ap.add_argument("input", help="기준 영상 파일")
    ap.add_argument("--compare", default=None, help="비교할 영상 파일")
    ap.add_argument("--scan", default=None, help="매칭 대상 디렉터리")
    ap.add_argument("--samples", type=int, default=DEFAULT_SAMPLES, help="샘플 프레임 수 (기본 16)")
    ap.add_argument("--threshold", type=float, default=0.40, help="유사도 보고 임계값 (기본 0.40)")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args(argv)

    if not _require_ffmpeg():
        return 3

    src = Path(args.input)
    if not src.is_file():
        print(f"영상을 찾을 수 없습니다: {src}", file=sys.stderr)
        return 2

    try:
        fp_src = fingerprint(src, args.samples)
    except RuntimeError as e:
        print(f"지문 생성 실패: {e}", file=sys.stderr)
        return 2

    if args.compare:
        other = Path(args.compare)
        try:
            fp_b = fingerprint(other, args.samples)
        except RuntimeError as e:
            print(f"비교 대상 지문 생성 실패: {e}", file=sys.stderr)
            return 2
        s = similarity(fp_src, fp_b)
        out = {"a": str(src), "b": str(other), **s, "verdict": verdict(s["similarity"])}
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(f"유사도 {s['similarity']:.3f} ({s['matched_frames']}/{s['compared_frames']} 프레임 일치, "
                  f"길이차 {s['duration_diff']}s) — {out['verdict']}")
        return 0

    if args.scan:
        scan_dir = Path(args.scan)
        if not scan_dir.is_dir():
            print(f"디렉터리를 찾을 수 없습니다: {scan_dir}", file=sys.stderr)
            return 2
        videos = sorted(p for p in scan_dir.rglob("*")
                        if p.suffix.lower() in VIDEO_EXTS and p.resolve() != src.resolve())
        results = []
        for v in videos:
            try:
                fp_v = fingerprint(v, args.samples)
                s = similarity(fp_src, fp_v)
                if s["similarity"] >= args.threshold:
                    results.append({"file": str(v), **s, "verdict": verdict(s["similarity"])})
            except RuntimeError as e:
                print(f"[SKIP] {v}: {e}", file=sys.stderr)
        results.sort(key=lambda x: -x["similarity"])
        if args.json:
            print(json.dumps({"query": str(src), "scanned": len(videos), "matches": results},
                             ensure_ascii=False, indent=2))
        else:
            if results:
                for r in results:
                    print(f"{r['similarity']:.3f}  {r['verdict']}  {r['file']}")
            else:
                print(f"유사 영상 없음 (유사도 ≥ {args.threshold} 기준, {len(videos)}개 스캔)")
        return 0

    # 비교/스캔 없으면 지문 자체를 출력한다
    fp_out = {**fp_src, "frame_hashes": [format(h, "016x") for h in fp_src["frame_hashes"]]}
    print(json.dumps(fp_out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
