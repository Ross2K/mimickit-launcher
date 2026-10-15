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
        repl=[
            (
                'self._logger.log("Test_Episode_Length", test_ep_len, collection="0_Main", quiet=True)',
                'self._logger.log("Test_Episode_Length", test_ep_len, collection="0_Main")  # launcher patch: in console',
            ),
            (
                'self._logger.log("Train_Episode_Length", train_ep_len, collection="0_Main", quiet=True)',
                'self._logger.log("Train_Episode_Length", train_ep_len, collection="0_Main")  # launcher patch: in console',
            ),
        ],
    ),
    "solver": dict(
        file="mimickit/engines/newton_engine.py",
        title="Solver: CG + sparse Jacobians (needed on GTX 10-series / sm_61)",
        why="MuJoCo-Warp's default Newton solver uses tile kernels that compute capability 6.1 cards can't run.\n"
        "The conjugate-gradient solver with sparse Jacobians avoids them. Newer GPUs don't need this.",
        repl=[('solver="newton",', 'solver="cg", jacobian="sparse",')],
    ),
    "clipstart": dict(
        file="mimickit/envs/deepmimic_env.py",
        title="Clip start share: some random-start episodes begin at the clip start",
        why="Adds an optional env yaml key clip_start_share (0-1, default 0 = MimicKit's normal behaviour). With rand_reset on,\n"
        "that share of episodes starts at time 0 of the clip instead of a random time. One tensor op per reset batch.",
        repl=[
            (
                '        self._rand_reset = env_config.get("rand_reset", True)\n',
                '        self._rand_reset = env_config.get("rand_reset", True)\n'
                '        self._clip_start_share = float(env_config.get("clip_start_share", 0.0))  # launcher patch: clip start share\n',
            ),
            (
                "            motion_times = self._motion_lib.sample_time(motion_ids)\n",
                "            motion_times = self._motion_lib.sample_time(motion_ids)\n"
                "            if (self._clip_start_share > 0.0):  # launcher patch: clip start share\n"
                "                motion_times = torch.where(torch.rand(n, device=self._device) < self._clip_start_share,\n"
                "                                           torch.zeros_like(motion_times), motion_times)\n",
            ),
        ],
    ),
}
BACKUP_EXT = ".launcher_orig"


def _path(mk, name):
    return os.path.join(mk, *PATCHES[name]["file"].split("/"))


def _pairs(name, txt):
    """The replacement pairs in the file's own line ending (Windows checkouts may use CRLF)."""
    pairs = PATCHES[name]["repl"]
    if "\r\n" in txt:
        pairs = [(o.replace("\n", "\r\n"), n.replace("\n", "\r\n")) for o, n in pairs]
    return pairs


def status(mk, name):
    p = _path(mk, name)
    if not os.path.isfile(p):
        return "missing"
    txt = open(p, encoding="utf-8", newline="").read()
    pairs = _pairs(name, txt)
    done = [new in txt for old, new in pairs]
    todo = [old in txt for old, new in pairs]
    if all(done):
        return "applied"
    if all(todo):
        return "not applied"
    if any(done):
        return "partial"
    return "unknown"  # neither form found: MimicKit changed, the launcher won't touch the file


def apply(mk, name):
    st = status(mk, name)
    if st == "applied":
        return "already applied"
    if st in ("missing", "unknown"):
        raise RuntimeError(
            "%s: can't patch (%s) - see README for the manual change" % (PATCHES[name]["file"], st)
        )
    p = _path(mk, name)
    txt = open(p, encoding="utf-8", newline="").read()
    if not os.path.exists(p + BACKUP_EXT):
        shutil.copy2(p, p + BACKUP_EXT)
    for old, new in _pairs(name, txt):
        if new not in txt:
            txt = txt.replace(old, new, 1)
    _write(p, txt)
    return "applied (backup: %s)" % os.path.basename(p + BACKUP_EXT)


def revert(mk, name):
    st = status(mk, name)
    if st == "not applied":
        return "not applied - nothing to revert"
    if st in ("missing", "unknown"):
        raise RuntimeError("%s: can't revert (%s)" % (PATCHES[name]["file"], st))
    p = _path(mk, name)
    txt = open(p, encoding="utf-8", newline="").read()
    for old, new in _pairs(name, txt):
        txt = txt.replace(new, old)
    _write(p, txt)
    return "reverted"


def _write(p, txt):
    tmp = p + ".launcher_tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(txt)
    os.replace(tmp, p)
