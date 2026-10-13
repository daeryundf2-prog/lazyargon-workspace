#!/usr/bin/env python3
"""trace_financial_flow.py - 금융 거래내역(은행 CSV/XLSX) 자금 흐름 분석기.

수백~수만 행 거래내역에서 기간별·상대방별 입출금 집계, 단기 자금 순환(인출 후
재입금) 의심 체인, 상대방 랭킹, Mermaid 흐름도를 마크다운으로 산출한다.

열 이름 자동 인식 (은행별 표기 차이 흡수):
    날짜      거래일시·거래일·일자·date
    입금      입금액·입금금액·입금
    출금      출금액·출금금액·출금
    금액+구분 금액 + (입금/출금 값을 갖는 구분·유형 열)
    상대방    상대방·상대·받는분·보내는분·거래처·적요·내용·비고·description

분석 규율: 이 도구는 계좌 명세 하나가 입력이다. 다른 계좌의 내부 흐름은 볼 수
없으므로 "체인"은 본 계좌 기준 홉(입금원 → 본 계좌 → 출금처)과 동일 상대방
출금↔입금 순환만 판정한다. 그 이상의 해석은 증거가 아니다.

Exit code: 0 완료 / 2 실행 오류
CLI:
    python scripts/trace_financial_flow.py 거래내역.csv -o 자금흐름.md --window-days 7
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
from datetime import datetime

DATE_KEYS = ["거래일시", "거래일", "일자", "거래시간", "date", "datetime"]
DEPOSIT_KEYS = ["입금액", "입금금액", "입금"]
WITHDRAW_KEYS = ["출금액", "출금금액", "출금"]
AMOUNT_KEYS = ["금액", "amount"]
DIRECTION_KEYS = ["구분", "유형", "거래구분", "type"]
COUNTERPARTY_KEYS = ["상대방", "상대", "받는분", "받는사람", "보내는분", "보낸분", "거래처", "적요", "내용", "비고", "counterparty", "description"]
DEPOSIT_WORDS = {"입금", "+", "in", "credit"}
WITHDRAW_WORDS = {"출금", "-", "out", "debit"}

_NUM_RE = re.compile(r"[^\d.\-]")
# 은행별 표기 편차를 전부 포함한다 — "2024.01.16 12:30:45" 같은 점/슬래시+
# 시간 형식이 빠지면 해당 행이 경고 없이 순환·홉 탐지에서 누락되었다.
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y.%m.%d",
    "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
    "%Y%m%d",
)


def _pick(columns: list[str], keys: list[str]) -> str | None:
    lowered = {c.strip().lower(): c for c in columns}
    for key in keys:
        if key in lowered:
            return lowered[key]
    for key in keys:  # 부분 일치 (예: "거래일시(등록일)")
        for low, orig in lowered.items():
            if key in low:
                return orig
    return None


def _parse_amount(value) -> float | None:
    if value is None:
        return None
    s = str(value).replace(",", "").replace("₩", "").replace(" ", "")
    if not s or s in "-+":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(value) -> datetime | None:
    s = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def read_rows(path: str) -> tuple[list[str], list[dict]]:
    """CSV 또는 XLSX에서 (열 목록, 행 dict 목록)을 읽는다."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                with open(path, "r", encoding=encoding, newline="") as f:
                    reader = csv.DictReader(f)
                    columns = reader.fieldnames or []
                    return columns, list(reader)
            except UnicodeDecodeError:
                continue
        raise ValueError("CSV 인코딩을 판별하지 못했습니다 (utf-8/cp949)")
    if ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            raise ValueError("XLSX 지원에는 openpyxl이 필요합니다: pip install openpyxl (CSV는 바로 가능)")
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:
            raise ValueError(f"XLSX를 읽지 못했습니다 (손상 파일로 보임): {exc}")
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return [], []
        columns = [str(c) if c is not None else f"col{i}" for i, c in enumerate(rows[0])]
        records = [dict(zip(columns, r)) for r in rows[1:]]
        return columns, records
    raise ValueError(f"지원하지 않는 형식: {ext} (.csv / .xlsx)")


