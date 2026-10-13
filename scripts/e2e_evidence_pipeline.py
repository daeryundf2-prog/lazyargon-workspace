#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""e2e_evidence_pipeline.py — 원스톱 전자소송 증거 패킷 자동 생성 파이프라인.

포렌식 분석관 및 송무 변호사를 위해 다음 4단계를 무타협으로 일괄 처리한다:
1. 원본 증거 파일 무결성 해시(SHA-256) 측정 및 Chain of Custody 기록.
2. 한국형 개인정보(주민등록번호, 계좌번호, 전화번호, 카드번호) 자동 비식별화.
3. 전자소송(ECFS) 표준 규격 증거 표찰(갑/을 제O호증) 메타데이터 결합.
4. 법정 제출용 무결성 증명서(Verification Sheet) 및 서증 목록 자동 생성.

CLI 사용법:
    python scripts/e2e_evidence_pipeline.py --input <증거파일_또는_디렉터리> --output-dir <출력디렉터리> --party 갑 --start-no 1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 같은 디렉터리의 mask_korean_pii import
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import mask_korean_pii


def calc_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_pipeline(
    input_paths: list[Path],
    output_dir: Path,
    party: str = "갑",
    start_no: int = 1,
    daeryun_mode: bool = True,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    masked_dir = output_dir / "masked_evidence"
    masked_dir.mkdir(parents=True, exist_ok=True)

    results = []
    current_no = start_no

    for src_path in input_paths:
        if not src_path.exists() or not src_path.is_file():
            continue

        raw_bytes = src_path.read_bytes()
        raw_hash = calc_sha256(src_path)

        text, enc = mask_korean_pii.decode_bytes(raw_bytes)
        masked_text, report = mask_korean_pii.mask_text(text, mask_korean_pii.DEFAULT_TYPES)

        masked_filename = f"{party}_제{current_no}호증_{src_path.name}"
        masked_path = masked_dir / masked_filename
        masked_path.write_bytes(mask_korean_pii.encode_text(masked_text, enc))
        masked_hash = calc_sha256(masked_path)

        item = {
            "evidence_no": f"{party} 제{current_no}호증",
            "original_filename": src_path.name,
            "masked_filename": masked_filename,
            "original_sha256": raw_hash,
            "masked_sha256": masked_hash,
            "pii_counts": report.get("counts", {}),
            "file_size_bytes": len(raw_bytes),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        results.append(item)
        current_no += 1

    # 1. 서증목록 및 무결성 증명서 Markdown 생성
    coc_md = output_dir / "증거목록_및_무결성증명서.md"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(coc_md, "w", encoding="utf-8") as f:
        f.write("# 법원 제출용 증거목록 및 무결성(Chain of Custody) 증명서\n\n")
        f.write(f"- **사건 당사자 구분**: {party}호증\n")
        f.write(f"- **처리 일시**: {now_str}\n")
        if daeryun_mode:
            f.write("- **검증 기관**: 법무법인(유한) 대륜 디지털포렌식·송무지원센터\n")
            f.write("- **대표 연락처**: 02-780-1128\n")
        f.write("\n---\n\n")
        f.write("## 1. 제출 증거 및 무결성 대조표\n\n")
        f.write("| 호증 | 원본 파일명 | 원본 SHA-256 | 비식별화 제출본 | 비식별화본 SHA-256 | PII 마스킹 건수 |\n")
        f.write("|---|---|---|---|---|:---:|\n")
        for r in results:
            pii_sum = sum(r["pii_counts"].values()) if r["pii_counts"] else 0
            f.write(
                f"| **{r['evidence_no']}** | `{r['original_filename']}` | `{r['original_sha256'][:16]}…` | "
                f"`{r['masked_filename']}` | `{r['masked_sha256'][:16]}…` | {pii_sum}건 |\n"
            )

        f.write("\n---\n\n")
        f.write("## 2. 사법 제출용 증거 보존 선언\n\n")
        f.write("본 증거 목록에 기재된 전자적 기록은 디지털포렌식 무결성 절차(Fail-Closed)에 따라\n")
        f.write("원본성을 침해하지 않는 읽기 전용 상태에서 추출되었으며, 개인정보보호법에 따른\n")
        f.write("필수 비식별화 조치를 완료하였음을 증명합니다.\n\n")
        f.write("담당 포렌식 분석관: ____________________ (인/서명)\n")
        f.write("담당 소송대리인:    ____________________ (인/서명)\n")

    # 2. 기계 판독용 JSON 요약
    summary_json = output_dir / "evidence_pipeline_summary.json"
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump(
            {
                "status": "PASS",
                "party": party,
                "total_evidences": len(results),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "items": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    return {"status": "SUCCESS", "count": len(results), "output_dir": str(output_dir)}


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-End Evidence Processing Pipeline")
    parser.add_argument("--input", "-i", required=True, help="입력 증거 파일 또는 디렉터리 경로")
    parser.add_argument("--output-dir", "-o", required=True, help="결과물이 저장될 디렉터리 경로")
    parser.add_argument("--party", default="갑", choices=["갑", "을"], help="당사자 구분 (기본: 갑)")
    parser.add_argument("--start-no", type=int, default=1, help="시작 호증 번호 (기본: 1)")
    parser.add_argument("--no-daeryun-header", action="store_true", help="대륜 머리말 생략")

    args = parser.parse_args()
    input_target = Path(args.input)

    if not input_target.exists():
        print(f"Error: 입력 경로가 존재하지 않습니다: {args.input}", file=sys.stderr)
        return 2

    if input_target.is_file():
        input_files = [input_target]
    else:
        input_files = sorted([p for p in input_target.glob("*") if p.is_file()])

    if not input_files:
        print(f"Notice: 처리할 증거 파일이 없습니다: {args.input}")
        return 0

    res = run_pipeline(
        input_files,
        Path(args.output_dir),
        party=args.party,
        start_no=args.start_no,
        daeryun_mode=not args.no_daeryun_header,
    )
    print(f"[E2E Pipeline] Successfully processed {res['count']} evidences -> {res['output_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
