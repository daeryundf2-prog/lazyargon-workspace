import importlib.util
import json
import sys
import tempfile
import unittest
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


pii = load_module("pii_mask", "scripts/pii_mask.py")
imgsim = load_module("image_similarity", "scripts/image_similarity.py")
vidfp = load_module("video_fingerprint", "scripts/video_fingerprint.py")
local_stt = load_module("local_stt", "scripts/local_stt.py")
audit_local = load_module("local_only_audit", "scripts/local_only_audit.py")
crime_xlsx = load_module("crime_schedule_xlsx", "scripts/crime_schedule_xlsx.py")
verify_rep = load_module("verify_report", "scripts/verify_report.py")

try:
    from PIL import Image  # noqa: F401
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class PiiMaskTests(unittest.TestCase):
    SAMPLE = (
        "피의자 홍길동 주민번호 901215-1234567\n"
        "연락처 010-1234-5678, 카드 1234-5678-9012-3456\n"
        "계좌 110-333-444555, 이메일 test@example.com\n"
        "거래일 2026-03-01 에 기록됨\n"
    )

    def test_detects_korean_pii_types(self):
        findings = pii.detect_in_text(self.SAMPLE)
        types = {f["type"] for f in findings}
        self.assertIn("주민등록번호", types)
        self.assertIn("휴대전화", types)
        self.assertIn("카드번호", types)
        self.assertIn("계좌번호", types)
        self.assertIn("이메일", types)

    def test_date_not_flagged_as_account(self):
        findings = pii.detect_in_text("날짜는 2026-03-01 이다\n")
        self.assertFalse(any(f["type"] == "계좌번호" for f in findings))

    def test_mask_redacts_but_preserves_structure(self):
        masked = pii.mask_text(self.SAMPLE)
        self.assertIn("901215-*******", masked)
        self.assertIn("010-****-5678", masked)
        self.assertIn("1234-****-****-3456", masked)
        self.assertIn("***@example.com", masked)
        self.assertNotIn("1234567", masked.split("*******")[0] + "X")
        self.assertIn("2026-03-01", masked)  # 날짜는 유지

    def test_cli_detect_only_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "doc.txt"
            f.write_text(self.SAMPLE, encoding="utf-8")
            code = pii.main([str(f), "--json"])
            self.assertEqual(code, 1)

    def test_cli_clean_file_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "clean.txt"
            f.write_text("개인정보 없는 일반 텍스트\n", encoding="utf-8")
            code = pii.main([str(f)])
            self.assertEqual(code, 0)

    def test_cli_mask_writes_masked_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "doc.txt"
            out = Path(tmp) / "out.txt"
            f.write_text(self.SAMPLE, encoding="utf-8")
            code = pii.main([str(f), "--mask", "-o", str(out)])
            self.assertEqual(code, 1)
            self.assertTrue(out.exists())
            self.assertIn("*******", out.read_text(encoding="utf-8"))
            # 원본은 그대로 남는다
            self.assertIn("901215-1234567", f.read_text(encoding="utf-8"))


class ImageSimilarityTests(unittest.TestCase):
    def test_hamming(self):
        self.assertEqual(imgsim.hamming(0b1010, 0b1001), 2)
        self.assertEqual(imgsim.hamming(0, 0), 0)

    def test_missing_dir_exit_2(self):
        code = imgsim.main(["/nonexistent-dir-xyz"])
        self.assertIn(code, (2, 3))  # 3 if Pillow missing

    @unittest.skipUnless(HAS_PIL, "Pillow not installed")
    def test_eval_corpus_self_match(self):
        # forensic-eval fixtures: 각 이미지는 자기 자신과 dist 0
        media = FIXTURES / "eval" / "media"
        if not media.is_dir():
            self.skipTest("eval fixtures absent")
        records = imgsim.scan_dir(media, __import__("PIL.Image", fromlist=["Image"]))
        self.assertEqual(len(records), 3)
        # 서로 다른 색 사각형은 임계값 밖이어야 한다
        pairs = imgsim.find_pairs(records, threshold=5)
        self.assertEqual(pairs, [])

    @unittest.skipUnless(HAS_PIL, "Pillow not installed")
    def test_resized_image_matches(self):
        from PIL import Image as PILImage

        with tempfile.TemporaryDirectory() as tmp:
            src = PILImage.new("RGB", (64, 64), (200, 30, 30))
            a = Path(tmp) / "a.png"
            b = Path(tmp) / "b.png"
            src.save(a)
            src.resize((256, 256)).save(b)
            ra = imgsim.hash_file(a, PILImage)
            rb = imgsim.hash_file(b, PILImage)
            self.assertIsNotNone(ra)
            self.assertIsNotNone(rb)
            self.assertLessEqual(imgsim.hamming(ra["phash"], rb["phash"]), 5)


