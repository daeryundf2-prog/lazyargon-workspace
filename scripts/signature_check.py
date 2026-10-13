#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
signature_check.py — 매직바이트 vs 확장자 불일치 감사

파일 시그니처(매직바이트)를 읽어 확장자와 대조한다.
'.jpg인 척하는 실행파일', '.docx로 위장된 스크립트' 같은
위장 파일을 1차 스크리닝한다. 표준 라이브러리만 사용.

사용:
    python scripts/signature_check.py evidence/
    python scripts/signature_check.py evidence/ --json

판정:
    MATCH     — 시그니처가 확장자와 일치
    MISMATCH  — 시그니처가 다른 형식을 가리킴 (위장 의심)
    UNKNOWN   — 알려진 시그니처가 없음 (텍스트·날파일 등 — 정상일 수 있음)

알려진 한계:
- 매직바이트는 선두 수 바이트만 본다. 시그니처를 위조한 파일은 못 잡는다.
- UNKNOWN은 '이상'이 아니다 — 시그니처 없는 텍스트류가 정상적으로 걸린다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# (시그니처, 오프셋, 형식명, 기대 확장자들)
SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", 0, "PNG", {".png"}),
    (b"\xff\xd8\xff", 0, "JPEG", {".jpg", ".jpeg"}),
    (b"GIF87a", 0, "GIF", {".gif"}),
    (b"GIF89a", 0, "GIF", {".gif"}),
    (b"RIFF", 0, "RIFF", {".wav", ".avi", ".webp"}),  # 세부는 8바이트에서 구분
    (b"%PDF", 0, "PDF", {".pdf"}),
    (b"PK\x03\x04", 0, "ZIP/DOCX/HWPX", {".zip", ".docx", ".xlsx", ".pptx", ".hwpx", ".jar"}),
    (b"\x7fELF", 0, "ELF 실행파일", {".elf", ".so", ""}),
    (b"MZ", 0, "PE 실행파일", {".exe", ".dll", ".sys", ".scr", ".com"}),
    (b"\x1f\x8b", 0, "GZIP", {".gz", ".tgz"}),
    (b"Rar!\x1a\x07", 0, "RAR", {".rar"}),
    (b"7z\xbc\xaf\x27\x1c", 0, "7Z", {".7z"}),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0, "CFB (HWP/DOC/XLS)", {".hwp", ".doc", ".xls", ".ppt", ".msi"}),
    (b"SQLite format 3", 0, "SQLite", {".db", ".sqlite", ".sqlite3"}),
    (b"ID3", 0, "MP3", {".mp3"}),
    (b"\xff\xfb", 0, "MP3", {".mp3"}),
    (b"fLaC", 0, "FLAC", {".flac"}),
    (b"OggS", 0, "OGG", {".ogg", ".opus"}),
    (b"\x00\x00\x00", 0, "ISOBMFF", {".mp4", ".m4a", ".mov"}),  # ftyp 박스
    (b"\x1a\x45\xdf\xa3", 0, "MKV/WebM", {".mkv", ".webm"}),
    (b"<?xm", 0, "XML", {".xml", ".svg"}),
]

# ISOBMFF 세부 확인: 4바이트가 길이 + 'ftyp'
def _is_isobmff(header: bytes) -> bool:
    return len(header) >= 8 and header[4:8] == b"ftyp"


def _is_json(header: bytes) -> bool:
    s = header.lstrip()
    return s[:1] in (b"{", b"[")


def sniff(path: Path) -> tuple[str, set[str]]:
    """(감지된 형식명, 기대 확장자 집합) 또는 ('UNKNOWN', set())."""
    try:
        with path.open("rb") as f:
            header = f.read(32)
    except OSError:
        return "UNREADABLE", set()
    if not header:
        return "EMPTY", set()
    for sig, offset, name, exts in SIGNATURES:
        if name == "JSON?":
            continue  # 별도 처리
        if name == "ISOBMFF":
            if _is_isobmff(header):
                return name, exts
            continue
        if header[offset:offset + len(sig)] == sig:
            return name, exts
    if _is_json(header):
        return "JSON?", {".json"}
    return "UNKNOWN", set()


def audit_file(path: Path) -> dict:
    name, exts = sniff(path)
    ext = path.suffix.lower()
    if name in ("UNKNOWN", "UNREADABLE", "EMPTY"):
        status = name
    elif not exts or ext in exts:
        status = "MATCH"
    else:
        status = "MISMATCH"
    return {"file": str(path), "detected": name, "ext": ext, "status": status}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="매직바이트 vs 확장자 위장 감사")
    ap.add_argument("target", help="감사할 파일 또는 디렉터리")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if target.is_dir():
        files = sorted(p for p in target.rglob("*") if p.is_file())
    elif target.is_file():
        files = [target]
    else:
        print(f"대상을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2

    records = [audit_file(f) for f in files]
    mismatches = [r for r in records if r["status"] == "MISMATCH"]

    if args.json:
        print(json.dumps({
            "total": len(records),
            "match": sum(1 for r in records if r["status"] == "MATCH"),
            "mismatch": len(mismatches),
            "unknown": sum(1 for r in records if r["status"] == "UNKNOWN"),
            "records": records,
        }, ensure_ascii=False, indent=2))
    else:
        for r in records:
            if r["status"] == "MISMATCH":
                print(f"[MISMATCH] {r['file']}: 확장자 {r['ext'] or '(없음)'} ≠ 실제 {r['detected']}")
        print(f"{len(records)}개 중 MATCH {sum(1 for r in records if r['status']=='MATCH')}, "
              f"MISMATCH {len(mismatches)}, UNKNOWN "
              f"{sum(1 for r in records if r['status'] in ('UNKNOWN','EMPTY'))}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
