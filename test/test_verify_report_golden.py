#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_report.py 출력 골든 스냅샷 테스트.

분리(C2) 리팩터 전후로 CLI 출력이 바이트 단위로 동일한지 보증한다.
스냅샷은 test/fixtures/verify_report_golden.json 에 저장되며,
REGEN_GOLDEN=1 환경변수로 재생성한다 (의도적 동작 변경 시에만).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "verify_report.py"
FIXTURE = ROOT / "test" / "fixtures" / "verify_report_golden.json"

HASH_A = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
HASH_B = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def _run(args: list[str]) -> dict:
    res = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {"exit": res.returncode, "stdout": res.stdout, "stderr": res.stderr}


def _normalize(blob: dict, tmp_dir: Path) -> dict:
    """머신/실행시각 의존 부분만 치환한다. JSON 출력은 역슬래시가 이스케이프되므로
    str(path)와 JSON 이스케이프 형태 둘 다 치환한다."""
    raw = str(tmp_dir)
    escaped = raw.replace("\\", "\\\\")
    out = {"exit": blob["exit"], "stdout": blob["stdout"], "stderr": blob["stderr"]}
    for key in ("stdout", "stderr"):
        text = out[key].replace(escaped, "<TMP>").replace(raw, "<TMP>")
        # Windows 경로 구분자 정규화 (<TMP>\ 및 <TMP>\\ -> <TMP>/)
        text = text.replace("<TMP>\\\\", "<TMP>/").replace("<TMP>\\", "<TMP>/")
        # '미래 시각 날조' 메시지에 현재 시각이 박힌다
        text = re.sub(r"현재\(\d{4}-\d{2}-\d{2} \d{2}:\d{2}\)", "현재(<NOW>)", text)
        out[key] = text
    return out


