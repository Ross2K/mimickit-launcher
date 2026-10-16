# MimicKit Launcher - main window
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
from mkl.core import *  # noqa: F401,F403 - shared helpers/constants
from mkl.core import __all__ as _core_names  # noqa: F401


class MainWindowMixin:
    """Main window: layout, theme, dialogs, log panel, GPU/VRAM meter, closing."""

    VRAM_COLORS = dict(ok="#3f9a54", warn="#d0952c", bad="#c0392b")

    def _build(self):
        """The main window, top to bottom: banner, settings row, what to run, status + cards + output | charts."""
        self._build_banner()  # health banner, version on its right
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        self._build_settings(top)
        self._build_job(top)
        mid = ttk.Panedwindow(self.root, orient="horizontal")
        mid.pack(fill="both", expand=True, padx=6, pady=4)
        left = ttk.Frame(mid)
        mid.add(left, weight=1)
        self._build_status(left)
        self._build_cards(left)
        self._build_output(left)
        self._build_charts(mid)
        self.apply_theme()

    def _build_settings(self, top):
        """Settings row: MimicKit folder, venv, light mode, phone, patches, About."""
        st = ttk.LabelFrame(top, text="Settings", padding=6)
        st.pack(fill="x")
        self.v_mk = tk.StringVar(value=self.s.get("mimickit", ""))
        self.v_venv = tk.StringVar(value=self.s.get("venv", ""))
        for r, (lab, var) in enumerate(
            (
                ("MimicKit folder", self.v_mk),
                ("Python venv", self.v_venv),
            )
        ):
            lw = ttk.Label(st, text=lab)
            lw.grid(row=r, column=0, sticky="w")
            ttk.Entry(st, textvariable=var, width=40).grid(row=r, column=1, sticky="we", padx=4)
            if var is self.v_venv:
                Tip(
                    lw,
                    "A venv folder or a python executable. Empty = the Python running this launcher.",
                )
            ttk.Button(st, text="Browse...", command=lambda v=var: self._browse(v)).grid(
                row=r, column=2
            )
        st.columnconfigure(1, weight=1)
        ttk.Button(st, text="Save + rescan", command=lambda: (self._save(), self.rescan())).grid(
            row=0, column=3, rowspan=2, padx=8
        )
        self.v_light = tk.BooleanVar(value=bool(self.s.get("light_mode", False)))
        cbx = ttk.Checkbutton(
            st, text="Light mode", variable=self.v_light, command=self._toggle_theme
        )
        cbx.grid(row=0, column=4, rowspan=2, padx=8)
        Tip(
            cbx,
            "Dark mode is the default (easy on OLED screens). Tick for a light theme. Saved automatically.",
        )
        b = ttk.Button(st, text="Phone + notifications...", command=self.remote_dialog)
        b.grid(row=0, column=5, padx=4)
        b2 = ttk.Button(st, text="MimicKit patches...", command=self.patch_dialog)
        b2.grid(row=1, column=5, padx=4)
        Tip(b2, HELP["patches"])
        b3 = ttk.Button(st, text="About", command=self.about_dialog)
        b3.grid(row=1, column=4, padx=8)
        cbx.grid_configure(row=0, rowspan=1)
        Tip(b, HELP["remote"])

    def _build_job(self, top):
        """'What to run': configs, num_envs, output folder, run buttons, preview options."""
        job = ttk.LabelFrame(top, text="What to run", padding=6)
        job.pack(fill="x", pady=4)
        self.v_train = tk.StringVar()
        self.v_view = tk.StringVar()
        ttk.Label(job, text="Training config").grid(row=0, column=0, sticky="w")
        self.cb_train = ttk.Combobox(job, textvariable=self.v_train, state="readonly", width=40)
        self.cb_train.grid(row=0, column=1, sticky="w")
        self.cb_train.bind("<<ComboboxSelected>>", self._train_changed)
        Tip(self.cb_train, HELP["trainsel"])
        ttk.Label(job, text="View config").grid(row=0, column=2, sticky="e", padx=(12, 0))
        self.cb_view = ttk.Combobox(job, textvariable=self.v_view, state="readonly", width=34)
        self.cb_view.grid(row=0, column=3, sticky="w")
        Tip(self.cb_view, HELP["viewsel"])
        self.l_preset_help = ttk.Label(job, text="", style="Dim.TLabel", wraplength=1100)
        self.l_preset_help.grid(row=1, column=0, columnspan=6, sticky="w")
        ttk.Label(job, text="num_envs").grid(row=2, column=0, sticky="w")
        self.v_envs = tk.IntVar(value=DEFAULT_ENVS)
        sp = ttk.Spinbox(job, from_=1, to=65536, increment=512, textvariable=self.v_envs, width=8)
        sp.grid(row=2, column=1, sticky="w")
        Tip(sp, HELP["envs"])
        sw = ttk.Frame(job)
        sw.grid(row=2, column=1, sticky="e")
        self.b_envswitch = ttk.Button(sw, text="Apply while training", command=self.change_envs_live)
        self.b_envswitch.pack(side="left")
        Tip(self.b_envswitch, HELP["envs_live"])
        self.l_envswitch = ttk.Label(job, text="", style="Dim.TLabel")
        self.l_envswitch.grid(row=7, column=0, columnspan=6, sticky="w")
        self.l_stopsave = ttk.Label(job, text="", style="Dim.TLabel")
        self.l_stopsave.grid(row=8, column=0, columnspan=6, sticky="w")
        ttk.Label(job, text="Output folder").grid(row=2, column=2, sticky="e")
        self.v_out = tk.StringVar()
        e = ttk.Entry(job, textvariable=self.v_out, width=36)
        e.grid(row=2, column=3, sticky="w", padx=4)
        Tip(e, HELP["out"])
        self.v_newton = tk.BooleanVar(value=bool(self.s.get("force_newton", True)))
        c = ttk.Checkbutton(
            job, text="Use Newton engine", variable=self.v_newton, command=self._save
        )
        c.grid(row=2, column=4, columnspan=2, sticky="w")
        Tip(c, HELP["newton"])
        ttk.Label(job, text="Extra args").grid(row=3, column=0, sticky="w")
        self.v_extra = tk.StringVar()
        e = ttk.Entry(job, textvariable=self.v_extra, width=60)
        e.grid(row=3, column=1, columnspan=3, sticky="we", pady=2)
        Tip(e, HELP["extra"])
        ttk.Label(job, text="Model for Watch").grid(row=4, column=0, sticky="w")
        self.v_model = tk.StringVar()
        e = ttk.Entry(job, textvariable=self.v_model, width=60)
        e.grid(row=4, column=1, columnspan=3, sticky="we")
        Tip(e, HELP["model"])
        ttk.Button(job, text="Browse...", command=self._browse_model).grid(
            row=4, column=4, sticky="w", padx=6
        )
        bf = ttk.Frame(job)
        bf.grid(row=5, column=0, columnspan=6, sticky="w", pady=(6, 0))
        for key, txt, fn in (
            ("view", "View clip", self.view),
            ("train", "Start training", self.train),
            ("resume", "Resume training", self.resume),
            ("continue", "Continue from run...", self.continue_from),
            ("watch", "Watch latest", self.watch),
            ("preview", "Render MP4", self.preview),
            ("stopsave", "Stop after next save", self.stop_after_save),
            ("stop", "STOP", self.stop),
        ):
            b = ttk.Button(
                bf,
                text=txt,
                command=fn,
                width=max(10, len(txt) + 2),
                style="Stop.TButton" if key == "stop" else "TButton",
            )
            b.pack(side="left", padx=3)
            Tip(b, HELP[key])
            self.run_btns = getattr(self, "run_btns", {})
            self.run_btns[key] = b
            if key == "stopsave":
                self.b_stopsave = b
        bf2 = ttk.Frame(job)
        bf2.grid(row=6, column=0, columnspan=6, sticky="w", pady=(4, 0))
        bfa = ttk.Frame(bf2)  # args/settings buttons (+ profile ACTIONS)
        bfa.pack(side="top", anchor="w")
        bfb = ttk.Frame(bf2)  # preview options on their own line so nothing is clipped at 1280 px
        bfb.pack(side="top", anchor="w", pady=(4, 0))
        b = ttk.Button(bfa, text="Rescan args", command=self.rescan)
        b.pack(side="left", padx=3)
        Tip(b, "Re-read MimicKit's args folder.")
        b = ttk.Button(bfa, text="Add args file...", command=self._add_custom)
        b.pack(side="left", padx=3)
        Tip(b, HELP["custom"])
        b = ttk.Button(bfa, text="Training settings...", command=self.train_settings_dialog)
        b.pack(side="left", padx=3)
        Tip(b, HELP["tsettings"])
        self._build_actions(bfa)  # launcher_profile.py ACTIONS (none in the public build)
        ttk.Label(bfb, text="Preview device").pack(side="left", padx=(3, 4))
        self.v_pdev = tk.StringVar(value=self.s.get("preview_device", "Auto"))
        cb = ttk.Combobox(
            bfb,
            textvariable=self.v_pdev,
            values=["Auto", "CPU only", "GPU"],
            state="readonly",
            width=9,
        )
        cb.pack(side="left")
        Tip(cb, HELP["pdevice"])
        cb.bind(
            "<<ComboboxSelected>>",
            lambda _=None: (
                self.s.__setitem__("preview_device", self.v_pdev.get()),
                self._save_settings_only(),
            ),
        )
        ttk.Label(bfb, text="Reference ghost").pack(side="left", padx=(12, 4))
        self.v_ghost = tk.StringVar(value=self.s.get("preview_ghost", "Overlay"))
        cb = ttk.Combobox(
            bfb, textvariable=self.v_ghost, values=list(GHOST_MODES), state="readonly", width=12
        )
        cb.pack(side="left")
        Tip(cb, HELP["ghost"])
        cb.bind(
            "<<ComboboxSelected>>",
            lambda _=None: (
                self.s.__setitem__("preview_ghost", self.v_ghost.get()),
                self._save_settings_only(),
            ),
        )
        ttk.Label(bfb, text="Clip layout").pack(side="left", padx=(12, 4))
        self.v_layout = tk.StringVar(value=self.s.get("preview_layout", "All at once"))
        cb = ttk.Combobox(
            bfb, textvariable=self.v_layout, values=list(CLIP_LAYOUTS), state="readonly", width=16
        )
        cb.pack(side="left")
        Tip(cb, HELP["layout"])
        cb.bind(
            "<<ComboboxSelected>>",
            lambda _=None: (
                self.s.__setitem__("preview_layout", self.v_layout.get()),
                self._save_settings_only(),
            ),
        )
        b = ttk.Button(bfb, text="Preview diagnostics", command=self.preview_diag)
        b.pack(side="left", padx=(12, 3))
        Tip(b, HELP["pdiag"])
        ttk.Label(bfb, text="Hover = help", style="Dim.TLabel").pack(side="left", padx=8)
        self.custom = list(self.s.get("custom_args", []))
        self.rescan()

    def _build_command_box(self, parent):
        """The exact command being run (copyable)."""
        cmdf = ttk.LabelFrame(
            parent, text="Exact command (copy it into a terminal to run it yourself)", padding=4
        )
        cmdf.pack(side="top", fill="x", pady=(0, 4))
        self.t_cmd = tk.Text(cmdf, height=2, width=60, wrap="word")
        self.t_cmd.pack(fill="x")
        self.t_cmd.configure(state="disabled")

    def _build_status(self, left):
        """Status text, progress target, GPU/VRAM meter."""
        stf = ttk.LabelFrame(left, text="Status", padding=4)
        stf.pack(fill="x")
        self.l_status = ttk.Label(
            stf,
            text="Idle.",
            justify="left",
            font=("Segoe UI", 10) if IS_WIN else ("TkDefaultFont", 10),
        )
        self.l_status.pack(anchor="w")
        tgf = ttk.Frame(stf)
        tgf.pack(anchor="w", fill="x", pady=(2, 0))
        ttk.Label(tgf, text="Progress target").pack(side="left")
        self.v_tkind = tk.StringVar(value="plateau (auto)")
        self.v_tval = tk.StringVar()
        self.cb_target = ttk.Combobox(
            tgf,
            textvariable=self.v_tkind,
            values=["plateau (auto)", "samples (millions)", "score (Train_Return)"],
            state="readonly",
            width=20,
        )
        self.cb_target.pack(side="left", padx=4)
        e = ttk.Entry(tgf, textvariable=self.v_tval, width=10)
        e.pack(side="left")
        b = ttk.Button(tgf, text="Set", command=self._target_from_widgets)
        b.pack(side="left", padx=4)
        self.cb_target.bind("<<ComboboxSelected>>", lambda _=None: self._target_from_widgets())
        for w in (self.cb_target, e, b):
            Tip(w, HELP["target"])
        self._target_root = None
        self.est_disp = {}
        gpuf = ttk.Frame(stf)
        gpuf.pack(anchor="w", fill="x")
        self.l_gpu = ttk.Label(gpuf, text="GPU: checking...", justify="left", style="Good.TLabel")
        self.l_gpu.pack(side="left", anchor="w")
        self.c_vram = tk.Canvas(gpuf, width=190, height=16, highlightthickness=0, bd=0)
        self.c_vram.pack(side="left", padx=(10, 0))
        Tip(
            self.c_vram,
            "GPU memory (VRAM) used / total from nvidia-smi.\nGreen < 75 %, amber 75-90 %, red > 90 % (close to out-of-memory).",
        )
        self.vram = None
        self.root.after(10, self._draw_vram)

    def _sync_run_buttons(self, running):
        """a0.7.0 cleanup: state-aware enabling. Training: start/resume/continue dim, stop buttons live; idle: reverse."""
        for k, b in (getattr(self, "run_btns", None) or {}).items():
            if k in ("train", "resume", "continue"):
                on = not running
            elif k in ("stop", "stopsave"):
                on = running
            else:
                continue
            try:
                b.state(["!disabled"] if on else ["disabled"])
            except tk.TclError:
                pass

    def _build_charts(self, mid):
        """Training progress charts with navigation buttons."""
        right = ttk.LabelFrame(
            mid,
            text="Training progress (refreshed every 10 s)",
            padding=4,
        )
        mid.add(right, weight=1)
        self.prog_frame = right
        self.root.after(300, lambda: mid.sashpos(0, 600))
        self.fig = Figure(figsize=(5.5, 5), dpi=90, layout="constrained")
        self.v_ps = tk.BooleanVar(value=bool(self.s.get("per_step_chart", True)))
        self.ax3 = None
        self._make_axes()
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        # chart navigation (no modes): left-drag = pan time (x) of both charts, wheel = zoom time at the cursor, y fixed to
        # the full data range (manual y drag only when a chart has visible data outside its y range), Home/double-click = reset
        self.xview = None
        self.drag = None
        self.v_cur = tk.BooleanVar(value=bool(self.s.get("current_session_only", False)))
        navf = ttk.Frame(right)
        navf.pack(side="bottom", fill="x")
        self.navf = navf
        self.b_home = ttk.Button(navf, text="Home", width=7, command=self._auto_follow)
        self.b_home.pack(side="left", padx=(0, 4))
        self.b_save = ttk.Button(navf, text="Save picture...", command=self._save_chart)
        self.b_save.pack(side="left")
        c = ttk.Checkbutton(
            navf, text="Current session only", variable=self.v_cur, command=self._cur_toggled
        )
        c.pack(side="left", padx=10)
        c2 = ttk.Checkbutton(
            navf, text="Per-step chart", variable=self.v_ps, command=self._ps_toggled
        )
        c2.pack(side="left")
        Tip(c2, HELP["perstep"])
        Tip(c, HELP["cursess"])
        Tip(self.b_home, HELP["chartnav"])
        Tip(self.b_save, "Save the charts as a PNG/SVG/PDF picture.")
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        # chart help: a small '?' badge in the top-right corner (hover shows the help, kept inside the window)
        self.chart_help = tk.Label(self.canvas.get_tk_widget(), text="?", width=2, cursor="question_arrow")
        self.chart_help.place(relx=1.0, x=-6, y=6, anchor="ne")
        Tip(self.chart_help, HELP["chartnav"])
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        ttk.Label(
            right, text=RETURN_TEXT + "\n" "Samples/hour = training speed.", style="Dim.TLabel"
        ).pack(anchor="w")

    def _toggle_theme(self):
        self.apply_theme()
        self._save()
        self._progress_tick(force=True)

    def apply_theme(self):
        T.clear()
        T.update(THEMES["light" if self.v_light.get() else "dark"])
        if hasattr(self, "c_vram"):
            self.root.after(0, self._draw_vram)
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure(
            ".",
            background=T["bg"],
            foreground=T["fg"],
            fieldbackground=T["field"],
            bordercolor=T["border"],
            lightcolor=T["border"],
            darkcolor=T["border"],
            troughcolor=T["panel"],
            selectbackground=T["sel"],
            selectforeground=T["fg"],
            insertcolor=T["fg"],
            focuscolor=T["accent"],
        )
        st.configure("TFrame", background=T["bg"])
        st.configure("TLabel", background=T["bg"], foreground=T["fg"])
        st.configure("Dim.TLabel", background=T["bg"], foreground=T["dim"])
        st.configure("Good.TLabel", background=T["bg"], foreground=T["good"])
        st.configure(
            "Big.TLabel", background=T["bg"], foreground=T["fg"], font=("Segoe UI", 12, "bold")
        )
        st.configure("Toolbutton", background=T["btn"], foreground=T["fg"], padding=(10, 3))
        st.map("Toolbutton", background=[("selected", T["sel"]), ("active", T["btn_act"])])
        st.configure("TLabelframe", background=T["bg"], bordercolor=T["border"])
        st.configure("TLabelframe.Label", background=T["bg"], foreground=T["accent"])
        st.configure(
            "TButton", background=T["btn"], foreground=T["fg"], bordercolor=T["border"], padding=4
        )
        st.map(
            "TButton",
            background=[("pressed", T["sel"]), ("active", T["btn_act"])],
            foreground=[("disabled", T["dim"])],
        )
        st.configure(
            "Stop.TButton", background=T["stop"], foreground=T["stop_fg"], bordercolor=T["stop"]
        )
        st.map("Stop.TButton", background=[("pressed", T["stop_act"]), ("active", T["stop_act"])])
        st.configure(
            "TCheckbutton",
            background=T["bg"],
            foreground=T["fg"],
            indicatorbackground=T["field"],
            indicatorforeground=T["fg"],
        )
        st.map(
            "TCheckbutton",
            background=[("active", T["bg"])],
            indicatorbackground=[("selected", T["accent"])],
        )
        for w in ("TEntry", "TSpinbox", "TCombobox"):
            st.configure(
                w,
                fieldbackground=T["field"],
                foreground=T["fg"],
                background=T["btn"],
                arrowcolor=T["fg"],
                insertcolor=T["fg"],
            )
        st.map(
            "TCombobox",
            fieldbackground=[("readonly", T["field"])],
            foreground=[("readonly", T["fg"])],
            selectbackground=[("readonly", T["field"])],
            selectforeground=[("readonly", T["fg"])],
        )
        st.configure(
            "TScrollbar",
            background=T["btn"],
            troughcolor=T["panel"],
            arrowcolor=T["fg"],
            bordercolor=T["border"],
        )
        st.configure("TPanedwindow", background=T["bg"])
        st.configure("Sash", background=T["border"])
        # classic tk bits: combobox drop-down list, Text widgets
        self.root.configure(bg=T["bg"])
        self.root.option_add("*TCombobox*Listbox.background", T["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", T["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", T["sel"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", T["fg"])
        self.root.option_add("*Listbox.background", T["field"])
        self.root.option_add("*Listbox.foreground", T["fg"])
        if not hasattr(self, "t_cmd"):
            return  # early (before the window is built): only the ttk styles, e.g. for a startup popup
        self.t_cmd.configure(
            bg=T["panel"],
            fg=T["fg"],
            insertbackground=T["fg"],
            selectbackground=T["sel"],
            highlightthickness=0,
            relief="flat",
        )
        self.t_log.configure(
            bg=T["log_bg"],
            fg=T["log_fg"],
            insertbackground=T["log_fg"],
            selectbackground=T["sel"],
            highlightthickness=0,
            relief="flat",
        )
        # matplotlib
        self.fig.set_facecolor(T["panel"])
        for ax in self._axes():
            self._style_ax(ax)
        self.canvas.get_tk_widget().configure(bg=T["panel"], highlightthickness=0)
        self.chart_help.configure(
            bg=T["panel"], fg=T["dim"], relief="solid", bd=1, font=("Segoe UI", 8, "bold"),
            highlightthickness=0,
        )
        self._restyle_artists()
        self.canvas.draw_idle()
        self._status_theme()

    def _browse(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or "/")
        if d:
            var.set(os.path.normpath(d))

    def _browse_model(self):
        f = filedialog.askopenfilename(
            initialdir=self.mk() or "/", filetypes=[("model", "*.pt"), ("all", "*.*")]
        )
        if f:
            self.v_model.set(f)

    def choose(self, title, text, options, default=None, danger=None):
        """options: [(label, value, one-line hint)]. Returns the chosen value, or None (window closed / Esc)."""
        hook = getattr(self, "_choose_hook", None)
        if hook:
            return hook(title, text, options)
        top = tk.Toplevel(self.root)
        top.withdraw()
        top.title(title)
        top.configure(bg=T["bg"])
        top.resizable(False, False)
        res = {"v": None}
        f = ttk.Frame(top, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=text, wraplength=460, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )

        def pick(v):
            res["v"] = v
            top.destroy()

        first = None
        for i, (lab, val, hint) in enumerate(options):
            b = ttk.Button(
                f,
                text=lab,
                width=10,
                command=lambda v=val: pick(v),
                style="Stop.TButton" if val == danger and val is not None else "TButton",
            )
            b.grid(row=1 + i, column=0, sticky="w", pady=3)
            ttk.Label(f, text=hint, style="Dim.TLabel", justify="left").grid(
                row=1 + i, column=1, sticky="w", padx=(10, 0)
            )
            if val == default:
                first = b
        top.bind("<Escape>", lambda _=None: pick(None))
        top.protocol("WM_DELETE_WINDOW", lambda: pick(None))
        if first:
            first.focus_set()
            top.bind("<Return>", lambda _=None: pick(default))
        self._choose_dlg = top
        place_popup(top, self.root)  # centred over the main window (the close dialog uses this)
        try:
            top.grab_set()
        except tk.TclError:
            pass
        self.root.wait_window(top)
        return res["v"]

    def about_dialog(self):
        top = new_popup(self.root, "About", T)
        f = ttk.Frame(top, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="MimicKit Launcher %s  (build %s)" % (VERSION, build_id()), style="TLabelframe.Label").pack(
            anchor="w"
        )
        ttk.Label(
            f,
            text="A GUI for training and previewing MimicKit policies.\n"
            "GPL-3.0-or-later. https://github.com/curelessSky/mimickit-launcher",
            style="Dim.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(6, 10))
        ttk.Button(f, text="Close", command=top.destroy).pack(anchor="w")
        self._about = top
        return top

    @staticmethod
    def _toggle_secret(entry, button):
        """Show / hide a masked field (the value itself never leaves the field)."""
        hidden = entry.cget("show") != ""
        entry.configure(show="" if hidden else "*")
        button.configure(text="Hide" if hidden else "Show")

    def _set_vram(self, used_mb, total_mb):
        self.vram = (float(used_mb), float(total_mb)) if used_mb is not None and total_mb else None
        self._draw_vram()

    def vram_color(self, frac):
        return self.VRAM_COLORS["ok" if frac < 0.75 else "warn" if frac <= 0.90 else "bad"]

    def _draw_vram(self):
        c = self.c_vram
        c.delete("all")
        w, h = int(c.cget("width")), int(c.cget("height"))
        c.configure(bg=T["bg"])
        c.create_rectangle(0, 0, w - 1, h - 1, fill=T["field"], outline=T["border"])
        if not self.vram:
            c.create_text(
                w / 2, h / 2, text="VRAM: no data", fill=T["dim"], font=("TkDefaultFont", 8)
            )
            return
        used, total = self.vram
        frac = max(0.0, min(1.0, used / total))
        c.create_rectangle(
            1,
            1,
            1 + int((w - 3) * frac),
            h - 2,
            fill=self.vram_color(frac),
            outline="",
            tags="fill",
        )
        c.create_text(
            w / 2,
            h / 2,
            text="%.1f / %.1f GB" % (used / 1024, total / 1024),
            fill="#f0f0f0",
            font=("TkDefaultFont", 8, "bold"),
            tags="text",
        )

    def _gpu_poll_thread(self):
        def loop():
            while True:
                try:
                    r = subprocess.run(
                        [
                            "nvidia-smi",
                            "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                            "--format=csv,noheader,nounits",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        creationflags=NO_WINDOW,
                    )
                    rows = [x.split(", ") for x in r.stdout.strip().splitlines() if x.strip()]
                    txt = "   ".join(
                        "GPU %s: %s / %s MB used, %s%% busy" % (r_[0], r_[1], r_[2], r_[3])
                        for r_ in rows
                        if len(r_) == 4
                    )
                    txt = txt or "GPU: nvidia-smi gave no data"
                    ok = [r_ for r_ in rows if len(r_) == 4 and _isnum(r_[1]) and _isnum(r_[2])]
                    vr = (ok[0][1], ok[0][2]) if ok else (None, None)
                except Exception as e:
                    txt = "GPU: nvidia-smi not available (%s)" % type(e).__name__
                    vr = (None, None)
                try:
                    self.root.after(0, lambda v=vr: self._set_vram(*v))
                    self.root.after(0, lambda t=txt: self.l_gpu.configure(text=t))
                except (RuntimeError, tk.TclError):
                    return  # window closed / main loop gone: just end this poll thread
                time.sleep(5)

        threading.Thread(target=loop, daemon=True).start()

    def _on_close(self):
        if self.proc and self.proc.poll() is None:
            a = self.choose(
                "Training is still running",
                "Training is still running. What should happen to it when the launcher closes?",
                [
                    (
                        "Detach",
                        "detach",
                        "Close the launcher, training keeps going in the background.\nOpen the launcher again to see it.",
                    ),
                    ("Stop", "stop", "Stop training and close. Your saved progress (model.pt) is kept."),
                    ("Cancel", None, "Don't close."),
                ],
                default="detach",
                danger="stop",
            )
            if a is None:
                return
            if a == "detach":
                self._tt_save()
                self.root.destroy()
                return  # it keeps running; the next launcher window reattaches
            self.stop()
        self._tt_save(final=True)
        if self.dash:
            self.dash.stop()
        self.root.destroy()

    def _append(self, s):
        if not hasattr(self, "t_log"):
            self.q.put(s)
            return
        self.t_log.insert("end", s)
        if int(self.t_log.index("end-1c").split(".")[0]) > 5000:
            self.t_log.delete("1.0", "1000.0")
        self.t_log.see("end")

    def _pump(self):
        try:
            for _ in range(500):
                line = self.q.get_nowait()
                self._append(line)
                if line.startswith("[gui] process ended"):
                    self.root.after(
                        50, lambda: self._progress_tick(force=True)
                    )  # save final history
        except queue.Empty:
            pass
        try:
            while True:
                self.rq.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(200, self._pump)

    def _show_cmd(self, cmd, cwd=None):
        shown = " ".join('"%s"' % c if " " in c else c for c in cmd)
        self.t_cmd.configure(state="normal")
        self.t_cmd.delete("1.0", "end")
        self.t_cmd.insert(
            "end", ('cd /d "%s"\n%s' if IS_WIN else 'cd "%s"\n%s') % (cwd or self.mk(), shown)
        )
        self.t_cmd.configure(state="disabled")
