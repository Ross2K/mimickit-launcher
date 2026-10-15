"""Live num_envs change: waits for the next model.pt save, stops, resumes from it with the new count.
xvfb-run -a python tests/envswitch_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.02")
import tkinter as tk, mimickit_launcher as G
from mkl.envswitch import CheckpointWatch

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: print("[dialog]", a))
G.messagebox.askyesno = lambda *a, **k: True
mk = os.path.join(HERE, "fake_mimickit")
G.filedialog.askdirectory = lambda **k: mk
shutil.rmtree(os.path.join(mk, "output"), ignore_errors=True)
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


# ---- CheckpointWatch (pure)
t = tempfile.mkdtemp()
p = os.path.join(t, "model.pt")
w = CheckpointWatch(p)
check("no file -> not saved", not w.saved())
open(p, "wb").write(b"a")
check("new file needs one still poll", not w.saved() and w.saved())
w = CheckpointWatch(p)
check("unchanged file -> not saved", not w.saved() and not w.saved())
time.sleep(0.02)
open(p, "wb").write(b"bb")
check("rewritten file -> saved after a still poll", not w.saved() and w.saved())

# ---- GUI
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


def steps():
    wait(1.5)
    app.v_out.set("output/live")
    src = app.outdir_abs("output/live")
    app.v_envs.set(256)
    app.train()
    wait(20, lambda: os.path.exists(os.path.join(src, "model.pt")))
    app.change_envs_live()
    check("armed while training", app.env_switch is not None)
    check(
        "status says waiting",
        "Waiting for next checkpoint" in app.l_envswitch.cget("text"),
        app.l_envswitch.cget("text"),
    )
    app.change_envs_live()
    check("second press cancels", app.env_switch is None and app.l_envswitch.cget("text") == "")
    app.v_envs.set(512)
    app.change_envs_live()
    old = app.proc
    r1 = src + "_resume1"
    wait(30, lambda: app.run_dir == r1 and app.proc is not old)
    check("resumed into the next _resumeN", app.run_dir == r1, str(app.run_dir))
    check("old process stopped", old.poll() is not None)
    c = app.t_cmd.get("1.0", "end")
    check("new num_envs used", "--num_envs 512" in c, c.strip().splitlines()[-1])
    check("starts from the checkpoint", "--model_file output/live_resume1/start_model.pt" in c)
    check("switch finished", app.env_switch is None and app.l_envswitch.cget("text") == "")
    wait(3)
    j = G.read_time(r1)
    check("chain continuity: parent + sessions", j and j["parent"] == src and j["sessions"] == 2, str(j))
    app.stop()
    wait(1.5)
    app.change_envs_live()
    check("nothing running -> not armed", app.env_switch is None)
    # training ends while waiting -> cancelled
    app.resume()
    wait(2)
    app.change_envs_live()
    app.stop()
    wait(2)
    check("training stopped while waiting -> cancelled", app.env_switch is None)


def safe():
    try:
        steps()
    except Exception:
        import traceback

        traceback.print_exc()
        ok.append(False)
    print("RESULT: %d/%d" % (sum(ok), len(ok)))
    try:
        app.stop()
    except Exception:
        pass
    root.destroy()


root.after(100, safe)
root.mainloop()
