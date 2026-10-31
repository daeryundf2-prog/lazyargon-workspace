"""Cases from the second blind review (2026-11-01): iOS KakaoTalk times, topic-matched counts, swapped speakers."""
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "source_grounding.py"
KAKAO = """2026. 9. 14. 오후 3:12, 박지훈 : 내일까지 계약금 넣을게요
2026. 9. 14. 오후 3:15, 박지훈 : 삼백 말고 350만원으로 하죠
2026. 9. 14. 오후 9:41, 최민서 : 등기부등본 확인했는데 근저당이 잡혀 있어요
2026. 9. 14. 오후 9:45, 박지훈 : 그건 제가 다음 주에 정리합니다
2026. 9. 15. 오전 10:05, 최민서 : 계약금 아직 안 들어왔어요
2026. 9. 15. 오후 2:47, 박지훈 : 방금 350만원 보냈습니다
"""


@pytest.fixture
def src(tmp_path: Path) -> Path:
    d = tmp_path / "src"
    d.mkdir()
    (d / "kakao_ios.txt").write_text(KAKAO, encoding="utf-8")
    (d / "call_stt.txt").write_text("통화 시간: 4분 31초\n[00:00:05] 박지훈: 각서는 좀 곤란하고요\n", encoding="utf-8")
    (d / "bank.csv").write_text("date,type,amount\n2026-09-13,입금,1000000\n2026-09-15,입금,3500000\n2026-09-16,출금,200000\n", encoding="utf-8")
    (d / "analysis.json").write_text(json.dumps({"bank": {"rows": 3}, "utterances": 7, "deposits": 2, "duration_sec": 271}), encoding="utf-8")
    return d


def run(src: Path, body: str) -> dict[str, Any]:
    rep = src.parent / "r.md"
    rep.write_text(f"# 보고서\n{body}\n", encoding="utf-8")
    out = subprocess.run([sys.executable, str(SCRIPT), str(rep), "--sources", str(src), "--json"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    return json.loads(out)


@pytest.mark.parametrize("body", [
    "2026년 9월 14일 오후 3시 12분경 박지훈은 “내일까지 계약금 넣을게요”라고 적었다.",
    "최민서는 9월 14일 21:41 등기부등본상 근저당 설정 사실을 언급하였다.",
    "| 시각 | 화자 | 발언 |\n|---|---|---|\n| 2026-09-14 15:15 | 박지훈 | 삼백 말고 350만원으로 하죠 |",
    "9월 15일 오후 2시 47분 박지훈은 '방금 350만원 보냈습니다'라고 보냈다.",
    "통화 STT 발화는 총 7회로 집계되었다.",
    "계좌 입출금 내역 3건 중 입금은 2건이다.",
    "통화 시간은 4분 31초였다.",
])
def test_honest_lines_pass(src: Path, body: str):
    res = run(src, body)
    assert res["verdict"] == "PASS", res["errors"]


@pytest.mark.parametrize("body", [
    '박지훈이 "계약금 아직 안 들어왔어요"라고 하자 최민서가 답했다.',
    '박지훈은 최민서로부터 "방금 350만원 보냈습니다"라는 문자를 받았다.',
    '박지훈은 "근저당이 잡혀 있어요 … 그건 제가 다음 주에 정리합니다"라고 했다.',
    "자료 폴더의 첨부 파일은 총 3개이다.",
    "근저당을 언급한 메시지는 3건이다.",
    "통화 시간은 6분 12초였다.",
    '박지훈은 2026. 9. 14. 오후 4:12 "내일까지 계약금 넣을게요"라고 보냈다.',
])
def test_fabrications_fail(src: Path, body: str):
    res = run(src, body)
    assert res["verdict"] == "FAIL", res
