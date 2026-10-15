"""Chart navigation without modes (left-drag pans time on both charts, wheel zooms time only, y fixed to the full data
range with manual y drag only when data lies outside it, Home/double-click reset, view kept across refreshes,
'Current session only'), live light/dark switching of the charts (+ screenshots), and single-instance tooltips.
  xvfb-run -a python tests/nav_test.py [--shots DIR]"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.03")
import tkinter as tk, mimickit_launcher as G
from matplotlib.backend_bases import MouseEvent
from matplotlib.colors import to_hex

SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else ""
for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
G.messagebox.askyesno = lambda *a, **k: True
mk = os.path.join(HERE, "fake_mimickit")
G.filedialog.askdirectory = lambda **k: mk
shutil.rmtree(os.path.join(mk, "output"), ignore_errors=True)
root = tk.Tk()
root.geometry("1280x880")
app = G.App(root)
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)


def wait(sec):
    t = time.time()
    while time.time() - t < sec:
        root.update()
        time.sleep(0.05)


def px(ax, x, y):
    return ax.transData.transform((x, y))


def ev(kind, ax, x, y, **k):
    X, Y = px(ax, x, y)
    e = MouseEvent(kind, app.canvas, X, Y, **k)
    app.canvas.callbacks.process(kind, e)


def drag(ax, x, y, dxpx, dypx):
    X, Y = px(ax, x, y)
    for kind, xx, yy in (
        ("button_press_event", X, Y),
        ("motion_notify_event", X + dxpx, Y + dypx),
        ("button_release_event", X + dxpx, Y + dypx),
    ):
        e = MouseEvent(kind, app.canvas, xx, yy, button=1)
        app.canvas.callbacks.process(kind, e)
    root.update()


def mid(ax):
    return sum(ax.get_xlim()) / 2, sum(ax.get_ylim()) / 2


def steps():
    wait(1.5)
    app.v_out.set("output/nav")
    base = app.outdir_abs("output/nav")
    app.train()
    wait(4)
    app.stop()
    wait(1.5)
    app.resume()
    wait(4)
    app._progress_tick(force=True)
    root.update()
    a1, a2 = app.ax1, app.ax2
    check(
        "no matplotlib mode toolbar; Home + Save buttons",
        not hasattr(app, "toolbar") and app.b_home.winfo_exists() and app.b_save.winfo_exists(),
    )
    full1, full2 = app._full_range(a1), app._full_range(a2)
    check(
        "y fixed at each chart's full data range (with margin)",
        a1.get_ylim() == full1 and a2.get_ylim() == full2,
        "%s %s" % (a1.get_ylim(), full1),
    )
    x0 = a1.get_xlim()
    y0 = a1.get_ylim()
    xm, ym = mid(a1)
    ev("scroll_event", a1, xm, ym, button="up", step=1)
    root.update()
    z = a1.get_xlim()
    check(
        "wheel zooms x in, centred on the cursor",
        (z[1] - z[0]) < 0.9 * (x0[1] - x0[0]) and abs(sum(z) / 2 - xm) < 0.01 * (x0[1] - x0[0]),
    )
    check("wheel leaves y alone (both charts)", a1.get_ylim() == y0 and a2.get_ylim() == full2)
    check(
        "wheel on the lower chart zooms both",
        (ev("scroll_event", a2, *mid(a2), button="up", step=1), a1.get_xlim() == a2.get_xlim())[1],
    )
    z = a1.get_xlim()
    check(
        "y drag locked: all visible data is inside the y range",
        not app.y_drag_allowed(a1) and not app.y_drag_allowed(a2),
    )
    drag(a1, *mid(a1), 80, 60)
    p = a1.get_xlim()
    w = a1.bbox.width
    check(
        "left-drag pans time (x) of both charts",
        abs((z[0] - p[0]) - 80 * (z[1] - z[0]) / w) < 1e-9 and a2.get_xlim() == p,
        "%s -> %s" % (z, p),
    )
    check("vertical drag ignored while locked", a1.get_ylim() == y0)
    drag(a2, *mid(a2), -40, 0)
    check("drag on the lower chart moves the upper one too", a1.get_xlim() == a2.get_xlim() != p)
    # unlock: narrow the y range so visible data lies outside -> drag moves y as well, for that chart only
    lo, hi = y0
    a1.set_ylim(lo + 0.4 * (hi - lo), hi - 0.4 * (hi - lo))
    check(
        "y drag unlocks when visible data is outside the y limits",
        app.y_drag_allowed(a1) and not app.y_drag_allowed(a2),
    )
    yb = a1.get_ylim()
    y2b = a2.get_ylim()
    drag(a1, *mid(a1), 0, 50)
    ya = a1.get_ylim()
    check(
        "unlocked vertical drag moves y of that chart only",
        abs((yb[0] - ya[0]) - 50 * (yb[1] - yb[0]) / a1.bbox.height)
        < 0.02 * 50 * (yb[1] - yb[0]) / a1.bbox.height
        and a2.get_ylim() == y2b,
        "%s -> %s (expected shift %.4f)" % (yb, ya, 50 * (yb[1] - yb[0]) / a1.bbox.height),
    )
    xv = a1.get_xlim()
    wait(1.5)
    app._progress_tick(force=True)
    root.update()
    check(
        "view (x + manual y) kept across the 10 s refresh",
        a1.get_xlim() == xv == a2.get_xlim() and a1.get_ylim() == ya,
        "%s %s" % (a1.get_xlim(), xv),
    )
    app.b_home.invoke()
    root.update()
    check(
        "Home: full view, auto-follow, y back to full range",
        app.xview is None
        and all(v is None for v in app.yman)
        and a1.get_ylim() == app._full_range(a1)
        and a1.get_xlim()[1] >= x0[1] - 1e-9,
    )
    ev("scroll_event", a1, *mid(a1), button="up", step=1)
    ev("button_press_event", a1, *mid(a1), button=1, dblclick=True)
    root.update()
    check("double-click resets too", app.xview is None and a1.get_xlim() == a2.get_xlim())
    wait(1)
    app._progress_tick(force=True)
    full = a1.get_xlim()
    app.v_cur.set(True)
    app._cur_toggled()
    cur = a1.get_xlim()
    first = (app.live.data["Samples"][0] + G.load_history(base)["Samples"][-1]) / 1e6
    check(
        "current session only: x starts at this session, both charts",
        cur[0] > full[0] and cur[0] < first and a2.get_xlim() == cur,
        "%s %s %.3f" % (full, cur, first),
    )
    check("current session only keeps y at the full range", a1.get_ylim() == app._full_range(a1))
    ev("scroll_event", a1, *mid(a1), button="up", step=1)
    zz = a1.get_xlim()
    app._progress_tick(force=True)
    check("zoom inside current-session view is kept", a1.get_xlim() == zz)
    app.v_cur.set(False)
    app._cur_toggled()
    app.stop()
    wait(1)
    app._progress_tick(force=True)
    root.update()

    # ---- themes
    def theme_ok(name):
        T = G.THEMES[name]
        bad = []
        if to_hex(app.fig.get_facecolor()) != to_hex(T["panel"]):
            bad.append("figure bg")
        for ax in (a1, a2):
            if to_hex(ax.get_facecolor()) != to_hex(T["field"]):
                bad.append("axes bg")
            if any(
                to_hex(t.get_color()) != to_hex(T["fg"])
                for t in ax.get_xticklabels() + ax.get_yticklabels()
            ):
                bad.append("tick labels")
            if to_hex(ax.xaxis.label.get_color()) != to_hex(T["fg"]) or to_hex(
                ax.yaxis.label.get_color()
            ) != to_hex(T["fg"]):
                bad.append("axis labels")
            if any(to_hex(g.get_color()) != to_hex(T["grid"]) for g in ax.get_xgridlines()):
                bad.append("grid")
            for ln in ax.get_lines():
                want = {
                    "cur1": T["line1"],
                    "cur2": T["line2"],
                    "cur3": T["line3"],
                    "earlier": T["dim"],
                    "bridge": T["dim"],
                }.get(ln.get_gid())
                if want and to_hex(ln.get_color()) != to_hex(want):
                    bad.append("line %s" % ln.get_gid())
        leg = a1.get_legend()
        if not leg or to_hex(leg.get_frame().get_facecolor()) != to_hex(T["panel"]):
            bad.append("legend bg")
        if leg and any(to_hex(t.get_color()) != to_hex(T["fg"]) for t in leg.get_texts()):
            bad.append("legend text")
        st = G.ttk.Style(root)
        if st.lookup("TButton", "background") != T["btn"]:
            bad.append("buttons")
        return sorted(set(bad))

    roles = {ln.get_gid() for ln in a1.get_lines() + a2.get_lines()}
    check(
        "chart has earlier sessions, bridges and current lines",
        {"earlier", "bridge", "cur1", "cur3"} <= roles,
        str(roles),
    )
    app.v_light.set(False)
    app._toggle_theme()
    root.update()
    check("dark theme: every chart element styled", theme_ok("dark") == [], str(theme_ok("dark")))
    if SHOTS:
        app.fig.savefig(os.path.join(SHOTS, "chart_dark.png"), facecolor=app.fig.get_facecolor())
    app.v_light.set(True)
    app._toggle_theme()
    root.update()
    check(
        "light theme live switch: every chart element styled",
        theme_ok("light") == [],
        str(theme_ok("light")),
    )
    if SHOTS:
        app.fig.savefig(os.path.join(SHOTS, "chart_light.png"), facecolor=app.fig.get_facecolor())
    app.apply_theme()
    check("restyle without a data redraw also recolours lines", theme_ok("light") == [])
    app.v_light.set(False)
    app._toggle_theme()
    root.update()
    # ---- tooltips
    w = app.cb_target
    t1 = G.Tip(w, "a")
    t2 = G.Tip(w, "b")
    check("one Tip per widget (re-creating only updates the text)", t1 is t2 and t1.text == "b")
    for _ in range(4):
        w.event_generate("<Motion>", warp=True, x=5, y=5)
        w.event_generate("<Enter>")
        wait(0.5)
        app._progress_tick(force=True)
        root.update()
    check(
        "hovering + refreshes: a single tooltip window",
        G.Tip.open_count(root) == 1,
        str(G.Tip.open_count(root)),
    )
    w2 = app.b_home
    w2.event_generate("<Motion>", warp=True, x=5, y=5)
    w2.event_generate("<Enter>")
    wait(0.6)
    check("another widget's tooltip replaces it (never two)", G.Tip.open_count(root) == 1)
    w2.event_generate("<Leave>")
    root.update()
    check("leave destroys it", G.Tip.open_count(root) == 0)
    w.event_generate("<Enter>")
    w.event_generate("<Leave>")
    wait(0.6)
    check("quick pass over a widget shows nothing", G.Tip.open_count(root) == 0)
    n_binds = len(w.bind("<Enter>").strip().splitlines())
    for _ in range(3):
        G.Tip(w, "again")
    check(
        "re-creating does not stack bindings",
        len(w.bind("<Enter>").strip().splitlines()) == n_binds,
    )


def safe():
    try:
        steps()
    except Exception:
        import traceback

        traceback.print_exc()
        ok.append(False)
    print("RESULT: %d/%d" % (sum(ok), len(ok)))
    root.destroy()


root.after(100, safe)
root.mainloop()
