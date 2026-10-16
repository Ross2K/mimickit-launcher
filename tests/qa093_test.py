"""a0.9.3: Cancel render (PC + phone) - kills ONLY the preview process tree (identity checked, never the training),
removes the partial files, progress back to idle with 'Render cancelled'. Windows: taskkill /PID <preview> /T /F.
   xvfb-run -a -s '-screen 0 1600x1000x24' python tests/qa093_test.py"""

import result_exit  # noqa: F401
import os, shutil, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import tkinter as tk, mimickit_launcher as G
import mimickit_remote as R
from mkl import process

G.messagebox.askyesno = lambda *a, **k: True
for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
mk = os.path.join(tempfile.mkdtemp(), "mk")
G.filedialog.askdirectory = lambda **k: mk
shutil.copytree(os.path.join(HERE, "fake_mimickit"), mk, ignore=shutil.ignore_patterns("output"))
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


def alive(pid):
    i = G.proc_info(pid)
    return bool(i and i.get("alive"))


wait(1.5)
app.v_mk.set(mk)
app.rescan()
work = tempfile.mkdtemp()
logp = os.path.join(work, "console.txt")
# fake 'training' (its own detached session, like the real one)
app.proc = app._spawn_detached([sys.executable, "-c", "import time; time.sleep(120)"], logp, dict(os.environ))
app.run_kind = "train"
train_pid = app.proc.pid
# fake preview: a script named mimickit_preview.py that starts a child (like render workers / ffmpeg) and writes output
fdir = os.path.join(work, "fake")
os.makedirs(fdir)
script = os.path.join(fdir, "mimickit_preview.py")
child_pid_file = os.path.join(work, "child.pid")
open(script, "w").write(
    "import subprocess, sys, time\n"
    "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "open(%r, 'w').write(str(c.pid))\n"
    "time.sleep(120)\n" % child_pid_file)
mp4 = os.path.join(work, "preview_500.mp4")
old = os.path.join(work, "preview_400.mp4")
open(old, "wb").write(b"finished earlier")
os.utime(old, (time.time() - 3600, time.time() - 3600))


def start_fake_preview():
    for f in (child_pid_file,):
        if os.path.exists(f):
            os.remove(f)
    app._preview_started = time.time()
    app._preview_out = mp4
    app.preview_proc = app._spawn_detached([sys.executable, script, "all", "--out", mp4], logp, dict(os.environ))
    app._preview_progress("", origin="PC")
    threading.Thread(target=app._reader, args=(app.preview_proc, logp, 0, None, "preview"), daemon=True).start()
    wait(5, lambda: os.path.exists(child_pid_file) and open(child_pid_file).read().strip())
    open(mp4, "wb").write(b"partial")
    open(os.path.splitext(mp4)[0] + ".npz", "wb").write(b"partial")
    td = tempfile.mkdtemp(prefix="mk_preview_")
    open(os.path.join(td, "part000.mp4"), "wb").write(b"x")
    return app.preview_proc.pid, int(open(child_pid_file).read()), td


check("PC: Cancel render button exists, greyed when nothing renders",
      hasattr(app, "b_stoprender") and app.b_stoprender.instate(["disabled"]))
def inside(w, box):
    while w is not None:
        if w is box:
            return True
        w = w.master
    return False


pvb = app.preview_box
check("PC: all preview controls in their own 'Preview' box", pvb.cget("text") == "Preview" and all(
    inside(w, pvb) for w in (app.b_stoprender, app.cb_allclips, app.b_clips, app.run_btns["preview"], app.l_pause,
                             app.pv_bar)))
check("PC: 'Choose clips...' (greyed while All clips is ticked)", app.b_clips.cget("text") == "Choose clips...")
check("PC: pause notices go on the render status line", app.l_pause is app.l_pvprog)
check("PC: Preview sits right of 'What to run' when wide, below it when narrow",
      app._jobrow_mode in ("side", "side1", "stack") and str(app.preview_box.grid_info().get("column")) in ("0", "1"))
_jw, _pw = app._job_basew + 8, app._pv_widths
modes = {}
for _w, _want in ((_jw + _pw["wide"] + 20, "side"), (_jw + _pw["narrow"] + 10, "side1"), (_jw + _pw["narrow"] - 30, "stack")):
    app._jobrow_mode = None
    app._jobrow.winfo_width = (lambda v=_w: v)
    app._jobrow_layout()
    app.root.update_idletasks()
    gi = app.preview_box.grid_info()
    modes[_want] = (app._jobrow_mode, str(gi.get("row")), str(gi.get("column")), app._pv_mode,
                    app.b_pdiag.cget("text"))
