# Programmatic Showreel & FFmpeg Videogen (`revfactory/showreel@64521220a2f8` 증류)

수동 타임라인 편집 없이 JSON 선언(`scene_manifest/v1`)과 결정적 FFmpeg 필터그래프만으로 제품 데모·포렌식 브리핑·쇼릴 영상을 합성하는 `revfactory/showreel` (`omh-show-reel`) 레퍼런스다. 원본 증거 영상에는 적용하지 않으며, 홍보·요약·시각 브리핑용 파생 영상 생성에만 사용한다.

## 1. `scene_manifest/v1` JSON 설계 스키마

각 씬(Scene)의 지속 시간, 비주얼 에셋, 모션 프리셋, 타이포그래피 오버레이, 전환 효과를 단일 매니페스트로 정의한다.

```json
{
  "schema": "scene_manifest/v1",
  "title": "LazyArgon v2.0 Showreel",
  "resolution": "1920x1080",
  "fps": 30,
  "audio": {
    "bgm": "assets/bgm.mp3",
    "narration": "assets/voiceover.wav",
    "ducking_threshold": 0.03,
    "ducking_ratio": 6
  },
  "scenes": [
    {
      "id": "scene_01_intro",
      "duration_sec": 4.0,
      "source": "assets/slide_01.png",
      "motion": "zoom_in_center",
      "caption": {
        "text": "Deterministic Agentic Engineering",
        "fontfile": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "fontsize": 56,
        "fontcolor": "white",
        "boxcolor": "black@0.55"
      },
      "transition": { "type": "fadeblack", "duration_sec": 0.5 }
    },
    {
      "id": "scene_02_metrics",
      "duration_sec": 4.5,
      "source": "assets/slide_02.png",
      "motion": "pan_left_to_right",
      "caption": {
        "text": "Zero-Slop Guard & Formal Verification",
        "fontfile": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "fontsize": 52,
        "fontcolor": "white",
        "boxcolor": "black@0.55"
      },
      "transition": { "type": "smoothleft", "duration_sec": 0.5 }
    }
  ]
}
```

## 2. 핵심 FFmpeg 필터그래프 레시피
### 2.1 켄 번즈 줌팬(`zoompan`) + 모션 타이포그래피(`drawtext`)
정지 이미지를 30fps 부드러운 줌인 클립으로 변환하고 페이드인 자막 박스를 하단 중앙에 합성한다.
```bash
ffmpeg -y -loop 1 -t 4 -i slide_01.png \
  -vf "scale=3840:2160,zoompan=z='min(zoom+0.0012,1.18)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=120:s=1920x1080:fps=30,drawtext=fontfile='/System/Library/Fonts/Supplemental/Arial Bold.ttf':text='Deterministic Agentic Engineering':fontsize=56:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=18:x=(w-text_w)/2:y=h-160:alpha='if(lt(t,0.4),t/0.4,1)'" \
  -c:v libx264 -pix_fmt yuv420p -r 30 scene_01.mp4
```
### 2.2 씬 간 크로스페이드 전환(`xfade`)
두 씬 클립(`scene_01.mp4` 4.0초, `scene_02.mp4` 4.5초)을 `offset=3.5` 지점에서 0.5초 동안 자연스럽게 연결한다.

```bash
ffmpeg -y -i scene_01.mp4 -i scene_02.mp4 \
  -filter_complex "[0:v][1:v]xfade=transition=smoothleft:duration=0.5:offset=3.5,format=yuv420p[v]" \
  -map "[v]" -c:v libx264 -crf 18 merged_video.mp4
```

### 2.3 내레이션 연동 오디오 덕킹(`sidechaincompress`)

내레이션(`1:a`)이 발화할 때만 배경음악(`0:a`) 볼륨을 자동으로 낮추고 발화 종료 후 복원해 명료도를 확보한다.

```bash
ffmpeg -y -i merged_video.mp4 -i bgm.mp3 -i voiceover.wav \
  -filter_complex "[1:a]volume=0.35[bgm];[2:a]asplit=2[vo_sc][vo_mix];[bgm][vo_sc]sidechaincompress=threshold=0.03:ratio=6:attack=40:release=400[bgm_ducked];[bgm_ducked][vo_mix]amix=inputs=2:duration=first:dropout_transition=2[aout]" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 192k showreel_final.mp4
```

## 3. 품질 및 타이밍 불변식

| 점검 항목 | 기준값 | 비고 |
| :--- | :--- | :--- |
| 픽셀 포맷 / 프레임레이트 | `yuv420p` / 고정 `30fps` (`-r 30`) | `xfade` 타임베이스 불일치 오류 방지 |
| `xfade` 오프셋 공식 | `offset = sum(prev_durations) - sum(prev_transitions)` | 누적 전환 시간 차감 필수 |
| 자막 안전 영역 (Safe Area) | 상하좌우 여백 `>= 8%` (`y <= h-140`) | 플레이어 컨트롤 바 가림 방지 |
