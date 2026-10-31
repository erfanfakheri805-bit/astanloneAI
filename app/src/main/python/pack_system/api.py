"""
pack_system.api - the object a code pack receives: `register(api)`
===================================================================
The pack's whole window onto the app. Everything a pack may do goes through it, so the user can be told exactly what a
pack asked for and the app can refuse the rest:

    api.register_chat(name, matcher, handler, stage="fallback", priority=50)
    api.register_tool(tool_id, title_fa, fn, summary_fa="", params=None)       -> `pack.<id>.<tool>` in the capability map
    api.register_android_action(feature_id, action, fn)                         [permission: android]
    api.register_runtime(runtime)                                               [permission: model]
    api.register_recipe(recipe_id, recipe)                                      [permission: teacher]
    api.read_pack_file(rel)  api.read_text/write_text/read_json/write_json(rel) api.list_data()   (own folders only)
    api.inbox_list()  api.inbox_read(name)  api.inbox_take(name, rel)           (files the user shared into the app)
    api.net_fetch(url)                                                          [permission: network]  (the hub's gate)
    api.ask_model(prompt, max_tokens=160)                                       [permission: model]
    api.android   (the doors: speech, intents, notifications, clipboard ...)    [permission: android]
    api.teacher   (ask ChatGPT / Claude / Gemini for something)                 [permission: teacher]

`ctx` given to chat handlers: `.text .norm .toks .api .brain .memory .hub`.
"""

import json
import os
import re
import time

from . import limits
from .errors import PackError
from .registry import REGISTRY

__all__ = ["PackAPI", "PackPermissionError", "ChatContext"]

_REL_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,60}(?:/[A-Za-z0-9_][A-Za-z0-9_.\-]{0,60}){0,4}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,100}$")
MAX_DATA_WRITE = 1_000_000
MAX_DATA_TOTAL = 20_000_000
MAX_READ = 50_000_000
MAX_LOG = 20_000


class PackPermissionError(PermissionError):
    """The pack used a part of `api` it did not declare in its manifest."""


class ChatContext:
    __slots__ = ("text", "norm", "toks", "api", "brain", "memory", "hub")

    def __init__(self, text, norm, toks, api, brain):
        self.text, self.norm, self.toks, self.api, self.brain = text, norm, list(toks or ()), api, brain
        self.memory = getattr(brain, "memory", None)
        self.hub = REGISTRY.hub()

    def with_api(self, api):
        """The same sentence, handed to the handler of one pack: `.api` is that pack's own window onto the app."""
        other = ChatContext.__new__(ChatContext)
        other.text, other.norm, other.toks, other.api, other.brain = self.text, self.norm, self.toks, api, self.brain
        other.memory, other.hub = self.memory, self.hub
        return other


