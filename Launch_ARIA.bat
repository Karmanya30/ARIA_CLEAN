@echo off
rem Double-click to start ARIA (API + web) and open it in Edge. Add "gpu" to also start the lip-sync server: Launch_ARIA.bat gpu
if /i "%~1"=="gpu" (set URL=aria://launch-gpu) else (set URL=aria://launch)
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\aria_launcher.ps1" "%URL%"
