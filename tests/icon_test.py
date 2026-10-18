"""Window icon plumbing: assets exist, .ico is multi-size, apply_icon works, set_app_id is a no-op off Windows.
xvfb-run -a python tests/icon_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, sys, tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mkl import icon

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


check("icon.png + icon.ico shipped", os.path.isfile(icon.ICON_PNG) and os.path.isfile(icon.ICON_ICO))
try:
    from PIL import Image

    sizes = Image.open(icon.ICON_ICO).info.get("sizes", set())
    check("ico has 16/32/48/256", {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(sizes), str(sorted(sizes)))
except ImportError:
    n = int.from_bytes(open(icon.ICON_ICO, "rb").read()[4:6], "little")
    check("ico has several sizes", n >= 4, str(n))
check("set_app_id only on Windows", icon.set_app_id() == (sys.platform == "win32"))
root = tk.Tk()
check("apply_icon", icon.apply_icon(root) and root._icon_img.width() == 256)
check("iconphoto gets several sizes (taskbar big + small icon)", len(root._icon_imgs) >= 3)
root.destroy()

# the ico entries must be classic BMP/DIB (Tk's .ico reader); PNG-compressed small sizes can be skipped on Windows
d = open(icon.ICON_ICO, "rb").read()
offs = [int.from_bytes(d[6 + 16 * i + 12 : 6 + 16 * i + 16], "little") for i in range(int.from_bytes(d[4:6], "little"))]
check("ico entries are BMP (not PNG)", all(d[o : o + 4] != b"\x89PNG" for o in offs))
check("asset path independent of the current folder", os.path.isabs(icon.ICON_ICO) and os.path.isfile(icon.ICON_ICO))

# call order (taskbar regression): DPI awareness + AppUserModelID before tk.Tk(), the icon right after it
import mimickit_launcher as L

calls = []
real_tk = L.tk.Tk
orig = (icon.set_dpi_aware, icon.set_app_id, icon.apply_icon, L.App)
icon.set_dpi_aware = lambda: calls.append("dpi")
icon.set_app_id = lambda *a: calls.append("app_id")
icon.apply_icon = lambda r: calls.append("icon")


class FakeRoot:
    def withdraw(self):
        calls.append("withdraw")

    def mainloop(self):
        calls.append("mainloop")


L.tk.Tk = lambda: (calls.append("Tk"), FakeRoot())[1]
L.App = lambda root: (calls.append("App"), icon.apply_icon(root))
try:
    L.main()
finally:
    L.tk.Tk = real_tk
    icon.set_dpi_aware, icon.set_app_id, icon.apply_icon, L.App = orig
check("main(): dpi -> app_id -> Tk -> hidden -> icon -> mainloop", calls == ["dpi", "app_id", "Tk", "withdraw", "App", "icon", "mainloop"], str(calls))
src = open(os.path.join(os.path.dirname(icon.__file__), "..", "mimickit_launcher.py")).read()
check("App applies the icon in __init__", "icon.apply_icon(root)" in src)
bat = open(os.path.join(os.path.dirname(icon.ICON_ICO), "..", "launch.bat")).read()
check("launch.bat prefers pythonw (no console window on the taskbar)", bat.find("pythonw") < bat.find("where python >"))

# 1.0.0 taskbar fix: one app ID shared by the process and the shortcut script; Z gets its own
check("APP_ID is Ross2K.MimicKitLauncher (+.Z in the Z build)", icon.APP_ID == "Ross2K.MimicKitLauncher" + (
    ".Z" if os.path.isfile(os.path.join(icon.APP_DIR, "launcher_profile.py")) else ""), icon.APP_ID)
ps1 = open(os.path.join(icon.APP_DIR, "tools", "make_shortcut.ps1"), encoding="utf-8-sig").read()
check("make_shortcut.ps1 derives the same id", '"Ross2K.MimicKitLauncher"' in ps1 and 'launcher_profile.py' in ps1
      and '+= ".Z"' in ps1 and "MimicKitLauncher.Launcher\"" not in ps1)
isrc = open(icon.__file__).read()
check("Start-menu shortcut gets -AppId APP_ID", '"-AppId", APP_ID' in isrc)
check("shortcut recreated when app id / folder / pythonw changes",
      set(icon._shortcut_wanted("x")) == {"app_id", "pythonw", "app_dir", "icon_mtime"}
      and icon._shortcut_wanted("x")["app_id"] == icon.APP_ID)
# non-Windows: every Windows-only step is a guarded no-op
if sys.platform != "win32":
    check("off Windows: shortcut / native icon / dpi are no-ops",
          icon.ensure_start_menu_shortcut() == "" and icon.set_native_icons(None) is False
          and icon.set_dpi_aware() is False and icon.hide_own_console() is False)
seen = []
real_ip = tk.Wm.iconphoto
tk.Wm.iconphoto = lambda self, default, *imgs: (seen.append((default, [i.width() for i in imgs])), real_ip(self, default, *imgs))
try:
    root = tk.Tk()
    icon.apply_icon(root)
    top = tk.Toplevel(root)
    root.update()
finally:
    tk.Wm.iconphoto = real_ip
check("iconphoto(default=True, 256..16): every later Toplevel gets the icon",
      seen and seen[0][0] is True and seen[0][1][0] == 256 and min(seen[0][1]) <= 16, str(seen))
check("native-icon <Map> hooks only on Windows", bool(root.bind_class("Toplevel", "<Map>")) == (sys.platform == "win32"))
root.destroy()
# the .exe starter only starts pythonw and steps aside: no window of its own (so no own taskbar group) and it never
# waits for the launcher to end; the launcher sets its own AppUserModelID, so the exe's icon resource is Explorer-only
c = open(os.path.join(icon.APP_DIR, "tools", "exe-starter", "launcher.c")).read()
check("exe starter: no window, no AppID of its own, short wait only",
      "CreateWindow" not in c and "AppUserModelID" not in c and "INFINITE" not in c and "CreateProcessW" in c)
pyw = open(os.path.join(icon.APP_DIR, "mimickit_launcher.pyw")).read()
check(".pyw goes through mimickit_launcher.main (same app id + icon)", "mimickit_launcher.main()" in pyw)

# 1.0.1: window-level taskbar identity (the real fix) + the diagnostic
v = icon.window_identity_values()
check("window identity: ID = APP_ID, icon = our .ico, name, start command", v["ID"] == icon.APP_ID
      and v["RelaunchIconResource"] == icon.ICON_ICO + ",0" and v["RelaunchDisplayNameResource"] == "MimicKit Launcher"
      and ("MimicKit Launcher.exe" in v["RelaunchCommand"] or "mimickit_launcher.py" in v["RelaunchCommand"]))
check("relaunch props set before the ID (ID last makes the taskbar re-read)",
      isrc.find('("RelaunchCommand", "RelaunchIconResource", "RelaunchDisplayNameResource", "ID")') > 0)
check("PKEY_AppUserModel_* pids (ID 5, RelaunchCommand 2, Icon 3, Name 4)",
      icon.PKEY_PIDS == {"RelaunchCommand": 2, "RelaunchIconResource": 3, "RelaunchDisplayNameResource": 4, "ID": 5})
if sys.platform != "win32":
    check("off Windows: identity / process ID are guarded no-ops",
          icon.set_window_identity(None) is False and icon.get_process_app_id() is None)
src_main = open(os.path.join(icon.APP_DIR, "mimickit_launcher.py")).read()
check("main window gets the identity on <Map> (wrapper exists), log line on Windows",
      'set_window_identity(e.widget)' in isrc and "identity_log_line" in src_main)
check("identity log line names ID + icon", icon.APP_ID in icon.identity_log_line() and icon.ICON_ICO in icon.identity_log_line())
check("make_shortcut.ps1 reads the ID back and fails loudly", "ExtendedProperty(\"System.AppUserModel.ID\")" in ps1
      and "exit 2" in ps1)
bat = open(os.path.join(icon.APP_DIR, "Check taskbar icon.bat"), "rb").read()
check("Check taskbar icon.bat: CRLF, cd /d first, launcher's python, writes the report",
      b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"") and b'cd /d "%~dp0"' in bat.split(b"setlocal")[0]
      and b"find_launcher_python.ps1" in bat and b"check_taskbar_icon.py" in bat)
import subprocess, tempfile
rep = os.path.join(tempfile.mkdtemp(), "r.txt")
r = subprocess.run([sys.executable, os.path.join(icon.APP_DIR, "tools", "check_taskbar_icon.py"), "--out", rep,
                    "--no-window"], capture_output=True, text=True, timeout=60)
txt = open(rep, encoding="utf-8").read() if os.path.isfile(rep) else ""
check("diagnostic runs and reports app ID, icon file, venv, Tk", r.returncode == 0 and icon.APP_ID in txt
      and "exists=True" in txt and "in a venv:" in txt and "Tcl " in txt, (r.stderr or "")[-300:])
print("RESULT: %d/%d" % (sum(ok), len(ok)))
