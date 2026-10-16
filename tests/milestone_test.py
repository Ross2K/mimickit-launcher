"""a0.9.0: 'First steps!' / 'Walking well' milestone alerts - rules, fallbacks, once per run chain (resume doesn't
re-fire), desktop card, phone banner, Discord/Telegram, Training settings fields.
   xvfb-run -a -s '-screen 0 1600x1000x24' python tests/milestone_test.py"""

import result_exit  # noqa: F401
import json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


from mkl import milestones as MS

C = MS.cfg({})
check("defaults: 20 % / 50 %, upright 80 %, 3 checks", (C["first_pct"], C["well_pct"], C["upright_pct"], C["evals"])
      == (20.0, 50.0, 80.0, 3))
FULL = 300.0  # 10 s x 30 Hz


def H(pcts, lens):
    return {"Test_Return": [p / 100.0 * l for p, l in zip(pcts, lens)], "Test_Episode_Length": list(lens)}


check("3 checks at 21.8 % and full length -> First steps", set(MS.reached(H([21.8] * 3, [300] * 3), FULL, C))
      == {"first_steps"})
check("only 2 checks in a row -> nothing", MS.reached(H([5, 21.8, 21.8], [300] * 3), FULL, C) == {})
check("falls early (length 60 %) -> nothing, even with a high score",
      MS.reached(H([60] * 3, [180] * 3), FULL, C) == {})
check("score 19 % -> nothing", MS.reached(H([19] * 3, [300] * 3), FULL, C) == {})
r = MS.reached(H([55] * 3, [290] * 3), FULL, C)
check("55 % upright -> both levels", set(r) == {"first_steps", "walking_well"}, r)
check("text says the score and length", "55.0%" in r["walking_well"]["text"] and "97%" in r["walking_well"]["text"])
# fallbacks
h = {"Test_Return": [0.25 * 300] * 3}
r = MS.reached(h, FULL, C)
check("no Test_Episode_Length logged -> match score alone (Return / max length)", set(r) == {"first_steps"}
      and "match score only" in r["first_steps"]["text"], r)
check("no episode length and no max length -> nothing", MS.reached(h, None, C) == {})
r = MS.reached(H([30] * 3, [100] * 3), None, C)
check("length logged but max unknown -> upright check skipped, score counts", set(r) == {"first_steps"})
check("nan rows skipped", set(MS.reached({"Test_Return": [float("nan"), 66, 66, 66],
                                          "Test_Episode_Length": [300, 300, 300, 300]}, FULL, C)) == {"first_steps"})

# per-folder flag + chain
out = tempfile.mkdtemp()
base = os.path.join(out, "run")
os.makedirs(base)
open(os.path.join(base, "env_config.yaml"), "w").write("env_name: deepmimic\nepisode_length: 10.0 # seconds\n")
open(os.path.join(base, "engine_config.yaml"), "w").write("engine_name: isaac_gym\ncontrol_freq: 30\nsim_freq: 120\n")
check("max length from the run's copied yaml = 10 s x 30 Hz", MS.max_len(base) == 300.0, MS.max_len(base))
h = H([22] * 4, [300] * 4)
new = MS.check(base, [base], h, C)
check("fires once", [i["key"] for i in new] == ["first_steps"])
check("flag stored in the output folder", "first_steps" in MS.load(base))
check("not again in the same folder", MS.check(base, [base], h, C) == [])
res = os.path.join(out, "run_resume1")
os.makedirs(res)
check("resumed run (no yaml of its own) doesn't re-fire", MS.check(res, [base, res], h, C) == [])
new = MS.check(res, [base, res], H([52] * 3, [300] * 3), C)
check("...but the higher level still fires once in the resume", [i["key"] for i in new] == ["walking_well"])
check("disabled -> nothing", MS.check(os.path.join(out, "x"), [], h, dict(C, enabled=False)) == [])
src = open(os.path.join(ROOT, "mkl", "milestones.py")).read()
check("documented log keys + fallback", all(k in src for k in ("Test_Return", "Test_Episode_Length", "Fallbacks")))

# ---- GUI: card, phone banner, notify, Training settings ----------------------------------------------------------
import tkinter as tk
import mimickit_launcher as G
from fake_mk import fake_mk

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
G.filedialog.askdirectory = lambda *a, **k: fake_mk()
root = tk.Tk()
app = G.App(root)
app.v_mk.set(fake_mk())
app.rescan()
root.update()
sent = []
app.notifier.targets = lambda: ["discord"]
app.notifier.send = lambda text, **k: sent.append((text, k.get("kind")))
run2 = os.path.join(out, "gui_run")
os.makedirs(run2)
for f in ("env_config.yaml", "engine_config.yaml"):
    open(os.path.join(run2, f), "w").write(open(os.path.join(base, f)).read())
app.run_kind = "train"
check("not while not training", app._check_milestones(run2, h, False) == [])
new = app._check_milestones(run2, h, True)
time.sleep(0.3)
root.update()
check("GUI: fires while training", [i["key"] for i in new] == ["first_steps"])
check("GUI: desktop card shown", "milestone" in app.cards)
check("GUI: Discord/Telegram message sent", sent and sent[0][1] == "milestone" and "First steps!" in sent[0][0], sent)
lines = ["RUNNING (train)  -  " + run2]
app._publish(lines, run2, True)
check("phone: snapshot carries the banner", (app.snap.get("milestone") or {}).get("title") == "First steps!",
      app.snap.get("milestone"))
import mimickit_remote as R

page = R.PAGE if hasattr(R, "PAGE") else open(os.path.join(ROOT, "mimickit_remote.py")).read()
check("phone page has the banner", 'id="mile"' in page and "S.milestone" in page)
check("GUI: no re-fire on the next tick", app._check_milestones(run2, h, True) == [])
# console rows without episode length -> log.txt is used
run3 = os.path.join(out, "gui_run3")
os.makedirs(run3)
for f in ("env_config.yaml", "engine_config.yaml"):
    open(os.path.join(run3, f), "w").write(open(os.path.join(base, f)).read())
cols = ["Iteration", "Samples", "Test_Return", "Test_Episode_Length"]
with open(os.path.join(run3, "log.txt"), "w") as fh:
    fh.write("".join("%-25s" % c for c in cols) + "\n")
    for i in range(4):
        fh.write("".join("%-25s" % v for v in (i, (i + 1) * 1000, 0.6 * 290, 290)) + "\n")
console = {"Iteration": [0, 1, 2, 3], "Test_Return": [174.0] * 4}  # stock console: no episode length
new = app._check_milestones(run3, console, True)
check("console lacks Test_Episode_Length -> read from log.txt (both levels)",
      [i["key"] for i in new] == ["first_steps", "walking_well"], new)
# Training settings fields
top = app.train_settings_dialog()
root.update()
vs = app._ts_ms_vars
check("Training settings: plain-label threshold fields", set(vs) >= {"first_pct", "well_pct", "upright_pct", "evals"})
vs["first_pct"][0].set("25")
vs["evals"][0].set("4")
app._ts_dlg["save"]()
root.update()
check("saved to the launcher settings", MS.cfg(app.s)["first_pct"] == 25.0 and MS.cfg(app.s)["evals"] == 4,
      app.s.get("milestones"))
top = app.train_settings_dialog()
root.update()
app._ts_ms_vars["well_pct"][0].set("10")
check("'Walking well' below 'First steps!' refused", app._ts_ms_apply() != [])
top.destroy()
root.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
