"""eval_baseline.py가 쓰는 결정적 지표 어서션 레이어.

metrics.py(v1)·metrics_v2.py(v2)의 신호 함수를 eval 스위트가 기대하는
단일 인터페이스로 묶는 어댑터다. 패턴 규칙을 여기서 새로 정의하지 않는다 —
SSOT는 metrics* 이고, 이 모듈은 이름 → 함수 디스패치와 eval 전용 불변식
(보호 토큰 보존·register 보존)만 담당한다.

eval_baseline.py가 sys.path에 이 디렉터리와 tests/를 넣고
`import humanize_asserts as ha` 로 임포트한다.
"""

from __future__ import annotations

import re
import unicodedata

import metrics as _m1
import metrics_v2 as _m2

# eval_baseline.SIGNAL_NAMES 이 참조하는 이름만 등록한다.
# 값은 text 하나를 받는 호출 가능 객체여야 한다.
SIGNALS = {
    "conclusion_pivot_count": _m1.conclusion_pivot_count,
    "safe_balance_count": _m1.safe_balance_count,
    "double_passive_count": _m2.double_passive_count,
    "by_passive_count": _m2.by_passive_count,
    "have_make_literal_count": _m2.have_make_literal_count,
    "double_particle_count": _m2.double_particle_count,
}


def signal(text: str, name: str) -> float:
    """이름으로 결정적 신호를 계산해 반환한다.

    모르는 이름은 ValueError — eval_baseline은 예외를 잡아 None으로
    기록하지만, 오타가 조용히 0으로 기록되는 사고를 막으려 명시적으로
    실패하게 만든다.
    """
    fn = SIGNALS.get(name)
    if fn is None:
        raise ValueError(f"unknown signal name: {name!r} (known: {sorted(SIGNALS)})")
    return float(fn(text))


def change_rate(src: str, out: str) -> float:
    """철칙 #4 변경률 (0~1). SSOT인 metrics_v2.change_rate 에 위임한다.

    verify_change_rate.py(게이트 CLI)와 같은 함수를 쓰므로 eval 수치와
    게이트 판정이 어긋날 수 없다.
    """
    return _m2.change_rate(src, out)


def missing_protected_tokens(out: str, protected: list[str]) -> list[str]:
    """윤문본에서 사라진 보호 토큰(수치·고유명사·직접 인용)을 반환한다.

    빈 리스트 = 보존 완료. 비교는 NFC 정규화 후 substring 포함으로 한다.
    토큰 경계까지 보려는 유혹이 있지만 보호 토큰은 조사가 붙어 재등장하는
    경우(「2026년」→「2026년의」)가 오히려 일반적이므로 substring이 맞다.
    공백 접기 변형도 함께 본다(마크다운 줄바꿈으로 토큰이 쪼개진 경우).
    """
    if not protected:
        return []
    hays = {_norm(out), _norm(out).replace(" ", "")}
    missing: list[str] = []
    for tok in protected:
        needles = {_norm(tok), _norm(tok).replace(" ", "")}
        if not any(n in hay for n in needles for hay in hays):
            missing.append(tok)
    return missing


# register(문체 등급) 판정 — SKILL.md "register 보존 — 양방향"의 eval 구현.
# 문장 종결어미로 합쇼체/해요체/평서체를 분류하고 다수파를 고른다.
# 격식 상향('-했-'→'-하였-')·구어 종결 보존을 숫자로 검증하기 위한 최소판정이다.
_FORMAL_END_RE = re.compile(
    r"(?:니다|십시오|합시다|답시다)[.!?…]*\s*$"
)
_POLITE_END_RE = re.compile(
    r"(?:어요|아요|해요|네요|에요|예요|세요|군요|까요|지요|거든요|인데요|이에요|걸요|가요|죠)[.!?…]*\s*$"
)
_PLAIN_END_RE = re.compile(r"(?:다|인가|는가|은가|냐)[.!?…]*\s*$")


def register_of(text: str) -> str:
    """텍스트의 지배 종결 스타일을 반환한다.

    반환값: "formal"(합니다체) | "polite"(해요체) | "plain"(평서 ~다체)
    | "mixed"(최다 득점 동률) | "unknown"(종결어미 부족).

    문장별로 formal → polite → plain 순으로 처음 맞는 분류에 한 표씩
    준다(술어 어미는 한 문장에 하나가 지배적이므로 충분하다).
    """
    sents = _m1._split_sentences(text)
    counts = {"formal": 0, "polite": 0, "plain": 0}
    for s in sents:
        s = s.strip()
        if not s:
            continue
        if _FORMAL_END_RE.search(s):
            counts["formal"] += 1
        elif _POLITE_END_RE.search(s):
            counts["polite"] += 1
        elif _PLAIN_END_RE.search(s):
            counts["plain"] += 1
    top = max(counts.values())
    if top == 0:
        return "unknown"
    winners = [k for k, v in counts.items() if v == top]
    if len(winners) > 1:
        return "mixed"
    return winners[0]


def _norm(text: str) -> str:
    """NFC 정규화 + 주변 공백 제거. sanitize_text.py와 같은 정규형을 쓴다."""
    return unicodedata.normalize("NFC", text).strip()
