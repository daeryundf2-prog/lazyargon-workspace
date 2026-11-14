# LazyForensic — Gemini / Antigravity

호스트는 Google Antigravity이며 세션 모델은 `## 런타임`의 `세션 모델`(호스트 보고값)만 믿는다(API 키 모드 `agy`는 Argon/Carbon 미매핑 시 Gemini 3.8 Flash(High) 폴백). 이 플러그인은 증거 자료 정리와 보고서 초안만 수행하며 포렌식 획득이나 법원 제출 적격성을 보장하지 않는다. 일반 런타임 제약(≤200줄 원샷·초과 시 100줄 이하 청크·18KB 쓰기, 256K 상한·`.lazyargon/pins.md` 고정, 재열람, 범위 전수 명시, 요약 10줄·문단 4문장 상한, 과장 금지 응답 태도, CLI 1.4.12 훅 비차단 규약)은 `lazyargon/rules/AGENTS.md`를 따른다.

| 세션 모델 | 제공 플랜 | 역할 |
| :--- | :--- | :--- |
| Gemini 4 Argon (MEDIUM/HIGH) | Ultra · Enterprise · Pro(주간 쿼터) | 범용 기본 주력 — 코딩·포렌식·파싱·법률 초안·판결문·보고서·UI·검증 전 레인 (`Model: "inherit"`) |
| Gemini 4 Carbon (MEDIUM/HIGH) | Ultra · Enterprise · Pro(주간 쿼터) | 사이버방어·리버싱·익스플로잇 전문가 (Argon 안전 필터 오탐 시 네이티브 전담) |
| Claude Opus/Sonnet 5.5 | Ultra (독립 쿼터) | `swarm` 핀 고정 읽기 전용 교차 가족 감사 1기 / 안전 필터 반복 차단 시 폴백 |
| Gemini 3.8 Flash | 폐기 (`flash` 비활성) | `browser` 포함 전면 폐기 — 주력 쿼터 0% 비상 시에만 `flash_lite` 폴백 |

## 도구 및 `invoke_subagent` 계약

호스트 `read_file`(이미지 지원)·`write_file`·`edit_file`·`invoke_subagent`와 빌드·키 확인된 `korean_law` MCP만 쓴다(`task(...)`, `model_tier`, `subagent_type`, `Task`, `view_file` 생성 금지). `invoke_subagent`는 평면 `{ TypeName, Role, Model, Prompt, Workspace? }`만 쓰며 `Subagents` 배열·`toolAction` 래퍼를 금지한다(`}}}}` 루프 방지, 상세 스키마·한글 9항목 워커 계약은 `docs/antigravity-tools.md` 참조). 팬아웃 전 `예산: <N> 레인 / <M> 웨이브`(기본 4레인/2웨이브) 선언, `browser` 포함 전 레인 `inherit` 일원화(`flash` 전면 폐기, 0% 쿼터 비상시만 `flash_lite`), 다중 파일 편집 워커는 `run_command` 생략 후 부모가 1회 배치 검증, 종료 조건(동일 도구 3회·호출 40회·무진척 2턴 → UNKNOWN), 반환 ≤40줄, 승인 도구(`run_command`) 턴당 단일 호출(`#1249`)을 지키며 `modelName`이 같으면 자식 모델 변경을 주장하지 않는다.

## 실패 폐쇄 (할루시네이션 차단 — 최우선)

- `--input` 없으면 샘플 USB/카카오 유출 사건을 만들지 않는다.
- 파일·로그 없으면 빈칸 또는 `미확인`/`미측정`으로 두며 이벤트·해시·시각을 만들지 않는다.
- Windows 복사의 `생성시각 > 수정시각`을 Timestomping으로 단정하지 않는다.
- 카카오 파서는 `.txt` 내보내기만 지원한다(SQLite 직접 파싱 금지).
- 법령 MCP 미빌드나 `LAW_OC` 미설정 시 그 사실만 알리고 조문을 창작하지 않는다.
- 금지 문구: "명백히 입증", "법원에 유효", "유출 확정", "court-admissible", "Timestomping으로 단정".
- 증거 오디오는 명시적 `--upload-audio` 동의 없이 외부 전송 금지.
- **근거-결론 분리**: 모든 수치·해시·시각·조문은 스크립트 stdout / MCP 응답에만 근거하며 없으면 `미확인` 처리한다.
- **모델 유보 및 안전 필터**: 거부·유보·안전 필터(agy 1.4.4+) 발생 시 재요청·우회 없이 `미확인(모델 유보: <사유>)`로 적고 다음으로 간다. 민감 증거 원문은 스크립트가 다룬다(장문 인용 금지, 반복 차단 시에만 Claude 5.5 폴백).
- **결측 비율**: `verify_report.py`의 `unverified.ratio`가 수치·해시·시각의 절반 초과 시 WARN(`--strict`는 FAIL)이며 사유(증거 부재 / 모델 유보 / 도구 미설치)를 적는다.
- **감사 수치**: "N개 중 M개 결함" 결론은 직접 연 `파일:라인`과 실행 출력에만 근거한다.
- **비전·STT 원칙**: 비전 판독은 텍스트 증거가 아니다 — 이미지·프레임 글자·수치는 `tesseract`/`local_ocr.py` 출력만 인용(모델 판독은 `모델 판독(미검증)` 표기). 야간·저화질 번호판은 다중 프레임 스태킹(ECC)+IBP 초해상화+번호판 고시 소거법만 인용한다. STT는 로컬 Whisper 금지, 서버 STT(`yt-dlp` 자동자막·`local_stt.py` Google STT 병렬 전송) 전사본만 인용한다.
- **SPA 채증**: 표준/ARIA 셀렉터를 쓰고 네비게이션 직후 `waitForLoadState`/`waitForSelector` 안정화 뒤 조작한다.
- **커버리지 수신증**: "전수/100% 커버리지" 주장은 `node scripts/coverage_audit.mjs --source <원문파일> --target <산출물…> --json <수신증.json>` 출력으로만 뒷받침한다(`--source` 필수).
- **부모 검증 & High-Fidelity**: `forensic-report` 초안은 `Model: "inherit"`가 `python scripts/verify_report.py <보고서> --evidence <audit.json> --morph-grounding --high-fidelity`로 재검증한다(`<evidence>` 누락·형태소 커버리지 70% 미달·`FAIL` 시 제출 금지). `.lazyargon/pins.md`·`.lazyargon/ulw-scope.md`·`claim-graph.md` 등 메타 파일은 `hallucination_guard.mjs`에서 제외한다.
- **컴팩션 요약 불신 및 볼륨 시리얼 대조**: `<CONTEXT_SUMMARY>`는 인접 행 `hit_id`·`artifact_name`을 오염시키므로 인용 전 `query_evidence_db.py --verify-hits/--verify-report`(`verify_report.py --axiom-db`)와 `.lazyargon/pins.md`로 재검증한다. 다중 디스크 환경은 볼륨 시리얼과 구 드라이브 후속 입출력 대조 전까지 드라이브 문자 변경으로 단정하지 않는다.

