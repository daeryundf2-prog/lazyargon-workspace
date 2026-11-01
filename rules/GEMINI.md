# LazyForensic — Gemini / Antigravity

호스트는 Google Antigravity, 세션 UI는 사용자가 선택한 모델을 따른다. 실제 모델은 `## 런타임`의 `세션 모델` 값(호스트 보고값)만 믿는다(API 키 모드의 `agy`는 Argon 미매핑 시 Gemini 3.8 Flash(High)로 폴백). 이 플러그인은 증거 자료를 정리하고 보고서 초안을 만든다. 포렌식 획득이나 법원 제출 적격성을 보장하지 않는다.

| 세션 모델 | 제공 플랜 | 역할 |
| :--- | :--- | :--- |
| Gemini 4 Argon (MEDIUM/HIGH) | Ultra · Enterprise · Pro(주간 쿼터) | 법률 초안·판결문 분석·보고서 본문·검증 판정 레인 (`Model: "inherit"`) |
| Gemini 3.8 Flash | Pro · Ultra | 파싱·추출·표 정리·초안 골격·단순 편집 (`Model: "flash"`) |
| Claude Opus/Sonnet 5.5 | Ultra | 코드 변경의 교차 가족 최종 판정 1레인 |

Argon 기계적 제약(`lazyargon/docs/argon-field-notes.md`): **(1)** 100줄 이하 청크(20KB 미만) 쓰기(60초 컷오프 `#1255` 방지). **(2)** 실효 컨텍스트 상한 256K(240~280K 컴팩션 전에 해시·경로·사건번호·측정값을 `.lazyargon/pins.md`에 고정하고 컴팩션 후 원본·핀 파일 재열람). **(3)** 쓴 파일 재열람 확인. **(4)** 처리 범위 전수 명시. **(5)** 보고서 요약 10줄, 문단 4문장 이하.

## 도구

| 목적 | 사용 |
| :--- | :--- |
| 파일·추출 프레임 읽기 | 호스트 `Read` (이미지 지원) |
| 파일 수정 | 호스트 `Write` / `Edit` |
| 탐색·파싱·초안·검증 | `invoke_subagent` |
| 법령 조회 | 빌드와 API 키를 확인한 `korean_law` MCP |

OpenCode `task(...)`, `model_tier`, `subagent_type`, Cursor `Task`, `view_file`을 만들지 않는다.

## `invoke_subagent` 계약

스키마와 프롬프트 형식(TASK / DELIVERABLE / SCOPE / VERIFY / STOP / RETURN / WRITE / ROLE ENVELOPE)은 `docs/antigravity-tools.md` 한 곳에만 둔다(규칙 파일 예산 초과 `#1254` 방지). 레인 힌트는 `hostEnforced=false`이며 기본값은 `lazyargon/rules/AGENTS.md`를 따른다(`flash`: 탐색·파싱·초안 골격, `inherit`: 본문·법률·검증, `flash_lite`: 긴급 쿼터 폴백). 팬아웃 전 `예산: <N> 레인 / <M> 웨이브`(기본 4레인/2웨이브 상한)를 선언하고, 종료 조건(동일 도구 3회·호출 40회·무진척 2턴 → UNKNOWN), 반환 상한(≤40줄), 승인 도구(`run_command` 등) 단일 호출 규칙(`#1249`)을 지킨다. 호스트 `modelName`이 다르지 않으면 자식 모델이 바뀌었다고 말하지 않는다.

## 실패 폐쇄 (할루시네이션 차단 — 최우선)

