#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
forensic_video_audit.py
Forensic Video Metadata & Frame Integrity Auditor for Daeryun Law Forensic Center.
Extracts QuickTime/MP4 container creation time, camera device info, frame count, audio sample rate, and integrity hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def compute_sha256(filepath: str) -> str:
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def audit_video_file(filepath: str) -> dict:
    p = Path(filepath).resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    ffprobe = shutil.which("ffprobe")
    probe_data = {}
    if ffprobe:
        cmd = [
            ffprobe,
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-of", "json",
            str(p),
        ]
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
            probe_data = json.loads(out)
        except Exception as e:
            probe_data = {"error": str(e)}

    fmt = probe_data.get("format", {})
    tags = fmt.get("tags", {})
    creation_time = tags.get("creation_time") or tags.get("date") or "N/A"
    encoder = tags.get("encoder") or tags.get("compatible_brands") or "N/A"
    duration = float(fmt.get("duration", 0.0))
    size_bytes = p.stat().st_size

    streams = probe_data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

    file_stat = p.stat()
    # st_ctime 은 Windows 에선 대체로 생성시각이지만 POSIX 에선 inode 메타데이터 변경시각이다
    # (audit_timestamps.py 의 ctime_semantics 기준과 일치)
    ctime_semantics = "Windows creation time" if os.name == "nt" else "POSIX inode metadata change time; not file creation"
    fs_created = datetime.fromtimestamp(file_stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
    fs_modified = datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    sha256_val = compute_sha256(str(p))

    return {
        "file_name": p.name,
        "file_path": str(p),
        "file_size": size_bytes,
        "sha256": sha256_val,
        "fs_created": fs_created,
        "ctime_semantics": ctime_semantics,
        "fs_modified": fs_modified,
        "container_creation_time": creation_time,
        "encoder_brand": encoder,
        "duration_sec": duration,
        "video": {
            "codec": video_stream.get("codec_name"),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "fps": video_stream.get("r_frame_rate"),
            "frames": video_stream.get("nb_frames") or "N/A",
        },
        "audio": {
            "codec": audio_stream.get("codec_name") if audio_stream else "None",
            "channels": audio_stream.get("channels") if audio_stream else 0,
            "sample_rate": audio_stream.get("sample_rate") if audio_stream else "None",
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Forensic Video Metadata & Integrity Auditor")
    parser.add_argument("video", help="Target video file (.mp4, .mov, .avi, etc.)")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    result = audit_video_file(args.video)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("=" * 70)
    print("  동영상 컨테이너 태그 / 파일 해시 (ffprobe + os.stat)")
    print("=" * 70)
    print(f"  파일명             : {result['file_name']}")
    print(f"  파일 크기          : {result['file_size']:,} Bytes")
    print(f"  SHA-256            : {result['sha256']}")
    print("-" * 70)
    print(f"  파일시스템 생성일시 : {result['fs_created']} ({result.get('ctime_semantics', '')})")
    print(f"  파일시스템 수정일시 : {result['fs_modified']}")
    print(f"  컨테이너 태그 시각  : {result['container_creation_time']}")
    print(f"  인코더/브랜드 태그  : {result['encoder_brand']}")
    print("-" * 70)
    print(f"  재생 시간          : {result['duration_sec']:.2f} 초")
    print(f"  비디오 사양        : {result['video']['width']}x{result['video']['height']} | {result['video']['codec']} | FPS: {result['video']['fps']}")
    print(f"  오디오 사양        : {result['audio']['codec']} ({result['audio']['channels']} ch, {result['audio']['sample_rate']} Hz)")
    print("-" * 70)
    print("  [한계] 컨테이너 태그는 촬영 시각의 법정 증명이 아니다. 로컬 시각은 타임존 미변환.")
    print("=" * 70)


if __name__ == "__main__":
    main()
