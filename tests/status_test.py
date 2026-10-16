"""a0.5.0 status panel: console -> status model, health banner, error cards (+ their one fix), "looks trained"
prompt, Status/Console toggle, dark message boxes.
  xvfb-run -a python tests/status_test.py"""

import result_exit  # noqa: F401 - non-zero exit on any FAIL / incomplete RESULT
import os, re, shutil, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp()
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(TMP, "settings.json")
from mkl import status_model as SM

ok = []


def check(n, c, i=""):
    ok.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + ("  - " + str(i) if i else ""), flush=True)


REAL = open(os.path.join(HERE, "data", "console_cpu_run.txt"), encoding="utf-8").read()
OOM = (
    'Traceback (most recent call last):\n  File "mimickit/run.py", line 160, in <module>\n'
    "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB.\n"
)
YAML = (
    "Traceback (most recent call last):\nyaml.scanner.ScannerError: mapping values are not allowed here\n"
    '  in "data/envs/my_env.yaml", line 7, column 15\n'
)

# ---------------------------------------------------------------- model on a real console capture
m = SM.StatusModel(ipo=3)
t0 = time.time()
m.feed(REAL, now=t0)
ev = [e for _, e in m.events]
check(
    "stage and iteration from the console",
    m.stage == "training" and m.iteration == 12,
    (m.stage, m.iteration),
)
check(
    "plain events: clips, policy, training, first iteration",
    any(e.startswith("Loaded 2 motion clip") for e in ev)
    and any(e.startswith("Policy built") for e in ev)
    and any(e.startswith("Training started") for e in ev)
    and "First training iteration done." in ev,
    ev,
)
check(
    "saves every iters_per_output (MimicKit saves at iteration % ipo == 0)",
    [e for e in ev if e.startswith("Model saved")]
    == ["Model saved (iteration %d)." % i for i in (0, 3, 6, 9, 12)],
    ev,
)
check(
    "known harmless warnings filtered (jit deprecation, no CUDA driver)",
    m.warnings == [],
    m.warnings,
)
check(
    "no false errors on a healthy run", m.errors == [] and SM.diagnose_text(m.text) == [], m.errors
)
tl = m.tiles()
check(
    "score + rate tiles",
    tl["score"][0] is not None and tl["score"][1] is not None and tl["rate"] > 0,
    tl,
)
check("next save / last save", m.next_save() == (0, 3) and m.last_save_iteration() == 12)
m.feed("[gui] process ended (exit code 0)\n")
check("exit marker -> finished", m.exit_code == 0 and m.ended_text() == "Finished.")
m2 = SM.StatusModel(ipo=None)
m2.feed(REAL)
check(
    "no ipo known: no fake save events",
    not [e for _, e in m2.events if e.startswith("Model saved")],
)

w = SM.StatusModel()
w.feed(
    "/x/y.py:12: UserWarning: array is not writable\n/x/y.py:12: UserWarning: array is not writable\n"
    "WARNING: low disk\nRuntimeError: boom\n"
)
check(
    "warnings (incl. UserWarning) counted and de-duplicated",
    [(l, c) for _, l, c in w.warnings]
    == [("/x/y.py:12: UserWarning: array is not writable", 2), ("WARNING: low disk", 1)],
    w.warnings,
)
check("errors highlighted", len(w.errors) == 1 and "RuntimeError" in w.errors[0][1])


# ---------------------------------------------------------------- health banner
def H(model, running=True, **kw):
    return SM.health(model, running, now=kw.pop("now", time.time()), **kw)


