[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$output = & git worktree list --porcelain
if ($LASTEXITCODE -ne 0) {
  throw "git worktree list failed"
}

$blocks = @()
$current = [ordered]@{}
foreach ($line in $output) {
  if ([string]::IsNullOrWhiteSpace($line)) {
    if ($current.Count -gt 0) {
      $blocks += [PSCustomObject]$current
      $current = [ordered]@{}
    }
    continue
  }

  if ($line.StartsWith("worktree ")) {
    $current.path = $line.Substring(9)
  } elseif ($line.StartsWith("HEAD ")) {
    $current.head = $line.Substring(5)
  } elseif ($line.StartsWith("branch ")) {
    $current.branch = $line.Substring(7) -replace "^refs/heads/", ""
  } elseif ($line -eq "detached") {
    $current.branch = "(detached)"
  }
}

if ($current.Count -gt 0) {
  $blocks += [PSCustomObject]$current
}

if ($blocks.Count -eq 0) {
  Write-Host "No worktrees found."
  exit 0
}

$blocks |
  Select-Object path, branch, head |
  Format-Table -AutoSize

