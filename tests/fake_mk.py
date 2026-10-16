"""a0.8.5: a private, throw-away copy of tests/fake_mimickit per test process, so runs write their output/ into a
temp dir and never into the repo (tests/fake_mimickit/output).
a0.8.7 (S4): each copy records its owner pid; a new copy first removes /tmp/mkl_test_* folders whose owner is gone
(a test killed by a timeout or ended with os._exit never runs its atexit cleanup)."""

import atexit, glob, os, shutil, tempfile, time

_HERE = os.path.dirname(os.path.abspath(__file__))
_mk = None


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def sweep():
    """Remove leftover mkl_test_* folders of test processes that no longer run. Returns the removed paths."""
    gone = []
    for d in glob.glob(os.path.join(tempfile.gettempdir(), "mkl_test_*")):
        try:
            pid = int(open(os.path.join(d, "owner.pid")).read().strip())
            dead = pid != os.getpid() and not _alive(pid)
        except (OSError, ValueError):  # no pid file (made before a0.8.7): only when clearly stale
            try:
                dead = time.time() - os.path.getmtime(d) > 3600
            except OSError:
                dead = False
        if dead:
            shutil.rmtree(d, True)
            gone.append(d)
    return gone


def fake_mk():
    global _mk
    if _mk is None:
        sweep()
        d = tempfile.mkdtemp(prefix="mkl_test_")
        with open(os.path.join(d, "owner.pid"), "w") as f:
            f.write(str(os.getpid()))
        atexit.register(shutil.rmtree, d, True)
        _mk = os.path.join(d, "fake_mimickit")
        shutil.copytree(os.path.join(_HERE, "fake_mimickit"), _mk, ignore=shutil.ignore_patterns("output", "__pycache__"))
    return _mk
