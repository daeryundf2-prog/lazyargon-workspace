import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relpath):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verify_rep = load_module("verify_report", "scripts/verify_report.py")
report_core = load_module("report_core", "scripts/report_core.py")

HASH_OWNED = "ab" * 32
HASH_OTHER = "cd" * 32
HASH_PIN_ONLY = "ef" * 32


def run_verify(report_text, evidence_files):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        verify_rep.main([str(report_text), "--evidence", *map(str, evidence_files)])
    return buf.getvalue()


class EvidenceLoadingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._old_cwd = Path.cwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_utf16le_audit_json_hash_is_recognized(self):
        audit = self.tmp / "audit.json"
        payload = [{"file": "evidence.E01", "sha256": HASH_OWNED}]
        audit.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-16"))
        report = self.tmp / "report.md"
        report.write_text(f"원본 SHA-256: {HASH_OWNED} (evidence.E01)\n", encoding="utf-8")

        hashes = report_core.load_evidence_hashes([str(audit)], report_path=report)
        self.assertIn(HASH_OWNED, hashes)

        output = run_verify(report, [audit])
        self.assertNotIn("근거 없는 해시", output)

    def test_hash_only_in_pins_md_is_orphan(self):
        pins_dir = self.tmp / ".lazyargon"
        pins_dir.mkdir()
        (pins_dir / "pins.md").write_text(f"- 원본 SHA-256: {HASH_PIN_ONLY}\n", encoding="utf-8")
        audit = self.tmp / "audit.json"
        audit.write_text(json.dumps([{"file": "other.E01", "sha256": HASH_OTHER}]), encoding="utf-8")
        report = self.tmp / "report.md"
        report.write_text(f"원본 SHA-256: {HASH_PIN_ONLY} (other.E01)\n", encoding="utf-8")

        hashes = report_core.load_evidence_hashes([str(audit)], report_path=report)
        self.assertNotIn(HASH_PIN_ONLY, hashes)

        output = run_verify(report, [audit])
        self.assertIn("근거 없는 해시", output)

    def test_evidence_tag_curly_quotes_match_straight_quoted_evidence(self):
        evidence = self.tmp / "statement.txt"
        evidence.write_text('진술: "현장에 있었다"\n', encoding="utf-8")
        report = self.tmp / "report.md"
        report.write_text(
            "피의자는 <evidence>진술: \u201c현장에 있었다\u201d</evidence> 라고 말했다.\n",
            encoding="utf-8",
        )

        output = run_verify(report, [evidence])
        self.assertNotIn("근거 인용 불일치", output)

    def test_evidence_tag_absent_phrase_still_reports_mismatch(self):
        evidence = self.tmp / "statement.txt"
        evidence.write_text('진술: "현장에 있었다"\n', encoding="utf-8")
        report = self.tmp / "report.md"
        report.write_text(
            "피의자는 <evidence>진술: \u201c현장에 없었다\u201d</evidence> 라고 말했다.\n",
            encoding="utf-8",
        )

        output = run_verify(report, [evidence])
        self.assertIn("근거 인용 불일치", output)


if __name__ == "__main__":
    unittest.main()
