# MimicKit Launcher - phone dashboard (read-only web page) and optional Discord/Telegram notifications.
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
"""Standard library only (http.server in a daemon thread, urllib for notifications); matplotlib (agg) for chart PNGs.
The web server never touches Tk: the GUI publishes a snapshot dict (set_snapshot) every refresh, and the only action
('Render preview') is handed to the GUI through a queue that the GUI thread drains."""
import hmac, html, io, json, mimetypes, os, queue, re, secrets, socket, threading, time, urllib.parse, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RENDER_MIN_INTERVAL = 300          # s between web-triggered previews
DISCORD_MAX_MB = 10.0              # default upload limit for webhooks (non-boosted server)
TELEGRAM_MAX_MB = 50.0             # Bot API upload limit
COLORS = {"cur1": "#6ea8d8", "cur2": "#d8a05e", "cur3": "#7fb38a", "earlier": "#8a8a8a", "bridge": "#8a8a8a"}

def new_token(): return secrets.token_urlsafe(18)

def lan_addresses():
    """Addresses a phone could use (no packets are sent: UDP connect only picks the outgoing interface)."""
    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); out.append(s.getsockname()[0]); s.close()
    except OSError: pass
    try:
        for a in socket.gethostbyname_ex(socket.gethostname())[2]:
            if a not in out and not a.startswith("127."): out.append(a)
    except OSError: pass
    return out

def is_tailscale_ip(a):
    """Tailscale hands out addresses from the CGNAT range 100.64.0.0/10."""
    try:
        import ipaddress; return ipaddress.ip_address(a) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False

def tailscale_info(timeout=4):
    """(ipv4 list, MagicDNS name or '') from the tailscale CLI if installed; ([], '') otherwise. Never raises."""
    import shutil, subprocess
    exe = shutil.which("tailscale")
    if not exe and os.name == "nt":
        for c in (r"C:\Program Files\Tailscale\tailscale.exe", r"C:\Program Files (x86)\Tailscale\tailscale.exe"):
            if os.path.exists(c): exe = c; break
    if not exe: return [], ""
    flags = 0x08000000 if os.name == "nt" else 0
    ips, name = [], ""
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=timeout, creationflags=flags).stdout
        me = (json.loads(out or "{}") or {}).get("Self") or {}
        name = (me.get("DNSName") or "").rstrip(".")
        ips = [a for a in me.get("TailscaleIPs") or [] if "." in a]
    except Exception:
        pass
    if not ips:
        try:
            out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=timeout, creationflags=flags).stdout
            ips = [l.strip() for l in out.splitlines() if l.strip()]
        except Exception:
            pass
    return ips, name

def dashboard_urls(host, port, token, labelled=False, ts=None, lan=None, hostname=None):
    """Tailscale addresses first (they work from anywhere), then LAN, then the hostname. labelled=True -> [(label, url)]."""
    if host == "127.0.0.1":
        items = [("this PC", "127.0.0.1")]
    else:
        ts_ips, ts_name = ts if ts is not None else tailscale_info()
        lan = lan_addresses() if lan is None else lan
        items, seen = [], set()
        def add(label, h):
            if h and h not in seen: seen.add(h); items.append((label, h))
        for a in ts_ips + [a for a in lan if is_tailscale_ip(a)]: add("Tailscale", a)
        if ts_name: add("Tailscale (MagicDNS)", ts_name)
        for a in lan:
            if not is_tailscale_ip(a): add("LAN", a)
        add("hostname", hostname or socket.gethostname())
    out = [(lab, "http://%s:%d/?t=%s" % (h, port, token)) for lab, h in items]
    return out if labelled else [u for _, u in out]

def load_qrcode():
    """Import qrcode, also right after it was pip-installed while the launcher is running (clears Python's import caches)."""
    import importlib, sys
    importlib.invalidate_caches()
    if "qrcode" in sys.modules: return sys.modules["qrcode"]
    try:
        import site; importlib.reload(site)      # picks up a user site-packages dir created by the install
    except Exception:
        pass
    try:
        return importlib.import_module("qrcode")
    except ImportError:
        return None

