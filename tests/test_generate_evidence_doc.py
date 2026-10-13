import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import generate_evidence_doc as ged
import processing_receipt as pr


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_doc(tmp_path, items, **extra):
    manifest = tmp_path / "evidence.json"
    manifest.write_text(json.dumps({"evidence_list": items, **extra}), encoding="utf-8")
    output = tmp_path / "report.md"
    result = tmp_path / "report.json"
    code = ged.main(["-i", str(manifest), "-o", str(output), "--output-json", str(result), "--case-num", "2024가합1"])
    return code, output, result


def test_full_sha256_and_relative_path_resolution(tmp_path):
    source = tmp_path / "증거.pdf"
    source.write_bytes(b"synthetic document")
    code, output, result = run_doc(tmp_path, [{"file_path": source.name}])
    assert code == 1
    assert _sha256(source) in output.read_text(encoding="utf-8")
    assert "2024가합1" in output.read_text(encoding="utf-8")
    item = json.loads(result.read_text(encoding="utf-8"))["evidence_list"][0]
    assert item["processing_receipt_status"] == "unverified"
    assert item["hash_status"] == "verified"
    assert item["processing_receipt"]["case_id"] is None


def test_missing_file_marks_na(tmp_path):
    code, output, _ = run_doc(tmp_path, [{"file_path": "absent.pdf"}])
    assert code == 1
    assert "N/A (file not found)" in output.read_text(encoding="utf-8")


def test_explicit_sha256_respected(tmp_path):
    _, output, result = run_doc(tmp_path, [{"sha256": "abc123"}])
    assert "abc123" in output.read_text(encoding="utf-8")
    item = json.loads(result.read_text(encoding="utf-8"))["evidence_list"][0]
    assert item["claimed_sha256"] == "abc123"
    assert item["sha256"] is None
    assert item["hash_status"] == "unknown"


def test_sample_generation_carries_submission_ban_watermark(tmp_path):
    output = tmp_path / "sample.md"
    ged.main(["-o", str(output), "--allow-sample"])
    text = output.read_text(encoding="utf-8")
    assert "법원 제출 금지" in text and "[SAMPLE]" in text


def test_sample_without_flag_is_refused(tmp_path):
    output = tmp_path / "sample.md"
    with pytest.raises(SystemExit) as exc:
        ged.main(["-o", str(output)])
    assert exc.value.code == 2
    assert not output.exists()


def test_real_input_has_no_watermark(tmp_path):
    _, output, _ = run_doc(tmp_path, [{"sha256": "deadbeef"}])
    assert "법원 제출 금지" not in output.read_text(encoding="utf-8")
    assert "변호사 검토" in output.read_text(encoding="utf-8")


def test_malformed_json_falls_back_to_sample_instead_of_crash(tmp_path):
    manifest = tmp_path / "bad.json"
    manifest.write_text("{broken", encoding="utf-8")
    output = tmp_path / "sample.md"
    ged.main(["-i", str(manifest), "-o", str(output), "--allow-sample"])
    assert "법원 제출 금지" in output.read_text(encoding="utf-8")


@pytest.mark.parametrize("claimed", [None, "a" * 64, "matching"])
def test_claimed_hash_is_recomputed(tmp_path, claimed):
    source = tmp_path / "source.txt"
    source.write_text("synthetic source", encoding="utf-8")
    actual = _sha256(source)
    claimed = actual if claimed == "matching" else claimed
    _, _, result = run_doc(tmp_path, [{"file_path": source.name, "sha256": claimed}])
    item = json.loads(result.read_text(encoding="utf-8"))["evidence_list"][0]
    assert item["sha256"] == actual
    assert item["claimed_sha256"] == claimed
    assert item["hash_status"] == ("mismatch" if claimed and claimed != actual else "verified")


def export_item(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("original synthetic evidence", encoding="utf-8")
    artifact = tmp_path / "export.txt"
    artifact.write_text("synthetic derivative", encoding="utf-8")
    receipt = pr.make_receipt(source, "forensic-export", evidence_id="E-001")
    receipt["source"]["path"] = source.name
    receipt["artifacts"] = [{"path": artifact.name, "sha256": _sha256(artifact)}]
    return {"file_path": artifact.name, "evidence_id": "E-001", "processing_receipt": receipt}


def test_forensic_export_end_to_end_and_explicit_approval(tmp_path):
    item = export_item(tmp_path)
    code, output, result = run_doc(tmp_path, [item])
    assert code == 0
    report = json.loads(result.read_text(encoding="utf-8"))
    generated = report["evidence_list"][0]
    assert generated["processing_receipt_status"] == "verified"
    assert generated["imported_processing_receipt"] == item["processing_receipt"]
    receipt = generated["processing_receipt"]
    assert pr.verify_receipt(receipt) == []
    assert receipt["review"]["status"] == "pending"
    assert receipt["artifacts"][0]["sha256"] == _sha256(output)
    manifest = tmp_path / "evidence.json"
    assert ged.main(["-i", str(manifest), "-o", str(output), "--output-json", str(result), "--reviewer", "Synthetic reviewer"]) == 0
    approved = json.loads(result.read_text(encoding="utf-8"))["evidence_list"][0]["processing_receipt"]
    assert approved["review"]["status"] == "approved"
    assert approved["review"]["reviewer"] == "Synthetic reviewer"


@pytest.mark.parametrize("change", ["changed", "missing", "unrelated", "id", "malformed", "partial"])
def test_invalid_export_never_verifies(tmp_path, change):
    item = export_item(tmp_path)
    if change == "changed":
        (tmp_path / "source.txt").write_text("changed synthetic source", encoding="utf-8")
    elif change == "missing":
        (tmp_path / "source.txt").unlink()
    elif change == "unrelated":
        (tmp_path / "other.txt").write_text("unrelated", encoding="utf-8")
        item["file_path"] = "other.txt"
    elif change == "id":
        item["evidence_id"] = "E-002"
    elif change == "malformed":
        item["processing_receipt"] = {"source": []}
    else:
        item["processing_receipt"]["status"] = "partial"
    code, _, result = run_doc(tmp_path, [item])
    assert code == 1
    generated = json.loads(result.read_text(encoding="utf-8"))["evidence_list"][0]
    assert generated["processing_receipt_status"] == "unverified"
    receipt = generated["processing_receipt"]
    if receipt:
        with pytest.raises(ValueError):
            pr.approve_receipt(receipt, "Synthetic reviewer")


def test_input_and_source_output_collisions(tmp_path):
    item = export_item(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"items": [item]}), encoding="utf-8")
    before = manifest.read_bytes()
    assert ged.main(["-i", str(manifest), "-o", str(manifest)]) == 2
    assert manifest.read_bytes() == before
    source = tmp_path / "source.txt"
    before = source.read_bytes()
    assert ged.main(["-i", str(manifest), "-o", str(source)]) == 2
    assert source.read_bytes() == before


def test_no_cwd_fallback_for_missing_relative_source(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("not in manifest directory", encoding="utf-8")
    base = tmp_path / "manifest"
    base.mkdir()
    monkeypatch.chdir(tmp_path)
    items = [{"file_path": "source.txt"}]
    ged.resolve_evidence_hashes(items, str(base))
    assert items[0]["sha256"] is None
