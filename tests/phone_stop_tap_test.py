"""a0.8.3: phone Stop buttons work with a TAP + confirm (long-press hold failed on Android), the confirm auto-cancels,
every button blocks text selection / context menu.   python tests/phone_stop_tap_test.py (needs chromium)"""

import result_exit  # noqa: F401
import json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mimickit_remote as R

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


check("buttons: no text select / callout, touch-action manipulation",
      "-webkit-touch-callout:none" in R.PAGE and "user-select:none" in R.PAGE and "touch-action:manipulation" in R.PAGE)
check("no hold-to-confirm left on the page", "pointerdown" not in R.PAGE and "holdStep" not in R.PAGE)
check("stop buttons in their own row", 'class="stoprow"' in R.PAGE)
chrome = next((shutil.which(c) for c in ("chromium", "chromium-browser", "google-chrome", "chrome") if shutil.which(c)), None)
if not chrome:
    print("RESULT: %d/%d" % (sum(ok), len(ok)))
    sys.exit(0)
snap = {"state": "Training", "running": True, "control": True, "charts": {}}
mock = ("<script>Object.defineProperty(document,'title',{configurable:true,get(){return (document.querySelector('title')||{}).textContent||''},set(v){if(/^(RESULT|ERR)/.test(v)||!/^(RESULT|ERR)/.test(this.title)){const t=document.querySelector('title');if(t)t.textContent=v}}});"
        "window.onerror=(m,s,l)=>{document.title='ERR '+m+' @'+l};localStorage.mkSes='S1';window.CALLS=[];"
        "window.fetch=async(u,o)=>{CALLS.push(u+' '+((o&&o.body)||''));const b=u.includes('/control/nonce')?{nonce:'N'+CALLS.length}:u.includes('/control/')?{message:'ok'}:(%s);"
        "return {ok:true,status:200,json:async()=>b}};</script>" % json.dumps(snap))
test = r"""<script>
async function run(){const W=ms=>new Promise(r=>setTimeout(r,ms)),out={};await W(800);
 q('a_stopnow').click();await W(100);out.modalOpen=q('modal').classList.contains('on');out.label=q('m_holdt').textContent;
 q('m_hold').click();await W(100);out.tooEarlyIgnored=q('modal').classList.contains('on');
 await W(500);q('m_hold').click();await W(600);out.closed=!q('modal').classList.contains('on');
 out.stopSent=CALLS.some(c=>c.includes('/control/stop_now'));
 q('a_stopsave').click();await W(6500);out.autoCancel=!q('modal').classList.contains('on');
 out.noSaveSent=!CALLS.some(c=>c.includes('/control/stop_after_save'));
 q('a_stopsave').click();await W(600);q('m_hold').click();await W(600);out.saveSent=CALLS.some(c=>c.includes('/control/stop_after_save'));
 document.title='RESULT'+JSON.stringify(out)}
setTimeout(run,300);</script>"""
html = R.PAGE.replace("<title>", mock + "<title>", 1).replace("</body>", test + "</body>")
d = tempfile.mkdtemp()
f = os.path.join(d, "p.html")
open(f, "w").write(html)
r = subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--user-data-dir=" + os.path.join(d, "u"),
                    "--window-size=390,844", "--virtual-time-budget=30000", "--dump-dom", "file://" + f],
                   capture_output=True, text=True, timeout=120)
m = re.search(r"<title>RESULT(\{.*?\})</title>", r.stdout)
check("page ran", bool(m), (re.search(r"<title>(.*?)</title>", r.stdout) or [0, r.stdout[:200]])[1] if not m else "")
o = json.loads(m.group(1)) if m else {}
check("tap Stop now opens a confirm with 'Yes, stop now (5 s)'", o.get("modalOpen") and "Yes, stop now (5 s)" in o.get("label", ""), o)
check("an instant second tap (ghost tap) is ignored", o.get("tooEarlyIgnored"))
check("tap Yes sends stop_now (PIN session + nonce path)", o.get("closed") and o.get("stopSent"), o)
check("confirm auto-cancels after ~5 s, nothing sent", o.get("autoCancel") and o.get("noSaveSent"), o)
check("Stop after next save: tap + Yes sends it", o.get("saveSent"), o)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
