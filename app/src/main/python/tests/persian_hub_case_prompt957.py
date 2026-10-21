"""
Shared base for the Prompt-957 chat-integration tests (not a test module itself): the Persian brain (FULL scope) on a
real MemorySystem and a real HubService whose network, downloads and Android bridge are scripted doubles. `open_app()`
is "the app starts" again on the same files (new MemorySystem, new hub, new brain), so restarts are real.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub.service import HubService, set_hub
from memory.memory_system import MemorySystem
from persian_brain import activation, hub_state
from persian_brain.brain import PersianBrain
from self_builder import service as sb_service
from tests import brain_hub_fixtures_prompt957 as F


class FakeClock:
    def __init__(self, start=1_700_000_000.0):
        self.t = float(start)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def fenced(pkg):
    """A chat message that carries a package the way people paste one (prose + a ```json block)."""
    return "این بسته را بررسی کن:\n```json\n" + json.dumps(pkg, ensure_ascii=False, indent=1) + "\n```"


class HubChatCase(unittest.TestCase):
    scope = activation.SCOPE_FULL

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="phc_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db = os.path.join(self.tmp, "data", "memory.db")
        self.hub_root = os.path.join(self.tmp, "data", "brain_hub")
        self.clock = FakeClock()
        self.fetch = F.FakeFetchTransport()
        self.stream = F.FakeStreamTransport(F.MODEL_BYTES)
        self.memory = self.hub = self.brain = None
        self.addCleanup(self.close_app)
        self.open_app()

    # ------------------------------------------------------------------ the app
    def new_hub(self, memory):
        return HubService(self.hub_root, memory=memory, clock=self.clock, transport=self.fetch,
                          download_transport=self.stream, free_space_fn=F.PLENTY, bridge=F.HubFakeBridge())

    def open_app(self):
        self.close_app()
        self.memory = MemorySystem(self.db)
        activation.enable(self.memory, self.scope)
        self.hub = self.new_hub(self.memory)
        set_hub(self.memory, self.hub)
        self.brain = PersianBrain(self.memory, clock=self.clock)

    def close_app(self):
        memory, hub, self.memory, self.hub = self.memory, self.hub, None, None
        if hub is not None:
            hub.close()
        if memory is None:
            return
        try:
            service = sb_service.get_service(memory)
            if service is not None:
                service.close()
        finally:
            memory._conn.close()

    # ------------------------------------------------------------------ talking
    def say(self, text):
        return self.brain.respond(text)

    def paste(self, pkg):
        return self.say(fenced(pkg))

    def install(self, pkg):
        """Paste, check that nothing changed before the user's «بله», then check the verified activation. Returns the final reply."""
        before = self.active_version(pkg["id"])
        proposal = self.paste(pkg)
        self.assertIsNotNone(proposal)
        self.assertIn("هنوز چیزی نصب یا فعال نشده", proposal)
        self.assertEqual(self.active_version(pkg["id"]), before)
        reply = self.say("بله")
        self.assertIn("نصب و فعال شد", reply)
        self.assertNotEqual(self.active_version(pkg["id"]), before)
        self.assertEqual(self.hub.extension(pkg["id"])["state"], "active")
        return reply

    def active_version(self, cid):
        cap = self.hub.extension(cid)
        return cap.get("active_version") if cap else None

    def pending(self):
        return hub_state.load(self.memory, self.clock)

    def installed_ids(self):
        return sorted(c["capability_id"] for c in self.hub.extensions())

    def trace_kind(self):
        trace = self.brain.last_trace or {}
        intent = trace.get("intent") or {}
        return intent.get("kind"), intent.get("sub")


__all__ = ["HubChatCase", "FakeClock", "fenced"]
