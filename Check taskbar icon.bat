@echo off
rem Double-click if the taskbar button shows the wrong icon. Changes nothing: it opens a small test window for
rem 3 seconds (look at its taskbar button) and writes taskbar_icon_report.txt in this folder - send that file.
rem Tip: start the launcher first, so the report also covers the running launcher window.
cd /d "%~dp0"
setlocal
set "PY="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\find_launcher_python.ps1"`) do if not defined PY set "PY=%%i"
if not defined PY (
  echo Could not find the launcher's Python ^(pythonw.exe^). Set MIMICKIT_LAUNCHER_PYTHON or start the launcher once.
  pause
  goto :eof
)
echo Using %PY%
if exist "taskbar_icon_report.txt" del "taskbar_icon_report.txt"
start "" /wait "%PY%" "%~dp0tools\check_taskbar_icon.py"
if not exist "taskbar_icon_report.txt" (
  echo No report was written. Trying again with console output:
  "%PY:pythonw.exe=python.exe%" "%~dp0tools\check_taskbar_icon.py"
)
if exist "taskbar_icon_report.txt" (
  echo Wrote %~dp0taskbar_icon_report.txt
  start "" notepad "%~dp0taskbar_icon_report.txt"
)
pause
