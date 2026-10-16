"""Build the release zips: run the tests first, then zip.  python tools/build.py [--z DIR] [--skip-tests]
Version and zip names come from VERSION in mkl/core.py (+ VERSION_SUFFIX of a launcher_profile.py overlay).
Public zip = git archive of HEAD (+ the starter .exe if built, it is not in git). --z DIR also tests and zips that
overlay folder, whose public files must be identical to HEAD. Refuses to build from uncommitted changes. Each zip
carries a BUILD file (commit hash) that the About box shows.
Tests run under xvfb at 1280x1024 (TEST_SCREEN=WxH for another size, e.g. 1920x1200).
Preview tests need a MimicKit install: set PREVIEW_TEST_MK / PREVIEW_TEST_PY / PREVIEW_TEST_ARGS (else they skip).
"""

import os, re, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("BUILD_OUT", os.path.dirname(HERE))
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
    "dashboard_page_test",
    "runs_test",
    "amp_log_test",
    "preset_req_test", "control_gate_test", "window_place_test", "phone_stop_tap_test", "stopsave_race_test", "stop_visible_test", "flow_test", "qa085_test", "qa086_test", "qa087_test", "qa088_test",
    "chart_lines_test",
    "placement_test",
    "fixes042_test",
    "status_test",
    "status_longrun_test",
    "envswitch_test",
    "stopsave_test",
    "icon_test",
    "build_test",
    "actions_test",
    "preview_test",
    "ghost_test",
    "multi_test",
    "view_test",
    "replay_test",
]
KNOWN = {}  # name -> accepted "a/b"; empty: every test must pass


def _version_file(d):
    """VERSION lives in mkl/core.py since a0.5.0 (mimickit_launcher.py before)."""
    p = os.path.join(d, "mkl", "core.py")
    return p if os.path.isfile(p) else os.path.join(d, "mimickit_launcher.py")


def version(d):
    v = re.search(r'^VERSION = \(?\s*"([^"]+)"', open(_version_file(d)).read(), re.M).group(1)
    prof = os.path.join(d, "launcher_profile.py")
    if os.path.isfile(prof):
        m = re.search(r'^VERSION_SUFFIX = "([^"]*)"', open(prof).read(), re.M)
        v += m.group(1) if m else ""
    return v


def git(*a):
    return subprocess.run(["git", "-C", HERE] + list(a), capture_output=True, text=True, check=True).stdout


def check_clean():
    """No release from uncommitted work: every change must be in a commit (so BUILD names exactly what shipped)."""
    dirty = git("status", "--porcelain").strip()
    if dirty:
        sys.exit("uncommitted changes - commit them first, no zip written:\n" + dirty)


def check_overlay_synced(z):
    """The overlay folder = public files of HEAD + its own extras. A stale copy would ship old code."""
    stale = []
    for f in git("ls-files").splitlines():
        p = os.path.join(z, f)
        if not os.path.isfile(p) or open(p, "rb").read() != open(os.path.join(HERE, f), "rb").read():
            stale.append(f)
    if stale:
        sys.exit("overlay %s is out of sync with HEAD (%s) - copy the public files over it first" % (z, ", ".join(stale)))


def stamp(commit, suffix=""):
    return "commit %s%s\n" % (commit, suffix)


def run_tests(d):
    py = os.environ.get("PREVIEW_TEST_PY") or sys.executable
    xvfb = (
        ["xvfb-run", "-a", "-s", "-screen 0 %sx24" % os.environ.get("TEST_SCREEN", "1280x1024")]
        if sys.platform.startswith("linux")
        else []
    )
    bad = []
    extra = sorted(f[:-3] for f in os.listdir(os.path.join(d, "tests")) if f.endswith("_z_test.py"))  # overlay-only
    for t in TESTS + extra + list(KNOWN):
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
        ok = (KNOWN.get(t) == res) if t in KNOWN else (bool(m) and m[-1][0] == m[-1][1] and r.returncode == 0)
        if m and r.returncode != 0 and t not in KNOWN:
            res += " (exit %d)" % r.returncode
        print("%-22s %s%s" % (t, res, "" if ok else "   <-- FAILED"), flush=True)
        if not ok:
            bad.append(t)
            tail = (r.stdout.strip().splitlines()[-5:] + r.stderr.strip().splitlines()[-15:])
            print("\n".join("    | " + x for x in tail), flush=True)
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
    check_clean()
    if z:
        check_overlay_synced(z)
    commit = git("rev-parse", "--short=10", "HEAD").strip()
    if "--skip-tests" not in sys.argv:
        for d in [HERE] + ([z] if z else []):
            print("== tests in", d, flush=True)
            bad = run_tests(d)
            if bad:
                sys.exit("tests failed in %s: %s - no zip written" % (d, ", ".join(bad)))
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
    with zipfile.ZipFile(dst, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimickit-launcher/BUILD", stamp(commit))
        if exe:
            zf.write(exe, "mimickit-launcher/MimicKit Launcher.exe")
    print("wrote", dst)
    if z:
        vz = version(z)
        dz = os.path.join(OUT, "mimickit_launcher_%s.zip" % vz)
        prefix = os.path.basename(os.path.normpath(z))
        zip_dir(z, dz, prefix)
        with zipfile.ZipFile(dz, "a", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(prefix + "/BUILD", stamp(commit, " + overlay"))
        print("wrote", dz)


if __name__ == "__main__":
    main()
