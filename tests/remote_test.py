"""Phone dashboard (token, JSON, chart PNG, HTTP range requests for the preview MP4, render rate limit), notification
formatting with mocked HTTP, and GUI responsiveness while the server is hammered.   xvfb-run -a python tests/remote_test.py
"""

import http.client, json, os, socket, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import mimickit_remote as R

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


def req(port, path, method="GET", headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, dict(r.getheaders()), body


tmp = tempfile.mkdtemp()
mp4 = os.path.join(tmp, "preview_100.mp4")
data = os.urandom(300000)
open(mp4, "wb").write(data)
snap = dict(
    title="t",
    state="RUNNING (train)",
    rate="7.5 M samples/hour",
    vram="5.3 / 8.0 GB",
    vram_pct=66,
    charts={
        "return": [dict(role="cur1", label="Train return", x=[0, 1, 2], y=[1, 2, None])],
        "rate": [dict(role="cur3", x=[0, 1], y=[7, 7.5])],
    },
    preview=dict(path=mp4, name="preview_100.mp4", key="k1"),
)
calls = []


def on_render():
    calls.append(time.time())
    return True, "started"


tok = R.new_token()
d = R.Dashboard(tok, "127.0.0.1", 0, on_render=on_render, min_interval=300).start()
d.set_snapshot(snap)
P = d.port
check("token is long and random", len(tok) >= 20 and tok != R.new_token())
check(
    "no token -> 403 everywhere",
    all(req(P, p)[0] == 403 for p in ("/", "/api/status", "/chart.png", "/preview.mp4")),
)
check(
    "wrong token -> 403",
    req(P, "/api/status?t=" + tok[:-1] + "x")[0] == 403
    and req(P, "/", headers={"X-Token": "nope"})[0] == 403,
)
st, h, body = req(P, "/?t=" + tok)
check(
    "page with token: 200 html, mobile viewport, dark default",
    st == 200 and b"width=device-width" in body and b"--bg:#121212" in body,
)
check(
    "token cookie set (HttpOnly, SameSite=Strict)",
    "mkt=" + tok in h.get("Set-Cookie", "")
    and "HttpOnly" in h["Set-Cookie"]
    and "Strict" in h["Set-Cookie"],
)
check("cookie alone authorises", req(P, "/api/status", headers={"Cookie": "mkt=" + tok})[0] == 200)
st, h, body = req(P, "/api/status", headers={"X-Token": tok})
j = json.loads(body)
check(
    "JSON endpoint: status, charts, vram",
    st == 200
    and j["rate"] == snap["rate"]
    and j["vram_pct"] == 66
    and j["charts"]["return"][0]["y"][2] is None,
)
check(
    "JSON never exposes the local file path",
    "path" not in j["preview"] and tmp not in body.decode(),
)
st, h, body = req(P, "/chart.png?t=" + tok)
check(
    "chart PNG rendered server-side",
    st == 200 and body[:8] == b"\x89PNG\r\n\x1a\n" and h["Content-Type"] == "image/png",
)
st, h, body = req(P, "/preview.mp4?t=" + tok)
check(
    "video without Range: 200, full file, Accept-Ranges",
    st == 200 and body == data and h.get("Accept-Ranges") == "bytes",
)
st, h, body = req(P, "/preview.mp4?t=" + tok, headers={"Range": "bytes=100-199"})
check(
    "Range bytes=100-199 -> 206 with exact bytes",
    st == 206 and body == data[100:200] and h["Content-Range"] == "bytes 100-199/%d" % len(data),
)
st, h, body = req(P, "/preview.mp4?t=" + tok, headers={"Range": "bytes=299000-"})
check(
    "open-ended range",
    st == 206 and body == data[299000:] and h["Content-Length"] == str(len(data) - 299000),
)
st, h, body = req(P, "/preview.mp4?t=" + tok, headers={"Range": "bytes=-500"})
check("suffix range (last 500 bytes)", st == 206 and body == data[-500:])
st, h, body = req(P, "/preview.mp4?t=" + tok, headers={"Range": "bytes=999999-"})
check("unsatisfiable range -> 416", st == 416 and h["Content-Range"] == "bytes */%d" % len(data))
st, h, body = req(P, "/preview.mp4?t=" + tok, method="HEAD")
check("HEAD: headers only", st == 200 and body == b"" and h["Content-Length"] == str(len(data)))
st, _, b1 = req(P, "/api/render", "POST", {"X-Token": tok})
st2, _, b2 = req(P, "/api/render", "POST", {"X-Token": tok})
check(
    "render: first accepted, second rate-limited (429)",
    st == 202 and st2 == 429 and len(calls) == 1,
    "%s %s %s" % (st, st2, b2),
)
check("render without token refused", req(P, "/api/render", "POST")[0] == 403 and len(calls) == 1)
check(
    "no start/stop endpoints",
    all(
        req(P, p + "?t=" + tok, "POST")[0] == 404 for p in ("/api/start", "/api/stop", "/api/train")
    ),
)
d2 = R.Dashboard(tok, "127.0.0.1", 0, on_render=lambda: (False, "busy")).start()
check(
    "a refused render does not use up the rate limit",
    req(d2.port, "/api/render", "POST", {"X-Token": tok})[0] == 409
    and req(d2.port, "/api/render", "POST", {"X-Token": tok})[0] == 409,
)
d.stop()
d2.stop()
# ---- notifications (mocked HTTP)
posts = []


def post(url, body, ct):
    posts.append((url, body, ct))
    return 204, b""


logs = []
cfg = {
    "discord_webhook": "https://discord.com/api/webhooks/1/SECRET",
    "telegram_token": "123:TOKEN",
    "telegram_chat": "42",
    "every_hours": 3,
}
n = R.Notifier(lambda: cfg, log=logs.append, post=post)
check("targets from settings", n.targets() == ["discord", "telegram"])
res = n.send_status(snap)
check(
    "status sent to both", res == {"discord": "ok", "telegram": "ok"} and len(posts) == 2, str(res)
)
u, body, ct = posts[0]
check(
    "discord: webhook URL, multipart with payload_json + chart.png",
    u == cfg["discord_webhook"]
    and ct.startswith("multipart/form-data")
    and b'name="payload_json"' in body
    and b'filename="chart.png"' in body
    and b"\x89PNG" in body
    and b"7.5 M samples/hour" in body,
)
check("discord: mentions disabled", b'"allowed_mentions": {"parse": []}' in body)
u, body, ct = posts[1]
check(
    "telegram: sendPhoto with chat id + caption",
    u == "https://api.telegram.org/bot123:TOKEN/sendPhoto"
    and b'name="chat_id"\r\n\r\n42' in body
    and b'name="caption"' in body
    and b"\x89PNG" in body,
)
posts.clear()
R.DISCORD_MAX_MB = 0.1
res = n.send("New preview", video_path=mp4, kind="preview")
check(
    "video over the Discord limit: skipped with a note",
    b"over the discord limit" in posts[0][1] and b"video/mp4" not in posts[0][1],
)
check(
    "telegram (50 MB limit) gets the video via sendVideo",
    posts[1][0].endswith("/sendVideo") and data[:1000] in posts[1][1],
)


def bad(url, body, ct):
    raise OSError("connection to %s failed" % url)


n2 = R.Notifier(lambda: cfg, log=logs.append, post=bad)
res = n2.send_status(snap)
check("failures are reported, never raised", all(v.startswith("OSError") for v in res.values()))
check(
    "secrets redacted from logged errors",
    not any("SECRET" in l or "123:TOKEN" in l for l in logs)
    and any("<discord_webhook>" in l for l in logs),
)
n3 = R.Notifier(lambda: dict(cfg, every_hours=3), post=post)
n3.last = time.time() - 3 * 3600 - 1
check(
    "due every N hours; 0 = off; nothing configured = off",
    n3.due()
    and not R.Notifier(lambda: dict(cfg, every_hours=0)).due()
    and not R.Notifier(lambda: {"every_hours": 3}).due(),
)
check(
    "status text",
    "Speed: 7.5 M samples/hour" in R.status_text(snap)
    and "VRAM: 5.3 / 8.0 GB" in R.status_text(snap),
)
# ---- GUI stays responsive while the dashboard is hammered; web render goes through the GUI queue
import tkinter as tk, mimickit_launcher as G

for nm in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, nm, lambda *a, **k: None)
s = socket.socket()
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()
root = tk.Tk()
app = G.App(root)
app.v_mk.set(os.path.join(HERE, "fake_mimickit"))
app.s["remote"] = dict(enabled=True, host="127.0.0.1", port=port)
app._remote_apply()
t0 = time.time()
while time.time() - t0 < 2:
    root.update()
    time.sleep(0.02)
