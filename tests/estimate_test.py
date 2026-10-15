"""Progress estimate on synthetic training curves: plateau fit, noise, resume dips, flat, still-linear, targets,
display smoothing.   python tests/estimate_test.py  (the GUI part needs xvfb: xvfb-run -a python tests/estimate_test.py)
"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import math, os, random, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import mimickit_launcher as G

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


random.seed(1)


def curve(n, xmax, f, noise=0.0, sessions=1, dip=0.0):
    """n points up to xmax samples split into sessions; after each resume the first points dip."""
    xs = [xmax * (i + 1) / n for i in range(n)]
    segs = []
    per = n // sessions
    for s in range(sessions):
        X = xs[s * per : (s + 1) * per if s < sessions - 1 else n]
        Y = [
            f(x) + random.gauss(0, noise) - (dip * max(0, 1 - j / 4) if s > 0 else 0)
            for j, x in enumerate(X)
        ]
        segs.append((X, Y))
    return segs


sat = lambda c: (lambda x: 10 - 8 * math.exp(-x / c))
RATE = 7.5e6  # samples / hour
# 1) clean saturating curve, 60% of the way to the 95% point
c = 1e8
x95 = c * math.log(20)
r = G.estimate_progress(curve(200, 0.6 * x95, sat(c)), RATE)
check(
    "saturating: ~88% (60% of the samples to the 95% point)",
    r["pct"] is not None and abs(r["pct"] - 100 * (1 - math.exp(-0.6 * x95 / c)) / 0.95) < 6,
    r["text"],
)
check(
    "saturating: ETA from the current rate",
    "h left" in r["text"] and "rough" in r["text"],
    r["text"],
)
r = G.estimate_progress(curve(200, 1.3 * x95, sat(c)), RATE)
check(
    "past the plateau: 99% and 'at the plateau'",
    r["pct"] == 99.0 and "at the plateau" in r["text"],
    r["text"],
)
# 2) noisy
r = G.estimate_progress(curve(300, 0.8 * x95, sat(c), noise=0.4), RATE)
want = 100 * (1 - math.exp(-0.8 * x95 / c)) / 0.95
check(
    "noisy: still close",
    r["pct"] is not None and abs(r["pct"] - want) < 12,
    "%s (true ~%d%%)" % (r["text"], want),
)
# 3) resume dips
r = G.estimate_progress(curve(300, 0.7 * x95, sat(c), noise=0.2, sessions=4, dip=3.0), RATE)
want = 100 * (1 - math.exp(-0.7 * x95 / c)) / 0.95
check(
    "resume dips ignored",
    r["pct"] is not None and abs(r["pct"] - want) < 12,
    "%s (true ~%d%%)" % (r["text"], want),
)
# 4) flat
r = G.estimate_progress(curve(200, 5e8, lambda x: 4.0, noise=0.3), RATE)
check(
    "flat: no estimate, says so",
    r["pct"] is None and "no clear improvement" in r["text"],
    r["text"],
)
# 5) still linear
r = G.estimate_progress(curve(200, 5e8, lambda x: 1 + x / 1e8, noise=0.05), RATE)
check(
    "still linear: no plateau in sight",
    r["pct"] is None and ("no plateau in sight" in r["text"] or "not stable" in r["text"]),
    r["text"],
)
# 6) too little data
r = G.estimate_progress(curve(10, 1e8, sat(c)), RATE)
check(
    "few points: not enough data yet",
    r["pct"] is None and "not enough data" in r["text"],
    r["text"],
)
# 7) early in a saturating run (curvature barely visible) must not claim a confident number
r = G.estimate_progress(curve(40, 0.08 * x95, sat(c), noise=0.3), RATE)
check("very early: no confident claim", r["pct"] is None or r["pct"] < 30, r["text"])
# 8) targets
segs = curve(200, 0.6 * x95, sat(c))
r = G.estimate_progress(segs, RATE, dict(kind="samples", value=0.6 * x95 * 2))
check("samples target: 50% + ETA", abs(r["pct"] - 50) < 1 and "h left" in r["text"], r["text"])
r = G.estimate_progress(segs, RATE, dict(kind="score", value=9.5))
check(
    "score target below plateau: % + ETA",
    r["pct"] is not None and 0 < r["pct"] < 100 and "left" in r["text"],
    r["text"],
)
r = G.estimate_progress(segs, RATE, dict(kind="score", value=11))
check(
    "score target above plateau: may not be reached",
    r["pct"] is None and "may not be reached" in r["text"],
    r["text"],
)
r = G.estimate_progress(segs, RATE, dict(kind="score", value=3))
check("score target already passed: reached", r["pct"] == 100 and "reached" in r["text"], r["text"])
# 9) GUI: smoothing/clamping of the displayed value, target persisted per run chain
if os.environ.get("DISPLAY"):
    import tkinter as tk

    G.messagebox.showinfo = lambda *a, **k: None
    G.filedialog.askdirectory = lambda **k: os.path.join(HERE, "fake_mimickit")
    root = tk.Tk()
    app = G.App(root)
    vals = [app._smooth_estimate("chainA", v) for v in (20, 90, 90, 90)]
    check(
        "display smoothing: no big jumps",
        vals[0] == 20 and all(abs(b - a) <= 10 for a, b in zip(vals, vals[1:])),
        str(vals),
    )
    check("display: new chain starts fresh", app._smooth_estimate("chainB", 70) == 70)
    app._set_target("/x/run_a", dict(kind="score", value=9.5))
    check(
        "target persisted per run chain",
        G.load_settings().get("targets", {}).get(os.path.normcase(os.path.abspath("/x/run_a")))
        == dict(kind="score", value=9.5)
        and app._get_target("/x/run_b") is None,
    )
    check(
        "target widgets + tooltip text",
        hasattr(app, "cb_target") and "rough" in G.HELP["target"].lower(),
    )
    root.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
