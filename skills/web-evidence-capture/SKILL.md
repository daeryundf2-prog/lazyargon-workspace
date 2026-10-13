---
name: web-evidence-capture
description: "웹 채증 스킬 — playwright MCP로 게시물·댓글·SNS·기사를 스크린샷/PDF로 캡처하고, 캡처 직후 URL·시각·SHA-256을 결합한 채증 기록을 생성하며, 필요 시 서증 표찰까지 연결한다. Triggers: 채증, 스크린샷 증거, 웹 증거 캡처, 게시물 캡처, 온라인 증거, URL 증명."
---

# Web Evidence Capture — 온라인 채증 파이프라인

온라인 게시물·댓글·SNS·포털 기사를 증거로 남길 때, 스크린샷 하나로는 "언제,
어느 URL의" 증거인지 증명할 수 없다. 이 스킬은 **캡처 → 인증 → 표찰** 3단으로
채증 기록을 만든다.

## 1단 — 캡처 (playwright MCP)

브라우저로 대상 페이지를 열어 캡처한다. 도구는 `mcp_config.json`의
`playwright` 서버(버전 고정 `@playwright/mcp@0.0.79`)를 사용한다.

- 정적 게시물: 뷰포트 스크린샷 1장 + 전체 페이지 PDF 1부
- 긴 게시물: 전체 페이지 스크린샷 (스크롤 병합)
- 동적 콘텐츠·로그인 필요: 렌더링 완료를 기다린 뒤 캡처. 로그인 세션 화면에
  개인정보가 보이면 블러 처리 **전에** 원본 캡처를 먼저 인증·보존한다
  (편집본은 원본과 별도 파일로만 만든다).
- URL 표시줄·시계가 화면에 보이는 브라우저 전체 캡처는 신뢰도를 높인다.
- 동적 상호작용 증명(Cursor-Synced Recording): Vercel agent-browser 연동 시 마우스 이동 궤적과 클릭 타임스탬프를 비디오 프레임 단위로 동기화 기록하여 "분석관이 실제로 페이지를 확인·조작했음"에 대한 사법적 증거력을 강화한다.

## 2단 — 인증 (캡처 직후, 결정적)

```bash
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/certify_evidence_file.py 캡처1.png 캡처2.pdf \
    --url "https://example.com/post/123" \
    --note "2026-08-29 14:05 게시물 본문+댓글 캡처" \
    --case "2024가합12345" \
    --output 채증기록.json --output-md 채증기록.md
```

채증 기록에는 인증 시각(UTC), 출처 URL, 파일별 SHA-256/MD5, 캡처 파일 생성
시각이 묶이고, **기록 자체의 SHA-256**도 남는다. 캡처 파일은 인증 후 절대
편집하지 않는다 — 블러·크롭이 필요하면 원본을 보존한 채 별도 파일로.

## 3단 — 표찰·편입 (선택)

```bash
# 법원 제출용 표찰이 필요하면
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/stamp_evidence.py 캡처1.png.pdf -o "갑제3호증_채증.pdf" --label "갑 제3호증"
# 증거설명서에 편입 (원본 해시 기준)
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/generate_evidence_doc.py --input-json evidence.json -o 증거설명서.md
# 기재 해시 대조 (제출 전)
${PLUGIN_ROOT}/scripts/py ${PLUGIN_ROOT}/scripts/audit_evidence_integrity.py --scan-dir 채증폴더 --report 증거설명서.md
```

## 증거력 주의

- **제3자 호스티드 프록시(Jina Reader 등) 경유 채증 엄격 금지**:
  외부 중계 프록시(예: `r.jina.ai` 등)를 통해 파싱된 마크다운 텍스트나 문서는 원본 웹 서버와의 직접 통신 증적이 아니며, 중간자 변조 위험 및 제3자 서버 개입으로 인해 **Chain of Custody(포렌식 무결성 체인)**가 법정에서 즉시 탄핵된다. 법원 제출용 채증은 반드시 로컬 브라우저(Playwright 등)가 원본 서버와 직접 TLS 통신을 맺고 렌더링한 **원시 바이트(Raw Bytes) / 렌더 스크린샷 + 로컬 SHA-256 해시**여야 한다. 외부 프록시 파싱 결과물은 단순 리서치 메모일 뿐 사법 증거물이 아니다.
- 스크린샷은 조작 가능성이 다투어질 수 있다. 채증 기록(JSON 해시) + 캡처 원본
  + 필요시 원 페이지 전체 PDF를 함께 보관해 조작 가능성을 최소화한다.
- 게시물이 삭제될 수 있으므로 **최초 발견 시 즉시** 채증하고, 가능하면
  캡처 시각의 페이지 HTTP 상태·제목을 메모(`--note`)로 남긴다.
- 공정 증명(공증·전자문서 유효확인)이 필요한 사건은 이 스킬 기록을 참고자료로
  쓰고 공적 절차를 병행한다.
