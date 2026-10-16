"""MimicKit Launcher - preview MP4 renderer (part of MimicKit Launcher, Copyright (c) 2026 curelessSky, SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0).

Runs in MimicKit's own Python environment, in a separate (detached) process so it can never take down a training run.
  all    : record (CPU first, GPU fallback per --device) -> render with plain MuJoCo on the CPU -> open the MP4
  record : MimicKit build_env/build_agent, 1 env, deterministic actions, logs the joint state per frame to an .npz
  render : MuJoCo (CPU) renders the .npz with a tracking camera, frame chunks in parallel, streamed to H.264 MP4
RAM: the budget is 80% of the free RAM at launch; workers/buffers are sized to it and the process tree's RSS is
monitored - the job aborts cleanly (exit code 3) if it approaches the budget.
"""

import os, sys


# CPU recording: hide CUDA before torch/warp can be imported. "-1" (an invalid ordinal) hides every GPU on Windows and
# Linux; an EMPTY value is ignored on Windows.
def _argv_get(k):
    return sys.argv[sys.argv.index(k) + 1] if k in sys.argv[:-1] else None


if (
    len(sys.argv) > 1
    and sys.argv[1] == "record"
    and (
        _argv_get("--variant") == "cpu-hidden"
        or (_argv_get("--variant") is None and _argv_get("--device") == "cpu")
    )
):
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    os.environ.setdefault(
        "PYTORCH_JIT", "0"
    )  # TorchScript compile with CUDA hidden crashed (0xC0000005) on Windows
import faulthandler

faulthandler.enable()  # a native crash prints the Python stack (pinpoints the line)
import argparse, json, socket, math, shutil, subprocess, tempfile, threading, time

import mimickit_util as U
from mimickit_util import log_exc

FPS_DEFAULT = 30
RAM_FRACTION = 0.80  # budget = 80% of free RAM at launch
ABORT_AT = 0.92  # abort when the process tree uses 92% of the budget
RECORD_EST_MB = 900  # torch + warp + newton recording 1 env on the CPU (measured peak ~700 MB)
WORKER_EST_MB = 320  # one MuJoCo renderer + ffmpeg encoder at 640x480 (measured ~300 MB)
BASE_EST_MB = 150  # this orchestrating process
MIN_GPU_FREE_MB = 600  # refuse the GPU path below this much free VRAM
SLOW_FACTOR = 20.0  # Auto: fall back to the GPU if CPU recording would take > 20x the clip length
EXIT_RAM = 3


def log(*a):
    print("[preview]", *a, flush=True)


# ---------------------------------------------------------------- memory
def free_ram_mb():
    if os.environ.get("MIMICKIT_PREVIEW_FREE_MB"):  # tests: simulate a low-memory machine
        return float(os.environ["MIMICKIT_PREVIEW_FREE_MB"])
    try:
        import psutil

        return psutil.virtual_memory().available / 2**20
    except ImportError:
        pass
    if os.name == "nt":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullAvailPhys / 2**20
    try:
        for l in open("/proc/meminfo"):
            if l.startswith("MemAvailable:"):
                return int(l.split()[1]) / 1024
    except OSError:
        pass
    return 4096.0


def tree_rss_mb(pid):
    """RSS of a process and all its children in MB (psutil, else /proc on Linux; None if unknown)."""
    try:
        import psutil

        p = psutil.Process(pid)
        tot = 0
        for q in [p] + p.children(recursive=True):
            try:
                tot += q.memory_info().rss
            except psutil.Error:
                pass
        return tot / 2**20
    except ImportError:
        pass
    except Exception:
        return None
    if not os.path.isdir("/proc"):
        return None
    kids = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                st = open("/proc/%s/stat" % d).read()
                ppid = int(st[st.rindex(")") + 2 :].split()[1])
                kids.setdefault(ppid, []).append(int(d))
            except (OSError, ValueError):
                pass
    tot, todo = 0, [pid]
    while todo:
        q = todo.pop()
        todo += kids.get(q, [])
        try:
            for l in open("/proc/%d/status" % q):
                if l.startswith("VmRSS:"):
                    tot += int(l.split()[1]) * 1024
        except OSError:
            pass
    return tot / 2**20


class RamGuard:
    """Watches the RSS of this process tree; on reaching ABORT_AT x budget it kills the children and flags an abort."""

    def __init__(self, budget_mb):
        self.budget, self.peak, self.tripped, self.children = budget_mb, 0.0, None, []
        self._stop = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self._stop:
            r = tree_rss_mb(os.getpid())
            if r is not None:
                self.peak = max(self.peak, r)
                if r > ABORT_AT * self.budget and not self.tripped:
                    self.tripped = r
                    for c in list(self.children):
                        try:
                            c.kill()
                        except Exception as e:
                            log_exc("mimickit_preview: _loop", e)
            time.sleep(0.25)

    def stop(self):
        self._stop = True


def ram_abort(guard):
    log(
        "ABORTED: RAM use reached %.0f MB, close to the budget of %.0f MB (80%% of the RAM that was free at launch)."
        % (guard.tripped, guard.budget)
    )
    log(
        "Nothing else was affected. Close other programs (or wait until less RAM is in use) and try again."
    )
    sys.exit(EXIT_RAM)


# ---------------------------------------------------------------- record (inside MimicKit)
def install_cpu_guard(wp):
    """CPU path: any Warp kernel launched on a CUDA device aborts with a clear message instead of a cryptic error."""
    import warp._src.context as ctx

    orig = wp.launch

    def guarded(kernel, *args, **kw):
        dev = kw.get("device")
        d = wp.get_device(dev) if dev is not None else wp.get_device()
        if getattr(d, "is_cuda", False):
            raise RuntimeError(
                "[preview] CPU path: Warp kernel '%s' was launched on %s - it must stay on the CPU. Use Preview "
                "device 'GPU' or report this." % (getattr(kernel, "key", kernel), d)
            )
        for v in list(kw.get("inputs", []) or []) + list(
            args[1] if len(args) > 1 and isinstance(args[1], (list, tuple)) else []
        ):
            if getattr(getattr(v, "device", None), "is_cuda", False):
                raise RuntimeError(
                    "[preview] CPU path: a Warp array for kernel '%s' is on %s."
                    % (getattr(kernel, "key", kernel), v.device)
                )
        return orig(kernel, *args, **kw)

    wp.launch = guarded
    ctx.launch = guarded
    return guarded


def ckpt(name):
    print("[preview] CKPT %s  (t=%.1f s)" % (name, time.time() - _T0), flush=True)


_T0 = time.time()


def _maybe_simulated_crash(variant, where):
    """Tests: MIMICKIT_PREVIEW_SIMULATE_CRASH=<variant>[:<where>] makes that stage die with a real native crash."""
    v = os.environ.get("MIMICKIT_PREVIEW_SIMULATE_CRASH", "")
    if v and v.split(":")[0] == variant and (v.split(":")[1] if ":" in v else "build_env") == where:
        import ctypes

        ckpt("simulated native crash")
        ctypes.string_at(0)


def _view_ids_times(env):
    """View (motion playback) envs: env k plays motion k % count at time_buf * time_scale."""
    import torch

    return env._get_env_motion_ids(), env._time_buf * getattr(env, "_time_scale", 1.0)


def _ref_joint_q(env, jtypes, jstart, nq, e=0, view=False):
    """Reference pose of the motion the policy is tracking (same motion id, same time), in Newton's joint_q layout."""
    import torch

    lib = env._motion_lib
    if view:
        ids, ts = _view_ids_times(env)
        mids, t = ids[e : e + 1], ts[e : e + 1]
    else:
        mids = env._motion_ids[e : e + 1]
        t = env._get_motion_times()[e : e + 1]
    rp, rr, _, _, jr, _ = lib.calc_motion_frame(mids, t)
    kin = env._kin_char_model
    dof = kin.rot_to_dof(jr)[0]
    q = torch.zeros(nq)
    bp = kin.forward_kinematics(rp, rr, jr)[0][0]
    for j, (tname, s) in enumerate(zip(jtypes, jstart)):
        if tname == "FREE":
            q[s : s + 3] = rp[0]
            q[s + 3 : s + 7] = rr[0]
        elif tname == "BALL":
            q[s : s + 4] = jr[0, j - 1]
        elif tname in ("REVOLUTE", "PRISMATIC"):
            q[s] = dof[kin.get_joint_dof_idx(j)]
    return q.cpu().numpy(), bp.detach().cpu().numpy(), float(t[0])


