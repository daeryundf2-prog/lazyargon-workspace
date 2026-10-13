"""generate_legal_draft.py 회귀 테스트 — 문서 구조·증거 자동 인용·고지 강제."""

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import generate_legal_draft as gld  # noqa: E402

BASE = {
    "type": "소장",
    "case_info": {"court": "서울중앙지방법원", "plaintiff": "홍길동", "defendant": "주식회사 XXX"},
    "claims": ["대여금 원금 10,000,000원 및 지연손해금"],
    "facts": [
        {
            "heading": "1. 대여 관계의 성립",
            "paragraphs": ["원고는 2024년 1월 16일 피고에게 금 10,000,000원을 전달하였다(갑제1호증)."],
        },
        {
            "heading": "2. 변제 기한 경과",
            "paragraphs": ["피고는 변제 기한인 2024년 3월 1일까지 변제하지 않았다."],
            "evidence": ["갑 제2호증"],
        },
    ],
    "evidence_list": [
        {"label": "갑 제1호증", "title": "차용증"},
        {"label": "갑 제2호증", "title": "내용증명"},
    ],
}


def test_sojang_structure_and_watermark():
    md = gld.generate(BASE)
    assert "청구취지" in md and "청구원인" in md and "구하건은" in md
    assert gld.DISCLAIMER in md, "변호사 검토 고지는 항상 포함되어야 한다"
    assert "서울중앙지방법원" in md
    assert "증거 목록" in md and "차용증" in md


def test_evidence_auto_citation_normalizes_compact_label():
    """'갑제1호증'(붙여 씀)도 자동 탐지해 표준형 라벨+서증명으로 결합한다."""
    md = gld.generate(BASE)
    assert "*입증방법: 갑 제1호증, 차용증*" in md
    assert "*입증방법: 갑 제2호증, 내용증명*" in md


def test_unknown_label_reports_missing_title():
    data = json.loads(json.dumps(BASE))
    data["facts"][1]["evidence"] = ["갑 제9호증"]
    md = gld.generate(data)
    assert "갑 제9호증" in md and "(서증명 미기재)" in md


def test_all_document_types_render():
    for doc_type, must_contain in {
        "준비서면": ["답변의 요지", "기각"],
        "고소장": ["범죄사실", "고소 취지"],
        "내용증명": ["경위", "14일 이내"],
    }.items():
        data = json.loads(json.dumps(BASE))
        data["type"] = doc_type
        md = gld.generate(data)
        for token in must_contain:
            assert token in md, f"{doc_type}에 '{token}' 누락"
        assert gld.DISCLAIMER in md


def test_ministry_report_preset_renders_hierarchy():
    """업무보고서 타입은 행안부 상단 표기와 1. → 가. 위계를 출력한다."""
    data = {
        "type": "업무보고서",
        "case_info": {
            "doc_number": "감정-2026-15호",
            "recipient": "법무법인 대륜",
            "title": "분석 진행 상황 업무보고",
        },
        "claims": ["이번 주 디스크 이미징 및 타임라인 병합을 완료하였음을 보고드립니다."],
        "facts": [
            {
                "heading": "분석 진행 현황",
                "paragraphs": [
                    "대상 디스크 이미지 획득 및 해시 검증을 완료하였다.",
                    "이벤트 로그 타임라인 병합을 진행 중이다.",
                ],
            },
        ],
        "evidence_list": [],
    }
    md = gld.generate(data)
    assert "문서번호: 감정-2026-15호" in md
    assert "수    신: 법무법인 대륜" in md
    assert "제    목: 분석 진행 상황 업무보고" in md
    assert "1. 분석 진행 현황" in md
    assert "가. 대상 디스크 이미지" in md
    assert "나. 이벤트 로그 타임라인" in md
    assert "끝." in md


def test_ministry_report_title_placeholder_when_missing():
    data = {"type": "업무보고서", "case_info": {}, "claims": [], "facts": []}
    md = gld.generate(data)
    assert "{보고서 제목}" in md


def test_invalid_type_rejected():
    data = json.loads(json.dumps(BASE))
    data["type"] = "이혼소장"
    with pytest.raises(ValueError):
        gld.generate(data)


