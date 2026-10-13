# CHARTER — lazyargon-workspace (lazyforensic + lazyothers)

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

---

# CHARTER — lazyothers

## Role
Reporting plane — 한국 법률·문서·PII·금융·문체 도구 묶음.

## Do
- 한국 공문서 파싱(HWP/HWPX/PDF), 표찰, 법률 초안(변호사 검토 전제)
- PII 토큰화·마스킹, 금융 흐름 분석
- 웹 채증(로컬 브라우저 직접 접속만 — 제3자 프록시 금지)

## Don't
- 법원 제출물의 무검토 완성본 주장 금지 — 항상 초안+검토 고지
- 도메인 간 결합은 계약 파일로만 — 직접 런타임 의존 금지
- 검증기 부재 시 검증 통과 시뮬레이션 금지 (not_checked/unavailable 표기)

## Contracts
- Consumes: lazy-evidence-case-v1 (lazyforensic 산출물 편입)
- Produces: 증거설명서·법률 초안·채증 기록
- Vendored: `contracts/` (lazy-contracts, hash-pinned)

## Claims allowed
`observed`, `heuristic`. 문서 산출물은 초안 지위 — `examiner-verified`는 변호사 검토 후에만.
