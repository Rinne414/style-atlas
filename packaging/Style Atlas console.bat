@echo off
rem A console where the style-atlas command works, using this folder's own Python.
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0python\style-atlas-env.json" (
  echo 请先双击 "Style Atlas.bat"，让它装好需要的组件。
  echo Double-click "Style Atlas.bat" first, so it can install what the program needs.
  pause
  exit /b 1
)
set "PYTHONPATH=%~dp0app"
doskey style-atlas="%~dp0python\python.exe" -m styleatlas $*
echo 输入 style-atlas --help 查看所有命令，例如：style-atlas audit "D:\lora\artistX"
echo Type style-atlas --help for the commands, e.g.: style-atlas audit "D:\lora\artistX"
cmd /k
