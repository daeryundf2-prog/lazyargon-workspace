#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
local_stt.py — 서버 STT 최우선 배치 전사기 (유튜브 자동자막 + Google STT 서버 병렬 전송 기본)

로컬 Whisper(faster-whisper, openai-whisper, whisper.cpp)는 속도가 극도로 느리고(다수 영상 시
30분 이상 행 발생) 한국어 고유명사·구어체 오타가 많으므로 기본 비활성화한다.
엔진 자동 탐지 순서:

  1. google-server (SpeechRecognition `recognize_google` + `ffmpeg` 16kHz PCM 병렬 청크 서버 전송)
     — 유튜브 URL 또는 파일명 내 11자리 유튜브 ID가 있고 `yt-dlp`가 설치된 경우 유튜브 서버 자동자막(VTT)을 우선 추출하고,
       자막이 없거나 일반 로컬 오디오/영상 파일이면 Google STT 서버(`ko-KR`)로 병렬 전송해 초고속·고정확도 전사 수행
  2. sensevoice (FunASR `funasr` 패키지 또는 `sensevoice` 바이너리) — 감정·비언어 이벤트 태그 필요 시
  3. (--allow-local-whisper 명시 시에만) faster-whisper / openai-whisper / whisper.cpp

사용:
    python scripts/local_stt.py audio/                          # 디렉터리 배치 (기본: google-server)
    python scripts/local_stt.py audio/call.wav --lang ko
    python scripts/local_stt.py "https://www.youtube.com/watch?v=..." --out yt_stt.json
    python scripts/local_stt.py audio/ --keywords "돈,송금,계좌" --out stt_report.json
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import difflib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_WHISPER_MODEL_CACHE: dict[str, object] = {}


@contextlib.contextmanager
def _win_symlink_fallback():
    if os.name != "nt":
        yield
        return
    orig_symlink = os.symlink

    def _safe_win_symlink(src, dst, target_is_directory=False, *args, **kwargs):
        try:
            return orig_symlink(src, dst, target_is_directory=target_is_directory, *args, **kwargs)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                src_str = str(src)
                dst_str = str(dst)
                if not os.path.isabs(src_str):
                    dst_dir = os.path.dirname(dst_str)
                    src_str = os.path.normpath(os.path.join(dst_dir, src_str))
                if os.path.isdir(src_str):
                    shutil.copytree(src_str, dst_str, dirs_exist_ok=True)
                else:
                    dst_dir = os.path.dirname(dst_str)
                    if dst_dir:
                        os.makedirs(dst_dir, exist_ok=True)
                    shutil.copy2(src_str, dst_str)
                return None
            raise

    os.symlink = _safe_win_symlink
    try:
        yield
    finally:
        os.symlink = orig_symlink


AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".mp4", ".mkv", ".mov", ".webm"}


def detect_engine(allow_local_whisper: bool = False) -> str | None:
    """사용 가능한 STT 엔진 이름을 반환한다. 기본은 무조건 서버 STT(google-server) 최우선."""
    if importlib.util.find_spec("speech_recognition") and shutil.which("ffmpeg"):
        return "google-server"
    if shutil.which("yt-dlp"):
        return "youtube-subs"
    if importlib.util.find_spec("funasr"):
        return "sensevoice"
    for binary in ("sensevoice", "sensevoice-cli", "sensevoice-onnx"):
        if shutil.which(binary):
            return f"binary-sensevoice:{binary}"
    if allow_local_whisper:
        if importlib.util.find_spec("faster_whisper"):
            return "faster-whisper"
        if importlib.util.find_spec("whisper"):
            return "openai-whisper"
        for binary in ("whisper-cli", "whisper.cpp", "main", "transcribe-cli"):
            if shutil.which(binary):
                return f"binary:{binary}"
    if importlib.util.find_spec("moonshine"):
        return "moonshine"  # 영어 전용 — 최후순위
    return None


