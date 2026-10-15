"""MimicKit Launcher - a small desktop GUI for running MimicKit (https://github.com/xbpeng/MimicKit).

Unofficial and unaffiliated with MimicKit. Vibe coded; see README.md.
Copyright (c) 2026 curelessSky, licensed under GPL-3.0-or-later.
Run with any Python 3.9+ that has tkinter and matplotlib:  python mimickit_launcher.py
"""

# the one version string: window title, banner, About box, zip names (tools/build.py)
VERSION = "a0.6.0"
import codecs, json, math, os, queue, shlex, shutil, signal, subprocess, sys, threading, time, datetime, glob, re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import matplotlib

matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mimickit_remote as R
import mimickit_util as U
from mimickit_util import log_exc
import mimickit_trainsettings as TS

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the launcher folder (mkl/..)


def _config_path():
    base = (
        os.environ.get("APPDATA")
        if os.name == "nt"
        else os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    )
    return os.path.join(base or HERE, "mimickit-launcher", "settings.json")


CONFIG = os.environ.get("MIMICKIT_LAUNCHER_CONFIG") or _config_path()
IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW: no black console windows
NEWTON = ["--engine_config", "data/engines/newton_engine.yaml"]

# ---------------------------------------------------------------- args discovery
TRAIN_PREFIXES = ("deepmimic", "amp", "ase", "add", "lcp", "smp", "vault", "awr", "ppo")


def read_args_file(path):
    """MimicKit args files: '--key value ...' tokens, '#' comments. Returns dict key -> list of values."""
    toks = []
    try:
        for line in open(path, errors="replace"):
            line = line.split("#", 1)[0].strip()
            if line:
                toks += line.split()
    except OSError:
        return {}
    out, key = {}, None
    for t in toks:
        if t.startswith("--"):
            key = t[2:]
            out.setdefault(key, [])
        elif key:
            out[key].append(t)
    return out


def motion_of(mk, env_rel):
    try:
        for line in open(os.path.join(mk, env_rel), errors="replace"):
            m = re.match(r'\s*motion_file:\s*"?([^"#\n]+)"?', line)
            if m:
                return m.group(1).strip()
    except (OSError, TypeError):
        pass
    return ""


def discover(mk):
    """Scan <mk>/args/*.txt -> (train configs, view configs); each a dict(name, file, info...)."""
    train, view = [], []
    for f in sorted(glob.glob(os.path.join(mk, "args", "*.txt"))):
        a = read_args_file(f)
        name = os.path.basename(f)[: -len(".txt")]
        if name.endswith("_args"):
            name = name[:-5]
        env = (a.get("env_config") or [""])[0]
        item = dict(
            name=name,
            file=os.path.relpath(f, mk).replace(os.sep, "/"),
            env=env,
            engine=(a.get("engine_config") or [""])[0],
            num_envs=int((a.get("num_envs") or ["0"])[0] or 0),
            out=(a.get("out_dir") or [""])[0],
            motion=motion_of(mk, env),
        )
        is_view = (a.get("mode") or [""])[0] == "test" and "agent_config" not in a
        if is_view or "view" in name:
            view.append(item)
        elif "agent_config" in a or name.split("_")[0] in TRAIN_PREFIXES:
            train.append(item)
        else:
            view.append(item)
    return train, view


def default_out(item):
    o = (item.get("out") or "").rstrip("/\\")
    return o if o and o not in ("output", "output/") else "output/" + item["name"]


def detect_python(mk):
    exe = ("Scripts", "python.exe") if IS_WIN else ("bin", "python")
    for v in (
        os.path.join(mk, ".venv"),
        os.path.join(mk, "venv"),
        os.path.join(os.path.dirname(mk), "venv"),
        os.path.join(os.path.dirname(mk), ".venv"),
    ):
        p = os.path.join(v, *exe)
        if os.path.exists(p):
            return v
    return ""


GHOST_MODES = {"Off": "off", "Side by side": "side", "Overlay": "overlay"}
CLIP_LAYOUTS = {"All at once": "grid", "One after another": "seq"}

