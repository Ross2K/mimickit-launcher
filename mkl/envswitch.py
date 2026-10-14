"""Live num_envs change: wait for the next model.pt save, stop training, resume from it with the new env count.
MimicKit reads num_envs only at start, so a change needs a restart; doing it right after a save loses no training."""

import os


class CheckpointWatch:
    """Reports a model.pt save that happened after it was created: mtime/size changed, then held still for one poll
    (so a half-written file is never picked up)."""

    def __init__(self, path):
        self.path = path
        self.base = self._stat()
        self._seen = None

    def _stat(self):
        try:
            s = os.stat(self.path)
            return (s.st_mtime_ns, s.st_size)
        except OSError:
            return None

    def saved(self):
        now = self._stat()
        if now is None or now == self.base:
            self._seen = None
            return False
        if now == self._seen:
            return True
        self._seen = now
        return False


class EnvSwitchMixin:
    POLL_MS = 500

    def _envswitch_init(self):
        self.env_switch = None  # dict(n=new count, watch=CheckpointWatch, phase="wait"/"stopping")

    def _training_running(self):
        return self.run_kind == "train" and self.proc is not None and self.proc.poll() is None

    def change_envs_live(self):
        if self.env_switch:
            self._envswitch_done("[gui] live num_envs change cancelled\n")
            return
        if not self._training_running() or not self.run_dir:
            self._append("[gui] live num_envs change: no training is running - just set num_envs and start\n")
            return
        if getattr(self, "stop_save", None):
            self._append("[gui] 'Stop after next save' is armed - cancel it first\n")
            return
        n = int(self.v_envs.get())
        self.env_switch = dict(n=n, watch=CheckpointWatch(os.path.join(self.run_dir, "model.pt")), phase="wait")
        self._envswitch_status("Waiting for next checkpoint... (then restarts with %d envs)" % n)
        self._append("[gui] num_envs -> %d after the next model.pt save\n" % n)
        self.root.after(self.POLL_MS, self._envswitch_tick)

    def _envswitch_tick(self):
        sw = self.env_switch
        if not sw:
            return
        if sw["phase"] == "wait":
            if not self._training_running():
                self._envswitch_done("[gui] training ended before the next checkpoint - num_envs change cancelled\n")
                return
            if sw["watch"].saved():
                sw["phase"] = "stopping"
                self._envswitch_status("Checkpoint saved - stopping training...")
                self._append("[gui] checkpoint saved - stopping to restart with %d envs\n" % sw["n"])
                self.stop()
        elif self.proc is None or self.proc.poll() is not None:
            self.v_envs.set(sw["n"])
            self._envswitch_done("[gui] resuming with num_envs %d\n" % sw["n"])
            self.resume()
            return
        self.root.after(self.POLL_MS, self._envswitch_tick)

    def _envswitch_done(self, msg):
        self.env_switch = None
        self._envswitch_status("")
        self._append(msg)

    def _envswitch_status(self, text):
        if hasattr(self, "l_envswitch"):
            self.l_envswitch.configure(text=text)
        if hasattr(self, "b_envswitch"):
            self.b_envswitch.configure(text="Cancel env change" if self.env_switch else "Apply while training")
