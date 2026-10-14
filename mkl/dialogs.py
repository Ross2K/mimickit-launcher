"""Dark-themed replacement for tkinter.messagebox (same function names, so callers and tests are unchanged)."""

import sys
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox as _native

from mimickit_util import log_exc

ICONS = {
    "info": ("i", "accent"),
    "warning": ("!", "warn"),
    "error": ("x", "err"),
    "question": ("?", "accent"),
}


# ---- placement shared by every pop-up and tooltip ---------------------------------------------------------------


def monitor_rect(w):
    """Work area (x, y, width, height) of the monitor that holds w's toplevel window (Tk only knows the primary
    screen, so on Windows ask the OS for the monitor under the window; elsewhere the virtual root)."""
    top = w.winfo_toplevel()
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            cx = top.winfo_rootx() + top.winfo_width() // 2
            cy = top.winfo_rooty() + top.winfo_height() // 2
            mon = ctypes.windll.user32.MonitorFromPoint(wintypes.POINT(cx, cy), 2)  # 2 = nearest
            mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
            if mon and ctypes.windll.user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                r = mi.rcWork
                return (r.left, r.top, r.right - r.left, r.bottom - r.top)
        except Exception as e:
            log_exc("dialogs: monitor_rect - falling back to the virtual root", e)
    return (top.winfo_vrootx(), top.winfo_vrooty(), top.winfo_vrootwidth(), top.winfo_vrootheight())


def clamp(x, y, w, h, area):
    """Top-left corner that keeps a w x h box inside area (x, y, width, height); top-left wins if it can't fit."""
    ax, ay, aw, ah = area
    return max(ax, min(x, ax + aw - w)), max(ay, min(y, ay + ah - h))


def window_rect(w):
    top = w.winfo_toplevel()
    return (top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height())


def place_popup(win, parent):
    """Centre win over parent's main window, kept on parent's monitor; transient + raised. Use for every pop-up."""
    owner = parent.winfo_toplevel()
    try:
        win.transient(owner)
    except tk.TclError:
        pass
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    px, py, pw, ph = window_rect(owner)
    x, y = clamp(px + (pw - w) // 2, py + (ph - h) // 2, w, h, monitor_rect(owner))
    win.geometry("+%d+%d" % (x, y))
    win.deiconify()
    win.lift()
    return x, y


def new_popup(parent, title, theme):
    """Themed Toplevel that places itself (place_popup) once its content is built (first idle moment)."""
    top = tk.Toplevel(parent)
    top.withdraw()
    top.title(title)
    top.configure(bg=theme["bg"])
    top.after_idle(lambda: top.winfo_exists() and place_popup(top, parent))
    return top


def tip_position(anchor, w, h, gap=4):
    """Tooltip below the anchor widget (flipped above when there's no room), clamped inside the anchor's window
    (or its monitor if the tooltip is bigger than the window)."""
    ax, ay, ah = anchor.winfo_rootx(), anchor.winfo_rooty(), anchor.winfo_height()
    win, mon = window_rect(anchor), monitor_rect(anchor)
    area = win if w <= win[2] and h <= win[3] else mon
    x, y = ax + 10, ay + ah + gap
    if y + h > area[1] + area[3]:
        y = ay - h - gap
    return clamp(x, y, w, h, area)


class DarkMessageBox:
    def __init__(self, theme):
        self.T = theme  # the live colour dict from mkl.core (changes when the theme is switched)

    # ---- tkinter.messagebox-compatible API ------------------------------------------------
    def showinfo(self, title=None, message=None, **kw):
        return self._ask(title, message, [("OK", "ok")], "ok", kw.get("icon", "info"), kw)

    def showwarning(self, title=None, message=None, **kw):
        return self._ask(title, message, [("OK", "ok")], "ok", kw.get("icon", "warning"), kw)

    def showerror(self, title=None, message=None, **kw):
        return self._ask(title, message, [("OK", "ok")], "ok", kw.get("icon", "error"), kw)

    def askyesno(self, title=None, message=None, **kw):
        d = "no" if kw.get("default") == "no" else "yes"
        return self._ask(
            title,
            message,
            [("Yes", True), ("No", False)],
            d == "yes",
            kw.get("icon", "question"),
            kw,
            esc=False,
        )

    def askokcancel(self, title=None, message=None, **kw):
        return self._ask(
            title,
            message,
            [("OK", True), ("Cancel", False)],
            True,
            kw.get("icon", "question"),
            kw,
            esc=False,
        )

    def askyesnocancel(self, title=None, message=None, **kw):
        return self._ask(
            title,
            message,
            [("Yes", True), ("No", False), ("Cancel", None)],
            True,
            kw.get("icon", "question"),
            kw,
            esc=None,
        )

    # ---- implementation -------------------------------------------------------------------
    def _ask(self, title, message, buttons, default, icon, kw, esc="ok"):
        root = kw.get("parent") or getattr(tk, "_default_root", None)
        if root is None or "bg" not in self.T:
            fn = {1: _native.showinfo}.get(len(buttons))
            if len(buttons) == 1:
                {"error": _native.showerror, "warning": _native.showwarning}.get(icon, fn)(
                    title, message
                )
                return "ok"
            if len(buttons) == 3:
                return _native.askyesnocancel(title, message)
            return (_native.askyesno if buttons[0][0] == "Yes" else _native.askokcancel)(
                title, message
            )
        T = self.T
        top = tk.Toplevel(root)
        top.withdraw()
        top.title(title or "")
        top.configure(bg=T["bg"])
        top.resizable(False, False)
        res = {"v": esc}
        f = ttk.Frame(top, padding=14)
        f.pack(fill="both", expand=True)
        sym, col = ICONS.get(icon, ICONS["info"])
        tk.Label(
            f, text=sym, width=2, bg=T.get(col, T["fg"]), fg=T["bg"], font=("Segoe UI", 12, "bold")
        ).grid(row=0, column=0, sticky="nw", padx=(0, 12))
        ttk.Label(f, text=message or "", wraplength=440, justify="left").grid(
            row=0, column=1, sticky="w"
        )
        row = ttk.Frame(f)
        row.grid(row=1, column=0, columnspan=2, sticky="e", pady=(14, 0))

        def pick(v):
            res["v"] = v
            top.destroy()

        first = None
        for lab, val in buttons:
            b = ttk.Button(row, text=lab, width=9, command=lambda v=val: pick(v))
            b.pack(side="left", padx=(6, 0))
            if val == default:
                first = b
        top.bind("<Escape>", lambda _=None: pick(esc))
        top.protocol("WM_DELETE_WINDOW", lambda: pick(esc))
        top.bind("<Return>", lambda _=None: pick(default))
        place_popup(top, root)
        if first:
            first.focus_set()
        try:
            top.grab_set()
        except tk.TclError:
            pass
        root.wait_window(top)
        return res["v"]
