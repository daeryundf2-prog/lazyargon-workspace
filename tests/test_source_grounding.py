import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "source_grounding.py"

CHAT = """2026년 3월 12일 오후 2:05, 김철수 : 이번 달 안에 돈 갚을게
2026년 3월 12일 오후 2:07, 이영희 : 언제까지 줄 건데
2026년 3월 12일 오후 2:09, 김철수 : 내일 꼭 줄게
"""
STT = "[00:12] 이영희: 돈은 언제 보낼 거야?\n[00:20] 김철수: 다음 주에 정리해서 보낼게\n"


@pytest.fixture
def case(tmp_path: Path) -> Path:
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "kakao_chat.txt").write_text(CHAT, encoding="utf-8")
    (ev / "stt_call_0313.txt").write_text(STT, encoding="utf-8")
    (ev / "photo_receipt.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg")
    return tmp_path


def run(report: Path, *sources: str) -> dict[str, Any]:
    args = [sys.executable, str(SCRIPT), str(report), "--json"]
    if sources:
        args += ["--sources", *sources]
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
    return json.loads(proc.stdout)


def write(case: Path, body: str) -> Path:
    p = case / "report.md"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.mark.parametrize(
    "line,needle",
    [
        ('2026-03-12 14:09 김철수는 "돈을 이미 보냈다"라고 보냈다.', "원본에 없는 인용"),
        ('2026-03-12 14:07 김철수는 "언제까지 줄 건데"라고 보냈다.', "화자 불일치"),
        ("통화에서 김철수는 「다음 달에 갚겠다」고 말했다.", "원본에 없는 인용"),
        ("2026-03-14 22:10 통화가 있었다.", "없는 시각"),
        ("분석 대상 메시지는 총 1,532건이다.", "근거 없는 수치"),
        ("- 갑 제3호증: 녹음파일_0312.m4a", "자료 폴더에 없는 파일"),
    ],
)
def test_each_fabrication_is_an_error(case: Path, line: str, needle: str):
    res = run(write(case, f"# 보고서\n{line}\n"), str(case / "evidence"))
    assert res["verdict"] == "FAIL"
    assert any(needle in e for e in res["errors"]), res["errors"]


def test_grounded_report_passes(case: Path):
    body = (
        "# 보고서\n"
        '2026-03-12 14:09 김철수는 "내일 꼭 줄게"라고 보냈다.\n'
        "통화에서 김철수는 「다음 주에 정리해서 보낼게」라고 말했다.\n"
        "- 갑 제1호증: kakao_chat.txt\n- 갑 제2호증: photo_receipt.jpg\n"
        '"돈을 이미 보냈다"는 주장은 미확인이다.\n'
        '```\n"코드 안 예시 인용" 2026-03-15 11:11\n```\n'
        "회사 3회의 회의, 3통화 기록.\n"
    )
    res = run(write(case, body), str(case / "evidence"))
    assert res["verdict"] == "PASS", res["errors"]


def _kakao_pc_case(tmp_path: Path) -> Path:
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "KakaoTalk_chat.txt").write_text(
        "김민수, 박준호 님과 카카오톡 대화\n"
        "--------------- 2026년 10월 3일 금요일 ---------------\n"
        "[김민수] [오전 9:07] 내일까지 300만원 보내줘\n"
        "[김민수] [오후 3:33] 내일까지 300만원 보내줘\n"
        "--------------- 2026년 10월 4일 토요일 ---------------\n"
        "[박준호] [오전 12:03] 내가 50만원 빌려줄 수 있어\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.parametrize(
    "row,needle",
    [
        ("| 2026-10-03 | 15:33 | 김민수 | 내일까지 300만원 보내줘 |", None),
        ("| 2026-10-04 | 00:03 | 박준호 | 내가 50만원 빌려줄 수 있어 |", None),
        ("| 2026-10-03 | 13:33 | 김민수 | 내일까지 300만원 보내줘 |", "시각-발언 불일치"),
        ("| 2026-10-04 | 12:03 | 박준호 | 내가 50만원 빌려줄 수 있어 |", "시각-발언 불일치"),
    ],
)
def test_kakao_pc_table_rows_check_time_per_quote(tmp_path: Path, row: str, needle: str | None):
    """카카오톡 PC 내보내기('[이름] [오후 3:33]', 날짜는 구분선)와 날짜·시각이 다른 칸인 표(실세션 2026-11-01)."""
    case = _kakao_pc_case(tmp_path)
    body = f"# 보고서\n\n| 날짜 | 시각 | 발언자 | 원문 |\n|---|---|---|---|\n{row}\n"
    res = run(write(case, body), str(case / "evidence"))
    if needle is None:
        assert not res["errors"], res["errors"]
    else:
        assert any(needle in e for e in res["errors"]), res["errors"]


