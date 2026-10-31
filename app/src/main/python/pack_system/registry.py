"""
pack_system.registry - what active packs have registered (chat handlers, tools, Android actions, engines, recipes)
==================================================================================================================
A code pack's `register(api)` calls `api.register_*`; those land here. The rest of the app only ever asks this module:

    run_chat(stage, ctx)      chat handlers of one stage ("early": before the Persian brain looks at the sentence;
                              "fallback": when nothing else answered)
    tools()                   pack tools (shown in the capability map as `pack.<id>.<tool>`)
    android_actions()         extra actions for Android features (`AndroidAdapterLayer` consults them)
    runtimes()                extra model engines (`model_runtime` consults them)
    recipes()                 teacher recipes (how to ask a given assistant app for something)

A handler that raises is counted; after `MAX_PACK_FAILURES` the manager switches the pack off. A handler can never break
the conversation: `run_chat` returns None on any failure.
"""

import threading
import time

from . import limits

__all__ = ["Registry", "REGISTRY", "ChatHandler", "ToolEntry", "interrupt_thread", "call_guarded"]


def interrupt_thread(thread):
    """Ask a runaway pack thread to stop (an exception raised inside it at its next bytecode). Best effort: a thread
    stuck inside native code, or one that swallows the exception, cannot be stopped from Python."""
    try:
        import ctypes
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread.ident), ctypes.py_object(SystemExit))
        return True
    except Exception:
        return False


def call_guarded(fn, seconds):
    """`fn()` in a helper thread with a deadline: its result, its exception, or TimeoutError (and the thread is asked to stop)."""
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        interrupt_thread(thread)
        raise TimeoutError("pack handler did not finish in %s seconds" % seconds)
    if "error" in box:
        raise box["error"]
    return box.get("value")


class ChatHandler:
    __slots__ = ("pack_id", "name", "stage", "matcher", "handler", "priority", "order", "api")

    def __init__(self, pack_id, name, stage, matcher, handler, priority, order, api=None):
        self.pack_id, self.name, self.stage, self.matcher = pack_id, name, stage, matcher
        self.handler, self.priority, self.order, self.api = handler, priority, order, api


class ToolEntry:
    __slots__ = ("pack_id", "tool_id", "title_fa", "summary_fa", "fn", "params")

    def __init__(self, pack_id, tool_id, title_fa, summary_fa, fn, params):
        self.pack_id, self.tool_id, self.title_fa, self.summary_fa, self.fn, self.params = pack_id, tool_id, title_fa, summary_fa, fn, params

    @property
    def node_id(self):
        return "pack.%s.%s" % (self.pack_id, self.tool_id)


