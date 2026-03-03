[CmdletBinding()]
param(
  [string]$Checkpoint = "latest",
  [switch]$CreateResumeBranch,
  [string]$BranchName = ""
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

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$checkpointsDir = Join-Path $repoRoot ".checkpoints"
$meta = $null

if ($Checkpoint -eq "latest") {
  $latest = Join-Path $checkpointsDir "latest.json"
  if (-not (Test-Path $latest)) {
    throw "No latest checkpoint file found: $latest"
  }
  $meta = (Get-Content -Path $latest -Raw) | ConvertFrom-Json
} else {
  $candidate = Join-Path $checkpointsDir "$Checkpoint.json"
  if (Test-Path $candidate) {
    $meta = (Get-Content -Path $candidate -Raw) | ConvertFrom-Json
  } else {
    $resolved = (Invoke-Git @("rev-parse", "--verify", $Checkpoint) | Select-Object -First 1).Trim()
    $meta = [PSCustomObject]@{
      checkpoint_id = "git-ref-$Checkpoint"
      stage = "unknown"
      created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
      branch = (Invoke-Git @("branch", "--show-current") | Select-Object -First 1).Trim()
      commit = $resolved
      short_commit = (Invoke-Git @("rev-parse", "--short", $resolved) | Select-Object -First 1).Trim()
      tag = ""
      summary = "Loaded from git ref."
      next = ""
    }
  }
}

Write-Host "Checkpoint loaded:"
Write-Host "  id:      $($meta.checkpoint_id)"
Write-Host "  stage:   $($meta.stage)"
Write-Host "  commit:  $($meta.commit)"
Write-Host "  tag:     $($meta.tag)"
Write-Host "  summary: $($meta.summary)"
Write-Host "  next:    $($meta.next)"

if ($CreateResumeBranch) {
  if ([string]::IsNullOrWhiteSpace($BranchName)) {
    $safeStage = ($meta.stage -replace "[^a-zA-Z0-9-_]", "-").Trim("-")
    if ([string]::IsNullOrWhiteSpace($safeStage)) {
      $safeStage = "stage"
    }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $BranchName = "resume/$safeStage/$stamp"
  }

  Invoke-Git @("switch", "-c", $BranchName, $meta.commit) | Out-Null
  Write-Host "Created and switched to resume branch: $BranchName"
} else {
  Write-Host "No branch switch was performed. Use -CreateResumeBranch to resume from this checkpoint."
}
