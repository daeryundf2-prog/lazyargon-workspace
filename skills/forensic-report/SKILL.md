---
name: forensic-report
description: "포렌식 감정서/보고서 초안. 측정값만 채운다. 의뢰인 주장 입증·법원 적격 단정에는 쓰지 말 것. Triggers: forensic-report, 포렌식 감정서, 포렌식 보고서, forensic-factuality-health."
---

# forensic-report: 보고서 초안 작성

분석 결과, 해시, 타임라인, 아티팩트 목록을 보고서 초안으로 정리한다.  
이 스킬은 감정인 서명, 법률 효력, 법원 채택을 보장하지 않는다.

## 목차

1. 사건 개요
2. 감정물 명세와 해시 (측정값만, 일치 단정은 값이 있을 때만)
3. 분석 환경과 도구 (실제 사용한 것만)
4. 쟁점별 관찰
5. 종합 — 데이터에 부합/불부합/판단 불능. 의뢰인 주장을 자동으로 입증하지 말 것.

## 품질 게이트

- [ ] Chain of Custody가 비어 있으면 빈칸으로 두고 채우지 말 것
- [ ] KST/UTC를 구분할 수 없으면 "미확인"으로 표기
- [ ] `$MFT`, Timestomping 등 용어는 실제 분석한 경우에만 사용
- [ ] "명백히 입증", "법원에 유효" 같은 선결론 금지

서식: `templates/forensic_report_template.md`. 초안은 `invoke_subagent` `Model: "inherit"`, 선결론 점검은 `Model: "inherit"`.

## Antigravity hard grounding (할루시네이션 차단)

`gemini_hallucination_mitigation_deep_dive.md`의 전수 환각 억제 프로토콜을 강제합니다:
1. **Evidence-First 인용 선행 (Section 3.2 #1)**: 분석 결론 서술 전 반드시 `<evidence>...</evidence>` 태그 안에 원시 측정값(해시, 타임스탬프, 이벤트 로그)을 20단어 이내로 문자 그대로 인용합니다.
2. **Strict Abstention 엄격 기권 (Section 3.2 #2)**: Chain of Custody나 타임라인 근거가 불충분할 경우 지어내지 않고 `미측정`, `미확인`, `[INSUFFICIENT_DATA]`로 표기합니다.
3. **법령 조문 및 판례 상한 경계 (Section 5.1 #1)**: 정보통신망법(76조), 형법(372조) 등 상한 및 판례 연도를 검증합니다.
4. **공공기관 명칭 날조 차단 (Section 5.1 #2)**: `디지털포렌식청`, `사이버수사처` 등 실존하지 않는 가짜 수사/포렌식 기관 날조를 차단합니다.
5. **Kiwi 형태소 하이브리드 그라운딩 (Section 5.2)**: `kiwipiepy` 포렌식 전문 용어 사전을 통해 원본 증거와 보고서 간 형태소 어휘 일치도를 검증합니다 (`--morph-grounding`).
6. **Local High-Fidelity 비파라메트릭 게이트 (Section 4.2)**: `--high-fidelity` 플래그 활성화 시, 원본 증거(`--evidence`)와 `<evidence>` 태그가 강제되며 형태소 그라운딩 70% 미달 시 즉시 차단합니다. Vertex API를 호출하지 않는 로컬 게이트입니다.
7. **한국사 사건 및 조약 날조 차단 (Section 5.1 #3)**: `갑오개혁 4차`, `제四차 갑오개혁`, `第4次 甲午改革`, `제2차 을사조약`, `제2차 을미개혁`, `3차 동학농민운동` 등 실존하지 않는 역사 차수/한자 숫자 및 단일 조약 날조를 차단합니다.
8. **불가능한 사법 절차 날조 차단 (Section 5.1 #4)**: `대검찰청의 약식명령 청구`, `경찰의 영장 직접 청구`, `경찰의 직접 기소`, `헌법재판소의 징역형 선고` 등 실정법상 성립 불가능한 절차를 장문 복문 수식어와 무관하게 기계적으로 차단합니다.
9. **학술 논문 및 저널 날조 차단 (Section 5.1 #3)**: 가짜 학술지/논문집(`대한인공지능법학회지`, `한국사이버포렌식학회논문집` 등) 및 미래 연도 학술 논문 인용 날조를 기계적으로 차단합니다.

```bash
# 부모가 반드시 재실행하는 검증 (High-Fidelity 비파라메트릭 모드)
python skills/forensic-audit/scripts/audit_timestamps.py "증거파일" --json > audit.json  # 측정
python scripts/verify_report.py "보고서초안.md" --evidence audit.json --timeline events.json --morph-grounding --high-fidelity --strict --json
# exit 1이면 금지문구/근거없는 해시/미지원 조문/High-Fidelity 미달 → 수정 없이 제출 금지

# 포렌식 사실성 종합 헬스체크 (Section 5.1 및 7-8 전수 10대 카테고리 100점 감사)
python scripts/verify_report.py --health-check --json

# Kiwi 형태소 포렌식 그라운딩 단독 감사
python scripts/korean_morph_forensic.py --evidence audit.json --report "보고서초안.md" --high-fidelity --json
```

- 해시가 하나라도 있으면 `--evidence`로 audit/timeline을 넘겨야 함. 근거 없는 해시는 `FAIL`
- 금지문구(`명백히 입증`, `법원에 유효`, `유출 확정`, `Timestomping으로 단정`, `court-admissible`) 포함 시 `FAIL`
- Chain of Custody/시각이 없으면 `미측정`/`미확인`으로 둔다. 빈칸을 추측으로 채우지 않는다.
- High-Fidelity 모드(`--high-fidelity`)에서는 증거 파일 및 `<evidence>` 인용 태그가 필수이며 70% 미달 시 차단됩니다.

