# 종료 코드 레퍼런스 (Exit Codes)

스크립트를 셸/CI/다른 도구에 연동할 때 쓰는 종료 코드 계약이다.
`sys.exit(main())` 반환값 기준 — `main`이 반환하는 정수가 곧 종료 코드다.

## 공통 계약

| 코드 | 의미 | 사용 예 |
|:---:|:---|:---|
| `0` | 성공. 검증 게이트는 "발견된 위반 없음(PASS/WARN)"도 0 | 전 스크립트 |
| `1` | 검증 실패 또는 실행 오류. `verify_report`의 FAIL/`--strict` WARN 차단 | `verify_report.py`, `verify_claim_ledger.py`, `setup_forensic_env.py` |
| `2` | 사용법/입력 오류. 파일 없음, 읽기 실패, 인자 오류 (argparse 기본값과 동일) | `parse_kakao.py`, `audit_timestamps.py`, `generate_timeline.py` 등 대부분의 스크립트 |
| `3` | BYO 도구/엔진 부재 — **결과를 지어내지 않고** 실패폐쇄 | `local_stt.py`, `audio_fingerprint.py`, `parse_ntfs_artifacts.py`, `check_tool.py` 계열 |
| `78` | `EX_CONFIG` — 설정/빌드 미완 (korean-law-mcp 미빌드 또는 키 없음) | `scripts/setup_korean_law.mjs --check` |

## 스크립트별 표

| 스크립트 | 0 | 1 | 2 | 3 | 78 |
|:---|:---:|:---:|:---:|:---:|:---:|
| `verify_report.py` | PASS/WARN | FAIL, `--strict`+WARN | 보고서 없음/인자 오류 | — | — |
| `verify_claim_ledger.py` | 위반 없음 | 위반 있음 | (argparse) | — | — |
| `parse_kakao.py` | 파싱 완료 | — | 입력 파일 없음/판별 실패 | — | — |
| `audit_timestamps.py` | 감사 완료 | — | 파일 없음 | — | — |
| `generate_timeline.py` | 렌더 완료 | — | 입력 없음/JSON 오류 | — | — |
| `korean_morph_forensic.py` | 그라운딩 통과 | — | 인자 오류 | — | — |
| `merge_timeline.py` | 병합 완료 | — | 매니페스트/입력 오류 | — | — |
| `local_stt.py` | 전사 완료 | — | 인자 오류 | STT 엔진 없음 | — |
| `audio_fingerprint.py` | 지표 완료 | — | 인자 오류 | fpcalc 없음 | — |
| `parse_ntfs_artifacts.py` | 파싱 완료 | 일반 오류 | — | BYO 도구 없음 | — |
| `exif_audit.py` / `image_similarity.py` | 감사 완료 | — | 인자 오류 | exiftool 등 없음 | — |
| `evidence_manifest.py` | 생성 완료 | 검증 실패 | 인자 오류 | — | — |
| `case_envelope.py` | 생성 완료 | — | 인자 오류 | — | — |
| `check_tool.py` | 도구 발견 | — | 하나 이상 미발견 (설치 안내만 출력) | — | — |
| `setup_forensic_env.py` | 설정 완료 | 단계 실패 | — | — | — |
| `setup_korean_law.mjs --check` | 빌드+키 OK | 빌드 실패 | — | — | 미빌드/키 없음 |
| `analyze_deepfake_evidence.py` | 분석 완료 | 파일 없음 | FFT 플롯 실패 | — | — |
| `local_only_audit.py` | UNGATED 없음 | UNGATED 지점 발견 | — | — | — |

표에 없는 나머지 `scripts/*.py`는 `0`(성공)/`2`(사용법 오류) 관례를 따른다.

## 연동 지침

- **CI에서 게이트로 쓸 때**: `1`만 실패로 취급하고 `2`/`3`/`78`은 환경·입력 문제로
  구분해 알림 경로를 달리하는 것이 좋다.
- **`3`은 "측정 0건"이 아니다**: 도구가 없어 아무것도 하지 못한 상태다.
  출력 JSON은 항상 `error` 필드를 포함하며, 빈 결과를 성공으로 위장하지 않는다.
- **`78`은 재시도하지 않는다**: `setup_korean_law.mjs` 빌드+키 설정 후 다시 실행.
