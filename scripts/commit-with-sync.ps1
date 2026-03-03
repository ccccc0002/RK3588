[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$Message,

  [switch]$AddAll,
  [string[]]$Paths = @(),
  [string]$VerifyCommand = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if ($VerifyCommand) {
  Write-Host "Running verification command: $VerifyCommand"
  Invoke-Expression $VerifyCommand
  if ($LASTEXITCODE -ne 0) {
    throw "Verification command failed. Commit aborted."
  }
}

if ($AddAll) {
  & git add -A
  if ($LASTEXITCODE -ne 0) { throw "git add -A failed" }
} elseif ($Paths.Count -gt 0) {
  & git add @Paths
  if ($LASTEXITCODE -ne 0) { throw "git add <paths> failed" }
}

& git commit -m $Message
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts/post-commit-sync.ps1")
if ($LASTEXITCODE -ne 0) { throw "post-commit sync failed" }

Write-Host "Commit and sync completed."

