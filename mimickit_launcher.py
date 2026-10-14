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
from mkl import icon


class App(MainWindowMixin, ProcessMixin, ChartsMixin, DashboardMixin, SettingsMixin, StatusMixin, EnvSwitchMixin, StopAfterSaveMixin, ActionsMixin):
    def __init__(self, root):
        self.root = root
        root.title("MimicKit Launcher  %s" % VERSION)
        icon.apply_icon(root)
        root.geometry("1280x880")
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


def main():
    icon.prepare_process()  # before the first window, so the taskbar shows our icon (Windows)
    root = tk.Tk()
    App(root)  # applies the window icon first thing
    root.mainloop()


if __name__ == "__main__":
    main()
