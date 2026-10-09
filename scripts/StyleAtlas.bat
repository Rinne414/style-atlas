@echo off
rem Drag an image folder onto this file to open its style map in the browser.
rem Run scripts\setup.bat once first (or install style-atlas yourself).
chcp 65001 >nul
if "%~1"=="" (
  echo Drag an image folder onto this file, or run:  style-atlas serve "D:\your\folder"
  pause
  exit /b 1
)
set "SA=%~dp0..\.venv\Scripts\style-atlas.exe"
if not exist "%SA%" set "SA=style-atlas"
if "%SA%"=="style-atlas" (
  where style-atlas >nul 2>nul
  if errorlevel 1 (
    echo style-atlas is not installed yet. Run scripts\setup.bat first.
    pause
    exit /b 1
  )
)
"%SA%" serve "%~1" --time name
if errorlevel 1 pause
