@echo off
rem Opens a console where the style-atlas command works (the .venv made by setup.bat).
chcp 65001 >nul
set "VENV=%~dp0..\.venv\Scripts"
if not exist "%VENV%\style-atlas.exe" (
  echo 還沒安裝：請先執行 scripts\setup.bat / style-atlas is not installed yet. Run scripts\setup.bat first.
  pause
  exit /b 1
)
set "PATH=%VENV%;%PATH%"
cd /d "%~dp0.."
echo 這個視窗可以直接用 style-atlas 指令，例如 / style-atlas is ready in this window. Examples:
echo   style-atlas audit "D:\lora\artistX"
echo   style-atlas cluster "D:\lora\artistX" --layout kohya --name artistX --dedupe --export copy
echo   style-atlas --help
echo   python scripts\make_demo_images.py demo_styles   （產生 72 張示範圖 / 72 demo images to try）
echo 指令輸出的英文說明：docs\LORA_GUIDE.md 第 7 節 / The output explained in Chinese: docs\LORA_GUIDE.md, section 7
echo.
cmd /k
