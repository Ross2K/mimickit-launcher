"""a0.8.6 QA: R1 phone cancel / stop-after-save decided by the WANTED state (pending request, else armed);
R4 flow() doesn't poll; UX: top area wheel over child widgets (not comboboxes), <~20 px hidden -> no scrollbar.
   xvfb-run -a -s '-screen 0 1600x1000x24' python tests/qa086_test.py"""

import result_exit  # noqa: F401
import os, sys, queue, threading, tempfile, time

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
from tkinter import ttk
from mkl.dashboard import DashboardMixin
from mkl.window import flow

# ---- R1 ---------------------------------------------------------------------------------------------------------


class A(DashboardMixin):
    def __init__(s, armed):
        s._remote_lock, s.rq, s.stop_save, s.proc = threading.Lock(), queue.Queue(), "phone" if armed else None, None

    def stop_after_save(s, who):
        s.stop_save = None if s.stop_save else who

    def _training_running(s):
        return True


def run(seq, armed=False, order=None):
    a = A(armed)
    rep = [a._remote_action(x, {}) for x in seq]
    cbs = []
    while not a.rq.empty():
        cbs.append(a.rq.get())
    for c in (reversed(cbs) if order == "rev" else cbs):
        c()
    return rep, bool(a.stop_save)


rep, fin = run(["cancel_stop", "stop_after_save"], armed=True)
check("R1 armed: cancel then SaS -> SaS queued (not 'Already set'), ends armed", rep[1][0] == 202 and fin, rep)
rep, fin = run(["cancel_stop", "stop_after_save", "cancel_stop"], armed=True)
check("R1 armed: cancel/SaS/cancel ends cancelled", not fin and all(r[0] == 202 for r in rep), rep)
rep, fin = run(["stop_after_save", "stop_after_save"])
check("R1 SaS twice: second says Already set, ends armed", rep[1] == (200, "Already set: will stop after next save.") and fin)
rep, fin = run(["stop_after_save", "cancel_stop", "stop_after_save"], order="rev")
check("R1 SaS/cancel/SaS ends armed whatever the run order", fin, rep)
rep, fin = run(["cancel_stop"])
check("R1 cancel with nothing armed -> Nothing to cancel", rep[0] == (200, "Nothing to cancel.") and not fin)

# ---- R4: flow() without polling ---------------------------------------------------------------------------------
root = tk.Tk()
root.geometry("400x200")
f = ttk.Frame(root)
f.pack(fill="x")
for i in range(6):
    ttk.Button(f, text="Button %d" % i).pack(side="left", padx=3)
flow(f)
for _ in range(20):
    root.update()
    time.sleep(0.03)
n0 = len(root.tk.call("after", "info"))
time.sleep(1.0)
root.update()
n1 = len(root.tk.call("after", "info"))
check("R4 flow(): no timer left polling once laid out", n0 == 0 and n1 == 0, (n0, n1))
late = ttk.Button(f, text="Late")
late.pack(side="left")
for _ in range(20):
    root.update()
    time.sleep(0.03)
check("R4 flow(): a widget packed later is still adopted (via <Configure>)", late.winfo_manager() == "pack"
      and late.pack_info().get("in") is not f, late.pack_info().get("in"))
root.destroy()

# ---- UX 2 + 4 on the real window -------------------------------------------------------------------------------
import mimickit_launcher as G
from fake_mk import fake_mk

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
G.filedialog.askdirectory = lambda *a, **k: fake_mk()
r = tk.Tk()
a = G.App(r)
a.v_mk.set(fake_mk())
r.geometry("1280x700+0+0")
for _ in range(60):
    r.update()
    time.sleep(0.03)
cv, inner = a._top_cv, a._top_inner
req, h = inner.winfo_reqheight(), cv.winfo_height()
scrolls = req > h + 1
check("UX: short window -> top area scrolls", scrolls, (h, req))
def _walk(w):
    for c in w.winfo_children():
        yield c
        yield from _walk(c)


child = next(w for w in _walk(inner) if w.winfo_class() == "TButton")  # 1.0.0: any button in the Train left column
a._top_hover["on"] = True
cv.yview_moveto(0)

class E:
    pass

e = E()
e.widget, e.delta, e.num = child, -120, 5
res = a._top_wheel(e)
r.update()
check("UX 2: wheel over a child button scrolls the top area", cv.yview()[0] > 0, cv.yview())
cb = ttk.Combobox(inner)
cv.yview_moveto(0)
e.widget = cb
check("UX 2: wheel over a combobox is left to the combobox", a._top_wheel(e) is None and cv.yview()[0] == 0)
check("UX 3: '\u25be more' strip shown while scrolled to the top", a._top_more.winfo_manager() == "place")
# UX 4: a window where only a few px would be hidden
k = max(1.0, r.winfo_fpixels("1i") / 96.0)
bad, seen = [], []
for hh in range(700, 1000, 6):
    r.geometry("1280x%d+0+0" % hh)
    for _ in range(6):
        r.update()
        time.sleep(0.02)
    req, h = inner.winfo_reqheight(), cv.winfo_height()
    seen.append(req - h)
    if 1 < req - h <= int(20 * k):
        bad.append((hh, req - h))
check("UX 4: never a scrollbar for <= ~20 px hidden (took it from the bottom half)", not bad and min(seen) <= 0,
      bad or min(seen))
r.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
