@echo off
rem Starts the MuseTalk lip-sync server for ARIA's Live Avatar on port 8010 (about 3 minutes the first time, ~25 s after).
rem Set MUSETALK_DIR first if MuseTalk is not in E:\musetalk\MuseTalk; its Python environment is expected next to it in ..\env.
if not defined MUSETALK_DIR set MUSETALK_DIR=E:\musetalk\MuseTalk
set PYTHONIOENCODING=utf-8
"%MUSETALK_DIR%\..\env\python.exe" -u "%~dp0musetalk_server.py" --source "%~dp0..\interface\avatar\office-wide-glasses.webp" --source-video "%~dp0..\interface\avatar\presenter-lipsync.mp4" --port 8010 %*
