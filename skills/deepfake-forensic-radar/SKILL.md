---
name: deepfake-forensic-radar
description: 2026년 8월 기준 딥페이크 생성·탐지·출처인증·사법증거 관련 기술 레퍼런스 모음과 1차 정량 분석(해시·C2PA·EXIF·FFT) 보조 스킬. 최종 생성/원본 판정은 별도 다중 탐지기 앙상블이 필요하다.
---

# deepfake-forensic-radar: 딥페이크 통합 기술 레이더 & 포렌식 분석기

2024~2026년 8월 기준 공개된 **주요 딥페이크 생성·합성 모델**, **위조 탐지 및 물리·생체 포렌식 불변량**, **C2PA/워터마크 출처 인증 표준**, **ComfyUI 오픈소스 생태계**, **지능형 우회 공격 기법** 및 **국내외 사법 체계(성폭력처벌법 제14조의2 개정, ECFS 무결성 요건)**를 참조하는 레퍼런스 모음 + 1차 정량 분석 스킬이다. "공개된 모든 모델을 안다"는 주장이 아니며, 신규·비공개 모델은 레퍼런스에 없을 수 있다.

---

## 🎯 기술 영역별 심층 레퍼런스 색인

본 스킬은 요청의 성격에 따라 다음 전수 레퍼런스를 즉시 참조한다:

| 영역 | 레퍼런스 파일 | 핵심 내용 |
| :--- | :--- | :--- |
| **생성 & 합성 모델** | [`references/01_generation_synthesis.md`](references/01_generation_synthesis.md) | Wan2.1, HunyuanVideo, CogVideoX, Kling, LivePortrait(12.8ms), Hallo2(4K 1hr), EchoMimic, PuLID, InstantID, F5-TTS(RTF 0.15), CosyVoice 2, ComfyUI 13대 노드 전수 |
| **탐지 & 생체 포렌식** | [`references/02_detection_forensics.md`](references/02_detection_forensics.md) | DeepfakeBench 30종, UnivFD(92.3%), DIRE, NPR, F3-Net, SPSL, FakeShield(MLLM), rPPG 혈류 펄스, 각막 반사광 3D 광선 추적, 립싱크 위상차, 벤치마크 데이터셋 9종(FF++/Celeb-DF/DFDC/DF40/GenImage 등) |
| **출처 인증 & 워터마크** | [`references/03_c2pa_watermarks.md`](references/03_c2pa_watermarks.md) | C2PA v1.3/v2.0 ISO JUMBF, Hard/Soft 바인딩, PKI 서명, SynthID(Text/Image/Video), Stable Signature VAE 각인, Tree-Ring 푸리에 노이즈 |
| **국내외 사법 & 증거능력**| [`references/04_legal_and_court.md`](references/04_legal_and_court.md) | 성폭력처벌법 제14조의2(소지·시청죄 신설, 반포목적 삭제, 계속범 법리), 성인 신분위장수사(2025.06), 형소법 제310조의2/313조 SHA-256 무결성, Daubert 표준 |
| **우회 기법 & 실전 한계** | [`references/05_evasion_and_limits.md`](references/05_evasion_and_limits.md) | 아날로그 재촬영(PRNU), 필름 그레인 주입, Latent Img2Img 저강도 세척, 적대적 섭동, Telegram/WhatsApp 4:2:0 압축 붕괴(50~65% 추락), ESL 역차별 |

---

## 🛡️ 프로덕션 4계층 하이브리드 방어 파이프라인

```
                                  [수집된 미디어 파일]
                                           │
                         1단계: 암호학적 매니페스트 검증 (O(1) ms)
                                           │
                     ┌─────────────────────┴─────────────────────┐
               [C2PA 서명 유효]                            [C2PA 부재 / 스트리핑]
                     │                                           │
           X.509 루트 PKI 검증                          2단계: 능동 워터마크 스캔 (O(10) ms)
                     │                                           │
          ┌──────────┴──────────┐                  ┌─────────────┴─────────────┐
     [AI 생성 서명 검출]   [카메라 촬영 서명 검출]   [SynthID / Tree-Ring 검출]   [워터마크 미검출]
    (EU AI Act 분류)     (하드웨어 서명 인증)       (서명 기반 출처 단서 — 위조/제거 가능성 별도 검토) │
                                                                       3단계: 수동 앙상블 고속 스크리닝 (O(100) ms)
                                                                                   │
                                                          ┌────────────────────────┼────────────────────────┐
                                                          ▼                        ▼                        ▼
                                                    [UnivFD / NPR]          [DIRE / RECCE]          [rPPG / LipForensics]
                                                   (공간/텍스처 아티팩트)     (디퓨전 재구성 오차)       (생체 신호 & 립 다이내믹스)
                                                          │                        │                        │
                                                          └────────────────────────┼────────────────────────┘
                                                                                   │
                                                                      판정 모호 구간 (0.40 ≤ p ≤ 0.70)
                                                                                   │
                                                                                   ▼
                                                                      4단계: MLLM 포렌식 추론 (FakeShield)
                                                                                   │
                                                                                   ▼
                                                                      [포렌식 분석 보고서 초안]
                                                                    (픽셀 위조 히트맵 + 소명 텍스트 + SHA-256)
                                                                    — 법정 제출용 감정서가 아닌 1차 분석 문서
```

---

## 💻 CLI 분석 스크립트 실행 레시피

`scripts/analyze_deepfake_evidence.py`를 호출하여 원본 미디어의 해시, C2PA 매니페스트, EXIF, 2D FFT 주파수 스펙트럼 아티팩트를 추출하고 1차 정량 분석 마크다운 보고서 초안을 작성할 수 있다. 이 출력은 "법정 제출용 감정서"가 아니라 다중 탐지기 앙상블 등 후속 검증의 입력물이다.

```bash
# 1. 단일 이미지/비디오 1차 표면 포렌식 분석 및 마크다운 리포트 생성
python scripts/analyze_deepfake_evidence.py "증거_영상.mp4" --output "포렌식_분석서.md"

# 2. JSON 정량 측정값만 추출 (파이프라인 연계용)
python scripts/analyze_deepfake_evidence.py "위조의심_사진.jpg" --json

# 3. 2D FFT 주파수 스펙트럼 체커보드 스파이크 시각화 플롯 저장
python scripts/analyze_deepfake_evidence.py "위조의심_사진.png" --plot-fft "fft_spectrum.png"
```

---

## ⚖️ 사법 포렌식 감정 시 필수 준수 원칙

1. **상용 AI 판별기 확률 스코어("92% AI") 단독 제출 절대 금지**: 법원(형사소송법 제310조의2, 제313조)은 블랙박스 AI 탐지기 점수를 독립 증거로 채택하지 않는다.
2. **증거 연계보관성(Chain of Custody) 확보**: 압수 시점부터 법정 제출 시점까지 **SHA-256 해시 일치 증명서**, 원본 비트스트림 이미지(E01, DD),  파일시스템 타임스탬프를 병합 기재해야 한다.
3. **손실 압축 플랫폼 전송 이력 확인**: Telegram Photo, WhatsApp, X를 거친 파일은 압축으로 고주파 주파수 지문이 파괴되므로, 무압축 `File(문서)` 원본 확보를 최우선 권고한다.
