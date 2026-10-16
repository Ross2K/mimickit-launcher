# MimicKit Launcher - main window
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
from mkl.core import *  # noqa: F401,F403 - shared helpers/constants
from mkl.core import __all__ as _core_names  # noqa: F401


class TitleBox(ttk.LabelFrame):
    """LabelFrame whose title row can hold extra widgets (the chart '?' badge). configure(text=) / cget('text') still
    work on the title text."""

    def __init__(self, master, text="", **kw):
        self.title_row = ttk.Frame(master)
        self._title = ttk.Label(self.title_row, text=text, style="TLabelframe.Label")
        self._title.pack(side="left")
        super().__init__(master, labelwidget=self.title_row, **kw)

    def configure(self, cnf=None, **kw):
        if "text" in kw:
            self._title.configure(text=kw.pop("text"))
        if cnf or kw:
            return super().configure(cnf, **kw)

    config = configure

    def cget(self, key):
        return self._title.cget("text") if key == "text" else super().cget(key)


def _pad(v):
    """pack padding (int, 'n', '3 5' or (a, b)) -> (a, b) ints."""
    if isinstance(v, (tuple, list)):
        v = list(v) + list(v)[:1]
        return int(float(str(v[0]))), int(float(str(v[1])))
    parts = str(v).split() or ["0"]
    a = int(float(parts[0]))
    return a, int(float(parts[1])) if len(parts) > 1 else a


def flow(frame, groups=False):
    """Re-lay the packed children of frame into as many rows as needed (a0.8.4: nothing is cut off at 125 %).
    groups=True keeps a label together with the widget after it (e.g. 'Clip layout' + its box).
    a0.8.5: each widget keeps its own pack padding; a widget hidden later (pack_forget) stays hidden, and one packed
    into frame later (new, or shown again) is adopted with its padding on the next check."""
    rows, units, opts = [], [], {}

    def grab(w):
        try:
            i = w.pack_info()
        except tk.TclError:
            i = {}
        opts[w] = dict(padx=_pad(i.get("padx", 3)), pady=_pad(i.get("pady", 1)),
                       ipadx=i.get("ipadx", 0), ipady=i.get("ipady", 0))

    def adopt():
        """Children packed straight into frame (not into our rows) -> units. Returns True if anything changed."""
        new = [w for w in frame.pack_slaves() if w not in rows]
        if not new:
            return False
        known = {w for u in units for w in u}
        i = 0
        while i < len(new):
            w = new[i]
            grab(w)
            if w in known:  # shown again: keep its old place
                i += 1
                continue
            if groups and isinstance(w, ttk.Label) and i + 1 < len(new) and not isinstance(new[i + 1], ttk.Label) \
                    and new[i + 1] not in known:
                grab(new[i + 1])
                units.append((w, new[i + 1]))
                i += 2
            else:
                units.append((w,))
                i += 1
        for w in new:
            w.pack_forget()
            shown.add(w)
        return True

    shown, placed = set(), set()
    state = {"w": -1}

    def relayout(_=None, force=False):
        width = frame.winfo_width()
        if width <= 1 or (width == state["w"] and not force):
            return
        state["w"] = width
        for u in units:
            for w in u:
                if w.winfo_manager() == "pack":
                    w.pack_forget()
        for r in rows:
            r.pack_forget()
        placed.clear()
        n, used = 0, 0
        for u in units:
            vis = [w for w in u if w in shown]
            if not vis:
                continue
            need = sum(w.winfo_reqwidth() + sum(opts[w]["padx"]) for w in vis)
            if used and used + need > width:
                n, used = n + 1, 0
            while len(rows) <= n:
                rows.append(ttk.Frame(frame))
            for w in vis:
                w.pack(in_=rows[n], side="left", **opts[w])
                w.lift(rows[n])
                placed.add(w)
            used += need
        for r in rows[: n + 1]:
            r.pack(side="top", anchor="w", fill="x")

    def check(_=None):
        """Notice widgets the app hid (pack_forget from a row) or packed into frame since the last layout.
        a0.8.6: runs only on <Map>/<Configure> (of frame or a row) or on request - no 400 ms polling."""
        state["pend"] = False
        if not frame.winfo_exists():
            return
        changed = adopt()
        for u in units:
            for w in u:
                packed = w.winfo_manager() == "pack"
                if w in placed and not packed:
                    placed.discard(w)
                    shown.discard(w)  # hidden by the app
                    changed = True
        if changed:
            relayout(force=True)
            try:  # a0.8.8: tell the window its widgets were re-laid out (top area re-hooks new boxes)
                frame.winfo_toplevel().event_generate("<<FlowRebuilt>>", when="tail")
            except tk.TclError:
                pass
        for r in rows:
            if r not in hooked:
                hooked.add(r)
                r.bind("<Configure>", soon, add="+")

    hooked = set()

    def soon(_=None):
        if not state.get("pend") and frame.winfo_exists():
            state["pend"] = True
            frame.after_idle(check)

    def on_conf(e=None):
        relayout(e)
        soon()

    adopt()
    frame._flow_relayout = lambda: (adopt(), relayout(force=True), soon())
    frame._flow_check = soon
    frame.bind("<Configure>", on_conf, add="+")
    frame.bind("<Map>", soon, add="+")
    frame.after_idle(relayout)
    frame.after_idle(soon)


