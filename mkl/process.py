# MimicKit Launcher - configs and runs
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
from mkl.core import *  # noqa: F401,F403 - shared helpers/constants
from mkl.core import __all__ as _core_names  # noqa: F401


class ProcessMixin:
    """Configs and runs: scanning args, starting/resuming/stopping detached MimicKit processes, previews, reattach."""

    def rescan(self):
        self.train_items, self.view_items = discover(self.mk()) if self.mk() else ([], [])
        for f in self.custom:
            a = read_args_file(f if os.path.isabs(f) else os.path.join(self.mk(), f))
            item = dict(
                name="custom: " + os.path.basename(f),
                file=f,
                env=(a.get("env_config") or [""])[0],
                engine="",
                num_envs=int((a.get("num_envs") or ["0"])[0] or 0),
                out=(a.get("out_dir") or [""])[0],
                motion="",
            )
            (
                self.view_items
                if (a.get("mode") or [""])[0] == "test" and "agent_config" not in a
                else self.train_items
            ).append(item)
        pre = {"train": [], "view": []}
        for pr in PRESETS:  # profile presets (launcher_profile.py) go first in the lists
            a = read_args_file(os.path.join(self.mk(), pr["file"])) if self.mk() else {}
            ex = list(pr.get("args", []))
            env = (
                ex[ex.index("--env_config") + 1]
                if "--env_config" in ex
                else (a.get("env_config") or [""])[0]
            )
            pre[pr.get("kind", "train")].append(
                dict(
                    name=pr["name"],
                    file=pr["file"],
                    args=ex,
                    help=pr.get("help", ""),
                    env=env,
                    engine=(a.get("engine_config") or [""])[0],
                    num_envs=int(pr.get("num_envs") or (a.get("num_envs") or ["0"])[0] or 0),
                    out=pr.get("out") or (a.get("out_dir") or [""])[0],
                    motion=motion_of(self.mk(), env) if self.mk() and env else "",
                )
            )
        self.train_items = pre["train"] + self.train_items
        self.view_items = pre["view"] + self.view_items
        self.cb_train.configure(values=[i["name"] for i in self.train_items])
        self.cb_view.configure(values=[i["name"] for i in self.view_items])
        last_t, last_v = self.s.get("last_train"), self.s.get("last_view")
        tn = [i["name"] for i in self.train_items]
        vn = [i["name"] for i in self.view_items]
        self.v_train.set(
            last_t
            if last_t in tn
            else (
                next((n for p in PREFERRED_TRAIN for n in tn if n.startswith(p)), tn[0])
                if tn
                else ""
            )
        )
        self.v_view.set(
            last_v
            if last_v in vn
            else (
                next(
                    (n for p in PREFERRED_VIEW for n in vn if n == p),
                    next((n for n in vn if n.startswith("view_motion")), vn[0]),
                )
                if vn
                else ""
            )
        )
        self._train_changed()
        if self.mk():
            self._append(
                "[gui] found %d training and %d view configs in %s\n"
                % (len(tn), len(vn), os.path.join(self.mk(), "args"))
            )

    def _item(self, kind):
        name = (self.v_train if kind == "train" else self.v_view).get()
        return next(
            (
                i
                for i in (self.train_items if kind == "train" else self.view_items)
                if i["name"] == name
            ),
            None,
        )

    def _train_changed(self, _=None):
        it = self._item("train")
        if not it:
            self.l_preset_help.configure(text="No configs found - set the MimicKit folder above.")
            return
        self.v_out.set(default_out(it))
        if it["num_envs"]:
            self.v_envs.set(it["num_envs"])
        self.l_preset_help.configure(
            text=(it["help"] + "\n" if it.get("help") else "")
            + "%s  |  env: %s  |  motion: %s  |  engine in file: %s"
            % (it["file"], it["env"] or "?", it["motion"] or "?", it["engine"] or "?")
        )

    def _add_custom(self):
        f = filedialog.askopenfilename(
            initialdir=os.path.join(self.mk(), "args"),
            filetypes=[("args files", "*.txt"), ("all", "*.*")],
        )
        if not f:
            return
        try:
            f2 = os.path.relpath(f, self.mk())
        except ValueError:
            f2 = f
        if f2.startswith(".."):
            f2 = f
        self.custom.append(f2.replace(os.sep, "/"))
        self._save()
        self.rescan()

    def _first_run(self):
        if self.mk() and os.path.exists(os.path.join(self.mk(), "mimickit", "run.py")):
            return
        messagebox.showinfo(
            "Welcome",
            "First run: please choose your MimicKit folder\n(the one that contains mimickit\\run.py and args\\).",
        )
        d = filedialog.askdirectory(title="Choose the MimicKit folder")
        if not d:
            return
        self.v_mk.set(os.path.normpath(d))
        v = detect_python(self.mk())
        if v:
            self.v_venv.set(v)
            self._append("[gui] found a Python venv: %s\n" % v)
        elif not self.v_venv.get():
            self._append(
                "[gui] no venv found next to MimicKit - using this Python: %s (change it in Settings)\n"
                % sys.executable
            )
        self._save()
        self.rescan()

    def mk(self):
        return self.v_mk.get().strip()

    def python(self):
        v = self.v_venv.get().strip()
        if v:
            if os.path.isfile(v):
                return v
            cand = os.path.join(
                v, "Scripts" if IS_WIN else "bin", "python.exe" if IS_WIN else "python"
            )
            if os.path.exists(cand):
                return cand
        exe = sys.executable
        if IS_WIN and exe.lower().endswith("pythonw.exe"):
            exe = exe[: -len("pythonw.exe")] + "python.exe"
        return exe

    def outdir_abs(self, rel=None):
        return os.path.join(self.mk(), (rel or self.v_out.get().strip()).replace("/", os.sep))

    def engine_args(self):
        return NEWTON if self.v_newton.get() else []

    def extra_args(self):
        try:
            return shlex.split(self.v_extra.get(), posix=not IS_WIN)
        except ValueError as e:
            messagebox.showerror("Extra args", str(e))
            raise

    def _check(self, kind):
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning("Busy", "Something is already running. Press STOP first.")
            return False
        if not os.path.exists(os.path.join(self.mk(), "mimickit", "run.py")):
            self._append("[gui] MimicKit not found: no mimickit/run.py in %s\n" % self.mk())
            self._show_card("mk_missing", folder=self.mk())
            return False
        it = self._item(kind)
        if not it:
            messagebox.showerror(
                "Nothing selected",
                "No %s config selected (MimicKit's args folder may be empty)." % kind,
            )
            return False
        self.s["last_train"], self.s["last_view"] = self.v_train.get(), self.v_view.get()
        self._save()
        return True

    def _tt_save(self, final=False):
        with self.tt_lock:
            t = self.tt
            if not t:
                return
            j = dict(
                seconds=round(t["base"] + time.time() - t["start"], 1),
                sessions=t["sessions"],
                parent=t["parent"],
                updated=datetime.datetime.now().isoformat(timespec="seconds"),
                launcher_version=VERSION,
            )
            write_time(t["dir"], j)
            if final:
                self.tt = None

    def _tt_total(self):
        with self.tt_lock:
            if self.tt:
                return (
                    self.tt["base"] + time.time() - self.tt["start"],
                    time.time() - self.tt["start"],
                    self.tt["sessions"],
                )
        try:
            tot, ses = chain_total(run_chain(self._model_dirs(self.v_out.get().strip())[-1][1]))
        except Exception:
            tot, ses = 0.0, 0
        return tot, None, ses

    def _model_dirs(self, base_rel):
        """base folder + its _resumeN folders, as (N, abs path)"""
        return chain_folders(self.outdir_abs(base_rel))

    def _no_model_card(self):
        self._append("[gui] no model.pt in %s yet\n" % self.outdir_abs())
        self._show_card("no_model", folder=self.outdir_abs(), ipo=self._ipo(None))

    def _latest_model(self):
        best = None
        for _, d in self._model_dirs(self.v_out.get().strip()):
            m = os.path.join(d, "model.pt")
            if os.path.exists(m) and (best is None or os.path.getmtime(m) > os.path.getmtime(best)):
                best = m
        return best

    def view(self):
        if not self._check("view"):
            return
        it = self._item("view")
        self._run(
            ["--arg_file", it["file"]]
            + it.get("args", [])
            + self.engine_args()
            + ["--visualize", "true"]
            + self.extra_args(),
            kind="view",
            out=None,
        )

    def train(self):
        if not self._check("train"):
            return
        out_rel = self.v_out.get().strip()
        out = self.outdir_abs(out_rel)
        if os.path.isdir(out) and os.listdir(out):
            if not messagebox.askyesno(
                "Folder already used",
                "The folder\n%s\nalready has files (an earlier run).\n\nStarting again OVERWRITES its model.pt and log.txt.\n"
                "Tip: press No and use 'Resume training' instead, or type a new folder name.\n\nOverwrite?"
                % out,
                icon="warning",
            ):
                return
        it = self._item("train")
        self.tt_next = dict(base=0.0, sessions=1, parent=None)
        self._run(
            self._ovr(it)
            + ["--arg_file", it["file"]]
            + it.get("args", [])
            + self.engine_args()
            + ["--num_envs", str(self.v_envs.get()), "--visualize", "false", "--out_dir", out_rel]
            + self.extra_args(),
            kind="train",
            out=out,
        )

    def resume(self):
        if not self._check("train"):
            return
        model = self._latest_model()
        if not model:
            self._no_model_card()
            self._append(
                "[gui] nothing to resume: no model.pt in %s (or its _resume folders)\n"
                % self.outdir_abs(),
            )
            return
        dirs = self._model_dirs(self.v_out.get().strip())
        n = dirs[-1][0] + 1
        new_rel = "%s_resume%d" % (self.v_out.get().strip().rstrip("/\\"), n)
        new_abs = self.outdir_abs(new_rel)
        os.makedirs(new_abs, exist_ok=True)
        start = os.path.join(new_abs, "start_model.pt")
        shutil.copy2(model, start)
        tot, ses = chain_total(run_chain(dirs[-1][1]))
        self.tt_next = dict(base=tot, sessions=ses + 1, parent=dirs[-1][1])
        self._append(
            "[gui] carrying total training time %s (%d earlier sessions)\n" % (hms(tot), ses)
        )
        self._append("[gui] copied %s -> %s\n" % (model, start))
        it = self._item("train")
        self._run(
            self._ovr(it)
            + ["--arg_file", it["file"]]
            + it.get("args", [])
            + self.engine_args()
            + [
                "--num_envs",
                str(self.v_envs.get()),
                "--visualize",
                "false",
                "--model_file",
                os.path.relpath(start, self.mk()).replace(os.sep, "/"),
                "--out_dir",
                new_rel,
            ]
            + self.extra_args(),
            kind="train",
            out=new_abs,
        )

    def watch(self):
        if not self._check("train"):
            return
        model = self.v_model.get().strip() or self._latest_model()
        if not model:
            self._no_model_card()
            return
        it = self._item("train")
        mrel = os.path.relpath(model, self.mk()) if os.path.isabs(model) else model
        view = self._view_env(
            it, "watch"
        )  # first occurrence of a key wins in MimicKit's arg parser -> put it first
        self._run(
            (["--env_config", view] if view else [])
            + self._ovr(it, agent_only=True)
            + ["--arg_file", it["file"]]
            + it.get("args", [])
            + self.engine_args()
            + [
                "--mode",
                "test",
                "--num_envs",
                "1",
                "--visualize",
                "true",
                "--model_file",
                mrel.replace(os.sep, "/"),
            ]
            + self.extra_args(),
            kind="watch",
            out=None,
        )

    def _view_env(self, it, kind):
        """Generated chronological view yaml (relative to MimicKit) for item it, or None if it has no env_config."""
        if not it.get("env"):
            self._append("[gui] this config has no env_config - playing it as is\n")
            return None
        dst = os.path.join(self.mk(), "output", "_launcher_" + kind, "view_env.yaml")
        c = TS.current(self.mk(), it["name"])
        src = (c or {}).get("env") or it["env"]
        if not make_view_env(self.mk(), src, dst):
            self._append("[gui] could not read %s - playing the config as is\n" % it["env"])
            return None
        self._append(
            "[gui] chronological view env: %s (from %s)\n"
            % (os.path.relpath(dst, self.mk()).replace(os.sep, "/"), src)
        )
        return os.path.relpath(dst, self.mk()).replace(os.sep, "/")

    def continue_from(self):
        """Start a new training run of the current config from the newest model of another run chain."""
        if not self._check("train"):
            return
        src = filedialog.askdirectory(
            title="Pick the run to continue from (a folder with model.pt, or its _resumeN folders)",
            initialdir=os.path.join(self.mk(), "output"),
        )
        if not src:
            return
        src = os.path.abspath(src)
        models = [
            os.path.join(d, "model.pt")
            for _, d in chain_folders(base_of(src))
            if os.path.exists(os.path.join(d, "model.pt"))
        ]
        if not models:
            messagebox.showerror(
                "No model there", "No model.pt in %s or its _resumeN folders." % src
            )
            return
        model = max(models, key=os.path.getmtime)
        src_dir = os.path.dirname(model)
        out_rel = self.v_out.get().strip().rstrip("/\\")
        out = self.outdir_abs(out_rel)
        if os.path.isdir(out) and os.listdir(out):
            new_rel = "%s_resume%d" % (out_rel, self._model_dirs(out_rel)[-1][0] + 1)
        else:
            new_rel = out_rel
        new_abs = self.outdir_abs(new_rel)
        if os.path.normcase(os.path.abspath(new_abs)) in [
            os.path.normcase(os.path.abspath(c)) for c in run_chain(src_dir)
        ]:
            messagebox.showerror("Same folder", "The new run folder is part of the source run.")
            return
        tot, ses = chain_total(run_chain(src_dir))
        it = self._item("train")
        if not messagebox.askyesno(
            "Continue from another run",
            "Continue training\n  config: %s\nfrom\n  %s\ninto\n  %s\n\nCarries %s of training (%d sessions) and the chart history."
            % (it["name"], model, new_abs, hms(tot), ses),
        ):
            return
        os.makedirs(new_abs, exist_ok=True)
        start = os.path.join(new_abs, "start_model.pt")
        shutil.copy2(model, start)
        try:
            U.save_json(
                os.path.join(new_abs, LINK_FILE),
                dict(
                    parent=src_dir,
                    parent_model=model,
                    config=it["name"],
                    env=it.get("env", ""),
                    created=datetime.datetime.now().isoformat(timespec="seconds"),
                    launcher_version=VERSION,
                ),
            )
        except OSError as e:
            log_exc("writing the run link", e)
        self.tt_next = dict(base=tot, sessions=ses + 1, parent=src_dir)
        self._append(
            "[gui] continuing from %s (total %s, %d sessions) -> %s\n"
            % (src_dir, hms(tot), ses, new_rel)
        )
        self._run(
            self._ovr(it)
            + ["--arg_file", it["file"]]
            + it.get("args", [])
            + self.engine_args()
            + [
                "--num_envs",
                str(self.v_envs.get()),
                "--visualize",
                "false",
                "--model_file",
                os.path.relpath(start, self.mk()).replace(os.sep, "/"),
                "--out_dir",
                new_rel,
            ]
            + self.extra_args(),
            kind="train",
            out=new_abs,
        )

    def preview_diag(self):
        return self.preview(diag=True)

    def preview(self, diag=False):
        """Render preview MP4 (or run the preview diagnostics) in a separate detached process (never touches training)."""
        if self.preview_proc and self.preview_proc.poll() is None:
            if messagebox.askyesno("Preview running", "A preview is being rendered. Cancel it?"):
                self._kill(self.preview_proc.pid, "preview")
            return
        if not os.path.exists(os.path.join(self.mk(), "mimickit", "run.py")):
            self._append("[gui] MimicKit not found: no mimickit/run.py in %s\n" % self.mk())
            self._show_card("mk_missing", folder=self.mk())
            return
        it = self._item("train")
        model = self.v_model.get().strip() or self._latest_model()
        if diag and it:
            return self._start_preview(it, model, diag=True)
        if not it:
            messagebox.showinfo("No training config", "Pick a training config first.")
            return
        if not model:
            self._no_model_card()
            return
        return self._start_preview(it, model)

    def _start_preview(self, it, model, diag=False):
        pdir = os.path.join(self.mk(), "output", "_launcher_preview")
        os.makedirs(pdir, exist_ok=True)
        view = self._view_env(it, "preview")
        if not view:
            messagebox.showerror(
                "No env config", "This config has no env_config, so there is nothing to preview."
            )
            return
        margs = []
        if model:
            model = model if os.path.isabs(model) else os.path.join(self.mk(), model)
            snap = os.path.join(pdir, "preview_model.pt")
            shutil.copy2(model, snap)  # snapshot: training may overwrite model.pt any time
            margs = ["--model_file", os.path.relpath(snap, self.mk()).replace(os.sep, "/")]
        mk_args = (
            ["--env_config", view]
            + self._ovr(it, agent_only=True)
            + margs
            + ["--arg_file", it["file"]]
            + it.get("args", [])
            + self.engine_args()
        )
        script = os.path.join(HERE, "mimickit_preview.py")
        if diag:
            mp4 = os.path.join(pdir, "preview_diagnostics.txt")
            cmd = [self.python(), "-u", script, "diag", "--mk", self.mk(), "--"] + mk_args
        else:
            itn = last_iteration(os.path.dirname(model))
            mp4 = os.path.join(
                os.path.dirname(model),
                "preview_%s.mp4" % (itn if itn is not None else time.strftime("%Y%m%d_%H%M%S")),
            )
            dev = {"Auto": "auto", "CPU only": "cpu", "GPU": "gpu"}.get(self.v_pdev.get(), "auto")
            cmd = [
                self.python(),
                "-u",
                script,
                "all",
                "--mk",
                self.mk(),
                "--device",
                dev,
                "--ghost",
                GHOST_MODES.get(self.v_ghost.get(), "overlay"),
                "--layout",
                CLIP_LAYOUTS.get(self.v_layout.get(), "grid"),
                "--out",
                mp4,
                "--",
            ] + mk_args
        logp = os.path.join(pdir, CONSOLE_FILE)
        try:
            offset = os.path.getsize(logp) if os.path.exists(logp) else 0
            self.preview_proc = self._spawn_detached(
                cmd, logp, env=dict(os.environ, PYTHONUNBUFFERED="1")
            )
        except Exception as e:
            messagebox.showerror("Could not start the preview", str(e))
            return
        write_run_state(
            os.path.join(pdir, RUN_STATE),
            dict(
                pid=self.preview_proc.pid,
                cmd=cmd,
                kind="preview",
                started=time.time(),
                log=logp,
                offset=offset,
                out=None,
                launcher_version=VERSION,
            ),
        )
        self._append(
            "\n[gui] ===== %s  %s =====\n[gui] model %s -> %s (device %s, PID %d; runs in the background)\n"
            % (
                "PREVIEW DIAGNOSTICS" if diag else "PREVIEW",
                datetime.datetime.now().strftime("%H:%M:%S"),
                model or "(none: untrained policy)",
                mp4,
                self.v_pdev.get(),
                self.preview_proc.pid,
            )
        )
        threading.Thread(
            target=self._reader,
            args=(self.preview_proc, logp, offset, None, "preview"),
            daemon=True,
        ).start()

    def stop(self):
        if not self.proc or self.proc.poll() is not None:
            self._append("[gui] nothing is running\n")
            return
        pid = self.proc.pid
        self._tt_save(final=True)
        self.sm.stopped_by_user = True
        self._kill(pid)
        self._append("[gui] stopped. Your saved progress (model.pt) is kept.\n")

    def _kill(self, pid, what=""):
        """Kill a detached process and its whole tree (Windows: taskkill /T /F, Linux: its process group)."""
        if IS_WIN:
            r = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                creationflags=NO_WINDOW,
            )
            self._append(
                "[gui] taskkill%s: %s%s\n"
                % (" " + what if what else "", r.stdout.strip(), r.stderr.strip())
            )
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except Exception as e:
                self._append("[gui] kill failed: %s\n" % e)
        if what:
            self._append("[gui] %s cancelled\n" % what)

    def _run(self, args, kind, out):
        cmd = [self.python(), "-u", "mimickit/run.py"] + args
        self._show_cmd(cmd)
        self._append(
            "\n[gui] ===== %s  %s =====\n"
            % (kind.upper(), datetime.datetime.now().strftime("%H:%M:%S"))
        )
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        log_dir = out or os.path.join(
            self.mk(), "output", "_launcher_" + kind
        )  # view / watch: their own small log folder
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            pass
        if kind == "train":
            for fn in (
                HIST_FILE,
                CONSOLE_FILE,
            ):  # fresh start / new resume folder: history restarts here
                try:
                    os.remove(os.path.join(log_dir, fn))
                except OSError:
                    pass
        logp = os.path.join(log_dir, CONSOLE_FILE)
        try:
            offset = os.path.getsize(logp) if os.path.exists(logp) else 0
            # detached: MimicKit writes straight into console_log.txt, so it keeps running if this window closes or crashes
            self.proc = self._spawn_detached(cmd, logp, env)
        except Exception as e:
            messagebox.showerror("Could not start", str(e))
            return
        self.run_kind, self.started = kind, time.time()
        self._status_reset(kind)
        if out:
            self.run_dir = out
        nxt = None
        if kind == "train":
            self.live.reset()
            self.live_dir = out
            self.hist_n = 0
            nxt = self.tt_next or dict(base=0.0, sessions=1, parent=None)
            self.tt_next = None
            with self.tt_lock:
                self.tt = dict(nxt, dir=out, start=self.started)
            self._tt_save()
        i = proc_info(self.proc.pid) or {}
        st = dict(
            pid=self.proc.pid,
            cmd=cmd,
            cwd=self.mk(),
            kind=kind,
            started=self.started,
            proc_start=i.get("start"),
            log=logp,
            offset=offset,
            out=out,
            out_rel=self.v_out.get().strip() if out else None,
            tt=nxt,
            launcher_version=VERSION,
            started_text=datetime.datetime.now().isoformat(timespec="seconds"),
        )
        self.state_path = os.path.join(log_dir, RUN_STATE)
        write_run_state(self.state_path, st)
        self.s["active_run"] = self.state_path
        self._save_settings_only()
        self._append("[gui] started PID %d (detached; output -> %s)\n" % (self.proc.pid, logp))
        threading.Thread(
            target=self._reader, args=(self.proc, logp, offset, self.state_path), daemon=True
        ).start()
        self._progress_tick(force=True)

    def _spawn_detached(self, cmd, logp, env):
        """Start cmd in MimicKit's folder, detached from this window, output appended (unbuffered) to logp."""
        with open(logp, "ab", buffering=0) as logf:
            return subprocess.Popen(
                cmd,
                cwd=self.mk(),
                stdout=logf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=DETACHED_FLAGS,
                start_new_session=not IS_WIN,
                close_fds=True,
            )

    def _reattach(self):
        """On startup: if a detached run from an earlier window is still running, show it again and keep tailing its log."""
        p = self.s.get("active_run")
        st = read_run_state(p) if p else None
        if not st or (self.proc and self.proc.poll() is None):
            return False
        if not run_state_matches(st):
            if not st.get("ended"):
                st["ended"] = "not running at reattach"
                write_run_state(p, st)
            return False
        self.proc = PidProc(st["pid"], st)
        self.state_path = p
        self.run_kind, self.started = st["kind"], st["started"]
        self._status_reset(st["kind"])
        self._show_cmd(st.get("cmd", []), st.get("cwd"))
        if st.get("out"):
            self.run_dir = st["out"]
            if st.get("out_rel"):
                self.v_out.set(st["out_rel"])
        if st["kind"] == "train":
            self.live.reset()
            self.live_dir = st["out"]
            self.hist_n = 0
            nxt = st.get("tt") or dict(base=0.0, sessions=1, parent=None)
            with self.tt_lock:
                self.tt = dict(nxt, dir=st["out"], start=st["started"])
        self._append(
            "\n[gui] ===== REATTACHED to running %s (PID %d, started %s) =====\n"
            % (
                st["kind"].upper(),
                st["pid"],
                datetime.datetime.fromtimestamp(st["started"]).strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        threading.Thread(
            target=self._reader, args=(self.proc, st["log"], st.get("offset", 0), p), daemon=True
        ).start()
        self._progress_tick(force=True)
        return True

    def _reader(self, proc, logp, offset, state_path=None, kind=None):
        """Tails console_log.txt (written by the detached process) into the log panel and the live chart parser."""
        feed = kind is None and self.run_kind == "train"
        tail = LineTail()
        f = None

        def emit(lines):
            for line in lines:
                self.q.put(line)
                if kind is None:
                    self.sm_q.put(line)
                if feed:
                    with self.live_lock:
                        self.live.feed(line)

        def drain(final=False):
            data = f.read() if f else b""
            emit(tail.feed(data, final))
            return bool(data)

        while True:
            if f is None:
                try:
                    f = open(logp, "rb")
                    f.seek(offset)
                except OSError:
                    f = None
            alive = proc.poll() is None
            if not drain() and alive:
                time.sleep(0.2)
            if not alive:
                break
        time.sleep(0.3)
        drain(final=True)
        if f:
            f.close()
        if feed:
            self._tt_save(final=True)
        if state_path:
            st = read_run_state(state_path)
            if st and st.get("pid") == proc.pid:
                st["ended"] = datetime.datetime.now().isoformat(timespec="seconds")
                st["exit_code"] = proc.returncode
                write_run_state(state_path, st)
        ended = "[gui] %sprocess ended (exit code %s)\n" % (
            "%s " % kind if kind else "",
            proc.returncode,
        )
        self.q.put(ended)
        if kind is None:
            self.sm_q.put(ended)
        elif kind == "preview" and proc.returncode not in (0, None):
            self.sm_q.put(("preview_end", proc.returncode, logp))
        if kind == "preview" and proc.returncode == 0:
            self._preview_finished()

    def _ovr(self, it, agent_only=False):
        """Args that point MimicKit at the saved edited copies (first value of a key wins, so they go first)."""
        if not it:
            return []
        a = TS.override_args(self.mk(), it["name"])
        if agent_only:
            a = (
                a[a.index("--agent_config") : a.index("--agent_config") + 2]
                if "--agent_config" in a
                else []
            )
        if a:
            self._append("[gui] using edited training settings: %s\n" % " ".join(a))
        return a

    def _cfg_files(self, it):
        """(env yaml, agent yaml) of a config, relative to MimicKit (preset extra args win, like on the command line)."""
        a = read_args_file(os.path.join(self.mk(), it["file"]))
        ex = it.get("args", [])
        env = (
            ex[ex.index("--env_config") + 1]
            if "--env_config" in ex
            else (a.get("env_config") or [""])[0]
        )
        ag = (
            ex[ex.index("--agent_config") + 1]
            if "--agent_config" in ex
            else (a.get("agent_config") or [""])[0]
        )
        return env, ag
