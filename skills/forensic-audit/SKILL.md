---
name: forensic-audit
description: 파일 생성/수정/접근 시각과 SHA-256이 필요할 때. os.stat만. $MFT·Timestomping·Maya·MOV 감정에는 쓰지 말 것.
---

# forensic-audit: OS 표면 타임스탬프와 해시

이 스킬은 `os.stat()`가 보여주는 MAC 시각과 파일 해시만 점검한다.

## 하는 일

- 생성/수정/접근 시각 (로컬 타임존 오프셋 포함)
- Windows `st_ctime`은 대체로 생성시각, POSIX `st_ctime`은 inode 메타데이터 변경시각으로 구분 표기
- SHA-256 (무결성 비교용)
- MD5 (레거시 호환, 단독 증거로 쓰지 말 것)
- 생성시각 > 수정시각이면 **복사/다운로드에서 흔한 현상**으로 기록. 조작 단정 금지.

## 하지 않는 일

- NTFS `$MFT` `$STANDARD_INFORMATION` vs `$FILE_NAME`
- Timestomping 판정
- MOV/MP4 `mvhd`, EXIF, Maya `.mb`, HWP/Office `core.xml`

그런 분석이 필요하면 EnCase, X-Ways, MFTECmd 등 전용 도구를 쓰고, 이 스크립트 결과를 그 대체물로 인용하지 않는다.

## 엔드포인트 원격 수집 (Velociraptor — BYO)

엔드포인트에 Velociraptor가 배포된 환경에서는 VQL로 프로세스/네트워크/
브라우저 이력을 일괄 수집할 수 있다. 쿼리 템플릿은
`references/vql_templates.md`를 참조한다. 바이너리 게이트는
`python scripts/check_tool.py velociraptor.exe` — 미설치 시 쿼리를 만들지
않는다. 수집 전 대상 호스트의 권한 확인이 선행이다.

## 실행

```bash
# 기본 측정 (표준 출력)
python skills/forensic-audit/scripts/audit_timestamps.py "대상파일.ext"

# 보고서 검증용 원본 증거 JSON 산출 (verify_report.py의 필수 grounding 근거)
python skills/forensic-audit/scripts/audit_timestamps.py "대상파일.ext" --json > audit.json
```

## Antigravity / Gemini & Report Grounding Gate

- 스크립트 stdout 또는 `audit.json`을 그대로 인용한다. C>M을 조작으로 올리지 않는다.
- 본 스킬에서 측정된 SHA-256/시각은 `verify_report.py`의 `--evidence audit.json`으로 전달되어야 하며, High-Fidelity 비파라메트릭 모드(`--high-fidelity`) 및 Kiwi 형태소 그라운딩(`--morph-grounding`)을 통해 보고서 내 측정값과 용어의 실존 여부가 엄격히 차단/검증됩니다.
- 검증 레인은 `invoke_subagent` `Model: "inherit"`.
