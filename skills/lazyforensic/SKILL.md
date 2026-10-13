---
name: lazyforensic
description: 설명서·도움말·명령어와 포렌식·카카오톡 txt·타임라인·해시·감정서 라우터. 증거 없이 사건을 만들지 않는다.
---

# lazyforensic

Antigravity 진입점. 먼저 `GEMINI.md`를 읽고, **레인 하나**만 고른 뒤 그 안에서 파일 **하나만** Read 한다.

## Help

사용자가 `설명서`, `도움말`, `명령어 알려줘`, `무엇을 할 수 있어?`라고 요청하면 `../../docs/USER_GUIDE.md`를 읽고 기능별 채팅 예시와 필요한 입력을 안내한다. 기능을 실행하지 않는다.

## Forensic (14 스킬 — BYO 래퍼는 `check_tool.py` 게이트 통과 시에만, 보고서/검증 계열 = 무조건 검증)

**트리거에 `보고서`/`검토해줘`/`검증해줘`/`검증`/`할루시네이션`/`할루체크`/`팩트체크`/`거짓말검사`/`사실확인`/`무결성검사`/`verify` 중 하나라도 포함되면 모든 경로는 `report-guard` + `verify_report.py` 무조건 검증을 거친다. 이것은 사후 게이트다 — 호스트 `PostToolUse` 훅이 LLM 스킵 여부와 무관하게 동일 검증을 재실행하고, 호스트가 FAIL_CLOSED를 지원하면 후속 제출이 막힌다. 스킵 경로는 `docs/GAPS.md`. 슬래시 `/verify`, `/할루체크`, `/검증` 동일.**

| 요청 | 스킬 | 무조건 검증 |
| :--- | :--- | :--- |
| 타임라인 HTML | `../forensic-timeline/SKILL.md` | — |
| 생성/수정 시각, 해시 | `../forensic-audit/SKILL.md` | — |
| 카카오톡 내보내기 | `../kakao-chat-extractor/SKILL.md` | — |
| 텔레그램 JSON 내보내기 | `../telegram-chat-extractor/SKILL.md` | — |
| **보고서 초안** | `../forensic-report/SKILL.md` | **보고서 → 무조건** |
| **보고서 검증 (무조건)** | `../report-guard/SKILL.md` | **검증/할루체크/팩트체크 → 무조건** |
| CCTV/동영상 프레임 | `../forensic-video/SKILL.md` | — |
| 자르기/필름스트립 | `../video-editor/SKILL.md` | — |
| **한국어 문체 윤문·교정** | `../humanize-korean/SKILL.md` | **검토해줘 → 무조건 (보고서면)** |
| DLP 표 | `../dlp-leakage-detector/SKILL.md` | — |
| **AI 탐지 / AI 흔적 포렌식** | `../ai-trace-detector/SKILL.md` | — |
| **딥페이크 기술 레이더 & 포렌식** | `../deepfake-forensic-radar/SKILL.md` | — |
| EVTX 헌팅 (BYO Hayabusa/Chainsaw) | `../dfir-evtx-hunter/SKILL.md` | — |
| MFT/Prefetch (BYO Dissect/EZ-Tools) | `../forensic-mft-parser/SKILL.md` | — |
| 메모리 래퍼 (BYO MemProcFS) | `../memory-triage/SKILL.md` | — |

### 스크립트 직행 (스킬 없이 `scripts/`를 바로 실행 — 전부 로컬 전용)

