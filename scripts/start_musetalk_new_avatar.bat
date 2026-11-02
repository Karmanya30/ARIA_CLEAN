@echo off
rem Starts the MuseTalk lip-sync server for the "New ARIA Avatar" (the video presenter) on port 8011, so it can run next to or
rem instead of the original avatar's server on 8010 (the first start prepares the video: a few minutes, then it is cached).
if not defined MUSETALK_DIR set MUSETALK_DIR=E:\musetalk\MuseTalk
set PYTHONIOENCODING=utf-8
"%MUSETALK_DIR%\..\env\python.exe" -u "%~dp0musetalk_server.py" --source "%~dp0..\interface\avatar\presenter-lipsync.mp4" --port 8011 %*
