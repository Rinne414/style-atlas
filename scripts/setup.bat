@echo off
rem One-time setup for Windows: creates .venv in this folder, installs torch (CUDA if an
rem NVIDIA GPU is found, else CPU) and style-atlas. Safe to run again.
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo 需要 Python 3.10 以上：https://www.python.org/downloads/ （安装时勾选 "Add python.exe to PATH"）
  echo Python 3.10 or newer is required: https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  echo 也可以在这个窗口安装 / Or install it from this window:  winget install -e --id Python.Python.3.12
  echo 装好后开一个新窗口，再运行一次 setup.bat / Then open a new window and run setup.bat again.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo 需要 Python 3.10 以上，目前是 / Python 3.10 or newer is required. Found:
  %PY% --version
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo 创建 .venv / Creating .venv ...
  %PY% -m venv .venv
  if errorlevel 1 ( pause & exit /b 1 )
)
set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip
where nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo 没有找到 NVIDIA 显卡：安装 CPU 版 torch（约 200 MB，较慢但可用）
  echo No NVIDIA GPU found: installing CPU torch ^(about 200 MB; slower, still works^).
  "%VPY%" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
) else (
  rem a CPU build installed earlier counts as installed for pip: check, then swap it
  "%VPY%" -c "import torch, sys; sys.exit(0 if torch.version.cuda else 1)" >nul 2>nul
  if errorlevel 1 (
    echo 找到 NVIDIA 显卡：安装 CUDA 版 torch（约 2.5 GB，请稍候）
    echo NVIDIA GPU found: installing CUDA torch ^(about 2.5 GB download, please wait^).
    "%VPY%" -m pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128
  ) else (
    echo 已经是 CUDA 版 torch / CUDA torch is already installed.
  )
)
if errorlevel 1 ( echo torch 安装失败 / torch install failed. & pause & exit /b 1 )
"%VPY%" -m pip install -e .[app]
if errorlevel 1 ( echo style-atlas 安装失败 / style-atlas install failed. & pause & exit /b 1 )
echo.
".venv\Scripts\style-atlas.exe" doctor
echo.
"%VPY%" -m styleatlas.desktop --shortcut
if errorlevel 1 echo 没能在桌面创建快捷方式；可以直接运行 .venv\Scripts\style-atlas-app.exe / Could not make the desktop shortcut; run .venv\Scripts\style-atlas-app.exe instead.
echo.
echo 完成。双击桌面上的“Style Atlas”就会打开程序，在里面选文件夹。
echo Done. Double-click "Style Atlas" on the desktop to open the program, then pick a folder.
echo 也可以照旧把图片文件夹拖到 scripts\StyleAtlas.bat 上，在浏览器打开。
echo Or drag an image folder onto scripts\StyleAtlas.bat to open it in the browser, as before.
echo 要用 audit、cluster 等命令，请开 scripts\StyleAtlas-console.bat。
echo For commands such as audit or cluster, open scripts\StyleAtlas-console.bat.
echo 第一次分析会下载一次 CSD 模型（2.4 GB）/ The first run downloads the CSD model ^(2.4 GB^) once.
pause
