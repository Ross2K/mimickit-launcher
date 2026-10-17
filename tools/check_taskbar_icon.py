"""Taskbar icon diagnostic (Windows). Started by "Check taskbar icon.bat" with the launcher's own pythonw.exe.
Writes taskbar_icon_report.txt next to the launcher: the launch chain (process tree with exe paths), venv redirector
yes/no, Python/Tk versions, the icon file, the Start-menu/Desktop shortcuts (target, icon, AppUserModelID), and for
a small test window opened with the launcher's own startup code - plus every running MimicKit Launcher window - the
AppUserModelID Windows reports, the window-level identity and the WM_GETICON icons. Changes nothing.
Usage: pythonw tools/check_taskbar_icon.py [--out FILE] [--no-window]"""

import datetime, os, platform, subprocess, sys, time

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)
WIN = sys.platform == "win32"
LINES = []


def out(s=""):
    LINES.append(str(s))


def section(t):
    out("")
    out("== " + t)


def safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return "ERROR: %s: %s" % (type(e).__name__, e)


# ---------- processes ----------
def _proc_table():
    """{pid: (ppid, exe name)} via a Toolhelp snapshot."""
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snap = k.CreateToolhelp32Snapshot(2, 0)
    t = {}
    e = PE()
    e.dwSize = ctypes.sizeof(PE)
    ok = k.Process32FirstW(ctypes.c_void_p(snap), ctypes.byref(e))
    while ok:
        t[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
        ok = k.Process32NextW(ctypes.c_void_p(snap), ctypes.byref(e))
    k.CloseHandle(ctypes.c_void_p(snap))
    return t


def _exe_path(pid):
    import ctypes
    from ctypes import wintypes

    k = ctypes.windll.kernel32
    k.OpenProcess.restype = ctypes.c_void_p
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    buf = ctypes.create_unicode_buffer(1024)
    n = wintypes.DWORD(1024)
    ok = k.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(n))
    k.CloseHandle(ctypes.c_void_p(h))
    return buf.value if ok else None


def chain(pid, table=None):
    table = table or _proc_table()
    res, seen = [], set()
    while pid in table and pid not in seen and len(res) < 12:
        seen.add(pid)
        ppid, name = table[pid]
        res.append((pid, name, _exe_path(pid)))
        pid = ppid
    return res


def print_chain(pid, table=None):
    for i, (p, name, path) in enumerate(chain(pid, table)):
        out("  %s%s pid %d  %s" % ("  " * i, "<- " if i else "", p, path or name))


def venv_info():
    base = getattr(sys, "_base_executable", "")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    launcher = os.environ.get("__PYVENV_LAUNCHER__", "")
    return in_venv, base, launcher


# ---------- windows ----------
def icon_size(hicon):
    import ctypes
    from ctypes import wintypes

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", wintypes.BOOL), ("x", wintypes.DWORD), ("y", wintypes.DWORD),
                    ("hbmMask", ctypes.c_void_p), ("hbmColor", ctypes.c_void_p)]

    class BITMAP(ctypes.Structure):
        _fields_ = [("t", ctypes.c_long), ("w", ctypes.c_long), ("h", ctypes.c_long), ("wb", ctypes.c_long),
                    ("pl", ctypes.c_ushort), ("bpp", ctypes.c_ushort), ("bits", ctypes.c_void_p)]

    ii = ICONINFO()
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    u.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(ICONINFO)]
    if not u.GetIconInfo(ctypes.c_void_p(hicon), ctypes.byref(ii)):
        return "?"
    bm = BITMAP()
    g.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    g.GetObjectW(ctypes.c_void_p(ii.hbmColor or ii.hbmMask), ctypes.sizeof(bm), ctypes.byref(bm))
    for b in (ii.hbmMask, ii.hbmColor):
        if b:
            g.DeleteObject(ctypes.c_void_p(b))
    return "%dx%d" % (bm.w, bm.h)


def window_icons(hwnd):
    import ctypes

    u = ctypes.windll.user32
    u.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                      ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
    res = {}
    for name, typ in (("ICON_BIG", 1), ("ICON_SMALL", 0), ("ICON_SMALL2", 2)):
        r = ctypes.c_size_t(0)
        u.SendMessageTimeoutW(ctypes.c_void_p(hwnd), 0x7F, ctypes.c_void_p(typ), None, 2, 2000, ctypes.byref(r))
        res["WM_GETICON " + name] = ("0x%x (%s)" % (r.value, icon_size(r.value))) if r.value else "none"
    f = getattr(u, "GetClassLongPtrW", None) or u.GetClassLongW
    f.restype = ctypes.c_size_t
    f.argtypes = [ctypes.c_void_p, ctypes.c_int]
    for name, idx in (("class HICON", -14), ("class HICONSM", -34)):
        v = f(ctypes.c_void_p(hwnd), idx)
        res[name] = ("0x%x (%s)" % (v, icon_size(v))) if v else "none"
    return res


