---
name: ai-trace-detector
description: 로컬 드라이브, 폴더, E01 포렌식 이미지 내 마크다운(.md) 및 텍스트 파일의 AI 사용 흔적(보캐블러리 기반 모델 추정, 라인별 AI 슬롭/CoT 태그 진단, 시계열 활동 타임라인)을 휴리스틱으로 분석·시각화하는 디지털 포렌식 AI 탐지 스킬.
---

# ai-trace-detector: 디지털 포렌식 AI 사용 흔적 & 활동 타임라인 탐지기

로컬 디스크, 특정 폴더, 또는 **EnCase E01 포렌식 디스크 이미지** 내의 마크다운(`*.md`) 및 텍스트 문서를 스캔해 **"AI 사용을 시사하는 단서(보캐블러리·태그·서식 패턴)가 어느 라인에 있는지"**, **"기록된 시각에 어떤 행위 흔적이 남아 있는지"**를 휴리스틱으로 분석하는 포렌식 스킬이다. 단서 매칭 기반이므로 "어떤 AI 도구·모델인지"는 추정이며, 매칭 사전에 없는 도구는 탐지되지 않는다.

---

## 🔍 핵심 포렌식 탐지 영역

1. **오픈 보캐블러리(Open-Vocabulary) 동적 AI 모델 역추적**:
   - 고정된 화이트리스트에 국한되지 않고, 프론트매터(`model:`, `engine:`, `harness:`) 및 본문 선언문, 주석에서 임의의 모델명(`fable`, `gpt sol`, `runa terra`, `sonnet5`, `gemini 3.7`, `o3-mini`, `claude-3-7-sonnet`, 사내 커스텀 파인튜닝 LLM 등)을 100% 동적 추출.
2. **라인별 5대 AI 사용 흔적 마이크로 진단 (Line-by-Line Micro Forensic)**:
   - **추론/CoT 아티팩트**: `<think>`, `<antThinking>`, `<antArtifact>`, `<task>`, `<attempt_completion>`
   - **AI 정형 어투/슬롭**: "Certainly!", "물론입니다!", "도움이 되셨기를 바랍니다", "As an AI language model"
   - **시스템 프롬프트/파라미터**: `role: system`, `developer prompt`, `temperature: 0.2`, `few-shot`
   - **AI 도구/IDE 시그니처**: `.cursorrules`, `.windsurfrules`, `CLAUDE.md`, `.traerules`, `.roomodes`, `Signed-off-by: aider`
   - **구조적 기계 패턴**: 코드 블록 후 기계적 설명 단락, 불릿 기호의 극단적 대칭성
3. **시계열 활동 포렌식 타임라인 (Activity Chronology)**:
   - 파일시스템 MACB(생성/수정 일시) + 본문 내 명시 일자 + AI 질의/생성 + 민감정보 노출 + 회의 의사결정을 시간순으로 정렬한 포렌식 타임라인 제공.
4. **E01 포렌식 이미지 스트리밍 지원**:
   - 물리/논리 디스크 압축 이미지(E01) 마운트 없이 원시 바이트 스트림에서 직접 파싱.

---

## 🚀 CLI 실행 및 분석 가이드

**엔진은 이 플러그인에 번들되지 않는다 (BYO).** 아래 순서로 위치를 해석하고, 어느 것도 없으면 스킬을 실행하지 말고 사용자에게 설치 경로를 물어라 — 경로를 추측해서 실행하면 안 된다.

1. 환경 변수 `LAZYFORENSIC_MD_ANALYZER_HOME`
2. `~/.gemini/antigravity/scratch/md-analyzer` (Windows: `%USERPROFILE%\.gemini\antigravity\scratch\md-analyzer`)

아래 명령은 모두 해석된 엔진 디렉터리를 cwd 로 두고 실행한다.

### 1. 대상 디렉토리 / 드라이브 AI 흔적 전수 스캔 및 보고서 생성
```bash
# 특정 디렉토리 또는 드라이브 스캔 + 인터랙티브 HTML 보고서 자동 생성
python -m src.cli scan D:\TargetFolder --report --db md_analysis.db

# E01 포렌식 디스크 이미지 직접 분석
python -m src.cli scan --e01 "E:\Evidence\DiskImage.E01" --report
```

### 2. 시계열 활동 타임라인 (When & What) 즉시 조회
```bash
python -m src.cli timeline --db md_analysis.db
```

### 3. 인터랙티브 웹 대시보드 구동
```bash
python -m src.cli serve --port 8501
```

---

## 📋 포렌식 보고서 출력 양식

- **콘솔 요약**: 총 문서 수, AI 생성 비율, 감지된 AI 도구/모델 분포표
- **단일 HTML 리포트 (`reports/md_analysis_report.html`)**: 외부 의존성 없는 반응형 대시보드, 라인별 AI 흔적 진단 모달, 시간순 활동 타임라인 피드 탑재
- **SQLite FTS5 DB (`md_analysis.db`)**: 키워드 및 정규식 전문 검색 가능
