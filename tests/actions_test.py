"""Profile ACTIONS buttons + install_files (backup originals, copy patch files).  xvfb-run -a python tests/actions_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import tkinter as tk, mimickit_launcher as G
from mkl import core
from mkl.actions import install_files
import expect  # per-build expected defaults

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


def w(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(t)


t = tempfile.mkdtemp()
src, mk, bk = (os.path.join(t, x) for x in ("src", "mk", "mk/backup"))
w(os.path.join(src, "data", "a.txt"), "new a")
w(os.path.join(src, "code", "b.py"), "new b")
w(os.path.join(mk, "data", "a.txt"), "old a")
c, b = install_files(src, mk, bk)
check("all files copied", sorted(c) == [os.path.join("code", "b.py"), os.path.join("data", "a.txt")], str(c))
check("only existing files backed up", b == [os.path.join("data", "a.txt")], str(b))
check("backup holds the original", open(os.path.join(bk, "data", "a.txt")).read() == "old a")
check("patched file in place", open(os.path.join(mk, "data", "a.txt")).read() == "new a")
c, b = install_files(src, mk, bk)
check("second run keeps the first backup", b == [] and open(os.path.join(bk, "data", "a.txt")).read() == "old a")

for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
G.filedialog.askdirectory = lambda **k: os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_mimickit")
check("actions: none in the public build, the profile's in an overlay", len(core.ACTIONS) == expect.PROFILE_ACTIONS)
hit = []
core.ACTIONS = [dict(text="Do thing", help="tip", run=lambda app: hit.append(app))]
root = tk.Tk()
app = G.App(root)


def find(wid):
    for ch in wid.winfo_children():
        if ch.winfo_class() == "TButton" and ch.cget("text") == "Do thing":
            return ch
        r = find(ch)
        if r:
            return r


b = find(root)
check("profile action becomes a button", b is not None)
if b:
    b.invoke()
check("button runs the action with the app", hit == [app])
root.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
