"""'Stop after next save': let training finish its current iteration and write the next model.pt, then stop -
so nothing since the last save is lost.

a0.8.0 rework (it failed on Windows in a0.6.0/a0.7.0: training kept iterating past saves). The old loop
  * cleared its armed state BEFORE calling stop(), so if stop() failed nothing retried and nothing was shown;
  * ran inside a Tk after() callback with no try/except: one exception ended the loop for good, and under pythonw.exe
    Tk prints that traceback to a console that doesn't exist - the button kept saying 'armed' while nothing watched;
  * trusted a single signal (model.pt mtime+size held still for one 0.5 s poll) and never checked that the training
    process really ended after the stop;
  * wrote refusals ('no training is running', 'a num_envs change is waiting') only into the log panel.
Now: two independent save signals (model.pt changed and settled, or MimicKit's log.txt gained a row - it only writes
log.txt right before each save - followed by model.pt settling or a 30 s grace), the stop is verified (process gone),
retried once by command line if it isn't, every refusal / error is shown under the button (and returned to the phone),
and the poll loop can't die silently."""

import glob, os, time

from mimickit_util import log_exc
from mkl.envswitch import CheckpointWatch


class SaveWatch:
    """Reports the first model.pt save after it was created. Signals (either is enough):
    1. model.pt (mtime, size) changed and then held still for one poll;
    2. log.txt grew (MimicKit writes its log row only at save iterations, right before saving model.pt), then
       model.pt settled - or LOG_GRACE_S passed (a save of these small networks takes well under a second)."""

    LOG_GRACE_S = 30.0

    def __init__(self, run_dir, now=time.time):
        self.run_dir, self.now = run_dir, now
        self.model = CheckpointWatch(os.path.join(run_dir, "model.pt"))
        self.log_path = os.path.join(run_dir, "log.txt")
        self.log_size0 = self._log_size()
        self.log_grew_at = None
        self.why = ""

    def _log_size(self):
        try:
            return os.path.getsize(self.log_path)
        except OSError:
            return None

    def saved(self):
        if self.model.saved():
            self.why = "model.pt was rewritten"
            return True
        s = self._log_size()
        if self.log_grew_at is None and s is not None and self.log_size0 is not None and s > self.log_size0:
            self.log_grew_at = self.now()
        if self.log_grew_at is not None:
            if self.model._seen is None and self.now() - self.log_grew_at >= self.LOG_GRACE_S:
                self.why = "log.txt got a new save row %.0f s ago (model.pt change not visible)" % (
                    self.now() - self.log_grew_at)
                return True
        return False


def _norm(p):
    return os.path.normcase(os.path.abspath(os.path.normpath(p)))


def _out_dir_of(cmd):
    """The --out_dir value from a command line (quoted or not), or ''."""
    import shlex

    try:
        toks = shlex.split(cmd, posix=(os.name != "nt"))
    except ValueError:
        toks = cmd.split()
    for i, t in enumerate(toks):
        t = t.strip('"')
        if t == "--out_dir" and i + 1 < len(toks):
            return toks[i + 1].strip('"')
        if t.startswith("--out_dir="):
            return t.split("=", 1)[1].strip('"')
    return ""


def cmd_matches_run(cmd, run_dir, mk_dir=""):
    """True only if cmd runs MimicKit's run.py with --out_dir EXACTLY run_dir (after normalizing; a relative
    --out_dir is taken relative to the MimicKit folder). 'output/a' no longer matches 'output/a_resume2'."""
    if "run.py" not in cmd:
        return False
    od = _out_dir_of(cmd)
    if not od or not run_dir:
        return False
    want = _norm(run_dir)
    if os.path.isabs(od):
        return _norm(od) == want
    return any(_norm(os.path.join(base, od)) == want for base in filter(None, (mk_dir, os.getcwd())))


def _linux_children(pid):
    kids = {}
    for p in glob.glob("/proc/[0-9]*/stat"):
        try:
            f = open(p).read().rsplit(")", 1)[1].split()
            kids.setdefault(int(f[1]), []).append(int(p.split("/")[2]))
        except (OSError, IndexError, ValueError):
            continue
    out, todo = [], [pid]
    while todo:
        for k in kids.get(todo.pop(), []):
            out.append(k)
            todo.append(k)
    return out