def test_main_writes_file_and_exit_codes(tmp_path):
    src = tmp_path / "draft.json"
    src.write_text(json.dumps(BASE, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "소장_초안.md"
    assert gld.main(["--input-json", str(src), "--output", str(out)]) == 0
    assert gld.DISCLAIMER in out.read_text(encoding="utf-8")

    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    assert gld.main(["--input-json", str(bad)]) == 2
    assert gld.main(["--input-json", "없음.json"]) == 2


def test_factuality_verification_blocks_hallucinated_statute(tmp_path):
    data = json.loads(json.dumps(BASE))
    data["claims"].append("민법 제1500조에 기한 부당이득반환청구")
    
    # Library call with verify=True raises ValueError
    with pytest.raises(ValueError) as exc:
        gld.generate(data, verify=True)
    assert "민법" in str(exc.value) and "허위 조문" in str(exc.value)

    # CLI with default --verify exits 1
    src = tmp_path / "hallucinated_draft.json"
    src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "blocked.md"
    assert gld.main(["--input-json", str(src), "--output", str(out)]) == 1
    assert not out.exists()

    # CLI with --no-verify passes through
    assert gld.main(["--input-json", str(src), "--no-verify", "--output", str(out)]) == 0
    assert out.exists()


def test_factuality_verification_blocks_future_precedent(tmp_path):
    data = json.loads(json.dumps(BASE))
    data["facts"][0]["paragraphs"].append("대법원 2030다99999 판결의 법리에 따름.")

    src = tmp_path / "future_draft.json"
    src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "future_out.md"
    assert gld.main(["--input-json", str(src), "--output", str(out)]) == 1
    assert not out.exists()


def test_evidence_tags_supported():
    data = json.loads(json.dumps(BASE))
    data["facts"][0]["paragraphs"] = [
        "<evidence>2024년 1월 16일 금 10,000,000원을 무통장 입금하였다.</evidence> 피고에게 대여금을 교부하였습니다."
    ]
    md = gld.generate(data)
    assert "<evidence>" in md and "무통장 입금" in md


def test_strict_evidence_blocks_ungrounded_paragraph():
    data = json.loads(json.dumps(BASE))
    data["facts"] = [{"heading": "무근거 사실", "paragraphs": ["피고는 원고에게 폭언을 일삼았다."]}]
    with pytest.raises(ValueError) as exc:
        gld.generate(data, strict_evidence=True)
    assert "Strict Evidence Gate" in str(exc.value)


def test_attributed_evidence_tags_supported():
    data = json.loads(json.dumps(BASE))
    data["facts"][0]["paragraphs"] = [
        '<evidence source="bank_receipt.pdf">2024년 1월 16일 금 10,000,000원을 입금하였다.</evidence> 대여금을 지급하였습니다.'
    ]
    md = gld.generate(data, strict_evidence=True)
    assert '<evidence source="bank_receipt.pdf">' in md


def test_generate_legal_draft_source_cli(tmp_path):
    facts_file = tmp_path / "facts.txt"
    facts_file.write_text("2024년 1월 16일 금 10,000,000원을 입금하였다.", encoding="utf-8")

    data = json.loads(json.dumps(BASE))
    data["facts"][0]["paragraphs"] = [
        "<evidence>2024년 1월 16일 금 10,000,000원을 입금하였다.</evidence> 원고는 피고에게 대여하였습니다."
    ]
    src = tmp_path / "draft.json"
    src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.md"

    # With matching source, passes with 0
    res = gld.main(["--input-json", str(src), "--output", str(out), "--source", str(facts_file)])
    assert res == 0
    assert out.exists()

    # With mismatched source, fails with 1
    mismatch_file = tmp_path / "wrong.txt"
    mismatch_file.write_text("전혀 다른 내용입니다.", encoding="utf-8")
    out2 = tmp_path / "out2.md"
    res_mismatch = gld.main(["--input-json", str(src), "--output", str(out2), "--source", str(mismatch_file)])
    assert res_mismatch == 1
    assert not out2.exists()


def test_generate_legal_draft_high_fidelity(tmp_path):
    facts_file = tmp_path / "facts.txt"
    facts_file.write_text("2024년 1월 16일 금 10,000,000원을 입금하였다. 원고는 피고에게 대여하였습니다.", encoding="utf-8")

    data = json.loads(json.dumps(BASE))
    data["facts"] = [
        {
            "heading": "1. 대여 관계의 성립",
            "paragraphs": [
                "<evidence>2024년 1월 16일 금 10,000,000원을 입금하였다.</evidence> 원고는 피고에게 대여하였습니다."
            ],
            "evidence": ["갑 제1호증"],
        }
    ]
    src = tmp_path / "draft.json"
    src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # High fidelity requires --source (fails if omitted)
    out1 = tmp_path / "out_no_source.md"
    res_no_source = gld.main(["--input-json", str(src), "--output", str(out1), "--high-fidelity"])
    assert res_no_source == 1

    # High fidelity with valid source succeeds
    out2 = tmp_path / "out_hf_pass.md"
    res_pass = gld.main(["--input-json", str(src), "--output", str(out2), "--source", str(facts_file), "--high-fidelity"])
    assert res_pass == 0
    assert out2.exists()


