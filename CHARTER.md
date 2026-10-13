# CHARTER — lazyforensic

## Role
Evidence plane — 로컬 DFIR 분석·보고서 보조·감사 원장.

## Do
- 로컬 아티팩트 분석 (EVTX/MFT/타임라인/STT)
- append-only 감사 원장 (`audit_ledger.py` — tamper-evident)
- fail-closed BYOB 도구 게이트

## Don't
- acquisition·court admissibility suite 주장 금지 (README GAPS 참조)
- 타임스탬프를 사실 증명으로 표현 금지 — 기록값일 뿐
- STT 상대시각의 무앵커 벽시계 변환 금지
- 외부 전송은 명시 승인 게이트 없이 금지

## Contracts
- Consumes: lazy-evidence-case-v1 (rapid/frametrace 산출물)
- Produces: 감사 원장 이벤트, 보고서 초안, 분석 JSON
- Vendored: `contracts/` (lazy-contracts, hash-pinned)

## Claims allowed
`observed`, `heuristic`, `model-assisted`(limitations 필수), `cryptographically-anchored`(외부 앵커 존재 시). `examiner-verified`는 분석관 검토 기록이 있을 때만.
