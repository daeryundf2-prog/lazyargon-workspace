"""bind_court_pdf.py 회귀 테스트 — 병합·북마크·용량 분할·엄격 모드."""

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

fitz = pytest.importorskip("fitz", reason="pymupdf required")

import bind_court_pdf as bcp  # noqa: E402


def _make_pdf(path: Path, pages: int, marker: str) -> Path:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"{marker} page {i + 1}")
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def evidence_pdfs(tmp_path):
    files = [
        _make_pdf(tmp_path / "갑제1호증.pdf", 2, "갑1"),
        _make_pdf(tmp_path / "갑제2호증.pdf", 3, "갑2"),
        _make_pdf(tmp_path / "갑제3호증.pdf", 1, "갑3"),
    ]
    items = [
        {"label": "갑 제1호증", "title": "차용증", "file": str(files[0])},
        {"label": "갑 제2호증", "title": "계좌거래내역", "file": str(files[1])},
        {"label": "갑 제3호증", "title": "카카오톡", "file": str(files[2])},
    ]
    manifest = tmp_path / "evidence.json"
    manifest.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return manifest, items


def test_bind_single_volume_with_bookmarks(tmp_path, evidence_pdfs):
    manifest, items = evidence_pdfs
    out = tmp_path / "바인더.pdf"
    assert bcp.main(["--input-json", str(manifest), "-o", str(out)]) == 0

    doc = fitz.open(str(out))
    assert len(doc) == 6, "2+3+1 = 6페이지가 병합되어야 함"
    toc = doc.get_toc()
    assert [t[1] for t in toc] == [
        "갑 제1호증 차용증", "갑 제2호증 계좌거래내역", "갑 제3호증 카카오톡",
    ]
    assert [t[2] for t in toc] == [1, 3, 6]  # 각 증거의 시작 페이지(1-based)
    doc.close()


def test_bind_splits_by_size_limit(tmp_path, evidence_pdfs):
    manifest, _ = evidence_pdfs
    out = tmp_path / "바인더.pdf"
    # 원본 PDF 1개 크기보다 작게 → 전부 분할
    assert bcp.main(["--input-json", str(manifest), "-o", str(out), "--max-mb", "0.0001"]) == 0
    volumes = sorted(tmp_path.glob("바인더_*권.pdf"))
    assert len(volumes) == 3, "각 증거가 별도 권으로 분할되어야 함"
    for vol in volumes:
        doc = fitz.open(str(vol))
        assert len(doc.get_toc()) == 1
        doc.close()


def test_evidence_list_wrapper_json_compatible(tmp_path):
    """증거설명서 형식({"evidence_list": [...]})도 수용한다."""
    pdf = _make_pdf(tmp_path / "a.pdf", 1, "A")
    manifest = tmp_path / "evidence.json"
    manifest.write_text(
        json.dumps({"evidence_list": [{"label": "갑 제1호증", "file": str(pdf)}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    out = tmp_path / "binder.pdf"
    assert bcp.main(["--input-json", str(manifest), "-o", str(out)]) == 0
    doc = fitz.open(str(out))
    assert len(doc) == 1
    doc.close()


def test_missing_file_aborts(tmp_path):
    manifest = tmp_path / "evidence.json"
    manifest.write_text(
        json.dumps([{"label": "갑 제1호증", "file": "없는증거.pdf"}], ensure_ascii=False),
        encoding="utf-8",
    )
    assert bcp.main(["--input-json", str(manifest), "-o", str(tmp_path / "b.pdf")]) == 2
    assert not (tmp_path / "b.pdf").exists()


def test_empty_list_and_bad_json(tmp_path, evidence_pdfs):
    manifest, _ = evidence_pdfs
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    assert bcp.main(["--input-json", str(empty), "-o", str(tmp_path / "b.pdf")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert bcp.main(["--input-json", str(bad), "-o", str(tmp_path / "b.pdf")]) == 2