b = SM.StatusModel(ipo=3)
check("idle", H(b, False) == SM.BANNER["idle"])
b.feed("Setting seed: 1\nBuilding deepmimic env\n")
check("starting", H(b)[0] == "info" and H(b)[1] == "Starting: building the simulation.", H(b))
b = SM.StatusModel(ipo=3)
b.feed(REAL)
lv, tx = H(b)
check(
    "healthy (with rate)",
    lv == "ok" and tx.startswith("Training normally - iteration 12,") and "samples/hour" in tx,
    tx,
)
check(
    "quiet after 5 min without output",
    H(b, now=b.last_output + 301)[0] == "warn"
    and "No new output for 5 min" in H(b, now=b.last_output + 301)[1],
)
check("not quiet before", H(b, now=b.last_output + 200)[0] == "ok")
b.rates = [40e6] * 14 + [10e6] * 9
check("slow", H(b)[0] == "warn" and "25% of its usual speed" in H(b)[1], H(b))
b.rates = [40e6] * 20
check("looks trained", H(b, looks_trained=True) == SM.BANNER["trained"])
b.feed("[gui] process ended (exit code 0)\n")
check(
    "finished",
    H(b, False) == ("ok", "Finished - the last model was saved at iteration 12."),
    H(b, False),
)
b.exit_code, b.stopped_by_user = None, True
check("stopped by user", H(b, False) == SM.BANNER["stopped"])
b.stopped_by_user = False
b.feed("[gui] process ended (exit code 3)\n")
check("crashed (unknown)", H(b, False) == ("error", SM.BANNER["crashed"][1].format(code=3)))
b.feed(OOM)
check("known error -> points at the card", H(b, False) == SM.BANNER["error"])
wv = SM.StatusModel()
wv.reset(kind="watch")
check("watch running", H(wv) == ("info", "Watch is running."))
wv.feed("[gui] process ended (exit code 0)\n")
check("watch closed: no 'model saved' claim", "saved" not in H(wv, False)[1], H(wv, False))
check("watch closed text", H(wv, False) == ("idle", "Watch closed."))
wv.feed("FileNotFoundError: [Errno 2] No such file or directory: 'output/r/model.pt'\n")
check(
    "watch failed: not called training",
    H(wv, False) == ("error", "Watch stopped with an error - see the card below."),
    H(wv, False),
)
m3 = SM.StatusModel(ipo=None)
m3.feed("Setting seed: 1\n[gui] process ended (exit code 0)\n")
check(
    "finished with nothing known: no 'None'",
    H(m3, False) == SM.BANNER["finished_noit"],
    H(m3, False),
)
for k, (lvl, txt) in SM.BANNER.items():
    check(
        "banner '%s' fits one line" % k,
        len(txt) <= 110 and lvl in ("idle", "info", "ok", "warn", "error"),
        len(txt),
    )

# ---------------------------------------------------------------- diagnosis + cards
check("CUDA OOM recognised", SM.diagnose_text(OOM) == ["cuda_oom"])
check(
    "Warp OOM recognised",
    SM.diagnose_text("Warp CUDA error 2: out of memory (in function x)") == ["cuda_oom"],
)
check(
    "bad yaml recognised + located",
    SM.diagnose_text(YAML) == ["bad_yaml"]
    and SM.yaml_problem(YAML)
    == ("data/envs/my_env.yaml", 7, "mapping values are not allowed here"),
    SM.yaml_problem(YAML),
)
check(
    "missing model recognised",
    SM.diagnose_text("FileNotFoundError: [Errno 2] No such file or directory: 'output/r/model.pt'")
    == ["no_model"],
)
check(
    "MimicKit not found (Windows, doubled backslashes)",
    SM.diagnose_text(
        r"python: can't open file 'C:\\MK\\mimickit\\run.py': [Errno 2] No such file or directory"
    )
    == ["mk_missing"],
)
check(
    "MimicKit not found (Linux)",
    SM.diagnose_text("python3: can't open file '/x/mimickit/run.py': [Errno 2]") == ["mk_missing"],
)
check(
    "CPU access violation codes",
    all(
        SM._ACCESS.search(s)
        for s in ("exit code 3221225477", "exit code -1073741819", "0xC0000005")
    ),
)
check(
    "halve_envs", (SM.halve_envs(4096), SM.halve_envs(1000), SM.halve_envs(100)) == (2048, 448, 64)
)
for cid in SM.CARDS:
    for ctx in (
        {},
        dict(
            n=2048, folder="output/run", ipo=3, file="a.yaml", line=4, problem="bad", running=True
        ),
    ):
        c = SM.card(cid, **ctx)
        txt = " ".join(str(c[k]) for k in ("title", "what", "safe", "fix_label"))
        check(
            "card %s filled (%s)" % (cid, "ctx" if ctx else "no ctx"),
            "{" not in txt and "None" not in txt and c["fix"],
            txt,
        )
