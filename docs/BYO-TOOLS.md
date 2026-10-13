# BYO 외부 도구 카탈로그

레포에 편입하지 않고 **다운받아 쓰는** 도구 목록. 각 항목은 '무엇을·왜·어떻게'만 적는다.
이 문서의 도구를 설치하면 대응 스크립트가 자동으로 활성화된다(fail-closed는 유지).

## 포렌식 직결

| 도구 | 용도 | 설치 | 연동 |
|---|---|---|---|
| **sherlock-project** | 닉네임→482개 사이트 존재 여부 OSINT 스캔 | `pip install sherlock-project` | `scripts/osint_username.py` 자동 탐지. ⚠️ 조회 닉네임이 외부 사이트에 노출 — 의뢰인 동의 필요 |
| **CrisperWhisper** | verbatim STT — 필러음·말더듬·단어 타임스탬프 보존. 증거 녹취에 표준 Whisper보다 적합 | faster-whisper로 HF에서 자동 다운로드 | `local_stt.py --model nyrahealth/CrisperWhisper --verbatim` |
| **transcribe.cpp** | whisper.cpp 확장, 16개 모델 계열 로컬 STT | GitHub 빌드 | `local_stt.py`의 binary 엔진 탐지 |
| **Subtitle Edit** | 전사문 사람 검토·수정 GUI (로컬 전용, MIT) | 릴리스 다운로드 | `local_stt.py` 산출물을 수동 교정할 때 |
| **Moonshine** (`useful-moonshine`) | 스트리밍 설계 초경량 STT — ⚠️ **영어 전용** | `pip install useful-moonshine` | `local_stt.py`가 자동 탐지(최후순위). 한국어 증거엔 부적합 |
| **chromaprint (fpcalc)** | 오디오 내용 지문 — 재인코딩된 같은 녹음 탐지 | `brew install chromaprint` / `winget install chromaprint` | `audio_fingerprint.py` 자동 활성화 |
| **korean-munseo-diff** | HWP·HWPX·PDF 신구대비표 (공무원 개정 문서용) | `github.com/obundh/korean-munseo-diff` | 바이너리 .hwp는 이걸로 — HWPX는 `extract_hwpx.py`가 커버 |
| **Unlimited-OCR** (Baidu) | 40p+ PDF 통째 OCR | GitHub | 스캔 증거 문서 대량 텍스트화 후 `keyword_report.py` |
| **Upscayl** | 저해상도 이미지 업스케일 (로컬, 오픈소스) | 릴리스 다운로드 | 증거 사진 선명화 — 단, 업스케일본은 파생물로 표시 |
| **claude-video (`/watch`)** | 영상 링크→프레임+전사+AI 분석 | `github.com/bradautomates/claude-video` | 프레임 추출은 `forensic-video`와 겹침 — 영상 '내용 읽기'용 |
| **kordoc** | HWPX 글자 100% 보존 검증된 파서/리팩터링 사례 | GitHub | `extract_hwpx.py`가 못 읽는 구조(표·서식)가 필요할 때 |
| **Camofox** | OSINT용 어사이드 연동 브라우저 (봇 탐지 회피 설계) | GitHub | sherlock이 막히는 사이트 수동 확인용. ⚠️ 외부 접속 — 동의 필요 |
| **검색 API 무료 티어** (Exa·Tavily·SerpAPI·Brave) | OSINT 웹 검색 보조 | 각 사이트 키 발급 | `osint_username.py` 보조 — 외부 쿼리이므로 allowlist 검토 대상 |
| **untrunc** | moov 손상 mp4 복구 (정상 참조 파일 필요) | GitHub | `video_integrity.py`가 DAMAGED/UNREADABLE로 잡은 파일의 복구 시도 |
| **qpdf / pikepdf** | PDF 정밀 파싱·암호 해제·객체 스트림 검사 | `brew install qpdf` / `pip install pikepdf` | `pdf_audit.py`가 못 보는 객체 스트림 내부, 암호 해제본 생성 |
| **Gemini Transcribe 3.5** | 클라우드 STT — 녹음분 **화자분리 최대 3명**(로컬 스택에 없는 유일 기능) | AI Studio/API | ⚠️ **증거 오디오를 외부 업로드** — 의뢰인 서면 동의 없이 사용 금지. `local_stt.py`가 못 하는 화자분리가 필요한 경우의 최후 옵션 |

## 워크플로 보조

| 도구 | 용도 |
|---|---|
| **dryforge** | bounded-autonomy 에이전트 하네스 — lazyagentic과 설계 철학 유사, 참고용 |
| **Paperthin** | 에이전트 컨텍스트 위생 스킬 (re0/ssotize/debloat) — 문서 팽창 제어 |
| **ARTEMIS** (google) | 안드로이드 자연어 자동화 — 모바일 앱 반복 조작 자동화에 응용 |
| **Letta CLI / Orca** | 장기메모리 LLM / 멀티작업 에이전트 IDE |
| **ego lite** | 에이전트 전용 Chromium — 로그인 필요 사이트 자동화 |
| **Tailscale tsnet 단일 도구** | 계정 없이 홈서버 외부 접속 — 다른 컴퓨터의 포렌식 환경 원격 작업 시 |
| **Magnitude** | 로컬 LLM 자동 설치(사양 확인→모델 추천→설정) — 다른 컴퓨터에서 로컬 분석 환경 셋업 보조 |
| **GenOffice / Office CLI** | Office 파일 읽기·생성·PDF 편집 CLI — `court_evidence_sheet.py` 초안을 제출용 DOCX/HWPX 변환 |

## 문서·보고서 품질

| 도구 | 용도 |
|---|---|
| **bluenyx 한국어 문장 검토 스킬** | 보고서·대본 문체 검토 (9개 문서 유형) |
| **avoid-ai-writing / patina** | AI 문체 습관 제거 — 의뢰인 제출 문서 최종 다듬기 |
| **jurisupport-plugins** | 변호사 감수 한국 법률 문서 초안 스킬 — legal-forensic-consult 레인 초안 품질 참고(출력물은 항상 변호사 검토 전 단계) |

## 증거 수집·환경 참고사항

- **구글 지도 타임라인은 이제 단말기에만 있다** — PC 브라우저에서 타임라인이 삭제됨(온디바이스 전환). 위치 증거는 반드시 단말에서 수집해야 한다.
- **로컬 LLM도 완전한 비공개가 아니다** — 로컬 추론도 캐시·디토크나이저 흔적 같은 사이드채널로 프롬프트/생성문이 복원될 수 있다는 보고가 있다. "로컬이니까 안전"이 아니라 "외부 전송이 없다"가 정확한 표현이다.
- **로컬 모델 다운로드 자체도 흔적** — HF 모델 다운로드는 외부 요청이다. 새 컴퓨터 셋업 시 `setup_forensic_env.py`가 어떤 외부 호스트에 접속하는지는 스크립트와 `.local_only_allowlist`에 명시돼 있다.
- **전문분야 지식 DB는 그래프DB가 효과적**이라는 실무 조언 — legal-forensic-consult에 판례·실무서적(PDF) 지식베이스를 붙일 때 Neo4j류 그래프 구조를 검토할 것.

## 규칙

- 이 표에 없는 도구를 스크립트가 호출하게 만들 때는 `check_tool.py`식 fail-closed 게이트를 둘 것
- 외부로 데이터가 나가는 도구(sherlock, API 계열)는 `.local_only_allowlist` 검토 대상이다
- 새 도구를 발견하면 이 표에 행을 추가하고 README 능력 표와 동기화할 것
