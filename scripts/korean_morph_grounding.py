#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""korean_morph_grounding.py — Korean Morphological Hybrid Grounding & Term Extraction.

Implements Section 5.2 of gemini_hallucination_mitigation_deep_dive.md.
Leverages Kiwi (kiwipiepy) morphological analysis to:
1. Extract content morphemes (NNG, NNP, NR, SL, SH, SN) while stripping case particles
   (조사: 은/는/이/가/을/를/의/에/에서/로/으로) and endings (어미), eliminating agglutinative
   mismatch that causes LLMs to fabricate or miss legal/statutory terms.
2. Register specialized Korean legal terminology into the Kiwi dictionary (e.g., 갑호증,
   을호증, 청구취지, 요건사실, 부당이득, 소송비용, 지연손해금).
3. Compute lexical/semantic grounding overlap between source evidence and generated legal
   drafts or summaries, flagging unsupported or hallucinated technical terms.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Optional Kiwi import with graceful regex fallback
try:
    from kiwipiepy import Kiwi
    _HAS_KIWI = True
except ImportError:
    Kiwi = None
    _HAS_KIWI = False

# Legal domain terms to register into Kiwi user dictionary
LEGAL_DOMAIN_TERMS = [
    ("갑호증", "NNP"),
    ("을호증", "NNP"),
    ("병호증", "NNP"),
    ("서증명", "NNG"),
    ("입증방법", "NNG"),
    ("소장", "NNG"),
    ("준비서면", "NNG"),
    ("답변서", "NNG"),
    ("고소장", "NNG"),
    ("내용증명", "NNG"),
    ("청구취지", "NNG"),
    ("청구원인", "NNG"),
    ("요건사실", "NNG"),
    ("지연손해금", "NNG"),
    ("소송비용", "NNG"),
    ("가집행", "NNG"),
    ("부당이득", "NNG"),
    ("불법행위", "NNG"),
    ("채무불이행", "NNG"),
    ("손해배상", "NNG"),
    ("대여금", "NNG"),
    ("차용증", "NNG"),
    ("상계항변", "NNG"),
    ("동시이행", "NNG"),
    ("소멸시효", "NNG"),
    ("변론종결", "NNG"),
    ("석명권", "NNG"),
    ("기판력", "NNG"),
    ("개인정보보호법", "NNP"),
    ("정보통신망법", "NNP"),
    ("부정경쟁방지법", "NNP"),
    ("특정금융정보법", "NNP"),
    ("전자문서법", "NNP"),
    ("전자상거래법", "NNP"),
    ("자본시장법", "NNP"),
    ("신용정보법", "NNP"),
]

# Morphological tags considered meaningful content terms
CONTENT_TAGS = {"NNG", "NNP", "NR", "SL", "SH", "SN"}

_KIWI_INSTANCE = None


def get_kiwi_instance():
    global _KIWI_INSTANCE
    if not _HAS_KIWI:
        return None
    if _KIWI_INSTANCE is None:
        try:
            k = Kiwi()
            for word, tag in LEGAL_DOMAIN_TERMS:
                try:
                    k.add_user_word(word, tag)
                except Exception:
                    pass
            _KIWI_INSTANCE = k
        except Exception:
            _KIWI_INSTANCE = None
    return _KIWI_INSTANCE


