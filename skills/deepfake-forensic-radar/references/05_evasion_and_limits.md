# 지능형 탐지 우회 기법 및 실제 환경(In-the-Wild) 한계 분석

## 1. 지능형 탐지 우회 기법 (Evasion Attacks)
1. **아날로그 루프 (Analog Re-capture)**: 모니터 화면을 스마트폰으로 재촬영하거나 인쇄 후 스캔(Print & Scan). 카메라 센서 노이즈(PRNU)와 렌즈 왜곡이 덧씌워져 탐지기가 99% 확률로 "진짜 사진" 판정.
2. **필름 그레인 & 가우시안 노이즈 주입**: ComfyUI 상에서 미세 아날로그 질감을 합성하여 생성 모델 고유의 고주파 격자 지문을 파괴.
3. **Latent Img2Img 재정제 (Low Denoise Refinement)**: SUPIR/ControlNet Tile을 이용해 Denoising Strength 0.15~0.25 수준으로 2차 재합성 시 잠재공간 시그니처가 완전 세척됨.
4. **적대적 섭동 (Adversarial Perturbation)**: 사람 눈에는 보이지 않는 미세 역전파 노이즈(DiffJPEG, AdvImage)를 주입하여 분류기 판정을 강제 역전.
5. **C2PA 헤더 스트리핑**: 소셜 플랫폼 업로드 또는 단순 캡처만으로 JUMBF 메타데이터 100% 무력화.

## 2. 실제 환경(In-the-Wild) 탐지 성능 붕괴
- **손실 압축에 의한 주파수 파괴**: WhatsApp, Telegram, YouTube, X(Twitter) 업로드 시 크로마 서브샘플링(4:2:0) 및 강한 양자화로 고주파 지문이 소실되어 탐지 정확도가 **50~65% (동전 던지기 수준)**로 추락.
- **메신저 전송 방식 차이**:
  - **Telegram 사진 모드 / WhatsApp / X(이미지)**: EXIF/C2PA 100% 제거, 강한 JPEG 재압축 $\to$ 탐지 불가.
  - **Telegram 파일 모드(File/문서)**: 100% 원본 비트스트림 및 메타데이터 보존 $\to$ 정밀 포렌식 가능.
- **텍스트 탐지기 역차별**: 비원어민(ESL) 작문 및 학술 논문 초록이 40% 이상의 높은 오탐률로 AI 판정되는 신뢰성 붕괴.
