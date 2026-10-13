#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_survey.py — 오디오 발화 구간 선조사 (무음/RMS 지도)

STT 전사 전에 "어디에 발화가 있는가"를 먼저 본다.
전사 엔진 없이도 돌아가므로 수백 개 녹음 중 실제 발화가 있는
파일만 골라내는 1차 스크리닝에 쓴다.

WAV는 표준 라이브러리(wave)로 직접 읽고, 그 외 포맷은 ffmpeg가
있을 때만 PCM으로 변환해 읽는다. 둘 다 없으면 exit 3(fail-closed).

사용:
    python scripts/audio_survey.py rec.wav
    python scripts/audio_survey.py audio/ --json
    python scripts/audio_survey.py rec.m4a --threshold 0.01

출력: 길이, 샘플레이트, 초당 RMS, 무음 비율, 발화 구간 목록

알려진 한계:
- RMS 기반이라 배경소음이 큰 녹음은 무음도 발화로 잡힐 수 있다.
  구간 목록은 '후보'이지 확정이 아니다.
- 화자 구분·내용 판독은 하지 않는다. 전사는 scripts/local_stt.py.
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac"}
DEFAULT_THRESHOLD = 0.01


def read_wav(path: Path) -> tuple[list[float], int] | None:
    """WAV를 모노 float(-1..1)로 읽는다. 실패 시 None."""
    try:
        with wave.open(str(path), "rb") as wf:
            framerate = wf.getframerate()
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            if wf.getnframes() * nchannels * sampwidth > 8 * 1024 * 1024:
                return None
            raw = wf.readframes(wf.getnframes())
    except (wave.Error, OSError):
        return None
    if sampwidth != 2:
        return None  # 16-bit PCM만 지원, 나머지는 ffmpeg 경로로
    count = len(raw) // 2
    samples = struct.unpack(f"<{count}h", raw)
    mono = [sum(samples[i:i + nchannels]) / nchannels
            for i in range(0, count - nchannels + 1, nchannels)]
    return [s / 32768.0 for s in mono], framerate


