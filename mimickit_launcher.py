"""MimicKit Launcher - a small desktop GUI for running MimicKit (https://github.com/xbpeng/MimicKit).

Unofficial and unaffiliated with MimicKit. Vibe coded; see README.md.
Copyright (c) 2026 curelessSky, licensed under GPL-3.0-or-later.
Run with any Python 3.9+ that has tkinter and matplotlib:  python mimickit_launcher.py
"""
VERSION = "a0.1.5"
import codecs, json, os, queue, shlex, shutil, signal, subprocess, sys, threading, time, datetime, glob, re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

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

HELP = {
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
    "watch": "Watch latest model: shows 4 characters controlled by the newest saved model.pt (test mode).",
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
HIST_COLS = ["Iteration", "Samples", "Wall_Time", "Train_Return", "Test_Return", "Samples_Per_Second"]

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
        with open(f, "w" if new else "a") as fh:
            if new: fh.write(",".join(HIST_COLS) + "\n"); already = 0
            for i in range(already, n):
                fh.write(",".join(("%.10g" % data[k][i]) if k in data and i < len(data[k]) and data[k][i] == data[k][i] else ""
                                  for k in HIST_COLS) + "\n")
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

class Tip:
    def __init__(self, w, text):
        self.w, self.text, self.top = w, text, None
        w.bind("<Enter>", self.show); w.bind("<Leave>", self.hide)
    def show(self, _=None):
        if self.top: return
        x, y = self.w.winfo_rootx() + 10, self.w.winfo_rooty() + self.w.winfo_height() + 4
        self.top = tk.Toplevel(self.w); self.top.wm_overrideredirect(True); self.top.geometry("+%d+%d" % (x, y))
        tk.Label(self.top, text=self.text, justify="left", bg=T["tip_bg"], fg=T["tip_fg"], relief="solid", bd=1,
                 wraplength=420, padx=6, pady=4).pack()
    def hide(self, _=None):
        if self.top: self.top.destroy(); self.top = None

# ---------------------------------------------------------------- app
class App:
    def __init__(self, root):
        self.root = root; root.title("MimicKit Launcher  %s" % VERSION); root.geometry("1280x880")
        self.s = load_settings(); self.proc = None; self.q = queue.Queue()
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
                             ("resume", "Resume training", self.resume), ("watch", "Watch latest model", self.watch),
                             ("stop", "STOP", self.stop)):
            b = ttk.Button(bf, text=txt, command=fn, width=20, style="Stop.TButton" if key == "stop" else "TButton")
            b.pack(side="left", padx=3); Tip(b, HELP[key])
        b = ttk.Button(bf, text="Rescan args", command=self.rescan); b.pack(side="left", padx=(24, 3)); Tip(b, "Re-read MimicKit's args folder.")
        b = ttk.Button(bf, text="Add args file...", command=self._add_custom); b.pack(side="left", padx=3); Tip(b, HELP["custom"])
        ttk.Label(job, text="Hover over anything to see what it does.", style="Dim.TLabel").grid(row=6, column=0, columnspan=6, sticky="w")
        self.custom = list(self.s.get("custom_args", []))
        self.rescan()

        cmdf = ttk.LabelFrame(self.root, text="Exact command being run (copy it into a terminal to run it yourself)", padding=4)
        cmdf.pack(fill="x", padx=6)
        self.t_cmd = tk.Text(cmdf, height=3, width=100, wrap="word"); self.t_cmd.pack(fill="x"); self.t_cmd.configure(state="disabled")

        mid = ttk.Panedwindow(self.root, orient="horizontal"); mid.pack(fill="both", expand=True, padx=6, pady=4)
        left = ttk.Frame(mid); mid.add(left, weight=1)
        stf = ttk.LabelFrame(left, text="Status", padding=4); stf.pack(fill="x")
        self.l_status = ttk.Label(stf, text="Idle.", justify="left", font=("Segoe UI", 10) if IS_WIN else ("TkDefaultFont", 10)); self.l_status.pack(anchor="w")
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
        self.ax1 = self.fig.add_subplot(211); self.ax2 = self.fig.add_subplot(212)
        self.canvas = FigureCanvasTkAgg(self.fig, master=right); self.canvas.get_tk_widget().pack(fill="both", expand=True)
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
        for ax in (self.ax1, self.ax2): self._style_ax(ax)
        self.canvas.get_tk_widget().configure(bg=T["panel"], highlightthickness=0)
        self.canvas.draw_idle()

    def _style_ax(self, ax):
        ax.set_facecolor(T["field"])
        ax.tick_params(colors=T["fg"], labelcolor=T["fg"])
        for sp in ax.spines.values(): sp.set_color(T["border"])
        ax.xaxis.label.set_color(T["fg"]); ax.yaxis.label.set_color(T["fg"]); ax.title.set_color(T["fg"])
        ax.grid(True, color=T["grid"], alpha=0.6)
        leg = ax.get_legend()
        if leg:
            leg.get_frame().set_facecolor(T["panel"]); leg.get_frame().set_edgecolor(T["border"])
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
        try: tot, ses = chain_total([d for _, d in self._model_dirs(self.v_out.get().strip())])
        except Exception: tot, ses = 0.0, 0
        return tot, None, ses

    def _model_dirs(self, base_rel):
        """base folder + its _resumeN folders, as (N, abs path)"""
        base = self.outdir_abs(base_rel); parent, name = os.path.split(base); out = [(0, base)]
        if os.path.isdir(parent):
            for d in os.listdir(parent):
                if d.startswith(name + "_resume") and d[len(name) + 7:].isdigit():
                    out.append((int(d[len(name) + 7:]), os.path.join(parent, d)))
        return sorted(out)

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
        tot, ses = chain_total([d for _, d in dirs])
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
        self._run(["--arg_file", it["file"]] + it.get("args", []) + self.engine_args() + ["--mode", "test", "--num_envs", "4", "--visualize", "true",
                   "--model_file", mrel.replace(os.sep, "/")] + self.extra_args(), kind="watch", out=None)

    def stop(self):
        if not self.proc or self.proc.poll() is not None:
            self._append("[gui] nothing is running\n"); return
        pid = self.proc.pid; self._tt_save(final=True)
        if IS_WIN:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, creationflags=NO_WINDOW)
            self._append("[gui] taskkill: %s%s\n" % (r.stdout.strip(), r.stderr.strip()))
        else:
            try: os.killpg(pid, signal.SIGKILL)
            except Exception as e: self._append("[gui] kill failed: %s\n" % e)
        self._append("[gui] stopped. The last saved model.pt is kept.\n")

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
            with open(logp, "ab", buffering=0) as logf:
                self.proc = subprocess.Popen(cmd, cwd=self.mk(), stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                             env=env, creationflags=DETACHED_FLAGS, start_new_session=not IS_WIN, close_fds=True)
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

    def _reader(self, proc, logp, offset, state_path=None):
        """Tails console_log.txt (written by the detached process) into the log panel and the live chart parser."""
        feed = self.run_kind == "train"; tail = LineTail(); f = None
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
        self.q.put("[gui] process ended (exit code %s)\n" % proc.returncode)

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
            chain = [c for _, c in self._model_dirs(self.v_out.get().strip())]
            norm = [os.path.normcase(os.path.abspath(c)) for c in chain]
            k = norm.index(os.path.normcase(os.path.abspath(d)))
            earlier = [h for h in (load_history(c) for c in chain[:k]) if h.get("Samples")]
        except (ValueError, OSError):
            pass
        self.prog_frame.configure(text="Training progress (data: %s, %d points%s; refreshed every 10 s)" % (
            src, len(log.get("Samples", [])), ", +%d earlier sessions" % len(earlier) if earlier else ""))
        self.ax1.clear(); self.ax2.clear(); self._style_ax(self.ax1); self._style_ax(self.ax2)
        off = 0.0; xmax = 0.0; sparse = 0; prev = {}   # last point of the previous session, per series
        def bridge(ax, key, x0, y0):
            """dotted grey line from the previous session's last point to this session's first point"""
            if key in prev and x0 == x0 and y0 == y0:
                ax.plot([prev[key][0], x0], [prev[key][1], y0], color=T["dim"], alpha=0.7, linestyle=":", linewidth=1.3, gid="bridge")
        for i, h in enumerate(earlier):
            xs = [(v + off) / 1e6 for v in h["Samples"]]; nh = len(xs)
            if nh < 3: sparse += 1
            lab = ("earlier sessions" + (" (pre-a0.1.3: few points)" if any(len(e["Samples"]) < 3 for e in earlier) else "")) if i == 0 else None
            for key in ("Train_Return", "Test_Return"):
                if h.get(key):
                    ys = h[key][:nh]; bridge(self.ax1, key, xs[0], ys[0])
                    self.ax1.plot(xs[:len(ys)], ys, color=T["dim"], alpha=0.6, marker="o", markersize=5,
                                  linewidth=1.5, label=lab if key == "Train_Return" else None)
                    prev[key] = (xs[len(ys) - 1], ys[-1])
            r = rate_per_hour(h)[1]
            if r:
                rv = [v / 1e6 for v in r]; bridge(self.ax2, "rate", xs[0], rv[0])
                self.ax2.plot(xs[:len(rv)], rv, color=T["dim"], alpha=0.6, marker="o", markersize=5, linewidth=1.5)
                prev["rate"] = (xs[len(rv) - 1], rv[-1])
            off += h["Samples"][-1]; xmax = xs[-1]          # each session's own final sample count
        if sparse:
            lines.append("Note: %d earlier session(s) have only 1-2 points - sessions run before a0.1.3 only left MimicKit's "
                         "log.txt (written rarely), so their sample counts and x positions are too low." % sparse)
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
            for key, lab, col in (("Train_Return", "Train return", T["line1"]), ("Test_Return", "Test return", T["line2"])):
                if log.get(key):
                    bridge(self.ax1, key, x[0], log[key][0])
                    self.ax1.plot(x[:len(log[key])], log[key][:n], label=lab, color=col, marker="o", markersize=3)
            if rates:
                bridge(self.ax2, "rate", x[0], rates[0] / 1e6)
                self.ax2.plot(x[:len(rates)], [r / 1e6 for r in rates], color=T["line3"], marker="o", markersize=3)
            if n < 2 and not earlier:   # one point: sensible x range instead of matplotlib's +-tiny default
                for ax in (self.ax1, self.ax2): ax.set_xlim(0, max(x[-1] * 2, 0.1))
                self.ax1.text(0.02, 0.95, "only %d point so far - more appear as training runs" % n, color=T["dim"],
                              transform=self.ax1.transAxes, va="top", fontsize=8)
        elif not earlier:
            lines.append("No training data yet (waiting for the first '| Iteration |' table or log.txt rows).")
            self.ax1.text(0.5, 0.5, "waiting for data", ha="center", color=T["dim"], transform=self.ax1.transAxes)
            for ax in (self.ax1, self.ax2): ax.set_xlim(0, 1)
        else:
            lines.append("This session has no data yet; grey = earlier sessions.")
        self.ax1.set_ylabel("Return"); self.ax2.set_ylabel("M samples / hour")
        for ax in (self.ax1, self.ax2): ax.set_xlabel("Total samples, all sessions (millions)"); self._style_ax(ax)
        if self.ax1.get_lines(): self.ax1.legend(loc="lower right", fontsize=8)
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
        self.l_status.configure(text="\n".join(lines))
        self.canvas.draw_idle()

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
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk(); App(root); root.mainloop()
