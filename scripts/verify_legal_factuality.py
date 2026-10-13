#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_legal_factuality.py — Korean Legal and Precedent Hallucination Verifier.

Audits legal drafts, court ruling analyses, and legal documents against:
1. Statutory boundary bounds (e.g., Civil Act max article 1118, Criminal Act max 372).
2. Precedent format validity and year bounds (e.g., blocking future years or nonsense codes).
3. Grounding citations (warning on ungrounded legal claims without source references).

Directly addresses Section 5.1 & 5.2 of gemini_hallucination_mitigation_deep_dive.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Max article numbers for major Korean codes — data/statute_bounds.json이 SSOT이며
# 아래는 파일 부재 시 내장 fallback이다. JSON 형태: {"version": "2026.09", "bounds": {...}}
_STATUTE_BOUNDS_FALLBACK = {
    "민법": 1118,
    "형법": 372,
    "개인정보보호법": 76,
    "정보통신망법": 76,
    "정보통신망 이용촉진 및 정보보호 등에 관한 법률": 76,
    "상법": 935,
    "민사소송법": 502,
    "형사소송법": 493,
    "행정소송법": 46,
    "근로기준법": 116,
    "부정경쟁방지법": 18,
    "부정경쟁방지 및 영업비밀보호에 관한 법률": 18,
    "전자문서법": 37,
    "전자문서 및 전자거래 기본법": 37,
    "특정금융정보법": 22,
    "특정 금융거래정보의 보고 및 이용 등에 관한 법률": 22,
    "전자상거래법": 45,
    "전자상거래 등에서의 소비자보호에 관한 법률": 45,
    "자본시장법": 449,
    "자본시장과 금융투자업에 관한 법률": 449,
    "신용정보법": 53,
    "신용정보의 이용 및 보호에 관한 법률": 53,
    "소비자기본법": 86,
    "가사소송법": 72,
    "특허법": 232,
    "저작권법": 142,
    "도로교통법": 205,
    "의료법": 95,
}


_STATUTE_SUBARTICLES_FALLBACK: dict[str, int] = {
    "민법": 2,  # 제2조의2까지만 존재
    "형법": 2,
    "형사소송법": 6,  # 제200조의2~제200조의6 등
    "개인정보보호법": 5,  # 제32조의2 등 존재
    "정보통신망법": 7,  # 제44조의2~제44조의7 (명예훼손·도청) 실존
    "정보통신망 이용촉진 및 정보보호 등에 관한 법률": 7,
    "상법": 5,
    "민사소송법": 6,
    "행정소송법": 0,
    "근로기준법": 2,
    "부정경쟁방지법": 0,
    "부정경쟁방지 및 영업비밀보호에 관한 법률": 0,
    "전자문서법": 0,
    "전자문서 및 전자거래 기본법": 0,
    "특정금융정보법": 0,
    "특정 금융거래정보의 보고 및 이용 등에 관한 법률": 0,
    "전자상거래법": 0,
    "전자상거래 등에서의 소비자보호에 관한 법률": 0,
    "자본시장법": 4,
    "자본시장과 금융투자업에 관한 법률": 4,
    "신용정보법": 0,
    "신용정보의 이용 및 보호에 관한 법률": 0,
    "소비자기본법": 0,
    "가사소송법": 0,
    "특허법": 3,
    "저작권법": 0,
    "도로교통법": 24,  # 제52조의2 등 (실측 상한)
    "의료법": 0,
}

_LOAD_WARNINGS: list[str] = []


def _record_load_warning(msg: str) -> None:
    _LOAD_WARNINGS.append(msg)
    print(msg, file=sys.stderr)


def _load_statute_bounds(custom_path: Path | None = None) -> dict:
    try:
        p = custom_path or (Path(__file__).resolve().parent.parent / "data" / "statute_bounds.json")
        if not p.is_file():
            _record_load_warning(f"[WARN] data/statute_bounds.json 파일 부재 — 기본 내장 상한 사용")
            return dict(_STATUTE_BOUNDS_FALLBACK)
        data = json.loads(p.read_text(encoding="utf-8"))
        bounds = data.get("bounds", data) if isinstance(data, dict) else {}
        if isinstance(bounds, dict) and bounds:
            return {str(k): int(v) for k, v in bounds.items()}
        _record_load_warning(f"[WARN] data/statute_bounds.json 파손(유효 bounds 없음) — 기본 내장 상한 사용")
    except Exception as exc:
        _record_load_warning(f"[WARN] data/statute_bounds.json 파손({exc}) — 기본 내장 상한 사용")
    return dict(_STATUTE_BOUNDS_FALLBACK)


def _load_statute_subarticles(custom_path: Path | None = None) -> dict:
    try:
        p = custom_path or (Path(__file__).resolve().parent.parent / "data" / "statute_subarticles.json")
        if not p.is_file():
            _record_load_warning(f"[WARN] data/statute_subarticles.json 파일 부재 — 기본 내장 가지번호 상한 사용")
            return dict(_STATUTE_SUBARTICLES_FALLBACK)
        data = json.loads(p.read_text(encoding="utf-8"))
        subs = data.get("subarticles", data) if isinstance(data, dict) else {}
        if isinstance(subs, dict) and subs:
            return {str(k): int(v) for k, v in subs.items()}
        _record_load_warning(f"[WARN] data/statute_subarticles.json 파손(유효 subarticles 없음) — 기본 내장 가지번호 상한 사용")
    except Exception as exc:
        _record_load_warning(f"[WARN] data/statute_subarticles.json 파손({exc}) — 기본 내장 가지번호 상한 사용")
    return dict(_STATUTE_SUBARTICLES_FALLBACK)


def statute_bounds_version() -> str:
    """data/statute_bounds.json의 버전(YYYY.MM). 없으면 'unknown'."""
    try:
        p = Path(__file__).resolve().parent.parent / "data" / "statute_bounds.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version"):
                return str(data["version"])
    except Exception:
        pass
    return "unknown"


def statute_subarticles_version() -> str:
    """data/statute_subarticles.json의 버전(YYYY.MM). 없으면 'unknown'."""
    try:
        p = Path(__file__).resolve().parent.parent / "data" / "statute_subarticles.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version"):
                return str(data["version"])
    except Exception:
        pass
    return "unknown"


