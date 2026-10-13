# LazyForensic — Gemini / Antigravity

호스트는 Google Antigravity, 세션 UI는 사용자가 선택한 모델(Gemini 3.8 Flash, Claude Opus/Sonnet 5.5)을 따른다.
이 플러그인은 증거 자료를 정리하고 보고서 초안을 만든다. 포렌식 획득이나 법원 제출 적격성을 보장하지 않는다.

## 도구

| 목적 | 사용 |
| :--- | :--- |
| 파일·추출 프레임 읽기 | 호스트 `Read` (이미지 지원) |
| 파일 수정 | 호스트 `Write` / `Edit` |
| 탐색·파싱·초안·검증 | `invoke_subagent` |
| 법령 조회 | 빌드와 API 키를 확인한 `korean_law` MCP |

OpenCode `task(...)`, `model_tier`, `subagent_type`, Cursor `Task`, `view_file`을 만들지 않는다.

## `invoke_subagent` 계약

최상위 필드는 `Subagents`, `toolAction`, `toolSummary`다.
항목 필드는 `TypeName`, `Role`, `Model`, `Prompt`, `Workspace`다.
`Model`은 `inherit` | `flash_lite` | `flash` | `pro`만 허용한다.

```
invoke_subagent(
  Subagents=[{
    TypeName: "self",
    Role: "<short-role>",
    Model: "flash",
    Prompt: """
TASK: <명령형 작업>
DELIVERABLE: <정확한 산출물 또는 판정>
SCOPE: <경로와 제약>
VERIFY: <부모가 재실행할 검증>
ROLE ENVELOPE: mayFinalizeRun=false; mayModifyGlobalRunState=false; mustReturn=SubagentResultEnvelope; requiresParentAck=true
"""
  }],
  toolAction: "<역할> 서브에이전트 호출",
  toolSummary: "<한 줄 요약>"
)
```

레인 힌트는 `hostEnforced=false`다. 대량 탐색·파싱·초안에는 `flash`, 가벼운 작업에는 `flash_lite`, 검증·대조 레인에는 `pro`를 쓴다. Claude 5.5 세션이어도 `inherit`는 최종 판정 레인 하나에만 쓴다. Ultra 요금제에서 Claude 할당량이 Gemini보다 훨씬 적기 때문이다.
세션 UI는 사용자가 선택한 세션 모델을 따른다. 호스트 `modelName`이 다르지 않으면 자식 모델이 바뀌었다고 말하지 않는다.

## 실패 폐쇄 (할루시네이션 차단 — 최우선)

- `--input`이 없으면 샘플 USB/카카오 유출 사건을 만들지 않는다.
- 파일·로그가 없으면 빈칸 또는 `미확인`/`미측정`으로 둔다. 이벤트/해시/시각을 만들지 않는다.
- Windows 복사에서 생성시각 > 수정시각은 흔하다. Timestomping으로 단정하지 않는다.
- 카카오 파서는 텍스트 내보내기만 지원한다. SQLite를 읽지 않는다.
- 법령 MCP 빌드나 `LAW_OC`가 없으면 그 사실을 말하고 조문을 만들지 않는다.
- "명백히 입증", "법원에 유효", "유출 확정", "court-admissible", "Timestomping으로 단정"을 쓰지 않는다.
- 증거 오디오는 명시적 `--upload-audio` 동의 없이 외부로 보내지 않는다.
- **근거-결론 분리**: 모든 수치·해시·시각·조문은 스크립트 stdout / MCP 응답에만 근거한다. 근거 없으면 `미확인`으로 둔다. 추측으로 빈칸을 채우지 않는다.
- **커버리지 주장은 감사 수신증으로만**: "전수/100% 커버리지" 류의 감사 결론은 `node scripts/coverage_audit.mjs --source <원문파일> --target <산출물…> --json <수신증.json>` 출력으로만 뒷받침한다. 감사 전에 원문을 반드시 파일로 저장하고, 원문 없는 감사(자체 생성 키워드 목록과의 대조)는 하지 않는다 — 도구가 `--source` 부재 시 실행을 거부한다. 수신증에는 항목별 원문 행 → 산출 위치 매핑이 남는다.
- **부모 검증**: `forensic-report` 초안은 `Model: "pro"`가 `python scripts/verify_report.py <보고서> --evidence <audit.json> --morph-grounding --high-fidelity`로 재검증한다 (`verify_report.py` 출력이 최종 판정 권한). `FAIL`이면 제출 금지.
- **High-Fidelity 비파라메트릭 모드**: 포렌식 보고서 작성 시 `verify_report.py`에 `--high-fidelity`를 강제하며, 원본 증거와 `<evidence>` 태그 누락 또는 형태소 커버리지 70% 미달 시 즉시 차단한다.

