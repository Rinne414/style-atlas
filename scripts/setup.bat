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
  echo 需要 Python 3.10 以上：https://www.python.org/downloads/ （安裝時勾選 "Add python.exe to PATH"）
  echo Python 3.10 or newer is required: https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  echo 也可以在這個視窗安裝 / Or install it from this window:  winget install -e --id Python.Python.3.12
  echo 裝好後開一個新視窗，再執行一次 setup.bat / Then open a new window and run setup.bat again.
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
  echo 建立 .venv / Creating .venv ...
  %PY% -m venv .venv
  if errorlevel 1 ( pause & exit /b 1 )
)
set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip
where nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo 沒有找到 NVIDIA 顯卡：安裝 CPU 版 torch（約 200 MB，較慢但可用）
  echo No NVIDIA GPU found: installing CPU torch ^(about 200 MB; slower, still works^).
  "%VPY%" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
) else (
  rem a CPU build installed earlier counts as installed for pip: check, then swap it
  "%VPY%" -c "import torch, sys; sys.exit(0 if torch.version.cuda else 1)" >nul 2>nul
  if errorlevel 1 (
    echo 找到 NVIDIA 顯卡：安裝 CUDA 版 torch（約 2.5 GB，請稍候）
    echo NVIDIA GPU found: installing CUDA torch ^(about 2.5 GB download, please wait^).
    "%VPY%" -m pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128
  ) else (
    echo 已經是 CUDA 版 torch / CUDA torch is already installed.
  )
)
if errorlevel 1 ( echo torch 安裝失敗 / torch install failed. & pause & exit /b 1 )
"%VPY%" -m pip install -e .
if errorlevel 1 ( echo style-atlas 安裝失敗 / style-atlas install failed. & pause & exit /b 1 )
echo.
".venv\Scripts\style-atlas.exe" doctor
echo.
echo 完成。把圖片資料夾拖到 scripts\StyleAtlas.bat 上，就會打開它的畫風地圖。
echo Done. Drag an image folder onto scripts\StyleAtlas.bat to open its style map.
echo 要用 audit、cluster 等指令，請開 scripts\StyleAtlas-console.bat。
echo For commands such as audit or cluster, open scripts\StyleAtlas-console.bat.
echo 第一次分析會下載一次 CSD 模型（2.4 GB）/ The first run downloads the CSD model ^(2.4 GB^) once.
pause
