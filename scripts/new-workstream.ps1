[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$Task,

  [ValidatePattern("^P[0-3]$")]
  [string]$Stage = "P0",

  [string]$BaseBranch = "master",
  [string]$RootPath = "",
  [switch]$NoCheckout
)

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

function Slugify {
  param([string]$Value)
  $slug = $Value.ToLowerInvariant()
  $slug = $slug -replace "[^a-z0-9\- ]", ""
  $slug = $slug -replace "\s+", "-"
  $slug = $slug.Trim("-")
  if ([string]::IsNullOrWhiteSpace($slug)) {
    return "task"
  }
  return $slug
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if ([string]::IsNullOrWhiteSpace($RootPath)) {
  $RootPath = Join-Path $repoRoot ".worktrees"
}

if (-not (Test-Path $RootPath)) {
  New-Item -Path $RootPath -ItemType Directory -Force | Out-Null
}

$slug = Slugify $Task
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$branch = "ws/$($Stage.ToLowerInvariant())-$slug"
$worktreePath = Join-Path $RootPath "$($Stage.ToLowerInvariant())-$slug-$stamp"

if ($NoCheckout) {
  Invoke-Git @("worktree", "add", "--detach", $worktreePath, $BaseBranch) | Out-Null
} else {
  Invoke-Git @("worktree", "add", "-b", $branch, $worktreePath, $BaseBranch) | Out-Null
}

$metaPath = Join-Path $repoRoot "docs/workflow/workstreams.md"
if (-not (Test-Path $metaPath)) {
  $seed = @"
# Workstreams

| Time | Stage | Task | Branch | Path | Base |
| --- | --- | --- | --- | --- | --- |
"@
  Set-Content -Path $metaPath -Value $seed -Encoding UTF8
}

$time = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
$branchLabel = if ($NoCheckout) { "(detached)" } else { $branch }
$line = "| $time | $Stage | $($Task -replace "\|", "\/") | $branchLabel | $($worktreePath -replace "\|", "\/") | $BaseBranch |"
Add-Content -Path $metaPath -Value $line -Encoding UTF8

Write-Host "Workstream created:"
Write-Host "  stage:  $Stage"
Write-Host "  task:   $Task"
Write-Host "  branch: $branchLabel"
Write-Host "  path:   $worktreePath"