@pytest.mark.parametrize(
    "body,needle",
    [
        ("김철수는 '돈을 이미 보냈다'라고 했다.", "원본에 없는 인용"),
        ("김철수는 《돈을 이미 보냈다》라고 했다.", "원본에 없는 인용"),
        ("> 2026-03-12 14:09 김철수: 돈을 이미 보냈다", "원본에 없는 인용"),
        ("```\n김철수 : 돈을 이미 보냈다\n```", "원본에 없는 인용"),
        ("| 시각 | 화자 | 발언 |\n|---|---|---|\n| 2026-03-12 14:07 | 김철수 | 언제까지 줄 건데 |", "화자 불일치"),
        ('김철수는 "돈을 이미\n보냈다"라고 했다.', "원본에 없는 인용"),
        ('<p>김철수는 "돈을 <b>이미</b> 보냈다"라고 했다.</p>', "원본에 없는 인용"),
        ('김철수는 `"돈을 이미 보냈다"`라고 했다.', "원본에 없는 인용"),
        ('2026-03-12 14:05 김철수는 "내일 꼭 줄게"라고 했다.', "시각-발언 불일치"),
        ("3월 12일 14:30에 메시지가 왔다.", "없는 시각"),
        ("2026.03.12 14:30 메시지.", "없는 시각"),
        ("메시지는 총 1532 건이다.", "근거 없는 수치"),
        ("김철수는 7차례 연락했다.", "근거 없는 수치"),
        ("통화는 42분간 이어졌다.", "근거 없는 수치"),
        ("김철수는 300만원을 요구했다.", "근거 없는 금액"),
        ('김철수는 "돈을 이미 보냈다"라고 말했다(일부 미확인).', "원본에 없는 인용"),
        ("메시지는 총 1,532건이다(미확인 포함).", "근거 없는 수치"),
    ],
)
def test_adversarial_forms_are_errors(case: Path, body: str, needle: str):
    res = run(write(case, f"# 보고서\n{body}\n"), str(case / "evidence"))
    assert any(needle in e for e in res["errors"]), res["errors"]


@pytest.mark.parametrize(
    "body",
    [
        "「개인정보 보호법」 제17조와 「민법」 제750조를 검토했다.",
        '금전소비대차 계약(이하 "이 사건 계약"이라 한다)을 검토했다.',
        "The suspect's phone and the victim's laptop were imaged.",
        "증거 파일은 kakao_chat.txt 이다.",
        "> 2026년 3월 12일 오후 2:09, 김철수 : 내일 꼭 줄게",
        "| 시각 | 화자 | 발언 |\n|---|---|---|\n| 2026-03-12 14:09 | 김철수 | 내일 꼭 줄게 |",
        "| 증거번호 | 내용 |\n|---|---|\n| 각1 | 카카오톡 대화 캐처 |",
        '김철수는 "내일 꼭\n줄게"라고 했다.',
        "3월 12일 14:09 메시지를 확인했다.",
    ],
)
def test_legitimate_forms_pass(case: Path, body: str):
    res = run(write(case, f"# 보고서\n{body}\n"), str(case / "evidence"))
    assert res["verdict"] == "PASS", res["errors"]


def test_money_and_counts_match_by_unit_or_matching_key(case: Path):
    (case / "evidence" / "counts.json").write_text('{"messages": 4, "speakers": 2, "amount_krw": 5000000}', encoding="utf-8")
    ok = run(write(case, "# 보고서\n메시지는 4건, 화자는 2명, 요구액은 500만원이다.\n"), str(case / "evidence"))
    assert ok["verdict"] == "PASS", ok["errors"]
    bad = run(write(case, "# 보고서\n화자는 4명이다.\n"), str(case / "evidence"))
    assert any("근거 없는 수치" in e for e in bad["errors"]), bad["errors"]


