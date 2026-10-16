"""Phone 'Runs' + 'MimicKit patches' (a0.8.0): start a new training, continue from an earlier run, apply / revert
patches - through the real PIN + session + action-bound nonce gate, validated on the PC, same refusals as the PC.
  xvfb-run -a python tests/runs_test.py"""

import result_exit  # noqa: F401
import os, shutil, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.02")
import tkinter as tk, mimickit_launcher as G
import mimickit_patches as MP
from mimickit_remote import hash_pin
from mkl.runs import validate_run_params, validate_out

DLG = []
for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: DLG.append(a))
G.messagebox.askyesno = lambda *a, **k: DLG.append(a) or True
mk = os.path.join(tempfile.mkdtemp(), "mk")
shutil.copytree(os.path.join(HERE, "fake_mimickit"), mk, ignore=shutil.ignore_patterns("output"))
G.filedialog.askdirectory = lambda **k: mk
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


# ---- pure validation
ch = dict(configs=["A", "B"], runs={"k1": "/x"}, patches={"logging": dict(can_revert=True), "z": dict(can_revert=False)})
good = dict(config="A", num_envs=64, out="output/run1")
check("valid start accepted", validate_run_params("start_train", good, ch)[0] == dict(good, overwrite=False))
for bad, why in ((dict(good, config="C"), "unknown config"), (dict(good, num_envs=0), "num_envs 0"),
                 (dict(good, num_envs="64"), "num_envs as text"), (dict(good, num_envs=True), "num_envs bool"),
                 (dict(good, out="../evil"), "out with .."), (dict(good, out="output/../x"), "out output/../x"),
                 (dict(good, out="C:/x"), "absolute out"), (dict(good, out="output/_launcher_preview"), "launcher folder"),
                 (dict(good, overwrite="yes"), "overwrite not bool")):
    check("start refused: " + why, validate_run_params("start_train", bad, ch)[0] is None)
check("continue needs a listed run", validate_run_params("continue_run", dict(good, src="nope"), ch)[0] is None
      and validate_run_params("continue_run", dict(good, src="k1"), ch)[0]["src"] == "k1")
check("patch: unknown name / bad op / no revert refused",
      validate_run_params("patch", dict(name="x", op="apply"), ch)[0] is None
      and validate_run_params("patch", dict(name="logging", op="delete"), ch)[0] is None
      and validate_run_params("patch", dict(name="z", op="revert"), ch)[0] is None)
check("out folder rules", validate_out("output/a_b-1.2")[0] == "output/a_b-1.2" and validate_out("data/x")[0] is None)

# ---- in the window, through the gate
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


def phone(action, params=None, session=None, nonce_for=None):
    ctl = app._control()
    box = {}

    def run():
        c, b = ctl.new_nonce(session, nonce_for or action)
        box["r"] = ctl.act(session, b.get("nonce"), action, params or {}) if c == 200 else (c, b)

    t = threading.Thread(target=run)
    t.start()
    wait(10, lambda: not t.is_alive())
    return box["r"]


def refresh():
    app._progress_tick(force=True)
    wait(0.5)
    return app.snap["runs_ui"]


wait(2)
app.v_mk.set(mk)
app.rescan()
wait(0.5)
app.s.setdefault("remote", {}).update(allow_control=True, pin_hash=hash_pin("2468"))
ctl = app._control()
SES = ctl.login("2468", client="100.64.0.7")[1]["session"]
DLG.clear()
ui = refresh()
check("phone gets the PC's training configs", ui["configs"] == [i["name"] for i in app.train_items] and ui["config"] in ui["configs"])
check("patches listed with state", {p["name"] for p in ui["patches"]} >= set(MP.PATCHES)
      and all("status" in p for p in ui["patches"]))
