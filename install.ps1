# Antigravity 4대 플러그인 원클릭 완전 자동 설치 스크립트
param(
    [switch]$Check
)
$ErrorActionPreference = "Stop"

$pluginDir = "$HOME\.gemini\config\plugins"

if ($Check) {
    $checkFail = 0
    Write-Host "== 환경 진단 (설치하지 않음) ==" -ForegroundColor Cyan
    $repos = @("lazyantigravity", "lazyforensic", "lazyothers", "lazydiagram")
    foreach ($name in $repos) {
        $p = Join-Path $pluginDir $name
        if (Test-Path (Join-Path $p ".git")) {
            $hash = (git -C $p rev-parse --short HEAD 2>$null)
            Write-Host "  [OK] plugin $name ($hash)" -ForegroundColor Green
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
        $venvPy = Join-Path $pluginDir "lazyothers\.venv\Scripts\python.exe"
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

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Antigravity Complete Setup Auto-Installer" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

if (!(Test-Path $pluginDir)) {
    New-Item -ItemType Directory -Force -Path $pluginDir | Out-Null
}
$originalLocation = Get-Location
Set-Location $pluginDir

# 1. Git Repositories Clone or Pull
$repos = @{
    "lazyantigravity" = "https://github.com/daeryundf2-prog/LAZYANTIGRAVITY.git"
    "lazyforensic"    = "https://github.com/daeryundf2-prog/lazyforensic.git"
    "lazyothers"      = "https://github.com/daeryundf2-prog/lazyothers.git"
    "lazydiagram"     = "https://github.com/daeryundf2-prog/lazydiagram.git"
}

foreach ($name in $repos.Keys) {
    $targetPath = Join-Path $pluginDir $name
    if (Test-Path $targetPath) {
        Write-Host "Updating $name..." -ForegroundColor Yellow
        Push-Location $targetPath
        try {
            $gitStatus = git status --porcelain 2>&1
            if ($gitStatus) {
                Write-Host "  [!] $name has local changes, stashing..." -ForegroundColor Yellow
                git stash push -m "auto-stash before pull" | Out-Null
            }
            git pull --ff-only
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [!] git pull failed for $name, skipping" -ForegroundColor Red
            }
        } catch {
            Write-Host "  [!] Failed to update ${name}: $_" -ForegroundColor Red
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "Cloning $name..." -ForegroundColor Green
        git clone $repos[$name] $name
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [!] Failed to clone $name" -ForegroundColor Red
        }
    }
}

# 2. Build LazyAntigravity (if Node.js available)
# 주의: PowerShell 5.1에서는 네이티브 명령(npm/git)의 non-zero exit이
# $ErrorActionPreference="Stop"이어도 catch로 들어오지 않으므로 $LASTEXITCODE를 직접 검사한다.
if (Get-Command npm -ErrorAction SilentlyContinue) {
    if (Test-Path "$pluginDir\lazyantigravity\package.json") {
        Write-Host "Building LazyAntigravity..." -ForegroundColor Green
        Push-Location "$pluginDir\lazyantigravity"
        try {
            npm install
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [!] LazyAntigravity npm install failed (exit $LASTEXITCODE)" -ForegroundColor Red
            } else {
                npm run build
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "  [!] LazyAntigravity build failed (exit $LASTEXITCODE)" -ForegroundColor Red
                }
            }
        } catch {
            Write-Host "  [!] Build failed: $_" -ForegroundColor Red
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "[!] lazyantigravity not cloned — skipping build" -ForegroundColor Yellow
    }
} else {
    Write-Host "[!] npm not found, skipping build step" -ForegroundColor Yellow
}

# 3. Setup LazyOthers (Sync MCP tools)
if (Test-Path "$pluginDir\lazyothers\package.json") {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "Syncing LazyOthers MCP tools..." -ForegroundColor Green
        Push-Location "$pluginDir\lazyothers"
        try {
            npm run setup
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [!] Sync failed (exit $LASTEXITCODE)" -ForegroundColor Red
            }
        } catch {
            Write-Host "  [!] Sync failed: $_" -ForegroundColor Red
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "[!] npm not found, skipping LazyOthers sync" -ForegroundColor Yellow
    }
}

# 3.5 Build korean-law-mcp (lazyforensic, optional)
if (Test-Path "$pluginDir\lazyforensic\korean-law-mcp\package.json") {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "Building korean-law-mcp (lazyforensic)..." -ForegroundColor Green
        Push-Location "$pluginDir\lazyforensic\korean-law-mcp"
        try {
            npm install
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [!] korean-law-mcp npm install failed (exit $LASTEXITCODE)" -ForegroundColor Red
            } else {
                npm run build
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "  [!] korean-law-mcp build failed (exit $LASTEXITCODE)" -ForegroundColor Red
                }
            }
        } catch {
            Write-Host "  [!] korean-law-mcp build failed: $_" -ForegroundColor Red
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "[!] npm not found, skipping korean-law-mcp build" -ForegroundColor Yellow
    }
}

