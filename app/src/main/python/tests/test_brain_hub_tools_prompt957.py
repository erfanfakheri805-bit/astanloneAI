"""
Prompt 957 - HubService tools: the permission-gated web reader, the device's connectivity report and the Android adapter
layer. The network and the phone are scripted doubles; the hub, the gate, the policy and the audit chain are the real ones.

Acceptance behaviours covered: 9 (network features fail clearly offline / permission-blocked; the rest keeps working),
plus the audit rule "a URL's query string and fragment never reach a log".
"""
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from android_adapters import NullBridge
from android_adapters.bridge import BridgeConnectivity
from brain_hub.service import HubService
from brain_hub.builtin_tools import safe_url_for_log
from tests import brain_hub_fixtures_prompt957 as F
from net_tools import TransportError

PAGE = "<html><head><title>سلام</title></head><body><p>متن آزمایشی</p></body></html>"


class HubCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "brain_hub")
        self.now = [1_700_000_000.0]
        self.hubs = []

    def tearDown(self):
        for hub in self.hubs:
            hub.close()

    def hub(self, **kw):
        kw.setdefault("clock", lambda: self.now[0])
        hub = HubService(self.root, **kw)
        self.hubs.append(hub)
        return hub

    def audit_text(self, hub):
        with open(hub.audit.path, encoding="utf-8") as handle:
            return handle.read()


