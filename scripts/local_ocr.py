#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
local_ocr.py — 로컬 전용 OCR 배치 추출기 (이미지 · 스캔 PDF)

증거 이미지·스캔 PDF를 외부 API로 보내지 않고 로컬 엔진으로 OCR 추출한다.
엔진 자동 탐지 순서:
  1. easyocr (pip 패키지) — 한국어·영어 동시 인식 및 한글 경로 호환(PIL RGB 버퍼 전달)
  2. tesseract (시스템 바이너리 또는 C:\Program Files\Tesseract-OCR\tesseract.exe)
     — 한국어(ko/kor) 요청 시 kor.traineddata 존재 여부 검증

엔진이 하나도 없으면 텍스트를 지어내지 않고 exit 3 + 안내로 종료한다(fail-closed).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
SUPPORTED_EXTS = IMAGE_EXTS | {".pdf"}
_EASYOCR_READER_CACHE: dict[tuple[str, ...], object] = {}


def _find_tesseract() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    if os.name == "nt":
        win_path = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if win_path.is_file():
            return str(win_path)
    return None


def _tesseract_has_lang(tess_bin: str, lang_code: str) -> bool:
    try:
        proc = subprocess.run(
            [tess_bin, "--list-langs"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        )
        langs = {line.strip().lower() for line in (proc.stdout + "\n" + proc.stderr).splitlines()}
        return lang_code.lower() in langs
    except Exception:
        return False


def detect_engine(lang: str = "ko,en") -> str | None:
    wants_ko = any(k in lang.lower() for k in ("ko", "kor"))
    has_easyocr = importlib.util.find_spec("easyocr") is not None
    tess_bin = _find_tesseract()
    if wants_ko:
        if has_easyocr:
            return "easyocr"
        if tess_bin and _tesseract_has_lang(tess_bin, "kor"):
            return "tesseract"
        return None
    if has_easyocr:
        return "easyocr"
    if tess_bin:
        return "tesseract"
    return None


def _engine_available(engine: str, lang: str = "ko,en") -> bool:
    if engine == "easyocr":
        return importlib.util.find_spec("easyocr") is not None
    if engine == "tesseract":
        tess_bin = _find_tesseract()
        if not tess_bin:
            return False
        if any(k in lang.lower() for k in ("ko", "kor")) and not _tesseract_has_lang(tess_bin, "kor"):
            return False
        return True
    return False


def _get_easyocr_reader(langs: list[str]):
    norm = []
    for l in langs:
        l_low = l.strip().lower()
        if l_low in ("kor", "ko"):
            norm.append("ko")
        elif l_low in ("eng", "en"):
            norm.append("en")
        elif l_low:
            norm.append(l_low)
    key = tuple(norm or ["ko", "en"])
    if key not in _EASYOCR_READER_CACHE:
        import easyocr
        _EASYOCR_READER_CACHE[key] = easyocr.Reader(list(key), gpu=False, verbose=False)
    return _EASYOCR_READER_CACHE[key]


def ocr_pil_image(img, engine: str = "easyocr", lang: str = "ko,en") -> list[dict]:
    import numpy as np
    rgb = img.convert("RGB")
    if engine == "easyocr":
        reader = _get_easyocr_reader(lang.replace("+", ",").split(","))
        arr = np.array(rgb)
        raw = reader.readtext(arr, detail=1)
        blocks = []
        for bbox, text, conf in raw:
            t = str(text).strip()
            if t:
                blocks.append({"text": t, "confidence": round(float(conf), 4)})
        return blocks
    if engine == "tesseract":
        import tempfile
        tess_bin = _find_tesseract()
        if not tess_bin:
            raise RuntimeError("tesseract binary not found")
        t_langs = []
        for l in lang.replace(",", "+").split("+"):
            l_low = l.strip().lower()
            t_langs.append("kor" if l_low == "ko" else ("eng" if l_low == "en" else l_low))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            rgb.save(tmp_path, format="PNG")
            proc = subprocess.run(
                [tess_bin, tmp_path, "stdout", "-l", "+".join(t_langs)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip()[:200] or "tesseract failed")
            return [{"text": line.strip(), "confidence": None} for line in proc.stdout.splitlines() if line.strip()]
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    raise ValueError(f"Unsupported OCR engine: {engine}")


def ocr_file(path: Path, engine: str, lang: str = "ko,en") -> dict:
    from PIL import Image
    ext = path.suffix.lower()
    if ext == ".pdf":
        import fitz
        doc = fitz.open(str(path))
        pages = []
        all_blocks = []
        try:
            for idx, page in enumerate(doc):
                pix = page.get_pixmap(dpi=200)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                blocks = ocr_pil_image(img, engine=engine, lang=lang)
                page_text = "\n".join(b["text"] for b in blocks)
                pages.append({"page": idx + 1, "text": page_text, "blocks": blocks})
                all_blocks.extend(blocks)
        finally:
            doc.close()
        return {
            "engine": engine,
            "page_count": len(pages),
            "pages": pages,
            "blocks": all_blocks,
            "text": "\n\n".join(p["text"] for p in pages if p["text"]),
        }

    with Image.open(path) as img:
        blocks = ocr_pil_image(img, engine=engine, lang=lang)
    return {
        "engine": engine,
        "page_count": 1,
        "blocks": blocks,
        "text": "\n".join(b["text"] for b in blocks),
    }


def keyword_hits(blocks: list[dict], keywords: list[str]) -> list[dict]:
    hits = []
    for idx, b in enumerate(blocks):
        txt = b.get("text", "")
        low = txt.lower()
        for kw in keywords:
            if kw and kw.lower() in low:
                hits.append({"keyword": kw, "block_index": idx, "text": txt, "confidence": b.get("confidence")})
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="로컬 전용 OCR 추출기 (이미지·스캔 PDF)")
    ap.add_argument("input", help="이미지/PDF 파일 또는 디렉터리")
    ap.add_argument("--lang", default="ko,en", help="언어 코드 (기본 ko,en)")
    ap.add_argument("--engine", default=None, help="엔진 강제 지정 (easyocr|tesseract)")
    ap.add_argument("--keywords", default=None, help="쉼표 구분 키워드 히트 리포트")
    ap.add_argument("--out", "--output", dest="out", default=None, help="결과 JSON 저장 경로")
    ap.add_argument("--json", action="store_true", help="stdout에 JSON 출력")
    args = ap.parse_args(argv)

    if args.engine:
        engine = args.engine
        if not _engine_available(engine, args.lang):
            print(f"지정 OCR 엔진을 사용할 수 없습니다: {engine} (lang={args.lang})", file=sys.stderr)
            return 3
    else:
        engine = detect_engine(args.lang)
    if engine is None:
        print(
            "사용 가능한 로컬 OCR 엔진이 없습니다 (한국어 요청 시 easyocr 또는 tesseract+kor 필요).\n"
            "설치 예: pip install easyocr",
            file=sys.stderr,
        )
        return 3

    target = Path(args.input)
    if target.is_dir():
        files = sorted(p for p in target.rglob("*") if p.suffix.lower() in SUPPORTED_EXTS)
    elif target.is_file():
        files = [target]
    else:
        print(f"입력을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2
    if not files:
        print(f"OCR 가능한 파일이 없습니다: {target}", file=sys.stderr)
        return 2

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else []
    summary = {"engine": engine, "lang": args.lang, "files": []}

    for f in files:
        try:
            res = ocr_file(f, engine=engine, lang=args.lang)
        except Exception as exc:
            print(f"[FAIL] {f}: {exc}", file=sys.stderr)
            summary["files"].append({"file": str(f), "status": "failed", "error": str(exc)[:300]})
            continue
        rec = {
            "file": str(f),
            "status": "ok",
            "engine": res["engine"],
            "page_count": res["page_count"],
            "block_count": len(res["blocks"]),
            "text": res["text"],
            "blocks": res["blocks"],
        }
        if keywords:
            rec["keyword_hits"] = keyword_hits(res["blocks"], keywords)
        summary["files"].append(rec)
        if not args.json:
            print(f"[OK] {f} — {rec['block_count']}개 블록 ({len(rec['text'])}자)")

    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json or not args.out:
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
