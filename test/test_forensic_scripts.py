import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_module(name, relpath):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


timeline = load_module("generate_timeline", "skills/forensic-timeline/scripts/generate_timeline.py")
audit = load_module("audit_timestamps", "skills/forensic-audit/scripts/audit_timestamps.py")
kakao = load_module("parse_kakao", "skills/kakao-chat-extractor/scripts/parse_kakao.py")
video_config = load_module("forensic_video_config", "skills/forensic-video/scripts/config.py")
video_whisper = load_module("forensic_video_whisper", "skills/forensic-video/scripts/whisper.py")


class TimelineTests(unittest.TestCase):
    def test_missing_input_exits_nonzero(self):
        # given no --input
        # when CLI runs
        code = timeline.main([])
        # then argparse fails closed
        self.assertEqual(code, 2)

    def test_empty_events_ok(self):
        # given empty list
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "empty.json"
            out = Path(tmp) / "out.html"
            src.write_text("[]", encoding="utf-8")
            # when
            code = timeline.main(["--input", str(src), "--output", str(out)])
            # then
            self.assertEqual(code, 0)
            html = out.read_text(encoding="utf-8")
            self.assertIn("0 건", html)
            self.assertNotIn("SanDisk", html)

    def test_escapes_html(self):
        # given XSS payload events
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.html"
            # when
            code = timeline.main([
                "--input", str(FIXTURES / "events_xss.json"),
                "--output", str(out),
            ])
            # then
            self.assertEqual(code, 0)
            html = out.read_text(encoding="utf-8")
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
            self.assertIn("a &amp; b", html)

    def test_rejects_object_root(self):
        # given object instead of list
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "bad.json"
            out = Path(tmp) / "out.html"
            src.write_text('{"timestamp":"x"}', encoding="utf-8")
            # when
            code = timeline.main(["--input", str(src), "--output", str(out)])
            # then
            self.assertEqual(code, 2)
            self.assertFalse(out.exists())

    def test_iso_events_are_sorted_and_critical_label_is_neutral(self):
        # given reverse-ordered ISO events
        events = [
            {"timestamp": "2024-01-16 15:00:00", "category": "critical", "description": "later"},
            {"timestamp": "2024-01-16 14:00:00", "category": "system", "description": "earlier"},
        ]
        # when
        html = timeline.generate_html(events)
        # then
        self.assertLess(html.index("earlier"), html.index("later"))
        self.assertIn("시각 오름차순", html)
        self.assertIn(">주의<", html)
        self.assertNotIn("유출의심", html)

    def test_source_has_no_sample_usb_story(self):
        # given generator source
        src = (ROOT / "skills/forensic-timeline/scripts/generate_timeline.py").read_text(encoding="utf-8")
        # then no baked leakage narrative
        self.assertNotIn("SanDisk", src)
        self.assertNotIn("최종_설계안.zip", src)


class AuditTests(unittest.TestCase):
    def test_missing_file_exits_nonzero(self):
        # given missing path
        code = audit.main([str(ROOT / "no-such-file-for-audit.bin")])
        # then
        self.assertEqual(code, 2)

    def test_stat_only_and_timezone(self):
        # given this test file
        target = Path(__file__)
        # when
        res = audit.audit_file(str(target), tz=timezone.utc, platform_name="nt")
        # then
        self.assertIsNotNone(res)
        self.assertIn("os.stat()", res["limitations"])
        self.assertIn("$MFT", res["limitations"])
        self.assertIn("+0000", res["created_time"])
        self.assertIn("Windows creation time", res["ctime_semantics"])
        self.assertEqual(len(res["sha256"]), 64)
        self.assertIn("md5_legacy", res)
        self.assertNotIn("is_inverted", res)

    def test_copy_like_ctime_not_called_tamper(self):
        # given created > modified
        later = datetime(2024, 1, 16, 15, 0, tzinfo=timezone.utc).timestamp()
        earlier = datetime(2024, 1, 16, 14, 0, tzinfo=timezone.utc).timestamp()

        class FakeStat:
            st_ctime = later
            st_mtime = earlier
            st_atime = later
            st_size = 1

        original_exists = audit.os.path.exists
        original_stat = audit.os.stat
        original_hashes = audit.compute_hashes
        try:
            audit.os.path.exists = lambda _p: True
            audit.os.stat = lambda _p: FakeStat()
            audit.compute_hashes = lambda _p: ("d" * 32, "a" * 64)
            res = audit.audit_file("fake.bin", tz=timezone.utc, platform_name="nt")
        finally:
            audit.os.path.exists = original_exists
            audit.os.stat = original_stat
            audit.compute_hashes = original_hashes

        # then
        self.assertTrue(res["created_gt_modified"])
        self.assertIn("복사/다운로드", res["analysis_note"])
        self.assertNotIn("역전 발견", res["analysis_note"])
        self.assertNotIn("조작 가능성", res["analysis_note"])

    def test_posix_ctime_is_not_reported_as_creation(self):
        class FakeStat:
            st_ctime = 2
            st_mtime = 1
            st_atime = 2
            st_size = 1

        original_exists = audit.os.path.exists
        original_stat = audit.os.stat
        original_hashes = audit.compute_hashes
        try:
            audit.os.path.exists = lambda _p: True
            audit.os.stat = lambda _p: FakeStat()
            audit.compute_hashes = lambda _p: ("d" * 32, "a" * 64)
            res = audit.audit_file("fake.bin", tz=timezone.utc, platform_name="posix")
        finally:
            audit.os.path.exists = original_exists
            audit.os.stat = original_stat
            audit.compute_hashes = original_hashes

        self.assertEqual(res["created_time"], "N/A")
        self.assertFalse(res["created_gt_modified"])
        self.assertIn("not file creation", res["ctime_semantics"])


