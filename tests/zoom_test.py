"""Chart zoom/pan: toolbar, wheel zoom at the cursor, view kept across refreshes, Home/double-click back to auto-follow,
'Current session only'.   xvfb-run -a python tests/zoom_test.py"""
import os, shutil, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
os.environ.update(STUB_ITERS="100000", STUB_SLEEP="0.03")
import tkinter as tk, mimickit_launcher as G
from matplotlib.backend_bases import MouseEvent
for n in ("showinfo", "showwarning", "showerror"): setattr(G.messagebox, n, lambda *a, **k: None)
G.messagebox.askyesno = lambda *a, **k: True
mk = os.path.join(HERE, "fake_mimickit"); G.filedialog.askdirectory = lambda **k: mk
shutil.rmtree(os.path.join(mk, "output"), ignore_errors=True)
root = tk.Tk(); app = G.App(root); ok = []
def check(n, c, i=""): ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)
def wait(sec):
    t = time.time()
    while time.time() - t < sec: root.update(); time.sleep(0.05)
def px(ax, x, y): return ax.transData.transform((x, y))
def scroll(ax, x, y, up=True):
    X, Y = px(ax, x, y); ev = MouseEvent("scroll_event", app.canvas, X, Y, button="up" if up else "down", step=1 if up else -1)
    app.canvas.callbacks.process("scroll_event", ev)
def steps():
    wait(1.5); app.v_out.set("output/zoom"); base = app.outdir_abs("output/zoom")
    app.train(); wait(4); app.stop(); wait(1.5)
    app.resume(); wait(4)
    app._progress_tick(force=True); root.update()
    tb = app.toolbar; names = [getattr(w, "cget", lambda k: "")("text") if isinstance(w, (tk.Button, tk.Checkbutton)) else "" for w in tb.winfo_children()]
    check("toolbar with Home / Pan / Zoom", all(any(k in str(n) for n in names) for k in ("Home", "Pan", "Zoom")) or
          all(k in tb._buttons for k in ("Home", "Pan", "Zoom")), str(list(getattr(tb, "_buttons", {}).keys())))
    check("toolbar is dark-themed", tb.cget("bg") == G.T["bg"], tb.cget("bg"))
    auto = app.ax1.get_xlim(); xm = sum(auto) / 2; ym = sum(app.ax1.get_ylim()) / 2
    scroll(app.ax1, xm, ym); root.update(); z = app.ax1.get_xlim()
    check("wheel zooms in", (z[1] - z[0]) < 0.9 * (auto[1] - auto[0]), "%s -> %s" % (auto, z))
    check("zoom centred on the cursor", abs((z[0] + z[1]) / 2 - xm) < 0.01 * (auto[1] - auto[0]))
    check("both charts share the zoomed x range", app.ax2.get_xlim() == z)
    check("zoom flag set", app.zoomed)
    wait(2); app._progress_tick(force=True); root.update()
    check("10 s refresh keeps the zoomed view", app.ax1.get_xlim() == z and app.ax2.get_xlim() == z, str(app.ax1.get_xlim()))
    # pan/zoom-rect from the toolbar: limits changed + release in that mode
    app.ax1.set_xlim(z[0] + 0.01, z[1] + 0.01); tb.pan(); app._on_release(None); tb.pan()
    p = app.ax1.get_xlim(); app._progress_tick(force=True)
    check("toolbar pan is kept too", app.ax1.get_xlim() == p)
    tb.home(); root.update(); h = app.ax1.get_xlim()
    check("Home returns to auto-follow", not app.zoomed and h != p, "%s" % (h,))
    scroll(app.ax1, xm, ym); X, Y = px(app.ax1, xm, ym)
    app.canvas.callbacks.process("button_press_event", MouseEvent("button_press_event", app.canvas, X, Y, button=1, dblclick=True))
    check("double-click returns to auto-follow", not app.zoomed)
    # current session only
    wait(2); app._progress_tick(force=True); full = app.ax1.get_xlim()
    app.v_cur.set(True); app._cur_toggled(); cur = app.ax1.get_xlim()
    first = (app.live.data["Samples"][0] + G.load_history(base)["Samples"][-1]) / 1e6
    check("current session only: x starts at this session", cur[0] > full[0] and cur[0] > first - 0.05 * (cur[1] - cur[0]) and cur[0] < first,
          "full %s, current %s, session starts %.3f" % (full, cur, first))
    check("setting saved", G.load_settings().get("current_session_only") is True)
    scroll(app.ax1, sum(cur) / 2, sum(app.ax1.get_ylim()) / 2); zz = app.ax1.get_xlim(); app._progress_tick(force=True)
    check("zoom inside current-session view is kept", app.ax1.get_xlim() == zz)
    app.v_cur.set(False); app._cur_toggled(); check("unticking shows all sessions again", app.ax1.get_xlim()[0] <= full[0] + 1e-9 and not app.zoomed)
    app.stop(); wait(1)
def safe():
    try: steps()
    except Exception:
        import traceback; traceback.print_exc(); ok.append(False)
    print("RESULT: %d/%d" % (sum(ok), len(ok))); root.destroy()
root.after(100, safe); root.mainloop()
