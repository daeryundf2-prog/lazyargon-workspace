"""test_verify_legal_factuality.py — 법률 환각 검증기(verify_legal_factuality.py) 단위 테스트."""

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import verify_legal_factuality as vlf


def test_valid_statute_and_precedent_pass():
    text = """
    # 준비서면
    원고는 민법 제390조(채무불이행) 및 제750조(불법행위)에 기하여 손해배상을 청구합니다.
    대법원 2017다220744 판결 및 2018도13792 판결의 법리에 따릅니다.
    변호사의 검토 후 제출 바랍니다. AI 생성 초안입니다.
    """
    res = vlf.verify_legal_text(text)
    assert res["verdict"] == "PASS"
    assert len(res["errors"]) == 0
    assert "민법 제390조" in res["cited_statutes"]
    assert "2017다220744" in res["cited_precedents"]


def test_statute_out_of_bounds_detected():
    text = "피고의 행위는 민법 제1500조 및 형법 제500조에 위반됩니다."
    res = vlf.verify_legal_text(text)
    assert res["verdict"] == "FAIL"
    assert any("민법" in e and "제1500조" in e for e in res["errors"])
    assert any("형법" in e and "제500조" in e for e in res["errors"])


def test_future_precedent_year_blocked():
    text = "대법원 2099다12345 판결에 따라 원고의 청구는 이유 있다."
    res = vlf.verify_legal_text(text, current_year=2026)
    assert res["verdict"] == "FAIL"
    assert any("미래 연도 판결" in e and "2099다12345" in e for e in res["errors"])


def test_pre_1948_precedent_blocked():
    text = "대법원 1910다100 판결을 인용한다."
    res = vlf.verify_legal_text(text)
    assert res["verdict"] == "FAIL"
    assert any("1948년 이전" in e for e in res["errors"])


def test_unusual_case_code_warns():
    text = "서울중앙지방법원 2024쀍9999 판결 참조."
    res = vlf.verify_legal_text(text)
    assert res["verdict"] == "WARN"
    assert any("비표준 사건부호" in w for w in res["warnings"])


def test_cli_execution_with_temp_file(tmp_path):
    f = tmp_path / "draft.md"
    f.write_text("민법 제750조 손해배상. 대법원 2021다274214 판결.", encoding="utf-8")
    res = vlf.verify_legal_file(str(f))
    assert res["verdict"] == "PASS"
    assert "2021다274214" in res["cited_precedents"]


def test_provisional_remedy_and_family_codes_pass():
    text = (
        "채권자는 서울중앙지방법원 2024카단12345 가압류 결정 및 "
        "서울가정법원 2023느단67890 상속한정승인 심판, 수원회생법원 2023개회55555 결정을 원용합니다."
    )
    res = vlf.verify_legal_text(text)
    assert res["verdict"] == "PASS"
    assert len(res["warnings"]) == 0
    assert "2024카단12345" in res["cited_precedents"]
    assert "2023느단67890" in res["cited_precedents"]
    assert "2023개회55555" in res["cited_precedents"]


def test_statute_branch_articles_preserved_and_bounded():
    valid_text = "개인정보보호법 제76조의2 과징금 및 정보통신망법 제44조의7 불법정보 유통금지."
    res_valid = vlf.verify_legal_text(valid_text)
    assert res_valid["verdict"] == "PASS"
    assert "개인정보보호법 제76조의2" in res_valid["cited_statutes"]
    assert "정보통신망법 제44조의7" in res_valid["cited_statutes"]

    invalid_text = "개인정보보호법 제99조의2 위반."
    res_invalid = vlf.verify_legal_text(invalid_text)
    assert res_invalid["verdict"] == "FAIL"
    assert any("개인정보보호법" in e and "제99조의2" in e for e in res_invalid["errors"])


def test_specialized_courts_recognized():
    text = "헌법재판소 2020헌바123 결정 및 특허법원 2022허4567 판결."
    res = vlf.verify_legal_text(text)
    assert res["verdict"] == "PASS"
    assert len(res["errors"]) == 0
    assert len(res["warnings"]) == 0
    assert "2020헌바123" in res["cited_precedents"]
    assert "2022허4567" in res["cited_precedents"]


