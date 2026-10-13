"""mask_korean_pii.py 회귀 테스트 — 체크섬·마스킹 규칙·날짜 오탐 방지."""

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import mask_korean_pii as mk  # noqa: E402

VALID_RRN = "901212-1234568"   # 체크섬 유효 (가상 인물)
INVALID_RRN = "901212-1234563"  # 형식은 맞지만 체크섬 불일치


def test_validate_rrn_checksum():
    assert mk.validate_rrn(VALID_RRN)
    assert not mk.validate_rrn(INVALID_RRN)
    assert not mk.validate_rrn("900212-123456")  # 자릿수 부족


def test_rrn_masked_regardless_of_checksum():
    text = f"갑: {VALID_RRN} 을: {INVALID_RRN}"
    masked, stats = mk.mask_text(text, {"rrn"})
    assert VALID_RRN not in masked and INVALID_RRN not in masked
    assert "901212-1******" in masked
    assert stats["rrn"] == 2 and stats["rrn_bad_checksum"] == 1


def test_phone_masking_keeps_prefix():
    masked, stats = mk.mask_text("연락처 010-1234-5678, 사무실 02-123-4567", {"phone"})
    assert "010-1234-****" in masked
    assert "02-123-****" in masked
    assert stats["phone"] == 2


def test_account_masked_but_dates_preserved():
    text = "계좌 123-45-678901, 지급일 2024-01-16"
    masked, stats = mk.mask_text(text, {"account"})
    assert "***-**-**8901" in masked  # 끝 4자리만 유지 정책
    assert "2024-01-16" in masked, "날짜가 계좌번호로 오탐되면 안 된다"
    assert stats["account"] == 1 and stats["account_skipped_date"] == 1


def test_email_masked():
    masked, stats = mk.mask_text("메일: hong.gildong@example.com", {"email"})
    assert "h**@example.com" in masked
    assert "hong.gildong" not in masked
    assert stats["email"] == 1


def test_type_filtering():
    text = f"주민번호 {VALID_RRN}, 메일 a@b.com"
    masked, stats = mk.mask_text(text, {"phone"})
    assert VALID_RRN in masked, "미선택 유형은 원본 유지되어야 한다"
    assert "a@b.com" in masked
    assert stats["rrn"] == 0


def test_full_pipeline_all_types():
    text = f"901212-1234561 / 010-1234-5678 / 123-45-678901 / x@y.co.kr / 2024-01-16"
    masked, _ = mk.mask_text(text, mk.ALL_TYPES)
    for original in (VALID_RRN, "010-1234-5678", "123-45-678901", "x@y.co.kr"):
        assert original not in masked
    assert "2024-01-16" in masked


def test_main_writes_output_and_report(tmp_path):
    src = tmp_path / "input.md"
    src.write_text(f"주민번호 {VALID_RRN}", encoding="utf-8")
    out = tmp_path / "masked.md"
    report = tmp_path / "report.md"
    assert mk.main([str(src), "-o", str(out), "--report", str(report)]) == 0
    assert "901212-1******" in out.read_text(encoding="utf-8")
    assert "체크섬" in report.read_text(encoding="utf-8")
    assert mk.main([str(src), "--types", "bogus"]) == 2


# ── 조사 접착 회귀 (P0: \b 경계는 한국어 조사에서 탐지를 실패했다) ──────

def test_rrn_masked_with_particle_attached():
    # "1234568임을"처럼 조사가 띄어쓰기 없이 붙어도 잡혀야 한다 —
    # 실제 판결문/공문서에서 가장 흔한 문장형이다.
    text = f"주민등록번호가 {VALID_RRN}임을 확인하였다."
    masked, stats = mk.mask_text(text, {"rrn"})
    assert VALID_RRN not in masked
    assert "901212-1******임을 확인하였다." in masked
    assert stats["rrn"] == 1


def test_phone_masked_with_particle_attached():
    masked, stats = mk.mask_text("피고는 010-1234-5678으로 전화하였다.", {"phone"})
    assert "010-1234-****으로" in masked
    assert stats["phone"] == 1


def test_account_masked_with_particle_attached():
    masked, stats = mk.mask_text("계좌 123-45-678901에서 송금하였다.", {"account"})
    assert "***-**-**8901에서" in masked
    assert stats["account"] == 1


def test_email_masked_with_particle_attached():
    masked, stats = mk.mask_text("회신은 hong@example.com으로 주시기 바랍니다.", {"email"})
    assert "h**@example.com으로" in masked
    assert stats["email"] == 1


def test_longer_digit_run_not_masked_as_rrn():
    # 더 긴 숫자열의 일부는 주민번호로 잡지 않는다.
    masked, stats = mk.mask_text("등록번호 901212-12345689 는 14자리다", {"rrn"})
    assert stats["rrn"] == 0
    assert "901212-12345689" in masked


