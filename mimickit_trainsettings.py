# MimicKit Launcher - Training settings: edit copies of a config's env/agent yaml and motion clips.
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
"""The originals are never modified. Every Save writes a NEW folder
    <MimicKit>/output/_launcher_configs/<config>/<timestamp>/  (env.yaml, agent.yaml, motions/, dataset.yaml)
plus current.json pointing at it, and the first Save also copies the untouched originals to .../originals/.
Runs started afterwards get '--env_config/--agent_config <copy>' in front of '--arg_file' (MimicKit's parser keeps
the first value of a key). A run already going keeps reading the folder it started with, which is never rewritten.
The yaml is edited line by line, so comments and layout stay as they were. No third-party modules needed."""
import datetime, json, os, pickle, re, shutil

# (key path, label, kind, hint).  kind: bool / int / float / text.  Paths with 2 parts are nested one level (agent yaml).
SECTIONS = [
    ("Episodes", "env", [
        (("episode_length",), "Episode length (s)", "float", "Longest a training episode runs before it restarts."),
        (("rand_reset",), "Random start time", "bool", "Start episodes at a random time in the clip. Off: always at the clip start."),
        (("clip_start_share",), "Starts at clip start (0-1)", "float",
         "With random start on: share of episodes that still begin at time 0. Needs the 'Clip start share' MimicKit patch."),
    ]),
    ("Early termination", "env", [
        (("enable_early_termination",), "Early termination", "bool", "End an episode early when the character falls (contact by non-contact bodies)."),
        (("pose_termination",), "Pose termination", "bool", "End an episode early when the pose drifts too far from the clip."),
        (("pose_termination_dist",), "Pose limit (m)", "float", "How far body parts may drift from the clip before pose termination."),
    ]),
    ("Learning", "agent", [
        (("discount",), "Discount", "float", "How much future reward counts (0.9-0.99). Higher = plans further ahead."),
        (("actor_optimizer", "learning_rate"), "Policy learning rate", "float", "Step size of the policy updates. Smaller = slower, steadier."),
        (("critic_optimizer", "learning_rate"), "Value learning rate", "float", "Step size of the value (critic) updates."),
        (("model", "action_std"), "Action noise", "float", "Exploration noise on the actions during training."),
        (("steps_per_iter",), "Steps per iteration", "int", "Simulation steps each env collects before every update."),
        (("actor_epochs",), "Policy epochs", "int", "Passes over each batch of data for the policy."),
        (("iters_per_output",), "Save every N iterations", "int", "How often model.pt and the log are written."),
        (("test_episodes",), "Test episodes", "int", "Episodes per evaluation (the Test_Return number)."),
    ]),
]
STUBS = [
    ("Start-speed randomization", "Start some episodes with the clip's velocities scaled up/down so the policy copes with harder entries."),
    ("Start from other animations (handoff)", "Begin episodes in the end pose of another clip, to train smooth transitions between clips."),
    ("Steering goal (walking policy)", "Give a walking policy a target direction/speed to follow instead of a fixed clip."),
    ("Curriculum", "Ramp episode length or termination limits up automatically as the score improves."),
    ("Terrain / pushes", "Uneven ground and random shoves during training for a sturdier policy."),
]
PATCH_NAME = "clipstart"     # key in mimickit_patches.PATCHES

# ---------- tiny line-based yaml access (top-level keys, or one nesting level)
_KEY = r"^(\s*)%s\s*:\s*(.*?)\s*(#.*)?$"

def _find(lines, path):
    """Index of the line holding path, or None."""
    if len(path) == 1:
        for i, l in enumerate(lines):
            if re.match(_KEY % re.escape(path[0]), l) and not l[:1].isspace(): return i
        return None
    blk = _find(lines, path[:1])
    if blk is None: return None
    for i in range(blk + 1, len(lines)):
        l = lines[i]
        if l.strip() and not l[:1].isspace() and not l.lstrip().startswith("#"): return None   # block ended
        if re.match(_KEY % re.escape(path[1]), l) and l[:1].isspace(): return i
    return None

