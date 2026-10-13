# LazyForensic 설명서

채팅에 **`설명서`**, **`도움말`**, **`명령어 알려줘`** 중 하나를 입력하면 이 문서의 기능별 요청 예시를 안내한다.

## 가장 많이 쓰는 요청

| 목적 | 채팅에 입력할 말 |
| :--- | :--- |
| 전체 기능 보기 | `설명서` |
| 파일 시각·해시 | `이 파일의 생성·수정 시각과 SHA-256을 확인해줘: <경로>` |
| 카카오톡 txt 파싱 | `이 카카오톡 내보내기 파일을 파싱해줘: <경로>` |
| 타임라인 HTML | `events.json으로 사건 타임라인 HTML을 만들어줘` |
| 감정서 초안 | `해시 결과와 parsed.json으로 포렌식 감정서 초안을 써줘` |
| 문장 교정 | `이 보고서를 교정해줘. 수치와 해시는 바꾸지 마: <경로>` |
| 보고서 검증 (무조건) | `이 보고서 검증해줘: <경로>` / `할루체크해줘: <경로>` / `/verify <경로>` |
| 팩트체크 | `팩트체크해줘: <경로>` / `거짓말검사해줘: <경로>` |
| 보고서 디자인 | `이 보고서를 깔끔한 HTML 뷰어(인라인 CSS, 외부 에셋 없음)로 만들어줘: <경로>` |
| 동영상 프레임 | `이 CCTV에서 프레임과 메타데이터를 추출해줘: <경로>` |
| 영상 구간 추출 | `이 영상의 30초부터 45초까지 사본으로 추출해줘: <경로>` |
| 인포그래픽 | `이 데이터로 한국어 인포그래픽을 만들어줘: <경로>` |
| DLP 표 정리 | `이 DLP/웹/USB 로그를 시간순 교차표로 정리해줘: <경로들>` |
| **AI 사용흔적 / AI 탐지** | `이 폴더/드라이브/E01의 AI 사용 흔적과 모델을 역추적해줘: <경로>` |
| 법령 조회 | `민법 제103조 원문을 조회하고 인용을 확인해줘` |

경로와 입력 자료를 같이 적는다. 자료가 없으면 사건, 해시, 시각, 법령을 만들지 않는다.

## 보고서 완성 워크플로

가장 안정적인 방법은 세 번에 나누는 것이다.

1. `해시 결과와 parsed.json으로 감정서 초안을 써줘`
2. `방금 초안을 교정해줘. 수치·해시는 보존해`
3. `교정본을 자기완결 HTML 뷰어로 만들어줘 (인라인 CSS)`

한 번에 요청하려면 순서를 명시한다.

> 1) `<입력 경로>`로 감정서 초안 작성  
> 2) 사실·수치·해시를 보존해 문장 교정  
> 3) 외부 에셋 없는 인라인 CSS HTML 뷰어 제작

## 디자인 요청

무라이선스 브랜드 디자인 카탈로그(mengto-skills/design-systems/ui-studio)는 본 레포에서 제거되었다.
HTML 뷰어 스타일링은 인라인 CSS로 직접 요청한다.

| 원하는 결과 | 요청 예시 |
| :--- | :--- |
| 보고서 뷰어 | `이 보고서를 읽기 좋은 HTML 뷰어로 만들어줘: <경로>` |
| 다크 테이블 | `이 타임라인을 다크 테마 HTML로 만들어줘` |
| 인쇄 최적화 | `이 HTML에 인쇄용 CSS를 넣어줘` |
| 디자인만 평가 | `수정하지 말고 이 HTML의 디자인만 검토해줘` |

브랜드 카탈로그는 참고 토큰이다. 공식 브랜드 디자인이나 상표 사용 권리를 제공하지 않는다.

## 터미널 명령

채팅 요청 대신 직접 실행할 때만 쓴다.

```powershell
# 파일 시각·해시
python skills/forensic-audit/scripts/audit_timestamps.py "대상파일.ext"

# 카카오톡 텍스트 내보내기
python skills/kakao-chat-extractor/scripts/parse_kakao.py "카카오톡_대화내용.txt" --keyword "키워드" --output parsed.json

# 정규화된 JSON → HTML 타임라인
python skills/forensic-timeline/scripts/generate_timeline.py --input events.json --output timeline.html --title "사건 타임라인"

# 영상 환경 확인·프레임 추출·메타데이터
python skills/forensic-video/scripts/setup.py --check
python skills/forensic-video/scripts/watch.py "영상.mp4" --resolution 720
python skills/forensic-video/scripts/forensic_video_audit.py "영상.mp4"

# 영상 필름스트립·구간 렌더
python skills/video-editor/helpers/timeline_view.py "영상.mp4" 30 45 -o timeline_strip.png --n-frames 12
python skills/video-editor/helpers/render.py edl.json -o extracted_clip.mp4 --build-subtitles

# 법령 MCP 로컬 빌드
node scripts/setup_korean_law.mjs

# 보고서 할루시네이션 검증 — 보고서/검토해줘/검증/할루체크 시 호스트가 무조건 실행, 수동으로도 가능
python scripts/verify_report.py "보고서초안.md" --evidence audit.json --timeline events.json --json
# 채팅 트리거 (모두 동일 게이트): 보고서, 검토해줘, 검증해줘, 검증, 할루시네이션, 할루체크, 팩트체크, 거짓말검사, 사실확인, 무결성검사
# 슬래시: /verify, /할루체크, /검증

# 전체 테스트
python -m unittest discover -s test -v
```

외부 음성 전사는 명시적 동의와 반출 승인 후에만 `--upload-audio`를 사용한다.

## 현재 한계

- 카카오톡 SQLite/백업 DB 분석은 `lazyothers` 플러그인의 `sqlite-evidence-query` 스킬을 활용한다 (복호화 키는 별도 확보 필요).
- `$MFT`, Timestomping, Maya, MOV 내부시각 감정 기능은 없다. `forensic-mft-parser`는 BYO Dissect/EZ-Tools 래퍼.
- EVTX/Memory (Hayabusa/Chainsaw/MemProcFS/Volatility)는 BYO 바이너리 래퍼이며 미포함.
- 타임라인은 최대 10,000 events, `details` 2KB cap (초과 시 잘림)
- DLP는 확보된 로그를 정리하는 체크리스트이며 자동 탐지 엔진이 아니다.
- 법령 MCP는 빌드와 `LAW_OC`가 모두 필요하다. `korean-law-mcp/node_modules`는 로컬 전용(679M) — `.gitignore`
- 증거 Hook은 best-effort이며 OS `chmod 444`를 대체하지 않는다. 감사로그는 `.lazyforensic/audit_trail.jsonl`에 격리.
- 법원 제출 적격성이나 법률 자문을 보장하지 않는다.

상세한 누락 기능은 `docs/GAPS.md`, 배포·라이선스 주의사항은 `NOTICE`를 본다.
