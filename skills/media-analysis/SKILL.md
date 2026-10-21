---
name: media-analysis
description: "음성/이미지/영상 파일 분석 워크플로: ffprobe 메타데이터 → 영상 무결성·오디오 서베이 → 프레임 추출(네이티브 비전 분석) → 서버 STT 전사(유튜브 자동자막·Google STT 서버 병렬 전송, 내부 Whisper 금지) → tesseract OCR. Triggers: media, stt, transcribe, ocr, video analysis, youtube, 음성, 전사, 영상 분석."
metadata:
  short-description: "Media analysis pipeline: probe, frames, OCR, server STT transcription, video/audio survey"
---

# media-analysis

음성·이미지·영상 파일을 분석할 때 이 스킬을 사용한다. **STT(음성 전사)는 느리고 부정확한 내부(로컬) Whisper를 절대 쓰지 말고, 무조건 서버(유튜브 서버 자동자막 + Google STT 서버 병렬 전송)로 보내서 수행한다.**

## Pipeline (이 순서를 지켜라)

1. **메타데이터 및 무결성 진단 (Probe 먼저)**:
   - 영상 스트림·코덱·손상 여부 진단:
     ```bash
     ./scripts/py scripts/video_integrity.py <영상파일_또는_폴더>
     ffprobe -v quiet -print_format json -show_format -show_streams <미디어파일>
     ```
   - 오디오 무음/발화 구간 서베이:
     ```bash
     ./scripts/py scripts/audio_survey.py <오디오파일_또는_폴더>
     ```
2. **영상 내용 및 키프레임 분석**:
   - `forensic-video`의 `watch.py`로 키프레임과 서버 STT/유튜브 자막을 추출한 뒤, 반환된 이미지 경로를 호스트 네이티브 비전(`Read`)으로 직접 판독한다 (기본 `--detail efficient`, 개괄 20프레임 — 부족할 때만 50):
     ```bash
     ./scripts/py skills/forensic-video/scripts/watch.py <영상파일_또는_URL> --detail efficient --max-frames 20
     ```
3. **서버 음성 전사 (STT — 내부 로컬 Whisper 금지, 무조건 서버 STT 사용)**:
   - **유튜브 영상/URL**: 유튜브 서버 자동자막이 가장 빠르고 정확하므로 `local_stt.py`에 URL(또는 파일명에 `[11자리_유튜브ID]`가 포함된 파일)을 넘기면 `yt-dlp`로 유튜브 서버 자막(`.vtt`)을 최우선 추출한다.
   - **로컬 오디오/영상 및 구간 검증**: `local_stt.py`의 기본 엔진(`google-server`)이 `ffmpeg` 16kHz PCM 청크(25초 단위)를 `ThreadPoolExecutor`로 Google Speech-to-Text 서버(`recognize_google`, `ko-KR`)에 병렬 전송해 수 초 내에 정확하게 전사한다:
     ```bash
     ./scripts/py scripts/local_stt.py <오디오파일_또는_폴더_또는_유튜브URL> --lang ko --keywords "주요키워드"
     python scripts/crime_schedule_xlsx.py --from-json schedule_rows.json -o 범죄일람표_청취검토.xlsx
     python scripts/crime_schedule_xlsx.py --recalc 범죄일람표_청취검토.xlsx
     python scripts/crime_schedule_xlsx.py --audit 범죄일람표_청취검토.xlsx --rule "쟁점어=근거어1,근거어2"
     ```
4. **이미지 텍스트 추출 (OCR)**:
   - 이미지 또는 추출 프레임 속 텍스트는 `tesseract` CLI(기본 `kor+eng`)로 직접 추출한다:
     ```bash
     tesseract <이미지파일> stdout -l kor+eng
     ```

## 도구별 전제 조건

