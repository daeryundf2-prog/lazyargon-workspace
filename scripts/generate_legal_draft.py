#!/usr/bin/env python3
"""generate_legal_draft.py - 대법원 전자소송 규격 법률 문서 초안 생성기.

사실관계 메모와 입증자료(증거) 목록을 입력받아 소장·준비서면·고소장·내용증명
초안을 마크다운으로 생성한다. 본문 주장 뒤에 증거 자동 인용(입증방법 결합)이
붙고, 모든 산출물에는 "변호사 검토 전 제출 금지" 고지가 강제로 들어간다.

입력 JSON 구조:
{
  "type": "소장",                      // 소장|준비서면|고소장|내용증명|업무보고서
  "case_info": {
    "court": "서울중앙지방법원",
    "case_number": "2024가합12345",   // 소장은 빈 값(제출 시 배호)
    "plaintiff": "홍길동",
    "defendant": "주식회사 XXX"
  },
  "claims": ["대여금 원금 10,000,000원 및 이에 대한 지연손해금"],
  "facts": [
    {"heading": "1. 대여 관계의 성립",
     "paragraphs": ["... 2024년 1월 16일 ... 금 10,000,000원을 빌렸다. ... 갑 제1호증 ..."],
     "evidence": []}                  // 명시 지정 없으면 본문에서 라벨 자동 탐지
  ],
  "evidence_list": [
    {"label": "갑 제1호증", "title": "차용증"}
  ]
}

Exit code: 0 생성 완료 / 2 입력 오류
CLI:
    python scripts/generate_legal_draft.py --input-json draft.json -o 소장_초안.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

try:
    from verify_legal_factuality import verify_legal_text
except ImportError:
    try:
        from scripts.verify_legal_factuality import verify_legal_text
    except ImportError:
        verify_legal_text = None

DRAFT_TYPES = ("소장", "준비서면", "고소장", "내용증명", "업무보고서")

DISCLAIMER = (
    "> ⚠️ **본 문서는 AI 생성 초안입니다. 변호사의 검토·수정 없이 법원이나 "
    "상대방에게 제출하지 마십시오.** 사실관계·법률 근거·청구 금액의 정확성은 "
    "제출자가 책임집니다."
)

# 본문에서 증거 라벨 자동 탐지: 갑/을/병 제N호증, 호증의 m 까지 지원
_LABEL_RE = re.compile(r"(갑|을|병)\s*제\s*(\d+)\s*호증(?:\s*의\s*(\d+))?")


def _norm_label(m: re.Match) -> str:
    """'갑제1호증의2'처럼 붙어 쓴 라벨을 표준형 '갑 제1호증의 2'로 통일."""
    base = f"{m.group(1)} 제{m.group(2)}호증"
    if m.group(3):
        return f"{base}의 {m.group(3)}"
    return base


def build_evidence_index(evidence_list: list[dict]) -> dict[str, str]:
    """라벨(공백 변형 허용) → 서증명 조회표. '갑제1호증'·'갑 제1호증' 모두 수용."""
    index: dict[str, str] = {}
    for item in evidence_list or []:
        label = str(item.get("label", "")).strip()
        if not label:
            continue
        title = str(item.get("title", "")).strip()
        norm = _norm_label(_LABEL_RE.search(label)) if _LABEL_RE.search(label) else label.replace(" ", "")
        index[norm] = title or "(서증명 미기재)"
        index[label.replace(" ", "")] = title or "(서증명 미기재)"
    return index


def find_cited_labels(text: str) -> list[str]:
    """본문에 등장하는 증거 라벨을 표준형으로, 출현 순서대로 중복 없이 반환."""
    seen: list[str] = []
    for m in _LABEL_RE.finditer(text):
        label = _norm_label(m)
        if label not in seen:
            seen.append(label)
    return seen


def method_line(text: str, explicit: list[str], index: dict[str, str]) -> str:
    """문단 뒤에 붙일 입증방법 문장. 명시 지정과 본문 자동 탐지를 합친다."""
    labels: list[str] = []
    for label in list(explicit) + find_cited_labels(text):
        label = _norm_label(_LABEL_RE.search(label)) if _LABEL_RE.search(label) else label
        if label not in labels:
            labels.append(label)
    if not labels:
        return ""
    parts = []
    for label in labels:
        # 서증명 미기재는 그대로 보여야 사람이 채우게 된다 — 조용히 숨기지 않는다.
        title = index.get(label) or index.get(label.replace(" ", "")) or "(서증명 미기재)"
        parts.append(f"{label}, {title}")
    return f"*입증방법: {'; '.join(parts)}*"


def _party_header(case_info: dict) -> list[str]:
    court = case_info.get("court", "관할 법원")
    case_number = case_info.get("case_number") or "20XX다XXXXXX"
    lines = [f"**{court}** 귀중\n", f"**사건번호:** {case_number}"]
    if case_info.get("plaintiff"):
        lines.append(f"**원고(또는 고소인):** {case_info['plaintiff']}")
    if case_info.get("defendant"):
        lines.append(f"**피고(또는 피고소인):** {case_info['defendant']}")
    return lines


def _facts_section(facts: list[dict | str], index: dict[str, str], strict_evidence: bool = False) -> list[str]:
    lines: list[str] = []
    for fact in facts:
        if isinstance(fact, str):
            heading = ""
            paragraphs = [fact]
            body = fact
            explicit_evidence = []
        else:
            heading = fact.get("heading") or ""
            if heading:
                lines.append(f"### {heading}\n")
            paragraphs = fact.get("paragraphs") or ([fact["text"]] if fact.get("text") else [])
            body = "\n\n".join(str(t) for t in paragraphs)
            explicit_evidence = fact.get("evidence") or []
        lines.append(body)
        evidence_tags = re.findall(r"<evidence(?:\s+[^>]*)?>(.*?)</evidence>", body, re.DOTALL | re.IGNORECASE)
        line = method_line(body, explicit_evidence, index)
        if strict_evidence and not line and not evidence_tags:
            raise ValueError(
                f"Strict Evidence Gate: 사실관계 항목({heading or body[:20]}...)에 서증 또는 <evidence> 근거 인용이 없습니다."
            )
        if line:
            lines.append("")
            lines.append(line)
        lines.append("")
    return lines


def _evidence_appendix(evidence_list: list[dict]) -> list[str]:
    lines = ["## 증거 목록\n", "| 순번 | 서증부호 및 번호 | 서증명 |", "| :--: | :-- | :-- |"]
    for i, item in enumerate(evidence_list or [], 1):
        lines.append(f"| {i} | **{item.get('label', f'갑 제{i}호증')}** | {item.get('title', '')} |")
    return lines


def render_sojang(case_info: dict, claims: list[str], facts: list[dict], evidence_list: list[dict], strict_evidence: bool = False) -> list[str]:
    lines = _party_header(case_info) + ["", "# 소 장\n", "## 청구취지\n"]
    for i, claim in enumerate(claims, 1):
        lines.append(f"{i}. {claim}")
    lines += ["", "## 청구원인\n"]
    lines += _facts_section(facts, build_evidence_index(evidence_list), strict_evidence=strict_evidence)
    lines += ["## 법적 근거\n", "{민법 제388조(채무불이행), 제750조(불법행위) 등 청구원인 규정을 변호사 검토 후 기재}\n"]
    lines += ["## 결론\n", "구하건은, 피고는 원고에게 본 청구취지 기재 금원을 지급하라.\n"]
    lines += _evidence_appendix(evidence_list)
    return lines


def render_junbi(case_info: dict, claims: list[str], facts: list[dict], evidence_list: list[dict], strict_evidence: bool = False) -> list[str]:
    lines = _party_header(case_info) + ["", "# 준 비 서 면\n", "## 답변의 요지\n"]
    for i, claim in enumerate(claims, 1):
        lines.append(f"{i}. {claim}")
    lines += ["", "## 주장 및 항변\n"]
    lines += _facts_section(facts, build_evidence_index(evidence_list), strict_evidence=strict_evidence)
    lines += ["## 결론\n", "구하건은, 원고의 청구를 모두 기각한다.\n"]
    lines += _evidence_appendix(evidence_list)
    return lines


def render_goso(case_info: dict, claims: list[str], facts: list[dict], evidence_list: list[dict], strict_evidence: bool = False) -> list[str]:
    lines = _party_header(case_info) + ["", "# 고 소 장\n", "## 범죄사실\n"]
    lines += _facts_section(facts, build_evidence_index(evidence_list), strict_evidence=strict_evidence)
    lines += ["## 고소 이유\n"]
    if claims:
        for i, c in enumerate(claims, 1):
            lines.append(f"{i}. {c}")
        lines.append("")
    lines += ["## 고소 취지\n", "{피고소인에 대한 처벌을 구한다 — 구체적 처벌 수위·합의 여부는 변호사 검토 후 기재}\n"]
    lines += _evidence_appendix(evidence_list)
    return lines


def render_naeyong(case_info: dict, claims: list[str], facts: list[dict], evidence_list: list[dict], strict_evidence: bool = False) -> list[str]:
    lines = [f"**발신인:** {case_info.get('plaintiff', '(발신인)')}", f"**수신인:** {case_info.get('defendant', '(수신인)')}", "", "# 내 용 증 명\n", "## 경위\n"]
    lines += _facts_section(facts, build_evidence_index(evidence_list), strict_evidence=strict_evidence)
    lines += ["## 요구 사항\n"]
    for i, c in enumerate(claims, 1):
        lines.append(f"{i}. {c}")
    lines += ["", "위 사항에 대하여 본 내용증명 수령일로부터 14일 이내에 회신하여 주시기 바랍니다. 기한 내 회신이 없으면 법적 조치를 취할 수 있습니다.", ""]
    lines += _evidence_appendix(evidence_list)
    return lines


def _ministry_header(case_info: dict) -> list[str]:
    """행안부 공문서 상단 표기 (문서번호/시행일자/수신/제목)."""
    lines = []
    if case_info.get("doc_number"):
        lines.append(f"문서번호: {case_info['doc_number']}")
    lines.append(f"시행일자: {case_info.get('doc_date') or datetime.now().strftime('%Y-%m-%d')}")
    if case_info.get("recipient"):
        lines.append(f"수    신: {case_info['recipient']}")
    if case_info.get("reference"):
        lines.append(f"참    조: {case_info['reference']}")
    lines.append(f"제    목: {case_info.get('title') or '{보고서 제목}'}")
    return lines


_HANGUL_SEQ = "가나다라마바사아자차카타파하"


def render_ministry(case_info: dict, claims: list[str], facts: list[dict], evidence_list: list[dict], strict_evidence: bool = False) -> list[str]:
    """행안부 편람 표준 업무보고서 프리셋 (kordoc `ministry` 체계).

    상단 표기 + `1. → 가. → 1) → 가)` 위계. facts[].heading 은 `N.` 수준,
    paragraphs 는 `가.`/`나.`/`다.` 자동 순번, claims 는 보고 요지로 둔다.
    """
    lines = _ministry_header(case_info) + [""]
    if claims:
        lines.append("【보고 요지】")
        for i, c in enumerate(claims, 1):
            lines.append(f"{i}. {c}")
        lines.append("")
    for idx, fact in enumerate(facts, 1):
        if isinstance(fact, str):
            lines.append(f"{idx}. {fact}")
            continue
        heading = fact.get("heading") or f"항목 {idx}"
        lines.append(f"{idx}. {heading}")
        paragraphs = fact.get("paragraphs") or ([fact["text"]] if fact.get("text") else [])
        for pidx, para in enumerate(paragraphs):
            marker = _HANGUL_SEQ[pidx] if pidx < len(_HANGUL_SEQ) else f"가-{pidx + 1}"
            lines.append(f"   {marker}. {para}")
        body = "\n".join(str(t) for t in paragraphs)
        line = method_line(body, fact.get("evidence") or [], build_evidence_index(evidence_list))
        if strict_evidence and not line:
            raise ValueError(f"Strict Evidence Gate: 보고 항목({heading})에 근거 인용이 없습니다.")
        if line:
            lines.append(f"   {line}")
        lines.append("")
    if evidence_list:
        lines += ["붙임: 증거 목록 1부."]
        lines += _evidence_appendix(evidence_list)
    lines += ["", "끝."]
    return lines


RENDERERS = {
    "소장": render_sojang,
    "업무보고서": render_ministry,
    "준비서면": render_junbi,
    "고소장": render_goso,
    "내용증명": render_naeyong,
}


def generate(
    data: dict,
    verify: bool = True,
    strict: bool = False,
    strict_evidence: bool = False,
    source_text: str | None = None,
    morph_grounding: bool = False,
    high_fidelity: bool = False,
    claim_ledger: str | None = None,
) -> str:
    doc_type = str(data.get("type", "소장")).strip()
    if doc_type not in DRAFT_TYPES:
        raise ValueError(f"type은 {DRAFT_TYPES} 중 하나여야 합니다: {doc_type!r}")
    case_info = data.get("case_info") or {}
    claims = data.get("claims") or []
    facts = data.get("facts") or []
    evidence_list = data.get("evidence_list") or []

    eff_strict_evidence = strict_evidence or high_fidelity
    lines = [DISCLAIMER, ""]
    lines += RENDERERS[doc_type](case_info, claims, facts, evidence_list, strict_evidence=eff_strict_evidence)
    lines.append("---\n")
    lines.append(f"**작성(초안 생성)일자:** {datetime.now().strftime('%Y년 %m월 %d일')}")
    lines.append("**고지:** 본 초안은 AI 생성물입니다. 법률 용어·청구 원인 구성·증거 번호 체계는 변호사 검토가 필수입니다.")
    md = "\n".join(lines) + "\n"

    if verify and verify_legal_text is not None:
        audit = verify_legal_text(
            md,
            source_text=source_text,
            morph_grounding=morph_grounding,
            high_fidelity=high_fidelity,
            claim_ledger_path=claim_ledger,
        )
        if audit["errors"]:
            raise ValueError(f"법률 사실성 검증 실패: {'; '.join(audit['errors'])}")
        if (strict or high_fidelity) and audit["warnings"]:
            raise ValueError(f"법률 경고 발생 (--strict/--high-fidelity): {'; '.join(audit['warnings'])}")

    return md


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="전자소송 규격 법률 문서 초안 생성기 (소장/준비서면/고소장/내용증명/업무보고서)")
    p.add_argument("--input-json", "-i", required=True, help="초안 재료 JSON (type/case_info/claims/facts/evidence_list)")
    p.add_argument("--output", "-o", default="", help="출력 마크다운 경로 (미지정 시 stdout)")
    p.add_argument("--source", help="입증 원문 또는 사실관계 원본 파일 (.txt, .md, .json)")
    p.add_argument("--claim-ledger", help="Optional path to claim-ledger.md for Section 6 verification")
    p.add_argument("--verify", dest="verify", action="store_true", default=True, help="조문 및 판례 사실성 검증 수행 (기본 활성)")
    p.add_argument("--no-verify", dest="verify", action="store_false", help="사실성 검증 건너뛰기")
    p.add_argument("--strict", action="store_true", help="경고 발생 시에도 실패 처리")
    p.add_argument("--strict-evidence", action="store_true", help="사실관계 항목마다 명시적 서증 또는 <evidence> 태그 인용 강제")
    p.add_argument("--morph-grounding", action="store_true", help="Kiwi 형태소 기반 하이브리드 그라운딩 검증")
    p.add_argument("--high-fidelity", action="store_true", help="Local High-Fidelity gate: require --source and <evidence> tags plus morpheme overlap (no Vertex API)")
    args = p.parse_args(argv)

    if not os.path.isfile(args.input_json):
        print(f"error: 입력 JSON을 찾을 수 없습니다: {args.input_json}", file=sys.stderr)
        return 2

    if args.high_fidelity and not args.source:
        print("error: High-Fidelity 모드에는 --source 원문 파일 지정이 필수입니다.", file=sys.stderr)
        return 1
    try:
        with open(args.input_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"error: JSON 파싱 실패: {exc}", file=sys.stderr)
        return 2

    source_text = None
    if args.source:
        if not os.path.isfile(args.source):
            print(f"error: 소스 파일을 찾을 수 없습니다: {args.source}", file=sys.stderr)
            return 2
        try:
            with open(args.source, "r", encoding="utf-8") as f:
                source_text = f.read()
        except UnicodeDecodeError:
            with open(args.source, "r", encoding="utf-8-sig", errors="replace") as f:
                source_text = f.read()

    try:
        md = generate(
            data,
            verify=args.verify,
            strict=args.strict,
            strict_evidence=args.strict_evidence,
            source_text=source_text,
            morph_grounding=args.morph_grounding,
            high_fidelity=args.high_fidelity,
            claim_ledger=args.claim_ledger,
        )
    except ValueError as exc:
        msg = str(exc)
        if (
            "법률 사실성 검증 실패" in msg
            or "Legal Factuality Verification Failed" in msg
            or "법률 경고 발생" in msg
            or "Legal Factuality Strict Gate Failed" in msg
            or "Strict Evidence Gate" in msg
        ):
            print(f"[FAIL] {msg}", file=sys.stderr)
            print("error: 허위 조문, 날조된 판례 또는 무근거 사실관계가 포함되어 초안 생성을 차단합니다.", file=sys.stderr)
            return 1
        print(f"error: {msg}", file=sys.stderr)
        return 2

    if args.verify and verify_legal_text is not None and not args.strict:
        audit = verify_legal_text(md)
        for w in audit["warnings"]:
            print(f"[WARN] {w}", file=sys.stderr)

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"[OK] 초안 생성: {args.output}")
    else:
        print(md)
    return 0


# ── 콘솔 하드닝 (#84) ───────────────────────────────────────────────
import os as _os  # noqa: E402
import sys as _sys  # noqa: E402

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import console as _console  # noqa: E402

if __name__ == "__main__":
    _console.force_utf8_console()
    raise SystemExit(main())
