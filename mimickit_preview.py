"""MimicKit Launcher - preview MP4 renderer (part of MimicKit Launcher, GPL-3.0-or-later, Copyright (c) 2026 curelessSky).

Runs in MimicKit's own Python environment, in a separate (detached) process so it can never take down a training run.
  all    : record (CPU first, GPU fallback per --device) -> render with plain MuJoCo on the CPU -> open the MP4
  record : MimicKit build_env/build_agent, 1 env, deterministic actions, logs the joint state per frame to an .npz
  render : MuJoCo (CPU) renders the .npz with a tracking camera, frame chunks in parallel, streamed to H.264 MP4
RAM: the budget is 80% of the free RAM at launch; workers/buffers are sized to it and the process tree's RSS is
monitored - the job aborts cleanly (exit code 3) if it approaches the budget.
"""
import argparse, json, math, os, shutil, subprocess, sys, tempfile, threading, time

FPS_DEFAULT = 30
RAM_FRACTION = 0.80          # budget = 80% of free RAM at launch
ABORT_AT = 0.92              # abort when the process tree uses 92% of the budget
RECORD_EST_MB = 900          # torch + warp + newton recording 1 env on the CPU (measured peak ~700 MB)
WORKER_EST_MB = 320          # one MuJoCo renderer + ffmpeg encoder at 640x480 (measured ~300 MB)
BASE_EST_MB = 150            # this orchestrating process
MIN_GPU_FREE_MB = 600        # refuse the GPU path below this much free VRAM
SLOW_FACTOR = 20.0           # Auto: fall back to the GPU if CPU recording would take > 20x the clip length
EXIT_RAM = 3

def log(*a):
    print("[preview]", *a, flush=True)

# ---------------------------------------------------------------- memory
def free_ram_mb():
    if os.environ.get("MIMICKIT_PREVIEW_FREE_MB"):          # tests: simulate a low-memory machine
        return float(os.environ["MIMICKIT_PREVIEW_FREE_MB"])
    try:
        import psutil; return psutil.virtual_memory().available / 2**20
    except ImportError:
        pass
    if os.name == "nt":
        import ctypes
        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS(); m.dwLength = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullAvailPhys / 2**20
    try:
        for l in open("/proc/meminfo"):
            if l.startswith("MemAvailable:"): return int(l.split()[1]) / 1024
    except OSError:
        pass
    return 4096.0

def tree_rss_mb(pid):
    """RSS of a process and all its children in MB (psutil, else /proc on Linux; None if unknown)."""
    try:
        import psutil
        p = psutil.Process(pid); tot = 0
        for q in [p] + p.children(recursive=True):
            try: tot += q.memory_info().rss
            except psutil.Error: pass
        return tot / 2**20
    except ImportError:
        pass
    except Exception:
        return None
    if not os.path.isdir("/proc"): return None
    kids = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                st = open("/proc/%s/stat" % d).read(); ppid = int(st[st.rindex(")") + 2:].split()[1])
                kids.setdefault(ppid, []).append(int(d))
            except (OSError, ValueError): pass
    tot, todo = 0, [pid]
    while todo:
        q = todo.pop(); todo += kids.get(q, [])
        try:
            for l in open("/proc/%d/status" % q):
                if l.startswith("VmRSS:"): tot += int(l.split()[1]) * 1024
        except OSError: pass
    return tot / 2**20

class RamGuard:
    """Watches the RSS of this process tree; on reaching ABORT_AT x budget it kills the children and flags an abort."""
    def __init__(self, budget_mb):
        self.budget, self.peak, self.tripped, self.children = budget_mb, 0.0, None, []
        self._stop = False; threading.Thread(target=self._loop, daemon=True).start()
    def _loop(self):
        while not self._stop:
            r = tree_rss_mb(os.getpid())
            if r is not None:
                self.peak = max(self.peak, r)
                if r > ABORT_AT * self.budget and not self.tripped:
                    self.tripped = r
                    for c in list(self.children):
                        try: c.kill()
                        except Exception: pass
            time.sleep(0.25)
    def stop(self): self._stop = True