HELP = {
    "perstep": "Avg reward per step = Return / episode length, in % (each step's reward is 0..1 in DeepMimic-style tasks, so\n"
    "100% = perfect tracking every step). Unlike Return it doesn't grow just because episodes get longer.\n"
    "Needs Train/Test_Episode_Length in the console: Settings -> MimicKit patches... -> logging patch\n"
    "(without it the value is read from log.txt, which MimicKit writes less often).",
    "patches": "Small optional changes to your MimicKit install, applied and reverted by the launcher (a backup of the original\n"
    "file is kept as <file>.launcher_orig). They affect runs started afterwards.",
    "tsettings": "Edit the selected training config: episode length, starts, early termination, clip end hold, learning and\n"
    "number of envs. Saves an edited COPY (the originals are backed up and never changed); it applies on the next\n"
    "Start / Resume / Continue / Watch / Preview of this config. A run already going keeps its settings.",
    "remote": "Optional, off by default. Phone dashboard: a small read-only web page (status, charts, VRAM, newest preview\n"
    "video, a rate-limited 'Render preview' button) served by the launcher, protected by a random token.\n"
    "Use it over Tailscale (docs/REMOTE_ACCESS.md) - never forward the port on your router.\n"
    "Notifications: Discord webhook and/or Telegram bot post a chart + status every N hours (and new previews).",
    "trainsel": "Training configs found in MimicKit's args folder (files with an --agent_config).",
    "viewsel": "View configs: files with '--mode test' and no agent (they only play a motion clip).",
    "custom": "Add any args .txt file (for example your own character). It is remembered.",
    "newton": "Adds --engine_config data/engines/newton_engine.yaml. Isaac Gym does not run on Windows,\n"
    "so keep this on unless you set up Isaac Gym / Isaac Lab yourself.",
    "extra": "Extra command-line options added to the end, e.g.  --max_samples 50000000  or  --rand_seed 1.\n"
    "Later options override the args file.",
    "model": "Optional .pt file for 'Watch'. Empty = newest model.pt in the output folder (or its _resume folders).",
    "view": "View clip: runs the selected View config - plays the reference motion (no AI, no training).\n"
    "A window opens; close it (or press Stop) when done.",
    "train": "Start training: starts a NEW training run that writes into the output folder.\n"
    "Runs with no window (fast). Watch the graph and log here. Can take hours.",
    "resume": "Resume training: continues from the newest saved model.pt.\n"
    "The old model is copied into a new folder (..._resume1, _resume2, ...) so nothing gets overwritten.",
    "watch": "Watch latest: plays the newest saved model.pt in order - one character, starting at the beginning of the clip,\n"
    "no random start and no early resets (a generated view copy of the env yaml; your data folder is not changed).",
    "continue": "Continue from another run: pick a finished or older run folder (anything with model.pt in it or its _resumeN\n"
    "folders). Its newest model.pt becomes the start of a new training run of the CURRENT config in the current\n"
    "output folder (or its next _resumeN if that folder is already used). Training time, session count and the\n"
    "source run's chart history are carried over (shown grey with dotted links in front of the new run).",
    "preview": "Render MP4: records the newest model.pt for one clip length in a separate background process (CPU by\n"
    "default, so no GPU memory is used and training is not disturbed), renders it with MuJoCo and opens the video.\n"
    "Saved as preview_<iteration>.mp4 next to the model. Uses at most 80% of the RAM that is free when it starts.\n"
    "Press again while it runs to cancel it.",
    "target": "Progress estimate (rough!). Default 'plateau (auto)': fits a curve that levels off (y = a - b*exp(-x/c)) to\n"
    "Train_Return over all sessions of this run (smoothed, newest data weighted more, the dips right after a resume\n"
    "ignored). % = how far along the way to 95% of that fitted level; time left = remaining samples / current speed.\n"
    "It says 'not enough data yet' until the fit is stable, and can't know about later jumps in skill - treat it as\n"
    "a hint, not a promise. 'samples' target: % of a total sample count (millions). 'score' target: when the fitted\n"
    "curve reaches that Train_Return ('may not be reached' if it levels off below it). Saved per run chain.",
    "cursess": "Show only the current session on the x axis (earlier sessions stay drawn, just out of view).",
    "chartnav": "Drag with the left mouse button = move along the time axis (both charts together). Mouse wheel = zoom the\n"
    "time axis at the cursor. The vertical scale stays at the full data range; you can drag it up/down only when\n"
    "that chart has data outside its current vertical range. Home or double-click = full view, follow new data.",
    "layout": "Clip layout of the preview when the training data has several motions (the first 4 are previewed, each from\n"
    "its start). All at once = a grid (1x2 or 2x2), one camera per clip; shorter clips hold their last frame.\n"
    "One after another = the clips in sequence, each labelled.",
    "ghost": "Reference ghost in the preview MP4: the motion clip the policy is tracking (same clip, same time), drawn as a\n"
    "translucent orange character. Overlay (default) = drawn in place, on top of the policy. Side by side = next to\n"
    "the policy (offset sideways, camera frames both). Off = policy only. Applies to every clip.",
    "pdiag": "Preview diagnostics: runs probes P1-P7 (versions, torch with the GPU hidden, torch.jit, a Warp CPU kernel, MimicKit\n"
    "imports, build_env on the CPU, a 30-frame recording per CPU variant), each in its own process with crash\n"
    "tracebacks on. Report: output/_launcher_preview/preview_diagnostics.txt (also shown in the log).",
    "pdevice": "Where the preview recording runs. Auto = CPU first (GPU hidden, then GPU visible but unused if that crashes), the\n"
    "GPU only if both fail or the CPU is far too slow. Each attempt is a fresh process; the log says which one ran.\n"
    "CPU only = never touches the GPU. GPU = cuda:0, refused if less than ~600 MB of VRAM is free. Rendering is always on the CPU.",
    "stop": "Stop: kills the running MimicKit process and all its child processes (taskkill /T /F).\n"
    "Your saved progress (model.pt) is kept. (Windows: taskkill /T /F, Linux: kills the process group.)",
    "envs": "Number of practice characters (num_envs) that train at once. More = faster but more GPU memory.\n"
    "An 8 GB card fits roughly 4000-5000 with the Newton engine. Out of memory? Lower it (see README).",
    "stopsave": "Let training finish its current iteration and write your saved progress (model.pt) once more,\n"
    "then stop. Nothing since the last saved progress is lost. Press again to cancel.",
    "envs_live": "Change the number of practice characters (num_envs) while training runs: set the new number in the\n"
    "box, then press this.\n"
    "The launcher waits for the next saved progress, stops training and resumes from it with the new number\n"
    "(new _resumeN folder; time, sessions and charts carry over). Press again to cancel.",
    "out": "Folder (inside MimicKit) where log.txt and model.pt are written.",
}

