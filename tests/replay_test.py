"""Runs the stub trainer (154 iterations at 1024 envs = 5.046 M samples, printed slowly as a console table) and checks
the charts/status use the console while it runs, then chart_history.csv, then log.txt (attach mode, a one-row
tests/data/replay_log.txt with Samples_Per_Second) once the window no longer owns the run.
xvfb-run -a python tests/replay_test.py [--shot out.png]
Set STUB_REPLAY=console.txt (+ STUB_LOG=log.txt) to replay a real capture instead; the iteration/sample checks
assume the 154-iteration default."""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.setdefault("STUB_ITERS", "154")
os.environ.setdefault("STUB_SLEEP", "0.05")  # ~8 s of output: the mid-run check sees a partial table
LOG_FIXTURE = os.path.join(HERE, "data", "replay_log.txt")
import shutil, tkinter as tk, mimickit_launcher as G

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: print("[dialog]", a))
G.messagebox.askyesno = lambda *a, **k: True
mk = os.path.join(HERE, "fake_mimickit")
G.filedialog.askdirectory = lambda **k: mk
shot = sys.argv[sys.argv.index("--shot") + 1] if "--shot" in sys.argv else None
root = tk.Tk()
app = G.App(root)
ok = []


def check(n, c, i=""):
    ok.append(c)
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


def go():
    app.v_envs.set(1024)
    app.train()


mid = {}


def midcheck():  # while the child is still printing slowly: data must already be arriving (no pipe buffering)
    app._progress_tick(force=True)
    mid["rows"] = app.live.rows()
    check(
        "rows arrive while child runs (unbuffered pipe)",
        0 < mid["rows"] < 154,
        "%d rows at mid-run" % mid["rows"],
    )
    check(
        "chart title shows console source",
        "data: console" in app.prog_frame.cget("text"),
        app.prog_frame.cget("text"),
    )
    check("version in title", G.VERSION in root.title(), root.title())


def verify():
    app._progress_tick(force=True)
    st = app.l_status.cget("text")
    check("live console rows parsed", app.live.rows() >= 150, "%d rows" % app.live.rows())
    check(
        "status from console, not log.txt",
        "from console" in st and "Iteration 153" in st,
        st.split("\n")[1],
    )
    l1 = app.ax1.get_lines()
    l2 = app.ax2.get_lines()
    check(
        "top chart: smooth lines, no per-point markers",
        len(l1) == 2 and l1[0].get_marker() in ("None", "", None) and len(l1[0].get_xdata()) >= 150,
    )
    check(
        "x = samples (millions)",
        abs(max(l1[0].get_xdata()) - 5.046) < 0.01,
        "max x %.3f" % max(l1[0].get_xdata()),
    )
    check("bottom chart has rate data", len(l2) == 1 and len(l2[0].get_xdata()) >= 150)
    if shot:
        root.update()
        time.sleep(0.5)
        root.update()
        from PIL import ImageGrab

        ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).crop(
            (0, 0, root.winfo_width(), root.winfo_height())
        ).save(shot)
    app.stop()
    # attach-mode: a window that didn't start the run falls back to the lagging log.txt
    app.live_dir = None
    app._progress_tick(force=True)
    st = app.l_status.cget("text")
    check(
        "attach mode prefers chart_history.csv",
        "from chart_history.csv" in st and "Iteration 153" in st,
    )
    for fn in (G.HIST_FILE, G.CONSOLE_FILE):
        p = os.path.join(app.run_dir, fn)
        if os.path.exists(p):
            os.remove(p)
    shutil.copy(LOG_FIXTURE, os.path.join(app.run_dir, "log.txt"))  # a lagging log.txt: 1 row so far
    app._progress_tick(force=True)
    st = app.l_status.cget("text")
    check(
        "attach mode uses log.txt (1 row) + lag note",
        "from log.txt" in st and "Iteration 0" in st and "may lag" in st,
        st.replace("\n", " | "),
    )
    l1 = app.ax1.get_lines()
    check(
        "single log point is visible (marker)",
        len(l1) == 2 and len(l1[0].get_xdata()) == 1 and l1[0].get_marker() == "o",
    )
    check("rate from Samples_Per_Second", "3.78 M samples/hour" in st)
    print("RESULT: %d/%d" % (sum(ok), len(ok)))
    root.destroy()


T = float(os.environ.get("VERIFY_AT", "14"))
root.after(1500, go)
root.after(int(T * 500), midcheck)
root.after(int(T * 1000), verify)
root.mainloop()
sys.exit(0 if all(ok) else 1)