class KakaoTests(unittest.TestCase):
    def test_mobile_format(self):
        # given mobile export
        msgs = kakao.parse_kakao_file(str(FIXTURES / "kakao_mobile.txt"))
        # then
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0]["timestamp"], "2024-01-16 14:15:00")
        self.assertEqual(msgs[1]["timestamp"], "2024-01-16 00:05:00")
        self.assertEqual(msgs[2]["timestamp"], "2024-01-16 12:00:00")
        self.assertTrue(msgs[1]["has_attachment"])
        self.assertIn("두 번째 줄", msgs[2]["message"])
        self.assertEqual(msgs[0]["second_precision"], "export-has-no-seconds")

    def test_pc_format(self):
        # given PC export
        msgs = kakao.parse_kakao_file(str(FIXTURES / "kakao_pc.txt"))
        # then
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["timestamp"], "2024-01-16 14:15:22")
        self.assertTrue(msgs[1]["has_attachment"])

    def test_utf16(self):
        # given UTF-16 LE export
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kakao16.txt"
            text = "--------------- 2024년 1월 16일 화요일 ---------------\n[홍길동] [오후 2:15] 안녕\n"
            path.write_bytes(text.encode("utf-16"))
            # when
            msgs = kakao.parse_kakao_file(str(path))
            # then
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0]["sender"], "홍길동")

    def test_mobile_without_date_header_has_unknown_timestamp(self):
        msgs = kakao.parse_kakao_text("[홍길동] [오후 2:15] 날짜 없음")
        self.assertEqual(len(msgs), 1)
        self.assertIsNone(msgs[0]["timestamp"])
        self.assertTrue(msgs[0]["timestamp_unknown"])

    def test_pc_sender_may_contain_colon(self):
        msgs = kakao.parse_kakao_text("[2024-01-16 14:15:22] 팀:홍길동: 안녕하세요.")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["sender"], "팀:홍길동")

    def test_real_pc_export_format_parses(self):
        # 실제 카카오톡 PC '대화내용 저장' 포맷 (===== 헤더 + [오후 2:15] 닉네임 : 메시지)
        msgs = kakao.parse_kakao_file(str(FIXTURES / "kakao_pc_real.txt"))
        messages = [r for r in msgs if r["type"] == "message"]
        self.assertEqual(len(messages), 5)
        self.assertEqual(messages[0]["timestamp"], "2024-01-16 14:15:00")
        self.assertEqual(messages[0]["second_precision"], "export-has-no-seconds")
        # 발신자/내용 구분은 ' : ' 한 번 — 메시지 내부 콜론은 보존된다
        self.assertEqual(messages[1]["sender"], "김철수")
        self.assertEqual(messages[1]["message"], "회의 시간: 3시입니다")
        # 초 있는 변형은 as-exported
        self.assertEqual(messages[2]["timestamp"], "2024-01-16 15:05:30")
        self.assertEqual(messages[2]["second_precision"], "as-exported")
        # 다음 날짜 헤더가 timestamp 를 갱신한다
        self.assertEqual(messages[4]["timestamp"], "2024-01-17 09:00:00")

    def test_real_pc_system_events_are_separate_records(self):
        records = kakao.parse_kakao_file(str(FIXTURES / "kakao_pc_real.txt"))
        system = [r for r in records if r["type"] == "system"]
        self.assertEqual(len(system), 1)
        self.assertEqual(system[0]["message"], "홍길동님이 나갔습니다.")
        self.assertEqual(system[0]["timestamp"], "2024-01-16 00:05:00")
        # 시각 접두어가 없는 시스템 이벤트도 분리되며 날짜만 있으면 timestamp 는 null 이 아닌 날짜 미상
        bare = kakao.parse_kakao_text("--------------- 2024년 1월 16일 화요일 ---------------\n홍길동님이 들어왔습니다.\n")
        self.assertEqual(bare[0]["type"], "system")
        self.assertIsNone(bare[0]["timestamp"])

    def test_attachment_word_mention_is_not_an_attachment(self):
        records = kakao.parse_kakao_file(str(FIXTURES / "kakao_pc_real.txt"))
        messages = [r for r in records if r["type"] == "message"]
        # '사진' 첨부 표기 → True
        self.assertTrue(messages[2]["has_attachment"])
        # '사진 좀 보내줘' 언급 → False (구버전은 True 로 위장했다)
        self.assertFalse(messages[3]["has_attachment"])

    def test_unrecognized_lines_are_preserved_as_unparsed(self):
        records = kakao.parse_kakao_text("대화 내용 저장: 2024-01-16 오후 3:00\n[홍길동] [오후 2:15] 안녕\n")
        self.assertEqual(records[0]["type"], "unparsed")
        self.assertEqual(records[0]["message"], "대화 내용 저장: 2024-01-16 오후 3:00")
        self.assertEqual(records[1]["type"], "message")

    def test_cp949_legacy_encoding_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kakao_cp949.txt"
            text = "--------------- 2024년 1월 16일 화요일 ---------------\n[홍길동] [오후 2:15] 안녕\n"
            path.write_bytes(text.encode("cp949"))
            msgs = kakao.parse_kakao_file(str(path))
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0]["sender"], "홍길동")
            self.assertEqual(msgs[0]["message"], "안녕")

    def test_undecodable_input_fails_closed(self):
        # BOM 은 UTF-16 이지만 유효하지 않은 서로게이트 — mojibake 로 읽지 않고 실패한다
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.txt"
            path.write_bytes(b"\xff\xfe" + b"\x00\xd8\x00\x00")  # unpaired high surrogate
            with self.assertRaises(ValueError):
                kakao.read_kakao_text(str(path))

    def test_multiline_indent_is_preserved(self):
        msgs = kakao.parse_kakao_text(
            "--------------- 2024년 1월 16일 화요일 ---------------\n[홍길동] [오후 2:15] 목록\n  - 항목 1\n"
        )
        self.assertEqual(msgs[0]["message"], "목록\n  - 항목 1")

    def test_events_out_emits_timeline_compatible_events(self):
        # --events-out: 파싱→타임라인 수동 변환 단계를 한 명령으로
        events = kakao.records_to_events(kakao.parse_kakao_file(str(FIXTURES / "kakao_pc_real.txt")))
        self.assertEqual(len(events), 6)  # 메시지 5 + 시각 있는 시스템 1
        self.assertEqual(events[0]["timestamp"], "2024-01-16 14:15:00")
        self.assertEqual(events[0]["category"], "chat")
        self.assertIn("[홍길동]", events[0]["description"])
        system = [e for e in events if e["category"] == "system"]
        self.assertEqual(len(system), 1)
        self.assertEqual(system[0]["timestamp"], "2024-01-16 00:05:00")
        # 시각 미상 레코드는 근거 없는 시각이므로 타임라인에 넣지 않는다
        unknown_only = kakao.records_to_events(kakao.parse_kakao_text("[홍길동] [오후 2:15] 날짜 없음"))
        self.assertEqual(unknown_only, [])

    def test_events_out_cli_writes_file(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            out_events = Path(tmp) / "events.json"
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = kakao.main([str(FIXTURES / "kakao_pc_real.txt"), "--events-out", str(out_events)])
            self.assertEqual(code, 0)
            events = json.loads(out_events.read_text(encoding="utf-8"))
            self.assertEqual(len(events), 6)
            # 생성된 events.json 이 실제 타임라인 렌더러에 그대로 먹히는지 (체인 검증)
            out_html = Path(tmp) / "timeline.html"
            self.assertEqual(timeline.main(["--input", str(out_events), "--output", str(out_html)]), 0)


class AuditChainTests(unittest.TestCase):
    """문서화된 검증 체인: audit_timestamps.py --json > audit.json → verify_report.py --evidence"""

    def test_json_flag_emits_audit_json(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = audit.main([str(Path(__file__)), "--json"])
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data["sha256"]), 64)
        self.assertIn("md5_legacy", data)

    def test_documented_report_chain_passes(self):
        import hashlib
        import io
        import subprocess
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "증거파일.bin"
            target.write_bytes(b"case-evidence-bytes")
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(audit.main([str(target), "--json"]), 0)
            audit_json = Path(tmp) / "audit.json"
            audit_json.write_text(buf.getvalue(), encoding="utf-8")

            sha = hashlib.sha256(b"case-evidence-bytes").hexdigest()
            report = Path(tmp) / "감정서 초안.md"
            report.write_text(f"# 감정서\n\nSHA-256: {sha}\n비교 결과: 미측정\n", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report),
                 "--evidence", str(audit_json)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_ntfs_parser_reports_error_not_empty(self):
        import subprocess
        # dissect 가 설치되어 있지 않은 환경에서도 '성공한 빈 결과'를 내면 안 된다
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "parse_ntfs_artifacts.py"), str(Path(__file__)),
             "--artifact", "prefetch"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 3)
        self.assertTrue(payload["error"])
        self.assertEqual(payload["count"], 0)

    def test_check_tool_gate(self):
        import subprocess
        ok = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_tool.py"), "python3"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        )
        self.assertEqual(ok.returncode, 0)
        missing = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_tool.py"), "no-such-binary-xyz"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        )
        self.assertEqual(missing.returncode, 2)