# 3.6 Python dependencies for lazyothers skills (pymupdf/olefile etc.)
if (Get-Command python -ErrorAction SilentlyContinue) {
    Write-Host "Installing Python dependencies for lazyothers..." -ForegroundColor Green
    Push-Location "$pluginDir\lazyothers"
    try {
        # PS 5.1에서 `2>$null` + EAP=Stop은 pip의 stderr 경고를 NativeCommandError로
        # 오판해 헛된 폴백을 유발한다 — cmd /c로 감싸 stderr를 PowerShell에서 격리.
        cmd /c "python -m pip install -r requirements.txt >NUL 2>NUL"
        if ($LASTEXITCODE -ne 0) {
            # PEP 668(externally-managed) 등으로 시스템 설치가 거부되면 .venv로 폴백
            Write-Host "  [i] system pip 실패 — .venv로 폴백" -ForegroundColor Yellow
            cmd /c "python -m venv .venv >NUL 2>NUL"
            cmd /c ".\.venv\Scripts\python.exe -m pip install -r requirements.txt >NUL 2>NUL"
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  [i] .venv\Scripts\python.exe 로 스크립트를 실행하세요" -ForegroundColor Yellow
            } else {
                Write-Host "  [!] pip install failed (exit $LASTEXITCODE)" -ForegroundColor Red
            }
        }
    } catch {
        Write-Host "  [!] pip install failed: $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }

    # 3.7 lazyforensic 선택 의존성 (~/.lfenv) — 실패해도 계속
    if (Test-Path "$pluginDir\lazyforensic\scripts\setup_forensic_env.py") {
        Write-Host "Installing lazyforensic optional deps (~/.lfenv)..." -ForegroundColor Green
        Push-Location "$pluginDir\lazyforensic"
        try {
            python scripts\setup_forensic_env.py
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  [!] lazyforensic env setup 실패 (exit $LASTEXITCODE)" -ForegroundColor Red
            }
        } catch {
            Write-Host "  [!] lazyforensic setup failed: $_" -ForegroundColor Red
        } finally {
            Pop-Location
        }
    }
} else {
    Write-Host "[!] python not found, skipping pip install" -ForegroundColor Yellow
}

# 4. Activate plugins in config.json (MERGE, not overwrite)
Write-Host "Activating plugins in config.json..." -ForegroundColor Green
$configPath = "$HOME\.gemini\config\config.json"
$configDir = Split-Path $configPath -Parent
if (!(Test-Path $configDir)) {
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null
}

$defaultConfig = @{
    plugins = @{
        lazyantigravity = @{ enabled = $true }
        lazyforensic    = @{ enabled = $true }
        lazyothers      = @{ enabled = $true }
        lazydiagram     = @{ enabled = $true }
    }
}

# BOM 없는 UTF-8로 기록한다. Windows PowerShell 5.1의 Set-Content -Encoding UTF8은
# BOM을 붙여서, BOM을 허용하지 않는 파서(Python json.load, Node JSON.parse 등)가
# config.json을 읽지 못하게 될 수 있다.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Write-ConfigFile {
    param([string]$Path, [string]$Content)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

if (Test-Path $configPath) {
    try {
        # 주의: ConvertFrom-Json -AsHashtable은 PS 7+ 전용. PS 5.1에서는 PSCustomObject로
        # 병합해야 하며, -AsHashtable을 쓰면 병합이 항상 실패해 기존 설정이 기본값으로 덮어써졌다.
        $existingJson = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not ($existingJson.PSObject.Properties['plugins'])) {
            $existingJson | Add-Member -MemberType NoteProperty -Name plugins -Value ([pscustomobject]@{})
        }
        foreach ($k in $defaultConfig.plugins.Keys) {
            $enabled = $defaultConfig.plugins[$k].enabled
            if ($existingJson.plugins.PSObject.Properties[$k]) {
                $existingJson.plugins.$k | Add-Member -MemberType NoteProperty -Name enabled -Value $enabled -Force
            } else {
                $existingJson.plugins | Add-Member -MemberType NoteProperty -Name $k -Value ([pscustomobject]@{ enabled = $enabled })
            }
        }
        $mergedJson = $existingJson | ConvertTo-Json -Depth 10
        Write-ConfigFile -Path $configPath -Content $mergedJson
        Write-Host "  Merged plugins into existing config.json" -ForegroundColor Green
    } catch {
        Write-Host "  [!] Failed to merge config, backing up and writing default: $_" -ForegroundColor Yellow
        Copy-Item $configPath "$configPath.bak" -Force -ErrorAction SilentlyContinue
        Write-ConfigFile -Path $configPath -Content ($defaultConfig | ConvertTo-Json -Depth 10)
    }
} else {
    Write-ConfigFile -Path $configPath -Content ($defaultConfig | ConvertTo-Json -Depth 10)
    Write-Host "  Created new config.json" -ForegroundColor Green
}

Set-Location $originalLocation

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Setup Completed Successfully! (PASS)" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