BUILD_CKPTS = [  # (module, attribute path) wrapped with CKPT enter/leave lines; missing ones are skipped
    ("envs.env_builder", "build_env"),
    ("engines.engine_builder", "build_engine"),
    ("envs.deepmimic_env", "DeepMimicEnv.__init__"),
    ("envs.char_env", "CharEnv.__init__"),
    ("envs.sim_env", "SimEnv.__init__"),
    ("envs.sim_env", "SimEnv._build_engine"),
    ("envs.sim_env", "SimEnv._build_envs"),
    ("engines.newton_engine", "NewtonEngine.__init__"),
    ("engines.newton_engine", "NewtonEngine.initialize_sim"),
    ("engines.newton_engine", "NewtonEngine._build_solver"),
    ("newton", "ModelBuilder.finalize"),
    ("anim.motion_lib", "MotionLib.__init__"),
    ("anim.kin_char_model", "KinCharModel.load_char_file"),
]


def install_build_ckpts():
    """Finer checkpoints inside build_env (a native crash then names the step), plus a note on every CUDA query torch
    gets while the GPU is supposed to be unused (torch.cuda.is_available / device_count / pin_memory).
    """
    import importlib, functools

    done = []

    def wrap(owner, attr, label):
        fn = getattr(owner, attr)
        if getattr(fn, "_mk_ckpt", False):
            return

        @functools.wraps(fn)
        def w(*a, **k):
            ckpt("> " + label)
            out = fn(*a, **k)
            ckpt("< " + label)
            return out

        w._mk_ckpt = True
        setattr(owner, attr, w)
        done.append(label)

    for mod, path in BUILD_CKPTS:
        try:
            if mod not in sys.modules:
                ckpt("import " + mod)
            m = importlib.import_module(mod)
            owner = m
            parts = path.split(".")
            for pp in parts[:-1]:
                owner = getattr(owner, pp)
            if hasattr(owner, parts[-1]):
                wrap(owner, parts[-1], "%s.%s" % (mod.split(".")[-1], path))
        except Exception as e:
            ckpt("(no checkpoint for %s.%s: %s)" % (mod, path, type(e).__name__))
    try:
        import torch

        for owner, attr in (
            (torch.cuda, "is_available"),
            (torch.cuda, "device_count"),
            (torch.Tensor, "pin_memory"),
        ):
            wrap(owner, attr, "torch.%s" % attr)
    except Exception as e:
        log_exc("mimickit_preview: install_build_ckpts", e)
    return done


