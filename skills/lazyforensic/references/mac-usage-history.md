# mac-usage-history: macOS 사용기록 조사

"내 맥북의 모든 사용기록을 검토해라" 같은 요청에 쓴다. 기억에 의존해 DB 경로·시간 형식을 지어내지 말고
아래 스크립트를 먼저 실행한다. 스크립트는 원본을 읽기로만 복사하고 임시 복사본에서 조회한다(원본에 쓰지 않는다).

## 1. 수집 (권한 획득 시도 포함)

보고서를 둘 폴더를 정하고, 그 옆 `evidence/`로 수집한다. 기간을 말하지 않았으면 전체 기간으로 수집한다.

```bash
python scripts/collect_mac_usage.py --out <작업폴더>/evidence --request-access --wait-access 120 --unified-log --days 7
```

- `--days 7`은 통합 로그(로그인/잠금)를 7일로 제한하는 데 필요하다. 전체 기간이 필요하면 `--days`를 빼고
  `--unified-log`도 빼서 먼저 돌린 뒤, 통합 로그만 `--days`를 주고 별도 폴더로 한 번 더 돌린다.
- 결과: 소스별 `evidence/<id>.txt`(한 줄에 `현지시각 | 내용`), `evidence/coverage.json`, `evidence/coverage.md`.

## 2. 권한이 막힌 소스 (DENIED)

Safari·앱 사용 기록(knowledgeC)·메시지는 macOS 전체 디스크 접근 권한이 없으면 `DENIED`다. 파일이나 상위 폴더를 권한 때문에 못 열면 모두 `DENIED`로 남기고, `ABSENT`는 파일이 실제로 없을 때만 쓴다.

1. `--request-access`가 시스템 설정의 전체 디스크 접근 권한 창을 이미 열었다. 사용자에게 한 문장으로 요청한다:
   "시스템 설정 > 개인정보 보호 및 보안 > 전체 디스크 접근 권한에서 `<coverage.json의 host_app>`을 켜 주세요."
2. 스크립트는 `--wait-access` 초 동안 3초마다 다시 시도한다. 그래도 거부면 그 앱을 완전히 종료했다 다시 열어야
   적용되는 경우가 많다고 알리고, 사용자가 허용했다고 답하면 같은 명령을 다시 실행한다.
3. 사용자가 허용하지 않거나 답이 없으면 기다리지 말고, 읽힌 소스만으로 끝까지 진행한다.
4. `sudo`, 원본 파일 권한 변경, TCC DB 수정, SIP 해제는 하지 않는다.

## 3. 보고서

- 첫 절에 `evidence/coverage.md` 표를 그대로 붙인다. 이 표가 이 보고서가 본 범위다.
- `OK`인 소스만 근거로 쓴다. 시각·URL·건수는 `evidence/<id>.txt`와 `coverage.json`의 값만 쓴다.
- `DENIED`/`ERROR`/`SKIPPED` 소스는 "기록 없음"이라고 쓰지 않는다. "Safari 방문 기록: 미확인(권한 없음)"처럼 적는다. `ABSENT`는 "기록 파일 없음(앱 미설치 또는 미사용)"으로 적는다. 가드는 앞의 세 상태에 대한 부재 단정을 막는다.
- 기록이 말하는 것만 쓴다. 방문 기록은 "<도메인> 접속"까지다. 메일 송수신·문서 작성 같은 행위나 도메인으로 짐작한 기관명은 쓰지 않는다.
- `OK`이지만 0건이면 "수집 기간 안 기록 0건"이라고 기간과 함께 적는다.
- 빠진 소스가 하나라도 있으면 "모든/전체 사용기록을 검토했다"고 쓰지 않는다.
- 보고서를 `evidence/` 옆에 저장하면 가드가 `source_grounding.py`로 자동 대조한다. 수동 확인:

```bash
python scripts/source_grounding.py <보고서.md> --sources <작업폴더>/evidence
```

## 하지 않는 일

- iCloud·iPhone 백업, 삭제된 기록 복구, Spotlight·FSEvents·Biome 해석(현재 미지원 — 요청받으면 미지원이라고 밝힌다)
- 메시지 본문이 `attributedBody`에만 있는 경우의 본문 복원(`(본문 미추출)`로 남는다)