def _check_version_freshness(label: str, version_fn, datafile: str, max_age_months: int) -> str | None:
    from datetime import datetime

    ver = version_fn()
    m = re.match(r"^(\d{4})\.(\d{1,2})$", ver)
    if not m:
        return f"[WARN] {label} 버전 불명({ver}) — {datafile}을 확인하고 최신 상한으로 갱신하십시오"
    try:
        vdate = datetime(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return f"[WARN] {label} 버전 형식 오류({ver})"
    age = (datetime.now().year - vdate.year) * 12 + (datetime.now().month - vdate.month)
    if age > max_age_months:
        return (
            f"[WARN] {label} v{ver}가 {age}개월 경과 — 법 개정으로 상한이 바뀌었을 수 있으니 "
            f"최신 법령으로 대조 후 {datafile}을 갱신하십시오"
        )
    return None


def check_statute_freshness(max_age_months: int = 6) -> str | None:
    """법상수/가지번호 데이터 버전이 max_age_months보다 오래되면 경고문을 반환, 아니면 None.

    개정 미반영 상한으로 오탐/미탐이 생길 수 있어 주기적 리프레시를 강제한다.
    bounds와 subarticles 중 먼저 만료된 쪽의 경고를 반환한다.
    """
    for label, fn, df in (
        ("statute_bounds", statute_bounds_version, "data/statute_bounds.json"),
        ("statute_subarticles", statute_subarticles_version, "data/statute_subarticles.json"),
    ):
        warn = _check_version_freshness(label, fn, df, max_age_months)
        if warn:
            return warn
    return None


STATUTE_BOUNDS = _load_statute_bounds()
STATUTE_SUBARTICLES = _load_statute_subarticles()


ARTICLE_REF_RE = re.compile(r"제?(\d+)조(?:의(\d+))?")


def _article_ref(value) -> str | None:
    """Normalize an article reference to '제N조'/'제N조의M'. Accepts MCP cache
    shapes: plain numbers, digit strings, '제N조' strings or dicts carrying
    article_number/number."""
    if isinstance(value, dict):
        value = value.get("article_number", value.get("number"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = f"제{int(value)}조"
    if isinstance(value, str) and value.strip().isdigit():
        value = f"제{value.strip()}조"
    if not isinstance(value, str):
        return None
    m = ARTICLE_REF_RE.match(re.sub(r"\s+", "", value))
    if not m:
        return None
    return f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")


def _article_candidates(node: dict) -> list:
    candidates = []
    for key in ("articles", "article", "matches", "matched_articles", "article_number"):
        if key not in node:
            continue
        value = node[key]
        if isinstance(value, dict):
            candidates.extend(value.keys()) if key == "articles" else candidates.append(value)
        elif isinstance(value, list):
            candidates.extend(value)
        else:
            candidates.append(value)
    return candidates


def mcp_cache_provenance(mcp_cache) -> dict | None:
    """Extract provenance/grounding markers from an MCP response so callers can
    label cache matches as bundled excerpts rather than official sources."""
    if isinstance(mcp_cache, dict):
        provenance = mcp_cache.get("provenance")
        if isinstance(provenance, dict):
            return provenance
        if isinstance(mcp_cache.get("grounding_status"), str):
            return {"grounding_status": mcp_cache["grounding_status"]}
    return None


def match_mcp_statute_cache(citation: str, mcp_cache: dict | list | str | Path | None) -> bool:
    if isinstance(mcp_cache, (str, Path)):
        try:
            raw = str(mcp_cache)
            if raw.lstrip().startswith(("{", "[")):
                mcp_cache = json.loads(raw)
            else:
                mcp_cache = json.loads(Path(raw).read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            return False
    normalize = lambda value: re.sub(r"\s+", "", value) if isinstance(value, str) else ""
    match = re.fullmatch(r"([가-힣]+)(제\d+조(?:의\d+)?)", normalize(citation))
    if not match:
        return False
    law, article = match.groups()

    def matches(node, depth=0):
        if depth > 32:
            return False
        if isinstance(node, list):
            return any(matches(item, depth + 1) for item in node)
        if not isinstance(node, dict):
            return False
        laws = [normalize(node[k]) for k in ("law", "statute", "law_name", "statute_name", "법령명") if k in node]
        if laws and all(value == law for value in laws):
            if any(_article_ref(value) == article for value in _article_candidates(node)):
                return True
        return any(matches(value, depth + 1) for value in node.values() if isinstance(value, (dict, list)))

    return matches(mcp_cache)

def _make_statute_pattern(statute_name: str) -> re.Pattern:
    clean_name = re.sub(r"\s+", "", statute_name)
    escaped_chars = [re.escape(c) for c in clean_name]
    pattern_str = r"\s*".join(escaped_chars) + r"\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?"
    return re.compile(pattern_str)

# Standard Korean court precedent symbol categories
VALID_CASE_CODES = {
    # 민사
    "가단", "가합", "가소", "나", "다", "라", "마", "그", "바", "자", "차",
    # 보전처분 / 민사신청
    "카", "카단", "카합", "카기", "카담", "카조", "카열", "카경",
    # 형사
    "고단", "고합", "고약", "노", "도", "로", "모", "오", "보", "코",
    # 가사소송 및 가사비송
    "드", "드단", "드합", "르", "르단", "르합", "므", "스", "으",
    "느", "느단", "느합", "즈", "즈단", "즈합",
    # 도산 / 회생 / 파산
    "회단", "회합", "회개", "개회", "개단", "개합", "하단", "하합", "하면", "개확",
    # 행정 / 특허
    "구", "구합", "구단", "누", "두", "루", "무", "허",
    # 헌법재판소
    "헌가", "헌나", "헌다", "헌라", "헌마", "헌바", "헌사", "헌아",
    # 소년보호
    "푸", "버",
    # 재심
    "재가단", "재가합", "재다", "재나", "재도", "재노", "재고단", "재고합",
}

PRECEDENT_RE = re.compile(
    r"\b(?P<court>대법원|헌법재판소|특허법원|[가-힣]{2,6}회생법원|[가-힣]{2,6}가정법원|[가-힣]{2,6}행정법원|[가-힣]{2,6}고등법원|서울중앙지방법원|[가-힣]{2,6}지방법원)?\s*"
    r"(?P<year>\d{4})\s*(?P<code>[가-힣]{1,4})\s*(?P<num>\d+)\b"
    # 사건부호 판정은 문맥 요건 충족 후보만: 임의 숫자+한글 조합(예:
    # "2024자연 12345")을 판례로 오탐하는 것을 막는다. 법원명이나
    # 선고/판결/결정/심판/명령/사건/호 어미가 뒤따를 때만 판례 인용으로 본다.
    r"(?=(?:\s*(?:[가-힣]{1,10}\s+)?(?:선고|판결|결정|심판|명령|사건|호|판시))|\s*$)"
)

# Standard Korean particle/suffix lookahead for court and agency bounds
KOREAN_PARTICLE_SUFFIX = (
    r"(?:장관|차관|처장|청장|국장|위원장|부장|판사|검사|법원장|령|고시|지침|규정)?"
    r"(?:[이가은는을를의에]|에서|에게|서|과|와|도|만|부터|까지|로|으로|란|이란|라|라는|이라|이라는|며|이며|고|이고|통해|대해|관해)?"
    r"(?![가-힣\w])"
)

# Standard Korean verbal predicate suffix lookahead (handling 하였다, 했고, 했다, 한다, 함, 등에 따라, 등)
KOREAN_VERB_SUFFIX = (
    r"(?:하여(?:다|도|는|며|서)?|하였다|하였고|하였으며|하였으나|했(?:다|고|으며|으나|음)?|한다|하는|하며|하고|하기로|함|된)?"
    r"(?:[이가은는을를의에]|에서|에게|서|과|와|도|만|부터|까지|로|으로|란|이란|라|라는|이라|이라는|며|이며|고|이고|통해|대해|관해)?"
    r"(?![가-힣\w])"
)

# Number patterns supporting Arabic digits, Hangul Korean numbers, and Hanja/Sino-Korean numerals
HIST_NUM_4_PLUS = (
    r"(?:[4-9]|\d{2,}|[사오육칠팔구]|십[일이삼사오육칠팔구]?|[이삼사오육칠팔구]십[일이삼사오육칠팔구]?|"
    r"[四五六七八九]|[十百]|\d{2,}|[二三四五六七八九]十[一二三四五六七八九]?|十[一二三四五六七八九]?)"
)
HIST_NUM_3_PLUS = (
    r"(?:[3-9]|\d{2,}|[삼사오육칠팔구]|십[일이삼사오육칠팔구]?|[이삼사오육칠팔구]십[일이삼사오육칠팔구]?|"
    r"[三四五六七八九]|[十百]|\d{2,}|[二三四五六七八九]十[一二三四五六七八九]?|十[一二三四五六七八九]?)"
)
HIST_NUM_2_PLUS = (
    r"(?:[2-9]|\d{2,}|[이삼사오육칠팔구]|십[일이삼사오육칠팔구]?|[이삼사오육칠팔구]십[일이삼사오육칠팔구]?|"
    r"[二三四五六七八九]|[十百]|\d{2,}|[二三四五六七八九]十[一二三四五六七八九]?|十[一二三四五六七八九]?)"
)

HIST_ORD_PREFIX = r"(?:제|第)?\s*"
HIST_ORD_SUFFIX = r"(?:\s*(?:차|차례|次))"

# Abolished or fabricated court names (Section 5.1 #2)
FABRICATED_COURT_RE = re.compile(
    rf"(?<![가-힣])(?P<court>서울민사지방법원|서울형사지방법원|한국연방법원|연방대법원|중앙고등법원|고등대법원|[가-힣]+민사지방법원|[가-힣]+형사지방법원){KOREAN_PARTICLE_SUFFIX}"
)

# Fabricated government agencies and investigative bodies (Section 5.1 #2)
FABRICATED_AGENCY_RE = re.compile(
    rf"(?<![가-힣])(?P<agency>디지털포렌식청|사이버수사처|국가포렌식연구원|사이버범죄특별수사처|경찰청사이버보안국|사이버보안청|인공지능윤리청|국가데이터청|개인정보보호청|사이버테러수사본부|정보보호조사위원회|디지털윤리위원회|한국연방검찰청|대검찰청사이버수사청){KOREAN_PARTICLE_SUFFIX}"
)

# Abolished / obsolete government ministries and their current successors (Section 5.1 #2)
ABOLISHED_GOV_AGENCIES: dict[str, tuple[str, str]] = {
    "정보통신부": ("2008년 폐지", "과학기술정보통신부 또는 방송통신위원회"),
    "문화공보부": ("1990년 폐지", "문화체육관광부"),
    "재정경제원": ("1998년 폐지", "기획재정부"),
    "재정경제부": ("2008년 개편", "기획재정부"),
    "미래창조과학부": ("2017년 개편", "과학기술정보통신부"),
    "과학기술처": ("1998년 개편", "과학기술정보통신부"),
    "과학기술부": ("2008년 개편", "과학기술정보통신부"),
    "교육인적자원부": ("2008년 개편", "교육부"),
    "교육과학기술부": ("2013년 개편", "교육부"),
    "건설교통부": ("2008년 개편", "국토교통부"),
    "국토해양부": ("2013년 개편", "국토교통부"),
    "행정자치부": ("2017년 개편", "행정안전부"),
    "안전행정부": ("2014년 개편", "행정안전부"),
    "국민안전처": ("2017년 개편", "행정안전부/소방청/해양경찰청"),
    "산업자원부": ("2008년 개편", "산업통상자원부"),
    "지식경제부": ("2013년 개편", "산업통상자원부"),
    "상공자원부": ("1994년 개편", "산업통상자원부"),
    "동력자원부": ("1993년 개편", "산업통상자원부"),
    "보건사회부": ("1994년 개편", "보건복지부"),
    "노동부": ("2010년 개편", "고용노동부"),
    "총무처": ("1998년 폐지", "행정안전부"),
    "내무부": ("1998년 폐지", "행정안전부"),
    "공보처": ("1998년 폐지", "문화체육관광부"),
    "기획예산처": ("2008년 개편", "기획재정부"),
    "철도청": ("2005년 개편", "한국철도공사/국가철도공단"),
}

# Fabricated academic journals (Section 5.1 #3)
FABRICATED_ACADEMIC_JOURNALS_RE = re.compile(
    rf"(?<![가-힣])(?P<journal>대한인공지능법학회지|한국사이버포렌식학회논문집|한국디지털증거법학회지|국제사이버수사학술지|대한디지털포렌식학회논문지|한국인공지능윤리학회지|대한사이버보안학회지){KOREAN_PARTICLE_SUFFIX}"
)

# Future academic citations (Section 5.1 #3)
FUTURE_ACADEMIC_CITATION_RE = re.compile(
    r"(?<![가-힣])(?P<citation>(?:「[^」]{2,60}」\s*,\s*[^,\n]{2,30}?(?:학회지|논문집|학술지|저널|리뷰)\s*,\s*(?P<year>\d{4})\s*년?)|(?:(?P<author>[가-힣]{2,4})\s*교수?(?:의|가)?\s*[^.!?\n]{0,60}?(?P<year2>\d{4})\s*년\s*(?:발표한|게재한|발간한|출간한|수록된)?\s*(?:논문|저널|학술지)))"
)

# Fabricated Korean historical events & treaties bounds (Section 5.1 #3)
FABRICATED_HISTORICAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    # 갑오개혁 (1차, 2차, 3차(을미개혁)만 존재 -> 4차 이상 날조)
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:(?:갑오\s*개혁|甲午\s*改革)\s*{HIST_ORD_PREFIX}{HIST_NUM_4_PLUS}{HIST_ORD_SUFFIX})|(?:{HIST_ORD_PREFIX}{HIST_NUM_4_PLUS}{HIST_ORD_SUFFIX}\s*(?:갑오\s*개혁|甲午\s*改革)))"
            + KOREAN_PARTICLE_SUFFIX
        ),
        "갑오개혁은 제1차(1894), 제2차(1894~1895), 제3차(을미개혁, 1895)까지만 존재하며 4차 이상은 존재하지 않는 역사 날조입니다.",
    ),
    # 동학농민운동 / 동학농민혁명 (1차, 2차 봉기만 존재 -> 3차 이상 날조)
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:(?:동학\s*농민\s*(?:운동|혁명)|東學\s*農民\s*(?:運動|革命))\s*{HIST_ORD_PREFIX}{HIST_NUM_3_PLUS}{HIST_ORD_SUFFIX})|(?:{HIST_ORD_PREFIX}{HIST_NUM_3_PLUS}{HIST_ORD_SUFFIX}\s*(?:동학\s*농민\s*(?:운동|혁명)|東學\s*農民\s*(?:運動|革命))))"
            + KOREAN_PARTICLE_SUFFIX
        ),
        "동학농민운동은 제1차 봉기(백산), 제2차 봉기(삼례)까지만 존재하며 3차 이상은 날조입니다.",
    ),
    # 임진왜란 (1차 임진왜란 1592, 2차 정유재란 1597 -> 3차 이상 날조)
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:(?:임진\s*왜란|壬辰\s*倭亂)\s*{HIST_ORD_PREFIX}{HIST_NUM_3_PLUS}{HIST_ORD_SUFFIX})|(?:{HIST_ORD_PREFIX}{HIST_NUM_3_PLUS}{HIST_ORD_SUFFIX}\s*(?:임진\s*왜란|壬辰\s*倭亂)))"
            + KOREAN_PARTICLE_SUFFIX
        ),
        "임진왜란은 임진왜란(1592)과 정유재란(1597) 2차례 교전이며 3차 이상은 날조입니다.",
    ),
    # 단일 체결 조약/늑약의 차수 날조 (을사조약, 을사늑약, 정미7조약, 정미칠조약, 한일신협약, 한일의정서, 강화도조약, 조일수호조규, 한일병합조약, 한일합방조약, 조미수호통상조약, 한일기본조약, 남북기본합의서 등 2차 이상 불가)
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:(?:을사\s*조약|을사\s*늑약|정미\s*7\s*조약|정미\s*칠\s*조약|한일\s*신\s*협약|한일\s*의정서|강화도\s*조약|조일\s*수호\s*조규|한일\s*(?:병합|합방)\s*조약|조미\s*수호\s*통상\s*조약|한일\s*기본\s*조약|남북\s*기본\s*합의서|乙巳條約|乙巳勒約|丁未七條約|韓日新協約|韓日議政書|江華島條約|朝日修好條規|韓日倂合條約|朝美修好通商條約|韓日基本條約|南北基本合意書)\s*{HIST_ORD_PREFIX}{HIST_NUM_2_PLUS}{HIST_ORD_SUFFIX})|(?:{HIST_ORD_PREFIX}{HIST_NUM_2_PLUS}{HIST_ORD_SUFFIX}\s*(?:을사\s*조약|을사\s*늑약|정미\s*7\s*조약|정미\s*칠\s*조약|한일\s*신\s*협약|한일\s*의정서|강화도\s*조약|조일\s*수호\s*조규|한일\s*(?:병합|합방)\s*조약|조미\s*수호\s*통상\s*조약|한일\s*기본\s*조약|남북\s*기본\s*합의서|乙巳條約|乙巳勒約|丁未七條약|韓日新協約|韓日議政書|江華島條約|朝日修好條規|韓日倂合條約|朝美修好通商條約|韓日基本條約|南北基本合意書)))"
            + KOREAN_PARTICLE_SUFFIX
        ),
        "해당 조약/의정서는 1회 단일 체결 사건으로 제2차 이상의 조약은 존재하지 않는 역사 날조입니다.",
    ),
    # 단일 역사적 사건/운동/개혁 차수 날조 (을미개혁, 을미사변, 3·1운동, 삼일운동, 신미양요, 병인양요, 갑신정변, 임오군란, 사화, 4·19혁명, 5·18민주화운동, 6월민주항쟁 등 2차 이상 불가)
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:(?:을미\s*개혁|을미\s*사변|3\s*[·.]\s*1\s*운동|삼일\s*운동|신미\s*양요|병인\s*양요|갑신\s*정변|임오\s*군란|무오\s*사화|갑자\s*사화|기묘\s*사화|을사\s*사화|4\s*[·.]\s*19\s*혁명|사일구\s*혁명|5\s*[·.]\s*18\s*민주화\s*운동|오일팔\s*민주화\s*운동|6\s*월\s*민주\s*항쟁|육월\s*민주\s*항쟁|乙未改革|乙未事變|三\s*[·.]\s*一\s*運動|辛未洋擾|丙寅洋擾|甲申政變|壬午軍亂|四\s*[·.]\s*一九\s*革命|五\s*[·.]\s*一八\s*民主化\s*運動|六月\s*民主\s*抗爭)\s*{HIST_ORD_PREFIX}{HIST_NUM_2_PLUS}{HIST_ORD_SUFFIX})|(?:{HIST_ORD_PREFIX}{HIST_NUM_2_PLUS}{HIST_ORD_SUFFIX}\s*(?:을미\s*개혁|을미\s*사변|3\s*[·.]\s*1\s*운동|삼일\s*운동|신미\s*양요|병인\s*양요|갑신\s*정변|임오\s*군란|무오\s*사화|갑자\s*사화|기묘\s*사화|을사\s*사화|4\s*[·.]\s*19\s*혁명|사일구\s*혁명|5\s*[·.]\s*18\s*민주화\s*운동|오일팔\s*민주화\s*운동|6\s*월\s*민주\s*항쟁|육월\s*민주\s*항쟁|乙未改革|乙未事變|三\s*[·.]\s*一\s*運動|辛未洋擾|丙寅洋擾|甲申政變|壬午軍亂|四\s*[·.]\s*一九\s*革命|五\s*[·.]\s*一八\s*民主化\s*運動|六月\s*民主\s*抗爭)))"
            + KOREAN_PARTICLE_SUFFIX
        ),
        "해당 역사적 사건/개혁은 단일 1회성 사건으로 제2차 이상의 사건은 존재하지 않는 역사 날조입니다.",
    ),
]

