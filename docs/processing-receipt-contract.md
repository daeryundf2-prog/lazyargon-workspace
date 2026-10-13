# processing_receipt 계약 (Cross-Repo Contract v1.0)

lazyforensic / lazyothers / LAZYANTIGRAVITY(media-mcp) 3개 저장소가 공유하는
처리 기록(processing receipt) 스키마와 해석 규칙의 합의안.
canonical: lazyforensic. 어느 저장소도 여기와 다른 규칙을 단독으로 도입하지 않는다.

## 1. 스키마 (schema_version: "1.0")

```
{ "processing_receipt": {
    "schema_version": "1.0",
    "case_id":      string | null,
    "evidence_id":  string (non-empty),
    "status":       "complete" | "partial" | "failed" | "not_measured",
    "source":       { "path": string, "sha256": hex64 | null },
    "artifacts":    [ { "path": string, "sha256": hex64 } ],   // sha256 필수
    "tool":         { "name": string, "version": string },
    "parameters":   object,
    "started_at":   ISO-UTC | null,   // null은 not_measured일 때만
    "finished_at":  ISO-UTC | null,   // null은 not_measured일 때만
    "exit_code":    int | null,       // null은 complete일 수 없음
    "warnings":     [string],
    "limitations":  [string],
    "review":       { "status": "pending" | "approved",
                      "reviewer": string | null,
                      "reviewed_at": ISO-UTC | null }
}}
```

## 2. 유효성 규칙 (validator 공통)

1. **sha256 표기**: 생성은 소문자 hex64. 검증 시 대소문자 모두 수용하되
   비교는 `.lower()` 정규화 후 수행한다.
2. **source.sha256 null 허용**: 디렉터리·미측정 소스를 표현한다. 단, 이 경우
   `status`는 `partial` 또는 `not_measured`여야 한다. **`complete`는
   측정된 정규 파일 소스(sha256 존재) + `exit_code == 0` 필수.**
   (lazyforensic `build_receipt`의 디렉터리 complete-유지 버그는 이 규칙으로 해소)
3. **artifacts[].sha256**: 항상 필수, null 불가.
4. **타임스탬프**: ISO 8601을 UTC 오프셋 0으로 파싱 가능해야 한다
   (`Z` 또는 `+00:00`). `started_at`/`finished_at` null은
   `status == "not_measured"`(이력/미측정 작업)일 때만 허용.
   `finished_at >= started_at`. `reviewed_at >= finished_at`.
5. **exit_code**: null 또는 int. `status == "complete"`이면 반드시 0.
6. **review**: `pending`이면 `reviewer == null`이고 `reviewed_at == null`.
   `approved`이면 둘 다 유효값 필수.
7. **validator 호출 규약**: 검증 대상은 내부 receipt 객체다. 래핑
   `{"processing_receipt": …}` 형태는 경계에서 언랩한 뒤 넘긴다.
   (lazyforensic `validate_receipt` 시그니처를 lazyothers 방식으로 통일)

## 3. 승인(approval) 경계

- `review.status = "approved"`는 **검증-후-승인 경로로만** 생성한다:
  소스·artifacts를 재해시하여 `verify_receipt`를 통과하고, artifacts가
  비어 있지 않으며, 명시적 reviewer 문자열이 있어야 한다
  (lazyothers `approve_receipt` 의미론이 표준).
- CLI 플래그(`--review-status approved --reviewer …`)만으로 approved를
  기록하는 경로는 허용하지 않는다. evidence_export의 해당 플래그는 제거
  또는 `pending` 고정으로 변경한다.
- `review.reviewer`는 **인증된 신원이 아니라 자기 선언된 명칭**이다.
  receipt에는 서명이 없으므로 산출물 문서에 "reviewer는 선언이며
  인증이 아님"을 표기한다. 보증은 승인 시점 재검증에서 온다.

## 4. evidence_export → generate_evidence_doc 연계

- **항목별 receipt 발행**: `evidence_list[]` 각 항목에
  `processing_receipt`를 넣는다. `source` = 해당 증거 파일,
  `artifacts` = []. 최상위 `processing_receipt`는 export 실행 자체의
  기록(source=manifest)으로 유지하며 소비자는 구별한다.
- **경로 키**: 정식 키는 `file_path`. `file`은 레거시 별칭으로 수용한다.
- **해시 키 의미**: `claimed_sha256` = 매니페스트 기재값,
  `sha256`/`verified_sha256` = 실측값. export는 `claimed_sha256`를
  명시 발행한다(기존 `sha256`=기재값 의미는 폐기 방향).
- **evidence_id**: export가 항목별 안정 ID를 발행한다
  (예: `{case_id}-{label}`). doc은 임포트 receipt의 evidence_id와
  불일치 시 오류로 처리하고, uuid4 임의 생성은 최후 폴백이다.
- `provenance.status`(export)는 매니페스트↔파일 대조 결과,
  `hash_status`(doc)는 기재↔실측 대조 결과 — 별개 필드로 유지한다.

## 5. 미디어 수명주기 (media-mcp)

- **어휘 분리**: 작업 수명주기 `status: running | done | failed`와
  결과 품질 `processing_receipt.status: complete | partial | failed |
  not_measured`는 별개 필드다. `status.json`의 `status`에는 수명주기
  어휴만 기록한다(완료 시 `"done"`).
- 폴링 응답: `{ status: <lifecycle>, processing_receipt: {...} }`.
  소비자는 결과 품질이 필요하면 `processing_receipt.status`를 읽는다.
  매핑: `done` → receipt `complete|partial`, `failed` → `failed`,
  `running` → `not_measured` 또는 미발행.
- 실행 중 폴링의 receipt는 `not_measured`(null 타임스탬프 허용 규칙 적용).

## 6. 법률 MCP 캐시 어댑터

- korean-law-mcp 응답 키: `statute_name`(법령명), `articles`는
  `{조번호: 본문}` dict, 키워드 검색은 `matches: [{article_number, text}]`.
- 매처는 `statute_name`을 법령명 키로 인식하고, `articles` dict의 키
  `"20"`을 `제20조`로 정규화하며, `matches[].article_number`도 동일하게
  처리한다.
- **provenance 무시 금지**: 응답의 `grounding_status` /
  `provenance.completeness: "limited"`는 번들 발췌임을 의미하므로
  캐시 매칭은 "공식 원문 확인"이 아니라 **보조 대조(corroboration)**로만
  표기한다. 결과에 발췌 출처를 명시한다.

## 변경 영향 요약

| 저장소 | 필요 변경 |
| --- | --- |
| lazyforensic | `validate_receipt`를 내부 객체 시그니처로; 디렉터리 complete 금지; complete 요건(sha256+exit 0) 강제; `--review-status` 플래그 제거; 항목별 receipt + `claimed_sha256`/`file_path`/`evidence_id` 발행 |
| lazyothers | validator에 not_measured-시-null-타임스탬프 규칙 추가(나머지는 이미 표준); `match_mcp_statute_cache`에 `statute_name`·dict-articles·`matches[]` 어댑터 + provenance 표기 |
| LAZYANTIGRAVITY | `status.json`의 `status`를 수명주기 어휘로 유지(complete 덮어쓰기 제거 → 폴링 `done` 분기 복구); `unknownReceipt`은 계약상 유효(§2.4) |