def ram_abort(guard):
    log("ABORTED: RAM use reached %.0f MB, close to the budget of %.0f MB (80%% of the RAM that was free at launch)."
        % (guard.tripped, guard.budget))
    log("Nothing else was affected. Close other programs (or wait until less RAM is in use) and try again.")
    sys.exit(EXIT_RAM)

# ---------------------------------------------------------------- record (inside MimicKit)
def cmd_record(a):
    mk = os.path.abspath(a.mk); os.chdir(mk); sys.path.insert(0, os.path.join(mk, "mimickit"))
    import numpy as np, torch
    torch.set_num_threads(os.cpu_count() or 1)
    try:
        import warp as wp
        log("torch threads: %d; warp %s (its CPU kernels have no thread-count setting)" % (torch.get_num_threads(), wp.config.version))
    except Exception:
        pass
    import run as mk_run, newton
    args = mk_run.load_args(["run.py"] + a.mk_args)
    t0 = time.time()
    env = mk_run.build_env(args, 1, a.device, False)
    agent = mk_run.build_agent(args, env, a.device)
    model_file = args.parse_string("model_file", "")
    if model_file: agent.load(model_file); log("loaded", model_file)
    else: log("no model file: using a freshly initialized (untrained) policy")
    if a.save_init_model: agent.save(a.save_init_model); log("saved initial model to", a.save_init_model)
    import learning.base_agent as base_agent
    agent.eval(); agent.set_mode(base_agent.AgentMode.TEST)
    eng = env._engine; sm = eng._sim_model
    dt = eng.get_timestep(); fps = 1.0 / dt
    with torch.no_grad():
        obs, info = env.reset()
    mid = int(env._motion_ids[0]) if hasattr(env, "_motion_ids") else 0
    clip_len = float(env._motion_lib.get_motion_length(torch.tensor([mid], device=a.device))[0]) if hasattr(env, "_motion_lib") else a.seconds
    n = a.frames or int(math.ceil(clip_len * fps))
    setup = time.time() - t0
    log("setup %.1f s on %s; clip %.2f s -> %d frames at %.0f fps" % (setup, a.device, clip_len, n, fps))
    # articulation 0 = the character; joint and body layout for the MuJoCo mapping
    art = sm.articulation_start.numpy(); j0, j1 = int(art[0]), int(art[1])
    jqs = sm.joint_q_start.numpy(); jt = sm.joint_type.numpy()
    jl = getattr(sm, "joint_label", None) or getattr(sm, "joint_key", None) or []
    bl = getattr(sm, "body_label", None) or getattr(sm, "body_key", None) or []
    jnames = [os.path.basename(str(x)) for x in list(jl)[j0:j1]]
    jtypes = [newton.JointType(int(t)).name for t in jt[j0:j1]]
    q0, q1 = int(jqs[j0]), int(jqs[j1])
    jstart = [int(jqs[j]) - q0 for j in range(j0, j1)]
    nb = j1 - j0      # one body per joint in an articulation
    bnames = [os.path.basename(str(x)) for x in list(bl)[j0:j1]]
    nqtot = sm.joint_q.shape[0] // 1
    Q = np.zeros((n, q1 - q0), np.float32); BP = np.zeros((n, nb, 3), np.float32)
    t1 = time.time(); last = t1
    with torch.no_grad():
        for i in range(n):
            act, _ = agent._decide_action(obs, info)
            obs, r, done, info = env.step(act)      # 'done' is ignored on purpose: one continuous take of the clip
            jq = eng._sim_state._torch_joint_q.view(1, -1)[0]
            Q[i] = jq[q0:q1].detach().cpu().numpy()
            BP[i] = eng._sim_state._torch_body_q.view(1, -1, 7)[0, j0:j1, :3].detach().cpu().numpy()
            now = time.time()
            if i == 9 and a.slow_check:
                proj = (now - t1) / 10 * n
                if proj > SLOW_FACTOR * clip_len:
                    log("CPU too slow: %.1f s projected for a %.1f s clip (limit %.0fx)" % (proj, clip_len, SLOW_FACTOR)); sys.exit(4)
            if now - last > 2 or i == n - 1:
                el = now - t1; log("record frame %d/%d  (%.1f frames/s = %.2fx real time)" % (i + 1, n, (i + 1) / el, (i + 1) / el / fps)); last = now
    el = time.time() - t1
    np.savez(a.out, joint_q=Q, body_pos=BP, joint_names=np.array(jnames), joint_types=np.array(jtypes), joint_start=np.array(jstart),
             body_names=np.array(bnames), fps=fps, clip_len=clip_len, motion_id=mid, frames=n,
             char_file=_char_file(mk, args.parse_string("env_config")),
             record_seconds=el, setup_seconds=setup, device=a.device)
    log("recorded %d frames in %.1f s (%.1fx real time; setup %.1f s) -> %s" % (n, el, n / fps / el, setup, a.out))

