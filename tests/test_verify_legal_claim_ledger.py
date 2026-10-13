# -*- coding: utf-8 -*-
"""test_verify_legal_claim_ledger.py — Tests for Section 6 Claim Ledger protocol verifier in lazyothers."""

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import verify_claim_ledger as vcl


VALID_LEDGER = """
# Claim Ledger

| Claim | Risk Level | Sources (2+ Domains) | Counter-Search Result | Primary Source | Status |
|---|---|---|---|---|:---:|
| [Claim 1] 민법 제750조 손해배상청구 요건 충족 | High | https://law.go.kr/법령/민법, https://glaw.scourt.go.kr | 반대 판례 및 면책 사유 부존재 확인 | https://law.go.kr | `VERIFIED` |
| [Claim 2] 피고의 고의 파산 주장 | High | https://court.go.kr, https://gov.kr | 채무자 회생 절차 개시 기각 판결 확인 | https://glaw.scourt.go.kr | `REFUTED` |
| [Claim 3] 제3자 채무인수 여부 | Med | https://law.go.kr | 추가 증거 서류 미확보 | https://law.go.kr | `UNRESOLVED` |
"""


def test_valid_claim_ledger_passes():
    res = vcl.validate_claim_ledger(VALID_LEDGER)
    assert res["ok"] is True
    assert res["totalClaims"] == 3
    assert res["verifiedCount"] == 1
    assert res["refutedCount"] == 1
    assert res["unresolvedCount"] == 1
    assert len(res["violations"]) == 0


def test_claim_ledger_fewer_than_2_domains_fails():
    single_domain_ledger = """
| Claim | Risk Level | Sources (2+ Domains) | Counter-Search Result | Primary Source | Status |
|---|---|---|---|---|:---:|
| [Claim 1] 단일 도메인 주장 | High | https://only-one.domain.com/page1, https://only-one.domain.com/page2 | 반증 검색 완료 | https://only-one.domain.com | `VERIFIED` |
"""
    res = vcl.validate_claim_ledger(single_domain_ledger)
    assert res["ok"] is False
    assert any("출처 독립성 미달" in v["violation"] for v in res["violations"])


def test_claim_ledger_missing_counter_search_fails():
    missing_counter_ledger = """
| Claim | Risk Level | Sources (2+ Domains) | Counter-Search Result | Primary Source | Status |
|---|---|---|---|---|:---:|
| [Claim 1] 반증 부재 주장 | High | https://site-a.com, https://site-b.com | n/a | https://site-a.com | `VERIFIED` |
"""
    res = vcl.validate_claim_ledger(missing_counter_ledger)
    assert res["ok"] is False
    assert any("명시적 반증 검색" in v["violation"] for v in res["violations"])


def test_claim_ledger_missing_primary_source_fails():
    missing_primary_ledger = """
| Claim | Risk Level | Sources (2+ Domains) | Counter-Search Result | Primary Source | Status |
|---|---|---|---|---|:---:|
| [Claim 1] 1차출처 부재 | High | https://site-a.com, https://site-b.com | 반증 없음 확인 | - | `VERIFIED` |
"""
    res = vcl.validate_claim_ledger(missing_primary_ledger)
    assert res["ok"] is False
    assert any("Primary Source" in v["violation"] or "1차 출처" in v["violation"] for v in res["violations"])


def test_synthesis_citation_lock_verified():
    synth_text = """
    # 준비서면
    [Claim 1]에 기하여 피고의 손해배상 책임을 주장합니다.
    """
    res = vcl.validate_claim_ledger(VALID_LEDGER, synthesis_text=synth_text)
    assert res["ok"] is True
    assert len(res["violations"]) == 0


def test_synthesis_citation_lock_rejects_refuted_and_unresolved():
    synth_text_refuted = """
    # 준비서면
    [Claim 2]에 따르면 피고는 고의 파산하였습니다.
    """
    res = vcl.validate_claim_ledger(VALID_LEDGER, synthesis_text=synth_text_refuted)
    assert res["ok"] is False
    assert any("REFUTED" in v["violation"] for v in res["violations"])

    synth_text_unresolved = """
    # 준비서면
    [Claim 3]에 따라 채무인수를 확인합니다.
    """
    res_unres = vcl.validate_claim_ledger(VALID_LEDGER, synthesis_text=synth_text_unresolved)
    assert res_unres["ok"] is False
    assert any("UNRESOLVED" in v["violation"] for v in res_unres["violations"])


def test_synthesis_citation_lock_rejects_unregistered_claim():
    synth_text_ghost = """
    # 소장
    [Claim 99]의 사실관계에 따릅니다.
    """
    res = vcl.validate_claim_ledger(VALID_LEDGER, synthesis_text=synth_text_ghost)
    assert res["ok"] is False
    assert any("등록되어 있지 않습니다" in v["violation"] for v in res["violations"])


def test_file_level_ledger_verification(tmp_path):
    ledger_file = tmp_path / "claim-ledger.md"
    ledger_file.write_text(VALID_LEDGER, encoding="utf-8")

    synth_file = tmp_path / "draft.md"
    synth_file.write_text("원고는 [Claim 1]에 의해 청구합니다.", encoding="utf-8")
    report = vcl.verify_claim_ledger_file(ledger_file, synthesis_path=synth_file)
    assert report["ok"] is True
    assert report["totalClaims"] == 3


def test_legal_claim_ledger_with_preamble_and_extended_statutes():
    ledger_with_preamble = """
# Case Information
| Attribute | Value |
|---|---|
| Court | Seoul Central District Court |
| Case | 2024Gahap12345 |

## Claim Ledger
| Claim | Risk Level | Sources (2+ Domains / Authorities) | Counter-Search / Falsification | Primary Source | Status |
|---|---|---|---|---|:---:|
| [Claim 1] 부당해고 및 저작권 침해 | High | 근로기준법 제23조, 저작권법 제136조, 2020다12345 | 사직합의 부존재 확인 | 근로기준법 제23조 | `VERIFIED` |
| [Claim 2] 사내 인트라넷 침해 | Med | http://10.0.0.1/audit, https://scourt.go.kr/portal | 사내망 루프백 반증 완료 | 10.0.0.1 | `VERIFIED` |
"""
    res = vcl.validate_claim_ledger(ledger_with_preamble)
    assert res["ok"] is True
    assert res["totalClaims"] == 2
    assert res["verifiedCount"] == 2
    assert len(res["violations"]) == 0

