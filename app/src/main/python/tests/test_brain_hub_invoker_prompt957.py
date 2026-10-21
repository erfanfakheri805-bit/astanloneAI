"""
Prompt 957 - the execution invoker (`HubService.execute`) and the module API (`get_hub` / `set_hub` / `reset_hub`).

Behaviour 2 (the registry enumerates capabilities and distinguishes unavailable / permission-blocked / active) and the
choke-point rule: nothing runs unless the node is usable RIGHT NOW, and nothing here ever raises into a conversation.
"""
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import graph as graph_mod
from brain_hub.service import HubService, default_root, get_hub, reset_hub, set_hub
from self_builder.registry import CAP_ACTIVE
from tests import brain_hub_fixtures_prompt957 as F


class FakeMemory:
    """Just enough of a MemorySystem for the hub: a database path and one query."""

    def __init__(self, db_path, healthy=True):
        self.db_path, self.healthy = db_path, healthy

    def query_one(self, sql, params=()):
        if not self.healthy:
            raise RuntimeError("database is closed")
        return {"ok": 1}


class FakeSB:
    """Stands in for the Self-Builder service: two registered capabilities, one of them switched off."""

    def __init__(self):
        self.calls = []

    def exists(self):
        return True

    def capability(self, cid):
        return {"id": cid} if cid in ("cm_to_m", "old_tool") else None

    def capabilities(self, include_disabled=False):
        return [{"id": "cm_to_m", "title": "سانتی‌متر به متر", "description": "تبدیل", "status": CAP_ACTIVE, "version": 2,
                 "tests": {"total": 3, "passed": 3, "ok": True}},
                {"id": "old_tool", "title": "ابزار قدیمی", "description": "", "status": "disabled", "version": None,
                 "tests": {"total": 1, "passed": 1, "ok": True}}]

    def invoke(self, cid, inputs):
        self.calls.append((cid, dict(inputs)))
        if cid == "cm_to_m":
            return {"ok": True, "value": "%s m" % (float(inputs.get("value", 0)) / 100)}
        return {"ok": False, "error": "not_active"}


class HubCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "brain_hub")
        self.hubs = []

    def tearDown(self):
        for hub in self.hubs:
            hub.close()

    def hub(self, **kw):
        kw.setdefault("bridge", F.HubFakeBridge())
        kw.setdefault("free_space_fn", F.PLENTY)
        hub = HubService(self.root, **kw)
        self.hubs.append(hub)
        return hub


