# Antigravity tool mapping (LazyArgon Workspace)

Defaults: Google Antigravity. The session model is whatever the host reports (`## 런타임` → `세션 모델`); never infer it from the plan tier or a config file.

| Session model | Plan | Lane role in this plugin |
| --- | --- | --- |
| Gemini 4 Argon (MEDIUM default, HIGH on request) | Ultra, Enterprise, paid Pro since 2026-10-15 (separate weekly-only quota, MEDIUM/HIGH only) | Legal drafts, ruling analysis, report bodies, verdict lanes. Long output, slow, quota-hungry |
| Gemini 3.8 Flash | Pro, Ultra | Parse, extract, tables, draft skeletons, simple edits — what `Model: "flash"` resolves to |
| Claude Opus/Sonnet 5.5 | Ultra (scarce quota) | One cross-family final-verdict lane for code changes |

In API-key mode (`modelProvider: "gemini"`), `agy` silently falls back to Gemini 3.8 Flash (High) when `gemini-4-argon` is not recognized. Report the host-reported model, not the intended one.

## Do

| Intent | Action |
| --- | --- |
| Explore / parse / draft / QA / review | `invoke_subagent` with TASK / DELIVERABLE / SCOPE / VERIFY / STOP / RETURN |
| Role envelope | `mayFinalizeRun=false`, `mayModifyGlobalRunState=false`, `mustReturn=SubagentResultEnvelope`, `requiresParentAck=true` |
| Child model hint (`canTierRoute`, not host-enforced) | `Subagents[].Model`: `flash` (parse/extract/draft skeleton/UI), `inherit` (report body, legal draft, verdict), `pro` (verify claims vs script output when the session is not Argon), `flash_lite` (tiny chores under quota pressure) |
| Budget | One line before any fan-out: `예산: <N> 레인 / <M> 웨이브`. Default cap 4 lanes / 2 waves |
| Read files / extracted frames | host `Read`; do not invent `view_file` |
| Edit | host `Write` / `Edit`, in chunks of ≤100 lines and <20KB per call, then re-read the written region |
| Identifiers you will cite later | pin to `.lazyargon/pins.md` when first observed; the real context cap is 256K and compaction drops them |

## Canonical `invoke_subagent` shape

Live Antigravity schema: top-level `Subagents`, `toolAction`, `toolSummary`; item `TypeName`, `Role`, `Model`, `Prompt`, `Workspace`. `Model` enum: `inherit` | `flash_lite` | `flash` | `pro`. There is **no** `model_tier` field and no thinking-level field (thinking level is session-scoped).

```
invoke_subagent(
  Subagents=[{
    TypeName: "self",
    Role: "<short-role>",
    Model: "flash",
    Prompt: """
TASK: <imperative assignment — name the full set of files/cases to cover>
DELIVERABLE: <exact artifact or verdict>
SCOPE: <paths / constraints — no duplicate implementations, no edits outside scope>
VERIFY: <commands or checks the parent will re-run>
STOP: same tool call repeated 3× / 40 tool calls / 2 turns without progress → return UNKNOWN immediately
RETURN: ≤40 lines — result, commands run, observed output, unresolved items. No plan restatement
WRITE: ≤100-line / <20KB chunks; re-read each written region
TOOLS: approval-gated tools (run_command, …) one per turn, never mixed with other calls
ROLE ENVELOPE: mayFinalizeRun=false; mayModifyGlobalRunState=false; mustReturn=SubagentResultEnvelope; requiresParentAck=true
"""
  }],
  toolAction: "Invoking <role> subagent",
  toolSummary: "<one-line summary>"
)
```

`Workspace` is optional. A lane that returns `UNKNOWN` or fails is retried once with the same prompt, then recorded as unresolved and excluded from synthesis. On a Claude 5.5 session use `Model: "inherit"` only for the single final-verdict lane (Claude quota is scarce on Ultra). Passing `Model` is an agent hint (`hostEnforced=false`).

## Do not

- Foreign spawn/wait/goal APIs and OpenCode `task(...)` / `call_omo_agent(...)` / `team_*(...)`
- `subagent_type=` / `run_in_background=` / `load_skills=` / `model_tier=` / `thinking_level=`
- Inventing evidence, statutes, or sample leakage timelines
- Filling a refused or hedged item by re-asking in other words — record `미확인(모델 유보)` and move on
- Single `write_to_file` calls above ~100 lines or ~20KB; the host drops them mid-stream (60 s silent-stream cutoff)
- Continuing in a conversation the safety filter already blocked; resume in a new conversation from `.lazyargon/ulw-scope.md`
