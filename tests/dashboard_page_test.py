"""Phone dashboard served headless: page markers for the a0.8.0 preview controls (closed 'Preview options', no
autoplay), previews listed without local paths, /preview.mp4 by key + download header, overlay card injection.
  python tests/dashboard_page_test.py"""

import result_exit  # noqa: F401
import json, os, sys, tempfile, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import mimickit_remote as R

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


d = tempfile.mkdtemp()
a, b = os.path.join(d, "a.mp4"), os.path.join(d, "b.mp4")
open(a, "wb").write(b"A" * 1000)
open(b, "wb").write(b"B" * 2000)
dash = R.Dashboard("tok123", host="127.0.0.1", port=0, page_extra=lambda: ('<div id="xcard">X</div>', "var XJS=1;"))
dash.set_snapshot(dict(state="training", preview=dict(name="b.mp4", key="kb", path=b),
                       previews=[dict(name="b.mp4", key="kb", path=b), dict(name="a.mp4", key="ka", path=a)],
                       render=dict(active=True, pct=40, stage="Rendering")))
dash.start()
port = dash.httpd.server_address[1]
base = "http://127.0.0.1:%d" % port


def get(path, tok=True):
    req = urllib.request.Request(base + path, headers={"X-Token": "tok123"} if tok else {})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


c, h, page = get("/", tok=False)
check("no token -> refused", c == 403)
c, h, page = get("/")
page = page.decode()
check("page served", c == 200)
for m in ("pv_play", "pv_seek", "pv_sel", 'data-r="0.25"', 'data-r="0.5"', 'data-r="1"', "pv_loop", "pv_dl", "rprog"):
    check("preview control " + m, m in page)
check("'Preview options' collapsed by default", "<details" in page and "Preview options" in page
      and "<details open" not in page.split("Preview options")[0][-200:])
check("no autoplay on the video", "autoplay=" not in page.lower() and ".autoplay" not in page.lower() and " autoplay>" not in page.lower())
check("overlay card + script injected", '<div id="xcard">' in page and "var XJS=1;" in page
      and "<!--EXTRA_HTML-->" not in page and "/*EXTRA_JS*/" not in page)
c, h, js = get("/api/status")
s = json.loads(js)
check("previews listed", [p["key"] for p in s["previews"]] == ["kb", "ka"])
check("no local paths sent to the phone", d not in js.decode())
c, h, body = get("/preview.mp4?k=ka")
check("preview by key", c == 200 and body == b"A" * 1000, c)
c, h, body = get("/preview.mp4?k=zzz")
check("unknown key -> newest", c == 200 and body == b"B" * 2000)
c, h, body = get("/preview.mp4?k=ka&dl=1")
check("download sets attachment header", "attachment" in (h.get("Content-Disposition") or ""), h.get("Content-Disposition"))
c, h, body = get("/preview.mp4?k=ka&t=x")
check("range-less fetch ok", c == 200)
dash.stop()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
