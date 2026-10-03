"""
Tests for the Self-Upgrade Lifecycle Health Check (Prompt 385).

`SelfUpgradeHealthCheck` is a small, READ-ONLY diagnostic over the
existing Self-Upgrade components. These tests cover:

  - all components available -> HEALTHY (static and live);
  - one missing / broken component -> DEGRADED, naming it;
  - two or more -> FAILED;
  - broken wiring between live services is reported;
  - the check never raises and never calls a stage function;
  - the check is read-only: it creates, registers, and activates no
    capability, changes no approval state, no lifecycle state, no
    version history, starts no Self-Upgrade cycle, executes no
    generated code, and repairs / retries nothing.

The read-only tests reuse the end-to-end dry-run harness
(`DryRunHarness`, Prompt 384) so the check is run against a real,
mid-lifecycle system rather than a hand-built fixture.

Run: python -m unittest tests.test_self_upgrade_health_check -v
(from app/src/main/python/)
"""

import builtins
import contextlib
import importlib
import json
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.capability_system import CapabilitySystem
from diagnostics import self_upgrade_health_check as health_module
from diagnostics.self_upgrade_health_check import (
    SelfUpgradeHealthCheck,
    SELF_UPGRADE_COMPONENTS,
    CHECK_NAMES,
    STATUS_HEALTHY,
    STATUS_DEGRADED,
    STATUS_FAILED,
    ALL_STATUSES,
)
from memory.memory_system import MemorySystem
from self_upgrade.capability_approval_manager import ApprovalManager
from self_upgrade.self_upgrade_execution_context import SelfUpgradeExecutionContextStore
from self_upgrade.self_upgrade_lifecycle_coordinator import (
    SelfUpgradeLifecycleCoordinator,
    DECISION_WAIT_FOR_APPROVAL,
    DECISION_COMPLETED,
)
from self_upgrade.self_upgrade_resume_manager import SelfUpgradeResumeManager
from self_upgrade.version_system import VersionSystem
from tests.test_self_upgrade_end_to_end_dry_run import (
    DryRunHarness,
    UPGRADE_REQUEST_ID,
    TARGET_MODULE,
)

REQUIRED_CHECKS = (
    "analysis", "capability_planning", "capability_building", "validation", "testing",
    "versioning", "human_approval", "registration_preparation", "registration_approval",
    "registration", "registration_verification", "lifecycle_tracking",
    "execution_context_persistence", "resume_support", "lifecycle_coordinator",
)


@contextlib.contextmanager
def replaced(module_name, attribute, value):
    """Temporarily replace `module_name.attribute` with `value`."""
    module = importlib.import_module(module_name)
    original = getattr(module, attribute)
    setattr(module, attribute, value)
    try:
        yield
    finally:
        setattr(module, attribute, original)


@contextlib.contextmanager
def removed(module_name, attribute):
    """Temporarily delete `module_name.attribute` altogether."""
    module = importlib.import_module(module_name)
    original = getattr(module, attribute)
    delattr(module, attribute)
    try:
        yield
    finally:
        setattr(module, attribute, original)


@contextlib.contextmanager
def unimportable(*module_names):
    """Make `importlib.import_module` fail for the named modules only."""
    real = importlib.import_module

    def fake(name, *args, **kwargs):
        if name in module_names:
            raise ImportError(f"No module named {name!r} (simulated)")
        return real(name, *args, **kwargs)

    with mock.patch("importlib.import_module", side_effect=fake):
        yield