def _char_file(mk, env_yaml):
    import yaml
    cfg = yaml.safe_load(open(os.path.join(mk, env_yaml))) or {}
    return os.path.join(mk, cfg.get("char_file", "")) if cfg.get("char_file") else ""

# ---------------------------------------------------------------- render (plain MuJoCo, CPU)
def _load_mj(char_file):
    import mujoco
    spec = mujoco.MjSpec.from_file(char_file)
    tex = spec.add_texture(); tex.name = "lk_grid"; tex.type = mujoco.mjtTexture.mjTEXTURE_2D
    tex.builtin = mujoco.mjtBuiltin.mjBUILTIN_CHECKER; tex.rgb1 = [0.22, 0.24, 0.27]; tex.rgb2 = [0.30, 0.32, 0.36]
    tex.width = tex.height = 512
    mat = spec.add_material(); mat.name = "lk_floor"; mat.texrepeat = [10, 10]
    mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = "lk_grid"
    g = spec.worldbody.add_geom(); g.name = "lk_floor"; g.type = mujoco.mjtGeom.mjGEOM_PLANE; g.size = [60, 60, 0.1]
    g.material = "lk_floor"; g.contype = 0; g.conaffinity = 0
    for pos, dirn in (([0, 0, 6], [0, 0, -1]), ([4, -4, 5], [-0.5, 0.5, -0.7])):
        l = spec.worldbody.add_light(); l.pos = pos; l.dir = dirn; l.diffuse = [0.6, 0.6, 0.6]; l.castshadow = True
    spec.visual.headlight.ambient = [0.35, 0.35, 0.35]
    return spec.compile()

def qpos_map(m, z):
    """Index plan Newton joint_q -> MuJoCo qpos, walking both in MJCF order.
    Newton quaternions are (x, y, z, w), MuJoCo's are (w, x, y, z). MimicKit/Newton merge the 2-3 hinge joints of one body
    into a single BALL joint (a quaternion); MuJoCo keeps the separate hinges, so those are solved back into hinge angles."""
    import mujoco
    types, starts = [str(x) for x in z["joint_types"]], [int(x) for x in z["joint_start"]]
    plan, k = [], 0
    for t, s in zip(types, starts):
        if t == "FIXED": continue
        if k >= m.njnt: raise ValueError("Newton has more joints than the MJCF")
        jt = int(m.jnt_type[k]); adr = int(m.jnt_qposadr[k])
        if t == "FREE":
            assert jt == mujoco.mjtJoint.mjJNT_FREE, "root joint mismatch"; plan.append(("free", s, adr)); k += 1
        elif t == "BALL" and jt == mujoco.mjtJoint.mjJNT_BALL:
            plan.append(("ball", s, adr)); k += 1
        elif t == "BALL":                       # merged hinges of one body
            body = int(m.jnt_bodyid[k]); adrs, axes = [], []
            while k < m.njnt and int(m.jnt_bodyid[k]) == body and int(m.jnt_type[k]) == mujoco.mjtJoint.mjJNT_HINGE:
                adrs.append(int(m.jnt_qposadr[k])); axes.append(m.jnt_axis[k].copy()); k += 1
            plan.append(("hinges", s, adrs, axes))
        else:
            plan.append(("scalar", s, adr)); k += 1
    return plan

def _qmat(w, x, y, zz):
    import numpy as np
    return np.array([[1 - 2 * (y * y + zz * zz), 2 * (x * y - zz * w), 2 * (x * zz + y * w)],
                     [2 * (x * y + zz * w), 1 - 2 * (x * x + zz * zz), 2 * (y * zz - x * w)],
                     [2 * (x * zz - y * w), 2 * (y * zz + x * w), 1 - 2 * (x * x + y * y)]])

