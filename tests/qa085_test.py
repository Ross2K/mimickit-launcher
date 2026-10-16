"""a0.8.5 QA: Q1 rq/_remote_lock exist before the GPU poll thread starts; Q2 phone arm/cancel/arm decided by
generation (newest request wins, whatever order the GUI runs the queued callbacks); tooltips never cover the
control's row; the bottom half keeps a real minimum height at 125 % (top scrolls first, STOP visible).
   xvfb-run -a -s '-screen 0 1600x1000x24' python tests/qa085_test.py"""

import result_exit  # noqa: F401
import os, sys, queue, threading, tempfile, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


import tkinter as tk
import mimickit_launcher as G
from mkl.window import MainWindowMixin
from mkl.dashboard import DashboardMixin
from mkl.dialogs import tip_position

# ---- Q1 ------------------------------------------------------------------------------------------------------
seen = {}
orig = MainWindowMixin._gpu_poll_thread


def spy(self):
    seen["rq"] = isinstance(getattr(self, "rq", None), queue.Queue)
    seen["lock"] = getattr(self, "_remote_lock", None) is not None
    return orig(self)


MainWindowMixin._gpu_poll_thread = spy
for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
root = tk.Tk()
app = G.App(root)
MainWindowMixin._gpu_poll_thread = orig
check("Q1: self.rq exists before the GPU poll thread starts", seen.get("rq"), seen)
check("Q1: _remote_lock exists before the GPU poll thread starts", seen.get("lock"), seen)


# ---- Q2 ------------------------------------------------------------------------------------------------------
class Fake(DashboardMixin):
    def __init__(self):
        self.rq = queue.Queue()
        self._remote_lock = threading.Lock()
        self.stop_save = None
        self.proc = None
        self.toggles = 0

    def _training_running(self):
        return True

    def stop_after_save(self, origin="PC"):
        self.toggles += 1
        self.stop_save = None if self.stop_save else {"origin": origin}
        return True, ""


def drain(f, order=None):
    cbs = []
    while not f.rq.empty():
        cbs.append(f.rq.get())
    for cb in (reversed(cbs) if order == "rev" else cbs):
        cb()


for order in (None, "rev"):
    f = Fake()
    r1 = f._remote_action("stop_after_save", {})
    r2 = f._remote_action("cancel_stop", {})
    r3 = f._remote_action("stop_after_save", {})
    drain(f, order)
    check("Q2: arm / cancel / arm (queued, %s order) ends ARMED" % (order or "fifo"),
          bool(f.stop_save) and [r1[0], r2[0], r3[0]] == [202, 202, 202], (f.stop_save, r1, r2, r3, f.toggles))
    f = Fake()
    f._remote_action("stop_after_save", {})
    f._remote_action("cancel_stop", {})
    drain(f, order)
    check("Q2: arm / cancel (%s order) ends cancelled, nothing toggled" % (order or "fifo"),
          not f.stop_save and f.toggles == 0, f.toggles)
f = Fake()
f._remote_action("stop_after_save", {})
drain(f)
r = f._remote_action("stop_after_save", {})
check("Q2: second arm is a no-op (200)", r[0] == 200 and f.rq.empty())
f._remote_action("cancel_stop", {})
drain(f)
check("Q2: cancel after arm disarms", not f.stop_save)

# ---- tooltip position ----------------------------------------------------------------------------------------
root.geometry("1200x800+0+0")
root.update()
b = app.run_btns["train"]
root.update()
x, y = tip_position(b, 300, 80)
by0, by1 = b.winfo_rooty(), b.winfo_rooty() + b.winfo_height()
check("tooltip doesn't overlap its button's row", y >= by1 or y + 80 <= by0, (x, y, by0, by1))
nb = app.run_btns["resume"]
check("tooltip doesn't cover the next button", not (x < nb.winfo_rootx() + nb.winfo_width() and x + 300 > nb.winfo_rootx()
                                                    and y < nb.winfo_rooty() + nb.winfo_height() and y + 80 > nb.winfo_rooty()))
x, y = tip_position(b, 300, 2000)  # can't fit above/below: beside
check("tall tooltip goes beside the control", x >= b.winfo_rootx() + b.winfo_width() or x + 300 <= b.winfo_rootx(), (x, y))
root.destroy()

# ---- bottom minimum at 125 % (child: tk scaling must be set before widgets are built) --------------------------
CHILD = r"""
import os, sys, tempfile
sys.path.insert(0, %r); sys.path.insert(0, %r)
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import tkinter as tk, mimickit_launcher as G
from fake_mk import fake_mk
for n in ("showinfo", "showwarning", "showerror"): setattr(G.messagebox, n, lambda *a, **k: None)
r = tk.Tk(); r.tk.call("tk", "scaling", 1.67)
a = G.App(r); a.v_mk.set(fake_mk()); a.rescan()
r.after(300, lambda: r.geometry("1536x816+0+0"))
def done():
    r.update()
    k = max(1.0, r.winfo_fpixels("1i") / 96.0)
    mid = a.prog_frame.winfo_height()
    s = a.run_btns["stop"]
    print("RES", mid, int(a.BOTTOM_MIN * k * 0.9), a._top_cv.winfo_height(), a._top_inner.winfo_reqheight(),
          s.winfo_rooty() + s.winfo_height() - r.winfo_rooty(), r.winfo_height(), flush=True)
    os._exit(0)
r.after(4000, done); r.mainloop()
""" % (ROOT, HERE)
out = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True, timeout=90).stdout
line = next((l for l in out.splitlines() if l.startswith("RES")), "RES 0 1 0 0 9999 0").split()
mid, need, toph, topreq, stopb, winh = map(int, line[1:])
check("125 %% 1536x816: charts box keeps its minimum (%d px >= %d)" % (mid, need), mid >= need)
check("125 %%: the top section is the one that scrolls (shown %d of %d px)" % (toph, topreq), toph < topreq)
check("125 %: STOP still inside the window", 0 < stopb <= winh, (stopb, winh))
print("RESULT: %d/%d" % (sum(ok), len(ok)))
