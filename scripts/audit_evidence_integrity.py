from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from processing_receipt import make_receipt, verify_receipt, write_verified

CHUNK = 1 << 20
_HASH_RE = {
    "sha256": re.compile(r"\b[a-fA-F0-9]{64}\b"),
    "sha1": re.compile(r"\b[a-fA-F0-9]{40}\b"),
    "md5": re.compile(r"\b[a-fA-F0-9]{32}\b"),
}


def compute_hash(path, algorithm):
    digest = hashlib.new(algorithm)
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_targets(scan_dir="", files=None):
    targets = set(files or [])
    if scan_dir:
        for root, _, names in os.walk(scan_dir):
            targets.update(os.path.join(root, name) for name in names)
    return sorted(targets)


def extract_report_hashes(report_text):
    return {algo: {match.group().lower() for match in pattern.finditer(report_text)} for algo, pattern in _HASH_RE.items()}


def _filename_pattern(name):
    return re.compile(r"(?<![\w./\\:-])" + re.escape(name) + r"(?![\w./\\:-])")


def _claim_verdict(entry, claims):
    measured = entry["hashes"]
    states = {}
    for algo, value in measured.items():
        values = {str(row.get(algo)).lower() for row in claims if row.get(algo) is not None}
        states[algo] = "mismatch" if values - {value.lower()} else "match" if values else "not_measured"
    entry["algorithm_verdicts"] = states
    if "mismatch" in states.values():
        return "불일치"
    if not states or all(state == "not_measured" for state in states.values()):
        return "미측정"
    return "일치" if all(state == "match" for state in states.values()) else "주의"


def verdict_for(entry, report_text, report_hashes):
    if not report_text:
        return "산출"
    name = str(entry["name"])
    base = os.path.basename(name)
    full_names = {name, os.path.abspath(name)}
    full_lines = [line for line in report_text.splitlines() if any(_filename_pattern(p).search(line) for p in full_names if p != base)]
    base_lines = [line for line in report_text.splitlines() if _filename_pattern(base).search(line)]
    lines = full_lines + base_lines
    if not lines:
        return "주의" if any(value.lower() in report_hashes.get(algo, set()) for algo, value in entry["hashes"].items()) else "미측정"
    if base_lines and entry.get("basename_ambiguous"):
        return "주의"
    claims = []
    for line in lines:
        cells = [cell.strip().strip("`\"' ") for cell in line.split("|")]
        identities = [cell for cell in cells if cell and re.search(r"\.[A-Za-z0-9]{1,10}$", cell)]
        if len(identities) > 1:
            return "주의"
        values = extract_report_hashes(line)
        for algo, hashes in values.items():
            claims.extend({algo: value} for value in hashes)
    verdict = _claim_verdict(entry, claims)
    ids = {match.group() for line in lines for match in re.finditer(r"(?:갑|을)\s*제\s*\d+\s*호증(?:의\s*\d+)?", line)}
    if len(ids) == 1:
        entry["evidence_id"] = ids.pop()
    elif len(ids) > 1 and verdict == "일치":
        return "주의"
    return verdict


def structured_verdict(entry, report, base_dir):
    rows = report if isinstance(report, list) else report.get("evidence_list", report.get("items", report.get("records", [])))
    if not isinstance(rows, list):
        return "주의"
    selected = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        receipt = row.get("processing_receipt")
        source = receipt.get("source", {}) if isinstance(receipt, dict) else {}
        source = source if isinstance(source, dict) else {}
        raw_path = row.get("file_path") or row.get("file") or row.get("name") or source.get("path")
        if isinstance(raw_path, str) and (Path(base_dir) / raw_path).resolve() == Path(entry["name"]).resolve():
            selected.append(row)
    if not selected:
        return "미측정"
    ids = {row.get("evidence_id") or (row.get("processing_receipt", {}).get("evidence_id") if isinstance(row.get("processing_receipt"), dict) else None) for row in selected}
    if len(ids) > 1:
        return "주의"
    evidence_id = next(iter(ids))
    if evidence_id:
        entry["evidence_id"] = evidence_id
        for row in rows:
            if not isinstance(row, dict) or row in selected:
                continue
            receipt = row.get("processing_receipt")
            other_id = row.get("evidence_id") or (receipt.get("evidence_id") if isinstance(receipt, dict) else None)
            if other_id == evidence_id:
                return "주의"
    claims = []
    errors = []
    for row in selected:
        claim = dict(row.get("hashes", {})) if isinstance(row.get("hashes"), dict) else {}
        claim.update({algo: row[algo] for algo in _HASH_RE if row.get(algo) is not None})
        claims.append(claim)
        receipt = row.get("processing_receipt")
        if receipt is None:
            errors.append("Legacy record: receipt absent; provenance unverified")
        else:
            errors.extend(verify_receipt(receipt, base_dir))
            if isinstance(receipt, dict) and receipt.get("evidence_id") != evidence_id:
                errors.append("Receipt evidence_id mismatch")
            if isinstance(receipt, dict) and not errors:
                entries = [receipt["source"], *receipt["artifacts"]]
                linked = [e for e in entries if (Path(base_dir) / e["path"]).resolve() == Path(entry["name"]).resolve()]
                if not linked:
                    errors.append("Receipt does not bind selected file")
                claims.extend({"sha256": e["sha256"]} for e in linked)
    entry["imported_processing_receipts"] = [row.get("processing_receipt") for row in selected]
    entry["verification_warnings"] = errors
    verdict = _claim_verdict(entry, claims)
    if errors and verdict != "불일치":
        return "주의"
    cases = {row["processing_receipt"].get("case_id") for row in selected if isinstance(row.get("processing_receipt"), dict)}
    if len(cases) == 1:
        entry["case_id"] = cases.pop()
    elif len(cases) > 1:
        return "주의"
    return verdict