def normalize(columns: list[str], rows: list[dict]) -> list[dict]:
    """행을 {date, date_dt, counterparty, amount(+입/−출)} 표준형으로 변환."""
    d_col = _pick(columns, DATE_KEYS)
    in_col = _pick(columns, DEPOSIT_KEYS)
    out_col = _pick(columns, WITHDRAW_KEYS)
    amt_col = _pick(columns, AMOUNT_KEYS)
    dir_col = _pick(columns, DIRECTION_KEYS)
    cp_col = _pick(columns, COUNTERPARTY_KEYS)
    if not d_col or not cp_col:
        raise ValueError(f"필수 열을 찾지 못했습니다 (날짜·상대방). 찾은 열: {columns}")
    if not (in_col or out_col) and not (amt_col and dir_col):
        raise ValueError(f"금액 열을 찾지 못했습니다 (입금액/출금액 또는 금액+구분). 찾은 열: {columns}")

    records: list[dict] = []
    for i, row in enumerate(rows):
        pairs: list[tuple[str, float]] = []
        if in_col or out_col:
            dep = _parse_amount(row.get(in_col)) if in_col else None
            wdr = _parse_amount(row.get(out_col)) if out_col else None
            if dep:
                pairs.append(("입금", dep))
            if wdr:
                pairs.append(("출금", -abs(wdr)))
        else:
            direction = str(row.get(dir_col, "")).strip().lower()
            amount = _parse_amount(row.get(amt_col))
            if amount:
                # 구분 열이 있으면 그것이 우선이다. 부호는 구분이 없을 때만 쓴다 —
                # '출금 30000'이 양수라는 이유로 입금으로 흡수되는 사고를 막는다.
                if direction in DEPOSIT_WORDS:
                    pairs.append(("입금", abs(amount)))
                elif direction in WITHDRAW_WORDS:
                    pairs.append(("출금", -abs(amount)))
                elif amount > 0:
                    pairs.append(("입금", abs(amount)))
                else:
                    pairs.append(("출금", -abs(amount)))
        for kind, amount in pairs:
            dt = _parse_date(row.get(d_col)) if row.get(d_col) else None
            records.append({
                "row": i + 2,  # 헤더 포함 원본 행 번호
                "date": str(row.get(d_col, "")),
                "date_dt": dt,
                "counterparty": str(row.get(cp_col, "")).strip() or "(상대방 미기재)",
                "kind": kind,
                "amount": amount,
            })
    if not records:
        raise ValueError("금액이 있는 거래 행을 찾지 못했습니다")
    return records


def summarize(records: list[dict]) -> dict:
    total_in = sum(r["amount"] for r in records if r["amount"] > 0)
    total_out = sum(-r["amount"] for r in records if r["amount"] < 0)
    by_cp: dict[str, dict] = {}
    for r in records:
        agg = by_cp.setdefault(r["counterparty"], {"입금": 0.0, "출금": 0.0, "건수": 0})
        agg[r["kind"]] += abs(r["amount"])
        agg["건수"] += 1
    ranking = sorted(
        by_cp.items(),
        key=lambda kv: -(kv[1]["입금"] + kv[1]["출금"]),
    )
    return {"total_in": total_in, "total_out": total_out, "ranking": ranking}


def detect_round_trips(records: list[dict], window_days: int) -> list[dict]:
    """동일 상대방에게 출금한 뒤 기한 내 다시 입금받은 쌍 (자금 순환 의심)."""
    trips: list[dict] = []
    by_cp: dict[str, list[dict]] = {}
    for r in records:
        if r["date_dt"] is not None:
            by_cp.setdefault(r["counterparty"], []).append(r)
    for cp, recs in by_cp.items():
        recs.sort(key=lambda r: r["date_dt"])
        outs = [r for r in recs if r["kind"] == "출금"]
        ins = [r for r in recs if r["kind"] == "입금"]
        for out_r in outs:
            for i_r in ins:
                delta = (i_r["date_dt"] - out_r["date_dt"]).total_seconds() / 86400
                if 0 <= delta <= window_days:
                    trips.append({
                        "counterparty": cp, "out_date": out_r["date"], "out_amount": abs(out_r["amount"]),
                        "in_date": i_r["date"], "in_amount": abs(i_r["amount"]), "days": round(delta, 1),
                    })
    trips.sort(key=lambda t: -t["out_amount"])
    return trips


