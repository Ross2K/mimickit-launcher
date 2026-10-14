"""Expected defaults per build, shared by the tests. The public build selects the fake humanoid config, whose motion
file is in the fake MimicKit tree, and has no extra buttons. A launcher_profile.py overlay brings its own presets
(selected by default; their motion files are not in the fake tree) and ACTIONS. Tests run unchanged in both."""

from mkl import core

PROFILE = getattr(core, "_P", None) is not None
PROFILE_PRESETS = PROFILE and bool(core.PRESETS)
PROFILE_ACTIONS = len(getattr(core, "_P", None) and getattr(core._P, "ACTIONS", []) or [])
VIEW_ENV = "--env_config output/_launcher_watch/view_env.yaml"


def watch_ok(cmd, app):
    """Watch runs the generated view env (public), or the selected preset's own args file (profile presets)."""
    if PROFILE_PRESETS:
        return "--arg_file " + app._item("train")["file"] in cmd
    return VIEW_ENV in cmd