- `--input`이 없으면 샘플 USB/카카오 유출 사건을 만들지 않는다.
- 파일·로그가 없으면 빈칸 또는 `미확인`/`미측정`으로 둔다. 이벤트/해시/시각을 만들지 않는다.
- Windows 복사에서 생성시각 > 수정시각은 흔하다. Timestomping으로 단정하지 않는다.
- 카카오 파서는 텍스트 내보내기만 지원한다. SQLite를 읽지 않는다.
- 법령 MCP 빌드나 `LAW_OC`가 없으면 그 사실을 말하고 조문을 만들지 않는다.
- "명백히 입증", "법원에 유효", "유출 확정", "court-admissible", "Timestomping으로 단정"을 쓰지 않는다.
- 증거 오디오는 명시적 `--upload-audio` 동의 없이 외부로 보내지 않는다.
- **근거-결론 분리**: 모든 수치·해시·시각·조문은 스크립트 stdout / MCP 응답에만 근거한다. 근거 없으면 `미확인`으로 둔다. 추측으로 빈칸을 채우지 않는다.
- **모델 유보는 결측이지 오류가 아니다**: 답을 거부·유보하거나 안전 필터가 걸리면 `미확인(모델 유보: <사유>)`로 적고 다음 항목으로 간다. 다른 표현으로 다시 물어 빈칸을 채우지 않는다.
- **결측은 WARN으로 드러난다**: `verify_report.py`는 결측 비율(`unverified.ratio`)을 출력한다. 수치·해시·시각 항목의 절반을 넘게 `미확인`이면 WARN(`--strict`에서는 FAIL)이며, 항목별 사유(증거 부재 / 모델 유보 / 도구 미설치)를 적는다.
- **코드베이스 감사 수치는 실행 근거로만**: "N개 중 M개 결함" 류의 감사 결론은 직접 연 `파일:라인`과 실행한 명령 출력에서만 나온다. 모델이 센 개수는 측정값이 아니다.
- **민감 증거 원문은 스크립트가 다룬다**: 성적·폭력 표현 증거는 안전 필터 차단 방지를 위해 스크립트에 맡기고 모델은 원문을 길게 인용하지 않는다. 차단 시 `미확인(모델 유보: 안전 필터)`로 기록하고 재요청하지 않는다. 반복 차단 시 Claude 5.5 세션으로 전환한다.
- **비전 판독은 텍스트 증거가 아니다 (STT는 무조건 서버 전송)**: 이미지·프레임 글자·수치는 `tesseract`/`local_ocr.py` 출력만 인용한다(모델 판독은 `모델 판독(미검증)` 표기). 야간/저화질 번호판은 단순 OCR을 불신하며, 다중 프레임 스태킹(ECC)+IBP 초해상화+자동차등록번호판 고시 소거법만 인용한다. STT는 내부 Whisper 대신 무조건 서버 STT(`yt-dlp` 자동자막·`local_stt.py` Google STT 서버 병렬 전송) 전사본만 인용한다.
- **SPA 채증**: 비표준 CSS 셀렉터 대신 표준/ARIA 역할을 쓰고, 동적 네비게이션 직후 `waitForLoadState`/`waitForSelector`로 DOM 안정을 기다린 뒤 조작한다(권장 절차).
- **커버리지 주장은 감사 수신증으로만**: "전수/100% 커버리지" 결론은 `node scripts/coverage_audit.mjs --source <원문파일> --target <산출물…> --json <수신증.json>` 출력으로만 뒷받침한다(`--source` 필수).
- **부모 검증**: `forensic-report` 초안은 `Model: "inherit"`가 `python scripts/verify_report.py <보고서> --evidence <audit.json> --morph-grounding --high-fidelity`로 재검증한다(`verify_report.py` 출력이 최종 판정 권한). `FAIL`이면 제출 금지.
- **High-Fidelity 비파라메트릭 모드**: 포렌식 보고서 작성 시 `verify_report.py`에 `--high-fidelity`를 강제하며, 원본 증거와 `<evidence>` 태그 누락 또는 형태소 커버리지 70% 미달 시 즉시 차단한다.
- **에이전트 메타 파일 가드 제외**: `.lazyargon/pins.md`, `.lazyargon/ulw-scope.md`, `claim-graph.md` 등 오케스트레이션·핀 파일은 `hallucination_guard.mjs` 검증 대상에서 제외되며 보고서·감정서 본문만 검증한다.
- **안전 필터 무한루프 차단 및 모델 유보**: agy 1.4.4+ 안전 필터 발동 시 재요청 없이 `미확인(모델 유보: 안전 필터)`로 기록하고 다음 단계로 진행한다.
- **암시적 캐시 보존**: 시스템 규칙·증거 원문 접두사는 상단에 고정하고 가변 메타데이터는 최하단에 둔다.
- **컴팩션 요약(`<CONTEXT_SUMMARY>`) 불신 및 AXIOM `hit_id`·볼륨 시리얼 실측 대조**: `<CONTEXT_SUMMARY>`는 1차 근거가 아니며 인접 행 `hit_id`·`artifact_name`을 오염시키므로 인용 전 `query_evidence_db.py --verify-hits/--verify-report`(`verify_report.py --axiom-db`)와 `.lazyargon/pins.md`로 재검증한다. 다중 디스크·파티션 환경은 볼륨 시리얼과 구 드라이브 후속 입출력을 대조하기 전까지 드라이브 문자 변경으로 단정하지 않는다.


