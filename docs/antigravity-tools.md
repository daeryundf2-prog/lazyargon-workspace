# Antigravity tool mapping (LazyForensic)

Defaults: Google Antigravity (Gemini 3.8 Flash, Claude Opus/Sonnet 5.5). Follow the session model.

## Do

| Intent | Action |
| --- | --- |
| Explore / parse / draft / QA / review | `invoke_subagent` with TASK / DELIVERABLE / SCOPE / VERIFY |
| Role envelope | `mayFinalizeRun=false`, `mayModifyGlobalRunState=false`, `mustReturn=SubagentResultEnvelope`, `requiresParentAck=true` |
| Child model hint (`canTierRoute`, not host-enforced) | `Subagents[].Model`: `flash` (parse/draft/UI), `pro` (verify claims vs script output, any session), `inherit` (single final-verdict lane on a Claude 5.5 session only), `flash_lite` (tiny chores) |
| Read files / extracted frames | host `Read`; do not invent `view_file` |
| Edit | host `Write` / `Edit` |

## Canonical `invoke_subagent` shape

Live Antigravity schema: top-level `Subagents`, `toolAction`, `toolSummary`; item `TypeName`, `Role`, `Model`, `Prompt`, `Workspace`. `Model` enum: `inherit` | `flash_lite` | `flash` | `pro`. There is **no** `model_tier` field.

```
invoke_subagent(
  Subagents=[{
    TypeName: "self",
    Role: "<short-role>",
    Model: "flash",
    Prompt: """
TASK: <imperative assignment>
DELIVERABLE: <exact artifact or verdict>
SCOPE: <paths / constraints>
VERIFY: <commands or checks the parent will re-run>
ROLE ENVELOPE: mayFinalizeRun=false; mayModifyGlobalRunState=false; mustReturn=SubagentResultEnvelope; requiresParentAck=true
"""
  }],
  toolAction: "Invoking <role> subagent",
  toolSummary: "<one-line summary>"
)
```

`Workspace` is optional. Follow the session model (Gemini 3.8 Flash, Claude Opus/Sonnet 5.5). Verify lanes pass `Model: "pro"` in any session; on a Claude 5.5 session use `Model: "inherit"` only for the single final-verdict lane (Claude quota is scarce on Ultra). Passing `Model` is an agent hint (`hostEnforced=false`).

## Do not

- Foreign spawn/wait/goal APIs and OpenCode `task(...)` / `call_omo_agent(...)` / `team_*(...)`
- `subagent_type=` / `run_in_background=` / `load_skills=` / `model_tier=`
- Inventing evidence, statutes, or sample leakage timelines
