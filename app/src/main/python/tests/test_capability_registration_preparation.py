"""
Tests for self_upgrade.capability_registration_preparation
.prepare_capability_registration (Prompt 373) - after a capability has
passed the existing human approval gate, assembles (but never performs)
the structured information a future Capability Registry entry needs:
APPROVED capability -> Registration Preparation -> READY_FOR_REGISTRATION.

Covers: BLOCKED for pending/rejected/blocked approvals; the existing
approval model's INVALID passing through unchanged (a request that only
*claims* APPROVED, no ApprovalManager, malformed input); READY_FOR_
REGISTRATION only for an explicitly APPROVED capability with valid
build information; INVALID for missing capability name / interface /
target module / schemas / mismatched capability; and that preparation
never registers, activates, executes, versions, approves, or modifies
anything.

Run directly:
    python -m unittest tests.test_capability_registration_preparation -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import ast
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent_loop import AgentLoop
from capabilities.capability_system import CapabilitySystem
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.code_change_plan_capability import (
    CAPABILITY_NAME as CODE_CHANGE_PLAN_NAME,
    create_code_change_plan_capability,
)
from execution.plan_execution_controller import PlanExecutionController
from memory.memory_system import MemorySystem
from planning.adaptive_plan_analyzer import AdaptivePlanAnalyzer
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from self_upgrade import capability_registration_preparation as preparation_module
from self_upgrade.capability_approval_manager import ApprovalManager
from self_upgrade.capability_build_spec import (
    build_capability_build_spec,
    STATUS_READY as BUILD_SPEC_STATUS_READY,
    STATUS_BLOCKED as BUILD_SPEC_STATUS_BLOCKED,
)
from self_upgrade.capability_correction_verification import STATUS_VERIFIED
from self_upgrade.capability_creation_plan import build_capability_creation_plan
from self_upgrade.capability_human_approval import (
    request_capability_human_approval,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_BLOCKED,
    APPROVAL_STATUS_INVALID,
)
from self_upgrade.capability_implementation_spec import build_capability_implementation_spec
from self_upgrade.capability_registration_preparation import (
    prepare_capability_registration,
    REGISTRATION_STATUS_BLOCKED,
    REGISTRATION_STATUS_INVALID,
    REGISTRATION_STATUS_READY_FOR_REGISTRATION,
    ALL_REGISTRATION_STATUSES,
)
from self_upgrade.self_upgrade_request import SelfUpgradeRequest
from self_upgrade.version_system import VersionSystem

PREPARATION_KEYS = {
    "capability_name", "interface_name", "target_module", "purpose",
    "input_schema", "output_schema", "dependencies", "source_version",
    "approval_request_id", "status", "reason", "errors", "created_at",
}
REGISTRY_FIELDS = (
    "interface_name", "target_module", "purpose", "input_schema",
    "output_schema", "source_version",
)


class _FakeCapabilitySystem:
    def __init__(self, registered):
        self._registered = dict(registered)

    def all(self):
        return [{"name": n, "enabled": e, "status": "enabled" if e else "disabled"}
                for n, e in self._registered.items()]


def _real_ready_build_spec(handlers):
    """A real READY CapabilityBuildSpec, produced by the existing chain
    (SelfUpgradeRequest -> analysis -> creation plan -> implementation
    spec -> build spec) - not hand-assembled."""
    goals = GoalManager()
    analyzer = AdaptivePlanAnalyzer(
        goals, PlanManager(goals),
        capability_system=_FakeCapabilitySystem({CODE_CHANGE_PLAN_NAME: True}),
        capability_handlers=handlers,
    )
    request = SelfUpgradeRequest(
        request_id="upgrade_request-1", goal="Reduce startup latency",
        requested_capability=CODE_CHANGE_PLAN_NAME,
        reason="Startup is slower than the target budget.",
    )
    plan = build_capability_creation_plan(analyzer.analyze_self_upgrade_request(request))
    impl_spec = build_capability_implementation_spec(plan, capability_handlers=handlers)
    return build_capability_build_spec(impl_spec)


class Base(unittest.TestCase):
    """A real HumanApprovalRequest registered with a real ApprovalManager
    (backed by the real VersionSystem/MemorySystem), plus a real READY
    CapabilityBuildSpec for the same capability."""

    def setUp(self):
        self.sandbox = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.sandbox, ignore_errors=True))
        self.path = os.path.join(self.sandbox, "capability_under_review.py")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("def demo():\n    return 1\n")

        self.memory = MemorySystem(tempfile.mktemp(suffix=".db"))
        self.versions = VersionSystem(self.memory)
        self.manager = ApprovalManager(self.memory)
        self.capability_system = CapabilitySystem(self.memory)

        self.handlers = CapabilityHandlerRegistry()
        self.handlers.register_capability(create_code_change_plan_capability())
        self.build_spec = _real_ready_build_spec(self.handlers)
        self.assertEqual(self.build_spec["status"], BUILD_SPEC_STATUS_READY)
        self.assertEqual(self.build_spec["capability_name"], CODE_CHANGE_PLAN_NAME)

    def registered_request(self, capability_name=CODE_CHANGE_PLAN_NAME):
        verification = {
            "status": STATUS_VERIFIED, "capability_name": capability_name,
            "file_path": self.path,
            "retest_result": {"tests_passed": 3, "tests_failed": 0},
        }
        request = request_capability_human_approval(
            verification, self.versions, allowed_dirs=[self.sandbox])
        self.assertEqual(request["status"], APPROVAL_STATUS_PENDING)
        created = self.manager.create_request(request)
        self.assertEqual(created["status"], APPROVAL_STATUS_PENDING)
        return request

    def approved_request(self):
        request = self.registered_request()
        self.manager.approve(request["request_id"])
        return request

    def prepare(self, request, build_spec=None, purpose=None):
        return prepare_capability_registration(
            request, self.manager,
            self.build_spec if build_spec is None else build_spec, purpose=purpose)

    def assert_nothing_prepared(self, result):
        for field in REGISTRY_FIELDS:
            self.assertIsNone(result[field], field)
        self.assertEqual(result["dependencies"], [])
        self.assertTrue(result["errors"])


# --------------------------------------------------------------------
# Approval must be explicit
# --------------------------------------------------------------------
class ApprovalBlockingTests(Base):
    def test_pending_approval_is_blocked(self):
        request = self.registered_request()
        result = self.prepare(request)
        self.assertEqual(result["status"], REGISTRATION_STATUS_BLOCKED)
        self.assert_nothing_prepared(result)

    def test_rejected_approval_is_blocked(self):
        request = self.registered_request()
        self.manager.reject(request["request_id"])
        result = self.prepare(request)
        self.assertEqual(result["status"], REGISTRATION_STATUS_BLOCKED)
        self.assert_nothing_prepared(result)

    def test_blocked_approval_request_is_blocked(self):
        request = self.registered_request()
        blocked = dict(request, status=APPROVAL_STATUS_BLOCKED, errors=["outside workspace"])
        result = self.prepare(blocked)
        self.assertEqual(result["status"], REGISTRATION_STATUS_BLOCKED)
        self.assert_nothing_prepared(result)

    def test_invalid_approval_follows_existing_approval_model(self):
        # The existing approval gate (Prompt 372) reports an INVALID
        # HumanApprovalRequest as INVALID; preparation mirrors it and
        # never turns it into anything ready.
        request = self.registered_request()
        self.manager.approve(request["request_id"])
        invalid = dict(request, status=APPROVAL_STATUS_INVALID, errors=["bad"])
        result = self.prepare(invalid)
        self.assertEqual(result["status"], REGISTRATION_STATUS_INVALID)
        self.assert_nothing_prepared(result)

    def test_request_claiming_approved_is_not_trusted(self):
        # Approval is never inferred from the request's own status
        # field: ApprovalManager still says PENDING_APPROVAL.
        request = self.registered_request()
        forged = dict(request, status=APPROVAL_STATUS_APPROVED)
        result = self.prepare(forged)
        self.assertNotEqual(result["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)
        self.assert_nothing_prepared(result)

    def test_unregistered_request_is_never_ready(self):
        request = self.registered_request()
        self.manager.approve(request["request_id"])
        never_registered = dict(request, request_id="never-created-in-manager")
        result = self.prepare(never_registered)
        self.assertNotEqual(result["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)
        self.assert_nothing_prepared(result)

    def test_missing_approval_manager_is_never_ready(self):
        request = self.approved_request()
        result = prepare_capability_registration(request, None, self.build_spec)
        self.assertNotEqual(result["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)
        self.assert_nothing_prepared(result)

    def test_malformed_approval_request_is_never_ready(self):
        result = prepare_capability_registration(None, self.manager, self.build_spec)
        self.assertNotEqual(result["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)
        self.assert_nothing_prepared(result)

    def test_approval_is_checked_before_registration_information(self):
        # Not yet approved AND the build spec is incomplete: still
        # BLOCKED (approval comes first), not INVALID.
        request = self.registered_request()
        incomplete = dict(self.build_spec, capability_name=None)
        result = self.prepare(request, build_spec=incomplete)
        self.assertEqual(result["status"], REGISTRATION_STATUS_BLOCKED)

    def test_passing_tests_or_a_valid_build_spec_alone_never_approve(self):
        request = self.registered_request()  # verified + fully valid build spec
        result = self.prepare(request)
        self.assertNotEqual(result["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)


# --------------------------------------------------------------------
# Explicitly approved + valid information
# --------------------------------------------------------------------
class ReadyForRegistrationTests(Base):
    def test_explicitly_approved_valid_build_is_ready(self):
        request = self.approved_request()
        result = self.prepare(request)
        self.assertEqual(result["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)
        self.assertEqual(result["errors"], [])

    def test_result_has_exactly_the_documented_keys(self):
        result = self.prepare(self.approved_request())
        self.assertEqual(set(result.keys()), PREPARATION_KEYS)

    def test_registration_fields_come_from_the_existing_build_spec(self):
        request = self.approved_request()
        result = self.prepare(request)
        self.assertEqual(result["capability_name"], self.build_spec["capability_name"])
        self.assertEqual(result["interface_name"], self.build_spec["interface_name"])
        self.assertEqual(result["target_module"], "execution.code_change_plan_capability")
        self.assertEqual(result["input_schema"], self.build_spec["input_schema"])
        self.assertEqual(result["output_schema"], self.build_spec["output_schema"])
        self.assertEqual(result["dependencies"], self.build_spec["dependencies"])

    def test_carries_approval_request_id_and_source_version(self):
        request = self.approved_request()
        result = self.prepare(request)
        self.assertEqual(result["approval_request_id"], request["request_id"])
        self.assertEqual(result["source_version"]["id"], request["version"]["id"])
        self.assertEqual(result["source_version"]["version_label"],
                         request["version"]["version_label"])

    def test_purpose_is_optional_and_carried_through(self):
        request = self.approved_request()
        self.assertIsNone(self.prepare(request)["purpose"])
        result = self.prepare(request, purpose="Plan code changes safely.")
        self.assertEqual(result["purpose"], "Plan code changes safely.")
        self.assertEqual(result["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)

    def test_purpose_can_come_from_the_build_spec(self):
        request = self.approved_request()
        spec = dict(self.build_spec, purpose="From the spec.")
        self.assertEqual(self.prepare(request, build_spec=spec)["purpose"], "From the spec.")

    def test_result_is_json_serializable(self):
        self.assertIsInstance(json.dumps(self.prepare(self.approved_request())), str)

    def test_result_does_not_alias_the_build_spec(self):
        request = self.approved_request()
        result = self.prepare(request)
        result["input_schema"]["injected"] = True
        result["dependencies"].append("injected.module")
        self.assertNotIn("injected", self.build_spec["input_schema"])
        self.assertNotIn("injected.module", self.build_spec["dependencies"])

    def test_empty_schema_is_a_valid_declaration(self):
        request = self.approved_request()
        spec = dict(self.build_spec, input_schema={}, output_schema={})
        result = self.prepare(request, build_spec=spec)
        self.assertEqual(result["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)


# --------------------------------------------------------------------
# Approved, but registration information missing/invalid
# --------------------------------------------------------------------
class InvalidRegistrationInformationTests(Base):
    def _invalid(self, **overrides):
        request = self.approved_request()
        spec = dict(self.build_spec, **overrides)
        result = self.prepare(request, build_spec=spec)
        self.assertEqual(result["status"], REGISTRATION_STATUS_INVALID, overrides)
        self.assert_nothing_prepared(result)
        return result

    def test_missing_capability_name_is_invalid(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                result = self._invalid(capability_name=value)
                self.assertTrue(any("capability_name" in e for e in result["errors"]))

    def test_missing_interface_information_is_invalid(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                result = self._invalid(interface_name=value)
                self.assertTrue(any("interface" in e for e in result["errors"]))

    def test_missing_target_module_is_invalid(self):
        for value in (None, ""):
            with self.subTest(value=value):
                self._invalid(target_module=value)

    def test_missing_schemas_are_invalid(self):
        self._invalid(input_schema=None)
        self._invalid(output_schema=None)
        self._invalid(input_schema="not a schema")

    def test_malformed_dependencies_are_invalid(self):
        self._invalid(dependencies=None)
        self._invalid(dependencies="execution.module")
        self._invalid(dependencies=["ok.module", ""])

    def test_non_ready_build_spec_is_invalid(self):
        self._invalid(status=BUILD_SPEC_STATUS_BLOCKED)

    def test_malformed_build_spec_is_invalid(self):
        request = self.approved_request()
        for bad in ("nope", 42, ["list"]):
            with self.subTest(build_spec=bad):
                result = prepare_capability_registration(request, self.manager, bad)
                self.assertEqual(result["status"], REGISTRATION_STATUS_INVALID)
                self.assert_nothing_prepared(result)
        result = prepare_capability_registration(request, self.manager, None)
        self.assertEqual(result["status"], REGISTRATION_STATUS_INVALID)

    def test_build_spec_for_a_different_capability_is_invalid(self):
        # Approval of one capability can never prepare another's registration.
        result = self._invalid(capability_name="some_other_capability")
        self.assertTrue(any("does not match" in e for e in result["errors"]))

    def test_non_string_purpose_is_invalid(self):
        request = self.approved_request()
        result = self.prepare(request, purpose=123)
        self.assertEqual(result["status"], REGISTRATION_STATUS_INVALID)

    def test_invalid_result_still_identifies_the_approved_request(self):
        request = self.approved_request()
        result = self.prepare(request, build_spec=dict(self.build_spec, interface_name=None))
        self.assertEqual(result["approval_request_id"], request["request_id"])
        self.assertEqual(result["capability_name"], CODE_CHANGE_PLAN_NAME)


# --------------------------------------------------------------------
# Preparation only - nothing is registered, activated, executed, changed
# --------------------------------------------------------------------
class _SpyManager(ApprovalManager):
    def __init__(self, memory):
        super().__init__(memory)
        self.calls = []

    def create_request(self, *args, **kwargs):
        self.calls.append("create_request")
        return super().create_request(*args, **kwargs)

    def approve(self, *args, **kwargs):
        self.calls.append("approve")
        return super().approve(*args, **kwargs)

    def reject(self, *args, **kwargs):
        self.calls.append("reject")
        return super().reject(*args, **kwargs)


class NoSideEffectsTests(Base):
    def test_capability_is_not_registered_or_activated(self):
        request = self.approved_request()
        registered_before = self.capability_system.all()
        handlers_before = list(self.handlers.list_registered())
        result = self.prepare(request)
        self.assertEqual(result["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)
        self.assertEqual(self.capability_system.all(), registered_before)
        self.assertEqual(list(self.handlers.list_registered()), handlers_before)
        self.assertFalse([c for c in self.capability_system.all()
                          if c["name"] == CODE_CHANGE_PLAN_NAME])

    def test_no_version_snapshot_is_created_or_rolled_back(self):
        request = self.approved_request()
        history_before = self.versions.history()
        current_before = self.versions.current_version()
        self.prepare(request)
        self.assertEqual(self.versions.history(), history_before)
        self.assertEqual(self.versions.current_version(), current_before)

    def test_approval_state_is_left_untouched(self):
        request = self.approved_request()
        before = self.manager.get_status(request["request_id"])
        self.prepare(request)
        after = self.manager.get_status(request["request_id"])
        self.assertEqual(before, after)
        self.assertEqual(after["status"], APPROVAL_STATUS_APPROVED)

    def test_never_creates_approves_or_rejects(self):
        spy = _SpyManager(self.memory)
        request = self.registered_request()
        spy.approve(request["request_id"])
        spy.calls.clear()
        result = prepare_capability_registration(request, spy, self.build_spec)
        self.assertEqual(result["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)
        self.assertEqual(spy.calls, [])

    def test_no_source_file_is_modified(self):
        request = self.approved_request()
        with open(self.path, "rb") as handle:
            content_before = handle.read()
        mtime_before = os.path.getmtime(self.path)
        files_before = sorted(os.listdir(self.sandbox))
        self.prepare(request)
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), content_before)
        self.assertEqual(os.path.getmtime(self.path), mtime_before)
        self.assertEqual(sorted(os.listdir(self.sandbox)), files_before)

    def test_inputs_are_not_mutated(self):
        request = self.approved_request()
        request_before = copy.deepcopy(request)
        spec_before = copy.deepcopy(self.build_spec)
        self.prepare(request, purpose="p")
        self.assertEqual(request, request_before)
        self.assertEqual(self.build_spec, spec_before)

    def test_module_contains_no_register_activate_execute_or_write_calls(self):
        # Structural guarantee: parse the module (docstrings excluded)
        # and confirm it can't register, enable, execute, version,
        # decide approval, or write files.
        with open(preparation_module.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        forbidden_attrs = {
            "register", "register_capability", "replace", "replace_capability",
            "unregister", "set_enabled", "create_version", "rollback_to",
            "create_request", "approve", "reject", "execute", "run",
            "write", "write_text", "system", "popen",
        }
        forbidden_names = {"exec", "eval", "open", "compile", "__import__"}
        forbidden_imports = {"subprocess", "os", "shutil", "importlib", "sqlite3"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    self.assertNotIn(func.attr, forbidden_attrs, ast.dump(func))
                if isinstance(func, ast.Name):
                    self.assertNotIn(func.id, forbidden_names, ast.dump(func))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], forbidden_imports)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], forbidden_imports)


class StatusVocabularyTests(unittest.TestCase):
    def test_statuses_are_exactly_the_three_documented_values(self):
        self.assertEqual(
            set(ALL_REGISTRATION_STATUSES),
            {"BLOCKED", "INVALID", "READY_FOR_REGISTRATION"})
        self.assertEqual(REGISTRATION_STATUS_BLOCKED, "BLOCKED")
        self.assertEqual(REGISTRATION_STATUS_INVALID, "INVALID")
        self.assertEqual(REGISTRATION_STATUS_READY_FOR_REGISTRATION, "READY_FOR_REGISTRATION")


class AgentLoopIntegrationTests(Base):
    def test_agent_loop_thin_passthrough(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        loop = AgentLoop(goals, plans, PlanExecutionController(plans))
        request = self.approved_request()
        result = loop.prepare_capability_registration(
            request, self.manager, self.build_spec, purpose="Plan code changes.")
        self.assertEqual(result["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)
        self.assertEqual(result["purpose"], "Plan code changes.")

    def test_agent_loop_passthrough_still_blocks_when_pending(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        loop = AgentLoop(goals, plans, PlanExecutionController(plans))
        request = self.registered_request()
        result = loop.prepare_capability_registration(request, self.manager, self.build_spec)
        self.assertEqual(result["status"], REGISTRATION_STATUS_BLOCKED)


if __name__ == "__main__":
    unittest.main()
