[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$Stage,

  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$Lane,

  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$Agent,

  [Parameter(Mandatory = $true)]
  [ValidateSet("planned", "in_progress", "blocked", "done")]
  [string]$Status,

  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$Summary,

  [string]$Next = "",
  [string]$Risks = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$logPath = Join-Path $repoRoot "docs/workflow/agent-sync-log.md"

if (-not (Test-Path $logPath)) {
  $seed = @"
# Agent Sync Log

Append-only collaboration log across lanes and stages.

| Time | Stage | Lane | Agent | Status | Summary | Next | Risks |
| --- | --- | --- | --- | --- | --- | --- | --- |
"@
  Set-Content -Path $logPath -Value $seed -Encoding UTF8
}

function Escape-Pipe {
  param([string]$Text)
  return ($Text -replace "\|", "\/")
}

$time = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
$line = "| $time | $(Escape-Pipe $Stage) | $(Escape-Pipe $Lane) | $(Escape-Pipe $Agent) | $Status | $(Escape-Pipe $Summary) | $(Escape-Pipe $Next) | $(Escape-Pipe $Risks) |"
Add-Content -Path $logPath -Value $line -Encoding UTF8

Write-Host "Sync log appended: $line"

