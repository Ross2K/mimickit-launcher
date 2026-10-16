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
print("RESULT: %d/%d" % (sum(ok), len(ok)))
