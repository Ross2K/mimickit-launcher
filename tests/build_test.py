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
# old GitHub owner guard (repo renamed to Ross2K): everything flagged except CHANGELOG history + the CONTRIBUTING note
o = tempfile.mkdtemp()
old = build.OLD_OWNER
os.makedirs(os.path.join(o, "mkl"))
open(os.path.join(o, "CHANGELOG.md"), "w").write("- taskbar identity (`%s.MimicKitLauncher`)\n" % old)
open(os.path.join(o, "CONTRIBUTING.md"), "w").write("2. You also grant Ross2K (formerly %s) a license\n" % old)
check("owner guard: CHANGELOG history + CONTRIBUTING 'formerly' note allowed", build.old_owner_hits(o) == [],
      build.old_owner_hits(o))
open(os.path.join(o, "mkl", "icon.py"), "w").write('APP_ID = "%s.MimicKitLauncher"\n# Copyright (C) 2026 %s.\n' % (old, old))
open(os.path.join(o, "LICENSE"), "w").write("Required Notice: Copyright (c) 2026 %s\n" % old)
open(os.path.join(o, "NOTICE"), "w").write("https://github.com/%s\n" % old.lower())
open(os.path.join(o, "mkl", "updatecheck.py"), "w").write('PUBLIC_REPO = "%s/mimickit-launcher"\n' % old)
open(os.path.join(o, "README.md"), "w").write("https://github.com/%s/mimickit-launcher\n" % old.upper())
open(os.path.join(o, "mkl", "window.py"), "w").write('ID = "%s.MimicKitLauncher"\n' % old)
h = build.old_owner_hits(o)
check("owner guard: App ID, copyright, LICENSE/NOTICE, REPO constant, URL (any case) -> flagged",
      sorted(x[0] for x in h) == ["LICENSE", "NOTICE", "README.md", "mkl/icon.py", "mkl/icon.py", "mkl/updatecheck.py",
                                  "mkl/window.py"], h)
open(os.path.join(o, "CONTRIBUTING.md"), "a").write("3. Contact %s\n" % old)
check("owner guard: old name in CONTRIBUTING outside the 'formerly' note flagged",
      [x[:2] for x in build.old_owner_hits(o) if x[0] == "CONTRIBUTING.md"] == [("CONTRIBUTING.md", 2)])
build.HERE = ROOT
check("owner guard: this repo is clean", build.old_owner_hits(ROOT, build.git("ls-files").splitlines()) == [],
      build.old_owner_hits(ROOT, build.git("ls-files").splitlines())[:3])
print("RESULT: %d/%d" % (sum(ok), len(ok)))