def audit(targets, algorithms, report_text="", report_base_dir=""):
    if not algorithms or any(algo not in _HASH_RE for algo in algorithms):
        raise ValueError("At least one supported algorithm is required")
    records = []
    counts = Counter(os.path.basename(str(path)) for path in targets)
    report = None
    if report_text.lstrip().startswith(("{", "[")):
        try:
            report = json.loads(report_text)
        except ValueError:
            report = {"records": None}
    report_hashes = extract_report_hashes(report_text)
    for path in targets:
        path = str(path)
        entry = {"name": path, "basename_ambiguous": counts[os.path.basename(path)] > 1}
        try:
            if not Path(path).is_file():
                raise ValueError("파일 없음")
            before = os.stat(path)
            entry.update(size=before.st_size, hashes={algo: compute_hash(path, algo) for algo in algorithms})
            receipt = make_receipt(path, "audit_evidence_integrity", parameters={"algorithms": algorithms})
            after = os.stat(path)
            identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            if identity(before) != identity(after) or receipt["source"]["sha256"] is None:
                raise ValueError("감사 중 파일 변경 감지 — 해시 무효")
            if "sha256" in entry["hashes"] and receipt["source"]["sha256"] != entry["hashes"]["sha256"]:
                raise ValueError("Source changed between measurements")
            entry["verdict"] = structured_verdict(entry, report, report_base_dir) if isinstance(report, (dict, list)) else verdict_for(entry, report_text, report_hashes)
            entry.setdefault("evidence_id", receipt["evidence_id"])
            receipt["evidence_id"] = entry["evidence_id"]
            receipt["case_id"] = entry.get("case_id")
            if entry["verdict"] not in ("산출", "일치"):
                receipt.update(status="partial", exit_code=1)
                receipt["warnings"].append("Report comparison unresolved or mismatched")
            entry["processing_receipt"] = receipt
        except (OSError, ValueError) as exc:
            entry.update(error=str(exc), verdict="불일치")
        records.append(entry)
    return {"records": records, "summary": {v: sum(row["verdict"] == v for row in records) for v in ("일치", "불일치", "주의", "미측정", "산출")}}


def render_markdown(result, algorithms, report_path, audit_time):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    lines = ["# 증거 무결성 감사 보고서", f"감사 시각(UTC): {audit_time}", f"대조 보고서: {cell(report_path)}", "", "| evidence_id | 파일 | 크기 | 해시 | 판정 |", "| --- | --- | --- | --- | --- |"]
    for entry in result["records"]:
        hashes = "; ".join(f"{algo}={entry.get('hashes', {}).get(algo, 'unknown')}" for algo in algorithms)
        lines.append("| " + " | ".join(cell(v) for v in [entry.get("evidence_id", "unknown"), entry["name"], entry.get("size", "unknown"), hashes, entry.get("error", entry["verdict"])]) + " |")
    payload = json.dumps({"records": result["records"], "audit_time": audit_time}, ensure_ascii=False, sort_keys=True)
    lines += ["", "## Local Integrity Measurement Record", f"본 감사 기록 SHA-256: {hashlib.sha256(payload.encode()).hexdigest()}", "> Local measurements only: not a signature, trusted timestamp or chain-of-custody proof. Legacy Markdown comparisons verify stated hashes only, not provenance.", json.dumps(result["summary"], ensure_ascii=False)]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="증거 파일 무결성 측정 및 보고서 대조")
    parser.add_argument("--scan-dir", default="")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--report", default="")
    parser.add_argument("--algorithms", default="sha256")
    parser.add_argument("--output", "-o", default="")
    parser.add_argument("--output-json", default="")
    args = parser.parse_args(argv)
    try:
        algorithms = list(dict.fromkeys(a.strip().lower().replace("-", "") for a in args.algorithms.split(",") if a.strip()))
        targets = collect_targets(args.scan_dir, args.file)
        if not targets:
            raise ValueError("No targets")
        report_text = Path(args.report).read_text(encoding="utf-8") if args.report else ""
        result = audit(targets, algorithms, report_text, str(Path(args.report).absolute().parent) if args.report else "")
        md = render_markdown(result, algorithms, args.report, datetime.now(timezone.utc).isoformat())
        if args.output:
            digest = write_verified(args.output, md, protected=[*targets, args.report, args.output_json])
            for row in result["records"]:
                if row.get("processing_receipt"):
                    row["processing_receipt"]["artifacts"] = [{"path": str(Path(args.output).absolute()), "sha256": digest}]
        else:
            print(md)
        if args.output_json:
            write_verified(args.output_json, json.dumps(result, ensure_ascii=False, indent=2), protected=[*targets, args.report, args.output])
        return 1 if any(row["verdict"] not in ("일치", "산출") for row in result["records"]) else 0
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
