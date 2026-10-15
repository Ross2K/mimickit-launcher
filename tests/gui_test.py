"""Drives the launcher under Xvfb against the fake MimicKit tree (or a real clone).
xvfb-run -a -s "-screen 0 1300x900x24" python tests/gui_test.py [MIMICKIT_DIR] [--shot docs/screenshot.png]
"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, subprocess, sys, tempfile, time, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
cfg = os.path.join(tempfile.mkdtemp(), "settings.json")
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = cfg
import tkinter as tk, mimickit_launcher as G
import expect  # per-build expected defaults

mk = (
    os.path.abspath(sys.argv[1])
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--")
    else os.path.join(HERE, "fake_mimickit")
)
shot = sys.argv[sys.argv.index("--shot") + 1] if "--shot" in sys.argv else None
fake = (
    os.path.exists(os.path.join(mk, "mimickit", "run.py"))
    and "stub" in open(os.path.join(mk, "mimickit", "run.py")).read()
)
results = []


def check(name, ok, info=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("  - " + info if info else ""), flush=True)


G.messagebox.showinfo = lambda *a, **k: print("[dialog] info:", a[0])
G.messagebox.showwarning = lambda *a, **k: print("[dialog] warn:", a[0])
G.messagebox.showerror = lambda *a, **k: print("[dialog] error:", a)
G.messagebox.askyesno = lambda *a, **k: (print("[dialog] ask:", a[0]), True)[1]
G.filedialog.askdirectory = lambda **k: mk
root = tk.Tk()
app = G.App(root)


def pgrep():
    return subprocess.run(
        ["pgrep", "-f", "time.sleep\\(600\\)"], capture_output=True, text=True
    ).stdout.split()


def cmd():
    return app.t_cmd.get("1.0", "end").strip()


def s_first():
    check("first-run setup picked MimicKit folder", app.mk() == mk, app.mk())
    check("settings saved", os.path.exists(cfg))
    check(
        "found training configs",
        len(app.train_items) > 0,
        "%d train / %d view: %s / %s"
        % (
            len(app.train_items),
            len(app.view_items),
            [i["name"] for i in app.train_items][:6],
            [i["name"] for i in app.view_items][:6],
        ),
    )
    check("found view configs", len(app.view_items) > 0)
    check("default output folder derived", app.v_out.get().startswith("output/"), app.v_out.get())
    if fake:
        app.v_extra.set("--rand_seed 7")
    app.view()


def s_view():
    c = cmd()
    check(
        "view command",
        "--arg_file args/view" in c and "--visualize true" in c and "newton_engine.yaml" in c,
        c.splitlines()[-1],
    )


def s_train():
    app.stop()
    time.sleep(0.5)
    app.train()


def s_train_check():
    c = cmd()
    check(
        "train command",
        "--visualize false" in c and "--out_dir" in c and "--num_envs" in c,
        c.splitlines()[-1],
    )
    if fake:
        check("extra args appended", c.endswith("--rand_seed 7"))
    app._progress_tick(force=True)
    st = app.l_status.cget("text")
    if fake:
        check(
            "progress parsed from log.txt",
            "Iteration" in st and "samples/hour" in st,
            st.replace("\n", " | "),
        )


def s_stop():
    before = len(pgrep())
    app.stop()
    time.sleep(1.0)
    after = len(pgrep())
    if fake:
        check(
            "STOP killed whole process tree",
            before >= 1 and after == 0,
            "children before %d, after %d" % (before, after),
        )
    else:
        check("STOP ran", True)


def s_resume():
    if fake:
        app.resume()
        c = cmd()
        check(
            "resume command",
            "_resume1/start_model.pt" in c and "--out_dir " + app.v_out.get() + "_resume1" in c,
            c.splitlines()[-1],
        )


def s_watch():
    app.stop()
    time.sleep(0.5)
    if fake:
        app.watch()
        c = cmd()
        check(
            "watch command",
            "--mode test" in c
            and "--num_envs 1" in c
            and "model.pt" in c
            and expect.watch_ok(c, app),
            c.splitlines()[-1],
        )


def s_theme():
    app.v_light.set(True)
    app._toggle_theme()
    root.update()
    check("light mode saved", json.load(open(cfg)).get("light_mode") is True)
    app.v_light.set(False)
    app._toggle_theme()
    root.update()


def s_shot():
    if fake:  # show a finished run's graph in the screenshot
        app.run_dir = app.outdir_abs(app.v_out.get())
    app._progress_tick(force=True)
    root.update()
    if shot:
        time.sleep(0.5)
        root.update()
        from PIL import ImageGrab

        ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).crop(
            (0, 0, root.winfo_width(), root.winfo_height())
        ).save(shot)
        print("screenshot ->", shot)


def s_end():
    app.stop()
    print("RESULT: %d/%d checks passed" % (sum(results), len(results)))
    root.destroy()


seq = [s_first, s_view, s_train, s_train_check, s_stop, s_resume, s_watch, s_theme, s_shot, s_end]
delays = [1500, 2500, 1000, 6000, 1000, 1000, 2500, 1500, 1500, 2500]
t = 0
for f, d in zip(seq, delays):
    t += d
    root.after(t, f)
root.mainloop()
sys.exit(0 if all(results) else 1)