check(
    "OOM card says training is still running when it is",
    SM.card("cuda_oom", running=True)["safe"] == SM.CARDS["cuda_oom"]["safe_running"],
)

# ---------------------------------------------------------------- GUI
import tkinter as tk
import mimickit_launcher as G
import mkl.status as S

calls = []
for n in ("showinfo", "showwarning", "showerror"):
    setattr(G.messagebox, n, lambda *a, n=n, **k: calls.append(n))
G.messagebox.askyesno = lambda *a, **k: True
mk = os.path.join(TMP, "fake")
shutil.copytree(os.path.join(HERE, "fake_mimickit"), mk, ignore=shutil.ignore_patterns("output"))
G.filedialog.askdirectory = lambda **k: mk
G.App._progress_tick = lambda self, force=False: None
root = tk.Tk()
root.geometry("1600x1000+0+0")
app = G.App(root)
app.v_mk.set(mk)
app._save()
app.rescan()
root.update()


class P:
    pid = 1
    rc = None

    def poll(self):
        return self.rc


def run(kind="train", ipo=3):
    app.proc = P()
    app.run_kind, app.started = kind, time.time()
    app._status_reset(kind)
    app.sm.ipo = ipo


def tick():
    app._status_drain()
    app._status_refresh()
    root.update()


check("dark message boxes by default", type(G.messagebox).__name__ == "DarkMessageBox")
check(
    "status view is the default, console one click away",
    app.v_outview.get() == "status"
    and app.st_panel.winfo_manager()
    and not app.con_panel.winfo_manager(),
)
app._set_outview("console")
root.update()
check(
    "toggle -> raw console (+ command box) shown, saved",
    app.con_panel.winfo_manager()
    and not app.st_panel.winfo_manager()
    and app.s["output_view"] == "console"
    and app.t_cmd.winfo_ismapped(),
)
app._set_outview("status")
run()
app.sm_q.put(REAL)
tick()
check(
    "banner from the console",
    app.ban_lab.cget("text").startswith("Training normally - iteration 12"),
    app.ban_lab.cget("text"),
)
check(
    "stage / iteration / next save painted",
    app.st_stage.cget("text") == "Training"
    and app.st_iter.cget("text") == "Iteration 12"
    and app.st_save_l.cget("text") == "0 / 3 iterations",
)
check("score tile painted", app.tiles["score"][2].cget("text") not in ("", "-"))
check("plain-language box filled", "Model saved (iteration 12)." in app.st_events.get("1.0", "end"))