class GraphOverview(HubCase):
    def test_a_fresh_install_lists_everything_and_creates_nothing(self):
        mem = FakeMemory(os.path.join(self._tmp.name, "m.db"))          # the hub holds its memory weakly: keep it alive here
        hub = self.hub(memory=mem)
        graph = hub.graph()
        counts = {}
        for node in graph.nodes():
            counts[node.kind] = counts.get(node.kind, 0) + 1
        self.assertEqual(counts, {"brain": 6, "tool": 2, "android": 9, "infra": 11, "gap": 17})
        self.assertEqual(len(graph), 45)
        self.assertFalse(os.path.exists(self.root))
        summary = graph.summary()
        self.assertEqual(sum(summary["by_state"].values()), 45)
        self.assertTrue(set(summary["by_state"]) <= set(graph_mod.STATES))
        self.assertEqual(summary["usable"], len(graph.usable()))
        self.assertEqual(summary["by_kind"], counts)

    def test_the_states_distinguish_usable_blocked_and_missing(self):
        mem = FakeMemory(os.path.join(self._tmp.name, "m.db"))          # the hub holds its memory weakly: keep it alive here
        hub = self.hub(memory=mem)
        graph = hub.graph()
        self.assertEqual(graph.get("brain.memory").state, "active")
        self.assertTrue(graph.get("brain.memory").tested)
        self.assertEqual(graph.get("tool.web_fetch").state, "permission_blocked")
        self.assertEqual(graph.get("tool.local_model").state, "dependency_blocked")
        self.assertEqual(graph.get("android.network_state").state, "available")
        self.assertEqual(graph.get("android.microphone").state, "not_implemented")
        self.assertEqual(graph.get("android.telephony").state, "policy_blocked")
        self.assertEqual(graph.get("infra.images_audio").state, "scaffold_only")
        usable = {n.node_id for n in graph.usable()}
        for blocked in ("tool.web_fetch", "tool.local_model", "android.microphone", "android.telephony", "infra.images_audio"):
            self.assertNotIn(blocked, usable)
        for node in graph.nodes():
            if not node.usable:
                self.assertTrue(node.blockers, node.node_id + " is not usable but names no blocker")
            self.assertNotEqual(node.state == "active" and not node.tested, True, node.node_id)

    def test_the_memory_node_depends_on_a_real_query(self):
        mem = FakeMemory(os.path.join(self._tmp.name, "m.db"), healthy=False)
        hub = self.hub(memory=mem)
        node = hub.graph().get("brain.memory")
        self.assertEqual((node.state, node.usable, node.blockers[0].kind), ("dependency_blocked", False, "dependency"))
        self.assertEqual(self.hub().graph().get("brain.memory").state, "dependency_blocked")          # no memory at all

    def test_the_conversation_node_becomes_active_only_after_a_real_answer(self):
        hub = self.hub()
        self.assertEqual(hub.graph().get("brain.conversation").state, "available")
        hub.note_served("brain.conversation")
        node = hub.graph().get("brain.conversation")
        self.assertEqual((node.state, node.tested), ("active", True))
        self.assertIn("1", node.evidence[0])

    def test_a_builder_that_fails_adds_a_broken_node_and_hides_nothing(self):
        hub = self.hub()

        def boom():
            raise RuntimeError("android layer exploded")
        hub.android_statuses = boom
        graph = hub.graph()
        broken = graph.get("hub.android_nodes_error")
        self.assertEqual((broken.state, broken.usable), ("broken", False))
        self.assertIsNotNone(graph.get("brain.conversation"))
        self.assertIsNotNone(graph.get("infra.images_audio"))
        self.assertEqual(len(graph.nodes(kind="android")), 0)


class SelfBuilderNodes(HubCase):
    def test_the_old_archetype_capabilities_appear_next_to_the_new_ones(self):
        hub = self.hub()
        hub._sb = lambda: FakeSB()
        graph = hub.graph()
        live = graph.get("sb.cm_to_m")
        self.assertEqual((live.state, live.tested, live.usable, live.version, live.actions), ("active", True, True, 2, ("invoke",)))
        old = graph.get("sb.old_tool")
        self.assertEqual((old.state, old.usable, old.actions), ("disabled", False, ()))
        done = hub.execute("sb.cm_to_m", "invoke", {"value": 250})
        self.assertEqual((done.ok, done.code, done.message_fa), (True, "ok", "2.5 m"))
        refused = hub.execute("sb.old_tool", "invoke", {})
        self.assertEqual((refused.ok, refused.code), (False, "not_usable"))

    def test_an_id_used_by_the_old_registry_cannot_be_reused_by_an_extension(self):
        hub = self.hub()
        hub._sb = lambda: FakeSB()
        pkg = F.jalali_pkg(id="cm_to_m")
        result = hub.propose_package(F.dumps(pkg))
        self.assertEqual((result["status"], result["code"]), ("rejected", "E_EXT_ID_TAKEN"))


