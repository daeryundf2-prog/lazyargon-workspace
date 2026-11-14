"""
케이스 모드 회귀 테스트 — scripts/case_mode.mjs

테스트 대상:
1. case-settings.json 형식 (Antigravity 스키마 키 검증)
2. SHA-256 해시 계산 및 변조 탐지
3. evidence_guard.mjs 파이프라인 false positive 수정 (read-only 파이프 허용, 실제 쓰기 차단)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = "node"
CASE_MODE = str(ROOT / "scripts" / "case_mode.mjs")
EVIDENCE_GUARD = str(ROOT / "scripts" / "evidence_guard.mjs")


def run_node(script, argv=(), env=None, cwd=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(
        [NODE, script, *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=e,
        cwd=str(cwd or ROOT),
    )


def run_guard(argv=(), env=None, stdin_payload=None, cwd=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(
        [NODE, EVIDENCE_GUARD, *argv],
        input=stdin_payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=e,
        cwd=str(cwd or ROOT),
    )


# ---------------------------------------------------------------------------
# Settings JSON shape tests
# ---------------------------------------------------------------------------

class CaseSettingsShapeTests(unittest.TestCase):
    """case init writes .agents/case-settings.json that follows the Antigravity settings schema."""

    def _init_case(self, evidence_dir):
        with tempfile.TemporaryDirectory() as case_dir:
            proc = run_node(
                CASE_MODE,
                ["init", str(evidence_dir), "--out", case_dir],
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            settings_path = Path(case_dir) / ".agents" / "case-settings.json"
            self.assertTrue(settings_path.exists(), "case-settings.json missing")
            return json.loads(settings_path.read_text())

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Create a small evidence folder (not named "evidence")
        self.ev_dir = Path(self.tmp) / "case_evidence_data"
        self.ev_dir.mkdir()
        (self.ev_dir / "sample.bin").write_bytes(b"\x00" * 64)
        (self.ev_dir / "readme.txt").write_text("test evidence")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_required_top_level_keys(self):
        """Antigravity schema keys: enableTerminalSandbox / toolPermission / allowNonWorkspaceAccess / permissions"""
        s = self._init_case(self.ev_dir)
        self.assertIn("enableTerminalSandbox", s)
        self.assertIn("toolPermission", s)
        self.assertIn("allowNonWorkspaceAccess", s)
        self.assertIn("permissions", s)

    def test_sandbox_enabled(self):
        s = self._init_case(self.ev_dir)
        self.assertTrue(s["enableTerminalSandbox"])
        self.assertEqual(s["toolPermission"], "proceed-in-sandbox")
        self.assertFalse(s["allowNonWorkspaceAccess"])

    def test_permissions_subkeys(self):
        s = self._init_case(self.ev_dir)
        p = s["permissions"]
        self.assertIn("allow", p)
        self.assertIn("deny", p)
        self.assertIsInstance(p["allow"], list)
        self.assertIsInstance(p["deny"], list)
        self.assertTrue(set(p) <= {"allow", "ask", "deny"})

    def test_evidence_read_allowed(self):
        """read_file on the evidence path is in allow."""
        s = self._init_case(self.ev_dir)
        allow = s["permissions"]["allow"]
        self.assertTrue(
            any("read_file" in r for r in allow),
            f"read_file rule missing; allow={allow}",
        )

    def test_evidence_write_denied(self):
        """write_file on the evidence path is in deny."""
        s = self._init_case(self.ev_dir)
        deny = s["permissions"]["deny"]
        self.assertTrue(
            any("write_file" in r for r in deny),
            f"write_file rule missing; deny={deny}",
        )

    def test_download_url_denied(self):
        s = self._init_case(self.ev_dir)
        deny = s["permissions"]["deny"]
        self.assertTrue(any("download_url" in r for r in deny))

    def test_execute_url_denied(self):
        s = self._init_case(self.ev_dir)
        deny = s["permissions"]["deny"]
        self.assertTrue(any("execute_url" in r for r in deny))

    def test_research_urls_allowed(self):
        """Research hosts such as attack.mitre.org are in allow."""
        s = self._init_case(self.ev_dir)
        allow_str = " ".join(s["permissions"]["allow"])
        self.assertIn("attack.mitre.org", allow_str)

    def test_no_ask_rule_overrides_allowlist(self):
        """Deny > Ask > Allow: an ask read_url(*) would make every allowlisted host prompt."""
        s = self._init_case(self.ev_dir)
        self.assertNotIn("ask", s["permissions"])

    def test_allowlist_comes_from_config(self):
        import json
        cfg = json.loads((ROOT / "config" / "case-mode-research-allowlist.json").read_text(encoding="utf-8"))
        s = self._init_case(self.ev_dir)
        allow = s["permissions"]["allow"]
        for host in cfg["hosts"]:
            self.assertIn(f"read_url({host})", allow)


# ---------------------------------------------------------------------------
# Hashing and tamper detection tests
# ---------------------------------------------------------------------------

class HashingAndTamperTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ev_dir = Path(self.tmp) / "corpus"
        self.ev_dir.mkdir()
        (self.ev_dir / "file_a.bin").write_bytes(b"\xDE\xAD\xBE\xEF" * 16)
        (self.ev_dir / "file_b.txt").write_text("hello forensics")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_hashes_start_json_created(self):
        with tempfile.TemporaryDirectory() as case_dir:
            proc = run_node(CASE_MODE, ["init", str(self.ev_dir), "--out", case_dir])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            hf = Path(case_dir) / "custody" / "hashes-start.json"
            self.assertTrue(hf.exists())

    def test_hashes_start_json_structure(self):
        with tempfile.TemporaryDirectory() as case_dir:
            run_node(CASE_MODE, ["init", str(self.ev_dir), "--out", case_dir])
            hf = Path(case_dir) / "custody" / "hashes-start.json"
            data = json.loads(hf.read_text())
            self.assertIn("files", data)
            self.assertIn("timestamp", data)
            self.assertIn("evidencePath", data)
            for entry in data["files"]:
                self.assertIn("path", entry)
                self.assertIn("sha256", entry)
                self.assertIn("sizeBytes", entry)
                # SHA-256 hex = 64 chars
                self.assertEqual(len(entry["sha256"]), 64)

    def test_custody_log_jsonl_created(self):
        with tempfile.TemporaryDirectory() as case_dir:
            run_node(CASE_MODE, ["init", str(self.ev_dir), "--out", case_dir])
            log = Path(case_dir) / "custody" / "log.jsonl"
            self.assertTrue(log.exists())
            lines = [l for l in log.read_text().splitlines() if l.strip()]
            self.assertGreater(len(lines), 0)
            first = json.loads(lines[0])
            self.assertEqual(first["type"], "init")

    def test_close_passes_when_untampered(self):
        with tempfile.TemporaryDirectory() as case_dir:
            run_node(CASE_MODE, ["init", str(self.ev_dir), "--out", case_dir])
            proc = run_node(CASE_MODE, ["close", "--case", case_dir])
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)

    def test_close_fails_when_file_tampered(self):
        with tempfile.TemporaryDirectory() as case_dir:
            run_node(CASE_MODE, ["init", str(self.ev_dir), "--out", case_dir])
            # Tamper: append a byte to file_a.bin
            (self.ev_dir / "file_a.bin").write_bytes(b"\xDE\xAD\xBE\xEF" * 16 + b"\xFF")
            proc = run_node(CASE_MODE, ["close", "--case", case_dir])
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("INTEGRITY", proc.stderr + proc.stdout)

    def test_close_fails_when_file_deleted(self):
        with tempfile.TemporaryDirectory() as case_dir:
            run_node(CASE_MODE, ["init", str(self.ev_dir), "--out", case_dir])
            (self.ev_dir / "file_b.txt").unlink()
            proc = run_node(CASE_MODE, ["close", "--case", case_dir])
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("MISSING", proc.stderr + proc.stdout)

    def test_close_fails_on_unexpected_new_file(self):
        with tempfile.TemporaryDirectory() as case_dir:
            run_node(CASE_MODE, ["init", str(self.ev_dir), "--out", case_dir])
            (self.ev_dir / "intruder.bin").write_bytes(b"\x00" * 8)
            proc = run_node(CASE_MODE, ["close", "--case", case_dir])
            self.assertNotEqual(proc.returncode, 0)
            # Should mention new file
            combined = proc.stderr + proc.stdout
            self.assertTrue("NEW" in combined or "unexpected" in combined.lower() or "intruder" in combined)

    def test_close_appends_to_log(self):
        with tempfile.TemporaryDirectory() as case_dir:
            run_node(CASE_MODE, ["init", str(self.ev_dir), "--out", case_dir])
            run_node(CASE_MODE, ["close", "--case", case_dir])
            log = Path(case_dir) / "custody" / "log.jsonl"
            lines = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
            types = [l["type"] for l in lines]
            self.assertIn("init", types)
            self.assertIn("close", types)

    def test_e01_segment_detection(self):
        """E01 세그먼트 세트(disk.E01, disk.E02)를 모두 해싱한다"""
        with tempfile.TemporaryDirectory() as ev_tmp:
            ev_path = Path(ev_tmp)
            (ev_path / "disk.E01").write_bytes(b"\x45\x57\x46" * 100)
            (ev_path / "disk.E02").write_bytes(b"\x45\x57\x46" * 50)
            # disk.E03 does NOT exist — should stop at E02
            with tempfile.TemporaryDirectory() as case_dir:
                proc = run_node(CASE_MODE, ["init", str(ev_path / "disk.E01"), "--out", case_dir])
                self.assertEqual(proc.returncode, 0, proc.stderr)
                hf = Path(case_dir) / "custody" / "hashes-start.json"
                data = json.loads(hf.read_text())
                paths = [Path(f["path"]).name for f in data["files"]]
                self.assertIn("disk.E01", paths)
                self.assertIn("disk.E02", paths)
                self.assertEqual(len(paths), 2)


# ---------------------------------------------------------------------------
# evidence_guard.mjs pipeline false-positive fix tests
# ---------------------------------------------------------------------------

class EvidenceGuardPipelineTests(unittest.TestCase):
    """
    Pipeline false-positive fix:
    - allowed when the evidence path is only an input (read) of the pipeline
    - real writes to the evidence path stay blocked
    """

    def test_strings_pipe_tail_passes(self):
        """strings <evidence>/disk.bin | tail -1 is a read-only pipe: allowed (false-positive fix)."""
        proc = run_guard(
            ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "strings evidence/disk.bin | tail -1"})},
        )
        self.assertEqual(proc.returncode, 0, f"Should pass but got: {proc.stderr}")

    def test_sha256sum_pipe_grep_passes(self):
        """sha256sum evidence/image.e01 | grep -i abc is read-only."""
        proc = run_guard(
            ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "sha256sum evidence/image.e01 | grep -i abc"})},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_cat_pipe_wc_passes(self):
        """cat evidence/log.txt | wc -l is read-only."""
        proc = run_guard(
            ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "cat evidence/log.txt | wc -l"})},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_strings_pipe_head_passes(self):
        """strings evidence/dump.raw | head -20 is read-only."""
        proc = run_guard(
            ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "strings evidence/dump.raw | head -20"})},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_pipe_with_tee_blocked(self):
        """cat evidence/disk.raw | tee backup.raw writes through tee: blocked."""
        proc = run_guard(
            ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "cat evidence/disk.raw | tee backup.raw"})},
        )
        self.assertEqual(proc.returncode, 1, "tee pipeline to evidence should be blocked")
        self.assertIn("BLOCKED", proc.stderr)

    def test_pipe_with_redirect_blocked(self):
        """sha256sum evidence/image.e01 > hashes.txt is a write redirection: blocked (evidence path involved)."""
        proc = run_guard(
            ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "sha256sum evidence/image.e01 > hashes.txt"})},
        )
        # sha256sum is read-only but > is a write sign — guard blocks writing
        # (The write in this case is to hashes.txt, not evidence, but guard conservatively blocks >)
        # This confirms the guard does NOT let > slip through
        self.assertEqual(proc.returncode, 1, "redirect in command should be blocked")

    def test_cp_into_evidence_still_blocked(self):
        """cp img.dmp evidence/ is still blocked."""
        proc = run_guard(
            ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "cp img.dmp evidence/"})},
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("BLOCKED", proc.stderr)

    def test_pipeline_with_semicolon_still_blocked(self):
        """strings evidence/disk.bin | tail -1; rm evil.sh chained with a semicolon: blocked."""
        proc = run_guard(
            ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "strings evidence/disk.bin | tail -1; rm evil.sh"})},
        )
        self.assertEqual(proc.returncode, 1, "semicolon-chained command must be blocked")

    def test_pipeline_with_subshell_blocked(self):
        """strings evidence/disk.bin | $(evil) uses a subshell: blocked."""
        proc = run_guard(
            ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "strings evidence/disk.bin | $(rm -rf /tmp/x)"})},
        )
        self.assertEqual(proc.returncode, 1)

    def test_nonreadonly_first_verb_in_pipe_blocked(self):
        """rm evidence/disk.bin | cat starts with a non-read verb: blocked."""
        proc = run_guard(
            ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "rm evidence/disk.bin | cat"})},
        )
        self.assertEqual(proc.returncode, 1)

    def test_single_strings_still_passes(self):
        """A single strings evidence/disk.bin stays allowed as before."""
        proc = run_guard(
            ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "strings evidence/disk.bin"})},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