def describe_window(hwnd, icon):
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    buf = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(ctypes.c_void_p(hwnd), buf, 512)
    cls = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(ctypes.c_void_p(hwnd), cls, 256)
    u.GetWindowLongW.restype = ctypes.c_long
    ex = u.GetWindowLongW(ctypes.c_void_p(hwnd), -20) & 0xFFFFFFFF
    out("  hwnd 0x%x  title %r  class %s  owner pid %d" % (hwnd, buf.value, cls.value, pid.value))
    out("  ex-style 0x%08x  (TOOLWINDOW=%s APPWINDOW=%s)  owner window 0x%x" % (
        ex, bool(ex & 0x80), bool(ex & 0x40000), u.GetWindow(ctypes.c_void_p(hwnd), 4) or 0))
    out("  window-owning process chain:")
    print_chain(pid.value)
    wi = safe(window_icons, hwnd)
    if isinstance(wi, dict):
        for k, v in wi.items():
            out("  %-22s %s" % (k, v))
    else:
        out("  icons: " + wi)
    ident = safe(icon.read_window_identity, hwnd)
    if isinstance(ident, dict):
        for k, v in ident.items():
            out("  window %-28s %s" % (k, v if v is not None else "(not set)"))
    else:
        out("  window identity: " + ident)
    return pid.value


def find_launcher_windows():
    import ctypes

    u = ctypes.windll.user32
    found = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(h, _):
        buf = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(ctypes.c_void_p(h), buf, 512)
        if buf.value.startswith("MimicKit Launcher") and u.IsWindowVisible(ctypes.c_void_p(h)):
            found.append(h)
        return True

    u.EnumWindows(proto(cb), None)
    return found


# ---------- shortcuts / files ----------
def shortcuts():
    ps = r"""
$sh = New-Object -ComObject WScript.Shell; $app = New-Object -ComObject Shell.Application
$dirs = @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'),
          (Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'))
foreach ($d in $dirs) { if (-not (Test-Path $d)) { continue }
  Get-ChildItem -LiteralPath $d -Filter *.lnk | Where-Object { $_.Name -match 'MimicKit|Python|pythonw' } | ForEach-Object {
    $l = $sh.CreateShortcut($_.FullName); $id = ''
    try { $id = $app.NameSpace($d).ParseName($_.Name).ExtendedProperty('System.AppUserModel.ID') } catch {}
    Write-Output ('  ' + $_.FullName); Write-Output ('    target: ' + $l.TargetPath + ' ' + $l.Arguments)
    Write-Output ('    icon:   ' + $l.IconLocation + '   workdir: ' + $l.WorkingDirectory)
    Write-Output ('    AppUserModelID: ' + $(if ($id) { $id } else { '(none)' })) } }
"""
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], capture_output=True,
                       text=True, timeout=60, creationflags=0x08000000)
    return (r.stdout + r.stderr).rstrip() or "  (no MimicKit/Python shortcuts found)"


def assoc():
    import winreg

    res = []
    for ext in (".py", ".pyw"):
        for root, name in ((winreg.HKEY_CURRENT_USER, r"Software\Classes\\" + ext), (winreg.HKEY_CLASSES_ROOT, ext)):
            try:
                with winreg.OpenKey(root, name) as k:
                    res.append("  %s -> %s" % (ext, winreg.QueryValueEx(k, "")[0]))
                    break
            except OSError:
                continue
    return "\n".join(res) or "  (none)"


def ico_sizes(path):
    d = open(path, "rb").read()
    n = int.from_bytes(d[4:6], "little")
    sz = []
    for i in range(n):
        w, h = d[6 + 16 * i] or 256, d[7 + 16 * i] or 256
        off = int.from_bytes(d[6 + 16 * i + 12:6 + 16 * i + 16], "little")
        sz.append("%dx%d%s" % (w, h, " png" if d[off:off + 4] == b"\x89PNG" else ""))
    return ", ".join(sz)


