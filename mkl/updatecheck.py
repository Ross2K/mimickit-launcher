"""a0.9.2 (A1): automatic update check - on launch and every few hours (default on, interval in About > Updates).

It only LOOKS: a small 'Update aX.Y.Z available' notice on the PC (Settings row, click it) and on the phone (one line).
It never downloads or installs anything by itself.
  * public build: reads the public GitHub releases of curelessSky/mimickit-launcher (no key needed);
  * Z build: the Updates plugin (launcher_updater.py) registers app.update_checker, which uses the stored read-only
    access key and the signed-manifest check - the same check as 'Check for updates', minus any install.
Offline / GitHub errors: no popup, no notice - one log line, and it tries again at the next interval."""

import json, os, re, threading, time, urllib.request, webbrowser

from mkl import core

PUBLIC_REPO = "curelessSky/mimickit-launcher"
API = "https://api.github.com"
DEFAULT_HOURS = 6
MIN_HOURS, MAX_HOURS = 1, 168
STARTUP_DELAY_MS = 8000
TICK_MS = 10 * 60 * 1000  # looks every 10 min whether the interval has passed (cheap: no network unless due)


def parse_version(v):
    m = re.match(r"a?(\d+)\.(\d+)\.(\d+)", str(v or "").strip().lstrip("v"))
    return tuple(int(x) for x in m.groups()) if m else None


def newer(a, b):
    pa, pb = parse_version(a), parse_version(b)
    return bool(pa and pb and pa > pb)


def cfg(s):
    """Settings (s['update']): auto_check (default True), check_hours (default 6, clamped 1-168)."""
    u = (s or {}).get("update") or {}
    try:
        h = float(u.get("check_hours", DEFAULT_HOURS))
    except (TypeError, ValueError):
        h = DEFAULT_HOURS
    if h != h:  # nan
        h = DEFAULT_HOURS
    return dict(auto=bool(u.get("auto_check", True)), hours=max(MIN_HOURS, min(MAX_HOURS, h)))


def due(last, hours, now=None):
    return last is None or (now if now is not None else time.time()) - last >= hours * 3600.0


def latest_public(releases, current):
    """Newest non-draft, non-prerelease release newer than current -> dict(version, url) or None."""
    best = None
    for r in releases or []:
        if not isinstance(r, dict) or r.get("draft") or r.get("prerelease"):
            continue
        tag = r.get("tag_name", "")
        if newer(tag, current) and (best is None or newer(tag, best["version"])):
            best = dict(version=tag, url=r.get("html_url") or "https://github.com/%s/releases" % PUBLIC_REPO)
    return best


