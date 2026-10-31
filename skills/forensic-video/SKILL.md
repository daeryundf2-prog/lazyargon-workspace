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

**STT는 내부(로컬) Whisper 대신 서버 STT를 기본으로 쓴다**:
- URL 또는 유튜브 영상 입력 시 `yt-dlp`로 유튜브 서버 자동자막(VTT)을 최우선 추출한다.
- 자막이 없거나 로컬 영상인 경우 기본값(`--whisper google`)으로 `ffmpeg` 16kHz PCM 청크를 Google Speech-to-Text 서버(`recognize_google`)에 병렬 전송해 전사한다. Groq/OpenAI 서버를 지정하려면 `--whisper groq` 또는 `--whisper openai`를 사용한다.

```bash
python skills/forensic-video/scripts/watch.py "<동영상경로>" --upload-audio --whisper google
```

`--upload-audio`는 기본값이 켜짐이며, 업로드를 막으려면 `--no-upload-audio`를 쓴다. 프레임 수는 `--max-frames`(0~100), 구간은 `--start`/`--end`, 특정 시점은 `--timestamps`, 밀도는 `--detail {transcript,efficient,balanced}`로 조절한다. URL 입력은 편의 다운로드일 뿐 포렌식 이미징이나 Chain of Custody가 아니다.

## Antigravity

추출된 프레임은 호스트 `Read`로 본다. `view_file`을 만들지 말 것.
해석과 태그 vs `os.stat` 대조는 `invoke_subagent` `Model: "inherit"`로 위임한다 (세션 모델을 그대로 쓴다).
번호판·신원 단정, 편집 여부 확정을 쓰지 않는다.

## 야간/저화질 영상 번호판 분석 및 소거법 절차 (로컬 실무 세션 7328aa53)

야간 블랙박스·CCTV 영상의 헤드라이트 빛번짐·모션블러 환경에서는 단순 OCR(Tesseract 등)이 실패하거나 번호를 날조할 위험이 높다. 아래 1~3 기법은 세션 작업 메모이며, 이 스킬의 스크립트에는 구현되어 있지 않다(ECC 정렬·IBP·노치 필터 코드 없음). 결과는 가설로만 쓰고 번호판을 확정하거나 신원을 단정하지 않는다.
1. **다중 프레임 스태킹**: 차량 정지 구간 프레임 전수 추출 및 ECC(Enhanced Correlation Coefficient) 정렬 스태킹.
2. **초해상화 재구성**: IBP(Iterative Back-Projection) 기법으로 번호판 윤곽 및 획 에지 복원.
3. **노치 필터 주파수 디스트라이핑**: 롤링셔터·LED 점멸에 의한 가로 줄무늬 노이즈를 2D FFT 노치 필터로 제거.
4. **법률 제식 규정 기반 소거법**(국토교통부 「자동차등록번호판 등의 제식에 관한 고시」, 현행 원문으로 확인할 것):
   - 비사업용 일반 승용차(흰색 번호판)는 사업용(노란색 택시·버스·택배) 전용 문자('바, 사, 아, 자, 배')는 후보에서 제외할 수 있다 (고시 원문 확인 필요).
   - 렌터카('하, 허, 호') 한글 획 토폴로지 대조('호'의 하단 획 유무 등)로 후보 압축.
   - 신형 3자리(100~699) vs 구형 2자리 차종 기호 분류 및 슬롯별 경계 힌트 결합 소거 매트릭스 도출.

