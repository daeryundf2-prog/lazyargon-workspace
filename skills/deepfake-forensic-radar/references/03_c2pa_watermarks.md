# C2PA 출처 인증 표준 및 능동 워터마킹 기술 스펙

## 1. C2PA (Content Credentials) 표준 아키텍처
- **표준 기구**: C2PA 연합 (Adobe, Microsoft, Google, Intel, BBC, Truepic, Leica, Sony).
- **기술 규격**: ISO/IEC 19566-5 JUMBF (JPEG Universal Metadata Box Format) 매니페스트 저장소.
- **주요 구조**:
  - `c2pa.actions`: 생성(created), AI 생성(ai_generated), 색상 조정(color_adjustments) 이력.
  - `c2pa.hash.data`: 매니페스트를 제외한 원본 자산의 바이트 레벨 SHA-256 해시 바인딩(Hard Binding).
  - X.509 PKI 인증서 기반 ECDSA (P-256/P-384) / Ed25519 디지털 서명.
- **소프트 바인딩 (Soft Binding)**: 소셜 플랫폼 업로드로 JUMBF 헤더가 삭제될 경우, 미디어의 시각 특징점 또는 능동 워터마크를 통해 클라우드 매니페스트 원장을 역조회.
- **공식 오픈소스 도구**: [c2pa-rs (Rust)](https://github.com/c2pa-org/c2pa-rs), [c2pa-js (JavaScript)](https://github.com/contentauth/c2pa-js).

## 2. 능동 워터마킹 기술 (Active Watermarking)
- **SynthID (Google DeepMind)**:
  - **SynthID-Text**: 토큰 생성 시 의사난수 해시 기반 토너먼트 샘플링 (G-criterion). 30토큰 이상에서 AUC > 0.99 (Nature 2024).
  - **SynthID-Image/Video**: 비가시성 잠재공간 적대적 CNN 워터마크 주입.
- **Stable Signature (Meta FAIR, ICCV 2023)**:
  - LDM의 **VAE Decoder 가중치에 k-bit 서명을 직접 각인**. 어떤 프롬프트나 시드로 생성해도 출력물에 서명 영구 내장. [facebookresearch/stable_signature](https://github.com/facebookresearch/stable_signature)
- **Tree-Ring Watermark (Wen et al., NeurIPS 2023)**:
  - 초기 노이즈 $x_T$의 **푸리에 도메인에 동심원 링 패턴 M 주입**. DDIM Inversion으로 역추적 검증. 논문은 회전/크롭/이동에 대한 불변성을 주장한다(실제 강건성은 구현·공격 조건에 따라 달라짐). [YuxinWenRick/tree-ring-watermark](https://github.com/YuxinWenRick/tree-ring-watermark)
- **RingID (IEEE S&P)**: 디퓨전 모델을 위한 동심원 링 코드북 임베딩.
- **StegaStamp / HiDDeN**: 딥러닝 기반 비가시적 하이퍼링크 은닉 및 Print & Scan 내구성 제공.