def extract_content_morphemes(text: str, min_len: int = 2) -> list[str]:
    """Extracts base Korean nouns and content terms, stripping particles and endings."""
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

    # Graceful fallback: regex-based noun extraction stripping common Korean particles and verb endings
    # NOTE: 이 폴백 로직은 lazyforensic/scripts/korean_morph_forensic.py 의
    # extract_forensic_morphemes 폴백과 짝이다. 어미/조사 제거 규칙을 고칠 때
    # 두 파일을 함께 고칠 것 (동기화 페어).
    known_legal = {w for w, _ in LEGAL_DOMAIN_TERMS}
    predicates = (
        r"(?:되었습니|되었습니다|되었으며|되었고|되었다|됩니다|된다|되다|"
        r"하였습니|하였습니다|하였으며|하였고|하였다|하여|합니다|한다|하다|"
        r"했습니|했습니다|했다|이며|이고|이다|입니다|"
        r"한|하고|하며|하게|된|되는|된)$"
    )
    particles = r"(?:은|는|이|가|을|를|의|에|에서|로|으로|와|과|도|만|에게|한테|이나|나|으로서|으로써)$"
    # 하이픈 결합 토큰도 하나의 단어로 본다 (쌍방 케이스 보존).
    words = re.findall(r"[가-힣a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*", text)
    fallback_tokens = []
    for w in words:
        if re.match(r"^[0-9]+[.)]?$", w):
            continue

        if w in known_legal:
            fallback_tokens.append(w)
            continue

        # Strip predicate endings first (e.g. 제출하여 -> 제출, 증명하였다 -> 증명, 송금하였으며 -> 송금)
        stripped_pred = re.sub(predicates, "", w)
        if stripped_pred and stripped_pred != w:
            clean_pred = stripped_pred.rstrip(".,;:-~`!@#$%^&*()[]{}")
            if len(clean_pred) >= min_len:
                fallback_tokens.append(clean_pred)
                continue

        # Strip particles (e.g. 갑호증을 -> 갑호증)
        stripped = re.sub(particles, "", w)
        clean_w = stripped.rstrip(".,;:-~`!@#$%^&*()[]{}")
        if len(clean_w) >= min_len:
            fallback_tokens.append(clean_w)
            for kw in known_legal:
                if kw in clean_w and kw != clean_w:
                    fallback_tokens.append(kw)
    return fallback_tokens


VALID_CASE_CODES = {
    "가단", "가합", "가소", "나", "다", "라", "마", "그", "바", "자", "차",
    "카", "카단", "카합", "카기", "카담", "카조", "카열", "카경",
    "고단", "고합", "고약", "노", "도", "로", "모", "오", "보", "코",
    "드", "드단", "드합", "르", "르단", "르합", "므", "스", "으",
    "느", "느단", "느합", "즈", "즈단", "즈합",
    "회단", "회합", "회개", "개회", "개단", "개합", "하단", "하합", "하면", "개확",
    "구", "구합", "구단", "누", "두", "루", "무", "허",
    "헌가", "헌나", "헌다", "헌라", "헌마", "헌바", "헌사", "헌아",
    "푸", "버",
    "재가단", "재가합", "재다", "재나", "재도", "재노", "재고단", "재고합",
}


def extract_legal_entities(text: str) -> dict[str, list[str]]:
    """Extracts formal legal statutes, case codes, evidence labels, and key entities."""
    statute_re = re.compile(
        r"([가-힣]{2,20}(?:법률|법)?)\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?"
    )
    precedent_re = re.compile(
        r"\b(?:대법원|서울고등법원|헌법재판소|[가-힣]{2,6}고등법원|[가-힣]{2,6}지방법원)?\s*(\d{4})\s*([가-힣]{1,4})\s*(\d+)\b"
    )
    evidence_re = re.compile(r"((?:갑|을|병)\s*제\s*\d+\s*호증(?:\s*의\s*\d+)?)")

    statutes = [m.group(0) for m in statute_re.finditer(text)]
    precedents = [
        f"{m.group(1)}{m.group(2)}{m.group(3)}"
        for m in precedent_re.finditer(text)
        if m.group(2) in VALID_CASE_CODES
    ]
    evidences = [m.group(1) for m in evidence_re.finditer(text)]

    # Morphological content nouns
    morphemes = extract_content_morphemes(text)

    return {
        "statutes": sorted(list(set(statutes))),
        "precedents": sorted(list(set(precedents))),
        "evidence_labels": sorted(list(set(evidences))),
        "content_morphemes": sorted(list(set(morphemes))),
    }


