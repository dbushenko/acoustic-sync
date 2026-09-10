[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [string]$StateDir = '',
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Cli = Join-Path $ProjectRoot '.venv\Scripts\acoustic-sync.exe'
if (-not (Test-Path -LiteralPath $Cli)) { throw 'Run scripts\install.ps1 -Profile web first.' }
if (-not $StateDir) { $StateDir = Join-Path $ProjectRoot 'results\web-state' }
$CliArguments = @('serve', '--port', [string]$Port)
$CliArguments += @('--state-dir', $StateDir)
if (-not $NoBrowser) { $CliArguments += '--open-browser' }
Write-Host "Acoustic Sync web UI: http://127.0.0.1:$Port"
Write-Host 'Keep this window open while using the UI. Press Ctrl+C to stop.'
Push-Location -LiteralPath $ProjectRoot
try {
    & $Cli @CliArguments
    $LaunchExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $LaunchExitCode
