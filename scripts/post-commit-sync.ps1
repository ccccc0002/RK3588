[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Git {
  param([string[]]$GitArgs)

  $previousErrorAction = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $output = & git @GitArgs 2>&1
  $exitCode = $LASTEXITCODE
  $ErrorActionPreference = $previousErrorAction

  $outputText = ($output | ForEach-Object { "$_" })
  if ($exitCode -ne 0) {
    $cmd = "git $($GitArgs -join ' ')"
    throw "$cmd failed.`n$($outputText -join "`n")"
  }
  return $outputText
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$time = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
$branch = (Invoke-Git @("branch", "--show-current") | Select-Object -First 1).Trim()
$sha = (Invoke-Git @("rev-parse", "--short", "HEAD") | Select-Object -First 1).Trim()
$subject = (Invoke-Git @("log", "-1", "--pretty=%s") | Select-Object -First 1).Trim()
$files = @(Invoke-Git @("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD") | Where-Object { $_.Trim().Length -gt 0 })
$fileCount = @($files).Count

$checkpointsDir = Join-Path $repoRoot ".checkpoints"
if (-not (Test-Path $checkpointsDir)) {
  New-Item -Path $checkpointsDir -ItemType Directory -Force | Out-Null
}

$timelinePath = Join-Path $checkpointsDir "commit-timeline.local.md"
if (-not (Test-Path $timelinePath)) {
  $seed = @"
# Local Commit Timeline

Auto-appended by .githooks/post-commit via scripts/post-commit-sync.ps1.

| Time | Branch | Commit | Subject | Files |
| --- | --- | --- | --- | --- |
"@
  Set-Content -Path $timelinePath -Value $seed -Encoding UTF8
}

$safeSubject = ($subject -replace "\|", "\/")
$line = "| $time | $branch | $sha | $safeSubject | $fileCount |"
Add-Content -Path $timelinePath -Value $line -Encoding UTF8

$state = [ordered]@{
  created_at = $time
  branch = $branch
  commit = $sha
  subject = $subject
  files = $files
}
$state | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $checkpointsDir "latest-commit.json") -Encoding UTF8

Write-Host "Post-commit sync updated: $sha ($fileCount files)"