| 작업 | 스크립트 / 바이너리 | 비고 |
| --- | --- | --- |
| 영상 무결성·메타데이터 | `scripts/video_integrity.py`, `ffprobe`, `ffmpeg` | 코덱·컨테이너 손상 및 길이 확인 |
| 영상 키프레임·자막 추출 | `skills/forensic-video/scripts/watch.py`, `ffmpeg`, `yt-dlp` | 유튜브 서버 자막 + Google 서버 STT 기본 활성 |
| 오디오 구간 서베이 | `scripts/audio_survey.py`, `ffmpeg` | 발화 구간·무음 구간 탐지 |
| 서버 음성 전사 (STT) | `scripts/local_stt.py` (`google-server` / `youtube-subs`) | **내부 Whisper 기본 금지**, 서버 병렬 STT 사용 |
| 이미지 OCR | `tesseract` (`kor+eng` traineddata) | 로컬 CLI 직접 실행 |

환경 점검: `./bin/lazyforensic setup --check`
설치 안내: `pip install SpeechRecognition yt-dlp` (및 `ffmpeg`, `tesseract`)

## 규칙

- **내부(로컬) Whisper 사용 금지**: `faster-whisper`, `openai-whisper`, `whisper-cli` 등 로컬 Whisper는 다수 영상 처리 시 30분 이상 멈추고 한국어 구어체·고유명사 오인식이 심하므로 사용하지 않는다. 무조건 유튜브 서버 자동자막(`yt-dlp`) 또는 Google STT 서버(`recognize_google` 병렬 청크 전송)로 처리한다.
- 대용량 영상은 `watch.py --detail efficient --max-frames 20`으로 먼저 개괄 확인한 뒤 필요한 타임스탬프 구간만 `--timestamps`로 정밀 추출한다. Gemini 4 Argon 세션에서 이미지 결과는 대화 전체와 함께 재전송돼 캐시 적중이 낮고(한 측정에서 약 4%) 한도를 빠르게 쓴다. 50프레임은 개괄이 부족할 때만 쓴다.
- **프레임은 한 번만 읽는다**: 각 프레임을 `Read`로 1회 판독하고 관찰을 `frames_notes.md`(프레임 경로·타임스탬프·관찰 1~2줄)에 즉시 적는다. 이후 판단은 노트로 하고, 같은 이미지를 "다시 확인"하려고 재열람하지 않는다.
- **글자·수치는 OCR, 말은 STT에서만**: 화면 속 글자, 손글씨, 계기판·다이얼·디지털 표시 수치는 `tesseract`/`scripts/local_ocr.py` 출력만 인용한다. 모델이 읽은 값은 `모델 판독(미검증)`으로 표기하며 OCR과 다르면 OCR 값을 쓴다. Argon은 손글씨 JSON 추출과 다이얼 판독에서 실패 사례가 보고됐다.
- **오디오와 영상은 따로 분석한다**: 음성 내용은 `local_stt.py` 서버 전사본, 시각 내용은 추출 프레임으로 각각 다룬다. 영상 파일을 통째로 모델에 보여 주고 대사를 받아 적게 하지 않는다 — 음성·영상을 분리 입력했을 때 날조가 최소였다는 보고가 있고, 모델 전사에는 명백한 오류 사례가 있다.
- **타임스탬프 표기 규격 (소수점 초 금지)**: STT 전사본 정리 및 보고서·녹취록 인용 시 `384.94s`, `12.0초` 같은 원시 소수점 초(float seconds) 표기를 금지하고, 반드시 `MM분 SS초`(예: `06분 24초`) 또는 `MM:SS`(예: `06:24`, 1시간 이상은 `HH:MM:SS`) 정수 단위로 변환해 표기한다.
- **원문 그대로 기술 (교차검증 메모·임의 윤문 금지)**: 전사 텍스트 및 대화록 본문에 `에이닷 N번 발언 교차확인`, `[전수 검증 완료]` 같은 에이전트 내부 교차검증 메모나 임의 윤문·의역을 섞지 말고 발화 원문 그대로 기술한다.
- 전사·OCR 결과 파일(`.txt`/`.json`)은 증거 매니페스트(`evidence_manifest.py`) 체크포인트에 첨부할 수 있다.
