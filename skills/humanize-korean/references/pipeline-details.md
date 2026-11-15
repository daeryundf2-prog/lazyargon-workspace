# 파이프라인 상세 절차 — 경로별 실행·청킹·Finalize 승급·결과 전달·후속 명령 (pipeline-details)

> `SKILL.md`에서 이관된 `Light 경로`, `Standard 경로`, `Heavy 경로 (P1~P3)`, `Finalize 승급 규칙`, `결과 전달`, `부분 재실행 / 후속 명령`, `구간 지정 모드`, `데이터 흐름 요약` 전문.

## Light 경로 (1콜) — 잘 쓴 글

어휘 티가 거의 없고 구조 티만 미미한 글. 목표는 **과윤문 방지**이지 많이 고치는 게 아니다.

1. **진단 생략.** `humanize-monolith`를 `Agent` 도구로 1회 호출 — 청킹 없음.
   - 입력: `input_path=01_input_with_metrics.txt`, `quick_rules_path=${SKILL_DIR}/references/quick-rules.md`, `genre_hint`, 그리고 강도 지시 `보수`(내용 앵커 원형 보존, 원문에 없던 표현 삽입 금지, 확신 없는 구간은 그대로 둔다).
   - 출력: `final.md` (본문 + `<!-- HUMANIZE-SUMMARY -->` 블록).
2. Phase 2.5 변경률 게이트(Bash — LLM 콜 아님).
3. **조기 종료 보고**: monolith 탐지가 거의 없고 게이트 변경률이 5% 미만이면, 결과 전달을 "이미 좋은 글입니다 — 손댄 곳은 {N}곳({요지}) 정도"로 요약한다. 억지로 더 고치지 않는다.
4. 게이트 exit 2(≥50%)일 때만 롤백 재실행 1회(이 경우 총 2콜). light에서 50%가 나오면 과윤문 사고이므로 재실행 지시에 보수 강도를 재강조한다.

**콜 수: 1 (게이트 실패 시 최대 2).**

## Standard 경로 (2콜) — 보통의 AI 초안

1. **진단 1콜**: `humanize-diagnostician`을 `Agent` 도구로 1회 호출.
   - 입력: `input_path=01_input_with_metrics.txt`, `taxonomy_path=${SKILL_DIR}/references/diagnosis-rules.md` (진단 전용 슬림 인덱스 — 전 패턴 전수, taxonomy에서 자동 생성)
   - 출력: `02_diagnosis.md` — 글 전체의 **지배 패턴 3~6개**(본진 ID + 근거 + 처방) + 장르·격식 + 보존 지침.
   - 진단은 span을 세지 않는다. "무엇이 이 글을 지배하는가"를 판단한다(안정적).
2. shim으로 진단을 monolith 입력 앞에 결합 (Bash — LLM 콜 아님):
   ```
   ${SKILL_ROOT}/scripts/py ${SKILL_ROOT}/scripts/prepare_monolith_input.py --run-dir _workspace/{run_id} --genre {genre} --diagnosis _workspace/{run_id}/02_diagnosis.md
   ```
   → `01_input_with_metrics.txt`가 [진단 → 정량 블록 → 원문] 순으로 재생성된다.
3. **윤문 1콜**: `humanize-monolith` 1회 호출 — **청킹 없음. 1만자급도 단일 콜이다.** → `final.md`.
4. Phase 2.5 변경률 게이트(Bash).
5. **finalize 생략이 기본.** 과윤문은 `verify_gates.py`의 결정적 게이트가 잡는다. finalize 승급 조건(아래 표)에 걸릴 때만 `humanize-finalizer` 1콜 추가(이 경우 총 3콜).

**콜 수: 2 (finalize 승급·게이트 롤백 시 3).**

## Heavy 경로 (3+콜) — 중증 AI 슬롭·검증 증적 필요

`--strict`·"정밀 모드"의 강제 대상. 진단→겨냥 윤문→finalize의 완전한 3콜 구조.

### Phase P1: 진단
Standard의 1과 동일 — `humanize-diagnostician` 1콜 → `02_diagnosis.md`. 장문이라도 진단은 통짜 1콜(전 청크 공유)이다.