SENSEVOICE_TAG_RE = re.compile(r"<\|([A-Za-z_]+)\|>")
_SENSEVOICE_LANGS = {"zh", "en", "yue", "ja", "ko"}
# SenseVoice가 방출하는 비언어 이벤트 토큰 (언어/감정 태그 제외)
_SENSEVOICE_EVENTS = {
    "APPLAUSE", "BGM", "COUGH", "CRY", "CRYING", "LAUGHTER", "NOISE",
    "SIGH", "SNEEZE", "SPEECH", "BREATH", "HICCUP",
}
_SENSEVOICE_EMOTIONS = {
    "HAPPY", "SAD", "ANGRY", "NEUTRAL", "FEARFUL", "DISGUSTED",
    "SURPRISED", "EMO_UNKNOWN",
}


def _engine_available(engine: str) -> bool:
    """--engine 강제 지정 시 해당 엔진의 실행 수단이 실재하는지 확인."""
    if engine == "google-server":
        return importlib.util.find_spec("speech_recognition") is not None and bool(shutil.which("ffmpeg"))
    if engine == "youtube-subs":
        return bool(shutil.which("yt-dlp"))
    if engine == "faster-whisper":
        return importlib.util.find_spec("faster_whisper") is not None
    if engine == "openai-whisper":
        return importlib.util.find_spec("whisper") is not None
    if engine == "sensevoice":
        return (importlib.util.find_spec("funasr") is not None
                or any(shutil.which(b) for b in ("sensevoice", "sensevoice-cli", "sensevoice-onnx")))
    if engine == "moonshine":
        return importlib.util.find_spec("moonshine") is not None
    return False


def parse_sensevoice_tags(raw_text: str) -> dict:
    """SenseVoice rich transcription 문자열에서 <|...|> 메타 토큰을 분리한다."""
    tags = SENSEVOICE_TAG_RE.findall(raw_text)
    text = SENSEVOICE_TAG_RE.sub("", raw_text).strip()
    return {
        "text": text,
        "lang": next((t.lower() for t in tags if t.lower() in _SENSEVOICE_LANGS), None),
        "emotion": next((t for t in tags if t in _SENSEVOICE_EMOTIONS), None),
        "events": [t for t in tags if t in _SENSEVOICE_EVENTS],
    }


_VTT_TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})")
_YT_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\]|(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})")


def _vtt_ts(h: str, m: str, s: str, ms: str) -> float:
    return round(int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0, 3)


