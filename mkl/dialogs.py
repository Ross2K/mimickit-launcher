"""Dark-themed replacement for tkinter.messagebox (same function names, so callers and tests are unchanged)."""

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox as _native

ICONS = {
    "info": ("i", "accent"),
    "warning": ("!", "warn"),
    "error": ("x", "err"),
    "question": ("?", "accent"),
}


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
        try:
            top.transient(root.winfo_toplevel())
        except tk.TclError:
            pass
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
        top.update_idletasks()
        try:  # centre over the main window
            rx, ry, rw, rh = (
                root.winfo_rootx(),
                root.winfo_rooty(),
                root.winfo_width(),
                root.winfo_height(),
            )
            top.geometry(
                "+%d+%d"
                % (
                    rx + max(0, (rw - top.winfo_reqwidth()) // 2),
                    ry + max(0, (rh - top.winfo_reqheight()) // 3),
                )
            )
        except tk.TclError:
            pass
        top.deiconify()
        if first:
            first.focus_set()
        try:
            top.grab_set()
        except tk.TclError:
            pass
        root.wait_window(top)
        return res["v"]
