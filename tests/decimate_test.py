"""Chart smoothing: cull points outside the visible time range + one min/max pair per pixel column (spikes stay) on the
desktop charts and the phone page; hover readouts report real data points.
  xvfb-run -a python tests/decimate_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import json, math, os, random, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import mimickit_remote as R

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


random.seed(1)
N = 20000
xs = [i * 0.01 for i in range(N)]
ys = [math.sin(i / 300) + random.uniform(-0.05, 0.05) for i in range(N)]
ys[7777] = 9.0
ys[12345] = -7.0
ys[15000] = float("nan")
dx, dy = R.minmax_decimate(xs, ys, xs[0], xs[-1], 400)
check(
    "full view: about 2 points per column", len(dx) <= 2 * 400 + 4 and len(dx) >= 400, str(len(dx))
)
check("spikes survive (max 9, min -7)", 9.0 in dy and -7.0 in dy)
check("NaN gap kept as a break", any(v != v for v in dy))
check("points stay in time order", all(dx[i] <= dx[i + 1] for i in range(len(dx) - 1)))
fin = [v for v in dy if v == v]
full = [v for v in ys if v == v]
check("min/max of the drawn line equal the data's", min(fin) == min(full) and max(fin) == max(full))
zx, zy = R.minmax_decimate(xs, ys, 50.0, 60.0, 400)
check(
    "zoomed: culled to the window (+1 sample each side) and reduced",
    49.985 <= zx[0] <= 50.02 and 59.98 <= zx[-1] <= 60.015 and len(zx) <= 802,
    "%s..%s n=%d" % (zx[0], zx[-1], len(zx)),
)
sx, sy = R.minmax_decimate(xs[:300], ys[:300], 0, 3, 400)
check("sparse data comes back unchanged", sx == xs[:300] and sy == ys[:300])
check("empty series", R.minmax_decimate([], [], 0, 1, 10) == ([], []))
t0 = time.time()
[R.minmax_decimate(xs, ys, 10, 150, 900) for _ in range(10)]
dt = (time.time() - t0) / 10
check("fast enough for drag/zoom (20k points < 40 ms)", dt < 0.04, "%.1f ms" % (dt * 1000))

# ---------- desktop chart
import tkinter as tk, mimickit_launcher as G
from matplotlib.backend_bases import MouseEvent

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
fmk = os.path.join(HERE, "fake_mimickit")
G.filedialog.askdirectory = lambda **k: fmk
root = tk.Tk()
root.geometry("1280x880")
app = G.App(root)
root.update()
app.CHART_MIN_2, app.CHART_MIN_3 = 0, 10**6  # pin the 2-chart layout (Return + Speed) whatever the height (Z adds rows)
app._chart_short = 1
app._make_axes()
root.update()
ax = app.ax1
for a in app._axes():
    a.clear()
(ln,) = ax.plot(xs, ys, marker="o", markersize=3, gid="cur1", label="Train")
app.ax2.plot(xs[::100], [1.0] * len(xs[::100]), gid="cur3")
app._apply_view()
app.canvas.draw()
root.update()
w = int(ax.bbox.width)
n = len(ln.get_xdata())
check("desktop: drawn points ~2 per pixel column", n <= 2.2 * w + 4, "%d points for %d px" % (n, w))
check("desktop: spikes drawn", 9.0 in list(ln.get_ydata()) and -7.0 in list(ln.get_ydata()))
check(
    "desktop: y range from the full data",
    app._full_range(ax)[1] > 9.0 and app._full_range(ax)[0] < -7.0,
)
app._set_x((50.0, 52.0))
app.canvas.draw()
root.update()
d = list(ln.get_xdata())
check(
    "desktop: zoom culls to the window and shows full detail",
    d[0] <= 50.0 <= d[1] and d[-1] >= 52.0 and len(d) <= 205 and len(d) >= 195,
    "n=%d" % len(d),
)
app._set_x((0, 200))
app.canvas.draw()
root.update()
X, Y = ax.transData.transform((77.77, 9.0))
e = MouseEvent("motion_notify_event", app.canvas, X + 3, Y - 2)
hv = app._hover(e)
check("desktop hover: readout is the real data point (the spike)", hv == (xs[7777], 9.0), str(hv))
X, Y = ax.transData.transform((xs[4321], ys[4321]))
hv = app._hover(MouseEvent("motion_notify_event", app.canvas, X, Y))
check(
    "desktop hover: ordinary point exact",
    hv and abs(hv[0] - xs[4321]) < 0.05 and hv[1] in ys,
    str(hv),
)
txts = [t.get_text() for t in ax.texts]
check("desktop hover: single readout", len(txts) == 1, str(txts))
app._progress_tick(force=True)
root.update()
app._hover(MouseEvent("motion_notify_event", app.canvas, X, Y))
check(
    "hover after a refresh: one readout, no stale artists",
    len(app.ax1.texts) <= 1 and sum(1 for l in app.ax1.get_lines() if l.get_gid() == "hover") <= 1,
)
snap = {}
app._publish = (
    app._publish
)  # series() is internal: check the snapshot via R.minmax_decimate size budget instead
root.destroy()

# ---------- phone page (headless Chrome): same culling/decimation, readout from full data
chrome = next(
    (shutil.which(c) for c in ("google-chrome", "chromium", "chromium-browser") if shutil.which(c)),
    None,
)
if not chrome:
    print("(no headless Chrome: phone checks skipped)")
else:
    big = {
        "charts": {
            "return": [
                {
                    "role": "cur1",
                    "label": "Train",
                    "x": xs,
                    "y": [None if v != v else v for v in ys],
                }
            ],
            "rate": [{"role": "cur3", "x": [0, 200], "y": [7, 7.5]}],
        },
        "state": "x",
    }
    mock = (
        "<script>Object.defineProperty(document,'title',{configurable:true,get(){return (document.querySelector('title')||{}).textContent||''},set(v){if(/^(RESULT|ERR)/.test(v)||!/^(RESULT|ERR)/.test(this.title)){const t=document.querySelector('title');if(t)t.textContent=v}}});window.onerror=(m,s,l)=>{document.title='ERR '+m+' @'+l};window.fetch=async()=>({ok:true,json:async()=>(%s)});</script>"
        % json.dumps(big)
    )
    test = r"""<script>
