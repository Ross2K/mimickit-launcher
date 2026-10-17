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


def kscale(root):
    """Screen scale vs 96 dpi (1.0 at 100 %, 1.25 at 125 %)."""
    try:
        return max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except (tk.TclError, ValueError):
        return 1.0


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
        """1.0.0 (Mockup D): four pages picked with the bottom tabs (Setup / Train / Preview / Results, Ctrl+1..4) and
        the transport strip above the tabs (run buttons, progress to the plateau, live stats, VRAM) on every page."""
        self._build_shell()  # pages + transport strip + tab bar (mkl/layout.py)
        self._build_transport()
        self._build_banner()  # health pill in the transport strip, hint + version in the tab bar
        self._build_setup_page(self.pages["setup"])
        self._build_train_page(self.pages["train"])
        self._build_preview_page(self.pages["preview"])
        self._build_preview_box(self._pv_right)
        self._build_preview_left(self._pv_left)
        self._build_results(self.pages["results"])
        self.rescan()
        self.apply_theme()
        self.show_page("train")

    BOTTOM_MIN = 400  # px at 96 dpi: chart area kept when the window is short (2 charts fit in CHART_MIN_2)
    LEFT_W = (400, 360)  # Train page left column at >= 1800 px / below (x scale)
    RIGHT_W = (340, 290)  # Train page right column
    CENTER_MIN = 500  # charts need at least this; else 'What's happening' moves under the charts

    # ------------------------------------------------------------------ Train page
    def _build_train_page(self, page):
        k = kscale(self.root)
        self._train_page = page
        page.rowconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        left = TitleBox(page, text="What to train", padding=(6, 2, 2, 4))
        ttk.Label(left.title_row, text="   applies on next Start", style="Dim.TLabel").pack(side="left")
        self._train_left = left
        top = self._top_area(left)  # scrolls when the window is short (combobox wheel only when focused)
        self._build_job(top)
        center = ttk.Frame(page)
        self._train_center = center
        self._build_cards(center)  # error / milestone cards: above the charts, full width
        self._build_charts(center)
        self._cards_anchor = self.prog_frame
        right = TitleBox(page, text="What's happening", padding=(8, 2, 8, 6))
        self._train_right = right
        self._build_status(right)
        self._build_output(right)
        self._feed_parts = list(right.pack_slaves())  # in packing order (side top / bottom)
        self._feed_opts = [{k: v for k, v in w.pack_info().items() if k != "in"} for w in self._feed_parts]
        self._feed_right_half = {self._warncard, self.st_ckpt.master, self.b_open_console.master}
        self._train_mode = None
        page.bind("<Configure>", lambda e: self._train_layout(), add="+")
        self._train_layout()

    def _train_layout(self, force=False):
        """3 columns when the charts keep CENTER_MIN; else 'What's happening' goes under the charts (still visible)."""
        page = self._train_page
        k = kscale(self.root)
        w = page.winfo_width()
        if w <= 1:
            w = self.root.winfo_width()
        wide = self.root.winfo_width() >= 1800
        lw, rw = int(self.LEFT_W[0 if wide else 1] * k), int(self.RIGHT_W[0 if wide else 1] * k)
        mode = ("3col" if w >= lw + rw + int(self.CENTER_MIN * k) + 40 else "2col", lw, rw)
        if mode == self._train_mode and not force:
            return
        self._train_mode = mode
        self._top_cv.configure(width=lw - int(24 * k))
        L, C, R = self._train_left, self._train_center, self._train_right
        L.grid(row=0, column=0, sticky="nsew")
        L.configure(width=lw)  # fixed width: content can't nudge the column (flow() rows would flip-flop)
        L.pack_propagate(False)
        C.grid(row=0, column=1, sticky="nsew", padx=(10, 10) if mode[0] == "3col" else (10, 0))
        R.grid_forget()
        R.pack_forget()
        page.columnconfigure(0, minsize=lw)
        self._feed_regrid(mode[0])
        if mode[0] == "3col":
            R.grid(in_=page, row=0, column=2, sticky="nsew")
            page.columnconfigure(2, minsize=rw)
            self._feed_text_h(8)
        else:  # under the charts, still on the Train page, in two short columns
            page.columnconfigure(2, minsize=0)
            R.pack(in_=C, side="bottom", fill="x", pady=(8, 0), before=self.prog_frame)
            self._feed_text_h(3)
        self._wrap_preset_help(lw - int(40 * k))
        for lab in (self.l_cardtitle, self.l_cardsub):  # the card never widens the column (no wrap feedback)
            lab.configure(wraplength=max(120, lw - int(150 * k)), justify="left")
        self.root.after_idle(self._top_fit)

    def _feed_regrid(self, mode):
        """'What's happening': one column (3col) or two short side-by-side halves under the charts (2col)."""
        R = self._train_right
        if not hasattr(self, "_feed_halves"):
            self._feed_halves = (ttk.Frame(R), ttk.Frame(R))
        a, b = self._feed_halves
        order = [w for w in self._feed_parts if w is not None]
        for w in order:
            w.pack_forget()
        for w in (a, b):
            w.grid_forget()
        if mode == "3col":
            for w, opt in zip(order, self._feed_opts):
                w.pack(in_=R, **opt)
        else:
            a.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
            b.grid(row=0, column=1, sticky="nsew")
            R.columnconfigure(0, weight=1, uniform="half")
            R.columnconfigure(1, weight=1, uniform="half")
            for w, opt in zip(order, self._feed_opts):
                w.pack(in_=b if w in self._feed_right_half else a, **opt)
                w.lift()  # the halves were created later: keep the parts above them

    def _feed_text_h(self, n):
        for w in (getattr(self, "st_events", None), getattr(self, "st_warn", None)):
            if w is not None:
                w.configure(height=n if w is self.st_events else max(2, n // 2))

    def _top_area(self, parent):
        """The Train page's left column ('What to train') in a frame that scrolls when the window is short
        (a0.8.5-a0.8.9 rules kept: whole-row cut, a '\u25be more' strip at the cut, the wheel scrolls it over any
        child, comboboxes / spinboxes take the wheel only when focused)."""
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        cv = tk.Canvas(outer, highlightthickness=0, bd=0, height=1, width=360, bg=T.get("bg", "#202020"))
        ys = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=ys.set)
        cv.pack(side="left", fill="x", expand=True, anchor="n")
        inner = ttk.Frame(cv, padding=(2, 2, 6, 0))
        win = cv.create_window(0, 0, window=inner, anchor="nw")
        self._top_cv, self._top_inner, self._top_outer = cv, inner, outer
        self._scroll_canvases = getattr(self, "_scroll_canvases", []) + [cv]

        more = tk.Label(outer, text="\u25be More settings below (scroll)", anchor="center", cursor="hand2",
                        font=("Segoe UI", 9, "bold"), padx=0, pady=0, bd=0)
        more.bind("<Button-1>", lambda e: cv.yview_scroll(3, "units"))
        self._top_more = more
        st = {"h": 0}

        def show_more():
            try:
                lo, hi = cv.yview()
            except tk.TclError:
                return
            if ys.winfo_manager() and hi < 0.999:
                more.configure(bg=T.get("sel", "#2d4f7c"), fg=T.get("fg", "#ffffff"))
                k = kscale(self.root)
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
            """y positions (inside the column) that cut no control in half (leaf widgets only)."""
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
            """Largest whole-row cut c with c + strip <= h -> visible height c + strip (never more than h);
            loses at most one row height (a0.8.9 U3)."""
            allc = cuts()
            ok = [c for c in allc if c + sh <= h]
            if not ok:
                return h
            c = max(ok)
            nxt = [x for x in allc if x > c]
            prv = [x for x in allc if x < c]
            row = (min(nxt) - c) if nxt else (c - max(prv)) if prv else int(36 * kscale(self.root))
            return c + sh if h - (c + sh) <= row else h

        self._top_cuts = cuts

        def fit(_=None):
            k = kscale(self.root)
            req = inner.winfo_reqheight()
            room = outer.winfo_height()
            if room <= 1:
                room = req
            # a few px short -> squeeze the Last preview card (sub line, padding) instead of a scrollbar
            card = getattr(self, "_lastcard", None)
            if card is not None:
                over = req - room
                if not st.get("compact") and 1 < over <= int(20 * k) + 1:
                    st["compact"] = self.l_cardsub.winfo_reqheight() + 16  # estimate until measured below
                    st["room0"], st["measured"] = room, False
                    self._card_compact(True)
                    cv.after_idle(fit)
                    return
                if st.get("compact") and not st["measured"] and room != st["room0"]:
                    st["compact"], st["measured"] = max(1, room - st["room0"]), True  # what the squeeze gave back
                if st.get("compact") and (over > int(60 * k) or -over > st["compact"] + 2):
                    st["compact"] = 0
                    self._card_compact(False)
                    cv.after_idle(fit)
                    return
            h = room
            if req > room + 1:
                h = snap(room, strip_h(k))
            if int(cv.cget("height")) != h:
                cv.configure(height=h)
            cv.itemconfigure(win, width=max(1, cv.winfo_width()))
            cv.configure(scrollregion=(0, 0, cv.winfo_width(), req))
            if req > room + 1:
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
        outer.bind("<Configure>", lambda e: cv.after_idle(fit))

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
            """Widget binding of a combobox / spinbox in the column (runs before its class binding)."""
            try:
                if self.root.focus_get() is e.widget:
                    return None  # focused: the box changes its value
            except (tk.TclError, KeyError):
                pass
            if ys.winfo_manager():
                step(e)
            return "break"  # not focused: never change the value

        import weakref

        hooked = weakref.WeakSet()

        def hook_boxes(_=None):
            stack = [inner]
            while stack:
                w = stack.pop()
                try:
                    stack.extend(w.winfo_children())
                    cls = w.winfo_class()
                except tk.TclError:
                    continue
                if w not in hooked and cls in own:
                    hooked.add(w)
                    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                        w.bind(seq, box_wheel, add="+")
        self._top_hook_boxes, self._top_hooked = hook_boxes, hooked
        inner.bind("<Map>", hook_boxes, add="+")
        self.root.bind("<<FlowRebuilt>>", hook_boxes, add="+")

        def on_box_map(e):
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
            if not inside():
                hover["on"] = False

        outer.bind("<Enter>", enter, add="+")
        outer.bind("<Leave>", leave, add="+")

        def teardown(e=None):
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

    # ------------------------------------------------------------------ Setup page
    def _build_setup_page(self, page):
        """Setup: 'Where things are' (MimicKit folder, venv, Save + rescan, Look) and 'Extras' (phone, patches,
        overlay buttons, updates, About), side by side; stacked on a narrow window. Scrolls when short."""
        k = kscale(self.root)
        body = self._scroll_area(page)
        self._setup_body = body
        wrap = ttk.Frame(body)
        wrap.pack(side="top", pady=(int(24 * k), 0))
        self._setup_wrap = wrap
        st = TitleBox(wrap, text="Where things are", padding=(12, 6, 12, 10))
        ttk.Label(st.title_row, text="   saved when you press Save + rescan", style="Dim.TLabel").pack(side="left")
        self._build_settings(st)
        ex = TitleBox(wrap, text="Extras", padding=(12, 6, 12, 10))
        self._build_extras(ex)
        self._setup_boxes = (st, ex)
        self._setup_mode = None
        page.bind("<Configure>", lambda e: self._setup_layout(), add="+")
        self._setup_layout()

    def _setup_layout(self):
        st, ex = self._setup_boxes
        w = self.pages["setup"].winfo_width()
        if w <= 1:
            w = self.root.winfo_width()
        mode = "side" if w >= st.winfo_reqwidth() + ex.winfo_reqwidth() + 60 else "stack"
        if mode == self._setup_mode:
            return
        self._setup_mode = mode
        st.grid(row=0, column=0, sticky="new")
        if mode == "side":
            ex.grid(row=0, column=1, sticky="new", padx=(14, 0), pady=0)
        else:
            ex.grid(row=1, column=0, sticky="new", padx=0, pady=(14, 0))

    def _build_settings(self, st):
        """MimicKit folder, venv, Save + rescan, light mode."""
        k = kscale(self.root)
        self.v_mk = tk.StringVar(value=self.s.get("mimickit", ""))
        self._mk_cache = self.v_mk.get().strip()
        self.v_mk.trace_add("write", lambda *_: (setattr(self, "_mk_cache", self.v_mk.get().strip()), setattr(self, "_patch_cache", None)))  # worker threads see the new folder at once
        self.v_venv = tk.StringVar(value=self.s.get("venv", ""))
        g = ttk.Frame(st)
        g.pack(fill="x")
        for r, (lab, var, attr) in enumerate((("MimicKit folder", self.v_mk, "mk"), ("Python venv", self.v_venv, "venv"))):
            lw = ttk.Label(g, text=lab)
            lw.grid(row=r, column=0, sticky="w", pady=3)
            e = ttk.Entry(g, textvariable=var, width=52)
            e.grid(row=r, column=1, sticky="we", padx=8, pady=3)
            setattr(self, "e_" + attr, e)
            if var is self.v_venv:
                tip = "A venv folder or a python executable. Empty = the Python running this launcher."
                Tip(lw, tip)
                Tip(e, tip)
            b = ttk.Button(g, text="Browse...", command=lambda v=var: self._browse(v))
            b.grid(row=r, column=2, pady=3)
            setattr(self, "b_%s_browse" % attr, b)
        g.columnconfigure(1, weight=1)
        r2 = ttk.Frame(st)
        r2.pack(fill="x", pady=(8, 0))
        self.b_saverescan = ttk.Button(r2, text="Save + rescan", command=lambda: (self._save(), self.rescan()))
        self.b_saverescan.pack(side="left")
        ttk.Label(r2, text="Re-reads MimicKit's configs after you change a folder.", style="Dim.TLabel").pack(
            side="left", padx=10)
        ttk.Separator(st, orient="horizontal").pack(fill="x", pady=(12, 6))
        ttk.Label(st, text="LOOK", style="Sec.TLabel").pack(anchor="w")
        r3 = ttk.Frame(st)
        r3.pack(fill="x", pady=(4, 0))
        self.v_light = tk.BooleanVar(value=bool(self.s.get("light_mode", False)))
        cbx = ttk.Checkbutton(r3, text="Light mode", variable=self.v_light, command=self._toggle_theme)
        cbx.pack(side="left")
        self.cb_light = cbx
        Tip(cbx, "Dark mode is the default (easy on OLED screens). Tick for a light theme. Saved automatically.")
        ttk.Label(r3, text="Dark (true-black OLED) is the default.", style="Dim.TLabel").pack(side="left", padx=10)

    def _build_extras(self, ex):
        """Phone + notifications, MimicKit patches, overlay plugin buttons, update settings, About."""
        k = kscale(self.root)
        g = ttk.Frame(ex)
        g.pack(fill="x")
        rows = (
            ("b_remote", "Phone + notifications...", self.remote_dialog, HELP["remote"], "Watch training from your phone."),
            ("b_patches", "MimicKit patches...", self.patch_dialog, HELP["patches"],
             "Enables episode length and the per-step score."),
        )
        for r, (attr, txt, fn, tip, hint) in enumerate(rows):
            b = ttk.Button(g, text=txt, command=fn, width=24)
            b.grid(row=r, column=0, sticky="w", pady=3)
            Tip(b, tip)
            setattr(self, attr, b)
            ttk.Label(g, text=hint, style="Dim.TLabel").grid(row=r, column=1, sticky="w", padx=10)
        # overlay plugins add their buttons here (none in the public build; Z: Check for updates...)
        self.plugin_frame = ttk.Frame(g)
        self.plugin_frame.grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self.b_about = ttk.Button(g, text="About", command=self.about_dialog, width=24)
        self.b_about.grid(row=4, column=0, sticky="w", pady=3)
        Tip(self.b_about, "Version, build and licence of this launcher, and the automatic update settings.")
        ttk.Label(g, text="Version %s (build %s)" % (VERSION, build_id()), style="Dim.TLabel").grid(
            row=4, column=1, sticky="w", padx=10)
        if hasattr(self, "build_update_settings"):  # automatic update check + interval + Check now
            self.build_update_settings(g).grid(row=3, column=0, columnspan=2, sticky="we", pady=(6, 6))

    # ------------------------------------------------------------------ Train page, left column
    def _build_job(self, top):
        """'What to train': configs + hint, num_envs, output folder, Newton, progress target, Advanced, last preview."""
        k = kscale(self.root)
        g = ttk.Frame(top)
        g.pack(side="top", fill="x")
        g.columnconfigure(1, weight=1)
        self._jobbox = g
        PAD = dict(pady=3)
        self.v_train = tk.StringVar()
        self.v_view = tk.StringVar()
        ttk.Label(g, text="Training config").grid(row=0, column=0, sticky="w", **PAD)
        self.cb_train = ttk.Combobox(g, textvariable=self.v_train, state="readonly", width=12)
        self.cb_train.grid(row=0, column=1, sticky="we", **PAD)
        self.cb_train.bind("<<ComboboxSelected>>", self._train_changed)
        Tip(self.cb_train, HELP["trainsel"])
        self.l_preset_help = ttk.Label(g, text="", style="Dim.TLabel", wraplength=340, justify="left")
        self.l_preset_help.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(g, text="View config").grid(row=2, column=0, sticky="w", **PAD)
        self.cb_view = ttk.Combobox(g, textvariable=self.v_view, state="readonly", width=12)
        self.cb_view.grid(row=2, column=1, sticky="we", **PAD)
        self.cb_view.bind("<<ComboboxSelected>>", self._view_changed)
        Tip(self.cb_view, HELP["viewsel"])
        ttk.Label(g, text="num_envs").grid(row=3, column=0, sticky="w", **PAD)
        sw = ttk.Frame(g)
        sw.grid(row=3, column=1, sticky="we", **PAD)
        self.v_envs = tk.IntVar(value=DEFAULT_ENVS)
        sp = ttk.Spinbox(sw, from_=1, to=65536, increment=512, textvariable=self.v_envs, width=7)
        sp.pack(side="left")
        self.sp_envs = sp
        Tip(sp, HELP["envs"])
        self.b_envswitch = ttk.Button(sw, text="Apply while training", command=self.change_envs_live)
        self.b_envswitch.pack(side="left", padx=(6, 0))
        Tip(self.b_envswitch, HELP["envs_live"])
        self.l_envs_hint = ttk.Label(sw, text="", style="Err.TLabel")
        self.l_envs_hint.pack(side="left", padx=(6, 0))

        def envs_hint(*_):
            self.l_envs_hint.configure(text="" if self._envs_or_0() >= 1 else "Whole number, e.g. 64")

        self.v_envs.trace_add("write", envs_hint)
        flow(sw)  # the button goes under the box when the column is narrow (125 %)
        self.l_envswitch = ttk.Label(g, text="", style="Dim.TLabel", wraplength=330, justify="left")
        self.l_envswitch.grid(row=4, column=0, columnspan=2, sticky="w")
        self.l_envswitch.grid_remove()  # takes no room until there is something to say
        ttk.Label(g, text="Output folder").grid(row=5, column=0, sticky="w", **PAD)
        self.v_out = tk.StringVar()
        e = ttk.Entry(g, textvariable=self.v_out, width=12)
        e.grid(row=5, column=1, sticky="we", **PAD)
        self.e_out = e
        Tip(e, HELP["out"])
        self.v_newton = tk.BooleanVar(value=bool(self.s.get("force_newton", True)))
        c = ttk.Checkbutton(g, text="Use Newton engine", variable=self.v_newton, command=self._save)
        c.grid(row=6, column=1, sticky="w", **PAD)
        self.cb_newton = c
        Tip(c, HELP["newton"])
        # progress target (an estimate only - it never stops training)
        ttk.Label(g, text="Progress target").grid(row=7, column=0, sticky="w", **PAD)
        tgf = ttk.Frame(g)
        tgf.grid(row=7, column=1, sticky="we", **PAD)
        tgf.columnconfigure(0, weight=1)
        self.v_tkind = tk.StringVar(value="plateau (auto)")
        self.v_tval = tk.StringVar()
        self.cb_target = ttk.Combobox(tgf, textvariable=self.v_tkind, state="readonly", width=10,
                                      values=["plateau (auto)", "samples (millions)", "score (Train_Return)"])
        self.cb_target.grid(row=0, column=0, sticky="we")
        self.e_tval = ttk.Entry(tgf, textvariable=self.v_tval, width=7)
        self.e_tval.grid(row=0, column=1, padx=(4, 0))
        self.b_tset = ttk.Button(tgf, text="Set", width=4, command=self._target_from_widgets)
        self.b_tset.grid(row=0, column=2, padx=(4, 0))
        self.cb_target.bind("<<ComboboxSelected>>", lambda _=None: self._target_from_widgets())
        for w in (self.cb_target, self.e_tval, self.b_tset):
            Tip(w, HELP["target"])
        self._target_root = None
        self.est_disp = {}
        # Advanced (collapsible, open by default; remembered)
        ttk.Separator(top, orient="horizontal").pack(side="top", fill="x", pady=(8, 4))
        ah = ttk.Frame(top)
        ah.pack(side="top", fill="x")
        self.v_adv = tk.BooleanVar(value=bool(self.s.get("advanced_open", True)))
        self.b_adv = ttk.Label(ah, text="", style="Sec.TLabel", cursor="hand2")
        self.b_adv.pack(side="left")
        ttk.Label(ah, text="rarely needed", style="Dim.TLabel").pack(side="right")
        self.b_adv.bind("<Button-1>", lambda e: self._toggle_advanced())
        Tip(self.b_adv, "Show or hide the advanced options (Extra args, Model for Watch, Training settings, args files).")
        adv = ttk.Frame(top)
        self._adv = adv
        adv.columnconfigure(1, weight=1)
        ttk.Label(adv, text="Extra args").grid(row=0, column=0, sticky="w", **PAD)
        self.v_extra = tk.StringVar()
        e = ttk.Entry(adv, textvariable=self.v_extra, width=12)
        e.grid(row=0, column=1, sticky="we", **PAD)
        self.e_extra = e
        Tip(e, HELP["extra"])
        ttk.Label(adv, text="Model for Watch").grid(row=1, column=0, sticky="w", **PAD)
        mf = ttk.Frame(adv)
        mf.grid(row=1, column=1, sticky="we", **PAD)
        mf.columnconfigure(0, weight=1)
        self.v_model = tk.StringVar()
        e = ttk.Entry(mf, textvariable=self.v_model, width=10)
        e.grid(row=0, column=0, sticky="we")
        self.e_model = e
        Tip(e, HELP["model"])
        self.b_model_browse = ttk.Button(mf, text="Browse...", command=self._browse_model)
        self.b_model_browse.grid(row=0, column=1, padx=(4, 0))
        bfa = ttk.Frame(adv)  # args / settings buttons (+ profile ACTIONS), wraps
        bfa.grid(row=2, column=0, columnspan=2, sticky="we", pady=(4, 0))
        self.b_tsettings = ttk.Button(bfa, text="Training settings...", command=self.train_settings_dialog)
        self.b_tsettings.pack(side="left", padx=(0, 4), pady=2)
        Tip(self.b_tsettings, HELP["tsettings"])
        self._build_actions(bfa)  # launcher_profile.py ACTIONS (none in the public build; Z: Apply death patch)
        self.b_rescan = ttk.Button(bfa, text="Rescan args", command=self.rescan)
        self.b_rescan.pack(side="left", padx=(0, 4), pady=2)
        Tip(self.b_rescan, "Re-read MimicKit's args folder.")
        self.b_addargs = ttk.Button(bfa, text="Add args file...", command=self._add_custom)
        self.b_addargs.pack(side="left", padx=(0, 4), pady=2)
        Tip(self.b_addargs, HELP["custom"])
        flow(bfa)
        self._paint_advanced()
        # last preview card (bottom of the column)
        card = tk.Frame(self._train_left, bd=0, highlightthickness=1, padx=8, pady=6)
        card.pack(side="bottom", fill="x", pady=(8, 2), padx=(0, 4), before=self._top_outer)
        self._lastcard = card
        self.l_cardimg = tk.Label(card, text="\u25a3", bd=0, font=("Segoe UI", 20))
        self.l_cardimg.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 10))
        self.l_cardtitle = tk.Label(card, text="Last preview", font=("Segoe UI", 10, "bold"), anchor="w")
        self.l_cardtitle.grid(row=0, column=1, sticky="w")
        self.l_cardsub = tk.Label(card, text="", anchor="w")
        self.l_cardsub.grid(row=1, column=1, sticky="w")
        cb = ttk.Frame(card)
        cb.grid(row=2, column=1, sticky="w", pady=(4, 0))
        self.b_card_render = ttk.Button(cb, text="Render MP4", command=self.preview)
        self.b_card_render.pack(side="left")
        Tip(self.b_card_render, HELP["preview"])
        b = ttk.Button(cb, text="Preview page", command=lambda: self.show_page("preview"))
        b.pack(side="left", padx=(4, 0))
        Tip(b, "All preview options, the picture of the last render, Watch latest and View clip (Ctrl+3).")
        self.custom = list(self.s.get("custom_args", []))  # rescan() runs once the Preview page exists (_build)

    def _card_compact(self, on):
        """Squeeze the Last preview card by a line when the left column is only a few px short."""
        card = self._lastcard
        card.configure(pady=1 if on else 6)
        card.pack_configure(pady=(2, 1) if on else (8, 2))
        if on:
            self.l_cardsub.grid_remove()
        else:
            self.l_cardsub.grid()

    def _toggle_advanced(self):
        self.v_adv.set(not self.v_adv.get())
        self.s["advanced_open"] = bool(self.v_adv.get())
        self._save_settings_only()
        self._paint_advanced()

    def _paint_advanced(self):
        on = bool(self.v_adv.get())
        self.b_adv.configure(text=("\u25be ADVANCED" if on else "\u25b8 ADVANCED"))
        if on and not self._adv.winfo_manager():
            self._adv.pack(side="top", fill="x", after=self.b_adv.master)
        elif not on and self._adv.winfo_manager():
            self._adv.pack_forget()
        if hasattr(self, "_top_fit"):
            self.root.after_idle(self._top_fit)

    def _wrap_preset_help(self, width):
        wl = max(220, int(width))
        try:
            if abs(int(str(self.l_preset_help.cget("wraplength")) or 0) - wl) > 4:
                self.l_preset_help.configure(wraplength=wl)
                self.l_envswitch.configure(wraplength=wl)
        except (tk.TclError, ValueError):
            return

    # ------------------------------------------------------------------ Preview page
    def _build_preview_box(self, pv):
        """Every preview control: Choose clips... + All clips (greys out the choice), Clip layout, Reference ghost,
        Preview device, Pause training for preview, Render MP4, progress + status line, Cancel render set apart,
        Preview diagnostics; then 'Look live': Watch latest, View clip."""
        self.preview_box = pv
        k = kscale(self.root)
        PAD = dict(pady=4)

        def save_on_select(cb, key, var):
            cb.bind("<<ComboboxSelected>>", lambda _=None: (self.s.__setitem__(key, var.get()), self._save_settings_only()))

        body = self._scroll_area(pv)
        body.columnconfigure(1, weight=1)
        cf = ttk.Frame(body)
        cf.grid(row=0, column=0, columnspan=2, sticky="we", **PAD)
        b = ttk.Button(cf, text="Choose clips...", command=self.clips_dialog)
        b.pack(side="left")
        Tip(b, "Which motion clips the MP4 preview shows (up to 4), saved per training config. Greyed out while "
               "All clips is ticked.")
        self.b_clips = b
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
        rows = (
            ("Clip layout", "v_layout", "preview_layout", "All at once", list(CLIP_LAYOUTS), "layout", "cb_layout"),
            ("Reference ghost", "v_ghost", "preview_ghost", "Overlay", list(GHOST_MODES), "ghost", "cb_ghost"),
            ("Preview device", "v_pdev", "preview_device", "Auto", ["Auto", "CPU only", "GPU"], "pdevice", "cb_pdev"),
        )
        for r, (lab, var, key, dflt, vals, help_, attr) in enumerate(rows, 1):
            ttk.Label(body, text=lab).grid(row=r, column=0, sticky="w", padx=(0, 10), **PAD)
            v = tk.StringVar(value=self.s.get(key, dflt))
            setattr(self, var, v)
            cb = ttk.Combobox(body, textvariable=v, values=vals, state="readonly", width=14)
            cb.grid(row=r, column=1, sticky="we", **PAD)
            setattr(self, attr, cb)
            Tip(cb, HELP[help_])
            save_on_select(cb, key, v)
        self.v_pause = tk.BooleanVar(value=bool(self.s.get("preview_pause_training", False)))
        cbp = ttk.Checkbutton(body, text="Pause training for preview", variable=self.v_pause, command=lambda: (
            self.s.__setitem__("preview_pause_training", bool(self.v_pause.get())), self._save_settings_only()))
        cbp.grid(row=4, column=0, columnspan=2, sticky="w", **PAD)
        self.cb_pause = cbp
        Tip(cbp, HELP["pausepreview"])
        b = ttk.Button(body, text="\u25b6  Render MP4", command=self.preview, style="Primary.TButton")
        b.grid(row=5, column=0, columnspan=2, sticky="we", pady=(8, 4))
        Tip(b, HELP["preview"])
        self.run_btns = getattr(self, "run_btns", {})
        self.run_btns["preview"] = b
        prog = ttk.Frame(body)
        prog.grid(row=6, column=0, columnspan=2, sticky="we", pady=(2, 0))
        self.pv_bar = ttk.Progressbar(prog, mode="determinate", maximum=100)
        self.pv_bar.pack(side="top", fill="x")
        # one status line: render stage and the 'Pause training for preview' notices (red for failures)
        self.l_pvprog = ttk.Label(prog, text="No render running.", style="Dim.TLabel", justify="left")
        self.l_pvprog.pack(side="top", anchor="w", pady=(3, 0))
        self.l_pause = self.l_pvprog
        prog.bind("<Configure>", lambda e: self.l_pvprog.configure(wraplength=max(160, e.width - 4)), add="+")
        act = ttk.Frame(body)
        act.grid(row=7, column=0, columnspan=2, sticky="we", pady=(8, 2))
        # Cancel render: set apart on the left, Preview diagnostics on the right - only the preview, never training
        self.b_stoprender = ttk.Button(act, text="Cancel render", command=self._stop_render_click, width=14)
        self.b_stoprender.pack(side="left")
        Tip(self.b_stoprender, HELP["stoprender"])
        self.b_stoprender.state(["disabled"])
        b = ttk.Button(act, text="Preview diagnostics", command=self.preview_diag)
        b.pack(side="right")
        self.b_pdiag = b
        Tip(b, HELP["pdiag"])
        ttk.Separator(body, orient="horizontal").grid(row=8, column=0, columnspan=2, sticky="we", pady=(12, 6))
        ttk.Label(body, text="LOOK LIVE (opens MimicKit's viewer)", style="Sec.TLabel").grid(
            row=9, column=0, columnspan=2, sticky="w")
        lf = ttk.Frame(body)
        lf.grid(row=10, column=0, columnspan=2, sticky="w", pady=(6, 0))
        for key, txt, fn in (("watch", "Watch latest", self.watch), ("view", "View clip", self.view)):
            b = ttk.Button(lf, text=txt, command=fn, width=14)
            b.pack(side="left", padx=(0, 6))
            Tip(b, HELP[key])
            self.run_btns[key] = b
        self.root.after(1000, self._pv_tick)

    def _build_preview_page(self, page):
        k = kscale(self.root)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        left = TitleBox(page, text="Last render", padding=(6, 4, 6, 6))
        left.grid(row=0, column=0, sticky="nsew")
        right = TitleBox(page, text="Make a preview video", padding=(10, 4, 10, 8))
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        page.columnconfigure(1, minsize=int(420 * k))
        self._pv_left, self._pv_right = left, right

    def _build_preview_left(self, left):
        hdr = ttk.Frame(left)
        hdr.pack(side="top", fill="x", pady=(0, 6))
        self.l_lastrender = ttk.Label(hdr, text="", style="Dim.TLabel")
        self.l_lastrender.pack(side="left")
        b = ttk.Button(hdr, text="Open folder", command=lambda: self._open_last_preview(folder=True))
        b.pack(side="right")
        Tip(b, "Open the folder of the newest preview MP4.")
        b = ttk.Button(hdr, text="Open video", command=self._open_last_preview)
        b.pack(side="right", padx=(0, 6))
        Tip(b, "Play the newest preview MP4 in your video player.")
        host = tk.Frame(left, bd=0, highlightthickness=0)
        host.pack(side="top", fill="both", expand=True)
        self._pv_host = host
        self.l_pvimg = tk.Label(host, text="", bd=0, justify="center")
        self.l_pvimg.place(relx=0.5, rely=0.5, anchor="center")
        host.bind("<Configure>", lambda e: self.root.after_idle(self._still_paint), add="+")

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
            self._still_check()  # 1.0.0: picture of the newest preview (Preview page + Train card), every 5 s
        except tk.TclError:
            return  # window closing
        except Exception as e:
            log_exc("preview box tick", e)
        self.root.after(1000, self._pv_tick)

    def _build_command_box(self, parent):
        """1.0.0: the exact command lives on the Results page (_build_results); kept for overlays that call it."""
        if not hasattr(self, "t_cmd"):
            self.t_cmd = tk.Text(parent, height=2, width=60, wrap="word", state="disabled")
            self.t_cmd.pack(fill="x")

    def _build_status(self, right):
        """Top of 'What's happening': stage + iteration, the status text and the GPU line (the VRAM meter is in the
        transport strip)."""
        top = ttk.Frame(right)
        top.pack(side="top", fill="x")
        self.st_stage = ttk.Label(top, text="Idle", style="Big.TLabel")
        self.st_stage.pack(side="left")
        self.st_iter = ttk.Label(top, text="", style="Big.TLabel")
        self.st_iter.pack(side="left", padx=(10, 0))
        self.l_status = ttk.Label(right, text="Idle.", justify="left", style="Dim.TLabel", wraplength=280)
        self.l_status.pack(side="top", anchor="w", fill="x", pady=(2, 0))
        self.l_gpu = ttk.Label(right, text="GPU: checking...", justify="left", style="Good.TLabel", wraplength=280)
        self.l_gpu.pack(side="top", anchor="w", fill="x", pady=(2, 4))
        # wrap to the column instead of being cut off on the right
        def wrap(e):
            w = e.width - 24 if (getattr(self, "_train_mode", None) or ("3col",))[0] == "3col" else e.width // 2 - 36
            for lab in (self.l_status, self.l_gpu):
                if abs(int(str(lab.cget("wraplength")) or 0) - max(160, w)) > 3:
                    lab.configure(wraplength=max(160, w))

        right.bind("<Configure>", wrap, add="+")

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
        rb = getattr(self, "run_btns", None) or {}
        try:  # 1.0.0: the Resume menu's first entry and 'Continue from selected run' follow Resume / Continue
            if hasattr(self, "_resume_menu") and "resume" in rb:
                self._resume_menu.entryconfigure(0, state="disabled" if rb["resume"].instate(["disabled"]) else "normal")
            if hasattr(self, "b_continue_sel") and "continue" in rb:
                self.b_continue_sel.state(["disabled"] if rb["continue"].instate(["disabled"]) else ["!disabled"])
            if hasattr(self, "b_card_render") and "preview" in rb:
                self.b_card_render.state(["disabled"] if rb["preview"].instate(["disabled"]) else ["!disabled"])
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
        """Training progress charts with their toolbar (Current session only, Per-step chart, Home, Save picture)."""
        right = TitleBox(mid, text="Training progress (refreshed every 10 s)", padding=(4, 2, 4, 4))
        right.pack(side="top", fill="both", expand=True)
        self.prog_frame = right
        try:
            dpi = max(72.0, min(240.0, float(self.root.winfo_fpixels("1i"))))
        except (tk.TclError, ValueError):
            dpi = 96.0
        self.fig = Figure(figsize=(560 / dpi, 500 / dpi), dpi=dpi, layout="constrained")
        self.v_ps = tk.BooleanVar(value=bool(self.s.get("per_step_chart", True)))
        self.ax3 = None
        self._make_axes()
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        # chart navigation (no modes): left-drag = pan time (x) of both charts, wheel = zoom time at the cursor, y fixed
        # to the full data range (manual y drag only when a chart has visible data outside its y range), Home /
        # double-click = reset
        self.xview = None
        self.drag = None
        self.v_cur = tk.BooleanVar(value=bool(self.s.get("current_session_only", False)))
        navf = ttk.Frame(right)
        navf.pack(side="top", fill="x", pady=(0, 2))
        self.navf = navf
        c = ttk.Checkbutton(navf, text="Current session only", variable=self.v_cur, command=self._cur_toggled)
        c.pack(side="left", padx=(0, 10))
        self.cb_cursess = c
        c2 = ttk.Checkbutton(navf, text="Per-step chart", variable=self.v_ps, command=self._ps_toggled)
        c2.pack(side="left", padx=(0, 10))
        self.cb_ps = c2
        self.b_home = ttk.Button(navf, text="\u2302 Home", width=8, command=self._auto_follow)
        self.b_home.pack(side="left", padx=(0, 4))
        self.b_save = ttk.Button(navf, text="Save picture...", command=self._save_chart)
        self.b_save.pack(side="left")
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
        flow(navf)  # the toolbar wraps onto a 2nd row instead of clipping at 125 %
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.get_tk_widget().bind("<Configure>", self._chart_resized, add="+")
        # chart help: '?' badge in the chart's title row, next to 'Training progress'
        self.chart_help = tk.Label(right.title_row, text="?", width=2, cursor="question_arrow")
        self.chart_help.pack(side="left", padx=(0, 6), before=right._title)
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
        # 1.0.0 (Mockup D): section labels, big transport buttons, the plateau bar, the runs list
        st.configure("Sec.TLabel", background=T["bg"], foreground=T["accent"], font=("Segoe UI", 9, "bold"))
        big = ("Segoe UI", 10, "bold")
        st.configure("Big.TButton", background=T["btn"], foreground=T["fg"], bordercolor=T["border"],
                     padding=(14, 7), font=big)
        st.map("Big.TButton", background=[("disabled", T["dis_bg"]), ("pressed", T["sel"]), ("active", T["btn_act"])],
               foreground=[("disabled", T["dis_fg"])])
        st.configure("BigNarrow.TButton", background=T["btn"], foreground=T["fg"], bordercolor=T["border"],
                     padding=(4, 7), font=big)
        st.map("BigNarrow.TButton", background=[("disabled", T["dis_bg"]), ("pressed", T["sel"]),
                                                ("active", T["btn_act"])], foreground=[("disabled", T["dis_fg"])])
        st.configure("Blue.TButton", background=T["blue"], foreground=T["blue_fg"], bordercolor=T["blue_b"],
                     padding=(12, 7), font=big)
        st.map("Blue.TButton", background=[("disabled", T["dis_bg"]), ("pressed", T["sel"]), ("active", T["blue_act"])],
               foreground=[("disabled", T["dis_fg"])], bordercolor=[("disabled", T["border"])])
        st.configure("BigStop.TButton", background=T["stop"], foreground=T["stop_fg"], bordercolor=T["stop"],
                     padding=(12, 7), font=big)
        st.map("BigStop.TButton", background=[("disabled", T["stop_dis"]), ("pressed", T["stop_act"]),
                                              ("active", T["stop_act"])],
               foreground=[("disabled", T["stop_dis_fg"])], bordercolor=[("disabled", T["stop_dis"])])
        st.configure("Primary.TButton", background=T["go"], foreground=T["go_fg"], bordercolor=T["go"],
                     padding=(10, 8), font=("Segoe UI", 11, "bold"))
        st.map("Primary.TButton", background=[("disabled", T["dis_bg"]), ("pressed", T["sel"]), ("active", T["go_act"])],
               foreground=[("disabled", T["dis_fg"])])
        st.configure("Plateau.Horizontal.TProgressbar", background=T["accent"], troughcolor=T["field"],
                     bordercolor=T["border"], lightcolor=T["accent"], darkcolor=T["accent"])
        st.configure("Horizontal.TProgressbar", troughcolor=T["field"], bordercolor=T["border"])
        st.configure("Treeview", background=T["field"], fieldbackground=T["field"], foreground=T["fg"],
                     bordercolor=T["border"], rowheight=int(22 * kscale(self.root)))
        st.map("Treeview", background=[("selected", T["sel"])], foreground=[("selected", T["fg"])])
        st.configure("Treeview.Heading", background=T["btn"], foreground=T["fg"], bordercolor=T["border"])
        st.map("Treeview.Heading", background=[("active", T["btn_act"])])
        st.configure("TSeparator", background=T["border"])
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
        self._layout_theme()

    def _layout_theme(self):
        """1.0.0: classic tk widgets of the page shell (tabs, stats, warning card, last preview card, picture)."""
        if hasattr(self, "_tabs_paint"):
            self._tabs_paint()
        for w in (getattr(self, "l_gpuname", None),):
            if w is not None:
                w.configure(bg=T["bg"], fg=T["fg"])
        for w in (getattr(self, "_tp_gpu", None),):
            if w is not None:
                w.configure(bg=T["bg"])
        card = getattr(self, "_lastcard", None)
        if card is not None:
            card.configure(bg=T["panel"], highlightbackground=T["border"], highlightcolor=T["border"])
            for w in (self.l_cardimg, self.l_cardtitle, self.l_cardsub):
                w.configure(bg=T["panel"] if w is not self.l_cardimg else T["plot"], fg=T["fg"] if w is self.l_cardtitle
                            else T["dim"])
        wc = getattr(self, "_warncard", None)
        if wc is not None:
            wc.configure(bg=T["warn_bg"], highlightbackground=T["warn_border"], highlightcolor=T["warn_border"])
            self.st_wl.configure(bg=T["warn_bg"], fg=T["warn"])
            self.st_warn.configure(bg=T["warn_bg"], fg=T["fg"])
        for w in (getattr(self, "_pv_host", None), getattr(self, "l_pvimg", None)):
            if w is not None:
                w.configure(bg=T["plot"])
        if getattr(self, "l_pvimg", None) is not None:
            self.l_pvimg.configure(fg=T["dim"])

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
                    gname = ok[0][0].replace("NVIDIA GeForce ", "").replace("NVIDIA ", "") if ok else None
                except Exception as e:
                    txt = "GPU: nvidia-smi not available (%s)" % type(e).__name__
                    vr = (None, None)
                    gname = None
                if getattr(self, "_closed", False):
                    return  # window closed: just end this poll thread
                # worker thread: never call Tk here - the GUI thread runs these from rq
                self.rq.put(lambda v=vr, t=txt, n=gname: (setattr(self, "gpu_name", n), self._set_vram(*v),
                                                          self.l_gpu.configure(text=t)))
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
        av = getattr(self, "v_autoscroll", None)
        if av is None or av.get():  # Results page: Auto-scroll (on by default = as before)
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