class VideoFingerprintTests(unittest.TestCase):
    def test_similarity_identical(self):
        fp = {"frame_hashes": [0, 1, 2, 3], "duration": 10.0}
        s = vidfp.similarity(fp, fp)
        self.assertEqual(s["similarity"], 1.0)

    def test_similarity_different(self):
        a = {"frame_hashes": [0] * 8, "duration": 10.0}
        b = {"frame_hashes": [0xFFFFFFFFFFFFFFFF] * 8, "duration": 10.0}
        s = vidfp.similarity(a, b)
        self.assertEqual(s["similarity"], 0.0)

    def test_verdict_bands(self):
        self.assertIn("동일", vidfp.verdict(0.95))
        self.assertIn("유사", vidfp.verdict(0.75))
        self.assertIn("부분", vidfp.verdict(0.5))
        self.assertIn("불일치", vidfp.verdict(0.1))

    def test_missing_file_exit(self):
        import shutil
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            self.assertEqual(vidfp.main(["x.mp4"]), 3)
        else:
            self.assertEqual(vidfp.main(["/nonexistent.mp4"]), 2)


class LocalSttTests(unittest.TestCase):
    def test_keyword_hits(self):
        segs = [
            {"start": 0.0, "end": 1.0, "text": "돈을 보내줘"},
            {"start": 1.0, "end": 2.0, "text": "점심 먹자"},
        ]
        hits = local_stt.keyword_hits(segs, ["송금", "돈"])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["keyword"], "돈")

    def test_engine_detection_returns_known_or_none(self):
        eng = local_stt.detect_engine()
        self.assertTrue(eng is None or eng in
                        ("google-server", "youtube-subs", "faster-whisper", "openai-whisper", "sensevoice", "moonshine")
                        or eng.startswith("binary:") or eng.startswith("binary-sensevoice:"))

    def test_vtt_segment_parse(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.500\n"
            "<c>안녕하세요</c> 테스트입니다\n\n"
            "00:00:03.500 --> 00:00:05.000\n"
            "안녕하세요 테스트입니다\n"
            "두 번째 문장\n"
        )
        segs = local_stt.parse_vtt_segments(vtt)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["text"], "안녕하세요 테스트입니다")
        self.assertEqual(segs[0]["start_mmss"], "00:01")
        self.assertEqual(segs[0]["end_mmss"], "00:03")
        self.assertEqual(segs[0]["start_kor"], "00분 01초")
        self.assertEqual(segs[1]["text"], "두 번째 문장")

    def test_format_mmss_and_kor_time(self):
        self.assertEqual(local_stt.format_mmss(384.94), "06:24")
        self.assertEqual(local_stt.format_mmss(3984.2), "01:06:24")
        self.assertEqual(local_stt.format_kor_time(384.94), "06분 24초")
        self.assertIsNone(local_stt.format_mmss(None))
        self.assertIsNone(local_stt.format_kor_time(None))

    def test_norm_kr_and_similarity(self):
        pmap = [("설계", "설기"), ("진도개", "진돗개")]
        self.assertEqual(local_stt.norm_kr("[웃음] 설계를 데리고 (확인)", pmap), "설기를데리고")
        res = local_stt.verify_transcript_similarity(
            "설기를 데리고 나갔다",
            "오늘 설계를 데리고 나갔다 왔어",
            phonetic_map=pmap,
        )
        self.assertEqual(res["pct"], 100)
        self.assertTrue(res["verified"])
        self.assertIn("서버STT 검증완료 (원음 일치율 100%)", res["tag"])

    def test_sensevoice_tag_parse(self):
        raw = "<|ko|><|ANGRY|><|Speech|><|withitn|>돈 안 갚으면 가만 안 둬 <|SIGH|>"
        p = local_stt.parse_sensevoice_tags(raw)
        self.assertEqual(p["lang"], "ko")
        self.assertEqual(p["emotion"], "ANGRY")
        self.assertIn("SIGH", p["events"])
        self.assertNotIn("<|", p["text"])
        self.assertIn("돈 안 갚으면", p["text"])

    def test_sensevoice_tag_parse_plain(self):
        p = local_stt.parse_sensevoice_tags("그냥 문장만 있음")
        self.assertIsNone(p["lang"])
        self.assertIsNone(p["emotion"])
        self.assertEqual(p["events"], [])
        self.assertEqual(p["text"], "그냥 문장만 있음")

    def test_engine_override_unavailable_exit_3(self):
        # 존재하지 않는 엔진 강제 지정 → fail-closed
        self.assertEqual(local_stt.main(["x.wav", "--engine", "nonexistent-engine"]), 3)

    def test_missing_input_exit_2(self):
        # 엔진 유무와 무관하게 잘못된 입력은 exit 2
        if local_stt.detect_engine() is None:
            self.assertEqual(local_stt.main(["/nonexistent.wav"]), 3)
        else:
            self.assertEqual(local_stt.main(["/nonexistent.wav"]), 2)

    def test_fail_closed_without_engine(self):
        if local_stt.detect_engine() is not None:
            self.skipTest("engine installed — fail-closed path not exercised")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.wav").write_bytes(b"RIFF")
            self.assertEqual(local_stt.main([tmp]), 3)


