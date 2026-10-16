"""Total-training-time persistence: start, stop, resume, external kill, GUI-crash bound, legacy seeding, watch not counted.
xvfb-run -a python tests/time_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import json, os, shutil, signal, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.2", STUB_TEST_SECS="3")
import tkinter as tk, mimickit_launcher as G

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: print("[dialog]", a))
G.messagebox.askyesno = lambda *a, **k: True
mk = os.path.join(HERE, "fake_mimickit")
G.filedialog.askdirectory = lambda **k: mk
shutil.rmtree(os.path.join(mk, "output"), ignore_errors=True)
root = tk.Tk()
app = G.App(root)
ok = []


def check(n, c, i=""):
    ok.append(c)
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


def J(d):
    return json.load(open(os.path.join(d, G.TIME_FILE)))


def wait(sec):
    t = time.time()
    while time.time() - t < sec:
        root.update()
        time.sleep(0.05)


def status():
    app._progress_tick(force=True)
    return app.l_status.cget("text")


def steps():
    wait(1.5)
    app.v_out.set("output/tt")
    base = app.outdir_abs("output/tt")
    # 1) start + stop
    app.train()
    wait(4)
    app._progress_tick()  # periodic save
    j = J(base)
    check("periodic save while training", 3 <= j["seconds"] <= 5 and j["sessions"] == 1, str(j))
    st = status()
    check(
        "status shows session + total lines",
        "(this session)" in st and "(total" in st,
        st.split("\n")[-2:].__str__(),
    )
    wait(2)
    app.stop()
    wait(1.5)
    s1 = J(base)["seconds"]
    check("stop saves final time", 5.5 <= s1 <= 7.5, "%.1f s" % s1)
    st = status()
    check("idle shows chain total", "Total training time 0:00:0" in st, st.split("\n")[-1])
    # 2) watch is not counted
    app.watch()
    wait(4)
    check("watch not counted", J(base)["seconds"] == s1)
    app.stop()
    wait(1)
    # 3) resume carries total; external kill (crash) still saves
    app.resume()
    wait(1)
    r1 = base + "_resume1"
    j = J(r1)
    check(
        "resume carries total + parent",
        abs(j["seconds"] - s1) < 1.5 and j["sessions"] == 2 and j["parent"] == base,
        str(j),
    )
    wait(3)
    os.killpg(app.proc.pid, signal.SIGKILL)
    wait(2)  # child dies on its own (crash / closed console)
    s2 = J(r1)["seconds"]
    check("killed child: reader saved final", s1 + 3 <= s2 <= s1 + 5.5, "%.1f s" % s2)
    # 4) GUI crash bound: no final save, only periodic ticks -> loss <= one tick interval
    app.resume()
    r2 = base + "_resume2"
    wait(3)
    app._progress_tick()
    t_tick = time.time()
    wait(2)
    app.tt_save_backup = app._tt_save
    app._tt_save = lambda final=False: None  # simulate GUI dying: no more saves
    os.killpg(app.proc.pid, signal.SIGKILL)
    wait(1.5)
    real = s2 + 5
    saved = J(r2)["seconds"]
    check(
        "GUI-crash loss bounded by last tick",
        -0.2 <= real - saved <= 2.6 + 1,  # a0.8.3: real is an estimate (sleep timing), allow 0.2 s
        "saved %.1f vs real ~%.1f" % (saved, real),
    )
    app._tt_save = app.tt_save_backup
    app.tt = None
    # 5) legacy chain without JSON: seed from log.txt Wall_Time (hours)
    leg = app.outdir_abs("output/legacy")
    os.makedirs(leg, exist_ok=True)
    os.makedirs(leg + "_resume1", exist_ok=True)
    open(os.path.join(leg, "model.pt"), "wb").write(b"x")
    open(os.path.join(leg, "log.txt"), "w").write(
        "Iteration Wall_Time Samples 0 0.25 100 1 0.5 200"
    )
    open(os.path.join(leg + "_resume1", "log.txt"), "w").write(
        "Iteration Wall_Time Samples\n0 0.1 10\n1 0.25 20\n"
    )
    app.v_out.set("output/legacy")
    st = status()
    check(
        "legacy seeded from Wall_Time (0.5h + 0.25h)",
        "Total training time 0:45:00" in st,
        st.split("\n")[-1],
    )
    app.resume()
    wait(1)
    j = J(leg + "_resume2")
    check("resume of legacy carries 2700 s", abs(j["seconds"] - 2700) < 1.5, str(j))
    app.stop()
    wait(1)
    print("RESULT: %d/%d" % (sum(ok), len(ok)))
    root.destroy()


def safe():
    try:
        steps()
    except Exception:
        import traceback

        traceback.print_exc()
        ok.append(False)
        print("RESULT: %d/%d" % (sum(ok), len(ok)))
        app.stop()
        root.destroy()


root.after(100, safe)
root.mainloop()
shutil.rmtree(os.path.join(mk, "output"), ignore_errors=True)
sys.exit(0 if all(ok) else 1)
