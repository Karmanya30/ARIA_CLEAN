@echo off
rem Double-click to start ARIA (API + web) and open it in Edge. Add "gpu" to also start the lip-sync servers (avatar engine :8010 and the LiveTalking avatar :8020): Launch_ARIA.bat gpu
rem   Switches (environment): ARIA_LIVETALKING=0 skips LiveTalking; ARIA_GPU_AVATARS=both^|engine^|livetalking. See docs\LIVETALKING_LAUNCH.md
rem Progress is shown in this window; a failure shows a message box and is logged in logs\launch.log.
if /i "%~1"=="gpu" (set URL=aria://launch-gpu) else (set URL=aria://launch)
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aria_launcher.ps1" "%URL%"
if errorlevel 1 (echo. & echo ARIA did not start. See logs\launch.log & pause)