## 스킬 라우팅

한 턴에 **레인 하나**만 고른다. 레인 안에서 `SKILL.md` / `REFERENCE.md` / `INDEX.md`를 **하나만** 읽는다.

> **무조건 검증 (사후 게이트)**: 채팅 트리거(`보고서`/`검토해줘`/`검증해줘`/`검증`/`할루시네이션`/`할루체크`/`팩트체크`/`거짓말검사`/`사실확인`/`무결성검사`/`verify`, 슬래시 `/verify`·`/할루체크`·`/검증`)가 포함된 쓰기(bash 리다이렉트 포함)는 `PostToolUse`가 `hallucination_guard.mjs → verify_report.py`로 재검사한다. 파일이 쓰인 뒤 검사한다. 호스트가 `FAIL_CLOSED`(exit 1)를 해석할 때만 후속 제출이 막힌다. python 미설치·대상 미특정·검증 타임아웃의 처리는 `docs/GAPS.md`. FAIL이면 수정 전까지 제출 금지.

### Help

사용자가 `설명서`, `도움말`, `명령어 알려줘`, `무엇을 할 수 있어?`라고 하면 `docs/USER_GUIDE.md`를 읽고 기능별 요청 예시를 보여준다. 도움말 요청만으로 분석이나 파일 생성을 시작하지 않는다.

### Forensic (14 — BYO binary 래퍼는 `check_tool.py` 게이트 통과 시에만, 보고서/검증 계열 = 무조건 검증)

진입점은 `skills/lazyforensic/SKILL.md`다. BYO 래퍼는 바이너리/라이브러리 미포함이며, 없으면 결과 생성 안 함.

