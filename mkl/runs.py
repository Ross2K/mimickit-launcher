# MimicKit Launcher - phone 'Runs' + 'Patches' controls (a0.8.0): start a new training, continue from an earlier
# run, apply / revert MimicKit patches. Copyright (C) 2026 Ross2K. SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0 (see LICENSE).
"""The phone only ever sends names and keys from the lists the PC published; everything is validated again on the
PC (server thread, then once more on the GUI thread right before acting). Same states and refusals as the PC buttons:
nothing starts while something runs, a used output folder needs an explicit 'overwrite', patches that change
MimicKit files (all of them touch the sim) are refused while training runs. Every refusal is logged."""

import hashlib, os, re, time
import tkinter

import mimickit_patches as MP
from mkl import core
from mkl.core import base_of, chain_folders, chain_total, hms, run_chain

OUT_RE = re.compile(r"^output/[A-Za-z0-9_][A-Za-z0-9_.-]{0,80}(/[A-Za-z0-9_][A-Za-z0-9_.-]{0,80}){0,3}$")
MAX_RUNS = 30
PATCH_CACHE_S = 30


def _key(path):
    return hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode()).hexdigest()[:12]


def validate_out(out):
    """Output folder from the phone: inside MimicKit's output/, plain names only."""
    if not isinstance(out, str) or not OUT_RE.match(out.strip()):
        return None, "Output folder must look like output/my_run (letters, digits, _ . -; no ..)."
    out = out.strip()
    if any(p in ("..", ".") for p in out.split("/")) or os.path.basename(out).startswith("_launcher"):
        return None, "That output folder isn't allowed."
    return out, None


def validate_run_params(action, p, choices):
    """Pure check of a phone request against what the PC published. -> (clean, None) or (None, reason)."""
    import mimickit_remote as R

    if not isinstance(p, dict):
        return None, "Bad request."
    out = {}
    if action in ("start_train", "continue_run"):
        if p.get("config") not in choices["configs"]:
            return None, "Unknown training config - refresh the page."
        out["config"] = p["config"]
        if "num_envs" in p:
            t, why = R.validate_tweaks({"num_envs": p["num_envs"]})
            if why:
                return None, why
            out["num_envs"] = t["num_envs"]
        o, why = validate_out(p.get("out"))
        if why:
            return None, why
        out["out"] = o
    if action == "start_train":
        if not isinstance(p.get("overwrite", False), bool):
            return None, "overwrite must be true or false."
        out["overwrite"] = bool(p.get("overwrite", False))
    if action == "continue_run":
        if p.get("src") not in choices["runs"]:
            return None, "Unknown run - refresh the page."
        out["src"] = p["src"]
    if action == "patch":
        pt = choices["patches"].get(p.get("name"))
        if not pt:
            return None, "Unknown patch."
        if p.get("op") not in ("apply", "revert"):
            return None, "op must be apply or revert."
        if p["op"] == "revert" and not pt.get("can_revert"):
            return None, "This patch can't be reverted from here."
        out.update(name=p["name"], op=p["op"])
    return out, None


