---
name: court-ruling-analyzer
description: "판결문 구조 분석 스킬 — 주문/이유/사실 섹션 분할, 인용 법령 조문·선고 형식 판례 전수 추출, 쟁점 요약표 골격 생성. Triggers: 판결문 분석, 판례 요약, 쟁점 정리, 판시사항 추출, 판결문 섹션."
---

# Court Ruling Analyzer — 판결문 구조 분석

수십 장의 판결문에서 **구조**(주문·이유·사실), **인용 근거**(법령 조문·선고
형식 판례)를 결정적으로 뽑고, 쟁점 요약표 골격을 만든다. 판단 요지의 "요약"은
에이전트가 원문 인용으로 채우고, 구조·목록은 스크립트가 SSOT다.

## 핵심 도구

```bash
# 1. 텍스트 확보 (스캔본이면 먼저 OCR — roadmap)
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/parse_korean_doc.py 판결문.pdf -o 판결문.json
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/analyze_court_ruling.py 판결문.txt -o 분석.md

# 2. 사실성 및 Kiwi 형태소 하이브리드 그라운딩 검증 포함 분석
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/analyze_court_ruling.py 판결문.txt --verify --source 원본판결.txt --morph-grounding -o 분석_검증완료.md

# 3. High-Fidelity 비파라메트릭 엄격 검증 (조문·판례 날조 및 미지원 용어 원천 차단)
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/verify_legal_factuality.py 분석_검증완료.md --source 판결문.txt --morph-grounding --high-fidelity --strict

# 4. 섹션 원문까지 포함한 JSON (에이전트 요약 입력용, --verify 지원)
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/analyze_court_ruling.py 판결문.txt --json --verify --high-fidelity --source 원본판결.txt -o 구조.json
```

## 산출물

1. **섹션 구조 표** — 【주 문】·【이 유】·【사 실】·【증 거】의 위치와 분량
2. **주장·항변·판단 구간** — "원고의 주장"·"피고의 항변"·"…에 대한 판단" 형태
3. **인용 법령** — 「민법 제750조」 형태 조문 전수 (출현 순, 중복 없음)
4. **인용 판례** — 「대법원 2023. 5. 26. 선고 … 판결」 형식 전수
5. **쟁점 요약표 골격** — 쟁점/원고 주장/피고 주장/법원 판단 4열

## 유의

- 판결문 양식은 법원·연도마다 다르다. 헤더를 못 찾으면 "전문" 1개 섹션으로
  반환하므로, 그 경우 원문을 직접 보고 구조를 확인한다.
- 추출된 법령·판례 **인용은 실제 조문·판결문으로 대조**해야 한다 — legal-case-search
  스킬(`lazyforensic_korean_law` 또는 `lazyantigravity_korean_law_offline`)로 원문을 가져와 검증하라. AI가 조문 번호를 지어내는
  할루시네이션은 이 대조로만 잡힌다.
- 쟁점표의 "법원 판단" 열은 원문 인용을 원칙으로 한다. 요약·윤문이 필요하면
  humanize-korean을 쓰되 법률 용어는 유지한다.