# ---------------------------------------------------------------- optional profile overlay
# A personal build can drop a launcher_profile.py next to this file to add presets, tooltips and defaults
# without touching the generic code. Supported names (all optional):
#   VERSION_SUFFIX (str), HELP (dict, merged), RETURN_TEXT (str), DEFAULT_ENVS (int),
#   PREFERRED_TRAIN / PREFERRED_VIEW (list of config names), PRESETS (list of dicts:
#   name, kind "train"/"view", file, args (extra list), out, num_envs, help),
#   ACTIONS (list of dicts: text, help, run(app)) - extra buttons, see mkl/actions.py
def build_id():
    """Commit a release zip was built from (tools/build.py writes BUILD into the zip); a git checkout has none."""
    try:
        with open(os.path.join(HERE, "BUILD")) as f:
            return f.read().split()[1]
    except (OSError, IndexError):
        return "dev"


RETURN_TEXT = "Return = how well the character copies the animation (higher is better)."
DEFAULT_ENVS = 4096
PREFERRED_TRAIN = ["deepmimic_humanoid_ppo"]
PREFERRED_VIEW = ["view_motion_humanoid"]
PRESETS = []
ACTIONS = []
if os.path.exists(os.path.join(HERE, "launcher_profile.py")):
    sys.path.insert(0, HERE)
    try:
        import launcher_profile as _P
    finally:
        sys.path.remove(HERE)
    VERSION += getattr(_P, "VERSION_SUFFIX", "")
    HELP.update(getattr(_P, "HELP", {}))
    for _k in ("RETURN_TEXT", "DEFAULT_ENVS", "PREFERRED_TRAIN", "PREFERRED_VIEW", "PRESETS", "ACTIONS"):
        if hasattr(_P, _k):
            globals()[_k] = getattr(_P, _k)

THEMES = {
    "dark": dict(
        bg="#121212",
        panel="#1e1e1e",
        field="#1a1a1a",
        fg="#d0d0d0",
        dim="#8a8a8a",
        accent="#5b8db8",
        border="#333333",
        sel="#2f4f6f",
        btn="#262626",
        btn_act="#333333",
        log_bg="#0d0d0d",
        log_fg="#c8c8c8",
        tip_bg="#2a2a2a",
        tip_fg="#e0e0e0",
        stop="#7a2a2a",
        stop_act="#943434",
        stop_fg="#f0d0d0",
        good="#7fb38a",
        grid="#3a3a3a",
        line1="#6ea8d8",
        line2="#d8a05e",
        line3="#7fb38a",
        warn="#d8b35e",
        err="#e07070",
    ),
    "light": dict(
        bg="#ececec",
        panel="#f5f5f5",
        field="#ffffff",
        fg="#1a1a1a",
        dim="#666666",
        accent="#2f6ea3",
        border="#b0b0b0",
        sel="#b8d4ee",
        btn="#e0e0e0",
        btn_act="#d0d0d0",
        log_bg="#111111",
        log_fg="#dddddd",
        tip_bg="#ffffe0",
        tip_fg="#000000",
        stop="#c94a4a",
        stop_act="#b03a3a",
        stop_fg="#ffffff",
        good="#14532d",
        grid="#cccccc",
        line1="tab:blue",
        line2="tab:orange",
        line3="tab:green",
        warn="#9a6200",
        err="#b02a2a",
    ),
}
T = dict(THEMES["dark"])  # current colours (updated in place)

from mkl.dialogs import DarkMessageBox, new_popup, place_popup, tip_position

messagebox = DarkMessageBox(T)  # dark popups; same API as tkinter.messagebox
# dashboard bind address -> what the user picks
BIND_LABEL = {
    "127.0.0.1": "This PC only",
    "0.0.0.0": "My phone and other devices (Tailscale recommended)",
}


def default_settings():
    return dict(mimickit="", venv="", light_mode=False, force_newton=True)


def load_settings(problems=None):
    """Settings from CONFIG over the defaults. A damaged file is NOT silently replaced: it is reported in
    `problems` (list) as dict(error, backup=(path, datetime) or None) and the defaults are returned.
    """
    s = default_settings()
    try:
        data = U.load_json(CONFIG)
        if not isinstance(data, dict):
            raise U.JsonDamaged("settings file does not hold an object")
        s.update(data)
    except FileNotFoundError:
        pass  # first start
    except (U.JsonDamaged, OSError) as e:
        log_exc("loading settings", e)
        if problems is not None:
            problems.append(dict(error=str(e), backup=U.backup_info(CONFIG)))
    return migrate_settings(s)


def migrate_settings(s):
    """Older settings: a dashboard that was set up before the bind choice existed listened on all interfaces -
    keep that explicitly (new installs default to this PC only)."""
    r = s.get("remote")
    if isinstance(r, dict) and "host" not in r and (r.get("enabled") or r.get("token")):
        r["host"] = "0.0.0.0"
    return s