def cmd_record(a):
    mk = os.path.abspath(a.mk)
    os.chdir(mk)
    sys.path.insert(0, os.path.join(mk, "mimickit"))
    cpu = a.device == "cpu"
    hidden = a.variant == "cpu-hidden"
    ckpt(
        "record start: variant %s, PYTORCH_JIT=%s, CUDA_VISIBLE_DEVICES=%r"
        % (a.variant, os.environ.get("PYTORCH_JIT"), os.environ.get("CUDA_VISIBLE_DEVICES"))
    )
    # Warp init must mirror MimicKit's training process: newton_engine.py sets wp.config.enable_backward = False BEFORE
    # importing newton, and Warp copies that option into every kernel module when the module is created. Importing newton
    # earlier built Newton's modules WITH backward kernels -> different cache key, fresh
    # compile of adjoint/tile kernels -> "device kernel image is invalid" on sm_61. So: same config, newton imported only
    # by MimicKit itself, and a separate kernel cache so the preview can never touch the training cache.
    import warp as wp

    wp.config.enable_backward = False
    if a.warp_cache:
        os.makedirs(a.warp_cache, exist_ok=True)
        wp.config.kernel_cache_dir = a.warp_cache
    ckpt("import torch")
    import numpy as np, torch

    torch.set_num_threads(os.cpu_count() or 1)
    ckpt("wp.init")
    wp.init()
    if cpu:
        wp.set_device("cpu")
        if hidden and (torch.cuda.is_available() or any(d.is_cuda for d in wp.get_devices())):
            log(
                "ABORTED: CPU mode but CUDA is still visible (CUDA_VISIBLE_DEVICES=%r)."
                % os.environ.get("CUDA_VISIBLE_DEVICES")
            )
            sys.exit(6)
        install_cpu_guard(wp)
    log(
        "warp %s: default device %s, enable_backward %s, kernel cache %s; torch threads %d; CUDA_VISIBLE_DEVICES=%r"
        % (
            wp.config.version,
            wp.get_device(),
            wp.config.enable_backward,
            wp.config.kernel_cache_dir,
            torch.get_num_threads(),
            os.environ.get("CUDA_VISIBLE_DEVICES"),
        )
    )
    ckpt("import MimicKit run.py")
    import run as mk_run, util.mp_util as mp_util

    args = mk_run.load_args(["run.py"] + a.mk_args)
    mp_util.init(0, 1, a.device, 6000)  # like run.py's run(): logger/agent tensors use this device
    mk_run.set_rand_seed(args)
    mk_run.set_np_formatting()
    t0 = time.time()
    if cpu:
        ckpt("finer build_env checkpoints: %d hooks" % len(install_build_ckpts()))
    _maybe_simulated_crash(a.variant, "build_env")
    ckpt("build_env")
    clips = dataset_motions(mk, args.parse_string("env_config"))
    sel = pick_clips(clips, a.clips)
    if sel:
        K = min(len(sel), MAX_CLIPS)
        log("chosen clips: %s" % ", ".join(os.path.basename(clips[i]) for i in sel[:K]))
    else:
        if a.clips:
            log("chosen clips %r not found in this env's motion list - previewing the first ones" % a.clips)
        K = max(1, min(a.motions, MAX_CLIPS, len(clips))) if a.motions > 0 else 1
        sel = list(range(K))
    log(
        "motions: %d%s; previewing %d (one env per motion, each from t=0)"
        % (
            len(clips),
            " (" + ", ".join(os.path.basename(c) for c in clips[:8]) + ")" if clips else "",
            K,
        )
    )
    with wp.ScopedDevice(a.device):
        env = mk_run.build_env(args, K, a.device, False)
    ckpt("build_agent")
    agent = mk_run.build_agent(args, env, a.device)
    import newton

    bad = [
        m
        for m in ("newton._src.solvers.mujoco.kernels",)
        if wp.get_module(m).options.get("enable_backward")
    ]
    if bad:
        log("warning: Warp modules built with backward kernels:", bad)
    if cpu and str(env._engine._sim_model.device) != "cpu":
        log(
            "ABORTED: the simulation landed on %s instead of the CPU."
            % env._engine._sim_model.device
        )
        sys.exit(6)
    model_file = args.parse_string("model_file", "")
    if model_file:
        agent.load(model_file)
        log("loaded", model_file)
    else:
        log("no model file: using a freshly initialized (untrained) policy")
    if a.save_init_model:
        agent.save(a.save_init_model)
        log("saved initial model to", a.save_init_model)
    import learning.base_agent as base_agent

    agent.eval()
    agent.set_mode(base_agent.AgentMode.TEST)
    eng = env._engine
    sm = eng._sim_model
    dt = eng.get_timestep()
    fps = 1.0 / dt
    scope = wp.ScopedDevice(a.device)
    scope.__enter__()  # MimicKit launches some kernels without a device
    ckpt("env.reset")
    forced = torch.tensor(sel[:K], device=a.device, dtype=torch.long)
    if hasattr(env, "_sample_motion_times"):
        # deepmimic_env._reset_ref_motion() asks _sample_motion_times(n) for (motion ids, start times): with rand_reset
        # False it samples a random motion by weight at t=0. Override on this instance: env e plays chosen clip e from
        # t=0. Other callers (AMP's demo sampling asks for many samples at once) keep MimicKit's own sampler.
        _orig_smt = env._sample_motion_times
        env._sample_motion_times = lambda n: (
            (forced[:n].clone(), torch.zeros(n, device=a.device)) if n <= K else _orig_smt(n))
    if hasattr(env, "_get_env_motion_ids") and hasattr(env, "_sync_motion"):
        env._get_env_motion_ids = lambda: forced.clone()  # view preset: env e shows chosen clip e
    with torch.no_grad():
        obs, info = env.reset()
    lib = getattr(env, "_motion_lib", None)
    view = hasattr(env, "_sync_motion") and hasattr(env, "_get_env_motion_ids") and lib is not None
    if view:
        # View/motion-playback preset: the env poses the character from the clip AFTER the physics step, so the sim's
        # joint_q lags a frame (and isn't the clip's start pose at frame 0). Record the clip pose itself instead.
        log("view preset: recording the motion clip itself (no policy, no ghost)")
        mids = [int(v) for v in env._get_env_motion_ids()[:K]]
    else:
        mids = [int(v) for v in env._motion_ids[:K]] if hasattr(env, "_motion_ids") else [0]
    lens = (
        [float(lib.get_motion_length(torch.tensor([m], device=a.device))[0]) for m in mids]
        if lib is not None
        else [a.seconds]
    )
    names = (
        [os.path.basename(str(lib.get_motion_file(m))) for m in mids]
        if lib is not None and hasattr(lib, "get_motion_file")
        else ["clip"]
    )
    nper = [int(math.ceil(L_ * fps)) for L_ in lens]
    if a.frames:
        nper = [min(v, a.frames) for v in nper]
    n = max(nper)
    clip_len = max(lens)
    setup = time.time() - t0
    for k in range(K):
        log(
            "clip %d: motion id %d %s, %.2f s -> %d frames"
            % (k + 1, mids[k], names[k], lens[k], nper[k])
        )
    log("setup %.1f s on %s; %d clip(s), %d steps at %.0f fps" % (setup, a.device, K, n, fps))
    art = sm.articulation_start.numpy()
    j0, j1 = int(art[0]), int(art[1])
    jqs = sm.joint_q_start.numpy()
    jt = sm.joint_type.numpy()
    jl = getattr(sm, "joint_label", None) or getattr(sm, "joint_key", None) or []
    bl = getattr(sm, "body_label", None) or getattr(sm, "body_key", None) or []
    jnames = [os.path.basename(str(x)) for x in list(jl)[j0:j1]]
    jtypes = [newton.JointType(int(t)).name for t in jt[j0:j1]]
    q0, q1 = int(jqs[j0]), int(jqs[j1])
    jstart = [int(jqs[j]) - q0 for j in range(j0, j1)]
    nb = j1 - j0
    bnames = [os.path.basename(str(x)) for x in list(bl)[j0:j1]]
    Q = np.zeros((n, K, q1 - q0), np.float32)
    BP = np.zeros((n, K, nb, 3), np.float32)
    has_ref = not view and all(
        hasattr(env, k)
        for k in ("_motion_lib", "_motion_ids", "_get_motion_times", "_kin_char_model")
    )
    RQ = np.zeros_like(Q)
    RBP = np.zeros_like(BP)
    RT = np.zeros((n, K), np.float32)
    if not has_ref and not view:
        log("this env has no reference motion - no ghost")
    off = getattr(env, "_ref_char_offset", None)
    ref_off = [float(v) for v in off.cpu().numpy()] if off is not None else [2.0, 0.0, 0.0]
    ckpt("stepping")
    t1 = time.time()
    last = t1
    with torch.no_grad():
        for i in range(n):
            act, _ = agent._decide_action(obs, info)
            obs, r, done, info = env.step(
                act
            )  # 'done' is ignored on purpose: one continuous take of each clip
            jq = eng._sim_state._torch_joint_q.view(K, -1)
            bq = eng._sim_state._torch_body_q.view(K, -1, 7)
            Q[i] = jq[:, q0:q1].detach().cpu().numpy()
            BP[i] = bq[:, j0:j1, :3].detach().cpu().numpy()
            if view:
                for k in range(K):
                    Q[i, k], BP[i, k], _ = _ref_joint_q(env, jtypes, jstart, q1 - q0, k, view=True)
            if has_ref:
                for k in range(K):
                    RQ[i, k], RBP[i, k], RT[i, k] = _ref_joint_q(env, jtypes, jstart, q1 - q0, k)
            now = time.time()
            if i == 9:
                t10 = now
            if i == 29 and a.slow_check:
                proj = (now - t10) / 20 * n
                if proj > SLOW_FACTOR * clip_len:
                    log(
                        "CPU too slow: %.1f s projected for a %.1f s clip (limit %.0fx)"
                        % (proj, clip_len, SLOW_FACTOR)
                    )
                    sys.exit(4)
            if now - last > 2 or i == n - 1:
                el = now - t1
                log(
                    "record frame %d/%d  (%.1f frames/s = %.2fx real time, %d clip(s) at once)"
                    % (i + 1, n, (i + 1) / el, (i + 1) / el / fps, K)
                )
                last = now
    el = time.time() - t1
    np.savez(
        a.out,
        joint_q=Q,
        body_pos=BP,
        joint_names=np.array(jnames),
        joint_types=np.array(jtypes),
        joint_start=np.array(jstart),
        body_names=np.array(bnames),
        fps=fps,
        clip_len=clip_len,
        motion_id=mids[0],
        frames=n,
        clips=K,
        motion_ids=np.array(mids),
        clip_names=np.array(names),
        clip_lens=np.array(lens, np.float32),
        clip_frames=np.array(nper),
        char_file=_char_file(mk, args.parse_string("env_config")),
        record_seconds=el,
        setup_seconds=setup,
        device=a.device,
        variant=a.variant,
        has_ref=has_ref,
        view=view,
        ref_joint_q=RQ,
        ref_body_pos=RBP,
        ref_time=RT,
        ref_offset=np.array(ref_off, np.float32),
    )
    log(
        "recorded %d steps x %d clip(s) in %.1f s (%.1fx real time; setup %.1f s) -> %s"
        % (n, K, el, n / fps / el, setup, a.out)
    )


def pick_clips(clips, spec):
    """--clips 'walk_v1,run_v1' (file names, with or without .pkl, or 0-based numbers) -> motion ids, in that order."""
    out = []
    for t in [x.strip() for x in (spec or "").split(",") if x.strip()]:
        if t.isdigit() and int(t) < len(clips):
            i = int(t)
        else:
            names = [os.path.splitext(os.path.basename(c))[0] for c in clips]
            t0 = os.path.splitext(os.path.basename(t))[0]
            i = names.index(t0) if t0 in names else next((j for j, n in enumerate(names) if n.endswith(t0)), -1)
        if i >= 0 and i not in out:
            out.append(i)
    return out


def dataset_motions(mk, env_yaml):
    """Motion files of the env (a .pkl, or a dataset .yaml listing several), in the motion library's id order."""
    import yaml

    try:
        cfg = yaml.safe_load(open(os.path.join(mk, env_yaml))) or {}
        mf = cfg.get("motion_file", "")
        if not mf:
            return []
        if mf.endswith(".yaml"):
            return [
                m["file"]
                for m in (yaml.safe_load(open(os.path.join(mk, mf))) or {}).get("motions", [])
            ]
        return [mf]
    except Exception:
        return []


def _char_file(mk, env_yaml):
    import yaml

    cfg = yaml.safe_load(open(os.path.join(mk, env_yaml))) or {}
    return os.path.join(mk, cfg.get("char_file", "")) if cfg.get("char_file") else ""