@pytest.mark.parametrize(
    "line",
    [
        '이영희는 김철수에게 "내일 꼭 줄게"라고 보냈다.',
        '김철수가 이영희에게 "언제까지 줄 건데"라고 물었다.',
    ],
)
def test_two_named_speakers_misattribution_is_an_error(case: Path, line: str):
    res = run(write(case, f"# 보고서\n{line}\n"), str(case / "evidence"))
    assert any("화자 불일치" in e for e in res["errors"]), res["errors"]


@pytest.mark.parametrize(
    "line",
    [
        '김철수는 이영희에게 "내일 꼭 줄게"라고 보냈다.',
        '이영희가 김철수에게 "언제까지 줄 건데"라고 물었다.',
    ],
)
def test_two_named_speakers_correct_attribution_passes(case: Path, line: str):
    res = run(write(case, f"# 보고서\n{line}\n"), str(case / "evidence"))
    assert res["verdict"] == "PASS", res["errors"]


@pytest.mark.parametrize(
    "line,needle",
    [
        ('김철수가 "돈을 이미 보냈다"고 했는지는 미확인이다.', "원본에 없는 인용"),
        ("2026-03-14 22:10 통화 여부는 미확인.", "없는 시각"),
        ("추가 메시지 1,532건은 미확인.", "근거 없는 수치"),
        ("녹음파일_0312.m4a 존재 여부 미확인.", "자료 폴더에 없는 파일"),
    ],
)
def test_abstain_line_unsupported_claims_are_warned_not_skipped(case: Path, line: str, needle: str):
    res = run(write(case, f"# 보고서\n{line}\n"), str(case / "evidence"))
    assert res["verdict"] == "PASS", res["errors"]
    assert any(needle in w for w in res["warnings"]), res["warnings"]


def test_abstain_line_still_catches_wrong_speaker(case: Path):
    res = run(write(case, '# 보고서\n김철수가 "언제까지 줄 건데"라고 한 의도는 미확인.\n'), str(case / "evidence"))
    assert any("화자 불일치" in e for e in res["errors"]), res["errors"]


def test_quotes_without_any_source_folder_fail_closed(tmp_path: Path):
    res = run(write(tmp_path, '# 보고서\n김철수는 "내일 꼭 줄게"라고 보냈다.\n'))
    assert any("원본 자료 미제시" in e for e in res["errors"])


def test_media_only_sources_require_text_transcripts(tmp_path: Path):
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "call.m4a").write_bytes(b"audio")
    res = run(write(tmp_path, '# 보고서\n김철수는 "내일 꼭 줄게"라고 말했다.\n'), str(ev))
    assert any("원본 텍스트 없음" in e for e in res["errors"])


def test_html_td_fabricated_quote_with_entities_fails(case: Path):
    body = '<table><tr><td>김철수는 &quot;돈을 이미 보냈다&quot;고 말했다.</td></tr></table>\n'
    res = run(write(case, "<h1>보고서</h1>\n" + body), str(case / "evidence"))
    assert res["verdict"] == "FAIL"
    assert any("원본에 없는 인용" in e for e in res["errors"]), res["errors"]


def test_absent_percentage_fails(case: Path):
    res = run(write(case, "# 보고서\n시장 점유율 37%다.\n"), str(case / "evidence"))
    assert res["verdict"] == "FAIL"
    assert any("근거 없는 수치" in e for e in res["errors"]), res["errors"]


def test_count_matching_only_a_date_fails(case: Path):
    # sources contain "3월" (a date), never "3건"
    res = run(write(case, "# 보고서\n총 3건이다.\n"), str(case / "evidence"))
    assert res["verdict"] == "FAIL"
    assert any("근거 없는 수치" in e for e in res["errors"]), res["errors"]


def test_count_grounded_by_structured_json_value_passes(case: Path):
    analysis = case / "evidence" / "analysis"
    analysis.mkdir()
    (analysis / "counts.json").write_text('{"messages": 5}', encoding="utf-8")
    res = run(write(case, "# 보고서\n분석 대상은 총 5건이다.\n"), str(case / "evidence"))
    assert res["verdict"] == "PASS", res["errors"]


def test_html_report_quoting_existing_sentence_passes(case: Path):
    body = "<p>김철수는 &quot;내일 꼭 줄게&quot;라고 보냈다.</p>\n"
    res = run(write(case, "<h1>보고서</h1>\n" + body), str(case / "evidence"))
    assert res["verdict"] == "PASS", res["errors"]
