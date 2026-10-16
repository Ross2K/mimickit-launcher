"""a0.8.2: Control.act runs the action outside the lock (slow action -> 202 'Working...', the same nonce later returns
the result, other phones are not blocked); PIN: 6+ digits on the network, global ceiling turns control off, lockout
entries pruned; stop-after-save matches the exact --out_dir.   python tests/control_gate_test.py"""

import result_exit  # noqa: F401
import os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mimickit_remote as R
from mkl.stopsave import cmd_matches_run, find_run_pids

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


cfg = dict(allow_control=True, pin_hash=R.hash_pin("246810"), pin_len=6, host="0.0.0.0")
gate = threading.Event()
offs = []


def on_action(a, p):
    if a == "resume":
        gate.wait(10)
    return 200, "done " + a


c = R.Control(lambda: cfg, on_action, turn_off=lambda why: (offs.append(why), cfg.update(allow_control=False, lockdown=True)))
c.ACT_WAIT_S = 0.3
S = c.login("246810", "a")[1]["session"]
n = c.new_nonce(S, "resume")[1]["nonce"]
t0 = time.time()
code, body = c.act(S, n, "resume")
check("slow action answers 202 quickly", code == 202 and body.get("pending") and time.time() - t0 < 2, (code, body))
n2 = c.new_nonce(S, "stop_now")[1]["nonce"]
t0 = time.time()
code2, b2 = c.act(S, n2, "stop_now")
check("another action is not blocked meanwhile", code2 == 200 and time.time() - t0 < 1, (code2, b2))
code3, b3 = c.act(S, n, "resume")
check("asking again with the nonce: still pending", code3 == 202, (code3, b3))
gate.set()
time.sleep(0.3)
code4, b4 = c.act(S, n, "resume")
check("then the real result", code4 == 200 and "done resume" in b4.get("message", ""), (code4, b4))

cfg2 = dict(allow_control=True, pin_hash=R.hash_pin("1234"), pin_len=4, host="0.0.0.0")
c2 = R.Control(lambda: cfg2, on_action)
code, b = c2.login("1234", "x")
check("4-digit PIN refused while reachable on the network", code == 403 and "6\u201312 digit" in b["error"], b)
cfg2["host"] = "127.0.0.1"
check("4-digit PIN still works for this-PC-only", c2.login("1234", "x")[0] == 200)

t = [1000.0]
c3 = R.Control(lambda: cfg, on_action, now=lambda: t[0],
               turn_off=lambda why: (offs.append(why), cfg.update(allow_control=False, lockdown=True)))
cfg.update(allow_control=True)
codes = []
for i in range(R.GLOBAL_FAILS_PER_HOUR):
    codes.append(c3.login("000000", "phone%d" % i))
code, b = codes[-1]
check("20 wrong PINs from many phones turn control off", code == 403 and b.get("lockdown") and offs, (code, b))
check("lockdown message is the plain one", b["error"] == R.LOCKDOWN_MSG)
check("afterwards every request says why", c3.login("246810", "y")[1]["error"] == R.LOCKDOWN_MSG)
cfg.update(allow_control=True, lockdown=False)
for i in range(R.MAX_PIN_FAILS):
    c3.login("000000", "z")
check("per-phone lockout set", "z" in c3.lock_until)
t[0] += R.LOCKOUT_S + 3700
c3.login("246810", "w")
check("old lockouts and fail times pruned", "z" not in c3.lock_until and not c3.fail_times, (c3.lock_until, c3.fail_times))

mk = "/x/mk"
check("exact --out_dir matches", cmd_matches_run("python mimickit/run.py --out_dir output/a", mk + "/output/a", mk))
check("_resume2 sibling does not match", not cmd_matches_run("python mimickit/run.py --out_dir output/a_resume2", mk + "/output/a", mk))
check("prefix folder does not match", not cmd_matches_run("python mimickit/run.py --out_dir output/ab", mk + "/output/a", mk))
check("quoted absolute path matches", cmd_matches_run('python run.py --out_dir "/x/mk/output/a/"', mk + "/output/a", mk))
check("own PID included", os.getpid() in find_run_pids("", "", os.getpid()))
print("RESULT: %d/%d" % (sum(ok), len(ok)))