def format_mmss(sec: float | None) -> str | None:
    """초(sec)를 정수 'MM:SS' (1시간 이상 시 'HH:MM:SS') 문자열로 변환한다."""
    if sec is None:
        return None
    total = max(0, int(float(sec)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def format_kor_time(sec: float | None) -> str | None:
    """초(sec)를 정수 'MM분 SS초' (1시간 이상 시 'HH시간 MM분 SS초') 문자열로 변환한다."""
    if sec is None:
        return None
    total = max(0, int(float(sec)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}시간 {m:02d}분 {s:02d}초" if h > 0 else f"{m:02d}분 {s:02d}초"


def norm_kr(text: str, phonetic_map: list[tuple[str, str]] | None = None) -> str:
    """한국어 음운 정규화 — 괄호 주석·공백·특수문자를 제거하고 한글/숫자만 남긴다."""
    s = re.sub(r"\[.*?\]|\(.*?\)", "", str(text or ""))
    for src, dst in phonetic_map or []:
        s = s.replace(src, dst)
    return "".join(re.findall(r"[가-힣0-9]+", s))


def verify_transcript_similarity(
    claimed_text: str,
    server_text: str,
    youtube_text: str = "",
    phonetic_map: list[tuple[str, str]] | None = None,
) -> dict:
    """주장 발언(claimed_text)과 서버 STT/유튜브 자막 원음 간 일치율(pct) 및 판정 태그를 반환한다."""
    nc = norm_kr(claimed_text, phonetic_map)
    ns = norm_kr(server_text, phonetic_map)
    ny = norm_kr(youtube_text, phonetic_map)
    if not nc or (not ns and not ny):
        return {"pct": 0, "ratio": 0.0, "tag": "서버STT 미확인 (원음 일치율 0%)", "verified": False}
    r_srv = difflib.SequenceMatcher(None, nc, ns, autojunk=False).ratio() if ns else 0.0
    r_yt = difflib.SequenceMatcher(None, nc, ny, autojunk=False).ratio() if ny else 0.0
    best = max(r_srv, r_yt)
    if (ns and nc in ns) or (ny and nc in ny):
        best = 1.0
    pct = int(round(best * 100))
    return {
        "pct": pct,
        "ratio": round(best, 4),
        "tag": f"서버STT 검증완료 (원음 일치율 {pct}%)",
        "verified": pct >= 55,
    }


def parse_vtt_segments(vtt_text: str) -> list[dict]:
    """YouTube 서버 자동자막(.vtt)에서 중복 롤업 줄을 제거하고 타임스탬프 세그먼트로 변환한다."""
    segments: list[dict] = []
    last_text = ""
    lines = vtt_text.splitlines()
    i = 0
    while i < len(lines):
        m = _VTT_TIME_RE.search(lines[i])
        if not m:
            i += 1
            continue
        start = _vtt_ts(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _vtt_ts(m.group(5), m.group(6), m.group(7), m.group(8))
        i += 1
        text_lines = []
        while i < len(lines) and lines[i].strip():
            clean = re.sub(r"<[^>]+>", "", lines[i]).strip()
            if clean and clean != last_text:
                text_lines.append(clean)
            i += 1
        if text_lines:
            merged = " ".join(text_lines)
            if merged != last_text and (end - start) >= 0.05:
                segments.append({
                    "start": start,
                    "end": end,
                    "start_mmss": format_mmss(start),
                    "end_mmss": format_mmss(end),
                    "start_kor": format_kor_time(start),
                    "text": merged,
                })
                last_text = merged
    return segments


def _extract_youtube_url(target_str: str) -> str | None:
    if target_str.startswith(("http://", "https://")) and ("youtube.com" in target_str or "youtu.be" in target_str):
        return target_str
    m = _YT_ID_RE.search(target_str)
    if m:
        vid = m.group(1) or m.group(2)
        return f"https://www.youtube.com/watch?v={vid}"
    return None


def transcribe_youtube_subs(url_or_path: str, lang: str | None = None) -> dict:
    """yt-dlp로 유튜브 서버 자동자막/자막(VTT)을 즉시 추출한다."""
    yt_url = _extract_youtube_url(str(url_or_path))
    if not yt_url or not shutil.which("yt-dlp"):
        raise RuntimeError("유튜브 URL/ID를 찾을 수 없거나 yt-dlp가 설치되어 있지 않습니다.")
    sub_langs = f"{lang}.*,ko.*,en.*" if lang else "ko.*,en.*"
    with tempfile.TemporaryDirectory() as tmp:
        out_tmpl = str(Path(tmp) / "sub.%(ext)s")
        cmd = [
            "yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
            "--sub-langs", sub_langs, "--sub-format", "vtt", "--convert-subs", "vtt",
            "-o", out_tmpl, yt_url,
        ]
        subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        vtts = sorted(Path(tmp).glob("*.vtt"))
        if not vtts:
            raise RuntimeError(f"유튜브 서버 자막이 존재하지 않습니다: {yt_url}")
        segments = parse_vtt_segments(vtts[0].read_text(encoding="utf-8", errors="replace"))
        return {"engine": "youtube-subs/vtt", "segments": segments}


def _probe_duration(path: Path) -> float:
    if shutil.which("ffprobe"):
        try:
            out = subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
                stderr=subprocess.DEVNULL, text=True, timeout=15,
            ).strip()
            return float(out)
        except Exception:
            pass
    return 0.0


def transcribe_google_server(path: Path, lang: str | None = None, chunk_sec: float = 25.0) -> dict:
    """Google Speech-to-Text 서버(`recognize_google`) + `ffmpeg` 16kHz PCM 병렬 청크 전사.
    파일명에 유튜브 ID가 있고 yt-dlp가 있으면 유튜브 서버 자동자막을 먼저 시도한다."""
    if _extract_youtube_url(path.name) and shutil.which("yt-dlp"):
        try:
            yt_res = transcribe_youtube_subs(path.name, lang)
            if yt_res.get("segments"):
                return yt_res
        except Exception:
            pass

    import speech_recognition as sr  # type: ignore

    lang_code = "ko-KR" if (not lang or lang.lower().startswith("ko")) else lang
    dur = _probe_duration(path)
    windows: list[tuple[float, float]] = []
    if dur <= 0:
        windows.append((0.0, 30.0))
    else:
        n_chunks = max(1, int(math.ceil(dur / chunk_sec)))
        for idx in range(n_chunks):
            s = round(idx * chunk_sec, 2)
            e = round(min(dur, (idx + 1) * chunk_sec), 2)
            if e - s >= 0.3:
                windows.append((s, e))

    def _work(win: tuple[float, float]) -> dict | None:
        s, e = win
        cmd = [
            "ffmpeg", "-nostdin", "-v", "error", "-ss", f"{s:.2f}", "-t", f"{e - s:.2f}",
            "-i", str(path), "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "-f", "s16le", "-",
        ]
        try:
            pcm = subprocess.run(cmd, capture_output=True, timeout=30).stdout
            if not pcm or len(pcm) < 1600:
                return None
            rec = sr.Recognizer()
            ad = sr.AudioData(pcm, 16000, 2)
            txt = rec.recognize_google(ad, language=lang_code)
            if txt and txt.strip():
                return {
                    "start": s,
                    "end": e,
                    "start_mmss": format_mmss(s),
                    "end_mmss": format_mmss(e),
                    "start_kor": format_kor_time(s),
                    "text": txt.strip(),
                }
        except Exception:
            return None
        return None

    segments: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(12, max(1, len(windows)))) as ex:
        for seg in ex.map(_work, windows):
            if seg:
                segments.append(seg)
    return {"engine": f"google-server/{lang_code}", "segments": segments}


def transcribe_faster_whisper(path: Path, lang: str | None, verbatim: bool, model_size: str) -> dict:
    from faster_whisper import WhisperModel  # type: ignore

    if model_size not in _WHISPER_MODEL_CACHE:
        with _win_symlink_fallback():
            _WHISPER_MODEL_CACHE[model_size] = WhisperModel(model_size)
    model = _WHISPER_MODEL_CACHE[model_size]
    segments_iter, _info = model.transcribe(
        str(path),
        language=lang,
        word_timestamps=verbatim,
        condition_on_previous_text=not verbatim,
    )
    segments = []
    for s in segments_iter:
        seg = {"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()}
        if verbatim and s.words:
            seg["words"] = [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word} for w in s.words]
        segments.append(seg)
    return {"engine": f"faster-whisper/{model_size}", "segments": segments}


def transcribe_openai_whisper(path: Path, lang: str | None, verbatim: bool, model_size: str) -> dict:
    import whisper  # type: ignore

    model = whisper.load_model(model_size)
    result = model.transcribe(
        str(path),
        language=lang,
        word_timestamps=verbatim,
        condition_on_previous_text=not verbatim,
        verbose=False,
    )
    segments = [
        {"start": round(s["start"], 3), "end": round(s["end"], 3), "text": s["text"].strip()}
        for s in result.get("segments", [])
    ]
    return {"engine": f"openai-whisper/{model_size}", "segments": segments}


def transcribe_binary(binary: str, path: Path, lang: str | None) -> dict:
    """whisper.cpp 계열 바이너리를 호출한다. -oj로 JSON 세그먼트를 받는다."""
    out_base = path.with_suffix("")
    cmd = [binary, "-f", str(path), "-oj", "-of", str(out_base)]
    if lang:
        cmd += ["-l", lang]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"{binary} failed: {proc.stderr.strip()[:300]}")
    json_path = out_base.with_suffix(".json")
    if not json_path.exists():
        raise RuntimeError(f"{binary} produced no JSON output at {json_path}")
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    segments = []
    for item in raw.get("transcription", []):
        offsets = item.get("offsets", {})
        segments.append({
            "start": round(offsets.get("from", 0) / 1000.0, 3),
            "end": round(offsets.get("to", 0) / 1000.0, 3),
            "text": item.get("text", "").strip(),
        })
    return {"engine": binary, "segments": segments}


def transcribe_sensevoice(path: Path, lang: str | None, model_size: str) -> dict:
    """FunASR SenseVoice — 한국어 포함 다국어 + 감정/비언어 이벤트 태그.

    BYOB: funasr 패키지가 없으면 호출되지 않는다(detect_engine이 차단).
    모델 기본값은 SenseVoiceSmall; model_size가 'turbo' 등 whisper 이름이면
    iic/SenseVoiceSmall로 매핑한다.
    """
    from funasr import AutoModel  # type: ignore
    from funasr.utils.postprocess_utils import rich_transcription_postprocess  # type: ignore

    model_id = model_size if "/" in model_size else "iic/SenseVoiceSmall"
    model = AutoModel(model=model_id, disable_update=True)
    res = model.generate(
        input=str(path),
        cache={},
        language=lang or "auto",
        use_itn=True,
        batch_size_s=60,
        merge_vad=True,
    )
    segments = []
    for item in res:
        raw = item.get("text", "")
        parsed = parse_sensevoice_tags(raw)
        text = rich_transcription_postprocess(raw)
        seg = {"start": None, "end": None, "text": text}
        if parsed["emotion"]:
            seg["emotion"] = parsed["emotion"]
        if parsed["events"]:
            seg["events"] = parsed["events"]
        segments.append(seg)
    return {
        "engine": f"sensevoice/{model_id}",
        "segments": segments,
        "note": "SenseVoice 감정/이벤트 태그는 모델 추정치 — 증거 기재 시 원본 음성 대조 필요",
    }


def transcribe_sensevoice_binary(binary: str, path: Path, lang: str | None) -> dict:
    """sensevoice 바이너리 계열 (ONNX 포트 등) — JSON 출력 가정, BYOB."""
    cmd = [binary, str(path), "--json"]
    if lang:
        cmd += ["--language", lang]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"{binary} failed: {proc.stderr.strip()[:300]}")
    raw = json.loads(proc.stdout)
    segments = []
    items = raw if isinstance(raw, list) else raw.get("segments", [raw])
    for item in items:
        text = item.get("text", "")
        parsed = parse_sensevoice_tags(text)
        seg = {
            "start": item.get("start"),
            "end": item.get("end"),
            "text": parsed["text"],
        }
        if parsed["emotion"]:
            seg["emotion"] = parsed["emotion"]
        if parsed["events"]:
            seg["events"] = parsed["events"]
        segments.append(seg)
    return {"engine": binary, "segments": segments}


