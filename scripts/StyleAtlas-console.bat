@echo off
rem Opens a console where the style-atlas command works (the .venv made by setup.bat).
chcp 65001 >nul
set "VENV=%~dp0..\.venv\Scripts"
if not exist "%VENV%\style-atlas.exe" (
  echo 还没安装：请先运行 scripts\setup.bat / style-atlas is not installed yet. Run scripts\setup.bat first.
  pause
  exit /b 1
)
set "PATH=%VENV%;%PATH%"
cd /d "%~dp0.."
echo 这个窗口可以直接用 style-atlas 命令，例如 / style-atlas is ready in this window. Examples:
echo   style-atlas audit "D:\lora\artistX"
echo   style-atlas cluster "D:\lora\artistX" --layout kohya --name artistX --dedupe --export copy
echo   style-atlas --help
echo   style-atlas demo   （生成 72 张示范图并打开网页 / 72 demo images to try in the web app）
echo 中文 Windows 上消息会用中文；英文请先运行 set STYLE_ATLAS_LANG=en / Messages follow the Windows language; set STYLE_ATLAS_LANG=en for English.
echo.
cmd /k
