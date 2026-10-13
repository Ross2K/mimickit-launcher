"""MimicKit Launcher - a small desktop GUI for running MimicKit (https://github.com/xbpeng/MimicKit).

Unofficial and unaffiliated with MimicKit. Vibe coded; see README.md.
Copyright (c) 2026 curelessSky, licensed under GPL-3.0-or-later.
Run with any Python 3.9+ that has tkinter and matplotlib:  python mimickit_launcher.py
"""
VERSION = "a0.3.2"
import codecs, json, math, os, queue, shlex, shutil, signal, subprocess, sys, threading, time, datetime, glob, re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mimickit_remote as R

HERE = os.path.dirname(os.path.abspath(__file__))
def _config_path():
    base = os.environ.get("APPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base or HERE, "mimickit-launcher", "settings.json")
CONFIG = os.environ.get("MIMICKIT_LAUNCHER_CONFIG") or _config_path()
IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0          # CREATE_NO_WINDOW: no black console windows
NEWTON = ["--engine_config", "data/engines/newton_engine.yaml"]

# ---------------------------------------------------------------- args discovery
TRAIN_PREFIXES = ("deepmimic", "amp", "ase", "add", "lcp", "smp", "vault", "awr", "ppo")

def read_args_file(path):
    """MimicKit args files: '--key value ...' tokens, '#' comments. Returns dict key -> list of values."""
    toks = []
    try:
        for line in open(path, errors="replace"):
            line = line.split("#", 1)[0].strip()
            if line: toks += line.split()
    except OSError:
        return {}
    out, key = {}, None
    for t in toks:
        if t.startswith("--"): key = t[2:]; out.setdefault(key, [])
        elif key: out[key].append(t)
    return out

def motion_of(mk, env_rel):
    try:
        for line in open(os.path.join(mk, env_rel), errors="replace"):
            m = re.match(r'\s*motion_file:\s*"?([^"#\n]+)"?', line)
            if m: return m.group(1).strip()
    except (OSError, TypeError):
        pass
    return ""

def discover(mk):
    """Scan <mk>/args/*.txt -> (train configs, view configs); each a dict(name, file, info...)."""
    train, view = [], []
    for f in sorted(glob.glob(os.path.join(mk, "args", "*.txt"))):
        a = read_args_file(f); name = os.path.basename(f)[:-len(".txt")]
        if name.endswith("_args"): name = name[:-5]
        env = (a.get("env_config") or [""])[0]
        item = dict(name=name, file=os.path.relpath(f, mk).replace(os.sep, "/"), env=env,
                    engine=(a.get("engine_config") or [""])[0], num_envs=int((a.get("num_envs") or ["0"])[0] or 0),
                    out=(a.get("out_dir") or [""])[0], motion=motion_of(mk, env))
        is_view = (a.get("mode") or [""])[0] == "test" and "agent_config" not in a
        if is_view or "view" in name: view.append(item)
        elif "agent_config" in a or name.split("_")[0] in TRAIN_PREFIXES: train.append(item)
        else: view.append(item)
    return train, view

def default_out(item):
    o = (item.get("out") or "").rstrip("/\\")
    return o if o and o not in ("output", "output/") else "output/" + item["name"]

def detect_python(mk):
    exe = ("Scripts", "python.exe") if IS_WIN else ("bin", "python")
    for v in (os.path.join(mk, ".venv"), os.path.join(mk, "venv"), os.path.join(os.path.dirname(mk), "venv"),
              os.path.join(os.path.dirname(mk), ".venv")):
        p = os.path.join(v, *exe)
        if os.path.exists(p): return v
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
    "watch": "Watch latest model: plays the newest saved model.pt in order - one character, starting at the beginning of the clip,\n"
             "no random start and no early resets (a generated view copy of the env yaml; your data folder is not changed).",
    "continue": "Continue from another run: pick a finished or older run folder (anything with model.pt in it or its _resumeN\n"
                "folders). Its newest model.pt becomes the start of a new training run of the CURRENT config in the current\n"
                "output folder (or its next _resumeN if that folder is already used). Training time, session count and the\n"
                "source run's chart history are carried over (shown grey with dotted links in front of the new run).",
    "preview": "Render preview MP4: records the newest model.pt for one clip length in a separate background process (CPU by\n"
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
            "Training keeps the last saved model.pt. (Windows: taskkill /T /F, Linux: kills the process group.)",
    "envs": "How many simulated characters train at once. More = faster but more GPU memory.\n"
            "An 8 GB card fits roughly 4000-5000 with the Newton engine. Out of memory? Lower it (see README).",
    "out": "Folder (inside MimicKit) where log.txt and model.pt are written.",
}

# ---------------------------------------------------------------- optional profile overlay
# A personal build can drop a launcher_profile.py next to this file to add presets, tooltips and defaults
# without touching the generic code. Supported names (all optional):
#   VERSION_SUFFIX (str), HELP (dict, merged), RETURN_TEXT (str), DEFAULT_ENVS (int),
#   PREFERRED_TRAIN / PREFERRED_VIEW (list of config names), PRESETS (list of dicts:
#   name, kind "train"/"view", file, args (extra list), out, num_envs, help)
RETURN_TEXT = "Return = how well the character copies the animation (higher is better)."
DEFAULT_ENVS = 4096
PREFERRED_TRAIN = ["deepmimic_humanoid_ppo"]
PREFERRED_VIEW = ["view_motion_humanoid"]
PRESETS = []
if os.path.exists(os.path.join(HERE, "launcher_profile.py")):
    sys.path.insert(0, HERE)
    try:
        import launcher_profile as _P
    finally:
        sys.path.remove(HERE)
    VERSION += getattr(_P, "VERSION_SUFFIX", "")
    HELP.update(getattr(_P, "HELP", {}))
    for _k in ("RETURN_TEXT", "DEFAULT_ENVS", "PREFERRED_TRAIN", "PREFERRED_VIEW", "PRESETS"):
        if hasattr(_P, _k): globals()[_k] = getattr(_P, _k)

THEMES = {
    "dark": dict(bg="#121212", panel="#1e1e1e", field="#1a1a1a", fg="#d0d0d0", dim="#8a8a8a", accent="#5b8db8",
                 border="#333333", sel="#2f4f6f", btn="#262626", btn_act="#333333", log_bg="#0d0d0d", log_fg="#c8c8c8",
                 tip_bg="#2a2a2a", tip_fg="#e0e0e0", stop="#7a2a2a", stop_act="#943434", stop_fg="#f0d0d0",
                 good="#7fb38a", grid="#3a3a3a", line1="#6ea8d8", line2="#d8a05e", line3="#7fb38a"),
    "light": dict(bg="#ececec", panel="#f5f5f5", field="#ffffff", fg="#1a1a1a", dim="#666666", accent="#2f6ea3",
                  border="#b0b0b0", sel="#b8d4ee", btn="#e0e0e0", btn_act="#d0d0d0", log_bg="#111111", log_fg="#dddddd",
                  tip_bg="#ffffe0", tip_fg="#000000", stop="#c94a4a", stop_act="#b03a3a", stop_fg="#ffffff",
                  good="#14532d", grid="#cccccc", line1="tab:blue", line2="tab:orange", line3="tab:green"),
}
T = dict(THEMES["dark"])          # current colours (updated in place)

def load_settings():
    s = dict(mimickit="", venv="", light_mode=False, force_newton=True)
    try: s.update(json.load(open(CONFIG)))
    except Exception: pass
    return s

# ---------------------------------------------------------------- log.txt parsing
def parse_table_text(txt):
    """MimicKit log.txt: whitespace-separated header names followed by numeric rows. Rows may be separated by
    '\\n', '\\r' or nothing at all (all on one line), so tokens are regrouped by header width.
    Header-only files, partial last rows and repeated headers are handled. Returns dict column -> floats."""
    head, data, row = [], {}, []
    in_head = False
    for t in txt.split():
        if not _isnum(t):
            if not in_head: head, data = [], {}; in_head = True   # a new header block = a new run; keep the latest
            head.append(t); data.setdefault(t, []); row = []
            continue
        in_head = False
        if not head: continue
        row.append(float(t))
        if len(row) == len(head):
            for h, v in zip(head, row): data[h].append(v)
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
        j = json.load(open(os.path.join(d, TIME_FILE)))
        return j if isinstance(j.get("seconds"), (int, float)) else None
    except (OSError, ValueError, AttributeError):
        return None

def write_time(d, j):
    try:
        tmp = os.path.join(d, TIME_FILE + ".tmp"); json.dump(j, open(tmp, "w"), indent=1); os.replace(tmp, os.path.join(d, TIME_FILE))
    except OSError:
        pass

def chain_total(dirs):
    """Total training seconds and sessions over a run chain [original, _resume1, ...]. A folder's JSON holds the
    cumulative total (it was carried over on resume); folders without one add their log.txt Wall_Time (hours)."""
    total, sessions = 0.0, 0
    for d in dirs:
        j = read_time(d)
        if j: total, sessions = float(j["seconds"]), int(j.get("sessions", sessions))
        else:
            W = [w for w in parse_log(os.path.join(d, "log.txt")).get("Wall_Time", []) if w == w]
            if W: total += W[-1] * 3600; sessions += 1
    return total, sessions

LINK_FILE = "launcher_link.json"   # written when a run continues from another run folder
_RESUME_RE = re.compile(r"^(.*)_resume(\d+)$")

def chain_folders(base):
    """base folder + its _resumeN folders, as sorted (N, abs path)"""
    parent, name = os.path.split(os.path.normpath(base)); out = [(0, base)]
    if os.path.isdir(parent):
        for d in os.listdir(parent):
            if d.startswith(name + "_resume") and d[len(name) + 7:].isdigit():
                out.append((int(d[len(name) + 7:]), os.path.join(parent, d)))
    return sorted(out)

def base_of(d):
    m = _RESUME_RE.match(os.path.basename(os.path.normpath(d)))
    return os.path.join(os.path.dirname(os.path.normpath(d)), m.group(1)) if m else d

def parent_of(d):
    """The run folder d continued from: the parent in launcher_time.json / launcher_link.json (may be another output folder),
    else for a _resumeN folder without JSON the previous folder of its own chain."""
    cands = []
    j = read_time(d)
    if j and j.get("parent"): cands.append(j["parent"])
    try:
        l = json.load(open(os.path.join(d, LINK_FILE)))
        if l.get("parent"): cands.append(l["parent"])
    except (OSError, ValueError, AttributeError):
        pass
    for c in cands:
        if os.path.isdir(c): return c
        alt = os.path.join(os.path.dirname(os.path.normpath(d)), os.path.basename(os.path.normpath(c)))   # MimicKit folder moved
        if os.path.isdir(alt): return alt
    if cands: return None
    m = _RESUME_RE.match(os.path.basename(os.path.normpath(d)))
    if m:
        base = base_of(d)
        for k in range(int(m.group(2)) - 1, 0, -1):
            if os.path.isdir(base + "_resume%d" % k): return base + "_resume%d" % k
        if os.path.isdir(base): return base
    return None

def run_chain(d, limit=500):
    """All run folders leading to d, oldest first, following parent links across output folders (cycle-safe)."""
    out, seen, cur = [d], {os.path.normcase(os.path.abspath(d))}, d
    while len(out) < limit:
        p = parent_of(cur)
        if not p: break
        n = os.path.normcase(os.path.abspath(p))
        if n in seen: break
        seen.add(n); out.insert(0, p); cur = p
    return out

def make_view_env(mk, env_rel, dst, episode_length=1000.0):
    """Copy of a training env yaml for chronological playback: no random start, no early termination, long episodes.
    Written to dst (a launcher folder under output/), never into MimicKit's data folder. Returns dst or None."""
    try: lines = open(os.path.join(mk, env_rel), errors="replace").read().splitlines()
    except OSError: return None
    over = dict(rand_reset="False", enable_early_termination="False", pose_termination="False", episode_length="%g" % episode_length)
    out, seen = ["# generated by MimicKit Launcher %s from %s (chronological view: rand_reset/early termination off)" % (VERSION, env_rel)], set()
    for l in lines:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", l)
        if m and m.group(1) in over:
            out.append("%s: %s" % (m.group(1), over[m.group(1)])); seen.add(m.group(1))
        else: out.append(l)
    out += ["%s: %s" % (k, v) for k, v in over.items() if k not in seen]
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True); open(dst, "w").write("\n".join(out) + "\n")
    except OSError: return None
    return dst

def last_iteration(d):
    h = load_history(d) if os.path.isdir(d) else {}
    it = [x for x in h.get("Iteration", []) if x == x]
    return int(it[-1]) if it else None

HIST_FILE = "chart_history.csv"
CONSOLE_FILE = "console_log.txt"
RUN_STATE = "launcher_run.json"   # pid, command and start time of a detached MimicKit process (for reattaching)
DETACHED_FLAGS = (0x00000200 | 0x08000000) if IS_WIN else 0   # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW (hidden console, survives the GUI)

# ---------------------------------------------------------------- detached process helpers
if IS_WIN:
    import ctypes
    from ctypes import wintypes
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

def _win_proc(pid):
    """(alive, exit_code, image path, creation time as unix seconds) of a Windows PID; None if it can't be opened."""
    h = _k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h: return None
    try:
        code = wintypes.DWORD(); _k32.GetExitCodeProcess(h, ctypes.byref(code))
        buf = ctypes.create_unicode_buffer(1024); n = wintypes.DWORD(1024)
        img = buf.value if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        ct = None
        if _k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            ct = ((c.dwHighDateTime << 32) | c.dwLowDateTime) / 1e7 - 11644473600
        return code.value == 259, code.value, img, ct      # 259 = STILL_ACTIVE
    finally:
        _k32.CloseHandle(h)

