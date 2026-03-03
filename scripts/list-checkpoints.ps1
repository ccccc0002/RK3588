[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$checkpointsDir = Join-Path $repoRoot ".checkpoints"

if (-not (Test-Path $checkpointsDir)) {
  Write-Host "No checkpoints directory found: $checkpointsDir"
  exit 0
}

$files = Get-ChildItem -Path $checkpointsDir -Filter "*.json" -File |
  Where-Object { $_.Name -ne "latest.json" } |
  Sort-Object LastWriteTime -Descending

if ($files.Count -eq 0) {
  Write-Host "No checkpoint metadata files found in $checkpointsDir"
  exit 0
}

$items = @()
foreach ($file in $files) {
  $raw = Get-Content -Path $file.FullName -Raw
  $obj = $raw | ConvertFrom-Json
  $items += [PSCustomObject]@{
    id = $obj.checkpoint_id
    stage = $obj.stage
    created_at = $obj.created_at
    branch = $obj.branch
    commit = $obj.short_commit
    tag = $obj.tag
  }
}

$items | Format-Table -AutoSize

