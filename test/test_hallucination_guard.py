import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = ["명백히 입증", "법원에 유효", "유출 확정", "court-admissible", "Timestomping으로 단정"]


class HallucinationGuardTests(unittest.TestCase):
    def test_verify_report_blocks_forbidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "bad.md"
            report.write_text("명백히 입증 되었습니다. SHA256: " + "a"*64, encoding="utf-8")
            proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report)], capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("명백히 입증", proc.stderr)

    def test_verify_report_blocks_orphan_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "hash.md"
            evidence = Path(tmp) / "evidence.json"
            report.write_text("해시: " + "b"*64, encoding="utf-8")
            evidence.write_text(json.dumps({"sha256": "a"*64}), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--evidence", str(evidence)], capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
            self.assertEqual(proc.returncode, 1)
            self.assertIn("근거 없는 해시", proc.stderr)

    def test_verify_report_passes_grounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "good.md"
            evidence = Path(tmp) / "evidence.json"
            h = "c"*64
            report.write_text(f"원본 SHA-256: {h}\n비교 결과: 미측정\n미확인", encoding="utf-8")
            evidence.write_text(h, encoding="utf-8")
            proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--evidence", str(evidence)], capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
            self.assertEqual(proc.returncode, 0)

    def test_verify_report_warns_on_mostly_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "empty.md"
            report.write_text(
                "# 감정서\n\n- 파일 1 해시: 미확인\n- 파일 2 해시: 미확인\n- 파일 3 수정시각: 미측정\n- 파일 4 수정시각: 미확인\n- 파일 5 크기: 1024바이트\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "WARN")
            self.assertEqual(data["unverified"]["count"], 4)
            self.assertEqual(data["unverified"]["claim_lines"], 5)
            self.assertTrue(any("결측 비율" in w for w in data["warnings"]))
            strict = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--strict"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(strict.returncode, 1)

    def test_verify_report_accepts_unverified_with_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "reasoned.md"
            report.write_text(
                "# 감정서\n\n- 파일 1 해시: 미확인(증거 부재 — audit.json 없음)\n- 파일 2 해시: 미확인(모델 유보: 안전 필터)\n- 파일 3 수정시각: 미측정(도구 미설치)\n- 파일 4 수정시각: 미확인(증거 부재)\n- 파일 5 크기: 1024바이트\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "PASS", data)
            self.assertEqual(data["unverified"]["with_reason"], 4)
            self.assertEqual(data["unverified"]["count"], 0)

    def test_guard_timeout_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "검토_보고서.md"
            report.write_text("# 보고서\n\n" + "- 항목: 정상\n" * 200, encoding="utf-8")
            env = dict(os.environ)
            env["TOOL_INPUT"] = json.dumps({"tool_input": {"file_path": str(report)}})
            env["LAZYFORENSIC_VERIFY_TIMEOUT_MS"] = "1"
            proc = subprocess.run(
                ["node", str(ROOT / "scripts" / "hallucination_guard.mjs")],
                capture_output=True, text=True, encoding="utf-8", cwd=tmp, env=env,
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertIn("검증 미완료", proc.stderr)
            self.assertEqual(json.loads(proc.stdout.strip())["decision"], "block")

    def test_no_skill_contains_forbidden_claim(self):
        for path in (ROOT / "skills").rglob("SKILL.md"):
            text = path.read_text(encoding="utf-8")
            for phrase in FORBIDDEN:
                if phrase in text:
                    idx = text.index(phrase)
                    ctx = text[max(0, idx-80):idx+80]
                    if any(k in ctx for k in ["쓰지 않는다", "금지", "FAIL", "의미가 아니다", "아니다", "하지 않는다"]):
                        continue
                    self.fail(f"{path} contains forbidden phrase '{phrase}' outside guard context: {ctx[:120]}")

    def test_gemini_has_hard_grounding(self):
        gemini = (ROOT / "GEMINI.md").read_text(encoding="utf-8")
        self.assertIn("근거-결론 분리", gemini)
        self.assertIn("미확인", gemini)
        self.assertIn("verify_report.py", gemini)
        self.assertIn("유출 확정", gemini)

    def test_gemini_has_argon_field_rules(self):
        # 2026-10 Argon 실사용 보고에서 온 규칙이 GEMINI.md 와 rules 사본 양쪽에 있어야 한다
        for path in (ROOT / "GEMINI.md", ROOT / "rules" / "GEMINI.md"):
            gemini = path.read_text(encoding="utf-8")
            self.assertIn("미확인(모델 유보", gemini, path)
            self.assertIn("민감 증거 원문은 스크립트가 다룬다", gemini, path)
            self.assertIn("비전 판독은 텍스트 증거가 아니다", gemini, path)
            self.assertIn("100줄 이하 청크", gemini, path)
        media = (ROOT / "skills" / "media-analysis" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("--max-frames 20", media)
        self.assertIn("모델 판독(미검증)", media)

    def test_forensic_report_skill_has_verify(self):
        skill = (ROOT / "skills" / "forensic-report" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("verify_report.py", skill)
        self.assertTrue('Model: "inherit"' in skill or 'Model: "pro"' in skill)
        self.assertIn("미측정", skill)

    def test_timeline_and_kakao_still_fail_closed(self):
        # timeline without --input must be 2, kakao without file must be 2
        import importlib.util
        spec = importlib.util.spec_from_file_location("gt", str(ROOT / "skills" / "forensic-timeline" / "scripts" / "generate_timeline.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual(m.main([]), 2)
        spec2 = importlib.util.spec_from_file_location("audit", str(ROOT / "skills" / "forensic-audit" / "scripts" / "audit_timestamps.py"))
        m2 = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(m2)
        self.assertEqual(m2.main(["/no/such/file"]), 2)

    def test_hooks_wire_hallucination_guard_unconditional(self):
        data = json.loads((ROOT / "hooks.json").read_text(encoding="utf-8"))
        post = data["hooks"]["PostToolUse"]
        first = post[0]["hooks"]
        # 문서 쓰기 매처: evidence_guard + hallucination_guard (+ markdown_structure_guard)
        self.assertGreaterEqual(len(first), 2)
        cmds = [h["command"] for h in first]
        self.assertTrue(any("hallucination_guard" in c for c in cmds))
        self.assertTrue(any("evidence_guard" in c for c in cmds))
        hall = [h for h in first if "hallucination_guard" in h["command"]][0]
        self.assertEqual(hall["type"], "command")
        self.assertNotIn("failurePolicy", hall)
        self.assertNotIn("statusMessage", hall)
        self.assertNotIn("PostCompact", data["hooks"])
        # bash 매처: 리다이렉트 쓰기도 같은 게이트를 통과한다 (구버전 우회 경로)
        bash_matchers = [g for g in post if "bash" in g["matcher"]]
        self.assertTrue(bash_matchers)
        bash_hall = [h for h in bash_matchers[0]["hooks"] if "hallucination_guard" in h["command"]]
        self.assertTrue(bash_hall)
        self.assertEqual(bash_hall[0]["type"], "command")

    def test_negation_context_is_not_a_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "negation.md"
            report.write_text(
                "이 사건은 유출의심 아님으로 본다. 조작 가능성을 배제할 수 없다.\n"
                "다만 유출 확정이 아니다.\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_utf16_report_encoding_is_detected(self):
        # Windows PowerShell Out-File 기본값(UTF-16)에서도 금지 문구를 잡아야 한다
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "utf16.md"
            report.write_text("판정: 법원에 유효하다.\n", encoding="utf-16")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("법원에 유효", proc.stderr)

    def test_labeled_md5_hash_is_grounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "md5.md"
            evidence = Path(tmp) / "audit.json"
            md5 = "d" * 32
            report.write_text(f"MD5 (legacy): {md5}\n", encoding="utf-8")
            evidence.write_text(json.dumps({"md5_legacy": md5}), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--evidence", str(evidence)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_labeled_md5_orphan_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "md5bad.md"
            evidence = Path(tmp) / "audit.json"
            report.write_text("MD5: " + "e" * 32 + "\n", encoding="utf-8")
            evidence.write_text(json.dumps({"md5_legacy": "d" * 32}), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--evidence", str(evidence)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 1)

    def test_unlabeled_32hex_is_not_treated_as_hash(self):
        # 무라벨 32hex(UUID 파편 등)는 해시로 취급해 오탈 차단하지 않는다
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "uuid.md"
            report.write_text("레코드 id: " + "0123456789abcdef0123456789abcdef" + "\n", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 0)

    def test_law_citation_without_source_warns_with_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "law.md"
            report.write_text("통신비밀보호법 제14조 제2항 위반이다.\n", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("제14조", proc.stdout)

    def test_audit_trail_jsonl_is_accepted_as_evidence(self):
        # 이 플러그인 자신이 쓰는 .lazyforensic/audit_trail.jsonl 도 근거 파일이어야 한다
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "grounded2.md"
            trail = Path(tmp) / ".lazyforensic" / "audit_trail.jsonl"
            trail.parent.mkdir()
            h = "a" * 64
            trail.write_text(json.dumps({"file": "x", "sha256": h}) + "\n", encoding="utf-8")
            report.write_text(f"SHA-256: {h}\n", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--evidence", str(trail)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_timeline_check_is_per_line_not_global(self):
        # '미확인' 한 줄이 있다고 보고서 전체 시각 검사가 꺼지면 안 된다
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "tl.md"
            events = Path(tmp) / "events.json"
            events.write_text(json.dumps([
                {"timestamp": "2024-01-16 14:00:00", "description": "a"},
            ]), encoding="utf-8")
            report.write_text(
                "근거 시각: 2024-01-16 14:00:00\n"
                "추정 시각: 2024-01-16 15:00:00\n"
                "미확인 시각: 2023-05-05 00:00:00\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--timeline", str(events)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("2024-01-16 15:00:00", proc.stdout)
            self.assertNotIn("2023-05-05", proc.stdout)

    def test_gemini_and_router_require_verify_on_report_keywords(self):
        gemini = (ROOT / "GEMINI.md").read_text(encoding="utf-8")
        router = (ROOT / "skills" / "lazyforensic" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("보고서", gemini)
        self.assertIn("검토해줘", gemini)
        self.assertIn("무조건", gemini)
        self.assertIn("hallucination_guard", gemini)
        self.assertIn("무조건", router)

    def test_verify_report_blocks_fabricated_historical_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "hist_fake.md"
            report.write_text("갑오개혁 4차 개혁안 및 제2차 을사조약 관련 포렌식 기록이다.", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 1)
            data = json.loads(proc.stdout)
            self.assertTrue(any("한국사 사건/조약 날조" in e for e in data["errors"]))

            # Hanja numerals, prefix 第, and single-occurrence treaties/reforms
            report2 = Path(tmp) / "hist_fake2.md"
            report2.write_text("第4次 甲午改革 및 제2차 을미개혁, 제2차 한일병합조약 기록이다.", encoding="utf-8")
            proc2 = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report2), "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc2.returncode, 1)
            data2 = json.loads(proc2.stdout)
            self.assertTrue(any("한국사 사건/조약 날조" in e for e in data2["errors"]))

    def test_verify_report_passes_valid_historical_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "hist_valid.md"
            report.write_text("제1차 갑오개혁 및 을사조약 체결 시점의 포렌식 기록 분석.", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 0)
            data = json.loads(proc.stdout)
            self.assertEqual(len(data["errors"]), 0)

    def test_verify_report_blocks_impossible_judicial_procedures(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "proc_fake.md"
            report.write_text("대검찰청의 약식명령 청구 및 경찰의 영장 직접 청구에 의해 압수수색이 진행되었다.", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 1)
            data = json.loads(proc.stdout)
            self.assertTrue(any("불가능한 사법절차 날조" in e for e in data["errors"]))

            # Long clause sentence
            report2 = Path(tmp) / "proc_fake2.md"
            report2.write_text("대검찰청 특별수사본부는 이번 사건과 관련하여 피의자들에 대해 약식명령을 청구하였다.", encoding="utf-8")
            proc2 = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report2), "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc2.returncode, 1)
            data2 = json.loads(proc2.stdout)
            self.assertTrue(any("불가능한 사법절차 날조" in e for e in data2["errors"]))

    def test_verify_report_blocks_academic_citation_hallucinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "academic_fake.md"
            report.write_text("대한인공지능법학회지 및 홍길동 교수의 2099년 학술지 논문 인용에 근거함.", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 1)
            data = json.loads(proc.stdout)
            self.assertTrue(any("학술논문/학술지 날조" in e for e in data["errors"]))

    def test_verify_report_health_check_cli(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_report.py"), "--health-check", "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(data["status"], "PASS")
        self.assertEqual(data["score"], 100)
        self.assertEqual(data["passed"], data["total"])

    def test_verify_report_hash_binding_ignores_json_keys_and_package_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "android_report.md"
            evidence = Path(tmp) / "audit.json"
            h = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            evidence.write_text(json.dumps({"file": "msg_store.db", "sha256": h}), encoding="utf-8")
            report.write_text(
                '# 감정서\n'
                '패키지 경로: "com.android.providers.telephony" ("com.android...")\n'
                f'메타데이터: {{"pkg.name": "com.kakao.talk", "sha256": "{h}"}}\n'
                '대상 파일: msg_store.db\n',
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), "--evidence", str(evidence), "--json"],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["errors"], [])

    def test_hallucination_guard_skips_manual_and_general_doc_with_report_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            manual = Path(tmp) / "iOS_포렌식_판독_매뉴얼.md"
            manual.write_text(
                "# iOS 포렌식 판독 매뉴얼\n\n"
                "본 매뉴얼은 포렌식 보고서 작성 시 참고할 아티팩트 해시(SHA-256) 개념과 "
                "타임스탬프(2025-05-01 10:00:00) 해석 방법을 설명합니다.\n",
                encoding="utf-8",
            )
            payload = json.dumps({
                "tool_input": {
                    "file_path": str(manual),
                    "content": "포렌식 보고서 작성용 매뉴얼 정리",
                }
            })
            proc = subprocess.run(
                ["node", str(ROOT / "scripts" / "hallucination_guard.mjs")],
                input=payload,
                capture_output=True, text=True, encoding="utf-8", cwd=tmp,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("timeline 근거 파일 미발견", proc.stderr)


if __name__ == "__main__":
    unittest.main()
