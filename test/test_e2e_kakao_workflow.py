#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""README "5분 워크플로" E2E 회귀 테스트.

카카오 픽스처 → 파싱 → 타임라인 → 감사 → 보고서 검증 체인을 서브프로세스로
끝까지 실행해 핵심 파이프라인이 깨지지 않았는지 보증한다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "test" / "fixtures"
PARSE_KAKAO = ROOT / "skills" / "kakao-chat-extractor" / "scripts" / "parse_kakao.py"
GEN_TIMELINE = ROOT / "skills" / "forensic-timeline" / "scripts" / "generate_timeline.py"
AUDIT = ROOT / "skills" / "forensic-audit" / "scripts" / "audit_timestamps.py"
VERIFY = ROOT / "scripts" / "verify_report.py"


def _run(script: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd else str(ROOT),
    )


@pytest.mark.parametrize("fixture", ["kakao_mobile.txt", "kakao_pc.txt"])
def test_kakao_five_minute_workflow(tmp_path: Path, fixture: str) -> None:
    case = tmp_path / "case"
    case.mkdir()
    src = FIXTURES / fixture
    if not src.exists():
        pytest.skip(f"fixture missing: {fixture}")
    target = case / fixture
    target.write_bytes(src.read_bytes())

    # 1. 대화 파싱 + 타임라인 이벤트 변환
    parsed = case / "parsed.json"
    events = case / "events.json"
    r = _run(PARSE_KAKAO, str(target), "--output", str(parsed), "--events-out", str(events))
    assert r.returncode == 0, f"parse_kakao failed: {r.stderr}"
    event_list = json.loads(events.read_text(encoding="utf-8"))
    assert isinstance(event_list, list) and len(event_list) > 0
    assert all("timestamp" in e and "description" in e for e in event_list)

    # 2. 타임라인 HTML 렌더
    timeline = case / "timeline.html"
    r = _run(GEN_TIMELINE, "--input", str(events), "--output", str(timeline))
    assert r.returncode == 0, f"generate_timeline failed: {r.stderr}"
    html = timeline.read_text(encoding="utf-8")
    assert "<html" in html.lower() and len(html) > 500

    # 3. 원본 해시 감사 → audit.json
    r = _run(AUDIT, str(target), "--json")
    assert r.returncode == 0, f"audit_timestamps failed: {r.stderr}"
    audit = json.loads(r.stdout)
    (case / "audit.json").write_text(r.stdout, encoding="utf-8")
    sha = audit["sha256"]
    assert len(sha) == 64

    # 4. 보고서 검증 — 감사 해시 + 파일명 인접 기술 + <evidence> 태그
    report = case / "감정서초안.md"
    report.write_text(
        "# 감정서 초안\n\n"
        f"분석 대상 파일 {fixture} 의 SHA-256 해시는\n"
        f"{sha} 이다.\n\n"
        f"<evidence>{sha}</evidence>\n\n"
        "상기 대화 내역은 타임라인으로 정리하였다.\n",
        encoding="utf-8",
    )
    r = _run(VERIFY, str(report), "--evidence", str(case / "audit.json"), "--json")
    assert r.returncode == 0, f"verify_report rejected grounded report: {r.stdout}{r.stderr}"
    verdict = json.loads(r.stdout)
    assert verdict["verdict"] == "PASS", verdict
    assert sha in verdict["report_hashes"]

    # 5. 음성 케이스 — 조작된 해시는 실패폐쇄로 차단돼야 한다
    bad = case / "조작보고서.md"
    bad.write_text(f"해시는 {'0' * 64} 이다.\n", encoding="utf-8")
    r = _run(VERIFY, str(bad), "--evidence", str(case / "audit.json"), "--json")
    assert r.returncode == 1
    verdict = json.loads(r.stdout)
    assert any("근거 없는 해시" in e for e in verdict["errors"])
