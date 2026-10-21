"""
Prompt 957 - HubService: extensions end to end (propose -> approve -> invoke -> update -> rollback), rejection of bad
and malicious packages, extension permissions, restart and recovery. The real extension manager and sandbox run; only the
clock and the network are scripted.

Acceptance behaviours covered: 3 (a new capability outside the hard-coded archetypes), 4 (restart), 5 (failed/malicious
never active), 6 (update + rollback), plus the "no disk until used" and "approval is explicit" rules.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub.service import HubService
from tests import brain_hub_fixtures_prompt957 as F


class HubCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = self._tmp.name
        self.root = os.path.join(self.base, "brain_hub")
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

    def install(self, hub, pkg):
        proposal = hub.propose_package(F.dumps(pkg))
        self.assertEqual(proposal["status"], "pending_approval", proposal)
        applied = hub.approve_proposal(proposal["proposal_id"], user_approved=True)
        self.assertEqual(applied["status"], "applied", applied)
        return applied

    def node(self, hub, node_id):
        return hub.graph().get(node_id)

    def ext_path(self, *parts):
        return os.path.join(self.root, "extensions", *parts)


class NothingIsCreatedUntilUsed(HubCase):
    def test_reading_and_matching_touch_no_disk(self):
        hub = self.hub()
        self.assertFalse(hub.exists())
        hub.graph()
        hub.status()
        self.assertEqual(hub.extensions(), [])
        self.assertEqual(hub.pending_proposals(), [])
        self.assertEqual(hub.match_extension("تاریخ شمسی 2024 3 20"), {"status": "none"})
        self.assertEqual(hub.list_models(), [])
        self.assertIsNone(hub.find_extension("تاریخ"))
        self.assertEqual(hub.extension_history(), [])
        self.assertEqual(hub.extension_versions("x"), [])
        self.assertIsNone(hub.extension("x"))
        self.assertIsNone(hub.ensure_started())
        self.assertFalse(os.path.exists(self.root))

    def test_actions_on_a_missing_store_fail_cleanly(self):
        hub = self.hub()
        self.assertEqual(hub.invoke_extension("jalali_date", {})["status"], "not_found")
        self.assertEqual(hub.decline_proposal("p1")["status"], "failed")
        self.assertEqual(hub.approve_proposal("p1", user_approved=True)["status"], "failed")
        self.assertEqual(hub.rollback_extension("jalali_date", user_approved=True)["status"], "failed")
        self.assertEqual(hub.disable_extension("jalali_date")["status"], "failed")
        self.assertEqual(hub.enable_extension("jalali_date", user_approved=True)["status"], "failed")
        self.assertEqual(hub.grant_extension_permission("jalali_date", "clock", user_approved=True)["status"], "failed")
        self.assertEqual(hub.revoke_extension_permission("jalali_date", "clock")["status"], "failed")
        self.assertEqual(hub.repair_extension_store(user_approved=True)["status"], "nothing_to_repair")
        self.assertFalse(os.path.exists(self.root))

    def test_the_first_proposal_creates_the_private_store(self):
        hub = self.hub()
        self.assertEqual(hub.propose_package(F.dumps(F.jalali_pkg()))["status"], "pending_approval")
        self.assertTrue(os.path.isfile(self.ext_path("hub.db")))
        self.assertTrue(hub.exists())


class ApprovalIsExplicit(HubCase):
    def test_a_proposal_alone_installs_and_activates_nothing(self):
        hub = self.hub()
        proposal = hub.propose_package(F.dumps(F.jalali_pkg()))
        self.assertEqual((proposal["status"], proposal["action"], proposal["planned_version"]), ("pending_approval", "create", 1))
        self.assertEqual(proposal["tests"], {"passed": 5, "total": 5})
        self.assertEqual(hub.extensions(), [])
        self.assertEqual(hub.match_extension("تاریخ شمسی 2024 3 20"), {"status": "none"})
        self.assertEqual(hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["status"], "not_found")
        self.assertEqual(os.listdir(self.ext_path("modules")), [])
        graph = hub.graph()
        self.assertIsNone(graph.get("ext.jalali_date"))
        pending = graph.get("ext.jalali_date.pending")
        self.assertEqual((pending.state, pending.tested, pending.usable), ("pending_approval", True, False))
        self.assertEqual(pending.blockers[0].kind, "approval")

    def test_only_an_exact_true_approves(self):
        hub = self.hub()
        pid = hub.propose_package(F.dumps(F.jalali_pkg()))["proposal_id"]
        for value in (False, None, "yes", 1, "true", [], {"ok": 1}):
            with self.subTest(value=value):
                self.assertEqual(hub.approve_proposal(pid, user_approved=value)["status"], "approval_required")
        self.assertEqual(hub.approve_proposal(pid)["status"], "approval_required")
        self.assertEqual(hub.extensions(), [])
        self.assertEqual(len(hub.pending_proposals()), 1)

    def test_declining_leaves_nothing_behind(self):
        hub = self.hub()
        pid = hub.propose_package(F.dumps(F.jalali_pkg()))["proposal_id"]
        self.assertEqual(hub.decline_proposal(pid)["status"], "declined")
        self.assertEqual(hub.pending_proposals(), [])
        self.assertEqual(hub.approve_proposal(pid, user_approved=True)["status"], "not_pending")
        self.assertEqual(hub.extensions(), [])
        self.assertEqual(os.listdir(self.ext_path("modules")), [])

    def test_a_stale_proposal_expires(self):
        hub = self.hub()
        pid = hub.propose_package(F.dumps(F.jalali_pkg()))["proposal_id"]
        self.now[0] += 8 * 24 * 3600
        self.assertEqual(hub.pending_proposals(), [])
        self.assertIn(hub.approve_proposal(pid, user_approved=True)["status"], ("expired", "not_pending"))
        self.assertEqual(hub.extensions(), [])


class NewCapabilityEndToEnd(HubCase):
    """Behaviour 3: a capability that is NOT unit conversion / formula / text tool, defined through the extension mechanism."""

    def test_install_then_use_it_from_a_sentence(self):
        hub = self.hub()
        applied = self.install(hub, F.jalali_pkg())
        self.assertEqual((applied["capability_id"], applied["version"], applied["tests"]), ("jalali_date", 1, {"passed": 5, "total": 5}))
        self.assertTrue(applied["verified"]["callable"] and applied["verified"]["loadable"] and applied["verified"]["registered"])
        for gy, gm, gd, jy, jm, jd in F.JALALI_DATES:
            hit = hub.match_extension("تاریخ شمسی %d %d %d" % (gy, gm, gd))
            self.assertEqual((hit["status"], hit["capability_id"]), ("invoke", "jalali_date"))
            out = hub.invoke_extension(hit["capability_id"], hit["inputs"])
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["outputs"], {"jy": jy, "jm": jm, "jd": jd})
        # an independent check of the algorithm: the day after the last Esfand of 1402 is Nowruz 1403
        self.assertEqual(hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["outputs"], {"jy": 1403, "jm": 1, "jd": 1})
        self.assertEqual(hub.invoke_extension("jalali_date", {"gy": 2025, "gm": 1, "gd": 1})["outputs"], {"jy": 1403, "jm": 10, "jd": 12})

    def test_the_answer_text_uses_persian_digits_and_the_template(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        out = hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})
        self.assertEqual(out["answer"], "۲۰۲۴/۳/۲۰ میلادی = ۱۴۰۳/۱/۱ شمسی")

    def test_bad_input_is_reported_not_raised(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        month = hub.match_extension("تاریخ شمسی 2024 13 20")
        self.assertEqual((month["status"], month["problems"][0]["name"]), ("invalid_inputs", "gm"))
        out = hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 13, "gd": 20})
        self.assertEqual((out["ok"], out["status"]), (False, "invalid_inputs"))
        self.assertEqual(hub.invoke_extension("jalali_date", {"gy": "x"})["status"], "invalid_inputs")
        self.assertEqual(hub.match_extension("تاریخ شمسی 2024 3")["status"], "none")
        self.assertEqual(hub.match_extension("سلام")["status"], "none")

    def test_the_graph_shows_it_as_registered_tested_and_active(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        node = self.node(hub, "ext.jalali_date")
        self.assertEqual((node.state, node.tested, node.usable, node.version), ("active", True, True, 1))
        self.assertEqual(node.actions, ("invoke",))
        self.assertIn("آزمون", " ".join(node.evidence))
        self.assertIsNone(self.node(hub, "ext.jalali_date.pending"))
        self.assertEqual(hub.served_count("ext.jalali_date"), 0)
        hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})
        self.assertEqual(hub.served_count("ext.jalali_date"), 1)

    def test_only_successful_runs_count_as_served(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 13, "gd": 20})
        hub.invoke_extension("jalali_date", {"gy": "x"})
        hub.invoke_extension("nope", {})
        self.assertEqual((hub.served_count("ext.jalali_date"), hub.served_count("ext.nope")), (0, 0))
        hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})
        self.assertEqual(hub.served_count("ext.jalali_date"), 1)

    def test_two_extensions_coexist_and_the_right_one_answers(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        self.install(hub, F.factors_pkg())
        self.assertEqual(hub.match_extension("عوامل اول 360")["capability_id"], "prime_factors")
        self.assertEqual(hub.invoke_extension("prime_factors", {"n": 360})["outputs"], {"factors": [2, 2, 2, 3, 3, 5], "count": 6})
        self.assertEqual(hub.match_extension("تاریخ شمسی 2024 3 20")["capability_id"], "jalali_date")
        self.assertEqual(sorted(c["capability_id"] for c in hub.extensions()), ["jalali_date", "prime_factors"])
        self.assertEqual(hub.find_extension("تبدیل تاریخ میلادی به شمسی"), "jalali_date")

    def test_installing_the_same_package_twice_changes_nothing(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        again = hub.propose_package(F.dumps(F.jalali_pkg()))
        self.assertEqual((again["status"], again["version"]), ("noop_identical", 1))
        self.assertEqual(hub.pending_proposals(), [])

    def test_a_package_may_arrive_as_a_zip_or_a_fenced_block(self):
        import io
        import zipfile
        hub = self.hub()
        pkg = F.jalali_pkg()
        source = pkg.pop("source")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", json.dumps(pkg, ensure_ascii=False))
            zf.writestr("ext.py", source)
        self.assertEqual(hub.propose_package(buf.getvalue())["status"], "pending_approval")
        fenced = "این بسته است:\n```json\n" + F.dumps(F.factors_pkg()) + "\n```\n"
        self.assertEqual(hub.propose_package(fenced)["status"], "pending_approval")


class RejectedPackagesNeverBecomeActive(HubCase):
    """Behaviour 5."""

    def assert_nothing_installed(self, hub):
        self.assertEqual(hub.extensions(), [])
        self.assertEqual(hub.pending_proposals(), [])
        self.assertEqual(hub.match_extension("تاریخ شمسی 2024 3 20"), {"status": "none"})
        modules = self.ext_path("modules")
        self.assertEqual(os.listdir(modules) if os.path.isdir(modules) else [], [])
        graph = hub.graph()
        self.assertEqual([n.node_id for n in graph.nodes(kind="extension")], [])

    def test_malicious_sources_are_rejected_before_anything_runs(self):
        for kind in F.MALICIOUS:
            with self.subTest(kind=kind):
                hub = self.hub()
                result = hub.propose_package(F.dumps(F.malicious_pkg(kind)))
                self.assertEqual(result["status"], "rejected", result)
                self.assertIn(result["stage"], ("source", "tests"))
                self.assertTrue(result["issues"])
                self.assert_nothing_installed(hub)
                self.assertEqual(hub.approve_proposal("pnone", user_approved=True)["status"], "failed")

    def test_a_failing_own_test_is_rejected_at_the_tests_stage(self):
        hub = self.hub()
        result = hub.propose_package(F.dumps(F.broken_tests_pkg()))
        self.assertEqual((result["status"], result["stage"], result["code"]), ("rejected", "tests", "E_EXT_TESTS"))
        self.assertIn("1400", result["issues"][0]["message"])
        self.assert_nothing_installed(hub)

    def test_garbage_packages_are_rejected_with_a_stage(self):
        hub = self.hub()
        cases = {"empty": "", "spaces": "   ", "not json": "{nope", "list": "[1, 2]", "binary": b"\xff\xfe\x00\x01",
                 "huge": "x" * 250_000, "no id": json.dumps({"schema": "ext.v1"}), "wrong schema": json.dumps({"schema": "ext.v9", "id": "abc"}),
                 "duplicate keys": '{"schema": "ext.v1", "schema": "ext.v1"}', "nan": '{"schema": "ext.v1", "x": NaN}'}
        for label, data in cases.items():
            with self.subTest(label=label):
                result = hub.propose_package(data)
                self.assertEqual(result["status"], "rejected", label)
                self.assertIn(result["stage"], ("package", "manifest"))
        self.assert_nothing_installed(hub)

    def test_a_wrong_expected_hash_is_refused(self):
        hub = self.hub()
        self.assertEqual(hub._manager(create=True).propose(F.dumps(F.jalali_pkg()), expected_sha256="0" * 64)["code"], "E_PACKAGE_HASH")
        self.assert_nothing_installed(hub)

    def test_an_id_used_by_another_capability_is_refused(self):
        hub = self.hub()

        class FakeSB:
            def capability(self, cid):
                return {"id": cid} if cid == "jalali_date" else None
        hub._sb = lambda: FakeSB()
        result = hub.propose_package(F.dumps(F.jalali_pkg()))
        self.assertEqual((result["status"], result["code"]), ("rejected", "E_EXT_ID_TAKEN"))
        self.assertEqual(hub.propose_package(F.dumps(F.factors_pkg()))["status"], "pending_approval")

    def test_a_rejection_after_an_install_leaves_the_installed_version_alone(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        bad = hub.propose_package(F.dumps(F.jalali_pkg(source=F.MALICIOUS["escape"])))
        self.assertEqual(bad["status"], "rejected")
        out = hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})
        self.assertTrue(out["ok"])
        self.assertEqual(out["version"], 1)


class UpdateAndRollback(HubCase):
    """Behaviour 6."""

    V1 = "{gy}/{gm}/{gd} میلادی = {jy}/{jm}/{jd} شمسی"
    V2 = "تاریخ شمسی: {jy}-{jm}-{jd}"

    def test_an_update_is_version_two_and_rollback_restores_version_one(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg(answer=self.V1))
        before = hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["answer"]
        proposal = hub.propose_package(F.dumps(F.jalali_pkg(answer=self.V2, title="تبدیل تاریخ (نسخهٔ ۲)")))
        self.assertEqual((proposal["status"], proposal["action"], proposal["planned_version"]), ("pending_approval", "update", 2))
        self.assertEqual(hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["answer"], before)      # not yet
        applied = hub.approve_proposal(proposal["proposal_id"], user_approved=True)
        self.assertEqual((applied["status"], applied["version"], applied["previous_version"]), ("applied", 2, 1))
        after = hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})
        self.assertEqual((after["version"], after["answer"]), (2, "تاریخ شمسی: ۱۴۰۳-۱-۱"))
        self.assertNotEqual(after["answer"], before)
        versions = hub.extension_versions("jalali_date")
        self.assertEqual([(v["version"], v["status"]) for v in versions], [(1, "superseded"), (2, "active")])
        self.assertEqual(os.path.isfile(self.ext_path("modules", "jalali_date_v1.py")) and os.path.isfile(self.ext_path("modules", "jalali_date_v2.py")), True)

        self.assertEqual(hub.rollback_extension("jalali_date")["status"], "approval_required")
        self.assertEqual(hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["version"], 2)
        rolled = hub.rollback_extension("jalali_date", user_approved=True)
        self.assertEqual((rolled["status"], rolled["from_version"], rolled["to_version"]), ("rolled_back", 2, 1))
        back = hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})
        self.assertEqual((back["version"], back["answer"]), (1, before))
        self.assertEqual([(v["version"], v["status"]) for v in hub.extension_versions("jalali_date")], [(1, "active"), (2, "rolled_back")])
        self.assertEqual(self.node(hub, "ext.jalali_date").version, 1)

    def test_history_records_every_step(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg(answer=self.V1))
        pid = hub.propose_package(F.dumps(F.jalali_pkg(answer=self.V2)))["proposal_id"]
        hub.approve_proposal(pid, user_approved=True)
        hub.rollback_extension("jalali_date", user_approved=True)
        events = [e["event"] for e in hub.extension_history("jalali_date", limit=30)]
        for name in ("ext.proposed", "ext.approved", "ext.activated", "ext.rolled_back"):
            self.assertIn(name, events)
        self.assertEqual(events[0], "ext.rolled_back")
        self.assertTrue(hub.status()["extension_store"]["audit"]["ok"])

    def test_rolling_back_the_first_version_has_nowhere_to_go(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        self.assertEqual(hub.rollback_extension("jalali_date", user_approved=True)["status"], "nothing_to_roll_back")
        self.assertTrue(hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["ok"])

    def test_a_declined_update_keeps_the_running_version(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg(answer=self.V1))
        pid = hub.propose_package(F.dumps(F.jalali_pkg(answer=self.V2)))["proposal_id"]
        hub.decline_proposal(pid)
        self.assertEqual(hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["version"], 1)
        self.assertEqual(len(hub.extension_versions("jalali_date")), 1)

    def test_disable_and_enable(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        self.assertEqual(hub.disable_extension("jalali_date")["status"], "disabled")
        self.assertEqual(hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["status"], "disabled")
        self.assertEqual(hub.match_extension("تاریخ شمسی 2024 3 20")["status"], "none")
        node = self.node(hub, "ext.jalali_date")
        self.assertEqual((node.state, node.usable, node.actions), ("disabled", False, ()))
        self.assertEqual(node.blockers[0].kind, "approval")
        self.assertEqual(hub.enable_extension("jalali_date")["status"], "approval_required")
        self.assertEqual(self.node(hub, "ext.jalali_date").state, "disabled")
        self.assertEqual(hub.enable_extension("jalali_date", user_approved=True)["status"], "enabled")
        self.assertTrue(hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["ok"])
        self.assertEqual(self.node(hub, "ext.jalali_date").state, "active")


class ExtensionPermissions(HubCase):
    def test_a_declared_permission_is_granted_at_approval_and_can_be_revoked(self):
        hub = self.hub()
        self.install(hub, F.clock_pkg())
        self.now[0] = 3660.0
        out = hub.invoke_extension("clock_reader", {})
        self.assertEqual(out["outputs"], {"hour": 1, "minute": 1})
        self.assertEqual(self.node(hub, "ext.clock_reader").state, "active")
        self.assertEqual(hub.revoke_extension_permission("clock_reader", "clock")["status"], "revoked")
        blocked = hub.invoke_extension("clock_reader", {})
        self.assertEqual((blocked["ok"], blocked["status"], blocked["missing_permissions"]), (False, "blocked_permission", ["clock"]))
        node = self.node(hub, "ext.clock_reader")
        self.assertEqual((node.state, node.usable, [b.kind for b in node.blockers]), ("permission_blocked", False, ["permission"]))
        self.assertEqual(hub.grant_extension_permission("clock_reader", "clock")["status"], "approval_required")
        self.assertEqual(hub.invoke_extension("clock_reader", {})["status"], "blocked_permission")
        self.assertEqual(hub.grant_extension_permission("clock_reader", "clock", user_approved=True)["status"], "granted")
        self.assertTrue(hub.invoke_extension("clock_reader", {})["ok"])

    def test_only_declared_permissions_can_be_granted(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        self.assertEqual(hub.grant_extension_permission("jalali_date", "network", user_approved=True)["code"], "E_EXT_PERMISSION")
        self.assertEqual(hub.grant_extension_permission("jalali_date", "storage", user_approved=True)["status"], "failed")

    def test_the_network_helper_needs_the_extension_grant_and_the_apps_internet_permission(self):
        transport = F.FakeFetchTransport(F.fetch_reply("<html><head><title>T</title></head><body><p>alpha beta gamma delta epsilon</p></body></html>"))
        hub = self.hub(transport=transport)
        self.install(hub, F.words_pkg())
        call = lambda: hub.invoke_extension("page_words", {"url": "https://a.test/page?token=SECRET"})  # noqa: E731
        # app-level internet permission off: the extension's own grant is not enough, and no socket is touched
        refused = call()
        self.assertEqual((refused["ok"], refused["status"]), (False, "runtime_error"))
        self.assertEqual(len(transport.requests), 0)
        self.assertEqual(hub.grant_permission("network").code, "approval_required")
        self.assertEqual(len(transport.requests), 0)
        self.assertTrue(hub.grant_permission("network", user_approved=True).ok)
        ok = call()
        self.assertEqual((ok["ok"], ok["outputs"]), (True, {"words": 5}))
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(transport.requests[0].url, "https://a.test/page?token=SECRET")
        # the extension's own grant revoked: blocked again even though the app permission is on
        hub.revoke_extension_permission("page_words", "network")
        self.assertEqual(call()["status"], "blocked_permission")
        self.assertEqual(len(transport.requests), 1)
        # app permission revoked: the (re-granted) extension is refused again
        hub.grant_extension_permission("page_words", "network", user_approved=True)
        self.assertTrue(call()["ok"])
        hub.revoke_permission("network")
        self.assertEqual(call()["status"], "runtime_error")
        self.assertEqual(len(transport.requests), 2)
        with open(hub.audit.path, encoding="utf-8") as handle:
            audit_text = handle.read()
        self.assertIn('"source":"extension"', audit_text)
        self.assertNotIn("SECRET", audit_text)
        self.assertTrue(hub.audit.verify()["ok"])


class RestartAndRecovery(HubCase):
    """Behaviour 4 (and the recovery of interrupted operations)."""

    def test_everything_survives_a_restart(self):
        first = self.hub()
        self.install(first, F.jalali_pkg())
        self.install(first, F.factors_pkg())
        first.close()
        second = self.hub()
        self.assertIsNone(second.startup_report)
        report = second.ensure_started()
        self.assertIsNotNone(report)
        self.assertFalse(report["attention"], report)
        self.assertEqual(sorted(c["capability_id"] for c in second.extensions()), ["jalali_date", "prime_factors"])
        hit = second.match_extension("تاریخ شمسی 2024 3 20")
        self.assertEqual(second.invoke_extension(hit["capability_id"], hit["inputs"])["outputs"], {"jy": 1403, "jm": 1, "jd": 1})
        node = self.node(second, "ext.jalali_date")
        self.assertEqual((node.state, node.tested, node.version), ("active", True, 1))
        self.assertTrue(second.audit.verify()["ok"])
        self.assertEqual(second.ensure_started(), report)                       # once per process

    def test_startup_runs_once_even_when_called_directly(self):
        first = self.hub()
        self.install(first, F.jalali_pkg())
        first.close()
        again = self.hub()
        report = again.startup()
        self.assertIs(again.startup(), report)
        self.assertIs(again.ensure_started(), report)
        self.assertEqual(len([e for e in again.audit.entries() if e["kind"] == "hub.started"]), 1)

    def test_attention_is_raised_for_every_kind_of_trouble_but_not_for_routine_cleanup(self):
        first = self.hub()
        self.install(first, F.jalali_pkg())
        first.close()

        class FakeManager:
            def __init__(self, report):
                self.report = report

            def reconcile(self):
                return dict(self.report)

            def close(self):
                pass
        for report in ({"failed_versions": [1]}, {"fell_back": 1}, {"disabled": 2}, {"quarantined": ["x"]}):
            with self.subTest(report=report):
                again = self.hub()
                again._ext = FakeManager(report)
                self.assertTrue(again.startup()["attention"])
        for report in ({"partials_removed": 3, "expired_proposals": 1}, {}):
            with self.subTest(report=report):
                again = self.hub()
                again._ext = FakeManager(report)
                self.assertFalse(again.startup()["attention"])

    def test_a_pending_proposal_survives_a_restart_and_can_still_be_approved(self):
        first = self.hub()
        pid = first.propose_package(F.dumps(F.jalali_pkg()))["proposal_id"]
        first.close()
        second = self.hub()
        self.assertEqual([p["proposal_id"] for p in second.pending_proposals()], [pid])
        self.assertEqual(second.approve_proposal(pid, user_approved=True)["status"], "applied")
        self.assertTrue(second.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["ok"])

    def test_permissions_survive_a_restart(self):
        first = self.hub()
        first.grant_permission("network", user_approved=True)
        first.close()
        self.assertTrue(self.hub().permissions.is_granted("network"))

    def test_a_damaged_active_version_falls_back_to_the_previous_one(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg(answer="v1 {jy}"))
        self.install(hub, F.jalali_pkg(answer="v2 {jy}"))
        hub.close()
        with open(self.ext_path("modules", "jalali_date_v2.py"), "a", encoding="utf-8") as handle:
            handle.write("\n# tampered\n")
        again = self.hub()
        report = again.ensure_started()
        self.assertTrue(report["attention"])
        self.assertEqual(report["extensions"]["fell_back"], 1)
        out = again.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})
        self.assertEqual((out["ok"], out["version"], out["answer"]), (True, 1, "v1 ۱۴۰۳"))
        self.assertEqual(self.node(again, "ext.jalali_date").version, 1)

    def test_a_damaged_only_version_is_disabled_never_run(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        hub.close()
        with open(self.ext_path("modules", "jalali_date_v1.py"), "w", encoding="utf-8") as handle:
            handle.write("def run(gy, gm, gd):\n    return {'jy': 1, 'jm': 1, 'jd': 1}\n")
        again = self.hub()
        report = again.ensure_started()
        self.assertTrue(report["attention"])
        self.assertEqual(report["extensions"]["disabled"], 1)
        out = again.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "disabled")
        self.assertEqual(self.node(again, "ext.jalali_date").state, "disabled")

    def test_partial_writes_are_swept_and_orphans_quarantined(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        hub.close()
        modules = self.ext_path("modules")
        for name in ("jalali_date_v7.py.partial", "x.tmp"):
            with open(os.path.join(modules, name), "w") as handle:
                handle.write("partial")
        with open(os.path.join(modules, "orphan_ext_v1.py"), "w") as handle:
            handle.write("def run():\n    return {}\n")
        report = self.hub().ensure_started()
        self.assertGreaterEqual(report["extensions"]["partials_removed"] + report["extensions"]["quarantined"], 1)
        self.assertFalse(os.path.exists(os.path.join(modules, "orphan_ext_v1.py")))
        self.assertTrue(self.hub().invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["ok"])

    def test_a_damaged_extension_database_is_reported_never_raised_and_never_trusted(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        hub.close()
        with open(self.ext_path("hub.db"), "wb") as handle:
            handle.write(b"this is not a database" * 50)
        again = self.hub()
        report = again.ensure_started()
        self.assertTrue(report["attention"])
        self.assertIn("extensions:store_unusable", report["errors"])
        # every entry point reports instead of raising, and nothing runs from a store that cannot be verified
        self.assertEqual(again.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["status"], "not_found")
        self.assertEqual(again.extensions(), [])
        self.assertEqual(again.pending_proposals(), [])
        self.assertEqual(again.match_extension("تاریخ شمسی 2024 3 20"), {"status": "none"})
        info = again.status()
        self.assertTrue(info["extension_store_error"])
        self.assertIsNone(info["extension_store"])
        node = again.graph().get("hub.extension_store")
        self.assertEqual((node.state, node.usable, node.blockers[0].kind), ("broken", False, "test"))
        refused = again.propose_package(F.dumps(F.factors_pkg()))
        self.assertEqual((refused["status"], refused["code"]), ("error", "E_HUB_EXT_STORE"))
        self.assertIn("ترمیم", refused["message_fa"])
        self.assertEqual(again.approve_proposal("p1", user_approved=True)["status"], "failed")

    def test_repair_needs_a_yes_keeps_the_old_files_and_starts_fresh(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        hub.close()
        with open(self.ext_path("hub.db"), "wb") as handle:
            handle.write(b"this is not a database" * 50)
        again = self.hub()
        self.assertEqual(again.repair_extension_store()["status"], "approval_required")
        for value in (False, None, "yes", 1):
            self.assertEqual(again.repair_extension_store(user_approved=value)["status"], "approval_required")
        self.assertEqual(again.execute("hub.extension_store", "repair").code, "approval_required")
        self.assertTrue(os.path.isfile(self.ext_path("hub.db")))
        done = again.execute("hub.extension_store", "repair", user_approved=True)
        self.assertEqual((done.ok, done.data["status"]), (True, "repaired"))
        names = os.listdir(self.ext_path())
        self.assertTrue(any(n.startswith("hub.db.corrupt.") for n in names), names)
        self.assertTrue(any(n.startswith("modules.corrupt.") for n in names), names)
        self.assertTrue(os.path.isfile(self.ext_path("modules.corrupt.1", "jalali_date_v1.py")))     # kept, not deleted
        self.assertFalse(os.path.exists(self.ext_path("hub.db")))
        self.assertIsNone(again.graph().get("hub.extension_store"))
        self.install(again, F.factors_pkg())
        self.assertEqual(again.invoke_extension("prime_factors", {"n": 12})["outputs"]["factors"], [2, 2, 3])
        self.assertEqual([c["capability_id"] for c in again.extensions()], ["prime_factors"])
        events = [e["kind"] for e in again.audit.entries()]
        self.assertIn("ext.store_repaired", events)

    def test_a_healthy_store_is_never_set_aside(self):
        hub = self.hub()
        self.install(hub, F.jalali_pkg())
        self.assertEqual(hub.repair_extension_store(user_approved=True)["status"], "not_damaged")
        self.assertTrue(hub.invoke_extension("jalali_date", {"gy": 2024, "gm": 3, "gd": 20})["ok"])
        self.assertFalse(any("corrupt" in n for n in os.listdir(self.ext_path())))


if __name__ == "__main__":
    unittest.main()
