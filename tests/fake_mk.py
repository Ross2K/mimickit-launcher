"""a0.8.5: a private, throw-away copy of tests/fake_mimickit per test process, so runs write their output/ into a
temp dir and never into the repo (tests/fake_mimickit/output).
a0.8.7 (S4): each copy records its owner pid; a new copy first removes /tmp/mkl_test_* folders whose owner is gone
(a test killed by a timeout or ended with os._exit never runs its atexit cleanup)."""

import atexit, glob, os, shutil, sys, tempfile, time

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(_HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))
_mk = None


def _alive(pid):
    """a0.8.8 (T1): liveness through mkl.core.proc_info - OpenProcess/GetExitCodeProcess on Windows (never os.kill,
    which there sends CTRL_C_EVENT and could Ctrl+C a training sim), /proc on Linux. Unknown -> alive (keep it)."""
    try:
        from mkl.core import proc_info
    except Exception:
        return True
    try:
        i = proc_info(pid)
    except Exception:
        return True
    return bool(i and i.get("alive"))


def _pids(d):
    """Owner (test process) + any fake sims (sim.<pid>.pid, written by fake_mimickit/mimickit/run.py) of a folder."""
    out = []
    for f in [os.path.join(d, "owner.pid")] + glob.glob(os.path.join(d, "sim.*.pid")):
        try:
            out.append(int(open(f).read().strip()))
        except (OSError, ValueError):
            pass
    return out


def sweep():
    """Remove leftover mkl_test_* folders whose owner AND fake sims have all ended. Never touches a folder whose
    owner or a sim still runs (a sim orphaned by a test timeout ends itself once its owner is gone, see run.py).
    Folders without an owner.pid (made before a0.8.7) only when older than a day. Returns the removed paths."""
    gone = []
    for d in glob.glob(os.path.join(tempfile.gettempdir(), "mkl_test_*")):
        pids = _pids(d)
        if os.path.isfile(os.path.join(d, "owner.pid")):
            dead = bool(pids) and os.getpid() not in pids and not any(_alive(p) for p in pids)
        else:
            try:
                dead = not pids and time.time() - os.path.getmtime(d) > 86400
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


def hard_kill(pid, group=False):
    """a0.8.8 (T1): kill a test's process (and its group/tree) the way that's safe on each OS: Windows taskkill
    /F (/T for the tree) - never os.kill, which sends CTRL_C_EVENT for signal 0/2; POSIX SIGKILL (killpg for group)."""
    if os.name == "nt":
        import subprocess

        subprocess.run(["taskkill", "/PID", str(pid), "/F"] + (["/T"] if group else []), capture_output=True)
        return
    import signal

    (os.killpg if group else os.kill)(pid, signal.SIGKILL)