# Impossible judicial procedures under Korean Law (Section 5.1 #4)
IMPOSSIBLE_JUDICIAL_PROCEDURE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:대검찰청|대검|고등검찰청|고검)(?:의|에서|이|은|는)?\s*[^.!?\n]{{0,100}}?(?:약식명령\s*(?:을\s*)?청구|약식기소|약식명령\s*기소))"
            r"(?!\s*(?:를\s*)?(?:검토|지시|지휘|지도|권고|시달|보고|요청|명령|하도록|하라는))"
            + KOREAN_VERB_SUFFIX
        ),
        "약식명령 청구권자는 1심 관할 지방검찰청(또는 지청) 검사이며, 상급 검찰청(대검찰청/고등검찰청)은 약식명령을 청구할 수 없습니다 (형사소송법 제448조 위반).",
    ),
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:대법원|고등법원)(?:에|에의|을\s*상대로)?\s*[^.!?\n]{{0,100}}?(?:약식명령\s*(?:을\s*)?청구|약식명령\s*신청|약식명령))"
            r"(?!\s*(?:를\s*)?(?:검토|지시|지휘|지도|권고|시달|보고|요청|명령|하도록|하라는))"
            + KOREAN_VERB_SUFFIX
        ),
        "약식명령은 지방법원 단독판사 관할이며 상급법원(대법원/고등법원)에 청구할 수 없습니다 (형사소송법 제448조 위반).",
    ),
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:경찰(?:청|관|서)?|사법경찰관)(?:이|의|은|는|에서)?\s*[^.!?\n]{{0,100}}?"
            r"(?:"
            r"(?:법원에\s*[^.!?\n]{0,50}?(?:구속영장|체포영장|압수수색영장|영장)(?:을|를)?\s*(?:직접\s*)?(?:청구|신청))"
            r"|(?:(?:직접\s*)?(?:구속영장|체포영장|압수수색영장|영장)(?:을|를)?\s*직접\s*청구)"
            r"|(?:(?:구속영장|체포영장|압수수색영장|영장)(?:을|를)?\s*청구)"
            r"))"
            r"(?!\s*(?:를\s*)?(?:신청|지시|지휘|지도|시달|보고|요청|기각|기각한))"
            + KOREAN_VERB_SUFFIX
        ),
        "영장 청구권은 검사에게만 전속되어 있으며, 사법경찰관은 검사에게 신청만 가능할 뿐 법원에 영장을 직접 청구하거나 신청할 수 없습니다 (헌법 제12조 제3항, 형사소송법 제200조의2, 제201조 위반).",
    ),
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:경찰(?:청|관|서)?|사법경찰관)(?:이|의|은|는)?\s*[^.!?\n]{{0,100}}?"
            r"(?:법원에\s*)?(?:직접\s*)?(?:공소제기|공소\s*제기|기소(?:\s*청구|\s*권|\s*결정|\s*강행|\s*(?:를\s*)?결정|하여|하였다|했다|함|한다)?))"
            r'(?!(?:\s*(?:의견|유예|중지|송치|지시|지휘|보고|요청)))'
            + KOREAN_VERB_SUFFIX
        ),
        "국가소추주의 및 기소독점주의에 따라 공소제기(기소)는 검사만 가능하며, 경찰은 송치/불송치 결정만 가능하고 직접 기소할 수 없습니다 (형사소송법 제246조 위반).",
    ),
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:대법원|대검찰청|대검)(?:의|에서|이)?\s*[^.!?\n]{{0,100}}?(?:구속영장|체포영장)(?:을|를)?\s*(?:청구|발부))"
            + KOREAN_VERB_SUFFIX
        ),
        "대법원은 상고심 법률심 법원으로 수사단계 구속영장을 발부하지 않으며 대검찰청은 영장청구 관할이 아닙니다.",
    ),
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:헌법재판소|헌재)(?:의|에서|이|은|는)?\s*[^.!?\n]{{0,100}}?(?:징역|금고|벌금|형벌|유죄|무죄)[^.!?\n]{{0,30}}?(?:선고|판결))"
            + KOREAN_VERB_SUFFIX
        ),
        "헌법재판소는 위헌법률심판, 탄핵, 헌법소원 등을 관할하며, 일반 형사사건의 징역형이나 유죄 판결을 선고할 수 없습니다 (헌법 제111조 위반).",
    ),
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>민사(?:소송|재판)(?:에서|으로|부)?\s*[^.!?\n]{{0,100}}?(?:징역|금고|벌금)[^.!?\n]{{0,30}}?(?:선고|부과))"
            + KOREAN_VERB_SUFFIX
        ),
        "민사소송은 사법상 권리분쟁 해결 절차로, 형벌인 징역형, 금고, 벌금형을 선고할 수 없습니다.",
    ),
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>형사(?:소송|재판)(?:의|에서)?\s*(?:원고|원고측))"
            + KOREAN_PARTICLE_SUFFIX
        ),
        "형사소송의 당사자는 검사와 피고인이며, '원고'는 민사/행정소송의 당사자 명칭으로 형사소송에는 존재하지 않습니다.",
    ),
    (
        re.compile(
            rf"(?<![가-힣\w])(?P<target>(?:지방법원|고등법원|대법원)(?:에|에의)?\s*[^.!?\n]{{0,50}}?헌법소원(?:\s*심판)?\s*청구)"
            + KOREAN_VERB_SUFFIX
        ),
        "헌법소원 심판 청구는 헌법재판소의 전속 관할이며 일반 법원에 청구할 수 없습니다 (헌법재판소법 제68조 위반).",
    ),
]

