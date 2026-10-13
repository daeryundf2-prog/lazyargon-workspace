<#
.SYNOPSIS
    lazyforensic 선택 의존성 환경 복제 (Windows PowerShell)

.DESCRIPTION
    setup_forensic_env.py의 Windows 래퍼.
    핵심 스크립트는 표준 라이브러리만 쓰므로 그대로 동작하고,
    이 스크립트는 venv 생성 + 선택 의존성 설치만 담당한다.

.EXAMPLE
    powershell -File scripts/setup_forensic_env.ps1 -Check
    powershell -File scripts/setup_forensic_env.ps1
    powershell -File scripts/setup_forensic_env.ps1 -With imaging,stt
#>
param(
    [switch]$Check,
    [string]$Dir = "$env:USERPROFILE\.lfenv",
    [string[]]$With = @()
)

$ErrorActionPreference = "Stop"

$DepGroups = @{
    imaging = @{ Desc = "이미지 유사도·EXIF"; Pkgs = @("pillow>=10.0,<12", "numpy>=1.26,<3") }
    stt     = @{ Desc = "로컬 STT";         Pkgs = @("faster-whisper>=1.1,<2") }
    osint   = @{ Desc = "사용자명 OSINT";    Pkgs = @("sherlock-project") }
    morph   = @{ Desc = "한국어 형태소";      Pkgs = @("kiwipiepy>=0.20,<1") }
}

function Test-Module([string]$py, [string]$mod) {
    & $py -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('$mod') else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) {
    Write-Error "python을 찾을 수 없습니다. python.org에서 3.11+ 설치 후 재시도하세요."
    exit 2
}

if ($Check) {
    Write-Output "python: $python"
    & $python --version
    foreach ($m in @("PIL", "numpy", "faster_whisper", "whisper", "moonshine",
                     "sherlock_project", "kiwipiepy")) {
        $ok = Test-Module $python $m
        Write-Output ("  {0} module {1}" -f ($(if ($ok) { "OK" } else { "--" })), $m)
    }
    foreach ($b in @("ffmpeg", "ffprobe", "fpcalc", "sherlock")) {
        $ok = [bool](Get-Command $b -ErrorAction SilentlyContinue)
        Write-Output ("  {0} binary {1}" -f ($(if ($ok) { "OK" } else { "--" })), $b)
    }
    exit 0
}

$groups = if ($With.Count -gt 0) { $With } else { $DepGroups.Keys }
$packages = foreach ($g in $groups) { $DepGroups[$g].Pkgs }

Write-Output "venv 생성: $Dir"
& $python -m venv $Dir
$pip = Join-Path $Dir "Scripts\pip.exe"
$venvPy = Join-Path $Dir "Scripts\python.exe"

Write-Output ("설치: " + ($packages -join ", "))
& $pip install @packages
if ($LASTEXITCODE -ne 0) { Write-Error "pip install 실패"; exit 1 }

Write-Output "`n완료. 이 python으로 실행하세요:`n  $venvPy scripts\local_stt.py ..."

foreach ($b in @("ffmpeg", "fpcalc")) {
    if (-not (Get-Command $b -ErrorAction SilentlyContinue)) {
        $hint = if ($b -eq "ffmpeg") { "winget install Gyan.FFmpeg" } else { "winget install chromaprint (또는 https://acoustid.org/chromaprint)" }
        Write-Output "시스템 바이너리 없음: $b -> $hint"
    }
}
exit 0
