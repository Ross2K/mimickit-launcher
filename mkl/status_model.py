# MimicKit Launcher - status model: turns MimicKit's console output into plain-language status.
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
"""Pure logic, no GUI (tested directly):
StatusModel  - fed console text; tracks stage, iteration, scores, speed, events, warnings and errors.
health()     - the one-line health banner: (level, text).
diagnose()   - known failures -> error cards (what happened, is training safe, one fix).
All user-facing text is in BANNER and CARDS so it can be reviewed in one place (docs: launcher_error_messages.md).
"""

import math, os, re, time

# ---------------------------------------------------------------- banner texts
BANNER = {
    "idle": ("idle", "Idle - nothing is running."),
    "starting": ("info", "Starting: {stage}."),
    "healthy": ("ok", "Training normally - iteration {it}, {rate}."),
    "healthy_norate": ("ok", "Training normally - iteration {it}."),
    "watching": ("info", "{kind} is running."),
    "quiet": (
        "warn",
        "No new output for {mins} min - MimicKit may be stuck. Training is still running.",
    ),
    "slow": (
        "warn",
        "Training slowed to {pct}% of its usual speed ({rate}). Is something else using the GPU?",
    ),
    "error": (
        "error",
        "Training stopped with an error. Your saved progress is safe; see below.",
    ),
    "crashed": (
        "error",
        "Training stopped unexpectedly. Your saved progress (model.pt) is kept.",  # code: banner_detail()
    ),
    "stopped": ("idle", "Stopped by you. Your saved progress (model.pt) is kept."),
    "finished": ("ok", "Finished - the last model was saved at iteration {it}."),
    "finished_noit": ("ok", "Finished. Your saved progress (model.pt) is in the output folder."),
    "closed": ("idle", "{kind} closed."),
    "failed": ("error", "{kind} stopped with an error - see the card below."),
    "trained": (
        "ok",
        "Looks trained - the score has levelled off. You can stop or keep polishing.",
    ),
}

# ---------------------------------------------------------------- error cards
# what: what happened (plain words; codes go in detail). safe: is training still OK. detail: grey line with the
# technical bits. fix: (button label, action id). First mention: "your saved progress (model.pt)", then "saved progress".
CARDS = {
    "cpu_preview_crash": dict(
        title="The preview crashed on the CPU",
        what="Windows stopped the CPU preview with a crash that happens on some PCs.",
        safe="Training is safe: previews run in their own process.",
        detail="Error code 0xC0000005 (access violation), a known problem with CPU-only previews.",
        fix=("Use the GPU for previews", "preview_gpu"),
    ),
    "cuda_oom": dict(
        title="The GPU ran out of memory",
        what="MimicKit needed more video memory than the card has. This usually means the number of practice "
        "characters (num_envs) is too high for this GPU.",
        safe="Training stopped. Your saved progress (model.pt) is safe.",
        safe_running="Training is still running but may fail. Your saved progress (model.pt) is safe; the button "
        "below restarts from the next save with fewer practice characters.",
        detail="CUDA out of memory",
        fix=("Lower to {n} and resume", "halve_envs"),
    ),
    "no_model": dict(
        title="No saved model yet",
        what="There is no saved progress (model.pt) in {folder} yet. MimicKit saves it every {ipo} iterations "
        "of training.",
        safe="Nothing is broken, and any running training is unaffected.",
        fix=("Pick a model...", "pick_model"),
    ),
    "bad_yaml": dict(
        title="A config file has a typo",
        what="{file} could not be read{where}: {problem}.",
        safe="Training didn't start, so nothing changed.",
        fix=("Open the file", "open_file"),
    ),
    "mk_missing": dict(
        title="MimicKit folder not found",
        what="There is no mimickit/run.py in {folder}.",
        safe="Nothing is running, and your runs and saved progress are untouched.",
        fix=("Choose folder...", "choose_mk"),
    ),
}

LOOKS_TRAINED = dict(
    title="Looks trained",
    what="The score has levelled off near {a} - more training will only change it a little.",
    safe="Training keeps running until you stop it. A preview shows how it moves now.",
    actions=[
        ("Render preview", "preview"),
        ("Stop training", "stop"),
        ("Keep training", "dismiss"),
    ],
    ping="Looks trained: {name} levelled off near {a} after {time}. Stop it or keep going - your choice.",
)