def _axis_rot(ax, t):
    import numpy as np
    ax = ax / np.linalg.norm(ax); K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    return np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * K @ K

def _solve_hinges(R, axes, t0):
    """Angles t with R = Rot(a1,t1) Rot(a2,t2) ... (hinges of one body compose in MJCF order); Gauss-Newton from t0."""
    import numpy as np
    t = np.array(t0, float)
    def f(t):
        M = np.eye(3)
        for a, ti in zip(axes, t): M = M @ _axis_rot(a, ti)
        return (M - R).ravel()
    for _ in range(30):
        r = f(t); J = np.empty((9, len(t))); h = 1e-6
        for i in range(len(t)):
            d = np.zeros(len(t)); d[i] = h; J[:, i] = (f(t + d) - r) / h
        step = np.linalg.lstsq(J, -r, rcond=None)[0]; t += step
        if np.abs(step).max() < 1e-10: break
    return t

def apply_q(plan, q, qpos, prev=None):
    """prev: dict carrying the last hinge solution per joint (keeps angles continuous between frames)."""
    prev = {} if prev is None else prev
    for e in plan:
        kind, s = e[0], e[1]
        if kind == "free":
            adr = e[2]; qpos[adr:adr + 3] = q[s:s + 3]; x, y, zz, w = q[s + 3:s + 7]; qpos[adr + 3:adr + 7] = (w, x, y, zz)
        elif kind == "ball":
            adr = e[2]; x, y, zz, w = q[s:s + 4]; qpos[adr:adr + 4] = (w, x, y, zz)
        elif kind == "hinges":
            x, y, zz, w = q[s:s + 4]; n = (x * x + y * y + zz * zz + w * w) ** 0.5
            t = _solve_hinges(_qmat(w / n, x / n, y / n, zz / n), e[3], prev.get(s, [0.0] * len(e[2])))
            prev[s] = t
            for adr, ti in zip(e[2], t): qpos[adr] = ti
        else:
            qpos[e[2]] = q[s]

def verify_mapping(char_file, npz):
    """Max distance between Newton's body positions and MuJoCo's forward kinematics of the mapped qpos."""
    import numpy as np, mujoco
    z = np.load(npz); m = mujoco.MjModel.from_xml_path(char_file); d = mujoco.MjData(m); plan = qpos_map(m, z)
    err, prev = 0.0, {}
    for i in range(int(z["frames"])):
        apply_q(plan, z["joint_q"][i].astype(float), d.qpos, prev); mujoco.mj_kinematics(m, d)
        for bi, bn in enumerate(z["body_names"]):
            b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, str(bn))
            if b >= 0: err = max(err, float(np.linalg.norm(d.xpos[b] - z["body_pos"][i, bi])))
    return err

def _render_chunk(job):
    char_file, npz, lo, hi, part, w, h = job
    import numpy as np, mujoco, imageio.v2 as imageio
    z = np.load(npz); m = _load_mj(char_file); d = mujoco.MjData(m); plan = qpos_map(m, z)
    r = mujoco.Renderer(m, h, w)
    cam = mujoco.MjvCamera(); cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING; cam.trackbodyid = 1
    cam.distance, cam.azimuth, cam.elevation = 3.6, 120.0, -12.0
    wr = imageio.get_writer(part, fps=float(z["fps"]), codec="libx264", quality=8, macro_block_size=8,
                            pixelformat="yuv420p", ffmpeg_log_level="error")
    prev = {}
    for i in range(lo, hi):
        apply_q(plan, z["joint_q"][i].astype(float), d.qpos, prev); mujoco.mj_forward(m, d)
        r.update_scene(d, camera=cam); wr.append_data(r.render())     # streamed: no frame list kept in RAM
    wr.close(); r.close()
    return hi - lo

