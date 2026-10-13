"""Reference ghost, staged CPU fallback and preview diagnostics against a REAL MimicKit install (same env vars as
preview_test.py: PREVIEW_TEST_MK, PREVIEW_TEST_PY, PREVIEW_TEST_ARGS; run with the MimicKit venv python under xvfb-run).
"""

import os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
MK, PY, ARGS = (
    os.environ.get("PREVIEW_TEST_MK"),
    os.environ.get("PREVIEW_TEST_PY"),
    os.environ.get("PREVIEW_TEST_ARGS"),
)
if not (MK and PY and ARGS):
    print("SKIP: set PREVIEW_TEST_MK, PREVIEW_TEST_PY and PREVIEW_TEST_ARGS")
    print("RESULT: 0/0")
    sys.exit(0)
import numpy as np, imageio.v2 as imageio
import mimickit_preview as P, mimickit_launcher as G

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


SCRIPT = os.path.join(ROOT, "mimickit_preview.py")
work = os.path.join(MK, "output", "_ghost_test")
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
env_rel = G.read_args_file(os.path.join(MK, ARGS)).get("env_config", [""])[0]
view = os.path.join(work, "view_env.yaml")
G.make_view_env(MK, env_rel, view)
view_rel = os.path.relpath(view, MK)
MKARGS = ["--env_config", view_rel, "--arg_file", ARGS]


def run(sub, extra=(), env=None, timeout=1200):
    r = subprocess.run(
        [PY, "-u", SCRIPT, sub, "--mk", MK] + list(extra) + ["--"] + MKARGS,
        cwd=MK,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=dict(os.environ, MIMICKIT_PREVIEW_NO_OPEN="1", **(env or {})),
    )
    return r.returncode, r.stdout + r.stderr


