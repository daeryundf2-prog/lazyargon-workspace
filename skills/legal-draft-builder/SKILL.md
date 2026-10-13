---
name: legal-draft-builder
description: "사실관계 메모와 입증자료 목록으로 대법원 전자소송 규격 소장·준비서면·고소장·내용증명 초안을 생성하는 스킬. 청구취지/청구원인 분리, 증거 자동 인용(입증방법 결합), 변호사 검토 고지 강제. Triggers: 소장 초안, 준비서면, 고소장 작성, 내용증명, 법률 문서 초안, 답변서, 법률 사실성 검증, 조문 판례 검증, 사법절차 검증, legal-factuality-health."
---

# Legal Draft Builder — 법률 문서 초안 생성기

사실관계와 증거 목록이 정리돼 있으면 전자소송 규격 형식의 법률 문서 **초안**을
만든다. 산출물은 항상 "변호사 검토 전 제출 금지" 고지를 포함하며, 이 고지는
끌 수 없다.

## 핵심 도구

```bash
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/generate_legal_draft.py --input-json draft.json -o 소장_초안.md
```

입력 JSON 구조(필드는 `generate_legal_draft.py` docstring 참조):

```json
{
  "type": "소장",                     // 소장 | 준비서면 | 고소장 | 내용증명 | 업무보고서
  "case_info": {"court": "서울중앙지방법원", "plaintiff": "홍길동", "defendant": "주식회사 XXX"},
  "claims": ["대여금 원금 10,000,000원 및 이에 대한 지연손해금"],
  "facts": [
    {"heading": "1. 대여 관계의 성립",
     "paragraphs": ["...금원을 전달하였다(갑 제1호증). ..."],
     "evidence": []}
  ],
  "evidence_list": [{"label": "갑 제1호증", "title": "차용증"}]
}
```

## 작동 방식

- **청구취지 / 청구원인 분리**: 소장은 `claims`를 청구취지로, `facts`를
  청구원인(사실관계)으로 배치한다. 준비서면은 주장·항변 구조, 고소장은
  범죄사실·고소 이유 구조, 내용증명은 경위·요구 구조.
- **증거 자동 인용**: 본문에 `갑 제1호증`(공백 유무 무관, `호증의 1` 지원)이
  나오면 증거 목록의 서증명을 찾아 `*입증방법: 갑 제1호증, 차용증*` 문장을
  문단 뒤에 결합한다. `facts[].evidence`로 명시 지정도 가능하다.
- **고지 강제**: 헤더와 푸터에 변호사 검토 전제 고지가 들어간다. 제거 금지.

## 법률 사실성 검증 (Anti-Hallucination Gate)

