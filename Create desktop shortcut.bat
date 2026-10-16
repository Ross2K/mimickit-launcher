@echo off
rem Double-click: makes a "MimicKit Launcher" shortcut on your Desktop and in the Start menu.
rem It starts the launcher with pythonw.exe (no black console window) and shows the launcher's own icon,
rem also when pinned to the taskbar. Run it again after moving the launcher folder.
cd /d "%~dp0"
setlocal
set "PY=%MIMICKIT_LAUNCHER_PYTHON%"
if defined PY if /i "%PY:~-10%"=="python.exe" if exist "%PY:~0,-10%pythonw.exe" set "PY=%PY:~0,-10%pythonw.exe"
if not defined PY for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY for /f "delims=" %%i in ('where pyw 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
  echo Could not find pythonw.exe. Install Python 3.11 from python.org ^(tick "Add to PATH"^),
  echo or set MIMICKIT_LAUNCHER_PYTHON to your python.exe, then run this again.
  pause
  goto :eof
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\make_shortcut.ps1" -Pythonw "%PY%"
echo.
echo Done. Start the launcher from the new "MimicKit Launcher" shortcut.
if /i not "%~1"=="nopause" pause
