"""name/address opt-in 타입 테스트 — 기본 off, 라벨/호칭/직함 구분."""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from mask_korean_pii import DEFAULT_TYPES, PiiVault, mask_text  # noqa: E402


def _mask(text, extra=frozenset()):
    return mask_text(text, DEFAULT_TYPES | set(extra))


# ── opt-in 게이트 ────────────────────────────────────────────────

def test_names_not_masked_by_default():
    out, _ = _mask("성명: 김철수")
    assert "김철수" in out  # 기본 타입에는 name이 없다


def test_addresses_not_masked_by_default():
    out, _ = _mask("주소: 서울특별시 강남구 테헤란로 123")
    assert "테헤란로" in out


# ── 이름 탐지 ────────────────────────────────────────────────────

def test_labeled_name_masked():
    out, stats = _mask("성명: 김철수", {"name"})
    assert "김철수" not in out
    assert "김**" in out
    assert stats["name"] == 1


def test_labeled_name_with_particle():
    out, _ = _mask("피고인 이영희는 출석했다.", {"name"})
    assert "이**는" in out  # 조사 '는'이 이름에 삼켜지지 않는다


def test_honorific_name_masked():
    out, stats = _mask("김철수님께서 확인했다. 박민수 씨 동의.", {"name"})
    assert "김철수" not in out and "박민수" not in out
    assert "김**님께서" in out and "박** 씨" in out
    assert stats["name"] == 2


def test_role_titles_not_masked():
    out, stats = _mask("사장님과 고객님, 담당자님께 안내드립니다.", {"name"})
    assert stats["name"] == 0
    assert stats["name_skipped_role"] == 3
    assert "사장님" in out and "고객님" in out


def test_non_surname_honorific_not_masked():
    out, stats = _mask("여러분 안녕하세요", {"name"})
    assert stats["name"] == 0


# ── 주소 탐지 ────────────────────────────────────────────────────

def test_road_address_masked():
    out, stats = _mask("주소: 서울특별시 강남구 테헤란로 123", {"address"})
    assert "테헤란로 123" not in out
    assert "서울특별시 ***" in out  # 시/도까지만 보존
    assert stats["address"] == 1


def test_jibun_address_masked():
    out, _ = _mask("경기도 성남시 분당구 판교로 10번지에 거주", {"address"})
    assert "10번지" not in out


def test_region_only_not_masked():
    # 시/군/구까지만 있는 지역 언급은 번지 없이 개인정보가 아니다
    out, stats = _mask("본점은 서울특별시 강남구에 있습니다.", {"address"})
    assert stats["address"] == 0
    assert "강남구" in out


# ── vault 토큰화 ─────────────────────────────────────────────────

def test_vault_tokenizes_name_and_address():
    vault = PiiVault(salt="test")
    out, stats = vault.tokenize_text("성명: 김철수, 서울특별시 강남구 테헤란로 123", {"name", "address"})
    assert "김철수" not in out and "테헤란로" not in out
    assert "[PII_NAME_1]" in out and "[PII_ADDRESS_1]" in out
    restored = vault.detokenize_text(out)
    assert "김철수" in restored and "테헤란로 123" in restored
