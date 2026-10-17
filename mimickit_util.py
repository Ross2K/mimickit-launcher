# MimicKit Launcher - shared helpers: atomic JSON files and logging of swallowed errors.
# Copyright (C) 2026 curelessSky. SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0 (see LICENSE).
"""save_json(): write to a temp file, fsync, keep the previous good file as <name>.bak, then os.replace() -
a crash or full disk mid-write never leaves a half-written file. load_json(): raises JsonDamaged for a corrupt
file (callers decide), load_json_or(): returns a default and logs instead.
log_exc(): record an exception that the caller deliberately ignores (to the launcher error log, or stderr in a helper
process). Registered secrets (webhook URLs, bot tokens, dashboard token) are masked in everything it writes.
"""

import datetime, json, os, re, shutil, sys, threading, traceback

BAK = ".bak"
_lock = threading.Lock()
_log_path = None
_secrets = set()
_seen = {}
MAX_LOG = 1_000_000


class JsonDamaged(ValueError):
    """The file exists but isn't valid JSON (or isn't readable as text)."""


def load_json(path):
    """Parsed JSON, or FileNotFoundError if missing, or JsonDamaged if unreadable/corrupt."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise
    except (ValueError, UnicodeDecodeError) as e:
        raise JsonDamaged("%s: %s" % (path, e)) from e


def load_json_or(path, default=None, where=""):
    """Parsed JSON, or `default` when missing or damaged (damaged is logged)."""
    try:
        return load_json(path)
    except FileNotFoundError:
        return default
    except (JsonDamaged, OSError) as e:
        log_exc(where or ("reading " + os.path.basename(path)), e)
        return default


def save_json(path, obj, backup=True, indent=1):
    """Atomic write; the previous file (if it parses) is kept as path + '.bak'."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = "%s.tmp%d" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=indent)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # some filesystems can't fsync; os.replace below is still atomic
    except BaseException:
        try:
            os.remove(tmp)  # failed write: the real file was never touched
        except OSError:
            pass
        raise
    if backup and os.path.isfile(path):
        try:
            load_json(path)  # only a good file becomes the backup
            shutil.copy2(path, path + BAK)
        except (JsonDamaged, OSError) as e:
            log_exc("keeping a backup of " + os.path.basename(path), e)
    os.replace(tmp, path)


def backup_info(path):
    """(backup path, modified datetime) if a readable backup exists, else None."""
    b = path + BAK
    try:
        load_json(b)
        return b, datetime.datetime.fromtimestamp(os.path.getmtime(b))
    except (OSError, JsonDamaged):
        return None


# ---------------------------------------------------------------- ignored errors
def set_log_path(path):
    global _log_path
    _log_path = path


def log_path():
    return _log_path


def add_secret(*values):
    for v in values:
        if v and isinstance(v, str) and len(v) >= 6:
            _secrets.add(v)


def scrub(text):
    """Mask registered secrets and anything that looks like a webhook / bot token."""
    text = str(text)
    for s in sorted(_secrets, key=len, reverse=True):
        text = text.replace(s, "***")
    text = re.sub(
        r"(https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/)[^\s'\"]+", r"\1***", text
    )
    text = re.sub(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b", "***", text)  # Telegram bot token
    text = re.sub(r"([?&]t=)[A-Za-z0-9_-]{8,}", r"\1***", text)  # dashboard token in links
    return text


def log_exc(where, exc=None, limit=20):
    """Record an exception the caller ignores on purpose. Never raises. Repeats of the same site are capped."""
    try:
        exc = exc if exc is not None else sys.exc_info()[1]
        key = (where, type(exc).__name__)
        n = _seen[key] = _seen.get(key, 0) + 1
        if n > limit:
            return
        tb = (
            traceback.extract_tb(exc.__traceback__)[-1:]
            if getattr(exc, "__traceback__", None)
            else []
        )
        at = " (%s:%d)" % (os.path.basename(tb[0].filename), tb[0].lineno) if tb else ""
        line = "%s ignored in %s: %s: %s%s%s\n" % (
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            where,
            type(exc).__name__,
            exc,
            at,
            " (further repeats not logged)" if n == limit else "",
        )
        line = scrub(line)
        with _lock:
            if _log_path:
                if os.path.exists(_log_path) and os.path.getsize(_log_path) > MAX_LOG:
                    os.replace(_log_path, _log_path + ".old")
                with open(_log_path, "a", encoding="utf-8") as f:
                    f.write(line)
            else:
                sys.stderr.write("[ignored] " + line)
    except (
        Exception
    ):  # noqa: logging must never break the caller - last resort, nothing else to report to
        pass
