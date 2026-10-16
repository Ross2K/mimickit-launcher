"""Every pop-up is centred over the main window and fully on screen, every tooltip stays inside the window, with
the main window in each screen corner (regression: close dialog not centred, chart hint clipped bottom-left).
xvfb-run -a -s "-screen 0 1280x1024x24" python tests/placement_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
CFG = os.path.join(tempfile.mkdtemp(), "s.json")  # own settings (no first-run prompt, nothing left by other tests)
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = CFG
open(CFG, "w").write('{"mimickit": %s}' % __import__("json").dumps(os.path.join(HERE, "fake_mimickit")))
import tkinter as tk, mimickit_launcher as G
from mkl import dialogs as D

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


G.filedialog.askdirectory = lambda **k: os.path.join(HERE, "fake_mimickit")
G.App._gpu_poll_thread = lambda self: None
root = tk.Tk()
app = G.App(root)
root.update()
SW, SH = root.winfo_screenwidth(), root.winfo_screenheight()
W, H = 900, 640
check("unit: clamp keeps a box inside the area", D.clamp(1300, 950, 200, 100, (0, 0, 1400, 1000)) == (1200, 900))


def rect(w):
    w.update_idletasks()
    return w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height()


def on_screen(r):
    x, y, w, h = r
    return x >= 0 and y >= 0 and x + w <= SW and y + h <= SH


def inside(r, o):
    return r[0] >= o[0] and r[1] >= o[1] and r[0] + r[2] <= o[0] + o[2] and r[1] + r[3] <= o[1] + o[3]


def centred(r, o, tol=3):
    return abs(r[0] + r[2] / 2 - (o[0] + o[2] / 2)) <= tol and abs(r[1] + r[3] / 2 - (o[1] + o[3] / 2)) <= tol


def blocking(open_fn, name, corner):
    """Open a modal pop-up (wait_window inside), measure it from a timer, then close it."""
    got = {}

    def probe():
        tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.winfo_viewable()
                and not getattr(w, "_mk_tip", False)]
        if not tops:
            return root.after(30, probe)
        t = tops[-1]
        root.update()
        got["r"] = rect(t)
        t.destroy()

    root.after(50, probe)
    open_fn()
    return got.get("r")


def nonblocking(open_fn):
    t = open_fn()
    root.update()
    root.update()
    r = rect(t)
    t.destroy()
    return r


TIP_WIDGETS = [("chart '?' badge", lambda: app.chart_help), ("Home button", lambda: app.b_home)]
corners = {"top-left": (0, 0), "top-right": (SW - W, 0), "bottom-left": (0, SH - H), "bottom-right": (SW - W, SH - H)}
for corner, (cx, cy) in corners.items():
    root.geometry("%dx%d+%d+%d" % (W, H, cx, cy))
    root.update()
    main = rect(root)
    pops = {
        "close dialog (choose)": lambda: blocking(
            lambda: app.choose("Training is still running", "x", [("Detach", "detach", "a"), ("Cancel", None, "b")]),
            "close", corner),
        "message box": lambda: blocking(lambda: G.messagebox.showinfo("Info", "hello"), "msg", corner),
        "training settings": lambda: nonblocking(lambda: (app.train_settings_dialog(), app._tsdlg)[1]),
        "about": lambda: nonblocking(app.about_dialog),
        "patches": lambda: nonblocking(lambda: (app.patch_dialog(), app._pdlg)[1]),
        "phone dashboard": lambda: nonblocking(lambda: (app.remote_dialog(), app._rdlg)[1]),
    }
    for name, fn in pops.items():
        r = fn()
        check("%s, window %s: on screen" % (name, corner), r and on_screen(r), (r, main))
        if r and r[2] <= W and r[3] <= H:
            check("%s, window %s: centred over the window" % (name, corner), centred(r, main), (r, main))
    for name, wf in TIP_WIDGETS:
        tip = G.Tip(wf(), "help " * 60)
        r = None
        for _ in range(5):  # a pointer <Leave> from a pop-up that just closed can hide the tip mid-update: re-show
            tip.show()
            root.update()
            if tip.top is not None:
                r = rect(tip.top)
                break
        tip.hide()
        check("tooltip %s, window %s: inside the window" % (name, corner), inside(r, main), (r, main))
badge = rect(app.chart_help)
canvas = rect(app.canvas.get_tk_widget())
check("'?' badge sits in the chart panel's title row, whole (not clipped), above the chart (a0.8.0)",
      badge[1] + badge[3] <= canvas[1] + 2 and badge[1] > canvas[1] - 60 and badge[2] >= 12, (badge, canvas))
check("no always-on tooltip on the chart itself", str(app.canvas.get_tk_widget()) not in G.Tip._by_widget)
# chart hover label flips left / below near the right / top edge
root.geometry("1280x880+0+0")
root.update()
app.canvas.draw()
ax = app.ax1
x1, y1 = ax.get_xlim()[1], ax.get_ylim()[1]
off, ha, va = app._label_offset(ax, x1, y1)
check("hover label flips left + below at the top-right corner", off[0] < 0 and off[1] < 0 and ha == "right" and va == "top")
off, ha, va = app._label_offset(ax, ax.get_xlim()[0], ax.get_ylim()[0])
check("hover label right + above elsewhere", off[0] > 0 and off[1] > 0)
root.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
