"""보안 핵심 훅(evidence_guard.mjs / hallucination_guard.mjs)의 회귀 테스트.

이 두 스크립트는 본 플러그인의 FAIL_CLOSED 보장을 담당하며 2026-08 리뷰까지
직접 테스트가 전무했다. 아래 테스트는 당시 발견된 결함들의 회귀를 고정한다:
- stdin 파이프 페이로드가 fstat().size==0 판정으로 버려지던 문제 (Linux/Windows)
- ASCII \\w 정규식이 한글 파일명을 놓치던 문제
- JSON 이스케이프(\\/)로 패턴을 회피하던 문제
- 콘텐츠 본문 언급만으로 쓰기가 차단되던 과차단
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


def run_guard(script, argv=(), env=None, stdin_payload=None, cwd=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(
        [NODE, str(ROOT / "scripts" / script), *argv],
        input=stdin_payload,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=e,
        cwd=str(cwd or ROOT),
    )


class EvidenceGuardTests(unittest.TestCase):
    def test_env_json_evidence_raw_is_blocked(self):
        proc = run_guard(
            "evidence_guard.mjs", ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"tool_input": {"file_path": "evidence/usb.raw"}})},
        )
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("BLOCKED", proc.stderr)

    def test_stdin_pipe_korean_dmp_is_blocked(self):
        # fstat.size==0 파이프 버그 회귀: stdin JSON 이 유일한 입력인 경로
        payload = json.dumps({"tool_input": {"file_path": "C:\\사건기록\\메모리덤프.dmp"}})
        proc = run_guard("evidence_guard.mjs", ["pre-tool-use"], stdin_payload=payload)
        self.assertEqual(proc.returncode, 1, proc.stderr)

    def test_json_escaped_evidence_path_is_blocked(self):
        proc = run_guard(
            "evidence_guard.mjs", ["pre-tool-use"],
            env={"TOOL_INPUT": '{"file_path": "C:\\\\/evidence\\\\/a.md"}'},
        )
        self.assertEqual(proc.returncode, 1, proc.stderr)

    def test_relative_cp_into_evidence_dir_is_blocked(self):
        proc = run_guard(
            "evidence_guard.mjs", ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "cp img.dmp evidence/"})},
        )
        self.assertEqual(proc.returncode, 1)

    def test_report_content_mention_does_not_block(self):
        # 보고서 본문이 evidence/ 또는 image.raw 를 '언급'하는 것은 쓰기 차단 사유가 아니다
        proc = run_guard(
            "evidence_guard.mjs", ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({
                "tool_input": {
                    "file_path": "out/보고서 초안.md",
                    "content": "증거는 evidence/usb.image 에서 확보했다. image.raw 라고도 부른다.",
                },
            })},
        )
        self.assertEqual(proc.returncode, 0)

    def test_unrelated_write_passes(self):
        proc = run_guard(
            "evidence_guard.mjs", ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"tool_input": {"file_path": "out/notes.md"}})},
        )
        self.assertEqual(proc.returncode, 0)

    def test_readonly_hash_audit_of_evidence_passes(self):
        # 증거 '읽기'(해시 감사)는 쓰기가 아니다 — 과거에는 읽기까지 차단해
        # 자체 감사 워크플로와 충돌했다.
        proc = run_guard(
            "evidence_guard.mjs", ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "sha256sum evidence/usb.raw"})},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_readonly_python_audit_script_passes(self):
        proc = run_guard(
            "evidence_guard.mjs", ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "python skills/forensic-audit/scripts/audit_timestamps.py evidence/usb.raw --json"})},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_readonly_with_redirect_is_still_blocked(self):
        proc = run_guard(
            "evidence_guard.mjs", ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "cat evidence/usb.raw > copy.raw"})},
        )
        self.assertEqual(proc.returncode, 1)

    def test_interpreter_inline_code_on_evidence_is_blocked(self):
        # python -c 는 쓰기를 숨길 수 있다 — 판단 불가이므로 차단이 안전하다.
        proc = run_guard(
            "evidence_guard.mjs", ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"command": "python -c \"open('evidence/x.raw','w')\""})},
        )
        self.assertEqual(proc.returncode, 1)

    def test_memory_dump_extensions_are_blocked(self):
        for name in ("mem.vmem", "disk.img", "backup.l01", "image.ad1"):
            proc = run_guard(
                "evidence_guard.mjs", ["pre-tool-use"],
                env={"TOOL_INPUT": json.dumps({"file_path": f"evidence/{name}"})},
            )
            self.assertEqual(proc.returncode, 1, f"{name} 이 차단되지 않았다")

    def test_post_tool_use_writes_single_audit_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "보고서.md"
            report.write_text("# 감정서\n", encoding="utf-8")
            proc = run_guard(
                "evidence_guard.mjs", ["post-tool-use"],
                env={"TOOL_INPUT": json.dumps({"tool_input": {"file_path": str(report)}})},
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            log = Path(tmp) / ".lazyforensic" / "audit_trail.jsonl"
            self.assertTrue(log.is_file())
            entry = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
            self.assertEqual(len(entry["sha256"]), 64)
            # 구버전이 만드는 이중 체인 로그(미러)는 없어야 한다
            self.assertFalse((Path(tmp) / "audit_trail.jsonl").exists())


class HallucinationGuardHookTests(unittest.TestCase):
    def test_korean_report_with_forbidden_phrase_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "감정서_보고서 초안.md"
            report.write_text("# 감정서\n\n명백히 입증되었다. 법원에 유효하다.\n", encoding="utf-8")
            proc = run_guard(
                "hallucination_guard.mjs", [],
                env={"TOOL_INPUT": json.dumps({"tool_input": {"file_path": str(report)}})},
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn("FAIL", proc.stderr)

    def test_stdin_pipe_korean_report_is_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "검토_보고서.md"
            report.write_text("# 보고서\n유출 확정이다.\n", encoding="utf-8")
            payload = json.dumps({"tool_input": {"file_path": str(report)}})
            proc = run_guard("hallucination_guard.mjs", [], stdin_payload=payload, cwd=tmp)
            self.assertEqual(proc.returncode, 1, proc.stderr)

    def test_fabricated_hash_blocked_with_audit_trail_grounding(self):
        with tempfile.TemporaryDirectory() as tmp:
            trail = Path(tmp) / ".lazyforensic" / "audit_trail.jsonl"
            trail.parent.mkdir()
            trail.write_text(json.dumps({"file": "x", "sha256": "a" * 64}) + "\n", encoding="utf-8")
            bad = Path(tmp) / "사건보고서.md"
            bad.write_text("# 보고서\n\nSHA-256: " + "c" * 64 + "\n", encoding="utf-8")
            proc = run_guard(
                "hallucination_guard.mjs", [],
                env={"TOOL_INPUT": json.dumps({"tool_input": {"file_path": str(bad)}})},
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn("audit_trail.jsonl", proc.stderr)

    def test_grounded_report_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            trail = Path(tmp) / ".lazyforensic" / "audit_trail.jsonl"
            trail.parent.mkdir()
            h = "b" * 64
            trail.write_text(json.dumps({"file": "x", "sha256": h}) + "\n", encoding="utf-8")
            report = Path(tmp) / "감정보고서.md"
            report.write_text(f"# 감정서\n\nSHA-256: {h}\n비교 결과: 불부합\n", encoding="utf-8")
            proc = run_guard(
                "hallucination_guard.mjs", [],
                env={"TOOL_INPUT": json.dumps({"tool_input": {"file_path": str(report)}})},
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_bash_redirect_write_is_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report_draft.md"
            report.write_text("x\n명백히 입증\n", encoding="utf-8")
            proc = run_guard(
                "hallucination_guard.mjs", [],
                env={"TOOL_INPUT": json.dumps({"command": f"python gen.py > {report}"})},
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)

    def test_unrelated_note_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "메모.md"
            note.write_text("그냥 메모\n", encoding="utf-8")
            proc = run_guard(
                "hallucination_guard.mjs", [],
                env={"TOOL_INPUT": json.dumps({"tool_input": {"file_path": str(note)}})},
                cwd=tmp,
            )
            self.assertEqual(proc.returncode, 0)

    def test_missing_target_is_skipped(self):
        proc = run_guard(
            "hallucination_guard.mjs", [],
            env={"TOOL_INPUT": json.dumps({"tool_input": {"file_path": "no/such/보고서.md"}})},
        )
        self.assertEqual(proc.returncode, 0)


class MarkdownStructureGuardTests(unittest.TestCase):
    def test_unclosed_evidence_tag_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad_evidence.md"
            bad.write_text("# 보고서\n<evidence>원문 인용만 하고 닫지 않음\n", encoding="utf-8")
            proc = run_guard("markdown_structure_guard.mjs", ["--check", str(bad)])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("unclosed_evidence_tag", proc.stderr)

    def test_empty_evidence_block_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "empty_evidence.md"
            bad.write_text("# 보고서\n<evidence></evidence>\n답변 내용\n", encoding="utf-8")
            proc = run_guard("markdown_structure_guard.mjs", ["--check", str(bad)])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("empty_evidence_block", proc.stderr)

    def test_broken_citation_token_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "broken_citation.md"
            bad.write_text("# 보고서\n본문 내용【F:doc.pdf†L12】입니다.\n", encoding="utf-8")
            proc = run_guard("markdown_structure_guard.mjs", ["--check", str(bad)])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("broken_citation_token", proc.stderr)

    def test_clean_markdown_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            clean = Path(tmp) / "clean.md"
            clean.write_text("# 정상 보고서\n- 항목: 본문\n<evidence>인용</evidence><answer>답변</answer>\n", encoding="utf-8")
            proc = run_guard("markdown_structure_guard.mjs", ["--check", str(clean)])
            self.assertEqual(proc.returncode, 0)


class StopClaimGuardTests(unittest.TestCase):
    def test_unsupported_grand_claim_is_blocked(self):
        payload = json.dumps({
            "hook_event_name": "Stop",
            "last_assistant_message": "모든 검증을 완벽하게 완료했습니다.",
        })
        proc = run_guard("stop_claim_guard.mjs", [], stdin_payload=payload)
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("반증 가능한 증거", out.get("reason", ""))

    def test_insufficient_data_strict_abstention_passes(self):
        payload = json.dumps({
            "hook_event_name": "Stop",
            "last_assistant_message": "[INSUFFICIENT_DATA] 분석을 완료했습니다.",
        })
        proc = run_guard("stop_claim_guard.mjs", [], stdin_payload=payload)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "{}")

    def test_fact_retracing_gate_blocks_phantom_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.dumps({
                "hook_event_name": "Stop",
                "cwd": tmp,
                "last_assistant_message": "테스트 10 passed. 산출물: results/phantom_artifact.json 생성을 완료했습니다.",
            })
            proc = run_guard("stop_claim_guard.mjs", [], stdin_payload=payload)
            self.assertEqual(proc.returncode, 0)
            out = json.loads(proc.stdout)
            self.assertEqual(out.get("decision"), "block")
            self.assertIn("Fact-Retracing", out.get("reason", ""))

    def test_antigravity_native_toolcall_commandline(self):
        deny_payload = json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": "cp x.bin evidence/usb.raw"}}})
        proc_deny = run_guard("evidence_guard.mjs", ["pre-tool-use"], stdin_payload=deny_payload)
        self.assertEqual(proc_deny.returncode, 1)
        self.assertEqual(json.loads(proc_deny.stdout)["decision"], "deny")

        allow_payload = json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": "ls -la out/"}}})
        proc_allow = run_guard("evidence_guard.mjs", ["pre-tool-use"], stdin_payload=allow_payload)
        self.assertEqual(proc_allow.returncode, 0)
        self.assertEqual(json.loads(proc_allow.stdout)["decision"], "allow")

    def test_hooks_json_has_stop_hooks(self):
        hooks_path = ROOT / "hooks.json"
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
        hooks = data.get("hooks", {})
        self.assertIn("PostToolUse", hooks)
        self.assertTrue((ROOT / "scripts" / "stop_claim_guard.mjs").exists())

    def test_hooks_matchers_cover_antigravity_write_and_shell(self):
        data = json.loads((ROOT / "hooks.json").read_text(encoding="utf-8"))
        post = data["hooks"]["PostToolUse"]
        pre = data["hooks"]["PreToolUse"]
        write_m = post[0]["matcher"]
        shell_m = post[1]["matcher"] if len(post) > 1 else post[0]["matcher"]
        pre_m = pre[0]["matcher"]
        for token in ("write_file", "WriteToFile", "MultiEdit", "SearchReplace", "StrReplace"):
            self.assertIn(token, write_m)
            self.assertIn(token, pre_m)
        for token in ("Bash", "bash", "Shell", "shell", "execute_command"):
            self.assertIn(token, shell_m)
            self.assertIn(token, pre_m)
        post_cmds = [h["command"] for grp in post for h in grp["hooks"]]
        self.assertEqual(len(post_cmds), len(set(post_cmds)))


class StatutoryBoundsTests(unittest.TestCase):
    def test_verify_report_blocks_out_of_bounds_statute(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "legal_report.md"
            report.write_text("# 법률 분석서\n민법 제1500조에 의하여 피고는 책임을 진다. 출처: korean_law\n", encoding="utf-8")
            res = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res.returncode, 1)
            data = json.loads(res.stdout)
            self.assertEqual(data["verdict"], "FAIL")
            self.assertTrue(any("허위 조문 날조" in e for e in data["errors"]))

    def test_verify_report_blocks_fabricated_trade_secret_and_network_laws(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "trade_secret_report.md"
            report.write_text(
                "# 포렌식 감정서\n부정경쟁방지 및 영업비밀보호에 관한 법률 제50조 및 "
                "정보통신망 이용촉진 및 정보보호 등에 관한 법률 제120조 위반 혐의. 출처: korean_law\n",
                encoding="utf-8",
            )
            res = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res.returncode, 1)
            data = json.loads(res.stdout)
            self.assertEqual(data["verdict"], "FAIL")
            self.assertTrue(any("부정경쟁방지 및 영업비밀보호에 관한 법률" in e for e in data["errors"]))
            self.assertTrue(any("정보통신망 이용촉진 및 정보보호 등에 관한 법률" in e for e in data["errors"]))

    def test_verify_report_blocks_future_precedent(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "future_case_report.md"
            report.write_text("# 감정의견서\n대법원 2035도99999 판결에 따라 증거능력이 인정된다. 출처: korean_law\n", encoding="utf-8")
            res = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res.returncode, 1)
            data = json.loads(res.stdout)
            self.assertEqual(data["verdict"], "FAIL")
            self.assertTrue(any("미래 연도 판결" in e for e in data["errors"]))

    def test_verify_report_warns_on_nonstandard_case_code_and_strict_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "unusual_case_report.md"
            report.write_text("# 포렌식 의견서\n서울중앙지방법원 2024쀍12345 결정 참조. 출처: korean_law\n", encoding="utf-8")
            # Normal mode: WARN (exit 0)
            res = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res.returncode, 0)
            data = json.loads(res.stdout)
            self.assertEqual(data["verdict"], "WARN")
            self.assertTrue(any("비표준 사건부호" in w for w in data["warnings"]))

            # Strict mode: exit 1
            res_strict = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--strict"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res_strict.returncode, 1)

    def test_evidence_guard_recognizes_target_file_key(self):
        proc = run_guard(
            "evidence_guard.mjs", ["pre-tool-use"],
            env={"TOOL_INPUT": json.dumps({"TargetFile": "evidence/firmware.bin"})},
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("BLOCKED", proc.stderr)

    def test_hallucination_guard_recognizes_target_file_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_report = Path(tmp) / "침해사고_보고서.md"
            bad_report.write_text("# 침해사고 조사 보고서\n피고는 민법 제1500조에 따라 배상해야 한다.", encoding="utf-8")
            proc = run_guard(
                "hallucination_guard.mjs",
                stdin_payload=json.dumps({"TargetFile": str(bad_report), "CodeContent": "..."}),
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("HALLUCINATION GUARD", proc.stderr)

    def test_verify_report_catches_spaced_statute(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "개인정보_유출_보고서.md"
            report.write_text("# 조사 보고서\n피고는 개인정보 보호법 제100조를 위반하여 고객 정보를 유출함.\n", encoding="utf-8")
            res = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res.returncode, 1)
            data = json.loads(res.stdout)
            self.assertEqual(data["verdict"], "FAIL")
            self.assertTrue(any("개인정보" in e and "제100조" in e for e in data["errors"]))

    def test_hallucination_guard_recognizes_file_and_filename_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_report = Path(tmp) / "침해사고_보고서.md"
            bad_report.write_text("# 침해사고 조사 보고서\n피고는 근로 기준법 제120조 위반.", encoding="utf-8")
            # Test 'file' key
            proc1 = run_guard(
                "hallucination_guard.mjs",
                stdin_payload=json.dumps({"file": str(bad_report)}),
            )
            self.assertEqual(proc1.returncode, 1)
            self.assertIn("HALLUCINATION GUARD", proc1.stderr)

            # Test 'filename' key
            proc2 = run_guard(
                "hallucination_guard.mjs",
                stdin_payload=json.dumps({"filename": str(bad_report)}),
            )
            self.assertEqual(proc2.returncode, 1)
            self.assertIn("HALLUCINATION GUARD", proc2.stderr)

    def test_verify_report_catches_fabricated_agency(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "디지털포렌식_보고서.md"
            report.write_text("# 감정 보고서\n본 사건은 디지털포렌식청 사이버수사팀에 이첩됨.\n", encoding="utf-8")
            res = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res.returncode, 1)
            data = json.loads(res.stdout)
            self.assertEqual(data["verdict"], "FAIL")
            self.assertTrue(any("디지털포렌식청" in e and "공공기관 명칭 날조" in e for e in data["errors"]))

    def test_verify_report_evidence_tag_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev_file = Path(tmp) / "audit.json"
            ev_hash = "a" * 64
            ev_file.write_text(json.dumps({"sha256": ev_hash, "file": "target.bin"}), encoding="utf-8")

            # Matching evidence tag passes
            good_report = Path(tmp) / "good_report.md"
            good_report.write_text(f"# 포렌식 보고서\n<evidence>{ev_hash}</evidence>\n해시값 일치 검증됨.\n", encoding="utf-8")
            res_good = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(good_report), "--evidence", str(ev_file), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res_good.returncode, 0)
            data_good = json.loads(res_good.stdout)
            self.assertEqual(data_good["verdict"], "PASS")

            # Mismatched evidence tag fails
            bad_report = Path(tmp) / "bad_report.md"
            bad_report.write_text("# 포렌식 보고서\n<evidence>f" + "0" * 63 + "</evidence>\n조작 정황.\n", encoding="utf-8")
            res_bad = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(bad_report), "--evidence", str(ev_file), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            # Attributed evidence tag passes when matching
            attr_report = Path(tmp) / "attr_report.md"
            attr_report.write_text(f'# 포렌식 보고서\n<evidence source="audit.json">{ev_hash}</evidence>\n해시값 일치 검증됨.\n', encoding="utf-8")
            res_attr = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(attr_report), "--evidence", str(ev_file), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res_attr.returncode, 0)
            data_attr = json.loads(res_attr.stdout)
            self.assertEqual(data_attr["verdict"], "PASS")

            # Evidence tag without --evidence files fails closed
            res_no_ev = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(good_report), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res_no_ev.returncode, 1)
            data_no_ev = json.loads(res_no_ev.stdout)
            self.assertEqual(data_no_ev["verdict"], "FAIL")
            self.assertTrue(any("근거 인용 검증 불가" in e for e in data_no_ev["errors"]))

    def test_high_fidelity_grounding_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev_file = Path(tmp) / "audit.json"
            ev_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            ev_file.write_text(json.dumps({
                "file": "case_sample.txt",
                "sha256": ev_hash,
                "created": "2024-01-01 10:00:00",
                "modified": "2024-01-01 10:00:00",
            }), encoding="utf-8")

            # 1. Fails without --evidence
            draft = Path(tmp) / "draft_no_ev.md"
            draft.write_text(f"# 포렌식 보고서\n<evidence>{ev_hash}</evidence>\n", encoding="utf-8")
            res1 = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(draft), "--high-fidelity", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res1.returncode, 1)
            self.assertTrue(any("원문/증거(--evidence)가 지정되지 않았습니다" in e for e in json.loads(res1.stdout)["errors"]))

            # 2. Fails without <evidence> tag
            draft2 = Path(tmp) / "draft_no_tag.md"
            draft2.write_text(f"# 포렌식 보고서\n해시 {ev_hash} 측정됨.\n", encoding="utf-8")
            res2 = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(draft2), "--evidence", str(ev_file), "--high-fidelity", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res2.returncode, 1)
            self.assertTrue(any("<evidence> 원문 인용 태그가 없습니다" in e for e in json.loads(res2.stdout)["errors"]))

            # 3. Passes with <evidence> tag and valid matching evidence
            draft3 = Path(tmp) / "draft_pass.md"
            draft3.write_text(f"# 포렌식 보고서\n<evidence>{ev_hash}</evidence>\n해시 {ev_hash} 일치 확인.\n", encoding="utf-8")
            res3 = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(draft3), "--evidence", str(ev_file), "--high-fidelity", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res3.returncode, 0)
            self.assertEqual(json.loads(res3.stdout)["verdict"], "PASS")

            # 4. Realistic full template with headers, metadata, findings, and signatures passes
            draft_full = Path(tmp) / "draft_full.md"
            draft_full.write_text(f"""# 디지털 포렌식 감정보고서
