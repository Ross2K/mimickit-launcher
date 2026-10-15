"""Long resumed run in the Status view (regression: 'What's happening' froze after 'First training iteration
done.', the Episode length card stayed blank, the last-checkpoint line could go stale).
xvfb-run -a python tests/status_longrun_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
TMP = tempfile.mkdtemp()
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(TMP, "s.json")
from mkl import status_model as SM

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


def table(it, ret, test):
    rows = [("Iteration", it), ("Wall_Time", 0.01 * it), ("Samples", 32768 * it), ("Test_Return", test),
            ("Train_Return", ret), ("Critic_Loss", 1.0)]
    return "-" * 42 + "\n" + "".join("| %20s | %15s |\n" % (k, ("%g" % v)) for k, v in rows) + "-" * 42 + "\n"


def capture(start, n):
    """A resumed run: iterations start..start+n, score rising with noise (stock MimicKit: no episode length)."""
    out = "Setting seed: 1\nBuilding deepmimic env\nLogging data to output/run_resume1/log.txt\n"
    for i in range(start, start + n):
        out += table(i, 100 + i * 0.5 + (i % 7), 90 + i * 0.5 + (i % 5))
    return out


# ---- model: events keep coming without iters_per_output (the reported case)
m = SM.StatusModel(ipo=None)
t0 = time.time()
cap = capture(400, 240)  # iterations 400..639
half = len(cap) // 2
m.feed(cap[:half], now=t0)
n_half = len(m.events)
m.feed(cap[half:], now=t0 + 60)
ev = [e for _, e in m.events]
check("first iteration event", "First training iteration done." in ev, ev)
check("periodic progress events keep coming", any(e.startswith("Iteration 500") for e in ev)
      and any(e.startswith("Iteration 600") for e in ev), ev)
check("progress events carry the scores", any("score" in e and "test" in e for e in ev if e.startswith("Iteration")))
check("test score updates reported", any(e.startswith("New best test score") for e in ev), ev)
check("more events in the second half than the first", len(m.events) > n_half or m.events[-1][0] == t0 + 60,
      (n_half, len(m.events)))
m.note_save(now=t0 + 61)
check("checkpoint save event (no ipo)", m.events[-1][1] == "Progress saved (iteration 639).", m.events[-1])
m3 = SM.StatusModel(ipo=50)
m3.feed(capture(400, 240))
m3.note_save()
ev3 = [e for _, e in m3.events]
check("with ipo: console save events, no duplicates from the file watch",
      "Model saved (iteration 600)." in ev3 and not any(e.startswith("Progress saved") for e in ev3), ev3[-4:])

# ---- GUI: events list, episode length card, checkpoint line, refresh loop
import tkinter as tk
import mimickit_launcher as G

G.App._progress_tick = lambda self, force=False: None
mk = os.path.join(TMP, "fake")
shutil.copytree(os.path.join(HERE, "fake_mimickit"), mk, ignore=shutil.ignore_patterns("output"))
G.filedialog.askdirectory = lambda **k: mk
root = tk.Tk()
root.geometry("1400x950+0+0")
app = G.App(root)
app.v_mk.set(mk)
app._save()
app.rescan()
root.update()
run = os.path.join(TMP, "run_resume1")
os.makedirs(run)
app.run_dir = run
open(os.path.join(run, "log.txt"), "w").write(
    "Iteration Train_Return Train_Episode_Length\n" + "".join("%d %g %g\n" % (i, i * 0.5, 150 + i % 3) for i in range(400, 640))
)
model = os.path.join(run, "model.pt")
open(model, "wb").write(b"x")
old = time.time() - 40 * 60
os.utime(model, (old, old))


class P:
    pid = 1

    def poll(self):
        return None


app.proc = P()
app.run_kind, app.started = "train", time.time()
app._status_reset("train")
app.sm.ipo = None
app._latest_model = lambda: model
app.v_outview.set("status")


def tick():
    app._ckpt_t = 0  # skip the 5 s throttle
    app._status_drain()
    app._status_refresh(force=True)
    root.update()


app.sm_q.put(cap[:half])
tick()
first = app.st_events.get("1.0", "end")
check("checkpoint line from the file", "40 min ago" in app.st_ckpt.cget("text"), app.st_ckpt.cget("text"))
app.sm_q.put(cap[half:])
os.utime(model, None)  # MimicKit saves again
tick()
txt = app.st_events.get("1.0", "end")
check("'What's happening' keeps updating", txt != first and "Iteration 600" in txt, txt)
check("new save shows up as an event", "Progress saved (iteration 639)." in txt, txt)
check("checkpoint 'ago' text refreshes after the save", "just now" in app.st_ckpt.cget("text"), app.st_ckpt.cget("text"))
ep = app.tiles["ep"][2].cget("text") if "ep" in app.tiles else ""
check("Episode length card filled (from log.txt)", ep not in ("", "-"), ep)

# the 1 s status loop survives an exception in one tick
boom = {"n": 0}
real = app._status_refresh


def flaky(force=False):
    boom["n"] += 1
    if boom["n"] == 1:
        raise RuntimeError("test: one bad tick")
    return real(force)


app._status_refresh = flaky
app._status_tick()
t = time.time()
while time.time() - t < 2.5:
    root.update()
    time.sleep(0.05)
check("status loop keeps running after an exception", boom["n"] >= 2, boom)
app._status_refresh = real

# ---- live: the fake MimicKit trains for several hundred iterations and saves model.pt every 50; every update
# after the first must still change the events, the episode length card and the checkpoint line
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.03", STUB_LOG_EPLEN="1")
del app._latest_model
app.proc = None
app.run_dir = None
app._ckpt_seen = None
G.messagebox.askyesno = lambda *a, **k: True
for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
app.v_out.set("output/longrun")
app.train()
app.sm.ipo = None  # the reported case: save interval not known from the config


def live_tick():
    app._ckpt_t = 0
    app._ep_log = (0.0, None, None)  # skip the 30 s log.txt throttle
    app._status_drain()
    app._status_refresh(force=True)
    root.update()


def wait(sec, until):
    t = time.time()
    while time.time() - t < sec:
        live_tick()
        if until():
            return True
        time.sleep(0.05)
    return False


def snap():
    return dict(
        events=[e for _, e in app.sm.events],
        ep=app.tiles["ep"][2].cget("text"),
        ckpt=app.st_ckpt.cget("text"),
        it=app.sm.iteration,
        saves=sum(e.startswith("Progress saved") for _, e in app.sm.events),
    )


lm = os.path.join(app.run_dir, "model.pt")
wait(20, lambda: os.path.exists(lm) and app.sm.iteration is not None)
first = snap()
check("live: first update has the first-iteration event", "First training iteration done." in first["events"], first)
old = time.time() - 40 * 60
os.utime(lm, (old, old))  # pretend the last save is old: the next refresh must re-read the file
live_tick()
check("live: checkpoint line re-reads the file ('40 min ago')", "40 min ago" in app.st_ckpt.cget("text"), app.st_ckpt.cget("text"))
saves = []
for k in (1, 2):  # two more model.pt saves after the first update
    ok_save = wait(20, lambda: snap()["saves"] >= first["saves"] + k and "just now" in app.st_ckpt.cget("text"))
    saves.append(snap())
    check("live: save %d after the first update shows up (event + 'just now')" % k, ok_save, saves[-1]["ckpt"])
    os.utime(lm, (old, old))
wait(20, lambda: app.sm.iteration >= 210)
last = snap()
check("live: iteration moved on", last["it"] > first["it"] + 150, (first["it"], last["it"]))
check("live: 'What's happening' got new lines after the first update",
      len(last["events"]) > len(first["events"]) and any(e.startswith("Iteration ") for e in last["events"]),
      last["events"][-5:])
check("live: periodic progress keeps coming (two 100-iteration lines)",
      sum(e.startswith("Iteration ") for e in last["events"]) >= 2, last["events"])
check("live: episode length card filled and updating", first["ep"] not in ("", "-") and last["ep"] != first["ep"],
      (first["ep"], last["ep"]))
check("live: shown in the window", "Progress saved" in app.st_events.get("1.0", "end"))
app.stop()
wait(2, lambda: False)
root.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
