"""parse_korean_doc.py 회귀 테스트 — 실제 HWPX(OWPML) 표준 네임스페이스 기반."""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "parse_korean_doc.py"

# 실제 HWPX(OWPML/KS X 6101)가 사용하는 표준 네임스페이스
HP_NS = "http://www.hancom.co.kr/hwpml/2011/hp"
HS_NS = "http://www.hancom.co.kr/hwpml/2011/hs"

SECTION_TMPL = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hs:root xmlns:hs="{hs}" xmlns:hp="{hp}">
  <hp:body>
    <hp:p><hp:t>제{{i}}조 표준 네임스페이스 문단입니다.</hp:t></hp:p>
    <hp:tbl>
      <hp:tr><hp:tc><hp:t>항목</hp:t></hp:tc><hp:tc><hp:t>금액</hp:t></hp:tc></hp:tr>
      <hp:tr><hp:tc><hp:t>계약금</hp:t></hp:tc><hp:tc><hp:t>{{i}}000원</hp:t></hp:tc></hp:tr>
    </hp:tbl>
  </hp:body>
</hs:root>
""".format(hs=HS_NS, hp=HP_NS)

CONTENT_HPF = """<?xml version="1.0" encoding="UTF-8"?>
<pkg:package xmlns:pkg="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>표준 계약서</dc:title>
  <dc:creator>홍길동</dc:creator>
