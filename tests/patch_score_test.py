"""MimicKit patches (apply/revert idempotent, backup once, CRLF kept, unknown files untouched), per-step score parsing,
history CSV with old headers, dashboard URL ordering/labels and QR refresh after a late 'pip install qrcode'.
  xvfb-run -a python tests/patch_score_test.py"""
import os, shutil, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
os.environ["MIMICKIT_LAUNCHER_CONFIG"] = os.path.join(tempfile.mkdtemp(), "s.json")
import mimickit_patches as MP, mimickit_remote as R
ok = []
def check(n, c, i=""): ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ("  - " + i if i else ""), flush=True)
mk = tempfile.mkdtemp(); os.makedirs(os.path.join(mk, "mimickit", "learning")); os.makedirs(os.path.join(mk, "mimickit", "engines"))
BA = os.path.join(mk, "mimickit", "learning", "base_agent.py"); NE = os.path.join(mk, "mimickit", "engines", "newton_engine.py")
orig_ba = ("class BaseAgent:\r\n    def _log(self):\r\n"
           "        self._logger.log(\"Test_Return\", test_return, collection=\"0_Main\")\r\n"
           "        self._logger.log(\"Test_Episode_Length\", test_ep_len, collection=\"0_Main\", quiet=True)\r\n"
           "        self._logger.log(\"Train_Episode_Length\", train_ep_len, collection=\"0_Main\", quiet=True)\r\n")
open(BA, "w", newline="").write(orig_ba)
open(NE, "w").write("def _build_solver(self):\n    return S(model, solver=\"newton\",\n             iterations=10)\n")
check("status before: not applied", MP.status(mk, "logging") == "not applied" and MP.status(mk, "solver") == "not applied")
m1 = MP.apply(mk, "logging"); after1 = open(BA, newline="").read(); m2 = MP.apply(mk, "logging"); after2 = open(BA, newline="").read()
check("apply: un-quiets both episode-length lines", "quiet=True" not in after1 and after1.count("launcher patch") == 2, m1)
check("apply twice = same file ('already applied')", after1 == after2 and m2 == "already applied")
check("backup of the untouched original, made once", open(BA + MP.BACKUP_EXT, newline="").read() == orig_ba)
check("Windows line endings kept", after1.count("\r\n") == orig_ba.count("\r\n"))
check("status: applied", MP.status(mk, "logging") == "applied")
r1 = MP.revert(mk, "logging"); r2 = MP.revert(mk, "logging")
check("revert restores byte-identical, twice is a no-op", open(BA, newline="").read() == orig_ba and r2.startswith("not applied"))
MP.apply(mk, "solver"); MP.apply(mk, "solver")
check("solver patch: applied once", open(NE).read().count('solver="cg", jacobian="sparse",') == 1 and MP.status(mk, "solver") == "applied")
MP.revert(mk, "solver"); check("solver patch reverted", 'solver="newton",' in open(NE).read() and MP.status(mk, "solver") == "not applied")
open(NE, "w").write("# rewritten upstream\n"); before = open(NE).read()
try: MP.apply(mk, "solver"); raised = False
except RuntimeError: raised = True
check("unknown file version: refused, untouched", raised and open(NE).read() == before and MP.status(mk, "solver") == "unknown")
check("missing file reported", MP.status(tempfile.mkdtemp(), "logging") == "missing")
# ---- per-step score
import tkinter as tk, mimickit_launcher as G
check("per_step_pct", abs(G.per_step_pct(150.0, 200.0) - 75.0) < 1e-9 and G.per_step_pct(5, 0) is None and G.per_step_pct(float("nan"), 3) is None)
tab = ("-" * 40 + "\n| Iteration | 7 |\n| Samples | 1000 |\n| Wall_Time | 0.1 |\n| Test_Return | 40 |\n| Test_Episode_Length | 50 |\n"
       "| Train_Return | 30 |\n| Train_Episode_Length | 60 |\n" + "-" * 40 + "\n")
t = G.StdoutTables(); t.feed(tab); t.feed(tab.replace("| 7 |", "| 8 |").replace("| 30 |", "| 45 |")); t.feed("-" * 10)
ps = G.per_step_series(t.data)
check("console table with episode length -> per-step series", ps.get("Train") == [50.0, 75.0] and ps.get("Test") == [80.0, 80.0], str(ps))
d = tempfile.mkdtemp(); G.append_history(d, t.data, 0)
h = G.load_history(d); check("history CSV keeps episode length", h.get("Train_Episode_Length") == [60.0, 60.0])
d2 = tempfile.mkdtemp(); open(os.path.join(d2, G.HIST_FILE), "w").write("Iteration,Samples,Wall_Time,Train_Return,Test_Return,Samples_Per_Second\n1,10,0,1,1,5\n")
n = G.append_history(d2, t.data, 1); h2 = G.load_history(d2)
check("appending to an old-format history keeps rows aligned", n == 2 and h2["Samples"] == [10.0, 1000.0], str(h2.get("Samples")))
for nm in ("showinfo", "showwarning", "showerror"): setattr(G.messagebox, nm, lambda *a, **k: None)
G.messagebox.askyesno = lambda *a, **k: False; G.filedialog.askdirectory = lambda **k: os.path.join(HERE, "fake_mimickit")
root = tk.Tk(); app = G.App(root); app.v_mk.set(os.path.join(HERE, "fake_mimickit"))
for _ in range(20): root.update(); time.sleep(0.02)
line = app._per_step_line(t.data, d)
check("status: live per-step score", line == "Avg reward per step: train 75.0%   test 80.0%", line)
nolen = {k: v for k, v in t.data.items() if "Episode_Length" not in k}; d3 = tempfile.mkdtemp()
check("unpatched, no log.txt: graceful hint", "needs the logging patch - see README" in app._per_step_line(nolen, d3))
open(os.path.join(d3, "log.txt"), "w").write("Iteration Samples Train_Return Train_Episode_Length Test_Return Test_Episode_Length\n"
                                              "1 100 20 40 10 20\n")
