@echo off
rem Double-click once if the taskbar still shows Python's icon instead of the launcher's.
rem 1) Recreates the "MimicKit Launcher" shortcuts (Desktop + Start menu) with the launcher icon and taskbar ID.
rem 2) Refreshes Windows' icon cache.
rem Afterwards: right-click the old MimicKit/Python button on the taskbar - "Unpin from taskbar", start the
rem launcher from the new shortcut, then right-click its taskbar button - "Pin to taskbar".
cd /d "%~dp0"
call "%~dp0Create desktop shortcut.bat" nopause
ie4uinit.exe -show >nul 2>nul
ie4uinit.exe -ClearIconCache >nul 2>nul
echo.
echo Done. Now unpin the old taskbar button (right-click - Unpin from taskbar),
echo start the launcher from the new shortcut and pin it again (right-click - Pin to taskbar).
pause