EVIDENCE_TAG_RE = re.compile(r"<evidence(?:\s+[^>]*)?>(.*?)</evidence>", re.DOTALL | re.IGNORECASE)


def verify_legal_text(
    text: str,
    current_year: int | None = None,
    source_text: str | None = None,
    morph_grounding: bool = False,
    high_fidelity: bool = False,
    allow_historical: bool = False,
    claim_ledger_path: str | Path | None = None,
    mcp_cache: str | Path | dict | list | None = None,
) -> dict:
    from datetime import datetime as _dt
    if current_year is None:
        current_year = _dt.now().year
    errors: list[str] = []
    warnings: list[str] = list(_LOAD_WARNINGS)
    cited_statutes: list[str] = []
    cited_precedents: list[str] = []

    # 1. Statutory bounds check (flexible spacing & span deduplication)
    matched_spans: list[tuple[int, int]] = []
    sorted_statutes = sorted(STATUTE_BOUNDS.items(), key=lambda x: len(x[0]), reverse=True)

    for statute_name, max_art in sorted_statutes:
        pattern = _make_statute_pattern(statute_name)
        for match in pattern.finditer(text):
            span = match.span()
            if any(s <= span[0] and span[1] <= e for s, e in matched_spans):
                continue
            matched_spans.append(span)
            art_num = int(match.group(1))
            sub_num = match.group(2)
            full_ref = match.group(0)
            cited_statutes.append(full_ref)
            if art_num < 1 or art_num > max_art:
                errors.append(
                    f"[{statute_name}] 허위 조문 날조: {full_ref} - "
                    f"현행 {statute_name}은 제1조~제{max_art}조까지만 존재합니다."
                )
            elif sub_num is not None:
                max_sub = STATUTE_SUBARTICLES.get(statute_name, 0)
                if int(sub_num) > max_sub or int(sub_num) < 1:
                    errors.append(
                        f"[{statute_name}] 허위 가지번호 날조: {full_ref} - "
                        f"현행 {statute_name}의 가지번호(제N조의M)는 최대 '의{max_sub}'까지만 존재합니다."
                    )

    # 1-1. 미등재 법령 조문 인용: 상한 딕셔너리에 없는 법명 + "제N조" 패턴은
    # 자동 대조가 불가능한 ungrounded 인용이다. 날조를 놓치지 않도록 경고(WARN).
    # 단, mcp_cache에 해당 조문이 존재하는 경우 경고를 해제한다.
    unknown_law_re = re.compile(r"(?<![가-힣])([가-힣]{2,15}법)\s*제\s*\d+\s*조(?:\s*의\s*\d+)?")
    known_clean = {re.sub(r"\s+", "", name) for name in STATUTE_BOUNDS}
    for m in unknown_law_re.finditer(text):
        law_clean = re.sub(r"\s+", "", m.group(1))
        if law_clean not in known_clean:
            ref_str = m.group(0)
            cited_statutes.append(ref_str)
            if mcp_cache and match_mcp_statute_cache(ref_str, mcp_cache):
                continue
            warnings.append(
                f"[미등재 법령 인용] '{ref_str}' - 상한 검증 대상 법령이 아닙니다. "
                f"korean_law MCP 등 공식 출처로 조문 존재 여부를 반드시 대조하십시오."
            )

    # 2. Precedent format and year sanity check
    for match in PRECEDENT_RE.finditer(text):
        year = int(match.group("year"))
        code = match.group("code")
        num = match.group("num")
        case_str = f"{year}{code}{num}"
        cited_precedents.append(case_str)

        if year > current_year:
            errors.append(
                f"[판례 날조] 미래 연도 판결 인용: {case_str} - "
                f"현재 연도({current_year}년)보다 미래의 사건번호는 날조된 환각입니다."
            )
        elif year < 1948:
            errors.append(
                f"[판례 날조] 대한민국 사법부 수립 이전 연도 판결: {case_str} (1948년 이전)."
            )

        if code not in VALID_CASE_CODES:
            warnings.append(
                f"[판례 부호 날조] 비표준 사건부호 인용: '{code}' in {case_str} - "
                f"대법원 규격 사건부호가 아니며 존재하지 않는 판례일 가능성이 높습니다."
            )

    # 3-1. Fabricated or abolished court names check (Section 5.1 #2)
    for m in FABRICATED_COURT_RE.finditer(text):
        fake_court = m.group("court")
        errors.append(
            f"[법원 명칭 날조] 폐지되거나 실존하지 않는 법원 명칭 인용: {fake_court} (Section 5.1 위반)"
        )

    # 3-2. Fabricated government agencies and committees (Section 5.1 #2)
    for m in FABRICATED_AGENCY_RE.finditer(text):
        fake_agency = m.group("agency")
        errors.append(
            f"[정부기관 명칭 날조] 실존하지 않는 가짜 관공서/기구 명칭 인용: {fake_agency} (Section 5.1 위반)"
        )

    # 3-3. Abolished government ministries check (Section 5.1 #2)
    for agency, (abolish_info, successor) in ABOLISHED_GOV_AGENCIES.items():
        pat = re.compile(rf"(?<![가-힣]){re.escape(agency)}{KOREAN_PARTICLE_SUFFIX}")
        if pat.search(text):
            successor_candidates = [s.strip() for s in re.split(r"또는|/|,", successor) if s.strip()]
            has_successor_annotation = any(cand in text for cand in successor_candidates)
            has_historical_marker = bool(
                re.search(rf"\((?:구|과거)\s*{re.escape(agency)}\)", text)
                or re.search(rf"{re.escape(agency)}\s*\((?:현|현행)", text)
            )

            if has_successor_annotation or has_historical_marker or allow_historical:
                warnings.append(
                    f"[정부기관 역사적 명칭 인용] 폐지된 구 정부 부처명 인용: '{agency}' ({abolish_info}, 현행 '{successor}' 병기됨/역사적 검토 허용)"
                )
            else:
                errors.append(
                    f"[정부기관 명칭 오류/날조] 폐지된 구 정부 부처명 인용: '{agency}' ({abolish_info}, 현행 '{successor}' 명칭 사용 필수) (Section 5.1 위반)"
                )

    # 3-4. Fabricated Korean historical events and treaties check (Section 5.1 #3)
    for pat, desc in FABRICATED_HISTORICAL_PATTERNS:
        for m in pat.finditer(text):
            matched_text = m.group("target") if "target" in m.groupdict() else m.group(0)
            errors.append(
                f"[한국사 사건/조약 날조] 실존하지 않는 역사적 사건/차수 날조: '{matched_text}' - {desc} (Section 5.1 #3 위반)"
            )

    # 3-5. Impossible judicial procedures check (Section 5.1 #4)
    for pat, desc in IMPOSSIBLE_JUDICIAL_PROCEDURE_PATTERNS:
        for m in pat.finditer(text):
            matched_text = m.group("target") if "target" in m.groupdict() else m.group(0)
            errors.append(
                f"[불가능한 사법절차 날조] 실정법상 성립할 수 없는 사법 절차/권한 인용: '{matched_text}' - {desc} (Section 5.1 #4 위반)"
            )

    # 3-6. Fabricated academic journals and future academic citations check (Section 5.1 #3)
    for m in FABRICATED_ACADEMIC_JOURNALS_RE.finditer(text):
        fake_journal = m.group("journal")
        errors.append(
            f"[학술논문/학술지 날조] 실존하지 않는 가짜 학술지/학회논문집 인용: '{fake_journal}' (Section 5.1 #3 위반)"
        )
    for m in FUTURE_ACADEMIC_CITATION_RE.finditer(text):
        cite_str = m.group("citation")
        pub_year = int(m.group("year") or m.group("year2"))
        if pub_year > current_year:
            errors.append(
                f"[학술논문/학술지 날조] 미래 연도 학술 논문/저널 인용: '{cite_str}' ({pub_year}년) - "
                f"현재 연도({current_year}년)보다 미래의 학술 출판물은 날조된 환각입니다 (Section 5.1 #3 위반)."
            )

    # 3-7. Optional Claim Ledger integration (Section 6)
    if claim_ledger_path:
        try:
            from scripts.verify_claim_ledger import verify_claim_ledger_file
        except ImportError:
            try:
                from verify_claim_ledger import verify_claim_ledger_file
            except ImportError:
                verify_claim_ledger_file = None

        if verify_claim_ledger_file is not None:
            ledger_report = verify_claim_ledger_file(claim_ledger_path, synthesis_path=None)
            # Check cited claims in text
            citation_re = re.compile(r"\[Claim\s*([A-Za-z0-9._-]+)\]", re.IGNORECASE)
            for m in citation_re.finditer(text):
                cited_id = f"Claim {m.group(1)}"
                found = next((r for r in ledger_report["rows"] if r["claimId"].lower() == cited_id.lower()), None)
                if not found:
                    errors.append(f"[Claim Ledger 위반] 문서에 인용된 [{cited_id}]가 claim-ledger.md에 등록되어 있지 않습니다.")
                elif found["status"] != "VERIFIED":
                    errors.append(
                        f"[Claim Ledger 위반] 문서에 인용된 [{cited_id}]의 원장 상태가 '{found['status']}'입니다. "
                        "오직 VERIFIED 주장만 최종 문서 인용이 허용됩니다 (Section 6 위반)."
                    )
            if not ledger_report["ok"]:
                for v in ledger_report["violations"]:
                    errors.append(f"[Claim Ledger 위반] [{v['claimId']}] {v['violation']}")
        else:
            warnings.append("verify_claim_ledger 모듈을 찾을 수 없어 원장 검증을 건너뛰었습니다.")

    # 4. Evidence tag attribution check (Section 3.2 #1)
    evidence_matches = EVIDENCE_TAG_RE.findall(text)
    for quote in evidence_matches:
        q_strip = quote.strip()
        if not q_strip:
            errors.append("<evidence> 태그가 비어 있습니다. 답변 근거 구절을 채우십시오.")
        elif source_text:
            # Check verbatim presence in source text
            clean_quote = re.sub(r"\s+", " ", q_strip)
            clean_source = re.sub(r"\s+", " ", source_text)
            if clean_quote not in clean_source:
                errors.append(
                    f"근거 인용 불일치: <evidence> 구절('{q_strip[:25]}...')이 원문(source)에 존재하지 않습니다."
                )
        else:
            warnings.append(
                f"<evidence> 인용 구절('{q_strip[:25]}...')이 존재하나 대조할 원문(--source)이 지정되지 않았습니다."
            )

    # 5. High-Fidelity non-parametric gate (Section 4.2)
    if high_fidelity:
        if not source_text:
            errors.append("[High-Fidelity Grounding 위반] High-Fidelity 검증을 위한 원문(--source)이 지정되지 않았습니다.")
        elif not evidence_matches:
            errors.append("[High-Fidelity Grounding 위반] 사실관계 주장을 뒷받침하는 <evidence> 원문 인용 태그가 없습니다.")

    # 6. Morphological grounding check if source text is provided (Section 5.2)
    if source_text and (morph_grounding or high_fidelity):
        try:
            from scripts.korean_morph_grounding import calculate_grounding_overlap
        except ImportError:
            try:
                from korean_morph_grounding import calculate_grounding_overlap
            except ImportError:
                calculate_grounding_overlap = None

        if calculate_grounding_overlap is not None:
            # If target text has dedicated factual sections, isolate them to avoid boilerplate dilution
            fact_section_match = re.search(
                r"(?:^|\n)\s*(?:#{1,4}\s*|\d+[\.\)]\s*|제\s*\d+\s*조?\s*|\b|【|\[)?\s*(?:\d+[\.\)]\s*)?"
                r"(?:청구원인|주장 및 항변|범죄사실|사실관계|사실\s*관계|통고 내용|통고\s*내용|신청이유|주장의 요지)\b[^\n]*\n?"
                r"(.*?)"
                r"(?=\n#{1,2}\s|\n\s*(?:#{1,4}\s*|\d+[\.\)]\s*|제\s*\d+\s*조?\s*|【|\[)?\s*(?:\d+[\.\)]\s*)?(?:법적|법률|입증|증거|결론|첨부|신청|관할|판단|이유|고소|주문)|\Z)",
                text,
                re.DOTALL,
            )
            eval_target = fact_section_match.group(1) if fact_section_match else text
            clean_tgt = re.sub(r"<[^>]+>", " ", eval_target)
            thresh = 0.65
            overlap = calculate_grounding_overlap(source_text, clean_tgt, threshold=thresh, filter_procedural=True)
            if not overlap["is_grounded"]:
                msg = (
                    f"형태소 그라운딩 미달 ({overlap['grounding_score']*100:.1f}% < {int(thresh*100)}%): "
                    f"원문에 없는 고유/전문 용어 다수 사용 {overlap['unsupported_terms'][:5]}"
                )
                if high_fidelity:
                    errors.append(f"[High-Fidelity Grounding 위반] {msg}")
                else:
                    warnings.append(msg)

    # 7. Grounding notice check for legal drafts
    if "# 소 장" in text or "# 준 비 서 면" in text or "# 고 소 장" in text:
        if "변호사" not in text and "AI 생성" not in text:
            warnings.append("법률 문서 초안에 필수 법적 고지(변호사 검토 안내)가 누락되었습니다.")

    verdict = "FAIL" if errors else ("WARN" if warnings else "PASS")
    cache_matched = [citation for citation in cited_statutes if match_mcp_statute_cache(citation, mcp_cache)]
    return {
        "validation_scope": "format_bounds_and_local_grounding_not_source_authentication",
        "source_verified": False,
        "cache_matched_statutes": sorted(set(cache_matched)),
        "cache_provenance": mcp_cache_provenance(mcp_cache),
        "verdict": verdict,
        "errors": errors,
        "warnings": warnings,
        "cited_statutes": sorted(list(set(cited_statutes))),
        "cited_precedents": sorted(list(set(cited_precedents))),
    }


