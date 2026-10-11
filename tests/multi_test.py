"""Preview of several training motions (up to 4, each from t=0) in both clip layouts, against a REAL MimicKit install.
  PREVIEW_TEST_MK=... PREVIEW_TEST_PY=... PREVIEW_TEST_ARGS=args/<training args>.txt \\
  PREVIEW_TEST_MULTI_ENV=data/envs/<env yaml whose motion_file is a dataset .yaml with 2+ motions> \\
      xvfb-run -a /path/to/venv/bin/python tests/multi_test.py"""
import os, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, ROOT)
MK, PY, ARGS, MENV = (os.environ.get(k) for k in ("PREVIEW_TEST_MK", "PREVIEW_TEST_PY", "PREVIEW_TEST_ARGS", "PREVIEW_TEST_MULTI_ENV"))
if not (MK and PY and ARGS and MENV):
    print("SKIP: set PREVIEW_TEST_MK, PREVIEW_TEST_PY, PREVIEW_TEST_ARGS and PREVIEW_TEST_MULTI_ENV"); print("RESULT: 0/0"); sys.exit(0)
import numpy as np, imageio.v2 as imageio
import mimickit_preview as P, mimickit_launcher as G
ok = []
def check(n, c, i=""): ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)
SCRIPT = os.path.join(ROOT, "mimickit_preview.py")
work = os.path.join(MK, "output", "_multi_test"); shutil.rmtree(work, ignore_errors=True); os.makedirs(work)
view = os.path.join(work, "view_env.yaml"); G.make_view_env(MK, MENV, view); view_rel = os.path.relpath(view, MK)
clips = P.dataset_motions(MK, view_rel); K = min(4, len(clips))
check("dataset has 2+ motions", len(clips) >= 2, str(clips))
def run(sub, extra):
    r = subprocess.run([PY, "-u", SCRIPT, sub, "--mk", MK] + extra + ["--", "--arg_file", ARGS, "--env_config", view_rel], cwd=MK,
                       capture_output=True, text=True, timeout=1800, env=dict(os.environ, MIMICKIT_PREVIEW_NO_OPEN="1"))
    return r.returncode, r.stdout + r.stderr
npz = os.path.join(work, "m.npz")
rc, out = run("record", ["--device", "cpu", "--out", npz])
check("record exits 0", rc == 0, out[-500:] if rc else "")
z = np.load(npz); c = P.clip_data(z); fps = float(z["fps"])
check("one env per motion, %d clips" % K, c["K"] == K and list(z["motion_ids"]) == list(range(K)), str(list(z["motion_ids"])))
check("clip names from the dataset", [os.path.basename(x) for x in clips[:K]] == c["names"], str(c["names"]))
check("each clip recorded for its full length", all(c["nper"][k] == int(np.ceil(float(z["clip_lens"][k]) * fps)) for k in range(K)),
      "%s %s" % (c["nper"], list(z["clip_lens"])))
check("every clip starts at t=0 (its reference clock)", np.allclose(z["ref_time"][0], 1 / fps, atol=1e-3), str(z["ref_time"][0]))
errs = P.verify_mapping(str(z["char_file"]), npz, ref=True, per_clip=True)
check("each clip's ghost matches its own motion", max(errs) < 0.01, str(["%.6f" % e for e in errs]))
check("clips really differ (different motions)", np.abs(c["RBP"][c["nper"][0] - 1, 0] - c["RBP"][c["nper"][1] - 1, 1]).max() > 0.05)
check("policy panels track their own clip (start pose = clip's start pose)",
      all(np.abs(c["BP"][0, k] - c["RBP"][0, k]).max() < 0.25 for k in range(K)))
for layout, frames in (("grid", max(c["nper"])), ("seq", sum(c["nper"]))):
    mp4 = os.path.join(work, "m_%s.mp4" % layout)
    rc, out = run("render", ["--npz", npz, "--layout", layout, "--ghost", "overlay", "--out", mp4])
    rd = imageio.get_reader(mp4); n = rd.count_frames(); fr = rd.get_data(0); rd.close()
    rows, cols = P.grid_shape(K) if layout == "grid" else (1, 1)
    check("%s: exits 0, %d frames" % (layout, frames), rc == 0 and n == frames, "got %d" % n)
    check("%s: frame size %dx%d panels" % (layout, rows, cols), fr.shape[:2] == (480 * rows, 640 * cols), str(fr.shape))
    check("%s: per-clip ghost check in the log" % layout, out.count(": 0.0") >= K and "(OK)" in out)
specs = P.frame_specs(c, "grid")
check("grid pads shorter clips by holding their last frame", all(specs[-1][k][1] == c["nper"][k] - 1 for k in range(K)))
check("layout helpers", P.grid_shape(1) == (1, 1) and P.grid_shape(2) == (1, 2) and P.grid_shape(3) == (2, 2) and P.grid_shape(4) == (2, 2))
shutil.rmtree(work, ignore_errors=True)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
