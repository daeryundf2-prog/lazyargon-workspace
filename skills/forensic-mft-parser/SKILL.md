---
name: forensic-mft-parser
description: "Dissect/EZ-Tools 래퍼 — bring-your-own-binary MFT/Prefetch 파싱. $MFT 미포함. Triggers: mft 분석, prefetch, dissect, ntfs 분석."
---

# Forensic MFT & Execution Artifact Parser (래퍼)

> **Bring-your-own-binary**: Dissect(`pip install dissect`)와 EZ-Tools(MFTECmd/PECmd)는 **별도 설치**다. 이 플러그인은 래퍼만 제공한다. `$MFT` 파싱 실패 시 대체 결과를 만들지 않는다.

NTFS `$MFT`, `$UsnJrnl:$J`, `$LogFile`, `Prefetch`/`Amcache`/`Shimcache`를 **도구가 있을 때만** 분석한다. 도구가 없으면 설치 안내 후 종료한다.

## 게이트 (명령 만들기 전에 실행)

도구별로 따로 검사한다. 하나가 없다고 다른 도구의 경로까지 막지 않는다.

```bash
python scripts/check_tool.py --python-module dissect.target   # exit 0 이면 아래 1번(Dissect) 진행
python scripts/check_tool.py MFTECmd.exe PECmd.exe            # exit 0 이면 아래 2번(EZ-Tools, Windows) 진행
```

둘 다 exit 2 면 결과를 만들지 않고 설치 안내만 한다.

## 핵심 도구 (도구가 있을 때만)

1. **Dissect Python 아티팩트 파서:**
   ```bash
   # Prefetch 실행 흔적 추출 (dissect 설치 시)
   python scripts/parse_ntfs_artifacts.py "disk.raw" --artifact prefetch --output prefetch.json

   # 사용자 계정 및 Shimcache 추출
   python scripts/parse_ntfs_artifacts.py "disk.raw" --artifact users --output users.json
   python scripts/parse_ntfs_artifacts.py "disk.raw" --artifact shimcache --output shimcache.json
   ```
   - 대상은 디스크 이미지 또는 `Windows/` 폴더가 있는 루트 폴더(타깃에서 복사한 폴더 구조)다. macOS에서 실행을 확인했다(Linux는 미확인).
   - Prefetch는 `.pf` 파일마다 한 건(실행 파일, 실행 횟수, 실행 시각 목록, 참조 파일 수)으로 나온다.
   - ShimCache 레코드에 `suspect` 필드가 있으면 해석 실패 가능성이 있다. 다른 도구로 교차 확인하기 전에는 근거로 쓰지 않는다.
   - `$MFT`·`$UsnJrnl`·Amcache·레지스트리 Run 키·LNK·점프리스트는 이 스크립트가 아직 뽑지 않는다. 설치된 Dissect에는 해당 플러그인이 있지만 스크립트에 연결되지 않았다(지금은 EZ-Tools로 처리).
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
