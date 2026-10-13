"""평가 코퍼스 불변식 — 알려진-답 코퍼스가 조용히 바뀌지 않았는지 잠근다.

test/fixtures/eval/ 은 에이전트 회귀 평가의 기준물이다. 파일이 하나라도
바뀌면 평가 결과 해석이 틀어지므로, 정답지(ANSWER_KEY.md)의 핵심 사실을
코드로 고정한다. 의도적 코퍼스 변경 시 이 테스트도 함께 고칠 것.
"""
import unittest
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "eval"


@unittest.skipUnless(FIXTURES.is_dir(), "eval corpus absent")
class EvalCorpusTests(unittest.TestCase):
    def test_file_count(self):
        files = [p for p in FIXTURES.rglob("*") if p.is_file()]
        self.assertEqual(len(files), 47)

    def test_expected_layout(self):
        self.assertTrue((FIXTURES / "EVAL.md").is_file())
        self.assertTrue((FIXTURES / "ANSWER_KEY.md").is_file())
        self.assertEqual(len(list((FIXTURES / "docs").glob("doc_*.txt"))), 40)
        self.assertEqual(len(list((FIXTURES / "media").glob("*.png"))), 3)

    def test_a1_absent_keyword(self):
        # '보이스피싱'은 질문지·정답지를 제외한 데이터 파일 어디에도 없어야 한다
        for p in FIXTURES.rglob("*"):
            if p.is_file() and p.name not in ("EVAL.md", "ANSWER_KEY.md"):
                self.assertNotIn("보이스피싱", p.read_text(encoding="utf-8", errors="replace"),
                                 msg=str(p))

    def test_b1_phrase_location(self):
        chat = (FIXTURES / "chats" / "kakao_export_2026-03.txt").read_text(encoding="utf-8")
        lines = chat.splitlines()
        self.assertIn("프로젝트 겨울나무", lines[3])  # 4행

    def test_b2_interest_rate(self):
        doc = (FIXTURES / "docs" / "doc_17.txt").read_text(encoding="utf-8")
        self.assertIn("연 5%", doc.splitlines()[4])  # 5행

    def test_b3_log_error(self):
        log_lines = (FIXTURES / "logs" / "app.log").read_text(encoding="utf-8").splitlines()
        errors = [l for l in log_lines if " ERROR " in l]
        self.assertEqual(len(errors), 1)
        self.assertIn("shard-7", errors[0])
        self.assertEqual(log_lines.index(errors[0]), 213)  # 214행
        self.assertFalse(any("shard-3" in l for l in log_lines))

    def test_c1_utterance_counts(self):
        chat = (FIXTURES / "chats" / "kakao_export_2026-03.txt").read_text(encoding="utf-8")
        self.assertEqual(chat.count("[김철수]"), 6)
        self.assertEqual(chat.count("[이영희]"), 4)


if __name__ == "__main__":
    unittest.main()
