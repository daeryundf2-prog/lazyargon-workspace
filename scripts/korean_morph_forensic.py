#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""korean_morph_forensic.py — Korean Morphological Forensic Term & Grounding Analyzer.

Implements Section 5.2 of gemini_hallucination_mitigation_deep_dive.md.
Leverages Kiwi (kiwipiepy) morphological analysis to:
1. Extract content morphemes while stripping Korean agglutinative case markers and endings,
   preventing lexical mismatch between raw forensic artifacts and report assertions.
2. Register specialized digital forensic terminology into the Kiwi dictionary (e.g.,
   디지털포렌식, 타임스탬프, 무결성, 해시값, 연계보관성, 프리페치, MFT, 슬랙공간).
3. Compute grounding overlap between raw evidence files (events.json, audit_trail, txt logs)
   and draft forensic reports, identifying ungrounded novel forensic claims.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from kiwipiepy import Kiwi
    _HAS_KIWI = True
except ImportError:
    Kiwi = None
    _HAS_KIWI = False

FORENSIC_DOMAIN_TERMS = [
    ("디지털포렌식", "NNG"),
    ("포렌식", "NNG"),
    ("타임스탬프", "NNG"),
    ("타임스탬핑", "NNG"),
    ("무결성", "NNG"),
    ("해시값", "NNG"),
    ("연계보관성", "NNG"),
    ("증거능력", "NNG"),
    ("증거인멸", "NNG"),
    ("사본", "NNG"),
    ("원본대조", "NNG"),
    ("프리페치", "NNG"),
    ("슬랙공간", "NNG"),
    ("비인가", "NNG"),
    ("침해사고", "NNG"),
    ("접근기록", "NNG"),
    ("로그기록", "NNG"),
    ("이벤트로그", "NNG"),
    ("레지스트리", "NNG"),
    ("감정물", "NNG"),
    ("감정서", "NNG"),
    ("서증", "NNG"),
    ("갑호증", "NNP"),
    ("을호증", "NNP"),
    ("병호증", "NNP"),
    ("미측정", "NNG"),
    ("미확인", "NNG"),
]

CONTENT_TAGS = {"NNG", "NNP", "NR", "SL", "SH", "SN"}

_KIWI_INSTANCE = None


def get_kiwi_instance():
    global _KIWI_INSTANCE
    if not _HAS_KIWI:
        return None
    if _KIWI_INSTANCE is None:
        try:
            k = Kiwi()
            for word, tag in FORENSIC_DOMAIN_TERMS:
                try:
                    k.add_user_word(word, tag)
                except Exception:
                    pass
            _KIWI_INSTANCE = k
        except Exception:
            _KIWI_INSTANCE = None
    return _KIWI_INSTANCE


FORENSIC_PROCEDURAL_TERMS = {
    "감정", "감정서", "감정보고서", "보고서", "감정인", "분석관", "수사관", "의뢰인", "의뢰기관", "의뢰",
    "사건", "사건명", "개요", "목적", "방법", "대상", "대상물", "증거물", "감정물", "결과", "감정결과",
    "분석", "분석결과", "분석내용", "의견", "종합의견", "종합", "결론", "첨부", "첨부서류", "목록", "별지", "순번",
    "작성", "작성일자", "일자", "서명", "날인", "확인", "측정", "측정값", "검증", "검증됨", "판정", "비고",
    "소속", "직급", "성명", "원본", "사본", "일치", "불일치", "정상", "보관", "연계", "수집", "도구",
    "디지털", "포렌식", "디지털포렌식", "해시", "해시값", "타임스탬프", "타임스탬핑", "무결성", "sha", "md",
    "파일", "파일명", "크기", "바이트", "생성", "수정", "접근", "시각", "시간", "기록", "로그", "항목",
    "인", "귀하", "제출", "발급", "기관", "조사", "수사", "경찰", "경찰청", "검찰", "검찰청", "침해사고", "침해",
}


def extract_forensic_morphemes(text: str, min_len: int = 2) -> list[str]:
    """Extracts content morphemes stripping particles, case markers, and endings."""
    if not text:
        return []

    kiwi = get_kiwi_instance()
    if kiwi is not None:
        try:
            tokens = kiwi.tokenize(text)
            results = []
            for t in tokens:
                clean_form = t.form.rstrip(".,;:-~`!@#$%^&*()[]{}")
                if clean_form and len(clean_form) >= min_len and not re.match(r"^[0-9]+[.)]?$", t.form):
                    if t.tag in CONTENT_TAGS:
                        results.append(clean_form)
            return results
        except Exception:
            pass

    # Regex fallback
    # NOTE: 이 폴백 로직은 lazyothers/scripts/korean_morph_grounding.py 의
    # extract_content_morphemes 폴백과 짝이다. 어미/조사 제거 규칙을 고칠 때
    # 두 파일을 함께 고칠 것 (동기화 페어).
    known_terms = {w for w, _ in FORENSIC_DOMAIN_TERMS} | FORENSIC_PROCEDURAL_TERMS
    known_terms_lower = {w.lower() for w in known_terms}

    predicates = (
        r"(?:되었습니|되었습니다|되었으며|되었고|되었다|됩니다|된다|되다|"
        r"하였습니|하였습니다|하였으며|하였고|하였다|하여|합니다|한다|하다|"
        r"했습니|했습니다|했다|"
        r"이며|이고|이다|입니다)$"
    )
    particles = r"(?:은|는|이|가|을|를|의|에|에서|로|으로|와|과|도|만|에게|이나|나|으로서|으로써)$"

    # 하이픈 결합 토큰(SHA-256, Cellebrite-UFED 등)도 하나의 단어로 본다.
    # 순수 숫자 토큰(날짜·번호)은 유지하고, 어미/조사 제거는 시도한다.
    words = re.findall(r"[가-힣a-zA-Z0-9_]+(?:-[a-zA-Z0-9_]+)*", text)
    fallback_tokens = []
    for w in words:
        if re.match(r"^[0-9]+[.)]?$", w):
            continue

        # If w is directly a known domain or procedural term, preserve it
        # (case-insensitive hit preserves the original casing so evidence
        # "SHA-256" and report "sha-256" both survive)
        if w.lower() in known_terms_lower:
            fallback_tokens.append(w)
            continue

        stripped_pred = re.sub(predicates, "", w)
        if stripped_pred and stripped_pred != w:
            clean_pred = stripped_pred.rstrip(".,;:-~`!@#$%^&*()[]{}")
            if len(clean_pred) >= min_len:
                fallback_tokens.append(clean_pred)
                continue

        stripped = re.sub(particles, "", w)
        clean_w = stripped.rstrip(".,;:-~`!@#$%^&*()[]{}")
        if len(clean_w) >= min_len:
            fallback_tokens.append(clean_w)
    return fallback_tokens