class Registry:
    def __init__(self, clock=time.time):
        self._lock = threading.RLock()
        self._clock = clock
        self._chat = []
        self._tools = {}
        self._android = {}
        self._runtimes = []
        self._recipes = {}
        self._errors = {}
        self._order = 0
        self.on_failure = None            # callable(pack_id, reason) set by the manager
        self.lang_version = 0             # bumped when lang packs change: the language index rebuilds
        self._hub_getter = None
        self._brain = None
        self.last_error = {}              # pack_id -> short text of the last failure (for the status report)

    # ---- context (set by the chat hooks) -----------------------------------------------------------------------------
    def bind(self, brain):
        with self._lock:
            self._brain = brain

    @property
    def brain(self):
        return self._brain

    def hub(self):
        brain = self._brain
        if brain is None:
            return None
        try:
            from brain_hub import service as hub_service
            return hub_service.get_hub(brain.memory)
        except Exception:
            return None

    # ---- registration -------------------------------------------------------------------------------------------------
    def add_chat(self, pack_id, name, stage, matcher, handler, priority=50, api=None):
        if stage not in ("early", "fallback") or not callable(matcher) or not callable(handler):
            raise ValueError("bad chat handler")
        with self._lock:
            self._order += 1
            self._chat.append(ChatHandler(pack_id, str(name)[:40], stage, matcher, handler, int(priority), self._order, api))
            self._chat.sort(key=lambda h: (h.priority, h.order))

    def add_tool(self, pack_id, tool_id, title_fa, fn, summary_fa="", params=None):
        if not callable(fn) or not isinstance(tool_id, str) or not tool_id.replace("_", "").isalnum():
            raise ValueError("bad tool")
        with self._lock:
            self._tools[(pack_id, tool_id)] = ToolEntry(pack_id, tool_id, str(title_fa)[:80], str(summary_fa)[:300], fn, dict(params or {}))

    def add_android_action(self, pack_id, feature_id, action, fn):
        if not callable(fn):
            raise ValueError("bad action")
        with self._lock:
            self._android[(str(feature_id), str(action))] = (pack_id, fn)

    def add_runtime(self, pack_id, runtime):
        with self._lock:
            self._runtimes = [(p, r) for p, r in self._runtimes if not (p == pack_id and getattr(r, "name", None) == getattr(runtime, "name", object()))]
            self._runtimes.append((pack_id, runtime))

    def add_recipe(self, pack_id, recipe_id, recipe):
        with self._lock:
            self._recipes[str(recipe_id)] = (pack_id, recipe)

    def unregister_pack(self, pack_id):
        with self._lock:
            self._chat = [h for h in self._chat if h.pack_id != pack_id]
            self._tools = {k: v for k, v in self._tools.items() if k[0] != pack_id}
            self._android = {k: v for k, v in self._android.items() if v[0] != pack_id}
            self._runtimes = [(p, r) for p, r in self._runtimes if p != pack_id]
            self._recipes = {k: v for k, v in self._recipes.items() if v[0] != pack_id}
            self._errors.pop(pack_id, None)

    def clear(self):
        with self._lock:
            self._chat, self._tools, self._android, self._runtimes, self._recipes, self._errors = [], {}, {}, [], {}, {}
            self.last_error = {}

    # ---- reading --------------------------------------------------------------------------------------------------------
    def tools(self):
        with self._lock:
            return list(self._tools.values())

    def tool(self, pack_id, tool_id):
        with self._lock:
            return self._tools.get((pack_id, tool_id))

    def android_actions(self, feature_id=None):
        with self._lock:
            return {k: v for k, v in self._android.items() if feature_id is None or k[0] == feature_id}

    def android_action(self, feature_id, action):
        with self._lock:
            return self._android.get((feature_id, action))

    def runtimes(self):
        with self._lock:
            return [r for _p, r in self._runtimes]

    def recipes(self):
        with self._lock:
            return dict((k, v[1]) for k, v in self._recipes.items())

    def has_stage(self, stage):
        with self._lock:
            return any(h.stage == stage for h in self._chat)

    def chat_names(self):
        with self._lock:
            return [(h.pack_id, h.name, h.stage) for h in self._chat]

    def pack_ids(self):
        with self._lock:
            ids = {h.pack_id for h in self._chat}
            ids |= {k[0] for k in self._tools}
            ids |= {v[0] for v in self._android.values()}
            ids |= {p for p, _r in self._runtimes}
            ids |= {v[0] for v in self._recipes.values()}
            return sorted(ids)

    # ---- running ---------------------------------------------------------------------------------------------------------
    def note_failure(self, pack_id, exc):
        with self._lock:
            count = self._errors.get(pack_id, 0) + 1
            self._errors[pack_id] = count
            self.last_error[pack_id] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
            callback = self.on_failure
        if count >= limits.MAX_PACK_FAILURES and callback is not None:
            try:
                callback(pack_id, "too_many_errors")
            except Exception:
                pass

    def errors(self, pack_id):
        with self._lock:
            return self._errors.get(pack_id, 0)

    def run_chat(self, stage, ctx):
        """`(pack_id, handler name, reply)` of the first handler of `stage` that matches and answers, else None."""
        with self._lock:
            handlers = [h for h in self._chat if h.stage == stage]
        for h in handlers:
            own = ctx.with_api(h.api) if h.api is not None and hasattr(ctx, "with_api") else ctx
            try:
                reply = call_guarded(lambda h=h, own=own: h.handler(own) if h.matcher(own) else None, limits.HANDLER_SECONDS)
            except Exception as exc:                  # a pack can never break the conversation
                self.note_failure(h.pack_id, exc)
                continue
            if isinstance(reply, str) and reply.strip():
                return h.pack_id, h.name, reply.strip()[:4000]
        return None


REGISTRY = Registry()