# ---------------------------------------------------------------- render (plain MuJoCo, CPU)
GHOST_RGBA = (1.0, 0.55, 0.15, 0.35)  # translucent orange reference
GHOST_MODES = ("off", "side", "overlay")


def _load_mj(char_file, ghost=False):
    import mujoco

    spec = mujoco.MjSpec.from_file(char_file)
    if ghost:  # second copy of the character, prefixed "ghost_", purely visual
        child = mujoco.MjSpec.from_file(char_file)
        frame = spec.worldbody.add_frame()
        frame.attach_body(child.worldbody.first_body(), "ghost_", "")
    tex = spec.add_texture()
    tex.name = "lk_grid"
    tex.type = mujoco.mjtTexture.mjTEXTURE_2D
    tex.builtin = mujoco.mjtBuiltin.mjBUILTIN_CHECKER
    tex.rgb1 = [0.22, 0.24, 0.27]
    tex.rgb2 = [0.30, 0.32, 0.36]
    tex.width = tex.height = 512
    mat = spec.add_material()
    mat.name = "lk_floor"
    mat.texrepeat = [10, 10]
    mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = "lk_grid"
    g = spec.worldbody.add_geom()
    g.name = "lk_floor"
    g.type = mujoco.mjtGeom.mjGEOM_PLANE
    g.size = [60, 60, 0.1]
    g.material = "lk_floor"
    g.contype = 0
    g.conaffinity = 0
    for pos, dirn in (([0, 0, 6], [0, 0, -1]), ([4, -4, 5], [-0.5, 0.5, -0.7])):
        l = spec.worldbody.add_light()
        l.pos = pos
        l.dir = dirn
        l.diffuse = [0.6, 0.6, 0.6]
        l.castshadow = True
    spec.visual.headlight.ambient = [0.35, 0.35, 0.35]
    m = spec.compile()
    if ghost:
        for gi in range(m.ngeom):
            bn = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, int(m.geom_bodyid[gi])) or ""
            if bn.startswith("ghost_"):
                m.geom_rgba[gi] = GHOST_RGBA
                m.geom_contype[gi] = 0
                m.geom_conaffinity[gi] = 0
    return m


def _char_joints(m, ghost=False):
    import mujoco

    return [
        k
        for k in range(m.njnt)
        if (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, k) or "").startswith("ghost_") == ghost
    ]


def qpos_map(m, z, ghost=False):
    """Index plan Newton joint_q -> MuJoCo qpos, walking both in MJCF order.
    Newton quaternions are (x, y, z, w), MuJoCo's are (w, x, y, z). MimicKit/Newton merge the 2-3 hinge joints of one body
    into a single BALL joint (a quaternion); MuJoCo keeps the separate hinges, so those are solved back into hinge angles.
    """
    import mujoco

    types, starts = [str(x) for x in z["joint_types"]], [int(x) for x in z["joint_start"]]
    J = _char_joints(m, ghost)
    nj = len(J)
    plan, i = [], 0
    for t, s in zip(types, starts):
        if t == "FIXED":
            continue
        if i >= nj:
            raise ValueError("Newton has more joints than the MJCF")
        k = J[i]
        jt = int(m.jnt_type[k])
        adr = int(m.jnt_qposadr[k])
        if t == "FREE":
            assert jt == mujoco.mjtJoint.mjJNT_FREE, "root joint mismatch"
            plan.append(("free", s, adr))
            i += 1
        elif t == "BALL" and jt == mujoco.mjtJoint.mjJNT_BALL:
            plan.append(("ball", s, adr))
            i += 1
        elif t == "BALL":  # merged hinges of one body
            body = int(m.jnt_bodyid[k])
            adrs, axes = [], []
            while (
                i < nj
                and int(m.jnt_bodyid[J[i]]) == body
                and int(m.jnt_type[J[i]]) == mujoco.mjtJoint.mjJNT_HINGE
            ):
                adrs.append(int(m.jnt_qposadr[J[i]]))
                axes.append(m.jnt_axis[J[i]].copy())
                i += 1
            plan.append(("hinges", s, adrs, axes))
        else:
            plan.append(("scalar", s, adr))
            i += 1
    return plan