| 요청 | 스킬 |
| :--- | :--- |
| 타임라인 HTML | `skills/forensic-timeline/SKILL.md` |
| 생성/수정 시각, 해시 | `skills/forensic-audit/SKILL.md` |
| 카카오톡 txt | `skills/kakao-chat-extractor/SKILL.md` |
| 맥 사용기록 조사 (권한 획득 시도, 수집 범위 표) | `python scripts/collect_mac_usage.py --out <작업폴더>/evidence --request-access --wait-access 120` 후 `skills/lazyforensic/references/mac-usage-history.md` |
| 텔레그램 JSON | `skills/telegram-chat-extractor/SKILL.md` |
| 감정서/보고서 초안 | `skills/forensic-report/SKILL.md` |
| **보고서 검증 (무조건)** | `skills/report-guard/SKILL.md` |
| CCTV/동영상 프레임 | `skills/forensic-video/SKILL.md` |
| 구간 자르기/필름스트립 | `skills/video-editor/SKILL.md` |
| DLP 표 정리 | `skills/dlp-leakage-detector/SKILL.md` |
| 윈도우 이벤트로그(.evtx 파일·폴더)·Prefetch·ShimCache·계정 — 외부 도구 없이 | `python scripts/parse_ntfs_artifacts.py <대상> -a eventlogs\|prefetch\|shimcache\|users -o out.json` |
| EVTX 헌팅 (BYO Hayabusa/Chainsaw) | `skills/dfir-evtx-hunter/SKILL.md` |
| MFT/Prefetch (BYO Dissect/EZ-Tools) | `skills/forensic-mft-parser/SKILL.md` |
| 메모리 래퍼 (BYO MemProcFS) | `skills/memory-triage/SKILL.md` |
| AI 사용 흔적 포렌식 (md/txt/E01 역추적) | `skills/ai-trace-detector/SKILL.md` |
| 딥페이크/AI 합성 미디어 (생성기 식별, C2PA, FFT, 탐지 레퍼런스) | `skills/deepfake-forensic-radar/SKILL.md` |

### Visual

| 요청 | 파일 |
| :--- | :--- |
| 인포그래픽 | `skills/infographic-creator/SKILL.md` |
| Manim 참고 | `video-editor`가 지시할 때만 `skills/video-editor/manim-video/REFERENCE.md` |
| HTML 뷰어 스타일 | 외부 디자인 카탈로그 없음 — 인라인 CSS로 직접 작성 (브랜드 토큰 재배포는 라이선스상 제외됨) |

### Legal

계약 서식·법령 조회는 `skills/legal-forensic-consult/SKILL.md`.  
세션 런타임의 `korean_law`가 `ready`일 때만 `korean_law` MCP를 쓴다. `missing-build`면 `node scripts/setup_korean_law.mjs`를 안내하고 조문을 만들지 않는다. `missing-LAW_OC`면 키 설정을 안내하고 조문을 만들지 않는다. 상세 API는 필요할 때만 `korean-law-mcp/docs/API.md` **한 파일**.


| 요청 | 스킬 |
| :--- | :--- |
| 전자소송 증거 표찰 / 갑·을호증 스탬핑 | `skills/court-evidence-stamper/SKILL.md` |
| 전자소송 증거 PDF 바인더 병합·분할 | `skills/court-pdf-binder/SKILL.md` |
| 판결문 구조 분석·쟁점 추출 | `skills/court-ruling-analyzer/SKILL.md` |
| 증거 무결성 해시 감사·CoC 시트 | `skills/evidence-integrity-audit/SKILL.md` |
| 계좌 거래내역·자금 흐름 추적 | `skills/financial-flow-tracer/SKILL.md` |
| 한국어 AI 문체 탈슬롭·윤문 | `skills/humanize-korean/SKILL.md` |
| HWP·HWPX·PDF 공문서 파싱 | `skills/korean-doc-parser/SKILL.md` |
| 한국형 개인정보(주민번호·계좌) 마스킹 | `skills/korean-pii-masker/SKILL.md` |
| 국가법령정보·대법원 판례 검색 | `skills/legal-case-search/SKILL.md` |
| 소장·준비서면·고소장 초안 작성 | `skills/legal-draft-builder/SKILL.md` |
| SQLite 증거 DB·카톡 백업 카빙·브라우저 방문기록(Chrome·Edge `History`, 시각 visit_time/1e6-11644473600 초) | `skills/sqlite-evidence-query/SKILL.md` |
| 웹페이지 증거 채증(스크린샷·PDF·해시) | `skills/web-evidence-capture/SKILL.md` |
| 음성 전사(Whisper STT)·영상/이미지 OCR | `skills/media-analysis/SKILL.md` |

전체 도구 형식은 `docs/antigravity-tools.md`에 있다.

제거된 무라이선스 카탈로그의 사유는 `docs/GAPS.md`에 있다.
