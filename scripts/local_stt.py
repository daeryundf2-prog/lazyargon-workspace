#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
local_stt.py — 로컬 전용 STT 배치 전사기

증거 오디오를 외부 API로 보내지 않고 로컬 엔진으로 전사한다.
엔진 자동 탐지 순서:

  1. faster-whisper (pip 패키지) — word timestamps 지원
  2. openai-whisper (pip 패키지)
  3. whisper.cpp / transcribe.cpp 계열 바이너리 (whisper-cli, main, transcribe-cli)
  4. SenseVoice (FunASR `funasr` 패키지 또는 `sensevoice` 바이너리)
     — ko/zh/yue/en/ja 지원 + 감정·비언어 이벤트 태그 (<|ANGRY|> 등)
  5. moonshine (pip 패키지 useful-moonshine) — ⚠️ 영어 전용, 한국어 증거엔 부적합

엔진이 하나도 없으면 전사를 지어내지 않고 exit 3 + 안내로 종료한다(fail-closed).
특정 엔진을 강제하려면 --engine (faster-whisper|openai-whisper|sensevoice|moonshine).

사용:
    python scripts/local_stt.py audio/                          # 디렉터리 배치
    python scripts/local_stt.py audio/call.wav --lang ko
    python scripts/local_stt.py audio/ --keywords "돈,송금,계좌" --out stt_report.json
    python scripts/local_stt.py audio/ --verbatim               # 필러음 보존 모드
    python scripts/local_stt.py a.wav --model nyrahealth/CrisperWhisper
    # faster-whisper는 HF 리포 ID도 받는다 — CrisperWhisper는 필러음·
    # 말더듬까지 verbatim 전사하는 파인튜닝 모델 (증거 녹취에 적합)

출력 (파일별 + 요약):
    - <입력>.transcript.json  : 타임스탬프 세그먼트 전사
    - --out 지정 시           : 배치 요약 + 키워드 히트 리포트

알려진 한계:
- 화자 분리(diarization)는 하지 않는다. 화자 구분이 필요하면 결과를
  '미확인'으로 표시하고 별도 도구를 쓸 것.
- verbatim 모드는 엔진이 지원하는 범위 내에서만 유효하다
  (faster-whisper: word_timestamps + condition_on_previous_text 해제).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".mp4", ".mkv", ".mov", ".webm"}


def detect_engine() -> str | None:
    """사용 가능한 로컬 STT 엔진 이름을 반환한다. 없으면 None."""
    if importlib.util.find_spec("faster_whisper"):
        return "faster-whisper"
    if importlib.util.find_spec("whisper"):
        return "openai-whisper"
    for binary in ("whisper-cli", "whisper.cpp", "main", "transcribe-cli"):
        if shutil.which(binary):
            return f"binary:{binary}"
    if importlib.util.find_spec("funasr"):
        return "sensevoice"
    for binary in ("sensevoice", "sensevoice-cli", "sensevoice-onnx"):
        if shutil.which(binary):
            return f"binary-sensevoice:{binary}"
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
    """SenseVoice rich transcription 문자열에서 <|...|> 메타 토큰을 분리한다.

    반환: {"text": 정제된 본문, "lang": 언어 태그|None,
          "emotion": 감정 태그|None, "events": [비언어 이벤트]}
    모델 없이 결정적으로 동작하는 순수 파서 — 태그가 없으면 빈 메타를 돌려준다.
    """
    tags = SENSEVOICE_TAG_RE.findall(raw_text)
    text = SENSEVOICE_TAG_RE.sub("", raw_text).strip()
    return {
        "text": text,
        "lang": next((t.lower() for t in tags if t.lower() in _SENSEVOICE_LANGS), None),
        "emotion": next((t for t in tags if t in _SENSEVOICE_EMOTIONS), None),
        "events": [t for t in tags if t in _SENSEVOICE_EVENTS],
    }


def transcribe_faster_whisper(path: Path, lang: str | None, verbatim: bool, model_size: str) -> dict:
    from faster_whisper import WhisperModel  # type: ignore

    model = WhisperModel(model_size)
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
    ap = argparse.ArgumentParser(description="로컬 전용 STT 배치 전사기 (외부 업로드 없음)")
    ap.add_argument("input", help="오디오/영상 파일 또는 디렉터리")
    ap.add_argument("--lang", default=None, help="언어 코드 (예: ko). 미지정 시 엔진 자동 감지")
    ap.add_argument("--model", default="turbo", help="모델 크기 (기본 turbo)")
    ap.add_argument("--verbatim", action="store_true", help="필러음·단어 단위 타임스탬프 보존 모드")
    ap.add_argument("--engine", default=None,
                    help="엔진 강제 지정 (faster-whisper|openai-whisper|sensevoice|moonshine). "
                         "감정 태그가 필요하면 sensevoice 지정")
    ap.add_argument("--keywords", default=None, help="쉼표 구분 키워드 히트 리포트")
    ap.add_argument("--out", default=None, help="배치 요약 JSON 출력 경로")
    args = ap.parse_args(argv)

    if args.engine:
        engine = args.engine
        if not _engine_available(engine):
            print(f"지정 엔진을 사용할 수 없습니다: {engine}", file=sys.stderr)
            return 3
    else:
        engine = detect_engine()
    if engine is None:
        print(
            "로컬 STT 엔진이 없습니다. 전사를 생성하지 않고 종료합니다.\n"
            "설치 예:\n"
            "  pip install faster-whisper      # 권장 (word timestamps)\n"
            "  pip install openai-whisper\n"
            "  pip install funasr              # SenseVoice — ko 지원 + 감정/이벤트 태그\n"
            "  brew install whisper-cpp        # 또는 transcribe.cpp 빌드\n"
            "외부 API(Groq/OpenAI) 업로드가 필요하면 의뢰인 동의·반출 승인 후\n"
            "skills/forensic-video 의 --upload-audio 경로를 사용하세요.",
            file=sys.stderr,
        )
        return 3

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
