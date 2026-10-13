"""mask_korean_pii.py 오탐 회귀 — 마스킹되면 안 되는 값의 기준선.

구분자 없는 번호 탐지(D1/D2)를 켜면 오탐 위험이 커지므로, 날짜·사건번호·
금액·법령 조문처럼 숫자 형식이 겹치는 값이 원본 그대로 유지되는지 고정한다.
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import mask_korean_pii as mk  # noqa: E402

ALL = mk.ALL_TYPES


def test_dates_survive_all_separator_styles():
    text = "기일 2024-01-16, 작성일 2024.01.16, 등록 2024 01 16"
    masked, stats = mk.mask_text(text, ALL)
    assert "2024-01-16" in masked
    assert "2024.01.16" in masked
    assert "2024 01 16" in masked
    assert stats["account"] == 0 and stats["phone"] == 0 and stats["card"] == 0


def test_case_numbers_not_masked():
    text = "2024가합12345, 2023고단1234, 2024드단5678, 2024나54321"
    masked, _ = mk.mask_text(text, ALL)
    for token in ("2024가합12345", "2023고단1234", "2024드단5678", "2024나54321"):
        assert token in masked


def test_money_amounts_not_masked():
    text = "청구금액 1,234,567원 및 지연손해금 10,000,000원"
    masked, stats = mk.mask_text(text, ALL)
    assert "1,234,567원" in masked and "10,000,000원" in masked
    assert stats["account"] == 0


def test_statute_articles_not_masked():
    text = "민법 제750조, 민법 제123조의2, 형사소송법 제308조에 따라"
    masked, stats = mk.mask_text(text, ALL)
    assert text == masked


def test_invalid_date_rrn_rejected():
    # 13월, 32일은 생년월일이 될 수 없어 후보에서 제외된다.
    for bad in ("901332-1234567", "901232-1234567", "900000-1234567"):
        masked, stats = mk.mask_text(f"번호 {bad} 확인", ALL)
        assert bad in masked
        assert stats["rrn"] == 0


def test_delimiterless_rrn_bad_checksum_is_suspect_not_masked():
    # 구분자 없는 13자리는 체크섬 통과해야 확정 마스킹. 실패 시 보고만 한다.
    masked, stats = mk.mask_text("번호 9012121234563 확인", ALL)
    assert "9012121234563" in masked
    assert stats["rrn"] == 0 and stats["rrn_suspect"] == 1


def test_short_passport_like_token_not_masked():
    # M+7자리(형식 미달)는 여권이 아니다.
    masked, stats = mk.mask_text("코드 M2200000 확인", ALL)
    assert "M2200000" in masked
    assert stats["passport"] == 0


def test_longer_digit_runs_not_split_into_phone():
    # 12자리 이상 숫자열은 휴대폰 조합으로 쪼개 잡지 않는다.
    masked, stats = mk.mask_text("일련번호 0101234567890123", ALL)
    assert "0101234567890123" in masked
    assert stats["phone"] == 0