| 자연어 요청 | 실행 |
| :--- | :--- |
| 폴더 전체 선조사·서베이·스캔해줘 | `python scripts/case_survey.py <폴더> [--markdown out.md]` |
| 이 폴더 변조됐는지·해시 목록·매니페스트 | `python scripts/evidence_manifest.py <폴더> -o m.json` / `--verify` |
| 개인정보 있는지·주민번호·계좌 마스킹 | `python scripts/pii_mask.py <대상>` |
| 키워드가 어디 나오는지·단어 찾아줘 | `python scripts/keyword_report.py <폴더> "키워드"` |
| 녹음 받아쓰기·전사·녹취록 | `python scripts/local_stt.py <대상> [--verbatim] [--keywords ...]` |
| 녹음에서 말하는 구간·무음 | `python scripts/audio_survey.py <대상>` |
| 이 사진이랑 비슷한 거·같은 사진 | `python scripts/image_similarity.py <폴더> [--query 사진]` |
| 이 영상이랑 같은 영상·영상 지문 | `python scripts/video_fingerprint.py <영상> --scan <폴더>` |
| 이 영상 손상됐는지·잘렸는지·재생 안 돼 | `python scripts/video_integrity.py <대상>` |
| 같은 녹음 다른 파일·음성 중복 | `python scripts/audio_fingerprint.py <폴더>` (fpcalc 필요) |
| 사진 정보·촬영시각·EXIF | `python scripts/exif_audit.py <대상>` |
| 확장자랑 다른 파일·위장 파일 | `python scripts/signature_check.py <폴더>` |
| 같은 파일 중복 | `python scripts/dedup_files.py <폴더>` |
| 압축파일 안에 뭐 있는지·zip 안 검사 | `python scripts/archive_survey.py <대상>` |
| PDF 암호·PDF 이상한지 | `python scripts/pdf_audit.py <대상>` |
| 카톡 DB·db 파일 안에 뭐 있는지 | `python scripts/sqlite_survey.py <대상>` (상세 쿼리는 `../sqlite-evidence-query/SKILL.md`) |
| 여러 시각 합쳐서 타임라인 | `python scripts/merge_timeline.py --manifest/--kakao/--exif/--stt` |
| HWPX 문서 텍스트 추출·hwp 안에 뭐 있는지 | `python scripts/extract_hwpx.py <파일|폴더>` (바이너리 .hwp는 외부 도구 영역) |
| 신구대비·두 문서 차이 비교 | `python scripts/doc_diff.py old.txt new.txt --markdown` |
| 서증 목록·증거설명서 초안 | `python scripts/court_evidence_sheet.py <manifest.json> --party 갑` |
| 서증을 법원 제출 문서로 변환·바인딩 | `python scripts/evidence_export.py <manifest.json> -o evidence.json` → `scripts/generate_evidence_doc.py` / `scripts/bind_court_pdf.py`가 소비 |
| DLP 로그 정리·유출 체크리스트 표 | `python scripts/dlp_log_table.py <로그.csv>` (탐지 아님 — 확보된 로그의 재배열) |
| 닉네임이 어디 사이트에 있는지 | `python scripts/osint_username.py <닉네임>` (⚠️ 외부 쿼리 — 의뢰인 동의 필요) |
| 다른 컴퓨터에서 환경 설치 | `python scripts/setup_forensic_env.py [--check]` |

터미널 단축: `bin/lazyforensic scan|triage|stt|pii|manifest|sig|dedup|similar|exif|kw|archive|pdf|db|vcheck|vfp|afp|osint|timeline|kakao|telegram|evtx|mft|memory|video|deepfake|timestamps|verify|sheet|export|dlp|audit|setup`
venv 인지 리졸버: 위 표의 `python` 자리에 `scripts/py`를 쓰면 `~/.lfenv` 설치분을 자동으로 찾는다 (의존성 필요 스크립트에서 유용).

## Visual

| 요청 | 파일 |
| :--- | :--- |
| 인포그래픽 | `../infographic-creator/SKILL.md` |
| Manim 참고 | `../video-editor`가 지시할 때만 `../video-editor/manim-video/REFERENCE.md` |
| HTML 뷰어 스타일 | 외부 카탈로그 없음 — 인라인 CSS로 직접 작성 |

## Legal

계약 서식·법령 조회는 `../legal-forensic-consult/SKILL.md`. 세션의 `korean_law`가 `ready`일 때만 MCP를 쓴다. 조문을 만들지 않는다.

병렬 작업은 `../../docs/antigravity-tools.md`의 `invoke_subagent`만 쓴다. `Model: "inherit"` 초안, 검증/대조 레인은 `Model: "inherit"`(세션 모델과 무관, Claude 할당량 절약).

## Evidence Integrity & Defensibility Mandates (사법 증거 무결성 원칙)

1. **Chain of Custody 제1원칙 (프록시 경유 절대 금지)**:
   - 모든 웹·네트워크 증거 채증은 로컬 브라우저가 원본 서버와 직접 TLS 통신을 맺고 원시 바이트와 스크린샷, 로컬 해시(SHA-256)를 즉시 산출해야 한다. 제3자 호스티드 프록시(Jina Reader 등)를 거친 데이터는 증거의 동일성이 법정에서 탄핵되므로 채증 파이프라인에서 원천 배제한다.
2. **Tamper-Evident 원칙 (변조 불가능 과장 금지)**:
   - 로컬 해시 체인 및 이벤트 로그는 '변조 탐지 가능(tamper-evident)'일 뿐 '변조 불가능(tamper-proof)'이 아니다. 외부 앵커(RFC 3161 공인시각인증 TSA 서버 타임스탬프 등)가 없는 단독 로컬 로그는 사법기관 제출 시 재계산 위조 공격에 대한 소명 한계를 반드시 명시한다.

