"""Training settings (edited yaml/clip copies, originals untouched, override args first on the command line, clip end
hold trim/extend, clip start share patch), the dialog incl. 'Coming soon' stubs, and the close/STOP popup actions.
  xvfb-run -a python tests/trainsettings_test.py"""

import json, os, pickle, shutil, sys, tempfile, time, types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.03")
import mimickit_trainsettings as S, mimickit_patches as MP

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


# ---------- a small MimicKit-like tree
mk = tempfile.mkdtemp()
for d in ("args", "data/envs", "data/agents", "data/motions/m", "data/datasets", "mimickit/envs"):
    os.makedirs(os.path.join(mk, d))
open(os.path.join(mk, "mimickit/run.py"), "w").write("")
ENV = """env_name: "deepmimic"
episode_length: 10.0 # seconds
pose_termination: True
pose_termination_dist: 1.0 # m
rand_reset: True
enable_early_termination: True
motion_file: "data/datasets/two.yaml"
"""
AG = """agent_name: "PPO"
model:
  actor_net: "fc"
  action_std: 0.05
actor_optimizer:
    type: "SGD"
    learning_rate: 1e-4
critic_optimizer:
    type: "SGD"
    learning_rate: 1e-4
discount: 0.99
steps_per_iter: 32
"""
open(os.path.join(mk, "data/envs/e.yaml"), "w", newline="").write(
    ENV.replace("\n", "\r\n")
)  # CRLF like a Windows checkout
open(os.path.join(mk, "data/agents/a.yaml"), "w").write(AG)


def clip(n_move, n_hold, loop=0):
    fr = [[0.1 * i, 0.0, 1.0] for i in range(n_move)]
    fr += [list(fr[-1]) for _ in range(n_hold)]
    return dict(loop_mode=loop, fps=30, frames=fr)


pickle.dump(clip(40, 12), open(os.path.join(mk, "data/motions/m/c1.pkl"), "wb"))
pickle.dump(clip(30, 0), open(os.path.join(mk, "data/motions/m/c2.pkl"), "wb"))
pickle.dump(clip(20, 5, loop=1), open(os.path.join(mk, "data/motions/m/loop.pkl"), "wb"))
open(os.path.join(mk, "data/datasets/two.yaml"), "w").write(
    'motions:\n  - file: "data/motions/m/c1.pkl"\n    weight: 2.0\n'
    '  - file: "data/motions/m/c2.pkl"\n    weight: 1.0\n  - file: "data/motions/m/loop.pkl"\n    weight: 1.0\n'
)
open(os.path.join(mk, "args/deepmimic_t_args.txt"), "w").write(
    "--num_envs 64\n--env_config data/envs/e.yaml\n--agent_config data/agents/a.yaml\n"
)
orig = {
    p: open(os.path.join(mk, p), "rb").read()
    for p in (
        "data/envs/e.yaml",
        "data/agents/a.yaml",
        "data/motions/m/c1.pkl",
        "data/datasets/two.yaml",
    )
}

# ---------- yaml line editing
t = open(os.path.join(mk, "data/envs/e.yaml"), newline="").read()
check(
    "read top-level values",
    S.get(t, ("episode_length",)) == 10.0 and S.get(t, ("pose_termination",)) is True,
)
t2 = S.set_(t, ("episode_length",), 4.5)
check(
    "set keeps the comment and CRLF line endings",
    "episode_length: 4.5  # seconds\r\n" in t2 and "\n" not in t2.replace("\r\n", ""),
)
check(
    "missing key is appended",
    S.get(S.set_(t, ("clip_start_share",), 0.3), ("clip_start_share",)) == 0.3,
)
check(
    "nested agent keys",
    S.get(AG, ("critic_optimizer", "learning_rate")) == 1e-4
    and S.get(AG, ("model", "action_std")) == 0.05
    and S.get(
        S.set_(AG, ("critic_optimizer", "learning_rate"), 3e-5),
        ("actor_optimizer", "learning_rate"),
    )
    == 1e-4,
)

# ---------- clips
ci = S.clip_info(os.path.join(mk, "data/motions/m/c1.pkl"))
check(
    "end hold detected (12 frames = 0.40 s)",
    abs(ci["hold"] - 0.4) < 1e-9 and ci["frames"] == 52,
    str(ci),
)
d = S.load_clip(os.path.join(mk, "data/motions/m/c1.pkl"))
check(
    "trim hold to 0.1 s keeps every moving frame",
    S.set_hold(d, 0.1)["frames"][:40] == d["frames"][:40]
    and len(S.set_hold(d, 0.1)["frames"]) == 43,
)
check(
    "extend hold to 1.0 s repeats the final pose", S.hold_frames(S.set_hold(d, 1.0)["frames"]) == 30
)
check(
    "dataset parse keeps weights",
    S.motion_files(mk, "data/datasets/two.yaml")[0] == ("data/motions/m/c1.pkl", 2.0),
)