# ── 외국인등록번호 (성별코드 5~8) ──────────────────────────────────

def test_foreigner_number_masked():
    text = "외국인등록번호 901212-5678901와 880301-7654321가 있다"
    masked, stats = mk.mask_text(text, {"rrn"})
    assert "901212-5******" in masked
    assert "880301-7******" in masked
    assert stats["rrn"] == 2


def test_foreigner_number_masked_with_particle():
    masked, _ = mk.mask_text("등록번호는 901212-5678901이다.", {"rrn"})
    assert "901212-5******이다." in masked


# ── 인코딩 (CP949 손실 방지) ────────────────────────────────────────

def test_cp949_input_masked_and_encoding_preserved(tmp_path):
    src = tmp_path / "bank.csv"
    src.write_bytes(f"이름,주민번호,연락처\n홍길동,{VALID_RRN},010-1234-5678\n".encode("cp949"))
    out = tmp_path / "masked.csv"
    assert mk.main([str(src), "-o", str(out)]) == 0
    decoded = out.read_bytes().decode("cp949")
    assert "홍길동" in decoded, "CP949 본문이 U+FFFD로 훼손되면 안 된다"
    assert "901212-1******" in decoded
    assert "010-1234-****" in decoded


def test_utf8_bom_input_preserved(tmp_path):
    src = tmp_path / "bom.md"
    src.write_bytes(b"\xef\xbb\xbf" + f"주민번호 {VALID_RRN}".encode("utf-8"))
    out = tmp_path / "masked.md"
    assert mk.main([str(src), "-o", str(out)]) == 0
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "901212-1******" in out.read_text(encoding="utf-8-sig")


def test_undecodable_input_fails_closed(tmp_path):
    # 어느 인코딩으로도 읽지 못하면 U+FFFD로 유실하는 대신 실패해야 한다.
    src = tmp_path / "broken.bin"
    src.write_bytes(b"\x80\x80\x80\x80")  # utf-8 연속 바이트, cp949 리드 바이트 범위 밖
    assert mk.main([str(src), "-o", str(tmp_path / "out.txt")]) == 2


# ── PII 확장 3종 (여권/운전면허/외국인등록번호 — 형식매칭+경고 수준) ──

def test_passport_masked_warn_level():
    masked, stats = mk.mask_text("여권번호 M22000000임을 확인", {"passport"})
    assert "M22000000" not in masked and "M********임을" in masked
    assert stats["passport"] == 1
    assert "passport" in mk.ALL_TYPES


def test_driver_license_masked_warn_level():
    masked, stats = mk.mask_text("면허 12-34-567890-12이다", {"driver_license"})
    assert "12-34-567890-12" not in masked and "12-34-******-**이다" in masked
    assert stats["driver_license"] == 1
    assert "driver_license" in mk.ALL_TYPES


def test_foreigner_number_checksum_attempt_but_masked():
    masked, stats = mk.mask_text("외국인 901212-5678901이다", {"foreigner"})
    assert "901212-5678901" not in masked and "901212-5******이다" in masked
    assert stats["foreigner"] == 1
    assert "foreigner" in mk.ALL_TYPES


# ── 구분자 확장 (D1/D2) ─────────────────────────────────────────────

def test_rrn_dot_and_space_separators_masked():
    # 점·공백 구분자도 하이픈처럼 날짜 형식만 맞으면 마스킹한다.
    masked, stats = mk.mask_text("901212.1234568 그리고 901212 1234568", {"rrn"})
    assert masked.count("901212-1******") == 2
    assert stats["rrn"] == 2


def test_rrn_delimiterless_checksum_pass_masked():
    masked, stats = mk.mask_text("연속 9012121234568 번호", {"rrn"})
    assert "901212-1******" in masked and "9012121234568" not in masked
    assert stats["rrn"] == 1 and stats["rrn_suspect"] == 0


def test_rrn_delimiterless_bad_checksum_masked_with_flag():
    masked, stats = mk.mask_text("연속 9012121234563 번호", {"rrn"}, mask_suspect_rrn=True)
    assert "901212-1******" in masked
    assert stats["rrn"] == 1


def test_mobile_all_separator_styles():
    text = "010-1234-5678 / 010 1234 5678 / 010.1234.5678 / 01012345678 / 0101234567"
    masked, stats = mk.mask_text(text, {"phone"})
    assert masked.count("010-1234-****") == 4
    assert "010-123-****" in masked
    assert stats["phone"] == 5


def test_landline_dot_and_space_separators():
    masked, stats = mk.mask_text("사무실 02.123.4567 및 02 123 4567", {"phone"})
    assert masked.count("02-123-****") == 2
    assert stats["phone"] == 2


