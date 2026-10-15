"""'Stop after next save': armed while training, status + cancel, stops right after the next model.pt save.
xvfb-run -a python tests/stopsave_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.02")
import tkinter as tk, mimickit_launcher as G

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: print("[dialog]", a))
G.messagebox.askyesno = lambda *a, **k: True
mk = os.path.join(HERE, "fake_mimickit")
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


def steps():
    wait(1.5)
    app.stop_after_save()
    check("nothing running -> not armed", app.stop_save is None)
    app.v_out.set("output/stopsave")
    src = app.outdir_abs("output/stopsave")
    app.v_envs.set(256)
    app.train()
    m = os.path.join(src, "model.pt")
    wait(20, lambda: os.path.exists(m))
    app.stop_after_save()
    check("armed while training", app.stop_save is not None)
    check("status says it", app.l_stopsave.cget("text") == "Will stop after next save...", app.l_stopsave.cget("text"))
    check("button offers cancel", app.b_stopsave.cget("text") == "Cancel stop after save")
    app.change_envs_live()
    check("num_envs change refused while armed", app.env_switch is None)
    app.stop_after_save()
    check("second press cancels", app.stop_save is None and app.l_stopsave.cget("text") == "")
    check("button back to normal", app.b_stopsave.cget("text") == "Stop after next save")
    wait(1)
    check("still training after cancel", app._training_running())
    app.stop_after_save()
    t_arm = os.stat(m).st_mtime_ns
    proc = app.proc
    wait(30, lambda: proc.poll() is not None)
    check("training stopped", proc.poll() is not None)
    check("...after a new model.pt save", os.stat(m).st_mtime_ns > t_arm)
    check("state cleared", app.stop_save is None and app.l_stopsave.cget("text") == "")
    log = app.t_log.get("1.0", "end")
    check("log explains it", "saved progress written - stopping training" in log)
    # training ends some other way while waiting -> disarmed
    app.resume()
    wait(2)
    app.stop_after_save()
    app.stop()
    wait(2)
    check("training stopped while waiting -> disarmed", app.stop_save is None)


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
