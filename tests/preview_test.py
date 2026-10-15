"""Preview MP4 pipeline end to end against a REAL MimicKit install (needs its venv with newton/warp/mujoco/imageio-ffmpeg).
  PREVIEW_TEST_MK=/path/to/MimicKit PREVIEW_TEST_PY=/path/to/venv/bin/python PREVIEW_TEST_ARGS=args/<training args>.txt \\
      xvfb-run -a /path/to/venv/bin/python tests/preview_test.py   (run it with the MimicKit venv python: it reads the mp4)
Checks: CPU recording + MuJoCo render -> playable mp4 whose frame count matches the clip, Newton->MuJoCo joint mapping,
RAM budget sizing, low-memory refusal and mid-run abort, GPU refusal paths, and the launcher's Render preview button."""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import glob, json, math, os, re, shutil, subprocess, sys, tempfile, time

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
import mimickit_preview as P, mimickit_launcher as G

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


SCRIPT = os.path.join(ROOT, "mimickit_preview.py")
work = os.path.join(MK, "output", "_preview_test")
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)
env_rel = G.read_args_file(os.path.join(MK, ARGS)).get("env_config", [""])[0]
view = os.path.join(work, "view_env.yaml")
G.make_view_env(MK, env_rel, view)
view_rel = os.path.relpath(view, MK)
model = os.path.join(work, "model.pt")


def run(extra_env=None, device="cpu", out="p.mp4", save_init=False, timeout=900):
    cmd = [
        PY,
        "-u",
        SCRIPT,
        "all",
        "--mk",
        MK,
        "--device",
        device,
        "--out",
        os.path.join(work, out),
        "--keep_npz",
    ]
    if save_init:
        cmd += ["--save_init_model", model]
    cmd += ["--", "--env_config", view_rel, "--arg_file", ARGS] + (
        [] if save_init else ["--model_file", os.path.relpath(model, MK)]
    )
    t0 = time.time()
    r = subprocess.run(
        cmd,
        cwd=MK,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=dict(os.environ, MIMICKIT_PREVIEW_NO_OPEN="1", **(extra_env or {})),
    )
    return r.returncode, r.stdout + r.stderr, time.time() - t0


# 1) end to end on the CPU (a freshly initialized policy is saved as model.pt on the way)
def cache_snapshot():
    import warp as wp_

    d = wp_.config.kernel_cache_dir or os.path.join(os.path.expanduser("~"), ".cache", "warp")
    return {
        os.path.join(r, f): os.path.getmtime(os.path.join(r, f))
        for r, _, fs in os.walk(os.path.expanduser("~/.cache/warp"))
        for f in fs
    }


snap0 = cache_snapshot()
rc, out, el = run(save_init=True)
print("\n".join(l for l in out.splitlines() if l.startswith("[preview]")))
mp4 = os.path.join(work, "p.mp4")
npz = os.path.join(work, "p.npz")
check("CPU end to end exits 0", rc == 0, "%.1f s" % el)
check("recorded on the CPU without CUDA", "recording on the CPU" in out and "cuda:0" not in out)
check(
    "Warp default device is cpu in the recorder",
    "default device cpu" in out,
    [l for l in out.splitlines() if "default device" in l][:1].__str__(),
)
check(
    "CUDA hidden with CUDA_VISIBLE_DEVICES='-1' (empty is ignored on Windows)",
    "CUDA_VISIBLE_DEVICES='-1'" in out,
)
check(
    "Warp init mirrors training (enable_backward False, newton modules too)",
    "enable_backward False" in out and "built with backward" not in out,
)
check(
    "preview uses its own Warp kernel cache",
    "_launcher_preview" in out
    and os.path.isdir(os.path.join(MK, "output", "_launcher_preview", "warp_cache"))
    and any(
        True for _ in os.scandir(os.path.join(MK, "output", "_launcher_preview", "warp_cache"))
    ),
)
check("default (training) Warp cache untouched", cache_snapshot() == snap0)
# CPU guard: a kernel launch that resolves to a CUDA device aborts with a clear message (simulated CUDA device)
g = subprocess.run(
    [
        PY,
        "-c",
        """
import sys; sys.argv = ["x"]; sys.path.insert(0, %r)
import mimickit_preview as P, warp as wp
wp.init(); P.install_cpu_guard(wp)
class FakeCuda:
    is_cuda = True
    def __str__(self): return "cuda:0"
orig = wp.get_device; wp.get_device = lambda d=None: FakeCuda()
@wp.kernel
def k(a: wp.array(dtype=float)): a[wp.tid()] = 1.0
try: wp.launch(k, dim=1, inputs=[wp.zeros(1, dtype=float, device="cpu")]); print("NO GUARD")
except RuntimeError as e: print("GUARD:", e)
""" % ROOT,
    ],
    capture_output=True,
    text=True,
    timeout=120,
)
check(
    "CPU guard stops a launch on a (simulated) CUDA device",
    "GUARD: [preview] CPU path: Warp kernel" in g.stdout,
    g.stdout.strip()[-160:],
)
import numpy as np, imageio.v2 as iio

