"""stamp_evidence.py 회귀 테스트 — 한글 표찰이 깨지지 않는지 검증."""

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

fitz = pytest.importorskip("fitz", reason="pymupdf required")

import stamp_evidence  # noqa: E402

LABEL = "갑 제1호증"


def _norm(text: str) -> str:
    """PDF 폰트 셰이핑이 공백을 NBSP(\xa0)로 바꿀 수 있어 정규화."""
    return text.replace("\xa0", " ")


def _make_pdf(path: Path, pages: int = 2) -> Path:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(path)
    doc.close()
    return path


def test_korean_font_detection_or_skip():
    """한글 폰트가 있으면 경로를, 없으면 None을 반환한다(테스트는 폰트 없으면 skip)."""
    font = stamp_evidence._get_korean_font()
    if font is None:
        pytest.skip("Korean font not available on this machine")


def test_stamp_label_is_not_question_marks(tmp_path):
    """회귀: 폰트가 있을 때 한글 라벨이 '?'로 깨지면 안 된다."""
    font = stamp_evidence._get_korean_font()
    if font is None:
        pytest.skip("Korean font not available on this machine")

    src = _make_pdf(tmp_path / "src.pdf")
    out = tmp_path / "stamped.pdf"
    assert stamp_evidence.stamp_pdf_pymupdf(str(src), str(out), LABEL)

    doc = fitz.open(str(out))
    page0 = _norm(doc[0].get_text())
    doc.close()
    assert LABEL in page0, f"Korean label corrupted: {page0!r}"


def test_bates_numbering_all_pages(tmp_path):
    src = _make_pdf(tmp_path / "src.pdf", pages=2)
    out = tmp_path / "bates.pdf"
    assert stamp_evidence.stamp_pdf_pymupdf(str(src), str(out), LABEL, bates_prefix="P", start_page=1, allow_broken_font=True)

    doc = fitz.open(str(out))
    texts = [_norm(p.get_text()) for p in doc]
    doc.close()
    assert "P-0001" in texts[0]
    assert "P-0002" in texts[1]


def test_first_only_flag(tmp_path):
    font = stamp_evidence._get_korean_font()
    if font is None:
        pytest.skip("Korean font not available on this machine")
    src = _make_pdf(tmp_path / "src.pdf", pages=2)
    out = tmp_path / "first.pdf"
    assert stamp_evidence.stamp_pdf_pymupdf(str(src), str(out), LABEL, all_pages=False)

    doc = fitz.open(str(out))
    p0, p1 = _norm(doc[0].get_text()), _norm(doc[1].get_text())
    doc.close()
    assert LABEL in p0
    assert LABEL not in p1


def test_long_label_fits_in_dynamically_sized_box(tmp_path):
    """회귀: 고정 110pt 박스에서 조용히 누락되던 긴 라벨이 동적 폭 계산으로 렌더링되어야 한다."""
    font = stamp_evidence._get_korean_font()
    if font is None:
        pytest.skip("Korean font not available on this machine")

    long_label = "을 제10호증의 3 (원본 대조필)"
    src = _make_pdf(tmp_path / "src.pdf")
    out = tmp_path / "long.pdf"
    assert stamp_evidence.stamp_pdf_pymupdf(str(src), str(out), long_label)

    doc = fitz.open(str(out))
    page0 = _norm(doc[0].get_text())
    doc.close()
    assert long_label in page0, f"Long label corrupted or dropped: {page0!r}"


def test_box_width_estimate_grows_with_label():
    """라벨이 길어질수록 박스 폭 추정치가 최소폭(110pt) 이상으로 늘어나야 한다."""
    short = stamp_evidence._label_box_width("갑 제1호증")
    long = stamp_evidence._label_box_width("을 제10호증의 3 (원본 대조필)")
    assert short >= 110
    assert long > short


def test_tiny_page_degrades_gracefully(tmp_path):
    """매우 작은 페이지에서도 크래시 없이 처리되어야 한다(표찰/Bates 스킵 경고만)."""
    src = tmp_path / "tiny.pdf"
    doc = fitz.open()
    doc.new_page(width=60, height=60)
    doc.save(src)
    doc.close()

    out = tmp_path / "tiny_stamped.pdf"
    assert stamp_evidence.stamp_pdf_pymupdf(str(src), str(out), "갑 제1호증", allow_broken_font=True)


def test_format_evidence_label_branch():
    """가지번호 포맷팅 단위 테스트."""
    assert stamp_evidence.format_evidence_label("갑 제1호증", 2) == "갑 제1호증의 2"
    assert stamp_evidence.format_evidence_label("을 제5호증", 1) == "을 제5호증의 1"
    assert stamp_evidence.format_evidence_label("갑 제1호증", None) == "갑 제1호증"
    # 이미 '의 2'가 붙어있는 경우 중복 추가 방지
    assert stamp_evidence.format_evidence_label("갑 제1호증의 2", 2) == "갑 제1호증의 2"


def test_stamp_branch_evidence(tmp_path):
    """가지번호가 지정된 서증 표찰 스탬핑 테스트."""
    font = stamp_evidence._get_korean_font()
    if font is None:
        pytest.skip("Korean font not available on this machine")

    src = _make_pdf(tmp_path / "branch_src.pdf")
    out = tmp_path / "branch_stamped.pdf"
    label = stamp_evidence.format_evidence_label("갑 제1호증", 3)
    assert stamp_evidence.stamp_pdf_pymupdf(str(src), str(out), label)

    doc = fitz.open(str(out))
    page0 = _norm(doc[0].get_text())
    doc.close()
    assert "갑 제1호증의 3" in page0


def test_stamp_avoids_existing_annot_zone(tmp_path):
    """상단 우측에 기존 주석/위젯이 있으면 표찰 박스가 겹치지 않고 아래로 이동한다."""
    src = tmp_path / "annot_src.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # 기본 표찰 영역(y=20~44)을 가리는 주석을 미리 심는다
    page.add_rect_annot(fitz.Rect(page.rect.width - 140, 10, page.rect.width - 5, 50))
    doc.save(src)
    doc.close()

    doc = fitz.open(str(src))
    page = doc[0]
    y, overlapped = stamp_evidence._free_stamp_y(
        page, page.rect.width - 140, page.rect.width - 5, 20, 24, page.rect.height
    )
    doc.close()
    assert y > 20, "점유 영역과 겹치면 박스가 아래로 이동해야 한다"
    assert overlapped


def test_stamp_clean_page_stays_on_top(tmp_path):
    """점유물이 없는 페이지는 기본 위치(y=20)를 유지한다."""
    src = tmp_path / "clean_src.pdf"
    _make_pdf(src)
    doc = fitz.open(str(src))
    page = doc[0]
    y, overlapped = stamp_evidence._free_stamp_y(
        page, page.rect.width - 140, page.rect.width - 5, 20, 24, page.rect.height
    )
    doc.close()
    assert y == 20 and not overlapped

