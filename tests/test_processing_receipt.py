from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import processing_receipt as pr


@pytest.fixture()
def evidence(tmp_path):
    src = tmp_path / "원본.pdf"
    src.write_bytes(b"original evidence bytes")
    out = tmp_path / "파생.pdf"
    out.write_bytes(b"derived artifact bytes")
    return tmp_path, str(src), str(out)


def make(evidence):
    _, src, out = evidence
    receipt = pr.make_receipt(src, "test-tool", case_id="2024가합12345", evidence_id="갑 제1호증")
    receipt["artifacts"] = [{"path": out, "sha256": pr.hash_file(out)}]
    return receipt


def test_valid_receipt_passes(evidence):
    receipt = make(evidence)
    assert pr.validate_receipt(receipt) == []
    assert pr.verify_receipt(receipt, base_dir=evidence[0]) == []


def test_unknown_case_id_is_null(evidence):
    _, src, _ = evidence
    receipt = pr.make_receipt(src, "test-tool")
    assert receipt["case_id"] is None
    assert pr.validate_receipt(receipt) == []


def test_missing_changed_source_detected(evidence):
    receipt = make(evidence)
    Path(receipt["source"]["path"]).write_bytes(b"tampered content")
    errors = pr.verify_receipt(receipt, base_dir=evidence[0])
    assert any("Changed file" in e for e in errors)


def test_missing_source_detected(evidence):
    receipt = make(evidence)
    Path(receipt["source"]["path"]).unlink()
    errors = pr.verify_receipt(receipt, base_dir=evidence[0])
    assert any("Missing, unreadable" in e for e in errors)


def test_unmeasured_source_not_verifiable(evidence):
    _, src, out = evidence
    receipt = {
        "schema_version": "1.0", "case_id": None, "evidence_id": "갑 제1호증",
        "status": "complete", "source": {"path": src, "sha256": None},
        "artifacts": [], "tool": {"name": "t", "version": "1.0"}, "parameters": {},
        "started_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:00:01+00:00",
        "exit_code": 0, "warnings": [], "limitations": [],
        "review": {"status": "pending", "reviewer": None, "reviewed_at": None},
    }
    errors = pr.validate_receipt(receipt)
    assert errors == ["Complete receipt requires measured source and zero exit_code"]
    assert pr.verify_receipt(receipt, base_dir=evidence[0]) == errors
    receipt["status"] = "not_measured"
    verify_errors = pr.verify_receipt(receipt, base_dir=evidence[0])
    assert any("Unmeasured" in e for e in verify_errors)
    assert any("not complete" in e for e in verify_errors)


def test_old_format_marked_unverified():
    legacy = {"file": "legacy.pdf", "sha256": "abc"}
    assert pr.validate_receipt(legacy) != []


def test_complete_requires_zero_exit_and_source(evidence):
    receipt = make(evidence)
    receipt["exit_code"] = 1
    assert any("zero exit_code" in e for e in pr.validate_receipt(receipt))


def test_approval_flow(evidence):
    receipt = make(evidence)
    with pytest.raises(ValueError):
        pr.approve_receipt(receipt, "", base_dir=evidence[0])
    approved = pr.approve_receipt(receipt, "검토자", base_dir=evidence[0])
    assert approved["review"]["status"] == "approved"
    assert approved["review"]["reviewer"] == "검토자"
    original = make(evidence)
    assert original["review"]["status"] == "pending"


def test_no_artifacts_rejects_approval(evidence):
    _, src, _ = evidence
    receipt = pr.make_receipt(src, "test-tool")
    with pytest.raises(ValueError):
        pr.approve_receipt(receipt, "검토자", base_dir=evidence[0])


def test_receipt_links_evidence_id(evidence):
    receipt = make(evidence)
    assert receipt["evidence_id"] == "갑 제1호증"
    assert receipt["status"] == "complete"


def test_null_timestamps_only_when_not_measured(evidence):
    receipt = make(evidence)
    receipt["status"] = "not_measured"
    receipt["exit_code"] = None
    receipt["started_at"] = receipt["finished_at"] = None
    assert pr.validate_receipt(receipt) == []
    for status in ("complete", "partial", "failed"):
        receipt["status"] = status
        assert any("Invalid UTC" in e for e in pr.validate_receipt(receipt)), status


def test_pending_review_rejects_declared_reviewer(evidence):
    receipt = make(evidence)
    receipt["review"]["reviewer"] = "caller-claimed"
    assert any("Pending review" in e for e in pr.validate_receipt(receipt))
