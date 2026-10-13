import importlib.util
import json
import struct
import tempfile
import unittest
import wave
import zipfile
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


manifest_mod = load_module("evidence_manifest", "scripts/evidence_manifest.py")
hwpx = load_module("extract_hwpx", "scripts/extract_hwpx.py")
docdiff = load_module("doc_diff", "scripts/doc_diff.py")
audio = load_module("audio_survey", "scripts/audio_survey.py")
exif = load_module("exif_audit", "scripts/exif_audit.py")
osint = load_module("osint_username", "scripts/osint_username.py")
kwr = load_module("keyword_report", "scripts/keyword_report.py")
survey_mod = load_module("case_survey", "scripts/case_survey.py")
setup_env = load_module("setup_forensic_env", "scripts/setup_forensic_env.py")
sigcheck = load_module("signature_check", "scripts/signature_check.py")
dedup = load_module("dedup_files", "scripts/dedup_files.py")
pdf_audit = load_module("pdf_audit", "scripts/pdf_audit.py")
archive_survey = load_module("archive_survey", "scripts/archive_survey.py")
sqlite_survey = load_module("sqlite_survey", "scripts/sqlite_survey.py")
video_integrity = load_module("video_integrity", "scripts/video_integrity.py")
audio_fp = load_module("audio_fingerprint", "scripts/audio_fingerprint.py")
merge_tl = load_module("merge_timeline", "scripts/merge_timeline.py")
audit_ledger = load_module("audit_ledger", "scripts/audit_ledger.py")
evidence_sheet = load_module("court_evidence_sheet", "scripts/court_evidence_sheet.py")
evidence_export = load_module("evidence_export", "scripts/evidence_export.py")
dlp_table = load_module("dlp_log_table", "scripts/dlp_log_table.py")

try:
    from PIL import Image  # noqa: F401
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def make_hwpx(path: Path, texts: list[str]) -> None:
    """최소한의 HWPX 구조를 만든다 (Contents/section0.xml + hp:t)."""
    xml = (
        '<?xml version="1.0"?>'
        '<opf:package xmlns:opf="x" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        "<hp:sec>" + "".join(f"<hp:t>{t}</hp:t>" for t in texts) + "</hp:sec>"
        "</opf:package>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Contents/section0.xml", xml)


class EvidenceManifestTests(unittest.TestCase):
    def test_build_and_verify_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("hello", encoding="utf-8")
            (root / "b.txt").write_text("world", encoding="utf-8")
            m = manifest_mod.build_manifest(root)
            self.assertEqual(m["file_count"], 2)
            self.assertEqual(manifest_mod.verify_manifest(root, m), [])

    def test_verify_detects_change_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("hello", encoding="utf-8")
            (root / "b.txt").write_text("world", encoding="utf-8")
            m = manifest_mod.build_manifest(root)
            (root / "a.txt").write_text("tampered", encoding="utf-8")
            (root / "b.txt").unlink()
            (root / "c.txt").write_text("new", encoding="utf-8")
            problems = manifest_mod.verify_manifest(root, m)
            self.assertEqual(len(problems), 3)
            self.assertTrue(any("CHANGED" in p for p in problems))
            self.assertTrue(any("MISSING" in p for p in problems))
            self.assertTrue(any("NEW" in p for p in problems))

    def test_cli_verify_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"
            root.mkdir()
            (root / "a.txt").write_text("x", encoding="utf-8")
            mf = Path(tmp) / "m.json"  # 매니페스트는 스캔 대상 밖에 둔다
            self.assertEqual(manifest_mod.main([str(root), "-o", str(mf)]), 0)
            self.assertEqual(manifest_mod.main([str(root), "--verify", str(mf)]), 0)
            (root / "a.txt").write_text("y", encoding="utf-8")
            self.assertEqual(manifest_mod.main([str(root), "--verify", str(mf)]), 1)