def proc_info(pid):
    """dict(alive, cmd, start) for a PID, or None if there is no such process. cmd/start may be '' / None if unknown."""
    try: pid = int(pid)
    except (TypeError, ValueError): return None
    if pid <= 0: return None
    if IS_WIN:
        w = _win_proc(pid)
        return None if w is None else dict(alive=w[0], code=w[1], cmd=w[2], start=w[3])
    if os.path.exists("/proc/%d/stat" % pid):
        try:
            stat = open("/proc/%d/stat" % pid).read(); rest = stat[stat.rindex(")") + 2:].split()
            cmd = open("/proc/%d/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            btime = next(float(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime"))
            return dict(alive=rest[0] not in ("Z", "X"), code=None, cmd=cmd, start=btime + int(rest[19]) / os.sysconf("SC_CLK_TCK"))
        except (OSError, ValueError, IndexError, StopIteration):
            return None
    try: os.kill(pid, 0)
    except ProcessLookupError: return None
    except OSError: pass
    return dict(alive=True, code=None, cmd="", start=None)

def run_state_matches(st):
    """True if the PID saved in a run-state JSON is still that same MimicKit python process (not a reused PID)."""
    if not st or st.get("ended"): return False
    i = proc_info(st.get("pid"))
    if not i or not i["alive"]: return False
    if i["cmd"] and "python" not in i["cmd"].lower(): return False
    if i["cmd"] and not IS_WIN and "run.py" not in i["cmd"]: return False
    if i["start"] is not None and st.get("proc_start") is not None and abs(i["start"] - st["proc_start"]) > 5: return False
    return True

def read_run_state(path):
    try: return json.load(open(path))
    except (OSError, ValueError): return None

def write_run_state(path, st):
    try:
        tmp = path + ".tmp"; json.dump(st, open(tmp, "w"), indent=1); os.replace(tmp, path)
    except OSError: pass

class PidProc:
    """Popen-like handle (pid / poll / wait / returncode) for a detached process this GUI did not start."""
    def __init__(self, pid, st): self.pid, self.st, self.returncode = int(pid), st, None
    def poll(self):
        if self.returncode is not None: return self.returncode
        if run_state_matches(self.st): return None
        i = proc_info(self.pid) if IS_WIN else None
        self.returncode = i["code"] if i and i.get("code") is not None and not i["alive"] else "unknown (reattached)"
        return self.returncode
    def wait(self):
        while self.poll() is None: time.sleep(0.5)
        return self.returncode

class LineTail:
    """Turns appended bytes of console_log.txt into lines with universal newlines (like a text-mode pipe)."""
    def __init__(self): self.dec = codecs.getincrementaldecoder("utf-8")("replace"); self.buf = ""; self.cr = False
    def feed(self, data, final=False):
        t = self.dec.decode(data, final)
        if self.cr and t.startswith("\n"): t = t[1:]
        if t: self.cr = t.endswith("\r")
        self.buf += t.replace("\r\n", "\n").replace("\r", "\n")
        *lines, self.buf = self.buf.split("\n")
        if final and self.buf: lines.append(self.buf); self.buf = ""
        return [l + "\n" for l in lines]
HIST_COLS = ["Iteration", "Samples", "Wall_Time", "Train_Return", "Test_Return", "Samples_Per_Second",
             "Train_Episode_Length", "Test_Episode_Length"]

def per_step_pct(ret, ep_len):
    """Average reward per step in % (DeepMimic-style rewards are 0..1 per step): return / episode length."""
    try:
        ret, ep_len = float(ret), float(ep_len)
    except (TypeError, ValueError):
        return None
    if not (ep_len > 0) or ret != ret: return None
    return 100.0 * ret / ep_len

def per_step_series(h):
    """{'Train': [...], 'Test': [...]} per-step % per row (None where unknown) for a history/console dict."""
    out = {}
    for k in ("Train", "Test"):
        R_, L = h.get(k + "_Return") or [], h.get(k + "_Episode_Length") or []
        if L and any(v == v for v in L): out[k] = [per_step_pct(a, b) for a, b in zip(R_, L)]
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
                if len(parts) != len(head): continue      # partial last line (crash while writing)
                for k, v in zip(head, parts):
                    if k in out: out[k].append(float(v) if v not in ("", "nan") else float("nan"))
            out = {k: v for k, v in out.items() if v and any(x == x for x in v)}
            if out.get("Samples"): return out
        except (OSError, ValueError):
            pass
    c = os.path.join(d, CONSOLE_FILE)          # rebuild from the captured console output
    if os.path.exists(c):
        t = StdoutTables()
        try:
            t.feed(open(c, errors="replace").read()); t.feed("-" * 10)
        except OSError:
            pass
        if t.rows(): return t.data
    return parse_log(os.path.join(d, "log.txt"))

def append_history(d, data, already):
    """Append rows [already:] of data (column -> list) to d/chart_history.csv. Returns the new row count."""
    n = len(data.get("Iteration", []))
    if n <= already: return already
    f = os.path.join(d, HIST_FILE)
    try:
        new = not os.path.exists(f) or already == 0
        cols = HIST_COLS
        if not new:          # keep the existing file's columns (older launchers wrote fewer)
            with open(f, errors="replace") as fh: cols = (fh.readline().strip().split(",") or HIST_COLS)
        with open(f, "w" if new else "a") as fh:
            if new: fh.write(",".join(HIST_COLS) + "\n"); already = 0
            for i in range(already, n):
                fh.write(",".join(("%.10g" % data[k][i]) if k in data and i < len(data[k]) and data[k][i] == data[k][i] else ""
                                  for k in cols) + "\n")
        return n
    except OSError:
        return already

def hms(sec): return str(datetime.timedelta(seconds=int(max(0, sec))))

class StdoutTables:
    """Collects MimicKit's boxed console tables ('|  Iteration |  0 |' ... '-----') into dict column -> floats."""
    def __init__(self): self.reset()
    def reset(self): self.data, self.cur, self.last_it = {}, {}, None
    def _commit(self):
        c, self.cur = self.cur, {}
        if "Iteration" not in c or len(c) < 2 or c["Iteration"] == self.last_it: return
        n = len(self.data.get("Iteration", []))
        for k, v in c.items():
            col = self.data.setdefault(k, [])
            col.extend([float("nan")] * (n - len(col))); col.append(v)
        self.last_it = c["Iteration"]
    def feed(self, text):
        for line in text.replace("\r", "\n").split("\n"):
            st = line.strip()
            if st.startswith("|"):
                parts = [p.strip() for p in st.strip("|").split("|")]
                if len(parts) == 2 and parts[0] and _isnum(parts[1]):
                    if parts[0] == "Iteration" and self.cur: self._commit()
                    self.cur[parts[0]] = float(parts[1])
            elif st and set(st) == {"-"} and self.cur:
                self._commit()
    def rows(self): return len(self.data.get("Iteration", []))

def _isnum(s):
    try: float(s); return True
    except (ValueError, TypeError): return False