class TimelineMaxEventsTests(unittest.TestCase):
    def test_max_events_flag_is_real(self):
        # 구버전은 에러 메시지에만 --max-events 가 있고 플래그는 없었다
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "big.json"
            src.write_text(json.dumps([
                {"timestamp": "2024-01-16 14:00:00", "description": f"e{i}"} for i in range(3)
            ]), encoding="utf-8")
            out = Path(tmp) / "out.html"
            code = timeline.main(["--input", str(src), "--output", str(out), "--max-events", "2"])
            self.assertEqual(code, 2)
            self.assertFalse(out.exists())
            code_ok = timeline.main(["--input", str(src), "--output", str(out), "--max-events", "3"])
            self.assertEqual(code_ok, 0)


class ForensicVideoTests(unittest.TestCase):
    def test_external_transcription_is_opt_in(self):
        # given an API key appears to be configured
        original_load_key = video_whisper.load_api_key
        original_extract = video_whisper.extract_audio
        calls = []
        try:
            video_whisper.load_api_key = lambda _backend=None: ("secret", "groq")
            video_whisper.extract_audio = lambda *_args: calls.append("extract")
            # when upload consent is absent
            result = video_whisper.transcribe_video("evidence.mp4", Path("."), backend="groq")
        finally:
            video_whisper.load_api_key = original_load_key
            video_whisper.extract_audio = original_extract

        # then the evidence audio is not extracted or uploaded
        self.assertEqual(result, [])
        self.assertEqual(calls, [])

    def test_video_frame_profiles_are_bounded(self):
        self.assertEqual(video_config.frame_cap("efficient"), 50)
        self.assertEqual(video_config.frame_cap("balanced"), 100)
        self.assertNotIn("token-burner", video_config.DETAIL_CAPS)