def parse_scalar(s):
    s = s.strip().strip('"').strip("'")
    if s.lower() in ("true", "false"): return s.lower() == "true"
    try: return int(s)
    except ValueError: pass
    try: return float(s)
    except ValueError: return s

def get(text, path):
    lines = text.splitlines(); i = _find(lines, path)
    if i is None: return None
    m = re.match(_KEY % re.escape(path[-1]), lines[i]); return parse_scalar(m.group(2)) if m.group(2) else None

def fmt(v):
    if isinstance(v, bool): return "True" if v else "False"
    if isinstance(v, float): return repr(v)
    return str(v)

def set_(text, path, value):
    """Return text with path set to value (comment kept). A missing top-level key is appended."""
    nl = "\r\n" if "\r\n" in text else "\n"; lines = text.splitlines(); i = _find(lines, path)
    if i is None:
        if len(path) != 1: raise KeyError("/".join(path) + " not in this yaml")
        if lines and lines[-1].strip() == "": lines.pop()
        lines.append("%s: %s  # set by the launcher" % (path[0], fmt(value)))
    else:
        m = re.match(_KEY % re.escape(path[-1]), lines[i])
        lines[i] = "%s%s: %s%s" % (m.group(1), path[-1], fmt(value), ("  " + m.group(3)) if m.group(3) else "")
    return nl.join(lines) + nl

# ---------- motion clips
def motion_files(mk, motion_file):
    """[(relative pkl path, weight)] for a .pkl or a dataset .yaml."""
    if not motion_file: return []
    if motion_file.endswith(".pkl"): return [(motion_file, 1.0)]
    p = os.path.join(mk, motion_file)
    if not os.path.isfile(p): return []
    out, cur = [], None
    for l in open(p, encoding="utf-8"):
        m = re.match(r"\s*-?\s*file\s*:\s*[\"']?([^\"'#]+?)[\"']?\s*(#.*)?$", l)
        if m: cur = [m.group(1).strip(), 1.0]; out.append(cur); continue
        m = re.match(r"\s*weight\s*:\s*([\d.eE+-]+)", l)
        if m and cur: cur[1] = float(m.group(1))
    return [tuple(x) for x in out]

def load_clip(path):
    with open(path, "rb") as f: return pickle.load(f)

def hold_frames(frames, tol=1e-5):
    """Number of trailing frames identical (within tol) to the frame before them = the held end."""
    n = 0
    for i in range(len(frames) - 1, 0, -1):
        if max(abs(float(a) - float(b)) for a, b in zip(frames[i], frames[i - 1])) <= tol: n += 1
        else: break
    return n

def clip_info(path):
    d = load_clip(path); fr = d["frames"]; fps = float(d["fps"]); h = hold_frames(fr)
    return dict(frames=len(fr), fps=fps, length=(len(fr) - 1) / fps, hold=h / fps, loop=int(d.get("loop_mode", 0)))

def set_hold(d, seconds):
    """Copy of clip dict d with its held end set to `seconds` (trims held frames, or repeats the final pose)."""
    fr = [list(f) for f in d["frames"]]; fps = float(d["fps"])
    base = fr[:len(fr) - hold_frames(fr)]
    n = max(0, int(round(float(seconds) * fps)))
    out = dict(d); out["frames"] = base + [list(base[-1]) for _ in range(n)]
    try:
        import numpy as np                                     # keep the original array type if it was one
        if not isinstance(d["frames"], list): out["frames"] = np.asarray(out["frames"], dtype=np.asarray(d["frames"]).dtype)
    except ImportError: pass
    return out

# ---------- save / load override sets
def _safe(name): return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
def root(mk, name): return os.path.join(mk, "output", "_launcher_configs", _safe(name))
def rel(mk, p): return os.path.relpath(p, mk).replace(os.sep, "/")