def test_legal_factuality_guard_target_file_key(tmp_path):
    import subprocess
    guard_script = SCRIPT_DIR / "legal_factuality_guard.mjs"
    bad_file = tmp_path / "소장_테스트.md"
    bad_file.write_text("피고는 민법 제1500조에 따라 원고에게 지급하라.", encoding="utf-8")

    # Pass TargetFile key as JSON payload
    payload = json.dumps({"TargetFile": str(bad_file), "CodeContent": "..."})
    proc = subprocess.run(
        ["node", str(guard_script)],
        input=payload,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    # Guard should catch the target file and fail-closed (exit code 1)
    assert proc.returncode == 1
    assert "민법" in proc.stderr or "LEGAL FACTUALITY GUARD" in proc.stderr


def test_flexible_spacing_statute_names_checked():
    # Spaced statute names (official spacing like 개인정보 보호법) must be caught
    text_pii = "피고는 개인정보 보호법 제100조를 위반하였다."
    res_pii = vlf.verify_legal_text(text_pii)
    assert res_pii["verdict"] == "FAIL"
    assert any("개인정보" in e and "제100조" in e for e in res_pii["errors"])

    text_labor = "근로 기준법 제120조에 기한 청구."
    res_labor = vlf.verify_legal_text(text_labor)
    assert res_labor["verdict"] == "FAIL"
    assert any("근로기준법" in e and "제120조" in e for e in res_labor["errors"])

    text_secret = "부정경쟁방지 및 영업비밀 보호에 관한 법률 제20조 위반."
    res_secret = vlf.verify_legal_text(text_secret)
    assert res_secret["verdict"] == "FAIL"
    assert any("부정경쟁방지" in e and "제20조" in e for e in res_secret["errors"])


def test_legal_factuality_guard_file_key(tmp_path):
    import subprocess
    guard_script = SCRIPT_DIR / "legal_factuality_guard.mjs"
    bad_file = tmp_path / "답변서_검토.md"
    bad_file.write_text("원고의 주장은 형사 소송법 제500조에 비추어 타당하지 않습니다.", encoding="utf-8")

    # Pass filename key as JSON payload
    payload = json.dumps({"filename": str(bad_file)})
    proc = subprocess.run(
        ["node", str(guard_script)],
        input=payload,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 1
    assert "형사소송법" in proc.stderr or "LEGAL FACTUALITY GUARD" in proc.stderr


def test_abolished_and_fabricated_courts_blocked():
    text1 = "서울민사지방법원 2021가단100 판결을 원용합니다."
    res1 = vlf.verify_legal_text(text1)
    assert res1["verdict"] == "FAIL"
    assert any("서울민사지방법원" in e and "법원 명칭 날조" in e for e in res1["errors"])

    text2 = "한국연방법원 2023가합500 소송 계속 중입니다."
    res2 = vlf.verify_legal_text(text2)
    assert res2["verdict"] == "FAIL"
    assert any("한국연방법원" in e and "법원 명칭 날조" in e for e in res2["errors"])


def test_evidence_tag_attribution_and_grounding():
    source_facts = "2024년 1월 16일 원고는 피고에게 금 10,000,000원을 무통장 송금하였다."

    # Matching quote passes
    draft_valid = (
        "<evidence>2024년 1월 16일 원고는 피고에게 금 10,000,000원을 무통장 송금하였다.</evidence>\n"
        "피고는 원고로부터 대여금을 수령하였습니다."
    )
    res_valid = vlf.verify_legal_text(draft_valid, source_text=source_facts)
    assert res_valid["verdict"] == "PASS"

    # Fabricated quote fails verbatim match
    draft_invalid = (
        "<evidence>2024년 5월 20일 피고가 전액 상환하겠다고 각서를 작성하였다.</evidence>\n"
        "피고는 채무를 승인하였습니다."
    )
    res_invalid = vlf.verify_legal_text(draft_invalid, source_text=source_facts)
    assert res_invalid["verdict"] == "FAIL"
    assert any("근거 인용 불일치" in e for e in res_invalid["errors"])

    # Empty evidence tag fails
    draft_empty = "<evidence>   </evidence>\n소장 내용."
    res_empty = vlf.verify_legal_text(draft_empty)
    assert res_empty["verdict"] == "FAIL"
    assert any("비어 있습니다" in e for e in res_empty["errors"])

    # Attributed evidence tag recognized
    draft_attr = (
        '<evidence source="bank_receipt.pdf">2024년 1월 16일 원고는 피고에게 금 10,000,000원을 무통장 송금하였다.</evidence>\n'
        '피고는 원고로부터 대여금을 수령하였습니다.'
    )
    res_attr = vlf.verify_legal_text(draft_attr, source_text=source_facts)
    assert res_attr["verdict"] == "PASS"

    # Evidence tag without source_text yields warning
    res_no_source = vlf.verify_legal_text(draft_valid, source_text=None)
    assert res_no_source["verdict"] == "WARN"
    assert any("대조할 원문(--source)이 지정되지 않았습니다" in w for w in res_no_source["warnings"])


def test_high_fidelity_mode_verifications():
    source_facts = "원고는 피고에게 대여금 일천만원을 지급하였고 변제기일은 2024년 12월 31일이다."

    # 1. High-fidelity fails without source
    draft = "<evidence>원고는 피고에게 대여금 일천만원을 지급하였고</evidence>\n대여금 청구."
    res_no_src = vlf.verify_legal_text(draft, source_text=None, high_fidelity=True)
    assert res_no_src["verdict"] == "FAIL"
    assert any("원문(--source)이 지정되지 않았습니다" in e for e in res_no_src["errors"])

    # 2. High-fidelity fails without evidence tag
    draft_no_ev = "원고는 피고에게 대여금 일천만원을 지급하였고 변제기일은 2024년 12월 31일이다."
    res_no_ev = vlf.verify_legal_text(draft_no_ev, source_text=source_facts, high_fidelity=True)
    assert res_no_ev["verdict"] == "FAIL"
    assert any("<evidence> 원문 인용 태그가 없습니다" in e for e in res_no_ev["errors"])

    # 3. High-fidelity passes with evidence tag and high morphological overlap
    draft_ok = (
        "<evidence>원고는 피고에게 대여금 일천만원을 지급하였고 변제기일은 2024년 12월 31일이다.</evidence>\n"
        "원고는 피고에게 대여금 일천만원 지급을 청구합니다."
    )
    res_ok = vlf.verify_legal_text(draft_ok, source_text=source_facts, high_fidelity=True)
    assert res_ok["verdict"] == "PASS"
    assert len(res_ok["errors"]) == 0


def test_cli_morph_grounding_and_high_fidelity(tmp_path):
    import subprocess
    vlf_script = SCRIPT_DIR / "verify_legal_factuality.py"

    src_file = tmp_path / "source.txt"
    src_file.write_text("원고와 피고는 차용증을 작성하고 금전을 대여하였다.", encoding="utf-8")

    draft_file = tmp_path / "draft.md"
    draft_file.write_text(
        "<evidence>원고와 피고는 차용증을 작성하고 금전을 대여하였다.</evidence>\n"
        "원고와 피고 사이의 차용증 작성 및 금전 대여 관계가 성립합니다.",
        encoding="utf-8",
    )

    # Run with --morph-grounding and --high-fidelity
    proc = subprocess.run(
        [sys.executable, str(vlf_script), str(draft_file), "--source", str(src_file), "--morph-grounding", "--high-fidelity", "--json"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["verdict"] == "PASS"
    assert len(data["errors"]) == 0


def test_high_fidelity_with_multi_level_and_bracketed_headings():
    source = "피고는 2024년 1월 1일 원고로부터 1000만원을 빌렸으나 변제하지 않았다."

    # 1. H3 format with numbering (### 1. 청구원인)
    draft_h3 = (
        "# 소 장\n"
        "원 고: 홍길동\n피 고: 김철수\n\n"
        "### 1. 청구원인\n"
        "피고는 2024년 1월 1일 원고로부터 1000만원을 빌렸으나 이를 변제하지 아니하였습니다.\n\n"
        "### 2. 입증방법\n"
        "<evidence>피고는 2024년 1월 1일 원고로부터 1000만원을 빌렸으나 변제하지 않았다.</evidence>\n"
        "본 문서는 변호사 검토를 거쳐야 합니다.\n"
    )
    res_h3 = vlf.verify_legal_text(draft_h3, source_text=source, high_fidelity=True)
    assert res_h3["verdict"] == "PASS"
    assert len(res_h3["errors"]) == 0

    # 2. Bracketed format (【청구원인】)
    draft_bracket = (
        "【당사자의 표시】\n원고 홍길동, 피고 김철수\n\n"
        "【청구원인】\n"
        "피고는 2024년 1월 1일 원고로부터 1000만원을 빌렸으나 변제하지 않았습니다.\n\n"
        "【입증방법】\n"
        "<evidence>피고는 2024년 1월 1일 원고로부터 1000만원을 빌렸으나 변제하지 않았다.</evidence>\n"
        "본 문서는 AI 생성물이며 변호사 확인이 필요합니다.\n"
    )
    res_bracket = vlf.verify_legal_text(draft_bracket, source_text=source, high_fidelity=True)
    assert res_bracket["verdict"] == "PASS"
    assert len(res_bracket["errors"]) == 0


def test_fabricated_government_agency_blocked():
    text = "본 사건은 사이버수사처 및 디지털포렌식청, 개인정보보호청의 조사 결과에 근거합니다."
    res = vlf.verify_legal_text(text)
    assert res["verdict"] == "FAIL"
    assert any("사이버수사처" in e for e in res["errors"])
    assert any("디지털포렌식청" in e for e in res["errors"])
    assert any("개인정보보호청" in e for e in res["errors"])


def test_obsolete_government_ministry_blocked():
    text = "정보통신부 고시 및 문화공보부 훈령, 재정경제부 인가를 근거로 합니다."
    res = vlf.verify_legal_text(text)
    assert res["verdict"] == "FAIL"
    assert any("정보통신부" in e and "2008년 폐지" in e for e in res["errors"])
    assert any("문화공보부" in e and "1990년 폐지" in e for e in res["errors"])
    assert any("재정경제부" in e and "기획재정부" in e for e in res["errors"])


def test_valid_current_government_ministry_passes():
    text = "과학기술정보통신부 고시 및 문화체육관광부 훈령, 고용노동부 지침에 따릅니다."
    res = vlf.verify_legal_text(text)
    assert res["verdict"] == "PASS"
    assert len(res["errors"]) == 0


def test_claim_ledger_integration_in_legal_file_verifier(tmp_path):
    ledger_file = tmp_path / "claim-ledger.md"
    ledger_file.write_text(
        "| Claim | Risk Level | Sources (2+ Domains) | Counter-Search Result | Primary Source | Status |\n"
        "|---|---|---|---|---|:---:|\n"
        "| [Claim 1] 민법 제750조 불법행위 성립 | High | https://law.go.kr, https://scourt.go.kr | 반대 판례 없음 | https://law.go.kr | `VERIFIED` |\n"
        "| [Claim 2] 위법성 조각사유 존재 | High | https://law.go.kr | 반증 확인 | https://law.go.kr | `REFUTED` |\n",
        encoding="utf-8",
    )

    draft_pass = tmp_path / "draft_pass.md"
    draft_pass.write_text(
        "# 준비서면\n원고는 [Claim 1]에 기하여 청구합니다. 민법 제750조. 변호사 검토 필요.\n",
        encoding="utf-8",
    )
    res_pass = vlf.verify_legal_file(str(draft_pass), claim_ledger_path=str(ledger_file))
    assert res_pass["verdict"] == "PASS"
    assert len(res_pass["errors"]) == 0

    draft_fail = tmp_path / "draft_fail.md"
    draft_fail.write_text(
        "# 준비서면\n피고는 [Claim 2]에 기하여 항변합니다. 변호사 검토 필요.\n",
        encoding="utf-8",
    )
    res_fail = vlf.verify_legal_file(str(draft_fail), claim_ledger_path=str(ledger_file))
    assert res_fail["verdict"] == "FAIL"
    assert any("Claim Ledger 위반" in e for e in res_fail["errors"])


def test_fabricated_court_with_korean_particles_blocked():
    text1 = "서울민사지방법원은 원고의 청구를 인용하였다."
    res1 = vlf.verify_legal_text(text1)
    assert res1["verdict"] == "FAIL"
    assert any("서울민사지방법원" in e and "법원 명칭 날조" in e for e in res1["errors"])

    text2 = "한국연방법원에 소장을 제출하였습니다."
    res2 = vlf.verify_legal_text(text2)
    assert res2["verdict"] == "FAIL"
    assert any("한국연방법원" in e and "법원 명칭 날조" in e for e in res2["errors"])


def test_fabricated_agency_with_korean_particles_blocked():
    text1 = "사이버수사처와 공조하여 압수수색을 진행하였다."
    res1 = vlf.verify_legal_text(text1)
    assert res1["verdict"] == "FAIL"
    assert any("사이버수사처" in e for e in res1["errors"])

    text2 = "디지털포렌식청과 회의를 가졌습니다."
    res2 = vlf.verify_legal_text(text2)
    assert res2["verdict"] == "FAIL"
    assert any("디지털포렌식청" in e for e in res2["errors"])


def test_obsolete_ministry_with_successor_annotation_or_allow_historical():
    # With successor annotation
    text_annotated = "정보통신부(현 과학기술정보통신부) 2005년 고시를 근거로 합니다."
    res_annotated = vlf.verify_legal_text(text_annotated)
    assert res_annotated["verdict"] == "WARN"
    assert len(res_annotated["errors"]) == 0
    assert any("역사적 명칭 인용" in w for w in res_annotated["warnings"])

    # With allow_historical=True
    text_hist = "정보통신부 2005년 고시를 근거로 합니다."
    res_hist = vlf.verify_legal_text(text_hist, allow_historical=True)
    assert res_hist["verdict"] == "WARN"
    assert len(res_hist["errors"]) == 0
    assert any("역사적 명칭 인용" in w for w in res_hist["warnings"])


def test_generate_legal_draft_with_claim_ledger(tmp_path):
    import subprocess
    script = SCRIPT_DIR / "generate_legal_draft.py"

    ledger_file = tmp_path / "claim-ledger.md"
    ledger_file.write_text(
        "| Claim | Risk Level | Sources (2+ Domains) | Counter-Search Result | Primary Source | Status |\n"
        "|---|---|---|---|---|:---:|\n"
        "| [Claim 1] 대여금 반환 청구 성립 | High | https://law.go.kr, https://scourt.go.kr | 반대 판례 없음 | https://law.go.kr | `VERIFIED` |\n",
        encoding="utf-8",
    )

    draft_input = {
        "type": "소장",
        "case_info": {"court": "서울중앙지방법원", "plaintiff": "홍길동", "defendant": "김철수"},
        "claims": ["피고는 원고에게 금 10,000,000원을 지급하라."],
        "facts": ["원고는 피고에게 금전을 대여하였다 [Claim 1]."],
        "evidence_list": [{"label": "갑 제1호증", "title": "차용증"}],
    }
    input_file = tmp_path / "draft_input.json"
    input_file.write_text(json.dumps(draft_input, ensure_ascii=False), encoding="utf-8")

    out_file = tmp_path / "out_draft.md"
    proc = subprocess.run(
        [sys.executable, str(script), "--input-json", str(input_file), "-o", str(out_file), "--claim-ledger", str(ledger_file)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    assert out_file.is_file()
    assert "[Claim 1]" in out_file.read_text(encoding="utf-8")


def test_fabricated_historical_events_blocked():
    # 4차 갑오개혁, 3차 동학농민운동, 제2차 을사조약, 제3차 임진왜란 등 날조 차단
    res1 = vlf.verify_legal_text("갑오개혁 4차 개혁안을 바탕으로 제도를 개편하였다.")
    assert res1["verdict"] == "FAIL"
    assert any("갑오개혁 4차" in e and "한국사 사건/조약 날조" in e for e in res1["errors"])

    res2 = vlf.verify_legal_text("제4차 갑오개혁 당시 수립된 법률이다.")
    assert res2["verdict"] == "FAIL"
    assert any("한국사 사건/조약 날조" in e for e in res2["errors"])

    res3 = vlf.verify_legal_text("제2차 을사조약 체결에 따라 외교권이 제한되었다.")
    assert res3["verdict"] == "FAIL"
    assert any("제2차 을사조약" in e and "한국사 사건/조약 날조" in e for e in res3["errors"])

    res4 = vlf.verify_legal_text("3차 동학농민운동 봉기 이후에 체결되었다.")
    assert res4["verdict"] == "FAIL"
    assert any("3차 동학농민운동" in e and "한국사 사건/조약 날조" in e for e in res4["errors"])

    res5 = vlf.verify_legal_text("강화도조약 2차 및 2차 삼일운동 관련 사료이다.")
    assert res5["verdict"] == "FAIL"
    assert any("강화도조약 2차" in e or "2차 삼일운동" in e for e in res5["errors"])

    # Hanja numerals, Sino-Korean prefix 第, and single-occurrence treaties/reforms (Section 5.1 #3)
    res6 = vlf.verify_legal_text("第4次 甲午改革 및 제四차 갑오개혁 사료를 분석한다.")
    assert res6["verdict"] == "FAIL"
    assert any("한국사 사건/조약 날조" in e for e in res6["errors"])

    res7 = vlf.verify_legal_text("제2차 을미개혁 및 제2차 한일병합조약 관련 기록이다.")
    assert res7["verdict"] == "FAIL"
    assert any("한국사 사건/조약 날조" in e for e in res7["errors"])

    res8 = vlf.verify_legal_text("제2차 조미수호통상조약 및 제2차 4·19 혁명 기념 문서이다.")
    assert res8["verdict"] == "FAIL"
    assert any("한국사 사건/조약 날조" in e for e in res8["errors"])


def test_valid_historical_events_pass():
    # 1차~3차 갑오개혁, 1차~2차 동학농민운동, 을사조약 체결 등 정상 역사 서술 통과
    valid_text = (
        "제1차 갑오개혁, 2차 갑오개혁, 3차 갑오개혁(을미개혁) 및 동학농민운동 1차 봉기, "
        "을사조약 체결, 조미수호통상조약 및 4·19 혁명 역사를 검토한다."
    )
    res = vlf.verify_legal_text(valid_text)
    assert res["verdict"] == "PASS"
    assert len(res["errors"]) == 0


def test_impossible_judicial_procedures_blocked():
    # 대검찰청의 약식명령 청구, 경찰의 영장 직접 청구, 헌법재판소의 징역형 선고 등 실정법상 불가 절차 차단
    res1 = vlf.verify_legal_text("대검찰청의 약식명령 청구에 따라 벌금형이 고지되었다.")
    assert res1["verdict"] == "FAIL"
    assert any("대검찰청의 약식명령 청구" in e and "불가능한 사법절차 날조" in e for e in res1["errors"])

    res2 = vlf.verify_legal_text("고등검찰청의 약식기소 처분을 확인하였다.")
    assert res2["verdict"] == "FAIL"
    assert any("고등검찰청의 약식기소" in e for e in res2["errors"])

    res3 = vlf.verify_legal_text("사법경찰관이 법원에 구속영장을 직접 청구하였다.")
    assert res3["verdict"] == "FAIL"
    assert any("구속영장을 직접 청구" in e or "구속영장" in e for e in res3["errors"])

    res4 = vlf.verify_legal_text("경찰은 피의자를 법원에 직접 기소하였다.")
    assert res4["verdict"] == "FAIL"
    assert any("경찰" in e and "기소" in e for e in res4["errors"])

    res5 = vlf.verify_legal_text("헌법재판소는 피고인에게 징역 2년을 선고하였다.")
    assert res5["verdict"] == "FAIL"
    assert any("헌법재판소" in e and "징역" in e for e in res5["errors"])

    res6 = vlf.verify_legal_text("민사소송에서 피고에게 징역 1년을 선고하였다.")
    assert res6["verdict"] == "FAIL"
    assert any("민사소송" in e and "징역" in e for e in res6["errors"])

    res7 = vlf.verify_legal_text("형사소송의 원고는 합의금을 요구하였다.")
    assert res7["verdict"] == "FAIL"
    assert any("형사소송의 원고" in e for e in res7["errors"])

    # Long compound Korean sentences with subordinate clauses (> 25 characters)
    res8 = vlf.verify_legal_text("대검찰청 특별수사본부는 이번 사건과 관련하여 피의자들에 대해 약식명령을 청구하였다.")
    assert res8["verdict"] == "FAIL"
    assert any("불가능한 사법절차 날조" in e for e in res8["errors"])

    res9 = vlf.verify_legal_text("경찰은 광범위한 압수수색 및 디지털 포렌식 분석을 완료한 후 관할 법원에 직접 영장을 청구하였다.")
    assert res9["verdict"] == "FAIL"
    assert any("불가능한 사법절차 날조" in e for e in res9["errors"])

    res10 = vlf.verify_legal_text("헌법재판소는 장기간의 심리를 거쳐 마침내 피고인에게 중형인 징역 2년을 선고하였다.")
    assert res10["verdict"] == "FAIL"
    assert any("불가능한 사법절차 날조" in e for e in res10["errors"])


def test_valid_judicial_procedures_pass():
    # 관할 지검 검사의 약식명령 청구, 경찰의 영장 신청, 대검찰청의 합법적 지휘, 민사소송의 원고 등 정상 절차 통과
    valid_proc = (
        "서울중앙지방검찰청 검사는 피의자에 대하여 벌금 300만원의 약식명령을 청구하였다. "
        "사법경찰관은 검사에게 구속영장을 신청하였고, 경찰은 기소의견으로 사건을 송치하였다. "
        "대검찰청은 관할 지방검찰청에 약식명령 청구를 검토하도록 지시하였다. "
        "민사소송의 원고는 손해배상을 청구하였다."
    )
    res = vlf.verify_legal_text(valid_proc)
    assert res["verdict"] == "PASS"
    assert len(res["errors"]) == 0


def test_academic_citation_hallucinations_blocked():
    # Section 5.1 #3: Fabricated academic journals and future publication years
    res1 = vlf.verify_legal_text("대한인공지능법학회지 제10권에 게재된 논문을 참조한다.")
    assert res1["verdict"] == "FAIL"
    assert any("학술논문/학술지 날조" in e and "대한인공지능법학회지" in e for e in res1["errors"])

    res2 = vlf.verify_legal_text("한국사이버포렌식학회논문집 수록 연구 결과를 바탕으로 한다.")
    assert res2["verdict"] == "FAIL"
    assert any("학술논문/학술지 날조" in e and "한국사이버포렌식학회논문집" in e for e in res2["errors"])

    res3 = vlf.verify_legal_text("홍길동 교수의 2099년 학술지 논문에 따르면 인공지능 책임이 인정된다.")
    assert res3["verdict"] == "FAIL"
    assert any("미래 연도 학술 논문" in e for e in res3["errors"])

    # Valid academic citations from past/current years must pass
    res_valid = vlf.verify_legal_text("「형사법연구」 제32권(2020년)에 게재된 학술 논문을 참조한다.")
    assert res_valid["verdict"] == "PASS"
    assert len(res_valid["errors"]) == 0


def test_run_legal_health_check_returns_100_score():
    health = vlf.run_legal_health_check()
    assert health["status"] == "PASS"
    assert health["score"] == 100
    assert health["passed"] == health["total"]
    assert len(health["details"]) == health["total"]


def test_cli_health_check():
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "verify_legal_factuality.py"), "--health-check", "--json"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["status"] == "PASS"
    assert data["score"] == 100


def test_strict_flag_fails_on_warnings(tmp_path):
    import subprocess
    warn_file = tmp_path / "warn_doc.md"
    # Unregistered statute emits a warning
    warn_file.write_text("피고는 우주항공보안법 제12조를 위반하였다.", encoding="utf-8")

    # Without --strict: warnings do not fail the process (exit 0)
    proc_normal = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "verify_legal_factuality.py"), str(warn_file)],
        capture_output=True,
        encoding="utf-8",
    )
    assert proc_normal.returncode == 0

    # With --strict: warnings trigger exit code 1
    proc_strict = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "verify_legal_factuality.py"), str(warn_file), "--strict"],
        capture_output=True,
        encoding="utf-8",
    )
    assert proc_strict.returncode == 1
    assert "Legal warnings" in proc_strict.stderr


