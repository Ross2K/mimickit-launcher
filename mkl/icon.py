"""Window / taskbar icon. To swap the design, replace assets/icon.png and assets/icon.ico (multi-size) - nothing else.
Windows groups windows on the taskbar by AppUserModelID; without our own ID it shows python.exe's icon.
Start paths (all go through mimickit_launcher.main): MimicKit Launcher.exe, launch.bat, mimickit_launcher.pyw, double-clicked mimickit_launcher.py (own console hidden), shortcuts. Icon paths are relative to this file, never the CWD.
Order matters: prepare_process() before tk.Tk(), apply_icon(root) right after it (see mimickit_launcher.main)."""

import os
import sys

from mimickit_util import log_exc

# relative to this file, never the current folder (the .exe starter / shortcuts may start us from anywhere)
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(APP_DIR, "assets")
ICON_PNG = os.path.join(ASSETS, "icon.png")
ICON_ICO = os.path.join(ASSETS, "icon.ico")
# Taskbar identity. Same rule in tools/make_shortcut.ps1 (Start-menu/Desktop shortcut AppUserModelID): the Z build
# (has launcher_profile.py) gets its own ID so Z and public never share one taskbar button / cached icon.
# 1.0.0: new ID (was "MimicKitLauncher.Launcher") - Windows caches a button's icon per ID, and pins made before the
# shortcut existed had cached python's icon under the old one.
APP_ID = "curelessSky.MimicKitLauncher" + (".Z" if os.path.isfile(os.path.join(APP_DIR, "launcher_profile.py")) else "")
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


DPI_STATE = {"aware": None}


def work_area(root):
    """(x, y, w, h) of the primary screen without the taskbar (Windows); the whole screen elsewhere."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            r = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
                return r.left, r.top, r.right - r.left, r.bottom - r.top
        except Exception as e:
            log_exc("icon: work area", e)
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def prepare_process():
    """Everything that must happen before tk.Tk(): DPI awareness, our taskbar identity (AppUserModelID), and no
    stray console button. Works for every start path: the .exe starter, launch.bat, the .pyw, the .py, shortcuts."""
    DPI_STATE["aware"] = set_dpi_aware()
    set_app_id()
    hide_own_console()


START_LNK = "MimicKit Launcher.lnk"


def _start_menu_lnk():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", START_LNK)


def _shortcut_stamp_path():
    return os.path.join(os.environ.get("APPDATA", ""), "mimickit-launcher", "start_menu_shortcut.json")


def _shortcut_wanted(exe):
    """What the Start-menu shortcut must carry; any change (new app ID, moved folder, other pythonw, new icon)
    means it is recreated."""
    ico_m = int(os.path.getmtime(ICON_ICO)) if os.path.isfile(ICON_ICO) else 0
    return {"app_id": APP_ID, "pythonw": exe, "app_dir": APP_DIR, "icon_mtime": ico_m}


def _pythonw():
    exe = sys.executable
    if exe.lower().endswith("python.exe") and os.path.isfile(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return exe


def ensure_start_menu_shortcut(log=None):
    """Windows only, call from a worker thread. Root cause of 'taskbar still shows Python's icon' (a0.8.0Z): the
    taskbar takes the icon AND the relaunch command of a pinned button from a Start-menu shortcut carrying the same
    AppUserModelID. Without one (user never ran 'Create desktop shortcut.bat', or started via the .exe / launch.bat)
    a pin falls back to pythonw.exe with its icon. So: if the Start-menu shortcut is missing or stale (other app ID,
    folder, pythonw or icon than recorded in the stamp file), (re)create it - Start menu only, no Desktop clutter -
    with our icon + AppUserModelID. Returns a plain-language result or ''."""
    if sys.platform != "win32":
        return ""
    import mimickit_util as U

    lnk = _start_menu_lnk()
    exe = _pythonw()
    want = _shortcut_wanted(exe)
    stamp = _shortcut_stamp_path()
    have = U.load_json_or(stamp, None, "icon: shortcut stamp")
    if os.path.isfile(lnk) and have == want:
        return ""
    ps1 = os.path.join(APP_DIR, "tools", "make_shortcut.ps1")
    if not os.path.isfile(ps1):
        return ""
    try:
        import subprocess

        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Pythonw", exe,
                            "-AppId", APP_ID, "-StartMenuOnly"],
                           capture_output=True, text=True, timeout=60, creationflags=0x08000000)
        msg = (r.stdout + r.stderr).strip()
        if r.returncode:
            log_exc("icon: Start-menu shortcut", RuntimeError(msg[-400:]))
            return "Couldn't create the Start-menu shortcut (taskbar icon may show Python's). Details: " + msg[-200:]
        try:
            U.save_json(stamp, want, backup=False)
        except (OSError, TypeError, ValueError) as e:
            log_exc("icon: shortcut stamp", e)
        return "Updated the Start-menu shortcut so the taskbar shows the launcher icon."
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
    if sys.platform == "win32" and os.path.isfile(ICON_ICO):
        # belt and braces for the taskbar: Tk's iconbitmap may hand Windows a 32 px ICON_BIG that the taskbar
        # (125-200 % scaling) blows up or ignores. Load the .ico at the real system sizes and WM_SETICON them on
        # every top-level wrapper window (root now, each Toplevel when it is mapped).
        try:
            for cls in ("Tk", "Toplevel"):  # class bindings: App's own <Map> bindings can't replace them
                root.bind_class(cls, "<Map>", lambda e: set_native_icons(e.widget), add="+")
        except Exception as e:
            log_exc("icon: native icons", e)
    return done


_HICONS = {}  # (cx, cy) -> HICON, loaded once and never freed (shared by all windows)


def _hicon(cx, cy):
    import ctypes

    if (cx, cy) not in _HICONS:
        u = ctypes.windll.user32
        u.LoadImageW.restype = ctypes.c_void_p
        u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_uint]
        _HICONS[(cx, cy)] = u.LoadImageW(None, ICON_ICO, 1, cx, cy, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
    return _HICONS[(cx, cy)]


def set_native_icons(win):
    """Windows only: WM_SETICON big + small from the multi-size .ico on win's top-level wrapper. No-op elsewhere
    or for non-toplevel widgets; returns True if both were sent."""
    if sys.platform != "win32" or not os.path.isfile(ICON_ICO):
        return False
    try:
        if win.winfo_toplevel() is not win or getattr(win, "_mk_native_icon", False):
            return False
        import ctypes

        u = ctypes.windll.user32
        hwnd = int(win.wm_frame(), 16) or u.GetParent(win.winfo_id())
        if not hwnd:
            return False
        big = _hicon(u.GetSystemMetrics(11), u.GetSystemMetrics(12))  # SM_CXICON / SM_CYICON
        small = _hicon(u.GetSystemMetrics(49), u.GetSystemMetrics(50))  # SM_CXSMICON / SM_CYSMICON
        u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        if big:
            u.SendMessageW(hwnd, 0x80, 1, big)  # WM_SETICON, ICON_BIG
        if small:
            u.SendMessageW(hwnd, 0x80, 0, small)  # ICON_SMALL
        win._mk_native_icon = True
        return bool(big and small)
    except Exception as e:
        log_exc("icon: WM_SETICON", e)
        return False