# ---------------------------------------------------------------- console parsing
_STAGES = [  # (regex, stage text, plain event or None)
    (r"^Setting seed", "starting up", None),
    (r"^Building (\w+) env\b", "building the simulation", None),
    (r"^Warp [\d.]+ initialized", "starting the physics engine", None),
    (r"^Loading (\d+)/(\d+) motion files", "loading motion clips", None),
    (
        r"^Loaded (\d+) motions? with a total length of ([\d.]+)s",
        "loading motion clips",
        "Loaded {0} motion clip(s), {1} s in total.",
    ),
    (r"^Initializing simulation", "starting the physics engine", None),
    (
        r"^Module .* load on device '(\w+)' took .*\(compiled\)",
        "compiling GPU code (first run: a few minutes)",
        None,
    ),
    (r"^Building (\w+) agent", "building the policy", None),
    (r"^Total parameter count: (\d+)", "building the policy", "Policy built ({0:,} parameters)."),
    (r"^Logging data to (.+)$", "training", "Training started - logging to {0}."),
]
_ROW = re.compile(r"^\|\s*([A-Za-z_]+)\s*\|\s*([-+\d.eE]+|nan|inf)\s*\|")
_WARN = re.compile(r"warn(ing)?\b", re.I)  # also UserWarning, FutureWarning, [Warning], WARNING:
_ERR = re.compile(
    r"(Traceback \(most recent call last\)|^\w*(Error|Exception)\b|^RuntimeError|CUDA error|out of memory)",
    re.I,
)
_NOISE = re.compile(
    r"FutureWarning: `torch\.jit\.script` is deprecated|^\s*warnings\.warn\(|Warp CUDA warning: Could not find"
)


def fmt_rate(r):
    return "%.1f M samples/hour" % (r / 1e6) if r else ""


