"""a0.4.2 fixes: atomic JSON save/load (+ .bak), damaged-settings popup (Restore / Start fresh), every swallowed
`except Exception` is logged (secrets masked), dashboard bind choice (new installs: this PC only; existing all-
interfaces setups kept), Show buttons on masked fields, secrets kept out of logs / dashboard / notifications.
  xvfb-run -a python tests/fixes042_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from fake_mk import fake_mk  # noqa: E402 - temp copy: test output never lands in the repo
import ast, datetime, glob, json, os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp()
CFG = os.path.join(TMP, "settings.json")
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = CFG
import mimickit_util as U

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


# ---------- atomic JSON
p = os.path.join(TMP, "a.json")
U.save_json(p, {"v": 1})
U.save_json(p, {"v": 2})
check("save + load round trip", U.load_json(p) == {"v": 2})
check("previous good file kept as .bak", U.load_json(p + ".bak") == {"v": 1})


class Boom:
    pass


try:
    U.save_json(p, {"v": Boom()})  # not serialisable: fails half-way through writing
except TypeError:
    pass
check("failed write leaves the file untouched", U.load_json(p) == {"v": 2})
check(
    "failed write leaves no temp file",
    not [f for f in os.listdir(TMP) if ".tmp" in f],
    str(os.listdir(TMP)),
)
open(p, "w").write('{"v": 3')
try:
    U.load_json(p)
    damaged = False
except U.JsonDamaged:
    damaged = True
check("damaged file raises JsonDamaged (not a silent default)", damaged)
check("load_json_or gives the default for a damaged file", U.load_json_or(p, {"d": 1}) == {"d": 1})
open(p, "w").write("{}")
U.save_json(p, {"v": 4})
open(p, "w").write("garbage")
U.save_json(p, {"v": 5})
check("a damaged file never becomes the backup", U.load_json(p + ".bak") == {})
srcs = {
    os.path.relpath(f, ROOT): open(f).read()
    for f in glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "mkl", "*.py"))
}
left = [
    f
    for f, s in srcs.items()
    if "json.load(open(" in s or "json.dump(" in s.replace("json.dump(obj, f", "")
]
check("no json.load(open())/json.dump left outside the helper", not left, str(left))


# ---------- every swallowed `except Exception` is logged
def silent(f):
    out = []
    for h in ast.walk(ast.parse(srcs[f])):
        if (
            isinstance(h, ast.ExceptHandler)
            and h.type is not None
            and ast.unparse(h.type) == "Exception"
        ):
            if all(isinstance(b, ast.Pass) for b in h.body):
                out.append(h.lineno)
    return out


bad = {f: silent(f) for f in srcs if silent(f) and f != "mimickit_util.py"}
check(
    "no silent `except Exception: pass` left (except the logger's own last resort)",
    not bad,
    str(bad),
)
check("the logger's own last resort is the only one", len(silent("mimickit_util.py")) == 1)
logf = os.path.join(TMP, "err.log")
U.set_log_path(logf)
U.add_secret("SEKRET-TOKEN-123456")
try:
    raise RuntimeError(
        "failed posting to https://discord.com/api/webhooks/1/abcdef with SEKRET-TOKEN-123456"
    )
except RuntimeError as e:
    U.log_exc("test site", e)
log = open(logf).read()
check(
    "log_exc writes where + type + message",
    "ignored in test site: RuntimeError" in log,
    log.strip(),
)
check("secrets masked in the error log", "SEKRET" not in log and "abcdef" not in log)
for i in range(30):
    U.log_exc("noisy", ValueError("x"))
check("repeats of one site are capped", open(logf).read().count("ignored in noisy") == 20)

# ---------- settings: damaged file -> popup with Restore / Start fresh
import tkinter as tk, mimickit_launcher as G

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
fmk = fake_mk()
G.filedialog.askdirectory = lambda **k: fmk
U.save_json(CFG, {"mimickit": fmk, "light_mode": False, "venv": "", "marker": "good"})
U.save_json(CFG, {"mimickit": fmk, "light_mode": False, "venv": "", "marker": "newer"})
bak_time = datetime.datetime.fromtimestamp(os.path.getmtime(CFG + ".bak")).strftime(
    "%Y-%m-%d %H:%M"
)
open(CFG, "w").write('{"mimickit": "x", ')  # damaged
asked = []


def hook(answer):
    def h(self, title, text, opts):
        asked.append((title, text, [o[0] for o in opts]))
        return answer

    return h


G.App._choose_hook = hook("restore")
root = tk.Tk()
app = G.App(root)
root.update()
check(
    "damaged settings: popup text + date",
    asked
    and asked[-1][1] == "Your settings file was damaged. Restore the backup from %s?" % bak_time,
    asked and asked[-1][1],
)
check("buttons Restore / Start fresh", asked and asked[-1][2] == ["Restore", "Start fresh"])
check(
    "Restore uses the backup",
    app.s.get("marker") == "good" and U.load_json(CFG).get("marker") == "good",
)
check("damaged file kept aside", glob.glob(CFG + ".damaged-*"))
root.destroy()
open(CFG, "w").write("nonsense")
G.App._choose_hook = hook("fresh")
root = tk.Tk()
app = G.App(root)
root.update()
check("Start fresh: default settings", "marker" not in app.s and app.s.get("mimickit") in ("", fmk))
root.destroy()
for f in glob.glob(CFG + "*"):
    os.remove(f)
open(CFG, "w").write("nonsense")
asked.clear()
root = tk.Tk()
app = G.App(root)
root.update()
check(
    "no backup: only Start fresh offered",
    asked and asked[-1][2] == ["Start fresh"],
    str(asked[-1:]),
)
root.destroy()
del G.App._choose_hook

# ---------- dashboard bind: new installs local only, existing all-interfaces kept
check("new install: no host -> this PC only", G.migrate_settings({}).get("remote") is None)
check(
    "older settings with the dashboard set up keep 0.0.0.0",
    G.migrate_settings({"remote": {"enabled": True, "port": 8765}})["remote"]["host"] == "0.0.0.0",
)
check(
    "explicit choices are kept",
    G.migrate_settings({"remote": {"enabled": True, "host": "127.0.0.1"}})["remote"]["host"]
    == "127.0.0.1"
    and G.migrate_settings({"remote": {"enabled": True, "host": "0.0.0.0"}})["remote"]["host"]
    == "0.0.0.0",
)
for f in glob.glob(CFG + "*"):
    os.remove(f)
U.save_json(CFG, {"mimickit": fmk})
root = tk.Tk()
app = G.App(root)
root.update()
app.remote_dialog()
root.update()
v = app._rdlg_vars
check("dialog offers the two plain choices", v["host"].get() == "Only this PC (phone can't connect)")
v["enabled"].set(True)
v["port"].set("8799")
v["apply"]()
root.update()
check(
    "new install binds 127.0.0.1",
    app.dash is not None and app.dash.host == "127.0.0.1",
    app.dash and app.dash.host,
)
v["host"].set(G.BIND_LABEL["0.0.0.0"])
v["apply"]()
root.update()
check(
    "the phone choice binds all interfaces",
    app.dash.host == "0.0.0.0" and app.s["remote"]["host"] == "0.0.0.0",
)

# ---------- Show buttons + secrets out of exports
ent, btn = app._secret_entries["discord_webhook"]
check(
    "webhook field masked with a Show button",
    ent.cget("show") == "*" and btn.cget("text") == "Show",
)
btn.invoke()
check("Show reveals, button says Hide", ent.cget("show") == "" and btn.cget("text") == "Hide")
btn.invoke()
check("Hide masks again", ent.cget("show") == "*")
check("telegram token field has one too", "telegram_token" in app._secret_entries)
hook_url = "https://discord.com/api/webhooks/123456/SECRETPART-abcdefghijklmnop"
tg = "123456789:AAH-secret-telegram-token-abcdefghijk"
app.s.setdefault("notify", {}).update(discord_webhook=hook_url, telegram_token=tg)
app._save_settings_only()
try:
    raise OSError("POST %s failed; bot %s" % (hook_url, tg))
except OSError as e:
    U.log_exc("notify", e)
log = open(logf).read()
check("secrets never reach the error log", "SECRETPART" not in log and "secret-telegram" not in log)
app._progress_tick(force=True)
root.update()
import urllib.request

tok = app.s["remote"]["token"]
time.sleep(0.3)
body = (
    urllib.request.urlopen("http://127.0.0.1:8799/api/status?t=" + tok, timeout=5).read().decode()
)
page = urllib.request.urlopen("http://127.0.0.1:8799/?t=" + tok, timeout=5).read().decode()
check(
    "dashboard JSON/page carry no webhook or bot token",
    all(s not in body + page for s in ("SECRETPART", "secret-telegram")),
)
import mimickit_remote as R

check(
    "notification text redacted",
    "SECRETPART" not in R.redact("error at " + hook_url, app.s["notify"]),
)
# ---------- unknown saved host (QA a0.6.0)
if getattr(app, "_rdlg", None) and app._rdlg.winfo_exists():
    app._rdlg.destroy()
app.s.setdefault("remote", {})["host"] = "192.168.1.50"  # not offered by this version (hand-edited / older build)
app.remote_dialog()
root.update()
check("unknown saved host falls back to 'This PC only'", app._rdlg_vars["host"].get() == "Only this PC (phone can't connect)")
app.dash.stop()
app.dash = None
root.destroy()

print("RESULT: %d/%d" % (sum(ok), len(ok)))
