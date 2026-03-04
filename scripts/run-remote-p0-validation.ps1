[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidateNotNullOrEmpty()]
  [string]$RepoPath,

  [string]$RemoteHost = "192.168.1.104",
  [string]$User = "",
  [string]$PythonBin = "python3.8",
  [switch]$BatchMode = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$sshPath = Get-Command ssh -ErrorAction SilentlyContinue
if (-not $sshPath) {
  throw "ssh command not found. Install OpenSSH client first."
}

$target = if ([string]::IsNullOrWhiteSpace($User)) { $RemoteHost } else { "$User@$RemoteHost" }
$repoEscaped = $RepoPath.Replace('"', '\"')
$pythonEscaped = $PythonBin.Replace('"', '\"')

$remoteCommand = @(
  "set -e"
  "cd `"$repoEscaped`""
  "`"$pythonEscaped`" --version"
  "`"$pythonEscaped`" -m unittest discover -s tests -p 'test_*.py'"
) -join "; "

$sshArgs = @("-o", "ConnectTimeout=8")
if ($BatchMode) {
  $sshArgs += @("-o", "BatchMode=yes")
}
$sshArgs += @("-o", "StrictHostKeyChecking=no")
$sshArgs += @("-o", "UserKnownHostsFile=NUL")

$sshArgs += $target
$sshArgs += $remoteCommand

Write-Host "Running remote validation on $target"
Write-Host "RepoPath: $RepoPath"
Write-Host "Command: $PythonBin -m unittest discover -s tests -p 'test_*.py'"

& $sshPath.Source @sshArgs
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
  throw "Remote validation failed with exit code $exitCode"
}

Write-Host "Remote py3.8 validation passed."
