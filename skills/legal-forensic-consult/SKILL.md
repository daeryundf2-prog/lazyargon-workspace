---
name: legal-forensic-consult
description: 위임계약 서식 빈칸·법령/판례 조회 보조. 법률 자문·적법/위법 단정·조문 창작에는 쓰지 말 것.
---

# legal-forensic-consult: 서식·법령 조회 보조

계약서 초안 작성과 `korean_law` MCP를 통한 법령/판례 **조회**를 돕는다.

이 스킬은 법률 자문이 아니다. 적법성, 위법수집증거, 압수수색 대응을 결정하지 않는다.  
변호사 검토 없이 법원/수사기관에 제출할 의견서로 쓰지 않는다.

## 사용

- 위임 계약 서식 빈칸 채우기 (`templates/contract_template.md`)
- 법령명·조문·판례번호 조회 후 **원문 확인**
- 인용 검증 도구가 있으면 환각 조문을 걸러 보기

## 하지 않는 일

- "최신 판례에 따르면 적법/위법" 단정
- 주민등록번호 수집
- MCP가 빌드되지 않았거나 `LAW_OC`가 없을 때 조문을 지어내기

세션 런타임의 `korean_law` 상태를 먼저 본다.

- `missing-build`: `node scripts/setup_korean_law.mjs`를 안내하고 조문을 만들지 않는다. 이 레포에서 `fly deploy`를 실행하지 않는다.
- `missing-LAW_OC`: `.env.example`을 보고 `LAW_OC` 또는 `KOREAN_LAW_API_KEY` 설정을 안내하고 조문을 만들지 않는다.
- exit 규약: 빌드없음 78, 키없음(`LAW_OC`) 79 — 메시지가 어느 쪽인지 명시한다.
- `ready`: `korean_law` MCP로 조회한 뒤 `invoke_subagent` `Model: "inherit"`로 원문과 대조한다. 상세 API는 필요할 때만 `korean-law-mcp/docs/API.md` **한 파일**.

키 값을 출력하거나 로그에 남기지 않는다.