z = np.load(npz)
n = int(z["frames"])
want = int(math.ceil(float(z["clip_len"]) * float(z["fps"])))
check(
    "frame count = ceil(clip length x fps)",
    n == want,
    "%d frames for %.2f s at %.0f fps" % (n, float(z["clip_len"]), float(z["fps"])),
)
rd = iio.get_reader(mp4)
nf = rd.count_frames()
meta = rd.get_meta_data()
check(
    "mp4 is playable with the same frame count",
    nf == n and abs(meta["fps"] - float(z["fps"])) < 0.01,
    "%d frames, %s fps, %s" % (nf, meta["fps"], meta.get("size")),
)
fr = rd.get_data(nf // 2)
check("frames are rendered (not blank)", fr.std() > 5, "pixel std %.1f" % fr.std())
m = re.search(r"max body position difference Newton vs MuJoCo = ([\d.]+) m", out)
check(
    "Newton -> MuJoCo joint mapping verified (< 1 cm)",
    m and float(m.group(1)) < 0.01,
    m.group(0) if m else "",
)
check(
    "parallel render workers",
    re.search(r"with (\d+) worker", out)
    and int(re.search(r"with (\d+) worker", out).group(1)) >= 1,
)
sp = re.search(
    r"recorded \d+ (?:frames|steps x \d+ clip\(s\)) in ([\d.]+) s \(([\d.]+)x real time", out
)
check(
    "CPU speed within the 20x limit",
    sp and float(sp.group(1)) <= 20 * float(z["clip_len"]),
    sp.group(0) if sp else "",
)
pk = re.search(r"peak RAM of the preview processes (\d+) MB of (\d+) MB", out)
check(
    "peak RAM stayed inside the budget",
    pk and int(pk.group(1)) < int(pk.group(2)),
    pk.group(0) if pk else "",
)
# 2) RAM cap logic
check(
    "worker plan fits the budget",
    P.plan_workers(150 + 3 * 320 + 10, 300, cpus=8) == 3
    and P.plan_workers(100000, 300, cpus=8) == 8
    and P.plan_workers(100000, 20, cpus=8) == 1
    and P.plan_workers(10, 300, cpus=8) == 1,
)
check("free RAM detection works", P.free_ram_mb() > 100 and (P.tree_rss_mb(os.getpid()) or 0) > 5)
rc, out, _ = run({"MIMICKIT_PREVIEW_FREE_MB": "300"}, out="low.mp4")
check(
    "simulated low RAM: refused up front (exit 3)",
    rc == 3 and "not enough free RAM" in out,
    out.strip().splitlines()[-1] if out.strip() else "",
)
rc, out, _ = run({"MIMICKIT_PREVIEW_FREE_MB": "700"}, out="abort.mp4")
check(
    "simulated low RAM: clean abort while running (exit 3)",
    rc == 3
    and "ABORTED: RAM use reached" in out
    and not os.path.exists(os.path.join(work, "abort.mp4")),
    [l for l in out.splitlines() if "ABORTED" in l][:1].__str__(),
)
time.sleep(1)
left = subprocess.run(
    ["pgrep", "-f", "mimickit_preview.py record"], capture_output=True, text=True
).stdout.split()
check("no recorder left running after abort", not left, str(left))
# 3) GPU path guards (rendering stays on the CPU)
rc, out, _ = run({"MIMICKIT_PREVIEW_GPU_FREE_MB": "300"}, device="gpu", out="g.mp4", timeout=120)
check("GPU refused when < 600 MB VRAM free", rc == 5 and "REFUSED" in out)
if not shutil.which("nvidia-smi"):
    rc, out, _ = run({}, device="gpu", out="g2.mp4", timeout=120)
    check("GPU path without a GPU: clear message", rc == 5 and "No NVIDIA GPU" in out)
# 4) the launcher's button: detached process, log in the panel, mp4 next to the model
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ["MIMICKIT_PREVIEW_NO_OPEN"] = "1"
import tkinter as tk

for n_ in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n_, lambda *a, **k: print("[dialog]", a))
G.messagebox.askyesno = lambda *a, **k: True
G.filedialog.askdirectory = lambda **k: MK
root = tk.Tk()
app = G.App(root)


def wait(sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        root.update()
        time.sleep(0.05)


wait(1.5)
app.v_mk.set(MK)
app.v_venv.set(PY)
app._save()
app.rescan()
name = os.path.splitext(os.path.basename(ARGS))[0]
app.v_train.set(
    next(
        i["name"]
        for i in app.train_items
        if i["file"].replace("\\", "/") == ARGS or i["name"] == name
    )
)
app._train_changed()
app.v_model.set(model)
app.v_pdev.set("CPU only")
for f in glob.glob(os.path.join(work, "preview_*.mp4")):
    os.remove(f)
app.preview()
pid = app.preview_proc.pid if app.preview_proc else None
check("preview runs as its own detached process", pid and G.proc_info(pid) and app.proc is None)
t0 = time.time()
while time.time() - t0 < 600 and app.preview_proc.poll() is None:
    wait(1)
wait(1.5)
log = app.t_log.get("1.0", "end")
outs = glob.glob(os.path.join(work, "preview_*.mp4"))
check(
    "button: progress + status in the log panel",
    "PREVIEW" in log
    and "[preview] record frame" in log
    and "PREVIEW_DONE" in log
    and "preview process ended (exit code 0)" in log,
)
check(
    "button: preview_<iteration>.mp4 next to the model",
    len(outs) == 1,
    str([os.path.basename(o) for o in outs]),
)
check(
    "button: chronological view env generated under output/",
    os.path.exists(os.path.join(MK, "output", "_launcher_preview", "view_env.yaml")),
)
print("RESULT: %d/%d" % (sum(ok), len(ok)))
root.destroy()
