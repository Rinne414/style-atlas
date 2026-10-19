@echo off
rem Double-click to try style-atlas without your own images: makes 72 demo images in four
rem procedural styles (no one's artwork) and opens their style map in the browser.
rem Run scripts\setup.bat once first.
chcp 65001 >nul
set "SA=%~dp0..\.venv\Scripts\style-atlas.exe"
if not exist "%SA%" set "SA=style-atlas"
if "%SA%"=="style-atlas" (
  where style-atlas >nul 2>nul
  if errorlevel 1 (
    echo 还没安装：请先运行 scripts\setup.bat / style-atlas is not installed yet. Run scripts\setup.bat first.
    pause
    exit /b 1
  )
)
"%SA%" demo
if errorlevel 1 pause
exit /b
