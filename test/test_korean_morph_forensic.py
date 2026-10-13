"""test_korean_morph_forensic.py — Kiwi 형태소 분석 기반 포렌식 용어 및 그라운딩 테스트."""

import json
import sys
from pathlib import Path

try:
    import pytest  # noqa: F401
except ImportError:
    pytest = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import korean_morph_forensic as kmf


def test_extract_forensic_morphemes_strips_particles():
    text = "디지털포렌식 분석관은 하드디스크의 슬랙공간에서 비인가 접근기록을 복원하였다."
    terms = kmf.extract_forensic_morphemes(text)
    assert "은" not in terms
    assert "의" not in terms
    assert "에서" not in terms
    assert "디지털포렌식" in terms
    assert "슬랙공간" in terms or "공간" in terms
    assert "비인가" in terms


def test_calculate_forensic_grounding_pass():
    evidence = "2024-01-16 09:00 USB 연결 기록 발견. VID_058F PID_6387 시리얼 12345678."
    report = "분석 결과 VID_058F PID_6387 USB 연결 기록이 확인되었습니다."

    res = kmf.calculate_forensic_grounding(evidence, report, threshold=0.50)
    assert res["is_grounded"] is True
    assert res["grounding_score"] >= 0.50


def test_calculate_forensic_grounding_detects_unsupported_novelty():
    evidence = "단순 ping 네트워크 패킷 3건 기록."
    report = "공격자가 랜섬웨어를 유포하고 비트코인 지갑으로 금전을 탈취한 정황이 확인되었습니다."

    res = kmf.calculate_forensic_grounding(evidence, report, threshold=0.50)
    assert res["is_grounded"] is False
    assert any(t in res["unsupported_terms"] for t in ["랜섬웨어", "비트코인", "탈취", "지갑"])


def test_main_cli_with_temp_files(tmp_path):
    ev_file = tmp_path / "evidence.txt"
    ev_file.write_text("SHA-256 해시값: a94a8fe5ccb19ba61c4c0873d391e987982fbbd3 이메일 첨부파일 무결성 검증", encoding="utf-8")

    rep_file = tmp_path / "report.md"
    rep_file.write_text("이메일 첨부파일에 대한 해시값 무결성 검증 결과 부합", encoding="utf-8")

    code = kmf.main(["--evidence", str(ev_file), "--report", str(rep_file), "--json"])
    assert code == 0


def test_main_cli_high_fidelity(tmp_path):
    ev_file = tmp_path / "evidence.txt"
    ev_file.write_text("USB 저장장치 연결 시각 2024-01-01 10:00:00 시리얼 123456", encoding="utf-8")

    # High fidelity pass
    rep_pass = tmp_path / "report_pass.md"
    rep_pass.write_text("USB 저장장치 연결 시각 2024-01-01 10:00:00 시리얼 123456 확인", encoding="utf-8")

    code_pass = kmf.main(["--evidence", str(ev_file), "--report", str(rep_pass), "--high-fidelity", "--json"])
    assert code_pass == 0

    # High fidelity fail with ungrounded terms
    rep_fail = tmp_path / "report_fail.md"
    rep_fail.write_text("악성코드 유포 및 랜섬웨어 감염 정황 발견", encoding="utf-8")

    code_fail = kmf.main(["--evidence", str(ev_file), "--report", str(rep_fail), "--high-fidelity", "--json"])
    assert code_fail == 1