## 스킬 라우팅

한 턴에 **레인 하나**만 고른다. 레인 안에서 `SKILL.md` / `REFERENCE.md` / `INDEX.md`를 **하나만** 읽는다.

> **무조건 검증 (사후 게이트)**: 채팅 트리거(`보고서`/`검토해줘`/`검증해줘`/`검증`/`할루시네이션`/`할루체크`/`팩트체크`/`거짓말검사`/`사실확인`/`무결성검사`/`verify`)가 포함된 쓰기에는 호스트 `PostToolUse`가 `hallucination_guard.mjs → verify_report.py`를 재실행한다. 이것은 **사후 게이트**다 — 파일이 이미 쓰인 뒤 검사하며, 호스트가 `failurePolicy: FAIL_CLOSED`(exit 1)을 지원할 때 후속 제출이 차단된다. bash 리다이렉트 쓰기도 같은 게이트를 거친다. python 미설치·대상 미특정 시 경고 후 통과(스킵 경로는 `docs/GAPS.md`). 검증 FAIL이면 파일을 수정 전까지 제출 금지. 슬래시 `/verify`, `/할루체크`, `/검증` 도 동일 게이트.

### Help

사용자가 `설명서`, `도움말`, `명령어 알려줘`, `무엇을 할 수 있어?`라고 하면 `docs/USER_GUIDE.md`를 읽고 기능별 요청 예시를 보여준다. 도움말 요청만으로 분석이나 파일 생성을 시작하지 않는다.

### Forensic (14 — BYO binary 래퍼는 `check_tool.py` 게이트 통과 시에만, 보고서/검증 계열 = 무조건 검증)

진입점은 `skills/lazyforensic/SKILL.md`다. BYO 래퍼는 바이너리/라이브러리 미포함이며, 없으면 결과 생성 안 함.

| 요청 | 스킬 |
| :--- | :--- |
| 타임라인 HTML | `skills/forensic-timeline/SKILL.md` |
| 생성/수정 시각, 해시 | `skills/forensic-audit/SKILL.md` |
| 카카오톡 txt | `skills/kakao-chat-extractor/SKILL.md` |
| 텔레그램 JSON | `skills/telegram-chat-extractor/SKILL.md` |
| 감정서/보고서 초안 | `skills/forensic-report/SKILL.md` |
| **보고서 검증 (무조건)** | `skills/report-guard/SKILL.md` |
| CCTV/동영상 프레임 | `skills/forensic-video/SKILL.md` |
| 구간 자르기/필름스트립 | `skills/video-editor/SKILL.md` |
| DLP 표 정리 | `skills/dlp-leakage-detector/SKILL.md` |
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
| SQLite 증거 DB·카톡 백업 카빙 | `skills/sqlite-evidence-query/SKILL.md` |
| 웹페이지 증거 채증(스크린샷·PDF·해시) | `skills/web-evidence-capture/SKILL.md` |
| 음성 전사(Whisper STT)·영상/이미지 OCR | `skills/media-analysis/SKILL.md` |

전체 도구 형식은 `docs/antigravity-tools.md`에 있다.

> **제거된 카탈로그**: 무라이선스 제3자 콘텐츠(`mengto-skills/`, `design-systems/`, `vendor/`, `skills/slopslap/`, UI 피커 스킬)는 배포 라이선스 리스크 때문에 본 레포에서 제거되었다. 필요하면 별도로 라이선스를 확보한 옵션 팩으로 제공한다.