def read_via_ffmpeg(path: Path) -> tuple[list[float], int] | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-i", str(path),
             "-ac", "1", "-ar", "16000", "-f", "wav", str(tmp_path)],
            capture_output=True,
        )
        if proc.returncode != 0:
            return None
        return read_wav(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def rms_per_second(samples: list[float], framerate: int) -> list[float]:
    out = []
    for sec in range(len(samples) // framerate):
        chunk = samples[sec * framerate:(sec + 1) * framerate]
        out.append((sum(v * v for v in chunk) / len(chunk)) ** 0.5)
    return out


def read_wav_streaming(path: Path, max_seconds: float | None = None) -> tuple[callable, int, int, float | None] | None:
    """WAV를 청크로 읽어 초당 RMS를 계산하는 제너레이터를 반환한다.

    전체 PCM을 메모리에 올리지 않는다 — 긴 녹음에서 OOM을 막는다.
    반환: (mono_청크_제너레이터, framerate, channels, duration_s|None)
    max_seconds를 넘으면 중단한다(상한 보고용 duration은 -1 초과 신호).
    실패 시 None.
    """
    try:
        wf = wave.open(str(path), "rb")
    except (wave.Error, OSError):
        return None
    if wf.getsampwidth() != 2:
        wf.close()
        return None

    framerate = wf.getframerate()
    nchannels = wf.getnchannels()
    if framerate <= 0 or nchannels <= 0:
        wf.close()
        return None
    total_frames = wf.getnframes()
    duration = total_frames / framerate

    def chunks(seconds_cap: float | None = None):
        limit = max_seconds if seconds_cap is None else seconds_cap
        limit = 86400 if limit is None else limit
        if not 0 < limit <= 86400:
            wf.close()
            raise ValueError("Audio limit must be in (0, 86400] seconds")
        sec_sq_sum = 0.0
        sec_count = 0
        frames_read = 0
        target_frames = min(total_frames, int(limit * framerate))
        try:
            while frames_read < target_frames:
                count = min(4096, framerate - sec_count, target_frames - frames_read)
                raw = wf.readframes(count)
                if len(raw) != count * 2 * nchannels:
                    raise OSError("Truncated PCM frames")
                values = struct.unpack(f"<{count * nchannels}h", raw)
                if nchannels == 1:
                    sec_sq_sum += sum(v * v for v in values)
                else:
                    sums = map(sum, zip(*(values[c::nchannels] for c in range(nchannels))))
                    sec_sq_sum += sum(v * v for v in sums) / (nchannels * nchannels)
                frames_read += count
                sec_count += count
                if sec_count == framerate:
                    yield (sec_sq_sum / sec_count) ** 0.5 / 32768.0
                    sec_sq_sum = 0.0
                    sec_count = 0
            if sec_count:
                yield (sec_sq_sum / sec_count) ** 0.5 / 32768.0
            if frames_read < total_frames:
                raise OSError("Audio duration exceeds processing limit")
        finally:
            wf.close()

    return chunks, framerate, nchannels, duration


def speech_segments(rms: list[float], threshold: float) -> list[dict]:
    """RMS > threshold인 연속 구간을 묶어서 반환한다."""
    segs = []
    start = None
    for i, v in enumerate(rms):
        if v > threshold and start is None:
            start = i
        elif v <= threshold and start is not None:
            segs.append({"start": start, "end": i})
            start = None
    if start is not None:
        segs.append({"start": start, "end": len(rms)})
    return segs


def survey(path: Path, threshold: float) -> dict:
    streamed = read_wav_streaming(path)
    if streamed is not None:
        chunks, framerate, _nchannels, duration = streamed
        try:
            rms = list(chunks())
        except OSError as e:
            return {"file": str(path), "status": "failed",
                    "error": f"스트리밍 판독 실패: {e}", "framerate": framerate}
        segs = speech_segments(rms, threshold)
        speech_secs = sum(s["end"] - s["start"] for s in segs)
        return {
            "file": str(path),
            "status": "ok",
            "duration_s": round(duration, 2),
            "framerate": framerate,
            "speech_ratio": round(speech_secs / max(len(rms), 1), 3),
            "speech_segments": segs,
            "rms_per_second": [round(v, 4) for v in rms],
        }
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"file": str(path), "status": "failed", "error": "No supported PCM reader or ffmpeg"}
    with tempfile.TemporaryDirectory() as directory:
        converted = Path(directory) / "decoded.wav"
        try:
            result = subprocess.run(
                [ffmpeg, "-v", "error", "-i", str(path), "-t", "86401",
                 "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-fs", "536870912", str(converted)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
            if result.returncode != 0 or not converted.is_file():
                raise OSError("ffmpeg conversion failed")
            if converted.stat().st_size >= 536870912:
                raise OSError("Decoded audio byte limit reached")
            if read_wav_streaming(converted) is None:
                raise OSError("Unsupported conversion output")
            record = survey(converted, threshold)
            record["file"] = str(path)
            return record
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"file": str(path), "status": "failed", "error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="오디오 발화 구간 선조사 (로컬 전용)")
    ap.add_argument("input", help="오디오 파일 또는 디렉터리")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"발화 판정 RMS 임계값 (기본 {DEFAULT_THRESHOLD})")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args(argv)

    target = Path(args.input)
    if target.is_dir():
        files = sorted(p for p in target.rglob("*") if p.suffix.lower() in AUDIO_EXTS)
    elif target.is_file():
        files = [target]
    else:
        print(f"대상을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2
    if not files:
        print(f"오디오 파일이 없습니다: {target}", file=sys.stderr)
        return 2

    if not shutil.which("ffmpeg") and any(f.suffix.lower() != ".wav" for f in files):
        print("경고: ffmpeg가 없어 .wav 이외 포맷은 읽지 못합니다", file=sys.stderr)

    records = [survey(f, args.threshold) for f in files]
    ok = sum(1 for r in records if r["status"] == "ok")

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        for r in records:
            if r["status"] == "ok":
                print(f"{r['file']}: {r['duration_s']}s, 발화 비율 {r['speech_ratio']*100:.0f}%, "
                      f"발화 구간 {len(r['speech_segments'])}개")
                for s in r["speech_segments"]:
                    print(f"    {s['start']:>4}s ~ {s['end']:>4}s")
            else:
                print(f"[FAIL] {r['file']}: {r['error']}", file=sys.stderr)
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
