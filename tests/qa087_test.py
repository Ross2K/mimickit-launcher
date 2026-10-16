"""a0.8.7 QA: comboboxes / spinboxes in the top area take the mouse wheel only when focused (else the top area
scrolls, the value stays); Text/Listbox keep their own wheel; widget matching by path (S2); teardown drops only our
all-binding (S5); at 125 % the top keeps ~260 px, two charts show (>= 312 px) and the chart toolbar doesn't clip.
   xvfb-run -a -s '-screen 0 1600x1000x24' python tests/qa087_test.py"""

import result_exit  # noqa: F401
import os, sys, tempfile, time, subprocess

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

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
G.filedialog.askdirectory = lambda *a, **k: fake_mk()


def pump(n=30):
    for _ in range(n):
        r.update()
        time.sleep(0.02)


r = tk.Tk()
a = G.App(r)
a.v_mk.set(fake_mk())
a.rescan()
r.geometry("1280x640+0+0")
pump(60)
cv, inner = a._top_cv, a._top_inner
check("short window: top area scrolls", inner.winfo_reqheight() > cv.winfo_height() + 1)
a._top_hover["on"] = True
stack, boxes = [inner], []
while stack:
    w = stack.pop()
    stack.extend(w.winfo_children())
    if w.winfo_class() in ("TCombobox", "TSpinbox"):
        boxes.append(w)
spin = next((b for b in boxes if b.winfo_class() == "TSpinbox"), None)
combo = next((b for b in boxes if b.winfo_class() == "TCombobox"), None)
check("top area has a spinbox (num_envs) and a combobox (Training config)", spin is not None and combo is not None)


def roll(w, up=False):
    w.event_generate("<Button-4>" if up else "<Button-5>")
    r.update()


for name, w in (("spinbox", spin), ("combobox", combo)):
    r.focus_set()
    pump(5)
    cv.yview_moveto(0)
    r.update()
    before = w.get()
    roll(w)
    check("%s without focus: wheel scrolls the top area" % name, cv.yview()[0] > 0, cv.yview())
    check("%s without focus: value unchanged" % name, w.get() == before, (before, w.get()))
spin.focus_force()
pump(5)
cv.yview_moveto(0)
r.update()
before = spin.get()
roll(spin, up=True)
check("spinbox WITH focus: wheel changes the value", spin.get() != before, (before, spin.get()))
check("spinbox WITH focus: top area doesn't scroll as well", cv.yview()[0] == 0, cv.yview())

r.focus_set()
pump(5)

class E:
    pass


for cls, maker in (("Text", lambda: tk.Text(inner, height=2)), ("Listbox", lambda: tk.Listbox(inner, height=2))):
    t = maker()
    cv.yview_moveto(0)
    e = E()
    e.widget, e.delta, e.num = t, -120, 5
    a._top_wheel(e)
    r.update()
    check("%s in the top area keeps its own wheel (top doesn't scroll)" % cls, cv.yview()[0] == 0)
    t.destroy()
# S2: a sibling whose path merely starts with the top area's path is not "inside"
outer = cv.master
sib = ttk.Label(r, name=str(outer).lstrip(".") + "x")  # path = top area path + "x"
e = E()
e.widget, e.delta, e.num = sib, -120, 5
cv.yview_moveto(0)
a._top_wheel(e)
r.update()
check("S2: widget outside the top area (path %s vs %s) doesn't scroll it" % (sib, outer), cv.yview()[0] == 0)
lab = next(w for w in inner.winfo_children()[0].winfo_children() if w.winfo_class() == "TLabel")
e.widget = lab
a._top_wheel(e)
r.update()
check("S2: a label inside scrolls it", cv.yview()[0] > 0)
# S5: teardown removes only our all-binding
a._top_hover["on"] = False
outer.event_generate("<Enter>")
r.update()
r.bind_all("<Button-5>", lambda e: None, add="+")
before = str(r.tk.call("bind", "all", "<Button-5>"))
a._top_teardown()
after = str(r.tk.call("bind", "all", "<Button-5>"))
check("S5: teardown drops our all-binding and keeps others", after.count("\n") < before.count("\n") + 1
      and after.strip() != "" and len(after) < len(before), (len(before), len(after)))
r.destroy()

# ---- 125 % layout (child: tk scaling before widgets are built) -------------------------------------------------
CHILD = r"""
import os, sys, tempfile
sys.path.insert(0, %r); sys.path.insert(0, %r)
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import tkinter as tk, mimickit_launcher as G, shutil
from fake_mk import fake_mk
G.filedialog.askdirectory = lambda *a, **k: fake_mk()
for n in ("showinfo", "showwarning", "showerror"): setattr(G.messagebox, n, lambda *a, **k: None)
r = tk.Tk(); r.tk.call("tk", "scaling", 1.6667)
a = G.App(r); a.v_mk.set(fake_mk()); a.rescan()
r.after(300, lambda: r.geometry("1536x816+0+0"))
def done():
    r.update()
    nav = a.navf
    clip = 0
    st = [nav]
    while st:
        w = st.pop(); st.extend(w.winfo_children())
        if w.winfo_ismapped() and w.winfo_class() in ("TButton", "TCheckbutton", "TRadiobutton"):
            if w.winfo_rootx() + w.winfo_width() > nav.winfo_rootx() + nav.winfo_width() + 1: clip += 1
    print("RES", a._top_cv.winfo_height(), a.canvas.get_tk_widget().winfo_height(), getattr(a, "_chart_short", 0), clip,
          a._top_more.winfo_height() if a._top_more.winfo_manager() else 0, flush=True)
    shutil.rmtree(os.path.dirname(fake_mk()), True)
    os._exit(0)
r.after(4000, done); r.mainloop()
""" % (ROOT, HERE)
out = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True, timeout=90).stdout
top, ch, short, clip, more = map(int, next((l for l in out.splitlines() if l.startswith("RES")), "RES 0 0 9 9 0").split()[1:])
check("125 %%: top keeps ~260 px, snapped down to a whole row (%d)" % top, top >= 210)  # a0.8.8: snap
check("125 %%: chart canvas >= 312 px, two charts (%d px, short=%d)" % (ch, short), ch >= 312 and short < 2)
check("125 %%: no chart toolbar control clipped (%d)" % clip, clip == 0)
check("125 %%: '\u25be More settings below' strip 20-24 px (%d)" % more, 20 <= more <= 24)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
