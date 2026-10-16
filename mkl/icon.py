"""Window / taskbar icon. To swap the design, replace assets/icon.png and assets/icon.ico (multi-size) - nothing else.
Windows groups windows on the taskbar by AppUserModelID; without our own ID it shows python.exe's icon.
Start paths (all go through mimickit_launcher.main): MimicKit Launcher.exe, launch.bat, mimickit_launcher.pyw, double-clicked mimickit_launcher.py (own console hidden), shortcuts. Icon paths are relative to this file, never the CWD.
Order matters: prepare_process() before tk.Tk(), apply_icon(root) right after it (see mimickit_launcher.main)."""

import os
import sys

from mimickit_util import log_exc

# relative to this file, never the current folder (the .exe starter / shortcuts may start us from anywhere)
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
ICON_PNG = os.path.join(ASSETS, "icon.png")
ICON_ICO = os.path.join(ASSETS, "icon.ico")
APP_ID = "MimicKitLauncher.Launcher"
PHOTO_SIZES = (16, 32, 48, 256)  # Windows takes ICON_SMALL / ICON_BIG from these


def set_app_id(app_id=APP_ID):
    """Windows only; call before the first Tk window is created. Returns True if set."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        f = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        f.argtypes = [ctypes.c_wchar_p]
        f.restype = ctypes.c_long  # HRESULT
        hr = f(app_id)
        if hr != 0:
            log_exc("icon: SetCurrentProcessExplicitAppUserModelID", OSError("HRESULT 0x%08x" % (hr & 0xFFFFFFFF)))
        return hr == 0
    except Exception as e:
        log_exc("icon: SetCurrentProcessExplicitAppUserModelID", e)
        return False


def set_dpi_aware():
    """Windows only: per-monitor DPI awareness (sharp text, real monitor coordinates for pop-up placement)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        try:
            return ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0  # Windows 8.1+
        except (AttributeError, OSError):
            return bool(ctypes.windll.user32.SetProcessDPIAware())  # Vista+
    except Exception:
        return False


def hide_own_console():
    """Windows: double-clicking mimickit_launcher.py starts python.exe with a NEW console window - that console is a
    second taskbar button with Python's icon (what the user saw). Hide it, but only if the console belongs to us
    alone (GetConsoleProcessList == 1); a console the user opened himself (cmd, launch.bat fallback) stays."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        k = ctypes.windll.kernel32
        hwnd = k.GetConsoleWindow()
        if not hwnd:
            return False  # pythonw.exe / the .exe starter: no console at all
        arr = (ctypes.c_uint * 4)()
        if k.GetConsoleProcessList(arr, 4) != 1:
            return False
        ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
        return True
    except Exception as e:
        log_exc("icon: hide console", e)
        return False


def prepare_process():
    """Everything that must happen before tk.Tk(): DPI awareness, our taskbar identity (AppUserModelID), and no
    stray console button. Works for every start path: the .exe starter, launch.bat, the .pyw, the .py, shortcuts."""
    set_dpi_aware()
    set_app_id()
    hide_own_console()


START_LNK = "MimicKit Launcher.lnk"


def _start_menu_lnk():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", START_LNK)


def ensure_start_menu_shortcut(log=None):
    """Windows only, call from a worker thread. Root cause of 'taskbar still shows Python's icon' (a0.8.0Z): the
    taskbar takes the icon AND the relaunch command of a pinned button from a Start-menu shortcut carrying the same
    AppUserModelID. Without one (user never ran 'Create desktop shortcut.bat', or started via the .exe / launch.bat)
    a pin falls back to pythonw.exe with its icon. So: if the Start-menu shortcut is missing, (re)create it - Start
    menu only, no Desktop clutter - with our icon + AppUserModelID. Returns a plain-language result or ''."""
    if sys.platform != "win32":
        return ""
    lnk = _start_menu_lnk()
    if os.path.isfile(lnk) and os.path.getmtime(lnk) >= os.path.getmtime(ICON_ICO if os.path.isfile(ICON_ICO) else lnk):
        return ""
    exe = sys.executable
    if exe.lower().endswith("python.exe") and os.path.isfile(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    ps1 = os.path.join(os.path.dirname(ASSETS), "tools", "make_shortcut.ps1")
    if not os.path.isfile(ps1):
        return ""
    try:
        import subprocess

        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Pythonw", exe,
                            "-StartMenuOnly"], capture_output=True, text=True, timeout=60, creationflags=0x08000000)
        msg = (r.stdout + r.stderr).strip()
        if r.returncode:
            log_exc("icon: Start-menu shortcut", RuntimeError(msg[-400:]))
            return "Couldn't create the Start-menu shortcut (taskbar icon may show Python's). Details: " + msg[-200:]
        return "Created the Start-menu shortcut so the taskbar shows the launcher icon."
    except Exception as e:
        log_exc("icon: Start-menu shortcut", e)
        return "Couldn't create the Start-menu shortcut: %s" % e


def apply_icon(root):
    """Set the icon of root and (default) every later Toplevel. Each step is independent, so one failing (old Tk,
    missing file) doesn't skip the others. Returns True if at least one icon was set."""
    done = False
    if os.path.isfile(ICON_PNG):
        try:
            import tkinter as tk

            full = tk.PhotoImage(master=root, file=ICON_PNG)
            imgs = [full.subsample(max(1, full.width() // s)) for s in PHOTO_SIZES[:-1]] + [full]
            root._icon_imgs = imgs  # keep references or Tk drops the images
            root._icon_img = full
            root.iconphoto(True, *reversed(imgs))  # largest first
            done = True
        except Exception as e:
            log_exc("icon: iconphoto", e)
    # .ico LAST on Windows: its real 16/24/32/48/256 entries win over the scaled PNGs (taskbar, Alt-Tab)
    if sys.platform == "win32" and os.path.isfile(ICON_ICO):
        try:
            root.iconbitmap(default=ICON_ICO)  # .ico (BMP entries, 16-256 px): Windows picks the size per place
            done = True
        except Exception as e:
            log_exc("icon: iconbitmap", e)
    return done
