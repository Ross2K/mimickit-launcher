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
# shortcut existed had cached python's icon under the old one. Unreleased: owner prefix changed to Ross2K (GitHub
# owner rename); icon.py re-creates the Start-menu shortcut when the ID changes, pinned buttons must be re-pinned.
APP_ID = "Ross2K.MimicKitLauncher" + (".Z" if os.path.isfile(os.path.join(APP_DIR, "launcher_profile.py")) else "")
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
            # class bindings: App's own <Map> bindings can't replace them. The main window (class Tk) also gets the
            # window-level taskbar identity (the real 1.0.1 fix, see set_window_identity).
            root.bind_class("Toplevel", "<Map>", lambda e: set_native_icons(e.widget), add="+")
            root.bind_class("Tk", "<Map>", lambda e: (set_native_icons(e.widget), set_window_identity(e.widget)),
                            add="+")
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
        if win.winfo_toplevel() is not win:
            return False
        import ctypes

        u = ctypes.windll.user32
        hwnd = _toplevel_hwnd(win)
        if not hwnd or getattr(win, "_mk_native_icon", None) == hwnd:
            return False
        big = _hicon(u.GetSystemMetrics(11), u.GetSystemMetrics(12))  # SM_CXICON / SM_CYICON
        small = _hicon(u.GetSystemMetrics(49), u.GetSystemMetrics(50))  # SM_CXSMICON / SM_CYSMICON
        u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        if big:
            u.SendMessageW(hwnd, 0x80, 1, big)  # WM_SETICON, ICON_BIG
        if small:
            u.SendMessageW(hwnd, 0x80, 0, small)  # ICON_SMALL
        win._mk_native_icon = hwnd
        return bool(big and small)
    except Exception as e:
        log_exc("icon: WM_SETICON", e)
        return False


# ---- 1.0.1: window-level taskbar identity -------------------------------------------------------------------------
# Root cause of "the running window shows the Python FILE icon on the taskbar" (all versions up to 1.0.0): once a
# process has an explicit AppUserModelID, the taskbar no longer uses the window's own icon (so iconphoto / iconbitmap
# / WM_SETICON never mattered). It looks for a Start-menu shortcut with the same ID and takes ITS icon; with no
# matching shortcut it builds the button from the process command line - pythonw.exe "...\mimickit_launcher.py" -
# and shows the .py file-type icon. The matching shortcut was never reliable: the PowerShell step that writes the ID
# into the .lnk could fail silently, it runs in a background thread AFTER the window is already on the taskbar, and
# a start through MimicKit Launcher.exe -> venv pythonw.exe (a redirector that runs the base pythonw.exe as a child)
# never involves the shortcut at all. Fix: put the identity ON THE WINDOW (SHGetPropertyStoreForWindow): the
# AppUserModelID plus RelaunchIconResource (our .ico), RelaunchCommand and RelaunchDisplayNameResource. Windows
# documents these as the source of the taskbar button's icon/name when no shortcut supplies them, they are read from
# the window itself (so the redirector / start path doesn't matter), and setting the ID makes the taskbar refresh.

_PKEY_FMTID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
PKEY_PIDS = {"RelaunchCommand": 2, "RelaunchIconResource": 3, "RelaunchDisplayNameResource": 4, "ID": 5}
IDENTITY_STATE = {"window": None, "error": ""}  # what set_window_identity did (logged + shown by the diagnostic)


def relaunch_command():
    """Command the taskbar would use to start us again: the starter .exe (carries our icon) if present, else
    pythonw.exe + the script."""
    exe = os.path.join(APP_DIR, "MimicKit Launcher.exe")
    if os.path.isfile(exe):
        return '"%s"' % exe
    py = sys.executable or "pythonw.exe"
    if py.lower().endswith("python.exe") and os.path.isfile(py[:-10] + "pythonw.exe"):
        py = py[:-10] + "pythonw.exe"
    return '"%s" "%s"' % (py, os.path.join(APP_DIR, "mimickit_launcher.py"))


def window_identity_values():
    return {"RelaunchCommand": relaunch_command(), "RelaunchIconResource": ICON_ICO + ",0",
            "RelaunchDisplayNameResource": "MimicKit Launcher", "ID": APP_ID}


