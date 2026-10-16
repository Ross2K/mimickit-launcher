"""'Stop after next save': armed while training, status + cancel, stops right after the next model.pt save.
xvfb-run -a python tests/stopsave_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from fake_mk import fake_mk  # noqa: E402 - temp copy: test output never lands in the repo
import os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.02")
import tempfile
import tkinter as tk, mimickit_launcher as G

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
    wait(3, lambda: app.stop_save is None)
    check("state cleared once the stop is verified", app.stop_save is None and app.l_stopsave.cget("text") == "")
    log = app.t_log.get("1.0", "end")
    check("log explains it", "saved progress written (model.pt was rewritten) - stopping training" in log)
    check("log confirms the process ended", "verified: process ended" in log)
    # refusals are shown under the button (not only in the log) and returned to the caller (phone)
    ok_, msg = app.stop_after_save()
    check("refusal when idle returned", ok_ is False and "no training is running" in msg, msg)
    check("refusal shown under the button", "no training is running" in app.l_stopsave.cget("text")
          and app.l_stopsave.winfo_manager() == "pack")
    # training ends some other way while waiting -> disarmed
    app.resume()
    wait(2)
    app.stop_after_save()
    app.stop()
    wait(2)
    check("training stopped while waiting -> disarmed", app.stop_save is None)
    # an exception inside the poll loop no longer kills it silently
    app.resume()
    wait(3)
    app.stop_after_save()
    real = app.stop_save.saved
    boom = {"n": 0}

    def flaky():
        boom["n"] += 1
        if boom["n"] == 1:
            raise RuntimeError("simulated poll failure")
        return real()

    app.stop_save.saved = flaky
    proc = app.proc
    wait(30, lambda: proc.poll() is not None)
    log = app.t_log.get("1.0", "end")
    check("poll error shown + logged, loop kept going, training stopped after the save",
          "simulated poll failure" in log and proc.poll() is not None, boom["n"])
    wait(2)
    # the stop didn't reach the process (first stop() does nothing) -> verified, retried, then it stops
    app.STOP_VERIFY_S = 2
    app.resume()
    wait(3)
    real_stop = app.stop
    calls = {"n": 0}

    def dud():
        calls["n"] += 1
        if calls["n"] == 1:
            app._append("[test] first stop swallowed\n")
            return
        return real_stop()

    app.stop = dud
    app.stop_after_save()
    proc = app.proc
    wait(40, lambda: proc.poll() is not None)
    app.stop = real_stop
    log = app.t_log.get("1.0", "end")
    check("stop that didn't take is retried", "still running 2 s after the stop - stopping again" in log and proc.poll() is not None,
          calls["n"])
    wait(2)
    # log.txt-only signal: model.pt change invisible (e.g. odd file system) -> log row + grace still stops it
    G.SaveWatch = None
    from mkl import stopsave as SS
    d = tempfile.mkdtemp()
    open(os.path.join(d, "log.txt"), "w").write("a\n")
    open(os.path.join(d, "model.pt"), "w").write("x")
    clock = [100.0]
    w = SS.SaveWatch(d, now=lambda: clock[0])
    w.model.saved = lambda: False
    open(os.path.join(d, "log.txt"), "a").write("b\n")
    r1 = w.saved()
    clock[0] += SS.SaveWatch.LOG_GRACE_S + 1
    r2 = w.saved()
    check("log.txt save row + grace counts as a save", r1 is False and r2 is True and "log.txt" in w.why, w.why)
    # every Tk callback error is caught (pythonw has no console)
    root.report_callback_exception(ZeroDivisionError, ZeroDivisionError("x"), None)
    check("Tk callback errors reach the log panel", "Launcher error in button/timer: ZeroDivisionError" in app.t_log.get("1.0", "end"))


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