def fetch_public(repo=PUBLIC_REPO, api=API, timeout=15):
    req = urllib.request.Request("%s/repos/%s/releases?per_page=10" % (api.rstrip("/"), repo), headers={
        "Accept": "application/vnd.github+json", "User-Agent": "MimicKitLauncher-update-check"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class AutoUpdateMixin:
    """upd_notice: None or dict(version, url, z). Never installs."""

    def _autoupd_init(self):
        self.upd_notice = None
        self.upd_last = None  # time.time() of the last attempt (ok or failed)
        self.upd_last_text = "never"
        self._upd_busy = False
        try:
            self.root.after(STARTUP_DELAY_MS, self._autoupd_tick)
        except Exception as e:
            core.log_exc("update check: scheduling", e)

    def _autoupd_tick(self):
        try:
            c = cfg(self.s)
            if c["auto"] and due(self.upd_last, c["hours"]) and not os.environ.get("MIMICKIT_NO_UPDATE_CHECK"):
                self.update_check_now(manual=False)
        except Exception as e:
            core.log_exc("update check: tick", e)
        try:
            self.root.after(TICK_MS, self._autoupd_tick)
        except Exception:
            return  # the window is closing

    def _public_check(self):
        return latest_public(fetch_public(), core.VERSION)

    def update_check_now(self, manual=True):
        """Start one check in a worker thread. Returns False if one is already running."""
        if self._upd_busy:
            return False
        self._upd_busy = True
        self.upd_last = time.time()
        checker = getattr(self, "update_checker", None) or self._public_check

        def work():
            res, err = None, None
            try:
                res = checker()
            except Exception as e:  # offline, GitHub down, no key...: silent, one log line
                err = e
                core.log_exc("update check", e)
                self.q.put("[update] automatic check didn't work (%s) - trying again later\n" % (
                    str(e)[:160] or type(e).__name__) if not manual else
                    "[update] check didn't work: %s\n" % (str(e)[:200] or type(e).__name__))
            finally:
                self._upd_busy = False
            self.rq.put(lambda: self._autoupd_show(res, err, manual))

        threading.Thread(target=work, daemon=True, name="update-check").start()
        return True

    def _autoupd_show(self, res, err=None, manual=False):
        stamp = time.strftime("%Y-%m-%d %H:%M")
        if err is None:
            old = self.upd_notice
            self.upd_notice = dict(res, z=bool(getattr(self, "update_checker", None))) if res else None
            self.upd_last_text = stamp + (" - %s available" % res["version"] if res else " - up to date")
            if res and (not old or old.get("version") != res["version"]):
                self._append("[update] %s is available - click the notice in the Settings row (nothing is installed "
                             "automatically)\n" % res["version"])
            elif manual and not res:
                self._append("[update] no newer version than %s\n" % core.VERSION)
        else:
            self.upd_last_text = stamp + " - couldn't check (offline?)"
        self._autoupd_paint()

    def _autoupd_paint(self):
        lab = getattr(self, "l_update", None)
        if lab is not None:
            try:
                if self.upd_notice:
                    lab.configure(text="Update %s available" % self.upd_notice["version"])
                    lab.grid()
                else:
                    lab.configure(text="")
                    lab.grid_remove()
            except Exception as e:
                core.log_exc("update check: notice", e)
        st = getattr(self, "_upd_about_status", None)
        if st is not None:
            try:
                st.configure(text="Last check: %s" % self.upd_last_text)
            except Exception:
                self._upd_about_status = None

    def open_update_notice(self, _e=None):
        n = self.upd_notice
        if not n:
            return
        for p in getattr(self, "plugins", []):  # Z: the Updates dialog (install only from there, with a yes)
            if hasattr(p, "open_dialog") and hasattr(p, "u"):
                p.open_dialog()
                return
        try:
            webbrowser.open(n.get("url") or "https://github.com/%s/releases" % PUBLIC_REPO)
        except Exception as e:
            core.log_exc("update check: opening the release page", e)

    def _autoupd_snapshot(self, snap):
        n = getattr(self, "upd_notice", None)
        snap["upd_notice"] = dict(version=n["version"], url=n.get("url", ""), z=bool(n.get("z"))) if n else None

    def build_update_settings(self, parent):
        """About > Updates: on/off + interval + Check now + last result."""
        import tkinter as tk
        from tkinter import ttk

        c = cfg(self.s)
        lf = ttk.LabelFrame(parent, text="Updates", padding=6)
        v_on = tk.BooleanVar(value=c["auto"])
        v_h = tk.StringVar(value=("%g" % c["hours"]))

        def save(*_):
            u = self.s.setdefault("update", {})
            u["auto_check"] = bool(v_on.get())
            try:
                u["check_hours"] = max(MIN_HOURS, min(MAX_HOURS, float(v_h.get())))
            except (TypeError, ValueError):
                return
            self._save_settings_only()

        cb = ttk.Checkbutton(lf, text="Check for updates automatically (on launch and every", variable=v_on, command=save)
        cb.grid(row=0, column=0, sticky="w")
        sp = ttk.Spinbox(lf, from_=MIN_HOURS, to=MAX_HOURS, increment=1, textvariable=v_h, width=5, command=save)
        sp.grid(row=0, column=1, padx=3)
        sp.bind("<FocusOut>", save)
        ttk.Label(lf, text="hours)").grid(row=0, column=2, sticky="w")
        ttk.Button(lf, text="Check now", command=lambda: self.update_check_now(manual=True)).grid(row=0, column=3, padx=8)
        ttk.Label(lf, text="Only shows a notice (PC Settings row + phone). Nothing is ever installed automatically.",
                  style="Dim.TLabel").grid(row=1, column=0, columnspan=4, sticky="w")
        self._upd_about_status = ttk.Label(lf, text="Last check: %s" % self.upd_last_text, style="Dim.TLabel")
        self._upd_about_status.grid(row=2, column=0, columnspan=4, sticky="w")
        self._upd_vars = (v_on, v_h, save)
        return lf
