# MimicKit Launcher - phone dashboard (read-only web page) and optional Discord/Telegram notifications.
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
"""Standard library only (http.server in a daemon thread, urllib for notifications); matplotlib (agg) for chart PNGs.
The web server never touches Tk: the GUI publishes a snapshot dict (set_snapshot) every refresh, and the only action
('Render preview') is handed to the GUI through a queue that the GUI thread drains."""

import hmac, html, io, json, mimetypes, os, queue, re, secrets, socket, threading, time, urllib.parse, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mimickit_util import log_exc

RENDER_MIN_INTERVAL = 300  # s between web-triggered previews
DISCORD_MAX_MB = 10.0  # default upload limit for webhooks (non-boosted server)
TELEGRAM_MAX_MB = 50.0  # Bot API upload limit
COLORS = {
    "cur1": "#6ea8d8",
    "cur2": "#d8a05e",
    "cur3": "#7fb38a",
    "earlier": "#8a8a8a",
    "bridge": "#8a8a8a",
}


def new_token():
    return secrets.token_urlsafe(18)


def minmax_decimate(xs, ys, x0, x1, ncols):
    """Points of one series to draw in the time window [x0, x1] at ncols pixel columns.
    Culls points outside the window (keeping one neighbour on each side so the line reaches the edges), then keeps
    per column the lowest and highest point in their original order, so spikes stay visible. NaN gaps are kept as
    breaks. Returns (xs, ys) lists. Already-sparse data comes back unchanged (all points in the window).
    """
    n = len(xs)
    if n == 0:
        return [], []
    if x1 < x0:
        x0, x1 = x1, x0
    import bisect

    lo = bisect.bisect_left(xs, x0)  # data is sorted by time
    hi = max(lo, bisect.bisect_right(xs, x1))
    lo = max(0, lo - 1)
    hi = min(n, hi + 1)
    ncols = max(1, int(ncols))
    if hi - lo <= 2 * ncols:
        return list(xs[lo:hi]), list(ys[lo:hi])
    span = (x1 - x0) or 1.0
    keep = []
    cur = None
    bmin = bmax = None
    gap = None

    def flush():
        idx = sorted(set(i for i in (bmin, bmax, gap) if i is not None))
        keep.extend(idx)

    for i in range(lo, hi):
        c = int((xs[i] - x0) / span * ncols)
        if c != cur:
            if cur is not None:
                flush()
            cur, bmin, bmax, gap = c, None, None, None
        y = ys[i]
        if y is None or y != y:
            gap = i
            continue
        if bmin is None or y < ys[bmin]:
            bmin = i
        if bmax is None or y > ys[bmax]:
            bmax = i
    flush()
    return [xs[i] for i in keep], [ys[i] for i in keep]


def nearest_point(series, x, y, sx, sy):
    """Nearest (x, y, index, series index) to (x, y) over FULL data; sx/sy = data units per pixel (for distance)."""
    best = None
    for k, (xs, ys) in enumerate(series):
        for i in range(len(xs)):
            yy = ys[i]
            if yy is None or yy != yy:
                continue
            d = ((xs[i] - x) / (sx or 1)) ** 2 + ((yy - y) / (sy or 1)) ** 2
            if best is None or d < best[0]:
                best = (d, xs[i], yy, i, k)
    return None if best is None else best[1:]


def lan_addresses():
    """Addresses a phone could use (no packets are sent: UDP connect only picks the outgoing interface)."""
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for a in socket.gethostbyname_ex(socket.gethostname())[2]:
            if a not in out and not a.startswith("127."):
                out.append(a)
    except OSError:
        pass
    return out


def is_tailscale_ip(a):
    """Tailscale hands out addresses from the CGNAT range 100.64.0.0/10."""
    try:
        import ipaddress

        return ipaddress.ip_address(a) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


