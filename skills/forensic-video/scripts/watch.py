#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watch.py
Video observation & keyframe extraction engine for Gemini & Antigravity.
Downloads video / resolves local file, extracts frames, fetches transcript,
and outputs a markdown report with clickable file links for Gemini vision inspection.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from config import frame_cap, get_config  # noqa: E402
from download import download, fetch_captions, is_url, resolve_local  # noqa: E402
from frames import (  # noqa: E402
    auto_fps,
    extract_at_timestamps,
    extract_keyframes,
    extract_scene_or_uniform,
    format_time,
    get_metadata,
    merge_frames,
    parse_time,
    parse_timestamps,
)
from transcribe import filter_range, format_transcript, parse_vtt  # noqa: E402
from whisper import transcribe_video  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="forensic-video",
        description="Watch a video, extract auto-scaled frames, and extract timestamped transcripts for Gemini.",
    )
    ap.add_argument("source", help="Video URL or local file path")
    ap.add_argument("--max-frames", type=int, default=None, help="Override frame cap")
    ap.add_argument("--resolution", type=int, default=720, help="Frame width in pixels (default 720)")
    ap.add_argument("--fps", type=float, default=None, help="Override auto-fps")
    ap.add_argument(
        "--detail",
        choices=["transcript", "efficient", "balanced"],
        default=None,
        help="Fidelity dial: transcript (0 frames), efficient (cap 50), balanced (cap 100).",
    )
    ap.add_argument(
        "--timestamps",
        type=str,
        default=None,
        help="Comma-separated timestamps (SS, MM:SS, HH:MM:SS) to capture specific frames.",
    )
    ap.add_argument("--start", type=str, default=None, help="Range start (SS, MM:SS, or HH:MM:SS)")
    ap.add_argument("--end", type=str, default=None, help="Range end (SS, MM:SS, or HH:MM:SS)")
    ap.add_argument("--out-dir", type=str, default=None, help="Output directory for frames")
    ap.add_argument(
        "--upload-audio",
        action="store_true",
        help="Explicitly consent to upload extracted audio to the selected transcription provider.",
    )
    ap.add_argument(
        "--whisper",
        choices=["groq", "openai"],
        default=None,
        help="External transcription provider; requires --upload-audio.",
    )
    ap.add_argument("--json", action="store_true", help="Output JSON structure instead of Markdown")
    args = ap.parse_args()

    config = get_config()
    detail = args.detail or str(config["detail"])
    max_frames = args.max_frames if args.max_frames is not None else frame_cap(detail)
    if max_frames is not None and (max_frames < 0 or max_frames > 100):
        print("[-] --max-frames must be between 0 and 100", file=sys.stderr)
        return 2
    if args.whisper and not args.upload_audio:
        print("[-] --whisper requires explicit --upload-audio consent", file=sys.stderr)
        return 2
    cue_timestamps = parse_timestamps(args.timestamps)
    start_sec = parse_time(args.start)
    end_sec = parse_time(args.end)

    if args.out_dir:
        work = Path(args.out_dir).expanduser().resolve()
    else:
        work = Path(tempfile.mkdtemp(prefix="forensic-video-"))
    work.mkdir(parents=True, exist_ok=True)
    frames_dir = work / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    url_source = is_url(args.source)
    dl: dict = {"subtitle_path": None, "info": {}, "downloaded": False}
    transcript_segments: list[dict] = []
    video_path: str | None = None

    if url_source:
        print(
            "[forensic-video] URL download is convenience acquisition, not forensic imaging or chain of custody.",
            file=sys.stderr,
        )
        print("[forensic-video] URL detected. Checking metadata/captions...", file=sys.stderr)
        dl = fetch_captions(args.source, work / "download")
        if dl.get("subtitle_path"):
            transcript_segments = parse_vtt(dl["subtitle_path"])

        if detail != "transcript" or not transcript_segments:
            print("[forensic-video] Downloading video stream...", file=sys.stderr)
            dl_vid = download(args.source, work / "download")
            video_path = dl_vid.get("video_path")
            if not transcript_segments and dl_vid.get("subtitle_path"):
                transcript_segments = parse_vtt(dl_vid["subtitle_path"])
    else:
        local_info = resolve_local(args.source)
        video_path = local_info["video_path"]
        dl["info"] = local_info["info"]

    # External transcription is opt-in because it uploads extracted evidence audio.
    if not transcript_segments and video_path and args.upload_audio:
        print(
            f"[forensic-video] Uploading extracted audio to {args.whisper or 'configured provider'}...",
            file=sys.stderr,
        )
        transcript_segments = transcribe_video(
            video_path,
            work,
            backend=args.whisper,
            allow_upload=True,
        )

    if transcript_segments:
        transcript_segments = filter_range(transcript_segments, start=start_sec, end=end_sec)

    # Frame extraction
    frames: list[dict] = []
    meta: dict = {}
    if video_path and detail != "transcript":
        meta = get_metadata(video_path)
        print(f"[forensic-video] Extracting frames (detail={detail}, resolution={args.resolution}px)...", file=sys.stderr)
        if detail == "efficient":
            frames = extract_keyframes(
                video_path,
                frames_dir,
                max_frames=max_frames or 50,
                resolution=args.resolution,
                start=start_sec,
                end=end_sec,
            )
        else:
            frames = extract_scene_or_uniform(
                video_path,
                frames_dir,
                max_frames=max_frames or 100,
                resolution=args.resolution,
                start=start_sec,
                end=end_sec,
                fps_override=args.fps,
            )

        if cue_timestamps:
            cue_frames = extract_at_timestamps(video_path, cue_timestamps, frames_dir, resolution=args.resolution)
            frames = merge_frames(frames, cue_frames, max_frames=max_frames)

    # Output generation
    if args.json:
        out_obj = {
            "title": dl.get("info", {}).get("title", args.source),
            "video_path": video_path,
            "metadata": meta,
            "frames": frames,
            "transcript": transcript_segments,
        }
        print(json.dumps(out_obj, ensure_ascii=False, indent=2))
        return 0

    # Markdown report
    title = dl.get("info", {}).get("title", args.source)
    print(f"# 동영상 분석 보고서: {title}\n")
    if meta:
        print("### [영상 메타데이터]")
        duration = meta.get("duration")
        print(f"- 재생 시간: {format_time(duration) if duration is not None else '미측정'}")
        print(f"- 해상도: {meta.get('width') or '미측정'} x {meta.get('height') or '미측정'}")
        print(f"- FPS: {meta.get('fps') if meta.get('fps') is not None else '미측정'}")
        print(f"- 코덱: {meta.get('codec', 'unknown')}\n")

    if frames:
        print(f"### [추출된 주요 프레임 ({len(frames)}개)]")
        for f in frames:
            norm_path = Path(f["path"]).as_posix()
            print(f"- **[{f['time_str']}]**: [{Path(f['path']).name}](file:///{norm_path})")
        print()

    if transcript_segments:
        print(f"### [오디오 전사 및 자막 ({len(transcript_segments)}개 세그먼트)]")
        for s in transcript_segments:
            print(f"- **[{format_time(s['start'])}]**: {s['text']}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
