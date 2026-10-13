import copy
import hashlib
import hmac
import importlib.util
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
import wave
import zipfile
from contextlib import redirect_stdout
from itertools import combinations
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load(relative):
    spec = importlib.util.spec_from_file_location(Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


receipt = load("scripts/processing_receipt.py")
audit = load("scripts/verify_audit_chain.py")
export = load("scripts/evidence_export.py")
frames = load("skills/forensic-video/scripts/frames.py")
renderer = load("skills/infographic-creator/scripts/render_infographic.py")
video = load("scripts/video_integrity.py")
keyword = load("scripts/keyword_report.py")
timeline = load("scripts/merge_timeline.py")
images = load("scripts/image_similarity.py")
audio = load("scripts/audio_survey.py")
archive = load("scripts/archive_survey.py")
hwpx = load("scripts/extract_hwpx.py")


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def source(self, name="source.txt", content=b"synthetic source"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_receipt_contract_and_artifact_hash(self):
        source = self.source()
        artifact = self.source("artifact.txt", b"derived")
        result = receipt.build_receipt("E1", "test", receipt.TOOL_VERSION, source,
            source_base=self.root, started_at=receipt.utc_now_iso(), artifacts=[artifact])
        self.assertEqual(receipt.validate_receipt(result), [])
        self.assertEqual(result["artifacts"][0]["sha256"], hashlib.sha256(b"derived").hexdigest())
        self.assertEqual(result["review"], {"status": "pending", "reviewer": None, "reviewed_at": None})
        self.assertIsNone(result["case_id"])
        self.assertEqual(result["status"], "not_measured")

    def test_receipt_validation_bad_types_never_crashes(self):
        source = self.source()
        base = receipt.build_receipt("E1", "test", "1", source,
            source_base=self.root, started_at=receipt.utc_now_iso())
        for key in base:
            changed = copy.deepcopy(base)
            del changed[key]
            self.assertTrue(receipt.validate_receipt(changed), key)
        for key, value in (("status", 5), ("source", "bad"), ("artifacts", "bad"),
                           ("review", "bad"), ("tool", 3), ("started_at", 9)):
            changed = copy.deepcopy(base)
            changed[key] = value
            self.assertTrue(receipt.validate_receipt(changed), key)

    def test_receipt_complete_requires_measured_source_and_zero_exit(self):
        source = self.source()
        ok = receipt.build_receipt("E1", "test", "1", source, source_base=self.root,
            started_at=receipt.utc_now_iso(), status="complete", exit_code=0)
        self.assertEqual(receipt.validate_receipt(ok), [])
        for mutate in (lambda r: r["source"].update(sha256=None),
                       lambda r: r.update(exit_code=None),
                       lambda r: r.update(exit_code=1)):
            changed = copy.deepcopy(ok)
            mutate(changed)
            self.assertTrue(receipt.validate_receipt(changed))

    def test_receipt_directory_source_cannot_be_complete(self):
        result = receipt.build_receipt("E1", "test", "1", self.root,
            source_base=self.root.parent, started_at=receipt.utc_now_iso(),
            status="complete", exit_code=0)
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["source"]["sha256"])
        self.assertEqual(receipt.validate_receipt(result), [])

    def test_receipt_null_timestamps_only_when_not_measured(self):
        base = receipt.build_receipt("E1", "test", "1", self.source(),
            source_base=self.root, started_at=receipt.utc_now_iso())
        historical = copy.deepcopy(base)
        historical.update(started_at=None, finished_at=None, status="not_measured")
        self.assertEqual(receipt.validate_receipt(historical), [])
        for status in ("complete", "partial", "failed"):
            changed = copy.deepcopy(historical)
            changed["status"] = status
            self.assertTrue(receipt.validate_receipt(changed), status)

    def test_receipt_build_always_pending_approval_needs_fields(self):
        source = self.source()
        result = receipt.build_receipt("E1", "test", "1", source,
            source_base=self.root, started_at=receipt.utc_now_iso())
        self.assertEqual(result["review"]["status"], "pending")
        declared = copy.deepcopy(result)
        declared["review"] = {"status": "approved", "reviewer": None, "reviewed_at": None}
        self.assertTrue(receipt.validate_receipt(declared))
        declared["review"] = {"status": "pending", "reviewer": "Caller", "reviewed_at": None}
        self.assertTrue(receipt.validate_receipt(declared))
        declared["review"] = {"status": "approved", "reviewer": "Reviewer",
                              "reviewed_at": result["finished_at"]}
        self.assertEqual(receipt.validate_receipt(declared), [])
        earlier = copy.deepcopy(declared)
        earlier["review"]["reviewed_at"] = "2000-01-01T00:00:00Z"
        self.assertTrue(receipt.validate_receipt(earlier))

    def test_receipt_unreadable_artifact_not_fabricated(self):
        source = self.source()
        with self.assertRaises(OSError):
            receipt.build_receipt("E1", "test", "1", source, source_base=self.root,
                started_at=receipt.utc_now_iso(), artifacts=[self.root / "absent.txt"])

    def test_source_containment(self):
        child = self.root / "child"
        child.mkdir()
        outside = self.source()
        with self.assertRaises(ValueError):
            receipt.resolve_source(outside, child)
        link = child / "reference.txt"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaises(ValueError):
            receipt.resolve_source(link, child)

    def test_strict_empty_and_missing_hmac(self):
        trail = self.source("trail.jsonl", b"")
        self.assertEqual(audit.verify_audit_chain(trail, False)["status"], "FAIL")
        result = audit.verify_audit_chain(trail)
        self.assertEqual(result["chain_status"], "not_measured")
        self.assertFalse(result["authenticated"])
        self.assertEqual(audit.verify_audit_chain(trail, require_hmac=True, hmac_key="test")["status"], "FAIL")
        trail.write_text(json.dumps({"timestamp": "2026-01-01T00:00:00Z", "file": "synthetic.txt", "prev_hash": None}), encoding="utf-8")
        result = audit.verify_audit_chain(trail, require_hmac=True, hmac_key="test")
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["valid_chain"])
        self.assertFalse(result["authenticated"])
        self.assertEqual(audit.verify_audit_chain(trail, require_hmac=True, hmac_key="")["status"], "FAIL")

    def test_signed_audit_and_cli(self):
        record = {"timestamp": "2026-01-01T00:00:00Z", "file": "synthetic.txt", "sha256": "", "prev_hash": None}
        message = "|".join(str(record.get(k) or "") for k in ("timestamp", "file", "sha256", "prev_hash"))
        record["hmac"] = hmac.new(b"synthetic-test-key", message.encode(), hashlib.sha256).hexdigest()
        trail = self.source("trail.jsonl", json.dumps(record).encode())
        result = audit.verify_audit_chain(trail, require_hmac=True, hmac_key="synthetic-test-key")
        self.assertTrue(result["authenticated"])
        self.assertTrue(result["valid_chain"])
        proc = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/verify_audit_chain.py"),
            str(trail), "--require-hmac", "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "LAZYFORENSIC_HMAC_KEY": "synthetic-test-key"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["authenticated"])

    def test_export_resolution_provenance_and_no_self_hash(self):
        source = self.source()
        manifest = self.source("manifest.json", json.dumps({"root": str(self.root), "files": [{
            "path": source.name, "sha256": receipt.sha256_file(source), "mtime": "", "size": source.stat().st_size}]}).encode())
        out = self.root / "out.json"
        self.assertEqual(export.main([str(manifest), "-o", str(out)]), 0)
        data = json.loads(out.read_text(encoding="utf-8"))
        item = data["evidence_list"][0]
        self.assertEqual(item["file_path"], str(source))
        self.assertEqual(item["provenance"]["status"], "verified")
        self.assertEqual(item["claimed_sha256"], item["verified_sha256"])
        self.assertEqual(item["processing_receipt"]["status"], "complete")
        self.assertEqual(item["processing_receipt"]["source"]["sha256"], item["sha256"])
        self.assertEqual(receipt.validate_receipt(item["processing_receipt"]), [])
        self.assertEqual(data["processing_receipt"]["artifacts"], [])
        self.assertEqual(receipt.validate_payload(data), [])
        source.write_bytes(b"updated synthetic source")
        self.assertEqual(export.main([str(manifest), "-o", str(out)]), 1)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["processing_receipt"]["status"], "partial")
        self.assertEqual(export.main([str(manifest), "-o", str(source)]), 2)
        self.assertEqual(source.read_bytes(), b"updated synthetic source")

    def test_timeline_offsets_and_stable_unknown_order(self):
        events = [{"timestamp": "2026-01-01T00:30:00+00:00", "id": 1},
                  {"timestamp": "2026-01-01T09:00:00+09:00", "id": 2},
                  {"timestamp": "unknown", "id": 3}, {"timestamp": "", "id": 4}]
        with patch.object(timeline, "events_from_manifest", return_value=events):
            result = timeline.merge(["synthetic"], [], [], [], {})["events"]
        self.assertEqual([e["id"] for e in result], [2, 1, 3, 4])
        self.assertEqual(result[0]["timestamp"], "2026-01-01T09:00:00+09:00")

    def test_metadata_missing_and_failed_probe_unknown(self):
        with patch.object(frames.shutil, "which", return_value=None):
            metadata = frames.get_metadata("synthetic.mp4")
        for field in ("duration", "width", "height", "fps"):
            self.assertIsNone(metadata[field])
        with patch.object(frames.shutil, "which", return_value="ffprobe"), patch.object(
                frames.subprocess, "check_output", side_effect=OSError("unavailable")):
            self.assertFalse(frames.get_metadata("synthetic.mp4")["available"])

    def test_infographic_local_render(self):
        bundle = self.source("bundle.js", b"local bundle placeholder")
        output = self.root / "render.html"
        renderer.render_infographic_html("plain synthetic DSL", str(output), str(bundle), "A & B")
        self.assertIn("A &amp; B", output.read_text(encoding="utf-8"))

    def test_decode_timeout_is_structured(self):
        source = self.source("synthetic.mp4")
        with patch.object(video, "probe", return_value={"streams": [], "format": {}}), patch.object(
                video, "moov_position", return_value="unknown"), patch.object(
                video, "decode_errors", return_value={"decode_error": "timeout", "errors": [], "error_count": None}):
            result = video.audit_video(source)
        self.assertEqual(result["status"], "DECODE_FAILED")
        self.assertIsNone(result["decode_error_count"])

    def test_keyword_read_failure_reported(self):
        source = self.source()
        output = io.StringIO()
        with patch.object(keyword, "search_file_result", return_value=([], "unreadable")), redirect_stdout(output):
            keyword.main([str(source), "word", "--json"])
        result = json.loads(output.getvalue())
        self.assertEqual(result["files_searched"], 0)
        self.assertEqual(result["files_read_failed"], 1)
        self.assertIn(str(source), result["skipped"])

    def test_audio_three_channel_mean_and_partial_second(self):
        source = self.root / "three.wav"
        import struct
        with wave.open(str(source), "wb") as stream:
            stream.setnchannels(3)
            stream.setsampwidth(2)
            stream.setframerate(8001)
            stream.writeframes(struct.pack("<hhh", 9000, -3000, 6000) * 12002)
        result = audio.survey(source, 0.01)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["rms_per_second"]), 2)
        for value in result["rms_per_second"]:
            self.assertAlmostEqual(value, 4000 / 32768, places=4)

    def test_zip_aggregate_limit_benign_members(self):
        source = self.root / "members.zip"
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for n in range(3):
                z.writestr(f"{n}.txt", b"a" * 200)
        with patch.object(archive, "READ_TOTAL_CAP", 500):
            result = archive.audit_zip(source, None)
        self.assertEqual(result["status"], "partial")
        self.assertLessEqual(result["read_budget_charged"], 500)
        self.assertEqual(sum("sha256" in m for m in result["members"]), 2)

    def test_hwpx_small_configured_limit(self):
        source = self.root / "document.hwpx"
        with zipfile.ZipFile(source, "w") as z:
            z.writestr("Contents/section0.xml", "<root>ordinary text</root>")
        with patch.object(hwpx, "SECTION_CAP", 8):
            with self.assertRaises(RuntimeError):
                hwpx.extract_text(source)

    def test_exact_image_candidates_all_thresholds(self):
        rng = random.Random(18)
        hashes = [rng.getrandbits(64) for _ in range(50)]
        hashes += [hashes[0], hashes[0] ^ 7, hashes[1] ^ 255]
        records = [{"phash": h, "ahash": h, "dhash": h, "file": str(i), "colorhist": [1.0]} for i, h in enumerate(hashes)]
        for threshold in (0, 1, 3, 10, 15, 16, 32, 64):
            expected = {(str(i), str(j)) for i, j in combinations(range(len(records)), 2)
                        if (hashes[i] ^ hashes[j]).bit_count() <= threshold}
            actual = {(p["a"], p["b"]) for p in images.find_pairs(records, threshold)}
            self.assertEqual(actual, expected, threshold)

    @unittest.skipIf(sys.platform == "win32",
                     "bin/lazyforensic is a POSIX shell script; symlink + exec requires POSIX")
    def test_symlink_launcher(self):
        link = self.root / "launcher"
        link.symlink_to(ROOT / "bin/lazyforensic")
        second = self.root / "second"
        second.symlink_to("launcher")
        result = subprocess.run([str(second), "manifest", "--help"], capture_output=True,
                                env={**os.environ, "LF_PYTHON": sys.executable}, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
