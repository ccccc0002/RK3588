[CmdletBinding()]
param(
  [string]$Host = "127.0.0.1",
  [int]$Port = 18080,
  [string]$DbPath = "",
  [string]$BootstrapToken = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:P0_RUNTIME_HOST = $Host
$env:P0_RUNTIME_PORT = [string]$Port
if ($DbPath) {
  $env:P0_RUNTIME_DB_PATH = $DbPath
}
if ($BootstrapToken) {
  $env:P0_RUNTIME_BOOTSTRAP_TOKEN = $BootstrapToken
}

Write-Host "Starting P0 runtime server on $Host`:$Port"
python -m src.p0_runtime.http_server
