# -*- coding: utf-8 -*-
"""test_verify_forensic_claim_ledger.py — Tests for Section 6 Forensic Claim Ledger protocol verifier."""

import sys
from pathlib import Path

try:
    import pytest  # noqa: F401  (pytest 수집용, unittest 환경에서는 없어도 동작)
except ImportError:
    pytest = None  # type: ignore

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import verify_claim_ledger as vcl


VALID_FORENSIC_LEDGER = """
# Forensic Claim Ledger

| Claim | Risk Level | Sources (2+ Domains / Artifacts) | Counter-Search / Falsification | Primary Source | Status |
|---|---|---|---|---|:---:|
| [Claim 1] 악성코드 hash e3b0c442 발현 | High | sample.evtx, malware_audit.json | 타임스탬프 조작(Timestomping) 부존재 검증 | a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90 | `VERIFIED` |
| [Claim 2] 공격자 내부망 횡이동 시도 | High | firewall.log, pcap_dump.pcap | 외부 트래픽 루프백 오탐 확인 | firewall.log | `REFUTED` |
| [Claim 3] 클라우드 계정 탈취 여부 | Med | auth.log | API 접근 로그 미확보 | auth.log | `UNRESOLVED` |
"""


def test_valid_forensic_claim_ledger_passes():
    res = vcl.validate_claim_ledger(VALID_FORENSIC_LEDGER)
    assert res["ok"] is True
    assert res["totalClaims"] == 3
    assert res["verifiedCount"] == 1
    assert res["refutedCount"] == 1
    assert res["unresolvedCount"] == 1
    assert len(res["violations"]) == 0


def test_forensic_claim_ledger_single_artifact_fails():
    single_artifact_ledger = """
| Claim | Risk Level | Sources (2+ Domains / Artifacts) | Counter-Search / Falsification | Primary Source | Status |
|---|---|---|---|---|:---:|
| [Claim 1] 단일 아티팩트 주장 | High | only_one.evtx | 가설 검증 완료 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | `VERIFIED` |
"""
    res = vcl.validate_claim_ledger(single_artifact_ledger)
    assert res["ok"] is False
    assert any("출처 독립성 미달" in v["violation"] for v in res["violations"])


def test_forensic_claim_ledger_missing_counter_search_fails():
    missing_counter_ledger = """
| Claim | Risk Level | Sources (2+ Domains / Artifacts) | Counter-Search / Falsification | Primary Source | Status |
|---|---|---|---|---|:---:|
| [Claim 1] 반대 가설 미검증 | High | artifact1.evtx, artifact2.json | n/a | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | `VERIFIED` |
"""
    res = vcl.validate_claim_ledger(missing_counter_ledger)
    assert res["ok"] is False
    assert any("명시적 반증 검색" in v["violation"] for v in res["violations"])


def test_forensic_claim_ledger_missing_primary_source_fails():
    missing_primary_ledger = """
| Claim | Risk Level | Sources (2+ Domains / Artifacts) | Counter-Search / Falsification | Primary Source | Status |
|---|---|---|---|---|:---:|
| [Claim 1] 1차 해시 부재 | High | artifact1.evtx, artifact2.json | 반증 가설 기각 | - | `VERIFIED` |
"""
    res = vcl.validate_claim_ledger(missing_primary_ledger)
    assert res["ok"] is False
    assert any("Primary Source" in v["violation"] or "1차 증거 출처" in v["violation"] for v in res["violations"])


def test_synthesis_report_citation_lock_verified():
    report_text = """
    # 디지털 포렌식 감정보고서
    본 분석관은 [Claim 1]의 검증된 침해 사실을 확인하였습니다.
    """
    res = vcl.validate_claim_ledger(VALID_FORENSIC_LEDGER, synthesis_text=report_text)
    assert res["ok"] is True
    assert len(res["violations"]) == 0


def test_synthesis_report_citation_lock_rejects_refuted_and_unresolved():
    report_refuted = "보고서: [Claim 2]에 따라 횡이동이 확인되었습니다."
    res = vcl.validate_claim_ledger(VALID_FORENSIC_LEDGER, synthesis_text=report_refuted)
    assert res["ok"] is False
    assert any("REFUTED" in v["violation"] for v in res["violations"])

    report_unres = "보고서: [Claim 3]에 따라 계정 탈취가 확정되었습니다."
    res_unres = vcl.validate_claim_ledger(VALID_FORENSIC_LEDGER, synthesis_text=report_unres)
    assert res_unres["ok"] is False
    assert any("UNRESOLVED" in v["violation"] for v in res_unres["violations"])


def test_file_level_forensic_ledger_verification(tmp_path):
    ledger_file = tmp_path / "claim-ledger.md"
    ledger_file.write_text(VALID_FORENSIC_LEDGER, encoding="utf-8")
    report_file = tmp_path / "report.md"
    report_file.write_text("결론: [Claim 1]이 검증됨.", encoding="utf-8")

    report = vcl.verify_claim_ledger_file(ledger_file, synthesis_path=report_file)
    assert report["ok"] is True
    assert report["totalClaims"] == 3


def test_forensic_claim_ledger_with_preamble_and_extended_artifacts():
    ledger_with_preamble = """
# Case Overview
| Property | Value |
|---|---|
| Investigator | Chief Examiner |
| Unit | Cyber Forensic Team |

## Claims
| Claim | Risk Level | Sources (2+ Domains / Artifacts) | Counter-Search / Falsification | Primary Source | Status |
|---|---|---|---|---|:---:|
| [Claim 1] 실행 흔적 발견 | High | winlogon.pf, forensic.sqlite, $MFT | 레지스트리 비활성 가설 반증 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 | `VERIFIED` |
| [Claim 2] IP 기반 외부 유출 | Med | http://192.168.1.10/log, https://external-leak.com/data | 내부 루프백 반증 완료 | 192.168.1.10.pcap | `VERIFIED` |
"""
    res = vcl.validate_claim_ledger(ledger_with_preamble)
    assert res["ok"] is True
    assert res["totalClaims"] == 2
    assert res["verifiedCount"] == 2
    assert len(res["violations"]) == 0
