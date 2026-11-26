"""
Test support (Prompt 959, stage B «مغز خودکار») - doubles for the phone's own brain (not a test module itself).

* `FakeBridge` / `FakeJvm`: stand in for the Java class `LiteRtLmBridge` (its static methods, answering with the same "OK\\n..." / "ERR\\n..."
  strings), so the REAL `LiteRtLmRuntime` - its crash guard, its error mapping, its chat call - is exercised without a phone;
* `tiny_choice()` / `tiny_catalog()`: catalog entries pinned to the hash of a small fake model file (the real entries are pinned to the real
  files, which no test may download);
* `OwnBrainApp`: the installed app (`AppCase`) whose hub has the fake engine, a scripted Hugging Face + CDN download (`FakeCdn`), a
  catalog of those tiny entries and a fake memory size, driven only through the real front door (HTTP `POST /api/message`).

Everything proves the app's logic only. Nothing here says how the real engine, the real file or the real phone behave.
"""
import hashlib
import os
import sys
import tempfile
import threading
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import android_entry
from brain_hub import ownbrain_catalog as catalog
from brain_hub import ownbrain_state as ST
from brain_hub.ownbrain import get_ownbrain
from brain_hub.service import HubService, default_root, set_hub
from interface.server import make_handler
from model_runtime import NgramRuntime
from model_runtime.litertlm_runtime import BRIDGE_CLASS, LiteRtLmRuntime
from net_tools import StreamResponse, resumable
from platform_layer import set_platform
from runtime_integration.runtime_core import RuntimeCore
from tests import brain_hub_fixtures_prompt957 as F
from tests.persian_app_case_prompt957 import AppCase
from tests.test_net_tools_resumable_prompt959 import FakeCdn

Usage = F.Usage

__all__ = ["FakeBridge", "FakeJvm", "tiny_choice", "tiny_catalog", "OwnBrainApp", "ThreadedOwnBrainApp", "big_light_data", "DATA", "SHA", "LIGHT_DATA",
           "write_meminfo",
           "FakeCdn", "OwnCdn", "GatedCdn", "engine_runtime", "Usage"]

DATA = bytes((i * 11 + (i >> 7)) % 251 for i in range(120_000))
SHA = hashlib.sha256(DATA).hexdigest()
LIGHT_DATA = bytes((i * 13 + (i >> 5)) % 251 for i in range(60_000))
URL = "https://huggingface.co/litert-community/own-test/resolve/main/%s.litertlm"


def tiny_choice(key="strong", data=None, **over):
    data = data if data is not None else (DATA if key == "strong" else LIGHT_DATA)
    fields = dict(key=key, model_id="own-test-%s" % key, title="Test brain %s (on-device)" % key, short_fa="مغز %s آزمایشی" % key, version="1",
                  url=URL % key, sha256=hashlib.sha256(data).hexdigest(), size_hint=len(data), tolerance=0.05, exact_size=len(data),
                  license="apache-2.0", min_ram=2_000_000_000 if key == "light" else 4_000_000_000,
                  comfortable_ram=0 if key == "light" else 6_000_000_000, languages=("fa", "en"),
                  persian_fa="فارسی‌اش آزمایشی است", source_fa="ساختهٔ آزمون")
    fields.update(over)
    return catalog.BrainChoice(**fields)


def tiny_catalog():
    return (tiny_choice("strong"), tiny_choice("light"))


def write_meminfo(path, kb=8_000_000):
    with open(path, "w", encoding="ascii") as handle:
        handle.write("MemTotal:       %d kB\nMemFree:         100000 kB\n" % kb)
    return path


class OwnCdn(FakeCdn):
    """`FakeCdn` that serves the file of whichever tiny brain the Hugging Face address names (the CDN hop that follows has no name in it)."""

    def __init__(self, files=None, **kwargs):
        self.files = dict(files or {"strong": DATA, "light": LIGHT_DATA})
        super().__init__(self.files["strong"], **kwargs)

    def stream(self, request):
        if request.host == "huggingface.co":
            for key, data in self.files.items():
                if request.path_query.split("?", 1)[0].endswith("/%s.litertlm" % key):
                    self.data = data
        return super().stream(request)


class GatedCdn(OwnCdn):
    """`OwnCdn` that stops delivering after `hold_after` bytes until the test opens `gate` or the user's stop arrives (`stop_event`, set by the
    test to the brain's cancel flag): a download that is really in progress while the test talks to the app. It never hangs - 20 seconds at most."""

    def __init__(self, hold_after=40_000, stop_event=None, **kwargs):
        super().__init__(**kwargs)
        self.hold_after, self.stop_event = hold_after, stop_event
        self.gate, self.reached = threading.Event(), threading.Event()

    def stream(self, request):
        response = super().stream(request)
        if response.status not in (200, 206):
            return response
        inner, outer = response._chunks, self

        def chunks():
            sent = 0
            for part in inner():
                if sent >= outer.hold_after and not outer.gate.is_set():
                    outer.reached.set()
                    for _ in range(2000):
                        if outer.gate.is_set() or (outer.stop_event is not None and outer.stop_event.is_set()):
                            break
                        time.sleep(0.01)
                sent += len(part)
                yield part

        response._chunks = chunks
        return response


