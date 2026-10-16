# MimicKit Launcher - status panel, health banner, error cards, "looks trained" prompt.
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
"""GUI for mkl.status_model: everything here is driven by MimicKit's console output (no extra processes)."""

from mkl.core import *
from mkl import status_model as SM

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
        f = tk.Frame(self.root, padx=6, pady=3)
        f.pack(fill="x", padx=6, pady=(4, 2))
        self.ban_f = f
        self.ban_ver = tk.Label(f, text="version " + VERSION)
        self.ban_ver.pack(side="right")
        self.ban_dot = tk.Label(f, text="\u25cf", font=("Segoe UI", 11))
        self.ban_dot.pack(side="left")
        self.ban_detail = tk.Label(f, text="", anchor="e")  # grey technical detail (exit code)
        self.ban_detail.pack(side="right", padx=(8, 8))
        self.ban_lab = tk.Label(f, text=SM.BANNER["idle"][1], anchor="w", justify="left")
        self.ban_lab.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.ban_level = "idle"
        f.bind("<Configure>", self._wrap_banner)

    def _wrap_banner(self, _=None):
        """The banner text wraps onto a second line instead of being cut off on a narrow window."""
        room = (
            self.ban_f.winfo_width()
            - self.ban_ver.winfo_reqwidth()
            - self.ban_dot.winfo_reqwidth()
            - self.ban_detail.winfo_reqwidth()
            - 40
        )
        if int(self.ban_lab.cget("wraplength")) != max(200, room):
            self.ban_lab.configure(wraplength=max(200, room))

    def _build_cards(self, left):
        self.cards_f = ttk.Frame(left)  # packed above the output panel by _build_output

    def _build_output(self, left):
        """Output panel: Status (graphical, from the console) / Console (raw) toggle."""
        logf = ttk.LabelFrame(left, text="Output", padding=4)
        logf.pack(fill="both", expand=True)
        self._cards_anchor = logf  # cards_f is packed just above it while a card is shown
        hdr = ttk.Frame(logf)
        hdr.pack(fill="x", pady=(0, 4))
        self.v_outview = tk.StringVar(value=self.s.get("output_view", "status"))
        for lab, val in (("Status", "status"), ("Console", "console")):
            ttk.Radiobutton(
                hdr,
                text=lab,
                value=val,
                variable=self.v_outview,
                style="Toolbutton",
                command=self._outview_changed,
            ).pack(side="left", padx=(0, 2))
        self.l_outhint = ttk.Label(hdr, text="", style="Dim.TLabel")
        self.l_outhint.pack(side="left", padx=8)
        body = ttk.Frame(logf)
        body.pack(fill="both", expand=True)
        self.st_panel = ttk.Frame(body)
        self.con_panel = ttk.Frame(body)
        self._build_console(self.con_panel)
        self._build_status_panel(self.st_panel)
        self._outview_changed(save=False)

    def _build_console(self, parent):
        self._build_command_box(parent)
        self.t_log = tk.Text(parent, wrap="none", width=70, font=MONO)
        ys = ttk.Scrollbar(parent, command=self.t_log.yview)
        self.t_log.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.t_log.pack(fill="both", expand=True)

    def _build_status_panel(self, p):
        p.columnconfigure(0, weight=1)
        top = ttk.Frame(p)
        top.grid(row=0, column=0, sticky="we")
        self.st_stage = ttk.Label(top, text="Idle", style="Big.TLabel")
        self.st_stage.pack(side="left")
        self.st_iter = ttk.Label(top, text="", style="Big.TLabel")
        self.st_iter.pack(side="left", padx=(10, 0))
        self.st_save_l = ttk.Label(top, text="", style="Dim.TLabel")
        self.st_save_l.pack(side="right")
        self.st_save = ttk.Progressbar(top, mode="determinate", maximum=1, length=110)
        self.st_save.pack(side="right", padx=6)
        ttk.Label(top, text="Next save").pack(side="right")
        tf = ttk.Frame(p)
        tf.grid(row=2, column=0, sticky="we", pady=(6, 0))
        self.tiles = {}
        for i, (k, title) in enumerate(
            (("score", "Score"), ("rate", "Speed"), ("ep", "Episode length"))
        ):
            tf.columnconfigure(i, weight=1, uniform="tile")
            t = tk.Frame(tf, padx=8, pady=3)
            t.grid(row=0, column=i, sticky="nswe", padx=(0 if i == 0 else 6, 0))
            t.columnconfigure(1, weight=1)
            a = tk.Label(t, text=title, anchor="w")
            b = tk.Label(t, text="-", anchor="e", font=("Segoe UI", 12, "bold"))
            c = tk.Label(t, text="", anchor="w")
            a.grid(row=0, column=0, sticky="w")
            b.grid(row=0, column=1, sticky="e")
            c.grid(row=1, column=0, columnspan=2, sticky="w")
            self.tiles[k] = (t, a, b, c)
        ck = ttk.Frame(p)
        ck.grid(row=3, column=0, sticky="we", pady=(4, 0))
        self.st_ckpt = ttk.Label(ck, text="Last checkpoint: none yet")
        self.st_ckpt.pack(side="left")
        ttk.Button(ck, text="Open console", command=lambda: self._set_outview("console")).pack(
            side="right"
        )
        bx = ttk.Frame(p)
        bx.grid(row=4, column=0, sticky="nswe", pady=(4, 0))
        p.rowconfigure(4, weight=1)
        for c, (attr, title) in enumerate(
            (("st_events", "What's happening"), ("st_warn", "Warnings and errors"))
        ):
            bx.columnconfigure(c, weight=1, uniform="box")
            bx.rowconfigure(1, weight=1)
            lab = ttk.Label(bx, text=title, style="Dim.TLabel")
            lab.grid(row=0, column=c, sticky="w", padx=(0 if c == 0 else 6, 0))
            t = tk.Text(bx, height=2, wrap="word", width=30, relief="flat")
            t.grid(row=1, column=c, sticky="nswe", padx=(0 if c == 0 else 6, 0))
            setattr(self, attr, t)
            if c == 1:
                self.st_wl = lab
        for w in (self.st_events, self.st_warn):
            w.configure(state="disabled")
        self._status_sig = None

    def _set_outview(self, v):
        self.v_outview.set(v)
        self._outview_changed()

    def _outview_changed(self, save=True):
        v = self.v_outview.get()
        show, hide = (
            (self.st_panel, self.con_panel) if v == "status" else (self.con_panel, self.st_panel)
        )
        hide.pack_forget()
        show.pack(fill="both", expand=True)
        self.l_outhint.configure(
            text="from MimicKit's console output" if v == "status" else "raw MimicKit output"
        )
        if v == "console":
            self.t_log.see("end")
        if save:
            self.s["output_view"] = v
            self._save_settings_only()
        self._status_refresh(force=True)

    def _status_theme(self):
        if not hasattr(self, "ban_f"):
            return
        for w in (self.st_events, self.st_warn):
            w.configure(
                bg=T["log_bg"],
                fg=T["log_fg"],
                insertbackground=T["fg"],
                highlightthickness=0,
                padx=6,
                pady=4,
            )
        self.st_warn.tag_configure("warn", foreground=T["warn"])
        self.st_warn.tag_configure("err", foreground=T["err"])
        self.st_warn.tag_configure("dim", foreground=T["dim"])
        self.st_events.tag_configure("dim", foreground=T["dim"])
        for t, a, b, c in self.tiles.values():
            for w in (t, a, b, c):
                w.configure(bg=T["panel"])
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
            self.ban_lab.configure(text=text)
        self.ban_level = level
        col = T.get(BANNER_COL.get(level, "dim"), T["fg"])
        bg = T["panel"]
        self.ban_f.configure(bg=bg)
        self.ban_ver.configure(bg=bg, fg=T["dim"])
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
        if not force and self.v_outview.get() != "status":
            return
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
            self._fill(
                self.st_events,
                [
                    (time.strftime("%H:%M", time.localtime(t)) + "  ", "dim", x, "")
                    for t, x in m.events[-8:]
                ]
                or [("", "", "Nothing yet.", "dim")],
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
                    "Errors (%d) and warnings (%d)" % (ne, nw)
                    if ne or nw
                    else "Warnings and errors"
                )
            )

    def _tile(self, k, value, sub):
        t, a, b, c = self.tiles[k]
        b.configure(text=value)
        c.configure(text=sub)

    def _fill(self, w, rows):
        w.configure(state="normal")
        w.delete("1.0", "end")
        for pre, ptag, text, tag in rows:
            w.insert("end", pre, ptag)
            w.insert("end", text + "\n", tag)
        w.configure(state="disabled")
        w.see("end")

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
        if cid == "looks_trained":
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
        self.card_texts = getattr(self, "card_texts", {})
        self.card_texts[cid] = c  # for tests / the doc generator

    def _close_card(self, cid, remember=True):
        fr = self.cards.pop(cid, (None, None))[0]
        if fr is not None:
            fr.destroy()
        if not self.cards:
            self.cards_f.pack_forget()  # an empty frame would keep its old height

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
    def _check_looks_trained(self, d, e, running):
        hit = (
            e
            and e.get("pct") is not None
            and (
                (e.get("kind") == "plateau" and e["pct"] >= 95)
                or (e.get("kind") == "target" and e["pct"] >= 100)
            )
        )
        key = self._chain_key(d)
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