class StatusModel:
    PROGRESS_EVERY = 100  # a "what's happening" line every this many iterations
    BEST_TEST_GAP = 50  # at most one "new best test score" line per this many iterations

    def __init__(self, ipo=None):
        self.reset(ipo)

    def reset(self, ipo=None, kind="train"):
        self.kind = kind
        self.stage = "waiting to start"
        self.stats = {}  # latest console table values
        self.iteration = None
        self.samples = None
        self.rates = []  # recent M samples/hour from consecutive rows
        self.events = []  # (time, plain text)
        self.warnings = []  # (time, line, count)
        self.errors = []  # (time, line)
        self.text = ""  # recent raw output (for diagnose)
        self.last_output = None
        self.exit_code = None
        self.stopped_by_user = False
        self.started = time.time()
        self.ipo = ipo
        self._buf = ""
        self._prev = None  # (samples, wall_time_h) of the previous row
        self._best_test = None  # (score, iteration of the last "new best" event)

    # -- feeding
    def feed(self, chunk, now=None):
        now = now or time.time()
        self._buf += chunk
        *lines, self._buf = self._buf.replace("\r", "\n").split("\n")
        for ln in lines:
            self._line(ln, now)

    def _event(self, text, now):
        if not self.events or self.events[-1][1] != text:
            self.events.append((now, text))
            del self.events[:-12]

    def _line(self, ln, now):
        s = ln.strip()
        if not s:
            return
        if s.startswith("[gui]") or s.startswith("[remote]") or s.startswith("[patch]"):
            m = re.search(r"process ended \(exit code (-?\d+|None)\)", s)
            if m and not s.startswith("[gui] preview"):
                self.exit_code = int(m.group(1)) if m.group(1) != "None" else None
                self._event(self.ended_text(), now)
            return
        self.last_output = now
        self.text = (self.text + ln + "\n")[-60000:]
        m = _ROW.match(s)
        if m:
            k, v = m.group(1), float(m.group(2))
            self.stats[k] = v
            if k == "Iteration":
                first = self.iteration is None
                prev = self.iteration if not first else 0
                self.iteration = int(v)
                self.stage = "training"
                if first:
                    self._event("First training iteration done.", now)
                elif self.iteration // self.PROGRESS_EVERY > prev // self.PROGRESS_EVERY:
                    self._event(self._progress_text(), now)
                if self.ipo and self.iteration % self.ipo == 0:
                    self._event("Model saved (iteration %d)." % self.iteration, now)
            elif k == "Test_Return" and v == v and self.iteration is not None:
                self._test_score(v, now)
            elif k == "Samples":
                self.samples = v
                wt = self.stats.get("Wall_Time")
                if self._prev and wt and wt > self._prev[1] and v > self._prev[0]:
                    self.rates.append((v - self._prev[0]) / (wt - self._prev[1]))
                    del self.rates[:-30]
                if wt:
                    self._prev = (v, wt)
            return
        for rx, stage, ev in _STAGES:
            m = re.search(rx, s)
            if m:
                self.stage = stage
                if ev:
                    g = [int(x) if x.isdigit() else x for x in m.groups()]
                    self._event(ev.format(*g), now)
                break
        if _NOISE.search(s):
            return
        if _ERR.search(s):
            self.errors.append((now, s[:300]))
            del self.errors[:-20]
            if self.kind == "train" and "Traceback" not in s:
                self._event("Error: " + s[:160], now)
        elif _WARN.search(s):
            for i, (t, l, c) in enumerate(self.warnings):
                if l == s[:300]:
                    self.warnings[i] = (now, l, c + 1)
                    break
            else:
                self.warnings.append((now, s[:300], 1))
                del self.warnings[:-20]

    def _progress_text(self):
        st = self.stats
        tr, te = st.get("Train_Return"), st.get("Test_Return")
        score = "" if tr is None else ": score %.3g" % tr + ("" if te is None else " (test %.3g)" % te)
        return "Iteration %d%s." % (self.iteration, score)

    def _test_score(self, v, now):
        best = self._best_test
        if best is None:
            self._best_test = (v, self.iteration)
        elif v > best[0]:
            if self.iteration - best[1] >= self.BEST_TEST_GAP:
                self._event("New best test score: %.3g (iteration %d)." % (v, self.iteration), now)
                self._best_test = (v, self.iteration)
            else:
                self._best_test = (v, best[1])

    def note_save(self, now=None):
        """The launcher saw model.pt change on disk. Only needed when iters_per_output is unknown (else the
        console already gave 'Model saved (iteration N)')."""
        if self.ipo:
            return
        it = " (iteration %d)" % self.iteration if self.iteration is not None else ""
        self._event("Progress saved%s." % it, now or time.time())

    # -- derived
    def rate(self):
        """Samples per hour (median of recent rows)."""
        if not self.rates:
            return None
        r = sorted(self.rates[-9:])
        return r[len(r) // 2]

    def usual_rate(self):
        if len(self.rates) < 12:
            return None
        r = sorted(self.rates[:-3])
        return r[len(r) // 2]

    def next_save(self):
        """(iterations done since the last save, iterations per save) or None."""
        if not self.ipo or self.iteration is None:
            return None
        return self.iteration % self.ipo, self.ipo

    def last_save_iteration(self):
        if not self.ipo or self.iteration is None:
            return None
        return self.iteration - self.iteration % self.ipo

    def ended_text(self):
        if self.stopped_by_user:
            return "Stopped by you."
        if self.exit_code == 0:
            return "Finished."
        return "MimicKit stopped (exit code %s)." % self.exit_code

    def tiles(self):
        st = self.stats
        ep = st.get("Train_Episode_Length")
        return dict(
            score=(st.get("Train_Return"), st.get("Test_Return")),
            rate=self.rate(),
            ep_len=ep,
        )


_KIND = {"watch": "Watch", "view": "Clip playback"}


def health(m, running, now=None, looks_trained=False, quiet_after=300):
    """(level, text) for the banner. level: idle / info / ok / warn / error."""
    now = now or time.time()

    def b(key, **kw):
        lvl, t = BANNER[key]
        return lvl, t.format(**kw)

    if not running:
        if m.exit_code is None and not m.stopped_by_user:
            return b("idle")
        if m.kind != "train":
            k = _KIND.get(m.kind, m.kind.title())
            return b("failed", kind=k) if diagnose_text(m.text) else b("closed", kind=k)
        if m.stopped_by_user:
            return b("stopped")
        if m.exit_code == 0:
            it = m.last_save_iteration() if m.last_save_iteration() is not None else m.iteration
            return b("finished", it=it) if it is not None else b("finished_noit")
        if diagnose_text(m.text):
            return b("error")
        return b("crashed", code=m.exit_code)
    if m.kind != "train":
        return b("watching", kind=_KIND.get(m.kind, m.kind.title()))
    quiet = now - (m.last_output or m.started)
    limit = quiet_after * (3 if m.stage.startswith("compiling") or m.iteration is None else 1)
    if quiet > limit:
        return b("quiet", mins=int(quiet // 60))
    if m.iteration is None:
        return b("starting", stage=m.stage)
    r, u = m.rate(), m.usual_rate()
    if r and u and r < 0.5 * u:
        return b("slow", pct=int(100 * r / u), rate=fmt_rate(r))
    if looks_trained:
        return b("trained")
    return (
        b("healthy", it=m.iteration, rate=fmt_rate(r)) if r else b("healthy_norate", it=m.iteration)
    )


# ---------------------------------------------------------------- diagnosis
_OOM = re.compile(
    r"CUDA out of memory|torch\.(cuda\.)?OutOfMemoryError|cudaErrorMemoryAllocation|CUDA error: out of memory|"
    r"Warp CUDA error.*out of memory|failed to allocate .* on device 'cuda",
    re.I,
)
_YAML = re.compile(
    r"yaml\.(scanner|parser|constructor|composer)\.\w+Error|while (scanning|parsing) a", re.I
)
_YAML_AT = re.compile(r'in "([^"]+)", line (\d+), column (\d+)')
_ACCESS = re.compile(r"exit code (3221225477|-1073741819)\b|0xC0000005", re.I)
_NO_MODEL = re.compile(r"(No such file or directory|FileNotFoundError).*model[^/\\'\"]*\.pt", re.I)
_NO_RUN = re.compile(r"(can't open file|No such file or directory:).*mimickit[/\\]+run\.py", re.I)


def diagnose_text(text):
    """Card ids for failures recognisable in console text (newest first, no duplicates)."""
    out = []
    if _OOM.search(text):
        out.append("cuda_oom")
    if _YAML.search(text):
        out.append("bad_yaml")
    if _NO_MODEL.search(text):
        out.append("no_model")
    if _NO_RUN.search(text):
        out.append("mk_missing")
    return out


def yaml_problem(text):
    """(file, line, problem) from a PyYAML error in console text."""
    lines = text.splitlines()
    prob, f, ln = "", "", None
    for i, l in enumerate(lines):
        if _YAML.search(l):
            prob = l.split(":", 1)[-1].strip() or l.strip()
            for l2 in lines[i : i + 8]:
                m = _YAML_AT.search(l2)
                if m:
                    f, ln = m.group(1), int(m.group(2))
                if re.match(r"^\s*(found|expected|mapping values|could not)", l2):
                    prob = l2.strip()
    return f, ln, prob


def card(cid, **ctx):
    """Filled-in card dict: title, what, safe, fix_label, fix (action id)."""
    c = CARDS[cid]
    safe = c.get("safe_running") if ctx.get("running") and c.get("safe_running") else c["safe"]
    lab, act = c["fix"]
    fmt = dict(
        n=ctx.get("n", "fewer"),
        folder=ctx.get("folder", "the output folder"),
        ipo=ctx.get("ipo") or "few",
        file=ctx.get("file") or "a config file",
        where=(" (line %d)" % ctx["line"]) if ctx.get("line") else "",
        problem=ctx.get("problem") or "it is not valid YAML",
    )
    return dict(
        id=cid,
        title=c["title"],
        what=c["what"].format(**fmt),
        safe=safe,
        detail=c.get("detail", ""),
        fix_label=lab.format(**fmt),
        fix=act,
    )


def banner_detail(m, running):
    """Grey detail next to the banner: the raw exit code of an unexplained crash (hex for Windows NTSTATUS codes)."""
    if running or m.kind != "train" or m.stopped_by_user or m.exit_code in (None, 0) or diagnose_text(m.text):
        return ""
    c = m.exit_code
    return "exit code 0x%08X" % (c & 0xFFFFFFFF) if abs(c) > 0xFFFF else "exit code %d" % c


def halve_envs(n):
    """Next num_envs to try after running out of GPU memory (half, rounded down to a multiple of 64, at least 64)."""
    return max(64, int(n) // 2 // 64 * 64)