def detect_hops(records: list[dict], window_days: int) -> list[dict]:
    """입금원 → 본 계좌 → 출금처 홉. 기한 내 입금 직후 출금 쌍."""
    hops: list[dict] = []
    ins = [r for r in records if r["kind"] == "입금" and r["date_dt"] is not None]
    outs = [r for r in records if r["kind"] == "출금" and r["date_dt"] is not None]
    outs.sort(key=lambda r: r["date_dt"])
    for in_r in ins:
        for out_r in outs:
            delta = (out_r["date_dt"] - in_r["date_dt"]).total_seconds() / 86400
            if 0 <= delta <= window_days:
                hops.append({
                    "from": in_r["counterparty"], "to": out_r["counterparty"],
                    "amount": abs(out_r["amount"]), "days": round(delta, 1),
                    "in_date": in_r["date"], "out_date": out_r["date"],
                })
    hops.sort(key=lambda h: -h["amount"])
    return hops


def detect_structuring(records: list[dict], threshold: float = 10_000_000.0, lower_ratio: float = 0.8) -> list[dict]:
    """고액현금거래보고(CTR 1천만 원) 회피 목적의 스머핑(Structuring, 800만~999만 원 분할 거래) 의심 탐지."""
    min_amount = threshold * lower_ratio
    struct_records = []
    for r in records:
        amt = abs(r["amount"])
        if min_amount <= amt < threshold:
            struct_records.append({
                "row": r["row"],
                "date": r["date"],
                "date_dt": r["date_dt"],
                "counterparty": r["counterparty"],
                "kind": r["kind"],
                "amount": amt,
                "reason": f"CTR 보고 기준({threshold:,.0f}원) 직전 분할 의심 ({lower_ratio*100:.0f}%~99%)",
            })
    struct_records.sort(key=lambda x: -(x["amount"]))
    return struct_records


def detect_rapid_drain(records: list[dict], window_hours: float = 24.0, min_amount: float = 5_000_000.0, drain_ratio: float = 0.8) -> list[dict]:
    """거액 입금 후 단시간 내 잔고 급속 유출(대포통장 패스스루 / 자금세탁 의심 체인) 탐지."""
    drains: list[dict] = []
    ins = [r for r in records if r["kind"] == "입금" and r["date_dt"] is not None and abs(r["amount"]) >= min_amount]
    outs = [r for r in records if r["kind"] == "출금" and r["date_dt"] is not None]

    for in_r in ins:
        in_amt = abs(in_r["amount"])
        in_time = in_r["date_dt"]
        matched_outs = []
        for out_r in outs:
            if out_r["date_dt"] >= in_time:
                diff_hours = (out_r["date_dt"] - in_time).total_seconds() / 3600.0
                if diff_hours <= window_hours:
                    matched_outs.append((diff_hours, out_r))
        
        tot_out = sum(abs(o["amount"]) for _, o in matched_outs)
        if tot_out >= in_amt * drain_ratio:
            for diff_h, out_r in matched_outs:
                drains.append({
                    "in_date": in_r["date"],
                    "in_from": in_r["counterparty"],
                    "in_amount": in_amt,
                    "out_date": out_r["date"],
                    "out_to": out_r["counterparty"],
                    "out_amount": abs(out_r["amount"]),
                    "hours": round(diff_h, 1),
                    "drain_ratio": round((tot_out / in_amt) * 100, 1),
                })
    drains.sort(key=lambda d: -d["in_amount"])
    return drains


