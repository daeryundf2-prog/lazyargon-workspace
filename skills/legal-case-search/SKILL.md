---
name: legal-case-search
description: "국가법령정보센터 및 대법원 판례 검색, 위법성 요건(정보통신망법, 개인정보보호법, 형법 등) 대조 스킬. Triggers: 판례 검색, 법령 조회, 법률 대조, 위법성 검토, korean-law."
---

# Legal Case & Statute Search (Korean Law)

국가법령정보센터 Open API 및 `lazyargon-workspace` 내장 법률 MCP(`korean_law`)를 연동하여 포렌식 증거 사실관계와 법률 조문, 대법원 판례 요지를 대조합니다.

## 핵심 도구

- **`korean_law` MCP (`./scripts/korean_law_mcp.mjs` — `LAW_OC` 환경변수 및 로컬 빌드 필요, 미설정 시 fail-closed):**
  - `search_law`: 법령 검색 (정확매칭 + 개정 이력, 법령 MST 반환)
  - `get_law_text`: 법령 MST의 본문·조문 전문 조회
  - `search_decisions` / `get_decision_text`: 판례 검색 및 판결문 전문 조회
  - 기타: `ordinance_radar`, `get_annexes`, `legal_research`, `legal_analysis`, `discover_tools`, `execute_tool`
- **오프라인 조문 상한·판례 형식 기계적 검증 (`verify_legal_factuality.py`):**
  - `LAW_OC` 미설정 또는 오프라인 환경에서는 조문을 임의 생성하지 않고 `missing-LAW_OC` / `missing-build` 상태를 고지하며, 작성된 문서의 인용 조문 번호·판례 번호는 `verify_legal_factuality.py`로 검증합니다.

> 세션 런타임의 `korean_law`가 `ready`일 때만 `korean_law` MCP를 호출합니다.
> **절대 법률 조문을 조작하거나 임의 창작하지 마십시오 (Never fabricate statutes).**
> 작성된 모든 법률 검토 결과물은 `verify_legal_factuality.py`를 통해 실존 법령 상한선 및 판례 번호 규칙에 대해 기계적으로 전수 감사됩니다.

## 기계적 사실성 및 High-Fidelity 게이트

```bash
# 사실성 및 Kiwi 형태소 하이브리드 그라운딩 검증
${PLUGIN_ROOT:-.}/scripts/py ${PLUGIN_ROOT:-.}/scripts/verify_legal_factuality.py 법률검토서.md --source 사실관계.txt --morph-grounding --high-fidelity --strict --json

# Kiwi 형태소 렉시컬 그라운딩 단독 분석
${PLUGIN_ROOT:-.}/scripts/py ${PLUGIN_ROOT:-.}/scripts/korean_morph_grounding.py --source 사실관계.txt --target 법률검토서.md --high-fidelity --json
```

## 설치 및 상태 점검

```bash
# korean_law MCP 빌드 및 LAW_OC 상태 점검
node scripts/setup_korean_law.mjs --check

# 최초 1회 korean-law-mcp 로컬 클론 및 빌드 (korean-law-mcp/build/index.js 생성)
node scripts/setup_korean_law.mjs
```

## 주요 위법성 대조 영역
- **정보통신망법 제48조/제49조:** 비밀침해, 악성프로그램 유포, 정보통신망 침입.
- **부정경쟁방지법 제18조:** 영업비밀 취득·사용·누설 행위.
- **개인정보보호법 제71조:** 개인정보 무단 유출 및 부정 이용.
- **형법 제314조/제316조:** 업무방해, 비밀침해.
