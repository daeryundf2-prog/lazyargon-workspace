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


if __name__ == "__main__":
    unittest.main()