class FakeBridge:
    """The static API of `LiteRtLmBridge`. Answers are scripted; every call is recorded."""

    def __init__(self, present=True, answers=("سلام! من مغزِ آزمایشی هستم.",), load_result="OK\nloaded", chat_error=None, probe_result="OK\nready",
                 api_text="Engine: <init>(EngineConfig); initialize();"):
        self.present, self.answers, self.load_result, self.chat_error = present, list(answers), load_result, chat_error
        self.probe_result, self.api_text, self.probes = probe_result, api_text, 0
        self.loaded, self.loads, self.chats, self.unloads, self.cancels = False, [], [], 0, 0
        self.gate, self.raise_on_load = None, None

    def isPresent(self):
        return self.present

    def isLoaded(self):
        return self.loaded

    def describe(self):
        return "fake bridge present=%s loaded=%s" % (self.present, self.loaded)

    def probe(self):
        self.probes += 1
        return self.probe_result

    def api(self):
        return self.api_text

    def load(self, path, tokens):
        self.loads.append((path, tokens))
        if self.raise_on_load is not None:
            raise self.raise_on_load
        self.loaded = self.load_result.startswith("OK")
        return self.load_result

    def chat(self, system, history, user, max_tokens):
        self.chats.append({"system": system, "history": history, "user": user, "max_tokens": max_tokens})
        if self.gate is not None:
            self.gate.wait(20)
        if self.chat_error is not None:
            return "ERR\n%s\n" % self.chat_error
        answers = self.answers
        return "OK\n" + (answers.pop(0) if len(answers) > 1 else answers[0])

    def unload(self):
        self.unloads += 1
        self.loaded = False
        return "OK\nunloaded"

    def cancel(self):
        self.cancels += 1
        if self.gate is not None:
            self.gate.set()


class FakeJvm:
    def __init__(self, bridge, available=True):
        self.bridge, self._available = bridge, available

    def available(self):
        return self._available

    def jclass(self, name):
        assert name == BRIDGE_CLASS, name
        return self.bridge


def engine_runtime(bridge, available=True):
    return LiteRtLmRuntime(jvm_provider=lambda: FakeJvm(bridge, available))


