@echo off
rem Starts the webcam for StructuraSense: registers it the first time, then just runs it.
rem Keep this window open while you want the live view and crack checks. Ctrl+C stops it.
rem Options: start-camera.bat --source 0   (use camera 0 instead of the auto pick)
cd /d "%~dp0..\backend"
if not exist ".venv\Scripts\python.exe" (
  echo backend\.venv is missing - run scripts\dev.ps1 once first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m edge.camera_agent --auto %*
pause