class Router(HubCase):
    def install_jalali(self, hub):
        pid = hub.propose_package(F.dumps(F.jalali_pkg()))["proposal_id"]
        self.assertEqual(hub.approve_proposal(pid, user_approved=True)["status"], "applied")

    def test_unknown_nodes_are_refused(self):
        hub = self.hub()
        for node_id in ("nope", "", "ext.", "ext.missing", None, 5, "x" * 300):
            with self.subTest(node=str(node_id)[:20]):
                result = hub.execute(node_id, "invoke")
                self.assertEqual((result.ok, result.code), (False, "unknown_node"))
        self.assertTrue(result.message_fa and result.message_en)

    def test_a_node_that_is_not_usable_names_its_blockers_and_runs_nothing(self):
        transport = F.FakeFetchTransport(F.fetch_reply())
        hub = self.hub(transport=transport)
        for node_id in ("tool.web_fetch", "tool.local_model", "android.microphone", "infra.images_audio", "gap.draw_images"):
            node = hub.graph().get(node_id)
            if node is None:
                continue
            with self.subTest(node=node_id):
                result = hub.execute(node_id, "invoke", {"url": "https://a.test/"})
                self.assertEqual((result.ok, result.code, result.state), (False, "not_usable", node.state))
                self.assertIn("الان قابل اجرا نیست", result.message_fa)
                self.assertIn("cannot run right now", result.message_en)
                self.assertTrue(result.data["blockers"])
        self.assertEqual(len(transport.requests), 0)

    def test_every_gap_in_the_catalogue_refuses_to_run(self):
        hub = self.hub()
        gaps = hub.graph().nodes(kind="gap")
        self.assertGreaterEqual(len(gaps), 15)
        for node in gaps:
            with self.subTest(node=node.node_id):
                self.assertFalse(node.usable)
                self.assertEqual(hub.execute(node.node_id, "invoke").code, "not_usable")

    def test_an_extension_runs_only_through_its_own_action(self):
        hub = self.hub()
        self.install_jalali(hub)
        done = hub.execute("ext.jalali_date", "invoke", {"gy": 2024, "gm": 3, "gd": 20})
        self.assertEqual((done.ok, done.code, done.state), (True, "ok", "active"))
        self.assertEqual(done.data["outputs"], {"jy": 1403, "jm": 1, "jd": 1})
        self.assertIn("۱۴۰۳", done.message_fa)
        bad = hub.execute("ext.jalali_date", "invoke", {"gy": 2024, "gm": 13, "gd": 20})
        self.assertEqual((bad.ok, bad.code), (False, "invalid_inputs"))
        self.assertEqual(hub.execute("ext.jalali_date", "delete").code, "unknown_action")
        self.assertEqual(hub.execute("ext.jalali_date", "invoke", None).code, "invalid_inputs")
        hub.disable_extension("jalali_date")
        self.assertEqual(hub.execute("ext.jalali_date", "invoke", {"gy": 2024, "gm": 3, "gd": 20}).code, "not_usable")

    def test_a_pending_extension_has_no_action_at_all(self):
        hub = self.hub()
        hub.propose_package(F.dumps(F.jalali_pkg()))
        node = hub.graph().get("ext.jalali_date.pending")
        self.assertEqual((node.state, node.actions), ("pending_approval", ()))
        self.assertEqual(hub.execute("ext.jalali_date.pending", "invoke").code, "not_usable")
        self.assertEqual(hub.execute("ext.jalali_date", "invoke", {"gy": 2024, "gm": 3, "gd": 20}).code, "unknown_node")

    def test_a_permission_blocked_extension_is_refused_by_the_router_before_it_runs(self):
        hub = self.hub()
        pid = hub.propose_package(F.dumps(F.clock_pkg()))["proposal_id"]
        hub.approve_proposal(pid, user_approved=True)
        self.assertTrue(hub.execute("ext.clock_reader", "invoke", {}).ok)
        hub.revoke_extension_permission("clock_reader", "clock")
        result = hub.execute("ext.clock_reader", "invoke", {})
        self.assertEqual((result.ok, result.code, result.state), (False, "not_usable", "permission_blocked"))
        self.assertIn("clock", result.message_fa)

    def test_the_router_never_raises_into_a_conversation(self):
        hub = self.hub()
        self.install_jalali(hub)

        def boom(*_a, **_k):
            raise RuntimeError("sandbox exploded")
        hub.invoke_extension = boom
        result = hub.execute("ext.jalali_date", "invoke", {"gy": 2024, "gm": 3, "gd": 20})
        self.assertEqual((result.ok, result.code), (False, "failed"))
        self.assertIn("RuntimeError", result.message_fa)
        self.assertNotIn("exploded", result.message_fa + result.message_en)

    def test_a_result_is_plain_data(self):
        hub = self.hub()
        data = hub.execute("nope", "invoke").to_dict()
        self.assertEqual(sorted(data), ["code", "data", "message_en", "message_fa", "node_id", "ok", "state"])


