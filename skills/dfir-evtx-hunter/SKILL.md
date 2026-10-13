---
name: dfir-evtx-hunter
description: "Hayabusa/Chainsaw 래퍼 — bring-your-own-binary EVTX 헌팅. 바이너리 미포함, 자동 탐지 아님. Triggers: evtx 분석, hayabusa, chainsaw, sigma 룰."
---

# DFIR EVTX Threat Hunter (Hayabusa & Chainsaw 래퍼)

> **Bring-your-own-binary**: Hayabusa/Chainsaw는 이 플러그인에 **포함되지 않는다**. `scripts/download_dfir_binaries.ps1`로 **별도 다운로드**하거나 직접 설치 후 사용한다. 자동 탐지/확정 엔진이 아니며, 결과를 법원 제출 적격으로 주장하지 않는다.

Rust 기반 Hayabusa/Chainsaw를 **있으면** 호출하는 래퍼다. `hayabusa.exe`/`chainsaw.exe`가 없으면 명령을 만들지 않고 설치 안내만 한다.

## 핵심 도구 (바이너리가 있을 때만)

1. **Hayabusa 타임라인 & 메트릭:**
   ```powershell
   # 1. EVTX 디렉터리 전체 스캔 및 CSV 타임라인 생성 (hayabusa.exe가 있을 때만)
   hayabusa.exe csv-timeline -d "C:\Evidence\Logs" -o "C:\Output\evtx_timeline.csv" --profile standard --min-level medium

   # 2. 호스트 요약 메트릭 및 컴퓨터 정보 추출
   hayabusa.exe computer-metrics -d "C:\Evidence\Logs"
   ```

2. **Chainsaw 정밀 키워드/IOC 헌팅:**
   ```powershell
   # 특정 키워드/IP/해시 고속 탐색 (chainsaw.exe가 있을 때만)
   chainsaw.exe search "mimikatz" "C:\Evidence\Logs" --json
   ```

3. **Chainsaw 내장 시그마 룰셋 (NetExec 침투 / MFT 변조):**
   - `rules/netexec_mft.yml` — NetExec(nxc/netexec) 실행, MFT 대량 변조·삭제,
     원격 서비스 설치(7045) 탐지 룰 3종.
   ```powershell
   chainsaw.exe hunt "C:\Evidence\Logs" -s "rules\netexec_mft.yml" --json
   ```

## 필수 준비 (게이트 메커니즘)
- 명령을 만들기 **전에** 게이트를 실행한다: `python scripts/check_tool.py hayabusa.exe chainsaw.exe`
  - exit 0 이면 진행, exit 2 이면 분석 결과를 만들지 않고 설치 안내만 한다 (fail-closed).
- 도구 부재 시 설치: `powershell -ExecutionPolicy Bypass -File scripts/download_dfir_binaries.ps1` 실행으로 최신 바이너리 설치. 다운로드 후 SHA256을 직접 확인한다.

## 하지 않는 일
- Hayabusa/Chainsaw 미설치 상태에서 Sigma 탐지 결과를 생성
- MITRE ATT&CK 자동 확정, 법원 적격성 보장