del app._jobrow.winfo_width
app._jobrow_mode = None
app._jobrow_layout()
check("PC: wide -> Preview beside 'What to run', two columns", modes["side"][:4] == ("side", "0", "1", "wide"), modes)
check("PC: narrower -> still beside, one setting per row", modes["side1"][:4] == ("side1", "0", "1", "narrow")
      and modes["side1"][4] == "Diagnostics", modes)
check("PC: too narrow -> Preview wraps below 'What to run'", modes["stack"][:4] == ("stack", "1", "0", "wide"), modes)
check("PC: Preview box is separate from the training controls", not inside(app.run_btns["train"], pvb)
      and not inside(pvb, app.run_btns["train"].master))
check("nothing running -> refused", app.stop_render() == (False, "No render is running."))
pid, child, td = start_fake_preview()
app._sync_run_buttons(app._training_running())
check("PC: Cancel render live while rendering", not app.b_stoprender.instate(["disabled"]))
check("setup: preview + its child + training alive", alive(pid) and alive(child) and alive(train_pid))
okk, msg = app.stop_render("PC")
wait(1.5)
check("Cancel render -> 'Render cancelled'", okk and msg == "Render cancelled.", msg)
check("preview process and its child are gone", not alive(pid) and not alive(child))
check("training NOT touched", alive(train_pid) and app.proc.poll() is None)
check("partial mp4 / npz / temp dir removed", not os.path.exists(mp4) and not os.path.exists(mp4[:-4] + ".npz")
      and not os.path.exists(td))
check("an older finished preview is kept", os.path.exists(old))
rp = app.render_prog
check("progress idle + 'Render cancelled' (no failure shown later)", not rp.get("active") and rp.get("stage") == "Render cancelled"
      and rp.get("pct") == 0, rp)
check("PC button greyed again", app.b_stoprender.instate(["disabled"]))

# identity checks: never the training, never a stranger
app.preview_proc = app.proc
okk, msg = app.stop_render()
check("preview_proc pointing at the training -> refused, training alive", not okk and alive(train_pid), msg)
stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
app.preview_proc = stranger
okk, msg = app.stop_render()
check("a process that isn't mimickit_preview.py -> refused, left alone", not okk and stranger.poll() is None, msg)
stranger.kill()

# Windows path: taskkill on the preview's own PID only
calls = []
real_run, real_win = process.subprocess.run, process.IS_WIN
process.subprocess.run = lambda cmd, **k: (calls.append(cmd), subprocess.CompletedProcess(cmd, 0, "", ""))[1]
process.IS_WIN = True
try:
    app._kill_preview_tree(4242)
finally:
    process.subprocess.run, process.IS_WIN = real_run, real_win
check("Windows: taskkill /PID <preview> /T /F, nothing else", calls == [["taskkill", "/PID", "4242", "/T", "/F"]], calls)

# phone
pid, child, td = start_fake_preview()
res = {}
th = threading.Thread(target=lambda: res.update(r=app._remote_action("stop_render", {})))
th.start()
wait(10, lambda: not th.is_alive())
check("phone stop_render -> 200 'Render cancelled.'", res.get("r") == (200, "Render cancelled."), res)
check("phone: preview gone, training alive", not alive(pid) and not alive(child) and alive(train_pid))
check("phone: nothing rendering -> 409", app._remote_action("stop_render", {})[0] == 409)
check("stop_render is a PIN-gated control action", "stop_render" in R.ACTIONS)
cfg = dict(allow_control=True, pin_hash=R.hash_pin("2468"), pin_len=4, host="0.0.0.0")
ctl = R.Control(lambda: cfg, lambda a, p: (200, "ok"))
check("phone: refused without a PIN session", ctl.act("x", "y", "stop_render", {})[0] == 401)
page = open(R.__file__, encoding="utf-8").read()
check("phone: small button, spaced row, tap + Yes/Keep rendering, auto-cancel 15 s",
      'class="danger small" id="r_stop"' in page and 'id="rstoprow"' in page and "act('stop_render'" in page
      and "holdText:'cancel render',timeout:15000" in page and "keep:'Keep rendering'" in page)
app.proc.kill()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
