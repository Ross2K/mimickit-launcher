"""Presets that need installed files ('requires', a0.8.0): listed but greyed with a plain hint until the files exist
(PC buttons, refusals, phone list + refusal); then usable. Preview clip choice: preset default, saved choice, the
Clips... dialog, --clips on the preview command, phone render clip check.   xvfb-run -a python tests/preset_req_test.py"""

import result_exit  # noqa: F401
import os, shutil, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.02")
import tkinter as tk, mimickit_launcher as G
from mkl import core, process
from mimickit_remote import hash_pin

DLG = []
for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: DLG.append(a))
G.messagebox.askyesno = lambda *a, **k: True
mk = os.path.join(tempfile.mkdtemp(), "mk")
shutil.copytree(os.path.join(HERE, "fake_mimickit"), mk, ignore=shutil.ignore_patterns("output"))
G.filedialog.askdirectory = lambda **k: mk
HINT = "Run install_widget.bat once (copies the files into MimicKit)."
REQ = ["args/widget_args.txt", "data/envs/widget_env.yaml", "data/datasets/widget_set.yaml"]
PRE = [dict(name="Widget (walk)", kind="train", file="args/widget_args.txt", out="output/widget", num_envs=128,
            help="A test preset.", requires=REQ, hint=HINT, preview_clips=["walk_b", "run_a", "nope"]),
       dict(name="Widget clips", kind="view", file="args/widget_view_args.txt", requires=REQ, hint=HINT)]
core.PRESETS[:] = PRE
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


def btn(k):
    return not app.run_btns[k].instate(["disabled"])


wait(2)
app.v_mk.set(mk)
app.rescan()
DLG.clear()
app.v_train.set("Widget (walk)")
app._train_changed()
it = app._item("train")
check("missing preset still listed", it is not None and it["missing"] == HINT)
check("hint shown in plain words", "NOT INSTALLED" in app.l_preset_help.cget("text") and HINT in app.l_preset_help.cget("text"))
check("Start / Resume / Continue / Watch greyed", not any(btn(k) for k in ("train", "resume", "continue", "watch")))
app.train()
check("start refused with the hint (dialog + log)", DLG and HINT in str(DLG[-1]) and "refused: Widget" in app.t_log.get("1.0", "end"))
app.v_view.set("Widget clips")
app._view_changed()
check("view preset greyed too", not btn("view"))
app.s.setdefault("remote", {}).update(allow_control=True, pin_hash=hash_pin("2468"))
ctl = app._control()
SES = ctl.login("2468")[1]["session"]
app._progress_tick(force=True)
wait(0.5)
ui = app.snap["runs_ui"]
check("phone list includes it, marked not installed", "Widget (walk)" in ui["configs"] and ui["missing"].get("Widget (walk)") == HINT)
box = {}


def ph(action, params):
    def run():
        c, b = ctl.new_nonce(SES, action)
        box["r"] = ctl.act(SES, b["nonce"], action, params)
    t = threading.Thread(target=run)
    t.start()
    wait(10, lambda: not t.is_alive())
    return box["r"]


r = ph("start_train", dict(config="Widget (walk)", num_envs=128, out="output/widget"))
check("phone start refused with the hint", r[0] == 409 and HINT in r[1]["error"], r)
# install the files
os.makedirs(os.path.join(mk, "data", "datasets"), exist_ok=True)
open(os.path.join(mk, REQ[0]), "w").write("--env_config data/envs/widget_env.yaml\n--out_dir output/widget\n")
open(os.path.join(mk, "args/widget_view_args.txt"), "w").write("--mode test\n--env_config data/envs/widget_env.yaml\n")
open(os.path.join(mk, REQ[1]), "w").write('env_name: "task_steering"\nmotion_file: "data/datasets/widget_set.yaml"\n')
clips = ["walk_a", "walk_b", "run_a", "run_b", "attack_a", "idle", "sprint_a"]
open(os.path.join(mk, REQ[2]), "w").write("motions:\n" + "".join(
    '  - file: "data/motions/w/w_%s.pkl"   # x\n    weight: 1.0\n' % c for c in clips))
app.rescan()
app.v_train.set("Widget (walk)")
app._train_changed()
it = app._item("train")
check("installed -> usable", not it["missing"] and btn("train") and btn("watch"), it.get("missing"))
check("preset help shown again", "A test preset." in app.l_preset_help.cget("text"))
check("clip list read from the dataset", app._clips_of(it) == ["w_" + c for c in clips], app._clips_of(it))
check("default clips = the preset's (missing names skipped)", app._chosen_clips(it) == ["w_walk_b", "w_run_a"], app._chosen_clips(it))
app.clips_dialog()
wait(0.5)
vars_, save, default = app._clipdlg_vars
for n in vars_:
    vars_[n].set(n in ("w_idle", "w_sprint_a", "w_walk_a"))
save()
check("Clips... saves the choice for this config", app._chosen_clips(it) == ["w_idle", "w_sprint_a", "w_walk_a"]
      or set(app._chosen_clips(it)) == {"w_idle", "w_sprint_a", "w_walk_a"}, app._chosen_clips(it))
CMD = []
os.makedirs(os.path.join(mk, "output", "widget"), exist_ok=True)
open(os.path.join(mk, "output", "widget", "model.pt"), "wb").write(b"x")


class P:
    pid = 1
    returncode = 0

    def poll(self):
        return 0


app._spawn_detached = lambda cmd, logp, env=None: CMD.append(cmd) or P()
app.preview()
wait(1)
cmd = CMD[-1] if CMD else []
check("preview command carries --clips", "--clips" in cmd and set(cmd[cmd.index("--clips") + 1].split(",")) == {"w_idle", "w_sprint_a", "w_walk_a"}, cmd)
app.preview_proc = None
app._progress_tick(force=True)
wait(0.5)
check("phone gets the clip list + choice", app.snap["clips"]["all"] == ["w_" + c for c in clips] and len(app.snap["clips"]["chosen"]) == 3)
ok1, m1 = app._remote_render(["w_run_b", "nope"])
check("phone render with an unknown clip refused", not ok1, m1)
ok2, m2 = app._remote_render(["w_run_a", "w_run_b"] * 3)
check("phone render with >4 clips refused", not ok2, m2)
ok3, m3 = app._remote_render(["w_run_b", "w_attack_a"])
wait(1)
cmd = CMD[-1]
check("phone render uses its clips (once, not saved)", ok3 and cmd[cmd.index("--clips") + 1] == "w_run_b,w_attack_a"
      and "--no_open" in cmd and set(app._chosen_clips(it)) == {"w_idle", "w_sprint_a", "w_walk_a"}, cmd)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
