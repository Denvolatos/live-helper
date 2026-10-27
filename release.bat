@echo off
rem One-click release: build exe + zip, then compile installer with the version from version.py
rem Close LiveHelper.exe before running (a running app locks dist).
setlocal
if not defined PY set "PY=%USERPROFILE%\miniconda3\envs\livetool\python.exe"
cd /d "%~dp0"
tasklist /FI "IMAGENAME eq LiveHelper.exe" | find /I "LiveHelper.exe" >nul
if not errorlevel 1 (
  echo LiveHelper.exe is running. Close it first.
  exit /b 1
)
call build.bat
if errorlevel 1 exit /b 1
for /f %%v in ('"%PY%" -c "from version import __version__ as v;print(v)"') do set VER=%%v
echo Version %VER%
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /DAppVer=%VER% LiveHelper.iss
endlocal