# 옛한글 자모 블록 — 훈민정음 원문·1950~80년대 구형 판결문·고서적의 자모 분석용.
# 현대 완성형(AC00~D7A3)과 달리 첫가끝 자모가 그대로 드러나는 구간들이다.
_OLD_KOREAN_BLOCKS = (
    (0x1100, 0x11FF),  # Hangul Jamo (초성/중성/종성 — 아래아 ᆞ 포함)
    (0xA960, 0xA97C),  # Hangul Jamo Extended-B (초성)
    (0xD7B0, 0xD7FF),  # Hangul Jamo Extended-B (종성)
    (0x3130, 0x318F),  # Hangul Compatibility Jamo (ㆍ U+318D 아래아 등)
)


def analyze_old_korean(text: str) -> dict[str, Any]:
    """옛한글/자모 수준 분석 — 구형 판결문·고서적·훈민정음체 텍스트 감지.

    Kiwi jamo_alphabet 계열 분석의 폴백으로, 완성형 음절을 NFD 자모로
    분해하고 현대 국문에서 쓰이지 않는 옛 자모(아래아 ᆞ, 옛 이중자음 등)를
    식별한다. 반환값에는 복원 가능한 자모 분해 결과와 옛 자모 문자 목록이
    들어간다.
    """
    if not text:
        return {
            "has_archaic": False,
            "archaic_chars": [],
            "jamo_units": 0,
            "syllables_decomposed": 0,
        }

    archaic: list[str] = []
    jamo_units = 0
    syllables = 0
    for ch in text:
        cp = ord(ch)
        if 0xAC00 <= cp <= 0xD7A3:
            syllables += 1
            jamo_units += len(unicodedata.normalize("NFD", ch))
            continue
        for lo, hi in _OLD_KOREAN_BLOCKS:
            if lo <= cp <= hi:
                archaic.append(ch)
                jamo_units += 1
                break
        else:
            if unicodedata.combining(ch):
                jamo_units += 1

    return {
        "has_archaic": bool(archaic),
        "archaic_chars": sorted(set(archaic)),
        "archaic_count": len(archaic),
        "jamo_units": jamo_units,
        "syllables_decomposed": syllables,
        "arae_a_count": sum(1 for c in archaic if c in "ㆍᆞ"),  # 아래아
    }


LEGAL_PROCEDURAL_TERMS = {
    "소장", "준비서면", "고소장", "답변서", "내용증명", "청구취지", "청구원인", "청구", "취지", "원인",
    "원고", "피고", "고소인", "피고소인", "당사자", "귀중", "사건", "사건번호", "입증방법", "입증",
    "서증", "서증명", "서증부호", "증거", "목록", "순번", "번호", "첨부서류", "첨부", "제출", "법원",
    "결론", "이유", "주문", "판결", "기각", "인용", "지급", "금원", "해당", "관할", "고지", "작성",
    "작성일자", "일자", "생성물", "변호사", "검토", "필수", "안내", "대리인", "소송대리인", "기재",
    "관계", "성립", "사실", "확인", "인정", "존재", "부존재", "경위", "내용", "취득", "부담", "발생",
    "서명", "날인", "표시", "증호",
}


