"""a0.9.1: 'One long clip (all animations)' preview layout, phone ghost selector, milestone M1 (save errors) / M2
(unreadable run chain).
   xvfb-run -a -s '-screen 0 1600x1000x24' python tests/qa091_test.py"""

import result_exit  # noqa: F401
import os, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


import mimickit_preview as P
import mimickit_remote as R
from mkl import core
from mkl import milestones as MS

# --- long layout ----------------------------------------------------------------------------------------------------
check("layout offered with the agreed label", core.CLIP_LAYOUTS.get("One long clip (all animations)") == "long")
check("preview accepts --layout long", "long" in P.LAYOUTS)
c = dict(K=3, nper=[2, 3, 1])
check("long = every clip back to back", P.frame_specs(c, "long") == [[(0, 0)], [(0, 1)], [(1, 0)], [(1, 1)], [(1, 2)], [(2, 0)]])
n, cap = P.long_caps([5.0, 10.0], 30)
check("short total: clips kept whole", n == [150, 300] and cap is None, (n, cap))
n, cap = P.long_caps([60.0] * 30, 30)
check("long total: each clip capped to its share (<= 15 min)", cap == 30.0 and n == [900] * 30 and sum(n) / 30 <= P.MAX_LONG_S, cap)
n, cap = P.long_caps([60.0] * 1000, 30)
check("very many clips: cap never below 2 s", cap == P.LONG_MIN_CLIP_S and n[0] == 60, cap)
check("env cap is small (<= 64)", P.MAX_LONG_CLIPS == 64)

CMD = []


class Stop(Exception):
    pass


def fake_popen(cmd, **k):
    CMD.append(cmd)
    raise Stop()


P.subprocess.Popen, real = fake_popen, P.subprocess.Popen
a = types.SimpleNamespace(mk="/mk", npz_path="/t/x.npz", save_init_model="", frames=0, motions=4, clips="b,c",
                          layout="long", mk_args=["--x"], warp_cache="/t/wc")
try:
    P._record_proc(a, "cpu", None, False)
except Stop:
    pass
P.subprocess.Popen = real
cmd = CMD[-1]
check("record step gets --clips and --layout long", cmd[cmd.index("--clips") + 1] == "b,c" and cmd[cmd.index("--layout") + 1] == "long"
      and cmd.index("--layout") < cmd.index("--"), cmd)

# --- phone: ghost selector + render layout --------------------------------------------------------------------------
check("phone ghost choices = GHOST_MODES", tuple(R.GHOST_CHOICES) == tuple(core.GHOST_MODES))
check("ghost is a control action", "ghost" in R.ACTIONS)
page = R.PAGE if hasattr(R, "PAGE") else open(R.__file__, encoding="utf-8").read()
check("page: layout select + ghost selector", all(x in page for x in ('id="r_layout"', 'id="g_mode"', "s_ghost", "act('ghost'")))
cfg = dict(allow_control=True, pin_hash=R.hash_pin("135790"), pin_len=6, host="0.0.0.0")
got = []
ctl = R.Control(lambda: cfg, lambda act, p: (got.append((act, p)), (200, "ok"))[1])
code, _ = ctl.act("nosession", "nononce", "ghost", {"mode": "Overlay"})
check("ghost without PIN session refused", code in (401, 403) and not got, code)
S = ctl.login("135790", "t")[1]["session"]
code, b = ctl.act(S, ctl.new_nonce(S, "ghost")[1]["nonce"], "ghost", {"mode": "Rainbow"})
check("unknown ghost mode -> 400", code == 400 and not got, (code, b))
code, b = ctl.act(S, ctl.new_nonce(S, "ghost")[1]["nonce"], "ghost", {"mode": "Side by side"})
check("valid ghost mode passes the gate", code == 200 and got and got[-1][0] == "ghost", (code, b, got))

# --- M1: save failure keeps the flag in memory -----------------------------------------------------------------------
import mimickit_util as U

out = tempfile.mkdtemp()
base = os.path.join(out, "run")
os.makedirs(base)
open(os.path.join(base, "env_config.yaml"), "w").write("env_name: deepmimic\nepisode_length: 10.0 # seconds\n")
open(os.path.join(base, "engine_config.yaml"), "w").write("engine_name: isaac_gym\ncontrol_freq: 30\nsim_freq: 120\n")
H = {"Test_Return": [0.22 * 300] * 4, "Test_Episode_Length": [300] * 4}
C = MS.cfg({})
real_save = U.save_json


def boom(*a, **k):
    raise PermissionError("locked")


U.save_json = boom
try:
    new = MS.check(base, [base], H, C)
    err = None
except Exception as e:  # noqa: BLE001
    new, err = [], e
check("M1: write fails -> no exception, alert still fires", err is None and [i["key"] for i in new] == ["first_steps"], err)
check("M1: ... and not again next tick (in-memory flag)", MS.check(base, [base], H, C) == [])
U.save_json = real_save

# --- M2: unknown run chain never re-fires the parent's level ---------------------------------------------------------
out2 = tempfile.mkdtemp()
par = os.path.join(out2, "run")
os.makedirs(par)
for f in ("env_config.yaml", "engine_config.yaml"):
    open(os.path.join(par, f), "w").write(open(os.path.join(base, f)).read())
check("parent fires", [i["key"] for i in MS.check(par, [par], H, C)] == ["first_steps"])
res = os.path.join(out2, "run_resume1")
os.makedirs(res)
check("M2: chain unknown (None) -> parent's level not re-fired", MS.check(res, None, H, C) == [])
H2 = {"Test_Return": [0.55 * 300] * 4, "Test_Episode_Length": [300] * 4}
check("M2: chain unknown + parent has flags -> new level held back too (safe)", MS.check(res, None, H2, C) == [])
lone = os.path.join(tempfile.mkdtemp(), "solo")
os.makedirs(lone)
for f in ("env_config.yaml", "engine_config.yaml"):
    open(os.path.join(lone, f), "w").write(open(os.path.join(base, f)).read())
check("M2: chain unknown, no parent flags -> still fires normally", [i["key"] for i in MS.check(lone, None, H, C)] == ["first_steps"])
src = open(os.path.join(ROOT, "mkl", "status.py"), encoding="utf-8").read()
check("status: run_chain errors -> chain=None (not [d])", "chain = None" in src)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