def test_landline_nodelim_opt_in_only():
    masked, stats = mk.mask_text("전화 0212345678 로", {"phone"})
    assert "0212345678" in masked and stats["phone"] == 0
    masked2, stats2 = mk.mask_text("전화 0212345678 로", {"phone", "landline_nodelim"})
    assert "02-1234-****" in masked2 and stats2["phone"] == 1


# ── 카드번호 (D3) ───────────────────────────────────────────────────

def test_card_masked_luhn_valid():
    # 4111-1111-1111-1111은 Luhn 유효한 테스트 번호다.
    masked, stats = mk.mask_text("카드 4111-1111-1111-1111", {"card"})
    assert "****-****-****-1111" in masked
    assert stats["card"] == 1


def test_card_delimiterless_masked():
    masked, stats = mk.mask_text("카드 4111111111111111", {"card"})
    assert "****-****-****-1111" in masked and stats["card"] == 1


def test_card_luhn_fail_not_masked():
    masked, stats = mk.mask_text("번호 4111-1111-1111-1112", {"card"})
    assert stats["card"] == 0 and stats["card_suspect"] == 1


def test_card_runs_before_account():
    # 4그룹 카드가 계좌 정규식에 먹히지 않아야 한다.
    masked, stats = mk.mask_text("결제 4111-1111-1111-1111", {"card", "account"})
    assert "****-****-****-1111" in masked
    assert stats["card"] == 1 and stats["account"] == 0


# ── 계좌 4~5그룹 (D4) ───────────────────────────────────────────────

def test_account_four_and_five_groups():
    masked, stats = mk.mask_text("a 110-123-456789-01 / b 123-456-7890-12-34", {"account"})
    assert "***-***-****89-01" in masked
    assert "***-***-****-12-34" in masked
    assert stats["account"] == 2


# ── 여권 확장 (D5) ──────────────────────────────────────────────────

def test_passport_lowercase_and_new_format():
    masked, stats = mk.mask_text("a m22000000 / b M123A4567 / c m123a4567", {"passport"})
    assert "m********" in masked and masked.count("M********") == 1
    assert "M22000000" not in masked and "M123A4567" not in masked
    assert stats["passport"] == 3


# ── PiiVault CLI (D6) ───────────────────────────────────────────────

def test_vault_roundtrip_via_cli(tmp_path):
    src = tmp_path / "in.md"
    src.write_text(f"주민 {VALID_RRN} 연락처 010-1234-5678", encoding="utf-8")
    vault_path = tmp_path / "v.pii-vault.json"
    out = tmp_path / "tokenized.md"
    assert mk.main([str(src), "-o", str(out), "--vault", str(vault_path)]) == 0
    tokenized = out.read_text(encoding="utf-8")
    assert "[PII_RRN_1]" in tokenized and VALID_RRN not in tokenized
    import json as _json
    payload = _json.loads(vault_path.read_text(encoding="utf-8"))
    assert "_warning" in payload

    restored = tmp_path / "restored.md"
    assert mk.main([str(out), "-o", str(restored), "--unmask", "--vault", str(vault_path)]) == 0
    assert VALID_RRN in restored.read_text(encoding="utf-8")


def test_unmask_requires_vault(tmp_path):
    src = tmp_path / "in.md"
    src.write_text("텍스트", encoding="utf-8")
    assert mk.main([str(src), "--unmask"]) == 2


# ── 대륜 개인정보 기본 양식 규칙 (2026-09-23 확정) 리그레션 ───────────

def test_daeryun_pii_handling_policy():
    """대륜 식별정보는 유지하고, 의뢰인/상대방의 사생활 PII는 철저히 마스킹되는지 검증."""
    sample_court_doc = (
        "수신: 서울중앙지방법원 제15민사부 귀중\n"
        "원고 소송대리인 법무법인(유한) 대륜 (대표전화: 02-780-1128)\n"
        "담당변호사: 김대륜, 박송무\n"
        "피고: 홍길동 (주민등록번호: 901212-1234568, 연락처: 010-9988-7766)\n"
        "피고 입금계좌: 신한은행 110-123-456789\n"
    )

    masked, stats = mk.mask_text(sample_court_doc, mk.DEFAULT_TYPES)

    # 1. 대륜 법인 식별정보 보존 확인
    assert "법무법인(유한) 대륜" in masked
    assert "02-780-1128" in masked  # 유선 대표전화는 nodelim 또는 보존 대상
    assert "김대륜" in masked

    # 2. 상대방 PII 완벽 비식별화 확인
    assert "901212-1234568" not in masked
    assert "901212-1******" in masked
    assert "010-9988-7766" not in masked
    assert "010-9988-****" in masked
    assert "110-123-456789" not in masked

