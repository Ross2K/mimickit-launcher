"""Imported by every *_test.py: the process exits non-zero if any check printed FAIL, or if the last
'RESULT: a/b' line has a < b (also when the RESULT line is printed from a Tk callback, which can't sys.exit)."""

import atexit, os, re, sys

os.environ.setdefault("MIMICKIT_NO_UPDATE_CHECK", "1")  # a0.9.2: tests never hit GitHub from the automatic check

_state = {"fail": False, "result": None}


class _Tee:
    def __init__(self, s):
        self._s = s
        self._buf = ""

    def write(self, t):
        self._buf += t
        *lines, self._buf = self._buf.split("\n")
        for ln in lines:
            if ln.startswith("FAIL "):
                _state["fail"] = True
            m = re.search(r"RESULT: (\d+)/(\d+)", ln)
            if m:
                _state["result"] = (int(m.group(1)), int(m.group(2)))
        return self._s.write(t)

    def __getattr__(self, a):
        return getattr(self._s, a)


sys.stdout = _Tee(sys.stdout)


def failed():
    r = _state["result"]
    return _state["fail"] or (r is not None and r[0] < r[1])


@atexit.register
def _exit_code():
    if failed():
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            os._exit(1)
