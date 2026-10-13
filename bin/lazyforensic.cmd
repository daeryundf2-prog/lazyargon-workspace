@echo off
rem lazyforensic.cmd — cmd/PowerShell 양쪽에서 lazyforensic.ps1을 부르는 진입점
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lazyforensic.ps1" %*
exit /b %ERRORLEVEL%