l2 = app._per_step_line(nolen, d3)
check("unpatched: falls back to log.txt with a note", "train 50.0%" in l2 and "test 50.0%" in l2 and "from log.txt" in l2, l2)
check("third chart present (per-step) and toggleable", app.ax3 is not None and (app.v_ps.set(False), app._ps_toggled(), app.ax3 is None)[2]
      and (app.v_ps.set(True), app._ps_toggled(), app.ax3 is not None)[2])
app.patch_dialog(); root.update(); app.v_mk.set(mk); MP.revert(mk, "logging") if MP.status(mk, "logging") == "applied" else None
app._patch_dlg["act"](MP.apply, "logging"); app._patch_dlg["act"](MP.apply, "logging")
check("patch dialog apply (twice) from the GUI", MP.status(mk, "logging") == "applied")
app._patch_dlg["act"](MP.revert, "logging"); check("patch dialog revert", MP.status(mk, "logging") == "not applied")
# ---- dashboard URLs: Tailscale first, labelled; QR uses it; QR appears after a late install + Refresh
items = R.dashboard_urls("0.0.0.0", 8765, "TOK", labelled=True, ts=([], ""), lan=["10.0.0.149", "100.75.74.44"], hostname="pc")
check("user's case: Tailscale IP first, then LAN, then hostname", [l for l, _ in items] == ["Tailscale", "LAN", "hostname"]
      and items[0][1] == "http://100.75.74.44:8765/?t=TOK", str(items))
items = R.dashboard_urls("0.0.0.0", 8765, "T", labelled=True, ts=(["100.75.74.44"], "pc.tail1234.ts.net"), lan=["10.0.0.149", "100.75.74.44"], hostname="pc")
check("with the tailscale CLI: IP, MagicDNS name, LAN, hostname (no duplicates)",
      [h for _, h in items] == ["http://%s:8765/?t=T" % x for x in ("100.75.74.44", "pc.tail1234.ts.net", "10.0.0.149", "pc")], str(items))
check("100.64.0.0/10 detection", R.is_tailscale_ip("100.64.0.1") and R.is_tailscale_ip("100.127.255.254") and not R.is_tailscale_ip("100.128.0.1")
      and not R.is_tailscale_ip("10.0.0.149"))
check("127.0.0.1 -> this PC only", R.dashboard_urls("127.0.0.1", 1, "x", labelled=True) == [("this PC", "http://127.0.0.1:1/?t=x")])
R.tailscale_info = lambda timeout=4: (["100.75.74.44"], "")
R.lan_addresses = lambda: ["10.0.0.149", "100.75.74.44"]
pkg = tempfile.mkdtemp(); sys.path.insert(0, pkg); sys.modules.pop("qrcode", None)
app.s["remote"] = dict(enabled=False, host="0.0.0.0", port=8765, token="TOK"); app.remote_dialog(); root.update()
qr = [w for w in app._rdlg.winfo_children()[0].winfo_children() if isinstance(w, tk.Canvas)][0]
check("without qrcode: placeholder", not qr.find_withtag("qr") and R.load_qrcode() is None)
os.makedirs(os.path.join(pkg, "qrcode"))
open(os.path.join(pkg, "qrcode", "__init__.py"), "w").write(
    "class QRCode:\n    def __init__(self, border=2): self.d = ''\n    def add_data(self, d): self.d = d\n    def make(self, fit=True): pass\n"
    "    def get_matrix(self): return [[(x * y + x) % 3 == 0 for x in range(21)] for y in range(21)]\n")
btn = [w for w in app._rdlg.winfo_children()[0].winfo_children() if isinstance(w, G.ttk.Button) and w.cget("text") == "Refresh"][0]
btn.invoke(); root.update()
check("installed while open + Refresh -> QR drawn", len(qr.find_withtag("qr")) > 50, str(len(qr.find_withtag("qr"))))
check("QR encodes the Tailscale URL", app._qr_url == "http://100.75.74.44:8765/?t=TOK", app._qr_url)
copies = [w for w in app._rdlg.winfo_descendants() if isinstance(w, G.ttk.Button) and w.cget("text") == "Copy"] if hasattr(app._rdlg, "winfo_descendants") else None
def walk(w):
    for c in w.winfo_children(): yield c; yield from walk(c)
copies = [w for w in walk(app._rdlg) if isinstance(w, G.ttk.Button) and w.cget("text") == "Copy"]
copies[0].invoke(); root.update()
check("a Copy button per URL; copies it", len(copies) == 3 and root.clipboard_get() == "http://100.75.74.44:8765/?t=TOK")
labels = [w.cget("text") for w in walk(app._rdlg) if isinstance(w, G.ttk.Label)]
check("lines labelled", all(x in labels for x in ("Tailscale", "LAN", "hostname")), str(labels[:12]))
root.destroy()
print("RESULT: %d/%d" % (sum(ok), len(ok)))
