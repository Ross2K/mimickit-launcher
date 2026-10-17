# MimicKit Launcher - training progress
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
import numpy as np

from mkl.core import *  # noqa: F401,F403 - shared helpers/constants
from mkl.core import __all__ as _core_names  # noqa: F401

STATUS_PANEL_SHOWS = ("model.pt last saved", "No training data yet", "Avg reward per step: needs")


class ChartsMixin:
    """Training progress: status text, charts (navigation, downsampling, hover) and the progress estimate."""

    def _restyle_artists(self):
        """Live theme switch without waiting for data: recolour what is already drawn (lines carry a role gid)."""
        role = {
            "cur1": T["line1"],
            "cur2": T["line2"],
            "cur3": T["line3"],
            "earlier": T["dim"],
            "bridge": T["dim"],
        }
        for ax in self._axes():
            for ln in ax.get_lines():
                g = ln.get_gid()
                if g in role:
                    ln.set_color(role[g])
                    ln.set_markerfacecolor(role[g])
                    ln.set_markeredgecolor(role[g])
            for t in ax.texts:
                t.set_color(T["dim"])
            self._style_ax(ax)

    def _smooth_estimate(self, chain, v):
        """Displayed % moves at most 10 points per refresh (and eases in), so a noisy fit doesn't jump around."""
        old = self.est_disp.get(chain)
        new = v if old is None else old + max(-10.0, min(10.0, 0.5 * (v - old)))
        self.est_disp = {chain: new}
        return new

    def _chain_key(self, d):
        return os.path.normcase(os.path.abspath(run_chain(d)[0]))

    def _get_target(self, d):
        return self.s.get("targets", {}).get(self._chain_key(d))

    def _set_target(self, d, t):
        tg = self.s.setdefault("targets", {})
        k = self._chain_key(d)
        if t:
            tg[k] = t
        else:
            tg.pop(k, None)
        self._save_settings_only()

    def _target_from_widgets(self):
        d = self.run_dir or self.outdir_abs()
        kind = self.v_tkind.get()
        if kind.startswith("plateau"):
            self._set_target(d, None)
        else:
            try:
                val = float(self.v_tval.get().replace(",", ""))
            except ValueError:
                if self.v_tval.get().strip():
                    messagebox.showerror(
                        "Target", "Type a number (samples in millions, or a score)."
                    )
                return
            self._set_target(
                d,
                (
                    dict(kind="samples", value=val * 1e6)
                    if kind.startswith("samples")
                    else dict(kind="score", value=val)
                ),
            )
        self._progress_tick(force=True)

    def _sync_target_widgets(self, d):
        k = self._chain_key(d)
        if k == self._target_root:
            return
        self._target_root = k
        t = self._get_target(d)
        if not t:
            self.v_tkind.set("plateau (auto)")
            self.v_tval.set("")
        elif t["kind"] == "samples":
            self.v_tkind.set("samples (millions)")
            self.v_tval.set("%g" % (t["value"] / 1e6))
        else:
            self.v_tkind.set("score (Train_Return)")
            self.v_tval.set("%g" % t["value"])

    def _make_axes(self):
        """2 charts (return, speed) or 3 with the per-step score chart."""
        self.fig.clear()
        n = 3 if self._ps_wanted() else 2
        axes = [self.fig.add_subplot(n, 1, i + 1) for i in range(n)]
        self.ax1, self.ax2 = axes[0], axes[1]
        self.ax3 = axes[2] if n == 3 else None
        self.yman = [None] * n
        self.yfull = [None] * n
        if getattr(self, "_chart_short", 0) >= 2:  # very short: ONE chart, picked with the Return/Speed tabs
            show = getattr(self, "v_onechart", None)
            hide = self.ax2 if not show or show.get() == "return" else self.ax1
            hide.set_visible(False)
            gs = self.fig.add_gridspec(2, 1, height_ratios=[1, 1e-3] if hide is self.ax2 else [1e-3, 1])
            self.ax1.set_subplotspec(gs[0])
            self.ax2.set_subplotspec(gs[1])

    def _ps_wanted(self):
        """Per-step chart shown: ticked, tall enough, and (1.0.0 UX) only once there is per-step data."""
        return bool(self.v_ps.get() and not getattr(self, "_chart_short", False)
                    and getattr(self, "per_step", None) is not None)

    def _ps_hint_paint(self):
        f = getattr(self, "f_pshint", None)
        if f is None:
            return
        show = bool(self.v_ps.get() and getattr(self, "per_step", None) is None)
        if show and not f.winfo_manager():
            f.pack(side="bottom", fill="x", pady=(2, 0), before=self.canvas.get_tk_widget())
        elif not show and f.winfo_manager():
            f.pack_forget()

    def _ps_avail_changed(self):
        self._make_axes()
        self.apply_theme()
        self._auto_follow()
        self._progress_tick(force=True)

    CHART_MIN_2 = 250  # below this only one chart (Return or Speed tab)
    CHART_MIN_3 = 360  # px (at 96 dpi) the chart area needs for 3 charts; below it the per-step chart is hidden

    def _chart_resized(self, e):
        """a0.8.4: on a short window the three charts were squashed into unreadable strips - hide the per-step one."""
        try:
            k = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            k = 1.0
        short = 2 if e.height < self.CHART_MIN_2 * k else 1 if e.height < self.CHART_MIN_3 * k else 0
        if short == getattr(self, "_chart_short", 0):
            return
        self._chart_short = short
        if hasattr(self, "f_onechart"):
            if short >= 2:
                self.f_onechart.pack(side="left", padx=(10, 0))
            else:
                self.f_onechart.pack_forget()
        if hasattr(self, "cb_ps"):
            self.cb_ps.configure(text="Per-step (hidden)" if short and self.v_ps.get()
                                 else "Per-step chart")
        self._make_axes()
        self.apply_theme()
        self._auto_follow()

    def _onechart_changed(self):
        self._make_axes()
        self.apply_theme()
        self._auto_follow()

    def _ps_toggled(self):
        self.s["per_step_chart"] = bool(self.v_ps.get())
        self._save_settings_only()
        self._ps_hint_paint()
        self._make_axes()
        self.apply_theme()
        self._auto_follow()

    def _axes(self):
        return tuple(a for a in (self.ax1, self.ax2, self.ax3) if a is not None)

    @staticmethod
    def _full(ln):
        """All points of a line (the drawn ones may be culled/downsampled)."""
        f = getattr(ln, "_mk_full", None)
        if f is None:
            f = ([float(v) for v in ln.get_xdata()], [float(v) for v in ln.get_ydata()])
            ln._mk_full = f
        return f

    @staticmethod
    def _full_np(ln):
        """The full data as float numpy arrays (cached next to _mk_full)."""
        a = getattr(ln, "_mk_np", None)
        f = ChartsMixin._full(ln)
        if a is None or a[2] is not f:
            a = (np.asarray(f[0], dtype=float), np.asarray(f[1], dtype=float), f)
            ln._mk_np = a
        return a[0], a[1]

    @staticmethod
    def np_decimate(xa, ya, x0, x1, ncols):
        """minmax_decimate() in numpy (a0.8.0: chart scrolling on long runs). Binary search for the visible window,
        then per pixel column the lowest and highest point in time order (spikes stay), NaN gaps kept as breaks."""
        n = len(xa)
        if n == 0:
            return xa, ya
        if x1 < x0:
            x0, x1 = x1, x0
        lo = max(0, int(np.searchsorted(xa, x0, "left")) - 1)
        hi = min(n, int(np.searchsorted(xa, x1, "right")) + 1)
        ncols = max(1, int(ncols))
        if hi - lo <= 2 * ncols:
            return xa[lo:hi], ya[lo:hi]
        xs, ys = xa[lo:hi], ya[lo:hi]
        col = np.trunc((xs - x0) / ((x1 - x0) or 1.0) * ncols).astype(np.int64)
        nan = np.isnan(ys)
        last = np.r_[col[1:] != col[:-1], True]
        first = np.r_[True, col[1:] != col[:-1]]
        o_min = np.lexsort((np.where(nan, np.inf, ys), col))
        o_max = np.lexsort((np.where(nan, -np.inf, ys), col))
        seg_first = np.flatnonzero(first)
        seg_last = np.flatnonzero(last)
        ni = np.flatnonzero(nan)  # one break (the column's last NaN) per column, like minmax_decimate
        ni = ni[np.r_[col[ni][1:] != col[ni][:-1], True]] if len(ni) else ni
        mins, maxs = o_min[seg_first], o_max[seg_last]
        keep = np.unique(np.concatenate([mins[~nan[mins]], maxs[~nan[maxs]], ni]))
        return xs[keep], ys[keep]

    def _decimate(self):
        """One smooth polyline per series, no point markers (like the phone page): only the visible time window, about one
        min/max pair per pixel column (spikes stay). The same Line2D is reused; hover reads the full data."""
        for ax in self._axes():
            x0, x1 = ax.get_xlim()
            w = max(50, int(ax.bbox.width))
            for ln in ax.get_lines():
                if ln.get_gid() == "hover":
                    continue
                xs, ys = self._full(ln)
                xa, ya = self._full_np(ln)
                dx, dy = self.np_decimate(xa, ya, x0, x1, w)
                ln.set_data(dx, dy)
                ln.set_marker("o" if len(xs) == 1 else "None")  # a lone point needs a dot to be seen
                ln.set_markersize(4)

    def _auto_follow(self):
        """Home / double-click: full view, follow new data, vertical scale back to the full data range."""
        self.xview = None
        self.yman = [None] * len(self._axes())
        self.drag = None
        self._progress_tick(force=True)

    def _cur_toggled(self):
        self.s["current_session_only"] = bool(self.v_cur.get())
        self._save_settings_only()
        self._auto_follow()

    def _set_x(self, xl):
        self.xview = (float(xl[0]), float(xl[1]))
        for a in self._axes():
            a.set_xlim(self.xview)  # both charts always share the time axis
        self._decimate()

    def y_drag_allowed(self, ax):
        """Vertical drag only when this chart has data inside the visible time range that lies outside its y limits."""
        x0, x1 = sorted(ax.get_xlim())
        y0, y1 = sorted(ax.get_ylim())
        for ln in ax.get_lines():
            if ln.get_gid() == "hover":
                continue
            xs, ys = ChartsMixin._full(ln)
            for x, y in zip(xs, ys):
                try:
                    x, y = float(x), float(y)
                except (TypeError, ValueError):
                    continue
                if x0 <= x <= x1 and y == y and (y < y0 or y > y1):
                    return True
        return False

    SCROLL_SETTLE_MS = 150  # wheel zoom: redraw once the wheel has been still this long

    def _on_scroll(self, ev):
        """Wheel = zoom time at the cursor. a0.8.0: each tick only moves the limits (cheap); the decimate + redraw
        runs once, SCROLL_SETTLE_MS after the last tick (it used to redraw on every tick)."""
        ax = ev.inaxes
        if ax is None or ev.xdata is None:
            return
        f = 1 / 1.25 if ev.button == "up" or getattr(ev, "step", 0) > 0 else 1.25
        x0, x1 = getattr(self, "_scroll_xl", None) or ax.get_xlim()
        xl = (ev.xdata - (ev.xdata - x0) * f, ev.xdata + (x1 - ev.xdata) * f)  # x only; y untouched
        self._scroll_xl = xl
        self.xview = (float(xl[0]), float(xl[1]))
        for a in self._axes():
            a.set_xlim(self.xview)
        if getattr(self, "_scroll_after", None):
            try:
                self.root.after_cancel(self._scroll_after)
            except Exception as e:
                log_exc("chart scroll timer", e)
        self._scroll_after = self.root.after(self.SCROLL_SETTLE_MS, self._scroll_settled)

    def _scroll_settled(self):
        self._scroll_after = None
        self._scroll_xl = None
        if self.xview:
            self._set_x(self.xview)
        self.canvas.draw_idle()

    def _on_click(self, ev):
        if getattr(ev, "dblclick", False) and ev.inaxes is not None:
            self._auto_follow()
            return
        if (
            getattr(ev, "button", None) in (1, "1")
            or str(getattr(ev, "button", "")) == "MouseButton.LEFT"
        ):
            if ev.inaxes in self._axes():
                ax = ev.inaxes
                self.drag = dict(
                    ax=ax,
                    x=ev.x,
                    y=ev.y,
                    xlim=ax.get_xlim(),
                    ylim=ax.get_ylim(),
                    ydrag=self.y_drag_allowed(ax),
                )

    @staticmethod
    def _label_offset(ax, x, y, w=170, h=28):
        """Readout offset (points) and alignment: right of / above the point, flipped left / below near the chart's
        right / top edge, so the label stays inside the chart (and so the window)."""
        px, py = ax.transData.transform((x, y))
        left, down = px + w > ax.bbox.x1, py + h > ax.bbox.y1
        return (-8 if left else 8, -8 if down else 8), ("right" if left else "left"), ("top" if down else "bottom")

    def _hover(self, ev):
        """Readout of the nearest real data point (from the full data, not the downsampled drawing)."""
        ax = ev.inaxes
        old = getattr(self, "_hov", None)
        if old is not None:
            for a in old:
                try:
                    a.remove()
                except Exception as e:
                    log_exc(
                        "mimickit_launcher: _hover - already gone with an ax.clear() refresh", e
                    )
            self._hov = None
        if ax is None or ax not in self._axes() or ev.xdata is None:
            self.canvas.draw_idle()
            return None
        lines = [ln for ln in ax.get_lines() if ln.get_gid() not in ("hover", "bridge")]
        if not lines:
            return None
        (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
        sx, sy = (x1 - x0) / max(ax.bbox.width, 1), (y1 - y0) / max(ax.bbox.height, 1)
        nb = R.nearest_point([self._full(ln) for ln in lines], ev.xdata, ev.ydata, sx, sy)
        if nb is None:
            return None
        x, y, i, k = nb
        if ((x - ev.xdata) / sx) ** 2 + ((y - ev.ydata) / sy) ** 2 > 40**2:
            self.canvas.draw_idle()
            return None
        lab = lines[k].get_label()
        lab = "" if str(lab).startswith("_") else lab + ": "
        (mk,) = ax.plot(
            [x],
            [y],
            marker="o",
            markersize=8,
            markerfacecolor="none",
            markeredgecolor=T["fg"],
            gid="hover",
        )
        off, ha, va = self._label_offset(ax, x, y)
        tx = ax.annotate(
            "%s%.4g  at %.4g M" % (lab, y, x),
            (x, y),
            xytext=off,
            textcoords="offset points",
            ha=ha,
            va=va,
            fontsize=8,
            color=T["fg"],
            bbox=dict(boxstyle="round,pad=0.25", fc=T["panel"], ec=T["border"], alpha=0.95),
        )
        self._hov = (mk, tx)
        self.canvas.draw_idle()
        return (x, y)

    def _on_motion(self, ev):
        d = self.drag
        if not d:
            return self._hover(ev)
        if ev.x is None:
            return
        ax = d["ax"]
        bb = ax.bbox
        (x0, x1), (y0, y1) = d["xlim"], d["ylim"]
        dx = (ev.x - d["x"]) * (x1 - x0) / max(bb.width, 1)
        self._set_x((x0 - dx, x1 - dx))
        if d["ydrag"] and ev.y is not None:
            dy = (ev.y - d["y"]) * (y1 - y0) / max(bb.height, 1)
            i = self._axes().index(ax)
            self.yman[i] = (y0 - dy, y1 - dy)
            ax.set_ylim(self.yman[i])
        self.canvas.draw_idle()

    def _on_release(self, ev):
        self.drag = None

    def _save_chart(self):
        f = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("SVG", "*.svg"), ("PDF", "*.pdf")],
        )
        if f:
            self.fig.savefig(f, facecolor=self.fig.get_facecolor())

    @staticmethod
    def _full_range(ax, pad=0.08):
        ys = []
        for ln in ax.get_lines():
            if ln.get_gid() == "hover":
                continue
            for y in ChartsMixin._full(ln)[1]:
                try:
                    y = float(y)
                    if y == y:
                        ys.append(y)
                except (TypeError, ValueError):
                    pass
        if not ys:
            return None
        lo, hi = min(ys), max(ys)
        p = max((hi - lo) * pad, abs(hi) * 0.02, 1e-3)
        return (lo - p, hi + p)

    def _apply_view(self, cur_range=None):
        """After every redraw: shared x (user view, current session, or all data) and y (manual, else full data range)."""
        for i, ax in enumerate(self._axes()):
            self.yfull[i] = self._full_range(ax)
        if self.xview:
            xl = self.xview
        elif cur_range:
            xl = cur_range
        else:
            xs = [
                float(x)
                for ax in self._axes()
                for ln in ax.get_lines()
                if ln.get_gid() != "hover"
                for x in self._full(ln)[0]
            ]
            xl = None
            if xs:
                lo, hi = min(xs), max(xs)
                p = max((hi - lo) * 0.03, 1e-3)
                xl = (lo - p, hi + p)
        if xl:
            for ax in self._axes():
                ax.set_xlim(xl)
        for i, ax in enumerate(self._axes()):
            yl = self.yman[i] or self.yfull[i]
            if yl:
                ax.set_ylim(yl)
        self._decimate()

    def _style_ax(self, ax):
        ax.set_facecolor(T.get("plot", T["field"]))  # a0.8.9: plots stay black when fields went #0d0d0d
        ax.tick_params(colors=T["fg"], labelcolor=T["fg"])
        for sp in ax.spines.values():
            sp.set_color(T["border"])
        ax.xaxis.label.set_color(T["fg"])
        ax.yaxis.label.set_color(T["fg"])
        ax.title.set_color(T["fg"])
        ax.grid(True, color=T["grid"], alpha=0.6)
        ax.set_axisbelow(True)
        leg = ax.get_legend()
        if leg:
            leg.get_frame().set_facecolor(T["panel"])
            leg.get_frame().set_edgecolor(T["border"])
            leg.get_frame().set_alpha(0.9)
            for t in leg.get_texts():
                t.set_color(T["fg"])

    def _progress_tick(self, force=False):
        if not force:
            self._tt_save()
        try:
            self._update_progress()
        except Exception as e:
            self.l_status.configure(text="Status error: %s" % e)
        if not force:
            self.root.after(10000, self._progress_tick)

    def _update_progress(self):
        d, earlier, lines, log, running, same, src = self._progress_sources()
        ax3, bridge, est_rate, off, segs = self._draw_earlier_sessions(earlier)
        est_rate = self._draw_current_session(
            ax3, bridge, earlier, est_rate, lines, log, off, running, same, segs, src
        )
        self._finish_axes(ax3, d, earlier, lines, log, off)
        self._status_lines(d, est_rate, lines, running, segs)
        try:
            self._check_milestones(d, log, running)  # a0.9.0
        except Exception as e:
            log_exc("milestones", e)
        if getattr(self, "v_outview", None) is not None and self.v_outview.get() == "status":
            lines = [
                l for l in lines if not l.startswith(STATUS_PANEL_SHOWS)
            ]  # already in the status panel
        self.l_status.configure(text="\n".join(lines))
        if getattr(self, "l_details", None) is not None:
            self.l_details.configure(text="\n".join(lines))
        self.canvas.draw_idle()
        try:
            self._publish(lines, d, running)
        except Exception as ex:
            self.q.put("[remote] snapshot failed: %s\n" % ex)

    def _progress_sources(self):
        """Which run to show, its log rows (live console or log.txt) and the earlier sessions of its chain."""
        running = self.proc is not None and self.proc.poll() is None
        self._sync_run_buttons(running)
        d = self.run_dir or self.outdir_abs()
        lines = ["%s  -  %s" % ("RUNNING (%s)" % self.run_kind if running else "Not running", d)]
        same = bool(self.live_dir) and os.path.normcase(
            os.path.abspath(self.live_dir)
        ) == os.path.normcase(os.path.abspath(d))
        with self.live_lock:
            live = {k: list(v) for k, v in self.live.data.items()}
            nlive = self.live.rows()
        if same and nlive:
            log, src = live, "console"
        else:
            log = load_history(d)
            src = (
                HIST_FILE
                if os.path.exists(os.path.join(d, HIST_FILE))
                else CONSOLE_FILE if os.path.exists(os.path.join(d, CONSOLE_FILE)) else "log.txt"
            )
        if src == "console":
            self.hist_n = append_history(d, live, self.hist_n)
        # earlier sessions of this run chain (original + _resumeN before d), offset so total samples keep growing
        earlier = []
        try:
            chain = run_chain(
                d
            )  # follows parent links, also into other output folders ("Continue from run")
            earlier = [h for h in (load_history(c) for c in chain[:-1]) if h.get("Samples")]
        except (ValueError, OSError):
            pass
        self.prog_frame.configure(
            text="Training progress (data: %s, %d points%s; refreshed every 10 s)"
            % (
                src,
                len(log.get("Samples", [])),
                ", +%d earlier sessions" % len(earlier) if earlier else "",
            )
        )
        return d, earlier, lines, log, running, same, src

    def _draw_earlier_sessions(self, earlier):
        """Clear the charts and draw the earlier sessions (grey) offset so total samples keep growing."""
        for ax in self._axes():
            ax.clear()
            self._style_ax(ax)
        ax3 = self.ax3
        off = 0.0
        xmax = 0.0
        sparse = 0
        prev = {}  # last point of the previous session, per series
        segs = []
        est_rate = 0.0  # (cumulative samples, Train_Return) per session, for the estimate

        def bridge(ax, key, x0, y0):
            """dotted grey line from the previous session's last point to this session's first point"""
            if key in prev and x0 == x0 and y0 == y0:
                ax.plot(
                    [prev[key][0], x0],
                    [prev[key][1], y0],
                    color=T["dim"],
                    alpha=0.8,
                    linestyle=":",
                    linewidth=1.5,
                    gid="bridge",
                )

        for i, h in enumerate(earlier):
            xs = [(v + off) / 1e6 for v in h["Samples"]]
            nh = len(xs)
            if nh < 3:
                sparse += 1
            lab = "earlier sessions" if i == 0 else None
            for key in ("Train_Return", "Test_Return"):
                if h.get(key):
                    ys = h[key][:nh]
                    bridge(self.ax1, key, xs[0], ys[0])
                    self.ax1.plot(
                        xs[: len(ys)],
                        ys,
                        color=T["dim"],
                        alpha=0.7,
                        linewidth=1.5,
                        label=lab if key == "Train_Return" else None,
                        gid="earlier",
                    )
                    prev[key] = (xs[len(ys) - 1], ys[-1])
            if ax3 is not None:
                for k, ps in per_step_series(h).items():
                    ys = [v if v is not None else float("nan") for v in ps][:nh]
                    bridge(ax3, "ps" + k, xs[0], ys[0])
                    ax3.plot(
                        xs[: len(ys)],
                        ys,
                        color=T["dim"],
                        alpha=0.7,
                        linewidth=1.3,
                        gid="earlier",
                    )
                    prev["ps" + k] = (xs[len(ys) - 1], ys[-1])
            r = rate_per_hour(h)[1]
            if r:
                rv = [v / 1e6 for v in r]
                bridge(self.ax2, "rate", xs[0], rv[0])
                self.ax2.plot(
                    xs[: len(rv)],
                    rv,
                    color=T["dim"],
                    alpha=0.7,
                    linewidth=1.5,
                    gid="earlier",
                )
                prev["rate"] = (xs[len(rv) - 1], rv[-1])
            segs.append(([v + off for v in h["Samples"]], h.get("Train_Return", [])))
            est_rate = rate_per_hour(h)[0] or est_rate
            off += h["Samples"][-1]
            xmax = xs[-1]  # each session's own final sample count
        return ax3, bridge, est_rate, off, segs

    def _draw_current_session(
        self, ax3, bridge, earlier, est_rate, lines, log, off, running, same, segs, src
    ):
        """Draw the current session (and its per-step series), linked to the earlier ones by dotted bridges."""
        if log.get("Samples"):
            S = log["Samples"]
            n = len(S)
            it = int(log.get("Iteration", [n - 1])[-1])
            W = log.get("Wall_Time", [0])
            wall = W[-1] if W[-1] == W[-1] else 0
            rate, rates = rate_per_hour(log)
            lines.append(
                "Iteration %d   |   samples %s%s   |   session time %s   |   speed %.2f M samples/hour   |   from %s"
                % (
                    it,
                    f"{int(S[-1]):,}",
                    " (%s in all sessions)" % f"{int(S[-1] + off):,}" if off else "",
                    str(datetime.timedelta(seconds=int(wall * 3600))),
                    rate / 1e6,
                    src,
                )
            )
            if src == "log.txt" and not (running and same):
                lines.append(
                    "Note: reading log.txt of a run this window didn't start - MimicKit writes it rarely, so it may lag the console."
                )
            x = [(v + off) / 1e6 for v in S]
            segs.append(([v + off for v in S], log.get("Train_Return", [])))
            est_rate = rate or est_rate
            for key, lab, col, g in (
                ("Train_Return", "Train return", T["line1"], "cur1"),
                ("Test_Return", "Test return", T["line2"], "cur2"),
            ):
                if log.get(key):
                    bridge(self.ax1, key, x[0], log[key][0])
                    self.ax1.plot(
                        x[: len(log[key])],
                        log[key][:n],
                        label=lab,
                        color=col,
                        gid=g,
                    )
            if ax3 is not None:
                for k, ps in per_step_series(log).items():
                    ys = [v if v is not None else float("nan") for v in ps][:n]
                    bridge(ax3, "ps" + k, x[0], ys[0])
                    ax3.plot(
                        x[: len(ys)],
                        ys,
                        color=T["line1"] if k == "Train" else T["line2"],
                        gid="cur1" if k == "Train" else "cur2",
                        label="%s per step" % k.lower(),
                    )
            if rates:
                bridge(self.ax2, "rate", x[0], rates[0] / 1e6)
                self.ax2.plot(
                    x[: len(rates)],
                    [r / 1e6 for r in rates],
                    color=T["line3"],
                    gid="cur3",
                )
            if (
                n < 2 and not earlier
            ):  # one point: sensible x range instead of matplotlib's +-tiny default
                for ax in self._axes():
                    ax.set_xlim(0, max(x[-1] * 2, 0.1))
                self.ax1.text(
                    0.02,
                    0.95,
                    "only %d point so far - more appear as training runs" % n,
                    color=T["dim"],
                    transform=self.ax1.transAxes,
                    va="top",
                    fontsize=8,
                )
        elif not earlier:
            lines.append(
                "No training data yet (waiting for the first '| Iteration |' table or log.txt rows)."
            )
            self.ax1.text(
                0.5,
                0.5,
                "waiting for data",
                ha="center",
                color=T["dim"],
                transform=self.ax1.transAxes,
            )
            for ax in self._axes():
                ax.set_xlim(0, 1)
        else:
            lines.append("This session has no data yet; grey = earlier sessions.")
        return est_rate

    def _finish_axes(self, ax3, d, earlier, lines, log, off):
        """View limits, labels, legends and the per-step chart."""
        cur_range = None
        if self.v_cur.get() and log.get("Samples") and (earlier or len(log["Samples"]) > 1):
            cx = [(v + off) / 1e6 for v in log["Samples"]]
            lo, hi = cx[0], cx[-1]
            pad = max((hi - lo) * 0.03, 1e-3)
            cur_range = (lo - pad, hi + pad)
        if any(ax.get_lines() for ax in self._axes()):
            self._apply_view(cur_range)
        # short labels in a smaller font: 'M samples / hour' and 'Reward / step (%)' ran into each other (a0.6.1 item)
        self.ax1.set_ylabel("Return", fontsize=8)
        self.ax2.set_ylabel("M samples/h", fontsize=8)
        lines.append(self._per_step_line(log, d))
        self._ps_hint_paint()
        if self._ps_wanted() != (self.ax3 is not None):  # per-step data appeared / went away
            self.root.after_idle(self._ps_avail_changed)
        try:
            self.fig.align_ylabels(list(self._axes()))
        except Exception as e:
            log_exc("chart y-labels", e)
        if ax3 is not None:
            ax3.set_ylabel("Reward/step %", fontsize=8)
            if not ax3.get_lines():
                ax3.text(
                    0.5,
                    0.5,
                    "per-step score needs episode length - see Setup -> MimicKit patches...",
                    ha="center",
                    va="center",
                    color=T["dim"],
                    transform=ax3.transAxes,
                    fontsize=8,
                )
        if self.ax1.get_lines():
            self.ax1.legend(loc="lower right", fontsize=8)
        for ax in self._axes():
            ax.set_xlabel(
                "Samples, all sessions (M)" if ax is self._axes()[-1] else ""
            )
            self._style_ax(ax)  # after legend()

    def _status_lines(self, d, est_rate, lines, running, segs):
        """Status text: last save, session/total time, progress estimate."""
        m = os.path.join(d, "model.pt")
        if os.path.exists(m):
            age = time.time() - os.path.getmtime(m)
            lines.append(
                "model.pt last saved %s (%d min ago)"
                % (time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(m))), age // 60)
            )
        if running and self.started:
            if self.run_kind != "train":
                lines.append(
                    "Running for %s (this session, %s - not counted as training)"
                    % (hms(time.time() - self.started), self.run_kind)
                )
        tot, ses_t, ses = self._tt_total()
        self._tt_last = (tot, ses_t, ses)  # 1.0.0: the transport strip's 'Training time' between refreshes
        if ses_t is not None:
            lines.append("Running for %s (this session)" % hms(ses_t))
        lines.append(
            "Running for %s (total%s)" % (hms(tot), ", %d sessions" % ses if ses else "")
            if ses_t is not None
            else "Total training time %s (this run + its resumes%s)"
            % (hms(tot), ", %d sessions" % ses if ses else "")
        )
        self._est_last = None
        try:
            self._sync_target_widgets(d)
            if segs:
                e = estimate_progress(segs, est_rate, self._get_target(d))
                txt = e["text"]
                shown = e["pct"]
                if e["pct"] is not None and e["pct"] < 100:
                    shown = self._smooth_estimate(
                        self._chain_key(d) + str(self._get_target(d)), e["pct"]
                    )
                    txt = re.sub(r"~?\d+%", "~%d%%" % round(shown), txt, count=1)
                lines.append(txt)
                self._est_last = dict(pct=shown, text=txt, kind=e.get("kind"))  # transport strip bar + text
                self._check_looks_trained(d, e, running, tot)
        except Exception as ex:
            lines.append("Progress estimate unavailable (%s)" % ex)

    def _per_step_line(self, log, d):
        """Status line 'Avg reward per step'. Live from the console when the logging patch is in; else from log.txt."""

        def latest(h):
            vals = {}
            for k, ps in per_step_series(h).items():
                v = next((p for p in reversed(ps) if p is not None), None)
                if v is not None:
                    vals[k] = v
            return vals

        v = latest(log)
        src = ""
        if not v:
            try:
                v = latest(parse_log(os.path.join(d, "log.txt")))
                src = " (from log.txt - may lag; the logging patch makes it live)"
            except Exception:
                v = {}
        if not v:
            self.per_step = None
            return "Avg reward per step: needs the logging patch - see README (Setup -> MimicKit patches...)"
        self.per_step = v
        return "Avg reward per step: %s%s" % (
            "   ".join("%s %.1f%%" % (k.lower(), x) for k, x in v.items()),
            src,
        )