check("dashboard started from settings", app.dash is not None and app.dash.port == port)
tok2 = app.s["remote"]["token"]
stop = [False]
nreq = [0]


def hammer():
    while not stop[0]:
        for p in ("/api/status", "/chart.png", "/"):
            try:
                req(port, p + "?t=" + tok2)
                nreq[0] += 1
            except Exception:
                pass


ths = [threading.Thread(target=hammer, daemon=True) for _ in range(6)]
for t in ths:
    t.start()
gaps = []
last = time.time()
t0 = last
while time.time() - t0 < 4:
    root.update()
    now = time.time()
    gaps.append(now - last)
    last = now
    time.sleep(0.01)
stop[0] = True
check(
    "GUI responsive under load (max main-loop gap < 0.3 s)",
    max(gaps) < 0.3 and nreq[0] > 50,
    "max gap %.3f s, %d requests" % (max(gaps), nreq[0]),
)
st, _, b = req(port, "/api/render", "POST", {"X-Token": tok2})
for _ in range(30):
    root.update()
    time.sleep(0.03)
check(
    "web render handed to the GUI thread",
    st == 202 and app.rq.empty() and app.render_msg,
    app.render_msg,
)
st, _, b = req(port, "/api/status?t=" + tok2)
j = json.loads(b)
check("snapshot published from the GUI", st == 200 and "MimicKit Launcher" in j.get("title", ""))
app.remote_dialog()
root.update()
v = app._rdlg_vars
check(
    "settings dialog: port, bind address, token URL",
    v["port"].get() == str(port) and v["host"].get() == G.BIND_LABEL["127.0.0.1"] == "This PC only",
)
v["enabled"].set(False)
v["apply"]()
root.update()
check("disabling stops the server", app.dash is None)
root.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
