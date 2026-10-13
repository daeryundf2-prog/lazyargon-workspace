---
name: media-analysis
description: "음성/이미지/영상 파일 분석 워크플로: ffprobe 메타데이터 → 영상 무결성·오디오 서베이 → 프레임 추출(네이티브 비전 분석) → 로컬 Whisper STT 전사 → tesseract OCR. Triggers: media, stt, transcribe, ocr, video analysis, youtube, 음성, 전사, 영상 분석."
metadata:
  short-description: "Media analysis pipeline: probe, frames, OCR, transcription, video/audio survey"
---

# media-analysis

음성·이미지·영상 파일을 분석할 때 이 스킬을 사용한다. 모든 도구는 `lazyargon-workspace`의 로컬 스크립트 및 로컬 바이너리(`ffmpeg`/`ffprobe`/`tesseract`/`whisper-cli`)로 동작하며, 외부 서버로 미디어 원본을 전송하지 않는다.

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
   - `forensic-video`의 `watch.py`로 키프레임을 추출한 뒤, 반환된 이미지 경로를 호스트 네이티브 비전(`Read`)으로 직접 판독한다 (기본 `--detail efficient`, 최대 50프레임):
     ```bash
     ./scripts/py skills/forensic-video/scripts/watch.py <영상파일> --detail efficient --max-frames 50
     ```
3. **로컬 음성 전사 (STT)**:
   - `local_stt.py`를 사용해 로컬 Whisper(`faster-whisper` 또는 `whisper.cpp`)로 전사한다:
     ```bash
     ./scripts/py scripts/local_stt.py <오디오파일_또는_폴더> --verbatim --keywords "주요키워드"
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
| 영상 키프레임 추출 | `skills/forensic-video/scripts/watch.py`, `ffmpeg` | 추출된 프레임을 호스트 Read로 시각 판독 |
| 오디오 구간 서베이 | `scripts/audio_survey.py`, `ffmpeg` | 발화 구간·무음 구간 탐지 |
| 로컬 음성 전사 (STT) | `scripts/local_stt.py` (`faster-whisper` / `whisper-cli`) | 로컬 전용, 외부 업로드 없음 |
| 이미지 OCR | `tesseract` (`kor+eng` traineddata) | 로컬 CLI 직접 실행 |

환경 점검: `./bin/lazyforensic setup --check`
설치 안내 (macOS): `brew install ffmpeg tesseract tesseract-lang whisper-cpp`

## 규칙

- 증거 오디오·영상은 명시적 동의 없이 외부 API로 전송하지 않는다.
- 대용량 영상은 `watch.py --detail efficient --max-frames 50`으로 먼저 개괄 확인한 뒤 필요한 타임스탬프 구간만 `--timestamps`로 정밀 추출한다.
- 전사·OCR 결과 파일(`.txt`/`.json`)은 증거 매니페스트(`evidence_manifest.py`) 체크포인트에 첨부할 수 있다.
