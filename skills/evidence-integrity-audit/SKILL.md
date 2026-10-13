---
name: evidence-integrity-audit
description: "포렌식 증거 파일 전수(SHA-256/MD5/SHA-1) 해시 감사 및 제출용 보고서 기재 해시와의 일치 대조, 무결성 증명서(Chain of Custody Verification Sheet) 자동 생성 스킬. Triggers: 해시 감사, 무결성 검증, 증거 해시 대조, chain of custody, 증거설명서 해시 확인."
---

# Evidence Integrity Audit — 증거 해시 무결성 감사

법정 제출 전, **원본 증거 파일의 실제 해시**와 **보고서(증거설명서 등)에 기재된
해시**가 일치하는지 전수 대조한다. 기재 오류·원본 교체·파손을 숫자 하나로
잡아낸다. 판정·집계는 스크립트가 하며(SSOT), 에이전트가 눈으로 대조하지 않는다.

## 핵심 도구

```bash
# 1. 증거 폴더 전수 감사 + 증거설명서 대조 → 감사 보고서
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/audit_evidence_integrity.py \
    --scan-dir 증거폴더 --report 증거설명서.md --output 감사보고서.md

# 2. 개별 파일 감사 + 다중 알고리즘
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/audit_evidence_integrity.py \
    --file 증거1.pdf --file 증거2.hwp --algorithms sha256,md5

# 3. 보고서 없이 산출만 (해시 목록 + 무결성 증명서)
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/audit_evidence_integrity.py --scan-dir 증거폴더
```

## 판정 규칙

| 판정 | 의미 | 후속 조치 |
|---|---|---|
| ✅ 일치 | 계산 해시가 보고서에 그대로 존재 | 통과 |
| ❌ 불일치 | 파일명 언급 근처에 다른 해시가 기재됨 | **제출 금지** — 원본 교체·파손·기재 오류 원인 규명 |
| ⚠️ 미측정 | 보고서에서 이 파일을 찾을 수 없음 | 보고서 기재 누락 — 증거설명서 갱신 |
| 🔍 산출 | 대조 보고서 미지정 (해시 산출만) | 필요 시 `generate_evidence_doc.py`로 편입 |

Exit code: `0` 불일치 없음 / `1` 불일치 존재 / `2` 실행 오류. **exit 1이면
법원 제출물 생성을 진행하지 않는다.**

## 워크플로 (증거설명서와의 연계)

1. `generate_evidence_doc.py --input-json evidence.json` → 증거설명서.md
   (SHA-256 자동 기재)
2. 본 스킬로 감사: `--report 증거설명서.md` → 모두 ✅ 일치인지 확인
3. 감사 보고서의 Chain of Custody Verification Sheet를 증거 봉투와 함께 보관
   (증명서 자체의 SHA-256도 기록되어 기록 위변조를 해시로 잠근다)

## 주의

- 감사 대상은 **원본**. 스탬핑본(`stamp_evidence.py` 출력)은 해시가 다르므로
  원본 감사와 별도로 관리한다 — 증거설명서 비고란은 항상 원본 해시다.
- 감사 보고서는 시점 정보를 담는다. 원본이 갱신되면 재감사가 필요하다.
