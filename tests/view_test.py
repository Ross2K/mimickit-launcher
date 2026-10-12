"""Preview of a VIEW (motion playback) preset: the clip pose is recorded from the motion library (the sim's joint_q
lags a frame there), so the joint mapping check passes and frame 0 is the clip's start pose.
  PREVIEW_TEST_MK=... PREVIEW_TEST_PY=... PREVIEW_TEST_VIEW_ARGS=args/<view args>.txt[,args/<another>.txt] \\
      xvfb-run -a /path/to/venv/bin/python tests/view_test.py"""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, ROOT)
MK, PY, VA = os.environ.get("PREVIEW_TEST_MK"), os.environ.get("PREVIEW_TEST_PY"), os.environ.get("PREVIEW_TEST_VIEW_ARGS")
if not (MK and PY and VA):
    print("SKIP: set PREVIEW_TEST_MK, PREVIEW_TEST_PY and PREVIEW_TEST_VIEW_ARGS"); print("RESULT: 0/0"); sys.exit(0)
import numpy as np, mimickit_preview as P
ok = []
def check(n, c, i=""): ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)
for args in VA.split(","):
    npz = os.path.join(tempfile.mkdtemp(), "v.npz")
    r = subprocess.run([PY, "-u", os.path.join(ROOT, "mimickit_preview.py"), "record", "--mk", MK, "--device", "cpu", "--out", npz, "--",
                        "--arg_file", args], cwd=MK, capture_output=True, text=True, timeout=1200); out = r.stdout + r.stderr
    name = os.path.basename(args)
    check("%s: record exits 0, view mode detected" % name, r.returncode == 0 and "view preset" in out, out[-300:] if r.returncode else "")
    z = np.load(npz); c = P.clip_data(z)
    err = P.verify_mapping(str(z["char_file"]), npz)
    check("%s: joint mapping OK (was 0.74 m)" % name, err < 0.01, "%.6f m" % err)
    check("%s: no ghost in view mode" % name, not bool(z["has_ref"]) and bool(z["view"]))
    # frame 0 = the clip's pose one control step in, i.e. next to its start; the old path showed the default pose
    steps = [np.abs(c["BP"][i + 1, 0] - c["BP"][i, 0]).max() for i in range(6)]
    d0, med = steps[0], float(np.median(steps[1:]))
    check("%s: frame 0 continues smoothly into frame 1 (start pose, no jump)" % name, d0 < 2 * med + 0.02, "%.4f m vs typical %.4f m" % (d0, med))
print("RESULT: %d/%d" % (sum(ok), len(ok)))