def _cases(tmp: Path) -> dict[str, dict]:
    """{name: {"report": str|None, "files": {name: content}, "args": [...]}}"""
    return {
        "clean_pass": {
            "report": "분석 보고서: 측정된 값만 기재한다.",
            "args": [],
        },
        "forbidden_phrase": {
            "report": "이 증거는 법원에 유효하며 피의자의 유출이 명백히 입증되었습니다.",
            "args": [],
        },
        "certainty_variant": {
            "report": "완벽히 입증되었으므로 결론은 확정적이다.",
            "args": ["--json"],
        },
        "orphan_hash": {
            "report": f"해시는 {HASH_A} 이다.",
            "args": ["--json"],
        },
        "statute_oob": {
            "report": "정보통신망법 제100조에 따라 처벌을 의뢰합니다.",
            "args": ["--json"],
        },
        "subarticle_oob": {
            "report": "민법 제1118조의99에 따라 해석한다.",
            "args": ["--json"],
        },
        "future_precedent": {
            "report": "대법원 2099도12345 판결 취지를 원용합니다.",
            "args": ["--json"],
        },
        "bad_case_code": {
            "report": "대법원 2020층12345 판결을 참조한다.",
            "args": ["--json"],
        },
        "fabricated_agency": {
            "report": "사이버수사처에서 수사를 진행하였다.",
            "args": ["--json"],
        },
        "abolished_agency": {
            "report": "당시 정보통신부의 지침을 따랐다.",
            "args": ["--json"],
        },
        "abolished_agency_allowed": {
            "report": "당시 정보통신부의 지침을 따랐다.",
            "args": ["--json", "--allow-historical"],
        },
        "fabricated_history": {
            "report": "제4차 갑오개혁 당시의 기록을 분석했다.",
            "args": ["--json"],
        },
        "impossible_procedure": {
            "report": "대검찰청이 약식명령을 청구하였다.",
            "args": ["--json"],
        },
        "fabricated_journal": {
            "report": "대한인공지능법학회지에 실린 논문이다.",
            "args": ["--json"],
        },
        "future_citation": {
            "report": "김철수 교수의 2099년 발표한 논문에 따르면.",
            "args": ["--json"],
        },
        "evidence_tag_no_evidence": {
            "report": "<evidence>2026-08-30T10:00:00Z</evidence> 측정 시각이다.",
            "args": ["--json"],
        },
        "evidence_tag_mismatch": {
            "report": "<evidence>없는값</evidence>",
            "files": {"evidence.json": '{"timestamp": "2026-08-30T10:00:00Z"}'},
            "args": ["--json", "--evidence", "{evidence.json}"],
        },
        "evidence_tag_ok": {
            "report": "<evidence>2026-08-30T10:00:00Z</evidence>",
            "files": {"evidence.json": '{"timestamp": "2026-08-30T10:00:00Z"}'},
            "args": ["--evidence", "{evidence.json}"],
        },
        "hash_binding_schema_warn": {
            "report": f"본체의 해시는 {HASH_A} 이다. 추가 분석이 필요하다.",
            "files": {"evidence.json": json.dumps({"path": "body.bin", "sha256": HASH_A})},
            "args": ["--json", "--evidence", "{evidence.json}"],
        },
        "hash_binding_table_violation": {
            "report": f"| 파일 | 해시 |\n| other.bin | {HASH_A} |",
            "files": {"evidence.json": json.dumps({"path": "body.bin", "sha256": HASH_A})},
            "args": ["--json", "--evidence", "{evidence.json}"],
        },
        "law_citation_no_marker": {
            "report": "민법 제750조에 따라 손해배상을 청구한다.",
            "args": ["--json"],
        },
        "strict_warn": {
            "report": "대법원 2020층12345 판결을 참조한다.",
            "args": ["--json", "--strict"],
        },
        "timeline_orphan": {
            "report": "접속은 2024-05-01 09:30 에 이뤄졌다.",
            "files": {"timeline.json": "events: 2024-05-01 12:00"},
            "args": ["--json", "--timeline", "{timeline.json}"],
        },
        "impossible_date": {
            "report": "기록 시각은 2024-13-45 09:30 이다.",
            "args": ["--json"],
        },
        "future_ts_context": {
            "report": "개정법은 2099-01-01 00:00 시행 예정이다.",
            "args": ["--json"],
        },
        "missing_report": {
            "report": None,
            "args": ["<MISSING>"],
        },
        "coc_warn": {
            "report": "비교 결과 일치함을 확인했다.",
            "args": ["--json"],
        },
        "negated_forbidden": {
            "report": "조작 가능성을 배제할 수 없다. 유출의심 아님으로 본다.",
            "args": ["--json"],
        },
        "health_check_json": {
            "report": None,
            "args": ["--health-check", "--json"],
        },
        "health_check_plain": {
            "report": None,
            "args": ["--health-check"],
        },
    }


@pytest.mark.parametrize("name", sorted(_cases(Path("."))))
def test_verify_report_golden_snapshot(tmp_path: Path, name: str) -> None:
    case = _cases(tmp_path)[name]
    for fname, content in (case.get("files") or {}).items():
        (tmp_path / fname).write_text(content, encoding="utf-8")

    args = list(case["args"])
    report = tmp_path / "report.md"
    if case["report"] is not None:
        report.write_text(case["report"], encoding="utf-8")
        args.insert(0, str(report))
    else:
        args = [str(tmp_path / "missing.md") if a == "<MISSING>" else a for a in args]
    args = [str(tmp_path / a[1:-1]) if a.startswith("{") else a for a in args]

    blob = _normalize(_run(args), tmp_path)

    if os.environ.get("REGEN_GOLDEN"):
        goldens = json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.exists() else {}
        goldens[name] = blob
        FIXTURE.write_text(json.dumps(goldens, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pytest.skip("regenerating golden fixture")

    goldens = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert name in goldens, f"golden snapshot missing for {name}"
    assert blob == goldens[name], (
        f"verify_report.py 출력이 골든과 다름 ({name}).\n"
        f"의도된 동작 변경이면 REGEN_GOLDEN=1 로 재생성하라.\n"
        f"--- actual ---\nexit={blob['exit']}\nstdout={blob['stdout']}\nstderr={blob['stderr']}"
    )