def resolve_damaged_settings(choose, problem, path=None):
    """Ask what to do with a damaged settings file. choose(title, text, options) -> value.
    Returns the settings to use. The damaged file is kept as <file>.damaged-<time> either way."""
    path = path or CONFIG
    b = problem.get("backup")
    if b:
        text = "Your settings file was damaged. Restore the backup from %s?" % b[1].strftime(
            "%Y-%m-%d %H:%M"
        )
        opts = [
            (
                "Restore",
                "restore",
                "Use the backup (your folders, presets and phone settings as they were then).",
            ),
            (
                "Start fresh",
                "fresh",
                "Default settings. The damaged file is kept next to it for reference.",
            ),
        ]
    else:
        text = "Your settings file was damaged and there is no backup to restore."
        opts = [
            (
                "Start fresh",
                "fresh",
                "Default settings. The damaged file is kept next to it for reference.",
            )
        ]
    a = choose("Settings file damaged", text, opts) or "fresh"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        if os.path.exists(path):
            os.replace(path, "%s.damaged-%s" % (path, stamp))
    except OSError as e:
        log_exc("moving the damaged settings file aside", e)
    s = default_settings()
    if a == "restore" and b:
        try:
            s.update(U.load_json(b[0]))
            shutil.copy2(b[0], path)
        except (OSError, U.JsonDamaged) as e:
            log_exc("restoring the settings backup", e)
    return migrate_settings(s)


# ---------------------------------------------------------------- log.txt parsing
def parse_table_text(txt):
    """MimicKit log.txt: whitespace-separated header names followed by numeric rows. Rows may be separated by
    '\\n', '\\r' or nothing at all (all on one line), so tokens are regrouped by header width.
    Header-only files, partial last rows and repeated headers are handled. Returns dict column -> floats.
    """
    head, data, row = [], {}, []
    in_head = False
    for t in txt.split():
        if not _isnum(t):
            if not in_head:
                head, data = [], {}
                in_head = True  # a new header block = a new run; keep the latest
            head.append(t)
            data.setdefault(t, [])
            row = []
            continue
        in_head = False
        if not head:
            continue
        row.append(float(t))
        if len(row) == len(head):
            for h, v in zip(head, row):
                data[h].append(v)
            row = []
    n = max((len(v) for v in data.values()), default=0)
    return {k: v for k, v in data.items() if v} if n else {}


def parse_log(path):
    try:
        return parse_table_text(open(path, "r", errors="replace").read())
    except OSError:
        return {}


TIME_FILE = "launcher_time.json"


def read_time(d):
    try:
        j = U.load_json(os.path.join(d, TIME_FILE))
        return j if isinstance(j.get("seconds"), (int, float)) else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError, AttributeError) as e:
        log_exc("reading the training time of " + d, e)
        return None


def write_time(d, j):
    try:
        U.save_json(os.path.join(d, TIME_FILE), j)
    except OSError as e:
        log_exc("saving the training time of " + d, e)


def chain_total(dirs):
    """Total training seconds and sessions over a run chain [original, _resume1, ...]. A folder's JSON holds the
    cumulative total (it was carried over on resume); folders without one add their log.txt Wall_Time (hours).
    """
    total, sessions = 0.0, 0
    for d in dirs:
        j = read_time(d)
        if j:
            total, sessions = float(j["seconds"]), int(j.get("sessions", sessions))
        else:
            W = [w for w in parse_log(os.path.join(d, "log.txt")).get("Wall_Time", []) if w == w]
            if W:
                total += W[-1] * 3600
                sessions += 1
    return total, sessions


LINK_FILE = "launcher_link.json"  # written when a run continues from another run folder
_RESUME_RE = re.compile(r"^(.*)_resume(\d+)$")


def chain_folders(base):
    """base folder + its _resumeN folders, as sorted (N, abs path)"""
    parent, name = os.path.split(os.path.normpath(base))
    out = [(0, base)]
    if os.path.isdir(parent):
        for d in os.listdir(parent):
            if d.startswith(name + "_resume") and d[len(name) + 7 :].isdigit():
                out.append((int(d[len(name) + 7 :]), os.path.join(parent, d)))
    return sorted(out)


def base_of(d):
    m = _RESUME_RE.match(os.path.basename(os.path.normpath(d)))
    return os.path.join(os.path.dirname(os.path.normpath(d)), m.group(1)) if m else d


def parent_of(d):
    """The run folder d continued from: the parent in launcher_time.json / launcher_link.json (may be another output folder),
    else for a _resumeN folder without JSON the previous folder of its own chain."""
    cands = []
    j = read_time(d)
    if j and j.get("parent"):
        cands.append(j["parent"])
    try:
        l = U.load_json(os.path.join(d, LINK_FILE))
        if l.get("parent"):
            cands.append(l["parent"])
    except FileNotFoundError:
        pass  # most folders have no link file
    except (OSError, ValueError, AttributeError) as e:
        log_exc("reading the run link of " + d, e)
    for c in cands:
        if os.path.isdir(c):
            return c
        alt = os.path.join(
            os.path.dirname(os.path.normpath(d)), os.path.basename(os.path.normpath(c))
        )  # MimicKit folder moved
        if os.path.isdir(alt):
            return alt
    if cands:
        return None
    m = _RESUME_RE.match(os.path.basename(os.path.normpath(d)))
    if m:
        base = base_of(d)
        for k in range(int(m.group(2)) - 1, 0, -1):
            if os.path.isdir(base + "_resume%d" % k):
                return base + "_resume%d" % k
        if os.path.isdir(base):
            return base
    return None


