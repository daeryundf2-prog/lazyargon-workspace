import argparse
import copy
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from processing_receipt import approve_receipt, hash_file, make_receipt, verify_receipt, write_verified, utc_now


SAMPLE_BANNER = "> [샘플 자동 생성본 — 법원 제출 금지] 실제 증거 목록으로 교체하십시오."


def calculate_sha256(filepath):
    try:
        return hash_file(filepath)
    except (OSError, ValueError):
        return "N/A"


def _escape_cell(text):
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").replace("\r", "")


def resolve_evidence_hashes(evidence_list, base_dir="", case_id=None):
    if not isinstance(evidence_list, list) or any(not isinstance(item, dict) for item in evidence_list):
        raise ValueError("Evidence items must be a list of objects")
    ids = set()
    for item in evidence_list:
        imported = item.get("processing_receipt")
        claimed = item.get("claimed_sha256", item.get("sha256"))
        errors = verify_receipt(imported, base_dir) if imported is not None else ["Legacy input: no processing_receipt; provenance unverified"]
        source = imported.get("source", {}) if isinstance(imported, dict) else {}
        source = source if isinstance(source, dict) else {}
        evidence_id = item.get("evidence_id") or (imported.get("evidence_id") if isinstance(imported, dict) else None) or str(uuid4())
        if not isinstance(evidence_id, str) or not evidence_id.strip() or evidence_id in ids:
            raise ValueError("Invalid or duplicate evidence_id")
        ids.add(evidence_id)
        path = item.get("file_path") or item.get("file") or source.get("path")
        if path is not None and not isinstance(path, str):
            raise ValueError("Invalid evidence path")
        resolved = str((Path(base_dir) / path).absolute()) if path else None
        actual = None
        if resolved:
            try:
                actual = hash_file(resolved)
            except (OSError, ValueError):
                errors.append("Source missing, unreadable or changed while hashing")
        else:
            errors.append("No source path")
        mismatch = claimed is not None and actual is not None and (not isinstance(claimed, str) or claimed.lower() != actual)
        if mismatch:
            errors.append("Claimed SHA-256 mismatch / 불일치")
        if isinstance(imported, dict):
            if imported.get("evidence_id") != evidence_id:
                errors.append("Receipt evidence_id mismatch")
            if case_id is not None and imported.get("case_id") != case_id:
                errors.append("Receipt case_id mismatch")
            linked = [source, *(imported.get("artifacts") if isinstance(imported.get("artifacts"), list) else [])]
            linked = [entry for entry in linked if isinstance(entry, dict) and isinstance(entry.get("path"), str)]
            if not resolved or not any((Path(base_dir) / entry["path"]).resolve() == Path(resolved).resolve() and entry.get("sha256") and entry["sha256"].lower() == actual for entry in linked):
                errors.append("Receipt does not bind this evidence file")
        item.update({
            "evidence_id": evidence_id, "file_path": resolved,
            "claimed_sha256": claimed, "sha256": actual, "verified_sha256": actual,
            "hash_status": "unknown" if actual is None else "mismatch" if mismatch else "verified",
            "processing_receipt_status": "verified" if not errors else "unverified",
            "verification_warnings": errors,
        })
        if imported is not None:
            item["imported_processing_receipt"] = copy.deepcopy(imported)
        if resolved:
            receipt = make_receipt(resolved, "generate_evidence_doc", case_id=case_id, evidence_id=evidence_id)
            if receipt["source"]["sha256"] != actual:
                errors.append("Source changed between measurements")
            receipt["warnings"].extend(errors)
            if errors and receipt["status"] == "complete":
                receipt["status"] = "partial"
                receipt["exit_code"] = 1
            item["processing_receipt"] = receipt
        else:
            item["processing_receipt"] = None


