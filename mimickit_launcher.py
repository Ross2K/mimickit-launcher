"""MimicKit Launcher - a small desktop GUI for running MimicKit (https://github.com/xbpeng/MimicKit).

Unofficial and unaffiliated with MimicKit. Vibe coded; see README.md.
Copyright (c) 2026 curelessSky, licensed under GPL-3.0-or-later.
Run with any Python 3.9+ that has tkinter and matplotlib:  python mimickit_launcher.py
"""

# The App is split into mixins under mkl/ (core helpers, main window, processes, charts, dashboard, settings).
from mkl.core import *  # noqa: F401,F403 - re-exported: tests and tools use mimickit_launcher.<name>
from mkl.core import __all__ as _core_names  # noqa: F401
from mkl.window import MainWindowMixin
from mkl.process import ProcessMixin
from mkl.charts import ChartsMixin
from mkl.dashboard import DashboardMixin
from mkl.settings import SettingsMixin
from mkl.status import StatusMixin
from mkl.envswitch import EnvSwitchMixin
from mkl.stopsave import StopAfterSaveMixin
from mkl.actions import ActionsMixin
from mkl.plugins import PluginsMixin
from mkl import icon


class App(MainWindowMixin, ProcessMixin, ChartsMixin, DashboardMixin, SettingsMixin, StatusMixin, EnvSwitchMixin, StopAfterSaveMixin, ActionsMixin, PluginsMixin):
    def __init__(self, root):
        self.root = root
        # Tk callback errors used to go to stderr - invisible under pythonw.exe. Now: launcher_errors.log + log panel
        # + banner detail, so a failing button can't fail silently.
        root.report_callback_exception = self._tk_callback_error
        root.title("MimicKit Launcher  %s" % VERSION)
        icon.apply_icon(root)
        root.deiconify()  # main() keeps it hidden until here (icon first); pop-ups below need a visible owner
        # DPI awareness is on: scale the 96-dpi base size, clamped to the screen
        try:
            k = max(1.0, root.winfo_fpixels("1i") / 96.0)
        except Exception:
            k = 1.0
        w = min(int(1280 * k), root.winfo_screenwidth())
        h = min(int(880 * k), root.winfo_screenheight())
        root.geometry("%dx%d" % (w, h))
        U.set_log_path(
            os.path.join(os.path.dirname(os.path.abspath(CONFIG)), "launcher_errors.log")
        )
        problems = []
        self.s = load_settings(problems)
        if problems:
            self.v_light = tk.BooleanVar(value=False)
            self.apply_theme()
            self.s = resolve_damaged_settings(self.choose, problems[0])
        self._register_secrets()
        self.proc = None
        self.q = queue.Queue()
        self.preview_proc = None
        self.run_dir = None
        self.run_kind = None
        self.started = None
        self.live = StdoutTables()
        self.live_dir = None
        self.live_lock = threading.Lock()
        self.tt = None
        self.tt_next = None
        self.tt_lock = threading.Lock()
        self.hist_n = 0
        self._status_init()
        self._envswitch_init()
        self._stopsave_init()
        self._build()
        self.root.after(400, self._first_run)
        self.root.after(600, self._reattach)
        self.root.after(200, self._pump)
        self.root.after(1000, self._status_tick)
        self.root.after(1000, self._progress_tick)
        self._gpu_poll_thread()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.dash = None
        self.rq = queue.Queue()
        self.snap = {}
        self.render_msg = ""
        self.notifier = R.Notifier(
            lambda: self.s.get("notify", {}), log=lambda m: self.q.put(m + "\n")
        )
        self.root.after(800, self._remote_apply)
        self._plugins_init()  # launcher_profile.py PLUGINS (none in the public build)


def _wait_for_pid(argv):
    """--wait-pid N: a reloading launcher (after an update) waits for the old window's process to exit first, so the
    two never fight over the dashboard port or the settings file. Capped at 30 s."""
    if "--wait-pid" not in argv:
        return
    try:
        pid = int(argv[argv.index("--wait-pid") + 1])
    except (IndexError, ValueError):
        return
    t0 = time.time()
    while time.time() - t0 < 30 and proc_info(pid) and proc_info(pid).get("alive"):
        time.sleep(0.25)


def main():
    _wait_for_pid(sys.argv)
    icon.prepare_process()  # before the first window, so the taskbar shows our icon (Windows)
    root = tk.Tk()
    root.withdraw()  # hidden until the icon + AppUserModelID are on it: the taskbar never shows python's icon
    App(root)  # applies the window icon first thing, then shows the window
    root.mainloop()


if __name__ == "__main__":
    main()