def run_chain(d, limit=500):
    """All run folders leading to d, oldest first, following parent links across output folders (cycle-safe)."""
    out, seen, cur = [d], {os.path.normcase(os.path.abspath(d))}, d
    while len(out) < limit:
        p = parent_of(cur)
        if not p:
            break
        n = os.path.normcase(os.path.abspath(p))
        if n in seen:
            break
        seen.add(n)
        out.insert(0, p)
        cur = p
    return out


def make_view_env(mk, env_rel, dst, episode_length=1000.0):
    """Copy of a training env yaml for chronological playback: no random start, no early termination, long episodes.
    Written to dst (a launcher folder under output/), never into MimicKit's data folder. Returns dst or None.
    """
    try:
        lines = open(os.path.join(mk, env_rel), errors="replace").read().splitlines()
    except OSError:
        return None
    over = dict(
        rand_reset="False",
        enable_early_termination="False",
        pose_termination="False",
        episode_length="%g" % episode_length,
    )
    out, seen = [
        "# generated by MimicKit Launcher %s from %s (chronological view: rand_reset/early termination off)"
        % (VERSION, env_rel)
    ], set()
    for l in lines:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", l)
        if m and m.group(1) in over:
            out.append("%s: %s" % (m.group(1), over[m.group(1)]))
            seen.add(m.group(1))
        else:
            out.append(l)
    out += ["%s: %s" % (k, v) for k, v in over.items() if k not in seen]
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "w").write("\n".join(out) + "\n")
    except OSError:
        return None
    return dst


def last_iteration(d):
    h = load_history(d) if os.path.isdir(d) else {}
    it = [x for x in h.get("Iteration", []) if x == x]
    return int(it[-1]) if it else None


HIST_FILE = "chart_history.csv"
CONSOLE_FILE = "console_log.txt"
RUN_STATE = "launcher_run.json"  # pid, command and start time of a detached MimicKit process (for reattaching)
DETACHED_FLAGS = (
    (0x00000200 | 0x08000000) if IS_WIN else 0
)  # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW (hidden console, survives the GUI)

# ---------------------------------------------------------------- detached process helpers
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]


def _win_proc(pid):
    """(alive, exit_code, image path, creation time as unix seconds) of a Windows PID; None if it can't be opened."""
    h = _k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        _k32.GetExitCodeProcess(h, ctypes.byref(code))
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        img = buf.value if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        ct = None
        if _k32.GetProcessTimes(
            h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)
        ):
            ct = ((c.dwHighDateTime << 32) | c.dwLowDateTime) / 1e7 - 11644473600
        return code.value == 259, code.value, img, ct  # 259 = STILL_ACTIVE
    finally:
        _k32.CloseHandle(h)