# 1) record once (full clip) with the reference pose, then render both ghost modes from the same npz
npz = os.path.join(work, "g.npz")
rc, out = run("record", ["--device", "cpu", "--out", npz])
check("record exits 0", rc == 0, out[-400:] if rc else "")
z = np.load(npz)
n = int(z["frames"])
fps = float(z["fps"])
check(
    "reference pose recorded", bool(z["has_ref"]) and z["ref_joint_q"].shape == z["joint_q"].shape
)
check(
    "reference follows the policy's motion id and clock",
    np.allclose(z["ref_time"].reshape(n, -1)[:, 0], (np.arange(n) + 1) / fps, atol=1e-3),
    "t[-1]=%s" % (z["ref_time"][-1],),
)
err = P.verify_mapping(str(z["char_file"]), npz, ref=True)
check("ghost pose matches the motion at t (MuJoCo FK vs motion-lib FK)", err < 0.01, "%.6f m" % err)
check(
    "frame 0 of the ghost equals the policy's start pose (reset to the reference)",
    np.abs(z["ref_body_pos"][0] - z["body_pos"][0]).max() < 0.25,
)
frames = {}
for mode in ("side", "overlay", "off"):
    mp4 = os.path.join(work, "g_%s.mp4" % mode)
    rc, out = run("render", ["--npz", npz, "--ghost", mode, "--out", mp4])
    rd = imageio.get_reader(mp4)
    cnt = rd.count_frames()
    frames[mode] = rd.get_data(n // 2).astype(int)
    rd.close()
    check("%s: render exits 0, %d frames" % (mode, n), rc == 0 and cnt == n, "got %d" % cnt)
    if mode != "off":
        check(
            "%s: log names the ghost mode and passes the pose check" % mode,
            "reference ghost:" in out and "(OK)" in out,
        )
orange = lambda im: int(
    ((im[..., 0] > 150) & (im[..., 1] > 60) & (im[..., 1] < 170) & (im[..., 2] < 90)).sum()
)
check(
    "ghost visible (orange pixels) in side and overlay, not in off",
    orange(frames["side"][60:]) > 300
    and orange(frames["overlay"][60:]) > 300
    and orange(frames["off"][60:]) < 50,
    "side %d overlay %d off %d"
    % (orange(frames["side"][60:]), orange(frames["overlay"][60:]), orange(frames["off"][60:])),
)
check(
    "legend drawn (Policy / Reference box)",
    orange(frames["side"][30:52, 10:32]) > 100 and orange(frames["off"][30:52, 10:32]) < 5,
)
check(
    "side by side offset is sideways (ref_char_offset, z=0)",
    abs(P.ghost_offset(z, "side")[2]) < 1e-9
    and np.linalg.norm(P.ghost_offset(z, "side")) >= 0.5
    and not P.ghost_offset(z, "overlay").any(),
)

# 2) staged fallback: a native crash in stage a -> stage b runs in a fresh process and records
rc, out = run(
    "all",
    ["--device", "cpu", "--frames", "20", "--ghost", "side", "--out", os.path.join(work, "s.mp4")],
    env={"MIMICKIT_PREVIEW_SIMULATE_CRASH": "cpu-hidden", "MIMICKIT_PREVIEW_FAKE_VRAM_MB": "120"},
)
check(
    "stage a crash (native) is caught, calm wording",
    "cpu-hidden is not usable on this PC" in out
    and "simulated native crash" in out
    and "crashed"
    not in out.split("simulated native crash")[1].split("recorded with")[0].replace("Fatal", ""),
)
check(
    "faulthandler printed the crash stack",
    "Fatal Python error" in out or "Segmentation fault" in out,
)
check(
    "stage b ran and recorded",
    "PREVIEW VARIANT cpu-visible" in out and "recorded with variant cpu-visible" in out and rc == 0,
)
check(
    "stage b ran with the GPU visible and PYTORCH_JIT=0",
    "variant cpu-visible, PYTORCH_JIT=0, CUDA_VISIBLE_DEVICES=None" in out,
)
rc, out = run(
    "all",
    ["--device", "auto", "--frames", "20", "--out", os.path.join(work, "s2.mp4")],
    env={
        "MIMICKIT_PREVIEW_SIMULATE_CRASH": "cpu-hidden",
        "MIMICKIT_PREVIEW_FAKE_VRAM_MB": "900",
        "MIMICKIT_PREVIEW_GPU_FREE_MB": "100",
    },
)
check(
    "stage b over the VRAM cap is aborted, then stage c (GPU) is tried",
    "used 900 MB of GPU memory" in out and "trying gpu" in out and "REFUSED" in out,
)
# Windows: after cpu-hidden crashed and cpu-visible worked, the next preview goes straight to cpu-visible (per machine)
stp = os.path.join(MK, "output", "_launcher_preview", "preview_state.json")
if os.path.exists(stp):
    os.remove(stp)
W = {
    "MIMICKIT_PREVIEW_SIMULATE_CRASH": "cpu-hidden",
    "MIMICKIT_PREVIEW_FAKE_VRAM_MB": "17",
    "MIMICKIT_PREVIEW_ASSUME_WINDOWS": "1",
}
rc1, out1 = run(
    "all", ["--device", "auto", "--frames", "10", "--out", os.path.join(work, "w1.mp4")], env=W
)
rc2, out2 = run(
    "all", ["--device", "auto", "--frames", "10", "--out", os.path.join(work, "w2.mp4")], env=W
)
check(
    "Windows: failure remembered per PC",
    rc1 == 0 and "noted for this PC" in out1 and os.path.exists(stp),
)
check(
    "Windows: next preview skips cpu-hidden calmly",
    rc2 == 0
    and "PREVIEW VARIANT cpu-hidden" not in out2
    and "using cpu-visible on this PC" in out2
    and "~17 MB" in out2,
)
os.remove(stp)
check(
    "CPU only never reaches the GPU stage",
    P.stages_for("cpu") == ["cpu-hidden", "cpu-visible"] and P.stages_for("auto")[-1] == "gpu",
)
e = P.variant_env("cpu-hidden", {})
e2 = P.variant_env("cpu-visible", {"CUDA_VISIBLE_DEVICES": "0"})
check(
    "variant environments",
    e["CUDA_VISIBLE_DEVICES"] == "-1"
    and e["PYTORCH_JIT"] == "0"
    and e["PYTHONFAULTHANDLER"] == "1"
    and "CUDA_VISIBLE_DEVICES" not in e2
    and e2["PYTORCH_JIT"] == "0"
    and "PYTORCH_JIT" not in P.variant_env("gpu", {}),
)

# 3) diagnostics
rep = os.path.join(MK, "output", "_launcher_preview", "preview_diagnostics.txt")
if os.path.exists(rep):
    os.remove(rep)
rc, out = run("diag", ["--frames", "10"], timeout=2400)
txt = open(rep).read() if os.path.exists(rep) else ""
check("diagnostics exit 0 and write the report", rc == 0 and "DIAGNOSTICS_DONE" in out and txt)
check(
    "all probes P1-P7 reported",
    all(("%s result:" % p) in txt for p in ("P1", "P2", "P3", "P4", "P5", "P6", "P7")),
)
check("probes print checkpoints", "CKPT build_env" in txt and "CKPT compile+launch" in txt)
check("same text in the log panel stream", all(l in out for l in txt.splitlines()[-3:]))
rc, out = run("diag", ["--probes", "P2"], env={"MIMICKIT_PREVIEW_SIMULATE_CRASH": ""})
check("probe subset", "P2 result: PASS" in out and "P3 result" not in out)
shutil.rmtree(work, ignore_errors=True)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
