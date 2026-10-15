"""Phone dashboard chart touch handling in headless Chrome (synthetic TouchEvents): a pinch zooms deep without
snapping back, a vertical swipe leaves the chart alone (the page scrolls: touch-action pan-y), a horizontal drag pans,
a double-tap resets.   python tests/dashboard_touch_test.py   (skips without google-chrome / chromium)
"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mimickit_remote as R

chrome = next(
    (shutil.which(c) for c in ("google-chrome", "chromium", "chromium-browser") if shutil.which(c)),
    None,
)
if not chrome:
    print("SKIP: no headless Chrome/Chromium")
    print("RESULT: 0/0")
    sys.exit(0)
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


check(
    "chart canvas uses touch-action: pan-y",
    "touch-action:pan-y" in R.PAGE and "touch-action:none" not in R.PAGE,
)
snap = {
    "charts": {
        "return": [
            {
                "role": "cur1",
                "x": [i * 0.1 for i in range(500)],
                "y": [1 + i * 0.01 for i in range(500)],
            }
        ],
        "rate": [{"role": "cur3", "x": [0, 50], "y": [7, 7.5]}],
    },
    "state": "x",
}
mock = (
    "<script>window.onerror=(m,s,l)=>{document.title='ERR '+m+' @'+l};window.fetch=async()=>({ok:true,json:async()=>(%s)});</script>"
    % json.dumps(snap)
)
test = r"""<script>
function TT(cv,pts){return pts.map((p,i)=>new Touch({identifier:i,target:cv,clientX:cv.getBoundingClientRect().left+p[0],clientY:cv.getBoundingClientRect().top+p[1]}))}
function ev(cv,type,pts,all){const t=TT(cv,pts);cv.dispatchEvent(new TouchEvent(type,{touches:all===undefined?t:TT(cv,all),changedTouches:t,cancelable:true,bubbles:true}))}
async function run(){await new Promise(r=>setTimeout(r,300));const cv=document.getElementById('c1'),out={};
 const span=()=>view?view[1]-view[0]:null;
 // pinch: finger 1 down, finger 2 lands 50 ms later (used to count as a double-tap -> snap back), spread apart repeatedly
 for(let k=0;k<6;k++){ev(cv,'touchstart',[[150,90]]);await new Promise(r=>setTimeout(r,50));
  ev(cv,'touchstart',[[150,90],[170,90]]);ev(cv,'touchmove',[[100,90],[260,90]]);ev(cv,'touchend',[[260,90]],[[100,90]]);ev(cv,'touchend',[[100,90]],[]);
  await new Promise(r=>setTimeout(r,40))}
 out.pinchSpan=span();out.full=full()[1]-full()[0];
 // deep zoom must survive a data refresh
 await tick();out.afterTick=span();
 // vertical swipe: chart view unchanged
 const v0=view.slice();ev(cv,'touchstart',[[150,60]]);ev(cv,'touchmove',[[152,100]]);ev(cv,'touchmove',[[153,160]]);ev(cv,'touchend',[[153,160]],[]);
 out.vertUnchanged=view[0]===v0[0]&&view[1]===v0[1];
 // horizontal drag pans (same span, shifted)
 ev(cv,'touchstart',[[200,90]]);ev(cv,'touchmove',[[150,92]]);ev(cv,'touchmove',[[100,93]]);ev(cv,'touchend',[[100,93]],[]);
 out.panShift=view[0]-v0[0];out.panSpanSame=Math.abs((view[1]-view[0])-(v0[1]-v0[0]))<1e-9;
 // single tap does nothing; double tap resets
 await new Promise(r=>setTimeout(r,400));ev(cv,'touchstart',[[150,90]]);ev(cv,'touchend',[[150,90]],[]);out.oneTapKeeps=view!==null;
 await new Promise(r=>setTimeout(r,80));ev(cv,'touchstart',[[150,90]]);ev(cv,'touchend',[[150,90]],[]);out.doubleTapResets=view===null;
 document.title='RESULT'+JSON.stringify(out)}
setTimeout(run,500);</script>"""
html = R.PAGE.replace("<title>", mock + "<title>", 1).replace("</body>", test + "</body>")
d = tempfile.mkdtemp()
f = os.path.join(d, "p.html")
open(f, "w").write(html)
r = subprocess.run(
    [
        chrome,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--user-data-dir=" + os.path.join(d, "u"),
        "--window-size=390,844",
        "--touch-events=enabled",
        "--virtual-time-budget=15000",
        "--dump-dom",
        "file://" + f,
    ],
    capture_output=True,
    text=True,
    timeout=120,
)
m = re.search(r"<title>RESULT(\{.*?\})</title>", r.stdout)
check(
    "page ran the touch script",
    bool(m),
    (re.search(r"<title>(.*?)</title>", r.stdout) or [0, r.stdout[:200]])[1] if not m else "",
)
o = json.loads(m.group(1)) if m else {}
check(
    "pinch with a late second finger zooms in (no double-tap snap-back)",
    o.get("pinchSpan") is not None and o["pinchSpan"] < o["full"] / 50,
    "span %s of %s" % (o.get("pinchSpan"), o.get("full")),
)
check("deep zoom kept through the auto-refresh", o.get("afterTick") == o.get("pinchSpan"))
check("vertical swipe starting on the chart doesn't pan/zoom it", o.get("vertUnchanged") is True)
check(
    "horizontal drag pans (span unchanged)",
    o.get("panShift", 0) > 0 and o.get("panSpanSame") is True,
    str(o.get("panShift")),
)
check(
    "single tap keeps the view; double-tap resets",
    o.get("oneTapKeeps") is True and o.get("doubleTapResets") is True,
)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