# ---------- main ----------
def main():
    no_window = "--no-window" in sys.argv
    dst = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(APP_DIR, "taskbar_icon_report.txt")
    from mkl import icon

    try:
        from mkl.core import VERSION
    except Exception as e:
        VERSION = "? (%s)" % e
    out("MimicKit Launcher taskbar icon report - %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    out("Launcher %s in %s" % (VERSION, APP_DIR))
    out("Windows %s / Python %s (%s) / %s" % (platform.version(), platform.python_version(), platform.architecture()[0],
                                             sys.executable))
    # app ID before any window (same as the launcher's main())
    if WIN:
        icon.set_dpi_aware()
        ok = icon.set_app_id()
    section("Python / venv")
    in_venv, base, launcher = venv_info()
    out("  sys.executable:        %s" % sys.executable)
    out("  sys._base_executable:  %s" % base)
    out("  running exe (OS):      %s" % (safe(_exe_path, os.getpid()) if WIN else "n/a"))
    out("  sys.prefix / base:     %s / %s" % (sys.prefix, getattr(sys, "base_prefix", "")))
    out("  in a venv:             %s" % in_venv)
    out("  __PYVENV_LAUNCHER__:   %s" % (launcher or "(not set)"))
    section("Launch chain (this diagnostic's process, newest first)")
    redirector = False
    if WIN:
        tab = safe(_proc_table)
        if isinstance(tab, dict):
            ch = chain(os.getpid(), tab)
            print_chain(os.getpid(), tab)
            if len(ch) > 1 and ch[1][2] and ch[0][2]:
                pn = os.path.basename(ch[1][2]).lower()
                redirector = pn in ("python.exe", "pythonw.exe") and os.path.normcase(ch[1][2]) != os.path.normcase(ch[0][2])
        else:
            out("  " + tab)
    out("  venv redirector parent (venv pythonw.exe -> base pythonw.exe): %s" % ("YES" if redirector else "no"))
    section("Tk")
    try:
        import tkinter as tk

        out("  Tcl %s / Tk %s" % (tk.Tcl().eval("info patchlevel"), tk.TkVersion))
    except Exception as e:
        out("  tkinter ERROR: %s" % e)
    section("Icon file")
    out("  app ID used:  %s" % icon.APP_ID)
    out("  .ico:         %s  exists=%s  %s" % (icon.ICON_ICO, os.path.isfile(icon.ICON_ICO),
                                            safe(ico_sizes, icon.ICON_ICO) if os.path.isfile(icon.ICON_ICO) else ""))
    out("  .png:         %s  exists=%s" % (icon.ICON_PNG, os.path.isfile(icon.ICON_PNG)))
    out("  relaunch:     %s" % icon.relaunch_command())
    if WIN:
        section("AppUserModelID of this process (GetCurrentProcessExplicitAppUserModelID)")
        out("  set_app_id() returned %s; Windows reports: %s" % (ok, safe(icon.get_process_app_id)))
        if not no_window:
            section("Test window (launcher startup code: app ID, icon, window identity), after 2.5 s")
            try:
                import tkinter as tk

                root = tk.Tk()
                root.withdraw()
                root.title("MimicKit Launcher taskbar test")
                icon.apply_icon(root)
                tk.Label(root, text="Taskbar icon check - look at the taskbar button.\nThis closes by itself.",
                         padx=30, pady=20).pack()
                root.deiconify()
                t0 = time.time()
                while time.time() - t0 < 2.5:
                    root.update()
                    time.sleep(0.05)
                out("  identity state: %s" % icon.IDENTITY_STATE)
                describe_window(icon._toplevel_hwnd(root), icon)
                out("  process app ID now: %s" % safe(icon.get_process_app_id))
                root.destroy()
            except Exception as e:
                out("  ERROR: %s: %s" % (type(e).__name__, e))
        section("Running MimicKit Launcher windows")
        hw = safe(find_launcher_windows)
        if isinstance(hw, list) and hw:
            for h in hw:
                safe(describe_window, h, icon)
                out("")
        else:
            out("  %s" % (hw if not isinstance(hw, list) else "(none running - start the launcher, then run this again)"))
        section("Shortcuts (Start menu, Desktop, pinned taskbar)")
        out(safe(shortcuts))
        section(".py / .pyw file association")
        out(safe(assoc))
    else:
        out("(not Windows: only the basics above)")
    section("How to read this")
    out("  Good: the launcher window lists 'window ID %s' and 'window RelaunchIconResource ...icon.ico,0'," % icon.APP_ID)
    out("  WM_GETICON shows icons, and the Start-menu shortcut has the same AppUserModelID.")
    out("  'window ID (not set)' on a running launcher = it is an older version or the identity call failed.")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")
    print("wrote " + dst)
    return dst


if __name__ == "__main__":
    main()