</pkg:package>
"""


def _build_hwpx(path: Path, section_count: int = 1) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/content.hpf", CONTENT_HPF)
        for i in range(section_count):
            z.writestr(f"Contents/section{i}.xml", SECTION_TMPL.replace("{i}", str(i)))
    return path


def _run(path: Path, *extra: str) -> dict:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(path), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_hwpx_standard_namespace_text_extraction(tmp_path):
    """회귀: 표준 hwpml/2011/hp 네임스페이스 HWPX에서 텍스트가 추출되어야 한다."""
    hwpx = _build_hwpx(tmp_path / "real.hwpx")
    out = _run(hwpx)
    assert "표준 네임스페이스 문단입니다" in out["text"]
    assert out["metadata"].get("title") == "표준 계약서"
    assert out["metadata"].get("creator") == "홍길동"


def test_hwpx_table_extraction(tmp_path):
    hwpx = _build_hwpx(tmp_path / "table.hwpx")
    out = _run(hwpx)
    assert out["tables"], "표가 추출되어야 함"
    assert out["tables"][0][0] == ["항목", "금액"]


def test_hwpx_section_natural_sort(tmp_path):
    """section10.xml이 section2.xml보다 앞에 오지 않아야 한다."""
    hwpx = _build_hwpx(tmp_path / "multi.hwpx", section_count=11)
    out = _run(hwpx)
    names = [s["name"] for s in out["sections"]]
    assert names.index("Contents/section2.xml") < names.index("Contents/section10.xml")


def test_hwpx_markdown_output(tmp_path):
    hwpx = _build_hwpx(tmp_path / "md.hwpx")
    out_path = tmp_path / "parsed.md"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(hwpx), "--markdown", "--output", str(out_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0, r.stderr
    md = out_path.read_text(encoding="utf-8")
    assert "표준 네임스페이스 문단입니다" in md
    assert "| 항목 | 금액 |" in md


def test_legacy_hwpx_namespace_still_works(tmp_path):
    """구 네임스페이스(schemas.hancom.co.kr/owl) 문서도 하위 호환으로 파싱되어야 한다."""
    legacy = SECTION_TMPL.replace(HP_NS, "http://schemas.hancom.co.kr/owl/hp")
    path = tmp_path / "legacy.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/section0.xml", legacy)
    out = _run(path)
    assert "표준 네임스페이스 문단입니다" in out["text"]


def test_hwp_invalid_file_returns_error_dict(tmp_path):
    """hwp-hwpx-parser가 설치되어 있어도 잘못된 .hwp는 크래시 없이 error dict를 반환한다."""
    bad = tmp_path / "bad.hwp"
    bad.write_bytes(b"not-an-hwp-file")
    r = subprocess.run([sys.executable, str(SCRIPT), str(bad)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 1
    assert "Error" in r.stderr


def test_hwpx_table_text_not_duplicated_in_body(tmp_path):
    """회귀: 표 셀 텍스트가 본문 text에 이중으로 들어가면 안 된다(표는 tables로 제공)."""
    hwpx = _build_hwpx(tmp_path / "dedup.hwpx")
    out = _run(hwpx)
    assert "계약금" not in out["text"], "표 셀 텍스트가 본문 text에 중복됨"
    assert out["tables"][0][1] == ["계약금", "0000원"], "표 데이터는 그대로 보존되어야 함"
    # 표 바깥 문단은 여전히 text에 있어야 한다
    assert "표준 네임스페이스 문단입니다" in out["text"]


def test_pdf_invalid_file_tries_both_parsers(tmp_path):
    """회귀: PyMuPDF가 ImportError가 아닌 예외로 실패해도 pypdf 폴백을 시도하고,
    둘 다 실패하면 두 파서의 오류 사유가 모두 담긴 error dict를 반환한다."""
    bad = tmp_path / "garbage.pdf"
    bad.write_bytes(b"this is definitely not a pdf file at all")
    r = subprocess.run([sys.executable, str(SCRIPT), str(bad)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 1
    assert "Error" in r.stderr
    # 폴백 체인이 실제로 양쪽을 모두 시도했는지 오류 메시지로 확인
    assert "PyMuPDF failed" in r.stderr, "PyMuPDF 실패 사유가 포함되어야 함"
    assert "pypdf failed" in r.stderr, "pypdf 폴백이 시도되었어야 함"


def test_anydoc_csv_and_office_support(tmp_path):
    """AnyDoc이 CSV 및 오피스 파일 형식을 마크다운으로 정상 파싱해야 한다."""
    csv_file = tmp_path / "sample.csv"
    csv_file.write_text("이름,부서,직급\n홍길동,디지털포렌식팀,수석연구원\n이순신,형사소송팀,변호사\n", encoding="utf-8")
    out = _run(csv_file)
    assert out["format"] == "CSV"
    assert "홍길동" in out["text"]
    assert "디지털포렌식팀" in out["text"]


def test_anydoc_markdown_flag_output(tmp_path):
    """AnyDoc 파일 파싱 시 --markdown 옵션이 정상 작동해야 한다."""
    csv_file = tmp_path / "table.csv"
    csv_file.write_text("호증,증거명,입증취지\n갑 제1호증,차용증,대여금 지급 사실\n", encoding="utf-8")
    out_path = tmp_path / "out.md"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(csv_file), "--markdown", "--output", str(out_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 0, r.stderr
    content = out_path.read_text(encoding="utf-8")
    assert "Document Content: table.csv" in content
    assert "갑 제1호증" in content


def test_anydoc_extensions_include_odp_without_duplicate_odt():
    """회귀: ANYDOC_EXTENSIONS에 .odp가 있어야 하고 .odt 중복이 없어야 한다."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "parse_korean_doc",
        str(Path(__file__).resolve().parent.parent / "scripts" / "parse_korean_doc.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    exts = mod.ANYDOC_EXTENSIONS
    assert ".odp" in exts, "ODP(Impress) 누락 회귀"
    assert ".odt" in exts
    assert isinstance(exts, set), "중복 방지를 위해 set 유지"
    # 소스 텍스트상 .odt 리터럴은 정확히 1회만 등장해야 함 (shadowing/중복 방지)
    src = (Path(__file__).resolve().parent.parent / "scripts" / "parse_korean_doc.py").read_text(encoding="utf-8")
    assert src.count('".odt"') == 1, "중복 .odt 리터럴 존재"


def test_mineru_gate_returns_tuple():
    """mineru_available()은 (bool, str) 튜플을 반환해야 한다(BYOB 게이트)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "parse_korean_doc",
        str(Path(__file__).resolve().parent.parent / "scripts" / "parse_korean_doc.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ok, reason = mod.mineru_available()
    assert isinstance(ok, bool)
    assert isinstance(reason, str) and reason


def test_mineru_engine_without_install_fails_closed(tmp_path):
    """--engine mineru 지정 시 MinerU 미설치 환경에서 fail-closed로 종료."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "parse_korean_doc",
        str(Path(__file__).resolve().parent.parent / "scripts" / "parse_korean_doc.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ok, _ = mod.mineru_available()
    if ok:
        pytest.skip("MinerU available — fail-closed path not exercised")
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(pdf), "--engine", "mineru"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert r.returncode == 1
    assert "MinerU" in r.stderr or "mineru" in r.stderr
