#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcribe.py
Parse VTT / SRT subtitles and format them into timestamped transcript blocks.
"""
from __future__ import annotations

import re
from pathlib import Path


def parse_vtt(vtt_path: str | Path) -> list[dict]:
    p = Path(vtt_path)
    if not p.exists():
        return []

    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    segments = []
    ts_pattern = re.compile(r"(\d{2}:)?\d{2}:\d{2}[\.,]\d{3}\s*-->\s*(\d{2}:)?\d{2}:\d{2}[\.,]\d{3}")

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if ts_pattern.search(line):
            times = ts_pattern.findall(line)
            # parse start time
            time_match = re.search(r"(?:(\d{2}):)?(\d{2}):(\d{2})[\.,](\d{3})", line)
            start_sec = 0.0
            if time_match:
                h = int(time_match.group(1) or 0)
                m = int(time_match.group(2))
                s = int(time_match.group(3))
                ms = int(time_match.group(4))
                start_sec = h * 3600 + m * 60 + s + ms / 1000.0

            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip():
                # Clean html tags like <c> </c>
                cleaned = re.sub(r"<[^>]+>", "", lines[i].strip())
                if cleaned:
                    text_lines.append(cleaned)
                i += 1
            
            content = " ".join(text_lines)
            if content:
                # Deduplicate identical consecutive segments (common in auto-captions)
                if not segments or segments[-1]["text"] != content:
                    segments.append({
                        "start": start_sec,
                        "text": content,
                    })
        else:
            i += 1

    return segments


def filter_range(segments: list[dict], start: float | None = None, end: float | None = None) -> list[dict]:
    res = []
    for s in segments:
        t = s["start"]
        if start is not None and t < start:
            continue
        if end is not None and t > end:
            continue
        res.append(s)
    return res


def format_transcript(segments: list[dict]) -> str:
    lines = []
    for s in segments:
        m = int(s["start"] // 60)
        sec = int(s["start"] % 60)
        lines.append(f"[{m:02d}:{sec:02d}] {s['text']}")
    return "\n".join(lines)