def test_statute_loaders_resilience_and_warnings(tmp_path):
    # 1. Missing file resilience
    missing_file = tmp_path / "nonexistent.json"
    bounds = vlf._load_statute_bounds(custom_path=missing_file)
    assert bounds["민법"] == 1118
    assert any("파일 부재" in w for w in vlf._LOAD_WARNINGS)

    subarticles = vlf._load_statute_subarticles(custom_path=missing_file)
    assert subarticles["민법"] == 2
    assert subarticles["도로교통법"] == 24

    # 2. Corrupted JSON resilience
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("{broken json", encoding="utf-8")
    bounds_corrupt = vlf._load_statute_bounds(custom_path=corrupt_file)
    assert bounds_corrupt["민법"] == 1118
    assert any("파손" in w for w in vlf._LOAD_WARNINGS)

    # 3. Valid real file loading
    real_subs = vlf._load_statute_subarticles()
    assert real_subs["개인정보보호법"] == 5
    assert real_subs["정보통신망법"] == 7
    assert real_subs["형사소송법"] == 6


def test_mcp_matcher_validation(tmp_path):
    # 1. match_mcp_statute_cache unit test
    mcp_cache = {"statute": "우주항공보안법", "articles": ["제12조", "제13조"]}
    assert vlf.match_mcp_statute_cache("우주항공보안법 제12조", mcp_cache) is True
    assert vlf.match_mcp_statute_cache("우주항공보안법 제99조", mcp_cache) is False
    # 1a. 회귀: 서로 다른 레코드의 법명+조문을 조합(교차 곱)해서 통과시키지 않는다
    cross = [{"law": "가상법", "article": "제1조"}, {"law": "다른법", "article": "제99조"}]
    assert vlf.match_mcp_statute_cache("가상법 제99조", cross) is False
    # 1b. 회귀: 파손된 캐시(파싱 불가 문자열)는 거짓 검증 근거가 되지 않는다
    assert vlf.match_mcp_statute_cache("우주항공보안법 제12조", "{broken json") is False
    # 1c. 같은 레코드(객체) 안에서 법명+조문이 함께 있어야 한다
    assert vlf.match_mcp_statute_cache("우주항공보안법 제13조", {"results": [mcp_cache]}) is True
    assert vlf.match_mcp_statute_cache("우주항공보안법 제12조", {"statute": "우주항공보안법"}) is False
    # 1d. 회귀: 전역 부분열 매칭은 더 이상 근거가 아니다
    assert vlf.match_mcp_statute_cache("우주항공보안법 제12조", "우주항공보안법 제12조 문자열만 있음") is False

    # 1e. korean-law-mcp 실제 응답 형태: statute_name 키 + dict형 articles
    mcp_all = {"ok": True, "statute_name": "우주항공보안법",
               "articles": {"12": "제12조 (의무) ...", "13": "제13조 ..."},
               "grounding_status": "CACHED_EXCERPT_UNVERIFIED"}
    assert vlf.match_mcp_statute_cache("우주항공보안법 제12조", mcp_all) is True
    assert vlf.match_mcp_statute_cache("우주항공보안법 제99조", mcp_all) is False
    # 단일 조문 응답(article_number)과 키워드 검색 응답(matches[])
    assert vlf.match_mcp_statute_cache(
        "우주항공보안법 제12조",
        {"ok": True, "statute_name": "우주항공보안법", "article_number": "12", "text": "..."}) is True
    assert vlf.match_mcp_statute_cache(
        "우주항공보안법 제13조",
        {"ok": True, "statute_name": "우주항공보안법",
         "matches": [{"article_number": "13", "text": "..."}]}) is True
    # provenance는 결과에 노출된다(발췌 캐시 = 보조 대조)
    res = vlf.verify_legal_text("피고는 우주항공보안법 제12조를 위반하였다.", mcp_cache=mcp_all)
    assert res["cache_provenance"] == {"grounding_status": "CACHED_EXCERPT_UNVERIFIED"}

    # 2. verify_legal_text with mcp_cache suppresses ungrounded warnings
    text = "피고는 우주항공보안법 제12조를 위반하였다."
    res_without = vlf.verify_legal_text(text)
    assert any("우주항공보안법 제12조" in w for w in res_without["warnings"])

    res_with = vlf.verify_legal_text(text, mcp_cache=mcp_cache)
    assert not any("우주항공보안법 제12조" in w for w in res_with["warnings"])

    # 3. CLI --mcp-cache integration
    cache_file = tmp_path / "mcp_cache.json"
    cache_file.write_text(json.dumps(mcp_cache, ensure_ascii=False), encoding="utf-8")
    doc_file = tmp_path / "doc.md"
    doc_file.write_text(text, encoding="utf-8")

    import subprocess
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "verify_legal_factuality.py"), str(doc_file), "--mcp-cache", str(cache_file), "--strict"],
        capture_output=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0


def test_statute_loader_corruption_warns_to_stderr(tmp_path, capsys):
    corrupt = tmp_path / "bounds_corrupt.json"
    corrupt.write_text("{broken json", encoding="utf-8")
    bounds = vlf._load_statute_bounds(custom_path=corrupt)
    assert bounds["민법"] == 1118
    captured = capsys.readouterr()
    assert "WARN" in captured.err and "파손" in captured.err










