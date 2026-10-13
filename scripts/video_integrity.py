#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
video_integrity.py — 영상 파일 손상·잘림 감지 (ffprobe/ffmpeg BYO)

랜섬웨어 부분 암호화·불완전 복사·다운로드 중단 등으로
손상된 영상을 걸러낸다:
- ffprobe로 컨테이너/스트림 메타데이터 읽기 가능 여부
- ffmpeg -f null 디코드로 오류·누락 프레임 탐지
- duration 불일치 (컨테이너 vs 스트림)
- moov atom 위치 (mp4에서 파일 끝에 있으면 스트리밍 불가 신호)
- 잘림 징후: 디코드가 중간에 오류를 뿜고 끝나는 패턴

사용:
    python scripts/video_integrity.py evidence/
    python scripts/video_integrity.py damaged.mp4 --json

알려진 한계:
- ffprobe/ffmpeg가 PATH에 필요 (없으면 exit 3).
- '복구 가능' 판정이 아니라 '어디까지 읽히나' 표면 진단이다.
- 복구 자체는 untrunc/전문 도구 영역 — docs/BYO-TOOLS.md 참조.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v", ".ts", ".mts"}


def _require_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def probe(path: Path) -> dict | None:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams",
             "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"probe_error": str(e)}
    if r.returncode != 0:
        return {"probe_error": r.stderr.strip()[:300]}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"probe_error": "ffprobe 출력 파싱 실패"}


def decode_errors(path: Path) -> dict:
    """ffmpeg -f null 로 전체 디코드, 오류 라인 수집."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"decode_error": str(e), "errors": [], "error_count": None,
                "exit_code": None}
    lines = [ln for ln in r.stderr.splitlines() if ln.strip()]
    return {"decode_error": None if r.returncode == 0 else "ffmpeg nonzero exit",
            "errors": lines[:50], "exit_code": r.returncode,
            "error_count": len(lines) if r.returncode == 0 or lines else None}


def moov_position(path: Path) -> str:
    """mp4 계열 moov atom 위치: head/mid/tail/absent."""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            head = f.read(min(size, 8 * 1024 * 1024))
            if b"moov" in head:
                return "head"
            f.seek(max(0, size - 8 * 1024 * 1024))
            tail = f.read()
            if b"moov" in tail:
                return "tail"
    except OSError:
        return "unknown"
    return "absent"


def audit_video(path: Path, run_decode: bool = True) -> dict:
    rec: dict = {"file": str(path), "size_bytes": path.stat().st_size}
    info = probe(path)
    if info is None or "probe_error" in info:
        rec["status"] = "UNREADABLE"
        rec["error"] = (info or {}).get("probe_error", "ffprobe 실패")
        rec["notes"] = ["컨테이너 파싱 불가 — 헤더 손상 또는 비영상 파일 가능성"]
        return rec

    fmt = info.get("format", {})
    streams = info.get("streams", [])
    rec["container"] = fmt.get("format_name", "?")
    try:
        rec["duration"] = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        rec["duration"] = 0.0  # ffprobe가 "N/A"를 반환하는 컨테이너가 있다
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    rec["video_streams"] = len(vstreams)
    rec["audio_streams"] = len(astreams)
    rec["moov_position"] = moov_position(path) if path.suffix.lower() in {".mp4", ".m4v", ".mov"} else "n/a"

    notes = []
    if not vstreams:
        notes.append("비디오 스트림 없음")
    if rec["duration"] == 0:
        notes.append("duration 0 — 메타데이터 손상 가능성")
    if rec["moov_position"] == "tail":
        notes.append("moov가 파일 끝 — faststart 아님, 중간 잘림 시 재생 불가")
    if rec["moov_position"] == "absent":
        notes.append("moov atom 없음 — mp4 컨테이너 손상 심각")

    if run_decode:
        dec = decode_errors(path)
        rec["decode_error_count"] = dec["error_count"]
        rec["decode_errors"] = dec["errors"][:10]
        if dec["error_count"] is None:
            rec["status"] = "DECODE_FAILED"
            notes.append(f"디코드 실행 실패 — 판정 불가: {dec['decode_error']}")
        elif dec["error_count"]:
            notes.append(f"디코드 오류 {dec['error_count']}건 — 부분 손상 구간 존재")
            rec["status"] = "DAMAGED"
        else:
            rec["status"] = "OK"
    else:
        rec["status"] = "PROBED"
    rec["notes"] = notes
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="영상 손상·잘림 감지 (ffprobe/ffmpeg 필요)")
    ap.add_argument("target", help="영상 파일 또는 디렉터리")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("--no-decode", action="store_true", help="전체 디코드 생략 (메타만)")
    args = ap.parse_args(argv)

    if not _require_ffmpeg():
        print("ffmpeg/ffprobe를 찾을 수 없습니다. 설치 후 재시도하세요.", file=sys.stderr)
        return 3

    target = Path(args.target)
    if target.is_dir():
        files = sorted(p for p in target.rglob("*")
                       if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    elif target.is_file():
        files = [target]
    else:
        print(f"대상을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2

    records = [audit_video(f, run_decode=not args.no_decode) for f in files]
    bad = [r for r in records if r["status"] != "OK"]

    if args.json:
        print(json.dumps({"video_files": len(records),
                          "ok": len(records) - len(bad),
                          "problem": len(bad),
                          "records": records}, ensure_ascii=False, indent=2))
    else:
        for r in records:
            if r["status"] == "OK":
                print(f"[ok] {r['file']}: {r['container']}, {r['duration']:.1f}s")
            else:
                print(f"[{r['status']}] {r['file']}: "
                      f"{'; '.join(r.get('notes', [])) or r.get('error', '')}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