def _win_ps_api():
    """ctypes plumbing for a window's IPropertyStore (Windows only)."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):  # 24 bytes on x64 / 16 on x86; we only use vt + the string pointer
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                    ("p", ctypes.c_void_p), ("pad", ctypes.c_void_p)]

    ole32 = ctypes.windll.ole32

    def guid(s):
        g = GUID()
        ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
        return g

    def store(hwnd):
        ole32.CoInitialize(None)  # S_FALSE if already initialised on this thread: fine
        iid = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")  # IID_IPropertyStore
        ps = ctypes.c_void_p()
        f = ctypes.windll.shell32.SHGetPropertyStoreForWindow
        f.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        f.restype = ctypes.c_long
        hr = f(hwnd, ctypes.byref(iid), ctypes.byref(ps))
        if hr != 0 or not ps:
            raise OSError("SHGetPropertyStoreForWindow HRESULT 0x%08x" % (hr & 0xFFFFFFFF))
        return ps

    def method(ps, idx, *argtypes):
        vtbl = ctypes.cast(ps, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[idx])

    def key(name):
        return PROPERTYKEY(guid(_PKEY_FMTID), PKEY_PIDS[name])

    return ctypes, PROPERTYKEY, PROPVARIANT, store, method, key


def _toplevel_hwnd(win):
    import ctypes

    return int(win.wm_frame(), 16) or ctypes.windll.user32.GetParent(win.winfo_id())


def set_window_identity(win, hwnd=None):
    """Windows only: AppUserModelID + relaunch icon/command/name on the main window's property store (relaunch
    properties first, the ID last - setting the ID makes the taskbar re-read the button). Once per window.
    Returns True on success; the outcome is kept in IDENTITY_STATE."""
    if sys.platform != "win32":
        return False
    try:
        if hwnd is None:
            if win.winfo_toplevel() is not win:
                return False
            hwnd = _toplevel_hwnd(win)
            if getattr(win, "_mk_identity", None) == hwnd:
                return False  # already on this wrapper (Tk can recreate the wrapper window: then we set it again)
        ctypes, PROPERTYKEY, PROPVARIANT, store, method, key = _win_ps_api()
        ps = store(hwnd)
        try:
            set_value = method(ps, 6, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))
            commit = method(ps, 7)
            vals = window_identity_values()
            for name in ("RelaunchCommand", "RelaunchIconResource", "RelaunchDisplayNameResource", "ID"):
                buf = ctypes.create_unicode_buffer(vals[name])  # SetValue copies the string
                pv = PROPVARIANT(31, 0, 0, 0, ctypes.cast(buf, ctypes.c_void_p).value, None)  # VT_LPWSTR
                k = key(name)
                hr = set_value(ps, ctypes.byref(k), ctypes.byref(pv))
                if hr != 0:
                    raise OSError("SetValue(%s) HRESULT 0x%08x" % (name, hr & 0xFFFFFFFF))
            commit(ps)
        finally:
            method(ps, 2)(ps)  # Release
        if win is not None:
            win._mk_identity = hwnd
        IDENTITY_STATE.update(window=hex(hwnd), error="")
        return True
    except Exception as e:
        IDENTITY_STATE.update(window=None, error=str(e))
        log_exc("icon: window AppUserModelID", e)
        return False


def read_window_identity(hwnd):
    """Windows only: {property: value or None} from any window's property store (also another process's)."""
    out = {}
    ctypes, PROPERTYKEY, PROPVARIANT, store, method, key = _win_ps_api()
    ps = store(hwnd)
    try:
        get_value = method(ps, 5, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))
        for name in PKEY_PIDS:
            pv = PROPVARIANT()
            k = key(name)
            if get_value(ps, ctypes.byref(k), ctypes.byref(pv)) == 0 and pv.vt == 31 and pv.p:
                out[name] = ctypes.wstring_at(pv.p)
            else:
                out[name] = None
            ctypes.windll.ole32.PropVariantClear(ctypes.byref(pv))
    finally:
        method(ps, 2)(ps)
    return out


def get_process_app_id():
    """Windows only: this process's explicit AppUserModelID as Windows has it (None if not set)."""
    if sys.platform != "win32":
        return None
    import ctypes

    p = ctypes.c_wchar_p()
    f = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID
    f.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
    f.restype = ctypes.c_long
    if f(ctypes.byref(p)) != 0:
        return None
    v = p.value
    ctypes.windll.ole32.CoTaskMemFree(p)
    return v


def identity_log_line():
    """One [gui] line for the log panel: what the taskbar sees (Windows)."""
    try:
        pid = get_process_app_id()
    except Exception as e:
        pid = "error: %s" % e
    st = IDENTITY_STATE
    win = ("set on window %s" % st["window"]) if st["window"] else ("NOT set (%s)" % (st["error"] or "not mapped yet"))
    return "[gui] taskbar: app ID %s (process: %s), window identity %s, icon %s%s\n" % (
        APP_ID, pid, win, ICON_ICO, "" if os.path.isfile(ICON_ICO) else " (MISSING)")
