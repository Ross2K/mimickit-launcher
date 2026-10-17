"""Generic extension points for a launcher_profile.py overlay (PLUGINS = [factory(app) -> plugin]). The public build
defines no plugins; these hooks only let a personal overlay add things without editing the generic code.

Optional plugin attributes / methods (all called on the GUI thread unless noted):
  build_settings(frame)            add widgets to the Setup page (Extras card)
  snapshot(snap)                   add keys to the phone dashboard snapshot (dict, mutate in place)
  control_actions                  dict action name -> handler(params) -> (http code, message); called from the web
                                   server thread through the PIN + session + nonce gate - must only queue GUI work
  page_html / page_js              strings added to the phone page (a card / script) - keep the dashboard's style
  run_ended()                      a training / view process ended
  closing()                        the window is closing (detach or stop)
Every hook call is wrapped: a failing plugin is logged and shown, never breaks the launcher."""

from mkl import core


class PluginsMixin:
    def _plugins_init(self):
        self.plugins = []
        for factory in core.PLUGINS:
            try:
                self.plugins.append(factory(self))
            except Exception as e:
                self._gui_error("plugin %s" % getattr(factory, "__name__", factory), e)
        for p in self.plugins:
            fr = getattr(self, "plugin_frame", None)
            if fr is not None and hasattr(p, "build_settings"):
                self._plugin_one(p, "build_settings", fr)

    def _plugin_one(self, p, name, *a):
        fn = getattr(p, name, None)
        if not callable(fn):
            return None
        try:
            return fn(*a)
        except Exception as e:
            self._gui_error("plugin %s.%s" % (type(p).__name__, name), e)
            return None

    def _plugin_call(self, name, *a):
        return [self._plugin_one(p, name, *a) for p in getattr(self, "plugins", [])]

    def plugin_actions(self):
        """Server thread: merged control actions of every plugin."""
        out = {}
        for p in getattr(self, "plugins", []):
            out.update(getattr(p, "control_actions", None) or {})
        return out

    def plugin_page(self):
        html = "".join(getattr(p, "page_html", "") or "" for p in getattr(self, "plugins", []))
        js = "".join(getattr(p, "page_js", "") or "" for p in getattr(self, "plugins", []))
        return html, js
