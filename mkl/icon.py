"""Window / taskbar icon. To swap the design, replace assets/icon.png and assets/icon.ico (multi-size) - nothing else.
Windows groups windows on the taskbar by AppUserModelID; without our own ID it shows python.exe's icon."""

import os
import sys

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
ICON_PNG = os.path.join(ASSETS, "icon.png")
ICON_ICO = os.path.join(ASSETS, "icon.ico")
APP_ID = "MimicKitLauncher.Launcher"


def set_app_id(app_id=APP_ID):
    """Windows only; call before the first Tk window is created. Returns True if set."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id) == 0
    except Exception:
        return False


def apply_icon(root):
    """Set the icon of root and (default=True) every later Toplevel. Missing files or old Tk: silently no icon."""
    try:
        if sys.platform == "win32" and os.path.isfile(ICON_ICO):
            root.iconbitmap(default=ICON_ICO)  # .ico carries 16-256 px, Windows picks the size
        if os.path.isfile(ICON_PNG):
            import tkinter as tk

            root._icon_img = tk.PhotoImage(file=ICON_PNG)  # keep a reference or Tk drops it
            root.iconphoto(True, root._icon_img)
        return True
    except Exception:
        return False