# CUDA OOM -> card -> one fix
app.v_envs.set(4096)
app.sm_q.put(OOM)
tick()
check(
    "OOM card shown while running (running wording)",
    "cuda_oom" in app.cards
    and app.card_texts["cuda_oom"]["safe"] == SM.CARDS["cuda_oom"]["safe_running"],
)
app.proc.rc = 1
app.sm_q.put("[gui] process ended (exit code 1)\n")
tick()
check(
    "after exit: stopped wording + error banner",
    app.card_texts["cuda_oom"]["safe"] == SM.CARDS["cuda_oom"]["safe"] and app.ban_level == "error",
    app.ban_lab.cget("text"),
)
check("fix button label", app.card_texts["cuda_oom"]["fix_label"] == "Lower to 2048 and resume")
resumed = []
real_resume, app.resume = app.resume, lambda: resumed.append(app.v_envs.get())
app._card_action("cuda_oom", "halve_envs", app.cards["cuda_oom"][1])
app.resume = real_resume
check(
    "fix: num_envs halved and resumed in one click, card closed, card area collapsed",
    app.v_envs.get() == 2048 and resumed == [2048] and "cuda_oom" not in app.cards
    and not app.cards_f.winfo_manager(),
)
check("OOM card says 'practice characters (num_envs)'", "number of practice characters (num_envs)" in app.card_texts["cuda_oom"]["what"])
check("OOM card: first mention 'saved progress (model.pt)'", "Your saved progress (model.pt)" in app.card_texts["cuda_oom"]["safe"])
check("error banner wording", SM.BANNER["error"][1] == "Training stopped with an error. Your saved progress is safe; see below.")
app.root.minsize(1, 1)  # a0.8.3 minsize 1100x720 - this check wants a narrow window
app.root.state("normal")
app.root.geometry("700x880")
app._paint_banner("error", SM.BANNER["error"][1])
app.root.update()
check(
    "banner wraps instead of clipping on a narrow window",
    app.ban_lab.winfo_reqwidth() <= app.ban_f.winfo_width() and int(app.ban_lab.cget("wraplength")) < 700,
    "%s / %s" % (app.ban_lab.winfo_reqwidth(), app.ban_f.winfo_width()),
)
app.root.geometry("1280x880")
app.root.update()
for cid in SM.CARDS:
    c = SM.card(cid)
    check("card %s: no hex code in the main sentence" % cid, not re.search(r"0x[0-9A-Fa-f]{4,}", c["what"] + c["safe"]))
c = SM.card("cpu_preview_crash")
check("CPU preview card wording", c["what"] == "Windows stopped the CPU preview with a crash that happens on some PCs.")
check("CPU preview code in the grey detail line", "0xC0000005" in c["detail"])
cr = SM.StatusModel()
cr.feed("[gui] process ended (exit code 3221225477)\n")
check("crash banner: code only in the grey detail", "exit code" not in SM.health(cr, False)[1]
      and SM.banner_detail(cr, False) == "exit code 0xC0000005", SM.banner_detail(cr, False))

# bad yaml -> open file
opened = []
S.open_path = lambda p: opened.append(p) or True
run()
app.sm_q.put(YAML)
app.proc.rc = 1
app.sm_q.put("[gui] process ended (exit code 1)\n")
tick()
check(
    "bad yaml card with file + line",
    "bad_yaml" in app.cards
    and "data/envs/my_env.yaml could not be read (line 7)" in app.card_texts["bad_yaml"]["what"],
)
app._card_action("bad_yaml", "open_file", app.cards["bad_yaml"][1])
check("fix: opens that file", opened == [os.path.join(app.mk(), "data/envs/my_env.yaml")], opened)

# new run clears old cards
run()
app._show_card("cuda_oom", n=1)
run()
check("a new run clears old error cards", not app.cards)

# MimicKit missing: card instead of a popup
calls.clear()
app.proc = None
app.v_mk.set(os.path.join(TMP, "nowhere"))
r = app._check("train")
check(
    "MimicKit missing -> card, no popup",
    r is False and "mk_missing" in app.cards and not calls,
    calls,
)
G.filedialog.askdirectory = lambda **k: mk
app._card_action("mk_missing", "choose_mk", app.cards["mk_missing"][1])
check(
    "fix: choose folder -> saved + card gone",
    app.v_mk.get() == mk and app.s["mimickit"] == mk and "mk_missing" not in app.cards,
)

# no model
calls.clear()
app.v_out.set("output/nothing_here")
app.v_model.set("")
app.watch()
check(
    "Watch without a model -> no_model card, no popup", "no_model" in app.cards and not calls, calls
)
app._close_card("no_model")
app.resume()
check("Resume without a model -> no_model card", "no_model" in app.cards)
app._close_card("no_model")
app.preview()
check(
    "Render preview without a model -> no_model card", "no_model" in app.cards and not calls, calls
)
app._close_card("no_model")
app.v_mk.set(os.path.join(TMP, "nowhere"))
app.preview()
check(
    "Render preview without MimicKit -> card, no popup",
    "mk_missing" in app.cards and not calls,
    calls,
)
app._close_card("mk_missing")
app.v_mk.set(mk)