class LocalOnlyAuditTests(unittest.TestCase):
    def test_detects_ungated_urllib(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            bad = root / "scripts" / "leak.py"
            bad.write_text("import urllib.request\nurllib.request.urlopen('https://x')\n",
                           encoding="utf-8")
            code = audit_local.main(["--root", str(root), "--json"])
            self.assertEqual(code, 1)

    def test_gated_when_flag_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            ok = root / "scripts" / "gated.py"
            ok.write_text(
                "def f(allow_upload=False):\n"
                "    if allow_upload:\n"
                "        import urllib.request\n"
                "        urllib.request.urlopen('https://x')  # requires --upload-audio\n",
                encoding="utf-8",
            )
            code = audit_local.main(["--root", str(root), "--json"])
            self.assertEqual(code, 0)

    def test_allowlist_marks_reviewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            dl = root / "scripts" / "downloader.ps1"
            dl.write_text("Invoke-WebRequest -Uri $u -OutFile $z\n", encoding="utf-8")
            (root / ".local_only_allowlist").write_text(
                "scripts/downloader.ps1 http_call\n", encoding="utf-8")
            code = audit_local.main(["--root", str(root), "--json"])
            self.assertEqual(code, 0)
            findings = audit_local.scan_file(dl, root,
                                             {("scripts/downloader.ps1", "http_call")})
            self.assertEqual(findings[0]["status"], "REVIEWED")

    def test_plugin_repo_has_no_ungated(self):
        # 실제 레포에 새 UNGATED 경로가 생기면 이 테스트가 실패한다
        self.assertEqual(audit_local.main(["--json"]), 0)


class CrimeScheduleXlsxAndReportGuardTests(unittest.TestCase):
    def test_calc_visual_lines_and_youtube_url(self):
        self.assertEqual(crime_xlsx.calc_visual_lines("", 20.0), 1)
        self.assertGreaterEqual(crime_xlsx.calc_visual_lines("가나다라마바사아자차카타파하" * 4, 20.0), 4)
        url = crime_xlsx.youtube_jump_url("20260405_방송_[dQw4w9WgXcQ].mp4", 384.9, pre_roll=2)
        self.assertEqual(url, "https://youtu.be/dQw4w9WgXcQ?t=382")

    def test_audit_schedule_consistency(self):
        rows = [
            {"row": 3, "transcript": "강아지 설기가 짖었다", "issue": "반려견 설기 학대 허위사실"},
            {"row": 4, "transcript": "날씨가 참 좋다", "issue": "반려견 설기 유기 허위사실"},
        ]
        bad = crime_xlsx.audit_schedule_consistency(rows, {"설기": ["설기", "설계", "강아지", "진돗개"]})
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["row"], 4)

    def test_self_reference_hash_excluded_and_pins_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = Path(tmp) / "report.md"
            self_hash = "a" * 64
            pin_hash = "b" * 64
            rep.write_text(f"보고서 해시 {self_hash}", encoding="utf-8")
            trail = Path(tmp) / "audit_trail.jsonl"
            trail.write_text(json.dumps({"file": str(rep), "sha256": self_hash}) + "\n", encoding="utf-8")
            pins_dir = Path(tmp) / ".lazyargon"
            pins_dir.mkdir()
            (pins_dir / "pins.md").write_text(f"- 고정 해시: {pin_hash}\n", encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(tmp)
                hashes = verify_rep.load_evidence_hashes([str(trail)], report_path=rep)
            finally:
                os.chdir(old_cwd)
            self.assertNotIn(self_hash, hashes)
            self.assertIn(pin_hash, hashes)


if __name__ == "__main__":
    unittest.main()
