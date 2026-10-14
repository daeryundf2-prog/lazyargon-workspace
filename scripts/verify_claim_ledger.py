#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_claim_ledger.py — Unified Forensic & Legal Claim Ledger Protocol Verifier (Section 6)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TWO_PART_CCTLDS = {
    "co.uk", "ac.uk", "org.uk", "gov.uk",
    "co.kr", "go.kr", "or.kr", "ne.kr", "re.kr",
    "com.au", "net.au", "org.au",
    "co.jp", "ne.jp", "ac.jp",
    "com.cn", "org.cn", "gov.cn",
}

INVALID_COUNTER_VALUES = {"n/a", "na", "-", "—", "none", "null", "", "없음", "해당없음", "미수행", "미검증"}

_DEFAULT_STATUTE_NAMES = [
    "민법", "형법", "개인정보보호법", "정보통신망법", "정보통신망 이용촉진 및 정보보호 등에 관한 법률",
    "상법", "민사소송법", "형사소송법", "행정소송법", "근로기준법", "부정경쟁방지법", "부정경쟁방지 및 영업비밀보호에 관한 법률",
    "전자문서법", "전자문서 및 전자거래 기본법", "특정금융정보법", "특정 금융거래정보의 보고 및 이용 등에 관한 법률",
    "전자상거래법", "전자상거래 등에서의 소비자보호에 관한 법률", "자본시장법", "자본시장과 금융투자업에 관한 법률",
    "신용정보법", "신용정보의 이용 및 보호에 관한 법률", "소비자기본법", "가사소송법", "특허법", "저작권법",
    "도로교통법", "의료법",
]


def _build_all_statute_names() -> str:
    names = set(_DEFAULT_STATUTE_NAMES)
    bounds_path = Path(__file__).resolve().parent.parent / "data" / "statute_bounds.json"
    if bounds_path.exists():
        try:
            data = json.loads(bounds_path.read_text(encoding="utf-8"))
            bounds = data.get("bounds", {})
            if isinstance(bounds, dict):
                names.update(str(k) for k in bounds.keys())
        except Exception:
            pass
    sorted_names = sorted(names, key=len, reverse=True)
    return "|".join(re.escape(n) for n in sorted_names)


ALL_STATUTE_NAMES = _build_all_statute_names()


def extract_registrable_domain(hostname: str) -> str:
    clean = hostname.lower().strip()
    if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", clean):
        return clean
    if clean.startswith("www."):
        clean = clean[4:]
    parts = clean.split(".")
    if len(parts) <= 2:
        return clean
    last2 = ".".join(parts[-2:])
    if last2 in TWO_PART_CCTLDS and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s)\]><\",]+", text, re.IGNORECASE)


def extract_unique_domains(text: str) -> list[str]:
    urls = extract_urls(text)
    domains: set[str] = set()
    for u in urls:
        try:
            parsed = urlparse(u)
            if parsed.hostname:
                domains.add(extract_registrable_domain(parsed.hostname))
        except Exception:
            pass
    return sorted(list(domains))


def extract_forensic_artifacts(text: str) -> list[str]:
    """Extract distinct forensic artifact references or hashes from sources column."""
    artifacts: set[str] = set()
    hashes = re.findall(r"\b[a-fA-F0-9]{32,64}\b", text)
    for h in hashes:
        artifacts.add(h.lower()[:16])
    file_matches = re.findall(
        r"(?:\$?[A-Za-z0-9_.-]+|\b[\w.-]+)\.(?:evtx|mft|pcap|pcapng|raw|dd|e01|json|jsonl|txt|log|csv|pf|reg|dat|sqlite|db|vhdx|vmdk)\b",
        text,
        re.IGNORECASE,
    )
    for f in file_matches:
        artifacts.add(f.lower())
    special_matches = re.findall(r"\$(?:MFT|LogFile|UsnJrnl|Boot|Volume|Extend)\b", text, re.IGNORECASE)
    for s in special_matches:
        artifacts.add(s.lower())
    return sorted(list(artifacts))


def extract_legal_authorities(text: str) -> list[str]:
    """Extract distinct legal statutes and precedents from sources column."""
    auths: set[str] = set()
    statutes = re.findall(rf"(?:{ALL_STATUTE_NAMES})\s*제\s*\d+\s*조(?:\s*의\s*\d+)?", text)
    for s in statutes:
        auths.add(re.sub(r"\s+", "", s))
    precedents = re.findall(r"\d{4}\s*[가-힣]{1,4}\s*\d+", text)
    for p in precedents:
        auths.add(re.sub(r"\s+", "", p))
    return sorted(list(auths))


