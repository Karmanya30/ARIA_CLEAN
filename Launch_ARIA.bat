@echo off
rem Double-click to start ARIA (API + web) and open it in Edge. The lip-sync server starts by itself when the GPU stack is installed; "cpu" skips it. "gpu" forces it: start the original avatar's lip-sync server (Launch_ARIA.bat gpu),
rem (it serves both the original avatar and the New ARIA Avatar; "gpu-new" is an alias).
rem Progress is shown in this window; a failure shows a message box and is logged in logs\launch.log.
if /i "%~1"=="gpu" (set URL=aria://launch-gpu) else if /i "%~1"=="gpu-new" (set URL=aria://launch-gpu-new) else if /i "%~1"=="cpu" (set URL=aria://launch-cpu) else (set URL=aria://launch)
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aria_launcher.ps1" "%URL%"
if errorlevel 1 (echo. & echo ARIA did not start. See logs\launch.log & pause)
