[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$Stage,

  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$Summary,

  [string]$Next = "",
  [string]$VerifyCommand = "",
  [switch]$Push,
  [switch]$SkipTag,
  [switch]$SkipCommit
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

function Ensure-File {
  param([string]$Path, [string]$Content)
  if (-not (Test-Path -Path $Path)) {
    $dir = Split-Path -Path $Path -Parent
    if ($dir -and -not (Test-Path -Path $dir)) {
      New-Item -Path $dir -ItemType Directory -Force | Out-Null
    }
    Set-Content -Path $Path -Value $Content -Encoding UTF8
  }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if (-not (Test-Path (Join-Path $repoRoot ".git"))) {
  throw "Current directory is not a git repository: $repoRoot"
}

if ($VerifyCommand) {
  Write-Host "Running verification command: $VerifyCommand"
  Invoke-Expression $VerifyCommand
  if ($LASTEXITCODE -ne 0) {
    throw "Verification command failed. Checkpoint aborted."
  }
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$isoTime = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
$safeStage = ($Stage -replace "[^a-zA-Z0-9-_]", "-").Trim("-")
if ([string]::IsNullOrWhiteSpace($safeStage)) {
  $safeStage = "stage"
}

$checkpointsDir = Join-Path $repoRoot ".checkpoints"
if (-not (Test-Path $checkpointsDir)) {
  New-Item -Path $checkpointsDir -ItemType Directory -Force | Out-Null
}

$dirtyStatus = @(Invoke-Git @("status", "--porcelain"))
$hasChanges = @($dirtyStatus | Where-Object { $_.Trim().Length -gt 0 }).Count -gt 0
$committedNow = $false

if ($hasChanges -and -not $SkipCommit) {
  Invoke-Git @("add", "-A") | Out-Null
  $commitMessage = "chore(checkpoint): $Stage - $Summary"
  Invoke-Git @("commit", "-m", $commitMessage) | Out-Null
  $committedNow = $true
}

$branch = (Invoke-Git @("branch", "--show-current") | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($branch)) {
  $branch = "detached-head"
}

$commit = (Invoke-Git @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
$shortCommit = (Invoke-Git @("rev-parse", "--short", "HEAD") | Select-Object -First 1).Trim()

$tagName = $null
if (-not $SkipTag) {
  $tagName = "checkpoint/$safeStage/$timestamp"
  Invoke-Git @("tag", $tagName, $commit) | Out-Null
}

$changedFiles = @()
if ($committedNow) {
  $changedFiles = @(Invoke-Git @("diff-tree", "--no-commit-id", "--name-only", "-r", $commit) |
    Where-Object { $_.Trim().Length -gt 0 } |
    ForEach-Object { $_.Trim() })
} elseif ($hasChanges) {
  $changedFiles = @(Invoke-Git @("status", "--porcelain") |
    Where-Object { $_.Length -ge 4 } |
    ForEach-Object { $_.Substring(3).Trim() })
}

$checkpointId = "$timestamp-$safeStage"
$checkpointJsonPath = Join-Path $checkpointsDir "$checkpointId.json"
$checkpointMdPath = Join-Path $checkpointsDir "$checkpointId.md"
$latestJsonPath = Join-Path $checkpointsDir "latest.json"
$memoryPath = Join-Path $repoRoot "docs/development-memory.md"

$metadata = [ordered]@{
  checkpoint_id = $checkpointId
  created_at = $isoTime
  stage = $Stage
  summary = $Summary
  next = $Next
  branch = $branch
  commit = $commit
  short_commit = $shortCommit
  tag = $tagName
  committed_now = $committedNow
  had_uncommitted_changes = $hasChanges
  changed_files = $changedFiles
}

$metadata | ConvertTo-Json -Depth 8 | Set-Content -Path $checkpointJsonPath -Encoding UTF8
$metadata | ConvertTo-Json -Depth 8 | Set-Content -Path $latestJsonPath -Encoding UTF8

$changedSection = if (@($changedFiles).Count -gt 0) {
  ($changedFiles | ForEach-Object { "- $_" }) -join "`n"
} else {
  "- (no file changes in this checkpoint)"
}

$tagText = if ($tagName) { $tagName } else { "(tag skipped)" }
$md = @"
# Checkpoint $checkpointId

- Time: $isoTime
- Stage: $Stage
- Branch: $branch
- Commit: $commit
- Tag: $tagText
- Summary: $Summary
- Next: $Next

## Changed Files
$changedSection
"@

Set-Content -Path $checkpointMdPath -Value $md -Encoding UTF8

Ensure-File -Path $memoryPath -Content @"
# Development Memory

Use this file as durable context between sessions.
Append-only checkpoints are written automatically by scripts/stage-checkpoint.ps1.
"@

$memoryEntry = @"

## [$isoTime] $Stage
- Branch: $branch
- Commit: $shortCommit
- Tag: $tagText
- Summary: $Summary
- Next: $Next
"@
Add-Content -Path $memoryPath -Value $memoryEntry -Encoding UTF8

if ($Push) {
  $remotes = Invoke-Git @("remote")
  $remote = $remotes | Where-Object { $_.Trim().Length -gt 0 } | Select-Object -First 1
  if (-not $remote) {
    throw "No git remote configured. Add one first, for example: git remote add origin <your-github-repo-url>"
  }

  Invoke-Git @("push", $remote, $branch) | Out-Null
  if ($tagName) {
    Invoke-Git @("push", $remote, $tagName) | Out-Null
  }
}

Write-Host "Checkpoint created:"
Write-Host "  id:      $checkpointId"
Write-Host "  stage:   $Stage"
Write-Host "  branch:  $branch"
Write-Host "  commit:  $shortCommit"
Write-Host "  tag:     $tagText"
Write-Host "  file:    $checkpointMdPath"