class RunsMixin:
    # ---------------------------------------------------------------- what the phone may choose (GUI thread)
    def _phone_patches(self, force=False):
        """[{name, title, why, status, can_revert, touches_sim}] - MimicKit patches + phone-enabled profile ACTIONS."""
        c = getattr(self, "_patch_cache", None)
        if c and not force and time.time() - c[0] < PATCH_CACHE_S:
            return c[1]
        mk = self.mk()
        out = []
        for name, p in MP.PATCHES.items():
            st = MP.status(mk, name) if mk else "missing"
            out.append(dict(name=name, title=p["title"], why=p["why"].replace("\n", " "), status=st,
                            can_revert=True, touches_sim=True))
        for a in core.ACTIONS:
            ph = a.get("phone")
            if not ph:
                continue
            try:
                st = ph["status"](self)
            except Exception as e:
                core.log_exc("patch status %s" % ph["name"], e)
                st = "unknown"
            out.append(dict(name=ph["name"], title=ph.get("title") or a["text"], why=(a.get("help") or "").replace("\n", " "),
                            status=st, can_revert=bool(ph.get("revert")), touches_sim=ph.get("touches_sim", True)))
        self._patch_cache = (time.time(), out)
        return out

    def _phone_runs(self):
        """Run chains under <MimicKit>/output with a model.pt, newest first (keys only go to the phone)."""
        mk = self.mk()
        root = os.path.join(mk, "output") if mk else ""
        chains = {}
        try:
            names = os.listdir(root) if root and os.path.isdir(root) else []
        except OSError:
            names = []
        for n in names:
            d = os.path.join(root, n)
            if n.startswith("_launcher") or not os.path.isdir(d):
                continue
            m = os.path.join(d, "model.pt")
            if not os.path.isfile(m):
                continue
            b = base_of(d)
            t = os.path.getmtime(m)
            if b not in chains or t > chains[b][1]:
                chains[b] = (d, t)
        runs = []
        for b, (d, t) in sorted(chains.items(), key=lambda kv: -kv[1][1])[:MAX_RUNS]:
            try:
                tot, ses = chain_total(run_chain(d))
            except Exception as e:
                core.log_exc("run total %s" % d, e)
                tot, ses = 0, 0
            runs.append(dict(key=_key(b), path=b, name=os.path.relpath(b, mk).replace(os.sep, "/"),
                             saved=time.strftime("%b %d %H:%M", time.localtime(t)), total=hms(tot), sessions=ses))
        return runs

    def _runs_snapshot(self, snap):
        runs = self._phone_runs()
        self._runs_paths = {r["key"]: r["path"] for r in runs}
        it = self._item("train") if hasattr(self, "train_items") else None
        snap["runs_ui"] = dict(
            configs=[i["name"] for i in getattr(self, "train_items", [])],
            helps={i["name"]: (i.get("help") or "")[:200] for i in getattr(self, "train_items", [])},
            outs={i["name"]: i.get("out") or "" for i in getattr(self, "train_items", [])},
            config=it["name"] if it else "",
            num_envs=self._envs_or_0(),
            out=self.v_out.get().strip() if hasattr(self, "v_out") else "",
            runs=[{k: v for k, v in r.items() if k != "path"} for r in runs],
            patches=self._phone_patches(),
            busy=bool(self.proc and self.proc.poll() is None),
            busy_kind=getattr(self, "run_kind", "") if self.proc and self.proc.poll() is None else "",
            msg=getattr(self, "runs_msg", ""),
            missing={i["name"]: i["missing"] for i in getattr(self, "train_items", []) if i.get("missing")},
        )

    def _envs_or_0(self):
        """The parallel-sims field as a number; text like '64x' gives 0 (shown on the PC as a hint, never a crash)."""
        try:
            return max(0, int(str(self.v_envs.get()).strip() or 0)) if hasattr(self, "v_envs") else 0
        except (ValueError, TypeError, tkinter.TclError):
            return 0

    def _runs_choices(self):
        snap = getattr(self, "snap", None) or {}
        ui = snap.get("runs_ui")
        if not ui:  # before the first snapshot: the lists come from Tk vars - never read them off the GUI thread
            return None
        return dict(configs=list(ui.get("configs") or []), runs=dict(getattr(self, "_runs_paths", {}) or {}),
                    patches={p["name"]: p for p in ui.get("patches") or []})

    # ---------------------------------------------------------------- server thread: validate, refuse or queue
    def _remote_runs_action(self, action, params):
        ch = self._runs_choices()
        if ch is None:
            return 503, "The PC is starting up - try again in a few seconds."
        clean, why = validate_run_params(action, params, ch)
        if why:
            return 400, why
        busy = self.proc is not None and self.proc.poll() is None
        miss = ((getattr(self, "snap", None) or {}).get("runs_ui") or {}).get("missing") or {}
        if action in ("start_train", "continue_run") and clean["config"] in miss:
            return 409, "%s is not installed yet - %s" % (clean["config"], miss[clean["config"]])
        if action in ("start_train", "continue_run"):
            if busy or self._training_running():
                return 409, self._busy_text() + " Start refused."
            with self._remote_lock:
                if getattr(self, "_phone_start_pending", False):
                    return 409, "A start from the phone is already on its way - refused (counted once)."
                self._phone_start_pending = True
            self.rq.put(lambda: self._phone_start_gui(action, clean))
            return 202, ("Starting a new training run on the PC: %s -> %s" % (clean["config"], clean["out"])
                         if action == "start_train" else "Continuing from the chosen run on the PC.")
        if action == "patch":
            why = self._patch_refusal(need_mk=False)
            if why:
                return 409, why
            self.rq.put(lambda: self._phone_patch_gui(clean))
            return 202, "%s %s on the PC..." % ("Applying" if clean["op"] == "apply" else "Reverting", clean["name"])
        return 400, "Unknown action."

    # ---------------------------------------------------------------- GUI thread: check again, then act
    def _runs_note(self, msg, refused=False):
        self.runs_msg = msg
        self._append("[remote] %s%s\n" % ("refused: " if refused else "", msg))
        try:
            self._progress_tick(force=True)
        except Exception as e:
            core.log_exc("runs note refresh", e)

    def _phone_start_gui(self, action, p):
        try:
            if self.proc is not None and self.proc.poll() is None:
                return self._runs_note("start refused - something started on the PC meanwhile", True)
            if p["config"] not in [i["name"] for i in self.train_items if not i.get("missing")]:
                return self._runs_note("start refused - config %s is gone (rescan?)" % p["config"], True)
            self.v_train.set(p["config"])
            self._train_changed()
            if "num_envs" in p:
                self.v_envs.set(p["num_envs"])
            self.v_out.set(p["out"])
            if action == "start_train":
                ok = self.train(overwrite=p["overwrite"])
                if not ok:
                    out = self.outdir_abs(p["out"])
                    why = ("%s already has an earlier run - tick 'overwrite' or pick another folder" % p["out"]
                           if os.path.isdir(out) and os.listdir(out) and not p["overwrite"] else "the PC refused the start (see its log)")
                    return self._runs_note("start refused - " + why, True)
                return self._runs_note("started %s -> %s (from the phone)" % (p["config"], p["out"]))
            src = self._runs_paths.get(p["src"]) if getattr(self, "_runs_paths", None) else None
            if not src:
                return self._runs_note("continue refused - that run is no longer listed", True)
            if not self._check("train"):
                return self._runs_note("continue refused - the PC is busy or MimicKit is missing", True)
            plan, err = self._continue_plan(src)
            if err:
                return self._runs_note("continue refused - %s" % err[1], True)
            self._continue_start(plan)
            self._runs_note("continuing %s from %s -> %s (from the phone)" % (
                p["config"], os.path.relpath(plan["src_dir"], self.mk()), plan["new_rel"]))
        finally:
            self._phone_start_pending = False

    def _busy_text(self):
        """Names what is actually running: 'A preview is running. Close it first.' etc."""
        if self._training_running():
            return "Training is running. Stop it first (or use Stop after next save)."
        kind = getattr(self, "run_kind", "") or ""
        return {"view": "The clip viewer is running. Close it first.",
                "watch": "Watch is running. Close it first.",
                "preview": "A preview is running. Close it first."}.get(kind, "Something is running on the PC (%s). "
                                                                          "Close it first." % (kind or "a run"))

    def _patch_refusal(self, need_mk=True):
        """Same rule on the PC and the phone: MimicKit files are not changed while anything of MimicKit runs."""
        if self._training_running() or (getattr(self, "proc", None) is not None and self.proc.poll() is None):
            return "Patches change MimicKit's files. " + self._busy_text()
        if need_mk and (not self.mk() or not os.path.isfile(os.path.join(self.mk(), "mimickit", "run.py"))):
            return "MimicKit folder not set (no mimickit/run.py)."
        return None

    def _phone_patch_gui(self, p):
        why = self._patch_refusal()
        if why:
            return self._runs_note("patch %s refused - %s" % (p["name"], why), True)
        try:
            if p["name"] in MP.PATCHES:
                msg = (MP.apply if p["op"] == "apply" else MP.revert)(self.mk(), p["name"])
            else:
                ph = next(a["phone"] for a in core.ACTIONS if (a.get("phone") or {}).get("name") == p["name"])
                msg = ph[p["op"]](self)
        except Exception as e:
            core.log_exc("phone patch %s" % p["name"], e)
            msg = "failed: %s" % e
            self._patch_cache = None
            return self._runs_note("patch %s %s %s" % (p["name"], p["op"], msg), True)
        self._patch_cache = None
        self._append("[patch] %s: %s (from the phone)\n" % (p["name"], msg))
        self._runs_note("patch %s: %s" % (p["name"], msg))
