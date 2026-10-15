"""Window icon plumbing: assets exist, .ico is multi-size, apply_icon works, set_app_id is a no-op off Windows.
xvfb-run -a python tests/icon_test.py"""

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
root.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