class WebFetch(HubCase):
    def test_without_the_internet_permission_nothing_leaves_the_phone(self):
        transport = F.FakeFetchTransport(F.fetch_reply(PAGE))
        hub = self.hub(transport=transport, bridge=F.HubFakeBridge())
        result = hub.fetch("https://a.test/page")
        self.assertEqual((result.ok, result.code), (False, "permission_denied"))
        self.assertIn("اینترنت", result.message_fa)
        self.assertEqual(len(transport.requests), 0)
        self.assertEqual(hub.served_count("tool.web_fetch"), 0)
        last = hub.audit.entries()[-1]
        self.assertEqual((last["kind"], last["detail"]["code"], last["detail"]["ok"]), ("web.fetch", "permission_denied", False))

    def test_with_the_permission_a_page_is_read_as_persian_text(self):
        transport = F.FakeFetchTransport(F.fetch_reply(PAGE))
        hub = self.hub(transport=transport, bridge=F.HubFakeBridge())
        self.assertTrue(hub.grant_permission("network", user_approved=True).ok)
        result = hub.fetch("https://a.test/page")
        self.assertEqual((result.ok, result.code, result.status), (True, "ok", 200))
        self.assertEqual(result.title, "سلام")
        self.assertIn("متن آزمایشی", result.text)
        self.assertNotIn("<p>", result.text)
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(hub.served_count("tool.web_fetch"), 1)

    def test_a_query_string_and_fragment_never_reach_the_audit_log(self):
        transport = F.FakeFetchTransport(F.fetch_reply(PAGE))
        hub = self.hub(transport=transport, bridge=F.HubFakeBridge())
        hub.grant_permission("network", user_approved=True)
        result = hub.fetch("https://a.test/page?token=SECRET#frag", source="chat")
        self.assertTrue(result.ok)
        entry = hub.audit.entries()[-1]
        self.assertEqual((entry["kind"], entry["subject"]), ("web.fetch", "https://a.test/page"))
        self.assertEqual(entry["detail"]["source"], "chat")
        text = self.audit_text(hub)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("frag", text)
        self.assertTrue(hub.audit.verify()["ok"])

    def test_safe_url_for_log(self):
        self.assertEqual(safe_url_for_log("https://a.test/x/y?k=v#f"), "https://a.test/x/y")
        self.assertEqual(safe_url_for_log("https://a.test"), "https://a.test/")
        self.assertEqual(len(safe_url_for_log("https://a.test/" + "p" * 500)), len("https://a.test/") + 79)
        for bad in ("", "not a url", "ftp://a.test/", "https://user:pw@a.test/", None, 5):
            self.assertEqual(safe_url_for_log(bad), "", bad)

    def test_unsafe_addresses_are_refused_before_any_connection(self):
        transport = F.FakeFetchTransport(F.fetch_reply(PAGE))
        hub = self.hub(transport=transport, bridge=F.HubFakeBridge())
        hub.grant_permission("network", user_approved=True)
        cases = {"not a url": "invalid_url", "ftp://a.test/x": "unsupported_scheme", "http://a.test/": "unsupported_scheme",
                 "https://127.0.0.1/": "blocked_address", "https://localhost/": "blocked_address",
                 "https://192.168.1.1/": "blocked_address", "https://user:pw@a.test/": "invalid_url",
                 "https://a.test/\x00": "invalid_url", "": "invalid_url"}
        for url, code in cases.items():
            with self.subTest(url=url):
                result = hub.fetch(url)
                self.assertEqual((result.ok, result.code), (False, code))
                self.assertTrue(result.message_fa)
        self.assertEqual(len(transport.requests), 0)
        self.assertEqual(hub.served_count("tool.web_fetch"), 0)

    def test_network_failures_come_back_as_clear_results(self):
        for error, code in (("offline", "offline"), ("timeout", "timeout"), ("dns_failure", "dns_failure"),
                            ("connect_refused", "connect_refused"), ("tls_error", "tls_error")):
            with self.subTest(error=error):
                hub = self.hub(transport=F.FakeFetchTransport(TransportError(error)), bridge=F.HubFakeBridge())
                hub.grant_permission("network", user_approved=True)
                result = hub.fetch("https://a.test/")
                self.assertEqual((result.ok, result.code), (False, code))
                self.assertTrue(result.message_fa and result.message_en)
                self.assertEqual(hub.served_count("tool.web_fetch"), 0)
                hub.close()

    def test_unexpected_transport_exceptions_are_contained(self):
        hub = self.hub(transport=F.FakeFetchTransport(RuntimeError("boom with secret path /data/x")), bridge=F.HubFakeBridge())
        hub.grant_permission("network", user_approved=True)
        result = hub.fetch("https://a.test/")
        self.assertEqual((result.ok, result.code), (False, "unknown_error"))
        self.assertNotIn("secret", result.message_fa + result.message_en)
        self.assertNotIn("secret", self.audit_text(hub))

    def test_unsupported_content_and_http_errors(self):
        hub = self.hub(transport=F.FakeFetchTransport(F.fetch_reply("%PDF-1.4", ctype="application/pdf")), bridge=F.HubFakeBridge())
        hub.grant_permission("network", user_approved=True)
        self.assertEqual(hub.fetch("https://a.test/f.pdf").code, "unsupported_content_type")
        hub.close()
        hub = self.hub(transport=F.FakeFetchTransport(F.fetch_reply("nope", status=404)), bridge=F.HubFakeBridge())
        result = hub.fetch("https://a.test/missing")                       # the grant was persisted by the first hub
        self.assertEqual((result.ok, result.code, result.status), (False, "http_error", 404))
        self.assertEqual(hub.served_count("tool.web_fetch"), 0)

    def test_revoking_the_permission_stops_the_next_read(self):
        transport = F.FakeFetchTransport(F.fetch_reply(PAGE))
        hub = self.hub(transport=transport, bridge=F.HubFakeBridge())
        hub.grant_permission("network", user_approved=True)
        self.assertTrue(hub.fetch("https://a.test/").ok)
        self.assertTrue(hub.revoke_permission("network").ok)
        self.assertEqual(hub.fetch("https://a.test/").code, "permission_denied")
        self.assertEqual(len(transport.requests), 1)
        kinds = [e["kind"] for e in hub.audit.entries()]
        self.assertEqual(kinds, ["permission.grant", "web.fetch", "permission.revoke", "web.fetch"])

    def test_the_permission_is_never_granted_by_anything_but_an_exact_true(self):
        hub = self.hub(transport=F.FakeFetchTransport(F.fetch_reply(PAGE)), bridge=F.HubFakeBridge())
        for value in (False, None, 1, "yes", "true", [1]):
            with self.subTest(value=value):
                change = hub.grant_permission("network", user_approved=value)
                self.assertEqual((change.ok, change.code), (False, "approval_required"))
        self.assertEqual(hub.grant_permission("network").code, "approval_required")
        self.assertEqual(hub.grant_permission("camera", user_approved=True).code, "unknown_permission")
        self.assertFalse(hub.permissions.is_granted("network"))
        self.assertEqual(hub.fetch("https://a.test/").code, "permission_denied")

    def test_the_permission_survives_a_restart_and_a_damaged_file_grants_nothing(self):
        first = self.hub(bridge=F.HubFakeBridge())
        first.grant_permission("network", user_approved=True)
        first.close()
        second = self.hub(bridge=F.HubFakeBridge())
        self.assertTrue(second.permissions.is_granted("network"))
        second.close()
        with open(os.path.join(self.root, "permissions.json"), "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        third = self.hub(bridge=F.HubFakeBridge())
        report = third.ensure_started()
        self.assertFalse(third.permissions.is_granted("network"))
        self.assertTrue(report["permissions_recovery"])
        self.assertTrue(report["attention"])
        self.assertTrue(any(n.startswith("permissions.json.corrupt") for n in os.listdir(self.root)))


class NetworkReport(HubCase):
    """`PlatformAdapter` / device network reporting is truthful: only the device's own answer, never a guess."""

    def state(self, bridge=None):
        return self.hub(bridge=bridge).network_status()

    def test_online_offline_and_unknown_are_reported_as_the_device_says(self):
        self.assertEqual(self.state(F.HubFakeBridge(connectivity=BridgeConnectivity("online", "validated"))).state, "online")
        self.assertEqual(self.state(F.HubFakeBridge(connectivity=BridgeConnectivity("offline", "no_network"))).state, "offline")
        self.assertEqual(self.state(F.HubFakeBridge(connectivity=BridgeConnectivity("unknown", "x"))).state, "unknown")
        self.assertEqual(self.state(F.HubFakeBridge(connectivity=BridgeConnectivity("weird", "x"))).state, "unknown")

    def test_without_a_phone_the_state_is_unknown_not_online(self):
        status = self.state(NullBridge())
        self.assertEqual(status.state, "unknown")
        self.assertTrue(status.message_fa)
        self.assertEqual(self.hub().network_status().state, "unknown")          # a desktop run: detect_bridge() finds no phone

    def test_an_online_report_does_not_promise_that_a_request_succeeds(self):
        status = self.state(F.HubFakeBridge())
        self.assertIn("موفق", status.message_fa)

    def test_a_bridge_that_throws_is_contained(self):
        class Broken(F.HubFakeBridge):
            def connectivity(self):
                raise RuntimeError("native crash")
        self.assertEqual(self.state(Broken()).state, "unknown")

    def test_offline_chat_and_memory_style_features_keep_working(self):
        """Behaviour 9: with the phone offline, only the network node is blocked; the local ones stay usable."""
        hub = self.hub(bridge=F.HubFakeBridge(connectivity=BridgeConnectivity("offline", "no_network")),
                       transport=F.FakeFetchTransport(TransportError("offline")))
        hub.grant_permission("network", user_approved=True)
        graph = hub.graph()
        web = graph.get("tool.web_fetch")
        self.assertEqual((web.state, web.usable, web.blockers[0].kind), ("dependency_blocked", False, "network"))
        self.assertEqual(graph.get("brain.conversation").state, "available")
        self.assertTrue(graph.get("brain.conversation").usable)
        self.assertEqual(hub.execute("tool.web_fetch", "fetch", {"url": "https://a.test/"}).code, "not_usable")
        # even when the device is wrong about being offline, a read that fails says so clearly
        self.assertEqual(hub.fetch("https://a.test/").code, "offline")


class WebGraphStates(HubCase):
    def test_permission_blocked_then_available_then_active_then_dependency_blocked(self):
        bridge = F.HubFakeBridge()
        transport = F.FakeFetchTransport(F.fetch_reply(PAGE))
        hub = self.hub(transport=transport, bridge=bridge)
        node = hub.graph().get("tool.web_fetch")
        self.assertEqual((node.state, node.usable, node.blockers[0].kind), ("permission_blocked", False, "permission"))
        self.assertIn("اینترنت را روشن کن", node.blockers[0].text_fa)
        hub.grant_permission("network", user_approved=True)
        node = hub.graph().get("tool.web_fetch")
        self.assertEqual((node.state, node.usable, node.tested), ("available", True, False))
        self.assertIn("هنوز خواندن واقعی انجام نشده", node.evidence)
        self.assertTrue(hub.fetch("https://a.test/").ok)
        node = hub.graph().get("tool.web_fetch")
        self.assertEqual((node.state, node.tested), ("active", True))
        bridge.conn = BridgeConnectivity("offline", "no_network")
        self.assertEqual(hub.graph().get("tool.web_fetch").state, "dependency_blocked")
        hub.revoke_permission("network")
        self.assertEqual(hub.graph().get("tool.web_fetch").state, "permission_blocked")

    def test_the_router_runs_the_fetch_only_when_the_node_is_usable(self):
        transport = F.FakeFetchTransport(F.fetch_reply(PAGE))
        hub = self.hub(transport=transport, bridge=F.HubFakeBridge())
        blocked = hub.execute("tool.web_fetch", "fetch", {"url": "https://a.test/"})
        self.assertEqual((blocked.ok, blocked.code, blocked.state), (False, "not_usable", "permission_blocked"))
        self.assertIn("اینترنت", blocked.message_fa)
        self.assertEqual(len(transport.requests), 0)
        hub.grant_permission("network", user_approved=True)
        done = hub.execute("tool.web_fetch", "fetch", {"url": "https://a.test/"})
        self.assertEqual((done.ok, done.code), (True, "ok"))
        self.assertEqual(done.data["title"], "سلام")
        self.assertEqual(hub.execute("tool.web_fetch", "delete", {}).code, "unknown_action")
        bad = hub.execute("tool.web_fetch", "fetch", {"url": 5})
        self.assertEqual((bad.ok, bad.code), (False, "invalid_url"))
        missing = hub.execute("tool.web_fetch", "fetch")
        self.assertEqual((missing.ok, missing.code), (False, "invalid_url"))


class AndroidFeatures(HubCase):
    def test_statuses_are_exact_and_only_connectivity_has_an_implemented_action(self):
        hub = self.hub(bridge=F.HubFakeBridge())
        by_id = {s.feature_id: s for s in hub.android_statuses()}
        self.assertEqual(sorted(by_id), ["battery_status", "camera", "clipboard", "file_picker", "microphone", "network_state",
                                         "notifications", "settings_write", "telephony"])
        self.assertEqual((by_id["network_state"].state, by_id["network_state"].implemented, by_id["network_state"].actions),
                         ("ready", True, ("read",)))
        self.assertEqual([i for i, s in by_id.items() if s.implemented], ["network_state"])
        self.assertEqual(by_id["microphone"].state, "permission_required")
        self.assertEqual(by_id["camera"].state, "permission_required")
        self.assertEqual(by_id["notifications"].state, "permission_not_declared")
        self.assertEqual(by_id["settings_write"].state, "permission_not_declared")
        self.assertEqual(by_id["telephony"].state, "limited_by_android_policy")
        self.assertEqual(by_id["file_picker"].state, "ready")

    def test_without_a_phone_every_feature_says_the_platform_is_missing(self):
        hub = self.hub(bridge=NullBridge())
        states = {s.feature_id: s.state for s in hub.android_statuses()}
        self.assertEqual(set(states.values()), {"unavailable_platform"})
        graph = hub.graph()
        for fid in states:
            node = graph.get("android." + fid)
            self.assertFalse(node.usable, fid)
            self.assertNotEqual(node.state, "active", fid)

    def test_unknown_feature_ids(self):
        hub = self.hub(bridge=F.HubFakeBridge())
        self.assertIsNone(hub.android_status("nope"))
        self.assertEqual(hub.android_status("camera").feature_id, "camera")
        result = hub.android_request_permission("nope", user_approved=True)
        self.assertEqual((result.dispatched, result.code), (False, "unknown_feature"))

    def test_a_permission_dialog_is_never_requested_without_a_yes_or_for_a_feature_with_no_action(self):
        bridge = F.HubFakeBridge()
        hub = self.hub(bridge=bridge)
        cases = (("microphone", False, "approval_required"), ("microphone", True, "feature_not_implemented"),
                 ("camera", True, "feature_not_implemented"), ("telephony", True, "feature_not_implemented"),
                 ("network_state", False, "approval_required"), ("network_state", True, "not_runtime_permission"),
                 ("file_picker", True, "no_permission_needed"))
        for feature, approved, code in cases:
            with self.subTest(feature=feature, approved=approved):
                result = hub.android_request_permission(feature, user_approved=approved)
                self.assertEqual((result.dispatched, result.code), (False, code))
        for value in (None, 1, "yes", "true"):
            self.assertEqual(hub.android_request_permission("microphone", user_approved=value).code, "approval_required")
        self.assertEqual(bridge.request_calls, [])                      # the phone was never asked
        entries = [e for e in hub.audit.entries() if e["kind"] == "android.permission_request"]
        self.assertEqual(len(entries), len(cases) + 4 + 0)
        self.assertTrue(all(e["detail"]["dispatched"] is False for e in entries))
        self.assertTrue(hub.audit.verify()["ok"])

    def test_the_graph_names_what_is_missing_for_each_feature(self):
        hub = self.hub(bridge=F.HubFakeBridge())
        graph = hub.graph()
        net = graph.get("android.network_state")
        self.assertEqual((net.state, net.usable, net.actions), ("available", True, ("read",)))
        self.assertIn("هنوز روی دستگاه واقعی آزموده نشده", net.evidence)
        self.assertFalse(net.tested)
        mic = graph.get("android.microphone")
        self.assertEqual((mic.state, mic.usable), ("not_implemented", False))
        self.assertEqual([b.kind for b in mic.blockers], ["design", "permission"])
        self.assertIn("RECORD_AUDIO", mic.blockers[1].text_en)
        tel = graph.get("android.telephony")
        self.assertEqual((tel.state, tel.blockers[0].kind), ("policy_blocked", "policy"))
        picker = graph.get("android.file_picker")
        self.assertEqual((picker.state, picker.usable), ("available", True))
        self.assertEqual(graph.get("android.notifications").state, "not_implemented")

    def test_an_apk_without_the_native_file_chooser_says_it_needs_a_new_apk(self):
        hub = self.hub(bridge=F.HubFakeBridge(native=()))
        node = hub.graph().get("android.file_picker")
        self.assertEqual((node.state, node.usable, node.blockers[0].kind), ("dependency_blocked", False, "new_apk"))

    def test_the_router_reads_connectivity_through_the_adapter_and_refuses_the_rest(self):
        hub = self.hub(bridge=F.HubFakeBridge())
        done = hub.execute("android.network_state", "read")
        self.assertEqual((done.ok, done.code), (True, "ok"))
        self.assertEqual(hub.execute("android.microphone", "record").code, "not_usable")
        self.assertEqual(hub.execute("android.network_state", "write").code, "unknown_action")
        approval = hub.execute("android.microphone", "request_permission")
        self.assertEqual(approval.code, "approval_required")
        asked = hub.execute("android.microphone", "request_permission", user_approved=True)
        self.assertEqual((asked.ok, asked.code), (False, "feature_not_implemented"))
        self.assertEqual(hub.execute("android.nope", "read").code, "unknown_node")

    def test_a_failing_adapter_layer_is_contained(self):
        hub = self.hub(bridge=F.HubFakeBridge())

        class Boom:
            def all_statuses(self):
                raise RuntimeError("native crash")

            def status(self, fid):
                raise RuntimeError("native crash")

            network_probe = staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("native crash")))
        hub._android = Boom()
        self.assertEqual(hub.android_statuses(), [])
        graph = hub.graph()                                     # the builder fails inside; the graph still comes back
        self.assertEqual(hub.network_status().state, "unknown")
        self.assertIsNotNone(graph.get("brain.conversation"))


if __name__ == "__main__":
    unittest.main()
