---
name: memory-triage
description: "MemProcFS/Volatility 래퍼 — bring-your-own-binary 메모리 덤프 분석. 바이너리 미포함, 마운트 자동화 아님."
---

# Volatile Memory Triage (MemProcFS & Volatility 3 래퍼)

> **Bring-your-own-binary**: MemProcFS와 Volatility 3는 **별도 설치**다. 이 플러그인은 명령 예시와 경로 안내만 제공한다. 덤프 마운트나 은닉 프로세스 자동 탐지를 수행하지 않는다.

물리 메모리 덤프(`.raw`, `.dmp`, `.vmem`)가 있고 **도구가 설치되어 있을 때만** 아래 명령을 안내한다.

## 게이트 (명령 만들기 전에 실행)

```bash
python scripts/check_tool.py MemProcFS.exe vol.py   # exit 2 면 분석 결과 생성 금지
```

## 핵심 도구 (바이너리가 있을 때만)

1. **MemProcFS (가상 드라이브 마운트 — 별도 설치):**
   ```powershell
   # 메모리 덤프를 M:\ 드라이브로 마운트하고 자동 포렌식 분석 실행 (MemProcFS.exe가 있을 때만)
   MemProcFS.exe -device "C:\Evidence\memory.raw" -mount M: -forensic 1
   ```
   - `M:\sys\proc\`: 프로세스별 가상 메모리 및 로드된 DLL
   - `M:\sys\net\`: 연결 소켓 및 IP/Port
   - `M:\forensic\csv\`: 자동 추출된 타임라인 및 YARA 탐지 결과

2. **Volatility 3 (심층 플러그인 분석 — 별도 설치):**
   ```powershell
   vol.py -f memory.raw windows.pslist
   vol.py -f memory.raw windows.malfind
   vol.py -f memory.raw windows.netscan
   ```

3. **YARA-X (초고속 시그니처 스캔 — 별도 설치):**
   - Rust 재작성 차세대 YARA. 구형 C YARA 대비 수 배 빠른 패턴 매칭.
   ```bash
   python scripts/check_tool.py yr   # yr.exe 미설치 시 스캔 명령 생성 금지
   ```
   ```powershell
   # 메모리 덤프 / 마운트된 파일시스템 IOC 스캔 (yr이 있을 때만)
   yr scan rules\ioc.yar "C:\Evidence\memory.raw"
   yr scan rules\ioc.yar "M:\" --recursive
   ```
   - `yr scan` 출력은 탐지 결과이지 확정 판정이 아니다 — 룰 품질·오탐
     검토는 별도 단계.

## 하지 않는 일
- MemProcFS/Volatility 미설치 상태에서 메모리 덤프 분석 결과 생성
- 은닉 프로세스/인젝션 자동 확정, 법원 적격성 보장