def verify_legal_file(
    file_path: str | Path,
    current_year: int | None = None,
    source_path: str | Path | None = None,
    morph_grounding: bool = False,
    high_fidelity: bool = False,
    allow_historical: bool = False,
    claim_ledger_path: str | Path | None = None,
    mcp_cache: str | Path | dict | list | None = None,
) -> dict:
    from datetime import datetime as _dt
    if current_year is None:
        current_year = _dt.now().year
    path = Path(file_path)
    if not path.is_file():
        return {
            "verdict": "FAIL",
            "errors": [f"File not found: {file_path}"],
            "warnings": [],
            "cited_statutes": [],
            "cited_precedents": [],
        }
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8-sig", errors="replace")

    source_text = None
    if source_path:
        sp = Path(source_path)
        if sp.is_file():
            source_text = sp.read_text(encoding="utf-8", errors="replace")

    result = verify_legal_text(
        content,
        current_year=current_year,
        source_text=source_text,
        morph_grounding=morph_grounding,
        high_fidelity=high_fidelity,
        allow_historical=allow_historical,
        claim_ledger_path=claim_ledger_path,
        mcp_cache=mcp_cache,
    )

    # Section 6 Claim Ledger integration
    if claim_ledger_path:
        try:
            from scripts.verify_claim_ledger import verify_claim_ledger_file
        except ImportError:
            try:
                from verify_claim_ledger import verify_claim_ledger_file
            except ImportError:
                verify_claim_ledger_file = None

        if verify_claim_ledger_file is not None:
            ledger_report = verify_claim_ledger_file(claim_ledger_path, synthesis_path=file_path)
            if not ledger_report["ok"]:
                for v in ledger_report["violations"]:
                    result["errors"].append(f"[Claim Ledger 위반] [{v['claimId']}] {v['violation']}")
            result["claim_ledger"] = {
                "ok": ledger_report["ok"],
                "totalClaims": ledger_report["totalClaims"],
                "verifiedCount": ledger_report["verifiedCount"],
            }
        else:
            result["warnings"].append("verify_claim_ledger 모듈을 찾을 수 없어 원장 검증을 건너뛰었습니다.")

    if result["errors"]:
        result["verdict"] = "FAIL"
    elif result["warnings"] and result["verdict"] == "PASS":
        result["verdict"] = "WARN"

    return result


