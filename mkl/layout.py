# MimicKit Launcher - 1.0.0 page layout (user-approved redesign "Mockup D")
# Copyright (C) 2026 Ross2K. SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0 (see LICENSE).
"""Four pages (Setup / Train / Preview / Results) picked with the bottom tabs (the ONLY navigation; Ctrl+1..4), a
persistent transport strip above the tabs (Start, Resume menu, Stop after next save, STOP, progress to the plateau,
live stats, VRAM), the Results page (console, exact command, runs list) and the picture of the last preview render.
Every control of a0.9.3 still exists under the same attribute name; CONTROL_MAP says where each one lives now
(tests/v100_layout_test.py checks that every one of them is reachable)."""

import re
from mkl.core import *  # noqa: F401,F403
from mkl.window import TitleBox, flow, kscale  # noqa: F401

PAGES = ("setup", "train", "preview", "results")
PAGE_TITLE = {"setup": "Setup", "train": "Train", "preview": "Preview", "results": "Results"}
PAGE_ICON = {"setup": "\u2699", "train": "\u25b6", "preview": "\u25a3", "results": "\u2630"}
PAGE_HELP = {
    "setup": "Setup (Ctrl+1): MimicKit folder, Python venv, light mode, phone + notifications, patches, updates, About.",
    "train": "Train (Ctrl+2): what to train, the training charts, what's happening and warnings.",
    "preview": "Preview (Ctrl+3): make a preview video, the picture of the last render, watch / view live.",
    "results": "Results (Ctrl+4): the full console, the exact command and your runs (continue from one).",
}

# a0.9.3 control -> (attribute on the app, page it lives on now, had a hover help in a0.9.3)
# 'transport' = the strip above the tabs (visible on every page), 'tabbar' = the bottom bar.
CONTROL_MAP = [
    # Settings row -> Setup page
    ("MimicKit folder", "e_mk", "setup", False),
    ("MimicKit folder Browse...", "b_mk_browse", "setup", False),
    ("Python venv", "e_venv", "setup", True),
    ("Python venv Browse...", "b_venv_browse", "setup", False),
    ("Save + rescan", "b_saverescan", "setup", False),
    ("Light mode", "cb_light", "setup", True),
    ("Phone + notifications...", "b_remote", "setup", True),
    ("MimicKit patches...", "b_patches", "setup", True),
    ("About", "b_about", "setup", False),
    ("Overlay plugin buttons (Z: Check for updates...)", "plugin_frame", "setup", False),
    ("Update X available notice", "l_update", "tabbar", True),
    # What to run -> Train page, left column
    ("Training config", "cb_train", "train", True),
    ("Training config hint", "l_preset_help", "train", False),
    ("View config", "cb_view", "train", True),
    ("num_envs", "sp_envs", "train", True),
    ("Apply while training", "b_envswitch", "train", True),
    ("Output folder", "e_out", "train", True),
    ("Use Newton engine", "cb_newton", "train", True),
    ("Progress target", "cb_target", "train", True),
    ("Progress target value", "e_tval", "train", True),
    ("Progress target Set", "b_tset", "train", True),
    ("Extra args", "e_extra", "train", True),
    ("Model for Watch", "e_model", "train", True),
    ("Model for Watch Browse...", "b_model_browse", "train", False),
    ("Rescan args", "b_rescan", "train", True),
    ("Add args file...", "b_addargs", "train", True),
    ("Training settings...", "b_tsettings", "train", True),
    # run buttons -> transport strip (Start / Resume / Stop after next save / STOP), Resume menu, Preview page
    ("Start training", "run_btns.train", "transport", True),
    ("Resume training", "run_btns.resume", "transport", True),
    ("Stop after next save", "run_btns.stopsave", "transport", True),
    ("STOP", "run_btns.stop", "transport", True),
    ("Continue from run...", "run_btns.continue", "transport", True),
    ("View clip", "run_btns.view", "preview", True),
    ("Watch latest", "run_btns.watch", "preview", True),
    # Preview box -> Preview page
    ("Choose clips...", "b_clips", "preview", True),
    ("All clips", "cb_allclips", "preview", True),
    ("Clip layout", "cb_layout", "preview", True),
    ("Reference ghost", "cb_ghost", "preview", True),
    ("Preview device", "cb_pdev", "preview", True),
    ("Pause training for preview", "cb_pause", "preview", True),
    ("Render MP4", "run_btns.preview", "preview", True),
    ("Preview diagnostics", "b_pdiag", "preview", True),
    ("Cancel render", "b_stoprender", "preview", True),
    ("Render progress bar", "pv_bar", "preview", False),
    ("Render status line", "l_pvprog", "preview", False),
    # Status box
    ("Status text", "l_details", "results", False),
    ("GPU line", "l_gpu", "train", False),
    ("VRAM meter", "c_vram", "transport", True),
    # Output panel (Status / Console) -> Train right column + Results page
    ("Stage", "st_stage", "train", False),
    ("Iteration", "st_iter", "train", False),
    ("Next save bar", "st_save", "train", False),
    ("Score tile", "tiles.score", "transport", False),
    ("Speed tile", "tiles.rate", "transport", False),
    ("Episode length tile", "tiles.ep", "transport", False),
    ("Last checkpoint", "st_ckpt", "train", False),
    ("Open console (now: Results page)", "b_open_console", "train", False),
    ("What's happening", "st_events", "train", False),
    ("Warnings and errors", "st_warn", "train", False),
    ("Console", "t_log", "results", False),
    ("Exact command", "t_cmd", "results", False),
    # Charts
    ("Chart help (?)", "chart_help", "train", True),
    ("Home", "b_home", "train", True),
    ("Save picture...", "b_save", "train", True),
    ("Current session only", "cb_cursess", "train", True),
    ("Per-step chart", "cb_ps", "train", True),
    # Banner
    ("Health banner", "ban_lab", "transport", False),
    ("Hover any control = help", "ban_hint", "tabbar", False),
    ("Version", "ban_ver", "tabbar", False),
]