class PackAPI:
    def __init__(self, pack_id, version, permissions, store, registry=REGISTRY, clock=time.time):
        self.pack_id = pack_id
        self.version = int(version)
        self.permissions = frozenset(permissions or ())
        self._store, self._registry, self._clock = store, registry, clock
        self._android, self._teacher = None, None

    # ---- permissions ---------------------------------------------------------------------------------------------------
    def _need(self, permission):
        if permission not in self.permissions:
            raise PackPermissionError("بستهٔ «%s» مجوز «%s» را در manifest اعلام نکرده است." % (self.pack_id, permission))

    # ---- registration --------------------------------------------------------------------------------------------------
    def register_chat(self, name, matcher, handler, stage="fallback", priority=50):
        self._registry.add_chat(self.pack_id, name, stage, matcher, handler, priority, api=self)

    def register_tool(self, tool_id, title_fa, fn, summary_fa="", params=None):
        self._registry.add_tool(self.pack_id, tool_id, title_fa, fn, summary_fa, params)

    def register_android_action(self, feature_id, action, fn):
        self._need("android")
        self._registry.add_android_action(self.pack_id, feature_id, action, fn)

    def register_runtime(self, runtime):
        self._need("model")
        self._registry.add_runtime(self.pack_id, runtime)

    def register_recipe(self, recipe_id, recipe):
        self._need("teacher")
        self._registry.add_recipe(self.pack_id, recipe_id, recipe)

    def make_context(self, text, norm, toks, brain):
        return ChatContext(text, norm, toks, self, brain)

    # ---- files of the pack itself ---------------------------------------------------------------------------------------
    def read_pack_file(self, rel):
        manifest = self._store.read_manifest(self.pack_id, self.version) or {}
        listed = manifest.get("files") or ()
        if rel not in listed:
            raise FileNotFoundError(rel)
        return self._store.read_file(self.pack_id, self.version, rel)

    # ---- the pack's own writable folder ----------------------------------------------------------------------------------
    def _data_root(self):
        root = self._store.data_dir(self.pack_id)
        os.makedirs(root, exist_ok=True)
        return os.path.realpath(root)

    def _data_path(self, rel):
        if not isinstance(rel, str) or not _REL_RE.match(rel) or ".." in rel.split("/"):
            raise PackError("E_PACK_DATA_PATH", "نام فایل داده «%s» مجاز نیست." % str(rel)[:40])
        root = self._data_root()
        path = os.path.realpath(os.path.join(root, *rel.split("/")))
        if os.path.commonpath([root, path]) != root:
            raise PackError("E_PACK_DATA_PATH", "مسیر خارج از پوشهٔ داده است.")
        return path

    def _data_total(self):
        total = 0
        for base, _dirs, names in os.walk(self._data_root()):
            for name in names:
                try:
                    total += os.path.getsize(os.path.join(base, name))
                except OSError:
                    pass
        return total

    def read_text(self, rel, default=None):
        path = self._data_path(rel)
        if not os.path.isfile(path):
            return default
        with open(path, "rb") as handle:
            return handle.read(MAX_DATA_WRITE + 1).decode("utf-8", "replace")

    def write_text(self, rel, text):
        data = str(text).encode("utf-8")
        if len(data) > MAX_DATA_WRITE:
            raise PackError("E_PACK_DATA_SIZE", "یک نوشتن بیش از %d بایت است." % MAX_DATA_WRITE)
        path = self._data_path(rel)
        if self._data_total() + len(data) > MAX_DATA_TOTAL:
            raise PackError("E_PACK_DATA_SIZE", "پوشهٔ داده از %d بایت بیشتر می‌شود." % MAX_DATA_TOTAL)
        from .fsutil import write_text_atomic
        write_text_atomic(path, data.decode("utf-8"))
        return len(data)

    def read_json(self, rel, default=None):
        text = self.read_text(rel)
        if text is None:
            return default
        try:
            return json.loads(text)
        except (ValueError, RecursionError):
            return default

    def write_json(self, rel, obj):
        return self.write_text(rel, json.dumps(obj, ensure_ascii=False, sort_keys=True))

    def list_data(self):
        out, root = [], self._data_root()
        for base, _dirs, names in os.walk(root):
            for name in names:
                out.append(os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/"))
        return sorted(out)[:500]

    def delete_data(self, rel):
        path = self._data_path(rel)
        try:
            os.unlink(path)
            return True
        except OSError:
            return False

    def log(self, message):
        """Append one line to the pack's own log (bounded)."""
        line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(self._clock())), " ".join(str(message).split())[:300])
        old = self.read_text("pack.log", "") or ""
        self.write_text("pack.log", (old + line)[-MAX_LOG:])

    # ---- the inbox (files the user shared / picked into the app) -----------------------------------------------------------
    def _inbox(self):
        """The ONE inbox of the app: the hub's `inbox/` folder (`<files>/data/brain_hub/inbox`) - where the Android share target
        and the file picker put what the user hands over, and where model files are imported from."""
        try:
            path = self._registry.hub().inbox_dir()
            if isinstance(path, str) and path:
                return path
        except Exception:
            pass
        return os.path.join(os.path.dirname(self._store.root), "brain_hub", "inbox")

    def inbox_list(self):
        try:
            names = sorted(os.listdir(self._inbox()))
        except OSError:
            return []
        out = []
        for name in names[:200]:
            path = os.path.join(self._inbox(), name)
            if _NAME_RE.match(name) and os.path.isfile(path) and not os.path.islink(path):
                out.append({"name": name, "bytes": os.path.getsize(path)})
        return out

    def _inbox_path(self, name):
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise PackError("E_PACK_INBOX", "نام فایل ورودی مجاز نیست.")
        path = os.path.join(self._inbox(), name)
        if os.path.islink(path) or not os.path.isfile(path):
            raise FileNotFoundError(name)
        return path

    def inbox_read(self, name, limit=5_000_000):
        path = self._inbox_path(name)
        limit = max(1, min(int(limit), MAX_READ))
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
        if len(data) > limit:
            raise PackError("E_PACK_INBOX", "فایل بزرگ‌تر از %d بایت است." % limit)
        return data

    def inbox_take(self, name, rel):
        """Move an inbox file into the pack's data folder (a rename: nothing is copied twice)."""
        src = self._inbox_path(name)
        dst = self._data_path(rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
        return dst

    # ---- the web, the model, the phone, the teachers ------------------------------------------------------------------------
    def net_fetch(self, url):
        self._need("network")
        hub = self._registry.hub()
        if hub is None:
            raise PackError("E_PACK_HUB", "هاب برنامه در دسترس نیست.")
        return hub.fetch(url, source="pack:%s" % self.pack_id).to_dict()

    def ask_model(self, prompt, max_tokens=160):
        self._need("model")
        try:
            from brain_hub import llm
        except ImportError:
            return None
        return llm.ask(self._registry.hub(), prompt, max_tokens=max_tokens)

    @property
    def android(self):
        self._need("android")
        if self._android is None:
            try:
                from native_bridge import facade
            except ImportError as exc:
                raise PackError("E_PACK_NATIVE", "درگاه‌های اندروید در این نسخه نیست.") from exc
            self._android = facade.for_pack(self.pack_id, self.permissions)
        return self._android

    @property
    def teacher(self):
        self._need("teacher")
        if self._teacher is None:
            try:
                from teacher import facade
            except ImportError as exc:
                raise PackError("E_PACK_TEACHER", "مسیر آموزگار در این نسخه نیست.") from exc
            self._teacher = facade.for_pack(self.pack_id, self.permissions, self._registry)
        return self._teacher
