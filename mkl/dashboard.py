# MimicKit Launcher - phone dashboard and notifications.
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
from mkl.core import *  # noqa: F401,F403 - shared helpers/constants
from mkl.core import __all__ as _core_names  # noqa: F401


class DashboardMixin:
    """Phone dashboard and notifications."""

    def _publish(self, lines, d, running):
        def series(ax):
            out = []
            for ln in ax.get_lines():
                if ln.get_gid() == "hover":
                    continue
                xs, ys = self._full(
                    ln
                )  # full data, min/max-reduced to ~1500 columns (the phone culls/decimates again per view)
                if xs:
                    xs, ys = R.minmax_decimate(xs, ys, xs[0], xs[-1], 1500)
                out.append(
                    dict(
                        role=ln.get_gid() or "",
                        label=(ln.get_label() if not str(ln.get_label()).startswith("_") else None),
                        x=xs,
                        y=[None if v is None or v != v else v for v in ys],
                    )
                )
            return out

        txt = "\n".join(lines)

        def grab(pat):
            m = re.search(pat, txt)
            return m.group(1).strip() if m else ""

        snap = dict(
            title="MimicKit Launcher %s - %s" % (VERSION, os.path.basename(d.rstrip("/\\"))),
            run_name=os.path.basename(d.rstrip("/\\")),
            state=lines[0] if lines else "",
            running=running,
            session_time=grab(r"Running for (\S+) \(this session") or grab(r"session time (\S+)"),
            total_time=grab(r"Running for (.+?) \(total") or grab(r"Total training time (.+?) \(this run"),
            samples=grab(r"samples ([\d,]+(?: \([\d,]+ in all sessions\))?)"),
            rate=grab(r"speed ([\d.]+ M samples/hour)"),
            estimate=next((l for l in lines if l.startswith(("Plateau estimate", "Target"))), ""),
            charts=dict(
                **{"return": series(self.ax1), "rate": series(self.ax2)},
                **({"per_step": series(self.ax3)} if self.ax3 is not None else {}),
            ),
            per_step=grab(r"Avg reward per step: ([^\n]+)"),
            updated=time.time(),
            render_msg=self.render_msg,
            pending=self._pending_text(),
            stop_save=bool(getattr(self, "stop_save", None)),
            tweaks=dict(self._remote_cfg().get("tweaks") or {}),
        )
        v = getattr(self, "vram", None)
        if v:
            snap["vram"] = "%.1f / %.1f GB" % (v[0] / 1024, v[1] / 1024)
            snap["vram_pct"] = round(100 * v[0] / v[1])
        snap["stop_save_msg"] = getattr(self, "stopsave_msg", "")
        snap["ghost"] = dict(mode=self.v_ghost.get(), modes=list(GHOST_MODES))  # a0.9.1: phone ghost selector
        snap["layouts"] = [[v, k] for k, v in CLIP_LAYOUTS.items()]
        ms = getattr(self, "_milestone", None)  # a0.9.0: phone banner
        if ms and ms.get("run") == os.path.basename(d.rstrip("/\\")):
            snap["milestone"] = dict(title=ms["title"], text=ms["text"], at=ms["at"], key=ms["key"])
        snap["render"] = dict(getattr(self, "render_prog", None) or {})
        prev = self._preview_list(d)
        if prev:
            p = prev[0]["path"]
            snap["preview"] = dict(path=p, name=os.path.basename(p), key=prev[0]["key"])
            snap["previews"] = prev
        try:
            it = self._item("train")
            names = self._clips_of(it) if it else []
            if len(names) > 1:
                snap["clips"] = dict(all=names, chosen=self._chosen_clips(it))
        except Exception as e:
            log_exc("phone clip list", e)
        try:
            self._runs_snapshot(snap)
        except Exception as e:
            log_exc("phone runs list", e)
        self._plugin_call("snapshot", snap)
        self.snap = snap
        if self.dash:
            self.dash.set_snapshot(snap)
        if self.notifier.due():
            threading.Thread(
                target=self.notifier.send_status, args=(dict(snap),), daemon=True
            ).start()

    PREVIEW_LIST_MAX = 12

    def _preview_list(self, d):
        """Newest preview MP4s (this run + every run folder), newest first. Paths stay on the PC: the phone only
        gets name/key and asks for a key, never a path."""
        mp4s = set(glob.glob(os.path.join(d, "preview_*.mp4")))
        mp4s |= set(glob.glob(os.path.join(self.mk(), "output", "*", "preview_*.mp4")))
        out = []
        for p in mp4s:
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append((st.st_mtime, st.st_size, p))
        out.sort(reverse=True)
        return [
            dict(
                path=p,
                name=os.path.basename(p),
                run=os.path.basename(os.path.dirname(p)),
                key="%s-%d" % (os.path.basename(p), int(t)),
                when=time.strftime("%b %d %H:%M", time.localtime(t)),
                mb=round(sz / 1e6, 1),
            )
            for t, sz, p in out[: self.PREVIEW_LIST_MAX]
        ]

    # preview render progress for the phone (set from the preview reader thread: plain dict swaps, no Tk)
    PREVIEW_STAGES = (
        ("free RAM", 10, "Checking memory"),
        ("PREVIEW VARIANT", 20, "Recording the motion"),
        ("loaded", 30, "Recording the motion"),
        ("setup ", 40, "Recording the motion"),
        ("recorded with variant", 60, "Rendering frames"),
        ("rendered ", 90, "Writing the MP4"),
        ("PREVIEW_DONE", 100, "Done"),
    )

    def _preview_progress(self, line, origin=None):
        rp = dict(getattr(self, "render_prog", None) or {})
        if origin is not None:  # start
            self.render_prog = dict(active=True, pct=5, stage="Starting", started=time.time(), origin=origin)
            return
        if not rp.get("active"):
            return
        for key, pct, stage in self.PREVIEW_STAGES:
            if key in line and pct >= rp.get("pct", 0):
                rp.update(pct=pct, stage=stage)
        m = re.search(r"(record|render) frame (\d+)/(\d+)", line)  # a0.9.1: finer progress (long clips)
        if m and int(m.group(3)) > 0:
            lo, hi = (40, 60) if m.group(1) == "record" else (60, 90)
            pct = lo + (hi - lo) * min(1.0, int(m.group(2)) / int(m.group(3)))
            if pct >= rp.get("pct", 0):
                rp.update(pct=int(pct), stage="%s frame %s of %s" % (
                    "Recording" if m.group(1) == "record" else "Rendering", m.group(2), m.group(3)))
        rp["elapsed"] = int(time.time() - rp.get("started", time.time()))
        self.render_prog = rp

    def _render_prog_done(self, rc):
        rp = dict(getattr(self, "render_prog", None) or {})
        rp.update(active=False, pct=100 if rc == 0 else rp.get("pct", 0),
                  stage="Done" if rc == 0 else "Failed (exit code %s) - see the PC log" % rc,
                  elapsed=int(time.time() - rp.get("started", time.time())))
        self.render_prog = rp

    def _remote_cfg(self):
        return self.s.setdefault("remote", {})

    def _remote_apply(self):
        """Start/stop the dashboard from the settings. Port in use etc. is logged, never fatal."""
        c = self._remote_cfg()
        want = bool(c.get("enabled"))
        host = c.get("host", "127.0.0.1")
        port = int(c.get("port", 8765))
        if self.dash and (
            not want
            or (self.dash.host, self.dash.port) != (host, port)
            or self.dash.token != c.get("token")
        ):
            self.dash.stop()
            self.dash = None
            self._append("[remote] dashboard stopped\n")
        if want and not self.dash:
            if not c.get("token"):
                c["token"] = R.new_token()
                self._save_settings_only()
            try:
                self.dash = R.Dashboard(
                    c["token"],
                    host,
                    port,
                    on_render=self._remote_render,
                    control=self._control(),
                    page_extra=self.plugin_page,
                    log=lambda m: self.q.put("[remote] %s\n" % m),
                ).start()
                self.dash.set_snapshot(self.snap)
                for u in R.dashboard_urls(host, self.dash.port, c["token"])[:3]:
                    self._append("[remote] %s\n" % u)
            except OSError as e:
                self.dash = None
                self._append(
                    "[remote] could not start the dashboard on %s:%d (%s)\n" % (host, port, e)
                )

    # ---------------------------------------------------------- phone control (a0.7.0)
    def _control(self):
        if not getattr(self, "ctl", None):
            self.ctl = R.Control(
                self._remote_cfg,
                self._remote_action,
                log=lambda m: self.q.put("[remote] %s\n" % m),
                extra_actions=self.plugin_actions,
                turn_off=self._control_lockdown,
            )
            self._import_phone_sessions()
        return self.ctl

    def _control_lockdown(self, why):
        """Server thread: too many wrong PINs from all phones - switch phone control off (saved), shown on the PC."""
        c = self._remote_cfg()
        c["allow_control"] = False
        c["lockdown"] = True
        self.q.put("[remote] phone control turned OFF (%s). Turn it back on in Settings - Phone.\n" % why)
        self.rq.put(self._save)  # server thread: no Tk calls here

    def _handoff_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(CONFIG)), "phone_sessions_handoff.json")

    def export_phone_sessions(self):
        """Before a window reload (e.g. after an update): hand the signed-in phones to the next window (hashed
        session tokens only, valid for 2 minutes)."""
        if not getattr(self, "ctl", None):
            return
        U.save_json(self._handoff_path(), dict(t=time.time(), sessions=self.ctl.export_sessions()), backup=False)

    def _import_phone_sessions(self):
        p = self._handoff_path()
        try:
            d = U.load_json(p)
        except Exception:
            return
        try:
            os.remove(p)
        except OSError:
            pass
        if time.time() - float(d.get("t", 0)) < 120:
            self.ctl.import_sessions(d.get("sessions") or {})

    def _pending_text(self):
        """Pending / in-progress action for the status line (desktop + phone)."""
        ph = getattr(self, "remote_phase", "")
        if ph:
            return ph
        if getattr(self, "stopsave_phase", "") == "stopping":
            return "Saved - stopping training..."
        if getattr(self, "stop_save", None):
            return "Will stop after the next save"
        return ""

    def _save_in_progress(self):
        """model.pt written in the last 3 s or still growing = a save is under way."""
        m = os.path.join(self.run_dir or "", "model.pt")
        try:
            st = os.stat(m)
        except OSError:
            return False
        last = getattr(self, "_mp_size", None)
        self._mp_size = st.st_size
        return time.time() - st.st_mtime < 3 or (last is not None and last != st.st_size)

    def _remote_action(self, action, params):
        """Server thread: decide with thread-safe reads, queue GUI work. Idempotent: a repeat is a no-op."""
        running = self._training_running()
        if action in ("start_train", "continue_run", "patch"):
            return self._remote_runs_action(action, params)
        if action == "ghost":  # a0.9.1: preview ghost type from the phone (PIN session + nonce like every control)
            mode = (params or {}).get("mode")
            if mode not in GHOST_MODES:
                return 400, "Unknown ghost type."

            def apply_ghost():
                self.v_ghost.set(mode)
                self.s["preview_ghost"] = mode
                self._save_settings_only()
                self._append("[remote] preview ghost set to %s (from phone)\n" % mode)

            self.rq.put(apply_ghost)
            return 200, "Preview ghost: %s (used by the next preview)." % mode
        if action == "resume":
            if running or (self.proc and self.proc.poll() is None):
                return 409, "Training is already running - resume refused."
            self.rq.put(self._remote_resume_gui)
            return 202, "Resuming training on the PC."
        if action in ("stop_now", "stop_after_save", "cancel_stop") and not running:
            if getattr(self, "remote_phase", ""):
                return 200, "Already stopping."
            return 409, "No training is running."
        if action == "stop_now":
            with self._remote_lock:  # check-then-set as one step (two phones tapping at once)
                if getattr(self, "remote_phase", ""):
                    return 200, "Already stopping (counted once)."
                self.remote_phase = "Stopping\u2026"
            self.rq.put(self._remote_stop_gui)
            return 202, "Stopping training."
        if action in ("stop_after_save", "cancel_stop"):
            want = action == "stop_after_save"
            with self._remote_lock:  # the wanted state (pending phone request, else the armed state) decides
                pending = getattr(self, "_ss_want", None)
                cur = pending if pending is not None else bool(getattr(self, "stop_save", None))
                if cur == want:
                    return 200, ("Already set: will stop after next save." if want else "Nothing to cancel.")
                self._ss_want = want
                gen = self._ss_gen = getattr(self, "_ss_gen", 0) + 1
            self.rq.put(lambda: self._ss_apply(gen, want))
            if want:
                return 202, "Will stop after the next save (if the PC refuses, the reason shows on the status line)."
            return 202, "Stop after next save cancelled."
        if action == "tweaks":  # settings belong to the GUI thread: queue the change, don't touch self.s here
            p = dict(params)

            def apply_tweaks():
                c = self._remote_cfg()
                c["tweaks"] = dict(c.get("tweaks") or {}, **p)
                self._save_settings_only()
                self._append("[remote] queued for the next resume: %s\n" % p)

            self.rq.put(apply_tweaks)
            return 200, "Queued for the next resume: %s" % ", ".join("%s = %s" % kv for kv in params.items())
        return 400, "Unknown action."

    SAVE_WAIT_MAX_S = 60  # a stop from the phone waits for a running save at most this long

    def _ss_apply(self, gen, want):
        """GUI thread: phone arm (want=True) / cancel (want=False) of stop-after-save. Only the NEWEST phone request
        (generation counter, decided under the lock) acts, so arm / cancel / arm always ends armed and
        arm / cancel always ends cancelled, whatever order the queued callbacks run in."""
        with self._remote_lock:
            if gen != getattr(self, "_ss_gen", 0):
                return  # superseded by a later phone request
            self._ss_want = None
        if bool(self.stop_save) != want:
            self.stop_after_save("phone")

    def _remote_stop_gui(self, t0=None):
        if not self._training_running():
            self.remote_phase = ""
            return
        t0 = t0 or time.time()
        if self._save_in_progress():
            if time.time() - t0 < self.SAVE_WAIT_MAX_S:
                self.remote_phase = "Waiting for the save to finish..."
                self.root.after(1000, self._remote_stop_gui, t0)
                return
            self._append("[remote] save still looked busy after %d s - stopping anyway (the previous model.pt "
                         "or its .bak is kept)\n" % self.SAVE_WAIT_MAX_S)
        self.remote_phase = "Stopping\u2026"
        self._append("[remote] stop now (from phone)\n")
        if getattr(self, "stop_save", None):
            self._stopsave_done("[gui] stop after next save replaced by stop now\n")
        self.stop()
        self.remote_phase = ""

    def _remote_resume_gui(self):
        if self._training_running():
            self._append("[remote] resume refused: training is already running\n")
            return
        tw = self._remote_cfg().pop("tweaks", None) or {}
        if "num_envs" in tw:
            self.v_envs.set(int(tw["num_envs"]))
            self._append("[remote] next-resume tweak applied: num_envs = %d\n" % tw["num_envs"])
        self._save_settings_only()
        self._append("[remote] resume (from phone)\n")
        self.resume()

    def _remote_render(self, clips=None, layout=None):
        """Called from the web server thread: never touches Tk, only queues work for the GUI thread.
        layout (a0.9.1): optional 'grid' / 'seq' / 'long' for this render only; 'long' ignores the clip choice."""
        if self.preview_proc and self.preview_proc.poll() is None:
            return False, "A preview is already being rendered."
        if layout is not None and layout not in CLIP_LAYOUTS.values():
            return False, "Unknown clip layout."
        if layout == "long":
            clips = None
        if clips is not None:
            known = ((getattr(self, "snap", None) or {}).get("clips") or {}).get("all") or []
            if (not isinstance(clips, list) or not clips or len(clips) > 4
                    or any(not isinstance(c, str) or c not in known for c in clips)):
                self.q.put("[remote] refused preview: clip choice %r is not 1-4 clips of this config\n" % (clips,))
                return False, "Pick 1 to 4 clips from the list."
        self.rq.put(lambda: self._remote_render_gui(clips, layout))
        self.render_msg = "Preview requested from the phone - rendering in the background."
        return (
            True,
            "Preview started - it appears here when it is done (usually under a minute or two).",
        )

    def _remote_render_gui(self, clips=None, layout=None):
        it = self._item("train")
        model = self.v_model.get().strip() or self._latest_model()
        if not it or not model:
            self.render_msg = "No saved progress yet - nothing to preview."
            self._append("[remote] %s\n" % self.render_msg)
            return
        self._append("[remote] preview requested from the dashboard (renders in the background; it is not "
                     "opened on this PC)\n")
        self._start_preview(it, model, origin="phone", clips=clips, layout=layout)

    def _preview_finished(self):
        self.render_msg = "Preview finished."
        self._render_prog_done(0)
        c = self.s.get("notify", {})
        if c.get("send_preview") and self.notifier.targets():
            mp4s = glob.glob(os.path.join(self.mk(), "output", "*", "preview_*.mp4")) + glob.glob(
                os.path.join(self.mk(), "output", "*", "*", "preview_*.mp4")
            )
            if mp4s:
                p = max(mp4s, key=os.path.getmtime)
                threading.Thread(
                    target=self.notifier.send,
                    args=("New preview: %s" % os.path.basename(p),),
                    kwargs=dict(video_path=p, kind="preview"),
                    daemon=True,
                ).start()

    def remote_dialog(self):
        if getattr(self, "_rdlg", None) and self._rdlg.winfo_exists():
            self._rdlg.lift()
            return
        c = self._remote_cfg()
        n = self.s.setdefault("notify", {})
        top = new_popup(self.root, "Phone dashboard + notifications", T)
        self._rdlg = top
        f = ttk.Frame(top, padding=10)
        f.pack(fill="both", expand=True)
        v_en = tk.BooleanVar(value=bool(c.get("enabled")))
        v_port = tk.StringVar(value=str(c.get("port", 8765)))
        v_host = tk.StringVar(
            value=BIND_LABEL.get(c.get("host", "127.0.0.1"), BIND_LABEL["127.0.0.1"])  # unknown saved host: safest choice
        )
        ttk.Label(f, text="Phone dashboard", style="TLabelframe.Label").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Checkbutton(f, text="Enable (web page; read-only unless control is allowed below; off by default)", variable=v_en).grid(
            row=1, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(f, text="Port").grid(row=2, column=0, sticky="w")
        ttk.Entry(f, textvariable=v_port, width=8).grid(row=2, column=1, sticky="w")
        ttk.Label(f, text="Who can open it").grid(row=3, column=0, sticky="w")
        ttk.Combobox(
            f, textvariable=v_host, values=list(BIND_LABEL.values()), state="readonly", width=46
        ).grid(row=3, column=1, columnspan=2, sticky="w")
        host_of = lambda: {v: k for k, v in BIND_LABEL.items()}.get(v_host.get(), "127.0.0.1")
        warn = ttk.Label(f, style="Dim.TLabel", wraplength=520, justify="left")
        warn.grid(row=4, column=0, columnspan=3, sticky="w")

        def upd_warn(*_):
            warn.configure(
                text=(
                    "Reachable from your other devices (Tailscale, home Wi-Fi). Anyone with the link incl. token can "
                    "watch. Never forward this port on your router - use Tailscale (docs/REMOTE_ACCESS.md)."
                    if host_of() == "0.0.0.0"
                    else "Only this PC can open the page (http://127.0.0.1). Pick the other option to use your phone."
                )
            )

        v_host.trace_add("write", upd_warn)
        upd_warn()
        cf = ttk.Frame(f)
        cf.grid(row=16, column=0, columnspan=4, sticky="w", pady=(8, 0))
        v_ctl = tk.BooleanVar(value=bool(c.get("allow_control")))
        ttk.Checkbutton(
            cf, text="Allow phone control (needs a PIN)", variable=v_ctl
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(cf, text="PIN: 6–12 digits").grid(row=1, column=0, sticky="w")
        v_pin = tk.StringVar()
        ttk.Entry(cf, textvariable=v_pin, width=14, show="*").grid(row=1, column=1, sticky="w")
        ctl_msg = ttk.Label(cf, style="Dim.TLabel", wraplength=520, justify="left")
        ctl_msg.grid(row=2, column=0, columnspan=3, sticky="w")
        ctl_msg.configure(
            text=(R.LOCKDOWN_MSG if c.get("lockdown") else
                  "PIN is set." if c.get("pin_hash") and int(c.get("pin_len") or 0) >= R.MIN_PIN_LAN else
                  R.PIN_RULES_MSG if c.get("pin_hash") else
                  "No PIN set yet - control stays off until you set one.")
        )

        def collect_ctl():
            pin = v_pin.get().strip()
            revoke = None
            if pin:
                if not (pin.isdigit() and R.MIN_PIN_LAN <= len(pin) <= 12):
                    ctl_msg.configure(text="PIN must be 6-12 digits - not changed.")
                    self._append("[remote] PIN not changed: must be 6-12 digits\n")
                else:
                    c["pin_hash"] = R.hash_pin(pin)
                    c["pin_len"] = len(pin)
                    v_pin.set("")
                    revoke = "PIN changed"
                    ctl_msg.configure(text="PIN changed - every phone must sign in again.")
            want = bool(v_ctl.get())
            if want:
                c.pop("lockdown", None)
            if bool(c.get("allow_control")) and not want:
                revoke = "control turned off"
            c["allow_control"] = want
            if revoke:
                self._control().revoke_all(revoke)

        self._rdlg_ctl = dict(allow=v_ctl, pin=v_pin, collect=collect_ctl, msg=ctl_msg)
        urlf = ttk.Frame(f)
        urlf.grid(row=5, column=0, columnspan=3, sticky="we", pady=4)
        qr = tk.Canvas(f, width=180, height=180, bg="white", highlightthickness=0)
        qr.grid(row=1, column=3, rowspan=6, padx=10)
        qr_lab = ttk.Label(f, style="Dim.TLabel")
        qr_lab.grid(row=7, column=3)

        def copy(u):
            self.root.clipboard_clear()
            self.root.clipboard_append(u)
            self._append("[remote] link copied\n")

        def show_urls():
            try:
                port = int(v_port.get() or 8765)
            except ValueError:
                port = 8765
            items = R.dashboard_urls(
                host_of(), port, c.get("token") or "(enable to create a token)", labelled=True
            )
            for w in urlf.winfo_children():
                w.destroy()
            for i, (lab, u) in enumerate(items):
                ttk.Label(urlf, text=lab, width=20).grid(row=i, column=0, sticky="w")
                e = ttk.Entry(urlf, width=58)
                e.insert(0, u)
                e.configure(state="readonly")
                e.grid(row=i, column=1, sticky="we", padx=4)
                ttk.Button(urlf, text="Copy", width=6, command=lambda u=u: copy(u)).grid(
                    row=i, column=2
                )
            qr.delete("all")
            self._qr_url = items[0][1] if items else ""
            mtx = None
            if items:
                try:
                    from mkl import qr as QR  # built in: no 'pip install qrcode' needed (a0.8.0)

                    mtx = QR.matrix(items[0][1])
                except Exception as e:
                    log_exc("phone dialog: QR code", e)
            if mtx:
                q = 2  # quiet zone (modules); the canvas is white
                k = 180 / (len(mtx) + 2 * q)
                for yy, row in enumerate(mtx):
                    for xx, on in enumerate(row):
                        if on:
                            qr.create_rectangle(
                                (xx + q) * k, (yy + q) * k, (xx + q + 1) * k, (yy + q + 1) * k,
                                fill="black", outline="", tags="qr",
                            )
                self._qr_matrix = mtx
                qr_lab.configure(text="QR: %s" % items[0][0])
            else:
                qr.create_text(90, 90, text="No QR code -\nuse Copy", justify="center")
                qr_lab.configure(text="")

        self._rdlg_show = show_urls
        ttk.Button(f, text="Refresh", command=lambda: show_urls()).grid(row=6, column=2, sticky="e")

        def new_tok():
            c["token"] = R.new_token()
            self._save_settings_only()
            show_urls()
            self._remote_apply()

        ttk.Button(f, text="New token (old links stop working)", command=new_tok).grid(
            row=6, column=0, columnspan=2, sticky="w"
        )
        ttk.Separator(f).grid(row=7, column=0, columnspan=4, sticky="we", pady=8)
        ttk.Label(
            f,
            text="Notifications (stored only in your local launcher settings)",
            style="TLabelframe.Label",
        ).grid(row=8, column=0, columnspan=3, sticky="w")
        vs = {}
        for i, (k, lab, w, hide) in enumerate(
            (
                ("discord_webhook", "Discord webhook URL", 60, True),
                ("telegram_token", "Telegram bot token", 46, True),
                ("telegram_chat", "Telegram chat id", 20, False),
                ("every_hours", "Status every N hours (0 = off)", 6, False),
            )
        ):
            vs[k] = tk.StringVar(value=str(n.get(k, 3 if k == "every_hours" else "")))
            ttk.Label(f, text=lab).grid(row=9 + i, column=0, sticky="w")
            ent = ttk.Entry(f, textvariable=vs[k], width=w, show="*" if hide else "")
            ent.grid(row=9 + i, column=1, columnspan=2, sticky="w")
            if hide:
                sb = ttk.Button(f, text="Show", width=6)
                sb.configure(command=lambda e=ent, b=sb: self._toggle_secret(e, b))
                sb.grid(row=9 + i, column=3, sticky="w")
                self._secret_entries = getattr(self, "_secret_entries", {})
                self._secret_entries[k] = (ent, sb)
        v_sp = tk.BooleanVar(value=bool(n.get("send_preview", False)))
        ttk.Checkbutton(
            f,
            text="Also send each new preview MP4 (skipped with a note if over the upload limit)",
            variable=v_sp,
        ).grid(row=13, column=0, columnspan=4, sticky="w")
        v_lt = tk.BooleanVar(value=bool(n.get("send_trained", False)))
        ttk.Checkbutton(f, text="Send a message when training looks trained", variable=v_lt).grid(
            row=14, column=0, columnspan=4, sticky="w"
        )

        def collect():
            try:
                c["port"] = int(v_port.get())
            except ValueError:
                c["port"] = 8765
            c["enabled"] = bool(v_en.get())
            c["host"] = host_of()
            for k, v in vs.items():
                n[k] = v.get().strip()
            try:
                n["every_hours"] = float(n["every_hours"] or 0)
            except ValueError:
                n["every_hours"] = 3.0
            n["send_preview"] = bool(v_sp.get())
            n["send_trained"] = bool(v_lt.get())
            collect_ctl()
            self._register_secrets()
            self._save_settings_only()

        def apply_():
            collect()
            self._remote_apply()
            show_urls()

        def test():
            collect()
            if not self.notifier.targets():
                self._append("[notify] nothing configured\n")
                return
            self._append("[notify] sending a test message...\n")
            threading.Thread(
                target=self.notifier.send_status,
                args=(dict(self.snap),),
                kwargs=dict(kind="test"),
                daemon=True,
            ).start()

        bf = ttk.Frame(f)
        bf.grid(row=17, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="Send test", command=test).pack(side="left", padx=4)
        ttk.Button(bf, text="Apply", command=apply_).pack(side="left", padx=4)
        ttk.Button(bf, text="Close", command=lambda: (apply_(), top.destroy())).pack(
            side="left", padx=4
        )
        show_urls()
        # centred over the main window once everything (QR, link rows) is built - it used to be placed before the
        # link rows existed and then grew down/right from there
        top.update_idletasks()
        place_popup(top, self.root)
        self._rdlg_vars = dict(
            enabled=v_en, port=v_port, host=v_host, apply=apply_, test=test, **vs
        )
