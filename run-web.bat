@echo off
setlocal
rem Double-click to start the local UI, or pass PowerShell options such as -Port 9000.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-web.ps1" %*
set "launch_exit=%ERRORLEVEL%"
if not "%launch_exit%"=="0" (
    echo.
    echo Acoustic Sync could not start. See the error above.
    pause
)
exit /b %launch_exit%