def render_mermaid(ranking: list[tuple[str, dict]], top: int, alert_cps: set[str] | None = None) -> str:
    lines = ["```mermaid", "flowchart LR", '  ACCT["본 계좌"]']
    alert_cps = alert_cps or set()
    alert_nodes = []
    for cp, agg in ranking[:top]:
        # 해시는 프로세스별 랜덤화(hash())를 쓰지 않는다 — 증거 도구의 산출물은
        # 같은 입력에 대해 실행마다 동일해야 재현·대조가 가능하다.
        node = "CP" + hashlib.sha1(cp.encode("utf-8")).hexdigest()[:8]
        label = f"{cp} (入{agg['입금']:,.0f} / 出{agg['출금']:,.0f})"
        lines.append(f'  {node}["{label}"]')
        if cp in alert_cps:
            alert_nodes.append(node)
        if agg["출금"] > 0:
            lines.append(f"  ACCT -->|출금 {agg['출금']:,.0f}| {node}")
        if agg["입금"] > 0:
            lines.append(f"  {node} -->|입금 {agg['입금']:,.0f}| ACCT")
    if alert_nodes:
        for an in alert_nodes:
            lines.append(f"  style {an} fill:#ffe6e6,stroke:#ff0000,stroke-width:2px")
    lines.append("```")
    return "\n".join(lines)


