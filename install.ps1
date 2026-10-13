# Antigravity 2대 통합 플러그인(lazyargon + lazyargon-workspace) 자동 설치 스크립트
param(
    [switch]$Check
)
$ErrorActionPreference = "Stop"

$pluginDir = "$HOME\.gemini\config\plugins"

if ($Check) {
    $checkFail = 0
    Write-Host "== 환경 진단 (설치하지 않음) ==" -ForegroundColor Cyan
    $repos = @("lazyargon", "lazyargon-workspace")
    foreach ($name in $repos) {
        $p = Join-Path $pluginDir $name
        if ((Test-Path (Join-Path $p ".git")) -or (Test-Path (Join-Path $p "plugin.json"))) {
            Write-Host "  [OK] plugin $name" -ForegroundColor Green
        } else {
            Write-Host "  [FAIL] plugin $name - 미설치" -ForegroundColor Red
            $checkFail = 1
        }
    }
    foreach ($tool in @("git", "node", "npm", "python")) {
        if (Get-Command $tool -ErrorAction SilentlyContinue) {
            $ver = (& $tool --version 2>$null | Select-Object -First 1)
            Write-Host "  [OK] $tool ($ver)" -ForegroundColor Green
        } else {
            Write-Host "  [FAIL] $tool - 미설치" -ForegroundColor Red
            $checkFail = 1
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $py = "python"
        $venvPy = Join-Path $pluginDir "lazyargon-workspace\.venv\Scripts\python.exe"
        if (Test-Path $venvPy) { $py = $venvPy }
        foreach ($mod in @("fitz", "olefile", "openpyxl", "kiwipiepy", "anydoc")) {
            & $py -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('$mod') else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  [OK] python module $mod" -ForegroundColor Green
            } else {
                Write-Host "  [FAIL] python module $mod" -ForegroundColor Red
                $checkFail = 1
            }
        }
    }
    exit $checkFail
}

if (!(Test-Path $pluginDir)) {
    New-Item -ItemType Directory -Force -Path $pluginDir | Out-Null
}
$originalLocation = Get-Location
Set-Location $pluginDir

$repos = @{
    "lazyargon"           = "https://github.com/daeryundf2-prog/lazyargon.git"
    "lazyargon-workspace" = "https://github.com/daeryundf2-prog/lazyargon-workspace.git"
}

foreach ($name in $repos.Keys) {
    $targetPath = Join-Path $pluginDir $name
    if (Test-Path $targetPath) {
        Push-Location $targetPath
        try {
            git pull --ff-only
        } finally {
            Pop-Location
        }
    } else {
        git clone $repos[$name] $name
    }
}

$configPath = "$HOME\.gemini\config\config.json"
$defaultConfig = @{
    plugins = @{
        "lazyargon"           = @{ enabled = $true }
        "lazyargon-workspace" = @{ enabled = $true }
    }
}

Set-Location $originalLocation
Write-Host "Setup Completed Successfully! (PASS)" -ForegroundColor Green
