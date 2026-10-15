"""Desktop charts draw like the phone page: one smooth polyline per series (no per-point markers), reduced to the
visible window at ~1 min/max pair per pixel column, through the REAL refresh path (_progress_tick), and the number
of drawn items stays constant however big the history is or where you zoom. Hover still snaps to real data.
xvfb-run -a python tests/chart_lines_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
CFG = os.path.join(tempfile.mkdtemp(), "s.json")  # own settings (no first-run prompt, nothing left by other tests)
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = CFG
open(CFG, "w").write('{"mimickit": %s}' % __import__("json").dumps(os.path.join(HERE, "fake_mimickit")))
import tkinter as tk, mimickit_launcher as G
from matplotlib.backend_bases import MouseEvent

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
G.App._gpu_poll_thread = lambda self: None


def history(n):
    return {
        "Samples": [i * 1e5 for i in range(n)],
        "Train_Return": [float(i % 97) for i in range(n)],
        "Test_Return": [float(i % 13) for i in range(n)],
        "Wall_Time": [i / 100 for i in range(n)],
        "Iteration": list(range(n)),
    }


root = tk.Tk()
root.geometry("1280x880")
app = G.App(root)
root.update()
LOG = {}
src = app._progress_sources
app._progress_sources = lambda: (lambda r: (r[0], [], r[2], LOG["log"], r[4], r[5], "console"))(src())


def items():
    """Drawn things: lines + markers actually rendered (a marker per drawn vertex when a marker is set)."""
    lines = [l for ax in app._axes() for l in ax.get_lines() if l.get_gid() != "hover"]
    markers = sum(len(l.get_xdata()) for l in lines if l.get_marker() not in ("None", "", None, " "))
    colls = sum(len(ax.collections) for ax in app._axes())
    return len(lines), markers, colls, max(len(l.get_xdata()) for l in lines)


def refresh(n):
    LOG["log"] = history(n)
    app._auto_follow()
    app.canvas.draw()
    root.update()


counts = {}
for n in (500, 50000):
    refresh(n)
    counts[n] = items()
    print("history %6d points: %d lines, %d markers, %d collections, max %d vertices per line" % ((n,) + counts[n]))
w = int(app.ax1.bbox.width)
check("no per-point markers (50k history)", counts[50000][1] == 0, counts[50000])
check("item count independent of history size", counts[500][:3] == counts[50000][:3], counts)
check("item count small (one line per series)", counts[50000][0] <= 6 and counts[50000][2] == 0, counts[50000])
check("vertices bounded by the pixel width", counts[50000][3] <= 2 * w + 4, "%d for %d px" % (counts[50000][3], w))
for xl in ((100.0, 120.0), (0.0, 5000.0), (2500.0, 2500.5)):
    app._set_x(xl)
    app.canvas.draw()
    root.update()
    c = items()
    check("zoom %s: same items, no markers, bounded" % (xl,), c[:3] == counts[50000][:3] and c[3] <= 2 * w + 4, c)
ln = app.ax1.get_lines()[0]
d = list(ln.get_xdata())
check("zoomed line only holds the visible window (+1 neighbour each side)", len(d) <= 2 * w + 4 and d[0] < 2500.0 < d[-1])
app._set_x((1000.0, 1010.0))
app.canvas.draw()
root.update()
full = app._full(app.ax1.get_lines()[0])
X, Y = app.ax1.transData.transform((full[0][10003], full[1][10003]))
hv = app._hover(MouseEvent("motion_notify_event", app.canvas, X, Y))
check("hover snaps to the real data point", hv == (full[0][10003], full[1][10003]), hv)
LOG["log"] = {k: v[:1] for k, v in history(1).items()}
app._auto_follow()
app.canvas.draw()
one = [l for l in app.ax1.get_lines() if l.get_gid() == "cur1"]
check("a lone point still gets a dot", one and one[0].get_marker() == "o")
root.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
