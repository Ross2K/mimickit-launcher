"""Extra buttons from a launcher_profile.py overlay (ACTIONS), plus a generic 'copy files into MimicKit' helper.
ACTIONS = [dict(text="Button text", help="tooltip", run=callable(app))]. The public build defines none."""

import os
import shutil
from tkinter import ttk

from mkl import core


def install_files(src, mk, backup):
    """Copy every file under src into the same relative place in mk. On the first install (no backup folder yet)
    every file that already exists there is first copied to the same relative place under backup; later installs
    leave that backup alone, so it keeps the originals. Returns (copied, backed_up) lists of relative paths."""
    copied, backed = [], []
    take_backup = not os.path.exists(backup)
    for root, _, files in os.walk(src):
        for f in sorted(files):
            rel = os.path.relpath(os.path.join(root, f), src)
            dst = os.path.join(mk, rel)
            if take_backup and os.path.isfile(dst):
                bk = os.path.join(backup, rel)
                os.makedirs(os.path.dirname(bk), exist_ok=True)
                shutil.copy2(dst, bk)
                backed.append(rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(root, f), dst)
            copied.append(rel)
    return copied, backed


class ActionsMixin:
    def _build_actions(self, parent):
        for a in core.ACTIONS:
            b = ttk.Button(parent, text=a["text"], command=lambda a=a: a["run"](self))
            b.pack(side="left", padx=3)
            if a.get("help"):
                core.Tip(b, a["help"])
