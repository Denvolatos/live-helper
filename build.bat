@echo off
rem Build LiveHelper (onedir, windowed) with conda env livetool, then zip it.
setlocal
if not defined PY set "PY=%USERPROFILE%\miniconda3\envs\livetool\python.exe"
cd /d "%~dp0"
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
"%PY%" make_version.py
if errorlevel 1 exit /b 1
"%PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --name LiveHelper ^
  --version-file version_info.txt --icon icon.ico --add-data "icon.ico;." --collect-all customtkinter ^
  --collect-all streamlink --collect-all streamlink_cli ^
  --hidden-import streamlink_cli.main --hidden-import websocket --hidden-import brotli --hidden-import psutil --hidden-import pystray --hidden-import pystray._win32 --collect-submodules streamlink.plugins ^
  --exclude-module matplotlib --exclude-module numpy --exclude-module pandas ^
  app.py
if errorlevel 1 exit /b 1
copy /y LICENSE dist\LiveHelper\ >nul
copy /y THIRD_PARTY_NOTICES.md dist\LiveHelper\ >nul
"%PY%" -c "import shutil;from version import __version__ as v;shutil.make_archive('LiveHelper-v'+v+'-win64','zip','dist','LiveHelper');print('zip ok',v)"
endlocal
