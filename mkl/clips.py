# MimicKit Launcher - which motion clips the MP4 preview shows (a0.8.0). SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0 (see LICENSE).
"""Datasets can hold many clips (e.g. 31); the preview shows at most MAX_PREVIEW_CLIPS in one video. The choice is
saved per training config (s['preview_clips'][config] = clip names). Without a saved choice: the preset's
preview_clips, else the first clips (MimicKit's order) as before."""

import os, re

import mimickit_trainsettings as TS
from mkl import core

MAX_PREVIEW_CLIPS = 4


def clip_names(mk, env_yaml):
    """Clip names (file name without .pkl) of an env yaml's motion_file, in the motion library's order."""
    if not mk or not env_yaml:
        return []
    try:
        txt = open(os.path.join(mk, env_yaml), encoding="utf-8").read()
    except OSError:
        return []
    m = re.search(r"^\s*motion_file\s*:\s*[\"']?([^\"'#\s]+)", txt, re.M)
    if not m:
        return []
    return [os.path.splitext(os.path.basename(f))[0] for f, _ in TS.motion_files(mk, m.group(1))]


def match(names, wanted):
    """Wanted names (exact, or a unique ending like 'walk_v1') -> names present, in the wanted order, max 4."""
    out = []
    for w in wanted or []:
        w = os.path.splitext(os.path.basename(str(w)))[0]
        hit = w if w in names else next((n for n in names if n.endswith("_" + w) or n.endswith(w)), None)
        if hit and hit not in out:
            out.append(hit)
    return out[:MAX_PREVIEW_CLIPS]


class ClipsMixin:
    def _clips_of(self, it):
        return clip_names(self.mk(), (it or {}).get("env", ""))

    def _chosen_clips(self, it):
        names = self._clips_of(it)
        if len(names) <= 1:
            return []
        saved = (self.s.get("preview_clips") or {}).get((it or {}).get("name", ""))
        return match(names, saved) or match(names, (it or {}).get("preview_clips")) or names[:MAX_PREVIEW_CLIPS]

    def _set_chosen_clips(self, it, chosen):
        self.s.setdefault("preview_clips", {})[it["name"]] = list(chosen)[:MAX_PREVIEW_CLIPS]
        self._save_settings_only()

    def clips_dialog(self):
        import tkinter as tk
        from tkinter import ttk

        it = self._item("train")
        names = self._clips_of(it)
        if len(names) <= 1:
            core.messagebox.showinfo("Preview clips", "This config has %s clip - nothing to choose."
                                     % ("one" if names else "no"))
            return
        top, f, pinned = core.scroll_popup(self.root, "Preview clips - " + it["name"], core.T)
        self._clipdlg = top
        ttk.Label(f, text="Pick up to %d clips for the MP4 preview (%d in this config)." % (MAX_PREVIEW_CLIPS, len(names)),
                  style="Dim.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        cur = set(self._chosen_clips(it))
        vars_ = {}
        msg = ttk.Label(pinned, text="", style="Dim.TLabel")

        def changed(_=None):
            on = [n for n in names if vars_[n].get()]
            for n, (v, cb) in ((n, (vars_[n], boxes[n])) for n in names):
                cb.state(["disabled"] if len(on) >= MAX_PREVIEW_CLIPS and not v.get() else ["!disabled"])
            msg.configure(text="%d of %d chosen" % (len(on), MAX_PREVIEW_CLIPS))

        boxes = {}
        cols = 3 if len(names) > 12 else 1
        rows = (len(names) + cols - 1) // cols
        for i, n in enumerate(names):
            vars_[n] = tk.BooleanVar(value=n in cur)
            boxes[n] = ttk.Checkbutton(f, text=n, variable=vars_[n], command=changed)
            boxes[n].grid(row=1 + i % rows, column=i // rows, sticky="w", padx=(0, 12))

        def save():
            on = [n for n in names if vars_[n].get()]
            self._set_chosen_clips(it, on)
            self._append("[gui] preview clips for %s: %s\n" % (it["name"], ", ".join(on) or "(first ones)"))
            top.destroy()

        def default():
            want = set(match(names, it.get("preview_clips")) or names[:MAX_PREVIEW_CLIPS])
            for n in names:
                vars_[n].set(n in want)
            changed()

        ttk.Button(pinned, text="Save", command=save).pack(side="left", padx=3)
        ttk.Button(pinned, text="Default", command=default).pack(side="left", padx=3)
        ttk.Button(pinned, text="Close", command=top.destroy).pack(side="left", padx=3)
        msg.pack(side="left", padx=8)
        self._clipdlg_vars = (vars_, save, default)
        changed()
