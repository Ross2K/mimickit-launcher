# MimicKit Launcher - small, optional, reversible patches to a MimicKit install.
# Copyright (C) 2026 curelessSky. GPL-3.0-or-later (see LICENSE).
"""Each patch is a list of exact (original, patched) line replacements in one MimicKit file.
apply(): backs up the untouched file once (<file>.launcher_orig), then replaces - running it twice changes nothing.
revert(): replaces back - also idempotent. status(): 'applied' / 'not applied' / 'partial' / 'unknown' / 'missing'.
Patches only affect runs started afterwards (Python reads the file when a run starts)."""
import os, shutil

PATCHES = {
    "logging": dict(
        file="mimickit/learning/base_agent.py",
        title="Logging: show episode length in the console table",
        why="MimicKit already computes the mean episode length but marks it quiet, so it only reaches log.txt. Un-quieting\n"
            "it puts Train/Test_Episode_Length into the console table the launcher reads live, for the per-step score\n"
            "(return / episode length). Two log calls per iteration: no measurable cost.",
        repl=[('self._logger.log("Test_Episode_Length", test_ep_len, collection="0_Main", quiet=True)',
               'self._logger.log("Test_Episode_Length", test_ep_len, collection="0_Main")  # launcher patch: in console'),
              ('self._logger.log("Train_Episode_Length", train_ep_len, collection="0_Main", quiet=True)',
               'self._logger.log("Train_Episode_Length", train_ep_len, collection="0_Main")  # launcher patch: in console')]),
    "solver": dict(
        file="mimickit/engines/newton_engine.py",
        title="Solver: CG + sparse Jacobians (needed on GTX 10-series / sm_61)",
        why="MuJoCo-Warp's default Newton solver uses tile kernels that compute capability 6.1 cards can't run.\n"
            "The conjugate-gradient solver with sparse Jacobians avoids them. Newer GPUs don't need this.",
        repl=[('solver="newton",', 'solver="cg", jacobian="sparse",')]),
}
BACKUP_EXT = ".launcher_orig"

def _path(mk, name): return os.path.join(mk, *PATCHES[name]["file"].split("/"))

def status(mk, name):
    p = _path(mk, name)
    if not os.path.isfile(p): return "missing"
    txt = open(p, encoding="utf-8", newline="").read(); pairs = PATCHES[name]["repl"]
    done = [new in txt for old, new in pairs]; todo = [old in txt for old, new in pairs]
    if all(done): return "applied"
    if all(todo): return "not applied"
    if any(done): return "partial"
    return "unknown"          # neither form found: MimicKit changed, the launcher won't touch the file

def apply(mk, name):
    st = status(mk, name)
    if st == "applied": return "already applied"
    if st in ("missing", "unknown"): raise RuntimeError("%s: can't patch (%s) - see README for the manual change" % (PATCHES[name]["file"], st))
    p = _path(mk, name); txt = open(p, encoding="utf-8", newline="").read()
    if not os.path.exists(p + BACKUP_EXT): shutil.copy2(p, p + BACKUP_EXT)
    for old, new in PATCHES[name]["repl"]:
        if new not in txt: txt = txt.replace(old, new, 1)
    _write(p, txt); return "applied (backup: %s)" % os.path.basename(p + BACKUP_EXT)

def revert(mk, name):
    st = status(mk, name)
    if st == "not applied": return "not applied - nothing to revert"
    if st in ("missing", "unknown"): raise RuntimeError("%s: can't revert (%s)" % (PATCHES[name]["file"], st))
    p = _path(mk, name); txt = open(p, encoding="utf-8", newline="").read()
    for old, new in PATCHES[name]["repl"]: txt = txt.replace(new, old)
    _write(p, txt); return "reverted"

def _write(p, txt):
    tmp = p + ".launcher_tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f: f.write(txt)
    os.replace(tmp, p)