def find_run_pids(run_dir, mk_dir="", root_pid=None):
    """PIDs of training processes for exactly this run: the launcher's own training PID (and its children) plus any
    python process running run.py with --out_dir == run_dir. Slow on Windows (PowerShell) - call from a worker
    thread, never from the Tk thread. Used only when the normal stop didn't end training."""
    out = []
    if root_pid:
        out.append(int(root_pid))
        if os.name != "nt":
            out += _linux_children(int(root_pid))
    if not run_dir:
        return sorted(set(out))
    if os.name == "nt":
        import subprocess

        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
                 "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
                capture_output=True, text=True, timeout=20, creationflags=0x08000000)
            rows = r.stdout.splitlines()
        except Exception as e:
            log_exc("stopsave: listing processes", e)
            return sorted(set(out))
        for row in rows:
            pid, _, cmd = row.partition("\t")
            if pid.strip().isdigit() and cmd_matches_run(cmd, run_dir, mk_dir):
                out.append(int(pid))
        return sorted(set(out))
    for p in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            raw = open(p, "rb").read().split(b"\0")
        except OSError:
            continue
        cmd = " ".join(__import__("shlex").quote(x.decode("utf-8", "replace")) for x in raw if x)
        if "mimickit" in cmd.replace("\\", "/") and cmd_matches_run(cmd, run_dir, mk_dir):
            out.append(int(p.split("/")[2]))
    return sorted(set(out))