def render_markdown(
    records: list[dict],
    summary: dict,
    trips: list[dict],
    hops: list[dict],
    window_days: int,
    top: int,
    structurings: list[dict] | None = None,
    drains: list[dict] | None = None,
) -> str:
    structurings = structurings or []
    drains = drains or []
    lines = ["# 자금 흐름 분석 보고서\n"]
    lines.append(f"- **거래 건수:** {len(records):,}건")
    lines.append(f"- **총 입금:** {summary['total_in']:,.0f}원 / **총 출금:** {summary['total_out']:,.0f}원")
    lines.append(f"- **분석 창:** {window_days}일 (순환·홉 판정 기준)\n")
    undated = sum(1 for r in records if r["date_dt"] is None)
    if undated:
        lines.append(
            f"> ⚠️ **타임스탬프를 파싱하지 못한 거래 {undated}건**이 순환·홉 탐지에서 제외되었다"
            f" (랭킹에는 포함). 지원 형식: {', '.join(_DATE_FORMATS)}\n"
        )

    # 1. 이상거래(AML) 경고 섹션 (존재 시 최상단 우선 노출)
    alert_cps: set[str] = set()
    if structurings or drains:
        lines.append("## ⚠️ 이상거래(AML) 의심 패턴 감지\n")
        if structurings:
            lines.append("### 고액현금보고(CTR) 회피 의심 분할 거래 (스머핑 / Structuring)")
            lines.append("| 일시 | 상대방 | 구분 | 거래금액 | 의심 사유 |")
            lines.append("| :-- | :-- | :--: | ---: | :-- |")
            for s in structurings[:top]:
                alert_cps.add(s["counterparty"])
                lines.append(f"| {s['date']} | {s['counterparty']} | {s['kind']} | {s['amount']:,.0f}원 | {s['reason']} |")
            lines.append("")

        if drains:
            lines.append("### 거액 입금 후 단기 급속 유출 (대포통장 패스스루 / 세탁 의심)")
            lines.append("| 입금일시 | 입금원 | 입금액 | 출금일시 | 출금처 | 출금액 | 경과시간 | 유출률 |")
            lines.append("| :-- | :-- | ---: | :-- | :-- | ---: | :--: | :--: |")
            for d in drains[:top]:
                alert_cps.add(d["in_from"])
                alert_cps.add(d["out_to"])
                lines.append(
                    f"| {d['in_date']} | {d['in_from']} | {d['in_amount']:,.0f}원 | "
                    f"{d['out_date']} | {d['out_to']} | {d['out_amount']:,.0f}원 | "
                    f"{d['hours']}시간 | {d['drain_ratio']}% |"
                )
            lines.append("")

    lines.append("## 상대방별 랭킹 (거래 규모 순)\n")
    lines.append("| 순위 | 상대방 | 입금합 | 출금합 | 건수 |")
    lines.append("| :--: | :-- | ---: | ---: | ---: |")
    for i, (cp, agg) in enumerate(summary["ranking"][:top], 1):
        lines.append(f"| {i} | {cp} | {agg['입금']:,.0f} | {agg['출금']:,.0f} | {agg['건수']} |")

    lines.append("\n## 자금 순환 의심 (동일 상대방 출금→재입금)\n")
    if trips:
        lines.append("| 상대방 | 출금일 | 출금액 | 재입금일 | 재입금액 | 경과일 |")
        lines.append("| :-- | :-- | ---: | :-- | ---: | ---: |")
        for t in trips[:top]:
            alert_cps.add(t["counterparty"])
            lines.append(
                f"| {t['counterparty']} | {t['out_date']} | {t['out_amount']:,.0f} | "
                f"{t['in_date']} | {t['in_amount']:,.0f} | {t['days']} |"
            )
    else:
        lines.append("해당 없음 — 기간 내 동일 상대방 출금→재입금 쌍이 없습니다.")

    lines.append("\n## 단기 홉 (입금원 → 본 계좌 → 출금처)\n")
    if hops:
        lines.append("| 입금원 | 출금처 | 금액 | 경과일 | 입금일 | 출금일 |")
        lines.append("| :-- | :-- | ---: | ---: | :-- | :-- |")
        for h in hops[:top]:
            lines.append(f"| {h['from']} | {h['to']} | {h['amount']:,.0f} | {h['days']} | {h['in_date']} | {h['out_date']} |")
    else:
        lines.append("해당 없음.")

    lines.append("\n## 흐름도 (Mermaid)\n")
    lines.append(render_mermaid(summary["ranking"], top, alert_cps=alert_cps))
    lines.append("\n> 본 보고서는 단일 계좌 명세 기반의 통계입니다. 순환·홉·이상거래 표시는 의심 패턴일 뿐이며, 자금세탁 등 위법성 판단은 법률 전문가의 검토 대상입니다.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="거래내역 자금 흐름 분석기 (랭킹·순환 감지·AML 이상거래·Mermaid)")
    p.add_argument("input", help="거래내역 파일 (.csv / .xlsx)")
    p.add_argument("--output", "-o", default="", help="보고서 마크다운 경로 (미지정 시 stdout)")
    p.add_argument("--window-days", type=int, default=7, help="순환·홉 판정 기간(일, 기본 7)")
    p.add_argument("--top", type=int, default=20, help="랭킹·표에 표시할 상위 건수 (기본 20)")
    p.add_argument("--ctr-threshold", type=float, default=10_000_000.0, help="고액현금보고(CTR) 임계치(기본 1천만 원)")
    p.add_argument("--drain-hours", type=float, default=24.0, help="급속 유출 판정 시간(기본 24시간)")
    args = p.parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"error: 파일을 찾을 수 없습니다: {args.input}", file=sys.stderr)
        return 2
    try:
        columns, rows = read_rows(args.input)
        records = normalize(columns, rows)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = summarize(records)
    trips = detect_round_trips(records, args.window_days)
    hops = detect_hops(records, args.window_days)
    structurings = detect_structuring(records, threshold=args.ctr_threshold)
    drains = detect_rapid_drain(records, window_hours=args.drain_hours)
    md = render_markdown(
        records, summary, trips, hops, args.window_days, args.top,
        structurings=structurings, drains=drains,
    )

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"[OK] 자금 흐름 보고서 저장: {args.output}")
    else:
        print(md)
    return 0


# ── 콘솔 하드닝 (#84) ───────────────────────────────────────────────
import os as _os  # noqa: E402
import sys as _sys  # noqa: E402

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import console as _console  # noqa: E402

if __name__ == "__main__":
    _console.force_utf8_console()
    raise SystemExit(main())
