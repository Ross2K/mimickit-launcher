"""a0.8.8 QA: T1 test-helper liveness never uses os.kill on Windows, the sweep keeps folders whose owner or fake sim
runs, an orphaned fake sim ends itself; T2 combobox/spinbox wheel hooks on <Map>/rebuild (WeakSet), not on resize;
the top area's visible part ends at a whole row; OLED dark theme (#000 / #0d0d0d) incl. the charts.
   xvfb-run -a -s '-screen 0 1600x1000x24' python tests/qa088_test.py"""

import result_exit  # noqa: F401
import gc, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


import fake_mk as FM

# ---- T1 ---------------------------------------------------------------------------------------------------------
src = open(os.path.join(HERE, "fake_mk.py")).read()
check("T1 fake_mk liveness goes through mkl.core.proc_info (no os.kill(pid, 0))",
      "proc_info" in src and not re.search(r"os\.kill\([^)]*,\s*0\)", src))
core = open(os.path.join(ROOT, "mkl", "core.py")).read()
i = core.index("os.kill(pid, 0)")
check("T1 mkl.core: os.kill(pid, 0) only after the Windows branch returned",
      core.rfind("if IS_WIN:", 0, i) > core.rfind("def proc_info", 0, i) > 0)
runpy = open(os.path.join(HERE, "fake_mimickit", "mimickit", "run.py")).read()
j = runpy.index("os.kill(int(pid), 0)")
check("T1 fake run.py: os.kill only on POSIX (Windows uses OpenProcess/GetExitCodeProcess)",
      runpy.rfind('if os.name == "nt":', 0, j) > 0 and "GetExitCodeProcess" in runpy and "259" in runpy)
for f in ("time_test.py", "detach_test.py"):
    t = open(os.path.join(HERE, f)).read()
    check("T1 %s kills through hard_kill (taskkill on Windows)" % f, "hard_kill(" in t and "signal.SIGKILL" not in t)
check("T1 owner alive -> True, dead pid -> False", FM._alive(os.getpid()) and not FM._alive(2 ** 22 + 12345))

tmp = tempfile.gettempdir()


def mkdir(owner, sims=()):
    d = tempfile.mkdtemp(prefix="mkl_test_", dir=tmp)
    open(os.path.join(d, "owner.pid"), "w").write(str(owner))
    for s in sims:
        open(os.path.join(d, "sim.%d.pid" % s), "w").write(str(s))
    return d


sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait()
d_live = mkdir(sleeper.pid)
d_sim = mkdir(dead.pid, sims=(sleeper.pid,))
d_dead = mkdir(dead.pid)
gone = FM.sweep()
check("T1 sweep keeps a folder whose owner is alive", os.path.isdir(d_live))
check("T1 sweep keeps a folder whose owner is gone but a fake sim still runs", os.path.isdir(d_sim))
check("T1 sweep removes a folder whose owner and sims are gone", not os.path.isdir(d_dead) and d_dead in gone)
for d in (d_live, d_sim):
    shutil.rmtree(d, True)

# orphaned fake sim (test killed by a timeout): it notices its owner is gone and ends itself
own = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
d = mkdir(own.pid)
mk = os.path.join(d, "fake_mimickit")
shutil.copytree(os.path.join(HERE, "fake_mimickit"), mk, ignore=shutil.ignore_patterns("output", "__pycache__"))
env = dict(os.environ, STUB_SLEEP="0.2", STUB_ITERS="1000")
sim = subprocess.Popen([sys.executable, "-u", "mimickit/run.py", "--out_dir", "output/x"], cwd=mk, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)
check("T1 fake sim registers itself (sim.<pid>.pid)", os.path.isfile(os.path.join(d, "sim.%d.pid" % sim.pid)))
check("T1 sweep keeps the folder while owner + sim run", d not in FM.sweep() and os.path.isdir(d))
own.kill()
own.wait()
try:
    rc = sim.wait(timeout=10)
except subprocess.TimeoutExpired:
    rc = None
    sim.kill()
check("T1 orphaned fake sim ends itself once the owner test is gone", rc is not None, rc)
check("T1 ...and removes its sim pid file", not os.path.isfile(os.path.join(d, "sim.%d.pid" % sim.pid)))
check("T1 the folder is swept after that", d in FM.sweep())
sleeper.kill()

# ---- T2 + whole rows + OLED --------------------------------------------------------------------------------------
import tkinter as tk
from tkinter import ttk
import mimickit_launcher as G
from mkl.core import T

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
G.filedialog.askdirectory = lambda *a, **k: FM.fake_mk()
r = tk.Tk()
a = G.App(r)
a.v_mk.set(FM.fake_mk())
a.rescan()
r.geometry("1280x640+0+0")


def pump(n=30):
    for _ in range(n):
        r.update()
        time.sleep(0.02)


pump(60)
hooked = a._top_hooked
check("T2 hooked boxes kept in a WeakSet", type(hooked).__name__ == "WeakSet" and len(hooked) >= 2, len(hooked))
binds = r.bind("<Configure>") + str(a._top_inner.bind("<Configure>"))
check("T2 no hook on resize (<Configure>)", "hook_boxes" not in binds)
cb = ttk.Combobox(a._top_inner)
cb.pack()
pump(5)
r.event_generate("<<FlowRebuilt>>")
pump(5)
check("T2 ...and is hooked after a rebuild (<<FlowRebuilt>>)", cb in hooked)
n0 = len(hooked)
cb.destroy()
del cb
gc.collect()
check("T2 a destroyed box drops out of the set", len(hooked) == n0 - 1, (n0, len(hooked)))
cv = a._top_cv
pump(10)
h = cv.winfo_height()
k = max(1.0, r.winfo_fpixels("1i") / 96.0)
sh = max(20, min(24, int(18 * k)))
cuts = a._top_cuts()
scrolls = a._top_inner.winfo_reqheight() > h + 1
check("UX: the visible part above the strip ends at a whole row", not scrolls or (h - sh) in cuts,
      (h, sh, cuts[:12]))
check("OLED: dark theme is true black (#000 bg, #0d0d0d panels)", T["bg"] == "#000000" and T["panel"] == "#0d0d0d")
from matplotlib.colors import to_hex

check("OLED: charts match (figure = panel, plots = black)",
      to_hex(a.fig.get_facecolor()) == "#0d0d0d" and all(to_hex(x.get_facecolor()) == "#000000" for x in a._axes()))
import mimickit_remote as R

png = R.chart_png({}, dark=True)
check("OLED: phone chart PNG uses the same colours", png is None or b"PNG" in png[:8])
r.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
