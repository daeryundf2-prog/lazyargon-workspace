#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_audit.py — PDF 구조 표면 감사 (stdlib 전용)

증거로 들어온 PDF를 열지 않고 구조만 훑는다:
- 암호화 여부 (/Encrypt)
- Info 메타데이터 (작성자·생성도구·생성/수정일)
- 능동 콘텐츠 신호 (/JavaScript, /JS, /Launch, /OpenAction, /AA)
- 임베딩 파일 (/EmbeddedFile)
- 대략적 페이지 수 (/Type /Page 개수)

사용:
    python scripts/pdf_audit.py evidence/
    python scripts/pdf_audit.py docs/a.pdf --json

알려진 한계:
- 바이트 패턴 기반 표면 감사다 — 객체 스트림(PDF 1.5+)에 숨은
  /Encrypt·/JavaScript는 못 잡는다. 정밀 파싱은 qpdf/pikepdf 영역.
- 암호화·JS 탐지는 '의심 신호'다 — 악성 여부 판정이 아니다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

_PDF_RE = {
    "author": re.compile(rb"/Author\s*\(([^)]*)\)"),
    "creator": re.compile(rb"/Creator\s*\(([^)]*)\)"),
    "producer": re.compile(rb"/Producer\s*\(([^)]*)\)"),
    "creation_date": re.compile(rb"/CreationDate\s*\(([^)]*)\)"),
    "mod_date": re.compile(rb"/ModDate\s*\(([^)]*)\)"),
}
# PDF 이름 토큰은 뒤에 영문자가 오면 같은 토큰이 아니다 — /EncryptMetadata가
# /Encrypt로 오인되지 않게 전부 단어 경계로 검사한다.
_ACTIVE_SIGNALS = [
    (re.compile(rb"/JavaScript(?![a-zA-Z])"), "javascript"),
    (re.compile(rb"/JS(?![a-zA-Z])"), "js_action"),
    (re.compile(rb"/Launch(?![a-zA-Z])"), "launch_action"),
    (re.compile(rb"/OpenAction(?![a-zA-Z])"), "open_action"),
    (re.compile(rb"/AA(?![a-zA-Z])"), "additional_actions"),
    (re.compile(rb"/EmbeddedFile(?![a-zA-Z])"), "embedded_file"),
    (re.compile(rb"/RichMedia(?![a-zA-Z])"), "rich_media"),
]
_ENCRYPT_RE = re.compile(rb"/Encrypt(?![a-zA-Z])")
_PAGE_RE = re.compile(rb"/Type\s*/Page(?!s)")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _decode_pdf_string(raw: bytes) -> str:
    """( ) 리터럴 문자열 → UTF-16BE/UTF-8/Latin-1 추정 디코드."""
    s = raw.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
    if s.startswith(b"\xfe\xff"):
        return s[2:].decode("utf-16-be", errors="replace")
    for enc in ("utf-8", "latin-1"):
        try:
            return s.decode(enc)
        except UnicodeDecodeError:
            continue
    return s.decode("utf-8", errors="replace")


def audit_pdf(path: Path) -> dict:
    rec: dict = {"file": str(path), "sha256": sha256_file(path), "is_pdf": False}
    try:
        data = path.read_bytes()
    except OSError as e:
        rec["error"] = str(e)
        return rec
    if not data.startswith(b"%PDF"):
        rec["error"] = "PDF 시그니처 없음"
        return rec

    rec["is_pdf"] = True
    m = re.match(rb"%PDF-(\d+\.\d+)", data)
    rec["pdf_version"] = m.group(1).decode() if m else "unknown"
    rec["size_bytes"] = len(data)
    rec["encrypted"] = bool(_ENCRYPT_RE.search(data))
    rec["linearized"] = b"/Linearized" in data[:1024]
    rec["page_count"] = len(_PAGE_RE.findall(data))
    rec["startxref_present"] = b"startxref" in data[-4096:]
    rec["eof_marker_present"] = b"%%EOF" in data[-4096:]

    signals = [label for rx, label in _ACTIVE_SIGNALS if rx.search(data)]
    rec["active_signals"] = signals
    rec["suspicious"] = bool(signals)

    meta = {}
    for key, rx in _PDF_RE.items():
        mm = rx.search(data)
        if mm:
            meta[key] = _decode_pdf_string(mm.group(1))
    rec["metadata"] = meta

    notes = []
    if rec["encrypted"]:
        notes.append("암호화됨 — 내용 검사 불가, 암호 해제본 확보 필요")
    if "javascript" in signals or "js_action" in signals:
        notes.append("JavaScript 포함 — 정적 문서가 아님, 주의")
    if "embedded_file" in signals:
        notes.append("임베딩 첨부 파일 존재 — 별도 추출·감사 대상")
    if not rec["eof_marker_present"]:
        notes.append("EOF 마커 없음 — 잘렸거나 비표준 생성 가능성")
    rec["notes"] = notes
    return rec


def scan(root: Path) -> list[dict]:
    files = sorted(p for p in root.rglob("*")
                   if p.is_file() and p.suffix.lower() == ".pdf")
    return [audit_pdf(f) for f in files]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PDF 구조 표면 감사 (로컬 전용)")
    ap.add_argument("target", help="PDF 파일 또는 디렉터리")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if target.is_dir():
        records = scan(target)
    elif target.is_file():
        records = [audit_pdf(target)]
    else:
        print(f"대상을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"pdf_files": len(records), "records": records},
                         ensure_ascii=False, indent=2))
    else:
        for r in records:
            if not r.get("is_pdf"):
                print(f"[비PDF] {r['file']}: {r.get('error', '')}")
                continue
            flag = "⚠" if r["suspicious"] or r["encrypted"] else " "
            print(f"[{flag}] {r['file']}: v{r['pdf_version']}, "
                  f"{r['page_count']}p, 암호화={r['encrypted']}, "
                  f"능동신호={','.join(r['active_signals']) or '없음'}")
            for n in r["notes"]:
                print(f"      · {n}")
    # 암호화·능동 신호가 하나라도 있으면 1 반환 (주의 필요 표시)
    return 1 if any(r.get("suspicious") or r.get("encrypted") for r in records) else 0


if __name__ == "__main__":
    sys.exit(main())
