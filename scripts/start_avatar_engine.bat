@echo off
rem Starts ARIA's local talking-avatar engine (MuseTalk 1.5 + Piper, no cloud) on port 8010. About 40 s to load and warm up.
rem Needs the MuseTalk checkout with its python environment next to it in ..\env (same layout as start_musetalk.bat).
rem Set MUSETALK_DIR if MuseTalk is not in E:\MuseTalk\MuseTalk.
rem Knobs (environment variables): AVATAR_PORT, AVATAR_VOICE, AVATAR_MOUTH_FPS, AVATAR_VAE (half|full|taesd), AVATAR_W/H, AVATAR_BACKEND=fake (no GPU).
if not defined MUSETALK_DIR set MUSETALK_DIR=E:\MuseTalk\MuseTalk
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
cd /d "%~dp0.."
"%MUSETALK_DIR%\..\env\python.exe" -u -m avatar_engine.server %*
