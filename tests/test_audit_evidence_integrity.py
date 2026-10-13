"""audit_evidence_integrity.py 회귀 테스트 — 해시 감사·보고서 대조·증명서."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import audit_evidence_integrity as aei
import processing_receipt as pr


@pytest.fixture()
def evidence(tmp_path):
    f1 = tmp_path / "증거1.pdf"
    f1.write_bytes(b"%PDF-1.4 evidence one")
    f2 = tmp_path / "증거2.hwp"
    f2.write_bytes(b"HWP binary evidence two")
    sub = tmp_path / "sub"
    sub.mkdir()
    f3 = sub / "증거3.png"
    f3.write_bytes(b"\x89PNG evidence three")
    return tmp_path, [str(f1), str(f2), str(f3)]


def test_collect_targets_recursive(evidence):
    tmp_path, expected = evidence
    assert sorted(aei.collect_targets(scan_dir=str(tmp_path))) == sorted(expected)


def test_compute_hash_matches_hashlib(evidence):
    _, files = evidence
    assert aei.compute_hash(files[0], "sha256") == hashlib.sha256(Path(files[0]).read_bytes()).hexdigest()


def test_audit_verdicts_against_report(evidence):
    tmp_path, files = evidence
    correct = aei.compute_hash(files[0], "sha256")
    wrong = "0" * 64
    report = f"| 갑 제1호증 | 증거1.pdf | {correct} |\n| 갑 제2호증 | 증거2.hwp | {wrong} |\n"
    result = aei.audit(files[:2], ["sha256"], report)
    verdicts = {Path(r["name"]).name: r["verdict"] for r in result["records"]}
    assert verdicts["증거1.pdf"] == "일치"
    assert verdicts["증거2.hwp"] == "불일치"
    assert result["summary"]["불일치"] == 1


def test_audit_unmentioned_file_is_unmeasured(evidence):
    result = aei.audit(evidence[1], ["sha256"], "관련 내용 없음")
    assert all(r["verdict"] == "미측정" for r in result["records"])


def test_audit_without_report_only_measures(evidence):
    _, files = evidence
    result = aei.audit(files, ["sha256"], "")
    assert all(r["verdict"] == "산출" for r in result["records"])
    assert all(r["hashes"]["sha256"] for r in result["records"])


def test_main_exit_codes_and_markdown(evidence, capsys):
    tmp_path, files = evidence
    correct = aei.compute_hash(files[0], "sha256")
    report = tmp_path / "증거설명서.md"
    report.write_text(f"| 갑 제1호증 | 증거1.pdf | {correct} |", encoding="utf-8")
    out_md = tmp_path / "감사보고서.md"
    assert aei.main(["--file", files[0], "--report", str(report), "-o", str(out_md), "--output-json", str(tmp_path / "audit.json")]) == 0
    md = out_md.read_text(encoding="utf-8")
    assert "일치" in md and "Local Integrity Measurement Record" in md
    wrong = "f" * 64
    report.write_text(f"| 갑 제1호증 | 증거1.pdf | {wrong} |", encoding="utf-8")
    assert aei.main(["--file", files[0], "--report", str(report)]) == 1
    assert aei.main([]) == 2


def test_multi_algorithm_audit(evidence):
    _, files = evidence
    hashes = aei.audit(files[:1], ["sha256", "md5", "sha1"], "")["records"][0]["hashes"]
    assert len(hashes["sha256"]) == 64 and len(hashes["md5"]) == 32 and len(hashes["sha1"]) == 40


def test_swapped_hashes_detected_as_mismatch(tmp_path):
    a = tmp_path / "a.pdf"; a.write_bytes(b"AAA")
    b = tmp_path / "b.pdf"; b.write_bytes(b"BBB")
    report = f"| a.pdf | {aei.compute_hash(str(a), 'sha256')}... |\n| b.pdf | {aei.compute_hash(str(b), 'sha256')}... |\n"
    report = report.replace("...", "")
    wrong = report.replace(aei.compute_hash(str(a), "sha256"), aei.compute_hash(str(b), "sha256"), 1)
    result = aei.audit([str(a)], ["sha256"], wrong)
    assert result["records"][0]["verdict"] == "불일치"


def test_correct_pairing_still_matches(tmp_path):
    a = tmp_path / "a.pdf"; a.write_bytes(b"AAA")
    result = aei.audit([str(a)], ["sha256"], f"| a.pdf | {aei.compute_hash(str(a), 'sha256')} |")
    assert result["records"][0]["verdict"] == "일치"


def test_hash_present_without_filename_marked_caution(tmp_path):
    a = tmp_path / "a.pdf"; a.write_bytes(b"AAA")
    result = aei.audit([str(a)], ["sha256"], f"부록: {aei.compute_hash(str(a), 'sha256')} (파일명 미기재)")
    assert result["records"][0]["verdict"] == "주의"


def test_substring_filename_not_matched(tmp_path):
    a = tmp_path / "a.pdf"; a.write_bytes(b"AAA")
    b = tmp_path / "ba.pdf"; b.write_bytes(b"BBB")
    report = f"| ba.pdf | {aei.compute_hash(str(b), 'sha256')} |"
    result = aei.audit([str(a)], ["sha256"], report)
    assert result["records"][0]["verdict"] == "미측정"


def test_same_basename_different_dirs_ambiguous(tmp_path):
    one = tmp_path / "one"; one.mkdir()
    two = tmp_path / "two"; two.mkdir()
    for index, folder in enumerate((one, two)):
        (folder / "same.pdf").write_bytes(f"content-{index}".encode())
    report = f"| same.pdf | {aei.compute_hash(str(one / 'same.pdf'), 'sha256')} |"
    result = aei.audit([str(one / "same.pdf"), str(two / "same.pdf")], ["sha256"], report)
    assert all(record["verdict"] == "주의" for record in result["records"])


def test_per_algorithm_mismatch_takes_precedence(tmp_path):
    a = tmp_path / "a.pdf"; a.write_bytes(b"AAA")
    data = Path(a).read_bytes()
    correct_sha = hashlib.sha256(data).hexdigest()
    wrong_md5 = "0" * 32
    result = aei.audit([str(a)], ["sha256", "md5"], f"| a.pdf | {correct_sha} | {wrong_md5} |")
    entry = result["records"][0]
    assert entry["verdict"] == "불일치"
    assert entry["algorithm_verdicts"] == {"sha256": "match", "md5": "mismatch"}


def test_conflicting_rows_do_not_pass(tmp_path):
    a = tmp_path / "a.pdf"; a.write_bytes(b"AAA")
    digest = aei.compute_hash(str(a), "sha256")
    report = f"| a.pdf | {digest} |\n| a.pdf | {'e' * 64} |\n"
    result = aei.audit([str(a)], ["sha256"], report)
    assert result["records"][0]["verdict"] == "불일치"


def test_structured_report_with_receipt_and_evidence_id(tmp_path):
    source = tmp_path / "a.pdf"
    source.write_bytes(b"AAA")
    receipt = pr.make_receipt(source, "forensic-export", case_id="case-1", evidence_id="갑 제1호증")
    receipt["source"]["path"] = source.name
    manifest = tmp_path / "export.json"
    manifest.write_text(json.dumps({"evidence_list": [{"evidence_id": "갑 제1호증", "file_path": source.name, "processing_receipt": receipt}]}), encoding="utf-8")
    result = aei.audit([str(source)], ["sha256"], manifest.read_text(encoding="utf-8"), str(tmp_path))
    record = result["records"][0]
    assert record["verdict"] == "일치"
    assert record["evidence_id"] == "갑 제1호증"
    assert record["processing_receipt"]["case_id"] == "case-1"
    assert pr.verify_receipt(record["processing_receipt"]) == []


def test_structured_receipt_tampering_is_not_match(tmp_path):
    source = tmp_path / "a.pdf"
    source.write_bytes(b"AAA")
    receipt = pr.make_receipt(source, "forensic-export", evidence_id="갑 제1호증")
    receipt["source"]["path"] = source.name
    source.write_bytes(b"BBB")
    manifest = tmp_path / "export.json"
    manifest.write_text(json.dumps({"evidence_list": [{"evidence_id": "갑 제1호증", "file_path": source.name, "processing_receipt": receipt}]}), encoding="utf-8")
    result = aei.audit([str(source)], ["sha256"], manifest.read_text(encoding="utf-8"), str(tmp_path))
    assert result["records"][0]["verdict"] == "주의"
    assert "Changed file" in result["records"][0]["verification_warnings"][0]


def test_structured_id_conflict_across_rows(tmp_path):
    source = tmp_path / "a.pdf"
    source.write_bytes(b"AAA")
    manifest = tmp_path / "export.json"
    manifest.write_text(json.dumps({"evidence_list": [
        {"evidence_id": "갑 제1호증", "file_path": source.name},
        {"evidence_id": "갑 제1호증", "file_path": "other.pdf"},
    ]}), encoding="utf-8")
    result = aei.audit([str(source)], ["sha256"], manifest.read_text(encoding="utf-8"), str(tmp_path))
    assert result["records"][0]["verdict"] == "주의"


def test_legacy_report_format_still_supported(tmp_path):
    a = tmp_path / "a.pdf"; a.write_bytes(b"AAA")
    result = aei.audit([str(a)], ["sha256"], f"| a.pdf | {aei.compute_hash(str(a), 'sha256')} |")
    record = result["records"][0]
    assert record["verdict"] == "일치"
    assert record["evidence_id"]
    assert record["processing_receipt"]["evidence_id"] == record["evidence_id"]
    with pytest.raises(ValueError):
        pr.approve_receipt(record["processing_receipt"], "reviewer")


def test_audit_during_change_detected(tmp_path, monkeypatch):
    source = tmp_path / "a.pdf"
    source.write_bytes(b"AAA")
    original_hash = aei.compute_hash
    def change_after_hash(path, algorithm):
        digest = original_hash(path, algorithm)
        source.write_bytes(b"changed synthetic contents")
        return digest
    monkeypatch.setattr(aei, "compute_hash", change_after_hash)
    result = aei.audit([str(source)], ["sha256"], "")
    assert result["records"][0]["verdict"] == "불일치"


def test_make_receipt_unmeasured_when_missing(tmp_path):
    receipt = aei.make_receipt and pr.make_receipt(tmp_path / "absent.pdf", "tool")
    assert receipt["status"] == "not_measured"
    assert receipt["source"]["sha256"] is None
    assert pr.validate_receipt(receipt) == []
