#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pii_mask.py — 한국형 개인정보 탐지·마스킹 (외부 전송 전 프리플라이트)

증거 텍스트·전사문·리포트 초안을 외부 API/리뷰어에게 보내기 전에
개인정보 패턴을 탐지하고 마스킹한다. 표준 라이브러리만 사용한다.
AI 모델이 아니라 정규식 기반이므로 결과는 결정적(deterministic)이다.

사용:
    python scripts/pii_mask.py report_draft.md                  # 탐지 리포트만
    python scripts/pii_mask.py report_draft.md --mask -o out.md # 마스킹본 생성
    python scripts/pii_mask.py dir/ --mask --in-place           # 디렉터리 일괄
    python scripts/pii_mask.py file.txt --json

탐지 패턴:
    - 주민등록번호 (6자리-7자리, 첫 자리 1-4)
    - 여권번호, 운전면허번호
    - 휴대전화·유선전화
    - 카드번호 (4-4-4-4)
    - 계좌번호 (숫자-숫자-숫자 형태)
    - 이메일 주소

알려진 한계:
- 정규식 기반이라 맥락 판단을 하지 않는다. '2026-03-01' 같은 날짜와
  전화번호 구분은 패턴으로만 한다. 오탐/미탐 가능성이 있으므로
  마스킹본도 사람이 검토할 것.
- 이름·주소 같은 비정형 PII는 탐지하지 못한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log", ".tsv", ".xml", ".html"}

PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # (이름, 패턴, 마스킹 치환)
    ("주민등록번호", re.compile(r"\b(\d{6})-([1-4]\d{6})\b"), r"\1-*******"),
    ("여권번호", re.compile(r"\b([MSRmsr]\d{8})\b"), r"********"),
    ("운전면허번호", re.compile(r"\b(\d{2}-\d{2}-\d{6}-\d{2})\b"), r"**-**-******-**"),
    ("휴대전화", re.compile(r"\b(01[016789])-?(\d{3,4})-?(\d{4})\b"), r"\1-****-\3"),
    ("유선전화", re.compile(r"\b(0\d{1,2})-?(\d{3,4})-?(\d{4})\b"), r"\1-****-\3"),
    ("카드번호", re.compile(r"\b(\d{4})[- ]?(\d{4})[- ]?(\d{4})[- ]?(\d{4})\b"), r"\1-****-****-\4"),
    ("계좌번호", re.compile(r"\b(\d{3,6})-(\d{2,6})-(\d{4,8})\b"), r"\1-**-******"),
    ("이메일", re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"), r"***@\2"),
]

# 계좌번호 패턴은 날짜(YYYY-MM-DD 등)와 겹칠 수 있어 후처리로 제외한다
DATE_LIKE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{2,4}-\d{1,2}-\d{1,2}$")


def detect_in_text(text: str) -> list[dict]:
    findings = []
    for name, pattern, _repl in PATTERNS:
        for m in pattern.finditer(text):
            if name == "계좌번호" and DATE_LIKE_RE.match(m.group(0)):
                continue
            line = text.count("\n", 0, m.start()) + 1
            findings.append({"type": name, "line": line, "match": m.group(0)})
    return findings


def mask_text(text: str) -> str:
    def _mask_account(m: re.Match) -> str:
        return m.group(1) + "-**-******" if not DATE_LIKE_RE.match(m.group(0)) else m.group(0)

    out = text
    for name, pattern, repl in PATTERNS:
        if name == "계좌번호":
            out = pattern.sub(_mask_account, out)
        else:
            out = pattern.sub(repl, out)
    return out


def process_file(path: Path, mask: bool, out_path: Path | None, in_place: bool) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"file": str(path), "error": str(e)}
    findings = detect_in_text(text)
    record: dict = {"file": str(path), "pii_count": len(findings), "findings": findings}
    if mask and findings:
        masked = mask_text(text)
        dest = path if in_place else (out_path or path.with_name(path.stem + ".masked" + path.suffix))
        dest.write_text(masked, encoding="utf-8")
        record["masked_to"] = str(dest)
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="한국형 개인정보 탐지·마스킹 프리플라이트")
    ap.add_argument("target", help="텍스트 파일 또는 디렉터리")
    ap.add_argument("--mask", action="store_true", help="마스킹본 생성")
    ap.add_argument("--in-place", action="store_true", help="원본 덮어쓰기 (원본 보존 원칙상 권장 안 함)")
    ap.add_argument("-o", "--output", default=None, help="단일 파일 마스킹 출력 경로")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if target.is_dir():
        files = sorted(p for p in target.rglob("*") if p.suffix.lower() in TEXT_EXTS)
    elif target.is_file():
        files = [target]
    else:
        print(f"대상을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2
    if not files:
        print(f"텍스트 파일이 없습니다: {target}", file=sys.stderr)
        return 2

    out_path = Path(args.output) if args.output else None
    records = [process_file(f, args.mask, out_path if len(files) == 1 else None, args.in_place)
               for f in files]

    total = sum(r.get("pii_count", 0) for r in records)
    if args.json:
        print(json.dumps({"files": records, "total_pii": total}, ensure_ascii=False, indent=2))
    else:
        for r in records:
            if r.get("pii_count"):
                print(f"{r['file']}: {r['pii_count']}건" + (f" → 마스킹: {r['masked_to']}" if r.get("masked_to") else ""))
                for fd in r["findings"]:
                    print(f"    L{fd['line']}  {fd['type']}: {fd['match']}")
        if total == 0:
            print(f"개인정보 패턴 미탐지 ({len(files)}개 파일)")
        else:
            print(f"총 {total}건 탐지" + (" — 마스킹 완료" if args.mask else " — --mask로 마스킹본 생성 가능"))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