class HwpxTests(unittest.TestCase):
    def test_extracts_text_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "doc.hwpx"
            make_hwpx(f, ["제1조 목적", "제2조 정의"])
            r = hwpx.process(f)
            self.assertEqual(r["status"], "ok")
            self.assertIn("제1조", r["text"])
            self.assertIn("제2조", r["text"])

    def test_non_hwpx_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "fake.hwpx"
            f.write_text("not a zip", encoding="utf-8")
            r = hwpx.process(f)
            self.assertEqual(r["status"], "failed")


class DocDiffTests(unittest.TestCase):
    def test_change_classification(self):
        rows = docdiff.build_rows(
            ["제1조", "제2조 옛말", "제3조"],
            ["제1조", "제2조 새말", "제3조", "제4조 신설"],
        )
        notes = [r["note"] for r in rows]
        self.assertIn("동일", notes)
        self.assertIn("변경", notes)
        self.assertIn("신설", notes)

    def test_identical_files(self):
        rows = [r for r in docdiff.build_rows(["a", "b"], ["a", "b"]) if r["note"] != "동일"]
        self.assertEqual(rows, [])

    def test_cli_missing_file(self):
        self.assertEqual(docdiff.main(["/no.txt", "/no2.txt"]), 2)


class AudioSurveyTests(unittest.TestCase):
    def _make_wav(self, path: Path, seconds: float, loud: bool) -> None:
        fr = 16000
        n = int(fr * seconds)
        amp = 8000 if loud else 100
        frames = struct.pack(f"<{n}h", *([amp] * n))
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(fr)
            wf.writeframes(frames)

    def test_speech_vs_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            loud = Path(tmp) / "loud.wav"
            quiet = Path(tmp) / "quiet.wav"
            self._make_wav(loud, 2.0, loud=True)
            self._make_wav(quiet, 2.0, loud=False)
            rl = audio.survey(loud, 0.01)
            rq = audio.survey(quiet, 0.01)
            self.assertEqual(rl["status"], "ok")
            self.assertGreater(rl["speech_ratio"], 0.9)
            self.assertLess(rq["speech_ratio"], 0.5)

    def test_unreadable_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "bad.wav"
            f.write_bytes(b"not a wave")
            r = audio.survey(f, 0.01)
            # wave 실패 후 ffmpeg이 있으면 ffmpeg 경로로 갈 수 있다
            self.assertIn(r["status"], ("ok", "failed"))


class ExifAuditTests(unittest.TestCase):
    @unittest.skipUnless(HAS_PIL, "Pillow not installed")
    def test_eval_images_no_exif(self):
        media = FIXTURES / "eval" / "media"
        if not media.is_dir():
            self.skipTest("eval fixtures absent")
        from PIL import Image as PILImage

        records = [exif.audit_image(f, PILImage) for f in sorted(media.glob("*.png"))]
        self.assertEqual(len(records), 3)
        self.assertTrue(all(r.get("exif_present") is False for r in records))


class OsintTests(unittest.TestCase):
    def test_fail_closed_without_sherlock(self):
        if osint.find_sherlock() is not None:
            self.skipTest("sherlock installed")
        self.assertEqual(osint.main(["testuser"]), 3)


class KeywordReportTests(unittest.TestCase):
    def test_hit_with_line_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "doc.txt"
            f.write_text("첫째 줄\n보이스피싱 주의\n셋째 줄\n", encoding="utf-8")
            hits = kwr.search_file(f, ["보이스피싱"], 0)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["line"], 2)

    def test_absence_is_documented(self):
        # 평가 코퍼스에서 '보이스피싱' 부재 확인 — 검색 범위가 리포트에 남는다
        eval_dir = FIXTURES / "eval"
        if not eval_dir.is_dir():
            self.skipTest("eval fixtures absent")
        code = kwr.main([str(eval_dir / "docs"), "보이스피싱", "--json"])
        self.assertEqual(code, 1)  # 미검출 → exit 1

    def test_eval_keyword_presence(self):
        eval_dir = FIXTURES / "eval"
        if not eval_dir.is_dir():
            self.skipTest("eval fixtures absent")
        hits = kwr.search_file(eval_dir / "chats" / "kakao_export_2026-03.txt",
                               ["프로젝트 겨울나무"], 0)
        self.assertEqual(len(hits), 1)