def run_legal_health_check() -> dict:
    """Run comprehensive Section 5.1 & Section 6 legal factuality health check suite.
    Scores 11 categories (10 points each = 110 points total; pass mark 100%).
    Returns health check report with factualityScore and test results.
    """
    tests = [
        # 1. Statutory bounds: Valid statutes must pass
        (
            "statutory_bounds_valid",
            "민법 제1118조 및 형법 제372조에 따라 청구합니다.",
            lambda r: len(r["errors"]) == 0 and len(r["cited_statutes"]) >= 2,
        ),
        # 2. Statutory bounds: Out-of-bound statute article must be blocked
        (
            "statutory_bounds_invalid",
            "민법 제1500조에 의하여 손해배상을 청구합니다.",
            lambda r: any("허위 조문 날조" in e and "1500" in e for e in r["errors"]),
        ),
        # 3. Precedents: Valid precedent format & year must pass, future must fail
        (
            "precedents_sanity",
            "대법원 2020다12345 판결과 대법원 2099다99999 판결을 참조합니다.",
            lambda r: any("미래 연도 판결 인용" in e for e in r["errors"]),
        ),
        # 4. Court names: Fabricated / abolished courts must be blocked
        (
            "court_names_sanity",
            "서울민사지방법원 및 한국연방법원에 소장을 제출합니다.",
            lambda r: any("법원 명칭 날조" in e for e in r["errors"]),
        ),
        # 5. Agency & Academic citations: Fabricated agencies, fake academic journals & future citations must be blocked (Section 5.1 #2 & #3)
        (
            "agency_and_academic_sanity",
            "사이버수사처와 대한인공지능법학회지 및 홍길동 교수의 2099년 학술지 논문 인용에 근거합니다.",
            lambda r: any("정부기관 명칭" in e for e in r["errors"]) and any("학술논문/학술지 날조" in e for e in r["errors"]),
        ),
        # 6. Historical events: Valid historical events must pass
        (
            "historical_events_valid",
            "제1차 갑오개혁 및 동학농민운동 1차 봉기, 을사조약 체결 내역을 고찰한다.",
            lambda r: len(r["errors"]) == 0,
        ),
        # 7. Historical events: Fabricated historical rounds, Hanja numerals & single treaties blocked (Section 5.1 #3)
        (
            "historical_events_invalid",
            "제四차 갑오개혁 및 第4次 갑오개혁, 제2차 을사조약, 제2차 을미개혁, 3차 동학농민운동에 따라 시행되었다.",
            lambda r: any("한국사 사건/조약 날조" in e for e in r["errors"]),
        ),
        # 8. Judicial procedures: Valid legal procedures must pass (including supervisory guidance)
        (
            "judicial_procedures_valid",
            "서울중앙지방검찰청 검사의 약식명령 청구 및 사법경찰관의 구속영장 신청, 대검찰청의 지휘에 의한다.",
            lambda r: len(r["errors"]) == 0,
        ),
        # 9. Judicial procedures: Impossible procedures with long clauses must be blocked (Section 5.1 #4)
        (
            "judicial_procedures_invalid",
            "대검찰청 특별수사본부는 이번 사건과 관련하여 피의자들에 대해 약식명령을 청구하였고 경찰은 관할 법원에 직접 영장을 청구하였다.",
            lambda r: any("불가능한 사법절차 날조" in e for e in r["errors"]),
        ),
        # 10. Evidence-First & Abstention protocol
        (
            "evidence_abstention_protocol",
            "<evidence>원문 증거 100만원 대여 사실</evidence> [INSUFFICIENT_DATA] 추가 증거 필요.",
            lambda r: len(r["errors"]) == 0,
        ),
        # 11. Benign regression: real branch articles and everyday number+Hangul
        #     phrases must not be flagged (review-found false positives)
        (
            "benign_real_articles_pass",
            "정보통신망법 제44조의2 위반 혐의이다. 민법 제2조의2에 따른 신의성실 원칙, "
            "형사소송법 제453조의2, 도로교통법 제52조의2를 인용한다. 2024학년도 3000명이 지원했다.",
            lambda r: len(r["errors"]) == 0,
        ),
    ]

    passed_tests = 0
    total_tests = len(tests)
    test_results = {}

    for name, text, checker in tests:
        res = verify_legal_text(text)
        ok = checker(res)
        if ok:
            passed_tests += 1
            test_results[name] = {"status": "PASS", "errors": res["errors"], "warnings": res["warnings"]}
        else:
            test_results[name] = {"status": "FAIL", "errors": res["errors"], "warnings": res["warnings"]}

    score = int((passed_tests / total_tests) * 100)
    return {
        "suite": "Korean Legal Factuality Health Check Suite (Section 5.1 & 7-8)",
        "score": score,
        "max_score": 100,
        "passed": passed_tests,
        "total": total_tests,
        "status": "PASS" if score == 100 else "FAIL",
        "details": test_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Korean Legal and Precedent Hallucination Verifier"
    )
    parser.add_argument("file", nargs="?", default=None, help="Path to legal document (.md, .txt) to verify")
    parser.add_argument("--health-check", action="store_true", help="Run comprehensive Section 5.1 & Section 6 legal factuality health check suite")
    parser.add_argument("--source", help="Optional path to source evidence/facts for grounding check")
    parser.add_argument("--claim-ledger", help="Optional path to claim-ledger.md for Section 6 verification")
    parser.add_argument("--mcp-cache", help="Optional path to korean_law MCP response JSON cache for corroboration")
    parser.add_argument("--allow-historical", action="store_true", help="Allow historical abolished ministry citations (warning instead of fatal error)")
    parser.add_argument("--morph-grounding", action="store_true", help="Enforce Kiwi morphological hybrid grounding check against source")
    parser.add_argument("--high-fidelity", action="store_true", help="Local High-Fidelity gate: require --source and <evidence> tags plus morpheme overlap (no Vertex API)")
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings as well")
    args = parser.parse_args(argv)

    if args.health_check:
        health_report = run_legal_health_check()
        if args.json:
            print(json.dumps(health_report, ensure_ascii=False, indent=2))
        else:
            print(f"[{health_report['status']}] {health_report['suite']}: {health_report['score']}/{health_report['max_score']} points ({health_report['passed']}/{health_report['total']} passed)")
            for name, d in health_report["details"].items():
                print(f"  - {name}: {d['status']}")
        return 0 if health_report["status"] == "PASS" else 1

    if not args.file:
        parser.print_help()
        return 2

    fresh_warn = check_statute_freshness()
    result = verify_legal_file(
        args.file,
        source_path=args.source,
        morph_grounding=args.morph_grounding,
        high_fidelity=args.high_fidelity,
        allow_historical=args.allow_historical,
        claim_ledger_path=args.claim_ledger,
        mcp_cache=args.mcp_cache,
    )
    if fresh_warn:
        if args.strict and "개월 경과" in fresh_warn:
            result.setdefault("errors", []).append(fresh_warn + " (--strict: FAIL 승격)")
            result["verdict"] = "FAIL"
        else:
            result.setdefault("warnings", []).append(fresh_warn)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["errors"]:
            print(f"[FAIL] Legal hallucination detected ({len(result['errors'])} errors):", file=sys.stderr)
            for err in result["errors"]:
                print(f"  - ERROR: {err}", file=sys.stderr)
        if result["warnings"]:
            print(f"[WARN] Legal warnings ({len(result['warnings'])} warnings):", file=sys.stderr)
            for warn in result["warnings"]:
                print(f"  - WARN: {warn}", file=sys.stderr)
        if result["verdict"] == "PASS":
            print(f"[PASS] {len(result['cited_statutes'])} statutes and {len(result['cited_precedents'])} precedents passed format/bounds checks "
                  "(형식·상한·로컬 대조만 검사 — 1차 원문 인증 아님; source_verified=false).")

    if result["errors"] or (args.strict and result["warnings"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
