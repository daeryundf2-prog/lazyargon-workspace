---
name: forensic-video
description: CCTV/블랙박스 프레임 추출·ffprobe 태그. ffmpeg 필요. 촬영일시 조작의 법정 증명에는 쓰지 말 것.
---

# forensic-video

프레임을 뽑고 컨테이너 태그를 읽는다. 촬영 시점을 확정하지 않는다.

## 실행

```bash
python skills/forensic-video/scripts/setup.py --check
python skills/forensic-video/scripts/watch.py "<동영상경로>" --resolution 720
python skills/forensic-video/scripts/forensic_video_audit.py "<동영상경로>"
```

기본 실행은 오디오를 외부로 보내지 않는다. Groq/OpenAI 전사가 꼭 필요하고 의뢰인 동의·반출 승인이 있는 경우에만 다음처럼 명시한다.

```bash
python skills/forensic-video/scripts/watch.py "<동영상경로>" --upload-audio --whisper groq
```

`--upload-audio`는 추출 오디오를 제3자 API로 전송한다. URL 입력은 편의 다운로드일 뿐 포렌식 이미징이나 Chain of Custody가 아니다. 프레임은 최대 100개다.

## Antigravity

추출된 프레임은 호스트 `Read`로 본다. `view_file`을 만들지 말 것.
해석은 `invoke_subagent` `Model: "inherit"`, 태그 vs `os.stat` 대조는 `Model: "inherit"`(세션 모델과 무관, Claude 할당량 절약).
번호판·신원 단정, 편집 여부 확정을 쓰지 않는다.