### Phase P2: 겨냥 윤문
1. shim으로 진단 결합 (Bash). **heavy에서만** `--chunk`를 함께 줄 수 있다:
   ```
   ${SKILL_ROOT}/scripts/py ${SKILL_ROOT}/scripts/prepare_monolith_input.py --run-dir _workspace/{run_id} --genre {genre} --diagnosis _workspace/{run_id}/02_diagnosis.md --chunk
   ```
   - 분할 여부·경계는 100% shim(Python)이 정한다(문단·문장 경계, 헤딩 승격, 말미 각주 passthrough — 청킹 임계는 shim 관리).
   - 산출: `01_chunk_{NN}_input_with_metrics.txt` N개 + `chunk_manifest.json`.
2. **청크 경로 판정**: `chunk_manifest.json`의 body 청크(passthrough 제외)가 **2개 이상일 때만** 청크 경로. **1개면 단일 monolith 콜로 처리한다** — 청킹은 shim의 결정이지 오케스트레이터의 추측이 아니다. 단일 콜로 처리할 때의 입력 파일도 manifest가 있으면 그 청크의 `input_file` 값을, 없으면 `01_input_with_metrics.txt`를 쓴다.
3. **단일 콜(기본)**: `humanize-monolith` 1회 호출(`input_path=01_input_with_metrics.txt`). monolith는 진단문을 앞머리에서 읽고 지배 패턴을 겨냥해 윤문한다. → `final.md`.
4. **청크 병렬(shim이 실제로 쪼갠 경우만)**:
   - 각 body 청크를 monolith로 **병렬 호출**(동시 최대 4). 입력·출력 파일명은 manifest의 **`input_file`·`rewritten_file` 필드를 그대로** 사용한다 — 파일명을 직접 조립하지 않는다(인덱싱 불일치 사고 방지).
   - 각 청크 콜은 같은 `quick_rules_path`(파일 참조)와 같은 `02_diagnosis.md`를 공유한다. **룰북·진단 전문을 청크 프롬프트에 복붙하지 않는다** — 재로드 비용이 청킹 토큰 폭발의 주범이었다(§설계 노트).
   - 재조립: `${SKILL_ROOT}/scripts/py ${SKILL_ROOT}/scripts/reassemble_chunks.py --run-dir _workspace/{run_id}` → `03_reassembled.md`(passthrough 원문 삽입 + 문자수 대사). 이걸 `final.md`로 삼는다.
   - 청크 경계 문체 이음매가 어색하면 경계 전후 2문단만 monolith로 국소 패치(전역 재작성 금지 — 의미 드리프트 유발).
   - **재청킹 주의**: `--chunk` 재실행 시 경계가 바뀌므로 기존 `02_chunk_*_rewritten.txt`는 shim이 자동 삭제한다(`stale_removed`). 청킹 후 입력을 수정하면 재청킹부터 다시 한다.

### Phase P2.5: 구조 게이트
Phase 2.5(공통)와 동일 — `verify_gates.py --genre {genre}`. Bash 1회 — LLM 콜 아님.

### Phase P3: finalize (heavy는 항상)
`humanize-finalizer`를 `Agent` 도구로 1회 호출.
- 입력: `original_path=01_input.txt`, `rewritten_path=final.md`, `diagnosis_path=02_diagnosis.md`
- 원문↔윤문본 **직접 대조**로 의미 보존 15항(각주·제목·없던 주장 주입 포함) + 자연성(잔존 + 과윤문 양방향)을 판정하고 **문제 구간만 국소 보정**(전체 재작성 금지).
- 출력: 보정된 `final.md`(원본은 `final_pre_finalize.md` 백업) + `09_finalize.json`.
- `verdict=hold_and_report`면 사람 검토 안내. 그 외 finalize 후 `verify_gates.py`를 한 번 더 돌려 최종 변경률 확정.

**콜 수: 3 (진단 1 + 윤문 1 + finalize 1). 청크 병렬 시 2 + N + 국소 패치.**

## Finalize 승급 규칙 (전 경로 공통)

finalize는 추가 LLM 콜이다. 다음 조건에서만 실행한다:

| 조건 | finalize |
|---|---|
| heavy 경로 | **항상** |
| 변경률 게이트 exit 1(경고 30~50%) | 실행 — 과윤문·의미 드리프트 의심 |
| monolith 자체검증 실패(6항 중 2+ 위반) | 실행 |
| 사용자가 검증·증적을 명시 요청 | 실행 |
| light·standard의 그 외 모든 경우 | **생략** — `verify_gates.py` 결정적 게이트가 과윤문을 확인 |

