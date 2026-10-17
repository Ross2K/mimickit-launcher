"""a0.9.2: 'All clips' preview (auto grid for many tiles), automatic update check (A1, notice only), PIN rule back to
4-12 digits.
   xvfb-run -a -s '-screen 0 1600x1000x24' python tests/qa092_test.py"""

import result_exit  # noqa: F401
import os, queue, sys, tempfile, threading, time, types, urllib.error

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
from mkl import updatecheck as UC

# --- All clips: grid shape + tile size ------------------------------------------------------------------------------
# 1.0.0: dropping the 'a' prefix must still count as newer than every alpha
check("1.0.0 is newer than a0.9.3 / a0.9.10, never the reverse",
      UC.newer("1.0.0", "a0.9.3") and UC.newer("1.0.0", "a0.9.10") and not UC.newer("a0.9.3", "1.0.0")
      and not UC.newer("1.0.0", "1.0.0") and UC.newer("1.0.1", "1.0.0") and UC.newer("v1.0.0", "a0.9.3"))
check("this build is 1.0.0 (1.0.0Z in the Z build), newer than a0.9.3", UC.parse_version(core.VERSION) == (1, 0, 0)
      and UC.newer(core.VERSION, "a0.9.3Z") and not UC.newer("a0.9.3", core.VERSION))
check("grid up to 4 unchanged", [P.grid_shape(k) for k in (1, 2, 3, 4)] == [(1, 1), (1, 2), (2, 2), (2, 2)])
check("31 clips -> 6x6 auto grid", P.grid_shape(31) == (6, 6), P.grid_shape(31))
check("5 clips -> 2x3, 64 -> 8x8", P.grid_shape(5) == (2, 3) and P.grid_shape(64) == (8, 8))
check("every clip has a cell", all(r * c >= k for k in range(1, 65) for r, c in [P.grid_shape(k)]))
check("tiles: 4 clips keep 640x480", P.tile_size(4, 640, 480) == (640, 480))
tw, th = P.tile_size(31, 640, 480)
check("31 tiles: 320x240, frame 1920x1440", (tw, th) == (320, 240), (tw, th))
tw, th = P.tile_size(64, 640, 480)
check("64 tiles: frame <= 1920 wide, multiples of 16", 8 * tw <= 1920 and tw % 16 == 0 and th % 16 == 0, (tw, th))
check("seq/long: tiles not shrunk", P.tile_size(31, 640, 480, "seq") == (640, 480))
c = dict(K=31, nper=[3] * 30 + [5])
fs = P.frame_specs(c, "grid")
check("grid of 31: every frame shows 31 panels, length = longest clip", len(fs) == 5 and all(len(f) == 31 for f in fs))
check("cap raised to 64 (not 4) for All clips", P.MAX_LONG_CLIPS == 64)
CMD = []


class Stop(Exception):
    pass


def fake_popen(cmd, **k):
    CMD.append(cmd)
    raise Stop()


real = P.subprocess.Popen
P.subprocess.Popen = fake_popen
a = types.SimpleNamespace(mk="/mk", npz_path="/t/x.npz", save_init_model="", frames=0, motions=4, clips="",
                          layout="grid", all_clips=True, mk_args=["--x"], warp_cache="/t/wc")
try:
    P._record_proc(a, "cpu", None, False)
except Stop:
    pass
P.subprocess.Popen = real
cmd = CMD[-1]
check("record step gets --all_clips + the layout", "--all_clips" in cmd and cmd[cmd.index("--layout") + 1] == "grid"
      and cmd.index("--all_clips") < cmd.index("--"), cmd)
check("preview CLI knows --all_clips", "--all_clips" in open(P.__file__, encoding="utf-8").read())

# --- phone: All clips -----------------------------------------------------------------------------------------------
page = open(R.__file__, encoding="utf-8").read()
i_dl, i_all, i_sel = page.index('id="pv_dl"'), page.index('id="pv_all"'), page.index('id="pv_clips"')
check("phone: All clips between Download MP4 and the clip selector", i_dl < i_all < i_sel)
check("phone: ticking greys out the clip selector", "q('pv_clips').disabled=q('pv_all').checked" in page)
got = []
d = R.Dashboard.__new__(R.Dashboard)
d.min_interval, d._last_render = 0, 0.0
d.on_render = lambda clips=None, layout=None, all_clips=False: (got.append((clips, layout, all_clips)), (True, "ok"))[1]
code, _ = d.request_render(None, "grid", all_clips=True)
check("phone render passes all_clips + layout", code == 202 and got[-1] == (None, "grid", True), got)
d._last_render = 0.0
d.request_render(["a"], None)
check("without All clips: as before", got[-1] == (["a"], None, False), got)

# --- A1 automatic update check --------------------------------------------------------------------------------------
check("defaults: on, every 6 h", UC.cfg({}) == dict(auto=True, hours=6))
check("interval clamped 1-168 h, junk -> 6", UC.cfg({"update": {"check_hours": 0}})["hours"] == 1
      and UC.cfg({"update": {"check_hours": 9999}})["hours"] == 168 and UC.cfg({"update": {"check_hours": "x"}})["hours"] == 6)
