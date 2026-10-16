# MimicKit Launcher - launcher settings, training settings dialog, mimickit patches.
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
from mkl.core import *  # noqa: F401,F403 - shared helpers/constants
from mkl.core import __all__ as _core_names  # noqa: F401
import mimickit_patches as MP


class SettingsMixin:
    """Launcher settings, training settings dialog, MimicKit patches."""

    def _save(self):
        self.s.update(
            mimickit=self.v_mk.get().strip(),
            venv=self.v_venv.get().strip(),
            light_mode=bool(self.v_light.get()),
            custom_args=list(getattr(self, "custom", [])),
        )
        if hasattr(self, "v_newton"):
            self.s["force_newton"] = bool(self.v_newton.get())
        try:
            U.save_json(CONFIG, self.s)
        except OSError as e:
            self._append("[gui] could not save settings: %s\n" % e)

    def _save_settings_only(self):
        self._register_secrets()
        try:
            U.save_json(CONFIG, self.s)
        except OSError as e:
            log_exc("saving settings", e)

    def train_settings_dialog(self):
        import mimickit_patches as MP

        it = self._item("train")
        if not it:
            messagebox.showinfo("No training config", "Pick a training config first.")
            return
        mk = self.mk()
        oenv, oag = self._cfg_files(it)
        cur = TS.current(mk, it["name"])
        env, ag = (cur.get("env") or oenv, cur.get("agent") or oag) if cur else (oenv, oag)
        base = TS.read_values(mk, env, ag)
        # capped at 80% of the screen: the settings scroll, the note + Save/Close stay pinned at the bottom
        top, f, pinned = scroll_popup(self.root, "Training settings - " + it["name"], T)
        self._tsdlg = top  # tests measure this (like _rdlg)
        src = "edited copy saved %s" % cur["saved"] if cur else "original files"
        hdr = ttk.Label(
            f,
            text="Config %s  -  now using: %s\nenv: %s    agent: %s"
            % (it["name"], src, env or "(none)", ag or "(none)"),
            style="Dim.TLabel",
            justify="left",
        )
        hdr.grid(row=0, column=0, columnspan=2, sticky="w")
        cols = [ttk.Frame(f), ttk.Frame(f)]
        for i, c in enumerate(cols):
            c.grid(row=1, column=i, sticky="nw", padx=(0, 12) if i == 0 else 0)
        vars_ = {}
        self._ts_fields(base, cols, mk, vars_)
        self._ts_clips(cols, env, mk)
        self._ts_scale(cols)
        self._ts_stubs(cols)
        # a0.6.1 item: never cut the right-hand column / help text sideways. If both columns don't fit in 80% of the
        # screen, stack them, so the dialog only ever scrolls up and down.
        f.update_idletasks()
        if f.winfo_reqwidth() > int(top.winfo_screenwidth() * 0.8) - 40:
            cols[0].grid_configure(padx=0)
            cols[1].grid(row=2, column=0, sticky="nw")
            self._ts_stacked = True
        else:
            self._ts_stacked = False
        note = ttk.Label(
            pinned,
            text="Save writes an edited copy (originals backed up, never changed). It applies on the next Start, Resume, Continue, "
            "Watch or Preview of this config.\nA run that is already going keeps the settings it started with.",
            style="Dim.TLabel",
            justify="left",
        )
        note.pack(side="top", anchor="w", pady=(0, 4))
        top.after_idle(top._scroll["fit"])  # the update_idletasks() above already ran the first fit, before stacking

        def collect():
            changes, bad = {}, []
            for (kind, path), (var, typ, v0) in vars_.items():
                raw = var.get()
                if typ == "bool":
                    v = bool(raw)
                else:
                    raw = str(raw).strip()
                    if raw == "":
                        continue
                    try:
                        v = int(raw) if typ == "int" else float(raw)
                    except ValueError:
                        bad.append(path[-1])
                        continue
                if v0 is None and path != ("clip_start_share",):
                    continue
                if v != v0 and not (path == ("clip_start_share",) and v0 is None and v == 0.0):
                    changes[(kind, path)] = v
            share = changes.get(("env", ("clip_start_share",)))
            if share is not None and not 0.0 <= share <= 1.0:
                bad.append("clip_start_share (0-1)")
            el = changes.get(("env", ("episode_length",)))
            if el is not None and el <= 0:
                bad.append("episode_length (> 0)")
            hold = self.v_hold.get().strip()
            h = None
            if hold:
                try:
                    h = float(hold)
                    assert 0 <= h <= 30
                except (ValueError, AssertionError):
                    bad.append("end hold (0-30 s)")
            return changes, h, bad

        def save():
            changes, h, bad = collect()
            if bad:
                messagebox.showerror("Check these values", "\n".join(bad), parent=top)
                return None
            if not changes and h is None:
                self._append("[gui] training settings: nothing changed\n")
                return "same"
            share = changes.get(("env", ("clip_start_share",)))
            if share and MP.status(mk, TS.PATCH_NAME) != "applied":
                self._append(
                    "[gui] note: 'Starts at clip start' only works with the Clip start share patch (Apply patch)\n"
                )
            try:
                c = TS.save(mk, it["name"], env, ag, changes, hold=h, orig_env=oenv, orig_agent=oag)
            except Exception as e:
                messagebox.showerror("Could not save", str(e), parent=top)
                return None
            self._append(
                "[gui] training settings saved -> %s (%s). Applies on the next Start / Resume.\n"
                % (
                    c["dir"],
                    ", ".join("%s=%s" % kv for kv in c["values"].items())
                    + (", end hold %gs" % h if h is not None else ""),
                )
            )
            top.destroy()
            return c

        def originals():
            TS.clear(mk, it["name"])
            self._append(
                "[gui] training settings: back to the original files for %s\n" % it["name"]
            )
            top.destroy()

        bf = ttk.Frame(pinned)
        bf.pack(side="top", anchor="w")
        ttk.Button(bf, text="Save", command=save).pack(side="left", padx=3)
        b = ttk.Button(bf, text="Use originals", command=originals)
        b.pack(side="left", padx=3)
        Tip(
            b,
            "Stop using the edited copy for this config (saved copies stay in output/_launcher_configs).",
        )
        if not cur:
            b.state(["disabled"])
        ttk.Button(bf, text="Close", command=top.destroy).pack(side="left", padx=3)
        self._ts_dlg = dict(top=top, vars=vars_, save=save, collect=collect, originals=originals)
        return top

    def _ts_fields(self, base, cols, mk, vars_):
        """Episodes / Early termination / Learning: one row per yaml setting (+ the clip start patch button)."""
        for si, (title, kind, fields) in enumerate(TS.SECTIONS):
            lf = self._ts_section(cols[0] if kind == "env" else cols[1], title)
            for r, (path, label, typ, hint) in enumerate(fields):
                v0 = base.get((kind, path))
                if path == ("clip_start_share",) and v0 is None:
                    v0 = 0.0
                if typ == "bool":
                    var = tk.BooleanVar(value=bool(v0))
                    w = ttk.Checkbutton(lf, variable=var)
                else:
                    var = tk.StringVar(
                        value=(
                            "" if v0 is None else ("%g" % v0 if isinstance(v0, float) else str(v0))
                        )
                    )
                    w = ttk.Entry(lf, textvariable=var, width=10)
                if v0 is None and path != ("clip_start_share",):
                    w.state(["disabled"])
                    hint += " (not in this config)"
                vars_[(kind, path)] = (var, typ, v0)
                self._ts_row(lf, r, label, w, hint)
            if title == "Episodes":
                st = MP.status(mk, TS.PATCH_NAME)
                pl = ttk.Label(
                    lf,
                    text="Clip start share patch: " + st,
                    style="Good.TLabel" if st == "applied" else "Dim.TLabel",
                )
                pl.grid(row=len(fields), column=0, columnspan=2, sticky="w", pady=(4, 0))

                def ap(lbl=pl):
                    try:
                        msg = MP.apply(mk, TS.PATCH_NAME)
                    except Exception as e:
                        msg = "failed: %s" % e
                    self._append("[patch] %s: %s\n" % (TS.PATCH_NAME, msg))
                    lbl.configure(text="Clip start share patch: " + MP.status(mk, TS.PATCH_NAME))

                b = ttk.Button(lf, text="Apply patch", command=ap)
                b.grid(row=len(fields), column=2, sticky="w", pady=(4, 0))
                Tip(b, HELP["patches"])

    def _ts_clips(self, cols, env, mk):
        """Motion clips: lengths, end holds and the End hold field."""
        lf = self._ts_section(cols[0], "Motion clips")
        envtxt = ""
        try:
            envtxt = open(os.path.join(mk, env), encoding="utf-8").read() if env else ""
        except OSError:
            pass
        clips = TS.motion_files(mk, TS.get(envtxt, ("motion_file",)) if envtxt else "")
        lines = []
        for fpath, _ in clips[:8]:
            try:
                ci = TS.clip_info(os.path.join(mk, fpath))
                lines.append(
                    "%s: %.2f s, end hold %.2f s%s"
                    % (
                        os.path.basename(fpath),
                        ci["length"],
                        ci["hold"],
                        " (loops: unchanged)" if ci["loop"] else "",
                    )
                )
            except Exception as e:
                lines.append("%s: can't read (%s)" % (os.path.basename(fpath), type(e).__name__))
        if len(clips) > 8:
            lines.append("... and %d more" % (len(clips) - 8))
        ttk.Label(
            lf, text="\n".join(lines) or "(no clips found)", style="Dim.TLabel", justify="left"
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        self.v_hold = tk.StringVar(value="")
        w = ttk.Entry(lf, textvariable=self.v_hold, width=10)
        if not clips:
            w.state(["disabled"])
        self._ts_row(
            lf,
            1,
            "End hold (s)",
            w,
            "How long each clip holds its final pose. Blank = keep. Trims or repeats the last frame "
            "(edited copies of the clips; looping clips are left alone).",
        )

    def _ts_scale(self, cols):
        """Scale: number of envs."""
        lf = self._ts_section(cols[0], "Scale")
        sp = ttk.Spinbox(lf, from_=1, to=65536, increment=512, textvariable=self.v_envs, width=8)
        self._ts_row(
            lf,
            0,
            "Number of envs",
            sp,
            "Parallel simulations. More = faster but more GPU memory. Same as num_envs on the main window.",
        )

    def _ts_stubs(self, cols):
        """Coming soon / needs your input (greyed out)."""
        lf = self._ts_section(cols[1], "Coming soon / needs your input")
        for r, (name, what) in enumerate(TS.STUBS):
            cb = ttk.Checkbutton(lf, text=name)
            cb.state(["disabled", "!selected"])
            cb.grid(row=r, column=0, sticky="w")
            ttk.Label(lf, text=what, style="Dim.TLabel", wraplength=360, justify="left").grid(
                row=r, column=1, sticky="w", padx=6
            )
        ttk.Label(
            lf,
            text="Not built yet: each needs your input on how it should work.",
            style="Dim.TLabel",
        ).grid(row=len(TS.STUBS), column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _ts_section(self, parent, title):
        """A titled box in the training settings dialog."""
        lf = ttk.LabelFrame(parent, text=title, padding=6)
        lf.pack(fill="x", pady=4)
        return lf

    @staticmethod
    def _ts_row(lf, r, label, widget, hint):
        """label | widget | one-line hint (also the tooltip)."""
        l = ttk.Label(lf, text=label)
        l.grid(row=r, column=0, sticky="w")
        widget.grid(row=r, column=1, sticky="w", padx=6)
        h = ttk.Label(lf, text=hint, style="Dim.TLabel", wraplength=330, justify="left")
        h.grid(row=r, column=2, sticky="w")
        Tip(l, hint)
        Tip(widget, hint)

    def _register_secrets(self):
        """Secrets from the settings are masked in the error log and anything else the launcher writes out."""
        n, r = self.s.get("notify") or {}, self.s.get("remote") or {}
        U.add_secret(n.get("discord_webhook"), n.get("telegram_token"), r.get("token"))

    def patch_dialog(self):
        import mimickit_patches as MP

        top, f, pinned = scroll_popup(self.root, "MimicKit patches", T)  # capped at 80% of the screen
        self._pdlg = top  # tests measure this (like _rdlg)
        rows = {}
        ttk.Label(f, text="Folder: " + self.mk(), style="Dim.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w"
        )

        def refresh():
            for name, (lab, _) in rows.items():
                lab.configure(text=MP.status(self.mk(), name))

        def act(fn, name):
            try:
                msg = fn(self.mk(), name)
            except Exception as e:
                msg = "failed: %s" % e
            self._append("[patch] %s: %s\n" % (name, msg))
            refresh()
            self._progress_tick(force=True)

        for i, (name, p) in enumerate(MP.PATCHES.items()):
            ttk.Label(f, text=p["title"]).grid(row=1 + 2 * i, column=0, sticky="w", pady=(8, 0))
            st = ttk.Label(f, text="", style="Good.TLabel")
            st.grid(row=1 + 2 * i, column=1, padx=8, pady=(8, 0))
            b1 = ttk.Button(f, text="Apply", command=lambda n=name: act(MP.apply, n))
            b1.grid(row=1 + 2 * i, column=2, pady=(8, 0))
            b2 = ttk.Button(f, text="Revert", command=lambda n=name: act(MP.revert, n))
            b2.grid(row=1 + 2 * i, column=3, pady=(8, 0))
            ttk.Label(
                f, text="%s: %s" % (p["file"], p["why"]), style="Dim.TLabel", justify="left"
            ).grid(row=2 + 2 * i, column=0, columnspan=4, sticky="w")
            for w in (b1, b2):
                Tip(w, HELP["patches"])
            rows[name] = (st, p)
        ttk.Label(
            f,
            text="Changes apply to runs started afterwards; a running training keeps its old code.",
            style="Dim.TLabel",
        ).grid(row=10, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Button(pinned, text="Close", command=top.destroy).pack(side="left", padx=3)
        refresh()
        self._patch_dlg = dict(top=top, refresh=refresh, act=act)