class StopAfterSaveMixin:
    STOPSAVE_POLL_MS = 500
    STOPSAVE_WAITING = "Will stop after next save..."
    STOP_VERIFY_S = 20  # after the stop: training must be gone within this time, else retry once, then say so
    REFUSAL_SHOW_MS = 20000

    def _stopsave_init(self):
        self.stop_save = None  # SaveWatch while armed
        self.stopsave_phase = ""  # "" | "wait" | "stopping"
        self.stopsave_msg = ""  # last refusal / error, shown under the button and on the phone

    # ---------------------------------------------------------------- public
    def stop_after_save(self, origin="PC"):
        """Arm (or, pressed again, cancel) the stop after the next model.pt save. Returns (ok, plain message);
        a refusal is logged and shown under the button. Never raises."""
        try:
            return self._stopsave_toggle(origin)
        except Exception as e:
            log_exc("stop after save", e)
            return self._stopsave_refuse("Couldn't set 'Stop after next save': %s: %s" % (type(e).__name__, e))

    def _stopsave_toggle(self, origin):
        if self.stop_save:
            self._stopsave_done("[gui] stop after next save cancelled (%s)\n" % origin)
            return True, "Stop after next save cancelled."
        if not self._training_running():
            return self._stopsave_refuse("Not set: no training is running.")
        if not self.run_dir or not os.path.isdir(self.run_dir):
            return self._stopsave_refuse(
                "Not set: the launcher doesn't know where this run saves (output folder missing). Use STOP instead.")
        if getattr(self, "env_switch", None):
            return self._stopsave_refuse("Not set: a num_envs change is already waiting for the next save - cancel it first.")
        self.stop_save = SaveWatch(self.run_dir)
        self.stopsave_phase = "wait"
        self.stopsave_msg = ""
        self._stopsave_status(self.STOPSAVE_WAITING)
        self._append("[gui] will stop after the next model.pt save (%s; watching %s)\n" % (origin, self.run_dir))
        self.root.after(self.STOPSAVE_POLL_MS, self._stopsave_tick)
        return True, "Will stop after the next save."

    # ---------------------------------------------------------------- loop
    def _stopsave_tick(self):
        """Poll loop. Wrapped so an exception is shown + logged and the loop keeps going (it used to die silently)."""
        if not self.stop_save:
            return
        try:
            again = self._stopsave_step()
        except Exception as e:
            log_exc("stop after save: poll", e)
            self.stopsave_msg = "Error while waiting for the save: %s: %s (still watching)" % (type(e).__name__, e)
            self._append("[gui] %s\n" % self.stopsave_msg)
            self._stopsave_status(self.STOPSAVE_WAITING, error=self.stopsave_msg)
            again = True
        if again and self.stop_save:
            self.root.after(self.STOPSAVE_POLL_MS, self._stopsave_tick)

    def _stopsave_step(self):
        w = self.stop_save
        if self.stopsave_phase == "wait":
            if not self._training_running():
                self._stopsave_done("[gui] training ended before the next save - stop after save cleared\n")
                return False
            if not w.saved():
                return True
            self._append("[gui] saved progress written (%s) - stopping training\n" % w.why)
            self.stopsave_phase = "stopping"
            self._stopsave_status("Saved - stopping training...")
            self._stop_deadline = time.time() + self.STOP_VERIFY_S
            self._stop_retried = False
            self.stop()
            return True
        # phase "stopping": verify that the training process is really gone
        if not self._training_running():
            self._stopsave_done("[gui] training stopped after the save (verified: process ended)\n")
            return False
        if time.time() < self._stop_deadline:
            return True
        if not self._stop_retried:
            self._stop_retried = True
            self._stop_deadline = time.time() + self.STOP_VERIFY_S
            self._stopsave_find_kill()
            return True
        msg = "Training did not stop after the save. Press STOP (details in the log)."
        self._stopsave_done("[gui] %s\n" % msg)
        self._stopsave_refuse(msg, log=False)
        return False

    def _stopsave_find_kill(self):
        """Retry: list the run's processes in a worker thread (PowerShell can take seconds - the window must not
        freeze), then stop + kill on the Tk thread."""
        import threading

        root_pid = getattr(getattr(self, "proc", None), "pid", None)
        mk = getattr(self, "_mk_cache", "") or ""
        res = {}

        def work():
            try:
                res["pids"] = find_run_pids(self.run_dir, mk, root_pid)
            except Exception as e:
                log_exc("stop after save: listing processes", e)
                res["pids"] = [root_pid] if root_pid else []

        t = threading.Thread(target=work, daemon=True, name="stopsave-pids")
        t.start()

        def check():
            if t.is_alive():
                self.root.after(100, check)
                return
            pids = res.get("pids", [])
            self._append("[gui] training still running %d s after the stop - stopping again (PIDs %s)\n"
                         % (self.STOP_VERIFY_S, ", ".join(map(str, pids)) or "-"))
            self.stop()
            for p in pids:
                try:
                    self._kill(p, "")
                except Exception as e:
                    log_exc("stop after save: retry kill", e)

        self.root.after(50, check)

    # ---------------------------------------------------------------- state / display
    def _stopsave_refuse(self, msg, log=True):
        """Every refusal: logged, shown under the button for a while, readable by the phone."""
        self.stopsave_msg = msg
        if log:
            self._append("[gui] stop after next save: %s\n" % msg)
        self._stopsave_status("", error=msg)
        try:
            self.root.after(self.REFUSAL_SHOW_MS, self._stopsave_clear_msg, msg)
        except Exception as e:
            log_exc("stop after save: refusal timer", e)
        return False, msg

    def _stopsave_clear_msg(self, msg):
        if self.stopsave_msg == msg and not self.stop_save:
            self.stopsave_msg = ""
            self._stopsave_status("")

    def _stopsave_done(self, msg):
        self.stop_save = None
        self.stopsave_phase = ""
        self._stopsave_status("")
        self._append(msg)

    def _stopsave_status(self, text, error=""):
        if hasattr(self, "l_stopsave"):
            self.l_stopsave.configure(text=error or text, style="Err.TLabel" if error else "Dim.TLabel")
            if error or text:
                if not self.l_stopsave.winfo_manager():
                    self.l_stopsave.pack(side="left", padx=(12, 0))
            else:
                self.l_stopsave.pack_forget()
        if hasattr(self, "b_stopsave"):
            self.b_stopsave.configure(text="Cancel stop after save" if self.stop_save else "Stop after next save")
        if hasattr(self, "_status_refresh"):
            try:
                self._status_refresh()
            except Exception as e:
                log_exc("stop after save: banner", e)
