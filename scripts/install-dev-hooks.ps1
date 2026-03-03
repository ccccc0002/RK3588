[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$hooksDir = Join-Path $repoRoot ".githooks"
if (-not (Test-Path $hooksDir)) {
  New-Item -Path $hooksDir -ItemType Directory -Force | Out-Null
}

$postCommitPath = Join-Path $hooksDir "post-commit"
$postCommit = @'
#!/bin/sh
REPO_ROOT=$(git rev-parse --show-toplevel)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$REPO_ROOT/scripts/post-commit-sync.ps1" >/dev/null 2>&1 || true
'@
Set-Content -Path $postCommitPath -Value $postCommit -Encoding ASCII

& git config core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
  throw "Failed to configure core.hooksPath"
}

Write-Host "Hook path configured: .githooks"
Write-Host "Installed hook: .githooks/post-commit"
