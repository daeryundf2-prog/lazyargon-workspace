"""certify_evidence_file.py 회귀 테스트 — 채증 기록의 해시·시각·URL 결합."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import certify_evidence_file as cef
import processing_receipt as pr


@pytest.fixture()
def capture(tmp_path):
    f = tmp_path / "캡처.png"
    f.write_bytes(b"\x89PNG fake screenshot bytes")
    return f


def test_certify_binds_hash_url_and_time(capture):
    rec = cef.certify([str(capture)], url="https://example.com/p/1", note="본문 캡처", case_number="2024가합1")
    assert rec["items"][0]["sha256"] == hashlib.sha256(capture.read_bytes()).hexdigest()
    assert rec["source_url"] == "https://example.com/p/1"
    assert rec["case_number"] == "2024가합1"
    assert rec["items"][0]["processing_receipt"]["case_id"] == "2024가합1"
    assert rec["items"][0]["file_mtime_utc"].endswith("+00:00")


def test_record_self_hash_deterministic(capture):
    rec = cef.certify([str(capture)], url="u", note="", case_number="")
    assert rec["record_sha256"] == cef.record_hash(rec)


def test_record_hash_excludes_itself(capture):
    rec = cef.certify([str(capture)], url="", note="", case_number="")
    changed = dict(rec)
    changed["record_sha256"] = "tampered"
    assert cef.record_hash(changed) == rec["record_sha256"]


def test_missing_file_returns_empty(capture):
    assert cef.certify([str(capture), "없는파일.png"], "", "", "") == {}


def test_source_url_is_claimed_not_verified(capture):
    capture.write_bytes(b"content")
    rec = cef.certify([str(capture)], url="https://unverified.example/", note="", case_number=None)
    assert rec["items"][0]["processing_receipt"]["parameters"]["claimed_source_url"] == "https://unverified.example/"
    assert rec["items"][0]["processing_receipt"]["case_id"] is None


def test_main_outputs_json_and_markdown_with_receipt(capture, tmp_path):
    out_json = tmp_path / "record.json"
    out_md = tmp_path / "record.md"
    assert cef.main([str(capture), "--url", "https://example.com/x", "--output", str(out_json), "--output-md", str(out_md)]) == 0
    rec = json.loads(out_json.read_text(encoding="utf-8"))
    item = rec["items"][0]
    receipt = item["processing_receipt"]
    assert pr.verify_receipt(receipt) == []
    assert receipt["artifacts"][0]["sha256"] == hashlib.sha256(out_md.read_bytes()).hexdigest()
    assert receipt["review"]["status"] == "pending"
    md = out_md.read_text(encoding="utf-8")
    assert "로컬 파일 측정" in md
    assert hashlib.sha256(capture.read_bytes()).hexdigest() in md
    assert "전자서명도 신뢰 타임스탬프도 아니며" in md or "보관 연속성" in md


def test_explicit_reviewer_approval(tmp_path, capture):
    out_json = tmp_path / "record.json"
    out_md = tmp_path / "record.md"
    assert cef.main([str(capture), "--output", str(out_json), "--output-md", str(out_md), "--reviewer", "검토자"]) == 0
    receipt = json.loads(out_json.read_text(encoding="utf-8"))["items"][0]["processing_receipt"]
    assert receipt["review"] == {"status": "approved", "reviewer": "검토자", "reviewed_at": receipt["review"]["reviewed_at"]}
    assert receipt["review"]["reviewed_at"].endswith("+00:00")
    assert pr.validate_receipt(receipt) == []


def test_approval_requires_verified_artifacts(capture, tmp_path):
    out_json = tmp_path / "record.json"
    out_md = tmp_path / "record.md"
    with pytest.raises(SystemExit):
        cef.main([str(capture), "--output", str(out_json), "--reviewer", "검토자"])
    assert not out_json.exists()
    with pytest.raises(SystemExit):
        cef.main([str(capture), "--output-md", str(out_md), "--reviewer", "검토자"])


def test_changed_source_is_rejected(capture, monkeypatch):
    original_hash = cef._hash_file
    def change_after_hash(path, algorithm):
        digest = original_hash(path, algorithm)
        capture.write_bytes(b"updated synthetic content")
        return digest
    monkeypatch.setattr(cef, "_hash_file", change_after_hash)
    assert cef.certify([str(capture)], "", "", "") == {}


def test_main_missing_file_exit_2():
    assert cef.main(["없는파일.png"]) == 2