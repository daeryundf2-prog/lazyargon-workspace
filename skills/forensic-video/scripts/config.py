#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config.py
Configuration loader for forensic-video / watch skill in LazyForensic.
Loads settings from ~/.config/lazyforensic/video.env or ~/.config/watch/.env
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DETAIL = "balanced"
DEFAULT_RESOLUTION = 512

DETAIL_CAPS = {
    "transcript": 0,
    "efficient": 50,
    "balanced": 100,
}

CONFIG_PATHS = [
    Path.home() / ".config" / "lazyforensic" / "video.env",
    Path.home() / ".config" / "watch" / ".env",
]


def frame_cap(detail: str) -> int | None:
    return DETAIL_CAPS.get(detail, 100)


def get_config() -> dict:
    cfg = {
        "detail": DEFAULT_DETAIL,
        "resolution": DEFAULT_RESOLUTION,
        "groq_api_key": os.getenv("GROQ_API_KEY", ""),
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
    }

    for path in CONFIG_PATHS:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("\"'")
                            if k in ("WATCH_DETAIL", "FORENSIC_DETAIL") and v in DETAIL_CAPS:
                                cfg["detail"] = v
                            elif k == "GROQ_API_KEY":
                                cfg["groq_api_key"] = v
                            elif k == "OPENAI_API_KEY":
                                cfg["openai_api_key"] = v
                            elif k == "GEMINI_API_KEY":
                                cfg["gemini_api_key"] = v
            except Exception:
                pass
            break

    # Environment variables override file config
    if os.getenv("GROQ_API_KEY"):
        cfg["groq_api_key"] = os.getenv("GROQ_API_KEY")
    if os.getenv("OPENAI_API_KEY"):
        cfg["openai_api_key"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("GEMINI_API_KEY"):
        cfg["gemini_api_key"] = os.getenv("GEMINI_API_KEY")

    return cfg