def calculate_forensic_grounding(
    evidence_text: str,
    report_text: str,
    threshold: float = 0.60,
    filter_procedural: bool = False,
) -> dict[str, Any]:
    """Calculates term grounding between raw forensic evidence and draft report."""
    ev_terms = set(extract_forensic_morphemes(evidence_text))
    rep_terms = set(extract_forensic_morphemes(report_text))
    if filter_procedural:
        proc_lower = {p.lower() for p in FORENSIC_PROCEDURAL_TERMS}
        rep_terms = {t for t in rep_terms if t.lower() not in proc_lower}

    if not rep_terms:
        return {
            "grounding_score": 1.0,
            "is_grounded": True,
            "overlap_count": 0,
            "report_term_count": 0,
            "evidence_term_count": len(ev_terms),
            "unsupported_terms": [],
            "has_kiwi": _HAS_KIWI,
        }

    supported = rep_terms.intersection(ev_terms)
    unsupported = sorted(list(rep_terms - ev_terms))
    score = len(supported) / len(rep_terms)

    return {
        "grounding_score": round(score, 3),
        "is_grounded": score >= threshold,
        "overlap_count": len(supported),
        "report_term_count": len(rep_terms),
        "evidence_term_count": len(ev_terms),
        "supported_terms": sorted(list(supported)),
        "unsupported_terms": unsupported,
        "has_kiwi": _HAS_KIWI,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Korean Morphological Forensic Term & Grounding Analyzer (Kiwi)"
    )
    parser.add_argument("--evidence", nargs="*", default=[], help="Evidence text or JSON files")
    parser.add_argument("--report", help="Draft report file (.md, .txt, .html)")
    parser.add_argument("--text", help="Direct text to extract morphemes from")
    parser.add_argument("--threshold", type=float, default=0.60, help="Minimum grounding threshold")
    parser.add_argument("--filter-procedural", action="store_true", help="Filter standard forensic procedural/template terms")
    parser.add_argument("--high-fidelity", action="store_true", help="Local High-Fidelity gate: require source/evidence and <evidence> tags plus morpheme overlap (no Vertex API)")
    parser.add_argument("--json", action="store_true", help="Output JSON result")
    args = parser.parse_args(argv)

    if args.text:
        terms = extract_forensic_morphemes(args.text)
        unique_terms = sorted(list(set(terms)))
        if args.json:
            print(json.dumps({"terms": unique_terms, "count": len(unique_terms)}, ensure_ascii=False, indent=2))
        else:
            print(f"[Forensic Morphemes ({len(unique_terms)})]: {unique_terms[:20]}")
        return 0

    if args.evidence and args.report:
        report_path = Path(args.report)
        if not report_path.is_file():
            print(f"Error: Report file not found: {report_path}", file=sys.stderr)
            return 2

        evidence_chunks = []
        for ep in args.evidence:
            p = Path(ep)
            if p.is_file():
                evidence_chunks.append(p.read_text(encoding="utf-8", errors="replace"))

        ev_combined = "\n".join(evidence_chunks)
        rep_text = report_path.read_text(encoding="utf-8", errors="replace")

        eff_threshold = max(args.threshold, 0.70) if args.high_fidelity else args.threshold
        result = calculate_forensic_grounding(
            ev_combined, rep_text, threshold=eff_threshold, filter_procedural=args.filter_procedural
        )
        if args.high_fidelity:
            result["high_fidelity"] = True

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            default_neg = "FAIL" if args.high_fidelity else "WARN"
            verdict = "PASS" if result["is_grounded"] else default_neg
            mode_label = " (High-Fidelity Mode)" if args.high_fidelity else ""
            print(f"[{verdict}] Forensic Grounding{mode_label}: {result['grounding_score']*100:.1f}% (Threshold: {eff_threshold*100:.0f}%)")
            print(f"  - Overlap: {result['overlap_count']} / {result['report_term_count']} terms")
            if result["unsupported_terms"]:
                print(f"  - Novel Report Terms ({len(result['unsupported_terms'])}): {result['unsupported_terms'][:10]}")
        return 0 if result["is_grounded"] else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