# ---------------------------------------------------------------- chart PNG (agg, no pyplot, safe in any thread)
def chart_png(snap, width=7.0, height=5.6, dpi=90, dark=True):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    bg, fg, field, grid = ("#1e1e1e", "#d0d0d0", "#1a1a1a", "#3a3a3a") if dark else ("#f5f5f5", "#1a1a1a", "#ffffff", "#cccccc")
    fig = Figure(figsize=(width, height), dpi=dpi, layout="constrained", facecolor=bg); FigureCanvasAgg(fig)
    charts = (snap or {}).get("charts") or {}
    panes = [("return", "Return"), ("rate", "M samples / hour")] + ([("per_step", "Reward / step (%)")] if charts.get("per_step") else [])
    for i, (key, ylabel) in enumerate(panes):
        ax = fig.add_subplot(len(panes), 1, i + 1); ax.set_facecolor(field)
        for s in charts.get(key, []):
            ax.plot(s["x"], s["y"], color=COLORS.get(s.get("role"), fg), linestyle=":" if s.get("role") == "bridge" else "-",
                    marker="o" if s.get("role") != "bridge" else None, markersize=2.5, label=s.get("label"))
        ax.set_ylabel(ylabel, color=fg); ax.set_xlabel("Total samples (millions)", color=fg)
        ax.tick_params(colors=fg); ax.grid(True, color=grid, alpha=0.6)
        for sp in ax.spines.values(): sp.set_color(grid)
        if any(s.get("label") for s in charts.get(key, [])):
            leg = ax.legend(loc="lower right", fontsize=8); leg.get_frame().set_facecolor(bg)
            for t in leg.get_texts(): t.set_color(fg)
    title = (snap or {}).get("title", "")
    if title: fig.suptitle(title, color=fg, fontsize=10)
    buf = io.BytesIO(); fig.savefig(buf, format="png", facecolor=bg); return buf.getvalue()

def status_text(snap):
    s = snap or {}
    parts = [s.get("title", "MimicKit Launcher"), s.get("state", "")]
    for k, lab in (("session_time", "Session"), ("total_time", "Total training"), ("rate", "Speed"), ("samples", "Samples"),
                   ("estimate", "Estimate"), ("per_step", "Reward/step"), ("vram", "VRAM")):
        if s.get(k): parts.append("%s: %s" % (lab, s[k]))
    return "\n".join(p for p in parts if p)

