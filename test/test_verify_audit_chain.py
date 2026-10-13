import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "verify_audit_chain.py"
sys.path.insert(0, str(ROOT / "scripts"))
from verify_audit_chain import verify_audit_chain


class TestVerifyAuditChain(unittest.TestCase):
    def test_empty_trail(self):
        with TemporaryDirectory() as tmp:
            trail = Path(tmp) / "audit_trail.jsonl"
            res = verify_audit_chain(trail, allow_empty=True)
            self.assertEqual(res["status"], "PASS")
            self.assertEqual(res["total_records"], 0)

            res_strict = verify_audit_chain(trail, allow_empty=False)
            self.assertEqual(res_strict["status"], "FAIL")

    def test_valid_hash_chain(self):
        with TemporaryDirectory() as tmp:
            trail = Path(tmp) / "audit_trail.jsonl"
            lines = []

            # Line 1 (genesis)
            r1 = {
                "timestamp": "2026-09-10T12:00:00Z",
                "file": "/tmp/evidence1.bin",
                "sizeBytes": 1024,
                "hook": "post-tool-use",
                "prev_hash": None,
            }
            l1 = json.dumps(r1)
            lines.append(l1)

            # Line 2
            h1 = hashlib.sha256(l1.encode("utf-8")).hexdigest()
            r2 = {
                "timestamp": "2026-09-10T12:01:00Z",
                "file": "/tmp/evidence2.bin",
                "sizeBytes": 2048,
                "hook": "post-tool-use",
                "prev_hash": h1,
            }
            l2 = json.dumps(r2)
            lines.append(l2)

            # Line 3
            h2 = hashlib.sha256(l2.encode("utf-8")).hexdigest()
            r3 = {
                "timestamp": "2026-09-10T12:02:00Z",
                "file": "/tmp/evidence3.bin",
                "sizeBytes": 4096,
                "hook": "post-tool-use",
                "prev_hash": h2,
            }
            l3 = json.dumps(r3)
            lines.append(l3)

            trail.write_text("\n".join(lines) + "\n", encoding="utf-8")

            res = verify_audit_chain(trail)
            self.assertEqual(res["status"], "PASS")
            self.assertEqual(res["total_records"], 3)
            self.assertTrue(res["valid_chain"])

    def test_tampered_hash_chain_detected(self):
        with TemporaryDirectory() as tmp:
            trail = Path(tmp) / "audit_trail.jsonl"
            lines = []

            # Line 1 (genesis)
            r1 = {"timestamp": "2026-09-10T12:00:00Z", "file": "/tmp/evidence1.bin", "sizeBytes": 100, "prev_hash": None}
            l1 = json.dumps(r1)
            lines.append(l1)

            # Line 2
            h1 = hashlib.sha256(l1.encode("utf-8")).hexdigest()
            r2 = {"timestamp": "2026-09-10T12:01:00Z", "file": "/tmp/evidence2.bin", "sizeBytes": 200, "prev_hash": h1}
            l2 = json.dumps(r2)
            lines.append(l2)

            # Tamper with line 1 content after line 2 was created
            lines[0] = json.dumps({"timestamp": "2026-09-10T12:00:00Z", "file": "/tmp/evidence1.bin", "sizeBytes": 999, "prev_hash": None})

            trail.write_text("\n".join(lines) + "\n", encoding="utf-8")

            res = verify_audit_chain(trail)
            self.assertEqual(res["status"], "FAIL")
            self.assertFalse(res["valid_chain"])
            self.assertTrue(any("Hash chain broken" in err for err in res["errors"]))

    def test_cli_execution(self):
        with TemporaryDirectory() as tmp:
            trail = Path(tmp) / "audit_trail.jsonl"
            trail.write_text(json.dumps({"timestamp": "2026-09-10T12:00:00Z", "file": "/tmp/1.bin", "prev_hash": None}) + "\n", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(trail), "--json"],
                capture_output=True,
                encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 0)
            data = json.loads(proc.stdout)
            self.assertEqual(data["status"], "PASS")
            self.assertEqual(data["total_records"], 1)


if __name__ == "__main__":
    unittest.main()