async function run(){await new Promise(r=>setTimeout(r,300));const cv=document.getElementById('c1'),o={};
 o.full=+cv.dataset.drawn;o.w=GEOM.c1.W;view=[50,52];draw();o.zoom=+cv.dataset.drawn;
 const [a,b]=decim(S.charts.return[0].x,S.charts.return[0].y,0,199.99,400);o.jsn=a.length;o.jsmax=Math.max(...b.filter(v=>v!==null));o.jsmin=Math.min(...b.filter(v=>v!==null));
 view=null;draw();const G=GEOM.c1,r=cv.getBoundingClientRect();
 const px=G.L+(77.77-G.x0)/(G.x1-G.x0)*G.W,py=6+(1-(9-G.y0)/(G.y1-G.y0))*G.Hh;const h=readout(cv,r.left+px+2,r.top+py+2);o.hov=h&&[h.x,h.y];
 document.title='RESULT'+JSON.stringify(o)}
setTimeout(run,500);</script>"""
    html = R.PAGE.replace("<title>", mock + "<title>", 1).replace("</body>", test + "</body>")
    dd = tempfile.mkdtemp()
    f = os.path.join(dd, "p.html")
    open(f, "w").write(html)
    r = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--user-data-dir=" + os.path.join(dd, "u"),
            "--window-size=390,844",
            "--virtual-time-budget=15000",
            "--dump-dom",
            "file://" + f,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    m = re.search(r"<title>RESULT(\{.*?\})</title>", r.stdout)
    o = json.loads(m.group(1)) if m else {}
    check(
        "phone page ran",
        bool(m),
        (re.search(r"<title>(.*?)</title>", r.stdout) or [0, ""])[1] if not m else "",
    )
    check(
        "phone: full view draws ~2 points per pixel column",
        o.get("full", 1e9) <= 2 * o.get("w", 0) + 8,
        "%s for %s px" % (o.get("full"), o.get("w")),
    )
    check("phone: zoom culls to the window", 190 <= o.get("zoom", 0) <= 215, str(o.get("zoom")))
    py_ = R.minmax_decimate(xs, [None if v != v else v for v in ys], 0, 199.99, 400)
    check(
        "phone decim() matches Python minmax_decimate",
        o.get("jsn") == len(py_[0]) and o.get("jsmax") == 9 and o.get("jsmin") == -7,
        "%s vs %d" % (o.get("jsn"), len(py_[0])),
    )
    check(
        "phone readout = the real spike point", o.get("hov") == [xs[7777], 9.0], str(o.get("hov"))
    )

# a0.8.0: the desktop charts use a numpy version - must give exactly the same points
try:
    from mkl.charts import np_decimate as _npd
except ImportError:
    from mkl import charts as _C
    _npd = getattr(_C, "np_decimate", None) or _C.ChartsMixin.np_decimate
import numpy as _np

bad = 0
for case in range(300):
    n = random.randint(0, 3000)
    xs2 = sorted(random.uniform(0, 100) for _ in range(n))
    ys2 = [float("nan") if random.random() < 0.02 else random.gauss(0, 1) for _ in range(n)]
    x0 = random.uniform(-10, 90)
    x1 = x0 + random.uniform(0.1, 60)
    cols = random.randint(1, 900)
    a = R.minmax_decimate(xs2, ys2, x0, x1, cols)
    bx, by = _npd(_np.array(xs2, float), _np.array(ys2, float), x0, x1, cols)
    same = list(a[0]) == list(bx) and all((u == v) or (u != u and v != v) for u, v in zip(a[1], by)) and len(a[1]) == len(by)
    bad += not same
check("numpy decimation == reference on 300 random cases", bad == 0, "%d differ" % bad)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