class ModuleApi(HubCase):
    def memory(self, name="m.db"):
        return FakeMemory(os.path.join(self._tmp.name, name))

    def test_default_root_sits_next_to_the_database_and_creates_nothing(self):
        mem = self.memory()
        self.assertEqual(default_root(mem), os.path.join(self._tmp.name, "brain_hub"))
        self.assertFalse(os.path.exists(os.path.join(self._tmp.name, "brain_hub")))
        for bad in (object(), FakeMemory(""), FakeMemory(None)):
            self.assertIsNone(default_root(bad))
            self.assertIsNone(get_hub(bad))

    def test_one_hub_per_memory_and_a_new_one_when_the_path_changes(self):
        mem = self.memory()
        first = get_hub(mem)
        self.assertIs(get_hub(mem), first)
        self.assertEqual(first.root, os.path.join(self._tmp.name, "brain_hub"))
        self.assertIs(first.memory, mem)
        other = self.memory("sub/m.db") if os.makedirs(os.path.join(self._tmp.name, "sub"), exist_ok=True) is None else None
        self.assertIsNot(get_hub(other), first)
        mem.db_path = os.path.join(self._tmp.name, "moved", "m.db")
        moved = get_hub(mem)
        self.assertIsNot(moved, first)
        self.assertEqual(moved.root, os.path.join(self._tmp.name, "moved", "brain_hub"))
        for hub in (first, moved):
            reset_hub(mem)
        self.assertFalse(os.path.exists(os.path.join(self._tmp.name, "brain_hub")))

    def test_the_registry_does_not_keep_a_memory_system_alive(self):
        import gc
        import weakref
        from brain_hub import service as service_mod
        mem = self.memory("alive.db")
        hub = get_hub(mem)
        self.assertIs(hub.memory, mem)
        probe = weakref.ref(mem)
        del mem
        gc.collect()
        self.assertIsNone(probe())                          # nothing (neither the registry nor the hub) holds it
        self.assertIsNone(hub.memory)
        self.assertEqual(hub.graph().get("brain.memory").state, "dependency_blocked")
        self.assertNotIn(probe, list(service_mod._HUBS.keyrefs()))
        # an object that cannot be weakly referenced is simply held
        holder = HubService(self.root, memory={"plain": "dict"})
        self.hubs.append(holder)
        self.assertEqual(holder.memory, {"plain": "dict"})

    def test_set_and_reset(self):
        mem = self.memory()
        fake = self.hub(memory=mem)
        set_hub(mem, fake)
        self.assertIs(get_hub(mem), fake)
        pid = fake.propose_package(F.dumps(F.jalali_pkg()))["proposal_id"]
        self.assertIsNotNone(pid)
        self.assertIsNotNone(fake._ext)
        reset_hub(mem)
        self.assertIsNone(fake._ext)                    # reset closes the open store
        fresh = get_hub(mem)
        self.assertIsNot(fresh, fake)
        reset_hub(mem)
        reset_hub(mem)                                  # a second reset is harmless

    def test_status_is_plain_data_and_reads_only(self):
        hub = self.hub()
        info = hub.status()
        self.assertEqual((info["exists"], info["extensions"], info["pending_proposals"], info["models"]), (False, 0, 0, 0))
        self.assertEqual([p["name"] for p in info["permissions"]], ["network"])
        self.assertFalse(info["permissions"][0]["granted"])
        self.assertIsNone(info["audit"])
        self.assertFalse(os.path.exists(self.root))
        pid = hub.propose_package(F.dumps(F.jalali_pkg()))["proposal_id"]
        self.assertEqual(hub.status()["pending_proposals"], 1)
        hub.approve_proposal(pid, user_approved=True)
        hub.grant_permission("network", user_approved=True)
        info = hub.status()
        self.assertEqual((info["extensions"], info["extensions_active"], info["pending_proposals"]), (1, 1, 0))
        self.assertTrue(info["permissions"][0]["granted"])
        self.assertTrue(info["audit"]["ok"])
        self.assertEqual(info["extension_store_error"], "")


if __name__ == "__main__":
    unittest.main()
