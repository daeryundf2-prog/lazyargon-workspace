---
name: korean-doc-parser
description: "한국 공문서(HWP, HWPX, PDF) 텍스트, 표, 메타데이터 추출 및 마크다운 구조화 스킬. 한컴 오피스 무설치 환경 지원. Triggers: hwp 파싱, hwpx 파싱, 공문서 파싱, 한글 문서 열기, 한글 파서."
---

# Korean Document Parser (HWP / HWPX / PDF)

한컴 오피스나 무거운 바이너리 의존성 없이, 순수 파이썬 및 최신 오픈소스 파서를 활용하여 대한민국 공문서 포맷(`HWPX`, `HWP 5.0`, `PDF`)의 텍스트, 표(Table), 메타데이터를 추출하고 마크다운/JSON으로 변환합니다.

## 핵심 도구

- **스크립트:** `${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/parse_korean_doc.py <파일경로> [--markdown] [--output <결과경로>]`
- **지원 포맷:**
  - `HWPX`: OWPML ZIP/XML 구조 파싱 (섹션별 본문, 표, 서식 메타데이터) — 의존성 없음. 네임스페이스 무관 로컬 이름 매칭이라 한컴 버전과 무관하게 동작. 본문 `text`는 표 셀 내용을 제외하며, 표는 `tables` 필드로 별도 제공(중복 없음).
  - `HWP 5.0`: `hwp-hwpx-parser`(HWP5Reader) 우선, 미설치 또는 파싱 실패 시 `olefile` 원시 스트림 폴백. 폴백은 레코드 구조를 해석하지 않는 **휴리스틱 추출**이라 깨진 문자가 남고 표/개요 구조는 유실됨 — 결과 JSON의 `metadata.quality = "rough"`로 표시되며, 정확한 추출이 필요하면 `pip install hwp-hwpx-parser`.
  - `PDF`: 텍스트층 추출 — `pymupdf` (권장), 실패/미설치 시 `pypdf` 폴백. 두 파서 모두 실패하면 양쪽 오류 사유를 함께 반환. 스캔본(이미지 PDF)은 텍스트가 비어 나오므로 별도 OCR 도구가 필요합니다 (roadmap: docling 연동).
  - `Docling OCR` (선택): 스캔본 PDF의 경우 `docling` 연동을 통한 CJK 고정밀 인식.

## 의존성

```bash
pip install -r ${PLUGIN_ROOT}/requirements.txt        # 전체
# 또는 최소: pip install olefile pymupdf pypdf
```

## 사용법

```bash
# 1. HWPX 문서 마크다운으로 파싱
${PLUGIN_ROOT}/scripts/py scripts/parse_korean_doc.py "압수문서.hwpx" --markdown --output parsed.md

# 2. JSON 구조화 출력
${PLUGIN_ROOT}/scripts/py scripts/parse_korean_doc.py "계약서.hwp" --output parsed.json

# 3. 파서 벤치마크 (페이지/초 + 표 재현도 — README/문서에 수치를 적기 전 실행)
${PLUGIN_ROOT}/scripts/py scripts/bench_parser.py --docs 20 --pages 30 --json
```

## 벤치마크

`scripts/bench_parser.py`는 합성 HWPX를 생성해 두 지표를 측정한다:

- `pages_per_sec` — 처리 섹션 수 / 경과 초
- `table_fidelity` — 기대 표 셀 대비 추출 일치율 (0~1)

성능 수치는 이 스크립트 출력을 그대로 인용한다(수기 추정 금지).
