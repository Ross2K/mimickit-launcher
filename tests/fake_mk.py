"""a0.8.5: a private, throw-away copy of tests/fake_mimickit per test process, so runs write their output/ into a
temp dir and never into the repo (tests/fake_mimickit/output)."""

import atexit, os, shutil, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_mk = None


def fake_mk():
    global _mk
    if _mk is None:
        d = tempfile.mkdtemp(prefix="mkl_test_")
        atexit.register(shutil.rmtree, d, True)
        _mk = os.path.join(d, "fake_mimickit")
        shutil.copytree(os.path.join(_HERE, "fake_mimickit"), _mk, ignore=shutil.ignore_patterns("output", "__pycache__"))
    return _mk
