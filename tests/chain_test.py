"""Run chains across output folders ("Continue from run"), parent-link walking for time + history, and the
chronological view env yaml.   xvfb-run -a python tests/chain_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from fake_mk import fake_mk  # noqa: E402 - temp copy: test output never lands in the repo
import json, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.05")
import tkinter as tk, mimickit_launcher as G
import expect  # per-build expected defaults

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: print("[dialog]", a))
G.messagebox.askyesno = lambda *a, **k: True
mk = fake_mk()
G.filedialog.askdirectory = lambda **k: mk
shutil.rmtree(os.path.join(mk, "output"), ignore_errors=True)
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


# ---- pure functions
t = tempfile.mkdtemp()
a, b, c = (os.path.join(t, x) for x in ("a", "a_resume1", "x"))
for d in (a, b, c):
    os.makedirs(d)
check("legacy _resumeN falls back to its own chain", G.run_chain(b) == [a, b])
G.write_time(c, dict(seconds=50, sessions=3, parent=b))
check("cross-folder parent followed recursively", G.run_chain(c) == [a, b, c])
G.write_time(a, dict(seconds=10, sessions=1, parent=c))
check("cycle-safe", len(G.run_chain(c)) == 3, str(G.run_chain(c)))
os.remove(os.path.join(a, G.TIME_FILE))
json.dump(
    dict(parent=os.path.join("/nowhere", "a_resume1")), open(os.path.join(c, G.LINK_FILE), "w")
)
os.remove(os.path.join(c, G.TIME_FILE))
check("moved MimicKit folder: parent found by name next to it", G.run_chain(c) == [a, b, c])
# ---- view env yaml
env = "data/envs/deepmimic_humanoid_env.yaml"
dst = os.path.join(mk, "output", "_t", "view_env.yaml")
orig = open(os.path.join(mk, env)).read()
G.make_view_env(mk, env, dst)
v = open(dst).read()
check(
    "view yaml: rand_reset/early termination/pose termination off",
    all(
        k in v
        for k in ("rand_reset: False", "enable_early_termination: False", "pose_termination: False")
    ),
)
check("view yaml: long episode", "episode_length: 1000" in v)
check(
    "view yaml keeps everything else",
    "motion_file:" in v and 'env_name: "deepmimic"' in v and v.count("\nrand_reset:") == 1,
)
check("data folder untouched", open(os.path.join(mk, env)).read() == orig)
check("missing env -> None", G.make_view_env(mk, "data/envs/nope.yaml", dst + "2") is None)
# ---- GUI: source chain, continue into an empty folder and into a used one
root = tk.Tk()
app = G.App(root)


def wait(sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        root.update()
        time.sleep(0.05)


def wait_model(d, sec=20):
    t0 = time.time()
    while time.time() - t0 < sec and not os.path.exists(os.path.join(d, "model.pt")):
        wait(0.2)


def steps():
    wait(1.5)
    app.v_out.set("output/src")
    src = app.outdir_abs("output/src")
    app.train()
    wait_model(src)
    wait(2)
    app.stop()
    wait(1.5)
    app.resume()
    wait_model(src + "_resume1")
    wait(2)
    app.stop()
    wait(1.5)
    tot, ses = G.chain_total(G.run_chain(src + "_resume1"))
    check("source chain has 2 sessions", ses == 2, "%.1f s, %d" % (tot, ses))
    G.filedialog.askdirectory = lambda **k: src  # user picks the source's base folder
    app.v_out.set("output/both")
    both = app.outdir_abs("output/both")
    app.continue_from()
    wait(1)
    check(
        "continue into empty folder uses it directly",
        app.run_dir == both and os.path.exists(os.path.join(both, "start_model.pt")),
    )
    j = G.read_time(both)
    l = json.load(open(os.path.join(both, G.LINK_FILE)))
    check(
        "parent = newest folder of the source chain",
        j["parent"] == src + "_resume1" and l["parent"] == src + "_resume1",
        str(j),
    )
    check("time + sessions carried", abs(j["seconds"] - tot) < 1.5 and j["sessions"] == 3, str(j))
    check(
        "start_model.pt is the newest source model",
        open(os.path.join(both, "start_model.pt"), "rb").read()
        == open(os.path.join(src + "_resume1", "model.pt"), "rb").read(),
    )
    check(
        "command continues from start_model.pt",
        "--model_file output/both/start_model.pt" in app.t_cmd.get("1.0", "end"),
    )
    wait(4)
    app._progress_tick(force=True)
    check(
        "charts: source chain shown as earlier sessions",
        "+2 earlier sessions" in app.prog_frame.cget("text"),
        app.prog_frame.cget("text"),
    )
    lab = [l.get_label() for l in app.ax1.get_lines()]
    gids = [l.get_gid() for l in app.ax1.get_lines()]
    check("dotted bridge drawn between sessions", "bridge" in gids, str(gids))
    app.stop()
    wait(1.5)
    tot2, ses2 = G.chain_total(G.run_chain(both))
    st = app._tt_total()
    check(
        "idle total follows the cross-folder chain",
        ses2 == 3 and abs(st[0] - tot2) < 0.01 and tot2 > tot + 3,
        "%.1f -> %.1f" % (tot, tot2),
    )
    # continue into a used folder -> its next _resumeN (like output/x continuing as output/x_resumeN with another env)
    G.filedialog.askdirectory = lambda **k: both
    app.v_out.set("output/src")
    app.continue_from()
    wait(1)
    r2 = src + "_resume2"
    check("continue into used folder -> next _resumeN", app.run_dir == r2, str(app.run_dir))
    ch = G.run_chain(r2)
    check(
        "chain src -> r1 -> both -> r2",
        ch == [src, src + "_resume1", both, r2],
        str([os.path.basename(x) for x in ch]),
    )
    check("sessions = 4", G.read_time(r2)["sessions"] == 4)
    wait(3)
    app._progress_tick(force=True)
    check(
        "charts: 3 earlier sessions",
        "+3 earlier sessions" in app.prog_frame.cget("text"),
        app.prog_frame.cget("text"),
    )
    app.stop()
    wait(1.5)
    # watch uses the generated chronological env, 1 env
    app.watch()
    c = app.t_cmd.get("1.0", "end")
    check(
        "watch: generated view env (or the preset's args) + 1 env",
        expect.watch_ok(c, app) and "--num_envs 1" in c,
        c.strip().splitlines()[-1],
    )
    app.stop()
    wait(1)


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