def rate_per_hour(d):
    """Samples/hour: Samples_Per_Second if logged, else Samples delta / Wall_Time delta (hours)."""
    sps = [v for v in d.get("Samples_Per_Second", []) if v == v]
    if sps: return sps[-1] * 3600, [v * 3600 for v in d["Samples_Per_Second"]]
    S, W = d.get("Samples", []), d.get("Wall_Time", [])
    n = min(len(S), len(W)); out = []
    for i in range(n):
        j = max(0, i - max(5, n // 10))
        if i > j and W[i] > W[j]: out.append((S[i] - S[j]) / (W[i] - W[j]))
        elif W[i] > 0: out.append(S[i] / W[i])
        else: out.append(float("nan"))
    return (out[-1] if out else 0.0), out

# ---------------------------------------------------------------- progress estimate (plateau fit / target)
PLATEAU_FRACTION = 0.95      # "done" = 95% of the way from the start to the fitted plateau
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
        for x, y in pts: X.append(float(x)); Y.append(float(y))
    order = sorted(range(len(X)), key=lambda i: X[i])
    return [X[i] for i in order], [Y[i] for i in order]

def _rolling_median(y, w):
    h = w // 2; out = []
    for i in range(len(y)):
        win = sorted(y[max(0, i - h):i + h + 1]); out.append(win[len(win) // 2])
    return out

def fit_plateau(X, Y):
    """Weighted least-squares fit of y = a - b*exp(-(x - x0)/c) (c by grid search, a/b linear), on median-smoothed data
    with more weight on recent points. Returns dict(a, b, c, x0, rmse, at_edge) or None."""
    import numpy as np
    n = len(X)
    if n < MIN_FIT_POINTS: return None
    x = np.asarray(X, float); y = np.asarray(_rolling_median(list(Y), max(3, (n // 25) | 1)), float)
    x0 = x[0]; span = x[-1] - x0
    if span <= 0: return None
    w = 0.5 + (x - x0) / span
    best = None
    cs = np.geomspace(span * 0.02, span * 20, 90)
    for c in cs:
        e = np.exp(-(x - x0) / c); A = np.stack([np.ones(n), -e], 1) * np.sqrt(w)[:, None]
        sol, *_ = np.linalg.lstsq(A, y * np.sqrt(w), rcond=None)
        r = float(np.sum(w * (y - (sol[0] - sol[1] * e)) ** 2))
        if best is None or r < best[0]: best = (r, float(sol[0]), float(sol[1]), float(c))
    r, a, b, c = best
    resid = np.asarray(Y, float) - (a - b * np.exp(-(x - x0) / c))
    return dict(a=a, b=b, c=c, x0=float(x0), rmse=float(np.sqrt(np.mean(resid ** 2))), at_edge=c >= cs[-2], span=float(span),
                noise=float(np.std(np.asarray(Y, float) - y)))

def _plateau_pct(f, xnow):
    return 100.0 * (1 - math.exp(-(xnow - f["x0"]) / f["c"])) / PLATEAU_FRACTION

def _eta_text(samples_left, rate):
    if rate <= 0 or samples_left != samples_left: return "time left unknown"
    h = samples_left / rate
    if h < 1: return "about %d min left" % max(1, round(h * 60))
    return "about %.0f h left" % h if h >= 3 else "about %.1f h left" % h

def estimate_progress(segs, rate, target=None):
    """-> dict(text, pct or None, kind). segs as in _prep_points; rate in samples/hour; target = dict(kind 'samples'|'score', value)."""
    X, Y = _prep_points(segs)
    xnow = max((x for xs, _ in segs for x in xs if x == x), default=0.0)
    if target and target.get("kind") == "samples" and target.get("value"):
        tv = float(target["value"]); pct = min(100.0, 100.0 * xnow / tv) if tv > 0 else None
        if xnow >= tv: return dict(kind="target", pct=100.0, text="Target %s samples: reached" % f"{int(tv):,}")
        return dict(kind="target", pct=pct, text="Target %s samples: %d%% (%s)" % (f"{int(tv):,}", pct, _eta_text(tv - xnow, rate)))
    f = fit_plateau(X, Y)
    if target and target.get("kind") == "score" and target.get("value") is not None:
        tv = float(target["value"]); cur = (sorted(Y[-9:])[len(Y[-9:]) // 2] if Y else float("nan"))
        if Y and cur >= tv: return dict(kind="target", pct=100.0, text="Target score %g: reached (recent return %.3g)" % (tv, cur))
        if not f or f["at_edge"] or f["b"] <= 0:
            return dict(kind="target", pct=None, text="Target score %g: not enough data yet to tell when (recent return %.3g)" % (tv, cur))
        if tv >= f["a"]:
            return dict(kind="target", pct=None, text="Target score %g: may not be reached - the curve levels off near %.3g (rough)" % (tv, f["a"]))
        xt = f["x0"] - f["c"] * math.log((f["a"] - tv) / f["b"]) if f["b"] > 0 and f["a"] - tv > 0 else float("nan")
        pct = max(0.0, min(99.0, 100.0 * (xnow - f["x0"]) / (xt - f["x0"]))) if xt > f["x0"] else 0.0
        return dict(kind="target", pct=pct, text="Target score %g: ~%d%% (%s) - rough" % (tv, pct, _eta_text(max(0.0, xt - xnow), rate)))
    if not f: return dict(kind="plateau", pct=None, text="Plateau estimate: not enough data yet")
    if f["b"] <= 0 or f["b"] * (1 - math.exp(-f["span"] / f["c"])) < 2 * max(f["noise"], 1e-9):
        return dict(kind="plateau", pct=None, text="Plateau estimate: no clear improvement in the data (flat or noisy) - can't estimate")
    if f["at_edge"]:
        return dict(kind="plateau", pct=None, text="Plateau estimate: still improving steadily, no plateau in sight yet")
    pct = _plateau_pct(f, xnow)
    # stability: the same fit without the newest 15% must roughly agree
    k = int(len(X) * 0.85); g = fit_plateau(X[:k], Y[:k])
    if not g or g["at_edge"] or g["b"] <= 0 or abs(_plateau_pct(g, xnow) - pct) > 25:
        return dict(kind="plateau", pct=None, text="Plateau estimate: not enough data yet (fit not stable)")
    pct = max(0.0, min(99.0, pct))
    x95 = f["x0"] + f["c"] * math.log(1 / (1 - PLATEAU_FRACTION))
    left = max(0.0, x95 - xnow)
    return dict(kind="plateau", pct=pct, a=f["a"], text="Plateau estimate: ~%d%% (%s) - rough" % (pct, _eta_text(left, rate) if left > 0 else "about at the plateau"))

class Tip:
    """Tooltip. One Tip per widget (creating another for the same widget only updates the text), and at most one
    tooltip window on screen app-wide. Shown after a short delay, destroyed on leave / click / when the pointer is gone."""
    _by_widget = {}; _active = None; DELAY = 350
    def __new__(cls, w, text):
        old = cls._by_widget.get(str(w))
        if old is not None and old.w is w:
            old.text = text; return old
        return super().__new__(cls)
    def __init__(self, w, text):
        if getattr(self, "w", None) is w: return          # already bound (see __new__)
        self.w, self.text, self.top, self._after = w, text, None, None
        Tip._by_widget[str(w)] = self
        w.bind("<Enter>", self._schedule, add="+"); w.bind("<Leave>", self.hide, add="+")
        w.bind("<ButtonPress>", self.hide, add="+"); w.bind("<Destroy>", self._gone, add="+")
    def _schedule(self, _=None):
        self._cancel(); self._after = self.w.after(self.DELAY, self.show)
    def _cancel(self):
        if self._after:
            try: self.w.after_cancel(self._after)
            except tk.TclError: pass
            self._after = None
    def _pointer_inside(self):
        try:
            px, py = self.w.winfo_pointerxy(); x, y = self.w.winfo_rootx(), self.w.winfo_rooty()
            return x <= px < x + self.w.winfo_width() and y <= py < y + self.w.winfo_height()
        except tk.TclError:
            return False
    def show(self, _=None):
        self._after = None
        if self.top is not None: return
        if Tip._active is not None and Tip._active is not self: Tip._active.hide()
        try:
            x, y = self.w.winfo_rootx() + 10, self.w.winfo_rooty() + self.w.winfo_height() + 4
            self.top = tk.Toplevel(self.w); self.top.wm_overrideredirect(True); self.top.geometry("+%d+%d" % (x, y))
            self.top._mk_tip = True
            tk.Label(self.top, text=self.text, justify="left", bg=T["tip_bg"], fg=T["tip_fg"], relief="solid", bd=1,
                     wraplength=420, padx=6, pady=4).pack()
        except tk.TclError:
            self.top = None; return
        Tip._active = self; self.w.after(500, self._watch)
    def _watch(self):
        """Safety net: a missed <Leave> (widget re-laid out, window moved) still closes the tooltip."""
        if self.top is None: return
        if not self._pointer_inside(): self.hide()
        else: self.w.after(500, self._watch)
    def hide(self, _=None):
        self._cancel()
        if self.top is not None:
            try: self.top.destroy()
            except tk.TclError: pass
            self.top = None
        if Tip._active is self: Tip._active = None
    def _gone(self, ev=None):
        if ev is not None and ev.widget is not self.w: return
        self.hide(); Tip._by_widget.pop(str(self.w), None)
    @classmethod
    def open_count(cls, root):
        n = 0
        def walk(w):
            nonlocal n
            for c in w.winfo_children():
                if getattr(c, "_mk_tip", False) and c.winfo_exists(): n += 1
                walk(c)
        walk(root); return n

# ---------------------------------------------------------------- app
class App:
    def __init__(self, root):
        self.root = root; root.title("MimicKit Launcher  %s" % VERSION); root.geometry("1280x880")
        self.s = load_settings(); self.proc = None; self.q = queue.Queue(); self.preview_proc = None
        self.run_dir = None; self.run_kind = None; self.started = None
        self.live = StdoutTables(); self.live_dir = None; self.live_lock = threading.Lock()
        self.tt = None; self.tt_next = None; self.tt_lock = threading.Lock(); self.hist_n = 0
        self._build()
        self.root.after(400, self._first_run)
        self.root.after(600, self._reattach)
        self.root.after(200, self._pump)
        self.root.after(1000, self._progress_tick)
        self._gpu_poll_thread()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.dash = None; self.rq = queue.Queue(); self.snap = {}; self.render_msg = ""
        self.notifier = R.Notifier(lambda: self.s.get("notify", {}), log=lambda m: self.q.put(m + "\n"))
        self.root.after(800, self._remote_apply)

    # ---------- layout
    def _build(self):
        ttk.Label(self.root, text="version " + VERSION, style="Dim.TLabel").pack(anchor="nw", padx=6)
        top = ttk.Frame(self.root, padding=6); top.pack(fill="x")
        st = ttk.LabelFrame(top, text="Settings", padding=6); st.pack(fill="x")
        self.v_mk = tk.StringVar(value=self.s.get("mimickit", "")); self.v_venv = tk.StringVar(value=self.s.get("venv", ""))
        for r, (lab, var) in enumerate((("MimicKit folder", self.v_mk), ("Python venv (folder or python exe; empty = this Python)", self.v_venv))):
            ttk.Label(st, text=lab).grid(row=r, column=0, sticky="w")
            ttk.Entry(st, textvariable=var, width=60).grid(row=r, column=1, sticky="we", padx=4)
            ttk.Button(st, text="Browse...", command=lambda v=var: self._browse(v)).grid(row=r, column=2)
        ttk.Button(st, text="Save + rescan", command=lambda: (self._save(), self.rescan())).grid(row=0, column=3, rowspan=2, padx=8)
        self.v_light = tk.BooleanVar(value=bool(self.s.get("light_mode", False)))
        cbx = ttk.Checkbutton(st, text="Light mode", variable=self.v_light, command=self._toggle_theme)
        cbx.grid(row=0, column=4, rowspan=2, padx=8); Tip(cbx, "Dark mode is the default (easy on OLED screens). Tick for a light theme. Saved automatically.")
        b = ttk.Button(st, text="Phone + notifications...", command=self.remote_dialog); b.grid(row=0, column=5, padx=4)
        b2 = ttk.Button(st, text="MimicKit patches...", command=self.patch_dialog); b2.grid(row=1, column=5, padx=4); Tip(b2, HELP["patches"])
        Tip(b, HELP["remote"])

        job = ttk.LabelFrame(top, text="What to run", padding=6); job.pack(fill="x", pady=4)
        self.v_train = tk.StringVar(); self.v_view = tk.StringVar()
        ttk.Label(job, text="Training config").grid(row=0, column=0, sticky="w")
        self.cb_train = ttk.Combobox(job, textvariable=self.v_train, state="readonly", width=40)
        self.cb_train.grid(row=0, column=1, sticky="w"); self.cb_train.bind("<<ComboboxSelected>>", self._train_changed)
        Tip(self.cb_train, HELP["trainsel"])
        ttk.Label(job, text="View config").grid(row=0, column=2, sticky="e", padx=(12, 0))
        self.cb_view = ttk.Combobox(job, textvariable=self.v_view, state="readonly", width=34)
        self.cb_view.grid(row=0, column=3, sticky="w"); Tip(self.cb_view, HELP["viewsel"])
        self.l_preset_help = ttk.Label(job, text="", style="Dim.TLabel", wraplength=1100); self.l_preset_help.grid(row=1, column=0, columnspan=6, sticky="w")
        ttk.Label(job, text="num_envs").grid(row=2, column=0, sticky="w")
        self.v_envs = tk.IntVar(value=DEFAULT_ENVS)
        sp = ttk.Spinbox(job, from_=1, to=65536, increment=512, textvariable=self.v_envs, width=8); sp.grid(row=2, column=1, sticky="w")
        Tip(sp, HELP["envs"])
        ttk.Label(job, text="Output folder").grid(row=2, column=2, sticky="e")
        self.v_out = tk.StringVar(); e = ttk.Entry(job, textvariable=self.v_out, width=36); e.grid(row=2, column=3, sticky="w", padx=4)
        Tip(e, HELP["out"])
        self.v_newton = tk.BooleanVar(value=bool(self.s.get("force_newton", True)))
        c = ttk.Checkbutton(job, text="Use Newton engine", variable=self.v_newton, command=self._save); c.grid(row=2, column=4, columnspan=2, sticky="w")
        Tip(c, HELP["newton"])
        ttk.Label(job, text="Extra args").grid(row=3, column=0, sticky="w")
        self.v_extra = tk.StringVar(); e = ttk.Entry(job, textvariable=self.v_extra, width=60); e.grid(row=3, column=1, columnspan=3, sticky="we", pady=2)
        Tip(e, HELP["extra"])
        ttk.Label(job, text="Model for Watch").grid(row=4, column=0, sticky="w")
        self.v_model = tk.StringVar(); e = ttk.Entry(job, textvariable=self.v_model, width=60); e.grid(row=4, column=1, columnspan=3, sticky="we")
        Tip(e, HELP["model"])
        ttk.Button(job, text="Browse...", command=self._browse_model).grid(row=4, column=4, sticky="w", padx=6)
        bf = ttk.Frame(job); bf.grid(row=5, column=0, columnspan=6, sticky="w", pady=(6, 0))
        for key, txt, fn in (("view", "View clip", self.view), ("train", "Start training", self.train),
                             ("resume", "Resume training", self.resume), ("continue", "Continue from run...", self.continue_from),
                             ("watch", "Watch latest model", self.watch), ("preview", "Render preview MP4", self.preview),
                             ("stop", "STOP", self.stop)):
            b = ttk.Button(bf, text=txt, command=fn, width=17, style="Stop.TButton" if key == "stop" else "TButton")
            b.pack(side="left", padx=3); Tip(b, HELP[key])
        bf2 = ttk.Frame(job); bf2.grid(row=6, column=0, columnspan=6, sticky="w", pady=(4, 0))
        b = ttk.Button(bf2, text="Rescan args", command=self.rescan); b.pack(side="left", padx=3); Tip(b, "Re-read MimicKit's args folder.")
        b = ttk.Button(bf2, text="Add args file...", command=self._add_custom); b.pack(side="left", padx=3); Tip(b, HELP["custom"])
        ttk.Label(bf2, text="Preview device").pack(side="left", padx=(24, 4))
        self.v_pdev = tk.StringVar(value=self.s.get("preview_device", "Auto"))
        cb = ttk.Combobox(bf2, textvariable=self.v_pdev, values=["Auto", "CPU only", "GPU"], state="readonly", width=9)
        cb.pack(side="left"); Tip(cb, HELP["pdevice"])
        cb.bind("<<ComboboxSelected>>", lambda _=None: (self.s.__setitem__("preview_device", self.v_pdev.get()), self._save_settings_only()))
        ttk.Label(bf2, text="Reference ghost").pack(side="left", padx=(12, 4))
        self.v_ghost = tk.StringVar(value=self.s.get("preview_ghost", "Overlay"))
        cb = ttk.Combobox(bf2, textvariable=self.v_ghost, values=list(GHOST_MODES), state="readonly", width=12)
        cb.pack(side="left"); Tip(cb, HELP["ghost"])
        cb.bind("<<ComboboxSelected>>", lambda _=None: (self.s.__setitem__("preview_ghost", self.v_ghost.get()), self._save_settings_only()))
        ttk.Label(bf2, text="Clip layout").pack(side="left", padx=(12, 4))
        self.v_layout = tk.StringVar(value=self.s.get("preview_layout", "All at once"))
        cb = ttk.Combobox(bf2, textvariable=self.v_layout, values=list(CLIP_LAYOUTS), state="readonly", width=16)
        cb.pack(side="left"); Tip(cb, HELP["layout"])
        cb.bind("<<ComboboxSelected>>", lambda _=None: (self.s.__setitem__("preview_layout", self.v_layout.get()), self._save_settings_only()))
        b = ttk.Button(bf2, text="Preview diagnostics", command=self.preview_diag); b.pack(side="left", padx=(12, 3)); Tip(b, HELP["pdiag"])
        ttk.Label(bf2, text="Hover = help", style="Dim.TLabel").pack(side="left", padx=8)
        self.custom = list(self.s.get("custom_args", []))
        self.rescan()

        cmdf = ttk.LabelFrame(self.root, text="Exact command being run (copy it into a terminal to run it yourself)", padding=4)
        cmdf.pack(fill="x", padx=6)
        self.t_cmd = tk.Text(cmdf, height=3, width=100, wrap="word"); self.t_cmd.pack(fill="x"); self.t_cmd.configure(state="disabled")

        mid = ttk.Panedwindow(self.root, orient="horizontal"); mid.pack(fill="both", expand=True, padx=6, pady=4)
        left = ttk.Frame(mid); mid.add(left, weight=1)
        stf = ttk.LabelFrame(left, text="Status", padding=4); stf.pack(fill="x")
        self.l_status = ttk.Label(stf, text="Idle.", justify="left", font=("Segoe UI", 10) if IS_WIN else ("TkDefaultFont", 10)); self.l_status.pack(anchor="w")
        tgf = ttk.Frame(stf); tgf.pack(anchor="w", fill="x", pady=(2, 0))
        ttk.Label(tgf, text="Progress target").pack(side="left")
        self.v_tkind = tk.StringVar(value="plateau (auto)"); self.v_tval = tk.StringVar()
        self.cb_target = ttk.Combobox(tgf, textvariable=self.v_tkind, values=["plateau (auto)", "samples (millions)", "score (Train_Return)"],
                                      state="readonly", width=20); self.cb_target.pack(side="left", padx=4)
        e = ttk.Entry(tgf, textvariable=self.v_tval, width=10); e.pack(side="left")
        b = ttk.Button(tgf, text="Set", command=self._target_from_widgets); b.pack(side="left", padx=4)
        self.cb_target.bind("<<ComboboxSelected>>", lambda _=None: self._target_from_widgets())
        for w in (self.cb_target, e, b): Tip(w, HELP["target"])
        self._target_root = None; self.est_disp = {}
        gpuf = ttk.Frame(stf); gpuf.pack(anchor="w", fill="x")
        self.l_gpu = ttk.Label(gpuf, text="GPU: checking...", justify="left", style="Good.TLabel"); self.l_gpu.pack(side="left", anchor="w")
        self.c_vram = tk.Canvas(gpuf, width=190, height=16, highlightthickness=0, bd=0); self.c_vram.pack(side="left", padx=(10, 0))
        Tip(self.c_vram, "GPU memory (VRAM) used / total from nvidia-smi.\nGreen < 75 %, amber 75-90 %, red > 90 % (close to out-of-memory).")
        self.vram = None; self.root.after(10, self._draw_vram)
        logf = ttk.LabelFrame(left, text="Program output", padding=4); logf.pack(fill="both", expand=True)
        self.t_log = tk.Text(logf, wrap="none", width=70, font=("DejaVu Sans Mono", 9) if not IS_WIN else ("Consolas", 9))
        ys = ttk.Scrollbar(logf, command=self.t_log.yview); self.t_log.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y"); self.t_log.pack(fill="both", expand=True)
        right = ttk.LabelFrame(mid, text="Training progress (live from console output; log.txt as fallback; refreshed every 10 s)", padding=4); mid.add(right, weight=1)
        self.prog_frame = right
        self.root.after(300, lambda: mid.sashpos(0, 600))
        self.fig = Figure(figsize=(5.5, 5), dpi=90, layout="constrained")
        self.v_ps = tk.BooleanVar(value=bool(self.s.get("per_step_chart", True))); self.ax3 = None
        self._make_axes()
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        # chart navigation (no modes): left-drag = pan time (x) of both charts, wheel = zoom time at the cursor, y fixed to
        # the full data range (manual y drag only when a chart has visible data outside its y range), Home/double-click = reset
        self.xview = None; self.drag = None
        self.v_cur = tk.BooleanVar(value=bool(self.s.get("current_session_only", False)))
        navf = ttk.Frame(right); navf.pack(side="bottom", fill="x"); self.navf = navf
        self.b_home = ttk.Button(navf, text="Home", width=7, command=self._auto_follow); self.b_home.pack(side="left", padx=(0, 4))
        self.b_save = ttk.Button(navf, text="Save picture...", command=self._save_chart); self.b_save.pack(side="left")
        c = ttk.Checkbutton(navf, text="Current session only", variable=self.v_cur, command=self._cur_toggled); c.pack(side="left", padx=10)
        c2 = ttk.Checkbutton(navf, text="Per-step chart", variable=self.v_ps, command=self._ps_toggled); c2.pack(side="left")
        Tip(c2, HELP["perstep"])
        Tip(c, HELP["cursess"]); Tip(self.b_home, HELP["chartnav"]); Tip(self.b_save, "Save the charts as a PNG/SVG/PDF picture.")
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        Tip(self.canvas.get_tk_widget(), HELP["chartnav"])
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        ttk.Label(right, text=RETURN_TEXT + "\n"
                              "Samples/hour = training speed.", style="Dim.TLabel").pack(anchor="w")

        self.apply_theme()

    # ---------- theme
    def _toggle_theme(self):
        self.apply_theme(); self._save(); self._progress_tick(force=True)

    def apply_theme(self):
        T.clear(); T.update(THEMES["light" if self.v_light.get() else "dark"])
        if hasattr(self, "c_vram"): self.root.after(0, self._draw_vram)
        st = ttk.Style(self.root); st.theme_use("clam")
        st.configure(".", background=T["bg"], foreground=T["fg"], fieldbackground=T["field"], bordercolor=T["border"],
                     lightcolor=T["border"], darkcolor=T["border"], troughcolor=T["panel"], selectbackground=T["sel"],
                     selectforeground=T["fg"], insertcolor=T["fg"], focuscolor=T["accent"])
        st.configure("TFrame", background=T["bg"]); st.configure("TLabel", background=T["bg"], foreground=T["fg"])
        st.configure("Dim.TLabel", background=T["bg"], foreground=T["dim"])
        st.configure("Good.TLabel", background=T["bg"], foreground=T["good"])
        st.configure("TLabelframe", background=T["bg"], bordercolor=T["border"])
        st.configure("TLabelframe.Label", background=T["bg"], foreground=T["accent"])
        st.configure("TButton", background=T["btn"], foreground=T["fg"], bordercolor=T["border"], padding=4)
        st.map("TButton", background=[("pressed", T["sel"]), ("active", T["btn_act"])], foreground=[("disabled", T["dim"])])
        st.configure("Stop.TButton", background=T["stop"], foreground=T["stop_fg"], bordercolor=T["stop"])
        st.map("Stop.TButton", background=[("pressed", T["stop_act"]), ("active", T["stop_act"])])
        st.configure("TCheckbutton", background=T["bg"], foreground=T["fg"], indicatorbackground=T["field"], indicatorforeground=T["fg"])
        st.map("TCheckbutton", background=[("active", T["bg"])], indicatorbackground=[("selected", T["accent"])])
        for w in ("TEntry", "TSpinbox", "TCombobox"):
            st.configure(w, fieldbackground=T["field"], foreground=T["fg"], background=T["btn"], arrowcolor=T["fg"], insertcolor=T["fg"])
        st.map("TCombobox", fieldbackground=[("readonly", T["field"])], foreground=[("readonly", T["fg"])],
               selectbackground=[("readonly", T["field"])], selectforeground=[("readonly", T["fg"])])
        st.configure("TScrollbar", background=T["btn"], troughcolor=T["panel"], arrowcolor=T["fg"], bordercolor=T["border"])
        st.configure("TPanedwindow", background=T["bg"]); st.configure("Sash", background=T["border"])
        # classic tk bits: combobox drop-down list, Text widgets
        self.root.configure(bg=T["bg"])
        self.root.option_add("*TCombobox*Listbox.background", T["field"]); self.root.option_add("*TCombobox*Listbox.foreground", T["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", T["sel"]); self.root.option_add("*TCombobox*Listbox.selectForeground", T["fg"])
        self.root.option_add("*Listbox.background", T["field"]); self.root.option_add("*Listbox.foreground", T["fg"])
        self.t_cmd.configure(bg=T["panel"], fg=T["fg"], insertbackground=T["fg"], selectbackground=T["sel"], highlightthickness=0, relief="flat")
        self.t_log.configure(bg=T["log_bg"], fg=T["log_fg"], insertbackground=T["log_fg"], selectbackground=T["sel"], highlightthickness=0, relief="flat")
        # matplotlib
        self.fig.set_facecolor(T["panel"])
        for ax in self._axes(): self._style_ax(ax)
        self.canvas.get_tk_widget().configure(bg=T["panel"], highlightthickness=0)
        self._restyle_artists()
        self.canvas.draw_idle()

    def _restyle_artists(self):
        """Live theme switch without waiting for data: recolour what is already drawn (lines carry a role gid)."""
        role = {"cur1": T["line1"], "cur2": T["line2"], "cur3": T["line3"], "earlier": T["dim"], "bridge": T["dim"]}
        for ax in self._axes():
            for ln in ax.get_lines():
                g = ln.get_gid()
                if g in role: ln.set_color(role[g]); ln.set_markerfacecolor(role[g]); ln.set_markeredgecolor(role[g])
            for t in ax.texts: t.set_color(T["dim"])
            self._style_ax(ax)

    # ---------- progress estimate
    def _smooth_estimate(self, chain, v):
        """Displayed % moves at most 10 points per refresh (and eases in), so a noisy fit doesn't jump around."""
        old = self.est_disp.get(chain)
        new = v if old is None else old + max(-10.0, min(10.0, 0.5 * (v - old)))
        self.est_disp = {chain: new}; return new
    def _chain_key(self, d): return os.path.normcase(os.path.abspath(run_chain(d)[0]))
    def _get_target(self, d):
        return self.s.get("targets", {}).get(self._chain_key(d))
    def _set_target(self, d, t):
        tg = self.s.setdefault("targets", {}); k = self._chain_key(d)
        if t: tg[k] = t
        else: tg.pop(k, None)
        self._save_settings_only()
    def _target_from_widgets(self):
        d = self.run_dir or self.outdir_abs(); kind = self.v_tkind.get()
        if kind.startswith("plateau"): self._set_target(d, None)
        else:
            try: val = float(self.v_tval.get().replace(",", ""))
            except ValueError:
                if self.v_tval.get().strip(): messagebox.showerror("Target", "Type a number (samples in millions, or a score).")
                return
            self._set_target(d, dict(kind="samples", value=val * 1e6) if kind.startswith("samples") else dict(kind="score", value=val))
        self._progress_tick(force=True)
    def _sync_target_widgets(self, d):
        k = self._chain_key(d)
        if k == self._target_root: return
        self._target_root = k; t = self._get_target(d)
        if not t: self.v_tkind.set("plateau (auto)"); self.v_tval.set("")
        elif t["kind"] == "samples": self.v_tkind.set("samples (millions)"); self.v_tval.set("%g" % (t["value"] / 1e6))
        else: self.v_tkind.set("score (Train_Return)"); self.v_tval.set("%g" % t["value"])

    # ---------- chart navigation
    def _make_axes(self):
        """2 charts (return, speed) or 3 with the per-step score chart."""
        self.fig.clear(); n = 3 if self.v_ps.get() else 2
        axes = [self.fig.add_subplot(n, 1, i + 1) for i in range(n)]
        self.ax1, self.ax2 = axes[0], axes[1]; self.ax3 = axes[2] if n == 3 else None
        self.yman = [None] * n; self.yfull = [None] * n
    def _ps_toggled(self):
        self.s["per_step_chart"] = bool(self.v_ps.get()); self._save_settings_only(); self._make_axes(); self.apply_theme(); self._auto_follow()
    def _axes(self): return tuple(a for a in (self.ax1, self.ax2, self.ax3) if a is not None)
    def _auto_follow(self):
        """Home / double-click: full view, follow new data, vertical scale back to the full data range."""
        self.xview = None; self.yman = [None] * len(self._axes()); self.drag = None; self._progress_tick(force=True)
    def _cur_toggled(self):
        self.s["current_session_only"] = bool(self.v_cur.get()); self._save_settings_only(); self._auto_follow()
    def _set_x(self, xl):
        self.xview = (float(xl[0]), float(xl[1]))
        for a in self._axes(): a.set_xlim(self.xview)     # both charts always share the time axis
    def y_drag_allowed(self, ax):
        """Vertical drag only when this chart has data inside the visible time range that lies outside its y limits."""
        x0, x1 = sorted(ax.get_xlim()); y0, y1 = sorted(ax.get_ylim())
        for ln in ax.get_lines():
            xs, ys = ln.get_xdata(), ln.get_ydata()
            for x, y in zip(xs, ys):
                try: x, y = float(x), float(y)
                except (TypeError, ValueError): continue
                if x0 <= x <= x1 and y == y and (y < y0 or y > y1): return True
        return False
    def _on_scroll(self, ev):
        ax = ev.inaxes
        if ax is None or ev.xdata is None: return
        f = 1 / 1.25 if ev.button == "up" or getattr(ev, "step", 0) > 0 else 1.25
        x0, x1 = ax.get_xlim()
        self._set_x((ev.xdata - (ev.xdata - x0) * f, ev.xdata + (x1 - ev.xdata) * f))     # x only; y untouched
        self.canvas.draw_idle()
    def _on_click(self, ev):
        if getattr(ev, "dblclick", False) and ev.inaxes is not None: self._auto_follow(); return
        if getattr(ev, "button", None) in (1, "1") or str(getattr(ev, "button", "")) == "MouseButton.LEFT":
            if ev.inaxes in self._axes():
                ax = ev.inaxes
                self.drag = dict(ax=ax, x=ev.x, y=ev.y, xlim=ax.get_xlim(), ylim=ax.get_ylim(), ydrag=self.y_drag_allowed(ax))
    def _on_motion(self, ev):
        d = self.drag
        if not d or ev.x is None: return
        ax = d["ax"]; bb = ax.bbox
        (x0, x1), (y0, y1) = d["xlim"], d["ylim"]
        dx = (ev.x - d["x"]) * (x1 - x0) / max(bb.width, 1)
        self._set_x((x0 - dx, x1 - dx))
        if d["ydrag"] and ev.y is not None:
            dy = (ev.y - d["y"]) * (y1 - y0) / max(bb.height, 1)
            i = self._axes().index(ax); self.yman[i] = (y0 - dy, y1 - dy); ax.set_ylim(self.yman[i])
        self.canvas.draw_idle()
    def _on_release(self, ev):
        self.drag = None
    def _save_chart(self):
        f = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png"), ("SVG", "*.svg"), ("PDF", "*.pdf")])
        if f: self.fig.savefig(f, facecolor=self.fig.get_facecolor())
    @staticmethod
    def _full_range(ax, pad=0.08):
        ys = []
        for ln in ax.get_lines():
            for y in ln.get_ydata():
                try:
                    y = float(y)
                    if y == y: ys.append(y)
                except (TypeError, ValueError): pass
        if not ys: return None
        lo, hi = min(ys), max(ys); p = max((hi - lo) * pad, abs(hi) * 0.02, 1e-3)
        return (lo - p, hi + p)
    def _apply_view(self, cur_range=None):
        """After every redraw: shared x (user view, current session, or all data) and y (manual, else full data range)."""
        for i, ax in enumerate(self._axes()):
            self.yfull[i] = self._full_range(ax)
        if self.xview: xl = self.xview
        elif cur_range: xl = cur_range
        else:
            xs = [float(x) for ax in self._axes() for ln in ax.get_lines() for x in ln.get_xdata()]
            xl = None
            if xs:
                lo, hi = min(xs), max(xs); p = max((hi - lo) * 0.03, 1e-3); xl = (lo - p, hi + p)
        if xl:
            for ax in self._axes(): ax.set_xlim(xl)
        for i, ax in enumerate(self._axes()):
            yl = self.yman[i] or self.yfull[i]
            if yl: ax.set_ylim(yl)

    def _style_ax(self, ax):
        ax.set_facecolor(T["field"])
        ax.tick_params(colors=T["fg"], labelcolor=T["fg"])
        for sp in ax.spines.values(): sp.set_color(T["border"])
        ax.xaxis.label.set_color(T["fg"]); ax.yaxis.label.set_color(T["fg"]); ax.title.set_color(T["fg"])
        ax.grid(True, color=T["grid"], alpha=0.6)
        ax.set_axisbelow(True)
        leg = ax.get_legend()
        if leg:
            leg.get_frame().set_facecolor(T["panel"]); leg.get_frame().set_edgecolor(T["border"]); leg.get_frame().set_alpha(0.9)
            for t in leg.get_texts(): t.set_color(T["fg"])

    def _browse(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or "/")
        if d: var.set(os.path.normpath(d))

    def _save(self):
        self.s.update(mimickit=self.v_mk.get().strip(), venv=self.v_venv.get().strip(), light_mode=bool(self.v_light.get()),
                      custom_args=list(getattr(self, "custom", [])))
        if hasattr(self, "v_newton"): self.s["force_newton"] = bool(self.v_newton.get())
        try:
            os.makedirs(os.path.dirname(CONFIG), exist_ok=True); json.dump(self.s, open(CONFIG, "w"), indent=1)
        except OSError as e:
            self._append("[gui] could not save settings: %s\n" % e)

    def rescan(self):
        self.train_items, self.view_items = discover(self.mk()) if self.mk() else ([], [])
        for f in self.custom:
            a = read_args_file(f if os.path.isabs(f) else os.path.join(self.mk(), f))
            item = dict(name="custom: " + os.path.basename(f), file=f, env=(a.get("env_config") or [""])[0], engine="",
                        num_envs=int((a.get("num_envs") or ["0"])[0] or 0), out=(a.get("out_dir") or [""])[0], motion="")
            (self.view_items if (a.get("mode") or [""])[0] == "test" and "agent_config" not in a else self.train_items).append(item)
        pre = {"train": [], "view": []}
        for pr in PRESETS:   # profile presets (launcher_profile.py) go first in the lists
            a = read_args_file(os.path.join(self.mk(), pr["file"])) if self.mk() else {}
            ex = list(pr.get("args", []))
            env = ex[ex.index("--env_config") + 1] if "--env_config" in ex else (a.get("env_config") or [""])[0]
            pre[pr.get("kind", "train")].append(dict(name=pr["name"], file=pr["file"], args=ex, help=pr.get("help", ""), env=env,
                engine=(a.get("engine_config") or [""])[0], num_envs=int(pr.get("num_envs") or (a.get("num_envs") or ["0"])[0] or 0),
                out=pr.get("out") or (a.get("out_dir") or [""])[0], motion=motion_of(self.mk(), env) if self.mk() and env else ""))
        self.train_items = pre["train"] + self.train_items; self.view_items = pre["view"] + self.view_items
        self.cb_train.configure(values=[i["name"] for i in self.train_items])
        self.cb_view.configure(values=[i["name"] for i in self.view_items])
        last_t, last_v = self.s.get("last_train"), self.s.get("last_view")
        tn = [i["name"] for i in self.train_items]; vn = [i["name"] for i in self.view_items]
        self.v_train.set(last_t if last_t in tn else (next((n for p in PREFERRED_TRAIN for n in tn if n.startswith(p)), tn[0]) if tn else ""))
        self.v_view.set(last_v if last_v in vn else (next((n for p in PREFERRED_VIEW for n in vn if n == p), next((n for n in vn if n.startswith("view_motion")), vn[0])) if vn else ""))
        self._train_changed()
        if self.mk(): self._append("[gui] found %d training and %d view configs in %s\n" % (len(tn), len(vn), os.path.join(self.mk(), "args")))

    def _item(self, kind):
        name = (self.v_train if kind == "train" else self.v_view).get()
        return next((i for i in (self.train_items if kind == "train" else self.view_items) if i["name"] == name), None)

    def _train_changed(self, _=None):
        it = self._item("train")
        if not it: self.l_preset_help.configure(text="No configs found - set the MimicKit folder above."); return
        self.v_out.set(default_out(it))
        if it["num_envs"]: self.v_envs.set(it["num_envs"])
        self.l_preset_help.configure(text=(it["help"] + "\n" if it.get("help") else "") + "%s  |  env: %s  |  motion: %s  |  engine in file: %s" % (it["file"], it["env"] or "?", it["motion"] or "?", it["engine"] or "?"))

    def _add_custom(self):
        f = filedialog.askopenfilename(initialdir=os.path.join(self.mk(), "args"), filetypes=[("args files", "*.txt"), ("all", "*.*")])
        if not f: return
        try: f2 = os.path.relpath(f, self.mk())
        except ValueError: f2 = f
        if f2.startswith(".."): f2 = f
        self.custom.append(f2.replace(os.sep, "/")); self._save(); self.rescan()

    def _browse_model(self):
        f = filedialog.askopenfilename(initialdir=self.mk() or "/", filetypes=[("model", "*.pt"), ("all", "*.*")])
        if f: self.v_model.set(f)

    def _first_run(self):
        if self.mk() and os.path.exists(os.path.join(self.mk(), "mimickit", "run.py")): return
        messagebox.showinfo("Welcome", "First run: please choose your MimicKit folder\n(the one that contains mimickit\\run.py and args\\).")
        d = filedialog.askdirectory(title="Choose the MimicKit folder")
        if not d: return
        self.v_mk.set(os.path.normpath(d))
        v = detect_python(self.mk())
        if v: self.v_venv.set(v); self._append("[gui] found a Python venv: %s\n" % v)
        elif not self.v_venv.get():
            self._append("[gui] no venv found next to MimicKit - using this Python: %s (change it in Settings)\n" % sys.executable)
        self._save(); self.rescan()

    # ---------- helpers
    def mk(self): return self.v_mk.get().strip()
    def python(self):
        v = self.v_venv.get().strip()
        if v:
            if os.path.isfile(v): return v
            cand = os.path.join(v, "Scripts" if IS_WIN else "bin", "python.exe" if IS_WIN else "python")
            if os.path.exists(cand): return cand
        exe = sys.executable
        if IS_WIN and exe.lower().endswith("pythonw.exe"): exe = exe[:-len("pythonw.exe")] + "python.exe"
        return exe
    def outdir_abs(self, rel=None): return os.path.join(self.mk(), (rel or self.v_out.get().strip()).replace("/", os.sep))
    def engine_args(self): return NEWTON if self.v_newton.get() else []
    def extra_args(self):
        try: return shlex.split(self.v_extra.get(), posix=not IS_WIN)
        except ValueError as e: messagebox.showerror("Extra args", str(e)); raise

    def _check(self, kind):
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning("Busy", "Something is already running. Press STOP first."); return False
        if not os.path.exists(os.path.join(self.mk(), "mimickit", "run.py")):
            messagebox.showerror("MimicKit not found", "Can't find mimickit/run.py in:\n%s\n\nSet the MimicKit folder in Settings." % self.mk()); return False
        it = self._item(kind)
        if not it:
            messagebox.showerror("Nothing selected", "No %s config selected (MimicKit's args folder may be empty)." % kind); return False
        self.s["last_train"], self.s["last_view"] = self.v_train.get(), self.v_view.get(); self._save()
        return True

    # ---------- total training time (launcher_time.json in each run folder)
    def _tt_save(self, final=False):
        with self.tt_lock:
            t = self.tt
            if not t: return
            j = dict(seconds=round(t["base"] + time.time() - t["start"], 1), sessions=t["sessions"], parent=t["parent"],
                     updated=datetime.datetime.now().isoformat(timespec="seconds"), launcher_version=VERSION)
            write_time(t["dir"], j)
            if final: self.tt = None

    def _tt_total(self):
        with self.tt_lock:
            if self.tt: return self.tt["base"] + time.time() - self.tt["start"], time.time() - self.tt["start"], self.tt["sessions"]
        try: tot, ses = chain_total(run_chain(self._model_dirs(self.v_out.get().strip())[-1][1]))
        except Exception: tot, ses = 0.0, 0
        return tot, None, ses

    def _model_dirs(self, base_rel):
        """base folder + its _resumeN folders, as (N, abs path)"""
        return chain_folders(self.outdir_abs(base_rel))

    def _latest_model(self):
        best = None
        for _, d in self._model_dirs(self.v_out.get().strip()):
            m = os.path.join(d, "model.pt")
            if os.path.exists(m) and (best is None or os.path.getmtime(m) > os.path.getmtime(best)): best = m
        return best

    # ---------- actions
    def view(self):
        if not self._check("view"): return
        it = self._item("view")
        self._run(["--arg_file", it["file"]] + it.get("args", []) + self.engine_args() + ["--visualize", "true"] + self.extra_args(), kind="view", out=None)

    def train(self):
        if not self._check("train"): return
        out_rel = self.v_out.get().strip(); out = self.outdir_abs(out_rel)
        if os.path.isdir(out) and os.listdir(out):
            if not messagebox.askyesno("Folder already used",
                    "The folder\n%s\nalready has files (an earlier run).\n\nStarting again OVERWRITES its model.pt and log.txt.\n"
                    "Tip: press No and use 'Resume training' instead, or type a new folder name.\n\nOverwrite?" % out, icon="warning"):
                return
        it = self._item("train"); self.tt_next = dict(base=0.0, sessions=1, parent=None)
        self._run(["--arg_file", it["file"]] + it.get("args", []) + self.engine_args() + ["--num_envs", str(self.v_envs.get()), "--visualize", "false",
                   "--out_dir", out_rel] + self.extra_args(), kind="train", out=out)

    def resume(self):
        if not self._check("train"): return
        model = self._latest_model()
        if not model:
            messagebox.showinfo("Nothing to resume", "No model.pt found in %s (or its _resume folders).\nStart a training run first." % self.outdir_abs()); return
        dirs = self._model_dirs(self.v_out.get().strip()); n = dirs[-1][0] + 1
        new_rel = "%s_resume%d" % (self.v_out.get().strip().rstrip("/\\"), n); new_abs = self.outdir_abs(new_rel)
        os.makedirs(new_abs, exist_ok=True)
        start = os.path.join(new_abs, "start_model.pt"); shutil.copy2(model, start)
        tot, ses = chain_total(run_chain(dirs[-1][1]))
        self.tt_next = dict(base=tot, sessions=ses + 1, parent=dirs[-1][1])
        self._append("[gui] carrying total training time %s (%d earlier sessions)\n" % (hms(tot), ses))
        self._append("[gui] copied %s -> %s\n" % (model, start))
        it = self._item("train")
        self._run(["--arg_file", it["file"]] + it.get("args", []) + self.engine_args() + ["--num_envs", str(self.v_envs.get()), "--visualize", "false",
                   "--model_file", os.path.relpath(start, self.mk()).replace(os.sep, "/"), "--out_dir", new_rel] + self.extra_args(),
                  kind="train", out=new_abs)

    def watch(self):
        if not self._check("train"): return
        model = self.v_model.get().strip() or self._latest_model()
        if not model:
            messagebox.showinfo("No model yet", "No model.pt found in the output folder yet.\nTrain first, or pick a .pt file in 'Model for Watch'."); return
        it = self._item("train")
        mrel = os.path.relpath(model, self.mk()) if os.path.isabs(model) else model
        view = self._view_env(it, "watch")   # first occurrence of a key wins in MimicKit's arg parser -> put it first
        self._run((["--env_config", view] if view else []) + ["--arg_file", it["file"]] + it.get("args", []) + self.engine_args() +
                  ["--mode", "test", "--num_envs", "1", "--visualize", "true", "--model_file", mrel.replace(os.sep, "/")] + self.extra_args(),
                  kind="watch", out=None)

    def _view_env(self, it, kind):
        """Generated chronological view yaml (relative to MimicKit) for item it, or None if it has no env_config."""
        if not it.get("env"): self._append("[gui] this config has no env_config - playing it as is\n"); return None
        dst = os.path.join(self.mk(), "output", "_launcher_" + kind, "view_env.yaml")
        if not make_view_env(self.mk(), it["env"], dst):
            self._append("[gui] could not read %s - playing the config as is\n" % it["env"]); return None
        self._append("[gui] chronological view env: %s (from %s)\n" % (os.path.relpath(dst, self.mk()).replace(os.sep, "/"), it["env"]))
        return os.path.relpath(dst, self.mk()).replace(os.sep, "/")

    def continue_from(self):
        """Start a new training run of the current config from the newest model of another run chain."""
        if not self._check("train"): return
        src = filedialog.askdirectory(title="Pick the run to continue from (a folder with model.pt, or its _resumeN folders)",
                                      initialdir=os.path.join(self.mk(), "output"))
        if not src: return
        src = os.path.abspath(src)
        models = [os.path.join(d, "model.pt") for _, d in chain_folders(base_of(src)) if os.path.exists(os.path.join(d, "model.pt"))]
        if not models:
            messagebox.showerror("No model there", "No model.pt in %s or its _resumeN folders." % src); return
        model = max(models, key=os.path.getmtime); src_dir = os.path.dirname(model)
        out_rel = self.v_out.get().strip().rstrip("/\\"); out = self.outdir_abs(out_rel)
        if os.path.isdir(out) and os.listdir(out):
            new_rel = "%s_resume%d" % (out_rel, self._model_dirs(out_rel)[-1][0] + 1)
        else: new_rel = out_rel
        new_abs = self.outdir_abs(new_rel)
        if os.path.normcase(os.path.abspath(new_abs)) in [os.path.normcase(os.path.abspath(c)) for c in run_chain(src_dir)]:
            messagebox.showerror("Same folder", "The new run folder is part of the source run."); return
        tot, ses = chain_total(run_chain(src_dir)); it = self._item("train")
        if not messagebox.askyesno("Continue from another run",
                "Continue training\n  config: %s\nfrom\n  %s\ninto\n  %s\n\nCarries %s of training (%d sessions) and the chart history." %
                (it["name"], model, new_abs, hms(tot), ses)):
            return
        os.makedirs(new_abs, exist_ok=True)
        start = os.path.join(new_abs, "start_model.pt"); shutil.copy2(model, start)
        try:
            json.dump(dict(parent=src_dir, parent_model=model, config=it["name"], env=it.get("env", ""), created=datetime.datetime.now()
                           .isoformat(timespec="seconds"), launcher_version=VERSION), open(os.path.join(new_abs, LINK_FILE), "w"), indent=1)
        except OSError: pass
        self.tt_next = dict(base=tot, sessions=ses + 1, parent=src_dir)
        self._append("[gui] continuing from %s (total %s, %d sessions) -> %s\n" % (src_dir, hms(tot), ses, new_rel))
        self._run(["--arg_file", it["file"]] + it.get("args", []) + self.engine_args() + ["--num_envs", str(self.v_envs.get()), "--visualize", "false",
                   "--model_file", os.path.relpath(start, self.mk()).replace(os.sep, "/"), "--out_dir", new_rel] + self.extra_args(),
                  kind="train", out=new_abs)

    def preview_diag(self):
        return self.preview(diag=True)

    def preview(self, diag=False):
        """Render preview MP4 (or run the preview diagnostics) in a separate detached process (never touches training)."""
        if self.preview_proc and self.preview_proc.poll() is None:
            if messagebox.askyesno("Preview running", "A preview is being rendered. Cancel it?"): self._kill(self.preview_proc.pid, "preview")
            return
        if not os.path.exists(os.path.join(self.mk(), "mimickit", "run.py")):
            messagebox.showerror("MimicKit not found", "Set the MimicKit folder in Settings."); return
        it = self._item("train")
        model = self.v_model.get().strip() or self._latest_model()
        if diag and it: return self._start_preview(it, model, diag=True)
        if not it or not model:
            messagebox.showinfo("No model yet", "No model.pt found in the output folder yet.\nTrain first, or pick a .pt file in 'Model for Watch'."); return
        return self._start_preview(it, model)

    def _start_preview(self, it, model, diag=False):
        pdir = os.path.join(self.mk(), "output", "_launcher_preview"); os.makedirs(pdir, exist_ok=True)
        view = self._view_env(it, "preview")
        if not view: messagebox.showerror("No env config", "This config has no env_config, so there is nothing to preview."); return
        margs = []
        if model:
            model = model if os.path.isabs(model) else os.path.join(self.mk(), model)
            snap = os.path.join(pdir, "preview_model.pt"); shutil.copy2(model, snap)   # snapshot: training may overwrite model.pt any time
            margs = ["--model_file", os.path.relpath(snap, self.mk()).replace(os.sep, "/")]
        mk_args = ["--env_config", view] + margs + ["--arg_file", it["file"]] + it.get("args", []) + self.engine_args()
        script = os.path.join(HERE, "mimickit_preview.py")
        if diag:
            mp4 = os.path.join(pdir, "preview_diagnostics.txt")
            cmd = [self.python(), "-u", script, "diag", "--mk", self.mk(), "--"] + mk_args
        else:
            itn = last_iteration(os.path.dirname(model))
            mp4 = os.path.join(os.path.dirname(model), "preview_%s.mp4" % (itn if itn is not None else time.strftime("%Y%m%d_%H%M%S")))
            dev = {"Auto": "auto", "CPU only": "cpu", "GPU": "gpu"}.get(self.v_pdev.get(), "auto")
            cmd = [self.python(), "-u", script, "all", "--mk", self.mk(), "--device", dev, "--ghost", GHOST_MODES.get(self.v_ghost.get(), "overlay"),
                   "--layout", CLIP_LAYOUTS.get(self.v_layout.get(), "grid"),
                   "--out", mp4, "--"] + mk_args
        logp = os.path.join(pdir, CONSOLE_FILE)
        try:
            offset = os.path.getsize(logp) if os.path.exists(logp) else 0
            self.preview_proc = self._spawn_detached(cmd, logp, env=dict(os.environ, PYTHONUNBUFFERED="1"))
        except Exception as e:
            messagebox.showerror("Could not start the preview", str(e)); return
        write_run_state(os.path.join(pdir, RUN_STATE), dict(pid=self.preview_proc.pid, cmd=cmd, kind="preview", started=time.time(),
                        log=logp, offset=offset, out=None, launcher_version=VERSION))
        self._append("\n[gui] ===== %s  %s =====\n[gui] model %s -> %s (device %s, PID %d; runs in the background)\n" % (
            "PREVIEW DIAGNOSTICS" if diag else "PREVIEW", datetime.datetime.now().strftime("%H:%M:%S"), model or "(none: untrained policy)",
            mp4, self.v_pdev.get(), self.preview_proc.pid))
        threading.Thread(target=self._reader, args=(self.preview_proc, logp, offset, None, "preview"), daemon=True).start()

    def stop(self):
        if not self.proc or self.proc.poll() is not None:
            self._append("[gui] nothing is running\n"); return
        pid = self.proc.pid; self._tt_save(final=True)
        self._kill(pid)
        self._append("[gui] stopped. The last saved model.pt is kept.\n")

    def _kill(self, pid, what=""):
        """Kill a detached process and its whole tree (Windows: taskkill /T /F, Linux: its process group)."""
        if IS_WIN:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, creationflags=NO_WINDOW)
            self._append("[gui] taskkill%s: %s%s\n" % (" " + what if what else "", r.stdout.strip(), r.stderr.strip()))
        else:
            try: os.killpg(pid, signal.SIGKILL)
            except Exception as e: self._append("[gui] kill failed: %s\n" % e)
        if what: self._append("[gui] %s cancelled\n" % what)

    # ---------- process
    def _run(self, args, kind, out):
        cmd = [self.python(), "-u", "mimickit/run.py"] + args
        self._show_cmd(cmd)
        self._append("\n[gui] ===== %s  %s =====\n" % (kind.upper(), datetime.datetime.now().strftime("%H:%M:%S")))
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        log_dir = out or os.path.join(self.mk(), "output", "_launcher_" + kind)   # view / watch: their own small log folder
        try: os.makedirs(log_dir, exist_ok=True)
        except OSError: pass
        if kind == "train":
            for fn in (HIST_FILE, CONSOLE_FILE):   # fresh start / new resume folder: history restarts here
                try: os.remove(os.path.join(log_dir, fn))
                except OSError: pass
        logp = os.path.join(log_dir, CONSOLE_FILE)
        try:
            offset = os.path.getsize(logp) if os.path.exists(logp) else 0
            # detached: MimicKit writes straight into console_log.txt, so it keeps running if this window closes or crashes
            self.proc = self._spawn_detached(cmd, logp, env)
        except Exception as e:
            messagebox.showerror("Could not start", str(e)); return
        self.run_kind, self.started = kind, time.time()
        if out: self.run_dir = out
        nxt = None
        if kind == "train":
            self.live.reset(); self.live_dir = out; self.hist_n = 0
            nxt = self.tt_next or dict(base=0.0, sessions=1, parent=None); self.tt_next = None
            with self.tt_lock: self.tt = dict(nxt, dir=out, start=self.started)
            self._tt_save()
        i = proc_info(self.proc.pid) or {}
        st = dict(pid=self.proc.pid, cmd=cmd, cwd=self.mk(), kind=kind, started=self.started, proc_start=i.get("start"),
                  log=logp, offset=offset, out=out, out_rel=self.v_out.get().strip() if out else None, tt=nxt,
                  launcher_version=VERSION, started_text=datetime.datetime.now().isoformat(timespec="seconds"))
        self.state_path = os.path.join(log_dir, RUN_STATE); write_run_state(self.state_path, st)
        self.s["active_run"] = self.state_path; self._save_settings_only()
        self._append("[gui] started PID %d (detached; output -> %s)\n" % (self.proc.pid, logp))
        threading.Thread(target=self._reader, args=(self.proc, logp, offset, self.state_path), daemon=True).start()
        self._progress_tick(force=True)

    def _spawn_detached(self, cmd, logp, env):
        """Start cmd in MimicKit's folder, detached from this window, output appended (unbuffered) to logp."""
        with open(logp, "ab", buffering=0) as logf:
            return subprocess.Popen(cmd, cwd=self.mk(), stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    env=env, creationflags=DETACHED_FLAGS, start_new_session=not IS_WIN, close_fds=True)

    def _show_cmd(self, cmd, cwd=None):
        shown = " ".join('"%s"' % c if " " in c else c for c in cmd)
        self.t_cmd.configure(state="normal"); self.t_cmd.delete("1.0", "end")
        self.t_cmd.insert("end", ('cd /d "%s"\n%s' if IS_WIN else 'cd "%s"\n%s') % (cwd or self.mk(), shown)); self.t_cmd.configure(state="disabled")

    def _save_settings_only(self):
        try:
            os.makedirs(os.path.dirname(CONFIG), exist_ok=True); json.dump(self.s, open(CONFIG, "w"), indent=1)
        except OSError: pass

    def _reattach(self):
        """On startup: if a detached run from an earlier window is still running, show it again and keep tailing its log."""
        p = self.s.get("active_run"); st = read_run_state(p) if p else None
        if not st or (self.proc and self.proc.poll() is None): return False
        if not run_state_matches(st):
            if not st.get("ended"): st["ended"] = "not running at reattach"; write_run_state(p, st)
            return False
        self.proc = PidProc(st["pid"], st); self.state_path = p
        self.run_kind, self.started = st["kind"], st["started"]
        self._show_cmd(st.get("cmd", []), st.get("cwd"))
        if st.get("out"):
            self.run_dir = st["out"]
            if st.get("out_rel"): self.v_out.set(st["out_rel"])
        if st["kind"] == "train":
            self.live.reset(); self.live_dir = st["out"]; self.hist_n = 0
            nxt = st.get("tt") or dict(base=0.0, sessions=1, parent=None)
            with self.tt_lock: self.tt = dict(nxt, dir=st["out"], start=st["started"])
        self._append("\n[gui] ===== REATTACHED to running %s (PID %d, started %s) =====\n" % (
            st["kind"].upper(), st["pid"], datetime.datetime.fromtimestamp(st["started"]).strftime("%Y-%m-%d %H:%M:%S")))
        threading.Thread(target=self._reader, args=(self.proc, st["log"], st.get("offset", 0), p), daemon=True).start()
        self._progress_tick(force=True)
        return True

    def _reader(self, proc, logp, offset, state_path=None, kind=None):
        """Tails console_log.txt (written by the detached process) into the log panel and the live chart parser."""
        feed = kind is None and self.run_kind == "train"; tail = LineTail(); f = None
        def emit(lines):
            for line in lines:
                self.q.put(line)
                if feed:
                    with self.live_lock: self.live.feed(line)
        def drain(final=False):
            data = f.read() if f else b""
            emit(tail.feed(data, final)); return bool(data)
        while True:
            if f is None:
                try: f = open(logp, "rb"); f.seek(offset)
                except OSError: f = None
            alive = proc.poll() is None
            if not drain() and alive: time.sleep(0.2)
            if not alive: break
        time.sleep(0.3); drain(final=True)
        if f: f.close()
        if feed: self._tt_save(final=True)
        if state_path:
            st = read_run_state(state_path)
            if st and st.get("pid") == proc.pid:
                st["ended"] = datetime.datetime.now().isoformat(timespec="seconds"); st["exit_code"] = proc.returncode
                write_run_state(state_path, st)
        self.q.put("[gui] %sprocess ended (exit code %s)\n" % ("%s " % kind if kind else "", proc.returncode))
        if kind == "preview" and proc.returncode == 0: self._preview_finished()

    def _append(self, s):
        if not hasattr(self, "t_log"): self.q.put(s); return
        self.t_log.insert("end", s)
        if int(self.t_log.index("end-1c").split(".")[0]) > 5000: self.t_log.delete("1.0", "1000.0")
        self.t_log.see("end")

    def _pump(self):
        try:
            for _ in range(500):
                line = self.q.get_nowait(); self._append(line)
                if line.startswith("[gui] process ended"): self.root.after(50, lambda: self._progress_tick(force=True))   # save final history
        except queue.Empty: pass
        try:
            while True: self.rq.get_nowait()(); 
        except queue.Empty: pass
        self.root.after(200, self._pump)

    # ---------- progress
    def _progress_tick(self, force=False):
        if not force: self._tt_save()
        try: self._update_progress()
        except Exception as e: self.l_status.configure(text="Status error: %s" % e)
        if not force: self.root.after(10000, self._progress_tick)

    def _update_progress(self):
        running = self.proc is not None and self.proc.poll() is None
        d = self.run_dir or self.outdir_abs()
        lines = ["%s  -  %s" % ("RUNNING (%s)" % self.run_kind if running else "Not running", d)]
        same = bool(self.live_dir) and os.path.normcase(os.path.abspath(self.live_dir)) == os.path.normcase(os.path.abspath(d))
        with self.live_lock: live = {k: list(v) for k, v in self.live.data.items()}; nlive = self.live.rows()
        if same and nlive: log, src = live, "console"
        else:
            log = load_history(d)
            src = HIST_FILE if os.path.exists(os.path.join(d, HIST_FILE)) else CONSOLE_FILE if os.path.exists(os.path.join(d, CONSOLE_FILE)) else "log.txt"
        if src == "console": self.hist_n = append_history(d, live, self.hist_n)
        # earlier sessions of this run chain (original + _resumeN before d), offset so total samples keep growing
        earlier = []
        try:
            chain = run_chain(d)      # follows parent links, also into other output folders ("Continue from run")
            earlier = [h for h in (load_history(c) for c in chain[:-1]) if h.get("Samples")]
        except (ValueError, OSError):
            pass
        self.prog_frame.configure(text="Training progress (data: %s, %d points%s; refreshed every 10 s)" % (
            src, len(log.get("Samples", [])), ", +%d earlier sessions" % len(earlier) if earlier else ""))
        for ax in self._axes(): ax.clear(); self._style_ax(ax)
        ax3 = self.ax3
        off = 0.0; xmax = 0.0; sparse = 0; prev = {}   # last point of the previous session, per series
        segs = []; est_rate = 0.0                     # (cumulative samples, Train_Return) per session, for the estimate
        def bridge(ax, key, x0, y0):
            """dotted grey line from the previous session's last point to this session's first point"""
            if key in prev and x0 == x0 and y0 == y0:
                ax.plot([prev[key][0], x0], [prev[key][1], y0], color=T["dim"], alpha=0.8, linestyle=":", linewidth=1.5, gid="bridge")
        for i, h in enumerate(earlier):
            xs = [(v + off) / 1e6 for v in h["Samples"]]; nh = len(xs)
            if nh < 3: sparse += 1
            lab = "earlier sessions" if i == 0 else None
            for key in ("Train_Return", "Test_Return"):
                if h.get(key):
                    ys = h[key][:nh]; bridge(self.ax1, key, xs[0], ys[0])
                    self.ax1.plot(xs[:len(ys)], ys, color=T["dim"], alpha=0.7, marker="o", markersize=5,
                                  linewidth=1.5, label=lab if key == "Train_Return" else None, gid="earlier")
                    prev[key] = (xs[len(ys) - 1], ys[-1])
            if ax3 is not None:
                for k, ps in per_step_series(h).items():
                    ys = [v if v is not None else float("nan") for v in ps][:nh]; bridge(ax3, "ps" + k, xs[0], ys[0])
                    ax3.plot(xs[:len(ys)], ys, color=T["dim"], alpha=0.7, marker="o", markersize=4, linewidth=1.3, gid="earlier")
                    prev["ps" + k] = (xs[len(ys) - 1], ys[-1])
            r = rate_per_hour(h)[1]
            if r:
                rv = [v / 1e6 for v in r]; bridge(self.ax2, "rate", xs[0], rv[0])
                self.ax2.plot(xs[:len(rv)], rv, color=T["dim"], alpha=0.7, marker="o", markersize=5, linewidth=1.5, gid="earlier")
                prev["rate"] = (xs[len(rv) - 1], rv[-1])
            segs.append(([v + off for v in h["Samples"]], h.get("Train_Return", [])))
            est_rate = rate_per_hour(h)[0] or est_rate
            off += h["Samples"][-1]; xmax = xs[-1]          # each session's own final sample count
        if log.get("Samples"):
            S = log["Samples"]; n = len(S)
            it = int(log.get("Iteration", [n - 1])[-1]); W = log.get("Wall_Time", [0]); wall = W[-1] if W[-1] == W[-1] else 0
            rate, rates = rate_per_hour(log)
            lines.append("Iteration %d   |   samples %s%s   |   session time %s   |   speed %.2f M samples/hour   |   from %s"
                         % (it, f"{int(S[-1]):,}", " (%s in all sessions)" % f"{int(S[-1] + off):,}" if off else "",
                            str(datetime.timedelta(seconds=int(wall * 3600))), rate / 1e6, src))
            if src == "log.txt" and not (running and same):
                lines.append("Note: reading log.txt of a run this window didn't start - MimicKit writes it rarely, so it may lag the console.")
            x = [(v + off) / 1e6 for v in S]
            segs.append(([v + off for v in S], log.get("Train_Return", []))); est_rate = rate or est_rate
            for key, lab, col, g in (("Train_Return", "Train return", T["line1"], "cur1"), ("Test_Return", "Test return", T["line2"], "cur2")):
                if log.get(key):
                    bridge(self.ax1, key, x[0], log[key][0])
                    self.ax1.plot(x[:len(log[key])], log[key][:n], label=lab, color=col, marker="o", markersize=3, gid=g)
            if ax3 is not None:
                for k, ps in per_step_series(log).items():
                    ys = [v if v is not None else float("nan") for v in ps][:n]; bridge(ax3, "ps" + k, x[0], ys[0])
                    ax3.plot(x[:len(ys)], ys, color=T["line1"] if k == "Train" else T["line2"], marker="o", markersize=3,
                             gid="cur1" if k == "Train" else "cur2", label="%s per step" % k.lower())
            if rates:
                bridge(self.ax2, "rate", x[0], rates[0] / 1e6)
                self.ax2.plot(x[:len(rates)], [r / 1e6 for r in rates], color=T["line3"], marker="o", markersize=3, gid="cur3")
            if n < 2 and not earlier:   # one point: sensible x range instead of matplotlib's +-tiny default
                for ax in self._axes(): ax.set_xlim(0, max(x[-1] * 2, 0.1))
                self.ax1.text(0.02, 0.95, "only %d point so far - more appear as training runs" % n, color=T["dim"],
                              transform=self.ax1.transAxes, va="top", fontsize=8)
        elif not earlier:
            lines.append("No training data yet (waiting for the first '| Iteration |' table or log.txt rows).")
            self.ax1.text(0.5, 0.5, "waiting for data", ha="center", color=T["dim"], transform=self.ax1.transAxes)
            for ax in self._axes(): ax.set_xlim(0, 1)
        else:
            lines.append("This session has no data yet; grey = earlier sessions.")
        cur_range = None
        if self.v_cur.get() and log.get("Samples") and (earlier or len(log["Samples"]) > 1):
            cx = [(v + off) / 1e6 for v in log["Samples"]]; lo, hi = cx[0], cx[-1]; pad = max((hi - lo) * 0.03, 1e-3)
            cur_range = (lo - pad, hi + pad)
        if any(ax.get_lines() for ax in self._axes()): self._apply_view(cur_range)
        self.ax1.set_ylabel("Return"); self.ax2.set_ylabel("M samples / hour")
        lines.append(self._per_step_line(log, d))
        if ax3 is not None:
            ax3.set_ylabel("Reward / step (%)")
            if not ax3.get_lines():
                ax3.text(0.5, 0.5, "per-step score needs episode length - see Settings -> MimicKit patches...", ha="center",
                         va="center", color=T["dim"], transform=ax3.transAxes, fontsize=8)
        if self.ax1.get_lines(): self.ax1.legend(loc="lower right", fontsize=8)
        for ax in self._axes(): ax.set_xlabel("Total samples, all sessions (millions)" if ax is self._axes()[-1] else ""); self._style_ax(ax)   # after legend()
        m = os.path.join(d, "model.pt")
        if os.path.exists(m):
            age = time.time() - os.path.getmtime(m)
            lines.append("model.pt last saved %s (%d min ago)" % (time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(m))), age // 60))
        if running and self.started:
            if self.run_kind != "train":
                lines.append("Running for %s (this session, %s - not counted as training)" % (hms(time.time() - self.started), self.run_kind))
        tot, ses_t, ses = self._tt_total()
        if ses_t is not None: lines.append("Running for %s (this session)" % hms(ses_t))
        lines.append("Running for %s (total%s)" % (hms(tot), ", %d sessions" % ses if ses else "") if ses_t is not None
                     else "Total training time %s (this run + its resumes%s)" % (hms(tot), ", %d sessions" % ses if ses else ""))
        try:
            self._sync_target_widgets(d)
            if segs:
                e = estimate_progress(segs, est_rate, self._get_target(d)); txt = e["text"]
                if e["pct"] is not None and e["pct"] < 100:
                    shown = self._smooth_estimate(self._chain_key(d) + str(self._get_target(d)), e["pct"])
                    txt = re.sub(r"~?\d+%", "~%d%%" % round(shown), txt, count=1)
                lines.append(txt)
        except Exception as ex:
            lines.append("Progress estimate unavailable (%s)" % ex)
        self.l_status.configure(text="\n".join(lines))
        self.canvas.draw_idle()
        try: self._publish(lines, d, running)
        except Exception as ex: self.q.put("[remote] snapshot failed: %s\n" % ex)

    def _per_step_line(self, log, d):
        """Status line 'Avg reward per step'. Live from the console when the logging patch is in; else from log.txt."""
        def latest(h):
            vals = {}
            for k, ps in per_step_series(h).items():
                v = next((p for p in reversed(ps) if p is not None), None)
                if v is not None: vals[k] = v
            return vals
        v = latest(log); src = ""
        if not v:
            try: v = latest(parse_log(os.path.join(d, "log.txt"))); src = " (from log.txt - may lag; the logging patch makes it live)"
            except Exception: v = {}
        if not v: self.per_step = None; return "Avg reward per step: needs the logging patch - see README (Settings -> MimicKit patches...)"
        self.per_step = v
        return "Avg reward per step: %s%s" % ("   ".join("%s %.1f%%" % (k.lower(), x) for k, x in v.items()), src)

    def patch_dialog(self):
        import mimickit_patches as MP
        top = tk.Toplevel(self.root); top.title("MimicKit patches"); top.configure(bg=T["bg"])
        f = ttk.Frame(top, padding=10); f.pack(fill="both", expand=True); rows = {}
        ttk.Label(f, text="Folder: " + self.mk(), style="Dim.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        def refresh():
            for name, (lab, _) in rows.items(): lab.configure(text=MP.status(self.mk(), name))
        def act(fn, name):
            try: msg = fn(self.mk(), name)
            except Exception as e: msg = "failed: %s" % e
            self._append("[patch] %s: %s\n" % (name, msg)); refresh(); self._progress_tick(force=True)
        for i, (name, p) in enumerate(MP.PATCHES.items()):
            ttk.Label(f, text=p["title"]).grid(row=1 + 2 * i, column=0, sticky="w", pady=(8, 0))
            st = ttk.Label(f, text="", style="Good.TLabel"); st.grid(row=1 + 2 * i, column=1, padx=8, pady=(8, 0))
            b1 = ttk.Button(f, text="Apply", command=lambda n=name: act(MP.apply, n)); b1.grid(row=1 + 2 * i, column=2, pady=(8, 0))
            b2 = ttk.Button(f, text="Revert", command=lambda n=name: act(MP.revert, n)); b2.grid(row=1 + 2 * i, column=3, pady=(8, 0))
            ttk.Label(f, text="%s: %s" % (p["file"], p["why"]), style="Dim.TLabel", justify="left").grid(row=2 + 2 * i, column=0, columnspan=4, sticky="w")
            for w in (b1, b2): Tip(w, HELP["patches"])
            rows[name] = (st, p)
        ttk.Label(f, text="Changes apply to runs started afterwards; a running training keeps its old code.", style="Dim.TLabel").grid(
            row=10, column=0, columnspan=4, sticky="w", pady=(10, 0))
        refresh(); self._patch_dlg = dict(top=top, refresh=refresh, act=act)

    # ---------- phone dashboard + notifications (mimickit_remote.py)
    def _publish(self, lines, d, running):
        def series(ax):
            out = []
            for ln in ax.get_lines():
                xs, ys = [float(v) for v in ln.get_xdata()], [float(v) for v in ln.get_ydata()]
                step = max(1, len(xs) // 600)
                out.append(dict(role=ln.get_gid() or "", label=(ln.get_label() if not str(ln.get_label()).startswith("_") else None),
                                x=xs[::step] + ([xs[-1]] if xs and (len(xs) - 1) % step else []),
                                y=[None if v != v else v for v in ys[::step]] + ([ys[-1]] if ys and (len(ys) - 1) % step else [])))
            return out
        txt = "\n".join(lines)
        def grab(pat):
            m = re.search(pat, txt); return m.group(1).strip() if m else ""
        snap = dict(title="MimicKit Launcher %s - %s" % (VERSION, os.path.basename(d.rstrip("/\\"))), state=lines[0] if lines else "",
                    running=running, session_time=grab(r"Running for (\S+) \(this session") or grab(r"session time (\S+)"),
                    total_time=grab(r"Running for (\S+) \(total") or grab(r"Total training time (\S+)"),
                    samples=grab(r"samples ([\d,]+(?: \([\d,]+ in all sessions\))?)"), rate=grab(r"speed ([\d.]+ M samples/hour)"),
                    estimate=next((l for l in lines if l.startswith(("Plateau estimate", "Target"))), ""),
                    charts=dict(**{"return": series(self.ax1), "rate": series(self.ax2)}, **({"per_step": series(self.ax3)} if self.ax3 is not None else {})),
                    per_step=grab(r"Avg reward per step: ([^\n]+)"), updated=time.time(), render_msg=self.render_msg)
        v = getattr(self, "vram", None)
        if v: snap["vram"] = "%.1f / %.1f GB" % (v[0] / 1024, v[1] / 1024); snap["vram_pct"] = round(100 * v[0] / v[1])
        mp4s = glob.glob(os.path.join(d, "preview_*.mp4")) + glob.glob(os.path.join(self.mk(), "output", "*", "preview_*.mp4"))
        if mp4s:
            p = max(mp4s, key=os.path.getmtime)
            snap["preview"] = dict(path=p, name=os.path.basename(p), key="%s-%d" % (os.path.basename(p), int(os.path.getmtime(p))))
        self.snap = snap
        if self.dash: self.dash.set_snapshot(snap)
        if self.notifier.due():
            threading.Thread(target=self.notifier.send_status, args=(dict(snap),), daemon=True).start()

    def _remote_cfg(self): return self.s.setdefault("remote", {})
    def _remote_apply(self):
        """Start/stop the dashboard from the settings. Port in use etc. is logged, never fatal."""
        c = self._remote_cfg()
        want = bool(c.get("enabled")); host = c.get("host", "0.0.0.0"); port = int(c.get("port", 8765))
        if self.dash and (not want or (self.dash.host, self.dash.port) != (host, port) or self.dash.token != c.get("token")):
            self.dash.stop(); self.dash = None; self._append("[remote] dashboard stopped\n")
        if want and not self.dash:
            if not c.get("token"): c["token"] = R.new_token(); self._save_settings_only()
            try:
                self.dash = R.Dashboard(c["token"], host, port, on_render=self._remote_render, log=lambda m: self.q.put("[remote] %s\n" % m)).start()
                self.dash.set_snapshot(self.snap)
                for u in R.dashboard_urls(host, self.dash.port, c["token"])[:3]: self._append("[remote] %s\n" % u)
            except OSError as e:
                self.dash = None; self._append("[remote] could not start the dashboard on %s:%d (%s)\n" % (host, port, e))

    def _remote_render(self):
        """Called from the web server thread: never touches Tk, only queues work for the GUI thread."""
        if self.preview_proc and self.preview_proc.poll() is None: return False, "A preview is already being rendered."
        self.rq.put(self._remote_render_gui); self.render_msg = "Preview requested from the phone - rendering in the background."
        return True, "Preview started - it appears here when it is done (usually under a minute or two)."

    def _remote_render_gui(self):
        it = self._item("train"); model = self.v_model.get().strip() or self._latest_model()
        if not it or not model: self.render_msg = "No model.pt yet - nothing to preview."; self._append("[remote] %s\n" % self.render_msg); return
        self._append("[remote] preview requested from the dashboard\n")
        self._start_preview(it, model)

    def _preview_finished(self):
        self.render_msg = "Preview finished."
        c = self.s.get("notify", {})
        if c.get("send_preview") and self.notifier.targets():
            mp4s = glob.glob(os.path.join(self.mk(), "output", "*", "preview_*.mp4")) + glob.glob(os.path.join(self.mk(), "output", "*", "*", "preview_*.mp4"))
            if mp4s:
                p = max(mp4s, key=os.path.getmtime)
                threading.Thread(target=self.notifier.send, args=("New preview: %s" % os.path.basename(p),),
                                 kwargs=dict(video_path=p, kind="preview"), daemon=True).start()

    def remote_dialog(self):
        if getattr(self, "_rdlg", None) and self._rdlg.winfo_exists(): self._rdlg.lift(); return
        c = self._remote_cfg(); n = self.s.setdefault("notify", {})
        top = tk.Toplevel(self.root); top.title("Phone dashboard + notifications"); top.configure(bg=T["bg"]); self._rdlg = top
        f = ttk.Frame(top, padding=10); f.pack(fill="both", expand=True)
        v_en = tk.BooleanVar(value=bool(c.get("enabled"))); v_port = tk.StringVar(value=str(c.get("port", 8765)))
        v_host = tk.StringVar(value=c.get("host", "0.0.0.0"))
        ttk.Label(f, text="Phone dashboard", style="TLabelframe.Label").grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(f, text="Enable (read-only web page; off by default)", variable=v_en).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text="Port").grid(row=2, column=0, sticky="w"); ttk.Entry(f, textvariable=v_port, width=8).grid(row=2, column=1, sticky="w")
        ttk.Label(f, text="Listen on").grid(row=3, column=0, sticky="w")
        ttk.Combobox(f, textvariable=v_host, values=["0.0.0.0", "127.0.0.1"], state="readonly", width=12).grid(row=3, column=1, sticky="w")
        warn = ttk.Label(f, style="Dim.TLabel", wraplength=520, justify="left"); warn.grid(row=4, column=0, columnspan=3, sticky="w")
        def upd_warn(*_):
            warn.configure(text="0.0.0.0 = reachable from other devices on your networks (Tailscale, home Wi-Fi). Anyone who has the "
                           "link incl. token can watch. Never forward this port on your router - use Tailscale (docs/REMOTE_ACCESS.md)."
                           if v_host.get() == "0.0.0.0" else "127.0.0.1 = this PC only (for testing, or behind your own tunnel).")
        v_host.trace_add("write", upd_warn); upd_warn()
        urlf = ttk.Frame(f); urlf.grid(row=5, column=0, columnspan=3, sticky="we", pady=4)
        qr = tk.Canvas(f, width=180, height=180, bg="white", highlightthickness=0); qr.grid(row=1, column=3, rowspan=6, padx=10)
        qr_lab = ttk.Label(f, style="Dim.TLabel"); qr_lab.grid(row=7, column=3)
        def copy(u):
            self.root.clipboard_clear(); self.root.clipboard_append(u); self._append("[remote] link copied\n")
        def show_urls():
            try: port = int(v_port.get() or 8765)
            except ValueError: port = 8765
            items = R.dashboard_urls(v_host.get(), port, c.get("token") or "(enable to create a token)", labelled=True)
            for w in urlf.winfo_children(): w.destroy()
            for i, (lab, u) in enumerate(items):
                ttk.Label(urlf, text=lab, width=20).grid(row=i, column=0, sticky="w")
                e = ttk.Entry(urlf, width=58); e.insert(0, u); e.configure(state="readonly"); e.grid(row=i, column=1, sticky="we", padx=4)
                ttk.Button(urlf, text="Copy", width=6, command=lambda u=u: copy(u)).grid(row=i, column=2)
            qr.delete("all"); q_mod = R.load_qrcode(); self._qr_url = items[0][1] if items else ""
            if q_mod is not None and items:
                q = q_mod.QRCode(border=2); q.add_data(items[0][1]); q.make(fit=True); mtx = q.get_matrix(); k = 180 / len(mtx)
                for yy, row in enumerate(mtx):
                    for xx, on in enumerate(row):
                        if on: qr.create_rectangle(xx * k, yy * k, (xx + 1) * k, (yy + 1) * k, fill="black", outline="", tags="qr")
                qr_lab.configure(text="QR: %s" % items[0][0])
            else:
                qr.create_text(90, 90, text="pip install qrcode\nfor a QR code,\nthen press Refresh;\nor use Copy", justify="center")
                qr_lab.configure(text="")
        self._rdlg_show = show_urls
        ttk.Button(f, text="Refresh", command=lambda: show_urls()).grid(row=6, column=2, sticky="e")
        def new_tok():
            c["token"] = R.new_token(); self._save_settings_only(); show_urls(); self._remote_apply()
        ttk.Button(f, text="New token (old links stop working)", command=new_tok).grid(row=6, column=0, columnspan=2, sticky="w")
        ttk.Separator(f).grid(row=7, column=0, columnspan=4, sticky="we", pady=8)
        ttk.Label(f, text="Notifications (stored only in your local launcher settings)", style="TLabelframe.Label").grid(row=8, column=0, columnspan=3, sticky="w")
        vs = {}
        for i, (k, lab, w, hide) in enumerate((("discord_webhook", "Discord webhook URL", 60, True), ("telegram_token", "Telegram bot token", 46, True),
                                               ("telegram_chat", "Telegram chat id", 20, False), ("every_hours", "Status every N hours (0 = off)", 6, False))):
            vs[k] = tk.StringVar(value=str(n.get(k, 3 if k == "every_hours" else "")))
            ttk.Label(f, text=lab).grid(row=9 + i, column=0, sticky="w")
            ttk.Entry(f, textvariable=vs[k], width=w, show="*" if hide else "").grid(row=9 + i, column=1, columnspan=3, sticky="w")
        v_sp = tk.BooleanVar(value=bool(n.get("send_preview", False)))
        ttk.Checkbutton(f, text="Also send each new preview MP4 (skipped with a note if over the upload limit)", variable=v_sp).grid(row=13, column=0, columnspan=4, sticky="w")
        def collect():
            try: c["port"] = int(v_port.get())
            except ValueError: c["port"] = 8765
            c["enabled"] = bool(v_en.get()); c["host"] = v_host.get()
            for k, v in vs.items(): n[k] = v.get().strip()
            try: n["every_hours"] = float(n["every_hours"] or 0)
            except ValueError: n["every_hours"] = 3.0
            n["send_preview"] = bool(v_sp.get()); self._save_settings_only()
        def apply_():
            collect(); self._remote_apply(); show_urls()
        def test():
            collect()
            if not self.notifier.targets(): self._append("[notify] nothing configured\n"); return
            self._append("[notify] sending a test message...\n")
            threading.Thread(target=self.notifier.send_status, args=(dict(self.snap),), kwargs=dict(kind="test"), daemon=True).start()
        bf = ttk.Frame(f); bf.grid(row=14, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="Send test", command=test).pack(side="left", padx=4)
        ttk.Button(bf, text="Apply", command=apply_).pack(side="left", padx=4)
        ttk.Button(bf, text="Close", command=lambda: (apply_(), top.destroy())).pack(side="left", padx=4)
        show_urls(); self._rdlg_vars = dict(enabled=v_en, port=v_port, host=v_host, apply=apply_, test=test, **vs)

    # ---------- GPU
    VRAM_COLORS = dict(ok="#3f9a54", warn="#d0952c", bad="#c0392b")

    def _set_vram(self, used_mb, total_mb):
        self.vram = (float(used_mb), float(total_mb)) if used_mb is not None and total_mb else None
        self._draw_vram()

    def vram_color(self, frac):
        return self.VRAM_COLORS["ok" if frac < 0.75 else "warn" if frac <= 0.90 else "bad"]

    def _draw_vram(self):
        c = self.c_vram; c.delete("all"); w, h = int(c.cget("width")), int(c.cget("height"))
        c.configure(bg=T["bg"])
        c.create_rectangle(0, 0, w - 1, h - 1, fill=T["field"], outline=T["border"])
        if not self.vram:
            c.create_text(w / 2, h / 2, text="VRAM: no data", fill=T["dim"], font=("TkDefaultFont", 8)); return
        used, total = self.vram; frac = max(0.0, min(1.0, used / total))
        c.create_rectangle(1, 1, 1 + int((w - 3) * frac), h - 2, fill=self.vram_color(frac), outline="", tags="fill")
        c.create_text(w / 2, h / 2, text="%.1f / %.1f GB" % (used / 1024, total / 1024), fill="#f0f0f0", font=("TkDefaultFont", 8, "bold"), tags="text")

    def _gpu_poll_thread(self):
        def loop():
            while True:
                try:
                    r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                                        "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                       timeout=10, creationflags=NO_WINDOW)
                    rows = [x.split(", ") for x in r.stdout.strip().splitlines() if x.strip()]
                    txt = "   ".join("GPU %s: %s / %s MB used, %s%% busy" % (r_[0], r_[1], r_[2], r_[3]) for r_ in rows if len(r_) == 4)
                    txt = txt or "GPU: nvidia-smi gave no data"
                    ok = [r_ for r_ in rows if len(r_) == 4 and _isnum(r_[1]) and _isnum(r_[2])]
                    vr = (ok[0][1], ok[0][2]) if ok else (None, None)
                except Exception as e:
                    txt = "GPU: nvidia-smi not available (%s)" % type(e).__name__; vr = (None, None)
                self.root.after(0, lambda v=vr: self._set_vram(*v))
                self.root.after(0, lambda t=txt: self.l_gpu.configure(text=t))
                time.sleep(5)
        threading.Thread(target=loop, daemon=True).start()

    def _on_close(self):
        if self.proc and self.proc.poll() is None:
            a = messagebox.askyesnocancel("Still running", "MimicKit is still running.\n\nYes = keep it running in the background "
                                          "(reopen the launcher to see it again)\nNo = stop it and close\nCancel = don't close")
            if a is None: return
            if a: self._tt_save(); self.root.destroy(); return   # it keeps running; the next launcher window reattaches
            self.stop()
        self._tt_save(final=True)
        if self.dash: self.dash.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk(); App(root); root.mainloop()
