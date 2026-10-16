"""a0.8.3: window opens at ~85 % of the work area, centred; a saved geometry is restored only if it fits the current
screen (monitor unplugged / resolution or DPI change -> centred default).   xvfb-run -a python tests/window_place_test.py"""

import result_exit  # noqa: F401
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import tkinter as tk, mimickit_launcher as G
from mkl import icon

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


class Fake:
    def __init__(self, saved):
        self.root = tk.Toplevel(ROOT)
        self.s = {"window": saved} if saved else {}
        self.appended = []

    def _append(self, m):
        self.appended.append(m)


ROOT = tk.Tk()
ROOT.withdraw()
icon.work_area = lambda r: (0, 0, 1920, 1040)


def place(saved):
    f = Fake(saved)
    G._place_window(f)
    f.root.update_idletasks()
    g = f.root.geometry()
    f.root.destroy()
    return g


g = place(None)
check("default: 85 % of the work area, centred", g.startswith("1632x884+144+78"), g)
g = place({"geometry": "1400x900+100+50", "zoomed": False})
check("saved geometry that fits is restored", g.startswith("1400x900+100+50"), g)
g = place({"geometry": "1400x900+3000+50", "zoomed": False})
check("saved position on an unplugged second monitor -> centred default", g.startswith("1632x884+144+78"), g)
g = place({"geometry": "2560x1400+0+0", "zoomed": False})
check("saved size larger than this screen -> centred default", g.startswith("1632x884+144+78"), g)
g = place({"geometry": "1400x900+-900+-700", "zoomed": False})
check("saved position far off the top-left -> centred default", g.startswith("1632x884+144+78"), g)
g = place({"geometry": "1400x900+1000+50", "zoomed": False})
check("saved window half off the right edge -> centred default", g.startswith("1632x884+144+78"), g)
g = place({"geometry": "garbage"})
check("damaged saved value -> centred default", g.startswith("1632x884+144+78"), g)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