# CPU preview crash
app.v_pdev.set("CPU only")
app.sm_q.put(("preview_end", 3221225477, None))
tick()
check("CPU preview access violation -> card", "cpu_preview_crash" in app.cards)
app._card_action("cpu_preview_crash", "preview_gpu", {})
check(
    "fix: previews on the GPU (saved)",
    app.v_pdev.get() == "GPU" and app.s["preview_device"] == "GPU",
)
app.sm_q.put(("preview_end", 3221225477, None))
tick()
check("no card when the preview already used the GPU", "cpu_preview_crash" not in app.cards)
app.sm_q.put(("preview_end", 1, None))
app.v_pdev.set("CPU only")
tick()
check("other preview failures: no CPU card", "cpu_preview_crash" not in app.cards)

# looks trained
sent = []
app.notifier.send = lambda text, *a, **k: sent.append(text)
app.notifier.targets = lambda: ["discord"]
app.s["notify"] = dict(send_trained=True)
run()
d = app.outdir_abs()
app._check_looks_trained(d, dict(kind="plateau", pct=80, a=0.7), True)
check("not yet at 80%", "looks_trained" not in app.cards)
app._check_looks_trained(d, dict(kind="plateau", pct=96, a=0.712), True)
time.sleep(0.2)
check("plateau >= 95% -> prompt + banner state", "looks_trained" in app.cards and app._looks_now)
check(
    "optional ping sent once, plain text",
    len(sent) == 1 and sent[0].startswith("Looks trained:") and "0.71" in sent[0],
    sent,
)
app._close_card("looks_trained")
app._check_looks_trained(d, dict(kind="plateau", pct=99, a=0.72), True)
check("only once per run chain", "looks_trained" not in app.cards and len(sent) == 1)
app._looks = None
app._check_looks_trained(d, dict(kind="plateau", pct=99, a=0.72), True)
check("... also after a launcher restart", "looks_trained" not in app.cards)
app.s.pop("looks_trained_seen")
app._looks = None
app.s["notify"] = dict(send_trained=False)
app._check_looks_trained(d, dict(kind="target", pct=100, a=1.0), True)
check(
    "target reached -> prompt; no ping when the box is off",
    "looks_trained" in app.cards and len(sent) == 1,
)
check("dashboard flag", app.snap.get("looks_trained") is True)
stopped = []
app.stop = lambda: stopped.append(1)
app._card_action("looks_trained", "stop", {})
check("prompt: Stop training", stopped == [1] and "looks_trained" not in app.cards)
del app.stop

# stop -> banner
run()
app.sm_q.put(REAL)
tick()
app.sm.stopped_by_user = True
app.proc.rc = 1
app.sm_q.put("[gui] process ended (exit code 1)\n")
tick()
check("stopped by you", app.ban_lab.cget("text") == SM.BANNER["stopped"][1])

# theme switch keeps cards
app._show_card("no_model", folder="x", ipo=3)
app.v_light.set(True)
app._toggle_theme()
root.update()
check(
    "light mode: cards rebuilt in the new colours",
    "no_model" in app.cards and app.ban_f.cget("bg") == G.T["panel"],
)
app.v_light.set(False)
app._toggle_theme()

# dark message box (real one, not the test stubs)
mb = S.DarkMessageBox if hasattr(S, "DarkMessageBox") else type(G.messagebox)
box = mb(G.T)


def press(label):
    def go():
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel):
                for b in w.winfo_children()[0].winfo_children()[-1].winfo_children():
                    if b.cget("text") == label:
                        b.invoke()
                        return
        root.after(50, go)

    root.after(150, go)


press("No")
check("dark askyesno: No -> False", box.askyesno("t", "Overwrite?") is False)
press("Yes")
check("dark askyesno: Yes -> True", box.askyesno("t", "Overwrite?") is True)
seen = {}


def look():
    for w in root.winfo_children():
        if isinstance(w, tk.Toplevel):
            seen["bg"] = w.cget("bg")


root.after(100, look)
press("OK")
check("dark showinfo returns", box.showinfo("t", "hello") == "ok")
check("popup uses the theme background", seen.get("bg") == G.T["bg"], seen)
root.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
