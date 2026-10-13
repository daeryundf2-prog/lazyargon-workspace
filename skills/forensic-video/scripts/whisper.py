#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
whisper.py
Speech-to-Text transcription via Groq or OpenAI.

Audio upload is disabled unless the caller passes allow_upload=True.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


def load_api_key(backend: str | None = None) -> tuple[str | None, str]:
    if backend == "groq" or (backend is None and os.getenv("GROQ_API_KEY")):
        k = os.getenv("GROQ_API_KEY")
        if k:
            return k, "groq"
    if backend == "openai" or (backend is None and os.getenv("OPENAI_API_KEY")):
        k = os.getenv("OPENAI_API_KEY")
        if k:
            return k, "openai"
    return None, "none"


def extract_audio(video_path: str, out_audio: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found for audio extraction")
    cmd = [
        ffmpeg,
        "-y",
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-b:a", "64k",
        str(out_audio),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_audio


def transcribe_video(
    video_path: str,
    out_dir: Path,
    backend: str | None = None,
    allow_upload: bool = False,
) -> list[dict]:
    if not allow_upload:
        print(
            "[forensic-video] external transcription disabled; audio was not uploaded",
            file=sys.stderr,
        )
        return []

    key, provider = load_api_key(backend)
    if not key:
        return []

    audio_path = out_dir / "audio.mp3"
    try:
        extract_audio(video_path, audio_path)
        if not audio_path.exists() or audio_path.stat().st_size == 0:
            return []

        if provider == "groq":
            return _transcribe_groq(audio_path, key)
        elif provider == "openai":
            return _transcribe_openai(audio_path, key)
        return []
    finally:
        # 증거 오디오는 외부 전송 후에도 로컬에 남기지 않는다 (반출 동의 시에도 cleanup)
        try:
            if audio_path.exists():
                audio_path.unlink()
        except Exception:
            pass


def _transcribe_groq(audio_path: Path, api_key: str) -> list[dict]:
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    
    with open(audio_path, "rb") as f:
        file_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'
        f"Content-Type: audio/mpeg\r\n\r\n"
    ).encode("utf-8") + file_bytes + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="model"\r\n\r\n'
        f"whisper-large-v3\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="response_format"\r\n\r\n'
        f"verbose_json\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            segments = []
            for seg in data.get("segments", []):
                segments.append({
                    "start": float(seg.get("start", 0.0)),
                    "text": seg.get("text", "").strip(),
                })
            return segments
    except Exception as e:
        print(f"[forensic-video] Groq transcription error: {e}", file=sys.stderr)
        return []


def _transcribe_openai(audio_path: Path, api_key: str) -> list[dict]:
    url = "https://api.openai.com/v1/audio/transcriptions"
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    
    with open(audio_path, "rb") as f:
        file_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'
        f"Content-Type: audio/mpeg\r\n\r\n"
    ).encode("utf-8") + file_bytes + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="model"\r\n\r\n'
        f"whisper-1\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="response_format"\r\n\r\n'
        f"verbose_json\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            segments = []
            for seg in data.get("segments", []):
                segments.append({
                    "start": float(seg.get("start", 0.0)),
                    "text": seg.get("text", "").strip(),
                })
            return segments
    except Exception as e:
        print(f"[forensic-video] OpenAI transcription error: {e}", file=sys.stderr)
        return []