def transcribe_moonshine(path: Path, model_size: str) -> dict:
    """moonshine.transcribe는 타임스탬프 없이 문장 리스트를 반환한다.
    영어 전용 엔진 — 한국어 증거에는 쓰지 않는다."""
    import moonshine  # type: ignore

    model = model_size if model_size.startswith("moonshine/") else f"moonshine/{model_size}"
    if model.endswith("/turbo"):
        model = "moonshine/base"  # turbo 매핑 없음 — base로 폴백
    lines = moonshine.transcribe(str(path), model)
    segments = [
        {"start": None, "end": None, "text": t.strip()}
        for t in lines if t and t.strip()
    ]
    return {"engine": model, "segments": segments,
            "note": "moonshine은 세그먼트 타임스탬프를 제공하지 않음"}


def transcribe_file(path: Path, engine: str, lang: str | None, verbatim: bool, model_size: str) -> dict:
    if engine == "google-server":
        return transcribe_google_server(path, lang)
    if engine == "youtube-subs":
        return transcribe_youtube_subs(str(path), lang)
    if engine == "faster-whisper":
        return transcribe_faster_whisper(path, lang, verbatim, model_size)
    if engine == "openai-whisper":
        return transcribe_openai_whisper(path, lang, verbatim, model_size)
    if engine.startswith("binary:"):
        return transcribe_binary(engine.split(":", 1)[1], path, lang)
    if engine == "sensevoice":
        return transcribe_sensevoice(path, lang, model_size)
    if engine.startswith("binary-sensevoice:"):
        return transcribe_sensevoice_binary(engine.split(":", 1)[1], path, lang)
    if engine == "moonshine":
        return transcribe_moonshine(path, model_size)
    raise RuntimeError(f"unknown engine: {engine}")


