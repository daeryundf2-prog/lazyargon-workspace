#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download.py
Download video via yt-dlp, or resolve a local file path.
Supports Korean and English subtitles (VTT/SRT).
Smart resolver finds yt-dlp in PATH, python Scripts dir, or python -m yt_dlp.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".wmv", ".ts", ".m2ts"}


def get_ytdlp_cmd() -> list[str] | None:
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    py_scripts_ytdlp = Path(sys.executable).parent / "Scripts" / "yt-dlp.exe"
    if py_scripts_ytdlp.exists():
        return [str(py_scripts_ytdlp)]
    try:
        res = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        pass
    return None


def is_url(source: str) -> bool:
    if source.startswith("-"):
        return False
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def resolve_local(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"File not found: {p}")
    if p.suffix.lower() not in VIDEO_EXTS:
        print(
            f"[forensic-video] warning: {p.suffix} is not a common video extension, proceeding anyway",
            file=sys.stderr,
        )
    return {
        "video_path": str(p),
        "subtitle_path": None,
        "info": {"title": p.name, "url": str(p)},
        "downloaded": False,
    }


def _pick_subtitle(out_dir: Path) -> Path | None:
    candidates = sorted(out_dir.glob("video*.vtt"))
    if not candidates:
        candidates = sorted(out_dir.glob("video*.srt"))
    if not candidates:
        return None
    preferred = [
        c for c in candidates
        if any(marker in c.name.lower() for marker in (".ko.", ".ko-kr.", ".ko-orig."))
    ]
    if preferred:
        return preferred[0]
    en_candidates = [
        c for c in candidates
        if any(marker in c.name.lower() for marker in (".en.", ".en-us.", ".en-gb.", ".en-orig."))
    ]
    return en_candidates[0] if en_candidates else candidates[0]


def _pick_video(out_dir: Path) -> Path | None:
    for ext in (".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".opus", ".avi"):
        for candidate in out_dir.glob(f"video*{ext}"):
            return candidate
    for candidate in out_dir.glob("video.*"):
        if candidate.suffix.lower() in VIDEO_EXTS:
            return candidate
    return None


def fetch_captions(url: str, out_dir: Path) -> dict:
    ytdlp = get_ytdlp_cmd()
    if not ytdlp:
        return {
            "video_path": None,
            "subtitle_path": None,
            "info": {"url": url},
            "downloaded": False,
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "video.%(ext)s")
    cmd = [
        *ytdlp,
        "--skip-download",
        "--write-info-json",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "ko.*,en.*",
        "--sub-format", "vtt/srt/best",
        "--convert-subs", "vtt",
        "--no-playlist",
        "--ignore-errors",
        "-o", output_template,
        "--",
        url,
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subtitle = _pick_subtitle(out_dir)
    info = _read_info(out_dir / "video.info.json", url)
    return {
        "video_path": None,
        "subtitle_path": str(subtitle) if subtitle else None,
        "info": info or {"url": url},
        "downloaded": False,
    }


def _read_info(info_path: Path, url: str) -> dict:
    info: dict = {}
    if info_path.exists():
        try:
            with open(info_path, "r", encoding="utf-8") as f:
                info = json.load(f)
        except Exception:
            pass
    if not info:
        info = {"url": url, "title": url}
    return info


def download(url: str, out_dir: Path, format_spec: str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best") -> dict:
    ytdlp = get_ytdlp_cmd()
    if not ytdlp:
        raise SystemExit("yt-dlp is not installed. Install with: python -m pip install yt-dlp")

    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "video.%(ext)s")
    cmd = [
        *ytdlp,
        "--format", format_spec,
        "--write-info-json",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "ko.*,en.*",
        "--sub-format", "vtt/srt/best",
        "--convert-subs", "vtt",
        "--no-playlist",
        "--ignore-errors",
        "-o", output_template,
        "--",
        url,
    ]
    subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr)
    video = _pick_video(out_dir)
    subtitle = _pick_subtitle(out_dir)
    info = _read_info(out_dir / "video.info.json", url)
    return {
        "video_path": str(video) if video else None,
        "subtitle_path": str(subtitle) if subtitle else None,
        "info": info or {"url": url},
        "downloaded": bool(video),
    }
