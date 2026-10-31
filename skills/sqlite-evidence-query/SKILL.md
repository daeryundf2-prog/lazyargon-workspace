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

# 4. Magnet AXIOM Case.mfdb(10.x scan_artifact_hit 포함) 인용 hit_id·분류명 1:1 실측 대조 및 qa_ids 추출
python scripts/query_evidence_db.py Case.mfdb --verify-hits "448773,786688,2134577" --json
python scripts/query_evidence_db.py Case.mfdb --verify-report 보고서초안.md --json

# 5. 내부자 유출·배임 심층 감사 (전체 아티팩트 집계, AI 프롬프트 배임·은폐 고의 스캔, 원본 .git/UTF-16 스캔)
python scripts/query_evidence_db.py Case.mfdb --export-axiom-counts ./out --scan-insider-prompts --json
python scripts/query_evidence_db.py Case.mfdb --scan-git-dir "E:\" --json
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
- **컴팩션(`<CONTEXT_SUMMARY>`) 오염 방어 및 AXIOM `Case.mfdb` 인용 검증**: 대형 DB(수백만 행) 다중 탐색 중 컨텍스트 컴팩션이 발동되면 요약기(`<CONTEXT_SUMMARY>`)가 인접 행의 `hit_id`와 `artifact_name`을 서로 뒤섞어 날조(`LNK Files` ↔ `Jump Lists`, 일반 `Windows Event Logs` ↔ `Storage Device Events`, `Pictures` ↔ `Text Documents` 등)한다. 탐색 즉시 확정된 `(hit_id, artifact_name, 핵심값)`을 `.lazyargon/pins.md`에 기록하고, `<CONTEXT_SUMMARY>` 내부의 ID·분류명은 절대 신뢰하지 말며, 최종 보고 직전 반드시 `--verify-hits` 또는 `--verify-report`(혹은 `verify_report.py --axiom-db Case.mfdb`)로 1:1 실측 대조한다.
- **상용 도구(AXIOM) 미파싱 사각지대 및 원격 푸시↔로컬 커밋 분리**: AXIOM `Case.mfdb`는 `.git/config`, `.git/logs/refs/remotes/origin/*`(원격 푸시), `.git/logs/HEAD`(로컬 커밋) 및 PowerShell `>` 리다이렉션이 만든 `UTF-16` 텍스트(`file_list.txt` 등)를 파싱하지 못한다. 소스코드·설계도면 유출 사건은 반드시 원본 이미지(E01 마운트 또는 디렉터리)에 `--scan-git-dir`을 실행해 **원격 푸시(`logs/refs/remotes/**`)**와 미전송 **로컬 커밋(`logs/HEAD`, `commit_msg*.txt`)**을 엄격히 분리하고, AI 코딩 도구 이력(`Claude Command History`)에 `--scan-insider-prompts`를 실행해 코드 은폐·주석 제거(`내부발신`, `안나가게`) 및 메모리 삭제 지시(`메모리에 적지마`)를 전수 탐지한다.
