[CmdletBinding()]
param(
    [ValidateSet('runtime', 'web', 'dev')][string]$Profile = 'web',
    [Alias('install-system-deps')][switch]$InstallSystemDeps,
    [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Executable failed (exit $LASTEXITCODE)." }
}
function Find-Python {
    if ($Python) { $candidates = @($Python) }
    else { $candidates = @((Join-Path $Root '.venv\Scripts\python.exe'), (Join-Path $Root '.runtime\python\tools\python.exe'), 'python3.13', 'python3.12', 'python', 'python3', 'py') }
    foreach ($candidate in $candidates) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            $resolved = & $candidate -c 'import sys; print(sys.executable) if sys.version_info >= (3,12) else sys.exit(1)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved) { return [string]($resolved | Select-Object -Last 1) }
        }
    }
    return $null
}

$Interpreter = Find-Python
if ($InstallSystemDeps -and (-not $Interpreter -or -not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue))) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'winget is required for -InstallSystemDeps. Install Python 3.12+ and FFmpeg manually, then rerun.' }
    if (-not $Interpreter) {
        Invoke-Checked 'winget' @('install', '--id', 'Python.Python.3.13', '--exact', '--accept-package-agreements', '--accept-source-agreements')
    }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
        Invoke-Checked 'winget' @('install', '--id', 'Gyan.FFmpeg', '--exact', '--accept-package-agreements', '--accept-source-agreements')
    }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
    $Interpreter = Find-Python
}
if (-not $Interpreter) { throw 'Python >=3.12 was not found. Install Python 3.12/3.13, reopen PowerShell, or use -Python C:\path\python.exe.' }
foreach ($tool in @('ffmpeg', 'ffprobe')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is missing from PATH. Install FFmpeg or rerun with -InstallSystemDeps; then reopen PowerShell." }
    Invoke-Checked $tool @('-version')
}
$Venv = Join-Path $Root '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
if (Test-Path -LiteralPath $Venv) {
    if (-not (Test-Path -LiteralPath $VenvPython)) { throw "$Venv exists but is not a usable Windows venv. Move it aside manually and retry." }
} else { Invoke-Checked $Interpreter @('-m', 'venv', $Venv) }
Invoke-Checked $VenvPython @('-c', 'import sys; assert sys.version_info >= (3,12)')
Invoke-Checked $VenvPython @('-m', 'pip', 'install', '-r', (Join-Path $Root 'requirements\build.txt'))
Invoke-Checked $VenvPython @('-m', 'pip', 'install', '-r', (Join-Path $Root "requirements\$Profile.txt"))
Invoke-Checked $VenvPython @('-m', 'pip', 'install', '--no-deps', '--no-build-isolation', '-e', $Root)
Invoke-Checked $VenvPython @('-m', 'pip', 'check')
Invoke-Checked (Join-Path $Venv 'Scripts\acoustic-sync.exe') @('doctor')
Write-Host "Installed $Profile profile. CLI: $Venv\Scripts\acoustic-sync.exe"
