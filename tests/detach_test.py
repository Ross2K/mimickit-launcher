"""Detached runs: training survives the GUI being killed, a new window reattaches (log replay + live tail + timers),
Stop kills the saved PID's whole process tree, 'keep running' on close, and PID-reuse protection.
  xvfb-run -a python tests/detach_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from fake_mk import fake_mk, hard_kill  # noqa: E402 - temp copy: test output never lands in the repo
import json, os, shutil, signal, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.2", STUB_TEST_SECS="600")
mk = fake_mk()
shutil.rmtree(os.path.join(mk, "output"), ignore_errors=True)
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


def alive(pid):
    i = G.proc_info(pid)
    return bool(i and i["alive"])


def group_alive(pid):
    return any(
        G.proc_info(int(p)) and G.proc_info(int(p))["alive"]
        for p in subprocess.run(
            ["pgrep", "-s", str(pid)], capture_output=True, text=True
        ).stdout.split()
    )


# 1) a separate GUI process starts training, then is SIGKILLed (simulated crash)
gui = subprocess.Popen(
    [
        sys.executable,
        "-c",
        """
import os, sys, time; sys.path.insert(0, %r)
import tkinter as tk, mimickit_launcher as G
for n in ("showinfo", "showwarning", "showerror"): setattr(G.messagebox, n, lambda *a, **k: None)
G.messagebox.askyesno = lambda *a, **k: True; G.filedialog.askdirectory = lambda **k: %r
root = tk.Tk(); app = G.App(root)
def go(): app.v_out.set("output/det"); app.train(); print("STARTED", app.proc.pid, flush=True)
root.after(1500, go); root.mainloop()
""" % (ROOT, mk),
    ],
    stdout=subprocess.PIPE,
    text=True,
)
line = gui.stdout.readline()
pid = int(line.split()[1]) if line.startswith("STARTED") else -1
time.sleep(4)
hard_kill(gui.pid)
gui.wait()
t_kill = time.time()
import tkinter as tk, mimickit_launcher as G

out = os.path.join(mk, "output", "det")
stp = os.path.join(out, G.RUN_STATE)
st = json.load(open(stp)) if os.path.exists(stp) else {}
check(
    "run-state JSON saved (pid, cmd, start time)",
    st.get("pid") == pid and "mimickit/run.py" in st.get("cmd", []) and st.get("started"),
    str({k: st.get(k) for k in ("pid", "kind", "started")}),
)
check("command uses python -u", st.get("cmd", [None, None])[1] == "-u")
check("training survives GUI crash", alive(pid), "pid %d" % pid)
n0 = os.path.getsize(os.path.join(out, G.CONSOLE_FILE))
time.sleep(1.5)
check(
    "child keeps writing console_log.txt", os.path.getsize(os.path.join(out, G.CONSOLE_FILE)) > n0
)
check("PID check accepts the real process", G.run_state_matches(st))
# 2) a new window reattaches
for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: print("[dialog]", a))
G.messagebox.askyesno = lambda *a, **k: True
G.filedialog.askdirectory = lambda **k: mk
root = tk.Tk()
app = G.App(root)


def wait(sec):
    t = time.time()
    while time.time() - t < sec:
        root.update()
        time.sleep(0.05)


wait(3)
check(
    "reattached to saved PID",
    app.proc is not None and app.proc.pid == pid and app.proc.poll() is None,
)
log = app.t_log.get("1.0", "end")
check(
    "log panel shows reattach + replayed console",
    "REATTACHED" in log and "stub run.py args:" in log and "|            Iteration |" in log,
)
r1 = app.live.rows()
wait(2.5)
r2 = app.live.rows()
check("live tail keeps parsing new rows", r1 > 5 and r2 > r1, "%d -> %d rows" % (r1, r2))
app._progress_tick(force=True)
stt = app.l_status.cget("text")
el = time.time() - st.get("started", time.time())
check(
    "status RUNNING (train) with session time from saved start",
    "RUNNING (train)" in stt and "Running for 0:00:" in stt,
    stt.split("\n")[-2:].__str__(),
)
app._tt_save()
j = json.load(open(os.path.join(out, G.TIME_FILE)))
check(
    "total training time counts time while GUI was gone",
    abs(j["seconds"] - el) < 2.5,
    "%.1f vs %.1f" % (j["seconds"], el),
)
check(
    "charts drawn from console",
    "data: console" in app.prog_frame.cget("text"),
    app.prog_frame.cget("text"),
)
# 3) stop kills the tree via the saved PID
check("stub's worker child alive before stop", group_alive(pid))
app.stop()
wait(2.5)
check("stop killed reattached process tree", not alive(pid) and not group_alive(pid))
check("log shows process ended", "process ended" in app.t_log.get("1.0", "end"))
check("run-state marked ended", bool(json.load(open(stp)).get("ended")))
check("no reattach to an ended run", app._reattach() is False)
# 4) close window with 'keep running', reopen -> reattach (watch run, own log folder)
app.watch()
wait(2)
wpid = app.proc.pid
app._choose_hook = lambda *a: "detach"
app._on_close()  # the close popup: Detach
time.sleep(1)
check("watch keeps running after closing with 'Detach'", alive(wpid))
root = tk.Tk()
app = G.App(root)
wait(2.5)
check(
    "new window reattaches to watch",
    app.proc is not None and app.proc.pid == wpid and app.run_kind == "watch",
)
check("watch log replayed", "test mode: would open a viewer window" in app.t_log.get("1.0", "end"))
app.stop()
wait(2)
check("stop after reattach (watch)", not alive(wpid))
# 5) PID reuse protection
sl = subprocess.Popen(["sleep", "60"])
t_exec = time.time()  # until exec() the child still looks like (or has no) cmdline: wait for "sleep"
while "sleep" not in ((G.proc_info(sl.pid) or {}).get("cmd") or "") and time.time() - t_exec < 5:
    time.sleep(0.02)
fake = dict(pid=sl.pid, started=time.time(), proc_start=G.proc_info(sl.pid)["start"], kind="train")
check("rejects a PID that is not MimicKit python", not G.run_state_matches(fake))
fake2 = dict(st, proc_start=(st.get("proc_start") or 0) - 3600, ended=None)
check("rejects a PID with a different start time", not G.run_state_matches(fake2))
sl.kill()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
root.destroy()
