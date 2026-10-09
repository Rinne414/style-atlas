@echo off
rem Opens a console where the style-atlas command works (the .venv made by setup.bat).
chcp 65001 >nul
set "VENV=%~dp0..\.venv\Scripts"
if not exist "%VENV%\style-atlas.exe" (
  echo style-atlas is not installed yet. Run scripts\setup.bat first.
  pause
  exit /b 1
)
set "PATH=%VENV%;%PATH%"
cd /d "%~dp0.."
echo style-atlas is ready in this window. Examples:
echo   style-atlas audit "D:\lora\artistX"
echo   style-atlas cluster "D:\lora\artistX" --layout kohya --name artistX --dedupe --export copy
echo   style-atlas --help
echo   python scripts\make_demo_images.py demo_styles   (72 demo images to try)
echo.
cmd /k