def keyword_hits(segments: list[dict], keywords: list[str]) -> list[dict]:
    hits = []
    for kw in keywords:
        for seg in segments:
            if kw in seg["text"]:
                hits.append({"keyword": kw, "start": seg["start"], "end": seg["end"], "text": seg["text"]})
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="서버 STT 최우선 배치 전사기 (유튜브 자동자막 + Google STT 서버 병렬 전송 기본)")
    ap.add_argument("input", help="오디오/영상 파일, 디렉터리 또는 유튜브 URL")
    ap.add_argument("--lang", default=None, help="언어 코드 (예: ko). 미지정 시 ko-KR 기본")
    ap.add_argument("--model", default="turbo", help="모델 크기 (기본 turbo)")
    ap.add_argument("--verbatim", action="store_true", help="필러음·단어 단위 타임스탬프 보존 모드")
    ap.add_argument("--allow-local-whisper", action="store_true",
                    help="느린 로컬 Whisper 폴백 허용 (기본 금지 — 서버 STT 강제)")
    ap.add_argument("--engine", default=None,
                    help="엔진 강제 지정 (google-server|youtube-subs|sensevoice|faster-whisper|openai-whisper|moonshine)")
    ap.add_argument("--keywords", default=None, help="쉼표 구분 키워드 히트 리포트")
    ap.add_argument("--out", "--output", dest="out", default=None, help="배치 요약 JSON 출력 경로")
    ap.add_argument("--out-dir", default=None, help="개별 .transcript.json 저장 디렉터리 (미지정 시 --out 폴더 또는 원본 옆)")
    args = ap.parse_args(argv)

    if args.engine:
        engine = args.engine
        if not _engine_available(engine):
            print(f"지정 엔진을 사용할 수 없습니다: {engine}", file=sys.stderr)
            return 3
    else:
        engine = detect_engine(allow_local_whisper=args.allow_local_whisper)
    if engine is None:
        print(
            "사용 가능한 서버 STT 엔진이 없습니다. (내부 Whisper는 기본 비활성화됨)\n"
            "설치 예:\n"
            "  pip install SpeechRecognition   # 권장 1순위: Google STT 서버 병렬 전송 (ffmpeg 필요)\n"
            "  pip install yt-dlp              # 유튜브 서버 자동자막 즉시 추출\n"
            "  pip install funasr              # SenseVoice — 감정/이벤트 태그",
            file=sys.stderr,
        )
        return 3

    if str(args.input).startswith(("http://", "https://")) and _extract_youtube_url(str(args.input)):
        try:
            result = transcribe_youtube_subs(str(args.input), args.lang)
            if args.out:
                Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except Exception as e:
            print(f"[FAIL] {args.input}: {e}", file=sys.stderr)
            return 1

    target = Path(args.input)
    if target.is_dir():
        files = sorted(p for p in target.rglob("*") if p.suffix.lower() in AUDIO_EXTS)
    elif target.is_file():
        files = [target]
    else:
        print(f"입력을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2
    if not files:
        print(f"전사 가능한 오디오/영상 파일이 없습니다: {target}", file=sys.stderr)
        return 2

    keywords = [k.strip() for k in args.keywords.split(",")] if args.keywords else []
    summary = {"engine": engine, "files": []}

    for f in files:
        try:
            result = transcribe_file(f, engine, args.lang, args.verbatim, args.model)
        except Exception as e:  # noqa: BLE001 — 파일별 실패를 기록하고 계속
            print(f"[FAIL] {f}: {e}", file=sys.stderr)
            summary["files"].append({"file": str(f), "status": "failed", "error": str(e)[:300]})
            continue

        record = {
            "file": str(f),
            "status": "ok",
            "engine": result["engine"],
            "segment_count": len(result["segments"]),
            "segments": result["segments"],
        }
        if keywords:
            record["keyword_hits"] = keyword_hits(result["segments"], keywords)

        if args.out_dir:
            out_dir = Path(args.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / (f.name + ".transcript.json")
        elif args.out:
            out_dir = Path(args.out).resolve().parent
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / (f.name + ".transcript.json")
        else:
            out_path = f.with_name(f.name + ".transcript.json")
        out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        hit_msg = f", 키워드 히트 {len(record.get('keyword_hits', []))}건" if keywords else ""
        print(f"[OK] {f} — {record['segment_count']}개 세그먼트{hit_msg} → {out_path.name}")
        summary["files"].append({**record, "segments": "<see transcript.json>"} if args.out else record)

    if args.out:
        Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"배치 요약 → {args.out}")

    ok = sum(1 for x in summary["files"] if x.get("status") == "ok")
    print(f"완료: {ok}/{len(files)}개 파일 전사 (엔진: {engine})")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
