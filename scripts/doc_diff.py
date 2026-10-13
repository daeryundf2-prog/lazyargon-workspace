#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doc_diff.py — 신구대비(신구조문대비표) 텍스트 비교 리포트

두 텍스트 파일을 줄 단위로 비교해 '현행 / 신안 / 비고' 형태의
신구대비표를 만든다. 계약서 개정 검토, 법령 개정 대조, 회의록 변경
확인에 쓴다. difflib만 쓰므로 외부 의존성이 없다.

사용:
    python scripts/doc_diff.py old.txt new.txt            # 텍스트 출력
    python scripts/doc_diff.py old.txt new.txt --markdown -o diff.md
    python scripts/doc_diff.py old.txt new.txt --json

알려진 한계:
- 줄 단위 비교다. 문장 내 한 단어만 바뀐 경우 해당 줄 전체가
  '변경'으로 표시된다(셀 안에서 old→new로 표기).
- 표 구조나 서식 차이는 비교하지 않는다.
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path


def build_rows(old: list[str], new: list[str]) -> list[dict]:
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    rows = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append({"old": old[i1 + k], "new": new[j1 + k], "note": "동일"})
        elif tag == "delete":
            for line in old[i1:i2]:
                rows.append({"old": line, "new": "", "note": "삭제"})
        elif tag == "insert":
            for line in new[j1:j2]:
                rows.append({"old": "", "new": line, "note": "신설"})
        else:  # replace — 길이 맞춰 쌍으로 표시
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                rows.append({
                    "old": old[i1 + k] if i1 + k < i2 else "",
                    "new": new[j1 + k] if j1 + k < j2 else "",
                    "note": "변경",
                })
    return rows


def to_markdown(rows: list[dict], name_a: str, name_b: str) -> str:
    lines = [
        "| # | 현행 | 신안 | 비고 |",
        "|---|---|---|---|",
    ]
    for idx, r in enumerate(rows, 1):
        old = r["old"].replace("|", "\\|")
        new = r["new"].replace("|", "\\|")
        lines.append(f"| {idx} | {old} | {new} | {r['note']} |")
    changed = sum(1 for r in rows if r["note"] != "동일")
    return f"# 신구대비표: {name_a} → {name_b}\n\n변경 {changed}행 / 전체 {len(rows)}행\n\n" + "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="신구대비 텍스트 비교 리포트")
    ap.add_argument("old", help="현행(구) 텍스트 파일")
    ap.add_argument("new", help="신안(신) 텍스트 파일")
    ap.add_argument("--markdown", action="store_true", help="마크다운 표 출력")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("-o", "--output", default=None, help="출력 파일 경로")
    ap.add_argument("--all", action="store_true", help="동일 행도 포함 (기본: 변경만)")
    args = ap.parse_args(argv)

    old_p, new_p = Path(args.old), Path(args.new)
    for p in (old_p, new_p):
        if not p.is_file():
            print(f"파일을 찾을 수 없습니다: {p}", file=sys.stderr)
            return 2

    old_lines = old_p.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines = new_p.read_text(encoding="utf-8", errors="replace").splitlines()
    rows = build_rows(old_lines, new_lines)
    if not args.all:
        rows = [r for r in rows if r["note"] != "동일"]

    if args.json:
        out = json.dumps({"old": str(old_p), "new": str(new_p), "rows": rows},
                         ensure_ascii=False, indent=2)
    elif args.markdown:
        out = to_markdown(rows, old_p.name, new_p.name)
    else:
        if not rows:
            out = "두 파일이 동일합니다 (변경 없음)"
        else:
            out = "\n".join(
                f"[{r['note']}] -{r['old']!r}  +{r['new']!r}" for r in rows
            )
            out = f"변경 {len(rows)}행\n" + out

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"→ {args.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
