@echo off
setlocal
rem Install Python, FFmpeg and the web dependencies into a local virtual environment.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" -InstallSystemDeps %*
set "install_exit=%ERRORLEVEL%"
if not "%install_exit%"=="0" echo Installation failed. See the error above.
pause
exit /b %install_exit%
