# 런타임 경로·run_id·입력 shim·참고 자료 상세 (runtime-paths)

> `SKILL.md`에서 이관된 `run_id 결정`, `스크립트 경로 규칙 (${SKILL_ROOT})`, `Phase 1: 입력 저장 + 정량 사전 점수`, `참고 자료` 전문.

### run_id 결정
- 모든 경로는 **cwd 기준**. 새 폴더 생성도 cwd 기준 `_workspace/{YYYY-MM-DD-NNN-TAG}/`에 만든다.
- **`TAG` 는 세션 구분자다. Phase 1 맨 처음에 한 번 만들어 그 run 내내 재사용한다.**

  ```bash
  TAG=$(python3 -c "import secrets;print(secrets.token_hex(2))")   # 예: a3f9
  ```

  이후 모든 명령의 `_workspace/{run_id}` 에 같은 TAG 를 쓴다. 중간에 새로 만들지 않는다.
- 기존 시퀀스 확인은 **`Glob` 도구**로 표지 파일을 매칭해 간접 조회.
  올바른 사용법: `Glob(pattern="_workspace/YYYY-MM-DD-*/01_input.txt")` → 결과에서 폴더명 추출 후 NNN 최댓값 + 1.
  (`-TAG` 가 뒤에 붙어도 접두어가 같아 이 패턴은 그대로 맞는다.)
  주의: Glob은 디렉토리 자체는 매칭하지 못한다. 반드시 그 안의 표지 파일(`01_input.txt`)을 매칭할 것.
  `Bash ls`는 OS·셸 환경에 따라 경로 해석이 달라지므로 사용 금지.
- 당일 폴더가 없으면 NNN = 001. 있으면 마지막 NNN + 1.
- 부분 재실행 신호("이 카테고리만 다시"·"2차 윤문")일 경우 기존 run_id 재사용(TAG 포함) + heavy 경로로 자동 승급.

> 🔴 **TAG 를 빼지 마라.** 한 머신에서 세션이 여러 개 동시에 도는 환경에서는 NNN 만으로
> 겹친다. Glob 으로 자리를 확인하고 `mkdir` 하기까지 틈이 있어 다른 세션이 같은 번호를
> 잡기 때문이다. 두 세션이 한 디렉터리를 쓰면 서로의 `01_input.txt` 를 덮어쓰고, 게이트가
> *남의 원문과 내 윤문본*을 비교해 있지도 않은 제목·인용이 사라졌다며 ABORT 를 낸다.
> 윤문본 자체는 멀쩡하므로 원인을 찾기가 특히 어렵다.

## 스크립트 경로 규칙 (`${SKILL_ROOT}`)

**스크립트는 절대경로로 부른다. cwd 기준 상대경로로 부르면 안 된다.**

`references/*` 는 **스킬 디렉터리** 기준이라 `${SKILL_DIR}` 를 쓴다 — `${SKILL_ROOT}` 와 기준이 다르니 섞지 않는다. 룰북·taxonomy 경로도 맨앞 접두어 없이 쓰면 cwd 로 풀려 `No such file or directory` 가 난다.

`${SKILL_DIR}` 는 이 스킬 폴더의 절대경로다. Antigravity 는 `PLUGIN_ROOT` 만 주입하므로 `${SKILL_DIR}` = `${PLUGIN_ROOT}/skills/humanize-korean` 으로 직접 풀어 쓴다. `PLUGIN_ROOT` 조차 비어 있으면 `python "${SKILL_ROOT}/scripts/resolve_plugin_root.py"` 로 설치 루트를 얻는다.

`scripts/*.py`는 설치 루트에 있고 cwd 는 사용자 작업 디렉터리다. 마켓플레이스 설치에서 둘은 **절대 일치하지 않는다.** 반면 `_workspace/` 같은 데이터 경로는 cwd 기준이다(run_id 규칙 참조). 두 기준이 한 명령줄에 섞이므로 스크립트 쪽만 절대경로로 고정한다.