def current(mk, name):
    """dict(env, agent, values, dir, saved) of the active override set, or None."""
    try:
        c = json.load(open(os.path.join(root(mk, name), "current.json"), encoding="utf-8"))
        if c.get("env") and not os.path.isfile(os.path.join(mk, c["env"])): return None
        return c
    except (OSError, ValueError): return None

def clear(mk, name):
    """Back to the original files (the saved folders stay for reference)."""
    p = os.path.join(root(mk, name), "current.json")
    if os.path.exists(p): os.replace(p, p + ".off")

def override_args(mk, name):
    c = current(mk, name)
    if not c: return []
    a = []
    if c.get("env"): a += ["--env_config", c["env"]]
    if c.get("agent"): a += ["--agent_config", c["agent"]]
    return a

def read_values(mk, env_rel, agent_rel):
    """Current values {(section kind, path): value} from the given yaml files."""
    vals = {}
    for kind, r in (("env", env_rel), ("agent", agent_rel)):
        try: txt = open(os.path.join(mk, r), encoding="utf-8").read() if r else ""
        except OSError: txt = ""
        for _, k, fields in SECTIONS:
            if k != kind: continue
            for path, *_ in fields: vals[(kind, path)] = get(txt, path) if txt else None
    return vals

def save(mk, name, env_rel, agent_rel, changes, hold=None, orig_env=None, orig_agent=None):
    """Write a new override folder. env_rel/agent_rel: the files to start from (current copies or originals).
    changes: {(kind, path): value}. hold: seconds for every clip's held end, or None to keep the clips.
    Returns the current.json dict."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S"); base = root(mk, name); d = os.path.join(base, stamp); k = 1
    while os.path.exists(d): k += 1; d = os.path.join(base, "%s-%d" % (stamp, k))
    os.makedirs(d)
    org = os.path.join(base, "originals")
    if not os.path.isdir(org):                      # one-time backup of the untouched originals
        os.makedirs(org)
        for r in (orig_env or env_rel, orig_agent or agent_rel):
            if r and os.path.isfile(os.path.join(mk, r)): shutil.copy2(os.path.join(mk, r), os.path.join(org, os.path.basename(r)))
    out = dict(dir=rel(mk, d), saved=stamp, values={}, env=None, agent=None, hold=hold)
    for kind, src in (("env", env_rel), ("agent", agent_rel)):
        if not src: continue
        txt = open(os.path.join(mk, src), encoding="utf-8", newline="").read()
        for (kd, path), v in changes.items():
            if kd == kind and v is not None:
                txt = set_(txt, path, v); out["values"]["/".join(path)] = v
        if kind == "env" and hold is not None:
            mf = get(txt, ("motion_file",))
            files = motion_files(mk, mf)
            if files:
                md = os.path.join(d, "motions"); os.makedirs(md)
                newf = []
                for i, (f, w) in enumerate(files):
                    clip = load_clip(os.path.join(mk, f))
                    moving = len(clip["frames"]) - hold_frames(clip["frames"])
                    if int(clip.get("loop_mode", 0)) == 0 and moving >= 2: clip = set_hold(clip, hold)   # looping / static clips: unchanged
                    dst = os.path.join(md, "%02d_%s" % (i, os.path.basename(f)))
                    with open(dst, "wb") as fh: pickle.dump(clip, fh)
                    newf.append((rel(mk, dst), w))
                if mf.endswith(".pkl"): new_mf = newf[0][0]
                else:
                    ds = os.path.join(d, "dataset.yaml")
                    with open(ds, "w", encoding="utf-8") as fh:
                        fh.write("motions:\n" + "".join('  - file: "%s"\n    weight: %g\n' % (f, w) for f, w in newf))
                    new_mf = rel(mk, ds)
                txt = set_(txt, ("motion_file",), '"%s"' % new_mf)
        p = os.path.join(d, kind + ".yaml")
        with open(p, "w", encoding="utf-8", newline="") as fh: fh.write(txt)
        out[kind] = rel(mk, p)
    tmp = os.path.join(base, "current.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh: json.dump(out, fh, indent=1)
    os.replace(tmp, os.path.join(base, "current.json"))
    return out