def check_named(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


def database_snapshot(memory):
    """Every row of every table, for a before/after comparison."""
    tables = [row["name"] for row in memory.query(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
    return {t: memory.query(f"SELECT * FROM {t}") for t in tables}


class StaticHealthTests(unittest.TestCase):
    def test_all_components_available_is_healthy(self):
        result = SelfUpgradeHealthCheck().check()
        self.assertEqual(result["status"], STATUS_HEALTHY, result["message"])
        self.assertEqual(result["failed_components"], [])
        self.assertEqual(result["checks_run"], 15)
        self.assertEqual(result["checks_passed"], 15)
        self.assertFalse(result["live_checked"])
        for check in result["checks"]:
            self.assertEqual(check["status"], STATUS_HEALTHY, check)
            self.assertEqual(check["problems"], [])
            self.assertFalse(check["live"])

    def test_every_required_check_is_reported_in_lifecycle_order(self):
        result = SelfUpgradeHealthCheck().check()
        self.assertEqual([c["name"] for c in result["checks"]], list(REQUIRED_CHECKS))
        self.assertEqual(CHECK_NAMES, REQUIRED_CHECKS)

    def test_result_shape_and_status_vocabulary(self):
        result = SelfUpgradeHealthCheck().check()
        self.assertEqual(set(result), {"status", "checks", "failed_components", "checks_run",
                                       "checks_passed", "live_checked", "message"})
        self.assertIn(result["status"], ALL_STATUSES)
        self.assertEqual(ALL_STATUSES, ("HEALTHY", "DEGRADED", "FAILED"))
        for check in result["checks"]:
            self.assertEqual(set(check), {"name", "status", "detail", "problems", "live"})
            self.assertIn(check["status"], (STATUS_HEALTHY, STATUS_FAILED))
        self.assertIsInstance(result["message"], str)
        self.assertTrue(result["message"])
        json.dumps(result)   # plain, serialisable data

    def test_the_check_is_deterministic(self):
        self.assertEqual(SelfUpgradeHealthCheck().check(), SelfUpgradeHealthCheck().check())

    def test_every_entry_point_checked_is_a_real_existing_component(self):
        for name, entries in SELF_UPGRADE_COMPONENTS:
            self.assertTrue(entries, name)
            for entry in entries:
                obj = getattr(importlib.import_module(entry["module"]), entry["name"])
                self.assertIsNotNone(obj, entry)


class OneBrokenComponentTests(unittest.TestCase):
    def assertDegraded(self, result, failed_name):
        self.assertEqual(result["status"], STATUS_DEGRADED, result["message"])
        self.assertEqual(result["failed_components"], [failed_name])
        self.assertEqual(result["checks_passed"], result["checks_run"] - 1)
        self.assertEqual(check_named(result, failed_name)["status"], STATUS_FAILED)
        self.assertTrue(check_named(result, failed_name)["problems"])
        for check in result["checks"]:
            if check["name"] != failed_name:
                self.assertEqual(check["status"], STATUS_HEALTHY, check)
        self.assertIn(failed_name, result["message"])

    def test_a_missing_function_is_degraded(self):
        with removed("self_upgrade.capability_builder", "build_capability"):
            result = SelfUpgradeHealthCheck().check()
        self.assertDegraded(result, "capability_building")
        self.assertIn("build_capability is missing", check_named(result, "capability_building")["detail"])

    def test_a_missing_class_is_degraded(self):
        with removed("self_upgrade.version_system", "VersionSystem"):
            result = SelfUpgradeHealthCheck().check()
        self.assertDegraded(result, "versioning")

    def test_a_component_that_is_not_callable_is_degraded(self):
        with replaced("self_upgrade.capability_registration_executor",
                      "register_approved_capability", None):
            result = SelfUpgradeHealthCheck().check()
        self.assertDegraded(result, "registration")

    def test_an_unimportable_module_is_degraded(self):
        with unimportable("self_upgrade.capability_registration_verifier"):
            result = SelfUpgradeHealthCheck().check()
        self.assertDegraded(result, "registration_verification")
        self.assertIn("could not be imported", check_named(result, "registration_verification")["detail"])

    def test_a_broken_connection_between_stages_is_degraded(self):
        # The stage still exists but no longer accepts what the previous
        # stage hands it - exactly the kind of disconnect a rename causes.
        def renamed(spec_renamed):
            return None
        with replaced("self_upgrade.capability_build_spec", "build_capability_build_spec", renamed):
            result = SelfUpgradeHealthCheck().check()
        self.assertDegraded(result, "capability_planning")
        self.assertIn("does not accept spec", check_named(result, "capability_planning")["detail"])

    def test_a_coordinator_that_cannot_take_stage_evidence_is_degraded(self):
        class OldCoordinator:
            def __init__(self, approval_manager=None):
                pass

            def decide(self, capability_name=None, build_result=None):
                pass

            def advance(self, context, capability_name=None):
                pass

            def resume(self, context):
                pass

        with replaced("self_upgrade.self_upgrade_lifecycle_coordinator",
                      "SelfUpgradeLifecycleCoordinator", OldCoordinator):
            result = SelfUpgradeHealthCheck().check()
        self.assertDegraded(result, "lifecycle_coordinator")
        self.assertIn("verification_result", check_named(result, "lifecycle_coordinator")["detail"])

    def test_a_class_missing_a_method_is_degraded(self):
        class NoLoad:
            def __init__(self, memory):
                pass

            def save(self, context):
                pass

            def get_or_create(self, upgrade_request_id, capability_name=None):
                pass

        with replaced("self_upgrade.self_upgrade_execution_context",
                      "SelfUpgradeExecutionContextStore", NoLoad):
            result = SelfUpgradeHealthCheck().check()
        self.assertDegraded(result, "execution_context_persistence")
        self.assertIn("no method load", check_named(result, "execution_context_persistence")["detail"])

    def test_the_message_says_nothing_was_repaired(self):
        with removed("self_upgrade.capability_builder", "build_capability"):
            result = SelfUpgradeHealthCheck().check()
        self.assertIn("nothing was repaired", result["message"].lower())


class MultipleBrokenComponentsTests(unittest.TestCase):
    def test_two_missing_components_are_failed(self):
        with removed("self_upgrade.capability_builder", "build_capability"), \
                removed("self_upgrade.version_system", "VersionSystem"):
            result = SelfUpgradeHealthCheck().check()
        self.assertEqual(result["status"], STATUS_FAILED, result["message"])
        self.assertEqual(result["failed_components"], ["capability_building", "versioning"])
        self.assertEqual(result["checks_passed"], 13)
        self.assertIn("capability_building", result["message"])
        self.assertIn("versioning", result["message"])

    def test_failed_components_are_listed_in_lifecycle_order(self):
        with removed("self_upgrade.self_upgrade_resume_manager", "SelfUpgradeResumeManager"), \
                removed("self_upgrade.capability_evaluation", "evaluate_capability_test_result"), \
                removed("self_upgrade.capability_lifecycle", "build_capability_lifecycle_state"):
            result = SelfUpgradeHealthCheck().check()
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertEqual(result["failed_components"], ["testing", "lifecycle_tracking", "resume_support"])

    def test_two_modules_failing_to_import_are_failed(self):
        with unimportable("self_upgrade.capability_registration_executor",
                          "self_upgrade.capability_registration_verifier"):
            result = SelfUpgradeHealthCheck().check()
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertEqual(result["failed_components"], ["registration", "registration_verification"])

    def test_everything_missing_is_failed_and_still_returns_a_result(self):
        with unimportable(*{entry["module"] for _, entries in SELF_UPGRADE_COMPONENTS
                            for entry in entries}):
            result = SelfUpgradeHealthCheck().check()
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertEqual(result["failed_components"], list(REQUIRED_CHECKS))
        self.assertEqual(result["checks_passed"], 0)

    def test_one_failure_in_a_multi_entry_check_fails_the_check_once(self):
        # 'human_approval' has four entry points; two broken ones are
        # still one failed component.
        with removed("self_upgrade.capability_approval_manager", "ApprovalManager"), \
                removed("self_upgrade.capability_first_pass_verification", "verify_capability_first_pass"):
            result = SelfUpgradeHealthCheck().check()
        self.assertEqual(result["status"], STATUS_DEGRADED)
        self.assertEqual(result["failed_components"], ["human_approval"])
        self.assertEqual(len(check_named(result, "human_approval")["problems"]), 2)


class LiveHealthTests(unittest.TestCase):
    def setUp(self):
        self.h = DryRunHarness()
        self.addCleanup(self.h.close)

    def health_check(self, **overrides):
        services = dict(
            version_system=self.h.versions, approval_manager=self.h.manager,
            capability_system=self.h.capability_system, context_store=self.h.store,
            coordinator=self.h.coordinator, resume_manager=self.h.resume_manager)
        services.update(overrides)
        return SelfUpgradeHealthCheck(**services)

    def test_a_correctly_wired_system_is_healthy(self):
        result = self.health_check().check()
        self.assertEqual(result["status"], STATUS_HEALTHY, result["message"])
        self.assertTrue(result["live_checked"])
        live = {c["name"] for c in result["checks"] if c["live"]}
        self.assertEqual(live, {"versioning", "human_approval", "registration_approval", "registration",
                                "registration_verification", "execution_context_persistence",
                                "resume_support", "lifecycle_coordinator"})

    def test_services_the_check_was_not_given_are_checked_statically_only(self):
        result = SelfUpgradeHealthCheck(version_system=self.h.versions).check()
        self.assertEqual(result["status"], STATUS_HEALTHY)
        self.assertEqual([c["name"] for c in result["checks"] if c["live"]], ["versioning"])

    def test_a_coordinator_wired_to_another_approval_manager_is_degraded(self):
        other_manager = ApprovalManager(self.h.memory)
        stray = SelfUpgradeLifecycleCoordinator(other_manager)
        result = self.health_check(coordinator=stray,
                                   resume_manager=SelfUpgradeResumeManager(self.h.store, stray)).check()
        self.assertEqual(result["status"], STATUS_DEGRADED)
        self.assertEqual(result["failed_components"], ["lifecycle_coordinator"])
        self.assertIn("different ApprovalManager", check_named(result, "lifecycle_coordinator")["detail"])

    def test_a_resume_manager_wired_to_another_coordinator_is_degraded(self):
        stray = SelfUpgradeResumeManager(self.h.store, SelfUpgradeLifecycleCoordinator(self.h.manager))
        result = self.health_check(resume_manager=stray).check()
        self.assertEqual(result["status"], STATUS_DEGRADED)
        self.assertEqual(result["failed_components"], ["resume_support"])
        self.assertIn("different coordinator", check_named(result, "resume_support")["detail"])

    def test_a_resume_manager_wired_to_another_context_store_is_degraded(self):
        stray = SelfUpgradeResumeManager(SelfUpgradeExecutionContextStore(self.h.memory),
                                         self.h.coordinator)
        result = self.health_check(resume_manager=stray).check()
        self.assertEqual(result["failed_components"], ["resume_support"])
        self.assertIn("different context store", check_named(result, "resume_support")["detail"])

    def test_a_service_of_the_wrong_type_is_degraded(self):
        result = self.health_check(version_system=object()).check()
        self.assertEqual(result["status"], STATUS_DEGRADED)
        self.assertEqual(result["failed_components"], ["versioning"])
        self.assertIn("is not a VersionSystem", check_named(result, "versioning")["detail"])

    def test_a_service_whose_lookup_raises_is_reported_not_raised(self):
        with mock.patch.object(VersionSystem, "current_version", side_effect=RuntimeError("db gone")):
            result = self.health_check().check()
        self.assertEqual(result["status"], STATUS_DEGRADED)
        self.assertEqual(result["failed_components"], ["versioning"])
        self.assertIn("RuntimeError", check_named(result, "versioning")["detail"])

    def test_a_service_two_checks_share_failing_fails_both_checks(self):
        with mock.patch.object(ApprovalManager, "get_stored_record", side_effect=RuntimeError("boom")):
            result = self.health_check().check()
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertEqual(result["failed_components"], ["human_approval", "registration_approval"])

    def test_no_active_version_is_reported(self):
        with mock.patch.object(VersionSystem, "current_version", return_value=None):
            result = self.health_check().check()
        self.assertEqual(result["failed_components"], ["versioning"])
        self.assertIn("no active version", check_named(result, "versioning")["detail"])

    def test_the_check_reports_on_a_mid_lifecycle_system(self):
        self.h.run_through("submit_for_approval")
        self.assertEqual(self.health_check().check()["status"], STATUS_HEALTHY)


class ReadOnlyTests(unittest.TestCase):
    """The health check must not change anything - checked against a real
    system, at the awkward moments: waiting at each approval gate and
    after a completed (verified) lifecycle."""

    def setUp(self):
        self.h = DryRunHarness()
        self.addCleanup(self.h.close)

    def live_check(self):
        return SelfUpgradeHealthCheck(
            version_system=self.h.versions, approval_manager=self.h.manager,
            capability_system=self.h.capability_system, context_store=self.h.store,
            coordinator=self.h.coordinator, resume_manager=self.h.resume_manager)

    @contextlib.contextmanager
    def forbid_all_mutation(self):
        """Any write to the database, any mutating call on a Self-Upgrade
        service, any file write, process, or network use fails the test."""
        real_open = builtins.open

        def guarded_open(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise AssertionError(f"health check tried to write a file: {file!r}")
            return real_open(file, mode, *args, **kwargs)

        def forbid(name):
            return mock.patch(name, side_effect=AssertionError(f"health check used {name}"))

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                MemorySystem, "_run", side_effect=AssertionError("health check wrote to the database")))
            for target, method in (
                    (CapabilitySystem, "register"), (CapabilitySystem, "set_enabled"),
                    (ApprovalManager, "create_request"), (ApprovalManager, "approve"),
                    (ApprovalManager, "reject"),
                    (VersionSystem, "create_version"), (VersionSystem, "rollback_to"),
                    (SelfUpgradeExecutionContextStore, "save"),
                    (SelfUpgradeExecutionContextStore, "get_or_create")):
                stack.enter_context(mock.patch.object(
                    target, method, side_effect=AssertionError(f"health check called {target.__name__}.{method}")))
            stack.enter_context(mock.patch("builtins.open", guarded_open))
            for name in ("subprocess.run", "subprocess.Popen", "socket.socket"):
                stack.enter_context(forbid(name))
            yield

    def snapshot(self):
        return {
            "database": database_snapshot(self.h.memory),
            "context": self.h.store.load(UPGRADE_REQUEST_ID),
            "versions": self.h.versions.history(),
            "registry": self.h.capability_system.all(),
            "workspace": sorted(os.listdir(self.h.workspace)),
        }

    def assertUnchangedByHealthCheck(self):
        before = self.snapshot()
        with self.forbid_all_mutation():
            result = self.live_check().check()
        self.assertEqual(result["status"], STATUS_HEALTHY, result["message"])
        self.assertEqual(self.snapshot(), before)
        return result

    def test_read_only_on_an_empty_system(self):
        self.assertUnchangedByHealthCheck()

    def test_read_only_while_waiting_at_the_first_approval_gate(self):
        self.h.run_through("submit_for_approval")
        self.assertUnchangedByHealthCheck()

    def test_read_only_while_waiting_at_the_registration_approval_gate(self):
        self.h.run_through("prepare_registration")
        self.assertUnchangedByHealthCheck()

    def test_read_only_after_a_verified_lifecycle(self):
        self.h.run_through("verify")
        self.assertUnchangedByHealthCheck()

    def test_read_only_when_a_component_is_broken(self):
        self.h.run_through("submit_for_approval")
        before = self.snapshot()
        with self.forbid_all_mutation(), removed("self_upgrade.capability_builder", "build_capability"):
            result = self.live_check().check()
        self.assertEqual(result["status"], STATUS_DEGRADED)
        self.assertEqual(self.snapshot(), before)

    def test_it_creates_no_capability(self):
        self.h.run_through("submit_for_approval")
        handlers_before = self.h.handlers.list_registered()
        self.live_check().check()
        self.assertEqual(self.h.registry_rows(), [])
        self.assertEqual(self.h.handlers.list_registered(), handlers_before)
        self.assertEqual(sorted(os.listdir(self.h.workspace)),
                         sorted([TARGET_MODULE + ".py", "test_selfupgrade_dryrun_echo_module.py"]))

    def test_it_registers_no_capability(self):
        self.h.run_through("prepare_registration")   # approved to plan, not yet registered
        with mock.patch.object(CapabilitySystem, "register") as register:
            self.live_check().check()
        register.assert_not_called()
        self.assertEqual(self.h.registry_rows(), [])
        # Even a fully approved registration request stays unregistered.
        self.h.approve_registration()
        self.live_check().check()
        self.assertEqual(self.h.registry_rows(), [])

    def test_it_activates_no_capability(self):
        self.h.run_through("verify")
        rows_before = self.h.registry_rows()
        with mock.patch.object(CapabilitySystem, "set_enabled") as set_enabled:
            self.live_check().check()
        set_enabled.assert_not_called()
        self.assertEqual(self.h.registry_rows(), rows_before)
        self.assertEqual(self.h.registry_rows()[0]["enabled"], 0)
        self.assertEqual(self.h.registry_rows()[0]["status"], "registered")

    def test_it_does_not_change_approval_state(self):
        self.h.run_through("submit_for_approval")
        approval_id = self.h.results["human_request"]["request_id"]
        before = self.h.manager.get_stored_record(approval_id)
        self.live_check().check()
        self.assertEqual(self.h.manager.get_stored_record(approval_id), before)
        self.assertEqual(before["status"], "PENDING_APPROVAL")
        self.assertEqual(self.h.count_state_keys("capability_approval:%"), 1)
        # ... and does not create, approve, or reject the second request.
        self.h.approve_first()
        self.h.prepare_registration()
        registration_id = self.h.results["registration_request_id"]
        before = self.h.manager.get_stored_record(registration_id)
        self.live_check().check()
        self.assertEqual(self.h.manager.get_stored_record(registration_id), before)
        self.assertEqual(before["status"], "PENDING_APPROVAL")
        self.assertEqual(self.h.count_state_keys("capability_approval:%"), 2)

    def test_it_does_not_modify_lifecycle_state(self):
        self.h.run_through("submit_for_approval")
        context_before = self.h.store.load(UPGRADE_REQUEST_ID)
        decision_before = self.h.decide()
        self.live_check().check()
        self.assertEqual(self.h.store.load(UPGRADE_REQUEST_ID), context_before)
        self.assertEqual(self.h.decide(), decision_before)
        self.assertEqual(self.h.decide()["decision"], DECISION_WAIT_FOR_APPROVAL)
        self.assertEqual(self.h.context, context_before)

    def test_it_does_not_advance_a_completed_lifecycle_or_start_a_new_cycle(self):
        self.h.run_through("verify")
        versions_before = len(self.h.versions.history())
        for _ in range(3):
            self.live_check().check()
        self.assertEqual(self.h.decide()["decision"], DECISION_COMPLETED)
        self.assertEqual(len(self.h.versions.history()), versions_before)
        self.assertEqual(self.h.count_state_keys("self_upgrade_execution_context:%"), 1)
        self.assertEqual(self.h.count_state_keys("capability_approval:%"), 2)

    def test_it_does_not_execute_generated_code(self):
        self.h.run_through("verify")
        self.live_check().check()
        self.assertEqual(self.h.probe.calls, [])
        self.assertNotIn(TARGET_MODULE, sys.modules)

    def test_it_never_calls_a_stage_function(self):
        # Every function the check inspects is swapped for a spec-preserving
        # mock that fails if called: the check must inspect, never invoke.
        with contextlib.ExitStack() as stack:
            spies = []
            for _, entries in SELF_UPGRADE_COMPONENTS:
                for entry in entries:
                    if entry["kind"] == "function":
                        module = importlib.import_module(entry["module"])
                        spies.append(stack.enter_context(mock.patch.object(
                            module, entry["name"], autospec=True,
                            side_effect=AssertionError(f"{entry['name']} was called"))))
            result = self.live_check().check()
        self.assertEqual(result["status"], STATUS_HEALTHY, result["message"])
        self.assertTrue(spies)
        for spy in spies:
            spy.assert_not_called()

    def test_it_does_not_repair_or_retry_a_broken_component(self):
        module = importlib.import_module("self_upgrade.capability_builder")
        original = module.build_capability
        with removed("self_upgrade.capability_builder", "build_capability"):
            first = self.live_check().check()
            second = self.live_check().check()
            still_missing = getattr(module, "build_capability", None)
        self.assertEqual(first["status"], STATUS_DEGRADED)
        self.assertEqual(first, second)
        self.assertIsNone(still_missing)          # not put back by the check
        self.assertIs(module.build_capability, original)   # restored only by the test's own context
        self.assertEqual(self.h.registry_rows(), [])


if __name__ == "__main__":
    unittest.main()