# ---------------------------------------------------------------- web server
PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MimicKit dashboard</title><style>
:root{--bg:#121212;--panel:#1e1e1e;--fg:#d8d8d8;--dim:#8a8a8a;--acc:#5b8db8;--b:#333}
body.light{--bg:#ececec;--panel:#fff;--fg:#1a1a1a;--dim:#666;--acc:#2f6ea3;--b:#bbb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.4 system-ui,sans-serif}
header{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:var(--panel);border-bottom:1px solid var(--b)}
h1{font-size:16px;margin:0}.card{background:var(--panel);margin:10px;padding:10px 12px;border-radius:10px;border:1px solid var(--b)}
.row{display:flex;justify-content:space-between;gap:8px;padding:2px 0}.k{color:var(--dim)}.v{text-align:right}
.bar{height:10px;background:var(--b);border-radius:5px;overflow:hidden}.bar>div{height:100%;width:0}
canvas{width:100%;height:190px;touch-action:pan-y;display:block}video{width:100%;border-radius:8px;background:#000}
button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:10px 14px;font-size:15px;width:100%}
button:disabled{opacity:.5}small{color:var(--dim)}#state{font-weight:600}a{color:var(--acc)}
</style></head><body>
<header><h1 id="title">MimicKit</h1><small><a href="#" id="theme">light</a> · <span id="age"></span></small></header>
<div class="card"><div id="state">loading...</div>
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
<div class="card"><div id="pv"><small>No preview yet.</small></div><p></p>
<button id="render">Render preview</button><p><small id="rmsg"></small></p></div>
<div class="card"><small>Read-only dashboard: training can't be started or stopped from here. Updates every 10 s.</small></div>
<script>
const T=new URLSearchParams(location.search).get('t')||'';const H={'X-Token':T};let S=null,view=null,pvKey='';
const COL={cur1:'#6ea8d8',cur2:'#d8a05e',cur3:'#7fb38a',earlier:'#8a8a8a',bridge:'#8a8a8a'};
function q(id){return document.getElementById(id)}
if(localStorage.mkTheme==='light')document.body.classList.add('light');
q('theme').onclick=e=>{e.preventDefault();document.body.classList.toggle('light');localStorage.mkTheme=document.body.classList.contains('light')?'light':'dark';draw()};
function ext(series){let x0=1e300,x1=-1e300,y0=1e300,y1=-1e300;for(const s of series){for(let i=0;i<s.x.length;i++){const x=s.x[i],y=s.y[i];if(y!==y||y===null)continue;x0=Math.min(x0,x);x1=Math.max(x1,x);y0=Math.min(y0,y);y1=Math.max(y1,y)}}
 if(x0>x1)return null;const p=Math.max((y1-y0)*.08,Math.abs(y1)*.02,1e-3);return [x0,x1,y0-p,y1+p]}
function chart(cv,series){const r=window.devicePixelRatio||1,w=cv.clientWidth,h=cv.clientHeight;cv.width=w*r;cv.height=h*r;
 const g=cv.getContext('2d');g.scale(r,r);const cs=getComputedStyle(document.body);g.fillStyle=cs.getPropertyValue('--panel');g.fillRect(0,0,w,h);
 const e=ext(series);if(!e){g.fillStyle=cs.getPropertyValue('--dim');g.fillText('no data yet',10,20);return}
 let [x0,x1,y0,y1]=e;if(view){x0=view[0];x1=view[1]}const L=44,B=18,W=w-L-6,Hh=h-B-6;
 const X=x=>L+(x-x0)/(x1-x0||1)*W,Y=y=>6+(1-(y-y0)/(y1-y0||1))*Hh;g.strokeStyle=cs.getPropertyValue('--b');g.fillStyle=cs.getPropertyValue('--dim');g.font='11px sans-serif';
 for(let i=0;i<=4;i++){const yy=y0+(y1-y0)*i/4,py=Y(yy);g.beginPath();g.moveTo(L,py);g.lineTo(L+W,py);g.stroke();g.fillText(yy.toPrecision(3),2,py+4)}
 for(let i=0;i<=4;i++){const xx=x0+(x1-x0)*i/4;g.textAlign=i==0?'left':i==4?'right':'center';g.fillText(xx.toFixed(1),X(xx),h-4)}g.textAlign='left';
 g.save();g.beginPath();g.rect(L,0,W,h);g.clip();for(const s of series){g.strokeStyle=COL[s.role]||'#ccc';g.setLineDash(s.role==='bridge'?[3,3]:[]);g.lineWidth=1.6;g.beginPath();let st=false;
 for(let i=0;i<s.x.length;i++){const y=s.y[i];if(y===null||y!==y){st=false;continue}const px=X(s.x[i]),py=Y(y);st?g.lineTo(px,py):g.moveTo(px,py);st=true}g.stroke()}g.restore()}
function draw(){if(!S)return;const C=S.charts||{};chart(q('c1'),C.return||[]);chart(q('c2'),C.rate||[]);
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
  if(tap){const now=Date.now();if(now-lastTap<TAP_MS){view=null;draw();lastTap=0}else lastTap=now}else lastTap=0},{passive:true});
 cv.addEventListener('touchcancel',()=>{t0=null;mode=null;lastTap=0},{passive:true});
 cv.addEventListener('wheel',e=>{if(!S)return;e.preventDefault();const v=view||full(),r=cv.getBoundingClientRect(),c=v[0]+(e.clientX-r.left-44)/(r.width-50)*(v[1]-v[0]),f=e.deltaY<0?0.8:1.25;view=[c-(c-v[0])*f,c+(v[1]-c)*f];draw()});
 cv.addEventListener('dblclick',()=>{view=null;draw()})}
async function tick(){try{const r=await fetch('/api/status',{headers:H,cache:'no-store'});if(!r.ok){q('state').textContent='access denied ('+r.status+')';return}
 S=await r.json();q('title').textContent=S.title||'MimicKit';q('state').textContent=S.state||'';
 for(const k of ['session_time','total_time','samples','rate','estimate','per_step','vram'])q(k).textContent=S[k]||'-';
 const vp=S.vram_pct;const vb=q('vbar');vb.style.width=(vp||0)+'%';vb.style.background=vp>90?'#c0392b':vp>75?'#d0952c':'#3f9a54';
 q('age').textContent=new Date().toLocaleTimeString();draw();
 const p=S.preview;if(p&&p.key!==pvKey){pvKey=p.key;q('pv').innerHTML='<small>'+p.name+'</small><video controls playsinline preload="metadata" src="/preview.mp4?t='+encodeURIComponent(T)+'&k='+encodeURIComponent(p.key)+'"></video>'}
 if(S.render_msg)q('rmsg').textContent=S.render_msg}catch(e){q('state').textContent='offline - retrying'}}
q('render').onclick=async()=>{q('render').disabled=true;try{const r=await fetch('/api/render',{method:'POST',headers:H});const j=await r.json();q('rmsg').textContent=j.message}catch(e){q('rmsg').textContent='failed: '+e}
 setTimeout(()=>q('render').disabled=false,3000)};
