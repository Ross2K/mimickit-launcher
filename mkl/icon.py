"""Window / taskbar icon. To swap the design, replace assets/icon.png and assets/icon.ico (multi-size) - nothing else.
Windows groups windows on the taskbar by AppUserModelID; without our own ID it shows python.exe's icon.
Order matters: prepare_process() before tk.Tk(), apply_icon(root) right after it (see mimickit_launcher.main)."""

import os
import sys

from mimickit_util import log_exc

# relative to this file, never the current folder (the .exe starter / shortcuts may start us from anywhere)
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
ICON_PNG = os.path.join(ASSETS, "icon.png")
ICON_ICO = os.path.join(ASSETS, "icon.ico")
APP_ID = "MimicKitLauncher.Launcher"
PHOTO_SIZES = (16, 32, 48, 256)  # Windows takes ICON_SMALL / ICON_BIG from these


def set_app_id(app_id=APP_ID):
    """Windows only; call before the first Tk window is created. Returns True if set."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id) == 0
    except Exception:
        return False


def set_dpi_aware():
    """Windows only: per-monitor DPI awareness (sharp text, real monitor coordinates for pop-up placement)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        try:
            return ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0  # Windows 8.1+
        except (AttributeError, OSError):
            return bool(ctypes.windll.user32.SetProcessDPIAware())  # Vista+
    except Exception:
        return False


def prepare_process():
    """Everything that must happen before tk.Tk(): DPI awareness, then our taskbar identity."""
    set_dpi_aware()
    set_app_id()


def apply_icon(root):
    """Set the icon of root and (default) every later Toplevel. Each step is independent, so one failing (old Tk,
    missing file) doesn't skip the others. Returns True if at least one icon was set."""
    done = False
    if sys.platform == "win32" and os.path.isfile(ICON_ICO):
        try:
            root.iconbitmap(default=ICON_ICO)  # .ico (BMP entries, 16-256 px): Windows picks the size per place
            done = True
        except Exception as e:
            log_exc("icon: iconbitmap", e)
    if os.path.isfile(ICON_PNG):
        try:
            import tkinter as tk

            full = tk.PhotoImage(master=root, file=ICON_PNG)
            imgs = [full.subsample(max(1, full.width() // s)) for s in PHOTO_SIZES[:-1]] + [full]
            root._icon_imgs = imgs  # keep references or Tk drops the images
            root._icon_img = full
            root.iconphoto(True, *reversed(imgs))  # largest first
            done = True
        except Exception as e:
            log_exc("icon: iconphoto", e)
    return done