def _split_markdown_row(line: str) -> list[str]:
    content = line.strip()
    if content.startswith("|"):
        content = content[1:]
    if content.endswith("|"):
        content = content[:-1]
    raw_cells = re.split(r"(?<!\\)\|", content)
    return [c.strip().replace(r"\|", "|") for c in raw_cells]


def parse_markdown_table(markdown: str) -> list[dict[str, str]]:
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in markdown.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("|") and ("|" in trimmed[1:] or trimmed.endswith("|")):
            current_block.append(trimmed)
        else:
            if current_block:
                blocks.append(current_block)
                current_block = []
    if current_block:
        blocks.append(current_block)

    claim_re = re.compile(r"claim|주장|항목", re.IGNORECASE)
    status_re = re.compile(r"status|상태", re.IGNORECASE)

    target_block = None
    for block in blocks:
        if len(block) >= 2:
            headers = [c.lower() for c in _split_markdown_row(block[0])]
            if any(claim_re.search(h) for h in headers) and any(status_re.search(h) for h in headers):
                target_block = block
                break

    if not target_block and blocks:
        target_block = blocks[0]

    if not target_block or len(target_block) < 2:
        return []

    header_cells = [c.lower() for c in _split_markdown_row(target_block[0])]
    rows: list[dict[str, str]] = []

    for line in target_block[1:]:
        if re.match(r"^\|?[\s\-:|]+\|?$", line):
            continue
        cells = _split_markdown_row(line)
        row_dict: dict[str, str] = {}
        for idx, h in enumerate(header_cells):
            if idx < len(cells):
                row_dict[h] = cells[idx]
        rows.append(row_dict)

    return rows


def find_column_value(row: dict[str, str], pattern: re.Pattern) -> str:
    for k, v in row.items():
        if pattern.search(k):
            return v
    return ""


def parse_claim_id(raw_claim: str, index: int) -> str:
    m = re.search(r"\[?Claim\s*([A-Za-z0-9._-]+)\]?", raw_claim, re.IGNORECASE)
    if m:
        return f"Claim {m.group(1)}"
    return f"Claim {index + 1}"


def validate_claim_ledger(
    ledger_text: str,
    synthesis_text: str | None = None,
) -> dict:
    raw_rows = parse_markdown_table(ledger_text)
    rows_data: list[dict] = []
    violations: list[dict[str, str]] = []

    verified_count = 0
    refuted_count = 0
    unresolved_count = 0

    claim_col_re = re.compile(r"claim|주장|항목", re.IGNORECASE)
    risk_col_re = re.compile(r"risk|위험|심각도", re.IGNORECASE)
    sources_col_re = re.compile(r"source|출처|증거|근거", re.IGNORECASE)
    counter_col_re = re.compile(r"counter|반증|반론|반가설", re.IGNORECASE)
    primary_col_re = re.compile(r"primary|1차|원천|원문", re.IGNORECASE)
    status_col_re = re.compile(r"status|상태", re.IGNORECASE)

    for i, raw in enumerate(raw_rows):
        raw_claim = find_column_value(raw, claim_col_re)
        claim_id = parse_claim_id(raw_claim, i)
        risk_level = find_column_value(raw, risk_col_re)
        sources = find_column_value(raw, sources_col_re)
        counter_search = find_column_value(raw, counter_col_re)
        primary_source = find_column_value(raw, primary_col_re)
        raw_status = find_column_value(raw, status_col_re).strip()
        norm_status = raw_status.replace("`", "").upper()

        row_violations: list[str] = []
        domains = extract_unique_domains(sources)
        artifacts = extract_forensic_artifacts(sources)
        legal_auths = extract_legal_authorities(sources)

        independence_count = len(domains) + len(artifacts) + len(legal_auths)

        if norm_status == "VERIFIED":
            verified_count += 1
            if independence_count < 2:
                msg = (
                    f"출처 독립성 미달 (발견: {independence_count}개): "
                    f"2개 이상의 독립 도메인, 법령/판례 또는 증거 파일/해시 필수 (도메인: {domains}, 아티팩트: {artifacts}, 법률: {legal_auths})"
                )
                row_violations.append(msg)
                violations.append({"claimId": claim_id, "violation": msg})

            counter_clean = counter_search.strip().lower()
            if counter_clean in INVALID_COUNTER_VALUES:
                msg = "VERIFIED 상태 주장에는 명시적 반증 검색 또는 반대 가설 검증(Counter-Search) 결과 기록 필수"
                row_violations.append(msg)
                violations.append({"claimId": claim_id, "violation": msg})

            primary_clean = primary_source.strip().lower()
            if not primary_clean or primary_clean in INVALID_COUNTER_VALUES:
                msg = "VERIFIED 상태 주장에는 1차 출처(Primary Source) 명시 필수"
                row_violations.append(msg)
                violations.append({"claimId": claim_id, "violation": msg})

        elif norm_status == "REFUTED":
            refuted_count += 1
        elif norm_status == "UNRESOLVED":
            unresolved_count += 1
        else:
            msg = f"유효하지 않은 상태 '{raw_status}': VERIFIED, REFUTED, UNRESOLVED 중 하나여야 함"
            row_violations.append(msg)
            violations.append({"claimId": claim_id, "violation": msg})

        rows_data.append({
            "claimId": claim_id,
            "claim": raw_claim,
            "riskLevel": risk_level,
            "sources": sources,
            "domains": domains,
            "artifacts": artifacts,
            "legalAuthorities": legal_auths,
            "counterSearch": counter_search,
            "primarySource": primary_source,
            "status": norm_status if norm_status in ("VERIFIED", "REFUTED", "UNRESOLVED") else "INVALID",
            "rawStatus": raw_status,
            "violations": row_violations,
        })

    if synthesis_text:
        citation_re = re.compile(r"\[Claim\s*([A-Za-z0-9._-]+)\]", re.IGNORECASE)
        for m in citation_re.finditer(synthesis_text):
            cited_id = f"Claim {m.group(1)}"
            found = next((r for r in rows_data if r["claimId"].lower() == cited_id.lower()), None)
            if not found:
                msg = f"문서에 인용된 [{cited_id}]가 claim-ledger.md에 등록되어 있지 않습니다."
                violations.append({"claimId": cited_id, "violation": msg})
            elif found["status"] != "VERIFIED":
                msg = (
                    f"문서에 인용된 [{cited_id}]의 원장 상태가 '{found['status']}'입니다. "
                    "오직 VERIFIED 주장만 본문 인용이 허용됩니다 (Section 6 위반)."
                )
                violations.append({"claimId": cited_id, "violation": msg})

    total_claims = len(rows_data)
    pass_count = sum(1 for r in rows_data if len(r["violations"]) == 0)
    fail_count = total_claims - pass_count

    return {
        "ok": len(violations) == 0,
        "totalClaims": total_claims,
        "verifiedCount": verified_count,
        "refutedCount": refuted_count,
        "unresolvedCount": unresolved_count,
        "passCount": pass_count,
        "failCount": fail_count,
        "rows": rows_data,
        "violations": violations,
    }


