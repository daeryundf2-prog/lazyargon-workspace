"""analyze_court_ruling.py 회귀 테스트 — 섹션 분할·인용 추출·JSON 모드."""

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import analyze_court_ruling as acr  # noqa: E402

RULING = """【주 문】
1. 피고는 원고에게 금 10,000,000원을 지급하라.

【이 유】
1. 원고의 주장
원고는 대여금 반환을 청구한다(민법 제388조 참조).

2. 피고의 항변
피고는 변제기가 아니라고 항변한다.

3. 위 항변에 대한 판단
법원은 대법원 2023. 5. 26. 선고 2021다274214 판결에 따라 판단한다.
개인정보보호법 제71조 위반 주장도 함께 검토한다.
"""


@pytest.fixture()
def ruling_file(tmp_path):
    p = tmp_path / "판결문.txt"
    p.write_text(RULING, encoding="utf-8")
    return p


def test_split_sections(ruling_file):
    sections = acr.split_sections(RULING)
    names = [s["name"] for s in sections]
    assert names[0] == "주문"
    assert "이유" in names
    jue = next(s for s in sections if s["name"] == "이유")
    assert jue["chars"] > 0, "이유 섹션에 본문이 담겨야 함"


def test_subsections_detected(ruling_file):
    subs = acr.find_subsections(RULING)
    assert any("원고의 주장" in s for s in subs)
    assert any("항변" in s for s in subs)
    assert any("판단" in s for s in subs)


def test_law_extraction_deduped():
    laws = acr.extract_laws("민법 제388조와 민법 제 388조, 개인정보보호법 제71조의 1에 따라")
    assert laws.count("민법 제388조") == 1, "공백 변형은 정규화되어 중복 제거되어야 함"
    assert "개인정보보호법 제71조의 1" in laws


def test_precedent_extraction():
    prec = acr.extract_precedents("대법원 2023. 5. 26. 선고 2021다274214 판결 참조")
    assert len(prec) == 1 and "2021다274214" in prec[0]


def test_markdown_render_has_issue_skeleton(ruling_file, tmp_path):
    out = tmp_path / "분석.md"
    assert acr.main([str(ruling_file), "-o", str(out)]) == 0
    md = out.read_text(encoding="utf-8")
    assert "쟁점 요약표" in md and "법원 판단" in md
    assert "민법 제388조" in md
    assert "2021다274214" in md


def test_json_mode_contains_section_text(ruling_file, tmp_path):
    out = tmp_path / "구조.json"
    assert acr.main([str(ruling_file), "--json", "-o", str(out)]) == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    jue = next(s for s in body["sections"] if s["name"] == "이유")
    assert "대여금 반환" in jue["text"]
    assert body["laws"] and "민법 제388조" in body["laws"]


def test_no_header_falls_back_to_full_text(tmp_path):
    p = tmp_path / "plain.txt"
    p.write_text("헤더 없는 자유 형식 판결문 본문입니다.", encoding="utf-8")
    assert acr.main([str(p), "-o", str(tmp_path / "r.md")]) == 0
    md = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "전문" in md


def test_empty_input_rejected(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("   \n", encoding="utf-8")
    assert acr.main([str(p)]) == 2
    assert acr.main(["없음.txt"]) == 2


def test_verify_mode_renders_audit_section(ruling_file, tmp_path):
    out = tmp_path / "분석_검증.md"
    assert acr.main([str(ruling_file), "--verify", "-o", str(out)]) == 0
    md = out.read_text(encoding="utf-8")
    assert "## 인용 법령·판례 무결성 검증 (Factuality Audit)" in md
    assert "검증 결과" in md

    # JSON mode with --verify
    out_json = tmp_path / "분석_검증.json"
    assert acr.main([str(ruling_file), "--json", "--verify", "-o", str(out_json)]) == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert "factuality_audit" in data
    assert data["factuality_audit"]["verdict"] in ("PASS", "WARN")


def test_verify_strict_mode_blocks_hallucinated_ruling(tmp_path):
    bad_ruling = tmp_path / "bad_ruling.txt"
    bad_ruling.write_text("주 문\n피고는 민법 제1500조에 따라 배상하라.", encoding="utf-8")
    out = tmp_path / "blocked.md"
    assert acr.main([str(bad_ruling), "--verify", "--strict", "-o", str(out)]) == 1
    assert not out.exists()


def test_analyze_court_ruling_with_source_and_morph_grounding(tmp_path):
    src_file = tmp_path / "reference_facts.txt"
    src_file.write_text("원고와 피고는 민법 제750조에 의하여 손해배상을 청구하였다.", encoding="utf-8")

    ruling_file = tmp_path / "ruling.txt"
    ruling_file.write_text("【주 문】\n피고는 원고에게 손해배상금을 지급하라.\n【이 유】\n민법 제750조에 근거한다.", encoding="utf-8")

    out_json = tmp_path / "result.json"
    rc = acr.main([str(ruling_file), "--source", str(src_file), "--morph-grounding", "--json", "-o", str(out_json)])
    assert rc == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert "factuality_audit" in data
    assert data["factuality_audit"]["verdict"] in ("PASS", "WARN")
