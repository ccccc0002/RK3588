[CmdletBinding()]
param(
  [ValidateRange(5, 240)]
  [int]$IntervalMinutes = 45,

  [ValidateRange(1, 1000)]
  [int]$MaxRounds = 8
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

for ($i = 1; $i -le $MaxRounds; $i++) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts/generate-compact-packet.ps1") -Quiet

  $time = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
  Write-Host "[$time] Compact reminder #${i}: review docs/workflow/compact-packet-latest.md and run /compact if context is heavy."

  if ($i -lt $MaxRounds) {
    Start-Sleep -Seconds ($IntervalMinutes * 60)
  }
}

Write-Host "Compact reminder session completed."