`generate_legal_draft.py`와 `verify_legal_factuality.py`는 `gemini_hallucination_mitigation_deep_dive.md`의 환각 방어 프로토콜을 구현합니다:
1. **Evidence-First 프로토콜 (Section 3.2 #1)**: 사실관계 서술 시 원문 증거 구절을 `<evidence>...</evidence>` 태그로 인용하거나 본문에 명시적 서증(`갑 제1호증`)을 기재하도록 강제합니다 (`--strict-evidence`).
2. **Strict Abstention 프로토콜 (Section 3.2 #2)**: 사실관계가 불명확하거나 증거가 없는 쟁점은 지어내지 않고 `[INSUFFICIENT_DATA]` 또는 `{...}` 플레이스홀더로 기권합니다.
3. **법령 조문 및 판례 상한 경계 (Section 5.1 #1)**: 대한민국 주요 법령의 조문 상한 경계(`STATUTE_BOUNDS`, 예: 민법 1118조, 형법 372조)와 대법원 판례 연도(1948~2026년) 및 사건부호 규칙을 기계적으로 자동 검증합니다.
4. **법원 명칭 날조 차단 (Section 5.1 #2)**: 폐지되거나 실존하지 않는 가짜 법원 명칭(`서울민사지방법원`, `한국연방법원`, `고등대법원` 등)을 즉시 차단합니다.
5. **Kiwi 형태소 하이브리드 그라운딩 (Section 5.2)**: `kiwipiepy` 형태소 분석기를 통해 조사(은/는/이/가/을/를/의)를 분리하고 법률 고유명사 사전을 탑재하여 원본 증거와 초안 간의 형태소 정합성을 감사합니다 (`--morph-grounding`).
6. **Local High-Fidelity 비파라메트릭 모드 (Section 4.2)**: 원본 증거(`--source`)와 `<evidence>` 인용 태그를 강제하며, 형태소 그라운딩 커버리지 70% 미달 시 생성을 차단합니다 (`--high-fidelity`). Vertex API를 호출하지 않는 로컬 게이트입니다.
7. **한국사 사건 및 조약 날조 차단 (Section 5.1 #3)**: 실존하지 않는 역사적 사건 차수(`갑오개혁 4차`, `제四차 갑오개혁`, `第4次 甲午改革`, `제2차 을사조약`, `제2차 을미개혁`, `3차 동학농민운동`, `강화도조약 2차` 등) 및 한자 숫자/단일 조약 날조를 기계적으로 차단합니다.
8. **불가능한 사법 절차 날조 차단 (Section 5.1 #4)**: 실정법/형사소송법/헌법상 성립할 수 없는 절차(`대검찰청의 약식명령 청구`, `경찰의 영장 직접 청구`, `경찰의 직접 기소`, `헌법재판소의 징역형 선고`, `민사소송에서의 징역형 선고` 등)를 장문 복문 수식어와 상관없이 원천 차단합니다.
9. **학술 논문 및 저널 날조 차단 (Section 5.1 #3)**: 가짜 학술지/논문집(`대한인공지능법학회지`, `한국사이버포렌식학회논문집` 등) 및 미래 연도 학술 논문 인용 날조를 기계적으로 차단합니다.

```bash
# 초안 생성 시 High-Fidelity 엄격 증거 및 사실성 검증 수행
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/generate_legal_draft.py --input-json draft.json --source 증거_사실관계.txt --high-fidelity -o 소장_초안.md

# 작성된 마크다운 초안의 조문/판례 사실성 및 Kiwi 형태소 하이브리드 그라운딩 검사
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/verify_legal_factuality.py 소장_초안.md --source 증거_사실관계.txt --morph-grounding --high-fidelity --strict --json

# 법률 사실성 종합 헬스체크 (Section 5.1 및 7-8 전수 검증 100점 감사)
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/verify_legal_factuality.py --health-check --json

# Kiwi 형태소 기반 증거-초안 렉시컬 그라운딩 오버랩 단독 감사
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/korean_morph_grounding.py --source 증거_사실관계.txt --target 소장_초안.md --high-fidelity --json
```

- 허위 조문(예: 민법 제1500조), 미래 판례, 가짜 법원명칭, 가짜 역사 사건, 불가능한 사법 절차 인용 시 exit 1로 생성이 차단됩니다.
- 포스트툴유즈 훅(`legal_factuality_guard.mjs`) 역시 새로 쓰인 법률 문서에 대해 FAIL_CLOSED 원칙으로 위반을 차단합니다.

## HWPX 변환 (제출용 서식이 필요할 때)

마크다운 초안은 `kordoc` MCP의 `generate_document`로 HWPX로 변환할 수 있다
("이 마크다운을 공문서로 뽑아줘"). 변환 후에도 표찰(`stamp_evidence.py`)과
해시(`audit_evidence_integrity.py`)는 원본·제출본 각각 관리한다.

- `type: "업무보고서"`는 행안부 편람 체계(상단 표기: 문서번호·시행일자·수신·
  제목, 본문 `1. → 가.` 위계)로 렌더링된다 — kordoc `ministry` 프리셋과
  동일한 조판 규칙.
- **서식 채우기(계약서·위임장 등)**: `kordoc` MCP ≥4.14.0의
  `fill_form(hwpx-preserve)` 모드는 원본 HWPX의 표 테두리·셀 너비·정렬을
  그대로 보존하고 빈칸 텍스트만 주입한다. 기존 양식 파일을 재사용할 때는
  재조판하지 말고 이 모드를 쓴다.

## 책임 경계

- 법률 요건사실 구성(청구원인 구조), 관할, 소제기 기간, 처벌 희망 여부 등은
  **변호사 판단 사항**이다. 본 스킬은 형식화된 초안을 만들 뿐 법률 자문이
  아니다. 요건사실이 비어 있으면 `{...}` 플레이스홀더로 표시되므로, 사람이
  채운 뒤 검토를 거쳐야 한다.
