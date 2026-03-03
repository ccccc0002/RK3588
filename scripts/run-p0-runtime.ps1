[CmdletBinding()]
param(
  [string]$Host = "127.0.0.1",
  [int]$Port = 18080,
  [string]$DbPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:P0_RUNTIME_HOST = $Host
$env:P0_RUNTIME_PORT = [string]$Port
if ($DbPath) {
  $env:P0_RUNTIME_DB_PATH = $DbPath
}

Write-Host "Starting P0 runtime server on $Host`:$Port"
python -m src.p0_runtime.http_server