def tailscale_info(timeout=4):
    """(ipv4 list, MagicDNS name or '') from the tailscale CLI if installed; ([], '') otherwise. Never raises."""
    import shutil, subprocess

    exe = shutil.which("tailscale")
    if not exe and os.name == "nt":
        for c in (
            r"C:\Program Files\Tailscale\tailscale.exe",
            r"C:\Program Files (x86)\Tailscale\tailscale.exe",
        ):
            if os.path.exists(c):
                exe = c
                break
    if not exe:
        return [], ""
    flags = 0x08000000 if os.name == "nt" else 0
    ips, name = [], ""
    try:
        out = subprocess.run(
            [exe, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        ).stdout
        me = (json.loads(out or "{}") or {}).get("Self") or {}
        name = (me.get("DNSName") or "").rstrip(".")
        ips = [a for a in me.get("TailscaleIPs") or [] if "." in a]
    except Exception as e:
        log_exc("mimickit_remote: tailscale_info", e)
    if not ips:
        try:
            out = subprocess.run(
                [exe, "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=flags,
            ).stdout
            ips = [l.strip() for l in out.splitlines() if l.strip()]
        except Exception as e:
            log_exc("mimickit_remote: tailscale_info", e)
    return ips, name


def dashboard_urls(host, port, token, labelled=False, ts=None, lan=None, hostname=None):
    """Tailscale addresses first (they work from anywhere), then LAN, then the hostname. labelled=True -> [(label, url)]."""
    if host == "127.0.0.1":
        items = [("This PC", "127.0.0.1")]
    else:
        ts_ips, ts_name = ts if ts is not None else tailscale_info()
        lan = lan_addresses() if lan is None else lan
        items, seen = [], set()

        def add(label, h):
            if h and h not in seen:
                seen.add(h)
                items.append((label, h))

        for a in ts_ips + [a for a in lan if is_tailscale_ip(a)]:
            add("Tailscale", a)
        if ts_name:
            add("Tailscale (MagicDNS)", ts_name)
        for a in lan:
            if not is_tailscale_ip(a):
                add("LAN", a)
        add("hostname", hostname or socket.gethostname())
    out = [(lab, "http://%s:%d/?t=%s" % (h, port, token)) for lab, h in items]
    return out if labelled else [u for _, u in out]


def load_qrcode():
    """Import qrcode, also right after it was pip-installed while the launcher is running (clears Python's import caches)."""
    import importlib, sys

    importlib.invalidate_caches()
    if "qrcode" in sys.modules:
        return sys.modules["qrcode"]
    try:
        import site

        importlib.reload(site)  # picks up a user site-packages dir created by the install
    except Exception as e:
        log_exc("mimickit_remote: load_qrcode", e)
    try:
        return importlib.import_module("qrcode")
    except ImportError:
        return None


# ---------------------------------------------------------------- chart PNG (agg, no pyplot, safe in any thread)
def chart_png(snap, width=7.0, height=5.6, dpi=90, dark=True):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    bg, fg, field, grid = (
        ("#1e1e1e", "#d0d0d0", "#1a1a1a", "#3a3a3a")
        if dark
        else ("#f5f5f5", "#1a1a1a", "#ffffff", "#cccccc")
    )
    fig = Figure(figsize=(width, height), dpi=dpi, layout="constrained", facecolor=bg)
    FigureCanvasAgg(fig)
    charts = (snap or {}).get("charts") or {}
    panes = [("return", "Return"), ("rate", "M samples / hour")] + (
        [("per_step", "Reward / step (%)")] if charts.get("per_step") else []
    )
    for i, (key, ylabel) in enumerate(panes):
        ax = fig.add_subplot(len(panes), 1, i + 1)
        ax.set_facecolor(field)
        for s in charts.get(key, []):
            ax.plot(
                s["x"],
                s["y"],
                color=COLORS.get(s.get("role"), fg),
                linestyle=":" if s.get("role") == "bridge" else "-",
                marker="o" if s.get("role") != "bridge" else None,
                markersize=2.5,
                label=s.get("label"),
            )
        ax.set_ylabel(ylabel, color=fg)
        ax.set_xlabel("Total samples (millions)", color=fg)
        ax.tick_params(colors=fg)
        ax.grid(True, color=grid, alpha=0.6)
        for sp in ax.spines.values():
            sp.set_color(grid)
        if any(s.get("label") for s in charts.get(key, [])):
            leg = ax.legend(loc="lower right", fontsize=8)
            leg.get_frame().set_facecolor(bg)
            for t in leg.get_texts():
                t.set_color(fg)
    title = (snap or {}).get("title", "")
    if title:
        fig.suptitle(title, color=fg, fontsize=10)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=bg)
    return buf.getvalue()


def status_text(snap):
    s = snap or {}
    parts = [s.get("title", "MimicKit Launcher"), s.get("state", "")]
    for k, lab in (
        ("session_time", "Session"),
        ("total_time", "Total training"),
        ("rate", "Speed"),
        ("samples", "Samples"),
        ("estimate", "Estimate"),
        ("per_step", "Reward/step"),
        ("vram", "VRAM"),
    ):
        if s.get(k):
            parts.append("%s: %s" % (lab, s[k]))
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------- web server
PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MimicKit</title><style>
:root{--bg:#000;--panel:#0d0d0d;--fg:#d8d8d8;--dim:#8a8a8a;--acc:#5b8db8;--b:#333}
body.light{--bg:#ececec;--panel:#fff;--fg:#1a1a1a;--dim:#666;--acc:#2f6ea3;--b:#bbb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.4 system-ui,sans-serif}
header{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:var(--panel);border-bottom:1px solid var(--b)}
h1{font-size:16px;margin:0}.card{background:var(--panel);margin:10px;padding:10px 12px;border-radius:10px;border:1px solid var(--b)}
.row{display:flex;justify-content:space-between;gap:8px;padding:2px 0}.k{color:var(--dim)}.v{text-align:right}
.bar{height:10px;background:var(--b);border-radius:5px;overflow:hidden}.bar>div{height:100%;width:0}
canvas{width:100%;height:190px;touch-action:pan-y;display:block}video{width:100%;border-radius:8px;background:#000}
button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:10px 14px;font-size:15px;width:100%}
button{min-height:44px}#ctlbtn,#theme,.seg button,.pvrow button,.bgrid button{min-height:44px}button:disabled{opacity:.5}button{user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;touch-action:manipulation}
.stoprow{display:flex;justify-content:space-between;gap:24px;margin:22px 0 6px;padding-top:12px;border-top:1px dashed var(--b)}.stoprow button.small{width:auto;font-size:13px;padding:6px 12px}small{color:var(--dim)}#state{font-weight:600}a{color:var(--acc)}
#theme{display:inline-block;min-width:32px;min-height:32px;line-height:32px;text-align:center;padding:0 6px}#ctlbtn{width:auto;padding:6px 10px;font-size:13px;margin-right:8px}#ctlbtn.off{background:var(--b);color:var(--dim)}
#pending{color:#e6bd66;font-weight:600}#pending:empty{display:none}
details.sec{border-top:1px solid var(--b);padding:6px 0}details.sec summary{font-weight:600;cursor:pointer;padding:4px 0}
.cnt{color:var(--dim);font-weight:400}.bgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:6px 0}
button.sec2{background:var(--b);color:var(--fg)}button.danger{background:#b23b3b}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;align-items:center;justify-content:center;z-index:9}
.modal.on{display:flex}.mbox{background:var(--panel);border:1px solid var(--b);border-radius:12px;padding:14px;width:min(92vw,380px)}
.hold{position:relative;overflow:hidden}.hold>i{position:absolute;left:0;top:0;bottom:0;width:0;background:rgba(255,255,255,.25)}
input,select{background:var(--bg);color:var(--fg);border:1px solid var(--b);border-radius:8px;padding:8px;font-size:15px;width:100%}
input[type=checkbox]{width:auto;vertical-align:middle}input[type=range]{padding:0;border:0;background:none;accent-color:var(--acc)}
.pvrow{display:flex;align-items:center;gap:8px;margin-top:6px}.pvrow button{width:auto;min-width:64px;padding:6px 10px}.pvrow small{white-space:nowrap}
.seg{display:inline-flex;gap:4px}.seg button{width:auto;padding:4px 10px;font-size:13px;background:var(--b);color:var(--fg)}.seg button.on{background:var(--acc);color:#fff}
select{width:auto;max-width:65%;padding:4px 6px;font-size:13px}
</style></head><body>
<header><h1 id="title">MimicKit</h1><span><button id="ctlbtn" class="off">Controls: off</button><small><a href="#" id="theme">light</a> · <span id="age"></span></small></span></header>
<div class="card" id="panel" style="display:none"><b>Controls</b> <small id="ctlnote"></small>
<div id="ctloff" style="display:none"><p id="ctlofft">Turned off on the PC.</p><small>Enable "Allow phone control" in the launcher (Settings &rarr; Phone + notifications) and set a PIN.</small></div>
<div id="ctlon">
<div id="pinbox" style="display:none"><p><small>Enter the PIN set on the PC (once; you stay signed in for 12 h on this phone).</small></p>
<input id="pin" type="password" inputmode="numeric" autocomplete="off" placeholder="PIN"><p></p><button id="pinok">Sign in</button><p><small id="pinmsg"></small></p></div>
<details class="sec" id="s_train"><summary>Training <span class="cnt" id="n_train"></span></summary><div class="bgrid">
<button id="a_resume">Resume</button></div>
<div class="stoprow"><button class="sec2 small" id="a_stopsave">Stop after next save</button><button class="danger small" id="a_stopnow">Stop now</button></div>
<small>Training saves its progress by itself every few minutes.</small></details>
<details class="sec" id="s_tweak"><summary>Next-resume tweaks <span class="cnt" id="n_tweak"></span></summary>
<p><small>Applied the next time training is resumed.</small></p><div class="bgrid"><input id="t_envs" type="number" min="1" max="65536" placeholder="Parallel sims, e.g. 64">
<button class="sec2" id="a_tweak">Queue for next resume</button></div><small id="tweakmsg"></small></details>
<details class="sec" id="s_runs"><summary>Runs <span class="cnt" id="n_runs"></span></summary><small id="runbusy"></small>
<div class="row"><span class="k">Config</span><select id="r_cfg"></select></div><small id="r_help"></small>
<div class="row"><span class="k">Parallel sims</span><input id="r_envs" type="number" min="1" max="65536" step="1" style="width:45%"></div><small id="r_envs_hint">Whole number, e.g. 64</small>
<div class="row"><span class="k">Output folder</span><input id="r_out" autocomplete="off" spellcheck="false" style="width:60%"></div>
<div class="row"><span class="k">Overwrite</span><label><input type="checkbox" id="r_ovw"> replace an earlier run there</label></div>
<div class="bgrid"><button id="a_start">Start new training</button></div>
<div class="row"><span class="k">Continue from</span><select id="r_src"></select></div><small id="r_srcinfo"></small>
<div class="bgrid"><button class="sec2" id="a_cont">Continue from run</button></div><small id="runmsg"></small></details>
<details class="sec" id="s_patch"><summary>MimicKit patches <span class="cnt" id="n_patch"></span></summary><div id="plist"></div><small id="patchmsg"></small></details>
</div><p><small id="ctlmsg"></small></p></div>
<div class="modal" id="modal"><div class="mbox"><b id="m_title">Stop training now?</b><p><small id="m_text"></small></p>
<div class="bgrid"><button id="m_keep">Keep training</button><button class="sec2" id="m_alt">Stop after next save</button></div>
<button class="danger" id="m_hold" disabled><span id="m_holdt">Yes, stop now</span></button>
<p><small id="m_msg"></small></p></div></div>
<div class="card"><div id="state">loading...</div><div id="pending"></div>
<div class="row"><span class="k">Session</span><span class="v" id="session_time"></span></div>
<div class="row"><span class="k">Total training</span><span class="v" id="total_time"></span></div>
<div class="row"><span class="k">Samples</span><span class="v" id="samples"></span></div>
<div class="row"><span class="k">Speed</span><span class="v" id="rate"></span></div>
<div class="row"><span class="k">Estimate</span><span class="v" id="estimate"></span></div>
<div class="row"><span class="k">Reward / step</span><span class="v" id="per_step"></span></div>
<div class="row"><span class="k">VRAM</span><span class="v" id="vram"></span></div><div class="bar"><div id="vbar"></div></div></div>
<div class="card"><small>Return - drag sideways to pan, pinch to zoom time, double-tap to reset</small><canvas id="c1"></canvas>
<small>M samples / hour</small><canvas id="c2"></canvas>
<div id="psw" style="display:none"><small>Avg reward per step (%)</small><canvas id="c3"></canvas></div></div>
<div class="card"><div id="pv"><small>No preview yet.</small></div>
<div id="pvc" style="display:none"><div class="pvrow"><button class="sec2" id="pv_play">Play</button><input type="range" id="pv_seek" min="0" max="1000" value="0" step="1"><small id="pv_time">0:00 / 0:00</small></div>
<details class="sec" id="s_pv"><summary>Preview options <span class="cnt" id="n_pv"></span></summary>
<div class="row"><span class="k">Clip</span><select id="pv_sel"></select></div>
<div class="row"><span class="k">Speed</span><span class="seg" id="pv_rate"><button data-r="0.25">0.25&times;</button><button data-r="0.5">0.5&times;</button><button data-r="1">1&times;</button></span></div>
<div class="row"><span class="k">Loop</span><label><input type="checkbox" id="pv_loop"> play again from the start</label></div>
<div class="row"><span class="k">File</span><a id="pv_dl" href="#">Download MP4</a></div>
<div id="pv_clipbox" style="display:none"><div class="row"><span class="k">Clips for a new render</span><small id="pv_clipn"></small></div><select id="pv_clips" multiple size="5" style="width:100%;max-width:100%"></select><small>Up to 4. Default = the PC's choice.</small></div></details></div><p></p>
<button id="render">Render new preview</button><div id="rprog" style="display:none;margin-top:6px"><div class="bar"><div id="rbar" style="background:var(--acc)"></div></div><small id="rstage"></small></div><p><small id="rmsg"></small></p></div>
<!--EXTRA_HTML-->
<div class="card"><small>Controls are off unless allowed on the PC (PIN required). Updates every 10 s.</small></div>
<script>
const T=new URLSearchParams(location.search).get('t')||'';const H={'X-Token':T};let S=null,view=null,pvKey='',hov=null;
const COL={cur1:'#6ea8d8',cur2:'#d8a05e',cur3:'#7fb38a',earlier:'#8a8a8a',bridge:'#8a8a8a'};
function q(id){return document.getElementById(id)}
if(localStorage.mkTheme==='light')document.body.classList.add('light');
q('theme').onclick=e=>{e.preventDefault();document.body.classList.toggle('light');localStorage.mkTheme=document.body.classList.contains('light')?'light':'dark';draw()};
function ext(series){let x0=1e300,x1=-1e300,y0=1e300,y1=-1e300;for(const s of series){for(let i=0;i<s.x.length;i++){const x=s.x[i],y=s.y[i];if(y!==y||y===null)continue;x0=Math.min(x0,x);x1=Math.max(x1,x);y0=Math.min(y0,y);y1=Math.max(y1,y)}}
 if(x0>x1)return null;const p=Math.max((y1-y0)*.08,Math.abs(y1)*.02,1e-3);return [x0,x1,y0-p,y1+p]}
// Cull to the visible time window, then one min/max pair per pixel column (spikes stay); same as minmax_decimate() in Python.
function decim(xs,ys,x0,x1,nc){const n=xs.length;if(!n)return [[],[]];let lo=0,hi=n;while(lo<n&&xs[lo]<x0)lo++;while(hi>lo&&xs[hi-1]>x1)hi--;
 lo=Math.max(0,lo-1);hi=Math.min(n,hi+1);nc=Math.max(1,nc|0);if(hi-lo<=2*nc)return [xs.slice(lo,hi),ys.slice(lo,hi)];
 const sp=(x1-x0)||1,K=[];let cur=null,mn=-1,mx=-1,gp=-1;const fl=()=>{const a=[...new Set([mn,mx,gp].filter(i=>i>=0))].sort((a,b)=>a-b);for(const i of a)K.push(i)};
 for(let i=lo;i<hi;i++){const c=Math.floor((xs[i]-x0)/sp*nc);if(c!==cur){if(cur!==null)fl();cur=c;mn=mx=gp=-1}const y=ys[i];
  if(y===null||y!==y){gp=i;continue}if(mn<0||y<ys[mn])mn=i;if(mx<0||y>ys[mx])mx=i}fl();return [K.map(i=>xs[i]),K.map(i=>ys[i])]}
function nearest(series,x,y,sx,sy){let b=null;for(const s of series){if(s.role==='bridge')continue;for(let i=0;i<s.x.length;i++){const yy=s.y[i];if(yy===null||yy!==yy)continue;
 const d=((s.x[i]-x)/sx)**2+((yy-y)/sy)**2;if(!b||d<b.d)b={d,x:s.x[i],y:yy,label:s.label||''}}}return b}
const GEOM={};
function chart(cv,series){const r=window.devicePixelRatio||1,w=cv.clientWidth,h=cv.clientHeight;cv.width=w*r;cv.height=h*r;
 const g=cv.getContext('2d');g.scale(r,r);const cs=getComputedStyle(document.body);g.fillStyle=cs.getPropertyValue('--panel');g.fillRect(0,0,w,h);
 const e=ext(series);if(!e){g.fillStyle=cs.getPropertyValue('--dim');g.fillText('no data yet',10,20);return}
 let [x0,x1,y0,y1]=e;if(view){x0=view[0];x1=view[1]}const L=44,B=18,W=w-L-6,Hh=h-B-6;
 const X=x=>L+(x-x0)/(x1-x0||1)*W,Y=y=>6+(1-(y-y0)/(y1-y0||1))*Hh;GEOM[cv.id]={x0,x1,y0,y1,L,W,Hh,series};g.strokeStyle=cs.getPropertyValue('--b');g.fillStyle=cs.getPropertyValue('--dim');g.font='11px sans-serif';
 for(let i=0;i<=4;i++){const yy=y0+(y1-y0)*i/4,py=Y(yy);g.beginPath();g.moveTo(L,py);g.lineTo(L+W,py);g.stroke();g.fillText(yy.toPrecision(3),2,py+4)}
 for(let i=0;i<=4;i++){const xx=x0+(x1-x0)*i/4;g.textAlign=i==0?'left':i==4?'right':'center';g.fillText(xx.toFixed(1),X(xx),h-4)}g.textAlign='left';
 g.save();g.beginPath();g.rect(L,0,W,h);g.clip();for(const s of series){g.strokeStyle=COL[s.role]||'#ccc';g.setLineDash(s.role==='bridge'?[3,3]:[]);g.lineWidth=1.6;g.beginPath();let st=false;
 const [dx,dy]=decim(s.x,s.y,x0,x1,W);cv.dataset.drawn=(+cv.dataset.drawn||0)+dx.length;
 for(let i=0;i<dx.length;i++){const y=dy[i];if(y===null||y!==y){st=false;continue}const px=X(dx[i]),py=Y(y);st?g.lineTo(px,py):g.moveTo(px,py);st=true}g.stroke()}
 if(hov&&hov.id===cv.id){const px=X(hov.x),py=Y(hov.y);g.strokeStyle=cs.getPropertyValue('--fg')||'#ddd';g.setLineDash([]);g.beginPath();g.arc(px,py,5,0,7);g.stroke();
  const t=(hov.label?hov.label+': ':'')+(+hov.y).toPrecision(4)+' at '+(+hov.x).toPrecision(4)+' M';g.font='12px sans-serif';const tw=g.measureText(t).width;
  const bx=Math.min(Math.max(L,px+8),L+W-tw-8),by=Math.max(16,py-10);g.fillStyle=cs.getPropertyValue('--bg')||'#111';g.fillRect(bx-3,by-12,tw+6,16);g.fillStyle=cs.getPropertyValue('--fg')||'#ddd';g.fillText(t,bx,by)}
 g.restore()}
// readout of the nearest REAL point (full data, not the drawn subset)
function readout(cv,cx,cy){const G=GEOM[cv.id];if(!G)return null;const r=cv.getBoundingClientRect(),px=cx-r.left,py=cy-r.top;
 const x=G.x0+(px-G.L)/G.W*(G.x1-G.x0),y=G.y0+(1-(py-6)/G.Hh)*(G.y1-G.y0),sx=(G.x1-G.x0)/G.W,sy=(G.y1-G.y0)/G.Hh,b=nearest(G.series,x,y,sx,sy);
 hov=(b&&b.d<40*40)?{id:cv.id,x:b.x,y:b.y,label:b.label}:null;draw();return hov}
function draw(){if(!S)return;for(const id of ['c1','c2','c3'])q(id).dataset.drawn=0;const C=S.charts||{};chart(q('c1'),C.return||[]);chart(q('c2'),C.rate||[]);
 const ps=C.per_step||[];q('psw').style.display=ps.length?'':'none';if(ps.length)chart(q('c3'),ps)}
function full(){const e=ext([].concat((S.charts||{}).return||[],(S.charts||{}).rate||[]));return e?[e[0],e[1]]:[0,1]}
// Touch: a vertical swipe scrolls the page (touch-action: pan-y + direction decided from the first movement);
// a horizontal drag pans and a two-finger pinch zooms the time axis; deep zoom is allowed (no snap-back);
// a double-tap (two quick single-finger taps without movement) resets. A pinch's second finger is never a tap.
const SLOP=8,TAP_MS=300;
for(const id of ['c1','c2','c3']){const cv=q(id);let t0=null,mode=null,moved=false,lastTap=0,multi=false;
 const pos=e=>{const r=cv.getBoundingClientRect();return [...e.touches].map(t=>[t.clientX-r.left,t.clientY-r.top])};
 const begin=e=>{const v=view||full(),r=cv.getBoundingClientRect();t0={v:v.slice(),p:pos(e),w:r.width}};
 cv.addEventListener('touchstart',e=>{if(!S)return;if(e.touches.length>1){multi=true;mode='pinch';begin(e);return}
  multi=false;mode=null;moved=false;begin(e)},{passive:true});
 cv.addEventListener('touchmove',e=>{if(!t0)return;const p=pos(e),[a,b]=t0.v,span=b-a;
  if(p.length>1&&t0.p.length>1){mode='pinch';e.preventDefault();
   const d0=Math.abs(t0.p[0][0]-t0.p[1][0])||1,d1=Math.abs(p[0][0]-p[1][0])||1,f=d0/d1,c=a+((t0.p[0][0]+t0.p[1][0])/2)/t0.w*span;
   let nv=[c-(c-a)*f,c+(b-c)*f];if(nv[1]-nv[0]<1e-9){const m=(nv[0]+nv[1])/2;nv=[m-5e-10,m+5e-10]}view=nv;draw();return}
  if(p.length!==1||mode==='pinch')return;
  const dx=p[0][0]-t0.p[0][0],dy=p[0][1]-t0.p[0][1];
  if(!mode){if(Math.abs(dx)<SLOP&&Math.abs(dy)<SLOP)return;moved=true;mode=Math.abs(dx)>Math.abs(dy)?'pan':'scroll'}
  if(mode!=='pan')return;              // vertical: the browser scrolls the page
  e.preventDefault();view=[a-dx/t0.w*span,b-dx/t0.w*span];draw()},{passive:false});
 cv.addEventListener('touchend',e=>{if(e.touches.length>0){if(mode==='pinch')begin(e);return}
  const tap=!moved&&!multi&&mode===null;t0=null;mode=null;
  if(tap){const now=Date.now();if(now-lastTap<TAP_MS){view=null;hov=null;draw();lastTap=0}else{lastTap=now;const c=e.changedTouches[0];if(c)readout(cv,c.clientX,c.clientY)}}else lastTap=0},{passive:true});
 cv.addEventListener('mousemove',e=>{if(S)readout(cv,e.clientX,e.clientY)});cv.addEventListener('mouseleave',()=>{if(hov){hov=null;draw()}});
 cv.addEventListener('touchcancel',()=>{t0=null;mode=null;lastTap=0},{passive:true});
 cv.addEventListener('wheel',e=>{if(!S)return;e.preventDefault();const v=view||full(),r=cv.getBoundingClientRect(),c=v[0]+(e.clientX-r.left-44)/(r.width-50)*(v[1]-v[0]),f=e.deltaY<0?0.8:1.25;view=[c-(c-v[0])*f,c+(v[1]-c)*f];draw()});
 cv.addEventListener('dblclick',()=>{view=null;draw()})}
async function tick(){try{const r=await fetch('/api/status',{headers:H,cache:'no-store'});if(!r.ok){q('state').textContent='access denied ('+r.status+')';return}
 S=await r.json();q('title').textContent=S.run_name?'MimicKit \u00b7 '+S.run_name:(S.title||'MimicKit');document.title=q('title').textContent;q('state').textContent=S.state||'';
 for(const k of ['session_time','total_time','samples','rate','estimate','per_step','vram'])q(k).textContent=S[k]||'-';
 const vp=S.vram_pct;const vb=q('vbar');vb.style.width=(vp||0)+'%';vb.style.background=vp>90?'#c0392b':vp>75?'#d0952c':'#3f9a54';
 q('age').textContent=new Date().toLocaleTimeString();draw();
 pvList();rProg();
 if(S.render_msg)q('rmsg').textContent=S.render_msg;q('pending').textContent=S.pending||S.stop_save_msg||'';CTL=!!S.control;q('ctlofft').textContent=S.control_lockdown?'Phone control turned off after too many wrong PINs. Turn it back on from the PC.':'Turned off on the PC.';updCtl();runsTick();if(window.extraTick)extraTick()}catch(e){q('state').textContent='offline - retrying'}}
// ---- preview card (a0.8.0): play/pause, scrub, loop (no autoplay), clip choice, 0.25/0.5/1x, download, render progress
let PV=null,pvPinned='',SEEKING=false;const pvRate=()=>+(localStorage.mkPvRate||1);
const pvSrc=(k,dl)=>'/preview.mp4?t='+encodeURIComponent(T)+'&k='+encodeURIComponent(k)+(dl?'&dl=1':'');
const fmt=t=>{t=Math.max(0,t||0);return Math.floor(t/60)+':'+String(Math.floor(t%60)).padStart(2,'0')};
function pvUpd(){if(!PV)return;const d=PV.duration||0;q('pv_play').textContent=PV.paused?'Play':'Pause';if(!SEEKING)q('pv_seek').value=d?Math.round(PV.currentTime/d*1000):0;q('pv_time').textContent=fmt(PV.currentTime)+' / '+fmt(d)}
function pvLoad(p){pvKey=p.key;const box=q('pv');box.textContent='';const lab=document.createElement('small');lab.textContent=p.name+(p.run?' \u00b7 '+p.run:'');
 const v=document.createElement('video');v.setAttribute('playsinline','');v.preload='metadata';v.src=pvSrc(p.key);v.loop=localStorage.mkPvLoop==='1';box.append(lab,v);PV=v;
 for(const ev of ['timeupdate','play','pause','ended','loadedmetadata'])v.addEventListener(ev,()=>{if(ev==='loadedmetadata')v.playbackRate=pvRate();pvUpd()});
 v.onclick=()=>q('pv_play').click();q('pvc').style.display='';q('pv_dl').href=pvSrc(p.key,1);q('pv_dl').setAttribute('download',p.name);pvUpd()}
function pvList(){const L=(S&&S.previews)||[];const sel=q('pv_sel');q('n_pv').textContent=L.length?'('+L.length+' clips)':'';
 const keys=L.map(p=>p.key).join('|');if(sel.dataset.keys!==keys){sel.dataset.keys=keys;sel.textContent='';for(const p of L){const o=document.createElement('option');o.value=p.key;o.textContent=p.when+' \u00b7 '+p.run+' \u00b7 '+p.name.replace('preview_','').replace('.mp4','');sel.append(o)}}
 if(!L.length)return;const want=(pvPinned&&L.find(p=>p.key===pvPinned))||L[0];if(want.key!==pvKey&&!(PV&&!PV.paused))pvLoad(want);sel.value=pvKey}
q('pv_sel').onchange=()=>{const L=(S&&S.previews)||[];const p=L.find(x=>x.key===q('pv_sel').value);if(p){pvPinned=p.key;pvLoad(p)}};
q('pv_play').onclick=()=>{if(!PV)return;if(PV.paused){PV.playbackRate=pvRate();PV.play()}else PV.pause()};
q('pv_seek').addEventListener('input',()=>{SEEKING=true;if(PV&&PV.duration){PV.currentTime=q('pv_seek').value/1000*PV.duration;pvUpd()}});
q('pv_seek').addEventListener('change',()=>{SEEKING=false});
q('pv_loop').checked=localStorage.mkPvLoop==='1';q('pv_loop').onchange=()=>{localStorage.mkPvLoop=q('pv_loop').checked?'1':'0';if(PV)PV.loop=q('pv_loop').checked};
function rateBtns(){for(const b of q('pv_rate').children)b.classList.toggle('on',+b.dataset.r===pvRate())}
for(const b of q('pv_rate').children)b.onclick=()=>{localStorage.mkPvRate=b.dataset.r;if(PV)PV.playbackRate=pvRate();rateBtns()};rateBtns();
function rProg(){const r=(S&&S.render)||{};const on=r.active||(r.stage&&r.elapsed!==undefined&&Date.now()/1000-(S.updated||0)<600&&r.stage!=='Done');
 q('rprog').style.display=(r.active||r.stage)?'':'none';q('rbar').style.width=(r.pct||0)+'%';
 q('rstage').textContent=r.stage?(r.stage+(r.active?' \u00b7 '+fmt(r.elapsed||0)+' so far':'')+(r.origin?' \u00b7 started on the '+(r.origin==='phone'?'phone':'PC'):'')):'';
 if(r.active&&!window.RFAST){window.RFAST=setTimeout(()=>{window.RFAST=0;tick()},2500)}
 q('render').disabled=!!r.active;q('render').textContent=r.active?'Rendering... ('+(r.pct||0)+'%)':'Render new preview'}
q('render').onclick=async()=>{const C=S&&S.clips,sel=C?[...q('pv_clips').selectedOptions].map(o=>o.value):null;if(sel&&(sel.length<1||sel.length>4)){q('rmsg').textContent='Pick 1 to 4 clips under Preview options.';return}
 q('render').disabled=true;try{const r=await fetch('/api/render',{method:'POST',headers:Object.assign({'Content-Type':'application/json'},H),body:JSON.stringify(sel?{clips:sel}:{})});const j=await r.json();q('rmsg').textContent=j.message}catch(e){q('rmsg').textContent='failed: '+e}
 setTimeout(tick,1500)};

// ---- Controls panel (a0.7.0). Session token lives in localStorage, never in the URL; every action needs a fresh nonce.
let SES=localStorage.mkSes||'',CTL=false;
const panelOpen=()=>localStorage.mkCtlOpen==='1';
function showPanel(){q('panel').style.display=panelOpen()?'':'none'}
q('ctlbtn').onclick=()=>{localStorage.mkCtlOpen=panelOpen()?'0':'1';showPanel()};
for(const d of document.querySelectorAll('details.sec')){d.open=localStorage['mkSec_'+d.id]==='1';d.addEventListener('toggle',()=>localStorage['mkSec_'+d.id]=d.open?'1':'0')}
async function cpost(what,body){const r=await fetch('/api/control/'+what,{method:'POST',headers:Object.assign({'Content-Type':'application/json','X-Session':SES},H),body:JSON.stringify(body||{})});
 let j={};try{j=await r.json()}catch(e){}if(r.status===401){SES='';localStorage.mkSes='';updCtl()}return [r.status,j]}
let LASTBTN=null;document.addEventListener('click',e=>{const b=e.target.closest&&e.target.closest('button');if(b&&!b.closest('#modal'))LASTBTN=b},true);
async function act(action,params,msgEl,btn){const m=msgEl||q('ctlmsg');btn=btn||LASTBTN;const [c1,n]=await cpost('nonce',{action});if(c1!==200){m.textContent=n.error||('refused ('+c1+')');return}
 const lbl=btn?btn.textContent:'';if(btn){btn.disabled=true;btn.textContent='Working\u2026'}
 try{let [c,j]=await cpost(action,{nonce:n.nonce,params});
  for(let i=0;c===202&&i<120;i++){m.textContent='Working\u2026';await new Promise(r=>setTimeout(r,1500));[c,j]=await cpost(action,{nonce:n.nonce,params})}
  m.textContent=c===202?'Still working on the PC - check again in a minute.':(j.message||j.error||('status '+c))}
 finally{if(btn){btn.textContent=lbl;btn.disabled=false}}setTimeout(tick,500)}
function updCtl(){const b=q('ctlbtn');b.textContent=CTL?'Controls':'Controls: off';b.classList.toggle('off',!CTL);
 q('ctloff').style.display=CTL?'none':'';q('ctlon').style.display=CTL?'':'none';q('pinbox').style.display=CTL&&!SES?'':'none';
 for(const id of ['s_train','s_tweak','s_runs','s_patch'])q(id).style.display=SES?'':'none';
 const run=S&&S.running;q('a_resume').disabled=!!run;q('a_stopnow').disabled=!run;q('a_stopsave').disabled=!run;
 q('a_stopsave').textContent=S&&S.stop_save?'Cancel stop after save':'Stop after next save';
 q('n_train').textContent='(3 of 4)';const tw=(S&&S.tweaks)||{};const nt=Object.keys(tw).length;q('n_tweak').textContent=nt?'('+nt+' pending)':'(0)';
 q('tweakmsg').textContent=nt?'Pending until next resume: '+Object.entries(tw).map(([k,v])=>(k==='num_envs'?'parallel sims':k)+' = '+v).join(', '):'';}
q('pinok').onclick=async()=>{const [c,j]=await cpost('login',{pin:q('pin').value});q('pin').value='';
 if(c===200){SES=j.session;localStorage.mkSes=SES;q('pinmsg').textContent=''}else q('pinmsg').textContent=j.error||('refused ('+c+')');updCtl()};
function modal(o){q('m_title').textContent=o.title;q('m_text').textContent=o.text||'';q('m_msg').textContent='';q('m_alt').textContent=o.alt?'Stop after next save':'Cancel';
 q('m_hold').style.display=o.hold?'':'none';HOLDTXT=o.holdText||'stop now';q('m_alt').style.display=(o.hold&&!o.alt)?'none':'';q('m_keep').textContent=o.keep||'Keep training';q('modal').classList.add('on');MODAL=o;
 if(o.hold){const h=q('m_hold');h.disabled=true;clearTimeout(MODAL_T);clearInterval(MODAL_I);let left=Math.round((o.timeout||(o.onhold?15000:5000))/1000);
  const lab=()=>q('m_holdt').textContent='Yes, '+HOLDTXT+' ('+left+' s)';lab();MODAL_T=setTimeout(()=>{h.disabled=false},400);
  MODAL_I=setInterval(()=>{left--;if(left<=0){closeModal();q('ctlmsg').textContent='Cancelled (no answer).'}else lab()},1000)}}
let HOLDTXT='stop now',MODAL=null,MODAL_T=0,MODAL_I=0;const closeModal=()=>{q('modal').classList.remove('on');clearTimeout(MODAL_T);clearInterval(MODAL_I);MODAL=null};
document.addEventListener('contextmenu',e=>{if(e.target.closest&&e.target.closest('button'))e.preventDefault()});
q('m_keep').onclick=()=>{if(MODAL&&MODAL.ok&&!MODAL.hold){const o=MODAL;closeModal();o.ok()}else closeModal()};
q('m_alt').onclick=()=>{const a=MODAL&&MODAL.alt;closeModal();if(a)act('stop_after_save',{},null,q('a_stopsave'))};
// a0.8.3: tap + confirm (hold-to-confirm failed on Android: long-press opens a system gesture)
q('m_hold').onclick=()=>{if(q('m_hold').disabled||!MODAL)return;const f=MODAL.onhold;closeModal();if(f)f();else act('stop_now',{},null,q('a_stopnow'))};
q('a_stopnow').onclick=()=>modal({title:'Stop training now?',text:'Anything since the last save is lost. Stop after next save keeps it.',alt:true,hold:true});
q('a_stopsave').onclick=()=>{const c=S&&S.stop_save;modal({title:c?'Cancel the stop after next save?':'Stop after the next save?',text:c?'Training keeps going.':'Training stops right after its next save - nothing is lost.',keep:'Cancel',hold:true,holdText:c?'cancel it':'stop after save',timeout:5000,onhold:()=>act(c?'cancel_stop':'stop_after_save',{},null,q('a_stopsave'))})};
q('a_resume').onclick=()=>modal({title:'Resume training?',text:'Starts from the latest saved progress on the PC.',keep:'Resume',ok:()=>act('resume')});
q('a_tweak').onclick=()=>{const v=q('t_envs').value.trim();const n=Number(v);modal({title:'Use '+v+' parallel sims for the next resume?',keep:'Confirm',ok:()=>act('tweaks',{num_envs:Number.isInteger(n)?n:v},q('tweakmsg'))})};
// ---- Runs + MimicKit patches (a0.8.0): names/keys only come from the PC's lists; the PC checks everything again
let RU_SIG='',RU_CFG='';const esc=t=>String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function opts(sel,items,cur){const v=sel.value;sel.innerHTML=items.map(([k,t])=>'<option value="'+esc(k)+'">'+esc(t)+'</option>').join('');sel.value=(v&&items.some(i=>i[0]===v))?v:(cur&&items.some(i=>i[0]===cur)?cur:(items[0]?items[0][0]:''))}
let CL_SIG='';function clipsTick(){const C=S&&S.clips;q('pv_clipbox').style.display=C?'':'none';if(!C)return;const sig=JSON.stringify(C);
 if(sig!==CL_SIG){CL_SIG=sig;q('pv_clips').innerHTML=C.all.map(n=>'<option'+(C.chosen.includes(n)?' selected':'')+'>'+esc(n)+'</option>').join('')}
 const n=[...q('pv_clips').selectedOptions].length;q('pv_clipn').textContent=n+' of 4';q('pv_clipn').style.color=n>4?'#e6bd66':''}
function runsTick(){clipsTick();const R=S&&S.runs_ui;if(!R)return;const sig=JSON.stringify([R.configs,R.runs.map(r=>r.key)]);
 if(sig!==RU_SIG){RU_SIG=sig;opts(q('r_cfg'),R.configs.map(c=>[c,c+((R.missing||{})[c]?' (not installed)':'')]),R.config);opts(q('r_src'),R.runs.map(r=>[r.key,r.name+' \u00b7 '+r.saved]),'')}
 const c=q('r_cfg').value;if(c!==RU_CFG){RU_CFG=c;if(document.activeElement!==q('r_out'))q('r_out').value=(c===R.config?R.out:(R.outs[c]||R.out))||'';if(!q('r_envs').value)q('r_envs').value=R.num_envs||''}
 const miss=(R.missing||{})[c];q('r_help').textContent=miss?('Not installed: '+miss):((R.helps&&R.helps[c])||'');q('r_help').style.color=miss?'#e6bd66':'';const r=R.runs.find(x=>x.key===q('r_src').value);q('r_srcinfo').textContent=r?('saved '+r.saved+' \u00b7 '+r.total+' trained, '+r.sessions+' session(s)'):'No earlier runs with a model.pt yet.';
 q('runbusy').textContent=R.busy?('Running on the PC ('+(R.busy_kind||'run')+') - starting is off until it stops.'):'';const ev=q('r_envs').value.trim(),eok=/^[0-9]+$/.test(ev)&&+ev>=1&&+ev<=65536;q('r_envs_hint').style.color=eok?'':'#e6bd66';q('a_start').disabled=!!R.busy||!!miss||!eok;q('a_cont').disabled=!!R.busy||!r||!!miss||!eok;
 q('n_runs').textContent='('+R.runs.length+' earlier)';if(R.msg)q('runmsg').textContent=R.msg;
 const P=R.patches||[];q('n_patch').textContent='('+P.filter(p=>p.status==='applied').length+' of '+P.length+' applied)';
 const ps=JSON.stringify(P)+!!S.running;if(ps!==q('plist').dataset.sig){q('plist').dataset.sig=ps;
  const whyOff=(p,op)=>S.running?'Off while training runs (patches change MimicKit files).':p.status==='missing'?'MimicKit folder not found on the PC.':p.status==='unknown'?'The PC could not read this patch\u2019s state (see the PC log).':op==='apply'&&p.status==='applied'?'Already applied.':op==='revert'&&!p.can_revert?'This one cannot be reverted.':op==='revert'&&p.status==='not applied'?'Not applied, nothing to revert.':'';
  q('plist').innerHTML=P.map(p=>{const wa=whyOff(p,'apply'),wr=whyOff(p,'revert'),w=wa&&wr?(wa===wr?wa:wa+' '+wr):'';return '<div class="row"><span class="k">'+esc(p.title)+'</span><span class="v">'+esc(p.status)+'</span></div><div class="bgrid"><button class="sec2" data-p="'+esc(p.name)+'" data-op="apply"'+(wa?' disabled title="'+esc(wa)+'"':'')+'>Apply</button><button class="sec2" data-p="'+esc(p.name)+'" data-op="revert"'+(wr?' disabled title="'+esc(wr)+'"':'')+'>Revert</button></div>'+((wa||wr)&&!S.running?'<small>'+esc(w||wa||wr)+'</small>':'')}).join('')+(S.running?'<small>Training is running: patches change MimicKit files, so they are off until it stops.</small>':'');
  for(const b of q('plist').querySelectorAll('button'))b.onclick=()=>{const p=P.find(x=>x.name===b.dataset.p),op=b.dataset.op;modal({title:(op==='apply'?'Apply':'Revert')+' "'+p.title+'"?',text:p.why+' Runs started afterwards use it.',keep:'Cancel',hold:true,holdText:op,onhold:()=>act('patch',{name:p.name,op},q('patchmsg'))})}}}
q('r_envs').oninput=()=>{try{runsTick()}catch(e){}};
q('a_start').onclick=()=>{const n=Number(q('r_envs').value),c=q('r_cfg').value,o=q('r_out').value.trim(),w=q('r_ovw').checked;
 modal({title:'Start a new training run?',text:c+' \u00b7 '+n+' parallel sims \u2192 '+o+(w?' (REPLACES an earlier run there)':''),keep:'Cancel',hold:true,holdText:'start',onhold:()=>act('start_train',{config:c,num_envs:Number.isInteger(n)?n:q('r_envs').value,out:o,overwrite:w},q('runmsg'))})};
q('a_cont').onclick=()=>{const R=S.runs_ui,r=R.runs.find(x=>x.key===q('r_src').value),n=Number(q('r_envs').value),c=q('r_cfg').value,o=q('r_out').value.trim();if(!r)return;
 modal({title:'Continue from '+r.name+'?',text:'New run of '+c+' into '+o+' (a new numbered folder if that one is used), from its newest saved progress. Carries '+r.total+' of training.',keep:'Cancel',hold:true,holdText:'continue',onhold:()=>act('continue_run',{config:c,num_envs:Number.isInteger(n)?n:q('r_envs').value,out:o,src:r.key},q('runmsg'))})};
/*EXTRA_JS*/
showPanel();
tick();setInterval(tick,10000);window.addEventListener('resize',draw);
</script></body></html>"""


class Dashboard:
    def __init__(
        self,
        token,
        host="0.0.0.0",
        port=8765,
        on_render=None,
        log=None,
        min_interval=RENDER_MIN_INTERVAL,
        control=None,
        page_extra=None,
    ):
        self.page_extra = page_extra  # () -> (html, js) added by overlay plugins
        self.token, self.host, self.port = token, host, int(port)
        self.control = control  # Control or None (= no control endpoints answer anything but 'off')
        self.on_render = on_render
        self.log = log or (lambda m: None)
        self.min_interval = min_interval
        self._snap = {}
        self._lock = threading.Lock()
        self._last_render = 0.0
        self.httpd = None
        self.thread = None
        self.requests = 0

    def set_snapshot(self, snap):
        with self._lock:
            self._snap = dict(snap)

    def snapshot(self):
        with self._lock:
            return dict(self._snap)

    def start(self):
        dash = self

        class H(BaseHTTPRequestHandler):
            server_version = "MimicKitDashboard"
            timeout = 10
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _authed(self):
                u = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(u.query)
                cands = qs.get("t", []) + [self.headers.get("X-Token", "")]
                m = re.search(r"(?:^|;\s*)mkt=([^;]+)", self.headers.get("Cookie", "") or "")
                if m:
                    cands.append(m.group(1))
                return any(
                    c and hmac.compare_digest(c.encode(), dash.token.encode()) for c in cands
                )

            def _send(self, code, body, ctype="application/json", extra=None):
                if isinstance(body, str):
                    body = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                dash.requests += 1
                if not self._authed():
                    return self._send(403, '{"error": "token required"}')
                path = urllib.parse.urlparse(self.path).path
                try:
                    if path == "/":
                        return self._send(
                            200,
                            dash.page(),
                            "text/html; charset=utf-8",
                            {
                                "Set-Cookie": "mkt=%s; HttpOnly; SameSite=Strict; Path=/"
                                % dash.token
                            },
                        )
                    if path == "/api/status":
                        return self._send(200, json.dumps(dash.public_snapshot()))
                    if path == "/chart.png":
                        return self._send(200, chart_png(dash.snapshot()), "image/png")
                    if path == "/preview.mp4":
                        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                        p = dash.preview_path((qs.get("k") or [""])[0])
                        return self._file(p, download=(qs.get("dl") or [""])[0] == "1")
                    return self._send(404, '{"error": "not found"}')
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):
                dash.requests += 1
                if not self._authed():
                    self.close_connection = True
                    return self._send(403, '{"error": "token required"}')
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = 0
                n = max(0, min(n, 65536))
                raw = self.rfile.read(n) if n else b""
                path = urllib.parse.urlparse(self.path).path
                if path.startswith("/api/control/"):
                    try:
                        data = json.loads(raw or b"{}")
                        data = data if isinstance(data, dict) else {}
                    except ValueError:
                        data = {}
                    return self._send(*dash.control_request(path[13:], data, self.headers.get("X-Session", ""),
                                                             self.client_address[0]))
                if path != "/api/render":
                    return self._send(404, '{"error": "not found"}')
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {}
                clips = body.get("clips") if isinstance(body, dict) else None
                code, msg = dash.request_render(clips)
                return self._send(code, json.dumps({"message": msg}))

            def _file(self, p, download=False):
                if not p or not os.path.isfile(p):
                    return self._send(404, '{"error": "no preview yet"}')
                size = os.path.getsize(p)
                rng = self.headers.get("Range")
                start, end = 0, size - 1
                m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
                if rng and m:
                    if m.group(1):
                        start = int(m.group(1))
                        end = int(m.group(2)) if m.group(2) else size - 1
                    elif m.group(2):
                        start = max(0, size - int(m.group(2)))
                    end = min(end, size - 1)
                    if start > end or start >= size:
                        return self._send(
                            416, b"", "video/mp4", {"Content-Range": "bytes */%d" % size}
                        )
                self.send_response(206 if rng and m else 200)
                self.send_header("Content-Type", mimetypes.guess_type(p)[0] or "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                self.send_header("Cache-Control", "no-store")
                if download:
                    self.send_header("Content-Disposition", 'attachment; filename="%s"'
                                     % re.sub(r'[^A-Za-z0-9._-]', "_", os.path.basename(p)))
                if rng and m:
                    self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
                self.end_headers()
                if self.command == "HEAD":
                    return
                with open(p, "rb") as f:
                    f.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = f.read(min(256 * 1024, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)

        class S(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.httpd = S((self.host, self.port), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            kwargs=dict(poll_interval=0.5),
            daemon=True,
            name="mk-dashboard",
        )
        self.thread.start()
        self.log("phone dashboard on http://%s:%d/ (token required)" % (self.host, self.port))
        return self

    def stop(self):
        if self.httpd:
            h = self.httpd
            self.httpd = None
            threading.Thread(target=lambda: (h.shutdown(), h.server_close()), daemon=True).start()

    def control_request(self, what, data, session, client="?"):
        """-> (code, json text). Every refusal carries a plain-language 'error'."""
        c = self.control
        if c is None or not c.enabled():
            code, body = c._off() if c is not None else (403, {"error": Control.OFF_MSG})
            if c is not None:
                c.log("control: refused %s - control is off" % what)
        elif what == "login":
            code, body = c.login(str(data.get("pin", "")), client)
        elif what == "nonce":
            code, body = c.new_nonce(session, str(data.get("action", "")))
        else:
            code, body = c.act(session, data.get("nonce"), what, data.get("params"))
        return code, json.dumps(body)

    def page(self):
        html, js = "", ""
        if self.page_extra:
            try:
                html, js = self.page_extra()
            except Exception as e:
                log_exc("dashboard: page extra", e)
        return PAGE.replace("<!--EXTRA_HTML-->", html).replace("/*EXTRA_JS*/", js)

    def preview_path(self, key):
        """Local path of the preview with this key (from the PC's own list), else the newest one. Never a phone path."""
        s = self.snapshot()
        for p in s.get("previews") or []:
            if key and p.get("key") == key:
                return p.get("path")
        return (s.get("preview") or {}).get("path")

    def public_snapshot(self):
        s = self.snapshot()
        s["control"] = bool(self.control and self.control.enabled())
        s["control_lockdown"] = bool(self.control and (self.control.cfg_get() or {}).get("lockdown"))
        p = s.get("preview")
        if p:
            s["preview"] = {k: p[k] for k in ("name", "key") if k in p}  # never the local path
        if s.get("previews"):
            s["previews"] = [{k: v for k, v in x.items() if k != "path"} for x in s["previews"]]
        return s

    def request_render(self, clips=None):
        """clips: optional list of clip names for this render (the PC checks them against its own list)."""
        now = time.time()
        wait = self.min_interval - (now - self._last_render)
        if wait > 0:
            return 429, "Please wait %d s - previews are limited to one per %d min." % (
                wait,
                self.min_interval // 60 or 1,
            )
        if not self.on_render:
            return 503, "Rendering is not available."
        self._last_render = now
        try:
            ok, msg = self.on_render(clips) if clips is not None else self.on_render()
        except Exception as e:
            ok, msg = False, "failed: %s" % e
        if not ok:
            self._last_render = 0.0
        return (202 if ok else 409), msg


# ---------------------------------------------------------------- notifications
def _multipart(fields, files):
    b = "----mk%s" % uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(
            ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (b, k, v)).encode()
        )
    for k, (name, data, ctype) in files.items():
        out.write(
            (
                '--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: %s\r\n\r\n'
                % (b, k, name, ctype)
            ).encode()
        )
        out.write(data)
        out.write(b"\r\n")
    out.write(("--%s--\r\n" % b).encode())
    return out.getvalue(), "multipart/form-data; boundary=%s" % b


def http_post(url, data, ctype, timeout=60):
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": ctype, "User-Agent": "MimicKitLauncher"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(2000)


def redact(text, cfg):
    for k in ("discord_webhook", "telegram_token"):
        v = (cfg or {}).get(k)
        if v:
            text = text.replace(v, "<%s>" % k)
    from mimickit_util import scrub

    return scrub(text)  # also anything else registered / shaped like a webhook or bot token


class Notifier:
    """cfg keys: discord_webhook, telegram_token, telegram_chat, every_hours, send_preview, send_trained."""

    def __init__(self, cfg_get, log=None, post=None):
        self.cfg_get = cfg_get
        self.log = log or (lambda m: None)
        self.post = post or http_post
        self.last = time.time()

    def targets(self):
        c = self.cfg_get() or {}
        t = []
        if (c.get("discord_webhook") or "").startswith("https://"):
            t.append("discord")
        if c.get("telegram_token") and c.get("telegram_chat"):
            t.append("telegram")
        return t

    def due(self, now=None):
        c = self.cfg_get() or {}
        h = float(c.get("every_hours") or 0)
        return bool(self.targets()) and h > 0 and (now or time.time()) - self.last >= h * 3600

    def _send_one(self, target, text, png=None, video=None):
        c = self.cfg_get() or {}
        if target == "discord":
            files = {}
            if png:
                files["files[0]"] = ("chart.png", png, "image/png")
            if video:
                files["files[1]" if png else "files[0]"] = (
                    os.path.basename(video[0]),
                    video[1],
                    "video/mp4",
                )
            data, ct = _multipart(
                {
                    "payload_json": json.dumps(
                        {"content": text[:1990], "allowed_mentions": {"parse": []}}
                    )
                },
                files,
            )
            return self.post(c["discord_webhook"], data, ct)
        base = "https://api.telegram.org/bot%s/" % c["telegram_token"]
        if video:
            data, ct = _multipart(
                {
                    "chat_id": c["telegram_chat"],
                    "caption": text[:1020],
                    "supports_streaming": "true",
                },
                {"video": (os.path.basename(video[0]), video[1], "video/mp4")},
            )
            return self.post(base + "sendVideo", data, ct)
        if png:
            data, ct = _multipart(
                {"chat_id": c["telegram_chat"], "caption": text[:1020]},
                {"photo": ("chart.png", png, "image/png")},
            )
            return self.post(base + "sendPhoto", data, ct)
        data, ct = _multipart({"chat_id": c["telegram_chat"], "text": text[:4000]}, {})
        return self.post(base + "sendMessage", data, ct)

    def send(self, text, png=None, video_path=None, kind="status"):
        """Send to every configured target; never raises. Returns {target: 'ok' | error text}."""
        res = {}
        c = self.cfg_get() or {}
        for t in self.targets():
            try:
                video = None
                note = ""
                if video_path:
                    mb = os.path.getsize(video_path) / 1e6
                    lim = DISCORD_MAX_MB if t == "discord" else TELEGRAM_MAX_MB
                    if mb > lim:
                        note = (
                            "\n(preview %s is %.1f MB - over the %s limit of %.0f MB, not attached)"
                            % (os.path.basename(video_path), mb, t, lim)
                        )
                    else:
                        video = (video_path, open(video_path, "rb").read())
                code, body = self._send_one(t, text + note, png, video)
                res[t] = "ok" if 200 <= int(code) < 300 else "HTTP %s %s" % (code, body[:200])
            except Exception as e:
                res[t] = redact("%s: %s" % (type(e).__name__, e), c)
            self.log("[notify] %s %s: %s" % (kind, t, res[t]))
        if kind == "status":
            self.last = time.time()
        return res

    def send_status(self, snap, kind="status"):
        try:
            png = chart_png(snap)
        except Exception as e:
            png = None
            self.log("[notify] chart failed: %s" % e)
        return self.send(status_text(snap), png=png, kind=kind)


# ---------------------------------------------------------------- phone control (a0.7.0)
SESSION_HOURS = 12
NONCE_TTL = 120  # s a confirm-box nonce stays valid
MAX_PIN_FAILS = 5
LOCKOUT_S = 300
GLOBAL_FAILS_PER_HOUR = 20  # wrong PINs from ALL phones within an hour -> phone control is turned OFF on the PC
MIN_PIN_LAN = 6  # dashboard reachable from the network: PIN must have at least this many digits
PIN_RULES_MSG = "Phone PIN rules changed. Set a new 6\u201312 digit PIN on the PC (one-time)."
LOCKDOWN_MSG = "Phone control turned off after too many wrong PINs. Turn it back on from the PC."
ACTIONS = ("stop_after_save", "stop_now", "resume", "cancel_stop", "tweaks", "start_train", "continue_run", "patch")
TWEAK_RULES = {"num_envs": (int, 1, 65536)}
TWEAK_LABEL = {"num_envs": "Parallel sims"}  # what the phone calls it  # name -> (type, min, max); applied on the next resume


def _sk(token):
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


def hash_pin(pin, salt=None):
    salt = salt or secrets.token_hex(8)
    import hashlib

    return salt + "$" + hashlib.pbkdf2_hmac("sha256", str(pin).encode(), salt.encode(), 100000).hex()


def check_pin(pin, stored):
    if not stored or "$" not in stored:
        return False
    return hmac.compare_digest(hash_pin(pin, stored.split("$", 1)[0]), stored)


def validate_tweaks(p):
    """-> (clean dict, None) or (None, plain-language reason)."""
    if not isinstance(p, dict) or not p:
        return None, "No changes were sent."
    out = {}
    for k, v in p.items():
        if k not in TWEAK_RULES:
            return None, "'%s' can't be changed from the phone." % k
        typ, lo, hi = TWEAK_RULES[k]
        if isinstance(v, bool) or not isinstance(v, typ):
            return None, "%s must be a whole number, e.g. 64." % TWEAK_LABEL.get(k, k)
        if not lo <= v <= hi:
            return None, "%s must be between %d and %d." % (TWEAK_LABEL.get(k, k), lo, hi)
        out[k] = v
    return out, None


class Control:
    """PC-side gate for every phone control request. Thread-safe; never touches Tk.
    cfg_get() -> dict with allow_control (bool) and pin_hash; on_action(name, params) -> (http code, message)
    runs in the server thread and must only queue GUI work. Every decision is logged via log().
    a0.8.0: wrong-PIN lockout is per phone (client address), each nonce is bound to the one action it was asked for,
    extra_actions() adds overlay actions (e.g. updates) behind the same PIN + session + nonce gate."""

    ACT_WAIT_S = 3.0  # wait this long for an action's answer, then reply 202 'Working…' (phone re-asks with the nonce)

    def __init__(self, cfg_get, on_action, log=None, now=time.time, extra_actions=None, turn_off=None):
        self.cfg_get, self.on_action, self.log, self.now = cfg_get, on_action, log or (lambda m: None), now
        self.turn_off = turn_off  # turn_off(reason): switch 'Allow phone control' off on the PC (global ceiling)
        self.fail_times = []  # times of wrong PINs from any phone (last hour)
        self.extra_actions = extra_actions or (lambda: {})
        self._lock = threading.Lock()
        self.sessions = {}  # sha256(session token) -> expiry (the raw token lives only on the phone)
        self.nonces = {}  # nonce -> (session, expiry, action)
        self.used = {}  # nonce -> (code, body) : a repeated tap returns the first answer
        self.fails = {}  # client -> wrong PINs in a row
        self.lock_until = {}  # client -> time the lockout ends

    def actions(self):
        return tuple(ACTIONS) + tuple(self.extra_actions() or ())

    def enabled(self):
        c = self.cfg_get() or {}
        return bool(c.get("allow_control")) and bool(c.get("pin_hash"))

    def revoke_all(self, why=""):
        with self._lock:
            n = len(self.sessions)
            self.sessions.clear()
            self.nonces.clear()
        self.log("control: all phone sessions revoked%s (%d)" % (" - " + why if why else "", n))

    OFF_MSG = "Turned off on the PC. Enable 'Allow phone control' in the launcher's Phone settings."

    def _off(self):
        c = self.cfg_get() or {}
        return 403, {"error": LOCKDOWN_MSG if c.get("lockdown") else self.OFF_MSG}

    def _prune(self, t):
        """Drop finished lockouts, idle fail counters and wrong-PIN times older than an hour (no unbounded growth)."""
        for k in [k for k, v in self.lock_until.items() if v <= t]:
            self.lock_until.pop(k, None)
        self.fail_times = [x for x in self.fail_times if x > t - 3600]
        if len(self.fails) > 200:
            self.fails = dict(list(self.fails.items())[-100:])

    def login(self, pin, client="?"):
        if not self.enabled():
            self.log("control: refused sign-in from %s - control is off" % client)
            return self._off()
        with self._lock:
            t = self.now()
            until = self.lock_until.get(client, 0.0)
            if t < until:
                left = int(until - t) + 1
                self.log("control: refused sign-in from %s - locked for %d s" % (client, left))
                return 429, {"error": "Too many wrong PINs. Locked for %d more seconds." % left, "locked_s": left}
            self._prune(t)
            c = self.cfg_get() or {}
            if c.get("host") == "0.0.0.0" and int(c.get("pin_len") or 0) < MIN_PIN_LAN:
                self.log("control: refused sign-in from %s - PIN shorter than %d digits while reachable on the network"
                         % (client, MIN_PIN_LAN))
                return 403, {"error": PIN_RULES_MSG}
            lockdown = False
            if not check_pin(pin, c.get("pin_hash")):
                self.fail_times.append(t)
                if len(self.fail_times) >= GLOBAL_FAILS_PER_HOUR:
                    self.fail_times = []
                    self.sessions.clear()
                    self.nonces.clear()
                    lockdown = True
                else:
                    n = self.fails[client] = self.fails.get(client, 0) + 1
                    if n >= MAX_PIN_FAILS:
                        self.fails[client] = 0
                        self.lock_until[client] = t + LOCKOUT_S
                        self.log("control: %d wrong PINs from %s - that phone is locked for %d s" % (MAX_PIN_FAILS, client, LOCKOUT_S))
                        return 429, {"error": "Too many wrong PINs. Locked for %d seconds." % LOCKOUT_S, "locked_s": LOCKOUT_S}
                    self.log("control: wrong PIN from %s (%d of %d)" % (client, n, MAX_PIN_FAILS))
                    return 403, {"error": "Wrong PIN (%d tries left)." % (MAX_PIN_FAILS - n)}
            if not lockdown:
                self.fails.pop(client, None)
                tok = secrets.token_urlsafe(24)
                self.sessions[_sk(tok)] = t + SESSION_HOURS * 3600
        if lockdown:  # outside the lock: turn_off touches settings / queues GUI work
            self.log("control: %d wrong PINs within an hour (all phones) - phone control turned OFF; "
                     "turn it back on from the PC" % GLOBAL_FAILS_PER_HOUR)
            if self.turn_off:
                try:
                    self.turn_off("too many wrong PINs")
                except Exception as e:
                    log_exc("control: turn off", e)
            return 403, {"error": LOCKDOWN_MSG, "lockdown": True}
        self.log("control: phone %s signed in (session valid %d h)" % (client, SESSION_HOURS))
        return 200, {"session": tok, "hours": SESSION_HOURS}

    def _session_ok(self, s):
        k = _sk(s or "")
        exp = self.sessions.get(k)
        if s and exp and exp > self.now():
            return True
        self.sessions.pop(k, None)
        return False

    def export_sessions(self):
        """Signed-in phones (hashed tokens + expiry) for a window reload, so the phone stays signed in."""
        with self._lock:
            t = self.now()
            return {k: v for k, v in self.sessions.items() if v > t}

    def import_sessions(self, d):
        with self._lock:
            t = self.now()
            for k, v in (d or {}).items():
                if isinstance(k, str) and len(k) == 64 and isinstance(v, (int, float)) and t < v <= t + SESSION_HOURS * 3600:
                    self.sessions[k] = float(v)
        self.log("control: %d phone session(s) kept across the window reload" % len(d or {}))

    def new_nonce(self, session, action=""):
        if not self.enabled():
            self.log("control: refused confirmation for %s - control is off" % (action or "?"))
            return self._off()
        with self._lock:
            if not self._session_ok(session):
                self.log("control: refused confirmation for %s - no valid session" % (action or "?"))
                return 401, {"error": "Please enter the PIN again (session missing or expired)."}
            if action not in self.actions():
                self.log("control: refused confirmation - unknown action '%s'" % action)
                return 400, {"error": "Unknown action '%s'." % action}
            n = secrets.token_urlsafe(16)
            t = self.now()
            self.nonces = {k: v for k, v in self.nonces.items() if v[1] > t}
            self.nonces[n] = (_sk(session), t + NONCE_TTL, action)
        return 200, {"nonce": n, "ttl": NONCE_TTL, "action": action}

    def act(self, session, nonce, action, params=None):
        if not self.enabled():
            self.log("control: refused %s - control is off" % action)
            return self._off()
        with self._lock:
            if not self._session_ok(session):
                self.log("control: refused %s - no valid session" % action)
                return 401, {"error": "Please enter the PIN again (session missing or expired)."}
            if nonce and nonce in self.used:
                code, body = self.used[nonce]
                return code, dict(body, repeat=True)
            ent = self.nonces.get(nonce or "")
            if not ent or ent[0] != _sk(session) or ent[1] < self.now():
                self.nonces.pop(nonce or "", None)
                self.log("control: refused %s - missing or stale confirmation" % action)
                return 403, {"error": "This tap wasn't confirmed (or the confirm box expired). Open it again."}
            if ent[2] != action:
                self.log("control: refused %s - the confirmation was for '%s'" % (action, ent[2]))
                return 403, {"error": "This confirmation was for a different action. Open the box again."}
            self.nonces.pop(nonce, None)
            extra = self.extra_actions() or {}
            if action not in ACTIONS and action not in extra:
                self.log("control: refused unknown action '%s'" % action)
                return 400, {"error": "Unknown action '%s'." % action}
            if action == "tweaks":
                params, why = validate_tweaks(params)
                if why:
                    self.log("control: refused tweaks - %s" % why)
                    self.used[nonce] = (400, {"error": why})
                    return 400, {"error": why}
            handler = extra[action] if action in extra else None
            self.used[nonce] = (202, {"message": "Working…", "pending": True})
            if len(self.used) > 500:
                self.used = dict(list(self.used.items())[-200:])
        # the lock is released: a slow handler (GUI queue, file I/O) can't block other phones / sign-ins
        res = {}

        def run():
            try:
                if handler:
                    code, msg = handler(params if isinstance(params, dict) else {})
                else:
                    code, msg = self.on_action(action, params or {})
            except Exception as e:
                log_exc("control action")
                code, msg = 500, "The PC couldn't do that (%s)." % e
            body = {"message": msg} if code < 400 else {"error": msg}
            with self._lock:
                self.used[nonce] = (code, body)
            res["r"] = (code, body)
            self.log("control: %s -> %d %s" % (action, code, msg))

        t = threading.Thread(target=run, daemon=True, name="control-" + action)
        t.start()
        t.join(self.ACT_WAIT_S)
        if "r" in res:
            return res["r"]
        self.log("control: %s still working after %.0f s - phone told 202, it asks again" % (action, self.ACT_WAIT_S))
        return 202, {"message": "Working…", "pending": True}
