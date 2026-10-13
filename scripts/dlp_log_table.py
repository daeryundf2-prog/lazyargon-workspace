#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dlp_log_table.py — 이미 확보한 DLP/로그 CSV를 체크리스트 표로 정리

dlp-leakage-detector 스킬의 4축(검색·수집·반출·정리)에 맞춰
사용자가 확보한 로그 CSV를 시간순 Markdown 표로 옮긴다.

이 도구는 '정리'만 한다 — 유출을 탐지하거나 결론내지 않는다.
CSV에 없는 행은 만들지 않으며, 행이 없으면 빈 표를 출력한다.

사용:
    python scripts/dlp_log_table.py dlp_events.csv
    python scripts/dlp_log_table.py logs.csv --time-col timestamp \
        --event-col action --src-col agent --phase-col phase

CSV 요구사항: 헤더 행 필수. --phase-col이 주어지면 그 값으로
4축 그룹핑하고, 없으면 단일 시간순 표로 출력한다.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PHASES = ["검색/준비", "수집/압축", "반출", "정리"]


def load_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader]
        return list(reader.fieldnames or []), rows


def pick_col(headers: list[str], requested: str | None,
             fallbacks: list[str]) -> str | None:
    if requested:
        return requested if requested in headers else None
    for c in fallbacks:
        for h in headers:
            if c in h.lower():
                return h
    return None


def to_markdown(rows: list[dict], time_col: str | None, event_col: str | None,
                src_col: str | None, phase_col: str | None) -> str:
    lines = [
        "# 유출 교차분석 로그 정리 (사용자 제공 로그의 재배열 — 탐지 아님)",
        "",
        "> 본 표는 입력 CSV의 행을 시간순으로 옮긴 것이다. 없는 로그를",
        "> 보강하지 않으며, 유출 여부 판단은 분석가의 몫이다.",
        "",
    ]

    def cell(r: dict, col: str | None) -> str:
        v = r.get(col, "") if col else ""
        return str(v).replace("|", "\\|").strip()

    def emit(group_rows: list[dict], title: str | None) -> None:
        if title:
            lines.append(f"## {title}")
        lines.extend(["| 시각 | 행위 | 출처 로그 | 비고 |", "|---|---|---|---|"])
        for r in group_rows:
            extras = [f"{k}={v}" for k, v in r.items()
                      if k not in {time_col, event_col, src_col, phase_col} and v]
            lines.append(
                f"| {cell(r, time_col)} | {cell(r, event_col)} | "
                f"{cell(r, src_col)} | {'; '.join(extras)} |")
        lines.append("")

    rows_sorted = sorted(rows, key=lambda r: r.get(time_col, "")) if time_col else rows
    if phase_col:
        used = set()
        for ph in PHASES:
            grp = [r for r in rows_sorted if str(r.get(phase_col, "")).strip() == ph]
            used.update(id(r) for r in grp)
            if grp:
                emit(grp, ph)
        rest = [r for r in rows_sorted if id(r) not in used]
        if rest:
            emit(rest, f"기타 ({phase_col} 미분류)")
    else:
        emit(rows_sorted, None)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="확보된 로그 CSV → 시간순 체크리스트 표 (탐지 아님, 정리)")
    ap.add_argument("input", help="CSV 경로")
    ap.add_argument("--time-col", default=None)
    ap.add_argument("--event-col", default=None)
    ap.add_argument("--src-col", default=None)
    ap.add_argument("--phase-col", default=None)
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args(argv)

    src = Path(args.input)
    if not src.is_file():
        print(f"입력을 찾을 수 없습니다: {src}", file=sys.stderr)
        return 2

    headers, rows = load_rows(src)
    if not rows:
        print("로그 행이 없습니다 — 빈 표는 만들지 않습니다.", file=sys.stderr)
        return 3

    time_col = pick_col(headers, args.time_col,
                        ["time", "date", "시각", "일시", "timestamp"])
    event_col = pick_col(headers, args.event_col,
                         ["event", "action", "행위", "내용", "operation"])
    src_col = pick_col(headers, args.src_col, ["src", "source", "출처", "agent"])
    phase_col = pick_col(headers, args.phase_col, ["phase", "단계"])

    for name, col, headers_l in [("--time-col", args.time_col, headers),
                                 ("--event-col", args.event_col, headers),
                                 ("--src-col", args.src_col, headers),
                                 ("--phase-col", args.phase_col, headers)]:
        if col and col not in headers_l:
            print(f"{name} '{col}'이(가) CSV 헤더에 없습니다: {headers_l}",
                  file=sys.stderr)
            return 2

    md = to_markdown(rows, time_col, event_col, src_col, phase_col)
    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"로그 정리 표 → {args.output} ({len(rows)}행)", file=sys.stderr)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