## 스킬 라우팅

한 턴에 **레인 하나**만 고르고 레인 안에서 `SKILL.md` / `REFERENCE.md` / `INDEX.md` **하나만** 읽는다.

> **무조건 검증 (사후 게이트)**: 트리거(`보고서`/`검토해줘`/`검증해줘`/`검증`/`할루시네이션`/`할루체크`/`팩트체크`/`거짓말검사`/`사실확인`/`무결성검사`/`verify`, `/verify`·`/할루체크`·`/검증`) 포함 쓰기는 `PostToolUse`가 `hallucination_guard.mjs → verify_report.py`로 재검사하며 `FAIL`이면 수정 전 제출 금지(예외 처리: `docs/GAPS.md`).

### Help

`설명서`·`도움말`·`명령어 알려줘`·`무엇을 할 수 있어?` 요청 시 `docs/USER_GUIDE.md`만 읽어 예시를 안내하고 분석·파일 생성은 하지 않는다.

### Forensic (15 — 진입점: `skills/lazyforensic/SKILL.md`; BYO 래퍼는 `check_tool.py` 통과 시에만, 미설치 시 결과 생성 안 함)

| 요청 | 스킬 |
| :--- | :--- |
| 타임라인 HTML | `skills/forensic-timeline/SKILL.md` |
| 생성/수정 시각, 해시 | `skills/forensic-audit/SKILL.md` |
| 카카오톡 txt | `skills/kakao-chat-extractor/SKILL.md` |
| 맥 사용기록 조사 | `python scripts/collect_mac_usage.py --out <작업폴더>/evidence --request-access --wait-access 120` 후 `skills/lazyforensic/references/mac-usage-history.md` |
| 텔레그램 JSON | `skills/telegram-chat-extractor/SKILL.md` |
| 감정서/보고서 초안 | `skills/forensic-report/SKILL.md` |
| **보고서 검증 (무조건)** | `skills/report-guard/SKILL.md` |
| CCTV/동영상 프레임 | `skills/forensic-video/SKILL.md` |
| 구간 자르기/필름스트립 | `skills/video-editor/SKILL.md` |
| DLP 표 정리 | `skills/dlp-leakage-detector/SKILL.md` |
| 윈도우 EVTX·Prefetch·ShimCache·계정 (내장) | `python scripts/parse_ntfs_artifacts.py <대상> -a eventlogs\|prefetch\|shimcache\|users -o out.json` |
| EVTX 헌팅 (BYO Hayabusa/Chainsaw) | `skills/dfir-evtx-hunter/SKILL.md` |
| MFT/Prefetch (BYO Dissect/EZ-Tools) | `skills/forensic-mft-parser/SKILL.md` |
| 메모리 래퍼 (BYO MemProcFS) | `skills/memory-triage/SKILL.md` |
| AI 사용 흔적 포렌식 (md/txt/E01) | `skills/ai-trace-detector/SKILL.md` |
| 딥페이크/합성 미디어 (C2PA·FFT·레퍼런스) | `skills/deepfake-forensic-radar/SKILL.md` |
| E01/증거 폴더 케이스 초기화·샌드박스 격리·hash CoC | `skills/case-mode/SKILL.md` |

### Visual

| 요청 | 파일 |
| :--- | :--- |
| 인포그래픽 | `skills/infographic-creator/SKILL.md` |
| Manim 참고 | `video-editor` 지시 시에만 `skills/video-editor/manim-video/REFERENCE.md` |
| HTML 뷰어 스타일 | 외부 카탈로그 없음 — 인라인 CSS 직접 작성 (`docs/GAPS.md`) |

### Legal

계약 서식·법령 조회: `skills/legal-forensic-consult/SKILL.md`. `korean_law`가 `ready`일 때만 MCP 사용(`missing-build`면 `node scripts/setup_korean_law.mjs` 안내, `missing-LAW_OC`면 키 설정 안내, 조문 창작 금지; 상세 `korean-law-mcp/docs/API.md`).

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
| SQLite 증거·카톡 백업·브라우저 History(`visit_time/1e6-11644473600`) | `skills/sqlite-evidence-query/SKILL.md` |
| 웹페이지 증거 채증(스크린샷·PDF·해시) | `skills/web-evidence-capture/SKILL.md` |
| 음성 전사(서버 STT)·영상/이미지 OCR | `skills/media-analysis/SKILL.md` |
