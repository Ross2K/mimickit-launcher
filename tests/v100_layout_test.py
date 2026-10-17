"""1.0.0: Mockup D layout - four bottom page tabs (the only navigation, Ctrl+1..4), the persistent transport strip
(idle vs training state) and the control inventory: every pre-1.0 control is still reachable on its page.
   xvfb-run -a -s '-screen 0 1920x1080x24' python tests/v100_layout_test.py"""

import result_exit  # noqa: F401
import os, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import tkinter as tk, mimickit_launcher as G
from mkl import layout
from mkl.core import Tip

G.messagebox.askyesno = lambda *a, **k: True
for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, **k: None)
mk = os.path.join(tempfile.mkdtemp(), "mk")
G.filedialog.askdirectory = lambda **k: mk
shutil.copytree(os.path.join(HERE, "fake_mimickit"), mk, ignore=shutil.ignore_patterns("output"))
ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


root = tk.Tk()
root.geometry("1600x900+0+0")
app = G.App(root)


def wait(sec, until=None):
    t0 = time.time()
    while time.time() - t0 < sec:
        root.update()
        if until and until():
            return True
        time.sleep(0.03)
    return bool(until and until())


wait(1.5)
app.v_mk.set(mk)
app.rescan()
wait(0.5)

# --- pages ---
check("four pages, in order", list(layout.PAGES) == ["setup", "train", "preview", "results"], layout.PAGES)
check("starts on Train", app.v_page.get() == "train" and app.pages["train"].winfo_ismapped())
for name in layout.PAGES:
    app.show_page(name)
    wait(0.2)
    shown = [p for p in layout.PAGES if app.pages[p].winfo_ismapped()]
    check("show_page(%s) -> only that page shown" % name, shown == [name], shown)
for i, name in enumerate(layout.PAGES, 1):
    app.show_page("train" if name != "train" else "setup")
    wait(0.1)
    root.focus_force()
    wait(0.1)
    root.event_generate("<Control-Key-%d>" % i)
    wait(0.2)
    check("Ctrl+%d -> %s" % (i, name), app.v_page.get() == name, app.v_page.get())
for name, (frame, bar, lab) in app.tabs.items():
    app.show_page("setup")
    wait(0.05)
    lab.event_generate("<Button-1>", x=2, y=2)
    wait(0.15)
    check("clicking the %s tab opens it" % name, app.v_page.get() == name, app.v_page.get())
check("tabs have hover help", all(str(lab) in Tip._by_widget or str(frame) in Tip._by_widget
                                  for frame, bar, lab in app.tabs.values()))
app.show_page("results")
wait(0.2)
check("Results page = the full console view", app.v_outview.get() == "console" and app.con_panel.winfo_ismapped()
      and app.t_cmd.winfo_ismapped())
app.show_page("train")
wait(0.2)
check("Train page = 'What's happening' view", app.v_outview.get() == "status" and app.st_panel.winfo_ismapped())

# --- transport strip, every page ---
for name in layout.PAGES:
    app.show_page(name)
    wait(0.15)
    check("transport strip + tab bar visible on %s" % name, app._transport.winfo_ismapped()
          and all(app.run_btns[k].winfo_ismapped() for k in ("train", "resume", "stopsave", "stop"))
          and app.tp_bar.winfo_ismapped() and app.c_vram.winfo_ismapped())
app.show_page("train")
app._sync_run_buttons(False)
wait(0.3)
idle = {k: not app.run_btns[k].instate(["disabled"]) for k in ("train", "resume", "stopsave", "stop")}
check("idle: Start + Resume live, Stop / Stop after next save greyed",
      idle["train"] and not idle["stopsave"] and not idle["stop"], idle)
check("idle: plateau bar says no data", "Plateau" in app.l_eta.cget("text"), app.l_eta.cget("text"))
logp = os.path.join(tempfile.mkdtemp(), "console.txt")
app.proc = app._spawn_detached([sys.executable, "-c", "import time; time.sleep(60)"], logp, dict(os.environ))
app.run_kind = "train"
app._sync_run_buttons(True)
wait(0.5)
busy = {k: not app.run_btns[k].instate(["disabled"]) for k in ("train", "resume", "stopsave", "stop")}
check("training: Stop + Stop after next save live, Start + Resume greyed",
      busy["stop"] and busy["stopsave"] and not busy["train"] and not busy["resume"], busy)
check("training: Continue from run... (Resume menu) greyed", app.run_btns["continue"].instate(["disabled"]))
check("training: Continue from selected run greyed", app.b_continue_sel.instate(["disabled"]))
app.proc.kill()
app.proc.wait()
app.proc = None
app._sync_run_buttons(False)
wait(0.3)
check("back to idle: Start live again", not app.run_btns["train"].instate(["disabled"]))
check("Resume menu has Continue from run...", any("Continue from run" in str(app._resume_menu.entrycget(i, "label"))
                                                 for i in range(app._resume_menu.index("end") + 1)
                                                 if app._resume_menu.type(i) == "command"))

# --- control inventory ---
names = [c[0] for c in layout.CONTROL_MAP]
check("control map is non-trivial and unique", len(names) >= 60 and len(set(names)) == len(names), len(names))
missing, hidden, notips = [], [], []
CONDITIONAL = ("l_update",)
for old, path, page, had_tip in layout.CONTROL_MAP:
    w = layout.resolve(app, path)
    if w is None:
        missing.append(old)
        continue
    if path in CONDITIONAL:  # only shown when there is something to say (as before 1.0.0)
        check("%s lives in the %s" % (old, page), str(w).startswith(str(app._tab_right if page == "tabbar"
                                                                        else app._transport)))
        continue
    pages = layout.PAGES if page in ("transport", "tabbar") else (page,)
    for p in pages:
        app.show_page(p)
        if p == "train" and getattr(app, "v_adv", None) is not None and not app.v_adv.get():
            app._toggle_advanced()
        wait(0.05)
        ww = w.anchor if isinstance(w, layout.MenuItem) else w
        try:
            seen = ww.winfo_ismapped()
            x, y = ww.winfo_rootx() - root.winfo_rootx(), ww.winfo_rooty() - root.winfo_rooty()
            inside = -2 <= x < root.winfo_width() and -2 <= y < root.winfo_height()
        except tk.TclError:
            seen = inside = False
        if not (seen and inside):
            # a scrolled column counts as reachable when the widget lives in it
            sc = str(getattr(app, "_top_inner", "")), str(getattr(app, "preview_box", ""))
            if not (seen or any(s and str(ww).startswith(s) for s in sc)):
                hidden.append("%s@%s" % (old, p))
    if had_tip:
        ww = w.anchor if isinstance(w, layout.MenuItem) else w
        cands = [str(ww), str(ww.master)] + ([str(c) for c in ww.master.winfo_children()] if path.startswith("tiles") else [])
        if isinstance(w, layout.MenuItem):
            cands.append(str(w.anchor))
        if not any(c in Tip._by_widget for c in cands):
            notips.append(old)
check("every old control still exists", not missing, missing)
check("every old control is shown on its page (transport/tab bar: on every page)", not hidden, hidden)
check("every control that had hover help still has it", not notips, notips)
check("Ctrl+1..4 named in the hint", "Ctrl+1..4" in app.ban_hint.cget("text"))
print("RESULT: %d/%d" % (sum(ok), len(ok)))
