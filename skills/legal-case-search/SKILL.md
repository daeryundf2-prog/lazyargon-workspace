---
name: legal-case-search
description: "국가법령정보센터 및 대법원 판례 검색, 위법성 요건(정보통신망법, 개인정보보호법, 형법 등) 대조 스킬. Triggers: 판례 검색, 법령 조회, 법률 대조, 위법성 검토, korean-law."
---

# Legal Case & Statute Search (Korean Law)

국가법령정보센터 Open API 및 시맨틱 법률 MCP(`korean-law` / `kr-law-mcp`)를 연동하여 포렌식 증거 사실관계와 법률 조문, 대법원 판례 요지를 대조합니다.

## 핵심 도구

- **`lazyforensic_korean_law` (live API — `LAW_OC` 환경변수 필요, 현재 미설정 시 비활성화):**
  - `search_law`: 법령 검색 (정확매칭 + 개정 이력, 법령 MST 반환)
  - `get_law_text`: 법령 MST의 본문·조문 전문 조회
  - `search_decisions` / `get_decision_text`: 판례 검색 및 판결문 전문 조회
  - 기타: `ordinance_radar`, `get_annexes`, `legal_research`, `legal_analysis`, `discover_tools`, `execute_tool`
- **`lazyantigravity_korean_law_offline` (offline landmark DB — 항상 사용 가능):**
  - `lookup_statute`: 주요 실정법 랜드마크 조문 오프라인 조회
  - `lookup_precedent`: 주요 판례 랜드마크 요지 오프라인 조회

> 실시간 법제처 API가 필요하고 `LAW_OC`가 설정된 환경에서는 `lazyforensic_korean_law`를 직접 호출하고, API 키가 없거나 오프라인 환경에서는 `lazyantigravity_korean_law_offline`을 직접 호출합니다.
> **절대 법률 조문을 조작하거나 임의 창작하지 마십시오 (Never fabricate statutes).**
> 작성된 모든 법률 검토 결과물은 `verify_legal_factuality.py`를 통해 실존 법령 상한선 및 판례 번호 규칙에 대해 기계적으로 전수 감사됩니다.

## 기계적 사실성 및 High-Fidelity 게이트

```bash
# 사실성 및 Kiwi 형태소 하이브리드 그라운딩 검증
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/verify_legal_factuality.py 법률검토서.md --source 사실관계.txt --morph-grounding --high-fidelity --strict --json

# Kiwi 형태소 렉시컬 그라운딩 단독 분석
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/korean_morph_grounding.py --source 사실관계.txt --target 법률검토서.md --high-fidelity --json
```

## 설치

```bash
# 별도 플러그인 (저장소 URL에 하이픈 있음, 플러그인 디렉터리명은 하이픈 없음)
git clone https://github.com/daeryundf2-prog/lazyforensic.git ~/.gemini/config/plugins/lazyforensic

# korean-law-mcp 빌드 (build/index.js 생성)
cd ~/.gemini/config/plugins/lazyforensic/korean-law-mcp
npm install && npm run build
```

## 주요 위법성 대조 영역
- **정보통신망법 제48조/제49조:** 비밀침해, 악성프로그램 유포, 정보통신망 침입.
- **부정경쟁방지법 제18조:** 영업비밀 취득·사용·누설 행위.
- **개인정보보호법 제71조:** 개인정보 무단 유출 및 부정 이용.
- **형법 제314조/제316조:** 업무방해, 비밀침해.
