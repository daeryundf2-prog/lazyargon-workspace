# Antigravity tool mapping (LazyArgon Workspace)

Defaults: Google Antigravity. The session model is whatever the host reports (`## 런타임` → `세션 모델`); never infer it from the plan tier or a config file.

| Session model | Plan | Lane role in this plugin |
| --- | --- | --- |
| Gemini 4 Argon (MEDIUM default, HIGH on request) | Ultra, Enterprise, paid Pro (separate weekly quota, MEDIUM/HIGH) | Universal primary — coding, UI, parse, extract, general forensics, legal drafts, ruling analysis, report bodies, and `browser` (`Model: "inherit"`) |
| Gemini 4 Carbon (MEDIUM/HIGH) | Ultra, Enterprise, paid Pro (separate weekly quota) | Cyber-defense / binary-reversing / exploit specialist when Argon safety filter would false-positive |
| Claude Opus/Sonnet 5.5 | Ultra (independent quota pool) | Zero-switch `swarm` read-only cross-family critic (`claude-opus-5-5-medium`), or fallback only when host safety filter repeatedly blocks |
| Gemini 3.8 Flash | Retired | Completely retired including `browser` (`flash_lite` only for 0% primary quota emergency fallback) |

In API-key mode (`modelProvider: "gemini"`), `agy` silently falls back to Gemini 3.8 Flash (High) when `gemini-4-argon` / `gemini-4-carbon` is unmapped. Always report the host-reported model, not the intended one.

## Do

| Intent | Action |
| --- | --- |
| Explore / parse / draft / QA / review | `invoke_subagent` with the 9-item Korean worker contract below |
| Child model routing (`hostEnforced=false`) | `Model`: `inherit` for all lanes including built-in `browser` (`flash` retired; `flash_lite` only for 0% primary quota emergency fallback) |
| Budget | One line before any fan-out: `예산: <N> 레인 / <M> 웨이브 / 세션 한도 추정 <%>` (default cap 4 lanes / 2 waves) |
| Read files / extracted frames | `read_file` (do not invent `view_file`) |
| Edit | `write_file` / `edit_file`: single-shot for ≤200 lines (<18KB) + 1 final `read_file`; split into ≤100-line chunks only above 200 lines |
| Identifiers you will cite later | Pin to `.lazyargon/pins.md` when first observed; the real context cap is 256K and compaction drops unpinned IDs |

## Canonical `invoke_subagent` shape

Live Antigravity schema is a **flat top-level object**: `TypeName`, `Role`, `Model`, `Prompt`, `Workspace` (optional). Do **not** wrap entries in a `Subagents: [...]` array or pass `toolAction` / `toolSummary` inside `invoke_subagent` (doing so breaks constrained JSON decoding with `}}}}` repetition loops). To fan out in parallel, emit multiple flat `invoke_subagent` calls in the same turn, and send replies back from subagents via `send_message`. There is **no** `model_tier` or `thinking_level` field.

```javascript
invoke_subagent({
  TypeName: "self",
  Role: "<short-role>",
  Model: "inherit", // All lanes including "browser"; "flash" retired ("flash_lite" only at 0% quota emergency)
  Prompt: [
    "목표: <한 문장>",
    "완료 조건: <담당 편집·조사 완료 기준 (다중 파일 편집 시 통합 검증은 부모가 1회 배치 실행)>",
    "범위: <담당 파일 전수 — 외부 파일 수정 금지, 동일 기능 중복 구현 금지>",
    "종료 조건: 같은 도구 3회 반복 / 도구 호출 40회 / 무진척 2턴 / 시간 예산 초과 → 즉시 UNKNOWN 반환",
    "시간 예산: <분> (기본 20분)",
    "근거 순서: 로컬 파일·로그·테스트 출력 → 저장소 문서 → 웹(검색 ≤8회)",
    "도구 규칙: 다중 파일 구현 워커는 편집·재열람만 수행(run_command 생략); 실행 필수 워커만 턴당 단독 호출 (#1249)",
    "반환 형식: ≤40줄 — 결과·실행 명령·관찰 출력·미해결 항목만",
    "쓰기 규칙: ≤200줄(<18KB) 원샷·초과 시 100줄 이하 청크, 완료 전 재열람"
  ].join("\n")
})
```

`Workspace` is optional (`inherit` default). Retry an `UNKNOWN` or failed lane once, then record as unresolved and exclude from synthesis. For cross-family high-risk audits, prefer one read-only `swarm` critic pinned to `claude-opus-5-5-medium` and `kill` it after the verdict.

## Do not

- Foreign spawn/wait/goal APIs or OpenCode `task(...)` / `call_omo_agent(...)` / `team_*(...)`
- `subagent_type=` / `run_in_background=` / `load_skills=` / `model_tier=` / `thinking_level=`
- Inventing evidence, statutes, or sample leakage timelines
- Filling a refused or hedged item by re-asking in other words — record `미확인(모델 유보: <사유>)` and move on
- Single `write_file` / `edit_file` calls above 250 lines or 24KB (guidance: ≤200 lines / <18KB single-shot; >200 lines split into ≤100-line chunks to avoid `#1255` 60 s stream cutoff)
- Continuing in a conversation the safety filter repeatedly blocked; resume from `.lazyargon/ulw-scope.md`