def verify_claim_ledger_file(
    ledger_path: str | Path,
    synthesis_path: str | Path | None = None,
) -> dict:
    lp = Path(ledger_path)
    if not lp.is_file():
        return {
            "ok": False,
            "totalClaims": 0,
            "verifiedCount": 0,
            "refutedCount": 0,
            "unresolvedCount": 0,
            "passCount": 0,
            "failCount": 0,
            "rows": [],
            "violations": [{"claimId": "N/A", "violation": f"Claim ledger file not found: {ledger_path}"}],
        }

    try:
        ledger_text = lp.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        ledger_text = lp.read_text(encoding="utf-8-sig", errors="replace")

    synthesis_text = None
    if synthesis_path:
        sp = Path(synthesis_path)
        if sp.is_file():
            try:
                synthesis_text = sp.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                synthesis_text = sp.read_text(encoding="utf-8-sig", errors="replace")

    return validate_claim_ledger(ledger_text, synthesis_text=synthesis_text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Section 6 Claim Ledger Protocol Verifier")
    parser.add_argument("file", help="Path to claim-ledger.md")
    parser.add_argument("--synthesis", help="Path to synthesis/report document to verify citation lock")
    parser.add_argument("--enforce", action="store_true", help="Exit with code 1 if violations are found")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    args = parser.parse_args(argv)

    report = verify_claim_ledger_file(args.file, synthesis_path=args.synthesis)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=== Claim Ledger Protocol Verification ===")
        print(f"Ledger File: {args.file}")
        if args.synthesis:
            print(f"Synthesis File: {args.synthesis}")
        print(
            f"Total Claims: {report['totalClaims']} "
            f"(Verified: {report['verifiedCount']}, Refuted: {report['refutedCount']}, Unresolved: {report['unresolvedCount']})"
        )
        print(f"Result: {'PASS' if report['ok'] else 'FAIL'} ({report['passCount']} passed, {report['failCount']} failed)\n")

        if report["violations"]:
            print(f"Violations ({len(report['violations'])}):")
            for v in report["violations"]:
                print(f"  [{v['claimId']}] {v['violation']}")
        else:
            print("No violations found. All claim records satisfy Section 6 Claim Ledger Protocol.")

    if args.enforce and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
