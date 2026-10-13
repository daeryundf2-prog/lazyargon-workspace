# LazyForensic (v1.0.4)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Node 18+](https://img.shields.io/badge/Node-18%2B-brightgreen.svg?style=flat-square&logo=node.js&logoColor=white)](https://nodejs.org/)
[![Integrity: Fail-Closed](https://img.shields.io/badge/Integrity-Fail--Closed-red.svg?style=flat-square)](docs/GAPS.md)

> **Fail-Closed Digital Forensic Analysis Toolkit & Evidentiary Integrity Pipeline**  
> Streamlining evidence parsing, timeline reconstruction, SHA-256 chain-of-custody verification, and forensic report generation for developers, researchers, and legal tech practitioners.

디지털 증거 파싱 → 타임라인 렌더 → 해시 감사(SHA-256) → 보고서 초안 생성 → **초안 무결성 검증**까지의 전 과정을 자동화하고 휴먼 에러를 방지하는 오픈소스 디지털 포렌식 분석 스위트입니다.

> ⚠️ **이 도구가 아닌 것**: 증거 획득 도구도, 법원 제출 적격성을 보장하는 스위트도 아니다
> (**not a forensic acquisition or court-admissibility suite**). 판단과 획득은 별도 검증된
> 도구/분석가의 몫이며, 이 플러그인은 "확인되지 않은 것은 `미확인`으로 비워 둔다"는
> fail-closed 원칙으로 초안을 만든다. 한계 목록은 [`docs/GAPS.md`](docs/GAPS.md).

---

## 요구 사항

| 구분 | 필수 여부 | 비고 |
| :--- | :--- | :--- |
| Python 3.10+ | 필수 (핵심 스크립트) | macOS/Linux/Windows 모두 동작. `python`이 없으면 `python3`로 읽어 실행 |
| Node 18+ | 필수 (훅·법령 MCP 래퍼) | `python`이 없으면 검증 게이트는 경고 후 통과(비활성) |
| ffmpeg / ffprobe | 영상 스킬만 | `brew install ffmpeg` / `winget install Gyan.FFmpeg` |
| Hayabusa·Chainsaw·EZ-Tools·Dissect·MemProcFS | 선택 (BYO 래퍼) | **미포함** — 있을 때만 해당 분석이 활성화됨 |
| Google Antigravity | 선택 (전체 기능) | 없으면 아래 "스크립트만 단독 사용" 경로 |

> 기본 사용 분위기는 **Windows**다(EVTX/MFT/MemProcFS 계열 도구가 Windows 네이티브).
> macOS/Linux에서도 카카오 파싱·타임라인·해시·검증 체인은 완전히 동작한다(직접 검증됨).

## 설치

### A. Antigravity 플러그인으로 (권장 — 스킬 라우팅 + 무결성 훅 포함)

저장소를 클론한 뒤 Antigravity에 플러그인으로 등록한다(`plugin.json` 매니페스트: `skills/`, `hooks/`, `mcpServers/` 등록). 이 경로에서만 다음이 자동으로 작동한다.

- 세션 시작 시 `GEMINI.md` 호스트 계약 주입 (`SessionStart` 훅)
- 증거 파일 쓰기 차단 시도 (`PreToolUse`, best-effort)
- 산출물 SHA-256 감사 로그 + 보고서 검증 게이트 (`PostToolUse`)

### B. 스크립트만 단독 사용 (호스트 없이 CLI로)

호스트가 없어도 스크립트는 그대로 쓸 수 있다. 단, 훅과 스킬 라우팅은 없으므로 검증을
수동으로 실행해야 한다.

```bash
git clone https://github.com/daeryundf2-prog/lazyforensic && cd lazyforensic
python -m pytest test/ -v   # 권장: 297개 테스트 (로컬 약 30~40초). pytest 없으면 python -m unittest discover -s test
```

### C. 다른 컴퓨터에서 한 방 세팅 (선택 의존성 포함)

```bash
git clone https://github.com/daeryundf2-prog/lazyforensic.git
cd lazyforensic && sh bootstrap.sh        # Windows는 scripts/setup_forensic_env.ps1
export PATH="$PWD/bin:$PATH"              # 셸 설정에 추가하면 영구 적용
```

`bootstrap.sh`가 하는 일: python3 확인 → `~/.lfenv` 가상환경 생성 → 선택 의존성
(pillow·faster-whisper·sherlock·kiwipiepy) 설치 → 없는 시스템 바이너리
(ffmpeg·fpcalc·whisper-cli 등)의 플랫폼별 설치 명령 안내.
`bin/lazyforensic`은 `~/.lfenv/bin/python`을 자동으로 우선 사용하므로 별도 활성화가
없다. 진단만 하려면 `sh bootstrap.sh --check`.

## 법령 조회 (선택 — 한국법 MCP)

법령·판례 인용 검증용 MCP 서버가 번들되어 있다. **키가 없으면 서버가 조용히 비활성**되고
조문을 날조하지 않는다(fail-closed). 쓰려면:

1. 국가법령정보센터(law.go.kr) 오픈API에서 **서비스 인증키**를 발급받는다.
2. 빌드 (최초 1회 — `node_modules` **약 680MB** 생성, 네트워크에 따라 수 분):
   ```bash
   node scripts/setup_korean_law.mjs   # npm install --ignore-scripts + build + 검증
   ```
3. 키 설정:
   ```bash
   cp .env.example .env        # .env 에 LAW_OC=<발급받은 인증키> 기입
   ```
   키는 콘솔/로그에 출력되지 않는다.

빌드가 없으면 `node scripts/korean_law_mcp.mjs`가 exit 78(빌드없음 안내)로 끝나고,
키(`LAW_OC`)가 없으면 exit 79(키없음 안내)로 끝나며,
스킬은 "조문을 만들지 않는다"는 원칙만 남는다.

> 용량 실측: `node_modules` 약 680MB는 로컬 빌드 산출물이며 배포물이 아니다.
> 시간 실측: `npm install`+`build`는 네트워크에 따라 수 분 소요된다(최초 1회만).
> 상태 확인: `node scripts/setup_korean_law.mjs --check` — 빌드/키 유무를 출력한다.
> 미빌드 상태에서는 법령 조회를 시도하지 않고 exit 78로 종료한다(fail-closed).
> 경량 배포 시 `node_modules`는 제외된다(`.gitattributes` export-ignore).

## 5분 워크플로 (실측 예시)

카카오톡 텍스트 내보내기 1장으로 끝까지 가는 최소 여정 — 아래 명령은 그대로 복붙해 동작한다.

```bash
# 0. 사례 폴더에 증거 텍스트를 둔다 (카카오톡 대화방 메뉴에서 텍스트로 내보낸 파일)
cp "카카오톡_대화내용.txt" case/

# 1. 대화 파싱 + 타임라인 이벤트 변환 (모바일/PC 자동 판별, UTF-8/CP949/UTF-16)
python skills/kakao-chat-extractor/scripts/parse_kakao.py case/카카오톡_대화내용.txt \
       --output case/parsed.json --events-out case/events.json

# 2. 타임라인 HTML (외부 의존 0 — 파일 하나를 브라우저로 열면 끝)
python skills/forensic-timeline/scripts/generate_timeline.py --input case/events.json --output case/timeline.html

# 3. 원본 파일 해시 감사 → audit.json (검증의 근거가 된다)
python skills/forensic-audit/scripts/audit_timestamps.py case/카카오톡_대화내용.txt --json > case/audit.json

# 4. 보고서 초안 작성 후 검증 — 근거 없는 해시/금지 문구/High-Fidelity 비파라메트릭 게이트
python scripts/verify_report.py case/감정서초안.md --evidence case/audit.json --morph-grounding --high-fidelity --strict --json

# 5. Kiwi 형태소 기반 포렌식 그라운딩 단독 감사
python scripts/korean_morph_forensic.py --evidence case/audit.json --report case/감정서초안.md --high-fidelity --json
```

검증기가 잡는 것 (실제 동작 확인):

- 근거 없는 SHA-256/MD5 → `FAIL (근거 없는 해시 N개)`
- `명백히 입증`, `법원에 유효`, `court-admissible` 등 과단정 문구 → `FAIL`
- 법령 조문 상한(정보통신망법 76조 등) 및 미래 연도 판례 날조 차단
- Local High-Fidelity 비파라메트릭 게이트 (`--high-fidelity`): 증거 원문/`<evidence>` 태그 일치도 70% 미달 시 즉시 차단. Vertex API 호출 없음.
- 부정 문맥(`유출의심 아님`, `조작 가능성을 배제할 수 없다`)은 오탈 차단하지 않음
- 인코딩이 UTF-16(Windows PowerShell 기본 출력)이어도 금지 문구를 읽어 낸다

## 무엇이 지원되고 무엇이 아닌가

| 요청 | 상태 | 조건 |
| :--- | :--- | :--- |
| 카카오톡 텍스트 내보내기 파싱 (모바일/PC) | ✅ | 텍스트 내보내기만. SQLite/백업 DB ❌ (SQLite 분석은 lazyothers sqlite-evidence-query 스킬 활용) |
| 타임라인 HTML 렌더 (XSS 이스케이프, 샘플 거부) | ✅ | events.json 필요 |
| 파일 MAC 시각 + SHA-256/MD5 감사 | ✅ | `os.stat` 표면값. `$MFT`/Timestomping 판정 ❌ |
| 보고서 초안 검증 (금지 문구/해시/법령상한/High-Fidelity/형태소 그라운딩) | ✅ | `verify_report.py` (--evidence, --morph-grounding, --high-fidelity) |
| EVTX 헌팅 (Hayabusa/Chainsaw) | 🟡 BYO | `python scripts/check_tool.py hayabusa.exe` 통과 시에만 |
| MFT/Prefetch/Shimcache (Dissect/EZ-Tools) | 🟡 BYO | 실패 시 `error` 필드 + exit 3 ("0건" 위장 없음) |
| 메모리 덤프 (MemProcFS/Volatility 3) | 🟡 BYO | 덤프+도구 모두 있을 때만 |
| 영상 프레임/메타데이터 감사 | ✅ | ffmpeg 필요 — `setup.py --check`로 확인 |
| AI 사용 흔적 포렌식 (md/txt/E01 역추적) | ✅ | `skills/ai-trace-detector/SKILL.md` |
| 딥페이크/AI 합성 미디어 1차 감사 (SHA-256, C2PA/JUMBF, 2D FFT) | ✅ | `python scripts/analyze_deepfake_evidence.py <파일> --output 리포트.md` — 최종 판정은 다중 탐지기 앙상블 별도 수행 |
| 영상 대화록(Whisper) | 🔒 동의 필요 | `--upload-audio` 명시 동의 없이 외부 전송 금지 |
| 로컬 STT 배치·verbatim·키워드 히트 | ✅ | `python scripts/local_stt.py <파일|폴더> --keywords "키워드"` — faster-whisper/openai-whisper/whisper.cpp/moonshine 자동탐지, 엔진 없으면 지어내지 않고 exit 3 |
| 오디오 내용 지문·유사 쌍 | 🟡 BYO | `python scripts/audio_fingerprint.py <폴더>` — fpcalc(chromaprint) 필요, 재인코딩된 같은 녹음도 지문 유사도로 탐지 |
| 다중 소스 타임라인 병합 | ✅ | `python scripts/merge_timeline.py --manifest m.json --kakao k.json --exif e.json [--stt t.json --anchor "파일=시각"]` → `events.json` (STT 상대시각은 --anchor 없이 벽시계로 올리지 않음) |
| 서증 목록표 초안 | ✅ | `python scripts/court_evidence_sheet.py <manifest.json> --party 갑` — 관행 양식 **초안**(제출 전 검토 필수), 입증취지는 `--purpose` 지정분만 기재 |
| lazyothers 증거 JSON보내기 | ✅ | `python scripts/evidence_export.py <manifest.json> -o evidence.json` — lazyothers `generate_evidence_doc.py`/`bind_court_pdf.py`가 그대로 소비하는 형식 (scan→서증→표찰·병합 파이프라인) |
| DLP 로그 체크리스트 정리 | ✅ | `python scripts/dlp_log_table.py <로그.csv>` — 확보된 로그의 시간순·4축 재배열. **탐지 아님** — 없는 로그는 만들지 않음 |
| CLI 래퍼 | ✅ | `bin/lazyforensic scan\|stt\|pii\|manifest\|timeline\|sheet\|export\|dlp ...` — `bin/`을 PATH에 추가. Windows는 `bin/lazyforensic.cmd`(또는 `.ps1`)로 동일 서브커맨드 |
| 유사 이미지 검색 (pHash/aHash/dHash+색 히스토그램) | ✅ | `python scripts/image_similarity.py <폴더> [--query 사진]` — Pillow 필요, 리사이즈·재압축본도 해밍 거리로 탐지 |
| 영상 지문 매칭 (프레임 해시 유사도) | ✅ | `python scripts/video_fingerprint.py A.mp4 --scan 폴더/` — ffmpeg 필요, 재인코딩·해상도 차이 영상도 유사도로 판정 |
| 개인정보 탐지·마스킹 (외부 전송 전 프리플라이트) | ✅ | `python scripts/pii_mask.py <파일|폴더> [--mask]` — 주민번호/전화/카드/계좌/이메일 정규식 탐지 |
| 외부 반출 가능 경로 정적 감사 | ✅ | `python scripts/local_only_audit.py` — 네트워크 송신 지점을 GATED/UNGATED로 분류 |
| 증거 매니페스트 (체인 오브 커스터디 초안) | ✅ | `python scripts/evidence_manifest.py <폴더> -o m.json` / `--verify m.json` — 변경·신규·삭제 파일 탐지 |
| HWPX 텍스트 추출 | ✅ | `python scripts/extract_hwpx.py <파일|폴더>` — stdlib 전용, 바이너리 .hwp는 외부 도구 영역 |
| 신구대비 텍스트 비교 | ✅ | `python scripts/doc_diff.py old.txt new.txt --markdown` — 현행/신안/비고 표 |
| 오디오 발화 구간 선조사 | ✅ | `python scripts/audio_survey.py <파일|폴더>` — WAV stdlib 직독, 그 외는 ffmpeg 경유. STT 전 스크리닝용 |
| 이미지 EXIF 감사 | ✅ | `python scripts/exif_audit.py <파일|폴더>` — Pillow 필요, 촬영일시·기기·GPS·편집흔적 표면 조사 |
| 증거형 키워드 검색 리포트 | ✅ | `python scripts/keyword_report.py <폴더> "키워드"` — file:line:원문+SHA-256, 부재도 '전수 검색 미검출'로 기록 |
| 파일 위장 감사 (매직바이트 vs 확장자) | ✅ | `python scripts/signature_check.py <폴더>` — 'jpg인 척하는 exe' 등 스크리닝, 불일치 시 exit 1 |
| 중복 파일 탐지 | ✅ | `python scripts/dedup_files.py <폴더>` — SHA-256 정확 중복 + Pillow 있으면 유사 이미지 그룹 |
| 아카이브 내부 감사 (추출 없이) | ✅ | `python scripts/archive_survey.py <파일|폴더>` — zip/tar 멤버 해시·이중확장자·압축폭탄·중첩 아카이브 |
| PDF 구조 감사 | ✅ | `python scripts/pdf_audit.py <파일|폴더>` — 암호화·JavaScript·임베딩 첨부·메타데이터 표면 조사 |
| SQLite 증거 DB 조사 | ✅ | `python scripts/sqlite_survey.py <파일|폴더>` — immutable 읽기전용, 테이블/행 수/무결성. `--sample 테이블 N`으로 표본 확인 |
| 영상 손상·잘림 감지 | 🟡 BYO | `python scripts/video_integrity.py <파일|폴더>` — ffmpeg/ffprobe 필요, 디코드 오류·moov 위치·duration 불일치 |
| 증거 통합 선조사 (위 도구 전부 한 번에) | ✅ | `python scripts/case_survey.py <폴더> [--keywords ...] [--stt] -o survey.json --markdown survey.md` — 단계별 실패도 '실패'로 기록 |
| 다른 컴퓨터 환경 복제 | ✅ | `python scripts/setup_forensic_env.py --check` / 실행 시 venv+선택 의존성 설치 (Windows는 `scripts/setup_forensic_env.ps1`) |
| 법령/판례 조회 | 🟡 키 필요 | 위 "법령 조회" 참고 |
| OSINT 사용자명 검색 | 🟡 BYO | `python scripts/osint_username.py <닉네임>` — sherlock 미설치 시 exit 3. 닉네임이 외부 사이트에 쿼리로 노출되므로 반출 승인 필요 |
| 바이너리 HWP(.hwp) 파싱·신구대비 | 🟡 외부 | `obundh/korean-munseo-diff` 별도 설치 — HWPX는 위 `extract_hwpx.py`로 가능. 다운로드 후보목록 전체는 [`docs/BYO-TOOLS.md`](docs/BYO-TOOLS.md) |
| 무결성 훅 (쓰기 차단/감사 로그) | 🟡 Antigravity | best-effort. OS 읽기전용(`chmod 444`) 병행 권장 |

## 트러블슈팅

- **증개 가드에 쓰기가 막힌다**: 사본도 같은 확장자(`.raw`, `.E01`)면 차단된다. 사본은
  `img.raw.analysis.txt`처럼 확장자를 바꾸거나 `evidence/` 밖에서 작업하라.
- **증거 디렉토리 읽기전용 설정**: `sh scripts/lock_evidence.sh [evidence_dir]` (Windows는
  `lock_evidence.ps1`) — `chmod 444` 상당의 OS 읽기전용으로 훅 가드를 보강한다.
  `perl -e`/`ruby -e`/`powershell -enc` 인라인 실행은 증거 경로와 무관하게 차단된다.
- **`korean_law`가 exit 78(빌드없음)/79(키없음)**: `node scripts/setup_korean_law.mjs --check`로
  어느 쪽인지 확인한다. exit 79는 `LAW_OC` 미설정 — **키가 없다고 조문을 만들어내지 않는다**.
  exit 78은 `setup_korean_law.mjs` 미실행 — 정상 동작이다.
- **영상 스킬이 조용히 안 될 때**: `python skills/forensic-video/scripts/setup.py --check` —
  무엇이 없는지 + 플랫폼별 설치 명령을 출력한다.
- **Windows에 python이 없어서**: 검증 게이트가 경고 후 통과한다(비활성). `python3` 설치를 권장.
- **카카오톡 파일이 깨져 보인다**: UTF-8/CP949/UTF-16을 자동 판별한다. 그래도 실패하면
  모바일 앱에서 텍스트로 재내보내기하고, 파일을 다른 인코딩으로 재저장하지 말 것.
- **감사 체인 검증**: `python scripts/verify_audit_chain.py` (기본 `.lazyforensic/audit_trail.jsonl`, 파일 없으면 PASS·empty session)
- JSON 출력은 `python scripts/verify_audit_chain.py --json`, 빈 체인 거부(엄격 모드)는 `--no-empty` 추가
- 깨짐 시 `FAIL` 줄번호·`prev_hash` 기대값을 출력하므로 해당 줄부터 원본 대조 후 재생성하라
- **평가 코퍼스**: `test/fixtures/eval/`에 정답지 포함 알려진-답 코퍼스가 있다(카톡 대화·문서·로그·이미지 47파일 + `EVAL.md` 11문항 + `ANSWER_KEY.md`). 플러그인/모델 변경 후 에이전트에게 EVAL.md를 던져 부재 환각·재현율을 회귀 검증할 수 있다. 오디오 픽스처는 저작권 문제로 미포함 — 로컬 오디오를 넣어 STT 문항을 검증할 것. 코퍼스 불변식은 `test/test_eval_corpus.py`가 커밋 레벨에서 잠근다.
- **커밋 게이트**: `git config core.hooksPath .githooks`를 설정하면 pre-commit이 `local_only_audit`(새 UNGATED 외부 송신 차단) + pytest 전체를 자동 실행한다. CI에도 같은 감사가 있다 — 의도된 외부 경로는 검토 후 `.local_only_allowlist`에 `파일 종류`로 등재할 것.

## 정직 선언 / 아키텍처

- **[`docs/GAPS.md`](docs/GAPS.md)** — 구현하지 않은 능력 목록 (광고-구현 차이 고정)
- **[`GEMINI.md`](GEMINI.md)** — Antigravity 호스트 계약, 스킬 라우팅, 실패 폐쇄 규칙
- **[`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)** — 요청 문구별 사용 예시
- 검증 게이트의 정체: `PostToolUse` **사후 게이트**다. 파일이 쓰인 뒤 검증하며, 호스트가
  `failurePolicy: FAIL_CLOSED`(exit 1)을 지원할 때 후속 제출이 막힌다. 우회 경로는 GAPS.md에 기록.

## 테스트 / CI

```bash
python -m pytest test/ -v
```

`.github/workflows/ci.yml`: Ubuntu/Windows 유닛 테스트 + 훅 가드 단언, korean-law-mcp 빌드+vitest.

## Lazy 생태계 (레포 경계)

- `LAZYANTIGRAVITY` — 런타임 우산: 훅 집계·공유 스킬 물질화·번들 MCP 런타임
- `lazyforensic` (본 레포) — 포렌식/한국법률 도메인 플러그인
- `lazyothers` — 리걸 문서·HWP·humanize 도메인 플러그인
- `lazyagentic` — 규칙 전용 거버넌스 플러그인 (Dual-Mount `~/agentic`)
- [`korean-law-mcp`](https://github.com/daeryundf2-prog/korean-law-mcp) — 한국법 조회 MCP 서버.
  본 레포가 `setup_korean_law.mjs`로 클론·빌드해 사용하고, LAZYANTIGRAVITY는 빌드본을 번들한다.

공유 자산: `scripts/coverage_audit.mjs`는 lazyforensic(캐노니컬)·lazyothers·LAZYANTIGRAVITY
3곳에 바이트 동일 사본으로 유지된다 — 수정 시 3곳 동기화 필수 (파일 헤더 주석 참조).

## 라이선스

본 레포 코드는 MIT ([`LICENSE`](LICENSE)). 한국 법령 MCP 서버는 별도 레포
[`daeryundf2-prog/korean-law-mcp`](https://github.com/daeryundf2-prog/korean-law-mcp)로 분리되어 있고
동일하게 MIT다 ([`NOTICE`](NOTICE)). `node scripts/setup_korean_law.mjs`가 최초 실행 시
해당 레포를 `./korean-law-mcp/`로 클론해 빌드한다. 무라이선스 제3자 디자인 카탈로그
(mengto-skills, design-systems 등)는 배포 리스크 때문에 제거되어 있다 — 자세한 사유는
[`NOTICE`](NOTICE)와 [`docs/GAPS.md`](docs/GAPS.md).
