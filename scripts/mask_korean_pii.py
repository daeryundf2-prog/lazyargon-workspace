#!/usr/bin/env python3
"""mask_korean_pii.py - 한국형 개인정보 자동 마스킹 (법원 제출본·공문서 비식별화).

텍스트에서 주민등록번호(체크섬 검증), 외국인등록번호(성별코드 5~8), 전화/휴대폰,
계좌번호, 이메일을 탐지해 마스킹한다. kordoc의 redact_document가 HWPX/HWP 원본
서식 보존 마스킹을 담당하므로, 이 스크립트는 텍스트·마크다운·CSV 레이어의
비식별화를 담당한다.

입력 인코딩은 UTF-8(BOM 포함) / UTF-16 / CP949(EUC-KR)를 자동 판별하고, 출력은
원본 인코딩을 그대로 유지한다.

마스킹 규칙 (일반적인 공적 서식 관행):
    주민/외국인번호  901212-1******   (생년월일+성별코드 유지, 뒤 6자리 마스크)
    전화/휴대폰   02-123-**** / 010-1234-****   (말미 4자리 마스크)
    카드번호      ****-****-****-3456   (Luhn 통과 시, 끝 4자리만 유지)
    계좌번호      ***-**-**8901   (3~5그룹, 끝 4자리만 유지)
    이메일        h**@example.com   (로컬파트 첫 글자만 유지)

구분자 정책:
    주민번호는 하이픈 외에 공백·점·무구분자(13자리 연속)도 후보로 잡는다.
    단, 무구분자 후보는 체크섬을 통과해야 확정 마스킹하고, 실패하면
    "의심(rrn_suspect)"으로 보고만 한다. --mask-suspect-rrn으로 강제 가능.
    휴대폰은 구분자 생략을 기본 지원하고, 유선전화의 무구분자 형식은 오탐이
    크므로 --types landline_nodelim 지정 시에만 잡는다.
    카드번호는 Luhn 체크섬 통과분만 마스킹한다(불일치는 card_suspect 보고).

한계 (문서에 명시해야 한다): 사람 이름·주소는 사전 없이는 탐지할 수 없다.
이름 단위 비식별화가 필요하면 ko-pii(MIT) 같은 사전 기반 라이브러리를
보강으로 검토하라.

Exit code: 0 완료 / 2 실행 오류
CLI:
    python scripts/mask_korean_pii.py 증거설명서.md -o 제출용.md
    python scripts/mask_korean_pii.py 데이터.csv --types rrn,phone
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

# ── 주민등록번호 / 외국인등록번호 ──────────────────────────────────
# 6자리 생년월일 - 성별코드 + 일련. 유효 생월일만 후보로 잡아 오탐을 줄인다.
# 성별코드 1~4는 주민등록번호, 5~8은 외국인등록번호다.
#
# 경계 주의: \b를 쓰면 안 된다. 한국어 조사는 띄어쓰기 없이 숫자에 바로
# 붙으므로("901212-1234568임을") 숫자-한글 사이에 단어 경계가 생기지 않는다.
# (\w도 마찬가지 — 한글은 \w다.) 따라서 숫자 경계만 검사한다:
#   (?<!\d) 앞이 숫자가 아니면 시작, (?!\d) 뒤가 숫자가 아니면 끝.
# 이러면 조사가 붙어도 잡히고, 더 긴 숫자열의 일부는 잡지 않는다.
_RRN_RE = re.compile(
    r"(?<!\d)(?P<birth>\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))"
    r"(?P<sep>[-\s.]?)(?P<sex>[1-8])(?P<rest>\d{6})(?!\d)"
)
_RRN_WEIGHTS = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)

# ── 여권 / 운전면허 / 외국인등록번호 (형식매칭+경고 수준) ──────────
# 여권: 구형 M+8자리 (예: M22000000)와 신형 M+3자리+영문+4자리
# (예: M123A4567). 대소문자를 가리지 않는다. 운전면허: 2-2-6-2
# (예: 12-34-567890-12). 외국인등록번호: RRN과 동일 생년월일+구분자+
# 성별코드 5~8+6자리. RRN 가중치로 체크섬 검증을 시도하되 실패해도
# 마스킹한다(틀린 번호≠비개인정보).
_PASSPORT_RE = re.compile(
    r"(?<![A-Za-z0-9])([Mm])(?:\d{8}|\d{3}[A-Za-z]\d{4})(?![A-Za-z0-9])"
)
_DRIVER_LICENSE_RE = re.compile(r"(?<!\d)(\d{2})-(\d{2})-(\d{6})-(\d{2})(?!\d)")
_FOREIGNER_RE = re.compile(
    r"(?<!\d)(?P<birth>\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))"
    r"(?P<sep>[-\s.]?)(?P<sex>[5-8])(?P<rest>\d{6})(?!\d)"
)

# ── 카드번호 (16자리, Luhn 통과분만 확정) ──────────────────────────
# 계좌번호보다 먼저 적용해 4그룹 이중 매칭을 막는다.
_CARD_RE = re.compile(
    r"(?<!\d)(\d{4})[-\s.]?(\d{4})[-\s.]?(\d{4})[-\s.]?(\d{4})(?!\d)"
)

# ── 전화/휴대폰 ─────────────────────────────────────────────────────
# 휴대폰은 구분자 생략까지 지원(01012345678). 유선은 구분자(-, 공백, 점)
# 필수 — 무구분자 유선은 오탐이 커서 landline_nodelim 옵션으로만 켠다.
_MOBILE_RE = re.compile(r"(?<!\d)(01[0136789])[-\s.]?(\d{3,4})[-\s.]?(\d{4})(?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)(02|0[3-6]\d|070|050\d)[-\s.](\d{3,4})[-\s.](\d{4})(?!\d)")
_LANDLINE_NODELIM_RE = re.compile(r"(?<!\d)(02|0[3-6]\d|070|050\d)(\d{3,4})(\d{4})(?!\d)")

# ── 공용/법인 대표번호 화이트리스트 (대륜 개인정보 기본 양식 규칙) ───────
_OFFICIAL_PHONE_WHITELIST = frozenset({
    "02-780-1128",
    "02-780-1129",
})
_OFFICIAL_PHONE_DIGITS_WHITELIST = frozenset({
    re.sub(r"\D", "", p) for p in _OFFICIAL_PHONE_WHITELIST
})


# ── 계좌번호 (은행 무관 3~5그룹 형식, 끝 4자리만 유지) ─────────────
# 첫 그룹은 최소 3자리로 둬 운전면허(2-2-6-2)와의 충돌을 피한다.
_ACCOUNT_RE = re.compile(r"(?<!\d)(\d{3,6})-(\d{2,6})-(\d{2,6})(?:-(\d{2,6}))?(?:-(\d{2,6}))?(?!\d)")
# 날짜(2024-01-16)와 0으로 시작하는 번호판별 값은 계좌로 오탐하지 않는다.
_DATEISH_RE = re.compile(r"^(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")

# ── 이메일 ──────────────────────────────────────────────────────────
# 이메일은 숫자 경계가 아니라 로컬파트/도메인 문자 집합으로 경계를 잡는다
# ("example.com이다"처럼 조사가 붙어도 잡히도록).
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*"
    r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![A-Za-z0-9.-])"
)

# ── 이름 (opt-in: 성씨 사전 + 호칭/라벨 패턴) ─────────────────────
# 맨 앞 글자가 성씨여야 하고, 직함/역할명(사장님·고객님 등)은 제외한다.
# 사전 없는 전수 이름 탐지는 오탐이 커서 기본 타입에 넣지 않는다.
_KOREAN_SURNAMES = frozenset(
    "김이박최정강조윤장임한오서신권황안송류홍전고문양손배백허유남심노하곽"
    "성차주우구민진지엄채원천방공현함변염여추도소석선설마길연위표명기반"
    "왕금옥육인맹제모탁국은편예봉"
)
_NAME_BLOCKLIST = frozenset({
    "사장", "부장", "과장", "차장", "팀장", "대리", "주임", "회장", "부회장",
    "선생", "고객", "회원", "사용자", "담당", "원장", "교수", "박사", "학생",
    "어머", "아버", "할머", "할아버", "손님", "어르신", "여러분", "국민",
    "주민", "시민", "관계자", "관련자", "책임자", "담당자", "작성자",
})
# 라벨 뒤의 이름: "성명: 김철수", "피고인 이영희는" — 라벨은 보존하고 이름만 마스킹.
# 이름 그룹은 비탐욕 — "김철수는"처럼 조사를 이름에 삼키지 않는다.
_LABELED_NAME_RE = re.compile(
    r"(성명|이름|성함|대표자|신청인|피고인|피해자|원고|참고인)[:：]?\s*([가-힣]{2,4}?)"
    r"(?=[은는이가을를도의과와께]|[^가-힣]|$)"
)
# 호칭 붙은 이름: "김철수님", "이영희 씨", "박대리님께서" — 성씨 사전 + 블록리스트로
# 오탐을 걸러내고, 호칭 뒤에는 조사나 비한글이 와야 한다(연속 한글 단어 오인 방지).
_HONORIFIC_NAME_RE = re.compile(
    r"(?<![가-힣])([가-힣]{2,4})\s*(씨|님|귀하)"
    r"(?=[은는이가을를도의과와께한테에게]|[^가-힣]|$)"
)

# ── 주소 (opt-in: 시도+시군구+도로명/지번 구조 필수) ────────────────
# 번지수/호수를 포함하는 완전한 구조만 잡는다 — "서울시 강남구" 같은
# 지역명만으로는 마스킹하지 않는다(개인 식별 정보가 아니므로).
_ADDR_RE = re.compile(
    r"[가-힣]{2,}(?:특별시|광역시|특별자치시|특별자치도|시|도)\s+"
    r"[가-힣]{1,10}(?:시|군|구)\s+"
    r"(?:[가-힣0-9]{1,10}(?:로|길)|[가-힣]{1,10}(?:읍|면|동|리))"
    r"\s*\d+(?:-\d+)*(?:번지?|호)?(?:\s*\d+층|\s*\d+호)?"
)


def validate_rrn(rrn: str) -> bool:
    """주민등록번호 체크섬 검증. 형식 후보가 실제 유효한지 2차 확인용."""
    digits = re.sub(r"\D", "", rrn)
    if len(digits) != 13:
        return False
    total = sum(int(d) * w for d, w in zip(digits[:12], _RRN_WEIGHTS))
    return (11 - total % 11) % 10 == int(digits[12])


def validate_card(num: str) -> bool:
    """Luhn 체크섬 — 16자리 카드번호 후보를 확정/의심으로 가른다."""
    digits = re.sub(r"\D", "", num)
    if len(digits) != 16:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def mask_keep_last4(s: str) -> str:
    """숫자 그룹 구조를 유지한 채 끝 4자리만 남기고 전부 *로 가린다."""
    seen = 0
    out = []
    for ch in reversed(s):
        if ch.isdigit():
            seen += 1
            out.append(ch if seen <= 4 else "*")
        else:
            out.append(ch)
    return "".join(reversed(out))


def mask_text(text: str, types: set[str], *, mask_suspect_rrn: bool = False) -> tuple[str, dict]:
    """텍스트를 마스킹하고 (마스킹본, 통계)를 반환한다.

    mask_suspect_rrn: True면 구분자 없는 13자리 주민번호 후보가 체크섬에
    실패해도 마스킹한다. 기본값(False)은 의심으로만 보고하고 원문을 유지한다.
    """
    stats: dict = {"rrn": 0, "rrn_bad_checksum": 0, "rrn_suspect": 0,
                   "phone": 0, "card": 0, "card_suspect": 0,
                   "account": 0, "account_skipped_date": 0, "email": 0,
                   "passport": 0, "driver_license": 0, "foreigner": 0, "foreigner_bad_checksum": 0,
                   "name": 0, "name_skipped_role": 0, "address": 0}

    def _rrn(m: re.Match) -> str:
        candidate = m.group(0)
        # 무구분자 13자리는 오탐 위험이 크다 — 체크섬 통과분만 확정 마스킹하고
        # 불일치는 의심으로 보고만 한다(--mask-suspect-rrn으로 강제 가능).
        if m.group("sep") == "" and not (mask_suspect_rrn or validate_rrn(candidate)):
            stats["rrn_suspect"] += 1
            return candidate
        stats["rrn"] += 1
        if m.group("sex") in "5678":
            # 외국인등록번호: 공식 체크섬 체계가 주민번호와 다르다. 여기서는
            # 표준 가중치 검증을 돌리지 않고 형식만으로 마스킹한다.
            return f"{m.group('birth')}-{m.group('sex')}******"
        if not validate_rrn(candidate):
            # 체크섬이 틀려도 마스킹은 한다 — 틀린 번호가 개인정보가 아니라는 뜻이 아니다.
            stats["rrn_bad_checksum"] += 1
        return f"{m.group('birth')}-{m.group('sex')}******"

    if "rrn" in types:
        text = _RRN_RE.sub(_rrn, text)

    def _phone(m: re.Match) -> str:
        candidate = m.group(0)
        digits = re.sub(r"\D", "", candidate)
        if candidate in _OFFICIAL_PHONE_WHITELIST or digits in _OFFICIAL_PHONE_DIGITS_WHITELIST:
            return candidate
        stats["phone"] += 1
        return f"{m.group(1)}-{m.group(2)}-****"

    if "phone" in types:
        text = _MOBILE_RE.sub(_phone, text)
        text = _PHONE_RE.sub(_phone, text)
        if "landline_nodelim" in types:
            text = _LANDLINE_NODELIM_RE.sub(_phone, text)

    def _card(m: re.Match) -> str:
        candidate = m.group(0)
        if not validate_card(candidate):
            stats["card_suspect"] += 1
            return candidate  # Luhn 불일치 — 카드로 단정하지 않고 보고만 한다
        stats["card"] += 1
        digits = re.sub(r"\D", "", candidate)
        return f"****-****-****-{digits[-4:]}"

    if "card" in types:
        # 카드는 계좌보다 먼저 적용 — 4그룹 번호를 계좌로 오분류하지 않는다.
        text = _CARD_RE.sub(_card, text)

    def _account(m: re.Match) -> str:
        candidate = m.group(0)
        if _DATEISH_RE.match(candidate):
            stats["account_skipped_date"] += 1
            return candidate  # 날짜로 보임 — 손대지 않는다
        stats["account"] += 1
        return mask_keep_last4(candidate)

    if "account" in types:
        text = _ACCOUNT_RE.sub(_account, text)

    def _email(m: re.Match) -> str:
        stats["email"] += 1
        return f"{m.group(1)}**@{m.group(2)}"

    if "email" in types:
        text = _EMAIL_RE.sub(_email, text)

    def _passport(m: re.Match) -> str:
        stats["passport"] += 1
        return f"{m.group(1)}********"  # 형식매칭+경고 수준: 원번호 미보존, 선행문자 대소문자 유지

    if "passport" in types:
        text = _PASSPORT_RE.sub(_passport, text)

    def _driver(m: re.Match) -> str:
        stats["driver_license"] += 1
        return f"{m.group(1)}-{m.group(2)}-******-**"

    if "driver_license" in types:
        text = _DRIVER_LICENSE_RE.sub(_driver, text)

    def _foreigner(m: re.Match) -> str:
        candidate = m.group(0)
        if m.group("sep") == "" and not (mask_suspect_rrn or validate_rrn(candidate)):
            stats["rrn_suspect"] += 1
            return candidate
        stats["foreigner"] += 1
        if not validate_rrn(candidate):
            # RRN 동일 가중치 검증 시도 — 실패해도 마스킹(경고 수준)
            stats["foreigner_bad_checksum"] += 1
        return f"{m.group('birth')}-{m.group('sex')}******"

    if "foreigner" in types:
        text = _FOREIGNER_RE.sub(_foreigner, text)

    def _labeled_name(m: re.Match) -> str:
        name = m.group(2)
        if name[0] not in _KOREAN_SURNAMES or name in _NAME_BLOCKLIST:
            stats["name_skipped_role"] += 1
            return m.group(0)
        stats["name"] += 1
        prefix = m.group(0).rsplit(name, 1)[0]  # "성명: " 등 라벨+구분자를 그대로 보존
        return f"{prefix}{name[0]}{'*' * (len(name) - 1)}"

    def _honorific_name(m: re.Match) -> str:
        name = m.group(1)
        if name[0] not in _KOREAN_SURNAMES or name in _NAME_BLOCKLIST:
            stats["name_skipped_role"] += 1
            return m.group(0)
        stats["name"] += 1
        return f"{name[0]}{'*' * (len(name) - 1)}{m.group(0)[len(name):]}"

    if "name" in types:
        text = _LABELED_NAME_RE.sub(_labeled_name, text)
        text = _HONORIFIC_NAME_RE.sub(_honorific_name, text)

    def _addr(m: re.Match) -> str:
        stats["address"] += 1
        head = m.group(0).split(None, 1)[0]  # 시/도 단위까지만 보존
        return f"{head} ***"

    if "address" in types:
        text = _ADDR_RE.sub(_addr, text)

    return text, stats


ALL_TYPES = {"rrn", "phone", "card", "account", "email", "passport", "driver_license", "foreigner",
             "landline_nodelim", "name", "address"}
DEFAULT_TYPES = ALL_TYPES - {"landline_nodelim", "name", "address"}


class PiiVault:
    """Pre-forward Anonymization Vault (ko-pii pattern).

    마스킹 대신 가역적 토큰([PII_RRN_1], [PII_PHONE_1] 등)으로 치환하여
    LLM에 전달하고, LLM 응답을 받은 뒤 원본 값으로 안전하게 복원할 수 있게 한다.
    또한 평문 노출 없이 SHA-256 감사 로그를 출력할 수 있다.
    """

    def __init__(self, salt: str | None = None) -> None:
        self.salt = salt or os.urandom(16).hex()
        self._token_to_value: dict[str, str] = {}
        self._value_to_token: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def get_or_create_token(self, pii_type: str, raw_value: str) -> str:
        if raw_value in self._value_to_token:
            return self._value_to_token[raw_value]
        idx = self._counters.get(pii_type, 0) + 1
        self._counters[pii_type] = idx
        token = f"[PII_{pii_type.upper()}_{idx}]"
        self._token_to_value[token] = raw_value
        self._value_to_token[raw_value] = token
        return token

    def tokenize_text(self, text: str, types: set[str], *, mask_suspect_rrn: bool = False) -> tuple[str, dict]:
        stats: dict = {"rrn": 0, "rrn_bad_checksum": 0, "rrn_suspect": 0,
                       "phone": 0, "card": 0, "card_suspect": 0,
                       "account": 0, "account_skipped_date": 0, "email": 0,
                       "passport": 0, "driver_license": 0, "foreigner": 0, "foreigner_bad_checksum": 0,
                       "name": 0, "name_skipped_role": 0, "address": 0}

        def _rrn(m: re.Match) -> str:
            val = m.group(0)
            if m.group("sep") == "" and not (mask_suspect_rrn or validate_rrn(val)):
                stats["rrn_suspect"] += 1
                return val
            stats["rrn"] += 1
            return self.get_or_create_token("rrn", val)

        if "rrn" in types:
            text = _RRN_RE.sub(_rrn, text)

        def _phone(m: re.Match) -> str:
            val = m.group(0)
            digits = re.sub(r"\D", "", val)
            if val in _OFFICIAL_PHONE_WHITELIST or digits in _OFFICIAL_PHONE_DIGITS_WHITELIST:
                return val
            stats["phone"] += 1
            return self.get_or_create_token("phone", val)

        if "phone" in types:
            text = _MOBILE_RE.sub(_phone, text)
            text = _PHONE_RE.sub(_phone, text)
            if "landline_nodelim" in types:
                text = _LANDLINE_NODELIM_RE.sub(_phone, text)

        def _card(m: re.Match) -> str:
            val = m.group(0)
            if not validate_card(val):
                stats["card_suspect"] += 1
                return val
            stats["card"] += 1
            return self.get_or_create_token("card", val)

        if "card" in types:
            text = _CARD_RE.sub(_card, text)

        def _account(m: re.Match) -> str:
            val = m.group(0)
            if _DATEISH_RE.match(val):
                return val
            stats["account"] += 1
            return self.get_or_create_token("account", val)

        if "account" in types:
            text = _ACCOUNT_RE.sub(_account, text)

        def _email(m: re.Match) -> str:
            val = m.group(0)
            stats["email"] += 1
            return self.get_or_create_token("email", val)

        if "email" in types:
            text = _EMAIL_RE.sub(_email, text)

        def _passport(m: re.Match) -> str:
            val = m.group(0)
            stats["passport"] += 1
            return self.get_or_create_token("passport", val)

        if "passport" in types:
            text = _PASSPORT_RE.sub(_passport, text)

        def _driver(m: re.Match) -> str:
            val = m.group(0)
            stats["driver_license"] += 1
            return self.get_or_create_token("driver_license", val)

        if "driver_license" in types:
            text = _DRIVER_LICENSE_RE.sub(_driver, text)

        def _foreigner(m: re.Match) -> str:
            val = m.group(0)
            if m.group("sep") == "" and not (mask_suspect_rrn or validate_rrn(val)):
                stats["rrn_suspect"] += 1
                return val
            stats["foreigner"] += 1
            return self.get_or_create_token("foreigner", val)

        if "foreigner" in types:
            text = _FOREIGNER_RE.sub(_foreigner, text)

        def _labeled_name(m: re.Match) -> str:
            name = m.group(2)
            if name[0] not in _KOREAN_SURNAMES or name in _NAME_BLOCKLIST:
                stats["name_skipped_role"] += 1
                return m.group(0)
            stats["name"] += 1
            return m.group(0).replace(name, self.get_or_create_token("name", name), 1)

        def _honorific_name(m: re.Match) -> str:
            name = m.group(1)
            if name[0] not in _KOREAN_SURNAMES or name in _NAME_BLOCKLIST:
                stats["name_skipped_role"] += 1
                return m.group(0)
            stats["name"] += 1
            return m.group(0).replace(name, self.get_or_create_token("name", name), 1)

        if "name" in types:
            text = _LABELED_NAME_RE.sub(_labeled_name, text)
            text = _HONORIFIC_NAME_RE.sub(_honorific_name, text)

        def _addr(m: re.Match) -> str:
            stats["address"] += 1
            return self.get_or_create_token("address", m.group(0))

        if "address" in types:
            text = _ADDR_RE.sub(_addr, text)

        return text, stats

    def detokenize_text(self, text: str) -> str:
        for token, original in self._token_to_value.items():
            text = text.replace(token, original)
        return text

    def save(self, path: str) -> None:
        """토큰↔원본 매핑을 JSON으로 저장한다. 이 파일은 비밀 취급이다."""
        payload = {
            "_warning": "PII 복원 매핑 파일 — git에 커밋하지 말 것 (.gitignore: *.pii-vault.json)",
            "salt": self.salt,
            "token_to_value": self._token_to_value,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "PiiVault":
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        vault = cls(salt=payload.get("salt"))
        vault._token_to_value = dict(payload.get("token_to_value", {}))
        vault._value_to_token = {v: k for k, v in vault._token_to_value.items()}
        return vault

    def export_audit(self) -> dict:
        return {
            "token_count": len(self._token_to_value),
            "tokens": [
                {
                    "token": t,
                    "sha256": hashlib.sha256((val + self.salt).encode()).hexdigest(),
                }
                for t, val in self._token_to_value.items()
            ],
        }


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """바이트를 디코딩한다. (텍스트, 재인코딩에 쓸 인코딩명) 반환.

    국내 공문서·은행 CSV가 흔히 쓰는 CP949/EUC-KR도 지원한다. 손실 있는
    errors="replace"로 읽으면 본문이 U+FFFD로 훼손되므로, 어느 인코딩으로도
    디코드하지 못하면 예외를 던져 실행 오류(exit 2)로 끝낸다 — 유실보다 실패.
    """
    import codecs

    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        return raw.decode("utf-16"), "utf-16"
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp949"), "cp949"
    except UnicodeDecodeError as e:
        raise ValueError("utf-8 / cp949 어느 쪽으로도 디코드할 수 없습니다") from e


def encode_text(text: str, encoding: str) -> bytes:
    return text.encode(encoding)


def render_report(stats: dict, source: str) -> str:
    lines = ["## 비식별화 처리 결과\n"]
    lines.append(f"- **원본:** {source}")
    lines.append(f"- **주민등록번호·외국인등록번호:** {stats['rrn']}건 마스킹 (체크섬 불일치 {stats['rrn_bad_checksum']}건 — 형식만 맞는 값이 포함되어 있을 수 있으니 원본 확인 요망, 무구분자 의심 {stats.get('rrn_suspect', 0)}건 미마스킹)")
    lines.append(f"- **전화/휴대폰:** {stats['phone']}건")
    lines.append(f"- **카드번호:** {stats.get('card', 0)}건 마스킹 (Luhn 불일치 의심 {stats.get('card_suspect', 0)}건 미마스킹)")
    lines.append(f"- **계좌번호:** {stats['account']}건 (날짜로 판별해 유지 {stats['account_skipped_date']}건)")
    lines.append(f"- **이메일:** {stats['email']}건")
    lines.append(f"- **여권(M+8자리):** {stats.get('passport', 0)}건 마스킹 (형식매칭+경고 수준 — 원본 확인 요망)")
    lines.append(f"- **운전면허(2-2-6-2):** {stats.get('driver_license', 0)}건 마스킹 (형식매칭+경고 수준 — 원본 확인 요망)")
    lines.append(f"- **외국인등록번호(성별코드 5~8):** {stats.get('foreigner', 0)}건 마스킹 (체크섬 불일치 {stats.get('foreigner_bad_checksum', 0)}건 — 형식만 맞는 값이 포함되어 있을 수 있으니 원본 확인 요망)")
    lines.append("\n> 사람 이름·주소는 이 도구가 탐지하지 못한다. 필요하면 사전 기반 도구(ko-pii 등)를 보강으로 사용하고, 최종 제출본은 사람이 1회 더 훑어야 한다.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="한국형 개인정보 자동 마스킹 (주민번호/전화/카드/계좌/이메일/여권/운전면허/외국인번호)")
    p.add_argument("input", help="입력 텍스트/마크다운/CSV 파일")
    p.add_argument("--output", "-o", default="", help="마스킹본 저장 경로 (미지정 시 stdout)")
    p.add_argument("--report", default="", help="처리 결과 리포트 저장 경로 (선택)")
    p.add_argument("--types", default=",".join(sorted(DEFAULT_TYPES)), help="쉼표 구분 타입 (opt-in: landline_nodelim, name, address)")
    p.add_argument("--mask-suspect-rrn", action="store_true", help="구분자 없는 주민번호 후보를 체크섬 불일치여도 마스킹")
    p.add_argument("--vault", default="", help="가역 토큰 매핑을 저장할 vault JSON 경로 (*.pii-vault.json 권장)")
    p.add_argument("--unmask", action="store_true", help="--vault 매핑으로 토큰을 원본 값으로 복원")
    args = p.parse_args(argv)

    types = {t.strip() for t in args.types.split(",") if t.strip()}
    unknown = types - ALL_TYPES
    if unknown:
        print(f"error: 알 수 없는 타입: {sorted(unknown)} (가능: {sorted(ALL_TYPES)})", file=sys.stderr)
        return 2
    if not os.path.isfile(args.input):
        print(f"error: 파일을 찾을 수 없습니다: {args.input}", file=sys.stderr)
        return 2
    if args.unmask and not args.vault:
        print("error: --unmask는 --vault 매핑 파일이 필요합니다", file=sys.stderr)
        return 2

    with open(args.input, "rb") as f:
        raw = f.read()
    try:
        text, encoding = decode_bytes(raw)
    except ValueError as e:
        print(f"error: {args.input}: {e} (utf-8 / utf-16 / cp949만 지원)", file=sys.stderr)
        return 2

    if args.unmask:
        try:
            vault = PiiVault.load(args.vault)
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: vault 매핑을 읽을 수 없습니다: {args.vault}: {e}", file=sys.stderr)
            return 2
        masked = vault.detokenize_text(text)
        stats = {}
        report = f"## 복원 처리 결과\n\n- **원본:** {args.input}\n- **복원된 토큰:** {len(vault._token_to_value)}건\n"
    elif args.vault:
        vault = PiiVault()
        masked, stats = vault.tokenize_text(text, types, mask_suspect_rrn=args.mask_suspect_rrn)
        vault.save(args.vault)
        report = render_report(stats, args.input)
    else:
        masked, stats = mask_text(text, types, mask_suspect_rrn=args.mask_suspect_rrn)
        report = render_report(stats, args.input)

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        # 원본 인코딩을 보존한다 — cp949 입력을 utf-8로 재작성하면 문서 무결성이 깨진다.
        with open(args.output, "wb") as f:
            f.write(encode_text(masked, encoding))
        print(f"[OK] 마스킹본 저장: {args.output} (encoding: {encoding})")
        if args.report:
            with open(args.report, "w", encoding="utf-8") as f:
                f.write(report + "\n")
        print(report, file=sys.stderr)
    else:
        print(masked)
        print("\n" + report, file=sys.stderr)
    return 0


# ── 콘솔 하드닝 (#84) ───────────────────────────────────────────────
import os as _os  # noqa: E402
import sys as _sys  # noqa: E402

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import console as _console  # noqa: E402

if __name__ == "__main__":
    _console.force_utf8_console()
    raise SystemExit(main())
