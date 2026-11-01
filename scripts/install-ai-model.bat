@echo off
rem Double-click: trains the crack-detection model from the dataset zip and installs it.
rem Looks for data.zip (or any *crack*.zip / 5y9wdsg2zt*.zip) in Downloads, Desktop and this folder.
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-ai-model.ps1" %*
echo.
pause