class CaseSurveyTests(unittest.TestCase):
    def test_survey_eval_corpus(self):
        eval_dir = FIXTURES / "eval"
        if not eval_dir.is_dir():
            self.skipTest("eval fixtures absent")
        report = survey_mod.survey(eval_dir, ["프로젝트 겨울나무"], run_stt=False)
        steps = report["steps"]
        # manifest/pii/keywords/audio/exif/similar_images/videos 단계가 기록된다
        for k in ("manifest", "pii", "keywords", "audio", "exif",
                  "similar_images", "signatures", "dedup", "archives",
                  "pdf", "sqlite", "videos", "video_integrity"):
            self.assertIn(k, steps)
        m = steps["manifest"]
        self.assertEqual(m["status"], "ok")
        self.assertEqual(m["result"]["file_count"], 47)
        kw = steps["keywords"]
        self.assertEqual(kw["status"], "ok")
        self.assertGreaterEqual(kw["result"]["total_hits"], 1)

    def test_survey_missing_dir_exit_2(self):
        self.assertEqual(survey_mod.main(["/nonexistent-xyz"]), 2)

    def test_markdown_renders(self):
        eval_dir = FIXTURES / "eval"
        if not eval_dir.is_dir():
            self.skipTest("eval fixtures absent")
        report = survey_mod.survey(eval_dir, [], run_stt=False)
        md = survey_mod.to_markdown(report)
        self.assertIn("파일 매니페스트", md)
        self.assertIn("47개 파일", md)


class SignatureCheckTests(unittest.TestCase):
    def test_detects_disguised_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "photo.jpg"
            f.write_bytes(b"MZ" + b"\x00" * 30)  # PE를 jpg로 위장
            r = sigcheck.audit_file(f)
            self.assertEqual(r["status"], "MISMATCH")
            self.assertEqual(r["detected"], "PE 실행파일")

    def test_real_png_matches(self):
        media = FIXTURES / "eval" / "media" / "red_square.png"
        if not media.is_file():
            self.skipTest("eval fixtures absent")
        r = sigcheck.audit_file(media)
        self.assertEqual(r["status"], "MATCH")

    def test_text_files_unknown_not_mismatch(self):
        eval_dir = FIXTURES / "eval"
        if not eval_dir.is_dir():
            self.skipTest("eval fixtures absent")
        code = sigcheck.main([str(eval_dir), "--json"])
        self.assertEqual(code, 0)  # 텍스트류는 UNKNOWN이라 MISMATCH가 아님


class DedupTests(unittest.TestCase):
    def test_exact_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("same", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "b.txt").write_text("same", encoding="utf-8")
            (root / "c.txt").write_text("different", encoding="utf-8")
            groups = dedup.exact_dups(list(root.rglob("*")))
            groups = [g for g in groups if Path(g["files"][0]).is_file()]
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0]["files"]), 2)


class AudioFingerprintTests(unittest.TestCase):
    def test_no_fpcalc_exit_3(self):
        if audio_fp._require_fpcalc():
            self.skipTest("fpcalc installed")
        self.assertEqual(audio_fp.main(["/tmp/x.mp3"]), 3)

    def test_hamming_similarity(self):
        same = [0xDEADBEEF, 0x12345678, 0xFFFFFFFF]
        self.assertEqual(audio_fp.hamming_similarity(same, same), 1.0)
        self.assertEqual(audio_fp.hamming_similarity(same, [0, 0, 0]), 0.0)
        # 길이가 다르면 짧은 쪽 기준
        self.assertEqual(audio_fp.hamming_similarity(same, same[:1]), 1.0)
        self.assertEqual(audio_fp.hamming_similarity([], same), 0.0)

    def test_survey_version_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("x", encoding="utf-8")
            report = survey_mod.survey(Path(tmp), [], run_stt=False)
        self.assertEqual(report["survey_version"], 2)
        self.assertIn("audio_fp", report["steps"])


