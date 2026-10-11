@echo off
rem MimicKit Launcher - Windows starter. Uses any Python that has tkinter + matplotlib
rem (your MimicKit venv works). Set MIMICKIT_LAUNCHER_PYTHON to force a specific python.exe.
cd /d "%~dp0"
if defined MIMICKIT_LAUNCHER_PYTHON ( start "" "%MIMICKIT_LAUNCHER_PYTHON%" mimickit_launcher.py & goto :eof )
where pyw >nul 2>nul && ( start "" pyw -3 mimickit_launcher.py & goto :eof )
where pythonw >nul 2>nul && ( start "" pythonw mimickit_launcher.py & goto :eof )
where python >nul 2>nul && ( python mimickit_launcher.py & goto :eof )
echo Could not find Python. Install Python 3.11 from python.org, or set MIMICKIT_LAUNCHER_PYTHON
echo to the full path of a python.exe (for example your MimicKit venv's Scripts\pythonw.exe).
pause
