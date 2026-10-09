@echo off
rem Drag an image folder onto this file to open its style map in the browser.
rem Needs style-atlas installed (pip install -e . in the repository folder).
chcp 65001 >nul
if "%~1"=="" (
  echo Drag an image folder onto this file, or run:  style-atlas serve "D:\your\folder"
  pause
  exit /b 1
)
where style-atlas >nul 2>nul
if errorlevel 1 (
  echo style-atlas is not installed. In the repository folder run:  pip install -e .
  pause
  exit /b 1
)
style-atlas serve "%~1" --time name
if errorlevel 1 pause
