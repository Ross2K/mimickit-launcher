"""a0.8.4: STOP (and Start / Resume / Stop after next save) fully inside the window at the minimum window size
(1100x720), at 100 % and 125 % scaling; the wrapped rows don't cut off any run button.
   xvfb-run -a -s '-screen 0 1600x1000x24' python tests/stop_visible_test.py"""

import result_exit  # noqa: F401
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


CHILD = r"""
import os, sys, tempfile, json
sys.path.insert(0, %r)
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import tkinter as tk, mimickit_launcher as G
import tkinter.filedialog as fd; fd.askdirectory = lambda *a, **k: ""
for n in ("showinfo", "showwarning", "showerror"): setattr(G.messagebox, n, lambda *a, **k: None)
r = tk.Tk(); r.tk.call("tk", "scaling", float(sys.argv[1]))
a = G.App(r); a.v_mk.set(os.path.join(%r, "tests", "fake_mimickit")); a.rescan()
r.state("normal"); r.geometry("1100x720+0+0")
def done():
    r.update()
    wx0, wy0, wx1, wy1 = r.winfo_rootx(), r.winfo_rooty(), r.winfo_rootx() + r.winfo_width(), r.winfo_rooty() + r.winfo_height()
    out = {}
    for k, b in a.run_btns.items():
        x0, y0 = b.winfo_rootx(), b.winfo_rooty()
        out[k] = bool(b.winfo_ismapped()) and x0 >= wx0 and y0 >= wy0 and x0 + b.winfo_width() <= wx1 and y0 + b.winfo_height() <= wy1
    print("JSON" + json.dumps(out), flush=True); os._exit(0)
r.after(2500, done); r.mainloop()
""" % (ROOT, ROOT)
for sc, lab in ((1.333, "100 %"), (1.667, "125 %")):
    r = subprocess.run([sys.executable, "-c", CHILD, str(sc)], capture_output=True, text=True, timeout=60)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("JSON")), "")
    import json

    res = json.loads(line[4:]) if line else {}
    check("%s: STOP fully visible at 1100x720" % lab, res.get("stop"), res or r.stderr[-300:])
    check("%s: Start / Resume / Stop after next save visible" % lab, all(res.get(k) for k in ("train", "resume", "stopsave")), res)
    check("%s: every run button visible (wrapped, not cut off)" % lab, res and all(res.values()), res)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
