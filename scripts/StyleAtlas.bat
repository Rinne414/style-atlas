@echo off
rem Drag an image folder onto this file, or double-click it and pick one, to open the
rem folder's style map in the browser. Run scripts\setup.bat once first.
chcp 65001 >nul
set "FOLDER=%~1"
if not defined FOLDER call :pick
if not defined FOLDER (
  echo 沒有選資料夾。如果沒有跳出選擇視窗，請把圖片資料夾拖到這個檔案上。
  echo No folder chosen. If no window opened, drag the image folder onto this file instead,
  echo or run:  style-atlas serve "D:\your\folder"
  pause
  exit /b 1
)
if "%FOLDER:~-1%"=="\" set "FOLDER=%FOLDER%."
set "SA=%~dp0..\.venv\Scripts\style-atlas.exe"
if not exist "%SA%" set "SA=style-atlas"
if "%SA%"=="style-atlas" (
  where style-atlas >nul 2>nul
  if errorlevel 1 (
    echo 還沒安裝：請先執行 scripts\setup.bat / style-atlas is not installed yet. Run scripts\setup.bat first.
    pause
    exit /b 1
  )
)
"%SA%" serve "%FOLDER%" --time name
if errorlevel 1 pause
exit /b

:pick
for /f "usebackq delims=" %%F in (`powershell -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0pick_folder.ps1"`) do set "FOLDER=%%F"
exit /b
