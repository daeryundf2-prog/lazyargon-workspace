---
name: sqlite-evidence-query
description: "압수 SQLite DB(메신저 백업·앱 데이터·브라우저 히스토리) 읽기전용 즉석 분석 스킬 — 스키마 자동 파악, SQL 추출(CSV/마크다운), 삭제된 레코드의 잔존 흔적(Freeblock·WAL·Journal) 키워드 검색. Triggers: sqlite 분석, 카톡 백업 분석, DB 증거, 삭제 데이터 흔적, 메시지 DB 추출."
---

# SQLite Evidence Query — 압수 DB 즉석 분석·흔적 검색

압수·확보한 SQLite 파일을 **원본 훼손 없이** 조회하고, 삭제된 레코드가
페이지에 남긴 잔존 바이트를 키워드로 찾는다. SQL 작성은 에이전트가 하되
실행·집계·포맷은 스크립트가 결정적으로 처리한다.

## 핵심 도구

```bash
# 1. 스키마 파악 (테이블·열·행 수)
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/query_evidence_db.py 증거.db --list-schema

# 2. SQL 추출 — SELECT/PRAGMA/EXPLAIN/WITH만 허용 (mode=ro + 문장 검사 3중 잠금)
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/query_evidence_db.py 증거.db \
    --sql "SELECT datetime(ts,'unixepoch','localtime'), sender, content FROM messages ORDER BY ts LIMIT 200"

# 3. 삭제 레코드 잔존 흔적 검색 (본 파일 + -wal/-journal)
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/query_evidence_db.py 증거.db \
    --keywords "회사명,영업비밀,010-1234-5678" -o 흔적검색.md
```

자연어 요청("작년 5월 특정인과의 통화 기록만")은 **에이전트가 스키마를 읽고
SQL로 번역**해 `--sql`로 넘긴다. 번역된 SQL과 결과 건수를 사용자에게 함께
보여 원하는 데이터인지 확인받는다.

## 안전 규율

- **읽기전용 3중 잠금**: (1) 파일은 `mode=ro`로 열려 SQLite 수준에서 쓰기가
  차단되고, (2) DELETE/UPDATE/INSERT/ATTACH 등은 접두어 검사에서 거부되며,
  (3) WITH 접두 문에 변경 구문이 숨어 있으면(CTE 부착 DELETE 등) 본문 스캔으로
  거부된다. 실 enforcement는 (1)이며 (2)(3)은 깊이방어다. 원본을 복사해 분석하더라도 동일
  규율이 적용된다.
- **흔적 검색은 복구가 아니다**: 잔존 바이트 발견은 "삭제 전 해당 문자열이
  있었다"는 참고 정보다. VACUUM·secure_delete로 덮였으면 못 찾고, 못 찾은
  것이 부존재 증명도 아니다. 법적 의미는 포렌식 전문가 검토 대상이다.
- 개인정보(전화번호·메시지 본문)가 결과에 나오므로, 공유용 보고서는
  비식별화 후 만든다.

## 팁

- 메신저 백업은 테이블명이 버전마다 다르다 — 반드시 `--list-schema`로 시작해
  실제 열을 확인하고 추측으로 SQL을 쓰지 않는다.
- 시간 열은 보통 unixepoch 정수다. `datetime(ts,'unixepoch','localtime')`으로
  변환해 보고서에 현지 시각을 쓴다.
- WAL 모드 DB는 `-wal` 파일이 없으면 최신 데이터가 본 파일에 없을 수 있다 —
  채증 시 본 파일과 `-wal`/`-journal`을 함께 확보한다(스캐너는 함께 읽음).