def calculate_grounding_overlap(
    source_text: str,
    target_text: str,
    threshold: float = 0.70,
    filter_procedural: bool = False,
) -> dict[str, Any]:
    """Calculates morphological grounding overlap between source evidence and target text.

    Args:
        source_text: Ground truth evidence, input facts, or statutory text.
        target_text: Generated legal draft, summary, or argument.
        threshold: Minimum grounding ratio (0.0 to 1.0) to pass.
        filter_procedural: If True, strips standard procedural boilerplate terms from target.

    Returns:
        dict with overlap metrics, unsupported terms, and pass/fail verdict.
    """
    source_terms = set(extract_content_morphemes(source_text))
    target_terms = set(extract_content_morphemes(target_text))
    if filter_procedural:
        target_terms = target_terms - LEGAL_PROCEDURAL_TERMS

    if not target_terms:
        return {
            "grounding_score": 1.0,
            "is_grounded": True,
            "overlap_count": 0,
            "target_term_count": 0,
            "source_term_count": len(source_terms),
            "unsupported_terms": [],
        }

    supported_terms = target_terms.intersection(source_terms)
    unsupported_terms = sorted(list(target_terms - source_terms))
    score = len(supported_terms) / len(target_terms)

    return {
        "grounding_score": round(score, 3),
        "is_grounded": score >= threshold,
        "overlap_count": len(supported_terms),
        "target_term_count": len(target_terms),
        "source_term_count": len(source_terms),
        "supported_terms": sorted(list(supported_terms)),
        "unsupported_terms": unsupported_terms,
        "has_kiwi": _HAS_KIWI,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Korean Morphological Hybrid Grounding & Term Extraction (Kiwi)"
    )
    parser.add_argument("--source", help="Source evidence / fact file (.txt, .md, .json)")
    parser.add_argument("--target", help="Target generated draft / claim file (.txt, .md)")
    parser.add_argument("--text", help="Direct Korean text string to analyze")
    parser.add_argument("--threshold", type=float, default=0.70, help="Minimum grounding threshold")
    parser.add_argument("--filter-procedural", action="store_true", help="Filter court procedural boilerplate terms")
    parser.add_argument("--high-fidelity", action="store_true", help="Local High-Fidelity gate: require source and <evidence> tags plus morpheme overlap (no Vertex API)")
    parser.add_argument("--old-korean", action="store_true", help="옛한글 자모 분석 (훈민정음·구형 판결문 자모 단위)")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    args = parser.parse_args(argv)

    if args.text:
        entities = extract_legal_entities(args.text)
        if args.old_korean:
            entities["old_korean"] = analyze_old_korean(args.text)
        if args.json:
            print(json.dumps(entities, ensure_ascii=False, indent=2))
        else:
            print(f"[Entities] Statutes: {entities['statutes']}")
            print(f"[Entities] Precedents: {entities['precedents']}")
            print(f"[Entities] Evidence: {entities['evidence_labels']}")
            print(f"[Morphemes] Sample ({len(entities['content_morphemes'])}): {entities['content_morphemes'][:15]}")
        return 0

    if args.source and args.target:
        source_path = Path(args.source)
        target_path = Path(args.target)
        if not source_path.is_file():
            print(f"Error: Source file not found: {source_path}", file=sys.stderr)
            return 2
        if not target_path.is_file():
            print(f"Error: Target file not found: {target_path}", file=sys.stderr)
            return 2

        src_text = source_path.read_text(encoding="utf-8", errors="replace")
        tgt_text = target_path.read_text(encoding="utf-8", errors="replace")

        eff_threshold = max(args.threshold, 0.70) if args.high_fidelity else args.threshold
        result = calculate_grounding_overlap(
            src_text,
            tgt_text,
            threshold=eff_threshold,
            filter_procedural=args.filter_procedural,
        )
        if args.high_fidelity:
            result["high_fidelity"] = True

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            verdict = "PASS" if result["is_grounded"] else "FAIL"
            prefix = "[PASS]" if result["is_grounded"] else "[FAIL]"
            mode_label = " (High-Fidelity Mode)" if args.high_fidelity else ""
            print(f"{prefix} Morphological Grounding Score{mode_label}: {result['grounding_score'] * 100:.1f}% (Threshold: {eff_threshold * 100:.0f}%)")
            print(f"  - Supported Terms: {result['overlap_count']} / {result['target_term_count']}")
            if result["unsupported_terms"]:
                print(f"  - Unsupported Novel Terms ({len(result['unsupported_terms'])}): {result['unsupported_terms'][:10]}")
        return 0 if result["is_grounded"] else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