# ---------- save / override / originals
r = S.save(
    mk,
    "deepmimic_t",
    "data/envs/e.yaml",
    "data/agents/a.yaml",
    {
        ("env", ("episode_length",)): 3.0,
        ("env", ("clip_start_share",)): 0.25,
        ("agent", ("actor_optimizer", "learning_rate")): 5e-5,
    },
    hold=0.2,
)
check(
    "save writes env + agent copies in a new folder",
    os.path.isfile(os.path.join(mk, r["env"])) and os.path.isfile(os.path.join(mk, r["agent"])),
)
check(
    "originals untouched", all(open(os.path.join(mk, p), "rb").read() == b for p, b in orig.items())
)
check(
    "originals backed up once",
    sorted(os.listdir(os.path.join(S.root(mk, "deepmimic_t"), "originals")))
    == ["a.yaml", "e.yaml"],
)
v = S.read_values(mk, r["env"], r["agent"])
check(
    "copy has the new values",
    v[("env", ("episode_length",))] == 3.0
    and v[("agent", ("actor_optimizer", "learning_rate"))] == 5e-5
    and S.get(open(os.path.join(mk, r["env"])).read(), ("clip_start_share",)) == 0.25,
)
mf = S.get(open(os.path.join(mk, r["env"])).read(), ("motion_file",))
files = S.motion_files(mk, mf)
infos = [S.clip_info(os.path.join(mk, f)) for f, _ in files]
check(
    "clip copies: hold 0.2 s, weights kept, looping clip unchanged",
    [round(i["hold"], 3) for i in infos]
    == [0.2, 0.2, round(S.clip_info(os.path.join(mk, "data/motions/m/loop.pkl"))["hold"], 3)]
    and [w for _, w in files] == [2.0, 1.0, 1.0],
    str([(f, i["hold"]) for (f, _), i in zip(files, infos)]),
)
check(
    "override args point at the copy",
    S.override_args(mk, "deepmimic_t") == ["--env_config", r["env"], "--agent_config", r["agent"]],
)
time.sleep(1.1)
first = r["env"]
firsttxt = open(os.path.join(mk, first)).read()
r2 = S.save(mk, "deepmimic_t", r["env"], r["agent"], {("env", ("episode_length",)): 6.0})
check(
    "a second save never rewrites the folder a running run uses",
    r2["env"] != first
    and open(os.path.join(mk, first)).read() == firsttxt
    and S.get(open(os.path.join(mk, r2["env"])).read(), ("episode_length",)) == 6.0
    and S.get(open(os.path.join(mk, r2["env"])).read(), ("clip_start_share",)) == 0.25,
)
S.clear(mk, "deepmimic_t")
check("'Use originals' drops the override", S.override_args(mk, "deepmimic_t") == [])

# ---------- clip start share patch (applied to a copy of the real env file if there is one)
src = next((p for p in ("/tmp/mk/mimickit/envs/deepmimic_env.py",) if os.path.isfile(p)), None)
if src:
    shutil.copy2(src, os.path.join(mk, "mimickit/envs/deepmimic_env.py"))
    check(
        "clipstart patch applies, is idempotent and reverts byte-exact",
        MP.apply(mk, "clipstart").startswith("applied")
        and MP.apply(mk, "clipstart") == "already applied"
        and MP.status(mk, "clipstart") == "applied"
        and MP.revert(mk, "clipstart") == "reverted"
        and open(os.path.join(mk, "mimickit/envs/deepmimic_env.py"), "rb").read()
        == open(src, "rb").read(),
    )
    raw = open(src, newline="").read().replace("\n", "\r\n")
    open(os.path.join(mk, "mimickit/envs/deepmimic_env.py"), "w", newline="").write(raw)
    MP.apply(mk, "clipstart")
    txt = open(os.path.join(mk, "mimickit/envs/deepmimic_env.py"), newline="").read()
    check(
        "clipstart patch on a CRLF file keeps CRLF",
        MP.status(mk, "clipstart") == "applied" and "\n" not in txt.replace("\r\n", ""),
    )
    try:
        import torch

        ns = {}
        code = open(os.path.join(mk, "mimickit/envs/deepmimic_env.py")).read().replace("\r\n", "\n")
        body = code[code.index("    def _sample_motion_times") :]
        body = body[: body.index("\n    def ", 10)]
        exec("import torch\nclass E:\n" + body, ns)
        e = ns["E"]()
        e._device = "cpu"
        e._rand_reset = True
        e._motion_lib = types.SimpleNamespace(
            sample_motions=lambda n: torch.zeros(n, dtype=torch.long),
            sample_time=lambda ids: torch.rand(len(ids)) + 0.5,
        )
        res = {}
        for share in (0.0, 0.3, 1.0):
            e._clip_start_share = share
            _, tt = e._sample_motion_times(20000)
            res[share] = float((tt == 0).float().mean())
        check(
            "patched _sample_motion_times: share of episodes at t=0 matches",
            res[0.0] == 0 and abs(res[0.3] - 0.3) < 0.02 and res[1.0] == 1.0,
            str(res),
        )
    except ImportError:
        print("(torch not installed here: skipped the runtime check of the patch)")
