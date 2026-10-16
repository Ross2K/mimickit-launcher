"""a0.8.4 P1: the stop-after-save retry looks for the run's processes in a worker (here: 3 s); if a NEW run was started
in that gap, it must survive (no stop(), no kill).   xvfb-run -a python tests/stopsave_race_test.py"""

import result_exit  # noqa: F401
import os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tkinter as tk
import mkl.stopsave as SS

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


class Fake(SS.StopAfterSaveMixin):
    STOP_VERIFY_S = 20

    def __init__(self, root, proc):
        self.root, self.proc, self.run_dir, self._mk_cache = root, proc, "/tmp/x/output/a", "/tmp/x"
        self.log, self.stops, self.kills = [], [], []

    def _append(self, m):
        self.log.append(m)

    def stop(self):
        self.stops.append(self.proc.pid)

    def _kill(self, pid, why):
        self.kills.append(pid)


def slow_find(run_dir, mk, root_pid):
    time.sleep(3)
    return [root_pid]


SS.find_run_pids = slow_find
root = tk.Tk()
root.withdraw()
old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
f = Fake(root, old)
f._stopsave_find_kill()
t0 = time.time()
while time.time() - t0 < 0.5:
    root.update()
    time.sleep(0.02)
old.kill()
old.wait()
new = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # user started a new run in the gap
f.proc = new
t0 = time.time()
while time.time() - t0 < 4.5:
    root.update()
    time.sleep(0.02)
check("new run started during the 3 s search survives", new.poll() is None and not f.kills and not f.stops,
      (f.kills, f.stops))
check("logged instead", any("nothing to stop" in m for m in f.log), f.log)
# same run still alive -> the retry does stop + kill it
f2 = Fake(root, new)
f2._stopsave_find_kill()
t0 = time.time()
while time.time() - t0 < 4.5:
    root.update()
    time.sleep(0.02)
check("same run still alive -> stopped again", f2.stops and f2.kills == [new.pid], (f2.stops, f2.kills))
new.kill()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