def _qmat(w, x, y, zz):
    import numpy as np

    return np.array(
        [
            [1 - 2 * (y * y + zz * zz), 2 * (x * y - zz * w), 2 * (x * zz + y * w)],
            [2 * (x * y + zz * w), 1 - 2 * (x * x + zz * zz), 2 * (y * zz - x * w)],
            [2 * (x * zz - y * w), 2 * (y * zz + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _axis_rot(ax, t):
    import numpy as np

    ax = ax / np.linalg.norm(ax)
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    return np.eye(3) + np.sin(t) * K + (1 - np.cos(t)) * K @ K


def _solve_hinges(R, axes, t0):
    """Angles t with R = Rot(a1,t1) Rot(a2,t2) ... (hinges of one body compose in MJCF order); Gauss-Newton from t0."""
    import numpy as np

    t = np.array(t0, float)

    def f(t):
        M = np.eye(3)
        for a, ti in zip(axes, t):
            M = M @ _axis_rot(a, ti)
        return (M - R).ravel()

    for _ in range(30):
        r = f(t)
        J = np.empty((9, len(t)))
        h = 1e-6
        for i in range(len(t)):
            d = np.zeros(len(t))
            d[i] = h
            J[:, i] = (f(t + d) - r) / h
        step = np.linalg.lstsq(J, -r, rcond=None)[0]
        t += step
        if np.abs(step).max() < 1e-10:
            break
    return t


def apply_q(plan, q, qpos, prev=None):
    """prev: dict carrying the last hinge solution per joint (keeps angles continuous between frames)."""
    prev = {} if prev is None else prev
    for e in plan:
        kind, s = e[0], e[1]
        if kind == "free":
            adr = e[2]
            qpos[adr : adr + 3] = q[s : s + 3]
            x, y, zz, w = q[s + 3 : s + 7]
            qpos[adr + 3 : adr + 7] = (w, x, y, zz)
        elif kind == "ball":
            adr = e[2]
            x, y, zz, w = q[s : s + 4]
            qpos[adr : adr + 4] = (w, x, y, zz)
        elif kind == "hinges":
            x, y, zz, w = q[s : s + 4]
            n = (x * x + y * y + zz * zz + w * w) ** 0.5
            t = _solve_hinges(
                _qmat(w / n, x / n, y / n, zz / n), e[3], prev.get(s, [0.0] * len(e[2]))
            )
            prev[s] = t
            for adr, ti in zip(e[2], t):
                qpos[adr] = ti
        else:
            qpos[e[2]] = q[s]


def clip_data(z):
    """Arrays with a clip axis: Q/BP/RQ/RBP are (steps, clips, ...); older single-clip files get a clip axis of 1."""
    import numpy as np

    Q, BP = z["joint_q"], z["body_pos"]
    RQ = z["ref_joint_q"] if "ref_joint_q" in z.files else np.zeros_like(Q)
    RBP = z["ref_body_pos"] if "ref_body_pos" in z.files else np.zeros_like(BP)
    if Q.ndim == 2:
        Q, BP, RQ, RBP = Q[:, None], BP[:, None], RQ[:, None], RBP[:, None]
    K = Q.shape[1]
    n = Q.shape[0]
    nper = [int(v) for v in z["clip_frames"]] if "clip_frames" in z.files else [n] * K
    names = [str(v) for v in z["clip_names"]] if "clip_names" in z.files else ["clip"] * K
    return dict(Q=Q, BP=BP, RQ=RQ, RBP=RBP, K=K, n=n, nper=nper, names=names)


LAYOUTS = ("grid", "seq")
MAX_CLIPS = 4


def frame_specs(c, layout):
    """Per output frame: list of (clip, step) panels. grid: all clips at once, shorter ones hold their last frame;
    seq: clips one after another."""
    if c["K"] == 1 or layout == "grid":
        return [
            [(k, min(i, c["nper"][k] - 1)) for k in range(c["K"])] for i in range(max(c["nper"]))
        ]
    return [[(k, i)] for k in range(c["K"]) for i in range(c["nper"][k])]


def grid_shape(K):
    return (1, 1) if K == 1 else (1, 2) if K == 2 else (2, 2)


def verify_mapping(char_file, npz, ref=False, per_clip=False):
    """Max distance between Newton's body positions (ref=True: the reference motion's forward kinematics) and MuJoCo's
    forward kinematics of the mapped qpos, over every clip's own frames. per_clip=True returns a list per clip.
    """
    import numpy as np, mujoco

    z = np.load(npz)
    m = mujoco.MjModel.from_xml_path(char_file)
    d = mujoco.MjData(m)
    plan = qpos_map(m, z)
    c = clip_data(z)
    Q, BP = (c["RQ"], c["RBP"]) if ref else (c["Q"], c["BP"])
    ids = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, str(bn)) for bn in z["body_names"]]
    errs = []
    for k in range(c["K"]):
        err, prev = 0.0, {}
        for i in range(c["nper"][k]):
            apply_q(plan, Q[i, k].astype(float), d.qpos, prev)
            mujoco.mj_kinematics(m, d)
            for bi, b in enumerate(ids):
                if b >= 0:
                    err = max(err, float(np.linalg.norm(d.xpos[b] - BP[i, k, bi])))
        errs.append(err)
    return errs if per_clip else max(errs)


def ghost_offset(z, mode):
    """World offset of the ghost root: side by side uses the env's ref_char_offset (default 2 m sideways), overlay none."""
    import numpy as np

    if mode != "side":
        return np.zeros(3)
    o = np.array(z["ref_offset"], float) if "ref_offset" in z.files else np.array([2.0, 0, 0])
    o[2] = 0.0
    if np.linalg.norm(o[:2]) < 0.5:
        o = np.array([2.0, 0, 0])
    return o


def _legend(img):
    from PIL import Image, ImageDraw, ImageFont

    im = Image.fromarray(img)
    dr = ImageDraw.Draw(im, "RGBA")
    try:
        f = ImageFont.load_default(size=16)
    except TypeError:
        f = ImageFont.load_default()
    dr.rectangle([8, 8, 128, 56], fill=(0, 0, 0, 120))
    dr.rectangle([14, 15, 28, 29], fill=(205, 205, 205, 255))
    dr.text((34, 13), "Policy", fill=(255, 255, 255), font=f)
    g = tuple(int(c * 255) for c in GHOST_RGBA[:3])
    dr.rectangle([14, 35, 28, 49], fill=g + (255,))
    dr.text((34, 33), "Reference", fill=(255, 255, 255), font=f)
    import numpy as np

    return np.asarray(im)


def _label(img, text, legend=False):
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np

    im = Image.fromarray(img)
    dr = ImageDraw.Draw(im, "RGBA")
    try:
        f = ImageFont.load_default(size=16)
    except TypeError:
        f = ImageFont.load_default()
    if text:
        w = int(dr.textlength(text, font=f)) if hasattr(dr, "textlength") else 8 * len(text)
        x = (im.width - w) // 2
        y = im.height - 30
        dr.rectangle([x - 8, y - 4, x + w + 8, y + 22], fill=(0, 0, 0, 140))
        dr.text((x, y), text, fill=(255, 255, 255), font=f)
    out = np.asarray(im)
    return _legend(out) if legend else out


def _render_chunk(job):
    char_file, npz, lo, hi, part, w, h = job[:7]
    mode = job[7] if len(job) > 7 else "off"
    layout = job[8] if len(job) > 8 else "grid"
    import numpy as np, mujoco, imageio.v2 as imageio

    z = np.load(npz)
    ghost = mode != "off" and bool(z["has_ref"]) if "has_ref" in z.files else False
    c = clip_data(z)
    specs = frame_specs(c, layout)
    K = c["K"]
    m = _load_mj(char_file, ghost)
    d = mujoco.MjData(m)
    plan = qpos_map(m, z)
    gplan = qpos_map(m, z, ghost=True) if ghost else None
    off = ghost_offset(z, mode) if ghost else None
    r = mujoco.Renderer(m, h, w)

    def make_cam():
        cam = mujoco.MjvCamera()
        cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
        cam.trackbodyid = 1
        cam.distance, cam.azimuth, cam.elevation = 3.6, 120.0, -12.0
        if (
            ghost and mode == "side"
        ):  # free camera looking perpendicular to the offset, framing both characters
            cam.type = mujoco.mjtCamera.mjCAMERA_FREE
            cam.azimuth = float(np.degrees(np.arctan2(off[1], off[0]))) + 90.0
            cam.distance = 3.6 + 0.9 * float(np.linalg.norm(off))
            cam.elevation = -10.0
        return cam

    cams = [make_cam() for _ in range(K)]  # one camera per clip/panel
    prev = [{} for _ in range(K)]
    gprev = [{} for _ in range(K)]
    rows, cols = grid_shape(K) if layout == "grid" else (1, 1)
    wr = imageio.get_writer(
        part,
        fps=float(z["fps"]),
        codec="libx264",
        quality=8,
        macro_block_size=8,
        pixelformat="yuv420p",
        ffmpeg_log_level="error",
    )
    for f in range(lo, hi):
        panels = []
        for k, i in specs[f]:
            apply_q(plan, c["Q"][i, k].astype(float), d.qpos, prev[k])
            if ghost:
                rq = c["RQ"][i, k].astype(float).copy()
                rq[0:3] += off  # root is the FREE joint at q[0:3]
                apply_q(gplan, rq, d.qpos, gprev[k])
            mujoco.mj_forward(m, d)
            cam = cams[k]
            if ghost and mode == "side":
                mid = 0.5 * (c["Q"][i, k][:3] + rq[:3])
                cam.lookat[:] = (mid[0], mid[1], 0.85)
            r.update_scene(d, camera=cam)
            img = r.render()
            txt = (
                c["names"][k]
                if K > 1 and layout == "grid"
                else ("clip %d/%d: %s" % (k + 1, K, c["names"][k]) if K > 1 else "")
            )
            panels.append(_label(img, txt, legend=ghost and (len(panels) == 0)))
        if len(panels) > 1:
            blank = np.zeros_like(panels[0])
            panels += [blank] * (rows * cols - len(panels))
            frame = np.concatenate(
                [np.concatenate(panels[r_ * cols : (r_ + 1) * cols], axis=1) for r_ in range(rows)],
                axis=0,
            )
        else:
            frame = panels[0]
        wr.append_data(frame)  # streamed: no frame list kept in RAM
    wr.close()
    r.close()
    return hi - lo


def plan_workers(budget_mb, frames, cap=0, cpus=None):
    """Parallel render workers: one per core, at least ~15 frames each, and only as many as fit in the RAM budget."""
    cpus = cpus or os.cpu_count() or 1
    fit = int((budget_mb - BASE_EST_MB) // WORKER_EST_MB)
    return max(1, min(cpus, cap or 99, fit, max(1, frames // 15)))


def cmd_render(a, guard=None):
    import numpy as np, multiprocessing as mpc, imageio_ffmpeg

    z = np.load(a.npz)
    char_file = a.char_file or str(z["char_file"])
    layout = getattr(a, "layout", "grid") or "grid"
    c = clip_data(z)
    n = len(frame_specs(c, layout))
    err = verify_mapping(char_file, a.npz)
    log(
        "joint mapping check: max body position difference Newton vs MuJoCo = %.6f m (%s)"
        % (err, "OK" if err < 0.01 else "WARNING: mapping looks wrong")
    )
    mode = getattr(a, "ghost", "off") or "off"
    if mode != "off" and not ("has_ref" in z.files and bool(z["has_ref"])):
        if not ("view" in z.files and bool(z["view"])):
            log("reference ghost: not available for this env")
        mode = "off"
    if mode != "off":
        gerrs = verify_mapping(char_file, a.npz, ref=True, per_clip=True)
        gerr = max(gerrs)
        mids = (
            [int(v) for v in z["motion_ids"]] if "motion_ids" in z.files else [int(z["motion_id"])]
        )
        log(
            "reference ghost: %s, per clip (motion id: pose check) %s (%s)"
            % (
                {"side": "side by side", "overlay": "overlay"}[mode],
                ", ".join("%d: %.6f m" % (mi, e) for mi, e in zip(mids, gerrs)),
                "OK" if gerr < 0.01 else "WARNING",
            )
        )
    if c["K"] > 1:
        rows, cols = grid_shape(c["K"])
        log(
            "clip layout: %s - %d clips (%s), %d frames%s"
            % (
                "all at once" if layout == "grid" else "one after another",
                c["K"],
                ", ".join(c["names"]),
                n,
                (
                    ", %dx%d grid of %dx%d panels" % (rows, cols, a.width, a.height)
                    if layout == "grid"
                    else ""
                ),
            )
        )
    budget = a.budget_mb or (guard.budget if guard else RAM_FRACTION * free_ram_mb())
    workers = plan_workers(budget, n, a.workers)
    if budget < WORKER_EST_MB + BASE_EST_MB:
        log(
            "ABORTED: only %.0f MB RAM budget; rendering needs about %d MB."
            % (budget, WORKER_EST_MB)
        )
        sys.exit(EXIT_RAM)
    log(
        "rendering %d frames at %dx%d with %d worker(s) (RAM budget %.0f MB, ~%d MB each)"
        % (n, a.width, a.height, workers, budget, WORKER_EST_MB)
    )
    tmp = tempfile.mkdtemp(prefix="mk_preview_")
    t0 = time.time()
    try:
        bounds = [round(i * n / workers) for i in range(workers + 1)]
        jobs = [
            (
                char_file,
                a.npz,
                bounds[i],
                bounds[i + 1],
                os.path.join(tmp, "part%03d.mp4" % i),
                a.width,
                a.height,
                mode,
                layout,
            )
            for i in range(workers)
            if bounds[i + 1] > bounds[i]
        ]
        ctx = mpc.get_context("spawn")
        with ctx.Pool(len(jobs)) as pool:
            if guard:
                guard.children = list(getattr(pool, "_pool", []))
            res = pool.map_async(_render_chunk, jobs)
            while not res.ready():
                res.wait(0.5)
                if guard and guard.tripped:
                    pool.terminate()
                    ram_abort(guard)
            done = sum(res.get())
        lst = os.path.join(tmp, "list.txt")
        open(lst, "w").write("".join("file '%s'\n" % j[4].replace("\\", "/") for j in jobs))
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                lst,
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                a.out,
            ],
            check=True,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    log("rendered %d frames in %.1f s -> %s" % (done, time.time() - t0, a.out))


# ---------------------------------------------------------------- orchestration
def gpu_free_mb():
    if os.environ.get("MIMICKIT_PREVIEW_GPU_FREE_MB"):  # tests: simulate a busy GPU
        return float(os.environ["MIMICKIT_PREVIEW_GPU_FREE_MB"])
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=0x08000000 if os.name == "nt" else 0,
        ).stdout
        return float(out.split()[0])
    except Exception:
        return None


VRAM_CAP_MB = 300  # stage b: the CPU process may hold a small CUDA context, never more
VARIANTS = {
    "cpu-hidden": ("cpu", "CPU, GPU hidden (CUDA_VISIBLE_DEVICES=-1, PYTORCH_JIT=0)"),
    "cpu-visible": (
        "cpu",
        "CPU, GPU visible but unused (forced cpu device + guard, PYTORCH_JIT=0, VRAM cap %d MB)"
        % VRAM_CAP_MB,
    ),
    "gpu": ("cuda:0", "GPU cuda:0, 1 env"),
}
NATIVE_CRASH_CODES = (0xC0000005, 0xC0000409, 0xC000001D)


def is_native_crash(rc):
    return rc is not None and (rc < 0 or (rc & 0xFFFFFFFF) in NATIVE_CRASH_CODES)


def _is_windows():
    return os.name == "nt" or os.environ.get("MIMICKIT_PREVIEW_ASSUME_WINDOWS") == "1"


def _state_path(a):
    return os.path.join(os.path.abspath(a.mk), "output", "_launcher_preview", "preview_state.json")


def load_state(a):
    try:
        return U.load_json(_state_path(a)).get(socket.gethostname(), {})
    except FileNotFoundError:
        return {}
    except Exception as e:
        log_exc("reading preview_state.json", e)
        return {}


def save_state(a, upd):
    p = _state_path(a)
    allst = U.load_json_or(p, {}, "reading preview_state.json")
    if not isinstance(allst, dict):
        allst = {}
    allst.setdefault(socket.gethostname(), {}).update(upd)
    try:
        U.save_json(p, allst)
    except OSError as e:
        log_exc("saving preview_state.json", e)


def stages_for(device):
    return {"cpu": ["cpu-hidden", "cpu-visible"], "gpu": ["gpu"]}.get(
        device, ["cpu-hidden", "cpu-visible", "gpu"]
    )


def _smi(args):
    out = subprocess.run(
        ["nvidia-smi"] + args,
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=0x08000000 if os.name == "nt" else 0,
    ).stdout
    return [l.strip() for l in out.splitlines() if l.strip()]


def proc_vram_mb(pid, baseline=None):
    """(MB, method) used by pid on the GPU. Windows WDDM often reports per-process memory as [N/A]: then the growth of total
    used memory since launch is used instead (an upper bound - training holding steady)."""
    if os.environ.get("MIMICKIT_PREVIEW_FAKE_VRAM_MB"):
        return float(os.environ["MIMICKIT_PREVIEW_FAKE_VRAM_MB"]), "test"
    try:
        for l in _smi(["--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"]):
            p, mem = [x.strip() for x in l.split(",")[:2]]
            if p == str(pid) and mem.replace(".", "").isdigit():
                return float(mem), "per-process"
        if baseline is not None:
            return (
                max(
                    0.0,
                    float(_smi(["--query-gpu=memory.used", "--format=csv,noheader,nounits"])[0])
                    - baseline,
                ),
                "total-delta",
            )
    except Exception as e:
        log_exc("mimickit_preview: proc_vram_mb", e)
    return 0.0, "unavailable"


def gpu_used_mb():
    try:
        return float(_smi(["--query-gpu=memory.used", "--format=csv,noheader,nounits"])[0])
    except Exception:
        return None


def variant_env(variant, base=None):
    env = dict(
        base if base is not None else os.environ, PYTHONUNBUFFERED="1", PYTHONFAULTHANDLER="1"
    )
    env.pop("CUDA_VISIBLE_DEVICES", None)  # GPU / visible: same CUDA view as training
    if variant == "cpu-hidden":
        env["CUDA_VISIBLE_DEVICES"] = "-1"  # zero GPU memory ("" is ignored on Windows)
    if variant.startswith("cpu"):
        env["PYTORCH_JIT"] = "0"
    return env


def _record_proc(a, device, guard, slow_check, variant=None):
    variant = variant or ("gpu" if device != "cpu" else "cpu-hidden")
    cmd = [
        sys.executable,
        "-u",
        os.path.abspath(__file__),
        "record",
        "--mk",
        a.mk,
        "--device",
        device,
        "--variant",
        variant,
        "--out",
        a.npz_path,
    ]
    if slow_check:
        cmd.append("--slow_check")
    if a.save_init_model:
        cmd += ["--save_init_model", a.save_init_model]
    if a.frames:
        cmd += ["--frames", str(a.frames)]
    cmd += ["--motions", str(getattr(a, "motions", 4))]
    cmd += ["--"] + a.mk_args
    env = variant_env(variant)
    cmd[cmd.index("--out") : cmd.index("--out")] = ["--warp_cache", a.warp_cache]
    base = gpu_used_mb() if variant == "cpu-visible" else None
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        env=env,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    guard.children = [p]
    vram = {"over": None, "peak": 0.0, "method": ""}
    if variant == "cpu-visible":
        import threading

        def watch():
            while p.poll() is None:
                mb, how = proc_vram_mb(p.pid, base)
                vram["method"] = how
                vram["peak"] = max(vram["peak"], mb)
                if mb > VRAM_CAP_MB:
                    vram["over"] = mb
                    p.kill()
                    return
                time.sleep(1.0)

        threading.Thread(target=watch, daemon=True).start()
    for line in p.stdout:
        if "load on device" in line or line.startswith("Module "):
            continue  # warp kernel-cache chatter
        sys.stdout.write(line)
        sys.stdout.flush()
    p.wait()
    guard.children = []
    if guard.tripped:
        ram_abort(guard)
    if variant == "cpu-visible":
        log(
            "stage cpu-visible GPU memory: peak %.0f MB (%s)"
            % (vram["peak"], vram["method"] or "unavailable")
        )
        a._visible_peak = vram["peak"]
    if vram["over"] is not None:
        log(
            "ABORTED stage cpu-visible: it used %.0f MB of GPU memory (cap %d MB)"
            % (vram["over"], VRAM_CAP_MB)
        )
        return 7
    return p.returncode


def cmd_all(a):
    free = free_ram_mb()
    budget = RAM_FRACTION * free
    log("free RAM %.0f MB -> budget %.0f MB (80%%); preview device: %s" % (free, budget, a.device))
    if budget < RECORD_EST_MB * 0.5:
        log(
            "ABORTED: not enough free RAM for a preview (budget %.0f MB, needs about %d MB). Close other programs and try again."
            % (budget, RECORD_EST_MB)
        )
        sys.exit(EXIT_RAM)
    if budget < RECORD_EST_MB:
        log("warning: tight RAM budget (%.0f MB); the preview may be aborted" % budget)
    guard = RamGuard(budget)
    out_dir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)
    a.npz_path = os.path.splitext(os.path.abspath(a.out))[0] + ".npz"
    a.warp_cache = a.warp_cache or os.path.join(
        os.path.abspath(a.mk), "output", "_launcher_preview", "warp_cache"
    )
    log("own Warp kernel cache (the training cache is never written): %s" % a.warp_cache)
    t0 = time.time()
    rc = None
    stages = stages_for(a.device)
    i = 0
    hidden_crash = None
    st = load_state(a)
    if (
        _is_windows()
        and st.get("skip_cpu_hidden")
        and "cpu-hidden" in stages
        and not os.environ.get("MIMICKIT_PREVIEW_RETRY_HIDDEN")
    ):
        stages.remove("cpu-hidden")
        log(
            "using cpu-visible on this PC: cpu-hidden (GPU fully hidden) stopped working here on %s, while cpu-visible works with a "
            "tiny GPU footprint (~%s MB, no training impact). Preview diagnostics re-checks both."
            % (st.get("since", "?"), st.get("visible_mb", "<300"))
        )
    log("staged recording plan: " + " -> ".join(stages))
    while i < len(stages):
        v = stages[i]
        dev, desc = VARIANTS[v]
        if v == "gpu":
            free_v = gpu_free_mb()
            if free_v is None:
                log("No NVIDIA GPU found (nvidia-smi) - cannot record on the GPU.")
                sys.exit(5)
            if free_v < MIN_GPU_FREE_MB:
                log(
                    "REFUSED: only %.0f MB of GPU memory free (need about %d MB). Training keeps running; try again later or use 'CPU only'."
                    % (free_v, MIN_GPU_FREE_MB)
                )
                sys.exit(5)
            desc += " (%.0f MB VRAM free)" % free_v
        log("PREVIEW VARIANT %s: %s - fresh process" % (v, desc))
        log(
            "recording on the CPU (GPU memory use: %s)"
            % ("none" if v == "cpu-hidden" else "at most %d MB" % VRAM_CAP_MB)
            if dev == "cpu"
            else "recording on cuda:0"
        )
        rc = _record_proc(
            a, dev, guard, slow_check=(a.device == "auto" and dev == "cpu"), variant=v
        )
        if rc == 0:
            log("recorded with variant %s" % v)
            if v == "cpu-visible" and hidden_crash is not None and _is_windows():
                save_state(
                    a,
                    dict(
                        skip_cpu_hidden=True,
                        since=time.strftime("%Y-%m-%d"),
                        hidden_exit=hidden_crash,
                        visible_mb=round(getattr(a, "_visible_peak", 0) or 0),
                    ),
                )
                log("noted for this PC: next previews go straight to cpu-visible")
            break
        if v == "cpu-hidden" and is_native_crash(rc):
            hidden_crash = rc & 0xFFFFFFFF if rc > 0 else rc
            i += 1
            log(
                "cpu-hidden is not usable on this PC (exit code %s%s) - switching to cpu-visible, which is the normal path on some "
                "Windows setups." % (rc, ", 0x%08X" % (rc & 0xFFFFFFFF) if abs(rc) > 255 else "")
            )
            continue
        if rc == EXIT_RAM:
            sys.exit(rc)
        why = (
            "too slow"
            if rc == 4
            else "crashed/failed (exit code %s%s)"
            % (rc, ", 0x%08X" % (rc & 0xFFFFFFFF) if rc and abs(rc) > 255 else "")
        )
        i += 1
        if rc == 4:
            i = stages.index("gpu") if "gpu" in stages else len(stages)
        if i < len(stages):
            log("variant %s %s - trying %s" % (v, why, stages[i]))
        else:
            log("variant %s %s - no stages left." % (v, why))
            sys.exit(rc if rc and 0 < rc < 256 else 1)
    a.npz = a.npz_path
    a.char_file = a.char_file or ""
    cmd_render(a, guard)
    guard.stop()
    log(
        "done in %.1f s (peak RAM of the preview processes %.0f MB of %.0f MB budget)"
        % (time.time() - t0, guard.peak, budget)
    )
    if not a.keep_npz:
        try:
            os.remove(a.npz_path)
        except OSError:
            pass
    if not a.no_open and not os.environ.get("MIMICKIT_PREVIEW_NO_OPEN"):
        try:
            if os.name == "nt":
                os.startfile(a.out)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", a.out])
            else:
                subprocess.Popen(
                    ["xdg-open", a.out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            log("opened", a.out)
        except Exception as e:
            log("could not open the video player (%s); the file is at %s" % (e, a.out))
    log("PREVIEW_DONE", a.out)


# ---------------------------------------------------------------- diagnostics (P1-P7)
_PRE = (
    "import os, sys, time, faulthandler; faulthandler.enable(); sys.path.insert(0, 'mimickit')\n"
    "def ck(n): print('CKPT', n, flush=True)\n"
)


def diag_probes(env_yaml):
    env_mod = ""
    try:
        import yaml

        env_mod = (yaml.safe_load(open(env_yaml)) or {}).get("env_name", "")
    except Exception as e:
        log_exc("mimickit_preview: diag_probes", e)
    return [
        (
            "P1",
            "versions and devices",
            "visible",
            "ck('python'); print(sys.version); import platform; print(platform.platform())\n"
            "ck('torch'); import torch; print('torch', torch.__version__, 'cuda build', torch.version.cuda, 'available', torch.cuda.is_available())\n"
            "ck('warp'); import warp as wp; wp.init(); print('warp', wp.config.version, [str(d) for d in wp.get_devices()])\n"
            "ck('mujoco'); import mujoco; print('mujoco', mujoco.__version__)",
        ),
        (
            "P2",
            "torch import with GPU hidden",
            "hidden",
            "ck('import torch'); import torch; ck('cuda.is_available'); print('available', torch.cuda.is_available()); "
            "ck('cpu tensor'); print(torch.ones(3).sum())",
        ),
        (
            "P3",
            "torch.jit.script with GPU hidden (JIT on - the suspected crash)",
            "hidden-jit",
            "import torch, warnings\n@torch.jit.script\ndef f(x: torch.Tensor) -> torch.Tensor:\n    return x * 2 + 1\n"
            "ck('jit call'); print(f(torch.ones(4)))\nck('jit call 2'); print(f(torch.ones(4)))",
        ),
        (
            "P4",
            "Warp CPU kernel compile + launch with GPU hidden",
            "hidden",
            "import warp as wp; wp.config.enable_backward = False; ck('wp.init'); wp.init(); wp.set_device('cpu')\n"
            "@wp.kernel\ndef k(a: wp.array(dtype=float)):\n    a[wp.tid()] = 2.0 * float(wp.tid())\n"
            "a = wp.zeros(8, dtype=float, device='cpu'); ck('compile+launch'); wp.launch(k, dim=8, inputs=[a], device='cpu'); "
            "wp.synchronize(); print(a.numpy()); print('cache', wp.config.kernel_cache_dir)",
        ),
        (
            "P5",
            "import MimicKit env module + mujoco in one process (GPU hidden)",
            "hidden",
            (
                "import warp as wp; wp.config.enable_backward = False; ck('import mujoco'); import mujoco\n"
                "ck('import torch'); import torch; ck('import envs.%s'); import importlib; importlib.import_module('envs.%s')\n"
                "ck('import newton'); import newton; print('ok')"
                % (env_mod + "_env", env_mod + "_env")
                if env_mod
                else "ck('import mujoco'); import mujoco; ck('import envs.env_builder'); import envs.env_builder; print('ok')"
            ),
        ),
        ("P6", "build_env with 1 env on the CPU (GPU hidden)", "build", None),
        ("P7", "short recording per CPU variant (30 frames)", "record", None),
    ]


def cmd_diag(a):
    mk = os.path.abspath(a.mk)
    out_dir = os.path.join(mk, "output", "_launcher_preview")
    os.makedirs(out_dir, exist_ok=True)
    rep_path = os.path.join(out_dir, "preview_diagnostics.txt")
    a.warp_cache = a.warp_cache or os.path.join(out_dir, "warp_cache")
    lines = []

    def out(*x):
        t = " ".join(str(v) for v in x)
        lines.append(t)
        log(t)

    out(
        "Preview diagnostics %s  (python %s, %s)"
        % (time.strftime("%Y-%m-%d %H:%M:%S"), sys.version.split()[0], sys.platform)
    )
    env_yaml = ""
    if "--env_config" in a.mk_args:
        env_yaml = os.path.join(mk, a.mk_args[a.mk_args.index("--env_config") + 1])
    results = {}
    for pid, title, kind, code in diag_probes(env_yaml):
        if a.probes and pid not in a.probes.split(","):
            continue
        out("---- %s %s" % (pid, title))
        t0 = time.time()
        if kind == "record":
            res = []
            for v in ("cpu-hidden", "cpu-visible"):
                a2 = argparse.Namespace(**vars(a))
                a2.frames = a.frames or 30
                a2.save_init_model = ""
                a2.npz_path = os.path.join(out_dir, "diag_%s.npz" % v)
                guard = RamGuard(RAM_FRACTION * free_ram_mb())
                rc = _record_proc(a2, "cpu", guard, slow_check=False, variant=v)
                guard.stop()
                res.append("%s=%s" % (v, "PASS" if rc == 0 else "FAIL(%s)" % rc))
                try:
                    os.remove(a2.npz_path)
                except OSError:
                    pass
            results[pid] = " ".join(res)
            out("%s result: %s  (%.1f s)" % (pid, results[pid], time.time() - t0))
            continue
        if kind == "build":
            code = (
                "import warp as wp; wp.config.enable_backward = False; wp.config.kernel_cache_dir = %r\n"
                "ck('import torch'); import torch; ck('wp.init'); wp.init(); wp.set_device('cpu')\n"
                "ck('import run'); import run, util.mp_util as mp; args = run.load_args(['run.py'] + %r); mp.init(0, 1, 'cpu', 6000)\n"
                "ck('build_env')\nwith wp.ScopedDevice('cpu'): env = run.build_env(args, 1, 'cpu', False)\n"
                "ck('build_agent'); agent = run.build_agent(args, env, 'cpu'); ck('reset'); env.reset(); print('sim on', env._engine._sim_model.device)"
                % (a.warp_cache, list(a.mk_args))
            )
        env = variant_env("cpu-hidden")
        if kind == "visible":
            env = variant_env("gpu")
        if kind == "hidden-jit":
            env["PYTORCH_JIT"] = "1"
        try:
            pr = subprocess.run(
                [sys.executable, "-u", "-X", "faulthandler", "-c", _PRE + code],
                cwd=mk,
                env=env,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=a.timeout,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            rc, txt = pr.returncode, (pr.stdout + pr.stderr)
        except subprocess.TimeoutExpired as e:
            rc, txt = "timeout", str(e.stdout or "")
        keep = [
            l
            for l in txt.splitlines()
            if l.strip() and "load on device" not in l and not l.startswith("Module ")
        ]
        for l in keep[-25:]:
            out("   " + l)
        last = [l for l in keep if l.startswith("CKPT")]
        verdict = (
            "PASS"
            if rc == 0
            else "CRASH/FAIL rc=%s%s%s"
            % (
                rc,
                " (0x%08X)" % (rc & 0xFFFFFFFF) if isinstance(rc, int) and abs(rc) > 255 else "",
                ", last checkpoint: " + last[-1][5:] if last else "",
            )
        )
        results[pid] = verdict
        out("%s result: %s  (%.1f s)" % (pid, verdict, time.time() - t0))
    out("---- summary")
    for k, v in results.items():
        out("%s: %s" % (k, v))
    open(rep_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    log("DIAGNOSTICS_DONE", rep_path)


def setup_gl():
    """MuJoCo's offscreen renderer: on Linux try EGL, then OSMesa, then GLFW (needs a display). Windows uses its default."""
    if os.name == "nt" or sys.platform == "darwin" or os.environ.get("MUJOCO_GL"):
        return
    for gl in ("egl", "osmesa", "glfw"):
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                'import mujoco;m=mujoco.MjModel.from_xml_string(\'<mujoco><worldbody><geom size=".1"/>'
                "</worldbody></mujoco>');mujoco.Renderer(m,16,16).render()",
            ],
            env=dict(os.environ, MUJOCO_GL=gl),
            capture_output=True,
            timeout=120,
        )
        if r.returncode == 0:
            os.environ["MUJOCO_GL"] = gl
            log("MuJoCo offscreen rendering via", gl)
            return
    log("warning: no working OpenGL backend found for MuJoCo (tried egl, osmesa, glfw)")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mk_args = []
    if "--" in argv:
        i = argv.index("--")
        mk_args = argv[i + 1 :]
        argv = argv[:i]
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("cmd", choices=["all", "record", "render", "diag"])
    p.add_argument("--variant", default="")
    p.add_argument("--ghost", default="overlay", choices=GHOST_MODES)
    p.add_argument("--layout", default="grid", choices=LAYOUTS)
    p.add_argument("--motions", type=int, default=4)
    p.add_argument("--clips", default="", help="comma list of clip names (or ids) to preview, max 4")
    p.add_argument("--mk", default=".")
    p.add_argument("--device", default="auto")
    p.add_argument("--out", default="preview.mp4")
    p.add_argument("--npz", default="")
    p.add_argument("--char_file", default="")
    p.add_argument("--frames", type=int, default=0)
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--budget_mb", type=float, default=0)
    p.add_argument("--slow_check", action="store_true")
    p.add_argument("--save_init_model", default="")
    p.add_argument("--warp_cache", default="")
    p.add_argument("--probes", default="")
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--keep_npz", action="store_true")
    p.add_argument("--no_open", action="store_true")
    a = p.parse_args(argv)
    a.mk_args = mk_args
    if a.cmd == "record":
        a.variant = a.variant or ("cpu-hidden" if a.device == "cpu" else "gpu")
        cmd_record(a)
    elif a.cmd == "diag":
        cmd_diag(a)
    elif a.cmd == "render":
        setup_gl()
        cmd_render(a)
    else:
        setup_gl()
        cmd_all(a)


if __name__ == "__main__":
    main()
