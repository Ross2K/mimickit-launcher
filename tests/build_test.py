"""Build hygiene: build.py refuses uncommitted changes and a stale overlay; the zip's BUILD stamp shows in About.
python tests/build_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


def refuses(fn, *a):
    try:
        fn(*a)
        return False
    except SystemExit:
        return True


t = tempfile.mkdtemp()
g = lambda *a: subprocess.run(["git", "-C", t] + list(a), capture_output=True, check=True)
g("init", "-q")
open(os.path.join(t, "a.py"), "w").write("x = 1\n")
g("add", "a.py")
g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
build.HERE = t
check("clean tree builds", not refuses(build.check_clean))
open(os.path.join(t, "a.py"), "w").write("x = 2\n")
check("modified file -> refused", refuses(build.check_clean))
g("checkout", "-q", "a.py")
open(os.path.join(t, "new.py"), "w").write("")
check("untracked file -> refused", refuses(build.check_clean))
os.remove(os.path.join(t, "new.py"))
z = tempfile.mkdtemp()
shutil.copy(os.path.join(t, "a.py"), z)
check("synced overlay accepted", not refuses(build.check_overlay_synced, z))
open(os.path.join(z, "a.py"), "w").write("x = 0\n")
check("stale overlay refused", refuses(build.check_overlay_synced, z))
check("stamp format", build.stamp("abc1234567") == "commit abc1234567\n")

from mkl import core

old = core.HERE
core.HERE = t
check("no BUILD -> 'dev'", core.build_id() == "dev")
open(os.path.join(t, "BUILD"), "w").write(build.stamp("abc1234567", " + overlay"))
check("BUILD -> commit shown", core.build_id() == "abc1234567")
core.HERE = old
src = open(os.path.join(ROOT, "mkl", "window.py")).read()
check("About box shows the build", "build_id()" in src)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
