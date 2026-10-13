---
name: forensic-mft-parser
description: "Dissect/EZ-Tools 래퍼 — bring-your-own-binary MFT/Prefetch 파싱. $MFT 미포함. Triggers: mft 분석, prefetch, dissect, ntfs 분석."
---

# Forensic MFT & Execution Artifact Parser (래퍼)

> **Bring-your-own-binary**: Dissect(`pip install dissect`)와 EZ-Tools(MFTECmd/PECmd)는 **별도 설치**다. 이 플러그인은 래퍼만 제공한다. `$MFT` 파싱 실패 시 대체 결과를 만들지 않는다.

NTFS `$MFT`, `$UsnJrnl:$J`, `$LogFile`, `Prefetch`/`Amcache`/`Shimcache`를 **도구가 있을 때만** 분석한다. 도구가 없으면 설치 안내 후 종료한다.

## 게이트 (명령 만들기 전에 실행)

```bash
python scripts/check_tool.py --python-module dissect MFTECmd.exe PECmd.exe   # exit 2 면 결과 생성 금지
```

## 핵심 도구 (도구가 있을 때만)

1. **Dissect Python 아티팩트 파서:**
   ```bash
   # Prefetch 실행 흔적 추출 (dissect 설치 시)
   python scripts/parse_ntfs_artifacts.py "disk.raw" --artifact prefetch --output prefetch.json

   # 사용자 계정 및 Shimcache 추출
   python scripts/parse_ntfs_artifacts.py "disk.raw" --artifact shimcache --output shimcache.json
   ```
   - E01은 `ewf` 플러그인 필요. 실패 시 JSON에 `error` 필드가 채워지고 exit 코드 3으로 끝난다 — "레코드 0건"과 파싱 실패를 혼동하지 말 것. `docs/GAPS.md` 참고.

2. **Eric Zimmerman Tools (EZ Tools) — 별도 설치:**
   ```powershell
   # 1. $MFT 파싱 (MFTECmd.exe가 있을 때만)
   MFTECmd.exe -f "C:\Evidence\C\`$MFT" --csv "C:\Output\MFT" --csvf mft_parsed.csv

   # 2. Prefetch 파싱 (PECmd.exe가 있을 때만)
   PECmd.exe -d "C:\Evidence\C\Windows\Prefetch" --csv "C:\Output\Prefetch"
   ```

## 하지 않는 일
- Dissect/EZ-Tools 미설치 상태에서 MFT 타임라인 생성
- Timestomping 자동 판정, 법원 적격성 보장
