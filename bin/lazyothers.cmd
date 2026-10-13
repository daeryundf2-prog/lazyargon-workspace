@echo off
rem lazyothers.cmd — cmd/PowerShell 양쪽에서 lazyothers.ps1을 부르는 진입점
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lazyothers.ps1" %*
exit /b %ERRORLEVEL%
