"""Build the release zips: run the tests first, then zip.  python tools/build.py [--z DIR] [--skip-tests]
Version and zip names come from VERSION in mimickit_launcher.py (+ VERSION_SUFFIX of a launcher_profile.py overlay).
Public zip = git archive of HEAD (+ the starter .exe if built, it is not in git). --z DIR also zips that overlay folder.
Preview tests need a MimicKit install: set PREVIEW_TEST_MK / PREVIEW_TEST_PY / PREVIEW_TEST_ARGS (else they skip).
"""

import os, re, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("BUILD_OUT", os.path.dirname(HERE))
# replay_test needs real console captures (STUB_REPLAY); without them 5/12 is the known baseline
TESTS = [
    "gui_test",
    "chain_test",
    "detach_test",
    "estimate_test",
    "history_test",
    "time_test",
    "vram_bridge_test",
    "nav_test",
    "remote_test",
    "patch_score_test",
    "dashboard_touch_test",
    "trainsettings_test",
    "decimate_test",
    "preview_test",
    "ghost_test",
    "multi_test",
    "view_test",
]
KNOWN = {"replay_test": "5/12"}


def version(d):
    v = re.search(
        r'^VERSION = "([^"]+)"', open(os.path.join(d, "mimickit_launcher.py")).read(), re.M
    ).group(1)
    prof = os.path.join(d, "launcher_profile.py")
    if os.path.isfile(prof):
        m = re.search(r'^VERSION_SUFFIX = "([^"]*)"', open(prof).read(), re.M)
        v += m.group(1) if m else ""
    return v


def run_tests(d):
    py = os.environ.get("PREVIEW_TEST_PY") or sys.executable
    xvfb = (
        ["xvfb-run", "-a", "-s", "-screen 0 1400x1000x24"]
        if sys.platform.startswith("linux")
        else []
    )
    bad = []
    for t in TESTS + list(KNOWN):
        shutil.rmtree(
            os.path.join(d, "tests", "fake_mimickit", "output"), ignore_errors=True
        )  # fresh state per test
        r = subprocess.run(
            xvfb + [py, os.path.join("tests", t + ".py")],
            cwd=d,
            capture_output=True,
            text=True,
            timeout=1500,
        )
        m = re.findall(r"RESULT: (\d+)/(\d+)", r.stdout)
        res = "%s/%s" % m[-1] if m else "no result (exit %d)" % r.returncode
        ok = (KNOWN.get(t) == res) if t in KNOWN else (bool(m) and m[-1][0] == m[-1][1])
        print("%-22s %s%s" % (t, res, "" if ok else "   <-- FAILED"), flush=True)
        if not ok:
            bad.append(t)
    return bad


def zip_dir(d, dst, prefix):
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(d):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", ".git", "output")]
            for f in files:
                if f.endswith(".pyc"):
                    continue
                p = os.path.join(root, f)
                z.write(p, os.path.join(prefix, os.path.relpath(p, d)))


def main():
    z = sys.argv[sys.argv.index("--z") + 1] if "--z" in sys.argv else None
    if "--skip-tests" not in sys.argv:
        bad = run_tests(HERE)
        if bad:
            sys.exit("tests failed: %s - no zip written" % ", ".join(bad))
    v = version(HERE)
    dst = os.path.join(OUT, "mimickit_launcher_%s.zip" % v)
    subprocess.run(
        [
            "git",
            "-C",
            HERE,
            "archive",
            "--format=zip",
            "--prefix=mimickit-launcher/",
            "-o",
            dst,
            "HEAD",
        ],
        check=True,
    )
    exe = next(
        (
            p
            for p in (
                os.path.join(HERE, "tools", "exe-starter", "out", "MimicKit Launcher.exe"),
                os.path.join(HERE, "MimicKit Launcher.exe"),
            )
            if os.path.isfile(p)
        ),
        None,
    )
    if exe:
        with zipfile.ZipFile(dst, "a", zipfile.ZIP_DEFLATED) as zf:
            zf.write(exe, "mimickit-launcher/MimicKit Launcher.exe")
    print("wrote", dst)
    if z:
        vz = version(z)
        dz = os.path.join(OUT, "mimickit_launcher_%s.zip" % vz)
        zip_dir(z, dz, os.path.basename(os.path.normpath(z)))
        print("wrote", dz)


if __name__ == "__main__":
    main()
