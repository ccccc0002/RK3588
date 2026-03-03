[CmdletBinding()]
param(
  [string]$BaseUrl = "http://127.0.0.1:18080",
  [int]$IntervalMs = 500,
  [int]$Limit = 20,
  [ValidateSet("real", "always_success", "always_fail")]
  [string]$Mode = "real",
  [int]$MaxIterations = 0,
  [string]$AuthToken = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "Starting standalone push worker process..."
Write-Host "base_url=$BaseUrl interval_ms=$IntervalMs limit=$Limit mode=$Mode max_iterations=$MaxIterations"

if ($AuthToken) {
  python -m src.p0_runtime.push_process_worker `
    --base-url "$BaseUrl" `
    --interval-ms $IntervalMs `
    --limit $Limit `
    --mode $Mode `
    --max-iterations $MaxIterations `
    --auth-token "$AuthToken"
} else {
  python -m src.p0_runtime.push_process_worker `
  --base-url "$BaseUrl" `
  --interval-ms $IntervalMs `
  --limit $Limit `
  --mode $Mode `
  --max-iterations $MaxIterations
}