class ClaimHonestyTests(unittest.TestCase):
    def test_plugin_does_not_claim_court_admissible(self):
        data = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        blob = json.dumps(data, ensure_ascii=False).lower()
        self.assertIn("not a forensic acquisition or court-admissibility suite", blob)
        caps = " ".join(data["interface"]["capabilities"]).lower()
        self.assertNotIn("court-admissible", caps)

    def test_core_skills_drop_overclaim_examples(self):
        kakao_skill = (ROOT / "skills/kakao-chat-extractor/SKILL.md").read_text(encoding="utf-8")
        audit_skill = (ROOT / "skills/forensic-audit/SKILL.md").read_text(encoding="utf-8")
        report = (ROOT / "templates/forensic_report_template.md").read_text(encoding="utf-8")
        contract = (ROOT / "templates/contract_template.md").read_text(encoding="utf-8")
        self.assertNotIn("정시원", kakao_skill)
        self.assertNotIn("최백랑", kakao_skill)
        self.assertIn("하지 않는 일", kakao_skill)
        self.assertIn("SQLite", kakao_skill)
        self.assertIn("하지 않는 일", audit_skill)
        self.assertIn("$MFT", audit_skill)
        self.assertNotIn("명백히 입증", report)
        self.assertNotIn("주민번호 / 사업자번호", contract)


verify_report = load_module("verify_report", "scripts/verify_report.py")