class MainWindowMixin:
    """Main window: layout, theme, dialogs, log panel, GPU/VRAM meter, closing."""

    VRAM_COLORS = dict(ok="#3f9a54", warn="#d0952c", bad="#c0392b")

    def _build(self):
        """The main window, top to bottom: banner, settings row, what to run, status + cards + output | charts."""
        self._build_banner()  # health banner, version on its right
        top = self._top_area()  # a0.8.5: Settings + What to run scroll/shrink first; the charts keep a real minimum
        # run / stop buttons: outside the scrolling top, so STOP is always visible whatever the window height
        self._runbar = ttk.Frame(self.root, padding=(10, 2, 6, 0))
        self._runbar.pack(fill="x")
        self._build_settings(top)
        self._build_job(top)
        self._build_preview_box(self._jobrow)  # a0.9.3: right of 'What to run' (wraps below it when narrow)
        self.rescan()
        mid = ttk.Panedwindow(self.root, orient="horizontal")
        mid.pack(fill="both", expand=True, padx=6, pady=(2, 4))
        lo = ttk.Frame(mid)
        mid.add(lo, weight=2)  # a0.8.3: left 2 : charts 3

        def left_need():  # a0.8.4: Status + cards + at least ~150 px of Output, else the whole column scrolls
            k = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
            h = self._stf.winfo_reqheight() + int(150 * k) + 40
            if hasattr(self, "cards_f") and self.cards_f.winfo_manager():
                h += self.cards_f.winfo_reqheight()
            return h

        left = self._scroll_area(lo, need=left_need)
        self._build_status(left)
        self._build_cards(left)
        self._build_output(left)
        self._build_charts(mid)
        self.apply_theme()

    BOTTOM_MIN = 400  # px at 96 dpi: chart area (~360 px charts + toolbar) kept when the window is short

    def _top_area(self):
        """a0.8.5: Settings + What to run in a frame that scrolls when the window is short, so the bottom half
        (status / output | charts) keeps a real minimum height instead of being squeezed first (125 %)."""
        outer = ttk.Frame(self.root)
        outer.pack(fill="x")
        cv = tk.Canvas(outer, highlightthickness=0, bd=0, height=1, bg=T.get("bg", "#202020"))
        ys = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=ys.set)
        cv.pack(side="left", fill="x", expand=True)
        inner = ttk.Frame(cv, padding=(6, 2, 6, 0))
        win = cv.create_window(0, 0, window=inner, anchor="nw")
        self._top_cv, self._top_inner = cv, inner
        self._scroll_canvases = getattr(self, "_scroll_canvases", []) + [cv]

        more = tk.Label(outer, text="\u25be More settings below (scroll)", anchor="center", cursor="hand2",
                        font=("Segoe UI", 9, "bold"), padx=0, pady=0, bd=0)
        more.bind("<Button-1>", lambda e: cv.yview_scroll(3, "units"))
        self._top_more = more
        st = {"h": 0}

        def show_more():
            """a0.8.6: a '\u25be more' strip at the cut while part of the top area is hidden below."""
            try:
                lo, hi = cv.yview()
            except tk.TclError:
                return
            if ys.winfo_manager() and hi < 0.999:
                more.configure(bg=T.get("sel", "#2d4f7c"), fg=T.get("fg", "#ffffff"))
                # a0.8.7 (UX 3): a 20-24 px strip (22 px at 125 %), easy to spot and to click
                k = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
                more.place(in_=cv, relx=0, rely=1.0, relwidth=1.0, anchor="sw", height=strip_h(k))
                more.lift()
            elif more.winfo_manager():
                more.place_forget()

        def yset(lo, hi):
            ys.set(lo, hi)
            show_more()

        cv.configure(yscrollcommand=yset)

        def strip_h(k):
            return max(20, min(24, int(18 * k)))

        def cuts():
            """y positions (inside the top area) that cut no control in half: below every widget that starts
            above them. Leaf widgets only (frames are containers)."""
            boxes, stack = [], list(inner.winfo_children())
            while stack:
                w = stack.pop()
                try:
                    kids = w.winfo_children()
                    if not w.winfo_ismapped():
                        continue
                    if kids and w.winfo_class() in ("TFrame", "Frame", "TLabelframe", "Labelframe"):
                        stack.extend(kids)
                        continue
                    y = w.winfo_rooty() - inner.winfo_rooty()
                    boxes.append((y, y + w.winfo_height()))
                except tk.TclError:
                    continue
            ends = sorted({b for _, b in boxes})
            return [e for e in ends if not any(t < e < b for t, b in boxes)]

        def snap(h, sh):
            """Largest whole-row cut c with c + strip <= h -> visible height c + strip (never more than h)."""
            ok = [c for c in cuts() if c + sh <= h]
            if not ok:
                return h
            c = max(ok)
            # a0.8.9 (U3): lose at most one row height (the gap to the next cut), else keep h as it is
            allc = cuts()
            nxt = [x for x in allc if x > c]
            prv = [x for x in allc if x < c]
            row = (min(nxt) - c) if nxt else (c - max(prv)) if prv else int(36 * max(1.0, self.root.winfo_fpixels("1i") / 96.0))
            return c + sh if h - (c + sh) <= row else h

        self._top_cuts = cuts

        def fit(_=None):
            k = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
            req = inner.winfo_reqheight()
            winh = self.root.winfo_height()
            others = self.ban_f.winfo_height() + (self._runbar.winfo_reqheight() if hasattr(self, "_runbar") else 0)
            room = winh - others - 10  # top + bottom half share this
            # a0.8.7 (UX 1): the bottom half must fit two charts (CHART_MIN_2, 312 px at 125 %) plus the chart
            # box's title + toolbar; the top keeps ~260 px at 125 % (208 x scale) and only then gives way
            ch = self.canvas.get_tk_widget() if hasattr(self, "canvas") else None
            over = int(90 * k)
            if ch is not None and self.prog_frame.winfo_reqheight() > ch.winfo_reqheight():
                # title row + toolbar rows + padding (requested sizes: they don't depend on how the space is split)
                over = self.prog_frame.winfo_reqheight() - ch.winfo_reqheight() + 8
            # (a0.8.7: measured from the actual heights this fed back into itself and the split never settled)
            bottom_need = int(self.CHART_MIN_2 * k) + over
            avail = room - int(self.BOTTOM_MIN * k)
            h = max(min(req, int(208 * k)), min(req, avail))
            h = min(h, max(min(req, int(110 * k)), room - bottom_need))  # the two charts win over the top
            # less than ~32 px hidden -> take it from the bottom half (if two charts still fit), no scrollbar
            if 0 < req - h <= int(32 * k) and room - req >= bottom_need:
                h = req
            if winh <= 1:
                h = req
            if req > h + 1:  # a0.8.8: end the visible part (above the 'more' strip) at the last whole row
                h = snap(h, strip_h(k))
            if int(cv.cget("height")) != h:
                cv.configure(height=h)
            cv.itemconfigure(win, width=max(1, cv.winfo_width()))
            cv.configure(scrollregion=(0, 0, cv.winfo_width(), req))
            if req > h + 1:
                if not ys.winfo_manager():
                    ys.pack(side="right", fill="y", before=cv)
            elif ys.winfo_manager():
                ys.pack_forget()
                cv.yview_moveto(0)
            st["h"] = h
            show_more()
        self._top_fit = fit
        ys.configure(style="Top.Vertical.TScrollbar")

        cv.bind("<Configure>", lambda e: cv.after_idle(fit))
        inner.bind("<Configure>", lambda e: cv.after_idle(fit))
        self.root.bind("<Configure>", lambda e: cv.after_idle(fit) if e.widget is self.root else None, add="+")

        # a0.8.6: the wheel scrolls the top area over ANY child widget (an all-binding, added once with add="+" so
        # dialog bindings stay, that only acts while the pointer is over the top area).
        # a0.8.7 (UX 2 / QA 1): comboboxes and spinboxes (Training config, num_envs) take the wheel only when they
        # have the keyboard focus; otherwise a widget binding scrolls the top area and stops their class binding
        # (which would change the value). Text and Listbox scroll their own content, so they are left alone (there
        # are none in the top area today; tests/qa087_test.py checks the rule).
        hover = {"on": False}
        own = ("TCombobox", "TSpinbox", "Spinbox")
        skip = own + ("Text", "Listbox")
        o = str(outer)

        def mine(w):
            w = str(w)
            return w == o or w.startswith(o + ".")

        def step(e):
            cv.yview_scroll(-1 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else 1, "units")

        def wheel(e):
            if not hover["on"] or not ys.winfo_manager():
                return
            try:
                if e.widget.winfo_class() in skip or not mine(e.widget):
                    return
            except (tk.TclError, AttributeError):
                return
            step(e)

        def box_wheel(e):
            """Widget binding of a combobox / spinbox in the top area (runs before its class binding)."""
            try:
                if self.root.focus_get() is e.widget:
                    return None  # focused: the box changes its value
            except (tk.TclError, KeyError):
                pass
            if ys.winfo_manager():
                step(e)
            return "break"  # not focused: never change the value

        import weakref

        hooked = weakref.WeakSet()  # a0.8.8 (T2): destroyed boxes drop out on their own

        def hook_boxes(_=None):
            stack = [inner]
            while stack:
                w = stack.pop()
                try:
                    stack.extend(w.winfo_children())
                    cls = w.winfo_class()
                except tk.TclError:  # destroyed meanwhile
                    continue
                if w not in hooked and cls in own:
                    hooked.add(w)
                    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                        w.bind(seq, box_wheel, add="+")
        self._top_hook_boxes, self._top_hooked = hook_boxes, hooked
        # a0.8.8 (T2): on <Map> and after a rebuild (flow() re-layout / an explicit self._top_hook_boxes() call),
        # not on every resize
        inner.bind("<Map>", hook_boxes, add="+")
        self.root.bind("<<FlowRebuilt>>", hook_boxes, add="+")

        def on_box_map(e):
            """a0.8.9 (U5): a box created or shown later outside flow() (grid/pack after start) hooks itself."""
            try:
                if mine(e.widget) and e.widget not in hooked:
                    hook_boxes()
            except (tk.TclError, TypeError):
                pass

        for cls in own:
            self.root.bind_class(cls, "<Map>", on_box_map, add="+")
        self.root.after_idle(hook_boxes)

        def inside():
            x, y = self.root.winfo_pointerxy()
            ox, oy = outer.winfo_rootx(), outer.winfo_rooty()
            return ox <= x < ox + outer.winfo_width() and oy <= y < oy + outer.winfo_height()

        def enter(_=None):
            if not hover["on"]:
                hover["on"] = True
                if not hover.get("ids"):
                    hover["ids"] = {seq: self.root.bind_all(seq, wheel, add="+")
                                    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>")}

        def leave(_=None):
            if not inside():  # <Leave> also fires when the pointer moves onto a child widget
                hover["on"] = False

        outer.bind("<Enter>", enter, add="+")
        outer.bind("<Leave>", leave, add="+")
        def teardown(e=None):
            """a0.8.7 (S5): drop only OUR all-binding when the window goes (dialog bindings stay)."""
            if e is not None and e.widget is not outer:
                return
            for seq, fid in (hover.pop("ids", None) or {}).items():
                try:
                    cur = self.root.tk.call("bind", "all", seq)
                    keep = "\n".join(ln for ln in str(cur).split("\n") if fid not in ln)
                    self.root.tk.call("bind", "all", seq, keep)
                    self.root.deletecommand(fid)
                except tk.TclError:
                    pass

        outer.bind("<Destroy>", teardown, add="+")
        self._top_wheel, self._top_box_wheel, self._top_teardown = wheel, box_wheel, teardown
        self._top_hover = hover
        return inner

    def _build_settings(self, top):
        """Settings row: MimicKit folder, venv, light mode, phone, patches, About."""
        st = ttk.LabelFrame(top, text="Settings", padding=(6, 2, 6, 4))
        st.pack(fill="x")
        self.v_mk = tk.StringVar(value=self.s.get("mimickit", ""))
        self._mk_cache = self.v_mk.get().strip()
        self.v_mk.trace_add("write", lambda *_: (setattr(self, "_mk_cache", self.v_mk.get().strip()), setattr(self, "_patch_cache", None)))  # worker threads see the new folder at once
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
        self.plugin_frame = ttk.Frame(st)  # overlay plugins add their buttons here (none in the public build)
        self.plugin_frame.grid(row=0, column=6, rowspan=2, padx=4, sticky="w")
        # a0.9.2: 'Update aX.Y.Z available' notice (automatic check) - hidden until there is one; click = details
        self.l_update = ttk.Label(st, text="", style="Err.TLabel", cursor="hand2")
        self.l_update.grid(row=0, column=7, rowspan=2, padx=6, sticky="w")
        self.l_update.bind("<Button-1>", lambda e: self.open_update_notice())
        Tip(self.l_update, "A newer launcher version is out. Click for details. Nothing is installed automatically.")
        self.l_update.grid_remove()

    def _build_job(self, top):
        """'What to run': configs, num_envs, output folder, run buttons, preview options."""
        # a0.9.3: 'What to run' on the left, the 'Preview' box beside it on the right (stacked when too narrow)
        row = ttk.Frame(top)
        row.pack(fill="x", pady=(3, 0))
        self._jobrow = row
        job = ttk.LabelFrame(row, text="What to run", padding=(6, 2, 6, 4))
        self._jobbox = job
        self.v_train = tk.StringVar()
        self.v_view = tk.StringVar()
        ttk.Label(job, text="Training config").grid(row=0, column=0, sticky="w")
        self.cb_train = ttk.Combobox(job, textvariable=self.v_train, state="readonly", width=29)
        self.cb_train.grid(row=0, column=1, sticky="w")
        self.cb_train.bind("<<ComboboxSelected>>", self._train_changed)
        Tip(self.cb_train, HELP["trainsel"])
        ttk.Label(job, text="View config").grid(row=0, column=2, sticky="e", padx=(12, 0))
        self.cb_view = ttk.Combobox(job, textvariable=self.v_view, state="readonly", width=26)
        self.cb_view.grid(row=0, column=3, sticky="w")
        self.cb_view.bind("<<ComboboxSelected>>", self._view_changed)
        Tip(self.cb_view, HELP["viewsel"])
        self.l_preset_help = ttk.Label(job, text="", style="Dim.TLabel", wraplength=640)  # a0.9.3: narrower (Preview box beside it)
        self.l_preset_help.grid(row=1, column=0, columnspan=6, sticky="w")
        # a0.9.3: wrap at the box's own width (it shares the row with the Preview box), never forcing it wider
        job.bind("<Configure>", lambda e: self._wrap_preset_help(e.width), add="+")
        ttk.Label(job, text="num_envs").grid(row=2, column=0, sticky="w")
        self.v_envs = tk.IntVar(value=DEFAULT_ENVS)
        sp = ttk.Spinbox(job, from_=1, to=65536, increment=512, textvariable=self.v_envs, width=8)
        sp.grid(row=2, column=1, sticky="w")
        Tip(sp, HELP["envs"])
        sw = ttk.Frame(job)
        sw.grid(row=2, column=1, sticky="e")
        self.l_envs_hint = ttk.Label(sw, text="", style="Err.TLabel")
        self.l_envs_hint.pack(side="left", padx=(0, 6))

        def envs_hint(*_):
            self.l_envs_hint.configure(text="" if self._envs_or_0() >= 1 else "Whole number, e.g. 64")

        self.v_envs.trace_add("write", envs_hint)
        self.b_envswitch = ttk.Button(sw, text="Apply while training", command=self.change_envs_live)
        self.b_envswitch.pack(side="left")
        Tip(self.b_envswitch, HELP["envs_live"])
        self.l_envswitch = ttk.Label(job, text="", style="Dim.TLabel")
        self.l_envswitch.grid(row=7, column=0, columnspan=6, sticky="w")
        self.l_envswitch.grid_remove()  # takes no room until there is something to say
        ttk.Label(job, text="Output folder").grid(row=2, column=2, sticky="e")
        self.v_out = tk.StringVar()
        e = ttk.Entry(job, textvariable=self.v_out, width=27)
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
        # a0.8.4: the run/stop buttons have their own row (STOP always visible at 125 %); the rest wraps below
        bf = ttk.Frame(self._runbar)  # a0.8.5: pinned below the scrolling top (see _build)
        bf.pack(side="left")
        bf2 = ttk.Frame(job)
        bf2.grid(row=6, column=0, columnspan=6, sticky="we", pady=(2, 0))
        bfa = ttk.Frame(bf2)  # other run buttons + args/settings buttons (+ profile ACTIONS), wraps
        bfa.pack(side="top", fill="x")
        for key, txt, fn, parent in (
            ("train", "Start training", self.train, bf),
            ("resume", "Resume training", self.resume, bf),
            ("stopsave", "Stop after next save", self.stop_after_save, bf),
            ("stop", "STOP", self.stop, bf),
            ("view", "View clip", self.view, bfa),
            ("continue", "Continue from run...", self.continue_from, bfa),
            ("watch", "Watch latest", self.watch, bfa),
        ):
            b = ttk.Button(
                parent,
                text=txt,
                command=fn,
                width=max(10, len(txt) + (2 if parent is bf else 0)),  # a0.9.3: tighter wrap row (Preview fits beside)
                style="Stop.TButton" if key == "stop" else "TButton",
            )
            b.pack(side="left", padx=(3, 3) if key != "stop" else (24, 3))
            Tip(b, HELP[key])
            self.run_btns = getattr(self, "run_btns", {})
            self.run_btns[key] = b
            if key == "stopsave":
                self.b_stopsave = b
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
        # 'Stop after next save' status / refusal, right under the run buttons (a0.8.0: refusals are visible here)
        self.l_stopsave = ttk.Label(bf, text="", style="Dim.TLabel")
        self.l_stopsave.pack(side="left", padx=(12, 0))
        self.l_stopsave.pack_forget()
        flow(bfa)
        self.custom = list(self.s.get("custom_args", []))  # rescan() runs once the Preview box exists (_build)

    def _build_preview_box(self, row):
        """a0.9.3: every preview control in its own 'Preview' box, right of 'What to run' (below it when the window is
        too narrow). Two columns: (Choose clips... + All clips | Clip layout), (Reference ghost | Preview device), then
        Pause, the buttons (Cancel render set apart on the right) and the progress bar + status line (render stage and
        pause notices, red for failures)."""
        pv = ttk.LabelFrame(row, text="Preview", padding=(10, 2, 10, 6))
        self.preview_box = pv
        PAD = dict(padx=(0, 8), pady=3)

        def save_on_select(cb, key, var):
            cb.bind("<<ComboboxSelected>>", lambda _=None: (self.s.__setitem__(key, var.get()), self._save_settings_only()))

        cf = ttk.Frame(pv)
        cf.grid(row=0, column=0, columnspan=2, sticky="w", **PAD)
        b = ttk.Button(cf, text="Choose clips...", command=self.clips_dialog)
        b.pack(side="left")
        Tip(b, "Which motion clips the MP4 preview shows (up to 4), saved per training config. Greyed out while "
               "All clips is ticked.")
        self.b_clips = b
        # a0.9.2: 'All clips' - every renderable clip (up to 64) in the chosen layout; greys out the clip choice
        self.v_allclips = tk.BooleanVar(value=bool(self.s.get("preview_all_clips", False)))

        def allclips_changed():
            self.s["preview_all_clips"] = bool(self.v_allclips.get())
            self._save_settings_only()
            self.b_clips.state(["disabled"] if self.v_allclips.get() else ["!disabled"])

        self.cb_allclips = ttk.Checkbutton(cf, text="All clips", variable=self.v_allclips, command=allclips_changed)
        self.cb_allclips.pack(side="left", padx=(12, 0))
        Tip(self.cb_allclips, HELP["allclips"])
        if self.v_allclips.get():
            self.b_clips.state(["disabled"])
        l_layout = ttk.Label(pv, text="Clip layout")
        self.v_layout = tk.StringVar(value=self.s.get("preview_layout", "All at once"))
        cb = ttk.Combobox(pv, textvariable=self.v_layout, values=list(CLIP_LAYOUTS), state="readonly", width=28)
        cb_layout = cb
        Tip(cb, HELP["layout"])
        save_on_select(cb, "preview_layout", self.v_layout)
        l_ghost = ttk.Label(pv, text="Reference ghost")
        self.v_ghost = tk.StringVar(value=self.s.get("preview_ghost", "Overlay"))
        cb = ttk.Combobox(pv, textvariable=self.v_ghost, values=list(GHOST_MODES), state="readonly", width=13)
        cb_ghost = cb
        Tip(cb, HELP["ghost"])
        save_on_select(cb, "preview_ghost", self.v_ghost)
        l_dev = ttk.Label(pv, text="Preview device")
        self.v_pdev = tk.StringVar(value=self.s.get("preview_device", "Auto"))
        cb = ttk.Combobox(pv, textvariable=self.v_pdev, values=["Auto", "CPU only", "GPU"], state="readonly", width=13)
        cb_dev = cb
        Tip(cb, HELP["pdevice"])
        save_on_select(cb, "preview_device", self.v_pdev)
        self.v_pause = tk.BooleanVar(value=bool(self.s.get("preview_pause_training", False)))
        cbp = ttk.Checkbutton(pv, text="Pause training for preview", variable=self.v_pause, command=lambda: (
            self.s.__setitem__("preview_pause_training", bool(self.v_pause.get())), self._save_settings_only()))
        Tip(cbp, HELP["pausepreview"])
        pv.columnconfigure(4, weight=1)
        act = ttk.Frame(pv)
        b = ttk.Button(act, text="Render MP4", command=self.preview, width=12)
        b.pack(side="left")
        Tip(b, HELP["preview"])
        self.run_btns = getattr(self, "run_btns", {})
        self.run_btns["preview"] = b
        b = ttk.Button(act, text="Preview diagnostics", command=self.preview_diag)
        b.pack(side="left", padx=(10, 0))
        self.b_pdiag = b
        Tip(b, HELP["pdiag"])
        # Cancel render: set apart on the far right - only the preview, never the training
        self.b_stoprender = ttk.Button(act, text="Cancel render", command=self._stop_render_click, width=14)
        self.b_stoprender.pack(side="right", padx=(40, 0))
        Tip(self.b_stoprender, HELP["stoprender"])
        self.b_stoprender.state(["disabled"])
        prog = ttk.Frame(pv)
        self.pv_bar = ttk.Progressbar(prog, mode="determinate", maximum=100, length=150)
        self.pv_bar.pack(side="left", padx=(0, 10))
        # one status line: render stage and the 'Pause training for preview' notices (red for failures)
        self.l_pvprog = ttk.Label(prog, text="No render running.", style="Dim.TLabel", justify="left")
        self.l_pvprog.pack(side="left", fill="x", expand=True)
        self.l_pause = self.l_pvprog
        prog.bind("<Configure>", lambda e: self.l_pvprog.configure(wraplength=max(160, e.width - 175)), add="+")
        self._pvw = dict(cf=cf, l_layout=l_layout, cb_layout=cb_layout, l_ghost=l_ghost, cb_ghost=cb_ghost, l_dev=l_dev,
                         cb_dev=cb_dev, pause=cbp, act=act, prog=prog)
        # requested widths of both inner layouts (two columns / one column), measured once; 'What to run' is measured
        # before the config hint gets its text (that hint wraps to whatever width the box gets)
        self._jobbox.update_idletasks()
        self._job_basew = self._jobbox.winfo_reqwidth()
        self._pv_widths = {}
        for m in ("narrow", "wide"):
            self._pv_regrid(m)
            pv.update_idletasks()
            self._pv_widths[m] = pv.winfo_reqwidth()
        row.bind("<Configure>", lambda e: self._jobrow_layout(), add="+")
        self._jobrow_mode = None
        self._jobrow_layout()
        self.root.after(1000, self._pv_tick)

    def _wrap_preset_help(self, width):
        wl = max(400, int(width) - 20)
        try:
            if abs(int(str(self.l_preset_help.cget("wraplength")) or 0) - wl) > 4:
                self.l_preset_help.configure(wraplength=wl)
        except (tk.TclError, ValueError):
            return

    def _pv_regrid(self, mode):
        """Inner layout of the Preview box: 'wide' = two columns, 'narrow' = one setting per row (used when it sits
        beside 'What to run' in a narrower window)."""
        w, PAD = self._pvw, dict(padx=(0, 8), pady=3)
        if getattr(self, "_pv_mode", None) == mode:
            return
        self._pv_mode = mode
        w["cf"].grid(row=0, column=0, columnspan=2, sticky="w", **PAD)
        if mode == "wide":
            w["l_layout"].grid(row=0, column=2, sticky="w", padx=(16, 8), pady=3)
            w["cb_layout"].grid(row=0, column=3, sticky="w", **PAD)
            w["l_ghost"].grid(row=1, column=0, sticky="w", **PAD)
            w["cb_ghost"].grid(row=1, column=1, sticky="w", **PAD)
            w["l_dev"].grid(row=1, column=2, sticky="w", padx=(16, 8), pady=3)
            w["cb_dev"].grid(row=1, column=3, sticky="w", **PAD)
            r = 2
            w["cb_layout"].configure(width=28)
        else:
            for i, (l, c) in enumerate((("l_layout", "cb_layout"), ("l_ghost", "cb_ghost"), ("l_dev", "cb_dev"))):
                w[l].grid(row=1 + i, column=0, sticky="w", **PAD)
                w[c].grid(row=1 + i, column=1, columnspan=3, sticky="w", **PAD)
            r = 4
            w["cb_layout"].configure(width=24)
        w["pause"].grid(row=r, column=0, columnspan=4, sticky="w", **PAD)
        w["act"].grid(row=r + 1, column=0, columnspan=5, sticky="we", pady=(6, 2))
        w["prog"].grid(row=r + 2, column=0, columnspan=5, sticky="we", pady=(4, 0))
        self.b_stoprender.pack_configure(padx=(40, 0) if mode == "wide" else (16, 0))
        self.b_pdiag.configure(text="Preview diagnostics" if mode == "wide" else "Diagnostics")

    def _jobrow_layout(self):
        """Preview beside 'What to run' when both fit side by side, else below it (narrow window / big scaling).
        Decided from the row width and the boxes' requested widths only, so it can't flip back and forth."""
        row, job, pv = self._jobrow, self._jobbox, self.preview_box
        try:
            w = row.winfo_width()
            if w <= 1:
                w = row.winfo_reqwidth()
            jw = getattr(self, "_job_basew", 0) or job.winfo_reqwidth()
            jw += 8
        except tk.TclError:
            return
        pw = getattr(self, "_pv_widths", {})
        mode = ("side" if w >= jw + pw.get("wide", 0) else "side1" if w >= jw + pw.get("narrow", 0) else "stack")
        if mode == self._jobrow_mode:
            return
        self._jobrow_mode = mode
        self._pv_regrid("narrow" if mode == "side1" else "wide")
        if mode in ("side", "side1"):
            self._wrap_preset_help(jw - 8)  # back to the box's own width (it was wider when stacked)
            job.grid(row=0, column=0, sticky="nsew")
            pv.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=0)
            row.columnconfigure(0, weight=0)
            row.columnconfigure(1, weight=1)
        else:
            job.grid(row=0, column=0, sticky="nsew")
            pv.grid(row=1, column=0, sticky="nsew", padx=0, pady=(6, 0))
            row.columnconfigure(0, weight=1)
            row.columnconfigure(1, weight=0)
        if hasattr(self, "_top_hook_boxes"):
            try:
                self._top_hook_boxes()
            except Exception as e:
                log_exc("preview box: re-layout", e)

    def _pv_tick(self):
        """Preview box: progress bar + status line, Cancel render enabled only while a render runs (every second)."""
        try:
            rp = getattr(self, "render_prog", None) or {}
            running = self._preview_alive() if hasattr(self, "_preview_alive") else False
            self.pv_bar.configure(value=rp.get("pct", 0) if (rp.get("active") or running) else 0)
            stage = rp.get("stage") or ""
            pm = getattr(self, "pp_msg", None) or {}
            err = False
            if running:
                txt = "Rendering: %s (%d%%)" % (stage or "starting", rp.get("pct", 0))
                if getattr(self, "pp", None):
                    txt += " - training paused, resumes after the render"
            elif pm and (getattr(self, "pp", None) or time.time() - pm.get("at", 0) < 900):
                txt, err = pm.get("text", ""), bool(pm.get("error"))
            else:
                txt = stage if stage in ("Render cancelled", "Done") or stage.startswith("Failed") else "No render running."
                err = stage.startswith("Failed")
            style = "Err.TLabel" if err else "Dim.TLabel"
            if self.l_pvprog.cget("text") != txt or str(self.l_pvprog.cget("style")) != style:
                self.l_pvprog.configure(text=txt, style=style)
            self.b_stoprender.state(["!disabled"] if running else ["disabled"])
        except tk.TclError:
            return  # window closing
        except Exception as e:
            log_exc("preview box tick", e)
        self.root.after(1000, self._pv_tick)

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
        self._stf = stf
        self.l_status = ttk.Label(
            stf,
            text="Idle.",
            justify="left",
            font=("Segoe UI", 10) if IS_WIN else ("TkDefaultFont", 10),
        )
        self.l_status.pack(anchor="w", fill="x")
        # wrap to the column instead of being cut off on the right (a0.6.1 item: 'speed 7.50 M samples/' was clipped)
        stf.bind("<Configure>", lambda e: self.l_status.configure(wraplength=max(200, e.width - 16)), add="+")
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

    def _view_changed(self, _=None):
        it = self._item("view") or {}
        if it.get("missing"):
            self._append("[gui] view '%s' is not installed yet - %s\n" % (it["name"], it["missing"]))
        self._sync_run_buttons(self._training_running())

    def _sync_run_buttons(self, running):
        """a0.7.0 cleanup: state-aware enabling. Training: start/resume/continue dim, stop buttons live; idle: reverse."""
        miss_t = bool((self._item("train") or {}).get("missing")) if hasattr(self, "train_items") else False
        miss_v = bool((self._item("view") or {}).get("missing")) if hasattr(self, "view_items") else False
        for k, b in (getattr(self, "run_btns", None) or {}).items():
            if k in ("train", "resume", "continue"):
                on = not running and not miss_t
            elif k == "watch":
                on = not miss_t
            elif k == "view":
                on = not miss_v
            elif k in ("stop", "stopsave"):
                on = running
            else:
                continue
            try:
                b.state(["!disabled"] if on else ["disabled"])
            except tk.TclError:
                pass
        sr = getattr(self, "b_stoprender", None)
        if sr is not None:
            pp = getattr(self, "preview_proc", None)
            try:
                sr.state(["!disabled"] if pp is not None and pp.poll() is None else ["disabled"])
            except tk.TclError:
                pass

    def _stop_render_click(self):
        if messagebox.askyesno("Cancel render", "Cancel the running preview render?\n\nOnly the preview stops - training "
                               "keeps running. The unfinished video is removed."):
            ok, msg = self.stop_render("PC")
            if not ok:
                self._append("[gui] %s\n" % msg)

    def _build_charts(self, mid):
        """Training progress charts with navigation buttons."""
        right = TitleBox(
            mid,
            text="Training progress (refreshed every 10 s)",
            padding=4,
        )
        mid.add(right, weight=3)
        self.prog_frame = right
        self.root.after(300, lambda: mid.sashpos(0, max(560, int(mid.winfo_width() * 0.4))))
        # a0.8.3: real screen DPI (x Windows scale) instead of a fixed 90 dpi - text no longer crunched at 125 %
        try:
            dpi = max(72.0, min(240.0, float(self.root.winfo_fpixels("1i"))))
        except (tk.TclError, ValueError):
            dpi = 96.0
        self.fig = Figure(figsize=(560 / dpi, 500 / dpi), dpi=dpi, layout="constrained")
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
        self.cb_ps = c2
        # a0.8.4: on a very short window only one chart fits - these tabs pick which (hidden otherwise)
        self.f_onechart = ttk.Frame(navf)
        self.v_onechart = tk.StringVar(value="return")
        for lab, val in (("Return", "return"), ("Speed", "speed")):
            ttk.Radiobutton(self.f_onechart, text=lab, value=val, variable=self.v_onechart, style="Toolbutton",
                            command=self._onechart_changed).pack(side="left", padx=1)
        Tip(c2, HELP["perstep"])
        Tip(c, HELP["cursess"])
        Tip(self.b_home, HELP["chartnav"])
        Tip(self.b_save, "Save the charts as a PNG/SVG/PDF picture.")
        flow(navf)  # a0.8.7 (UX 4): the toolbar wraps onto a 2nd row instead of clipping at 125 %
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.get_tk_widget().bind("<Configure>", self._chart_resized, add="+")
        if hasattr(self, "_top_fit"):  # a0.8.7: the chart box's toolbar may wrap -> re-split top / bottom
            self.canvas.get_tk_widget().bind("<Configure>", lambda e: self.root.after_idle(self._top_fit), add="+")
        # chart help: '?' badge in the chart's title row, next to 'Training progress' (a0.6.1 UX item: it used to be
        # a tiny badge on the end of the Return line); hover shows the help, kept inside the window
        self.chart_help = tk.Label(right.title_row, text="?", width=2, cursor="question_arrow")
        # before the title: on a narrow window the title row gets clipped from the right, the badge must stay whole
        self.chart_help.pack(side="left", padx=(0, 6), before=right._title)
        # a0.8.5: the chart caption (what Return / Samples/hour mean) moved into this tooltip - no squeezed line
        # under the charts any more
        self.chart_caption = RETURN_TEXT + "\nSamples/hour = training speed."
        Tip(self.chart_help, self.chart_caption + "\n\n" + HELP["chartnav"])
        Tip(right._title, self.chart_caption)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)

    def _toggle_theme(self):
        self.apply_theme()
        self._save()
        self._progress_tick(force=True)

    def _theme_popdowns(self, w=None):
        """a0.8.9 (UX4): drop-down lists already created keep their old colours (option_add only reaches new ones)."""
        stack = [w or self.root]
        while stack:
            x = stack.pop()
            try:
                stack.extend(x.winfo_children())
                if x.winfo_class() != "TCombobox":
                    continue
                pd = x.tk.call("ttk::combobox::PopdownWindow", x)
                x.tk.call(str(pd) + ".f.l", "configure", "-background", T["list_bg"], "-foreground", T["fg"],
                          "-selectbackground", T["sel"], "-selectforeground", T["fg"])
            except tk.TclError:
                continue

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
        st.configure("Err.TLabel", background=T["bg"], foreground=T["err"])
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
            background=[("disabled", T["dis_bg"]), ("pressed", T["sel"]), ("active", T["btn_act"])],
            foreground=[("disabled", T["dis_fg"])],  # a0.8.9 (UX2): not the same grey as secondary text
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
                bordercolor=T["in_border"],  # a0.8.9 (U4): inputs ~#555, box edges keep T["border"]
                lightcolor=T["in_border"],
                darkcolor=T["in_border"],
            )
            st.map(
                w,
                bordercolor=[("focus", T["focus"])],
                lightcolor=[("focus", T["focus"])],
                foreground=[("disabled", T["dis_fg"])],
                fieldbackground=[("disabled", T["dis_bg"])],
            )
        st.map(
            "TCombobox",
            fieldbackground=[("disabled", T["dis_bg"]), ("readonly", T["field"])],
            foreground=[("disabled", T["dis_fg"]), ("readonly", T["fg"])],
            selectbackground=[("readonly", T["field"])],
            selectforeground=[("readonly", T["fg"])],
        )
        st.configure(
            "TScrollbar",
            background=T["sb_thumb"],  # a0.8.9 (UX3): #6a6a6a thumb on a #1a1a1a trough
            troughcolor=T["sb_trough"],
            arrowcolor=T["fg"],
            bordercolor=T["border"],
        )
        dark = not self.v_light.get()
        st.configure(  # a0.8.6: the top-area scrollbar stands out in dark mode (users missed that it scrolls)
            "Top.Vertical.TScrollbar",
            background=T["sb_thumb"],
            troughcolor=T["sb_trough"],
            arrowcolor="#ffffff" if dark else T["fg"],
            bordercolor="#5a5a5a" if dark else T["border"],
        )
        st.map("Top.Vertical.TScrollbar", background=[("active", "#8a8a8a" if dark else T["btn_act"])])
        st.map("TScrollbar", background=[("active", "#8a8a8a" if dark else T["btn_act"])])
        if hasattr(self, "_top_more"):
            self._top_more.configure(bg=T["sel"], fg=T["fg"])
        st.configure("TPanedwindow", background=T["bg"])
        st.configure("Sash", background=T["border"])
        # classic tk bits: combobox drop-down list, Text widgets
        self.root.configure(bg=T["bg"])
        self.root.option_add("*TCombobox*Listbox.background", T["list_bg"])  # a0.8.9 (UX4): black lists
        self.root.option_add("*TCombobox*Listbox.foreground", T["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", T["sel"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", T["fg"])
        self.root.option_add("*Listbox.background", T["list_bg"])
        self._theme_popdowns()
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
            bg=T["panel"], fg=T["accent"], relief="solid", bd=1, font=("Segoe UI", 10, "bold"),
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
        if hasattr(self, "build_update_settings"):  # a0.9.2: automatic update check settings
            self.build_update_settings(f).pack(anchor="w", fill="x", pady=(0, 10))
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
                if getattr(self, "_closed", False):
                    return  # window closed: just end this poll thread
                # worker thread: never call Tk here - the GUI thread runs these from rq
                self.rq.put(lambda v=vr, t=txt: (self._set_vram(*v), self.l_gpu.configure(text=t)))
                time.sleep(5)

        threading.Thread(target=loop, daemon=True).start()

    def _close_save(self):
        """Right before the window goes (after the 'training is running' prompt): size/position + stop workers."""
        self._closed = True
        try:
            self._save_window_state()
            self._save_settings_only()
        except Exception as e:
            U.log_exc("window: save size", e)

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
                self._plugin_call("closing")
                if self.dash:
                    self.dash.stop()
                self._close_save()
                self.root.destroy()
                return  # it keeps running; the next launcher window reattaches
            self.stop()
        self._tt_save(final=True)
        self._plugin_call("closing")
        if self.dash:
            self.dash.stop()
        self._close_save()
        self.root.destroy()

    def _tk_callback_error(self, exc, val, tb):
        """root.report_callback_exception: any error in a button / timer callback."""
        import traceback

        try:
            with open(U.log_path() if hasattr(U, "log_path") else os.devnull, "a", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(exc, val, tb)))
        except OSError:
            pass  # the log file itself can't be written: _gui_error below still shows it
        self._gui_error("button/timer", val)

    def _gui_error(self, where, e):
        log_exc(where, e)
        msg = "Launcher error in %s: %s: %s (details in launcher_errors.log)" % (where, type(e).__name__, e)
        try:
            self._append("[gui] %s\n" % msg)
            if hasattr(self, "ban_detail"):
                self.ban_detail.configure(text="error: %s" % type(e).__name__)
        except Exception as e2:
            log_exc("showing a GUI error", e2)
        self.last_gui_error = msg

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
                    self.root.after(100, self._plugin_call, "run_ended")
        except queue.Empty:
            pass
        for _ in range(200):  # GUI work queued by other threads; one failing job no longer stops the pump
            try:
                job = self.rq.get_nowait()
            except queue.Empty:
                break
            try:
                job()
            except Exception as e:
                self._gui_error("queued job", e)
        self.root.after(200, self._pump)

    def _show_cmd(self, cmd, cwd=None):
        shown = " ".join('"%s"' % c if " " in c else c for c in cmd)
        self.t_cmd.configure(state="normal")
        self.t_cmd.delete("1.0", "end")
        self.t_cmd.insert(
            "end", ('cd /d "%s"\n%s' if IS_WIN else 'cd "%s"\n%s') % (cwd or self.mk(), shown)
        )
        self.t_cmd.configure(state="disabled")
