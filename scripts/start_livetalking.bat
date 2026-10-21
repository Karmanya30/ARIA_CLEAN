@echo off
rem Starts the local LiveTalking avatar service (Wav2Lip + Piper, no cloud) on 127.0.0.1:8020. Needs ~1 GB VRAM for Wav2Lip.
rem Knobs (environment variables): LIVETALKING_DIR (default E:\LiveTalking\src), LT_MODEL, LT_AVATAR, LT_VOICE (Piper .onnx),
rem LT_PORT, LT_BATCH, LT_LOGDIR (default logs). Env python: <LIVETALKING_DIR>\..\env\python.exe (E:\LiveTalking\env). Logs: logs\livetalking.out.log / .err.log
setlocal
if not defined LIVETALKING_DIR set LIVETALKING_DIR=E:\LiveTalking\src
if not defined LT_MODEL set LT_MODEL=wav2lip
if not defined LT_AVATAR set LT_AVATAR=wav2lip256_avatar1
if not defined LT_PORT set LT_PORT=8020
if not defined LT_BATCH set LT_BATCH=8
set PY=%LIVETALKING_DIR%\..\env\python.exe
cd /d "%~dp0.."
if not defined LT_VOICE set LT_VOICE=%CD%\models\tts\piper\en_US-kristin-medium.onnx
if not exist "%PY%" (echo LiveTalking python env missing: %PY% & exit /b 2)
if not exist "%LIVETALKING_DIR%\app.py" (echo LiveTalking checkout missing: %LIVETALKING_DIR%\app.py & exit /b 2)
if not exist "%LIVETALKING_DIR%\models\wav2lip.pth" if /i "%LT_MODEL%"=="wav2lip" (echo Wav2Lip weights missing: %LIVETALKING_DIR%\models\wav2lip.pth & exit /b 2)
if not exist "%LIVETALKING_DIR%\data\avatars\%LT_AVATAR%" (echo Avatar missing: %LIVETALKING_DIR%\data\avatars\%LT_AVATAR% & exit /b 2)
if not exist "%LT_VOICE%" (echo Piper voice missing: %LT_VOICE% & exit /b 2)
if not defined LT_LOGDIR set LT_LOGDIR=logs
if not exist "%LT_LOGDIR%" mkdir "%LT_LOGDIR%"
rem a locked log file makes the redirect below fail silently with exit code 0: check first and fail loudly (set LT_LOGDIR to use another folder)
type nul >>"%LT_LOGDIR%\livetalking.out.log" 2>nul || (echo Cannot write %LT_LOGDIR%\livetalking.out.log: another process holds it. Set LT_LOGDIR to another folder. & exit /b 3)
type nul >>"%LT_LOGDIR%\livetalking.err.log" 2>nul || (echo Cannot write %LT_LOGDIR%\livetalking.err.log: another process holds it. Set LT_LOGDIR to another folder. & exit /b 3)
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
"%PY%" -u -m livetalking_adapter.serve %* 1>>"%LT_LOGDIR%\livetalking.out.log" 2>>"%LT_LOGDIR%\livetalking.err.log"
exit /b %ERRORLEVEL%
