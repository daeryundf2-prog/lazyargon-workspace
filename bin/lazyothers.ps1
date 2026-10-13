# lazyothers.ps1 — bin/lazyothers의 Windows 네이티브 판 (PowerShell)
# 사용: PATH에 이 bin\ 디렉터리를 추가하면 cmd/PowerShell 어디서든:
#   lazyothers doc <파일>           (cmd shim: lazyothers.cmd 경유)
#   powershell -File bin\lazyothers.ps1 doc <파일>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

# 우선순위: $LF_PYTHON > $LO_PYTHON > $Root\.venv > %USERPROFILE%\.lfenv > python > py
if ($env:LF_PYTHON) {
    $Py = $env:LF_PYTHON
} elseif ($env:LO_PYTHON) {
    $Py = $env:LO_PYTHON
} elseif (Test-Path "$Root\.venv\Scripts\python.exe") {
    $Py = "$Root\.venv\Scripts\python.exe"
} elseif (Test-Path "$env:USERPROFILE\.lfenv\Scripts\python.exe") {
    $Py = "$env:USERPROFILE\.lfenv\Scripts\python.exe"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $Py = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $Py = "py"
} else {
    Write-Error "python을 찾을 수 없습니다. python.org에서 3.11+ 설치 후 재시도하세요."
    exit 2
}

function Usage {
    Write-Host @"
lazyothers - 법률/문서 스크립트 CLI 래퍼 (로컬 전용, Windows)

  lazyothers doc <파일>            HWP/HWPX/PDF 문서 텍스트 추출
  lazyothers sheet <evidence.json> 증거설명서 생성 (lazyforensic export 출력 호환)
  lazyothers stamp <pdf>           증거 표찰 스탬핑
  lazyothers bind <evidence.json>  표찰 PDF 병합 바인더 (ECFS 용량 분할)
  lazyothers draft                 법률 문서 초안 (변호사 검토 전제)
  lazyothers pii <파일>            한국어 개인정보 마스킹
  lazyothers ruling <파일>         판결문 구조 분석
  lazyothers flow <파일>           금융 거래 흐름 추적
  lazyothers db <쿼리>             증거 DB 조회
  lazyothers integrity <대상>      증거 무결성 감사
  lazyothers certify <파일>        증거 파일 인증
  lazyothers morph <파일>          Kiwi 형태소 그라운딩
"@
}

if ($args.Count -lt 1) { Usage; exit 2 }
$cmd = $args[0]
$rest = @($args | Select-Object -Skip 1)

switch ($cmd) {
    "doc"       { $script = "parse_korean_doc.py" }
    "sheet"     { $script = "generate_evidence_doc.py" }
    "stamp"     { $script = "stamp_evidence.py" }
    "bind"      { $script = "bind_court_pdf.py" }
    "draft"     { $script = "generate_legal_draft.py" }
    "pii"       { $script = "mask_korean_pii.py" }
    "ruling"    { $script = "analyze_court_ruling.py" }
    "flow"      { $script = "trace_financial_flow.py" }
    "db"        { $script = "query_evidence_db.py" }
    "integrity" { $script = "audit_evidence_integrity.py" }
    "certify"   { $script = "certify_evidence_file.py" }
    "morph"     { $script = "korean_morph_grounding.py" }
    { $_ -in @("-h", "--help", "help") } { Usage; exit 0 }
    default { Write-Error "알 수 없는 명령: $cmd"; Usage; exit 2 }
}

& $Py (Join-Path $Root "scripts\$script") @rest
exit $LASTEXITCODE
