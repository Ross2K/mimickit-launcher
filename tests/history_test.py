"""Chart history across resumes: start, resume, second resume, log.txt backfill.  xvfb-run -a python tests/history_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="30", STUB_SLEEP="0.03")
import tkinter as tk, mimickit_launcher as G

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: print("[dialog]", a))
G.messagebox.askyesno = lambda *a, **k: True
mk = os.path.join(HERE, "fake_mimickit")
G.filedialog.askdirectory = lambda **k: mk
shutil.rmtree(os.path.join(mk, "output"), ignore_errors=True)
shot = sys.argv[sys.argv.index("--shot") + 1] if "--shot" in sys.argv else None
root = tk.Tk()
app = G.App(root)
ok = []


def check(n, c, i=""):
    ok.append(c)
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


def wait(sec):
    t = time.time()
    while time.time() - t < sec:
        root.update()
        time.sleep(0.05)


def finish():
    while app.proc and app.proc.poll() is None:
        wait(0.2)
    wait(1.5)


def lines(ax, grey):
    return (
        [
            l
            for l in ax.get_lines()
            if (l.get_color() == G.THEMES["dark"]["dim"]) == grey and l.get_linestyle() != ":"
        ]
        if hasattr(G, "THEMES")
        else []
    )


def rows(f):
    return len(open(f).read().splitlines()) - 1


def steps():
    wait(1.5)
    app.v_envs.set(1024)
    app.v_out.set("output/hist")
    base = app.outdir_abs("output/hist")
    per = 30 * 1024 * 32 / 1e6
    app.train()
    finish()
    f0 = os.path.join(base, G.HIST_FILE)
    check(
        "history CSV written for first run",
        os.path.exists(f0) and rows(f0) == 30,
        "%d rows" % rows(f0) if os.path.exists(f0) else "missing",
    )
    app.resume()
    finish()
    r1 = base + "_resume1"
    check("resume1 history CSV", rows(os.path.join(r1, G.HIST_FILE)) == 30)
    check(
        "console_log.txt captured per session",
        all(
            "|            Iteration |" in open(os.path.join(x, G.CONSOLE_FILE)).read()
            for x in (base, r1)
        ),
    )
    td = tempfile.mkdtemp()
    G.append_history(td, {"Iteration": [3], "Samples": [1048576.0]}, 0)
    check("CSV keeps full precision", "1048576" in open(os.path.join(td, G.HIST_FILE)).read())
    app._progress_tick(force=True)
    g, c = lines(app.ax1, True), lines(app.ax1, False)
    xmax = max(max(l.get_xdata()) for l in c)
    check(
        "resume1: earlier session grey + current coloured",
        len(g) == 2 and len(c) == 2,
        "grey %d, colour %d" % (len(g), len(c)),
    )
    check(
        "resume1: x offset cumulative",
        abs(xmax - 2 * per) < 1e-6
        and abs(min(min(l.get_xdata()) for l in c) - (per + 1024 * 32 / 1e6)) < 1e-6,
        "max x %.4f (expect %.4f)" % (xmax, 2 * per),
    )
    check(
        "legend notes earlier sessions",
        "earlier sessions" in [t.get_text() for t in app.ax1.get_legend().get_texts()],
    )
    app.resume()
    finish()
    g, c = lines(app.ax1, True), lines(app.ax1, False)
    xmax = max(max(l.get_xdata()) for l in c)
    check(
        "resume2: two earlier sessions grey, x up to 3 runs",
        len(g) == 4 and abs(xmax - 3 * per) < 1e-6,
        "grey %d, max x %.4f" % (len(g), xmax),
    )
    check("rate chart has grey history too", len(lines(app.ax2, True)) == 2)
    check(
        "frame title mentions earlier sessions",
        "+2 earlier sessions" in app.prog_frame.cget("text"),
        app.prog_frame.cget("text"),
    )
    # old run without history file: backfill from log.txt
    check(
        "grey history clearly visible",
        all(l.get_linewidth() >= 1.5 and l.get_alpha() >= 0.6 for l in g),
    )
    os.remove(f0)
    app._progress_tick(force=True)
    g = lines(app.ax1, True)
    check(
        "rebuild from console_log.txt when CSV missing",
        len(g) == 4 and len(g[0].get_xdata()) == 30,
        "%d pts" % len(g[0].get_xdata()),
    )
    os.remove(os.path.join(base, G.CONSOLE_FILE))
    app._progress_tick(force=True)
    g = lines(app.ax1, True)
    check(
        "backfill from log.txt when both missing",
        len(g) == 4 and len(g[0].get_xdata()) == 30,
        "%d pts" % len(g[0].get_xdata()),
    )
    open(os.path.join(base, "log.txt"), "w").write(
        "Iteration Wall_Time Samples Train_Return 0 0.01 32768 3.5"
    )  # old session with only log.txt: 1 row
    app._progress_tick(force=True)
    g = lines(app.ax1, True)
    st = app.l_status.cget("text")
    check(
        "1-row old session: offset by its own final samples, plain label",
        abs(min(min(l.get_xdata()) for l in lines(app.ax1, False)) - (0.032768 + per + 0.032768))
        < 1e-6
        and "earlier sessions" in [t.get_text() for t in app.ax1.get_legend().get_texts()]
        and "a0.1" not in st,
    )
    if shot:
        wait(0.5)
        from PIL import ImageGrab

        ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).crop(
            (0, 0, root.winfo_width(), root.winfo_height())
        ).save(shot)
    print("RESULT: %d/%d" % (sum(ok), len(ok)), flush=True)
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
