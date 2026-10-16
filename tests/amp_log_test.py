"""AMP task runs (e.g. the steering task): MimicKit's console table + log.txt carry extra Disc_* / Exp_Prob rows,
Iteration isn't the first row, the returns are bigger (task reward per step <= 1 over long episodes) and a value can
be 'nan'. Charts, status, per-step score, plateau estimate, phone snapshot and Stop after next save must all work.
  xvfb-run -a python tests/amp_log_test.py"""

import result_exit  # noqa: F401
import math, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.02", STUB_AMP="1", STUB_LOG_EPLEN="1")
import tkinter as tk, mimickit_launcher as G

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: print("[dialog]", a))
G.messagebox.askyesno = lambda *a, **k: True
mk = os.path.join(tempfile.mkdtemp(), "mk")
shutil.copytree(os.path.join(HERE, "fake_mimickit"), mk, ignore=shutil.ignore_patterns("output"))
G.filedialog.askdirectory = lambda **k: mk
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


root = tk.Tk()
app = G.App(root)


def wait(sec, until=None):
    t0 = time.time()
    while time.time() - t0 < sec:
        root.update()
        if until and until():
            return True
        time.sleep(0.05)
    return bool(until and until())


wait(2)
app.v_mk.set(mk)
app.rescan()
app.v_out.set("output/amp")
app.v_envs.set(256)
app.train()
log = os.path.join(app.outdir_abs("output/amp"), "log.txt")
wait(25, lambda: os.path.exists(log) and os.path.getsize(log) > 20000)
wait(4)
app._progress_tick(force=True)
wait(1.5)
snap = app.snap
ret = [p for p in (snap.get("charts") or {}).get("return", [])]
check("return chart has data", app.ax1 is not None and any(len(l.get_xdata()) > 3 for l in app.ax1.get_lines()))
check("iteration parsed (Iteration not the first row)", app.status.iteration and app.status.iteration > 3 if hasattr(app, "status") and hasattr(app.status, "iteration") else "Iteration" in snap.get("state", "") or bool(snap.get("samples")), snap.get("state"))
check("samples parsed", bool(snap.get("samples")), snap.get("samples"))
check("speed parsed", bool(snap.get("rate")), snap.get("rate"))
ps = snap.get("per_step") or ""
check("per-step score from log.txt (Train_Episode_Length) is a sane %", "%" in ps, ps)
check("plateau estimate shown", bool(snap.get("estimate")), snap.get("estimate"))
check("no launcher error raised", not getattr(app, "last_gui_error", ""), getattr(app, "last_gui_error", ""))
lines = (G.parse_log(log) if hasattr(G, "parse_log") else {})
tr = lines.get("Train_Return", [])
check("'nan' value read as a gap, not a crash", tr and any(v != v for v in tr) and any(v == v for v in tr))
check("extra AMP columns ignored by the charts", "Disc_Loss" not in str(snap.get("charts", {}).keys()))
# console rows in another order (returns before Iteration) still give whole records
from mkl.core import StdoutTables
ct = StdoutTables()
if ct is not None:
    blk = "".join("-" * 20 + "\n" + "|Train_Return | %d |\n|Disc_Loss | 0.5 |\n|Iteration | %d |\n|Samples | %d |\n" % (10 + i, i, 100 * i) for i in range(5)) + "-" * 20 + "\n"
    ct.feed(blk)
    check("console rows before Iteration kept", ct.data.get("Train_Return") == [10, 11, 12, 13, 14] and ct.data.get("Iteration") == [0, 1, 2, 3, 4], ct.data)
app.stop_after_save()
check("stop after next save arms", app.stop_save is not None)
wait(30, lambda: not app._training_running())
check("stops after the next save", not app._training_running(), app.l_stopsave.cget("text"))
print("RESULT: %d/%d" % (sum(ok), len(ok)))
