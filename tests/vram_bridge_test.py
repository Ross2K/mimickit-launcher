"""a0.1.5: VRAM bar (fake nvidia-smi) and dotted session bridges on a 5-session chain.
xvfb-run -a python tests/vram_bridge_test.py [--shot out.png]"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, shutil, stat, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
bindir = tempfile.mkdtemp()
smi = os.path.join(bindir, "nvidia-smi")
valf = os.path.join(bindir, "used")
open(smi, "w").write('#!/bin/sh\necho "NVIDIA GeForce GPU, $(cat %s), 8190, 97"\n' % valf)
os.chmod(smi, 0o755)
open(valf, "w").write("5427")
os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]
import tkinter as tk, mimickit_launcher as G

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
mk = os.path.join(HERE, "fake_mimickit")
G.filedialog.askdirectory = lambda **k: mk
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


def bar():
    c = app.c_vram
    f = c.find_withtag("fill")
    t = c.find_withtag("text")
    return (
        (c.itemcget(f[0], "fill") if f else None),
        (c.itemcget(t[0], "text") if t else None),
        [c.itemcget(i, "text") for i in c.find_all() if c.type(i) == "text"],
    )


def steps():
    wait(1.5)
    col, txt, _ = bar()
    check(
        "VRAM bar from nvidia-smi, green < 75%",
        col == G.App.VRAM_COLORS["ok"] and txt == "5.3 / 8.0 GB",
        "%s %s" % (col, txt),
    )
    open(valf, "w").write("6500")
    wait(5.5)
    col, txt, _ = bar()
    check(
        "amber at 75-90%",
        col == G.App.VRAM_COLORS["warn"] and txt == "6.3 / 8.0 GB",
        "%s %s" % (col, txt),
    )
    open(valf, "w").write("7700")
    wait(5.5)
    col, txt, _ = bar()
    check("red > 90%", col == G.App.VRAM_COLORS["bad"], "%s %s" % (col, txt))
    app._set_vram(None, None)
    col, txt, alltxt = bar()
    check(
        "no nvidia-smi -> greyed 'no data'",
        col is None
        and "VRAM: no data" in alltxt
        and app.c_vram.itemcget(app.c_vram.find_all()[-1], "fill") == G.T["dim"],
    )
    app._set_vram("6000", "8190")
    # 5-session chain: 4 old 1-row log.txt sessions + current with a CSV
    root_dir = os.path.join(mk, "output")
    shutil.rmtree(root_dir, ignore_errors=True)
    names = ["bt", "bt_resume1", "bt_resume2", "bt_resume3", "bt_resume4"]
    for i, n in enumerate(names):
        d = os.path.join(root_dir, n)
        os.makedirs(d)
        if i < 4:
            open(os.path.join(d, "log.txt"), "w").write(
                "Iteration Wall_Time Samples Train_Return Test_Return 0 0.04 163840 %g 11.3"
                % (5.7 + i * 0.1)
            )
        else:
            G.append_history(
                d,
                {
                    "Iteration": [0, 1, 2],
                    "Samples": [262144, 524288, 786432],
                    "Wall_Time": [0.0656, 0.0843, 0.104],
                    "Train_Return": [5.75, 5.71, 9.02],
                    "Test_Return": [11.4, 11.4, 11.4],
                },
                0,
            )
    app.v_out.set("output/bt")
    app.run_dir = os.path.join(root_dir, "bt_resume4")
    app._progress_tick(force=True)
    b1 = [l for l in app.ax1.get_lines() if l.get_gid() == "bridge"]
    b2 = [l for l in app.ax2.get_lines() if l.get_gid() == "bridge"]
    check(
        "dotted bridges on return chart (4 transitions x 2 series)",
        len(b1) == 8 and all(l.get_linestyle() == ":" for l in b1),
        "%d" % len(b1),
    )
    check("dotted bridges on rate chart", len(b2) == 4, "%d" % len(b2))
    last = [
        l
        for l in b1
        if abs(l.get_xdata()[1] - (4 * 0.16384 + 0.262144)) < 1e-9 and l.get_ydata()[1] == 5.75
    ]
    check(
        "last bridge: end of resume3 -> first point of current session",
        len(last) == 1
        and abs(last[0].get_xdata()[0] - 4 * 0.16384) < 1e-9
        and abs(last[0].get_ydata()[0] - 6.0) < 1e-9,
    )
    check(
        "no vertical session markers any more",
        not any(
            len(set(l.get_xdata())) == 1 and len(l.get_xdata()) == 2 and l.get_gid() != "bridge"
            for l in app.ax1.get_lines()
        ),
    )
    cur = [l for l in app.ax1.get_lines() if l.get_label() == "Train return"]
    check(
        "current session coloured, earlier grey",
        cur
        and cur[0].get_color() == G.T["line1"]
        and all(
            l.get_color() == G.T["dim"]
            for l in app.ax1.get_lines()
            if l.get_label() not in ("Train return", "Test return")
        ),
    )
    app.v_light.set(True)
    app._toggle_theme()
    wait(0.3)
    app.v_light.set(False)
    app._toggle_theme()
    wait(0.3)
    check("bar survives theme toggle", bar()[1] == "5.9 / 8.0 GB")
    if shot:
        wait(0.5)
        from PIL import ImageGrab

        ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).crop(
            (0, 0, root.winfo_width(), root.winfo_height())
        ).save(shot)
    shutil.rmtree(root_dir, ignore_errors=True)
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
        root.destroy()


root.after(100, safe)
root.mainloop()
sys.exit(0 if all(ok) else 1)
