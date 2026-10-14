"""'Stop after next save': let training finish its current iteration and write the next model.pt, then stop -
so nothing since the last save is lost. Uses the same checkpoint wait as the live num_envs change."""

import os

from mkl.envswitch import CheckpointWatch


class StopAfterSaveMixin:
    STOPSAVE_POLL_MS = 500
    STOPSAVE_WAITING = "Will stop after next save..."

    def _stopsave_init(self):
        self.stop_save = None  # CheckpointWatch while armed

    def stop_after_save(self):
        """Arm (or, pressed again, cancel) the stop after the next model.pt save."""
        if self.stop_save:
            self._stopsave_done("[gui] stop after next save cancelled\n")
            return
        if not self._training_running() or not self.run_dir:
            self._append("[gui] stop after next save: no training is running\n")
            return
        if self.env_switch:
            self._append("[gui] a num_envs change is already waiting for the next save - cancel it first\n")
            return
        self.stop_save = CheckpointWatch(os.path.join(self.run_dir, "model.pt"))
        self._stopsave_status(self.STOPSAVE_WAITING)
        self._append("[gui] will stop after the next model.pt save\n")
        self.root.after(self.STOPSAVE_POLL_MS, self._stopsave_tick)

    def _stopsave_tick(self):
        if not self.stop_save:
            return
        if not self._training_running():
            self._stopsave_done("[gui] training ended before the next save\n")
            return
        if self.stop_save.saved():
            self._stopsave_done("[gui] saved progress written - stopping training\n")
            self.stop()
            return
        self.root.after(self.STOPSAVE_POLL_MS, self._stopsave_tick)

    def _stopsave_done(self, msg):
        self.stop_save = None
        self._stopsave_status("")
        self._append(msg)

    def _stopsave_status(self, text):
        if hasattr(self, "l_stopsave"):
            self.l_stopsave.configure(text=text)
        if hasattr(self, "b_stopsave"):
            self.b_stopsave.configure(text="Cancel stop after save" if self.stop_save else "Stop after next save")
