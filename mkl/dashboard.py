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
            state=lines[0] if lines else "",
            running=running,
            session_time=grab(r"Running for (\S+) \(this session") or grab(r"session time (\S+)"),
            total_time=grab(r"Running for (\S+) \(total") or grab(r"Total training time (\S+)"),
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
        )
        v = getattr(self, "vram", None)
        if v:
            snap["vram"] = "%.1f / %.1f GB" % (v[0] / 1024, v[1] / 1024)
            snap["vram_pct"] = round(100 * v[0] / v[1])
        mp4s = glob.glob(os.path.join(d, "preview_*.mp4")) + glob.glob(
            os.path.join(self.mk(), "output", "*", "preview_*.mp4")
        )
        if mp4s:
            p = max(mp4s, key=os.path.getmtime)
            snap["preview"] = dict(
                path=p,
                name=os.path.basename(p),
                key="%s-%d" % (os.path.basename(p), int(os.path.getmtime(p))),
            )
        self.snap = snap
        if self.dash:
            self.dash.set_snapshot(snap)
        if self.notifier.due():
            threading.Thread(
                target=self.notifier.send_status, args=(dict(snap),), daemon=True
            ).start()

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

    def _remote_render(self):
        """Called from the web server thread: never touches Tk, only queues work for the GUI thread."""
        if self.preview_proc and self.preview_proc.poll() is None:
            return False, "A preview is already being rendered."
        self.rq.put(self._remote_render_gui)
        self.render_msg = "Preview requested from the phone - rendering in the background."
        return (
            True,
            "Preview started - it appears here when it is done (usually under a minute or two).",
        )

    def _remote_render_gui(self):
        it = self._item("train")
        model = self.v_model.get().strip() or self._latest_model()
        if not it or not model:
            self.render_msg = "No model.pt yet - nothing to preview."
            self._append("[remote] %s\n" % self.render_msg)
            return
        self._append("[remote] preview requested from the dashboard\n")
        self._start_preview(it, model)

    def _preview_finished(self):
        self.render_msg = "Preview finished."
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
        ttk.Checkbutton(f, text="Enable (read-only web page; off by default)", variable=v_en).grid(
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
            q_mod = R.load_qrcode()
            self._qr_url = items[0][1] if items else ""
            if q_mod is not None and items:
                q = q_mod.QRCode(border=2)
                q.add_data(items[0][1])
                q.make(fit=True)
                mtx = q.get_matrix()
                k = 180 / len(mtx)
                for yy, row in enumerate(mtx):
                    for xx, on in enumerate(row):
                        if on:
                            qr.create_rectangle(
                                xx * k,
                                yy * k,
                                (xx + 1) * k,
                                (yy + 1) * k,
                                fill="black",
                                outline="",
                                tags="qr",
                            )
                qr_lab.configure(text="QR: %s" % items[0][0])
            else:
                qr.create_text(
                    90,
                    90,
                    text="pip install qrcode\nfor a QR code,\nthen press Refresh;\nor use Copy",
                    justify="center",
                )
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
        bf.grid(row=15, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="Send test", command=test).pack(side="left", padx=4)
        ttk.Button(bf, text="Apply", command=apply_).pack(side="left", padx=4)
        ttk.Button(bf, text="Close", command=lambda: (apply_(), top.destroy())).pack(
            side="left", padx=4
        )
        show_urls()
        self._rdlg_vars = dict(
            enabled=v_en, port=v_port, host=v_host, apply=apply_, test=test, **vs
        )