Phase 1 시작 전에 한 번 정한다. **드라이브 루트(`C:\`, `/`)를 SKILL_ROOT로 쓰지 않는다.**

우선순위:

1. Antigravity가 주입한 `${PLUGIN_ROOT}` (파일이 `${PLUGIN_ROOT}/scripts/prepare_monolith_input.py`에 있을 때만).
2. 그다음 `${PLUGIN_ROOT}/scripts/py scripts/resolve_plugin_root.py --start <이 SKILL.md가 있는 디렉터리>`. 스크립트는 `plugin.json` 또는 `.claude-plugin/`을 만나고 `scripts/prepare_monolith_input.py`가 있는 디렉터리만 반환한다.

```bash
SKILL_ROOT="${PLUGIN_ROOT:-}"
if [ -z "$SKILL_ROOT" ] || [ ! -f "$SKILL_ROOT/scripts/prepare_monolith_input.py" ]; then
  SKILL_ROOT="$(python "$(dirname "$0")/../../scripts/resolve_plugin_root.py" --start "$(cd -P "$(dirname "$0")" && pwd)" 2>/dev/null || true)"
fi
if [ -z "$SKILL_ROOT" ] || [ ! -f "$SKILL_ROOT/scripts/prepare_monolith_input.py" ]; then
  SKILL_ROOT="$(d="$(cd -P "${SKILL_DIR:-$(dirname "$0")}" && pwd)"; \
    while [ "$d" != / ] && [ ! -f "$d/plugin.json" ] && [ ! -d "$d/.claude-plugin" ] && [ ! -f "$d/scripts/prepare_monolith_input.py" ]; do d="$(dirname "$d")"; done; \
    [ "$d" = / ] && s="$(dirname "$(cd -P "${SKILL_DIR:-$(dirname "$0")}" && pwd)")/humanize-korean" && [ -f "$s/scripts/prepare_monolith_input.py" ] && d="$s"; echo "$d")"
fi
```

`plugin.json`·`.claude-plugin/` 디렉터리, 또는 `scripts/prepare_monolith_input.py` 를 품은 디렉터리를 만날 때까지 거슬러 올라간다. 뒤 조건은 `install.sh --copy` 설치용이다 — 복사 설치는 스킬 디렉터리만 떼어 오므로 조상에 마커가 없고, 대신 런타임 스크립트를 스킬 디렉터리 안 `scripts/` 에 함께 복사한다(#144). 둘째 줄은 `/humanize`·`/humanize-scan`·`/humanize-redo` 로 들어온 복사 설치용 폴백이다 — 이 래퍼 스킬에는 `scripts/` 가 없으므로, `/` 까지 올라가도 못 찾으면 형제 `humanize-korean/` 을 본다. **고정된 횟수로 올라가지 않는 이유**는 스킬 위치가 배포 방식마다 다를 수 있어서다 — 고정 깊이는 레이아웃이 바뀌면 조용히 엉뚱한 곳을 가리킨다.

PowerShell / Antigravity Windows:

```powershell
$SKILL_ROOT = $env:PLUGIN_ROOT
if (-not $SKILL_ROOT -or -not (Test-Path "$SKILL_ROOT\scripts\prepare_monolith_input.py")) {
  $start = Split-Path -Parent $PSCommandPath
  if (-not $start) { $start = Get-Location }
  $SKILL_ROOT = python (Join-Path $start "..\..\scripts\resolve_plugin_root.py") --start $start
}
```

에이전트가 셸 스크립트가 아니라 도구로 실행할 때는 `PLUGIN_ROOT`가 있으면 그걸 쓰고, 없으면 이 스킬 디렉터리(`skills/humanize-korean`)를 `--start`로 넘겨 `resolve_plugin_root.py`를 실행한다.

**확인**: `${SKILL_ROOT}/scripts/prepare_monolith_input.py`가 없으면 경로를 추측하지 말고, 정량 shim·게이트 없이 진행한다고 **사용자에게 알린 뒤** 계속한다. 드라이브 루트로 폴백하는 것은 금지다.

## Phase 1: 입력 저장 + 정량 사전 점수 (input shim — 전 경로 공통)

1. cwd 기준 `_workspace/{run_id}/` 생성
2. 입력 텍스트를 `01_input.txt`에 저장
   - **챗봇 잔재 위생 (v2.6)**: 저장 전에 챗봇 프레임 문장이 섞여 있으면 벗겨낸다 — 머리("물론입니다!", "다음은 ~입니다:", "요청하신 내용을 정리하면"), 꼬리("도움이 되셨길 바랍니다", "추가 질문이 있으시면"), 지식 한계 면책("제 지식은 ~까지입니다"). 실사용자는 챗봇 출력을 그대로 붙여넣는 일이 많고, 이 문장들은 본문이 아니므로 제거해도 의미 손실이 0이다. 본문 안에 자연스럽게 녹아 있는 유사 표현은 건드리지 않는다.
3. 첫 300자로 장르 자동 추정 (사용자 명시 시 우선)
4. 사전 처리 shim을 Bash로 1회 실행:
   ```
   ${SKILL_ROOT}/scripts/py ${SKILL_ROOT}/scripts/prepare_monolith_input.py --run-dir _workspace/{run_id} --genre {genre}
   ```
   - `--genre` 값은 영문 키: `essay | column | report | blog | abstract` (생략 시 `essay`). 장르 힌트 매핑: 칼럼→`column`, 리포트→`report`, 블로그→`blog`, 공적/기타→`essay`.
   - `--run-dir`·`--diagnosis`의 상대 경로는 **cwd 기준**으로 해석된다(위 run_id 규칙과 동일 기준). 그 외 인자: `--text`(run-dir 없이 즉석 실행 시 새 run 디렉토리 자동 생성 — 이때는 `--session-tag {TAG}` 를 같이 준다), `--baseline`(baseline JSON 경로 override, 평소 불필요), `--diagnosis`(진단 텍스트 파일을 점수 블록 앞에 prepend — standard·heavy의 진단 결합용).
   - 산출: `00_metrics.json`(정량 점수 + **`route_hint`**) + `01_input_with_metrics.txt`(점수 블록을 원문 앞에 붙인 결합 파일).
   - **graceful degrade 내장**: metrics 계산이 실패하면 shim이 점수 블록 없이 원문만 감싼 결합 파일을 쓰고 `00_metrics.error`를 남긴다. 이 경우 route_hint 없음 → standard 경로.
5. `00_metrics.json`의 `route_hint`를 읽어 Phase 0 규칙대로 경로를 확정하고 상태 줄을 출력한다.

**단일 콜 우선 — 청킹은 여기서 하지 않는다.** `--chunk`는 heavy 경로 전용이며, 그때도 청크 경로를 탈지는 shim이 실제로 청크를 2개 이상 만들었는지로 정한다(heavy 절 참조).

## 참고 자료

- 슬림 룰북 (monolith 전용): [`${SKILL_DIR}/references/quick-rules.md`](quick-rules.md) — S1·S2 핵심 패턴 + 자체검증 체크리스트
- 진단 인덱스 (diagnostician 전용): [`${SKILL_DIR}/references/diagnosis-rules.md`](diagnosis-rules.md) — 전 패턴 전수 ID·정의·시그니처. `build_diagnosis_rules.py`가 taxonomy에서 자동 생성(직접 편집 금지)
- 정량 점수 shim: `${SKILL_ROOT}/scripts/prepare_monolith_input.py` — `${SKILL_DIR}/references/metrics_v2.py`(실패 시 `metrics.py` fallback) + `${SKILL_DIR}/references/baseline.json` 기반 사전 점수 + `route_hint` 산출
- 텍스트 위생: `${SKILL_ROOT}/scripts/sanitize_text.py` — shim이 자동 호출(끄려면 `--no-sanitize`). 제로폭·bidi·특수공백 제거 + 한글 NFD→NFC 정규화를 `01_input.txt`에 반영해 이후 변경률 게이트·diff·글자수가 같은 기준을 쓰게 한다. 결정적 처리, LLM 0콜. 변경이 있으면 `00_sanitize.json` 기록. **AI 워터마크 제거 기능이 아니다** (CLAUDE.md 「AI 워터마킹에 대한 입장」 참조)
- 분류 체계 본진 (SSOT — 유지보수·taxonomist 전용): [`${SKILL_DIR}/references/ai-tell-taxonomy.md`](ai-tell-taxonomy.md) — 10대분류 × 85 패턴(활성 84 + A-17 hold) 전수. 런타임 콜은 이 파일을 직접 읽지 않는다
- 윤문 처방 (진단 전용): [`${SKILL_DIR}/references/rewriting-playbook.md`](rewriting-playbook.md) — 카테고리별 치환 레시피·장르별 허용 표
- 학술 인용 외부 SSOT: [`${SKILL_DIR}/references/scholarship.md`](scholarship.md) — v2.0 학자 인용·caveat verbatim 보존
- 웹 서비스 스펙 (옵션): [`${SKILL_DIR}/references/web-service-spec.md`](web-service-spec.md) — 웹 확장 시 로드
