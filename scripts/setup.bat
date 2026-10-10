@echo off
rem One-time setup for Windows: creates .venv in this folder, installs torch (CUDA if an
rem NVIDIA GPU is found, else CPU) and style-atlas. Safe to run again.
setlocal
cd /d "%~dp0.."
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python 3.10 or newer is required: https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  echo Or install it from this window with:  winget install -e --id Python.Python.3.12
  echo Then open a new window and run setup.bat again.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo Python 3.10 or newer is required. Found:
  %PY% --version
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv ...
  %PY% -m venv .venv
  if errorlevel 1 ( pause & exit /b 1 )
)
set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip
where nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo No NVIDIA GPU found: installing CPU torch ^(about 200 MB; slower, still works^).
  "%VPY%" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
) else (
  echo NVIDIA GPU found: installing CUDA torch ^(about 2.5 GB download, please wait^).
  "%VPY%" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
)
if errorlevel 1 ( echo torch install failed. & pause & exit /b 1 )
"%VPY%" -m pip install -e .
if errorlevel 1 ( echo style-atlas install failed. & pause & exit /b 1 )
echo.
".venv\Scripts\style-atlas.exe" doctor
echo.
echo Done. Drag an image folder onto scripts\StyleAtlas.bat to open its style map.
echo For commands such as audit or cluster, open scripts\StyleAtlas-console.bat.
echo The first run downloads the CSD model ^(2.4 GB^) once.
pause