def proc_info(pid):
    """dict(alive, cmd, start) for a PID, or None if there is no such process. cmd/start may be '' / None if unknown."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if IS_WIN:
        w = _win_proc(pid)
        return None if w is None else dict(alive=w[0], code=w[1], cmd=w[2], start=w[3])
    if os.path.exists("/proc/%d/stat" % pid):
        try:
            stat = open("/proc/%d/stat" % pid).read()
            rest = stat[stat.rindex(")") + 2 :].split()
            cmd = (
                open("/proc/%d/cmdline" % pid, "rb")
                .read()
                .replace(b"\0", b" ")
                .decode("utf-8", "replace")
                .strip()
            )
            btime = next(float(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime"))
            return dict(
                alive=rest[0] not in ("Z", "X"),
                code=None,
                cmd=cmd,
                start=btime + int(rest[19]) / os.sysconf("SC_CLK_TCK"),
            )
        except (OSError, ValueError, IndexError, StopIteration):
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except OSError:
        pass
    return dict(alive=True, code=None, cmd="", start=None)


def run_state_matches(st):
    """True if the PID saved in a run-state JSON is still that same MimicKit python process (not a reused PID)."""
    if not st or st.get("ended"):
        return False
    i = proc_info(st.get("pid"))
    if not i or not i["alive"]:
        return False
    if i["cmd"] and "python" not in i["cmd"].lower():
        return False
    if i["cmd"] and not IS_WIN and "run.py" not in i["cmd"]:
        return False
    if (
        i["start"] is not None
        and st.get("proc_start") is not None
        and abs(i["start"] - st["proc_start"]) > 5
    ):
        return False
    return True


def read_run_state(path):
    try:
        return U.load_json(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log_exc("reading run state " + path, e)
        return None


def write_run_state(path, st):
    try:
        U.save_json(path, st, backup=False)
    except OSError as e:
        log_exc("saving run state " + path, e)


class PidProc:
    """Popen-like handle (pid / poll / wait / returncode) for a detached process this GUI did not start."""

    def __init__(self, pid, st):
        self.pid, self.st, self.returncode = int(pid), st, None

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        if run_state_matches(self.st):
            return None
        i = proc_info(self.pid) if IS_WIN else None
        self.returncode = (
            i["code"]
            if i and i.get("code") is not None and not i["alive"]
            else "unknown (reattached)"
        )
        return self.returncode

    def wait(self):
        while self.poll() is None:
            time.sleep(0.5)
        return self.returncode


class LineTail:
    """Turns appended bytes of console_log.txt into lines with universal newlines (like a text-mode pipe)."""

    def __init__(self):
        self.dec = codecs.getincrementaldecoder("utf-8")("replace")
        self.buf = ""
        self.cr = False

    def feed(self, data, final=False):
        t = self.dec.decode(data, final)
        if self.cr and t.startswith("\n"):
            t = t[1:]
        if t:
            self.cr = t.endswith("\r")
        self.buf += t.replace("\r\n", "\n").replace("\r", "\n")
        *lines, self.buf = self.buf.split("\n")
        if final and self.buf:
            lines.append(self.buf)
            self.buf = ""
        return [l + "\n" for l in lines]


HIST_COLS = [
    "Iteration",
    "Samples",
    "Wall_Time",
    "Train_Return",
    "Test_Return",
    "Samples_Per_Second",
    "Train_Episode_Length",
    "Test_Episode_Length",
]


def per_step_pct(ret, ep_len):
    """Average reward per step in % (DeepMimic-style rewards are 0..1 per step): return / episode length."""
    try:
        ret, ep_len = float(ret), float(ep_len)
    except (TypeError, ValueError):
        return None
    if not (ep_len > 0) or ret != ret:
        return None
    return 100.0 * ret / ep_len


def per_step_series(h):
    """{'Train': [...], 'Test': [...]} per-step % per row (None where unknown) for a history/console dict."""
    out = {}
    for k in ("Train", "Test"):
        R_, L = h.get(k + "_Return") or [], h.get(k + "_Episode_Length") or []
        if L and any(v == v for v in L):
            out[k] = [per_step_pct(a, b) for a, b in zip(R_, L)]
    return out


def load_history(d):
    """Per-iteration rows of one run folder: chart_history.csv if present, else backfilled from log.txt."""
    f = os.path.join(d, HIST_FILE)
    if os.path.exists(f):
        out = {k: [] for k in HIST_COLS}
        try:
            lines = open(f, errors="replace").read().splitlines()
            head = lines[0].split(",") if lines else []
            for l in lines[1:]:
                parts = l.split(",")
                if len(parts) != len(head):
                    continue  # partial last line (crash while writing)
                for k, v in zip(head, parts):
                    if k in out:
                        out[k].append(float(v) if v not in ("", "nan") else float("nan"))
            out = {k: v for k, v in out.items() if v and any(x == x for x in v)}
            if out.get("Samples"):
                return out
        except (OSError, ValueError):
            pass
    c = os.path.join(d, CONSOLE_FILE)  # rebuild from the captured console output
    if os.path.exists(c):
        t = StdoutTables()
        try:
            t.feed(open(c, errors="replace").read())
            t.feed("-" * 10)
        except OSError:
            pass
        if t.rows():
            return t.data
    return parse_log(os.path.join(d, "log.txt"))


def append_history(d, data, already):
    """Append rows [already:] of data (column -> list) to d/chart_history.csv. Returns the new row count."""
    n = len(data.get("Iteration", []))
    if n <= already:
        return already
    f = os.path.join(d, HIST_FILE)
    try:
        new = not os.path.exists(f) or already == 0
        cols = HIST_COLS
        if not new:  # keep the existing file's columns (older launchers wrote fewer)
            with open(f, errors="replace") as fh:
                cols = fh.readline().strip().split(",") or HIST_COLS
        with open(f, "w" if new else "a") as fh:
            if new:
                fh.write(",".join(HIST_COLS) + "\n")
                already = 0
            for i in range(already, n):
                fh.write(
                    ",".join(
                        (
                            ("%.10g" % data[k][i])
                            if k in data and i < len(data[k]) and data[k][i] == data[k][i]
                            else ""
                        )
                        for k in cols
                    )
                    + "\n"
                )
        return n
    except OSError:
        return already


def hms(sec):
    return str(datetime.timedelta(seconds=int(max(0, sec))))


class StdoutTables:
    """Collects MimicKit's boxed console tables ('|  Iteration |  0 |' ... '-----') into dict column -> floats."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.data, self.cur, self.last_it = {}, {}, None

    def _commit(self):
        c, self.cur = self.cur, {}
        if "Iteration" not in c or len(c) < 2 or c["Iteration"] == self.last_it:
            return
        n = len(self.data.get("Iteration", []))
        for k, v in c.items():
            col = self.data.setdefault(k, [])
            col.extend([float("nan")] * (n - len(col)))
            col.append(v)
        self.last_it = c["Iteration"]

    def feed(self, text):
        for line in text.replace("\r", "\n").split("\n"):
            st = line.strip()
            if st.startswith("|"):
                parts = [p.strip() for p in st.strip("|").split("|")]
                if len(parts) == 2 and parts[0] and _isnum(parts[1]):
                    if parts[0] == "Iteration" and self.cur:
                        self._commit()
                    self.cur[parts[0]] = float(parts[1])
            elif st and set(st) == {"-"} and self.cur:
                self._commit()

    def rows(self):
        return len(self.data.get("Iteration", []))