else:
    print("(no MimicKit clone at /tmp/mk: skipped the clipstart patch checks)")

# ---------- GUI: dialog, override wiring, STOP/close popup
import tkinter as tk, mimickit_launcher as G
from expect import PROFILE_PRESETS

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
G.messagebox.askyesno = lambda *a, **k: True
fmk = os.path.join(HERE, "fake_mimickit")
G.filedialog.askdirectory = lambda **k: fmk
root = tk.Tk()
app = G.App(root)
root.update()
app.v_mk.set(mk)
app._save()
app.rescan()
root.update()
if PROFILE_PRESETS:  # an overlay selects its own preset by default; this test is about the dialog
    app.v_train.set("deepmimic_t")
it = app._item("train")
check(
    "dialog opens for the selected config",
    it and it["name"] == "deepmimic_t" and app.train_settings_dialog() is not None,
)
dl = app._ts_dlg
txt = []


def walk(w):
    for c in w.winfo_children():
        try:
            txt.append(str(c.cget("text")))
        except tk.TclError:
            pass
        walk(c)


walk(dl["top"])
alltext = "\n".join(txt)
check(
    "sections: Episodes, Early termination, Learning, Motion clips, Scale, Coming soon",
    all(
        s in alltext
        for s in (
            "Episodes",
            "Early termination",
            "Learning",
            "Motion clips",
            "Scale",
            "Coming soon / needs your input",
        )
    ),
)
check(
    "stubs listed (start speed, handoff, steering goal)", all(n in alltext for n, _ in S.STUBS[:3])
)
check("says when changes apply", "next Start" in alltext and "already going keeps" in alltext)
check(
    "clip list shows lengths and holds",
    "c1.pkl: 1.70 s, end hold 0.40 s" in alltext,
    [l for l in txt if "c1.pkl" in l][:1].__str__(),
)
dl["vars"][("env", ("episode_length",))][0].set("2.5")
app.v_hold.set("0.3")
c = dl["save"]()
root.update()
check(
    "dialog Save writes the override",
    c and S.current(mk, "deepmimic_t")["values"] == {"episode_length": 2.5},
    str(c and c["values"]),
)
cmds = []
app._run = lambda args, kind, out: cmds.append(args)
app.v_out.set("output/t1")
app.train()
a = cmds[-1]
ov = S.override_args(mk, "deepmimic_t")
check(
    "Start puts the override before --arg_file (first value wins in MimicKit)",
    a[:4] == ov and a.index("--arg_file") == 4,
    " ".join(a[:6]),
)
app.train_settings_dialog()
app._ts_dlg["originals"]()
root.update()
app.train()
check(
    "after 'Use originals' the run uses the original files",
    "--env_config" not in cmds[-1][: cmds[-1].index("--arg_file")],
)

asked = []
app._choose_hook = lambda title, text, opts: (asked.append((title, text, opts)), None)[1]


class P:
    pid = 999999

    def poll(self):
        return None


app.proc = P()
res = app._on_close()
labels = [o[0] for o in asked[-1][2]]
check(
    "close popup: one-word action buttons Detach / Stop / Cancel",
    labels == ["Detach", "Stop", "Cancel"],
    str(labels),
)
check(
    "popup text matches the actions (no Yes/No)",
    "Yes" not in asked[-1][1] + "".join(o[2] for o in asked[-1][2])
    and "background" in asked[-1][2][0][2],
)
app._choose_hook = lambda *a: None
destroyed = []
app.root.destroy, real = (lambda: destroyed.append(1)), app.root.destroy
app._on_close()
check("Cancel keeps the launcher open", not destroyed)
stopped = []
app.stop = lambda: stopped.append(1)
app._choose_hook = lambda *a: "stop"
app._on_close()
check("Stop stops training, then closes", stopped and destroyed)
destroyed.clear()
stopped.clear()
app._choose_hook = lambda *a: "detach"
app._on_close()
check("Detach closes and leaves training running", destroyed and not stopped)
del app._choose_hook
app.root.destroy = real
# the real themed dialog: buttons and dark colours
root.after(300, lambda: app._choose_dlg.destroy())
app.choose(
    "t",
    "x",
    [("Detach", "detach", "h1"), ("Stop", "stop", "h2"), ("Cancel", None, "h3")],
    default="detach",
    danger="stop",
)
check(
    "themed dialog runs (dark bg)",
    G.T["bg"].lower() in ("#1e1e1e", "#121212", "#202020") or not app.v_light.get(),
    G.T["bg"],
)
app.proc = None
root.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