def generate_evidence_markdown(case_info, evidence_list, output_path, is_sample=False, protected=()):
    lines = ["# 증 거 설 명 서", "", "> 법률 문서 초안 — 변호사 검토 후 제출하십시오. 자동 검증은 사실성·적법성·보관 연속성을 증명하지 않습니다."]
    if is_sample:
        lines.append(SAMPLE_BANNER)
    for key, label in (("case_number", "사 건"), ("case_name", "사건명"), ("plaintiff", "원 고"), ("defendant", "피 고")):
        lines.append(f"**{label}:** {_escape_cell(case_info.get(key, '미상'))}")
    lines += ["", "| 순번 | evidence_id | 서증부호 | 서증명 | 작성자 / 일자 | 입증취지 | 측정 SHA-256 | 기재 SHA-256 | 검증 상태 |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for idx, item in enumerate(evidence_list, 1):
        date = item.get('date') or '미상'
        basis = item.get('date_basis')
        if basis == 'filesystem_mtime_not_authorship':
            date = f"{date} (파일시스템 mtime — 작성일자 아님)"
        elif basis:
            date = f"{date} ({basis})"
        values = [idx, item.get("evidence_id", "unknown"), item.get("label", f"갑 제{idx}호증"), item.get("title", f"증거물_{idx}"), f"{item.get('author', '작성자불상')} / {date}", item.get("purpose", "입증취지 미제공"), item.get("verified_sha256") or "N/A (file not found)", item.get("claimed_sha256") or "unknown", f"hash={item.get('hash_status', 'unknown')}; receipt={item.get('processing_receipt_status', 'unverified')} (미검증 근거는 검증됨이 아님)"]
        lines.append("| " + " | ".join(_escape_cell(v) for v in values) + " |")
        for warning in item.get("verification_warnings", []):
            lines.append(f"\n> {_escape_cell(item.get('evidence_id'))}: {_escape_cell(warning)}\n")
    lines += ["", f"**작성일자:** {datetime.now().strftime('%Y-%m-%d')}", f"**제출인:** {_escape_cell(case_info.get('submitter', '미상'))}", f"**{_escape_cell(case_info.get('court', '관할 법원 미상'))} 귀중**"]
    if is_sample:
        lines.append(SAMPLE_BANNER)
    sources = [item.get("file_path") for item in evidence_list]
    return write_verified(output_path, "\n".join(lines) + "\n", protected=[*protected, *sources])


def main(argv=None):
    parser = argparse.ArgumentParser(description="증거설명서 초안 및 검증 기록 생성")
    parser.add_argument("--input-json", "-i")
    parser.add_argument("--output", "-o", default="증거설명서.md")
    parser.add_argument("--output-json")
    parser.add_argument("--reviewer")
    parser.add_argument("--case-id")
    parser.add_argument("--case-num", default="미상")
    parser.add_argument("--case-name", default="미상")
    parser.add_argument("--court", default="관할 법원 미상")
    parser.add_argument("--allow-sample", action="store_true")
    args = parser.parse_args(argv)
    case_info = {"case_number": args.case_num, "case_name": args.case_name, "court": args.court}
    case_id = args.case_id
    items = []
    data = None
    if args.input_json:
        try:
            data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[WARN] Cannot load input: {exc}", file=sys.stderr)
    if isinstance(data, dict):
        case_info.update(data.get("case_info", {}))
        case_id = case_id or data.get("case_id")
        items = data.get("evidence_list", data.get("items", data.get("evidence", [])))
        if not items and "processing_receipt" in data:
            items = [data]
    elif isinstance(data, list):
        items = data
    sample = not items
    if sample and not args.allow_sample:
        parser.error("No evidence: explicit --allow-sample required")
    if sample:
        items = [{"title": "[SAMPLE] 실제 증거로 교체 필요"}]
    if args.reviewer and not args.output_json:
        parser.error("--reviewer requires --output-json")
    base_dir = str(Path(args.input_json).absolute().parent) if args.input_json else ""
    try:
        resolve_evidence_hashes(items, base_dir, case_id)
        protected = [args.input_json] if args.input_json else []
        for item in items:
            imported = item.get("imported_processing_receipt")
            if isinstance(imported, dict):
                entries = [imported.get("source"), *(imported.get("artifacts") if isinstance(imported.get("artifacts"), list) else [])]
                protected.extend(str(Path(base_dir) / e["path"]) for e in entries if isinstance(e, dict) and isinstance(e.get("path"), str))
        if args.output_json and Path(args.output_json).resolve() == Path(args.output).resolve():
            raise ValueError("JSON and Markdown output paths must differ")
        digest = generate_evidence_markdown(case_info, items, args.output, sample, protected)
        for item in items:
            receipt = item["processing_receipt"]
            if not receipt:
                continue
            receipt["artifacts"] = [{"path": str(Path(args.output).absolute()), "sha256": digest}]
            receipt["finished_at"] = utc_now()
            errors = verify_receipt(receipt)
            if errors and receipt["status"] == "complete":
                receipt["status"] = "partial"
                receipt["exit_code"] = 1
                receipt["warnings"].extend(errors)
            if args.reviewer:
                item["processing_receipt"] = approve_receipt(receipt, args.reviewer)
        if args.reviewer and any(not i["processing_receipt"] for i in items):
            raise ValueError("Cannot approve unmeasured evidence")
        if args.output_json:
            output = {"case_id": case_id, "case_info": case_info, "evidence_list": items}
            write_verified(args.output_json, json.dumps(output, ensure_ascii=False, indent=2), protected=[*protected, args.output, *(i.get("file_path") for i in items)])
    except (OSError, ValueError, TypeError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    return 0 if all(i["processing_receipt_status"] == "verified" for i in items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