def resolve(app, path):
    """'run_btns.train' / 'tiles.score' / 'cb_train' -> the widget (or None)."""
    head, _, key = path.partition(".")
    w = getattr(app, head, None)
    if key and w is not None:
        w = w.get(key)
        if isinstance(w, tuple):  # tiles: (frame, title, value, sub)
            w = w[2]
    return w


class MenuItem:
    """A menu entry that looks like a button to the rest of the launcher (state / instate / invoke / cget('text')),
    so 'Continue from run...' keeps its place in run_btns after moving into the Resume menu. Geometry questions
    (winfo_*) go to the menu's button, where the entry is reached."""

    def __init__(self, menu, index, anchor, label, command):
        self.menu, self.index, self.anchor, self._label, self.command = menu, index, anchor, label, command
        self._off = False

    def state(self, spec=None):
        if spec is None:
            return ("disabled",) if self._off else ()
        for s in spec:
            if s == "disabled":
                self._off = True
            elif s == "!disabled":
                self._off = False
        self.menu.entryconfigure(self.index, state="disabled" if self._off else "normal")
        return ()

    def instate(self, spec):
        want = all((self._off if s == "disabled" else not self._off) for s in spec if s in ("disabled", "!disabled"))
        return want

    def invoke(self):
        if not self._off:
            return self.command()

    def cget(self, k):
        return self._label if k == "text" else self.anchor.cget(k)

    def configure(self, **kw):
        if "text" in kw:
            self._label = kw.pop("text")
            self.menu.entryconfigure(self.index, label=self._label)
        if kw:
            self.anchor.configure(**kw)

    config = configure

    def __getattr__(self, n):
        return getattr(self.anchor, n)