class VerifyReportHardeningTests(unittest.TestCase):
    """v1.0.1 수정 회귀: 고아 해시 FAIL·분할 해시·한국어 시각 grounding."""

    def _run(self, report_text, extra=()):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "감정서 초안.md"
            report.write_text(report_text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report), *extra],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
            )

    def test_orphan_hash_without_evidence_fails_closed(self):
        # 과거에는 --evidence 미제시 시 WARN(통과)으로 두어 '감사 생략 + 조작
        # 해시'가 게이트를 통과했다. 이제 FAIL이어야 한다.
        fabricated = "a" * 64
        proc = self._run(f"SHA-256: {fabricated}\n")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("근거 없는 해시", proc.stderr)

    def test_report_without_hashes_still_passes(self):
        proc = self._run("총평: 해시나 시각 주장이 없는 초안이다.\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_hash_split_across_lines_is_detected(self):
        import hashlib
        sha = hashlib.sha256(b"evidence").hexdigest()
        first, second = sha[:40], sha[40:]
        proc = self._run(f"SHA-256:\n{first}\n{second}\n")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("근거 없는 해시", proc.stderr)

    def test_korean_clock_time_grounding(self):
        times = verify_report.extract_timestamps("사건은 2024년 5월 1일 오전 9시 30분에 발생했다")
        self.assertIn("2024-05-01 09:30:00", times)
        times2 = verify_report.extract_timestamps("대응은 2024년 5월 1일 오후 3시에 끝났다")
        self.assertIn("2024-05-01 15:00:00", times2)
        # 콜론식 병기도 유지된다
        times3 = verify_report.extract_timestamps("2024년 5월 1일 21:05에 접속 기록이 있다")
        self.assertIn("2024-05-01 21:05:00", times3)

    def test_korean_date_only_still_extracts(self):
        times = verify_report.extract_timestamps("2024년 5월 1일에 발생했다")
        self.assertIn("2024-05-01", times)

    def test_fabricated_agency_in_report_fails(self):
        proc = self._run("본 보고서는 디지털포렌식청 및 사이버수사처의 수사 지침에 따라 작성되었습니다.")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("공공기관 명칭 날조", proc.stderr)

    def test_obsolete_ministry_in_report_fails(self):
        proc = self._run("해당 기술 기준은 정보통신부 고시 제2007-1호에 준거합니다.")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("정보통신부", proc.stderr)
        self.assertIn("폐지된 구 부처명", proc.stderr)

    def test_claim_ledger_integration_in_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "claim-ledger.md"
            ledger_path.write_text(
                "| Claim | Risk Level | Sources (2+ Domains / Artifacts) | Counter-Search / Falsification | Primary Source | Status |\n"
                "|---|---|---|---|---|:---:|\n"
                "| [Claim 1] 정상 검증 항목 | High | a.evtx, b.json | 반증 없음 확인 | hash123 | `VERIFIED` |\n"
                "| [Claim 2] 반증된 항목 | High | a.evtx, b.json | 반증 확인됨 | hash456 | `REFUTED` |\n",
                encoding="utf-8",
            )
            # Passing report: cites Claim 1
            proc_pass = self._run("결론: [Claim 1]이 확인됨.", extra=["--claim-ledger", str(ledger_path)])
            self.assertEqual(proc_pass.returncode, 0, proc_pass.stderr)

            # Failing report: cites Claim 2 (REFUTED)
            proc_fail = self._run("결론: [Claim 2]를 채택함.", extra=["--claim-ledger", str(ledger_path)])
            self.assertEqual(proc_fail.returncode, 1, proc_fail.stderr)
            self.assertIn("Claim Ledger 위반", proc_fail.stderr)

    def test_fabricated_agency_with_korean_particles_fails(self):
        proc1 = self._run("사이버수사처와 긴밀하게 공조하여 조사를 마쳤다.")
        self.assertEqual(proc1.returncode, 1, proc1.stderr)
        self.assertIn("공공기관 명칭 날조", proc1.stderr)

        proc2 = self._run("디지털포렌식청과 회의를 진행했다.")
        self.assertEqual(proc2.returncode, 1, proc2.stderr)
        self.assertIn("공공기관 명칭 날조", proc2.stderr)

    def test_obsolete_ministry_with_successor_annotation_or_allow_historical(self):
        # With current successor annotation, it downgrades to warning and does not exit 1
        proc_annotated = self._run("정보통신부(현 과학기술정보통신부) 2005년 고시를 참조함.")
        self.assertEqual(proc_annotated.returncode, 0, proc_annotated.stderr)

        # With --allow-historical flag, obsolete ministry is tolerated as warning
        proc_historical = self._run("정보통신부 2005년 기준에 따름.", extra=["--allow-historical"])
        self.assertEqual(proc_historical.returncode, 0, proc_historical.stderr)


if __name__ == "__main__":
    unittest.main()

