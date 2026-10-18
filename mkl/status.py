# MimicKit Launcher - status panel, health banner, error cards, "looks trained" prompt.
# Copyright (C) 2026 Ross2K. SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0 (see LICENSE).
"""GUI for mkl.status_model: everything here is driven by MimicKit's console output (no extra processes)."""

from mkl.core import *
from mkl import status_model as SM
import tkinter.font as tkfont
import re

BANNER_COL = {"idle": "dim", "info": "accent", "ok": "good", "warn": "warn", "error": "err"}
MONO = ("DejaVu Sans Mono", 9) if not IS_WIN else ("Consolas", 9)


class StatusMixin:
    # ------------------------------------------------------------------ setup
    def _status_init(self):
        self.sm = SM.StatusModel()
        self.sm_q = (
            queue.Queue()
        )  # console lines of the main run + ("preview_end", rc, log) from reader threads
        self.cards = {}  # id -> (frame, ctx)
        self._card_seen = (
            set()
        )  # card ids already shown for this run (dismissed ones stay dismissed)
        self._looks = None  # chain key the "looks trained" prompt was shown for
        self._looks_now = False
        self._ckpt_t = 0
        self._ckpt_seen = None  # (path, mtime) of the last model.pt seen, to report new saves
        self._ep_log = (0.0, None, None)  # (read time, log.txt path, its newest Train_Episode_Length)

    def _build_banner(self):
        """1.0.0: the health line is the pill in the transport strip (every page); 'Hover any control = help', the
        update notice and the version sit at the right of the tab bar."""
        f = tk.Frame(self._tp_bannerhost, padx=8, pady=2)
        f.pack(side="left", fill="x", expand=True)
        self.ban_f = f
        # keeps the strip from changing height while the window width stays the same (2 lines reserved, then
        # grow-only): the charts above never jump when the health text gets longer (and a chart drag stays exact)
        self._ban_spacer = tk.Frame(f, width=1, height=1, bd=0, highlightthickness=0)
        self._ban_spacer.pack(side="left", fill="y")
        self._ban_w = None
        self.ban_dot = tk.Label(f, text="\u25cf", font=("Segoe UI", 11))
        self.ban_dot.pack(side="left")
        self.ban_detail = tk.Label(f, text="", anchor="e")  # grey technical detail (exit code)
        self.ban_detail.pack(side="right", padx=(8, 0))
        self.ban_lab = tk.Label(f, text=SM.BANNER["idle"][1], anchor="w", justify="left")
        self.ban_lab.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.ban_level = "idle"
        f.bind("<Configure>", self._wrap_banner)
        tr = self._tab_right
        # a0.9.2: 'Update X available' notice (automatic check) - hidden until there is one; click = details
        self.l_update = ttk.Label(tr, text="", style="Err.TLabel", cursor="hand2")
        self.l_update.grid(row=0, column=0, padx=(0, 12), sticky="e")
        self.l_update.bind("<Button-1>", lambda e: self.open_update_notice())
        Tip(self.l_update, "A newer launcher version is out. Click for details. Nothing is installed automatically.")
        self.l_update.grid_remove()
        self.ban_hint = tk.Label(tr, text="Hover any control = help  \u00b7  Ctrl+1..4 = pages")
        self.ban_hint.grid(row=0, column=1, sticky="e")
        self.ban_ver = tk.Label(tr, text="version " + VERSION)
        self.ban_ver.grid(row=0, column=2, sticky="e", padx=(12, 0))

    def _wrap_banner(self, _=None):
        """The banner text wraps onto a second line instead of being cut off on a narrow window."""
        room = self.ban_f.winfo_width() - self.ban_dot.winfo_reqwidth() - self.ban_detail.winfo_reqwidth() - 30
        if int(self.ban_lab.cget("wraplength")) != max(160, room):
            self.ban_lab.configure(wraplength=max(160, room))
        w = self.ban_f.winfo_width()
        if w != self._ban_w:  # new width: back to the 2-line reservation, grow from there
            self._ban_w = w
            try:
                ls = tkfont.Font(font=self.ban_lab.cget("font")).metrics("linespace")
            except tk.TclError:
                ls = 16
            self._ban_spacer.configure(height=2 * ls + 2)
        self.root.after_idle(self._ban_hold)

    def _ban_hold(self):
        try:
            h = self.ban_lab.winfo_reqheight()
            if h > int(self._ban_spacer.cget("height")):
                self._ban_spacer.configure(height=h)
        except tk.TclError:
            pass

    def _build_cards(self, parent):
        self.cards_f = ttk.Frame(parent)  # packed above the charts while a card is shown (_show_card)

    def _build_output(self, right):
        """'What's happening' (right column of the Train page): events, last checkpoint, next save, the amber
        Warnings card and a link to the Results page (full console + exact command)."""
        self.v_outview = tk.StringVar(value="status")
        self.st_panel = right
        self.l_outhint = ttk.Label(right, text="from MimicKit's console output", style="Dim.TLabel")
        self._build_status_panel(right)

    def _build_status_panel(self, p):
        bot = ttk.Frame(p)
        bot.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Label(bot, text="Full console:", style="Dim.TLabel").pack(side="left")
        self.b_open_console = ttk.Button(bot, text="\u2630 Results page", command=lambda: self._set_outview("console"))
        self.b_open_console.pack(side="left", padx=(6, 0))
        Tip(self.b_open_console, "The full MimicKit console, the exact command and your runs (Ctrl+4).")
        wc = tk.Frame(p, bd=0, highlightthickness=1, padx=8, pady=6)
        wc.pack(side="bottom", fill="x", pady=(8, 0))
        self._warncard = wc
        self.st_wl = tk.Label(wc, text="\u26a0 Warnings and errors", anchor="w", font=("Segoe UI", 10, "bold"))
        self.st_wl.pack(side="top", fill="x")
        self.st_warn = tk.Text(wc, height=4, wrap="word", width=24, relief="flat")
        self.st_warn.pack(side="top", fill="both", expand=True, pady=(4, 0))
        kv = ttk.Frame(p)
        kv.pack(side="bottom", fill="x", pady=(6, 0))
        kv.columnconfigure(1, weight=1)
        self.st_ckpt = ttk.Label(kv, text="Last checkpoint: none yet", justify="left")
        self.st_ckpt.grid(row=0, column=0, columnspan=3, sticky="w")
        kv.bind("<Configure>", lambda e: self.st_ckpt.configure(wraplength=max(180, e.width - 4)), add="+")
        ttk.Label(kv, text="Next save").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.st_save = ttk.Progressbar(kv, mode="determinate", maximum=1, length=100)
        self.st_save.grid(row=1, column=1, sticky="we", padx=6, pady=(4, 0))
        self.st_save_l = ttk.Label(kv, text="", style="Dim.TLabel")
        self.st_save_l.grid(row=1, column=2, sticky="e", pady=(4, 0))
        self.st_events = tk.Text(p, height=8, wrap="word", width=24, relief="flat")
        self.st_events.pack(side="top", fill="both", expand=True)
        for w in (self.st_events, self.st_warn):
            w.configure(state="disabled")
        self._status_sig = None

    def _set_outview(self, v):
        self.v_outview.set(v)
        self._outview_changed()

    def _scroll_area(self, outer, need=None):
        """a0.8.3: the Status view scrolls instead of being cut off on short screens (1080p at 125 %). The inner
        frame fills the visible height when it fits (so its log still stretches), and scrolls when it doesn't."""
        cv = tk.Canvas(outer, highlightthickness=0, bd=0, bg=T["bg"])
        ys = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=ys.set)
        cv.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(cv)
        win = cv.create_window(0, 0, window=inner, anchor="nw")
        self._st_canvas = getattr(self, "_st_canvas", None) or cv
        self._scroll_canvases = getattr(self, "_scroll_canvases", []) + [cv]

        def fit(_=None):
            need_h = need() if need else inner.winfo_reqheight()
            h = max(cv.winfo_height(), need_h)
            cv.itemconfigure(win, width=cv.winfo_width(), height=h)
            cv.configure(scrollregion=(0, 0, cv.winfo_width(), h))
            if need_h > cv.winfo_height() + 2:
                if not ys.winfo_manager():
                    ys.pack(side="right", fill="y", before=cv)
            elif ys.winfo_manager():
                ys.pack_forget()
                cv.yview_moveto(0)

        cv.bind("<Configure>", fit)
        inner.bind("<Configure>", lambda e: cv.after_idle(fit))

        def wheel(e):
            if ys.winfo_manager():
                cv.yview_scroll(-1 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else 1, "units")

        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            cv.bind(seq, wheel)
            inner.bind(seq, wheel)
        return inner

    def _outview_changed(self, save=True):
        """1.0.0: 'console' = the Results page (full console + exact command), 'status' = the Train page."""
        v = self.v_outview.get()
        self.show_page("results" if v == "console" else "train")
        if save:
            self.s["output_view"] = v
            self._save_settings_only()
        self._status_refresh(force=True)

    def _status_theme(self):
        if not hasattr(self, "ban_f"):
            return
        for cv in getattr(self, "_scroll_canvases", []):
            cv.configure(bg=T["bg"])
        for w in (self.st_events, self.st_warn):
            w.configure(
                bg=T["log_bg"],
                fg=T["log_fg"],
                insertbackground=T["fg"],
                highlightthickness=0,
                padx=6,
                pady=4,
            )
        # 1.0.0 UX: the event list is part of the panel (themed like it, light theme too), not a black log box
        self.st_events.configure(bg=T["bg"], fg=T["fg"], padx=0, pady=2, font="TkDefaultFont")
        try:
            ind = tkfont.nametofont("TkDefaultFont").measure("00:00  ")
        except tk.TclError:
            ind = 40
        self.st_events.tag_configure("ev", lmargin2=ind, spacing3=5)
        self.st_warn.tag_configure("warn", foreground=T["warn"])
        self.st_warn.tag_configure("err", foreground=T["err"])
        self.st_warn.tag_configure("dim", foreground=T["dim"])
        self.st_events.tag_configure("dim", foreground=T["dim"])
        for t, a, b, c in self.tiles.values():
            for w in (t, a, b, c):
                w.configure(bg=T["bg"])
            a.configure(fg=T["dim"])
            b.configure(fg=T["fg"])
            c.configure(fg=T["dim"])
        self._paint_banner(force=True)
        for cid, (fr, ctx) in list(self.cards.items()):
            self._close_card(cid, remember=False)
            self._show_card(cid, **ctx)

    # ------------------------------------------------------------------ feeding (GUI thread)
    def _status_reset(self, kind, it=None):
        self.sm.reset(ipo=self._ipo(it) if kind == "train" else None, kind=kind)
        self._card_seen = set()
        for cid in list(self.cards):
            if cid != "looks_trained":
                self._close_card(cid, remember=False)
        try:
            while True:
                self.sm_q.get_nowait()
        except queue.Empty:
            pass

    def _ipo(self, it):
        """iters_per_output of the agent config that will be used (edited copy first)."""
        try:
            it = it or self._item("train")
            if not it:
                return None
            mk = self.mk()
            _, ag = self._cfg_files(it)
            cur = TS.current(mk, it["name"])
            ag = (cur or {}).get("agent") or ag
            if not ag:
                return None
            with open(os.path.join(mk, ag), encoding="utf-8") as f:
                v = TS.get(f.read(), "iters_per_output")
            return int(v) if v else None
        except (OSError, ValueError, TypeError) as e:
            log_exc("status: reading iters_per_output", e)
            return None

    def _status_tick(self):
        try:
            self._status_drain()
            self._status_refresh()
        except Exception as e:  # never let the status panel stop the window
            log_exc("status: tick", e)
        self.root.after(1000, self._status_tick)

    def _status_drain(self):
        n_err = len(self.sm.errors)
        ended = self.sm.exit_code
        try:
            for _ in range(2000):
                x = self.sm_q.get_nowait()
                if isinstance(x, tuple):
                    self._preview_ended(*x[1:])
                else:
                    self.sm.feed(x)
        except queue.Empty:
            pass
        if len(self.sm.errors) != n_err or (self.sm.exit_code is not None and ended is None):
            self._diagnose()

    def _diagnose(self):
        running = bool(self.proc and self.proc.poll() is None)
        for cid in SM.diagnose_text(self.sm.text):
            if cid in self._card_seen and cid != "cuda_oom":
                continue
            ctx = dict(running=running)
            if cid == "cuda_oom":
                try:
                    ctx["n"] = SM.halve_envs(self.v_envs.get())
                except (tk.TclError, ValueError):
                    ctx["n"] = 512
            elif cid == "bad_yaml":
                f, ln, prob = SM.yaml_problem(self.sm.text)
                ctx.update(file=f, line=ln, problem=prob)
            elif cid == "no_model":
                ctx.update(folder=self.outdir_abs(), ipo=self.sm.ipo or self._ipo(None))
            elif cid == "mk_missing":
                ctx.update(folder=self.mk())
            if cid in self.cards and self.cards[cid][1] == ctx:
                continue
            self._show_card(cid, **ctx)

    def _preview_ended(self, rc, logp=None):
        if hasattr(self, "_render_prog_done"):
            self._render_prog_done(rc)  # phone progress bar
        txt = "exit code %s\n" % rc
        try:
            with open(logp, "rb") as f:
                f.seek(max(0, os.path.getsize(logp) - 20000))
                txt += f.read().decode("utf-8", "replace")
        except (OSError, TypeError):
            pass
        if SM._ACCESS.search(txt) and self.v_pdev.get() != "GPU":
            self._show_card("cpu_preview_crash")

    # ------------------------------------------------------------------ painting
    def _paint_banner(self, level=None, text=None, force=False):
        level = level or self.ban_level
        if text is not None:
            # 1.0.0 UX: short pill while healthy ('Training \u00b7 iter N'; the speed is in its own tile), full text on hover
            m_ = re.match(r"Training normally - iteration (\d+)[,.]", text)
            self.ban_lab.configure(text="Training \u00b7 iter %s" % m_.group(1) if m_ else text)
            Tip(self.ban_lab, text)
            self.root.after_idle(self._ban_hold)
        self.ban_level = level
        col = T.get(BANNER_COL.get(level, "dim"), T["fg"])
        bg = T["panel"]
        self.ban_f.configure(bg=bg)
        self._ban_spacer.configure(bg=bg)
        self.ban_ver.configure(bg=T["bg"], fg=T["dim"])
        self.ban_hint.configure(bg=T["bg"], fg=T["dim"])
        self.ban_detail.configure(bg=bg, fg=T["dim"])
        self.ban_dot.configure(bg=bg, fg=col)
        self.ban_lab.configure(bg=bg, fg=T["fg"] if level in ("idle", "info", "ok") else col)

    def _status_refresh(self, force=False):
        m = self.sm
        running = bool(self.proc and self.proc.poll() is None)
        lvl, text = SM.health(m, running, looks_trained=self._looks_now)
        pend = self._pending_text() if hasattr(self, "_pending_text") else ""
        if pend and running:  # e.g. 'Training normally. Will stop after the next save.' (UX a0.6.1 item)
            text = "%s. %s." % (text.rstrip(". "), pend.rstrip(". "))
        if (lvl, text) != (self.ban_level, self.ban_lab.cget("text")):
            self._paint_banner(lvl, text)
        detail = SM.banner_detail(m, running)
        if detail != self.ban_detail.cget("text"):
            self.ban_detail.configure(text=detail)
            self._wrap_banner()
        stage = (
            m.stage
            if running or m.iteration is not None
            else ("idle" if m.exit_code is None else m.ended_text())
        )
        if not running and m.exit_code is not None:
            stage = m.ended_text().rstrip(".")
        if m.kind != "train" and running:
            stage = {"watch": "Watch window open", "view": "Playing clips"}.get(m.kind, m.kind)
        self.st_stage.configure(text=stage[:1].upper() + stage[1:])
        self.st_iter.configure(text="Iteration %d" % m.iteration if m.iteration is not None else "")
        ns = m.next_save()
        if ns:
            done, ipo = ns
            self.st_save.configure(maximum=ipo, value=done)
            self.st_save_l.configure(text="%d / %d iterations" % (done, ipo))
        else:
            self.st_save.configure(maximum=1, value=0)
            self.st_save_l.configure(text="")
        tl = m.tiles()
        tr, te = tl["score"]
        self._tile(
            "score",
            "%.2f" % tr if tr is not None else "-",
            "test %.2f" % te if te is not None else "higher is better",
        )
        r = tl["rate"]
        self._tile("rate", "%.1f M/h" % (r / 1e6) if r else "-", "samples per hour")
        ep, sub = tl["ep_len"], "steps per episode"
        if ep is None:  # stock MimicKit writes episode length only to log.txt (the logging patch adds it live)
            ep, sub = self._ep_from_log(), "steps per episode (log.txt)"
        self._tile(
            "ep",
            "%.0f" % ep if ep is not None else "-",
            sub if ep is not None else "needs MimicKit patches...",
        )
        self._paint_ckpt()
        sig = (
            len(m.events),
            m.events[-1] if m.events else None,
            tuple(m.warnings[-6:]),
            tuple(m.errors[-6:]),
        )
        if sig != self._status_sig or force:
            self._status_sig = sig
            self._fill(  # 1.0.0: Mockup D event list - newest first, time column, wrapped lines indented
                self.st_events,
                [
                    (time.strftime("%H:%M", time.localtime(t)) + "  ", "dim", x, "")
                    for t, x in reversed(m.events[-12:])
                ]
                or [("", "", "Nothing yet.", "dim")],
                top=True,
            )
            rows = [
                (time.strftime("%H:%M", time.localtime(t)) + "  ", "dim", l, "err")
                for t, l in m.errors[-6:]
            ]
            rows += [
                (
                    time.strftime("%H:%M", time.localtime(t)) + "  ",
                    "dim",
                    l + ("  (x%d)" % c if c > 1 else ""),
                    "warn",
                )
                for t, l, c in m.warnings[-6:]
            ]
            rows.sort(key=lambda r: r[0])
            self._fill(self.st_warn, rows or [("", "", "None.", "dim")])
            ne, nw = len(m.errors), len(m.warnings)
            self.st_wl.configure(
                text=(
                    "\u26a0 Errors (%d) and warnings (%d)" % (ne, nw)
                    if ne or nw
                    else "\u26a0 Warnings and errors"
                )
            )

    def _tile(self, k, value, sub):
        t, a, b, c = self.tiles[k]
        if b.cget("text") != value:
            b.configure(text=value)
        if c.cget("text") != sub:
            c.configure(text=sub)
            base = getattr(self, "_tile_tips", {}).get(k, "")
            for w in (t, a, b):  # 1.0.0: the tile's small print is in its hover help
                Tip(w, base + ("\n\nNow: %s" % sub if sub else ""))

    def _fill(self, w, rows, top=False):
        w.configure(state="normal")
        w.delete("1.0", "end")
        for pre, ptag, text, tag in rows:
            w.insert("end", pre, ptag)
            w.insert("end", text + "\n", tag)
        w.tag_add("ev", "1.0", "end")
        w.configure(state="disabled")
        w.see("1.0" if top else "end")

    def _ep_from_log(self):
        """Newest Train_Episode_Length of the shown run's log.txt (re-read every 30 s, or when the run changes)."""
        p = os.path.join(self.run_dir or self.outdir_abs(), "log.txt")
        t, seen, v = self._ep_log
        if seen == p and time.time() - t < 30:
            return v
        v = None
        try:
            vals = [x for x in parse_log(p).get("Train_Episode_Length", []) if x == x]
            v = vals[-1] if vals else None
        except Exception as e:
            log_exc("status: episode length from log.txt", e)
        self._ep_log = (time.time(), p, v)
        return v

    def _note_new_save(self, p, t):
        """A model.pt newer than the last one seen while training runs -> 'Progress saved' event."""
        seen, self._ckpt_seen = self._ckpt_seen, (p, t)
        if seen and (p, t) != seen and t > seen[1] and self.proc and self.proc.poll() is None:
            self.sm.note_save()

    def _paint_ckpt(self):
        if time.time() - self._ckpt_t < 5:
            return
        self._ckpt_t = time.time()
        try:
            p = self._latest_model()
        except Exception as e:
            log_exc("status: latest model", e)
            p = None
        if not p or not os.path.exists(p):
            self.st_ckpt.configure(text="Last checkpoint: none yet")
            return
        t = os.path.getmtime(p)  # re-read every time: the 'ago' text and new saves follow the file
        self._note_new_save(p, t)
        ago = int((time.time() - t) // 60)
        it = self.sm.last_save_iteration()
        self.st_ckpt.configure(
            text="Last checkpoint: %s, %s (%s)%s"
            % (
                os.path.basename(os.path.dirname(p)) + "/" + os.path.basename(p),
                time.strftime("%H:%M", time.localtime(t)),
                "just now" if ago < 1 else "%d min ago" % ago,
                (
                    ", iteration %d" % it
                    if it is not None and self.proc and self.proc.poll() is None
                    else ""
                ),
            )
        )

    # ------------------------------------------------------------------ cards
    def _show_card(self, cid, **ctx):
        """Error card (or the 'looks trained' prompt) above the output panel. One per id."""
        if cid in self.cards:
            self._close_card(cid, remember=False)
        self._card_seen.add(cid)
        if cid == "milestone":  # a0.9.0: 'First steps!' / 'Walking well' (one card, newest level wins)
            c = dict(
                title=ctx.get("title", "Milestone"),
                what=ctx.get("text", ""),
                safe="Training keeps running. A preview shows how it moves now.",
                actions=[("Render preview", "preview"), ("Keep training", "dismiss")],
            )
            col = T["good"]
        elif cid == "looks_trained":
            c = dict(
                title=SM.LOOKS_TRAINED["title"],
                what=SM.LOOKS_TRAINED["what"].format(a=ctx.get("a", "?")),
                safe=SM.LOOKS_TRAINED["safe"],
                actions=SM.LOOKS_TRAINED["actions"],
            )
            col = T["good"]
        else:
            c = SM.card(cid, **ctx)
            c["actions"] = [(c["fix_label"], c["fix"]), ("Dismiss", "dismiss")]
            col = T["err"] if cid != "no_model" else T["warn"]
        if not self.cards_f.winfo_manager():
            self.cards_f.pack(fill="x", pady=(4, 0), before=self._cards_anchor)
        outer = tk.Frame(self.cards_f, bg=col)
        outer.pack(fill="x", pady=(0, 4))
        inner = tk.Frame(outer, bg=T["panel"], padx=8, pady=5)
        inner.pack(fill="x", padx=(4, 0))
        inner.columnconfigure(0, weight=1)
        tk.Label(
            inner, text=c["title"], bg=T["panel"], fg=col, anchor="w", font=("Segoe UI", 10, "bold")
        ).grid(row=0, column=0, sticky="we")
        labs = []
        for r, (key, fg) in enumerate((("what", T["fg"]), ("safe", T["dim"]), ("detail", T["dim"]))):
            if not c.get(key):
                continue
            l = tk.Label(
                inner, text=c[key], bg=T["panel"], fg=fg, anchor="w", justify="left", wraplength=380
            )
            l.grid(row=1 + r, column=0, sticky="we")
            labs.append(l)
        bf = tk.Frame(inner, bg=T["panel"])
        bf.grid(row=0, column=1, rowspan=4, sticky="ne", padx=(8, 0))
        for lab, act in c["actions"]:
            ttk.Button(bf, text=lab, command=lambda a=act: self._card_action(cid, a, ctx)).pack(
                fill="x", pady=1
            )

        def wrap(e, labs=labs, bf=bf):
            for x in labs:
                x.configure(wraplength=max(200, e.width - bf.winfo_width() - 30))

        inner.bind("<Configure>", wrap)
        self.cards[cid] = (outer, ctx)
        if hasattr(self, "_tabs_paint"):
            self._tabs_paint()  # a dot on the Train tab while a card waits there
        self.card_texts = getattr(self, "card_texts", {})
        self.card_texts[cid] = c  # for tests / the doc generator

    def _close_card(self, cid, remember=True):
        fr = self.cards.pop(cid, (None, None))[0]
        if fr is not None:
            fr.destroy()
        if not self.cards:
            self.cards_f.pack_forget()  # an empty frame would keep its old height
        if hasattr(self, "_tabs_paint"):
            self._tabs_paint()

    def _card_action(self, cid, act, ctx):
        """One fix per card. Every action is logged in the console."""
        if act == "dismiss":
            return self._close_card(cid)
        if act == "preview_gpu":
            self.v_pdev.set("GPU")
            self.s["preview_device"] = "GPU"
            self._save_settings_only()
            self._append("[gui] previews now render on the GPU (Preview device: GPU)\n")
        elif act == "halve_envs":  # one click: lower num_envs and resume (running: after the next save)
            self.v_envs.set(int(ctx.get("n", 512)))
            if self._training_running():
                self.change_envs_live()
            else:
                self._append("[gui] num_envs set to %s - resuming\n" % ctx.get("n"))
                self.resume()
        elif act == "pick_model":
            self._browse_model()
            if not self.v_model.get().strip():
                return
        elif act == "open_file":
            p = ctx.get("file") or ""
            p = p if os.path.isabs(p) else os.path.join(self.mk(), p)
            if not open_path(p):
                messagebox.showerror("Could not open the file", p)
                return
        elif act == "choose_mk":
            self._browse(self.v_mk)
            if not os.path.exists(os.path.join(self.mk(), "mimickit", "run.py")):
                return
            self._save()
            self.rescan()
        elif act == "preview":
            self.preview()
        elif act == "stop":
            self.stop()
        self._close_card(cid)

    # ------------------------------------------------------------------ looks trained
    LOOKS_MIN_S = 2 * 3600  # a0.8.3: no 'looks trained' for a plateau before 2 h of total training (it fired at 30 min)
    LOOKS_FLAT_S = 45 * 60  # ... and the plateau must hold this long (training time) before it is shown

    def _check_looks_trained(self, d, e, running, tot=None):
        hit = (
            e
            and e.get("pct") is not None
            and (
                (e.get("kind") == "plateau" and e["pct"] >= 95)
                or (e.get("kind") == "target" and e["pct"] >= 100)
            )
        )
        key = self._chain_key(d)
        if hit and e.get("kind") == "plateau" and tot is not None:
            flat = getattr(self, "_looks_flat", None)
            if not flat or flat[0] != key or tot < flat[1]:
                self._looks_flat = flat = (key, tot)
            hit = tot >= self.LOOKS_MIN_S and tot - flat[1] >= self.LOOKS_FLAT_S
        elif not hit:
            self._looks_flat = None
        self._looks_now = bool(hit and running and self.run_kind == "train")
        if not hit or not running or self.run_kind != "train" or self._looks == key:
            return
        self._looks = key  # once per run chain
        if self.s.get("looks_trained_seen") == key:  # also across launcher restarts
            return
        self.s["looks_trained_seen"] = key
        self._save_settings_only()
        a = e.get("a")
        a_txt = "%.2f" % a if isinstance(a, (int, float)) else "its current level"
        self._show_card("looks_trained", a=a_txt)
        self._append("[gui] looks trained (score levelled off near %s)\n" % a_txt)
        if getattr(self, "snap", None) is not None:
            self.snap["looks_trained"] = True
        n = self.s.get("notify", {})
        if n.get("send_trained") and self.notifier.targets():
            tot = self._tt_total()[0]
            msg = SM.LOOKS_TRAINED["ping"].format(
                name=os.path.basename(d.rstrip("/\\")), a=a_txt, time=hms(tot)
            )
            threading.Thread(
                target=self.notifier.send, args=(msg,), kwargs=dict(kind="trained"), daemon=True
            ).start()


    # ------------------------------------------------------------------ milestones (a0.9.0)
    def _milestone_history(self, d, log):
        """The rows to judge: the live/console rows; log.txt when they lack Test_Episode_Length (stock MimicKit only
        writes it to log.txt). Cached by log.txt mtime."""
        from mkl import milestones as MS

        if any(MS._num(v) for v in (log.get("Test_Episode_Length") or [])):
            return log
        f = os.path.join(d, "log.txt")
        try:
            mt = os.path.getmtime(f)
        except OSError:
            return log
        c = getattr(self, "_ms_logcache", None)
        if not c or c[0] != f or c[1] != mt:
            try:
                h = parse_log(f)
            except Exception as e:
                log_exc("milestones: log.txt", e)
                h = {}
            self._ms_logcache = c = (f, mt, h)
        return c[2] if c[2].get("Test_Return") else log

    def _check_milestones(self, d, log, running):
        """'First steps!' / 'Walking well': once per run chain (flag in each output folder's milestones.json)."""
        from mkl import milestones as MS

        if not running or self.run_kind != "train" or not d or not os.path.isdir(d):
            return []
        try:
            chain = run_chain(d)
        except Exception as e:  # a0.9.1 (M2): unknown chain -> milestones.check() falls back safely
            log_exc("milestones: run chain", e)
            chain = None
        new = MS.check(d, chain, self._milestone_history(d, log), MS.cfg(self.s))
        for info in new:
            self._milestone = dict(info, run=os.path.basename(d.rstrip("/\\")), at=time.time())
            self._show_card("milestone", **info)
            self._append("[gui] milestone: %s %s\n" % (info["title"], info["text"]))
            if self.notifier.targets():
                msg = "%s %s - %s" % (info["title"], os.path.basename(d.rstrip("/\\")), info["text"])
                threading.Thread(target=self.notifier.send, args=(msg,), kwargs=dict(kind="milestone"),
                                 daemon=True).start()
        return new


def open_path(p):
    """Open a file with the system's default app. Returns False if it does not exist / cannot be opened."""
    if not os.path.exists(p):
        return False
    try:
        if IS_WIN:
            os.startfile(p)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as e:
        log_exc("status: open_path", e)
        return False


__all__ = ["StatusMixin", "open_path", "BANNER_COL"]
