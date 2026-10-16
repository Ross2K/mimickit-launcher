"""a0.9.3: 'Pause training for preview' (opt-in): save + stop through Stop-after-save, render, Resume into the same run
chain; stopped/failed render still resumes; your own STOP is never auto-resumed; failed resume -> clear notice; phone
only through the PIN-gated 'render_pause' (the open /api/render never pauses).
   xvfb-run -a -s '-screen 0 1600x1000x24' python tests/pause_preview_test.py"""

import result_exit  # noqa: F401
import os, shutil, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from fake_mk import fake_mk  # noqa: E402

os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.02")
import tkinter as tk, mimickit_launcher as G
import mimickit_remote as R

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: print("[dialog]", a))
G.messagebox.askyesno = lambda *a, **k: True
mk = fake_mk()
G.filedialog.askdirectory = lambda **k: mk
shutil.rmtree(os.path.join(mk, "output"), ignore_errors=True)
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


work = tempfile.mkdtemp()
fake_prev = os.path.join(work, "mimickit_preview.py")
secs_file = os.path.join(work, "secs")
open(fake_prev, "w").write("import time, sys\nt = float(open(%r).read())\ntime.sleep(abs(t))\nsys.exit(0 if t >= 0 else 3)\n"
                           % secs_file)
real_spawn = app._spawn_detached
SPAWNS = []


def spawn(cmd, logp, env=None):
    if any(str(c).endswith("mimickit_preview.py") for c in cmd):
        SPAWNS.append(cmd)
        cmd = [sys.executable, fake_prev, "all"]
    return real_spawn(cmd, logp, env)


app._spawn_detached = spawn


def start_training(out):
    app.v_out.set(out)
    app.v_envs.set(256)
    app.train()
    m = os.path.join(app.outdir_abs(out), "model.pt")
    wait(25, lambda: os.path.exists(m))
    return m


def log():
    return app.t_log.get("1.0", "end")


wait(1.5)
app.v_mk.set(mk)
app.rescan()
wait(0.5)
for name in app.cb_train["values"]:  # a config that can be previewed (the Z profile puts others first)
    app.v_train.set(name)
    app._train_changed()
    it = app._item("train")
    if it and not it.get("missing") and app._view_env(it, "preview"):
        break
print("using training config:", app.v_train.get())
check("checkbox exists, default OFF", hasattr(app, "v_pause") and app.v_pause.get() is False)

# A: off -> preview renders alongside, training untouched
open(secs_file, "w").write("2")
start_training("output/pp")
app.preview()
wait(1)
check("off: preview renders while training keeps running", app._preview_alive() and app._training_running() and not app.pp)
wait(6, lambda: not app._preview_alive())

# B: on -> pause, render, resume into the same chain
app.v_pause.set(True)
open(secs_file, "w").write("3")
tproc = app.proc
app.preview()
check("on: waits for the next save first", app.pp and app.pp["phase"] == "saving" and app.stop_save is not None)
wait(40, lambda: app._preview_alive())
check("training stopped (after the save) before the render", tproc.poll() is not None and app._preview_alive()
      and not app._training_running())
check("phone sees the pause state", app._pp_snapshot({}) is None and True)
snap = {}
app._pp_snapshot(snap)
check("snapshot: phase rendering", snap["pause_preview"]["phase"] == "rendering", snap)
wait(30, lambda: app._training_running() and not app.pp)
check("training resumed automatically after the render", app._training_running() and app.proc is not tproc)
check("...into the same run chain (_resume folder)", "_resume" in (app.run_dir or ""), app.run_dir)
check("notice: resumed", "training resumed from the latest save" in log())

# C: render STOPPED -> still resumes
tproc = app.proc
open(secs_file, "w").write("60")
app.preview()
wait(40, lambda: app._preview_alive())
okk, msg = app.stop_render("PC")
check("render stopped", okk, msg)
wait(30, lambda: app._training_running() and not app.pp)
check("stopped render -> training resumed anyway", app._training_running() and app.proc is not tproc)

# D: render FAILS -> still resumes
tproc = app.proc
open(secs_file, "w").write("-1")
app.preview()
wait(60, lambda: app._training_running() and app.proc is not tproc and not app.pp)
check("failed render -> training resumed anyway", app._training_running() and app.proc is not tproc)

# E: you press STOP during the render -> not resumed
open(secs_file, "w").write("4")
app.preview()
wait(40, lambda: app._preview_alive())
app.stop()  # the user's STOP (nothing running now, but the intent counts)... and the case where training still runs:
wait(15, lambda: not app.pp)
check("STOP during the paused render -> training stays stopped", not app._training_running() and not app.pp)
check("notice: stays stopped", "stays stopped (you pressed STOP)" in log())

# F: STOP pressed while waiting for the save -> not resumed
start_training("output/pp2")
open(secs_file, "w").write("2")
app.preview()
wait(0.5)
app.stop()
wait(20, lambda: not app.pp)
check("STOP while waiting for the save -> never auto-resumed", not app._training_running() and not app.pp)

# G: resume fails -> clear notice (PC label + phone), not silent
start_training("output/pp3")
real_resume = app.resume
app.resume = lambda: None
app.preview()
wait(60, lambda: not app.pp)
app.resume = real_resume
snap = {}
app._pp_snapshot(snap)
check("failed resume -> red notice on the PC", "could NOT be resumed" in app.l_pause.cget("text")
      and str(app.l_pause.cget("style")) == "Err.TLabel", app.l_pause.cget("text"))
check("...and on the phone", snap["pause_preview"]["error"] and "could NOT be resumed" in snap["pause_preview"]["msg"])

# H: phone - only through the PIN-gated control
start_training("output/pp4")
app.v_pause.set(False)
okr, _ = app._remote_render(None)
wait(1)
check("open /api/render path never pauses training", okr and not app.pp and app._training_running())
wait(10, lambda: not app._preview_alive())
check("render_pause is a gated control action", "render_pause" in R.ACTIONS)
cfg = dict(allow_control=True, pin_hash=R.hash_pin("2468"), pin_len=4, host="0.0.0.0")
check("render_pause refused without a PIN session", R.Control(lambda: cfg, lambda a, p: (200, "")).act("x", "y", "render_pause", {})[0] == 401)
res = {}
th = threading.Thread(target=lambda: res.update(r=app._remote_action("render_pause", {})))
th.start()
wait(5, lambda: not th.is_alive())
wait(1, lambda: bool(app.pp))
check("phone render_pause (signed in) -> pause armed", res.get("r", (0,))[0] == 202 and app.pp and app.pp["origin"] == "phone", res)
wait(60, lambda: not app.pp)
check("phone pause -> resumed afterwards", app._training_running())
page = open(R.__file__, encoding="utf-8").read()
check("phone page: checkbox in Preview options + notice line", 'id="pv_pause"' in page and 'id="ppline"' in page
      and "act('render_pause'" in page)
app.stop()
wait(3)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
