# lock_evidence.ps1 — 증거 디렉토리 원클릭 읽기전용 잠금 (Windows).
# 사용: powershell -ExecutionPolicy Bypass -File scripts\lock_evidence.ps1 [evidence_dir]
# 되돌리기: attrib -R <dir>\*.* /S
param([string]$Dir = "evidence")
if (-not (Test-Path $Dir -PathType Container)) {
  Write-Error "[lazyforensic] not a directory: $Dir"
  exit 2
}
Get-ChildItem $Dir -Recurse -File | ForEach-Object { $_.IsReadOnly = $true }
Write-Output "[lazyforensic] locked (read-only): $Dir"
