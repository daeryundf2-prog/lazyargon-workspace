---
name: infographic-creator
description: 포렌식 절차/유출경로 인포그래픽이 필요할 때만. AntV 번들은 별도 확보(--antv-script). 감정·법령·카카오 파싱에는 쓰지 말 것.
---

# infographic-creator

한국어 요청이면 제목/라벨을 한국어로 둔다. 중국어 원문을 사용자에게 따라가지 않는다.

1. 데이터(숫자·단계)가 없으면 그리지 않는다.
2. AntV DSL이 필요하면 렌더 스크립트에 **사용자가 검토해 제공한** AntV JavaScript 번들(로컬 경로 또는 버전 고정 HTTPS URL)을 명시한다. 번들은 이 플러그인에 포함되어 있지 않다(AntV는 MIT — 사용자가 직접 확보).
   `python skills/infographic-creator/scripts/render_infographic.py chart.infographic --antv-script "<검토한_번들.js|고정_URL>" --output chart.html`
3. AntV 번들 없이도 단순 절차도/유출경로도는 인라인 SVG/CSS로 직접 만들 수 있다 — 외부 카탈로그·CDN(`@latest`)을 자동 삽입하지 않는다.

`invoke_subagent` `Model: "inherit"`로 DSL/도형을 만들고, 부모는 렌더 스크립트만 실행한다.
입력이나 `--antv-script`(AntV 경로 사용 시)가 없으면 종료한다. 샘플 감정 절차를 자동 생성하지 않는다.