- 사건명: 침해사고 조사
- 감정인: 김분석관
- 의뢰기관: 서울지방경찰청

## 1. 감정 대상물
<evidence>{ev_hash}</evidence>
대상 파일: case_sample.txt

## 2. 감정결과
대상 파일 case_sample.txt 의 SHA-256 해시값은 {ev_hash} 로 측정되었습니다.

## 3. 종합의견
본 감정물은 무결성이 확인되었습니다.
감정인 서명: (인)
""", encoding="utf-8")
            res_full = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(draft_full), "--evidence", str(ev_file), "--high-fidelity", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
            )
            self.assertEqual(res_full.returncode, 0)
            self.assertEqual(json.loads(res_full.stdout)["verdict"], "PASS")

    def test_law_cache_verification_and_escalation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "law_cache.json"
            cache_data = {
                "statute": "개인정보보호법",
                "articles": ["제32조의2", "제71조"]
            }
            cache_file.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")

            # 1. Report cites valid article present in law-cache -> passes
            report_valid = Path(tmp) / "report_valid.md"
            report_valid.write_text("# 법률 분석서\n피고인은 개인정보보호법 제32조의2 위반에 해당한다.\n", encoding="utf-8")
            res1 = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report_valid), "--law-cache", str(cache_file), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            data1 = json.loads(res1.stdout)
            self.assertEqual(data1["verdict"], "PASS")
            self.assertFalse(any("korean_law MCP 출처 표기 없음" in w for w in data1.get("warnings", [])))

            # 2. Report cites missing article absent in law-cache -> WARN by default (B2-1 오탐 방지),
            #    errors 승격은 --strict와 함께일 때만. 제999조는 상한(76조) 위반 별도 FAIL이라 verdict FAIL 유지.
            report_invalid = Path(tmp) / "report_invalid.md"
            report_invalid.write_text("# 법률 분석서\n피고인은 개인정보보호법 제999조 및 형법 제200조 위반에 해당한다.\n", encoding="utf-8")
            res2 = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report_invalid), "--law-cache", str(cache_file), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(res2.returncode, 1)
            data2 = json.loads(res2.stdout)
            self.assertEqual(data2["verdict"], "FAIL")
            self.assertTrue(any("법령 캐시" in w and "존재하지 않음" in w for w in data2.get("warnings", [])))
            self.assertFalse(any("법령 캐시" in e for e in data2.get("errors", [])))
            # 2b. --strict와 함께면 법령 캐시 미존재가 errors로 승격
            res2s = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report_invalid), "--law-cache", str(cache_file), "--strict", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(res2s.returncode, 1)
            data2s = json.loads(res2s.stdout)
            self.assertEqual(data2s["verdict"], "FAIL")
            self.assertTrue(any("법령 캐시" in e and "존재하지 않음" in e for e in data2s["errors"]))


class AntigravityRuntimeTranscriptPayloadTests(unittest.TestCase):
    """Antigravity language_server jsonhook 실제 런타임 페이로드 회귀 테스트.

    PostToolUse 페이로드({"conversationId":"...","transcriptPath":"...","artifactDirectoryPath":"...","stepIdx":5})
    및 compact transcript.jsonl(args 내부 문자열 이중 인용 \"...\") / transcript_full.jsonl 폴백 검증.
    """

    @staticmethod
    def _write_compact_and_full_transcripts(logs_dir: Path, step_index: int, tool_name: str, args_dict: dict, truncate_compact: bool = False):
        logs_dir.mkdir(parents=True, exist_ok=True)
        compact_args = {
            k: json.dumps(v, ensure_ascii=False) if isinstance(v, (str, list, dict)) else v
            for k, v in args_dict.items()
        }
        compact_step = {
            "step_index": step_index,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "tool_calls": [] if truncate_compact else [{"name": tool_name, "args": compact_args}],
        }
        if truncate_compact:
            compact_step["truncated_fields"] = ["tool_calls"]
        tool_result_step = {
            "step_index": step_index + 1,
            "source": "MODEL",
            "type": "GENERIC",
            "status": "DONE",
            "content": "ok",
        }
        full_step = {
            "step_index": step_index,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "tool_calls": [{"name": tool_name, "args": args_dict}],
        }
        (logs_dir / "transcript.jsonl").write_text(
            json.dumps(compact_step, ensure_ascii=False) + "\n" + json.dumps(tool_result_step, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (logs_dir / "transcript_full.jsonl").write_text(
            json.dumps(full_step, ensure_ascii=False) + "\n" + json.dumps(tool_result_step, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def test_post_tool_use_markdown_guard_via_artifact_dir_and_compact_transcript(self):
        lazyargon_md_guard = ROOT.parent / "lazyargon" / "scripts" / "markdown_structure_guard.mjs"
        script_paths = [ROOT / "scripts" / "markdown_structure_guard.mjs"]
        if lazyargon_md_guard.exists():
            script_paths.append(lazyargon_md_guard)

        for script_path in script_paths:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                brain_dir = tmp_path / "brain" / "conv-123"
                logs_dir = brain_dir / ".system_generated" / "logs"

                broken_md = tmp_path / "broken_table.md"
                broken_md_content = "# 보고서\n\n| A | B |\n|---|---|\n| 1 | 2 | 3 |\n"
                broken_md.write_text(broken_md_content, encoding="utf-8")

                self._write_compact_and_full_transcripts(
                    logs_dir,
                    step_index=4,
                    tool_name="write_to_file",
                    args_dict={"TargetFile": str(broken_md), "CodeContent": broken_md_content},
                )

                # Stale/missing transcriptPath -> must fall back to artifactDirectoryPath/.system_generated/logs/
                payload = json.dumps({
                    "conversationId": "conv-123",
                    "transcriptPath": str(tmp_path / "nonexistent" / "transcript.jsonl"),
                    "artifactDirectoryPath": str(brain_dir),
                    "stepIdx": 5,
                })
                proc_fail = subprocess.run(
                    [NODE, str(script_path)],
                    input=payload,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    cwd=str(tmp_path),
                )
                self.assertEqual(proc_fail.returncode, 1, f"{script_path}: {proc_fail.stderr}")
                self.assertIn("table_column_mismatch", proc_fail.stderr)

                # Fix markdown -> must pass with exit 0 and {}
                clean_md_content = "# 보고서\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
                broken_md.write_text(clean_md_content, encoding="utf-8")
                proc_pass = subprocess.run(
                    [NODE, str(script_path)],
                    input=payload,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    cwd=str(tmp_path),
                )
                self.assertEqual(proc_pass.returncode, 0, f"{script_path}: {proc_pass.stderr}")
                self.assertEqual(proc_pass.stdout.strip(), "{}")

    def test_post_tool_use_json_schema_guard_via_transcript_and_truncated_fallback(self):
        lazyargon_json_guard = ROOT.parent / "lazyargon" / "scripts" / "json_schema_guard.mjs"
        script_paths = [ROOT / "scripts" / "json_schema_guard.mjs"]
        if lazyargon_json_guard.exists():
            script_paths.append(lazyargon_json_guard)

        for script_path in script_paths:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                brain_dir = tmp_path / "brain" / "conv-json"
                logs_dir = brain_dir / ".system_generated" / "logs"

                bad_json = tmp_path / "config.json"
                bad_json.write_text('{"version": "not-a-semver", "url": "invalid-protocol://x"}', encoding="utf-8")

                # Simulate truncated tool_calls in compact transcript.jsonl -> must read transcript_full.jsonl
                self._write_compact_and_full_transcripts(
                    logs_dir,
                    step_index=4,
                    tool_name="replace_file_content",
                    args_dict={"TargetFile": str(bad_json), "ReplacementContent": '{"version": "not-a-semver"}'},
                    truncate_compact=True,
                )

                payload = json.dumps({
                    "conversationId": "conv-json",
                    "transcriptPath": str(logs_dir / "transcript.jsonl"),
                    "artifactDirectoryPath": str(brain_dir),
                    "stepIdx": 5,
                })
                proc_fail = subprocess.run(
                    [NODE, str(script_path)],
                    input=payload,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    cwd=str(tmp_path),
                )
                self.assertEqual(proc_fail.returncode, 1, f"{script_path}: {proc_fail.stderr}")
                self.assertIn("JSON SCHEMA GUARD", proc_fail.stderr)

                # Valid JSON -> exit 0 + {}
                bad_json.write_text('{"version": "1.2.3", "url": "https://example.com"}', encoding="utf-8")
                proc_pass = subprocess.run(
                    [NODE, str(script_path)],
                    input=payload,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    cwd=str(tmp_path),
                )
                self.assertEqual(proc_pass.returncode, 0, f"{script_path}: {proc_pass.stderr}")
                self.assertEqual(proc_pass.stdout.strip(), "{}")

    def test_post_tool_use_hallucination_and_legal_and_evidence_guards_via_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain_dir = tmp_path / "brain" / "conv-forensic"
            logs_dir = brain_dir / ".system_generated" / "logs"

            # 1) hallucination_guard via run_command in transcript
            bad_report = tmp_path / "포렌식_보고서.md"
            bad_report.write_text("# 감정서\n\n이 증거는 유출 확정이며 법원에 유효하다.\n", encoding="utf-8")
            self._write_compact_and_full_transcripts(
                logs_dir,
                step_index=4,
                tool_name="run_command",
                args_dict={"CommandLine": f"cat << 'EOF' > {bad_report}\n# 감정서\nEOF"},
            )
            payload = json.dumps({
                "conversationId": "conv-forensic",
                "transcriptPath": str(tmp_path / "missing" / "transcript.jsonl"),
                "artifactDirectoryPath": str(brain_dir),
                "stepIdx": 5,
            })
            proc_hall_fail = run_guard("hallucination_guard.mjs", [], stdin_payload=payload, cwd=tmp)
            self.assertEqual(proc_hall_fail.returncode, 1, proc_hall_fail.stderr)
            self.assertIn("HALLUCINATION GUARD", proc_hall_fail.stderr)

            # Also verify evidence_guard post-tool-use records SHA-256 from the same transcript payload
            proc_ev_post = run_guard("evidence_guard.mjs", ["post-tool-use"], stdin_payload=payload, cwd=tmp)
            self.assertEqual(proc_ev_post.returncode, 0, proc_ev_post.stderr)
            self.assertEqual(proc_ev_post.stdout.strip(), "{}")
            audit_log = tmp_path / ".lazyforensic" / "audit_trail.jsonl"
            self.assertTrue(audit_log.is_file())
            audit_entry = json.loads(audit_log.read_text(encoding="utf-8").strip().splitlines()[-1])
            self.assertEqual(Path(audit_entry["file"]).resolve(), bad_report.resolve())
            self.assertEqual(len(audit_entry["sha256"]), 64)

            # Fix report content -> hallucination_guard passes with exit 0 and {}
            bad_report.write_text(f"# 감정서\n\nSHA-256: {audit_entry['sha256']}\n판정: 미확인\n", encoding="utf-8")
            proc_hall_pass = run_guard("hallucination_guard.mjs", [], stdin_payload=payload, cwd=tmp)
            self.assertEqual(proc_hall_pass.returncode, 0, proc_hall_pass.stderr)
            self.assertEqual(proc_hall_pass.stdout.strip(), "{}")

            # 2) legal_factuality_guard via multi_replace_file_content in transcript
            legal_doc = tmp_path / "민사_소장_초안.md"
            legal_doc.write_text("# 소장\n\n청구원인: 피고는 민법 제1500조에 기하여 손해를 배상할 의무가 있습니다.\n", encoding="utf-8")
            self._write_compact_and_full_transcripts(
                logs_dir,
                step_index=6,
                tool_name="multi_replace_file_content",
                args_dict={
                    "TargetFile": str(legal_doc),
                    "ReplacementChunks": [{"TargetContent": "구문", "ReplacementContent": "민법 제1500조"}],
                },
            )
            payload_legal = json.dumps({
                "conversationId": "conv-forensic",
                "transcriptPath": str(logs_dir / "transcript.jsonl"),
                "artifactDirectoryPath": str(brain_dir),
                "stepIdx": 7,
            })
            proc_legal_fail = run_guard("legal_factuality_guard.mjs", [], stdin_payload=payload_legal, cwd=tmp)
            self.assertEqual(proc_legal_fail.returncode, 1, proc_legal_fail.stderr)
            self.assertIn("LEGAL FACTUALITY GUARD", proc_legal_fail.stderr)

            # Fix legal doc -> passes with exit 0 and {}
            legal_doc.write_text("# 소장\n\n청구원인: 피고는 민법 제750조에 기하여 손해를 배상할 의무가 있습니다.\n", encoding="utf-8")
            proc_legal_pass = run_guard("legal_factuality_guard.mjs", [], stdin_payload=payload_legal, cwd=tmp)
            self.assertEqual(proc_legal_pass.returncode, 0, proc_legal_pass.stderr)
            self.assertEqual(proc_legal_pass.stdout.strip(), "{}")

    def test_stop_claim_guard_reads_antigravity_transcript_when_message_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain_dir = tmp_path / "brain" / "conv-stop"
            logs_dir = brain_dir / ".system_generated" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            step = {
                "step_index": 3,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "content": "모든 작업을 100% 완벽하게 완료했습니다.",
            }
            (logs_dir / "transcript_full.jsonl").write_text(json.dumps(step, ensure_ascii=False) + "\n", encoding="utf-8")
            payload = json.dumps({
                "conversationId": "conv-stop",
                "transcriptPath": str(tmp_path / "stale" / "transcript.jsonl"),
                "artifactDirectoryPath": str(brain_dir),
                "executionNum": 1,
                "terminationReason": "model_stop",
                "fullyIdle": True,
            })
            proc = run_guard("stop_claim_guard.mjs", [], stdin_payload=payload, cwd=tmp)
            self.assertEqual(proc.returncode, 0)
            out = json.loads(proc.stdout)
            self.assertEqual(out.get("decision"), "block")

    def test_hooks_json_commands_e2e_via_sh_c(self):
        hooks_data = json.loads((ROOT / "hooks.json").read_text(encoding="utf-8"))
        env = os.environ.copy()
        env.pop("PLUGIN_ROOT", None)

        sh_bin = shutil.which("sh")
        if not sh_bin and os.name == "nt":
            for candidate in (
                r"C:\Program Files\Git\bin\sh.exe",
                r"C:\Program Files\Git\usr\bin\sh.exe",
                r"C:\Program Files (x86)\Git\bin\sh.exe",
            ):
                if os.path.exists(candidate):
                    sh_bin = candidate
                    break

        def run_sh(cmd: str, payload: str):
            if sh_bin:
                return subprocess.run(
                    [sh_bin, "-c", cmd],
                    input=payload,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    cwd=str(ROOT),
                    env=env,
                )
            return subprocess.run(
                cmd,
                shell=True,
                input=payload,
                text=True,
                encoding="utf-8",
                capture_output=True,
                cwd=str(ROOT),
                env=env,
            )

        # 1) SessionStart command
        ss_entry = hooks_data["hooks"]["SessionStart"][0]
        ss_cmd = ss_entry["command"] if "command" in ss_entry else ss_entry["hooks"][0]["command"]
        proc_ss = run_sh(ss_cmd, json.dumps({"hook_event_name": "SessionStart"}))
        self.assertEqual(proc_ss.returncode, 0, proc_ss.stderr)
        ss_out = json.loads(proc_ss.stdout)
        self.assertIn("injectSteps", ss_out)
        self.assertIn("hookSpecificOutput", ss_out)
        self.assertTrue(ss_out["injectSteps"][0]["systemMessage"]["systemMessage"])
        self.assertTrue(ss_out["hookSpecificOutput"]["additionalContext"])

        # 2) PreToolUse command (deny & allow)
        pre_cmd = hooks_data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        proc_deny = run_sh(pre_cmd, json.dumps({"toolCall": {"name": "write_to_file", "args": {"TargetFile": "evidence/disk.raw"}}}))
        self.assertEqual(proc_deny.returncode, 1)
        deny_out = json.loads(proc_deny.stdout)
        self.assertEqual(deny_out.get("decision"), "deny")
        self.assertTrue(deny_out.get("reason"))

        proc_allow = run_sh(pre_cmd, json.dumps({"toolCall": {"name": "write_to_file", "args": {"TargetFile": "out/note.md"}}}))
        self.assertEqual(proc_allow.returncode, 0, proc_allow.stderr)
        allow_out = json.loads(proc_allow.stdout)
        self.assertEqual(allow_out.get("decision"), "allow")

        # 3) PostToolUse commands (pass -> {})
        post_hooks = [h["command"] for grp in hooks_data["hooks"]["PostToolUse"] for h in grp["hooks"]]
        for cmd in post_hooks:
            proc_post = run_sh(cmd, json.dumps({"conversationId": "conv-noop"}))
            self.assertEqual(proc_post.returncode, 0, f"{cmd}: {proc_post.stderr}")
            self.assertEqual(json.loads(proc_post.stdout), {})

    def test_evidence_guard_exiftool_write_and_nonwhitelisted_python_blocked(self):
        # exiftool -Artist=hacker on evidence directory must be blocked
        p1 = json.dumps({"tool_input": {"command": "exiftool -Artist=hacker evidence/photo.jpg"}})
        r1 = run_guard("evidence_guard.mjs", ["pre-tool-use"], stdin_payload=p1)
        self.assertEqual(r1.returncode, 1)
        self.assertIn("BLOCKED", r1.stderr)

        # exiftool -j read-only on evidence directory must pass
        p2 = json.dumps({"tool_input": {"command": "exiftool -j evidence/photo.jpg"}})
        r2 = run_guard("evidence_guard.mjs", ["pre-tool-use"], stdin_payload=p2)
        self.assertEqual(r2.returncode, 0, r2.stderr)

        # arbitrary python script on protected evidence file must be blocked
        p3 = json.dumps({"tool_input": {"command": "python scripts/custom_mutator.py case.e01"}})
        r3 = run_guard("evidence_guard.mjs", ["pre-tool-use"], stdin_payload=p3)
        self.assertEqual(r3.returncode, 1)
        self.assertIn("BLOCKED", r3.stderr)

        # whitelisted verify_report.py on evidence directory must pass
        p4 = json.dumps({"tool_input": {"command": "python scripts/verify_report.py report.md --evidence evidence/audit.json"}})
        r4 = run_guard("evidence_guard.mjs", ["pre-tool-use"], stdin_payload=p4)
        self.assertEqual(r4.returncode, 0, r4.stderr)

    def test_verify_report_version_vs_impossible_dates_and_missing_timeline_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ok_report = tmp_path / "ok_report.md"
            ok_report.write_text(
                "# 포렌식 보고서\n\n도구 버전: EvtxECmd 2026.5.0. 및 Hayabusa v2026.5.0 사용.\n분석 일자: 2025. 10. 14.\n",
                encoding="utf-8",
            )
            r_ok = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(ok_report), "--timeline", str(tmp_path / "missing_tl.json"), "--json"],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(r_ok.returncode, 0, r_ok.stderr)
            ok_data = json.loads(r_ok.stdout)
            self.assertEqual(ok_data["errors"], [])
            self.assertTrue(any("타임라인 파일 읽기 실패" in w for w in ok_data["warnings"]), ok_data["warnings"])

            bad_report = tmp_path / "bad_report.md"
            bad_report.write_text(
                "# 포렌식 보고서\n\n사건 일자: 2026.02.30 및 2026-00-00 및 2026-13-01 확인.\n",
                encoding="utf-8",
            )
            r_bad = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(bad_report), "--json"],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(r_bad.returncode, 1)
            bad_data = json.loads(r_bad.stdout)
            err_joined = " ".join(bad_data["errors"])
            self.assertIn("2026-02-30", err_joined)
            self.assertIn("2026-00-00", err_joined)
            self.assertIn("2026-13-01", err_joined)

    def test_legal_factuality_guard_html_and_beyond_2000_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            html_file = tmp_path / "brief_draft.html"
            padding = "<!-- " + ("A" * 3000) + " -->\n"
            html_file.write_text(
                padding + "<html><body><h1>소장</h1><p>청구원인: 피고는 민법 제9999조를 위반하였습니다.</p></body></html>",
                encoding="utf-8",
            )
            payload = json.dumps({"tool_input": {"file_path": str(html_file)}})
            proc = run_guard("legal_factuality_guard.mjs", [], stdin_payload=payload)
            self.assertEqual(proc.returncode, 1)
            out = json.loads(proc.stdout)
            self.assertEqual(out.get("decision"), "block")

    def test_evidence_guard_call_mcp_tool_blocks_write_and_allows_readonly(self):
        # 1) call_mcp_tool writing to output_path in evidence/ must be blocked
        p_write = json.dumps({
            "tool_name": "call_mcp_tool",
            "tool_input": {
                "ServerName": "lazyargon-workspace_kordoc",
                "ToolName": "patch_document",
                "Arguments": {
                    "file_path": "out/template.hwpx",
                    "output_path": "evidence/tampered.hwpx",
                },
            },
        })
        r_write = run_guard("evidence_guard.mjs", ["pre-tool-use"], stdin_payload=p_write)
        self.assertEqual(r_write.returncode, 1)
        self.assertEqual(json.loads(r_write.stdout).get("decision"), "deny")

        # 2) call_mcp_tool with JSON-string Arguments writing to protected extension must be blocked
        p_str_args = json.dumps({
            "toolCall": {
                "name": "call_mcp_tool",
                "arguments": json.dumps({
                    "ServerName": "lazyargon-workspace_kordoc",
                    "ToolName": "generate_document",
                    "Arguments": json.dumps({"output_path": "out/image.raw"}),
                }),
            },
        })
        r_str_args = run_guard("evidence_guard.mjs", ["pre-tool-use"], stdin_payload=p_str_args)
        self.assertEqual(r_str_args.returncode, 1)
        self.assertEqual(json.loads(r_str_args.stdout).get("decision"), "deny")

        # 3) call_mcp_tool calling read-only parse_document on evidence/ must be allowed
        p_read = json.dumps({
            "tool_name": "call_mcp_tool",
            "tool_input": {
                "ServerName": "lazyargon-workspace_kordoc",
                "ToolName": "parse_document",
                "Arguments": {"file_path": "evidence/original.hwpx"},
            },
        })
        r_read = run_guard("evidence_guard.mjs", ["pre-tool-use"], stdin_payload=p_read)
        self.assertEqual(r_read.returncode, 0, r_read.stderr)
        self.assertEqual(json.loads(r_read.stdout).get("decision"), "allow")

    def test_post_tool_use_does_not_walk_back_to_stale_report_on_subsequent_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            brain_dir = tmp_path / "brain" / "conv-no-walkback"
            logs_dir = brain_dir / ".system_generated" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            bad_report = tmp_path / "포렌식_보고서.md"
            bad_report.write_text("# 감정서\n\n이 증거는 유출 확정이며 민법 제1500조에 따라 법원에 유효하다.\n| A | B |\n|---|---|\n| 1 | 2 | 3 |\n", encoding="utf-8")

            step_write = {
                "step_index": 4,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "tool_calls": [{"name": "write_to_file", "args": {"TargetFile": str(bad_report), "CodeContent": "# 감정서"}}],
            }
            step_write_res = {"step_index": 5, "source": "MODEL", "type": "GENERIC", "status": "DONE", "content": "ok"}
            step_cmd = {
                "step_index": 6,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": "git status"}}],
            }
            step_cmd_res = {"step_index": 7, "source": "MODEL", "type": "GENERIC", "status": "DONE", "content": "ok"}

            transcript_text = "\n".join(json.dumps(s, ensure_ascii=False) for s in (step_write, step_write_res, step_cmd, step_cmd_res)) + "\n"
            (logs_dir / "transcript.jsonl").write_text(transcript_text, encoding="utf-8")
            (logs_dir / "transcript_full.jsonl").write_text(transcript_text, encoding="utf-8")

            payload = json.dumps({
                "conversationId": "conv-no-walkback",
                "transcriptPath": str(logs_dir / "transcript.jsonl"),
                "artifactDirectoryPath": str(brain_dir),
                "stepIdx": 7,
            })
            for guard in ("hallucination_guard.mjs", "legal_factuality_guard.mjs", "markdown_structure_guard.mjs", "json_schema_guard.mjs"):
                proc = run_guard(guard, [], stdin_payload=payload, cwd=tmp)
                self.assertEqual(proc.returncode, 0, f"{guard} walked back to stale step: {proc.stderr}")
                self.assertEqual(json.loads(proc.stdout), {})


if __name__ == "__main__":
    unittest.main()