class OwnBrainApp(AppCase):
    """The installed app with a fake engine, a scripted download and tiny catalog entries. `self.ob` is its `OwnBrain` (no worker thread:
    a job runs inside the chat call, so a test sees its end at once); `self.bridge` is the fake engine; `self.cdn` the scripted download."""

    ram_kb = 8_000_000
    use_thread = False
    engine_available = True
    connectivity = None                                     # a `BridgeConnectivity` (offline ...) or None for «online»
    free_fn = staticmethod(F.PLENTY)
    answers = ("سلام! من مغزِ آزمایشی هستم.",)
    cdn_factory = staticmethod(OwnCdn)

    def make_cdn(self):
        return self.cdn_factory()

    def catalog(self):
        return tiny_catalog()

    def setUp(self):
        self.bridge = FakeBridge(answers=self.answers)
        self.cdn = self.make_cdn()
        self.meminfo = os.path.join(tempfile.mkdtemp(prefix="meminfo_"), "meminfo")
        write_meminfo(self.meminfo, self.ram_kb)
        super().setUp()

    def start_app(self):
        self.stop_app()
        set_platform(android_entry.AndroidFilesDirAdapter(self.files))
        self.core = RuntimeCore()
        memory = self.core.memory
        self.cdn.requests.clear()
        bridge = F.HubFakeBridge(connectivity=self.connectivity) if self.connectivity is not None else F.HubFakeBridge()
        self.hub = HubService(default_root(memory), memory=memory, clock=self.clock, transport=self.fetch, download_transport=self.cdn,
                              free_space_fn=self.free_fn, bridge=bridge,
                              model_runtimes=[NgramRuntime(), engine_runtime(self.bridge, self.engine_available)])
        set_hub(memory, self.hub)
        self.ob = get_ownbrain(self.hub, catalog_choices=self.catalog(), meminfo=self.meminfo, use_thread=self.use_thread, idle_unload_seconds=0,
                               sleep=lambda _s: None)
        if isinstance(self.cdn, GatedCdn):
            self.cdn.stop_event = self.ob._cancel                # the user's stop also releases a download that the test holds
        self.server = __import__("http.server", fromlist=["ThreadingHTTPServer"]).ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.core))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def model_status(self, key="strong"):
        return self.hub.model_status(tiny_choice(key).model_id)

    # ------------------------------------------------------------------ helpers for the chat tests
    @property
    def own_dir(self):
        return os.path.join(self.hub.root, "own_brain")

    def pending_own(self):
        """The type of the open own-brain question ("consent" / "delete") or None."""
        from persian_brain import hub_ownbrain
        raw = self.memory.get_state(hub_ownbrain.PENDING_KEY, None)
        return raw["type"] if isinstance(raw, dict) else None

    def age_pending(self, seconds):
        """Make the open own-brain question `seconds` older. The app's brain has no clock of its own (it uses the real time), so a test cannot move
        time with `self.clock`; it moves the question's timestamp instead."""
        from persian_brain import hub_ownbrain
        raw = self.memory.get_state(hub_ownbrain.PENDING_KEY, None)
        self.assertIsInstance(raw, dict, "there is no open question to age")
        self.memory.set_state(hub_ownbrain.PENDING_KEY, dict(raw, ts=float(raw["ts"]) - seconds))

    def reset_brain(self):
        """Back to «no brain»: the user's own «مغز را پاک کن» + «بله»."""
        self.ask("مغز را پاک کن")
        self.ask("بله")
        self.assertEqual(self.ob.status()["phase"], "idle")

    def pending_cloud(self):
        from persian_brain import hub_brain
        raw = self.memory.get_state(hub_brain.PENDING_KEY, None)
        return raw["type"] if isinstance(raw, dict) else None

    def nothing_was_fetched(self):
        """No request at all went out, and nothing of the own brain is on the disk."""
        self.assertEqual(self.cdn.requests, [], "nothing may be requested before the user's yes")
        self.assertFalse(os.path.exists(os.path.join(self.own_dir, "state.json")), "no state may be written before the user's yes")
        leftovers = [name for name in (os.listdir(self.own_dir) if os.path.isdir(self.own_dir) else []) if name != "state.json"]
        self.assertEqual(leftovers, [])

    def permission_snapshot(self):
        return repr(self.hub.permission_rows())

    def internet_on(self):
        """Is the app-wide internet switch («اینترنت را روشن / خاموش کن») on?"""
        return bool(self.hub.permissions.is_granted("network"))

    def switch_internet(self, on):
        """Set the app-wide internet switch the way the user does (the hub's own grant / revoke)."""
        change = self.hub.grant_permission("network", user_approved=True) if on else self.hub.revoke_permission("network")
        self.assertTrue(change.ok, change)

    def seed_download(self, key="light", phase="paused", code="app_closed", consent=True, partial=30_000):
        """Leave on the disk what the app leaves when it stops in the middle of a download: the state file and the partial file. The app is not
        started here - the caller starts it, so that the state is read the way a restart reads it."""
        choice = tiny_choice(key)
        data = DATA if key == "strong" else LIGHT_DATA
        state = ST.default_state()
        state.update(choice=key, phase=phase, code=code, consent_at=1.0 if consent else 0.0, model_id=choice.model_id, total=len(data), bytes=partial)
        os.makedirs(self.own_dir, exist_ok=True)
        self.assertTrue(ST.StateFile(self.own_dir, clock=self.clock).save(state))
        if partial:
            path = resumable.partial_path(self.own_dir, choice.rel_dest)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(data[:partial])

    def say_all(self, *texts):
        return [self.ask(text) for text in texts]

    def install_light(self):
        """The whole way to a ready brain (inline): wish, choice, yes. Returns the reply to the yes."""
        self.ask("مغز خودت را بگیر")
        self.ask("سبک")
        reply = self.ask("بله")
        self.assertEqual(self.ob.status()["phase"], "ready", reply)
        return reply


_BIG = {}


def big_light_data(size=900_000):
    """A light brain file big enough that the downloader's progress report (every 256 KiB) happens while the CDN holds the download."""
    if size not in _BIG:
        _BIG[size] = bytes((i * 13 + (i >> 5)) % 251 for i in range(size))
    return _BIG[size]


class ThreadedOwnBrainApp(OwnBrainApp):
    """The same app, but the download runs in the brain's own worker thread and the CDN holds it after `hold_after` bytes (of a 900,000-byte
    light brain: two progress reports have happened by then) until the test opens `self.cdn.gate`: the chat can be used while a download is
    really in progress. Cleanup always lets the worker finish."""

    use_thread = True
    hold_after = 600_000
    light_size = 900_000

    def make_cdn(self):
        return GatedCdn(hold_after=self.hold_after, files={"strong": DATA, "light": big_light_data(self.light_size)})

    def catalog(self):
        return (tiny_choice("strong"), tiny_choice("light", data=big_light_data(self.light_size)))

    def setUp(self):
        super().setUp()
        self.addCleanup(self.release)

    def release(self):
        self.cdn.gate.set()
        self.ob._cancel.set()
        self.ob.wait(10)

    def start_download(self, wish="مغز خودت را بگیر", pick="سبک"):
        """Wish, choice, yes - and wait until the CDN is holding the download in the middle. Returns the reply to the yes."""
        self.ask(wish)
        if pick:
            self.ask(pick)
        reply = self.ask("بله")
        self.assertTrue(self.cdn.reached.wait(15), "the download never reached the held point")
        self.assertEqual(self.ob.status()["phase"], "downloading")
        return reply

    def open_gate_and_wait(self, seconds=30):
        self.cdn.gate.set()
        self.assertTrue(self.ob.wait(seconds), "the worker did not finish")