class MergeTimelineTests(unittest.TestCase):
    def test_manifest_and_kakao_merge_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("x", encoding="utf-8")
            m = manifest_mod.build_manifest(root)
            mf = root / "m.json"
            mf.write_text(json.dumps(m), encoding="utf-8")
            kf = root / "k.json"
            kf.write_text(json.dumps({"records": [
                {"type": "message", "timestamp": "2026-03-05 14:22:00",
                 "sender": "김", "message": "hi"},
                {"type": "message", "timestamp": None, "sender": "이",
                 "message": "no-time"},
            ]}), encoding="utf-8")
            merged = merge_tl.merge([str(mf)], [str(kf)], [], [], {})
            self.assertEqual(len(merged["events"]), 2)  # 파일1 + 시각있는 메시지1
            ts = [e["timestamp"] for e in merged["events"]]
            self.assertEqual(ts, sorted(ts))

    def test_stt_without_anchor_is_unanchored(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "call.wav.transcript.json"
            f.write_text(json.dumps({"segments": [
                {"start": 49.0, "end": 55.0, "text": "돈 보낼게"}]}),
                encoding="utf-8")
            merged = merge_tl.merge([], [], [], [str(f)], {})
            # 앵커 없는 상대시각은 벽시계로 지어내지 않는다
            self.assertEqual(len(merged["events"]), 0)
            self.assertEqual(len(merged["unanchored_stt"]), 1)
            # 앵커 주면 절대시각으로 변환
            merged2 = merge_tl.merge([], [], [], [str(f)],
                                     {"call.wav": "2026-03-05T14:00:00+09:00"})
            self.assertEqual(merged2["events"][0]["timestamp"],
                             "2026-03-05T14:00:49+09:00")

    def test_plaso_jsonl_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "plaso.jsonl"
            pf.write_text(
                '{"timestamp": 1741212000000000, "timestamp_desc": "Modification Time",'
                ' "parser": "filestat", "message": "/etc/passwd"}\n'
                '{"datetime": "2026-03-05T15:00:00+00:00", "timestamp_desc": "Creation Time",'
                ' "parser": "evtx", "message": "EventID 4624"}\n'
                '{"no_time": true, "parser": "broken"}\n',
                encoding="utf-8")
            merged = merge_tl.merge([], [], [], [], {}, plasos=[str(pf)])
            self.assertEqual(len(merged["events"]), 2)
            sources = {e["source"] for e in merged["events"]}
            self.assertIn("plaso:filestat", sources)
            self.assertIn("plaso:evtx", sources)
            ts = [e["timestamp"] for e in merged["events"]]
            self.assertEqual(ts, sorted(ts))

    def test_plaso_csv_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "plaso.csv"
            pf.write_text(
                "datetime,timestamp_desc,parser,message\n"
                "2026-03-05T14:00:00+00:00,Last Visit,chrome_history,https://x\n"
                ",Missing Time,winreg,bad row\n",
                encoding="utf-8")
            merged = merge_tl.merge([], [], [], [], {}, plasos=[str(pf)])
            self.assertEqual(len(merged["events"]), 1)
            self.assertEqual(merged["events"][0]["source"], "plaso:chrome_history")


class CourtEvidenceSheetTests(unittest.TestCase):
    def test_manifest_to_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ev.wav").write_text("x", encoding="utf-8")
            m = manifest_mod.build_manifest(root)
            mf = root / "m.json"
            mf.write_text(json.dumps(m), encoding="utf-8")
            out = root / "sheet.md"
            code = evidence_sheet.main(
                [str(mf), "--party", "을", "--start", "3",
                 "--purpose", "ev.wav=통화 내용 입증", "-o", str(out)])
            self.assertEqual(code, 0)
            md = out.read_text(encoding="utf-8")
            self.assertIn("을 제3호증", md)
            self.assertIn("통화 내용 입증", md)
            self.assertIn("초안", md)  # 검토 필수 문구

    def test_survey_json_also_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            survey = {"steps": {"manifest": {"result": {"files": [
                {"path": "a.txt", "sha256": "ab", "size": 1,
                 "mtime": "2026-01-01T00:00:00+09:00"}]}}}}
            f = Path(tmp) / "s.json"
            f.write_text(json.dumps(survey), encoding="utf-8")
            files = evidence_sheet.load_files(f)
            self.assertEqual(files[0]["path"], "a.txt")

    def test_bad_input_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.json"
            f.write_text("{}", encoding="utf-8")
            self.assertEqual(evidence_sheet.main([str(f)]), 2)


class EvidenceExportTests(unittest.TestCase):
    def test_manifest_to_lazyothers_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ev.wav").write_text("x", encoding="utf-8")
            m = manifest_mod.build_manifest(root)
            mf = root / "m.json"
            mf.write_text(json.dumps(m), encoding="utf-8")
            out = root / "evidence.json"
            code = evidence_export.main(
                [str(mf), "--party", "갑", "--start", "2",
                 "--purpose", "ev.wav=통화 입증", "-o", str(out)])
            self.assertEqual(code, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            item = data["evidence_list"][0]
            self.assertEqual(item["label"], "갑 제2호증")
            self.assertEqual(item["title"], "ev.wav")
            self.assertEqual(item["purpose"], "통화 입증")
            self.assertTrue(item["sha256"])
            self.assertTrue(Path(item["file"]).is_absolute())

    def test_unprovided_purpose_stays_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            survey = {"steps": {"manifest": {"result": {"files": [
                {"path": "a.txt", "sha256": "ab", "size": 1,
                 "mtime": "2026-01-01T00:00:00+09:00"}]}}}}
            f = Path(tmp) / "s.json"
            f.write_text(json.dumps(survey), encoding="utf-8")
            code = evidence_export.main([str(f)])
            self.assertEqual(code, 0)


class DlpLogTableTests(unittest.TestCase):
    def test_csv_to_grouped_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "logs.csv"
            csv_path.write_text(
                "timestamp,action,agent,phase\n"
                "2026-09-01 11:00,usb mount,syslog,반출\n"
                "2026-09-01 10:00,webhard login,dlp,검색/준비\n",
                encoding="utf-8")
            out = Path(tmp) / "t.md"
            code = dlp_table.main([str(csv_path), "-o", str(out)])
            self.assertEqual(code, 0)
            md = out.read_text(encoding="utf-8")
            self.assertIn("## 검색/준비", md)
            self.assertIn("## 반출", md)
            self.assertIn("탐지 아님", md)
            self.assertLess(md.index("webhard login"), md.index("usb mount"))

    def test_empty_csv_exit_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "empty.csv"
            csv_path.write_text("a,b\n", encoding="utf-8")
            self.assertEqual(dlp_table.main([str(csv_path)]), 3)

    def test_missing_file_exit_2(self):
        self.assertEqual(dlp_table.main(["/nonexistent/x.csv"]), 2)

    def test_bad_col_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "l.csv"
            csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
            self.assertEqual(
                dlp_table.main([str(csv_path), "--time-col", "nope"]), 2)


class SetupEnvTests(unittest.TestCase):
    def test_check_runs(self):
        self.assertEqual(setup_env.main(["--check"]), 0)

    def test_check_json(self):
        self.assertEqual(setup_env.main(["--check", "--json"]), 0)


def _make_pdf(path: Path, extra: bytes = b"") -> None:
    body = (b"%PDF-1.4\n"
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            b"3 0 obj << /Type /Page /Parent 2 0 R >> endobj\n"
            b"4 0 obj << /Author " + "(테스터)".encode("utf-8") +
            b" /Producer (unit-test) >> endobj\n"
            + extra +
            b"\nstartxref\n0\n%%EOF\n")
    path.write_bytes(body)


class PdfAuditTests(unittest.TestCase):
    def test_clean_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "doc.pdf"
            _make_pdf(f)
            r = pdf_audit.audit_pdf(f)
            self.assertTrue(r["is_pdf"])
            self.assertFalse(r["encrypted"])
            self.assertFalse(r["suspicious"])
            self.assertEqual(r["page_count"], 1)
            self.assertEqual(r["metadata"]["author"], "테스터")

    def test_encrypted_and_js_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "evil.pdf"
            _make_pdf(f, b"5 0 obj << /Encrypt 6 0 R /JavaScript (app.alert) "
                          b"/OpenAction 7 0 R >> endobj")
            r = pdf_audit.audit_pdf(f)
            self.assertTrue(r["encrypted"])
            self.assertTrue(r["suspicious"])
            self.assertIn("javascript", r["active_signals"])
            self.assertEqual(pdf_audit.main([str(f)]), 1)

    def test_non_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "doc.pdf"
            f.write_bytes(b"not a pdf at all")
            r = pdf_audit.audit_pdf(f)
            self.assertFalse(r["is_pdf"])

    def test_encrypt_metadata_not_flagged(self):
        # /EncryptMetadata는 암호화 키가 아님 — 이름 경계 오탐 방지
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "meta.pdf"
            _make_pdf(f, b"5 0 obj << /EncryptMetadata false >> endobj")
            r = pdf_audit.audit_pdf(f)
            self.assertFalse(r["encrypted"])
            self.assertEqual(pdf_audit.main([str(f)]), 0)


class ArchiveSurveyTests(unittest.TestCase):
    def test_double_ext_and_exec_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "pack.zip"
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("invoice.pdf.exe", b"MZ" + b"\x00" * 30)
                z.writestr("readme.txt", "안녕")
            r = archive_survey.audit_archive(zpath)
            self.assertEqual(r["type"], "zip")
            flagged = {m["name"]: m["flags"] for m in r["members"] if m["flags"]}
            self.assertIn("invoice.pdf.exe", flagged)
            self.assertTrue(any("이중확장자" in f for f in flagged["invoice.pdf.exe"]))
            self.assertTrue(any("실행형" in f for f in flagged["invoice.pdf.exe"]))
            self.assertEqual(archive_survey.main([str(zpath)]), 1)

    def test_zip_bomb_ratio_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "bomb.zip"
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("big.bin", b"\x00" * (2 * 1024 * 1024))
            r = archive_survey.audit_archive(zpath)
            self.assertTrue(any("압축폭탄" in f
                                for m in r["members"] for f in m["flags"]))

    def test_clean_zip_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "ok.zip"
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("a.txt", "hello")
            r = archive_survey.audit_archive(zpath)
            self.assertTrue(all(not m["flags"] for m in r["members"]))
            self.assertEqual(archive_survey.main([str(zpath)]), 0)


class SqliteSurveyTests(unittest.TestCase):
    def test_tables_and_integrity(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "chat.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE messages (id INTEGER, body TEXT)")
            conn.executemany("INSERT INTO messages VALUES (?, ?)",
                             [(1, "a"), (2, "b"), (3, "c")])
            conn.commit()
            conn.close()
            r = sqlite_survey.survey_db(db)
            self.assertTrue(r["is_sqlite"])
            self.assertTrue(r["integrity_ok"])
            tables = {t["name"]: t for t in r["tables"]}
            self.assertEqual(tables["messages"]["row_count"], 3)
            self.assertIn("body", tables["messages"]["columns"])

    def test_non_db_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "fake.db"
            f.write_bytes(b"not sqlite")
            r = sqlite_survey.survey_db(f)
            self.assertFalse(r["is_sqlite"])
            self.assertIn("error", r)

    def test_special_chars_in_filename(self):
        # 파일명의 특수문자(?·#·공백)가 file: URI 파싱을 깨지 않아야 한다 (Windows에서는 ?가 파일명에 금지됨)
        import os
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            fname = "case #1 (원본#특수).db" if os.name == "nt" else "case #1 (원본?).db"
            db = Path(tmp) / fname
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE t (a INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
            conn.commit()
            conn.close()
            r = sqlite_survey.survey_db(db)
            self.assertTrue(r["is_sqlite"])
            self.assertEqual(r["total_rows"], 1)


class VideoIntegrityTests(unittest.TestCase):
    def test_no_ffmpeg_exit_3(self):
        if video_integrity._require_ffmpeg():
            self.skipTest("ffmpeg installed")
        self.assertEqual(video_integrity.main(["/tmp/x.mp4"]), 3)

    @unittest.skipUnless(
        __import__("shutil").which("ffmpeg") is not None, "ffmpeg not installed")
    def test_ok_and_damaged(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            ok = Path(tmp) / "ok.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", "testsrc=duration=1:size=64x64:rate=5", str(ok)],
                check=True)
            r = video_integrity.audit_video(ok)
            self.assertEqual(r["status"], "OK")
            self.assertGreater(r["duration"], 0)
            # 잘린 파일 — 앞부분만 남김
            cut = Path(tmp) / "cut.mp4"
            data = ok.read_bytes()
            cut.write_bytes(data[: len(data) // 3])
            r2 = video_integrity.audit_video(cut)
            self.assertIn(r2["status"], ("DAMAGED", "UNREADABLE"))


class AuditLedgerTests(unittest.TestCase):
    def test_record_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = Path(tmp) / "case.jsonl"
            self.assertEqual(audit_ledger.main(
                ["record", str(led), "--kind", "tool_call",
                 "--actor", "local_stt.py", "--detail", "전사 실행"]), 0)
            payload = Path(tmp) / "out.json"
            payload.write_text('{"a":1}', encoding="utf-8")
            self.assertEqual(audit_ledger.main(
                ["record", str(led), "--kind", "file_write",
                 "--actor", "report.py",
                 "--payload-file", str(payload)]), 0)
            self.assertEqual(audit_ledger.main(["verify", str(led)]), 0)
            entries = audit_ledger.load(led)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["prev_hash"], audit_ledger.GENESIS)
            self.assertEqual(entries[1]["prev_hash"], entries[0]["entry_hash"])
            self.assertIn("payload_sha256", entries[1])

    def test_tamper_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = Path(tmp) / "case.jsonl"
            for i in range(3):
                audit_ledger.main(["record", str(led), "--kind", "ev",
                                   "--actor", "t", "--detail", f"e{i}"])
            lines = led.read_text(encoding="utf-8").splitlines()
            mid = json.loads(lines[1])
            mid["detail"] = "조작된 내용"
            lines[1] = json.dumps(mid, ensure_ascii=False)
            led.write_text("\n".join(lines) + "\n", encoding="utf-8")
            ok, idx, _msg = audit_ledger.verify(led)
            self.assertFalse(ok)
            self.assertEqual(idx, 1)  # 변조된 항목에서 탐지
            self.assertEqual(audit_ledger.main(["verify", str(led)]), 1)

    def test_truncation_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = Path(tmp) / "case.jsonl"
            for i in range(2):
                audit_ledger.main(["record", str(led), "--kind", "ev",
                                   "--actor", "t"])
            lines = led.read_text(encoding="utf-8").splitlines()
            led.write_text(lines[0] + "\n", encoding="utf-8")
            # 끝이 잘려도 체인 자체는 유효 — 항목 수 감소는 verify 통과.
            # (로컬 단독으로는 절단을 증명 못함 — 외부 앵커가 필요한 이유)
            ok, _idx, msg = audit_ledger.verify(led)
            self.assertTrue(ok)
            self.assertIn("1개", msg)

    def test_head_empty_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = Path(tmp) / "empty.jsonl"
            self.assertEqual(audit_ledger.main(["head", str(led)]), 1)


if __name__ == "__main__":
    unittest.main()


class ContractsVendoredTests(unittest.TestCase):
    """contracts/ 벤더 파일이 PIN.json 해시와 일치하는지 — 수동 편집 드리프트 탐지."""

    def _check(self):
        import hashlib
        root = Path(__file__).resolve().parents[1]
        pin = json.loads((root / "contracts" / "PIN.json").read_text(encoding="utf-8"))
        for name, want in pin["sha256"].items():
            f = root / "contracts" / name
            self.assertTrue(f.exists(), f"missing vendored file: {name}")
            got = hashlib.sha256(f.read_bytes()).hexdigest()
            self.assertEqual(got, want, f"drift detected in contracts/{name}")

    def test_vendored_contracts_match_pin(self):
        self._check()


class CaseEnvelopeTests(unittest.TestCase):
    """case_envelope.py — 레포 산출물 → lazy-evidence-case-v1 봉투."""

    def setUp(self):
        import scripts.case_envelope as ce
        self.ce = ce
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, obj):
        p = self.dir / name
        p.write_text(json.dumps(obj), encoding="utf-8")
        return p

    def _build(self, *inputs, case_id="CASE-1"):
        out = self.dir / "case.json"
        rc = self.ce.main() if False else None  # noqa - use argparse path below
        argv = ["build", "--case-id", case_id]
        for producer, path in inputs:
            argv += ["--input", f"{producer}:{path}"]
        argv += ["--out", str(out)]
        import argparse as _ap  # noqa
        # call main() via sys.argv patching
        import sys as _sys
        old = _sys.argv
        _sys.argv = ["case_envelope.py"] + argv
        try:
            self.ce.main()
        finally:
            _sys.argv = old
        return json.loads(out.read_text(encoding="utf-8"))

    def test_frametrace_rapid_deepfake_envelope_conforms(self):
        pkg = self._write("pkg.json", {"files": [
            {"relative_path": "db/case.db", "size_bytes": 10,
             "sha256": "a" * 64}]})
        rapid = self._write("rapid.json", {"items": [
            {"item_id": "it-1", "normalized_path": "a/b.txt",
             "observed_status": "recovered", "sha256": "b" * 64,
             "size_bytes": 5}]})
        scan = self._write("scan.json", {"rows": [
            {"path": "clip.mp4", "score": 88, "band": "high"}]})
        doc = self._build(("frametrace", pkg), ("rapid", rapid), ("deepfake", scan))
        self.assertEqual(doc["schema_version"], "lazy-evidence-case-v1")
        self.assertEqual(len(doc["items"]), 3)
        kinds = {i["kind"] for i in doc["items"]}
        self.assertEqual(kinds, {"file", "screening_result"})
        trusts = {i["trust"] for i in doc["items"]}
        self.assertEqual(trusts, {"observed", "model-assisted"})
        # 0-100 점수는 confidence(0..1)로 승격하지 않는다
        df = [i for i in doc["items"] if i["kind"] == "screening_result"][0]
        self.assertNotIn("confidence", df)
        self.assertIn("score=88", df["summary"])
        self.assertEqual(len(doc["lineage"]), 3)

    def test_envelope_passes_vendored_verifier(self):
        pkg = self._write("pkg.json", {"files": [
            {"relative_path": "db/case.db", "size_bytes": 10,
             "sha256": "a" * 64}]})
        doc_path = self.dir / "case.json"
        self._build(("frametrace", pkg))
        import subprocess, sys as _sys
        proc = subprocess.run(
            [_sys.executable, "scripts/case_envelope.py", "verify", str(doc_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=self.ce.REPO_ROOT)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("conforms", proc.stdout)

    def test_ledger_adapter_links_entry_hash(self):
        led = self.dir / "led.jsonl"
        led.write_text(json.dumps(
            {"kind": "tool_call", "actor": "x", "entry_hash": "abc"}) + "\n",
            encoding="utf-8")
        doc = self._build(("ledger", led))
        self.assertEqual(doc["items"][0]["ledger_ref"], "abc")
        self.assertEqual(doc["items"][0]["trust"], "observed")

    def test_unknown_producer_fails_closed(self):
        pkg = self._write("pkg.json", {"files": []})
        with self.assertRaises(SystemExit):
            self._build(("bogus", pkg))
