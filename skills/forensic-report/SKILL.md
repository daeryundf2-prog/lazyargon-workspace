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
- [ ] **법적 유불리 평가 및 추측 배제**: "상간소송 방어에 결정적", "양날의 검", "유리/불리한 정황" 등 소송 전략·법적 유불리 평가 및 추측성 서술을 일절 배제하고 순수 사실관계(측정값·원문 발화·로그)만 기술할 것
- [ ] **임의 요약 콜아웃 및 자기검증 배지 삽입 금지**: 에이전트 임의의 파란색 요약 콜아웃 박스나 `[전수 검증 완료]`, `(N개 발언 전문 수록)` 등 자기검증 배지·메타 주석을 본문에 삽입하지 말 것
- [ ] **대화록/녹취록 표 조판 및 인쇄 가독성 준수**: 대화록/녹취록 표에서 화자 이름 열에 `white-space: nowrap`을 적용해 3글자 성명이 두 줄로 깨지는 현상을 방지하고, 인쇄 가독성 기준(본문 `≥10pt`, 표 `≥9pt`)을 준수할 것
- [ ] **Material-First 조립 및 5대 여백 불변 규칙 (`print-paged-media.md` §8)**: HTML/PDF 또는 마크다운 보고서를 통째로 한 번에 생성하지 말고, ① 범위·배제 규칙 잠금 → ② 결정적 스크립트 출력(`audit.json`, `events.json`, STT/OCR 원문)을 데이터 재료로 먼저 분리 확보 → ③ 개별 증거 표/타임라인 카드를 원자적 단위(`.exhibit-atomic`)와 **2단 서브행(`tbody.row-group > tr.row-main + tr.row-sub`, 64자 `SHA-256` 전폭 1줄 바 `≤95ch`, `word-break: break-all`로 셀 수직 공백 및 Chromium 자동 축소 차단)**으로 조립 → ④ `.a4-sheet`(`min-height: 267mm`) + `.sheet-footer`(`margin-top: auto`) 하단 앵커링 및 페이지별 PNG 시각 검수(`pdftoppm`) 순서로 작성할 것 (상세: `lazyargon/docs/material-first-design.md`)
- [ ] **행위자 시간대 분리(직원 vs 사측 자체조사 구간) 및 3단계 증거 등급(`확정/정황/미확인`)**: 적발 직후 사측이 PC를 가동·백업한 구간은 직원 활동과 엄격히 분리(행위자 태그 명시)하여 증거 무결성 항변을 차단하고, 미이미징 디스크(예: 별도 HDD `D:`)나 미확보 외장매체 내부 본문은 `미확인`으로, 메타데이터 시계열 추론은 `정황`으로, 직접 증명된 아티팩트는 `확정`으로 구분 표기할 것
- [ ] **원격 푸시(`logs/refs/remotes/**`) ↔ 로컬 커밋(`logs/HEAD`, `commit_msg*.txt`) 및 LNK 볼륨 시리얼(`VSN`) 구분**: 로컬 커밋이나 `GIT.EXE` Prefetch 실행을 원격 전송(Push)으로 오판하지 말고, LNK 타깃 경로가 `D:\...`라도 LNK 내부 `Volume Serial Number`가 본체 디스크가 아닌 외부 볼륨이면 본체 설치·보관으로 단정하지 말 것. 브라우저 히스토리도 일괄 가져오기(동일 분·초 대량 생성) 여부를 먼저 확인할 것
- [ ] **내부자 사건 360° 점검 (배임 프롬프트·겸업·사측 역리스크·부정 결과 명시)**: 유출 경로 외에 ① AI 코딩 도구 프롬프트(`Claude Command History` 등)의 로직 제거·은폐 지시(`--scan-insider-prompts`), ② 개인 외부 인프라(Vercel/Cloudflare/숨고/학회 논문)·입사 전후 메모(`Microsoft Sticky Notes`), ③ 의뢰사 역리스크(전 직장 자료 반입, 크랙 SW, 평문 비밀번호), ④ 확인했으나 흔적이 없는 채널(이벤트 로그 1102/104, 와이핑 도구, 휴지통 등 부정 결과)을 함께 기재할 것

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

## 원본 자료 1:1 대조 (의뢰인 제출 전 필수)

보고서 옆 `evidence/`(또는 `증거/`, `자료/`, `첨부/`, `analysis/`)에 원본을 둔다. 가드가 이 폴더를 자동으로 찾아 `scripts/source_grounding.py`로 대조하며, 아래 중 하나라도 어기면 FAIL이다.

- 인용부호(`"…"`, `“…”`, `「…」`, `<evidence>`) 안 문장은 원본 텍스트에 글자 그대로 있어야 한다. 요약·의역은 인용부호 없이 쓴다.
- 발언자는 원본의 화자와 같아야 한다.
- `날짜 시:분` 시각은 원본 또는 타임라인에 있어야 한다.
- `N건/개/회/통/명`은 원본이나 `analysis/`의 집계 출력(스크립트로 산출한 JSON/CSV)에 값이 있어야 한다. 직접 센 수치는 쓰지 않는다.
- 첨부·증거로 적은 파일명은 자료 폴더에 실제로 있어야 한다.
- 이미지·음성·PDF는 글자를 대조할 수 없다. OCR/STT/내보내기 텍스트를 같은 폴더에 둔다. 없으면 해당 내용은 `미확인`으로 적는다.

```bash
python scripts/source_grounding.py "보고서초안.md" --sources evidence analysis --timeline events.json
```

```bash
# 부모가 반드시 재실행하는 검증 (High-Fidelity 비파라메트릭 모드)
python skills/forensic-audit/scripts/audit_timestamps.py "증거파일" --json > audit.json  # 측정
python scripts/verify_report.py "보고서초안.md" --evidence audit.json --timeline events.json --sources evidence analysis --require-sources --morph-grounding --high-fidelity --strict --json
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


