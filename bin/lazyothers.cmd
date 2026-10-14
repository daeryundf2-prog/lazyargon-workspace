@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
where bash >nul 2>nul
if %ERRORLEVEL% equ 0 (
  bash "%SCRIPT_DIR%lazyothers" %*
  exit /b %ERRORLEVEL%
)
where sh >nul 2>nul
if %ERRORLEVEL% equ 0 (
  sh "%SCRIPT_DIR%lazyothers" %*
  exit /b %ERRORLEVEL%
)
echo [lazyothers] Git Bash (bash/sh) is required on PATH.&2
exit /b 1