def plan_workers(budget_mb, frames, cap=0, cpus=None):
    """Parallel render workers: one per core, at least ~15 frames each, and only as many as fit in the RAM budget."""
    cpus = cpus or os.cpu_count() or 1
    fit = int((budget_mb - BASE_EST_MB) // WORKER_EST_MB)
    return max(1, min(cpus, cap or 99, fit, max(1, frames // 15)))

def cmd_render(a, guard=None):
    import numpy as np, multiprocessing as mpc, imageio_ffmpeg
    z = np.load(a.npz); n = int(z["frames"]); char_file = a.char_file or str(z["char_file"])
    err = verify_mapping(char_file, a.npz)
    log("joint mapping check: max body position difference Newton vs MuJoCo = %.6f m (%s)" % (err, "OK" if err < 0.01 else "WARNING: mapping looks wrong"))
    budget = a.budget_mb or (guard.budget if guard else RAM_FRACTION * free_ram_mb())
    workers = plan_workers(budget, n, a.workers)
    if budget < WORKER_EST_MB + BASE_EST_MB:
        log("ABORTED: only %.0f MB RAM budget; rendering needs about %d MB." % (budget, WORKER_EST_MB)); sys.exit(EXIT_RAM)
    log("rendering %d frames at %dx%d with %d worker(s) (RAM budget %.0f MB, ~%d MB each)" % (n, a.width, a.height, workers, budget, WORKER_EST_MB))
    tmp = tempfile.mkdtemp(prefix="mk_preview_"); t0 = time.time()
    try:
        bounds = [round(i * n / workers) for i in range(workers + 1)]
        jobs = [(char_file, a.npz, bounds[i], bounds[i + 1], os.path.join(tmp, "part%03d.mp4" % i), a.width, a.height)
                for i in range(workers) if bounds[i + 1] > bounds[i]]
        ctx = mpc.get_context("spawn")
        with ctx.Pool(len(jobs)) as pool:
            if guard: guard.children = list(getattr(pool, "_pool", []))
            res = pool.map_async(_render_chunk, jobs)
            while not res.ready():
                res.wait(0.5)
                if guard and guard.tripped: pool.terminate(); ram_abort(guard)
            done = sum(res.get())
        lst = os.path.join(tmp, "list.txt")
        open(lst, "w").write("".join("file '%s'\n" % j[4].replace("\\", "/") for j in jobs))
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                        "-c", "copy", "-movflags", "+faststart", a.out], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    log("rendered %d frames in %.1f s -> %s" % (done, time.time() - t0, a.out))

# ---------------------------------------------------------------- orchestration
def gpu_free_mb():
    if os.environ.get("MIMICKIT_PREVIEW_GPU_FREE_MB"):      # tests: simulate a busy GPU
        return float(os.environ["MIMICKIT_PREVIEW_GPU_FREE_MB"])
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=10, creationflags=0x08000000 if os.name == "nt" else 0).stdout
        return float(out.split()[0])
    except Exception:
        return None

def _record_proc(a, device, guard, slow_check):
    cmd = [sys.executable, "-u", os.path.abspath(__file__), "record", "--mk", a.mk, "--device", device, "--out", a.npz_path]
    if slow_check: cmd.append("--slow_check")
    if a.save_init_model: cmd += ["--save_init_model", a.save_init_model]
    if a.frames: cmd += ["--frames", str(a.frames)]
    cmd += ["--"] + a.mk_args
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    if device == "cpu": env["CUDA_VISIBLE_DEVICES"] = ""        # zero GPU memory: CUDA is invisible to this process
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", env=env,
                         creationflags=0x08000000 if os.name == "nt" else 0)
    guard.children = [p]
    for line in p.stdout:
        if "load on device" in line or line.startswith("Module "): continue    # warp kernel-cache chatter
        sys.stdout.write(line); sys.stdout.flush()
    p.wait(); guard.children = []
    if guard.tripped: ram_abort(guard)
    return p.returncode

def cmd_all(a):
    free = free_ram_mb(); budget = RAM_FRACTION * free
    log("free RAM %.0f MB -> budget %.0f MB (80%%); preview device: %s" % (free, budget, a.device))
    if budget < RECORD_EST_MB * 0.5:
        log("ABORTED: not enough free RAM for a preview (budget %.0f MB, needs about %d MB). Close other programs and try again."
            % (budget, RECORD_EST_MB)); sys.exit(EXIT_RAM)
    if budget < RECORD_EST_MB: log("warning: tight RAM budget (%.0f MB); the preview may be aborted" % budget)
    guard = RamGuard(budget)
    out_dir = os.path.dirname(os.path.abspath(a.out)); os.makedirs(out_dir, exist_ok=True)
    a.npz_path = os.path.splitext(os.path.abspath(a.out))[0] + ".npz"
    t0 = time.time(); rc = None
    if a.device in ("auto", "cpu"):
        log("recording on the CPU (GPU memory use: none)")
        rc = _record_proc(a, "cpu", guard, slow_check=(a.device == "auto"))
        if rc != 0 and a.device == "cpu":
            log("CPU recording failed (exit code %s)." % rc); sys.exit(rc or 1)
        if rc != 0: log("CPU recording %s - falling back to the GPU" % ("too slow" if rc == 4 else "failed (exit code %s)" % rc))
    if rc != 0:
        free_v = gpu_free_mb()
        if free_v is None:
            log("No NVIDIA GPU found (nvidia-smi) - cannot record on the GPU."); sys.exit(5)
        if free_v < MIN_GPU_FREE_MB:
            log("REFUSED: only %.0f MB of GPU memory free (need about %d MB). Training keeps running; try again later or use 'CPU only'."
                % (free_v, MIN_GPU_FREE_MB)); sys.exit(5)
        log("recording on cuda:0 (%.0f MB VRAM free)" % free_v)
        rc = _record_proc(a, "cuda:0", guard, slow_check=False)
        if rc != 0: log("GPU recording failed (exit code %s)." % rc); sys.exit(rc or 1)
    a.npz = a.npz_path; a.char_file = a.char_file or ""
    cmd_render(a, guard)
    guard.stop()
    log("done in %.1f s (peak RAM of the preview processes %.0f MB of %.0f MB budget)" % (time.time() - t0, guard.peak, budget))
    if not a.keep_npz:
        try: os.remove(a.npz_path)
        except OSError: pass
    if not a.no_open and not os.environ.get("MIMICKIT_PREVIEW_NO_OPEN"):
        try:
            if os.name == "nt": os.startfile(a.out)
            elif sys.platform == "darwin": subprocess.Popen(["open", a.out])
            else: subprocess.Popen(["xdg-open", a.out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log("opened", a.out)
        except Exception as e:
            log("could not open the video player (%s); the file is at %s" % (e, a.out))
    log("PREVIEW_DONE", a.out)

def setup_gl():
    """MuJoCo's offscreen renderer: on Linux try EGL, then OSMesa, then GLFW (needs a display). Windows uses its default."""
    if os.name == "nt" or sys.platform == "darwin" or os.environ.get("MUJOCO_GL"): return
    for gl in ("egl", "osmesa", "glfw"):
        r = subprocess.run([sys.executable, "-c", "import mujoco;m=mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom size=\".1\"/>"
                            "</worldbody></mujoco>');mujoco.Renderer(m,16,16).render()"], env=dict(os.environ, MUJOCO_GL=gl),
                           capture_output=True, timeout=120)
        if r.returncode == 0:
            os.environ["MUJOCO_GL"] = gl; log("MuJoCo offscreen rendering via", gl); return
    log("warning: no working OpenGL backend found for MuJoCo (tried egl, osmesa, glfw)")

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mk_args = []
    if "--" in argv: i = argv.index("--"); mk_args = argv[i + 1:]; argv = argv[:i]
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("cmd", choices=["all", "record", "render"])
    p.add_argument("--mk", default="."); p.add_argument("--device", default="auto")
    p.add_argument("--out", default="preview.mp4"); p.add_argument("--npz", default="")
    p.add_argument("--char_file", default=""); p.add_argument("--frames", type=int, default=0)
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument("--width", type=int, default=640); p.add_argument("--height", type=int, default=480)
    p.add_argument("--workers", type=int, default=0); p.add_argument("--budget_mb", type=float, default=0)
    p.add_argument("--slow_check", action="store_true"); p.add_argument("--save_init_model", default="")
    p.add_argument("--keep_npz", action="store_true"); p.add_argument("--no_open", action="store_true")
    a = p.parse_args(argv); a.mk_args = mk_args
    if a.cmd == "record": cmd_record(a)
    elif a.cmd == "render": setup_gl(); cmd_render(a)
    else: setup_gl(); cmd_all(a)

if __name__ == "__main__":
    main()
