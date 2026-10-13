# 딥페이크 생성 & 합성 기술 전수 카탈로그 (2024~2026.08)

## 1. 비디오 파운데이션 & DiT 생성 모델
- **Wan2.1** (Alibaba Cloud): Flow Matching + Video DiT (1.3B, 14B). 3D Causal VAE (16x16 공간, 4x 시간 압축). T5 다국어 인코더 결합. [Wan-Video/Wan2.1](https://github.com/Wan-Video/Wan2.1)
- **HunyuanVideo & 1.5** (Tencent): Dual-Stream to Single-Stream DiT (13B, 8.3B). Sliding Tile Attention (SSTA) 및 FP8 네이티브 양자화. 4K 비디오 생성. [Tencent-Hunyuan/HunyuanVideo](https://github.com/Tencent-Hunyuan/HunyuanVideo)
- **CogVideoX / 1.5** (THUDM / Zhipu AI): Expert Transformer DiT + 3D VAE (2B, 5B). 모달리티 전용 Expert Adaptive LayerNorm. 768x1360 (16 fps). [THUDM/CogVideo](https://github.com/THUDM/CogVideo)
- **Open-Sora** (HPCAITech): STDiT (Spatial-Temporal DiT) 기반 오픈소스 비디오 모델. [hpcaitech/Open-Sora](https://github.com/hpcaitech/Open-Sora)
- **Open-Sora-Plan** (PKU-YuanGroup): 3D VAE + Causal DiT 비디오 생성 파이프라인. [PKU-YuanGroup/Open-Sora-Plan](https://github.com/PKU-YuanGroup/Open-Sora-Plan)
- **Mochi 1** (Genmo): 10B Asymmetric DiT (AsymmDiT) 고성능 모션 보존 비디오 모델. [genmoai/models](https://github.com/genmoai/models)
- **LTX-Video** (Lightricks): 2B Real-time DiT 단일 소비자 GPU 로컬 렌더링. [Lightricks/LTX-Video](https://github.com/Lightricks/LTX-Video)
- **Kling AI (1.0/1.5/Omni)** (Kuaishou): DiT + 독점 3D Causal VAE. Full-Attention 롤링 컨텍스트 메커니즘. 상용 API.
- **MiniMax Hailuo (Video-01)** (MiniMax): 하이브리드 Linear/Softmax Attention DiT. 물리적 사전 지식 보존. 상용 API.
- **Runway Gen-2 / Gen-3 / Gen-4** (Runway): 멀티모달 DiT + 카메라 모션 컨트롤 브러시. 상용 API.
- **Luma Dream Machine / Ray 2** (Luma AI): 고속 Transformer 기반 실사 물리 렌더링 엔진. 카메라 3D 트래킹. 상용 API.
- **Sora / Sora Turbo** (OpenAI): 시공간 패치(Spatiotemporal Patches) 기반 대규모 DiT. 1분 연속 1080p. 비공개 가중치 / 상용 API.
- **Vidu / Vidu 1.5** (ShengShu / Tsinghua): Universal Visual Engine(UVE) 기반 고속 생성. 상용 API.
- **AnimateDiff (v1~v3, SDXL)**: 사전학습 2D 디퓨전 모델에 Temporal Attention 모션 모듈 주입. [guoyww/AnimateDiff](https://github.com/guoyww/AnimateDiff)
- **SVD / SVD-XT** (Stability AI): Stable Video Diffusion 잠재 비디오 디퓨전. [Stability-AI/generative-models](https://github.com/Stability-AI/generative-models)

## 2. 인물 애니메이션, 토킹 헤드 & 3DGS 아바타
- **LivePortrait** (KwaiVGI): 비디퓨전 암시적 키포인트 모델. 12.8ms/프레임 (RTX 4090 >80 FPS). 스티칭 & 리타겟팅 슬라이더. [KwaiVGI/LivePortrait](https://github.com/KwaiVGI/LivePortrait)
- **Hallo / Hallo2 / Hallo3** (Fudan Univ): 계층적 오디오-비전 디퓨전. Hallo2: 4K 해상도 1시간 연속 무손실 렌더링. Hallo3: VDT 동적 포즈. [fudan-generative-vision/hallo2](https://github.com/fudan-generative-vision/hallo2)
- **EchoMimic (V1~V3)** (Ant Group): V1 랜드마크 디퓨전, V2 APDH 상반신 제스처(CVPR 2025), V3 1.3B DiT 멀티태스크 모션(AAAI 2026). [antgroup/echomimic_v3](https://github.com/antgroup/echomimic_v3)
- **MuseTalk** (Tencent Music): 단일 스텝 잠재공간 인페인팅 GAN. Whisper-tiny 특징 추출 + SIS 시공간 샘플링. 30+ FPS 실시간 립싱크. [TMElyralab/MuseTalk](https://github.com/TMElyralab/MuseTalk)
- **EMO / EMO2** (Alibaba): 약한 조건 오디오-비디오 디퓨전. ReferenceNet ID 보존 + Temporal Attention. 가창/랩 발화 극대화. [HumanAIGC/EMO](https://github.com/HumanAIGC/EMO)
- **LatentSync** (ByteDance): 잠재공간 상 직접 U-Net 구동. TREPA 시공간 정렬 + SyncNet 감독 기반 512x512 고해상도 립싱크. [bytedance/LatentSync](https://github.com/bytedance/LatentSync)
- **FlashAvatar & 3DGS**: 3D Gaussian Splatting 기반 동적 헤드 아바타. UV 공간 가우시안 임베딩 + FLAME 지오메트리. >300 FPS 렌더링. [Awesome-3DGS](https://github.com/mrnerf/awesome-3D-gaussian-splatting)
- **SadTalker** (CVPR 2023): ExpNet + PoseVAE 기반 3D 모션 계수 추출. [OpenTalker/SadTalker](https://github.com/OpenTalker/SadTalker)
- **Wav2Lip / Wav2Lip-HD**: SyncNet 전문가 판별기 기반 입술 합성 GAN. [Rudrabha/Wav2Lip](https://github.com/Rudrabha/Wav2Lip)
- **LivePortrait-Realtime** (커뮤니티): LivePortrait ONNX/TensorRT 경량화 파이프라인. 프레당 ~12.8ms (RTX 4090 >80 FPS). [warmsnow/LivePortrait-Realtime](https://github.com/warmsnow/LivePortrait-Realtime)
- **V-Express** (Tencent AI Lab): 점진적 드롭아웃·균형 제어로 시각적 신원 손실 없이 오디오 구동. [tencent-ailab/V-Express](https://github.com/tencent-ailab/V-Express)
- **AniPortrait** (Tencent): 오디오 → 3D 랜드마크 시퀀스 예측 → Diffusion 렌더링. [ZFormer/AniPortrait](https://github.com/ZFormer/AniPortrait)
- **Champ** (Fudan/Tencent): 3D Parametric Human SMPL-X 가이던스 전신 댄스/모션 합성. [fudan-generative-vision/champ](https://github.com/fudan-generative-vision/champ)
- **MimicMotion** (Tencent): 신뢰도 인식 포즈 가이던스(Confidence-aware Pose) 전신 비디오 생성. [Tencent/MimicMotion](https://github.com/Tencent/MimicMotion)
- **AnimateAnyone** (Alibaba): ReferenceNet 기반 전신 의상/신원 보존 캐릭터 애니메이션. [HumanAIGC/AnimateAnyone](https://github.com/HumanAIGC/AnimateAnyone)

## 3. 얼굴 교체(Face-Swap) 및 신원 보존(Identity Preservation)
> 포렌식 팁: 아래 모델 가중치 파일명(`inswapper_128.onnx` 등)은 압수수색 현장 아티팩트 탐지의 핵심 지표다.
- **PuLID** (NeurIPS 2024): 대조 정렬 손실(Contrastive Alignment)로 텍스트 프롬프트 추종성 보존하며 FLUX/SDXL에 ID 주입. 가중치: `pulid_flux.safetensors`, `pulid_sdxl.safetensors`. [ToTheBeginning/PuLID](https://github.com/ToTheBeginning/PuLID)
- **InstantID**: IdentityNet — InsightFace Antelopev2 임베딩(강한 의미 제약) + 5점 랜드마크(약한 공간 제약) 1-Shot 얼굴 생성. 가중치: `ip-adapter-instantid.bin`. [InstantID/InstantID](https://github.com/InstantID/InstantID)
- **FaceFusion (v3.x)**: YOLOv8-face → InsightFace → BiSeNet 마스크 → CodeFormer/GPEN 복원 모듈형 데스크톱 파이프라인. 가중치: `inswapper_128.onnx`, `codeformer.onnx`. [facefusion/facefusion](https://github.com/facefusion/facefusion)
- **ReActor**: ComfyUI 전용 고속 InsightFace ONNX 실행 노드 (inswapper_128 교체 + 복원 필터 내장). 가중치: `inswapper_128.onnx`, `arcface_resnet50`. [Gourieff/comfyui-reactor-node](https://github.com/Gourieff/comfyui-reactor-node)
- **Rope (Sapphire)**: GPU 가속 실시간 비디오 페이스 스왑 GUI. 동적 오클루전 마스킹, 68점 정렬, 서브픽셀 합성. 가중치: `inswapper_128.onnx`, `simswap_512.onnx`. [Hillobar/Rope](https://github.com/Hillobar/Rope)
- **DeepFaceLab (DFL)**: 오토인코더(SAEHD, Quick96) + 수동 XSeg 마스킹 기반 고품질 딥페이크 툴킷. [iperov/DeepFaceLab](https://github.com/iperov/DeepFaceLab)
- **IP-Adapter-FaceID**: InsightFace 임베딩 크로스 어텐션 투영 모델 (FaceID / Plus / Portrait). 가중치: `ip-adapter-faceid_sdxl.bin`. [tencent-ailab/IP-Adapter](https://github.com/tencent-ailab/IP-Adapter)
- **PhotoMaker / V2**: 단일/다중 레퍼런스 사진 Stacked ID Embedding 기반 캐릭터 일관성 생성. 가중치: `photomaker-v2.safetensors`. [TencentARC/PhotoMaker](https://github.com/TencentARC/PhotoMaker)
- **SimSwap / 512**: ID Injection Module(IIM) + 약한 특징 매칭 손실 기반 얼굴 속성 분리. 가중치: `simswap_512.onnx`. [neuralchen/SimSwap](https://github.com/neuralchen/SimSwap)
- **Ghost / Ghost-UNet**: 원본 표정·조명 보존 원샷 신원 교체 네트워크. 가중치: `ghost_unet.onnx`. [s0md3v/roop](https://github.com/s0md3v/roop) 계열 파생

## 4. 음성 복제(Voice Cloning) & 오디오 합성
- **F5-TTS**: Non-Autoregressive Flow Matching + Sway Sampling. RTF ~0.15 극초고속 제로샷 복제. [SWivid/F5-TTS](https://github.com/SWivid/F5-TTS)
- **CosyVoice 2** (Alibaba): FSQ + Causal Flow Matching. 다국어 억양/호흡/감정 복제. 150ms 스트리밍 지연. [FunAudioLLM/CosyVoice](https://github.com/FunAudioLLM/CosyVoice)
- **Fish Speech (1.0~1.5)** (Fish Audio): Dual-AR (Master 4B + Slave 400M) + GFSQ 코드북. [fishaudio/fish-speech](https://github.com/fishaudio/fish-speech)
- **ChatTTS**: 대화형 LLM 음성 합성 (웃음, 추임새 재현). [2noise/ChatTTS](https://github.com/2noise/ChatTTS)
- **GPT-SoVITS / V2**: 5초 원본 음성 기반 퓨샷 파인튜닝. [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)
- **RVC (Retrieval-based VC)**: HuBERT 특징 추출 + Top-1 이웃 검색 실시간 변환 (<50ms). [RVC-Project/Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)
- **OpenVoice / V2**: 화자 음색(Tone Color) 임베딩 분리 변환. [myshell-ai/OpenVoice](https://github.com/myshell-ai/OpenVoice)
- **VoiceCraft**: Neural Codec LM 마스크드 생성 기반 실시간 오디오 편집·인필링. [jasonppy/VoiceCraft](https://github.com/jasonppy/VoiceCraft)
- **XTTS / XTTS-v2** (Coqui): 17개국어 실시간 제로샷 음성 복제. [coqui-ai/TTS](https://github.com/coqui-ai/TTS)
- **StyleTTS2**: 음성 스타일 확산 모델 + 대규모 적대적 훈련 기반 자연 운율. [yl4579/StyleTTS2](https://github.com/yl4579/StyleTTS2)
- **Mini-Omni / Mini-Omni2**: 음성 입력 → 음성 실시간 스트리밍 출력 end-to-end 옴니 모델. [gpt-omni/mini-omni](https://github.com/gpt-omni/mini-omni)

## 5. ComfyUI 13대 핵심 커스텀 노드
- [kijai/ComfyUI-WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper): Wan2.1 14B/1.3B FP8 비디오 생성
- [kijai/ComfyUI-HunyuanVideoWrapper](https://github.com/kijai/ComfyUI-HunyuanVideoWrapper): Tencent HunyuanVideo DiT 생성
- [kijai/ComfyUI-CogVideoXWrapper](https://github.com/kijai/ComfyUI-CogVideoXWrapper): THUDM CogVideoX 생성
- [kijai/ComfyUI-LivePortraitKJ](https://github.com/kijai/ComfyUI-LivePortraitKJ): LivePortrait 실시간 표정/포즈 제어
- [Gourieff/comfyui-reactor-node](https://github.com/Gourieff/comfyui-reactor-node): ReActor 페이스 스왑 & 복원
- [balazsbear/ComfyUI_PuLID_Flux_Enhanced](https://github.com/balazsbear/ComfyUI_PuLID_Flux_Enhanced): PuLID 기반 FLUX.1 ID 보존
- [ZHO-ZHO-ZHO/ComfyUI-InstantID](https://github.com/ZHO-ZHO-ZHO/ComfyUI-InstantID): InstantID 제로샷 얼굴 합성
- [chflame163/ComfyUI-LatentSyncWrapper](https://github.com/chflame163/ComfyUI-LatentSyncWrapper): ByteDance LatentSync 립싱크
- [niknah/ComfyUI-F5-TTS](https://github.com/niknah/ComfyUI-F5-TTS): F5-TTS 비자기회귀 음성 복제
- [AIFSH/ComfyUI-CosyVoice](https://github.com/AIFSH/ComfyUI-CosyVoice): CosyVoice 2 음성 복제
- [kijai/ComfyUI-SUPIR](https://github.com/kijai/ComfyUI-SUPIR): SUPIR 초고해상도 디테일 복원 및 잠재공간 정제
- [ltdrdata/ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack): FaceDetailer 국소 탐지 및 재보정
- [Kosinkadink/ComfyUI-AnimateDiff-Evolved](https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved): AnimateDiff 모션 로라 제어
