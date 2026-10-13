---
name: court-evidence-stamper
description: "대법원 전자소송(ECFS) 표준 규격 증거 표찰(갑/을 제O호증) 및 Bates 번호 날인, 증거설명서 자동 생성 스킬. Triggers: 증거 표찰, 호증 스탬핑, 갑호증, 을호증, 증거설명서, 전자소송 증거."
---

# Court Evidence Stamper & Explanation Generator

대한민국 대법원 전자소송(ECFS) 제출 규격에 부합하도록 증거 PDF 문서에 **[갑 제O호증] / [을 제O호증]** 표찰 박스를 인자하고, 페이지 일련번호(Bates Numbering) 날인 및 **증거설명서(입증취지 + SHA-256 해시 목록)**를 원클릭으로 생성합니다.

## 핵심 도구

1. **서증 표찰 및 Bates 스탬퍼:**
   ```bash
   # 전 페이지 표찰 (기본)
   ${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/stamp_evidence.py "원본증거.pdf" --output "갑제1호증_카카오톡.pdf" --label "갑 제1호증" --prefix "P" --start 1
   # 첫 페이지만 표찰
   ${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/stamp_evidence.py "원본증거.pdf" --output "갑제1호증_카카오톡.pdf" --label "갑 제1호증" --first-only
   # 우측 여백 조정 (기존 인장·전송표와 겹칠 때)
   ${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/stamp_evidence.py "원본증거.pdf" --output "갑제1호증_카카오톡.pdf" --label "갑 제1호증" --margin 60
   # 한글 폰트: 시스템 폰트 자동 탐색 (AppleSDGothicNeo/맑은고딕/NanumGothic).
   # 해당 폰트가 없으면 NotoSansKR-Regular.ttf를 scripts/ 폴더에 배치
   ```
2. **증거설명서 자동 생성기:**
   ```bash
   ${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/generate_evidence_doc.py --input-json evidence.json --output "증거설명서.md" --case-num "2024가합12345" --case-name "영업비밀침해금지"
   ```
   > `--input-json` 없이(또는 빈 목록으로) 실행하면 샘플 플레이스홀더가 들어가고 문서 본문에 **"[샘플 자동 생성본 — 법원 제출 금지]"** 워터마크가 표시됩니다. 실제 증거 JSON으로 재생성 후 제출하세요.

## 전자소송 규격 가이드
- **호증 구분:** 원고/고소인(`갑 제O호증`), 피고/피고소인(`을 제O호증`), 참가인(`병 제O호증`).
- **표찰 위치:** 첫 페이지 및 전 페이지 우측 상단 박스 처리.
- **무결성:** 원본 증거물의 SHA-256 해시를 증거설명서 비고란에 필수 병기.
