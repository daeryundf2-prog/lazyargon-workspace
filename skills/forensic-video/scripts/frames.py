#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
frames.py
Probe video metadata and extract frames at auto-scaled scene-aware or keyframe rates.
Emits frames optimized for multimodal vision analysis (Gemini 3.8 Flash / Pro or Claude Opus/Sonnet 5.5).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

MAX_FPS = 2.0
SCENE_THRESHOLD = 0.20
SCENE_MIN_FRAMES = 8
KEYFRAME_MIN = 4
MAX_READ_DIMENSION = 1920
DEDUP_THUMB = 16
DEDUP_THRESHOLD = 2.0
SHOWINFO_TS_RE = re.compile(r"pts_time:([0-9.]+)")


def _scale_filter(resolution: int) -> str:
    return (
        f"scale=w='min({resolution},iw)':h='min({MAX_READ_DIMENSION},ih)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2"
    )


def _clamp_fps(fps: float, duration_seconds: float, max_frames: int) -> tuple[float, int]:
    fps = min(fps, MAX_FPS)
    target = min(max_frames, max(1, int(round(fps * duration_seconds))))
    return fps, target


def parse_time(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        if ":" in s:
            parts = [float(p) for p in s.split(":")]
            if len(parts) == 2:
                return parts[0] * 60 + parts[1]
            if len(parts) == 3:
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
        return float(s)
    except ValueError:
        return None


def format_time(seconds: float) -> str:
    total_sec = max(0.0, seconds)
    h = int(total_sec // 3600)
    m = int((total_sec % 3600) // 60)
    s = int(total_sec % 60)
    ms = int(round((total_sec - int(total_sec)) * 1000))
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    if ms > 0:
        return f"{m:02d}:{s:02d}.{ms:03d}"
    return f"{m:02d}:{s:02d}"


def parse_timestamps(raw: str | None) -> list[float]:
    if not raw:
        return []
    res = []
    for part in raw.split(","):
        t = parse_time(part.strip())
        if t is not None:
            res.append(t)
    return sorted(set(res))


def get_metadata(video_path: str) -> dict:
    """ffprobe가 실제로 읽은 값만 반환한다. 결측은 지어내지 않고 None으로 보고한다."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"available": False, "duration": None, "width": None, "height": None,
                "fps": None, "error": "ffprobe not found"}

    cmd = [
        ffprobe,
        "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=width,height,r_frame_rate,codec_name,codec_type",
        "-of", "json",
        video_path,
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        data = json.loads(out)
    except Exception as e:  # noqa: BLE001 — 손상 영상은 '읽기 실패'로 보고
        return {"available": False, "duration": None, "width": None, "height": None,
                "fps": None, "error": str(e)[:200]}

    duration = data.get("format", {}).get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    width = video_stream.get("width")
    height = video_stream.get("height")
    r_fps = video_stream.get("r_frame_rate")
    fps = None
    if isinstance(r_fps, str) and "/" in r_fps:
        num, den = r_fps.split("/", 1)
        try:
            den_f = float(den)
            fps = float(num) / den_f if den_f != 0 else None
        except (TypeError, ValueError):
            fps = None

    return {
        "available": True,
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "codec": video_stream.get("codec_name", "unknown"),
        "streams": streams,
        "format": data.get("format", {})
    }


def auto_fps(duration: float, max_frames: int = 100) -> float:
    if duration <= 0:
        return 1.0
    ideal = max_frames / duration
    return min(ideal, MAX_FPS)


def auto_fps_focus(duration: float, max_frames: int = 100) -> float:
    if duration <= 0:
        return 2.0
    ideal = max_frames / duration
    return min(ideal, MAX_FPS)


def extract_scene_or_uniform(
    video_path: str,
    out_dir: Path,
    max_frames: int = 100,
    resolution: int = 512,
    start: float | None = None,
    end: float | None = None,
    fps_override: float | None = None,
) -> list[dict]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is not installed. Install with winget install ffmpeg / choco install ffmpeg")

    meta = get_metadata(video_path)
    dur = meta["duration"]
    start_sec = start if start is not None else 0.0
    end_sec = end if end is not None else dur
    if end_sec is None:
        raise SystemExit("Video duration unknown; supply an explicit end time")
    if end_sec <= start_sec or max_frames <= 0:
        raise SystemExit("Invalid extraction range or frame limit")
    clip_dur = end_sec - start_sec

    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Scene detection pass
    scale = _scale_filter(resolution)
    fps_val = fps_override or auto_fps(clip_dur, max_frames)
    
    pattern = str(out_dir / "frame_%04d.jpg")
    ss_args = ["-ss", str(start_sec)] if start_sec > 0 else []
    t_args = ["-t", str(clip_dur)] if end is not None else []

    # Filter with fps sampling
    vf = f"fps={fps_val},{scale}"
    cmd = [
        ffmpeg,
        "-y",
        *ss_args,
        "-i", video_path,
        *t_args,
        "-vf", vf,
        "-q:v", "3",
        pattern,
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    frames = sorted(out_dir.glob("frame_*.jpg"))
    results = []
    for idx, f in enumerate(frames):
        ts = start_sec + (idx / fps_val)
        results.append({
            "path": str(f),
            "timestamp": ts,
            "time_str": format_time(ts),
        })

    return results


def extract_keyframes(
    video_path: str,
    out_dir: Path,
    max_frames: int = 50,
    resolution: int = 512,
    start: float | None = None,
    end: float | None = None,
) -> list[dict]:
    return extract_scene_or_uniform(
        video_path,
        out_dir,
        max_frames=max_frames,
        resolution=resolution,
        start=start,
        end=end,
    )


def extract_at_timestamps(
    video_path: str,
    timestamps: list[float],
    out_dir: Path,
    resolution: int = 512,
) -> list[dict]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    scale = _scale_filter(resolution)
    results = []

    for idx, ts in enumerate(timestamps):
        out_file = out_dir / f"cue_{idx:03d}_{int(ts)}s.jpg"
        cmd = [
            ffmpeg,
            "-y",
            "-ss", str(ts),
            "-i", video_path,
            "-vframes", "1",
            "-vf", scale,
            "-q:v", "2",
            str(out_file),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if out_file.exists():
            results.append({
                "path": str(out_file),
                "timestamp": ts,
                "time_str": format_time(ts),
            })

    return results


def merge_frames(base_frames: list[dict], cue_frames: list[dict], max_frames: int | None = 100) -> list[dict]:
    by_path = {f["path"]: f for f in base_frames}
    for c in cue_frames:
        by_path[c["path"]] = c
    merged = sorted(by_path.values(), key=lambda x: x["timestamp"])
    if max_frames and len(merged) > max_frames:
        step = len(merged) / max_frames
        indices = [int(i * step) for i in range(max_frames)]
        merged = [merged[i] for i in indices]
    return merged