class PagesMixin:
    """The page shell: pages, bottom tabs, transport strip, Results page, last-render picture."""

    # ------------------------------------------------------------------ shell
    def _build_shell(self):
        root = self.root
        self.v_page = tk.StringVar(value="train")
        # bottom first: the tab bar, then the transport strip above it; the pages take what is left
        self._tabbar = ttk.Frame(root, padding=(10, 0, 10, 0))
        self._tabbar.pack(side="bottom", fill="x")
        ttk.Separator(root, orient="horizontal").pack(side="bottom", fill="x")
        self._transport = ttk.Frame(root, padding=(10, 6, 10, 6))
        self._transport.pack(side="bottom", fill="x")
        ttk.Separator(root, orient="horizontal").pack(side="bottom", fill="x")
        self._pages_f = ttk.Frame(root)
        self._pages_f.pack(side="top", fill="both", expand=True)
        self.pages = {n: ttk.Frame(self._pages_f, padding=(8, 8, 8, 6)) for n in PAGES}
        tb = self._tabbar
        tb.columnconfigure(0, weight=1, uniform="side")
        tb.columnconfigure(2, weight=1, uniform="side")
        self.l_runname = ttk.Label(tb, text="", style="Dim.TLabel", anchor="w")
        self.l_runname.grid(row=0, column=0, sticky="w")
        Tip(self.l_runname, "The run the charts and stats show (output folder) and its session.")
        mid = ttk.Frame(tb)
        mid.grid(row=0, column=1)
        self.tabs = {}
        for i, n in enumerate(PAGES, 1):
            f = tk.Frame(mid, cursor="hand2", bd=0, highlightthickness=0)
            f.pack(side="left")
            bar = tk.Frame(f, height=3, bd=0)
            bar.pack(side="top", fill="x")
            lab = tk.Label(f, text="%s  %s" % (PAGE_ICON[n], PAGE_TITLE[n]), padx=26, pady=7,
                           font=("Segoe UI", 10, "bold"), cursor="hand2")
            lab.pack(side="top")
            for w in (f, lab, bar):
                w.bind("<Button-1>", lambda e, n=n: self.show_page(n))
            Tip(lab, PAGE_HELP[n])
            self.tabs[n] = (f, bar, lab)
        self._tab_right = ttk.Frame(tb)
        self._tab_right.grid(row=0, column=2, sticky="e")
        for i, n in enumerate(PAGES, 1):
            # Ctrl+1..4 switch pages (window-wide; dialogs are separate windows and keep their own keys)
            root.bind("<Control-Key-%d>" % i, lambda e, n=n: (self.show_page(n), "break")[1], add="+")
            root.bind("<Control-KP_%d>" % i, lambda e, n=n: (self.show_page(n), "break")[1], add="+")

    def show_page(self, name):
        if name not in PAGES:
            return
        for n, p in self.pages.items():
            if n != name and p.winfo_manager():
                p.pack_forget()
        if not self.pages[name].winfo_manager():
            self.pages[name].pack(fill="both", expand=True)
        self.v_page.set(name)
        if hasattr(self, "v_outview"):
            self.v_outview.set("console" if name == "results" else "status")
        self._tabs_paint()
        try:
            if name == "results":
                self._runs_refresh()
                self.t_log.see("end")
            elif name == "preview":
                self._still_check(force=True)
            elif name == "train" and hasattr(self, "_top_fit"):
                self.root.after_idle(self._top_fit)
        except Exception as e:
            log_exc("page switch %s" % name, e)

    def _tabs_paint(self):
        cur = self.v_page.get() if hasattr(self, "v_page") else "train"
        bg = T["bg"]
        for n, (f, bar, lab) in getattr(self, "tabs", {}).items():
            on = n == cur
            badge = n == "train" and not on and bool(getattr(self, "cards", None))
            f.configure(bg=T["panel"] if on else bg)
            bar.configure(bg=T["accent"] if on else bg)
            lab.configure(bg=T["panel"] if on else bg, fg=T["fg"] if on else T["dim"],
                          text="%s  %s%s" % (PAGE_ICON[n], PAGE_TITLE[n], "  \u25cf" if badge else ""))
        if getattr(self, "cards", None) and "train" in getattr(self, "tabs", {}) and cur != "train":
            self.tabs["train"][2].configure(fg=T["warn"])

    # ------------------------------------------------------------------ transport strip
    def _build_transport(self):
        tp = self._transport
        self._tp_btns = ttk.Frame(tp)
        self._tp_mid = ttk.Frame(tp)
        self._tp_stats = ttk.Frame(tp)
        self._runbar = self._tp_btns
        bf = self._tp_btns
        self.run_btns = getattr(self, "run_btns", {})
        b = ttk.Button(bf, text="\u25b6 Start", command=self.train, style="Big.TButton")
        b.pack(side="left", padx=(0, 4))
        Tip(b, HELP["train"])
        self.run_btns["train"] = b
        rf = ttk.Frame(bf)
        rf.pack(side="left", padx=(0, 4))
        b = ttk.Button(rf, text="\u27f2 Resume", command=self.resume, style="Big.TButton")
        b.pack(side="left")
        Tip(b, HELP["resume"])
        self.run_btns["resume"] = b
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Resume training (newest save)", command=self.resume)
        m.add_separator()
        m.add_command(label="Continue from run\u2026", command=self.continue_from)
        self._resume_menu = m
        mb = ttk.Button(rf, text="\u25be", width=2, style="BigNarrow.TButton", command=self._post_resume_menu)
        mb.pack(side="left")
        self.b_resume_menu = mb
        Tip(mb, "More ways to resume: Resume training (newest save) or Continue from run...\n\n" + HELP["continue"])
        self.run_btns["continue"] = MenuItem(m, 2, mb, "Continue from run...", self.continue_from)
        b = ttk.Button(bf, text="Stop after next save", command=self.stop_after_save, style="Blue.TButton",
                       width=20)
        b.pack(side="left", padx=(8, 4))
        Tip(b, HELP["stopsave"])
        self.run_btns["stopsave"] = self.b_stopsave = b
        b = ttk.Button(bf, text="\u25a0 STOP", command=self.stop, style="BigStop.TButton", width=9)
        b.pack(side="left", padx=(4, 0))
        Tip(b, HELP["stop"])
        self.run_btns["stop"] = b
        # middle: health pill (banner) + estimate, progress-to-plateau bar, stop-after-save note
        mid = self._tp_mid
        top = ttk.Frame(mid)
        top.pack(side="top", fill="x")
        self._tp_top = top
        self.l_eta = ttk.Label(top, text="", style="Dim.TLabel", anchor="e")
        self.l_eta.pack(side="right", padx=(8, 0))
        Tip(self.l_eta, HELP["target"])
        self._tp_bannerhost = top
        self.tp_bar = ttk.Progressbar(mid, mode="determinate", maximum=100, style="Plateau.Horizontal.TProgressbar")
        self.tp_bar.pack(side="top", fill="x", pady=(4, 0))
        Tip(self.tp_bar, "Progress toward the plateau (or your progress target) - rough.\n\n" + HELP["target"])
        self._tp_note = ttk.Frame(mid)
        self._tp_note.pack(side="top", fill="x")
        # 'Stop after next save' status / refusal (packed only while there is something to say)
        self.l_stopsave = ttk.Label(self._tp_note, text="", style="Dim.TLabel")
        # stats: score, per-step, speed, episode, training time, GPU / VRAM
        st = self._tp_stats
        self.tiles = getattr(self, "tiles", {})
        tips = {
            "score": "Score = Train_Return (the reward per episode). Higher is better.",
            "ps": HELP["perstep"],
            "rate": "Training speed in million samples per hour.",
            "ep": "Episode length (steps per episode). Needs MimicKit patches... for the live value (else log.txt).",
            "time": "Total training time of this run and its resumes.",
        }
        for i, (k, title) in enumerate((("score", "Score"), ("ps", "Per-step"), ("rate", "Speed"),
                                        ("ep", "Episode"), ("time", "Training time"))):
            if i:
                ttk.Separator(st, orient="vertical").pack(side="left", fill="y", padx=2)
            t = tk.Frame(st, padx=9, pady=0)
            t.pack(side="left")
            b = tk.Label(t, text="-", anchor="w", font=("Segoe UI", 13, "bold"))
            a = tk.Label(t, text=title, anchor="w", font=("Segoe UI", 9))
            c = tk.Label(t, text="", anchor="w")  # sub text: shown in the hover help
            b.grid(row=0, column=0, sticky="w")
            a.grid(row=1, column=0, sticky="w")
            self.tiles[k] = (t, a, b, c)
            self._tile_tips = getattr(self, "_tile_tips", {})
            self._tile_tips[k] = tips[k]
            for w in (t, a, b):
                Tip(w, tips[k])
        ttk.Separator(st, orient="vertical").pack(side="left", fill="y", padx=2)
        g = tk.Frame(st, padx=9)
        g.pack(side="left")
        self._tp_gpu = g
        self.l_gpuname = tk.Label(g, text="GPU", anchor="w", font=("Segoe UI", 10, "bold"))
        self.l_gpuname.grid(row=0, column=0, sticky="w")
        k = kscale(self.root)
        self.c_vram = tk.Canvas(g, width=int(170 * k), height=int(16 * k), highlightthickness=0, bd=0)
        self.c_vram.grid(row=1, column=0, sticky="w", pady=(2, 0))
        vt = ("GPU memory (VRAM) used / total from nvidia-smi.\nGreen < 75 %, amber 75-90 %, red > 90 % "
              "(close to out-of-memory).")
        Tip(self.c_vram, vt)
        Tip(self.l_gpuname, vt)
        self.vram = None
        self.root.after(10, self._draw_vram)
        self._tp_mode = None
        tp.bind("<Configure>", lambda e: self._transport_layout(), add="+")
        self._transport_layout()
        self.root.after(1000, self._transport_tick)

    def _post_resume_menu(self):
        b = self.b_resume_menu
        try:
            self._resume_menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
        finally:
            try:
                self._resume_menu.grab_release()
            except tk.TclError:
                pass

    def _transport_layout(self):
        """One row when everything fits; the stats move to a 2nd row on a narrower window, and the progress area to
        its own row when even the buttons + bar don't fit (nothing is cut off at 125 %)."""
        tp = self._transport
        w = tp.winfo_width()
        if w <= 1:
            w = self.root.winfo_width()
        k = kscale(self.root)
        hint = getattr(self, "ban_hint", None)
        if hint is not None:  # narrow window: the short hint, so the version label is never cut off
            short = w < int(1400 * k)
            txt = "Hover = help \u00b7 Ctrl+1..4" if short else "Hover any control = help  \u00b7  Ctrl+1..4 = pages"
            if hint.cget("text") != txt:
                hint.configure(text=txt)
        bw, sw, mw = self._tp_btns.winfo_reqwidth(), self._tp_stats.winfo_reqwidth(), int(260 * k)
        # 1.0.0 UX: before the stats drop to a 2nd row, try them compact (smaller tiles, narrower bar) on one row
        cache = self.__dict__.setdefault("_tp_sw", {})
        cur = bool(getattr(self, "_tp_compact_on", False))
        cache[cur] = sw
        full = cache.get(False, sw)
        want = w < bw + mw + full + 40
        if want != cur:
            self._tp_compact(want)
            self._tp_mode = None
            self.root.after_idle(self._transport_layout)
            return
        if cur:
            mw = int(200 * k)
        mode = "one" if w >= bw + mw + sw + 40 else "two" if w >= bw + mw + 24 else "three"
        if mode == self._tp_mode:
            return
        self._tp_mode = mode
        for f in (self._tp_btns, self._tp_mid, self._tp_stats):
            f.grid_forget()
        for c in range(3):
            tp.columnconfigure(c, weight=0)
        if mode == "one":
            self._tp_btns.grid(row=0, column=0, sticky="w")
            self._tp_mid.grid(row=0, column=1, sticky="we", padx=(14, 14))
            self._tp_stats.grid(row=0, column=2, sticky="e")
            tp.columnconfigure(1, weight=1)
        elif mode == "two":
            self._tp_btns.grid(row=0, column=0, sticky="w")
            self._tp_mid.grid(row=0, column=1, sticky="we", padx=(14, 0))
            self._tp_stats.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
            tp.columnconfigure(1, weight=1)
        else:
            self._tp_btns.grid(row=0, column=0, sticky="w")
            self._tp_mid.grid(row=1, column=0, sticky="we", pady=(6, 0))
            self._tp_stats.grid(row=2, column=0, sticky="w", pady=(6, 0))
            tp.columnconfigure(0, weight=1)

    def _tp_compact(self, on):
        self._tp_compact_on = bool(on)
        k = kscale(self.root)
        for t, a, b, c in self.tiles.values():
            t.configure(padx=4 if on else 9)
            b.configure(font=("Segoe UI", 11 if on else 13, "bold"))
            a.configure(font=("Segoe UI", 8 if on else 9))
        self._tp_gpu.configure(padx=4 if on else 9)
        # compact: the plateau text goes on its own line under the health pill (the pill keeps its room)
        self.l_eta.pack_forget()
        bf = getattr(self, "ban_f", None)
        kw = dict(before=bf) if bf is not None else {}
        if on:
            self.l_eta.pack(side="bottom", anchor="w", padx=(8, 0), **kw)
        else:
            self.l_eta.pack(side="right", padx=(8, 0), **kw)
        self.c_vram.configure(width=int((120 if on else 170) * k))
        self.root.after_idle(self._draw_vram)

    def _transport_tick(self):
        try:
            self._transport_paint()
        except tk.TclError:
            return  # window closing
        except Exception as e:
            log_exc("transport tick", e)
        self.root.after(1000, self._transport_tick)

    def _transport_paint(self):
        ps = getattr(self, "per_step", None) or {}
        key = next((k for k in ps if k.lower().startswith("test")), next(iter(ps), None))
        if key is not None and ps.get(key) is not None:
            self._tile("ps", "%.0f %%" % ps[key], "%s per step" % key.lower())
        else:
            self._tile("ps", "-", "needs episode length (MimicKit patches...)")
        with self.tt_lock:
            live = bool(self.tt)
        tot = self._tt_total() if live else getattr(self, "_tt_last", None)
        if tot:
            self._tile("time", hms(tot[0]), "%d sessions" % tot[2] if tot[2] else "")
        e = getattr(self, "_est_last", None)
        pct = (e or {}).get("pct")
        self.tp_bar.configure(value=pct if pct is not None else 0)
        txt = (e or {}).get("text") or "Plateau: no data yet"
        txt = txt.replace("Plateau estimate: ", "Plateau: ")
        left = re.search(r"about ([^)]*?) left", txt)
        if pct is not None and left:  # 1.0.0 UX: '63 % to plateau \u00b7 ~2 h 10 m' once there is an estimate
            txt = "%d %% to plateau \u00b7 ~%s" % (round(pct), left.group(1).strip())
        if self.l_eta.cget("text") != txt:
            self.l_eta.configure(text=txt)
            Tip(self.l_eta, (e or {}).get("text", "") + "\n\n" + HELP["target"])
        k = kscale(self.root)
        room = max(int(160 * k), self._tp_top.winfo_width() // (1 if getattr(self, "_tp_compact_on", False) else 2))
        self.l_eta.configure(wraplength=room)
        d = self.run_dir or self.outdir_abs()
        name = os.path.basename((d or "").rstrip("/\\")) or "-"
        ses = tot[2] if tot else 0
        rn = "%s \u00b7 session %d" % (name, ses) if ses else name
        if self.l_runname.cget("text") != rn:
            self.l_runname.configure(text=rn)
        gn = getattr(self, "gpu_name", None) or "GPU"
        vr = self.vram
        lab = "%s \u00b7 %.0f %%" % (gn, 100.0 * vr[0] / vr[1]) if vr and vr[1] else gn
        if len(lab) > 30:
            lab = lab[:28] + "\u2026"
        if self.l_gpuname.cget("text") != lab:
            self.l_gpuname.configure(text=lab)
        self._tabs_paint()

    # ------------------------------------------------------------------ Results page
    def _build_results(self, page):
        k = kscale(self.root)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        con = TitleBox(page, text="Console", padding=(6, 4, 6, 6))
        con.grid(row=0, column=0, sticky="nsew")
        ttk.Label(con.title_row, text="  from MimicKit's console output \u00b7 live", style="Dim.TLabel").pack(side="left")
        self.con_panel = con
        hdr = ttk.Frame(con)
        hdr.pack(side="top", fill="x", pady=(0, 4))
        self.v_autoscroll = tk.BooleanVar(value=True)
        c = ttk.Checkbutton(hdr, text="Auto-scroll", variable=self.v_autoscroll,
                            command=lambda: self.v_autoscroll.get() and self.t_log.see("end"))
        c.pack(side="left")
        Tip(c, "Keep the newest console line in view. Untick to read back while training runs.")
        b = ttk.Button(hdr, text="Copy all", command=self._copy_log)
        b.pack(side="left", padx=(10, 0))
        Tip(b, "Copy the whole console to the clipboard.")
        b = ttk.Button(hdr, text="Open log folder", command=self._open_run_folder)
        b.pack(side="left", padx=(6, 0))
        Tip(b, "Open the output folder of the run (log.txt, model.pt, previews).")
        cmdf = ttk.Frame(con)
        cmdf.pack(side="bottom", fill="x", pady=(8, 0))
        ch = ttk.Frame(cmdf)
        ch.pack(fill="x")
        ttk.Label(ch, text="EXACT COMMAND (copy it into a terminal to run it yourself)", style="Sec.TLabel").pack(
            side="left")
        b = ttk.Button(ch, text="Copy command", command=self._copy_cmd)
        b.pack(side="right")
        Tip(b, "Copy the exact command (with the cd line) to the clipboard.")
        self.t_cmd = tk.Text(cmdf, height=3, width=60, wrap="word")
        self.t_cmd.pack(fill="x", pady=(4, 0))
        self.t_cmd.configure(state="disabled")
        body = ttk.Frame(con)
        body.pack(side="top", fill="both", expand=True)
        from mkl.status import MONO
        self.t_log = tk.Text(body, wrap="none", width=70, height=8, font=MONO)
        ys = ttk.Scrollbar(body, command=self.t_log.yview)
        xs = ttk.Scrollbar(body, orient="horizontal", command=self.t_log.xview)
        self.t_log.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.t_log.pack(fill="both", expand=True)
        # runs list
        rp = TitleBox(page, text="Runs", padding=(6, 4, 6, 6))
        rp.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self._runs_box = rp
        cols = ("saved", "total", "sessions")
        tv = ttk.Treeview(rp, columns=cols, show="tree headings", selectmode="browse", height=12)
        tv.heading("#0", text="Run (in output/)")
        tv.heading("saved", text="Last save")
        tv.heading("total", text="Training time")
        tv.heading("sessions", text="Sessions")
        tv.column("#0", width=int(220 * k), stretch=True)
        tv.column("saved", width=int(104 * k), stretch=False)
        tv.column("total", width=int(104 * k), stretch=False, anchor="e")
        tv.column("sessions", width=int(74 * k), stretch=False, anchor="e")
        tv.pack(side="top", fill="both", expand=True)
        self.tv_runs = tv
        Tip(tv, "Run chains under <MimicKit>/output that have a saved model.pt, newest first.")
        bb = ttk.Frame(rp)
        bb.pack(side="top", fill="x", pady=(6, 0))
        self.b_continue_sel = ttk.Button(bb, text="Continue from selected run", command=self._continue_selected)
        self.b_continue_sel.pack(side="left")
        Tip(self.b_continue_sel, HELP["continue"])
        b = ttk.Button(bb, text="Open folder", command=self._open_selected_run)
        b.pack(side="left", padx=(6, 0))
        Tip(b, "Open the selected run's folder.")
        b = ttk.Button(bb, text="Refresh", command=self._runs_refresh)
        b.pack(side="left", padx=(6, 0))
        Tip(b, "Re-read the runs list.")
        self._run_paths = {}
        ttk.Label(rp, text="RUN DETAILS", style="Sec.TLabel").pack(side="top", anchor="w", pady=(12, 2))
        self.l_details = ttk.Label(rp, text="Idle.", style="Dim.TLabel", justify="left", wraplength=int(500 * k))
        self.l_details.pack(side="top", anchor="w", fill="x")
        Tip(self.l_details, "The shown run's folder, iteration, samples, session and total training time and the "
                            "plateau estimate, as read from MimicKit's console.")
        rp.bind("<Configure>", lambda e: self.l_details.configure(wraplength=max(200, e.width - 20)), add="+")
        page.columnconfigure(1, minsize=int(540 * k))

    def _copy_text(self, txt):
        self.root.clipboard_clear()
        self.root.clipboard_append(txt)

    def _copy_log(self):
        self._copy_text(self.t_log.get("1.0", "end-1c"))

    def _copy_cmd(self):
        self._copy_text(self.t_cmd.get("1.0", "end-1c"))

    def _open_run_folder(self):
        from mkl.status import open_path
        d = self.run_dir or self.outdir_abs()
        if not open_path(d):
            messagebox.showerror("Could not open the folder", "%s\n\ndoes not exist yet." % d)

    def _runs_refresh(self):
        tv = getattr(self, "tv_runs", None)
        if tv is None:
            return
        try:
            runs = self._phone_runs() if self.mk() else []
        except Exception as e:
            log_exc("results: runs list", e)
            runs = []
        sel = self._selected_run()
        tv.delete(*tv.get_children())
        self._run_paths = {}
        for r in runs:
            nm = r["name"]
            nm = nm[len("output/"):] if nm.startswith(("output/", "output\\")) else nm  # the folder is always output/
            iid = tv.insert("", "end", text=nm, values=(r["saved"], r["total"], r["sessions"]))
            self._run_paths[iid] = r["path"]
            if sel and r["path"] == sel:
                tv.selection_set(iid)
        if not runs:  # empty state (not a run: no path, Continue says 'pick a run')
            tv.insert("", "end", text="No runs yet. Start one on the Train page.", values=("", "", ""), tags=("empty",))
            tv.tag_configure("empty", foreground=T["dim"])

    def _selected_run(self):
        tv = getattr(self, "tv_runs", None)
        s = tv.selection() if tv is not None else ()
        return self._run_paths.get(s[0]) if s else None

    def _continue_selected(self):
        p = self._selected_run()
        if not p:
            messagebox.showinfo("Continue from selected run", "Pick a run in the list first.")
            return
        self.continue_from(src=p)

    def _open_selected_run(self):
        from mkl.status import open_path
        p = self._selected_run()
        if p and not open_path(p):
            messagebox.showerror("Could not open the folder", p)

    # ------------------------------------------------------------------ last render picture (Preview page + card)
    def _ffmpeg_exe(self):
        if getattr(self, "_ffmpeg_cache", None) is not None:
            return self._ffmpeg_cache or None
        exe = shutil.which("ffmpeg") or ""
        if not exe:
            try:
                import imageio_ffmpeg  # noqa: F401 - only if the launcher's Python has it
                exe = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                exe = ""
        if not exe:  # MimicKit's venv renders previews with imageio-ffmpeg: use its bundled binary
            roots = [self.v_venv.get().strip()] if hasattr(self, "v_venv") else []
            for r in [x for x in roots if x]:
                r = r if os.path.isdir(r) else os.path.dirname(os.path.dirname(r))
                pats = [os.path.join(r, "Lib", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*"),
                        os.path.join(r, "lib", "python*", "site-packages", "imageio_ffmpeg", "binaries", "ffmpeg*")]
                hits = [p for pat in pats for p in glob.glob(pat) if not p.endswith(".txt")]
                if hits:
                    exe = hits[0]
                    break
        self._ffmpeg_cache = exe
        return exe or None

    def _newest_preview(self):
        try:
            lst = self._preview_list(self.run_dir or self.outdir_abs()) if self.mk() else []
        except Exception as e:
            log_exc("preview list", e)
            lst = []
        return lst[0] if lst else None

    def _still_check(self, force=False):
        """Every 5 s (and on opening the Preview page): newest preview MP4 -> a still frame in the background."""
        n = getattr(self, "_still_n", 0) + 1
        self._still_n = n
        if not force and n % 5 != 1:
            self._still_paint_text()
            return
        p = self._newest_preview()
        self._still_cur = p
        key = (p["path"], p["key"]) if p else None
        if key != getattr(self, "_still_key", "?"):
            self._still_key = key
            self._still_img = None
            if p:
                threading.Thread(target=self._still_worker, args=(p, key), daemon=True).start()
            self._still_paint()
        self._still_paint_text()

    def _still_worker(self, p, key):
        """Worker thread: one frame of the MP4 (at 1 s, or the first) -> PNG in output/_launcher_preview/stills.
        Never touches Tk; the GUI thread picks the result up from rq."""
        img, why = None, ""
        try:
            exe = self._ffmpeg_exe()
            if not exe:
                why = "No picture: ffmpeg not found (Open video plays it)."
            else:
                d = os.path.join(self.mk(), "output", "_launcher_preview", "stills")
                os.makedirs(d, exist_ok=True)
                out = os.path.join(d, re.sub(r"[^\w.-]", "_", p["key"]) + ".png")
                if not os.path.isfile(out):
                    for ss in ("1", "0"):
                        subprocess.run([exe, "-y", "-loglevel", "error", "-ss", ss, "-i", p["path"], "-frames:v", "1",
                                        "-vf", "scale='min(1600,iw)':-2", out], capture_output=True, timeout=30,
                                       creationflags=NO_WINDOW)
                        if os.path.isfile(out) and os.path.getsize(out) > 0:
                            break
                if os.path.isfile(out) and os.path.getsize(out) > 0:
                    img = out
                else:
                    why = "No picture: ffmpeg could not read the video."
        except Exception as e:
            log_exc("preview still", e)
            why = "No picture (%s)." % type(e).__name__
        self.rq.put(lambda: self._still_ready(key, img, why))

    def _still_ready(self, key, png, why):
        if key != getattr(self, "_still_key", None):
            return
        self._still_png, self._still_why = png, why
        self._still_img = None
        if png:
            try:
                from PIL import Image
                self._still_img = Image.open(png).convert("RGB")
            except Exception as e:
                log_exc("preview still: open", e)
                self._still_img = "tk"  # no Pillow: plain PhotoImage below
        self._still_paint()

    def _photo(self, w, h):
        """The still scaled to fit w x h (keeps its aspect)."""
        im = getattr(self, "_still_img", None)
        if im is None or w < 8 or h < 8:
            return None
        if im == "tk":
            ph = tk.PhotoImage(file=self._still_png)
            f = max(1, int(math.ceil(max(ph.width() / w, ph.height() / h))))
            return ph.subsample(f, f) if f > 1 else ph
        from PIL import ImageTk
        s = min(w / im.width, h / im.height)
        return ImageTk.PhotoImage(im.resize((max(1, int(im.width * s)), max(1, int(im.height * s)))))

    def _still_paint(self):
        p = getattr(self, "_still_cur", None)
        why = getattr(self, "_still_why", "") if p else "No preview rendered yet. Render MP4 makes one."
        if p and getattr(self, "_still_img", None) is None and not why:
            why = "Loading the picture\u2026"
        for lab, fw, fh in ((getattr(self, "l_pvimg", None), None, None), (getattr(self, "l_cardimg", None), 1, 1)):
            if lab is None:
                continue
            try:
                if fw is None:
                    host = lab.master
                    w, h = host.winfo_width() - 8, host.winfo_height() - 8
                else:
                    k = kscale(self.root)
                    w, h = int(112 * k), int(72 * k)
                ph = self._photo(w, h) if getattr(self, "_still_img", None) is not None else None
                if ph is not None:
                    lab.configure(image=ph, text="")
                else:
                    lab.configure(image="", text=why if fw is None else "\u25a3")
                lab._ph = ph
            except Exception as e:
                log_exc("preview still: paint", e)

    def _still_paint_text(self):
        p = getattr(self, "_still_cur", None)
        if p:
            try:
                age = int((time.time() - os.path.getmtime(p["path"])) // 60)
            except OSError:
                age = None
            ago = "just now" if age is not None and age < 1 else ("%d min ago" % age if age is not None and age < 120
                                                                    else p["when"])
            info = "%s \u00b7 %s \u00b7 %s MB \u00b7 %s" % (p["name"], ago, p["mb"], p["run"])
            card = "Last preview \u00b7 %s" % ago
        else:
            info, card = "No preview rendered yet", "Last preview \u00b7 none yet"
        sub = "%s \u00b7 ghost %s" % ("all clips" if self.v_allclips.get() else self.v_layout.get().lower(),
                                     self.v_ghost.get().lower())
        for attr, t in (("l_lastrender", info), ("l_cardtitle", card), ("l_cardsub", sub)):
            w = getattr(self, attr, None)
            if w is not None and w.cget("text") != t:
                w.configure(text=t)

    def _open_last_preview(self, folder=False):
        from mkl.status import open_path
        p = getattr(self, "_still_cur", None) or self._newest_preview()
        if not p:
            messagebox.showinfo("No preview yet", "No preview MP4 yet. Render MP4 makes one.")
            return
        tgt = os.path.dirname(p["path"]) if folder else p["path"]
        if not open_path(tgt):
            messagebox.showerror("Could not open", tgt)


__all__ = ["PagesMixin", "PAGES", "CONTROL_MAP", "resolve", "kscale", "MenuItem"]
