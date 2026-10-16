"""a0.9.3: 'Pause training for preview' (opt-in, default off).

With it ticked, a preview started while training runs goes:
  saving    -> the existing 'Stop after next save' path (checkpoint written, training stopped and verified)
  rendering -> the preview renders with the GPU free (latest model)
  resuming  -> the existing Resume (latest checkpoint, same run chain: a new _resumeN folder)
The render being stopped or failing still resumes. A failed save / resume shows a notice on the PC (log + red line in
the preview row) and on the phone - training is never left stopped silently. If YOU press the training STOP (PC or
phone) at any point, it is not resumed. Phone: only through the PIN-gated control 'render_pause' (the open
/api/render never pauses training)."""

import time

from mkl.core import log_exc

PP_POLL_MS = 500
RESUME_VERIFY_S = 10


class PausePreviewMixin:
    def _pp(self):
        return getattr(self, "pp", None)

    def _pp_begin(self, it, model, origin, clips, layout, all_clips):
        """GUI thread. Arm the pause; the preview starts once training has saved and stopped."""
        self.pp = dict(phase="saving", origin=origin, clips=clips, layout=layout, all_clips=all_clips,
                       paused=False, user_stopped=False, started=time.time(),
                       train=self.v_train.get(), out=self.v_out.get().strip())
        if getattr(self, "stop_save", None):  # you already asked for 'Stop after next save': keep it, never resume
            self.pp["user_stopped"] = True
            self._pp_notice("'Stop after next save' was already set - the preview renders after that stop; training "
                            "will not be resumed (you asked it to stop).")
            self.root.after(PP_POLL_MS, self._pp_tick)
            return True
        ok, msg = self.stop_after_save("pause for preview (%s)" % origin)
        if not ok:
            self.pp = None
            self._pp_notice("Couldn't pause training for the preview (%s) - training keeps running; the preview "
                            "renders alongside it." % msg, error=True)
            return self._pp_start_render(it, model, origin, clips, layout, all_clips)
        self._pp_notice("Pausing training for the preview: waiting for the next save...")
        self.root.after(PP_POLL_MS, self._pp_tick)
        return True

    def _pp_user_stop(self):
        """Called from stop(): a STOP that isn't the save path's own one is the user's -> never auto-resume."""
        p = self._pp()
        if p and not getattr(self, "_stop_from_save", False) and not p["user_stopped"]:
            p["user_stopped"] = True
            self._append("[gui] pause for preview: you pressed STOP - training will NOT be resumed after the preview\n")
        elif p and getattr(self, "_stop_from_save", False):
            p["paused"] = True

    def _pp_start_render(self, it, model, origin, clips, layout, all_clips):
        self._pp_bypass = True
        try:
            return self._start_preview(it, model, origin=origin, clips=clips, layout=layout, all_clips=all_clips,
                                       pause=False)
        finally:
            self._pp_bypass = False

    def _pp_tick(self):
        p = self._pp()
        if not p:
            return
        try:
            again = self._pp_step(p)
        except Exception as e:
            log_exc("pause for preview", e)
            again = self._pp_fail_safe("Pause for preview hit an error: %s: %s" % (type(e).__name__, e))
        if again and self._pp() is p:
            self.root.after(PP_POLL_MS, self._pp_tick)

    def _pp_fail_safe(self, why):
        """Never leave training stopped silently: try to resume (unless the user stopped it), else say so loudly."""
        p = self._pp()
        if p and p["paused"] and not p["user_stopped"] and not self._training_running():
            p["phase"] = "resuming"
            self._pp_notice(why + " - resuming training.", error=True)
            return True
        self.pp = None
        self._pp_notice(why, error=True)
        return False

    def _pp_step(self, p):
        if p["phase"] == "saving":
            if getattr(self, "stop_save", None):
                return True  # still waiting for the save / the verified stop
            running = self._training_running()
            it = self._item("train")
            model = self.v_model.get().strip() or self._latest_model()
            if running:  # stop-after-save cancelled, or the stop didn't work
                self.pp = None
                why = getattr(self, "stopsave_msg", "") or "the stop after save was cancelled"
                self._pp_notice("Training was not paused (%s) - it keeps running; the preview renders alongside it."
                                % why, error=True)
                if it and model:
                    self._pp_start_render(it, model, p["origin"], p["clips"], p["layout"], p["all_clips"])
                return False
            if not p["paused"] and not p["user_stopped"]:
                p["user_stopped"] = True  # ended on its own (finished / crashed) - not ours to restart
                self._append("[gui] pause for preview: training ended on its own before the save - it will not be "
                             "resumed automatically\n")
            p["phase"] = "rendering"
            self._pp_notice("Training paused (saved) - rendering the preview..." if p["paused"] else
                            "Rendering the preview (training is stopped).")
            if it and model:
                self._pp_start_render(it, model, p["origin"], p["clips"], p["layout"], p["all_clips"])
            if not self._preview_alive():
                self._append("[gui] pause for preview: the preview didn't start\n")
                p["phase"] = "resuming"
            return True
        if p["phase"] == "rendering":
            if self._preview_alive():
                return True
            p["phase"] = "resuming"
            return True
        if p["phase"] == "resuming":
            if p["user_stopped"]:
                self.pp = None
                self._pp_notice("Preview done. Training stays stopped (you pressed STOP).")
                return False
            if self._training_running():
                self.pp = None
                self._pp_notice("Preview done - training was already running again.")
                return False
            if self.v_train.get() != p["train"] or self.v_out.get().strip() != p["out"]:
                self.pp = None
                self._pp_notice("Training was NOT resumed: the training config / output folder was changed during "
                                "the preview. Press 'Resume training' yourself.", error=True)
                return False
            self._append("[gui] pause for preview: preview finished - resuming training from the latest save\n")
            try:
                self.resume()
            except Exception as e:
                log_exc("pause for preview: resume", e)
            p["phase"] = "verify"
            p["verify_until"] = time.time() + RESUME_VERIFY_S
            return True
        if p["phase"] == "verify":
            if self._training_running():
                if time.time() >= p["verify_until"]:
                    self.pp = None
                    self._pp_notice("Preview done - training resumed from the latest save.")
                    return False
                return True
            self.pp = None
            self._pp_notice("Training could NOT be resumed after the preview. Press 'Resume training' (details in "
                            "the log).", error=True)
            return False
        return False

    def _preview_alive(self):
        pp = getattr(self, "preview_proc", None)
        return bool(pp is not None and pp.poll() is None)

    def _pp_notice(self, msg, error=False):
        self.pp_msg = dict(text=msg, error=bool(error), at=time.time())
        self._append("[gui] %s%s\n" % ("PAUSE FOR PREVIEW: " if error else "pause for preview: ", msg))
        lab = getattr(self, "l_pause", None)
        if lab is not None:
            try:
                lab.configure(text=msg, style="Err.TLabel" if error else "Dim.TLabel")
            except Exception as e:
                log_exc("pause for preview: notice", e)

    def _pp_snapshot(self, snap):
        p = self._pp()
        m = getattr(self, "pp_msg", None)
        snap["pause_preview"] = dict(
            setting=bool(getattr(self, "v_pause", None) and self.v_pause.get()),
            phase=p["phase"] if p else "", msg=(m or {}).get("text", ""), error=bool((m or {}).get("error")),
            at=(m or {}).get("at", 0))
