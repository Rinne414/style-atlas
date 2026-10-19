@echo off
rem Double-click to start Style Atlas. The first time it installs what it needs (a few minutes).
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0python\python.exe" "%~dp0launch.py" %*
if errorlevel 1 pause
