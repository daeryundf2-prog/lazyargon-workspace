"""sanitize_text.py 규칙 고정 테스트.

scripts/sanitize_text.py:5 가 약속한 "tests/test_sanitize.py 가 규칙을 고정"을
실제로 만든다. 규칙을 바꾸려면 이 테스트와 함께 바꿔야 한다.
"""

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sanitize_text as st  # noqa: E402


def test_nfd_hangul_recomposed():
    nfd = unicodedata.normalize("NFD", "홍길동")
    assert nfd != "홍길동"
    out, rep = st.sanitize(nfd)
    assert out == "홍길동"
    assert rep.counts["hangul_recomposed"] > 0


def test_zero_width_removed():
    out, rep = st.sanitize("가\u200b나")
    assert "\u200b" not in out
    assert out == "가나"
    assert rep.counts["invisible"] >= 1


def test_meaning_preserved():
    src = "청구금액은 12,500,000원이며 이자는 연 5%로 한다."
    out, _ = st.sanitize(src)
    assert out == src, "정상 텍스트는 그대로여야 한다"


def test_ideographic_space_opt_in():
    src = "첫째\u3000둘째"
    out, _ = st.sanitize(src)
    assert "\u3000" in out, "전각공백 정규화는 opt-in이므로 기본 유지"
    out2, rep2 = st.sanitize(src, normalize_ideographic_space=True)
    assert "\u3000" not in out2
    assert rep2.counts["special_spaces"] >= 1


def test_inspect_does_not_mutate():
    src = "가\u200b나"
    rep = st.inspect(src)
    assert rep.changed
    assert src == "가\u200b나", "inspect는 원문을 바꾸지 않는다"