cfg = ui["configs"][0]
r = phone("start_train", dict(config=cfg, num_envs=256, out="output/ph1"), session="bad")
check("no session -> refused", r[0] == 401)
r = phone("patch", dict(name="logging", op="apply"), session=SES, nonce_for="start_train")
check("a 'start' confirmation can't apply a patch", r[0] == 403)
r = phone("start_train", dict(config="nope", num_envs=256, out="output/ph1"), session=SES)
check("unknown config refused on the PC", r[0] == 400, r)
r = phone("start_train", dict(config=cfg, num_envs=256, out="../../etc"), session=SES)
check("bad output folder refused on the PC", r[0] == 400, r)
r = phone("start_train", dict(config=cfg, num_envs=256, out="output/ph1"), session=SES)
check("start accepted", r[0] == 202, r)
wait(15, lambda: app._training_running())
check("training started with the phone's choices", app._training_running() and app.v_out.get() == "output/ph1"
      and int(app.v_envs.get()) == 256 and app.v_train.get() == cfg)
check("no PC dialog popped up", not DLG, DLG)
r = phone("start_train", dict(config=cfg, num_envs=256, out="output/ph2"), session=SES)
check("second start while running refused", r[0] == 409 and "already running" in r[1]["error"], r)
check("refusal logged", "start_train -> 409" in app.t_log.get("1.0", "end") or "refused" in app.t_log.get("1.0", "end"))
ui = refresh()
check("phone sees busy", ui["busy"])
r = phone("patch", dict(name="logging", op="apply"), session=SES)
check("patch refused while training", r[0] == 409 and "running" in r[1]["error"], r)
app._patch_dlg = None
app.patch_dialog()
wait(0.5)
app._patch_dlg["act"](MP.apply, "logging")
check("PC patch button refused while training too", any("Patch refused" in str(d) for d in DLG), DLG[-1:] )
DLG.clear()
m = os.path.join(app.outdir_abs("output/ph1"), "model.pt")
wait(20, lambda: os.path.exists(m))
app.stop()
wait(15, lambda: not app._training_running() and not (app.proc and app.proc.poll() is None))
r = phone("start_train", dict(config=cfg, num_envs=128, out="output/ph1"), session=SES)
wait(3)
check("start into a used folder without overwrite -> refused, reason shown",
      r[0] == 202 and not app._training_running() and "overwrite" in app.runs_msg, app.runs_msg)
ui = refresh()
run = next((x for x in ui["runs"] if x["name"] == "output/ph1"), None)
check("earlier run listed for Continue", run is not None and "path" not in run, ui["runs"])
r = phone("continue_run", dict(config=cfg, num_envs=128, out="output/ph1", src=run["key"]), session=SES)
check("continue accepted", r[0] == 202, r)
wait(15, lambda: app._training_running())
check("continued into a _resume folder", app._training_running() and app.run_dir and "ph1_resume" in app.run_dir, app.run_dir)
check("continue carried the start model", os.path.exists(os.path.join(app.run_dir, "start_model.pt")))
app.stop()
wait(15, lambda: not (app.proc and app.proc.poll() is None))
# patches when idle (a real patchable file)
BA = os.path.join(mk, *MP.PATCHES["logging"]["file"].split("/"))
os.makedirs(os.path.dirname(BA), exist_ok=True)
open(BA, "w").write('        self._logger.log("Test_Episode_Length", test_ep_len, collection="0_Main", quiet=True)\n'
                    '        self._logger.log("Train_Episode_Length", train_ep_len, collection="0_Main", quiet=True)\n')
app._patch_cache = None
refresh()
r = phone("patch", dict(name="logging", op="apply"), session=SES)
wait(2)
check("phone applies a patch when idle", r[0] == 202 and MP.status(mk, "logging") == "applied", app.runs_msg)
ui = refresh()
check("phone sees the new state", next(p for p in ui["patches"] if p["name"] == "logging")["status"] == "applied")
r = phone("patch", dict(name="logging", op="revert"), session=SES)
wait(2)
check("phone reverts it", MP.status(mk, "logging") == "not applied", app.runs_msg)
r = phone("patch", dict(name="solver", op="apply"), session=SES)
wait(2)
check("a patch that can't apply -> refusal shown + logged", "refused" in app.runs_msg or "failed" in app.runs_msg, app.runs_msg)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
