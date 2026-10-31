"""Cases from the 2026-11-01 adversarial review: realistic honest lines must pass, fabrications must fail."""
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "source_grounding.py"


@pytest.fixture
def ev(tmp_path: Path) -> Path:
    d = tmp_path / "ev"
    d.mkdir()
    (d / "kakao.txt").write_text(
        "2026년 3월 12일 오후 2:09, 김철수 : 내일까지 500만원 보내줄게\n2026년 3월 12일 오후 2:15, 이영희 : 알겠어 기다릴게\n",
        encoding="utf-8",
    )
    (d / "stt.txt").write_text("[00:01:12] 김철수: 그 돈은 내가 빌린 게 아니야\n", encoding="utf-8")
    (d / "pc.txt").write_text("[이영희] [오후 3:01] 다 퍼뜨린다 각오해\n", encoding="utf-8")
    (d / "summary.json").write_text('{"messages": 4, "speakers": 2}', encoding="utf-8")
    (d / "IMG_0001.jpg").write_bytes(b"\xff\xd8")
    return d


def run(ev: Path, body: str) -> dict[str, Any]:
    rep = ev.parent / "r.md"
    rep.write_text(f"# 보고서\n{body}\n", encoding="utf-8")
    out = subprocess.run([sys.executable, str(SCRIPT), str(rep), "--sources", str(ev), "--json"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    return json.loads(out)


@pytest.mark.parametrize("body", [
    '이영희는 "내일까지 500만원 보내줄게"라는 메시지를 받았다.',
    "이른바 '몸캠 피싱' 수법으로 보인다.",
    "의뢰인이 제출한 '사건 경위서'를 참고했다.",
    '"돈 갚을게"라는 메시지는 제출 자료에서 발견되지 않았다.',
    '김철수는 "그 돈은 (중략) 아니야"라고 말했다.',
    "내보내기 파일(kakao.txt)을 분석했다.",
    "수집 일시: 2026-10-31 15:20",
    "수령한 증거 파일은 5개다.",
    "| 시각 | 발신자 | 메시지 요약 |\n|---|---|---|\n| 2026-03-12 14:09 | 김철수 | 송금 약속 |",
    "- 이영희: 의뢰인, 3월 12일 14시경 대화 상대",
    "분석에는 약 2시간이 소요되었다.",
    "첨부 사진 IMG_0001.jpg를 확인했다.",
    "> 2026년 3월 12일 오후 2:09, 김철수 : 내일까지 500만원 보내줄게",
])
def test_honest_lines_pass(ev: Path, body: str):
    res = run(ev, body)
    assert res["verdict"] == "PASS", res["errors"]


@pytest.mark.parametrize("body", [
    '김철수의 메시지를 받은 이영희는 "내일까지 500만원 보내줄게"라고 말했다.',
    '김철수는 "내가 빌린 게"라고 인정했다.',
    "2026. 3. 14. 23:40경 통화가 있었다.",
    "김철수는 2억 2천만 원을 요구했다.",
    "첨부 사진 IMG_9999.jpg를 확인했다.",
    "첨부 사진 `IMG_9999.jpg` 확인.",
    "> 김철수: 다 퍼뜨린다 각오해",
    "| 보낸 사람 | 내용 |\n|---|---|\n| 김철수 | 다 퍼뜨린다 각오해 |",
    "<p>김철수는 <q>다 퍼뜨린 적 없다</q>라고 했다.</p>",
    "김철수는 «다 퍼뜨린 적 없다»라고 했다.",
    '김철수는 "다 퍼뜨린 적 없다"라고 보냈고 이영희의 답장은 미확인',
    '김철수는 "다 퍼뜨린 적 없다"라고 협박함 (미확인)',
    '이영희는 "내일까지 500만원 보내줄게"라고 보냈다.',
])
def test_fabrications_fail(ev: Path, body: str):
    res = run(ev, body)
    assert res["verdict"] == "FAIL", res


def test_coverage_absence_checks(ev: Path):
    cov = {"sources": [
        {"id": "chromium_history", "label": "Chrome", "match": r"chrome|크롬|edge|arc", "status": "OK", "rows": 312},
        {"id": "safari_history", "label": "Safari", "match": r"safari|사파리", "status": "DENIED", "rows": 0},
    ]}
    (ev / "coverage.json").write_text(json.dumps(cov), encoding="utf-8")
    for bad in ("Safari 접속 이력은 존재하지 않는다.", "권한 문제와 별개로 Safari 방문 기록은 없다.", "Safari에서 도박 사이트 방문 312건"):
        assert run(ev, bad)["verdict"] == "FAIL", bad
    for ok in ("Safari 방문 기록: 미확인(권한 없음)", "이 표는 전체 사용기록을 대표하지 않는다.", "knowledgeC 흔적은 없다.", "research 폴더를 확인했다."):
        assert run(ev, ok)["verdict"] == "PASS", ok
