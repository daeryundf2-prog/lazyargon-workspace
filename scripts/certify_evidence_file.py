from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from processing_receipt import approve_receipt, make_receipt, verify_receipt, write_verified, utc_now

CHUNK = 1 << 20


def _hash_file(path, algorithm):
    digest = hashlib.new(algorithm)
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_hash(record):
    payload = {key: value for key, value in record.items() if key != "record_sha256"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def certify(files, url, note, case_number):
    items = []
    try:
        for path in files:
            if not Path(path).is_file():
                raise ValueError("Source is not a file")
            before = os.stat(path)
            receipt = make_receipt(path, "certify_evidence_file", case_id=case_number or None, parameters={"claimed_source_url": url, "note": note})
            md5 = _hash_file(path, "md5")
            after = os.stat(path)
            identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            if identity(before) != identity(after) or verify_receipt(receipt):
                raise ValueError("Source changed or could not be measured")
            items.append({
                "file": str(Path(path).absolute()), "name": Path(path).name,
                "size": before.st_size, "sha256": receipt["source"]["sha256"], "md5": md5,
                "file_mtime_utc": datetime.fromtimestamp(before.st_mtime, timezone.utc).isoformat(),
                "evidence_id": receipt["evidence_id"], "processing_receipt": receipt,
            })
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return {}
    if not items:
        return {}
    record = {"certified_at_utc": utc_now(), "case_number": case_number, "case_id": case_number or None, "source_url": url, "note": note, "items": items}
    record["record_sha256"] = record_hash(record)
    return record


def render_markdown(record):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    lines = ["# 웹 채증 기록 (Local File Measurement)", f"측정 시각(UTC): {record['certified_at_utc']}", f"사건번호: {cell(record.get('case_number', ''))}", f"주장된 URL (미검증): {cell(record.get('source_url', ''))}", f"메모: {cell(record.get('note', ''))}", "", "| evidence_id | 파일 | 크기 | SHA-256 | MD5 | 파일 수정 시각(UTC) |", "| --- | --- | --- | --- | --- | --- |"]
    for item in record["items"]:
        lines.append("| " + " | ".join(cell(item[key]) for key in ("evidence_id", "name", "size", "sha256", "md5", "file_mtime_utc")) + " |")
    lines += ["", "본 기록 SHA-256: 별도 JSON의 record_sha256은 JSON 기록에 대한 자체 체크섬입니다.", "> 실행 시점의 로컬 파일 측정입니다. 캡처 시점, URL 진위, 생성 시각은 검증하지 않습니다. 전자서명, 신뢰 타임스탬프, 보관 연속성(custody) 증명이 아닙니다. 검토 승인 여부는 별도 JSON receipt를 확인하십시오."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="로컬 파일 측정 기록 생성")
    parser.add_argument("files", nargs="+")
    parser.add_argument("--url", default="")
    parser.add_argument("--note", default="")
    parser.add_argument("--case", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--reviewer")
    args = parser.parse_args(argv)
    if args.reviewer and not (args.output and args.output_md):
        parser.error("Approval requires --output and --output-md")
    record = certify(args.files, args.url, args.note, args.case)
    if not record:
        return 2
    try:
        md = render_markdown(record)
        if args.output_md:
            digest = write_verified(args.output_md, md, protected=[*args.files, args.output])
            for item in record["items"]:
                receipt = item["processing_receipt"]
                receipt["artifacts"] = [{"path": str(Path(args.output_md).absolute()), "sha256": digest}]
                receipt["finished_at"] = utc_now()
                errors = verify_receipt(receipt)
                if errors:
                    raise ValueError("; ".join(errors))
                if args.reviewer:
                    item["processing_receipt"] = approve_receipt(receipt, args.reviewer)
        record["record_sha256"] = record_hash(record)
        if args.output:
            write_verified(args.output, json.dumps(record, ensure_ascii=False, indent=2), protected=[*args.files, args.output_md])
        if not args.output and not args.output_md:
            print(md)
        return 0
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
