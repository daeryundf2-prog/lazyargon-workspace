---
name: report-guard
description: 보고서/문서 할루시네이션 무조건 검증 — 금지문구/근거없는 해시 차단. Triggers: 보고서, 검토해줘, 검증해줘, 검증, 할루시네이션, 할루체크, 팩트체크, 거짓말검사, 사실확인, 무결성검사, verify
---

# report-guard: 무조건 검증 게이트

채팅에 아래 **어느 하나라도** 포함되면 호스트 `PostToolUse` + 이 스킬이 **무조건** `verify_report.py`를 실행한다. 이것은 **사후 게이트**다 — 파일이 이미 쓰인 뒤 검증하며, LLM이 스킵해도 훅이 동일 검증을 재실행한다. 실제 쓰기 차단은 호스트가 `failurePolicy: FAIL_CLOSED`(exit 1)을 지원할 때 작동하고, 파이썬이 없거나 대상을 특정할 수 없으면 경고 후 통과한다. 스킵 경로는 `docs/GAPS.md`에 기록되어 있다.

**트리거 (모두 동일 게이트)**:
`보고서`, `검토해줘`, `검증해줘`, `검증`, `할루시네이션`, `할루체크`, `팩트체크`, `거짓말검사`, `사실확인`, `무결성검사`, `verify`, `/verify`, `/할루체크`, `/검증`

## 동작

1. 대상 보고서(`.md`/`.html`)를 찾는다 — 가장 최근 `Write` 파일 또는 명시 경로
2. 아래를 무조건 검사:
   - 금지문구: `명백히 입증`, `법원에 유효`, `유출 확정`, `court-admissible`, `Timestomping으로 단정`
   - 해시 grounding: 보고서 내 64자 해시가 `--evidence` (audit.json/timeline.json) 에 없으면 FAIL
   - 공공기관/법원 명칭: 폐지된 구 부처명, `디지털포렌식청`, `사이버수사처` 등 가짜 기관명 차단
   - 역사적 사건/조약 차수 날조: `갑오개혁 4차`, `제2차 을사조약`, `3차 동학농민운동` 등 차단
   - 불가능한 사법 절차 날조: `대검찰청의 약식명령 청구`, `경찰의 영장 직접 청구`, `헌법재판소의 징역형 선고` 등 차단
   - 빈칸 추측: `미확인/미측정`을 추측으로 채웠는지
3. `FAIL`이면 파일 유지하되 에러를 띄우고 **제출 금지**. `PASS/WARN`이면 통과 (WARN은 부모가 pro로 재대조)

## 실행 (스킬이 직접 하는 일 — 호스트도 동일하게 자동 실행)

```bash
# 스킬이 invoke_subagent Model: "inherit"로 실행하는 검증
python scripts/verify_report.py "보고서초안.md" --evidence audit.json --timeline events.json --json
# 슬래시/채팅 어느 쪽이든 동일
python scripts/verify_report.py "보고서초안.md" --evidence audit.json --json
```

## Antigravity / Gemini

- 이 스킬 자체는 `Model: "inherit"` 로 검증을 수행한다
- 동시에 호스트 `hallucination_guard.mjs`가 `PostToolUse`에서 동일 검증을 **자동 재실행**하므로 LLM이 이 스킬을 안 불러도 차단된다
- `보고서` 또는 `검토해줘`가 포함된 모든 쓰기는 이 게이트를 통과해야 한다 — `docs/GAPS.md` 위반 시 차단

## 슬래시 명령어

```
/verify <보고서경로> [--evidence audit.json]
/할루체크 <보고서경로>
/검증 <보고서경로>
검증해줘: <보고서경로>
보고서 검증해줘: <보고서경로>
팩트체크해줘: <보고서경로>
```

어느 형태로 불러도 동일 검증 (`verify_report.py`)이 돈다.