tick();setInterval(tick,10000);window.addEventListener('resize',draw);
</script></body></html>"""

class Dashboard:
    def __init__(self, token, host="0.0.0.0", port=8765, on_render=None, log=None, min_interval=RENDER_MIN_INTERVAL):
        self.token, self.host, self.port = token, host, int(port)
        self.on_render = on_render; self.log = log or (lambda m: None); self.min_interval = min_interval
        self._snap = {}; self._lock = threading.Lock(); self._last_render = 0.0; self.httpd = None; self.thread = None
        self.requests = 0

    def set_snapshot(self, snap):
        with self._lock: self._snap = dict(snap)
    def snapshot(self):
        with self._lock: return dict(self._snap)

    def start(self):
        dash = self
        class H(BaseHTTPRequestHandler):
            server_version = "MimicKitDashboard"; protocol_version = "HTTP/1.1"
            def log_message(self, *a): pass
            def _authed(self):
                u = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(u.query)
                cands = qs.get("t", []) + [self.headers.get("X-Token", "")]
                m = re.search(r"(?:^|;\s*)mkt=([^;]+)", self.headers.get("Cookie", "") or "")
                if m: cands.append(m.group(1))
                return any(c and hmac.compare_digest(c.encode(), dash.token.encode()) for c in cands)
            def _send(self, code, body, ctype="application/json", extra=None):
                if isinstance(body, str): body = body.encode()
                self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for k, v in (extra or {}).items(): self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD": self.wfile.write(body)
            def do_HEAD(self): self.do_GET()
            def do_GET(self):
                dash.requests += 1
                if not self._authed(): return self._send(403, '{"error": "token required"}')
                path = urllib.parse.urlparse(self.path).path
                try:
                    if path == "/":
                        return self._send(200, PAGE, "text/html; charset=utf-8",
                                          {"Set-Cookie": "mkt=%s; HttpOnly; SameSite=Strict; Path=/" % dash.token})
                    if path == "/api/status": return self._send(200, json.dumps(dash.public_snapshot()))
                    if path == "/chart.png": return self._send(200, chart_png(dash.snapshot()), "image/png")
                    if path == "/preview.mp4": return self._file((dash.snapshot().get("preview") or {}).get("path"))
                    return self._send(404, '{"error": "not found"}')
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def do_POST(self):
                dash.requests += 1
                n = int(self.headers.get("Content-Length") or 0)
                if n: self.rfile.read(min(n, 65536))
                if not self._authed(): return self._send(403, '{"error": "token required"}')
                if urllib.parse.urlparse(self.path).path != "/api/render": return self._send(404, '{"error": "not found"}')
                code, msg = dash.request_render()
                return self._send(code, json.dumps({"message": msg}))
            def _file(self, p):
                if not p or not os.path.isfile(p): return self._send(404, '{"error": "no preview yet"}')
                size = os.path.getsize(p); rng = self.headers.get("Range"); start, end = 0, size - 1
                m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
                if rng and m:
                    if m.group(1): start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else size - 1
                    elif m.group(2): start = max(0, size - int(m.group(2)))
                    end = min(end, size - 1)
                    if start > end or start >= size:
                        return self._send(416, b"", "video/mp4", {"Content-Range": "bytes */%d" % size})
                self.send_response(206 if rng and m else 200)
                self.send_header("Content-Type", mimetypes.guess_type(p)[0] or "video/mp4"); self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1)); self.send_header("Cache-Control", "no-store")
                if rng and m: self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
                self.end_headers()
                if self.command == "HEAD": return
                with open(p, "rb") as f:
                    f.seek(start); left = end - start + 1
                    while left > 0:
                        chunk = f.read(min(256 * 1024, left))
                        if not chunk: break
                        self.wfile.write(chunk); left -= len(chunk)
        class S(ThreadingHTTPServer):
            daemon_threads = True; allow_reuse_address = True
        self.httpd = S((self.host, self.port), H); self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs=dict(poll_interval=0.5), daemon=True, name="mk-dashboard")
        self.thread.start(); self.log("phone dashboard on http://%s:%d/ (token required)" % (self.host, self.port))
        return self

    def stop(self):
        if self.httpd:
            h = self.httpd; self.httpd = None
            threading.Thread(target=lambda: (h.shutdown(), h.server_close()), daemon=True).start()

    def public_snapshot(self):
        s = self.snapshot(); p = s.get("preview")
        if p: s["preview"] = {k: p[k] for k in ("name", "key") if k in p}       # never the local path
        return s

    def request_render(self):
        now = time.time(); wait = self.min_interval - (now - self._last_render)
        if wait > 0: return 429, "Please wait %d s - previews are limited to one per %d min." % (wait, self.min_interval // 60 or 1)
        if not self.on_render: return 503, "Rendering is not available."
        self._last_render = now
        try: ok, msg = self.on_render()
        except Exception as e: ok, msg = False, "failed: %s" % e
        if not ok: self._last_render = 0.0
        return (202 if ok else 409), msg

# ---------------------------------------------------------------- notifications
def _multipart(fields, files):
    b = "----mk%s" % uuid.uuid4().hex; out = io.BytesIO()
    for k, v in fields.items():
        out.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode())
    for k, (name, data, ctype) in files.items():
        out.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n" % (b, k, name, ctype)).encode())
        out.write(data); out.write(b"\r\n")
    out.write(("--%s--\r\n" % b).encode())
    return out.getvalue(), "multipart/form-data; boundary=%s" % b

def http_post(url, data, ctype, timeout=60):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype, "User-Agent": "MimicKitLauncher"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(2000)

def redact(text, cfg):
    for k in ("discord_webhook", "telegram_token"):
        v = (cfg or {}).get(k)
        if v: text = text.replace(v, "<%s>" % k)
    return text

class Notifier:
    """cfg keys: discord_webhook, telegram_token, telegram_chat, every_hours, send_preview."""
    def __init__(self, cfg_get, log=None, post=None):
        self.cfg_get = cfg_get; self.log = log or (lambda m: None); self.post = post or http_post; self.last = time.time()

    def targets(self):
        c = self.cfg_get() or {}; t = []
        if (c.get("discord_webhook") or "").startswith("https://"): t.append("discord")
        if c.get("telegram_token") and c.get("telegram_chat"): t.append("telegram")
        return t

    def due(self, now=None):
        c = self.cfg_get() or {}; h = float(c.get("every_hours") or 0)
        return bool(self.targets()) and h > 0 and (now or time.time()) - self.last >= h * 3600

    def _send_one(self, target, text, png=None, video=None):
        c = self.cfg_get() or {}
        if target == "discord":
            files = {}
            if png: files["files[0]"] = ("chart.png", png, "image/png")
            if video: files["files[1]" if png else "files[0]"] = (os.path.basename(video[0]), video[1], "video/mp4")
            data, ct = _multipart({"payload_json": json.dumps({"content": text[:1990], "allowed_mentions": {"parse": []}})}, files)
            return self.post(c["discord_webhook"], data, ct)
        base = "https://api.telegram.org/bot%s/" % c["telegram_token"]
        if video:
            data, ct = _multipart({"chat_id": c["telegram_chat"], "caption": text[:1020], "supports_streaming": "true"},
                                  {"video": (os.path.basename(video[0]), video[1], "video/mp4")})
            return self.post(base + "sendVideo", data, ct)
        if png:
            data, ct = _multipart({"chat_id": c["telegram_chat"], "caption": text[:1020]}, {"photo": ("chart.png", png, "image/png")})
            return self.post(base + "sendPhoto", data, ct)
        data, ct = _multipart({"chat_id": c["telegram_chat"], "text": text[:4000]}, {})
        return self.post(base + "sendMessage", data, ct)

    def send(self, text, png=None, video_path=None, kind="status"):
        """Send to every configured target; never raises. Returns {target: 'ok' | error text}."""
        res = {}; c = self.cfg_get() or {}
        for t in self.targets():
            try:
                video = None; note = ""
                if video_path:
                    mb = os.path.getsize(video_path) / 1e6; lim = DISCORD_MAX_MB if t == "discord" else TELEGRAM_MAX_MB
                    if mb > lim: note = "\n(preview %s is %.1f MB - over the %s limit of %.0f MB, not attached)" % (os.path.basename(video_path), mb, t, lim)
                    else: video = (video_path, open(video_path, "rb").read())
                code, body = self._send_one(t, text + note, png, video)
                res[t] = "ok" if 200 <= int(code) < 300 else "HTTP %s %s" % (code, body[:200])
            except Exception as e:
                res[t] = redact("%s: %s" % (type(e).__name__, e), c)
            self.log("[notify] %s %s: %s" % (kind, t, res[t]))
        if kind == "status": self.last = time.time()
        return res

    def send_status(self, snap, kind="status"):
        try: png = chart_png(snap)
        except Exception as e: png = None; self.log("[notify] chart failed: %s" % e)
        return self.send(status_text(snap), png=png, kind=kind)