check("off switch", UC.cfg({"update": {"auto_check": False}})["auto"] is False)
check("due: first time / after the interval only", UC.due(None, 6) and not UC.due(1000.0, 6, now=1000.0 + 3600)
      and UC.due(1000.0, 6, now=1000.0 + 6 * 3600))
rels = [dict(tag_name="a0.9.9", draft=True), dict(tag_name="a1.0.0", prerelease=True), dict(tag_name="a0.8.2"),
        dict(tag_name="a0.9.3", html_url="u3"), dict(tag_name="a0.9.4", html_url="u4")]
check("public: newest real release newer than this one", UC.latest_public(rels, "a0.9.2") == dict(version="a0.9.4", url="u4"))
check("public: nothing newer -> None", UC.latest_public(rels[:3], "a0.9.2") is None)
t0 = time.time()
try:
    UC.fetch_public(api="http://127.0.0.1:9", timeout=3)
    off = None
except Exception as e:  # noqa: BLE001
    off = e
check("offline: fetch raises quickly (caller logs it)", off is not None and time.time() - t0 < 10, off)


class FakeApp(UC.AutoUpdateMixin):
    def __init__(self):
        self.s, self.q, self.rq, self.log = {}, queue.Queue(), queue.Queue(), []

    def _append(self, t):
        self.log.append(t)


def drain(app, s=5):
    end = time.time() + s
    while time.time() < end:
        try:
            app.rq.get(timeout=0.2)()
            return
        except queue.Empty:
            pass


app = FakeApp()
app.upd_notice, app.upd_last, app.upd_last_text, app._upd_busy = None, None, "never", False


def offline():
    raise urllib.error.URLError("no network")


app.update_checker = offline
check("check starts in the background", app.update_check_now(manual=False))
drain(app)
logged = []
while not app.q.empty():
    logged.append(app.q.get())
check("offline: silent (no notice), one log line", app.upd_notice is None and len(logged) == 1 and "trying again later" in logged[0], logged)
app.update_checker = lambda: dict(version="a0.9.5", url="")
app.update_check_now(manual=False)
drain(app)
snap = {}
app._autoupd_snapshot(snap)
check("update found: notice with the version (PC + phone)", app.upd_notice["version"] == "a0.9.5"
      and snap["upd_notice"]["version"] == "a0.9.5" and any("a0.9.5 is available" in x for x in app.log), (snap, app.log))
check("notice text says nothing installs automatically", "Nothing installs by itself" in page and "upd_notice" in page)
src = open(UC.__file__, encoding="utf-8").read()
check("update check never downloads / installs", "install_staged" not in src and ".download(" not in src)

# Z only: the Updates plugin's checker (uses the stored key; check only)
try:
    import launcher_updater as LU
except ImportError:
    LU = None
if LU is not None:
    class FU:
        def __init__(self, result):
            self.lock = threading.RLock()
            self.state, self.message, self.details, self.available, self._gh = "up_to_date", "m0", "", None, None
            self.tokens = types.SimpleNamespace(load=lambda: "x")
            self.result, self.calls = result, 0

        def check(self):
            self.calls += 1
            self.state = self.result["state"]
            self.message = self.result.get("message", "")
            self.available = self.result.get("available")
            return dict(self.result)

        def status(self):
            return dict(state=self.state, available=self.available)

    fa = types.SimpleNamespace(s={}, root=types.SimpleNamespace(after=lambda *a: None), rq=queue.Queue(),
                               _autoupd_init=lambda: None, q=queue.Queue())
    pl = LU.UpdatesPlugin(fa, updater=FU(dict(state="available", available=dict(version="a0.9.5Z"))))
    check("Z: plugin registers the automatic checker", fa.update_checker == pl.auto_check)
    check("Z: found -> version, nothing downloaded", pl.auto_check() == dict(version="a0.9.5Z", url="") and pl.u.state == "available")
    pl2 = LU.UpdatesPlugin(fa, updater=FU(dict(state="error", message="Can't reach GitHub", details="")))
    try:
        pl2.auto_check()
        e2 = None
    except RuntimeError as e:
        e2 = e
    check("Z: offline -> raises for the log, state put back (silent)", e2 is not None and pl2.u.state == "up_to_date"
          and pl2.u.message == "m0", (e2, pl2.u.state))
    pl3 = LU.UpdatesPlugin(fa, updater=FU(dict(state="available", available=dict(version="a0.9.5Z"))))
    pl3.pending = dict(version="a0.9.4Z", timing="after_stop")
    pl3.auto_check()
    check("Z: a waiting install is left alone (no check)", pl3.u.calls == 0)

# --- PIN rule rollback ----------------------------------------------------------------------------------------------
check("PIN 4-12 digits again", R.MIN_PIN_LAN == 4 and R.MAX_PIN_LEN == 12)
dsrc = open(os.path.join(ROOT, "mkl", "dashboard.py"), encoding="utf-8").read()
check("PC label + check say 4-12", "PIN: 4\u201312 digits" in dsrc and "PIN must be 4-12 digits" in dsrc and "6-12" not in dsrc)
cfg = dict(allow_control=True, pin_hash=R.hash_pin("2468"), pin_len=4, host="0.0.0.0")
check("saved 4-digit PIN signs in on the network", R.Control(lambda: cfg, lambda a, p: (200, "")).login("2468", "c")[0] == 200)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
