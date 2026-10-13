# 딥페이크 탐지 알고리즘 및 물리·생체 포렌식 불변량 전수 분석

## 1. 딥페이크 탐지 알고리즘 및 벤치마크
- **DeepfakeBench** (SJTU/OpenDataLab): 30개 이상의 탐지기와 15개 벤치마크(FF++, Celeb-DF, DF40) 표준화 통합 플랫폼. [SCLBD/DeepfakeBench](https://github.com/SCLBD/DeepfakeBench)
- **UnivFD** (Univ. of Wisconsin): CLIP-ViT 백본을 동결하고 선형 프로브만 학습하여 미학습 디퓨전/GAN 모델에 대해 **GenImage 평균 92.3% AUC**(논문 보고) 달성. [Yuheng-Li/UniversalFakeDetect](https://github.com/Yuheng-Li/UniversalFakeDetect)
- **DIRE / DistilDIRE**: DDIM Inversion 후 재구성 오차 $\text{DIRE}(x) = |x - \mathcal{R}(x)|$를 측정하는 디퓨전 생성 이미지 탐지. [ZhendongWang6/DIRE](https://github.com/ZhendongWang6/DIRE)
- **NPR** (CVPR 2024): 업샘플링 보간 레이어가 남기는 인접 픽셀 간 비자연적 수학적 잔재 추출 (논문 보고 평균 91.4% AUC). [chuangchuangtan/NPR-DeepfakeDetection](https://github.com/chuangchuangtan/NPR-DeepfakeDetection)
- **F3-Net**: 주파수 대역 분할(FAD) 및 국소 주파수 통계(LFS)로 DCT 고주파 지문 포착. [weixiang/F3-Net](https://github.com/weixiang/F3-Net)
- **SPSL**: 2D 푸리에 변환 위상 스펙트럼($\Phi(u,v)$) 불연속성 검출. [clfm/SPSL](https://github.com/clfm/SPSL)
- **FreqNet**: 고주파 표현 스트림(HFR) + 푸리에 복소 가중 합성곱 기반 고주파 중심 탐지.
- **LGrad**: 사전학습 CNN의 그래디언트 맵 $G(x) = \nabla_x L(x)$로 의미 정보를 지우고 생성 잔재만 노출. [chuangchuangtan/LGrad](https://github.com/chuangchuangtan/LGrad)
- **RECCE**: 오토인코더 재구성 오차 맵 + 엣지 가이던스 결합 국소 조작 검출.
- **SBI (Self-Blended Images)**: 외부 가짜 데이터 없이 실제 사진 자체를 블렌딩해 가짜 학습 데이터를 합성 — 범용 탐지기 훈련법. [maple-research-lab/sbi](https://github.com/maple-research-lab/sbi)
- **FakeShield**: MLLM(LLaVA/Qwen-VL) 기반 위조 판별 + 픽셀 위조 히트맵 마스크 + 소명 텍스트 동시 출력. [Jizk/FakeShield](https://github.com/Jizk/FakeShield)
- **VIGIL**: 조명 일관성 에이전트 + 주파수 에이전트 + 해부학 에이전트가 협업하는 다중 에이전트 포렌식 추론.
- **LipForensics**: 시공간 ResNet을 통해 양순음 발음 시 입술 모션 불규칙성 검출 (압축에 극도로 강인). [ControlNet/LipForensics](https://github.com/ControlNet/LipForensics)
- **FakeCatcher** (Intel Labs / Binghamton Univ.): 32개 안면 관심영역(ROI)에서 rPPG 혈류 펄스를 추출하여 위상 일관성 검증.
- **CNNDetection** (Wang et al.): ProGAN 1종만 학습해 타 GAN 출력을 제로샷 탐지하는 초기 표준. [PeterWang512/CNNDetection](https://github.com/PeterWang512/CNNDetection)

## 2. 물리·생체 불변량 6대 포렌식 측정 체계
1. **rPPG 혈류 펄스 (FakeCatcher / DeepRhythm)**: 심장 박동에 따른 0.75~2.5 Hz 미세 혈류 색상 변화를 32개 ROI에서 측정. 이마와 뺨의 위상 반전 및 상관계수 붕괴 포착.
2. **각막 반사광(Corneal Specular Reflection) 기하학**: 양안 각막의 광원 반사 벡터 평행성 ($\vec{L}_L \cdot \vec{L}_R \approx 1.0$) 검증. 생성 모델의 양안 3D 광선 추적 불일치 검출 (Hu et al.).
3. **동공 윤곽 기하학**: Fourier Descriptor 기반 동공 경계면의 비타원형/다각형 왜곡률 측정.
4. **2D FFT 방사상 전력 스펙트럼 붕괴**: $1/f^\alpha$ 전력법칙 이탈 및 전치 합성곱에 의한 규칙적 체커보드 스파이크 검출.
5. **음소-시소(Lip) 동기화**: 양순음(/p/,/b/,/m/) 발음 시 음향 파형과 입술 닫힘 간 50~150ms 시공간 오프셋 측정.
6. **PRNU 센서 지문 결핍**: 카메라 하드웨어 고유 광반응 불균일성(PRNU) 잡음의 부재 검증.

## 3. 탐지 기법 특성 비교표 (정성 평가)
> 정량 AUC는 데이터셋·압축 조건·전처리에 따라 크게 달라진다. 본 표는 특성을 정성적으로 비교한 것이며, 수치는 반드시 원논문/DeepfakeBench 재현 결과에서 직접 확인한다.

| 탐지 모델 | 기법 분류 | 교차 일반화 | 압축 내구성 | 비고 |
| :--- | :--- | :---: | :---: | :--- |
| **Xception** | 공간 CNN | 낮음 (학습 생성기에 과적합) | 취약 | FF++ 세대 베이스라인 |
| **F3-Net** | 주파수 (DCT) | 보통 | 우수 | 고주파 지문 의존 |
| **SPSL** | 위상 스펙트럼 | 보통 | 우수 | 얼굴 블렌딩 경계 검출 |
| **UnivFD** | CLIP-ViT 선형 프로브 | **매우 높음** | 높음 | GenImage 평균 92.3%(논문 보고) |
| **DIRE** | 디퓨전 재구성 오차 | 높음 (디퓨전 계열) | 높음 | GAN 계열엔 불리 |
| **NPR** | 인접 픽셀 보간 | 높음 | 높음 | 업샘플링 잔재 특이 |
| **FakeCatcher** | 생체 혈류 신호 (rPPG) | 높음 | 압축 시 취약 | 비디오 전용, 고해상도 요구 |
| **LipForensics** | 시공간 립 다이내믹스 | **매우 높음** | **극도로 우수** | 토킹헤드 비디오 전용 |
| **CNNDetection** | CNN 아티팩트 | GAN 계열 한정 | 보통 | ProGAN 학습 → 제로샷 |
| **SBI** | 합성 학습 데이터 | **매우 높음** | 높음 | 탐지기 훈련 프레임워크 |
| **FakeShield** | MLLM 추론 | 높음 | 보통 | 설명 가능 + 픽셀 히트맵 |

## 4. 글로벌 벤치마크 데이터셋 (전수 목록)
- **FaceForensics++ (FF++)**: 1,000개 원본 비디오, 4개 조작 기법(Deepfakes, Face2Face, FaceSwap, NeuralTextures), 3단계 압축(c0 무압축 / c23 고화질 / c40 저화질).
- **Celeb-DF / v2**: 연예인 유튜브 영상 기반 고품질 딥페이크 5,639개 — 초기 FF++의 깜빡임/색상 결함 개선 고난도 데이터셋.
- **DFDC** (Deepfake Detection Challenge): Facebook/AWS 주관, 10만 개 이상 비디오의 대규모 상용 벤치마크.
- **DF40**: 40가지 최신 딥페이크 생성 기법을 망라해 DeepfakeBench에 통합된 최신 벤치마크.
- **GenImage**: Stable Diffusion, Midjourney, Wukong, ADM, VQ-DM, Glide 등 8개 생성기 기반 100만 장 이상 AI 생성 이미지.
- **DiffusionForensics**: SDXL, DeepFloyd, Midjourney v5/v6 등 최신 디퓨전 위조 탐지 전용.
- **WildDeepfake / Deepfake-Eval-2024**: 실제 소셜 미디어(Telegram, Reddit, X)에서 수집한 야생(In-the-Wild) 데이터셋 — 보고된 벤치마크 수치와 실전 성능 격차 측정 기준.
- **AVFakeBench / FakeAVCeleb**: 비디오+오디오 동시 조작 멀티모달 위조 벤치마크.
- **MMTD-Set**: MLLM의 위조 영역 분할 + 텍스트 설명 학습용 멀티모달 캡션 데이터셋.
