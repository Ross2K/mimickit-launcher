"""a0.8.9 QA: U5 boxes created / shown later outside flow() get the wheel rule (<Map>); U3 the whole-row cut loses at
most one row; U4/UX1-4 input borders + focus ~#555, fields #0d0d0d, scrollbar #6a6a6a on #1a1a1a, disabled
#5a5a5a on #121212 (not the secondary-text grey), black drop-down lists and Patches dialog.
   xvfb-run -a -s '-screen 0 1600x1000x24' python tests/qa089_test.py"""

import result_exit  # noqa: F401
import os, sys, tempfile, time

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
import mimickit_launcher as G
from fake_mk import fake_mk
from mkl.core import T

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
G.filedialog.askdirectory = lambda *a, **k: fake_mk()
r = tk.Tk()
a = G.App(r)
a.v_mk.set(fake_mk())
a.rescan()
r.geometry("1280x640+0+0")


def pump(n=30):
    for _ in range(n):
        r.update()
        time.sleep(0.02)


pump(60)
inner, hooked = a._top_inner, a._top_hooked
# U5: a box gridded into a nested frame later (no flow() involved), and one hidden then shown again
fr = ttk.Frame(inner)
fr.pack()
pump(5)
cb = ttk.Combobox(fr, values=["a", "b"])
cb.grid(row=0, column=0)
sp = ttk.Spinbox(fr, from_=0, to=9)
pump(10)
check("U5 combobox gridded later outside flow() is hooked (<Map>)", cb in hooked)
sp.grid(row=0, column=1)
pump(10)
check("U5 spinbox shown later is hooked", sp in hooked)
binds = cb.bind("<Button-5>") or ""
check("U5 hooked box has the wheel binding", "box_wheel" in str(binds), binds)
fr.destroy()
pump(5)
# U3: visible part ends at a cut and loses at most one row
cv = a._top_cv
k = max(1.0, r.winfo_fpixels("1i") / 96.0)
sh = max(20, min(24, int(18 * k)))
h = cv.winfo_height()
cuts = a._top_cuts()
c = h - sh
nxt = [x for x in cuts if x > c]
check("U3 cut at a whole row", c in cuts, (h, cuts[:10]))
check("U3 the next row would not have fit (loss < one row)", not nxt or min(nxt) + sh > h, (h, nxt[:2]))
# U4 / UX colours
st = ttk.Style(r)
check("U4 input fields #0d0d0d", st.lookup("TEntry", "fieldbackground").lower() == "#0d0d0d")
check("U4 input borders ~#555", st.lookup("TEntry", "bordercolor").lower() == "#555555"
      and st.lookup("TCombobox", "bordercolor").lower() == "#555555")
check("U4 focus ring ~#555", st.lookup("TEntry", "bordercolor", ["focus"]).lower() == "#555555")
check("U4 box edges keep #333", st.lookup("TLabelframe", "bordercolor").lower() == "#333333")
check("UX3 scrollbar thumb #6a6a6a on #1a1a1a", st.lookup("TScrollbar", "background").lower() == "#6a6a6a"
      and st.lookup("TScrollbar", "troughcolor").lower() == "#1a1a1a"
      and st.lookup("Top.Vertical.TScrollbar", "background").lower() == "#6a6a6a")
dfg = st.lookup("TButton", "foreground", ["disabled"]).lower()
dbg = st.lookup("TButton", "background", ["disabled"]).lower()
check("UX2 disabled #5a5a5a on #121212, not the secondary-text grey", dfg == "#5a5a5a" and dbg == "#121212"
      and dfg != T["dim"].lower(), (dfg, dbg, T["dim"]))
# UX4 drop-down list + Patches dialog
combo = next(w for w in list(a._top_hooked) if w.winfo_exists() and w.winfo_class() == "TCombobox")
pd = str(r.tk.call("ttk::combobox::PopdownWindow", combo))
check("UX4 drop-down list is black", str(r.tk.call(pd + ".f.l", "cget", "-background")).lower() in ("#000000", "black"))
a.patch_dialog()
pump(10)
tops = [w for w in r.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_exists()]
pt = next((w for w in tops if "patch" in w.title().lower()), None)
check("UX4 Patches dialog background is black", pt is not None and pt.cget("bg").lower() in ("#000000", "black"),
      pt and pt.cget("bg"))
if pt is not None:
    pt.destroy()
r.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
