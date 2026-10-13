"""test_korean_morph_grounding.py — Kiwi 형태소 분석 기반 한국어 법률 그라운딩 테스트."""

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import korean_morph_grounding as kmg


def test_extract_content_morphemes_strips_particles():
    text = "갑호증을 법원에 제출하여 대여금채권의 변제기를 증명하였다."
    tokens = kmg.extract_content_morphemes(text)
    # 조사(을, 에, 의, 를) 및 어미(하여, 하였다) 제거 검증
    assert "을" not in tokens
    assert "에" not in tokens
    assert "의" not in tokens
    assert "대여금" in tokens or "채권" in tokens
    assert "증명" in tokens or "제출" in tokens


def test_extract_legal_entities():
    text = (
        "원고는 민법 제390조 및 형법 제347조에 의하여 대법원 2017다220744 판결을 원용하고, "
        "갑 제1호증 차용증 및 을 제2호증 영수증을 제출합니다."
    )
    entities = kmg.extract_legal_entities(text)
    assert any("민법 제390조" in s for s in entities["statutes"])
    assert any("형법 제347조" in s for s in entities["statutes"])
    assert "2017다220744" in entities["precedents"]
    assert "갑 제1호증" in entities["evidence_labels"]
    assert "을 제2호증" in entities["evidence_labels"]


def test_calculate_grounding_overlap_high():
    source = "2024년 1월 16일 원고는 피고에게 금 10,000,000원을 송금하였고 피고는 차용증을 작성하여 교부하였다."
    target = "원고는 피고에게 10,000,000원을 송금하였으며 피고가 작성한 차용증을 증거로 제출합니다."

    res = kmg.calculate_grounding_overlap(source, target, threshold=0.70)
    assert res["is_grounded"] is True
    assert res["grounding_score"] >= 0.70
    assert "차용증" in res["supported_terms"]
    assert "송금" in res["supported_terms"]


def test_calculate_grounding_overlap_detects_unsupported_novel_claims():
    source = "원고는 피고에게 10,000,000원을 송금하였다."
    target = "피고는 원고를 폭행 협박하여 금전을 갈취하였고 사기 및 횡령죄로 고소합니다."

    res = kmg.calculate_grounding_overlap(source, target, threshold=0.70)
    assert res["is_grounded"] is False
    assert res["grounding_score"] < 0.50
    # Novel unsupported terms detected
    assert len(res["unsupported_terms"]) > 0
    assert any(t in res["unsupported_terms"] for t in ["폭행", "협박", "갈취", "사기", "횡령"])


def test_cli_execution_with_temp_files(tmp_path):
    src_file = tmp_path / "source.txt"
    src_file.write_text("원고와 피고는 대여금 계약을 체결하고 갑 제1호증 차용증을 교부하였다.", encoding="utf-8")

    tgt_file = tmp_path / "target.txt"
    tgt_file.write_text("대여금 계약에 따라 갑 제1호증 차용증이 교부되었습니다.", encoding="utf-8")

    code = kmg.main(["--source", str(src_file), "--target", str(tgt_file), "--json"])
    assert code == 0


def test_extract_legal_entities_does_not_extract_dates_as_precedents():
    text = "2024년 5월 1일 및 2023년 12월 25일에 계약을 체결하였으며 대법원 2024다12345 판결을 참조합니다."
    entities = kmg.extract_legal_entities(text)
    # Ensure standard dates like 2024년5 are NOT included
    assert "2024년5" not in entities["precedents"]
    assert "2023년12" not in entities["precedents"]
    assert "2024다12345" in entities["precedents"]


def test_korean_morph_grounding_high_fidelity(tmp_path):
    src_file = tmp_path / "source.txt"
    src_file.write_text("원고와 피고는 대여금 계약을 체결하고 차용증을 작성하였다.", encoding="utf-8")

    # Has novel unsupported terms
    tgt_file_fail = tmp_path / "target_fail.txt"
    tgt_file_fail.write_text("피고는 사기 및 횡령으로 원고를 기망하였다.", encoding="utf-8")

    code_fail = kmg.main(["--source", str(src_file), "--target", str(tgt_file_fail), "--high-fidelity", "--json"])
    assert code_fail == 1

    # Supported overlap passes
    tgt_file_pass = tmp_path / "target_pass.txt"
    tgt_file_pass.write_text("원고와 피고는 대여금 계약을 체결하고 차용증을 작성하였습니다.", encoding="utf-8")

    code_pass = kmg.main(["--source", str(src_file), "--target", str(tgt_file_pass), "--high-fidelity", "--json"])
    assert code_pass == 0



def test_analyze_old_korean_detects_arae_a():
    """아래아(ㆍ/ᆞ) 같은 옛 자모를 식별한다."""
    result = kmg.analyze_old_korean("ᄒᆞᆫ글이 아래앗 글짬판결문")
    assert result["has_archaic"] is True
    assert result["archaic_count"] > 0
    assert "ᆞ" in result["archaic_chars"] or "ㆍ" in result["archaic_chars"]


def test_analyze_old_korean_modern_text_clean():
    result = kmg.analyze_old_korean("대법원 2020다12345 판결")
    assert result["has_archaic"] is False
    assert result["archaic_chars"] == []
    assert result["syllables_decomposed"] > 0


def test_analyze_old_korean_empty():
    result = kmg.analyze_old_korean("")
    assert result["has_archaic"] is False
    assert result["jamo_units"] == 0


def test_old_korean_cli_flag(tmp_path):
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = kmg.main(["--text", "나랏말ᄊᆞ미", "--old-korean", "--json"])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["old_korean"]["has_archaic"] is True