**진단 파일이 없을 때(Light 승급).** Light 경로는 `02_diagnosis.md`를 만들지 않는다. Light에서 승급 조건에 걸리면 **`diagnosis_path` 없이** `humanize-finalizer`를 호출한다 — 진단을 만들려고 콜을 추가하지 않는다. finalize의 본체(의미 보존 15항 + 자연성)는 원문↔윤문본 직접 대조로 성립하므로 진단 없이도 온전히 동작하며, 이 경우 도구 호출은 3회로 줄어든다. (Light가 승급하는 상황은 애초에 "예상보다 많이 고쳤다"이므로, 겨냥 대상을 새로 진단하는 것보다 고친 결과를 검증하는 것이 맞다.)

## 결과 전달 (전 경로 공통)

사용자에게 다음 4개를 반환:
1. 한 줄 상태: `완료. 경로 {light|standard|heavy} / 변경률 X% / 등급 Y / 자체검증 N/6 통과` — 변경률은 **게이트 스크립트 출력값**을 그대로 쓴다
2. 윤문본 본문 (마크다운 블록) — 단, light 조기 종료면 "이미 좋습니다 + 손댄 곳 요약"으로 대체 가능
3. final.md 끝 `<!-- HUMANIZE-SUMMARY -->` 블록의 핵심 표 (메트릭 + 카테고리 탐지 + 자체검증)
4. 등급 B 이하면 "heavy(`--strict`, 진단→윤문→finalize 3콜)로 재실행" 안내

**wall-clock 목표:** light 1~2분 / standard 5,000자 2~3분·1만자 3~5분(단일 콜) / heavy 5~8분.

## 부분 재실행 / 후속 명령

| 사용자 신호 | 처리 |
|---|---|
| "특정 카테고리만 다시" | heavy 경로. `02_diagnosis.md`의 지배 패턴을 해당 카테고리로 한정해 P1부터 재실행 |
| "이 문단만" | heavy 경로, 해당 문단만 입력으로 새 run_id 생성 |
| "2차 윤문"·"`/humanize-redo`" | 기존 run_id의 `final.md`를 새 입력으로 heavy P1부터 재실행 |
| "윤문 강도 조정" | heavy 경로, 진단의 지배 패턴 개수(3~6)를 늘리거나 줄여 재실행 |
| "장르 바꿔서" | `genre` 변경 후 Phase 1부터 재실행 (경로는 route_hint 재판정) |
| "표시된 줄만"·`[SLOP GUARD] WARN` 제안 수락 | **구간 지정 모드**(아래) |

### 구간 지정 모드 (slop_guard 연동)

`${PLUGIN_ROOT}/scripts/slop_guard.mjs`가 보고서 파일에서 짚은 줄만 고친다. 자동으로 시작하지 않고, 사용자가 제안을 수락했을 때만 돌린다.

1. `node ${PLUGIN_ROOT}/scripts/slop_guard.mjs --file <보고서>`로 대상 줄 번호와 패턴을 다시 얻는다.
2. 그 줄의 문장만 light 경로로 윤문한다. 다른 줄은 한 글자도 바꾸지 않는다.
3. 인용부호 안·표 행·수치·고유명사·날짜는 제외한다(철칙 #1). 대상 줄에 이것만 있으면 고치지 않고 넣어간다.
4. `verify_change_rate.py --before <원본> --after <결과>`로 변경률을 잰고, `slop_guard.mjs --file`를 다시 돌려 표시가 줄었는지 보고한다.

## 데이터 흐름 요약

```
01_input.txt
    ↓ [scripts/prepare_monolith_input.py — 정량 점수 shim, Bash 1회]
00_metrics.json (route_hint 포함) + 01_input_with_metrics.txt
    ↓ route_hint (사용자 명시가 오버라이드)
    ├─ light ──→ [humanize-monolith ×1, 보수] ──→ final.md ──→ [verify_gates.py]
    │             (변경률 <5%면 "이미 좋습니다" 조기 종료 보고)
    ├─ standard → [humanize-diagnostician ×1] → 02_diagnosis.md
    │             ↓ [shim --diagnosis, Bash]
    │             [humanize-monolith ×1 — 단일 콜, 1만자급 포함] → final.md
    │             ↓ [verify_gates.py] (finalize는 승급 조건 시만)
    └─ heavy ───→ [humanize-diagnostician ×1] → 02_diagnosis.md
                  ↓ [shim --diagnosis (--chunk 가능), Bash]
                  [humanize-monolith ×1 — 또는 shim이 2+청크를 쪼갠 경우만 병렬 ×N]
                  ↓ [verify_gates.py]
                  [humanize-finalizer ×1] → final.md(보정) + 09_finalize.json
                  ↓ [verify_gates.py — 최종 확정]
```
