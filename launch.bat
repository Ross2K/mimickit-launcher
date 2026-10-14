@echo off
rem MimicKit Launcher - Windows starter. Uses any Python that has tkinter + matplotlib
rem (your MimicKit venv works). Set MIMICKIT_LAUNCHER_PYTHON to force a specific python.exe / pythonw.exe.
rem Always starts pythonw.exe when it can: python.exe opens an extra console window, and that console (not the
rem launcher) is what Windows then shows on the taskbar, with python's icon.
cd /d "%~dp0"
setlocal
set "PY=%MIMICKIT_LAUNCHER_PYTHON%"
if defined PY if /i "%PY:~-10%"=="python.exe" if exist "%PY:~0,-10%pythonw.exe" set "PY=%PY:~0,-10%pythonw.exe"
if defined PY ( start "" "%PY%" "%~dp0mimickit_launcher.py" & goto :eof )
where pyw >nul 2>nul && ( start "" pyw -3 "%~dp0mimickit_launcher.py" & goto :eof )
where pythonw >nul 2>nul && ( start "" pythonw "%~dp0mimickit_launcher.py" & goto :eof )
where python >nul 2>nul && ( python "%~dp0mimickit_launcher.py" & goto :eof )
echo Could not find Python. Install Python 3.11 from python.org, or set MIMICKIT_LAUNCHER_PYTHON
echo to the full path of a python.exe (for example your MimicKit venv's Scripts\pythonw.exe).
pause
