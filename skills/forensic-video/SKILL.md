---
name: forensic-video
description: CCTV/블랙박스·유튜브 영상 프레임 추출·서버 STT/유튜브 자동자막·ffprobe 태그. ffmpeg 필요. 촬영일시 조작의 법정 증명에는 쓰지 말 것.
---

# forensic-video

프레임과 서버 STT/유튜브 자동자막을 뽑고 컨테이너 태그를 읽는다. 촬영 시점을 확정하지 않는다.

## 실행

```bash
python skills/forensic-video/scripts/setup.py --check
python skills/forensic-video/scripts/watch.py "<동영상경로_또는_URL>" --resolution 720
python skills/forensic-video/scripts/forensic_video_audit.py "<동영상경로>"
```

**STT는 내부(로컬) Whisper를 쓰지 않고 무조건 서버 STT를 기본 사용한다**:
- URL 또는 유튜브 영상 입력 시 `yt-dlp`로 유튜브 서버 자동자막(VTT)을 최우선 추출한다.
- 자막이 없거나 로컬 영상인 경우 기본값(`--whisper google`)으로 `ffmpeg` 16kHz PCM 청크를 Google Speech-to-Text 서버(`recognize_google`)에 병렬 전송해 전사한다. Groq/OpenAI 서버를 지정하려면 `--whisper groq` 또는 `--whisper openai`를 사용한다.

```bash
python skills/forensic-video/scripts/watch.py "<동영상경로>" --upload-audio --whisper google
```

URL 입력은 편의 다운로드일 뿐 포렌식 이미징이나 Chain of Custody가 아니다. 프레임은 최대 100개다.

## Antigravity

추출된 프레임은 호스트 `Read`로 본다. `view_file`을 만들지 말 것.
해석은 `invoke_subagent` `Model: "inherit"`, 태그 vs `os.stat` 대조는 `Model: "inherit"`(세션 모델과 무관, Claude 할당량 절약).
번호판·신원 단정, 편집 여부 확정을 쓰지 않는다.