def _isnum(s):
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def rate_per_hour(d):
    """Samples/hour: Samples_Per_Second if logged, else Samples delta / Wall_Time delta (hours)."""
    sps = [v for v in d.get("Samples_Per_Second", []) if v == v]
    if sps:
        return sps[-1] * 3600, [v * 3600 for v in d["Samples_Per_Second"]]
    S, W = d.get("Samples", []), d.get("Wall_Time", [])
    n = min(len(S), len(W))
    out = []
    for i in range(n):
        j = max(0, i - max(5, n // 10))
        if i > j and W[i] > W[j]:
            out.append((S[i] - S[j]) / (W[i] - W[j]))
        elif W[i] > 0:
            out.append(S[i] / W[i])
        else:
            out.append(float("nan"))
    return (out[-1] if out else 0.0), out


# ---------------------------------------------------------------- progress estimate (plateau fit / target)
PLATEAU_FRACTION = 0.95  # "done" = 95% of the way from the start to the fitted plateau
MIN_FIT_POINTS = 25


def _prep_points(segs):
    """segs: [(samples list, return list)] per session, oldest first, samples already cumulative over the chain.
    Drops the first few points after every resume (the dip while the policy re-settles) and NaNs."""
    X, Y = [], []
    for i, (xs, ys) in enumerate(segs):
        pts = [(x, y) for x, y in zip(xs, ys) if x == x and y == y]
        if i > 0:
            k = max(2, len(pts) // 20)
            pts = pts[k:] if len(pts) > 2 * k + 2 else []
        for x, y in pts:
            X.append(float(x))
            Y.append(float(y))
    order = sorted(range(len(X)), key=lambda i: X[i])
    return [X[i] for i in order], [Y[i] for i in order]


def _rolling_median(y, w):
    h = w // 2
    out = []
    for i in range(len(y)):
        win = sorted(y[max(0, i - h) : i + h + 1])
        out.append(win[len(win) // 2])
    return out


def fit_plateau(X, Y):
    """Weighted least-squares fit of y = a - b*exp(-(x - x0)/c) (c by grid search, a/b linear), on median-smoothed data
    with more weight on recent points. Returns dict(a, b, c, x0, rmse, at_edge) or None."""
    import numpy as np

    n = len(X)
    if n < MIN_FIT_POINTS:
        return None
    x = np.asarray(X, float)
    y = np.asarray(_rolling_median(list(Y), max(3, (n // 25) | 1)), float)
    x0 = x[0]
    span = x[-1] - x0
    if span <= 0:
        return None
    w = 0.5 + (x - x0) / span
    best = None
    cs = np.geomspace(span * 0.02, span * 20, 90)
    for c in cs:
        e = np.exp(-(x - x0) / c)
        A = np.stack([np.ones(n), -e], 1) * np.sqrt(w)[:, None]
        sol, *_ = np.linalg.lstsq(A, y * np.sqrt(w), rcond=None)
        r = float(np.sum(w * (y - (sol[0] - sol[1] * e)) ** 2))
        if best is None or r < best[0]:
            best = (r, float(sol[0]), float(sol[1]), float(c))
    r, a, b, c = best
    resid = np.asarray(Y, float) - (a - b * np.exp(-(x - x0) / c))
    return dict(
        a=a,
        b=b,
        c=c,
        x0=float(x0),
        rmse=float(np.sqrt(np.mean(resid**2))),
        at_edge=c >= cs[-2],
        span=float(span),
        noise=float(np.std(np.asarray(Y, float) - y)),
    )


def _plateau_pct(f, xnow):
    return 100.0 * (1 - math.exp(-(xnow - f["x0"]) / f["c"])) / PLATEAU_FRACTION


def _eta_text(samples_left, rate):
    if rate <= 0 or samples_left != samples_left:
        return "time left unknown"
    h = samples_left / rate
    if h < 1:
        return "about %d min left" % max(1, round(h * 60))
    return "about %.0f h left" % h if h >= 3 else "about %.1f h left" % h


def estimate_progress(segs, rate, target=None):
    """-> dict(text, pct or None, kind). segs as in _prep_points; rate in samples/hour; target = dict(kind 'samples'|'score', value)."""
    X, Y = _prep_points(segs)
    xnow = max((x for xs, _ in segs for x in xs if x == x), default=0.0)
    if target and target.get("kind") == "samples" and target.get("value"):
        tv = float(target["value"])
        pct = min(100.0, 100.0 * xnow / tv) if tv > 0 else None
        if xnow >= tv:
            return dict(
                kind="target", pct=100.0, text="Target %s samples: reached" % f"{int(tv):,}"
            )
        return dict(
            kind="target",
            pct=pct,
            text="Target %s samples: %d%% (%s)" % (f"{int(tv):,}", pct, _eta_text(tv - xnow, rate)),
        )
    f = fit_plateau(X, Y)
    if target and target.get("kind") == "score" and target.get("value") is not None:
        tv = float(target["value"])
        cur = sorted(Y[-9:])[len(Y[-9:]) // 2] if Y else float("nan")
        if Y and cur >= tv:
            return dict(
                kind="target",
                pct=100.0,
                text="Target score %g: reached (recent return %.3g)" % (tv, cur),
            )
        if not f or f["at_edge"] or f["b"] <= 0:
            return dict(
                kind="target",
                pct=None,
                text="Target score %g: not enough data yet to tell when (recent return %.3g)"
                % (tv, cur),
            )
        if tv >= f["a"]:
            return dict(
                kind="target",
                pct=None,
                text="Target score %g: may not be reached - the curve levels off near %.3g (rough)"
                % (tv, f["a"]),
            )
        xt = (
            f["x0"] - f["c"] * math.log((f["a"] - tv) / f["b"])
            if f["b"] > 0 and f["a"] - tv > 0
            else float("nan")
        )
        pct = (
            max(0.0, min(99.0, 100.0 * (xnow - f["x0"]) / (xt - f["x0"]))) if xt > f["x0"] else 0.0
        )
        return dict(
            kind="target",
            pct=pct,
            text="Target score %g: ~%d%% (%s) - rough"
            % (tv, pct, _eta_text(max(0.0, xt - xnow), rate)),
        )
    if not f:
        return dict(kind="plateau", pct=None, text="Plateau estimate: not enough data yet")
    if f["b"] <= 0 or f["b"] * (1 - math.exp(-f["span"] / f["c"])) < 2 * max(f["noise"], 1e-9):
        return dict(
            kind="plateau",
            pct=None,
            text="Plateau estimate: no clear improvement in the data (flat or noisy) - can't estimate",
        )
    if f["at_edge"]:
        return dict(
            kind="plateau",
            pct=None,
            text="Plateau estimate: still improving steadily, no plateau in sight yet",
        )
    pct = _plateau_pct(f, xnow)
    # stability: the same fit without the newest 15% must roughly agree
    k = int(len(X) * 0.85)
    g = fit_plateau(X[:k], Y[:k])
    if not g or g["at_edge"] or g["b"] <= 0 or abs(_plateau_pct(g, xnow) - pct) > 25:
        return dict(
            kind="plateau", pct=None, text="Plateau estimate: not enough data yet (fit not stable)"
        )
    pct = max(0.0, min(99.0, pct))
    x95 = f["x0"] + f["c"] * math.log(1 / (1 - PLATEAU_FRACTION))
    left = max(0.0, x95 - xnow)
    return dict(
        kind="plateau",
        pct=pct,
        a=f["a"],
        text="Plateau estimate: ~%d%% (%s) - rough"
        % (pct, _eta_text(left, rate) if left > 0 else "about at the plateau"),
    )


class Tip:
    """Tooltip. One Tip per widget (creating another for the same widget only updates the text), and at most one
    tooltip window on screen app-wide. Shown after a short delay, destroyed on leave / click / when the pointer is gone.
    """

    _by_widget = {}
    _active = None
    DELAY = 350

    def __new__(cls, w, text):
        old = cls._by_widget.get(str(w))
        if old is not None and old.w is w:
            old.text = text
            return old
        return super().__new__(cls)

    def __init__(self, w, text):
        if getattr(self, "w", None) is w:
            return  # already bound (see __new__)
        self.w, self.text, self.top, self._after = w, text, None, None
        Tip._by_widget[str(w)] = self
        w.bind("<Enter>", self._schedule, add="+")
        w.bind("<Leave>", self.hide, add="+")
        w.bind("<ButtonPress>", self.hide, add="+")
        w.bind("<Destroy>", self._gone, add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._after = self.w.after(self.DELAY, self.show)

    def _cancel(self):
        if self._after:
            try:
                self.w.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _pointer_inside(self):
        try:
            px, py = self.w.winfo_pointerxy()
            x, y = self.w.winfo_rootx(), self.w.winfo_rooty()
            return x <= px < x + self.w.winfo_width() and y <= py < y + self.w.winfo_height()
        except tk.TclError:
            return False

    def show(self, _=None):
        self._after = None
        if self.top is not None:
            return
        if Tip._active is not None and Tip._active is not self:
            Tip._active.hide()
        try:
            self.top = tk.Toplevel(self.w)
            self.top.withdraw()
            self.top.wm_overrideredirect(True)
            self.top._mk_tip = True
            tk.Label(
                self.top,
                text=self.text,
                justify="left",
                bg=T["tip_bg"],
                fg=T["tip_fg"],
                relief="solid",
                bd=1,
                wraplength=420,
                padx=6,
                pady=4,
            ).pack()
            self.top.update_idletasks()  # measure, then place inside the window (above the widget if no room below)
            x, y = tip_position(self.w, self.top.winfo_reqwidth(), self.top.winfo_reqheight())
            self.top.geometry("+%d+%d" % (x, y))
            self.top.deiconify()
        except tk.TclError:
            self.top = None
            return
        Tip._active = self
        self.w.after(500, self._watch)

    def _watch(self):
        """Safety net: a missed <Leave> (widget re-laid out, window moved) still closes the tooltip."""
        if self.top is None:
            return
        if not self._pointer_inside():
            self.hide()
        else:
            self.w.after(500, self._watch)

    def hide(self, _=None):
        self._cancel()
        if self.top is not None:
            try:
                self.top.destroy()
            except tk.TclError:
                pass
            self.top = None
        if Tip._active is self:
            Tip._active = None

    def _gone(self, ev=None):
        if ev is not None and ev.widget is not self.w:
            return
        self.hide()
        Tip._by_widget.pop(str(self.w), None)

    @classmethod
    def open_count(cls, root):
        n = 0

        def walk(w):
            nonlocal n
            for c in w.winfo_children():
                if getattr(c, "_mk_tip", False) and c.winfo_exists():
                    n += 1
                walk(c)

        walk(root)
        return n


# ---------------------------------------------------------------- app


# everything above (incl. _private helpers and imported modules) is shared with the mkl.* mixins
__all__ = [n for n in list(globals()) if not n.startswith("__")]
