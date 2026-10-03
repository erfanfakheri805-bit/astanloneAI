"""
Tests for self_upgrade.capability_registration_plan
.build_capability_registration_plan (Prompt 374) - turns a
READY_FOR_REGISTRATION CapabilityRegistrationPreparation (Prompt 373)
into a structured CapabilityRegistrationPlan describing what a future,
explicitly approved registration would register:
READY_FOR_REGISTRATION -> Registration Plan -> READY_FOR_APPROVED_REGISTRATION.

Covers: BLOCKED/INVALID preparations staying BLOCKED/INVALID; a valid
preparation producing READY_FOR_APPROVED_REGISTRATION; missing
capability name / interface name / target module -> INVALID; the
approval reference being preserved (and, when an ApprovalManager is
supplied, re-confirmed, never inferred); and that building a plan never
registers, activates, executes, versions, approves, or modifies
anything.

Preparations are produced by the real Prompt 373 function on top of the
same real approval chain the Prompt 373 tests use (`Base`).

Run directly:
    python -m unittest tests.test_capability_registration_plan -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import ast
import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent_loop import AgentLoop
from execution.plan_execution_controller import PlanExecutionController
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from self_upgrade import capability_registration_plan as plan_module
from self_upgrade.capability_approval_manager import ApprovalManager
from self_upgrade.capability_human_approval import APPROVAL_STATUS_APPROVED
from self_upgrade.capability_registration_plan import (
    build_capability_registration_plan,
    PLAN_STATUS_BLOCKED,
    PLAN_STATUS_INVALID,
    PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION,
    ALL_PLAN_STATUSES,
)
from self_upgrade.capability_registration_preparation import (
    REGISTRATION_STATUS_BLOCKED,
    REGISTRATION_STATUS_INVALID,
    REGISTRATION_STATUS_READY_FOR_REGISTRATION,
)
from tests.test_capability_registration_preparation import Base as PreparationBase
from tests.test_capability_registration_preparation import CODE_CHANGE_PLAN_NAME

PLAN_KEYS = {
    "capability_name", "interface_name", "target_module", "purpose",
    "input_schema", "output_schema", "dependencies", "source_version",
    "approval_request_id", "registration_preparation", "status", "reason",
    "errors", "created_at",
}
REGISTRY_FIELDS = (
    "interface_name", "target_module", "purpose", "input_schema",
    "output_schema", "source_version",
)


class _RecordingManager(ApprovalManager):
    """Records every public call so a test can prove the plan step only
    ever reads (`get_status`)."""

    def __init__(self, memory):
        super().__init__(memory)
        self.calls = []

    def get_status(self, *args, **kwargs):
        self.calls.append("get_status")
        return super().get_status(*args, **kwargs)

    def get_request(self, *args, **kwargs):
        self.calls.append("get_request")
        return super().get_request(*args, **kwargs)

    def create_request(self, *args, **kwargs):
        self.calls.append("create_request")
        return super().create_request(*args, **kwargs)

    def approve(self, *args, **kwargs):
        self.calls.append("approve")
        return super().approve(*args, **kwargs)

    def reject(self, *args, **kwargs):
        self.calls.append("reject")
        return super().reject(*args, **kwargs)


class Base(PreparationBase):
    """Adds real Prompt 373 preparations in each of its three states."""

    def ready_preparation(self, purpose="Plan code changes safely."):
        request = self.approved_request()
        preparation = self.prepare(request, purpose=purpose)
        self.assertEqual(preparation["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)
        return request, preparation

    def blocked_preparation(self, reject=False):
        request = self.registered_request()  # approval still pending...
        if reject:
            self.manager.reject(request["request_id"])  # ...or explicitly rejected
        preparation = self.prepare(request)
        self.assertEqual(preparation["status"], REGISTRATION_STATUS_BLOCKED)
        return request, preparation

    def invalid_preparation(self):
        request = self.approved_request()
        preparation = self.prepare(
            request, build_spec=dict(self.build_spec, interface_name=None))
        self.assertEqual(preparation["status"], REGISTRATION_STATUS_INVALID)
        return request, preparation

    def assert_nothing_planned(self, plan):
        for field in REGISTRY_FIELDS:
            self.assertIsNone(plan[field], field)
        self.assertEqual(plan["dependencies"], [])
        self.assertTrue(plan["errors"])


# --------------------------------------------------------------------
# Only READY_FOR_REGISTRATION can be planned
# --------------------------------------------------------------------
class NonReadyPreparationTests(Base):
    def test_pending_approval_preparation_gives_blocked_plan(self):
        _, preparation = self.blocked_preparation()
        plan = build_capability_registration_plan(preparation)
        self.assertEqual(plan["status"], PLAN_STATUS_BLOCKED)
        self.assert_nothing_planned(plan)

    def test_rejected_approval_preparation_gives_blocked_plan(self):
        _, preparation = self.blocked_preparation(reject=True)
        plan = build_capability_registration_plan(preparation)
        self.assertEqual(plan["status"], PLAN_STATUS_BLOCKED)
        self.assert_nothing_planned(plan)

    def test_invalid_preparation_gives_invalid_plan(self):
        _, preparation = self.invalid_preparation()
        plan = build_capability_registration_plan(preparation)
        self.assertEqual(plan["status"], PLAN_STATUS_INVALID)
        self.assert_nothing_planned(plan)

    def test_blocked_and_invalid_plans_keep_the_approval_reference(self):
        request, blocked = self.blocked_preparation()
        plan = build_capability_registration_plan(blocked)
        self.assertEqual(plan["approval_request_id"], request["request_id"])
        self.assertEqual(plan["registration_preparation"]["status"], REGISTRATION_STATUS_BLOCKED)

    def test_malformed_or_unrecognized_preparation_is_invalid(self):
        _, preparation = self.ready_preparation()
        for bad in (None, "READY_FOR_REGISTRATION", 42, [preparation],
                    {}, dict(preparation, status="APPROVED"), dict(preparation, status=None)):
            with self.subTest(bad=bad):
                plan = build_capability_registration_plan(bad)
                self.assertEqual(plan["status"], PLAN_STATUS_INVALID)
                self.assert_nothing_planned(plan)


# --------------------------------------------------------------------
# A valid READY_FOR_REGISTRATION preparation
# --------------------------------------------------------------------
class ReadyPlanTests(Base):
    def test_valid_preparation_gives_ready_for_approved_registration(self):
        _, preparation = self.ready_preparation()
        plan = build_capability_registration_plan(preparation)
        self.assertEqual(plan["status"], PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION)
        self.assertEqual(plan["errors"], [])

    def test_plan_has_exactly_the_documented_keys(self):
        _, preparation = self.ready_preparation()
        plan = build_capability_registration_plan(preparation)
        self.assertEqual(set(plan.keys()), PLAN_KEYS)

    def test_registration_fields_are_carried_from_the_preparation(self):
        _, preparation = self.ready_preparation(purpose="Plan code changes safely.")
        plan = build_capability_registration_plan(preparation)
        for field in ("capability_name", "interface_name", "target_module", "purpose",
                      "input_schema", "output_schema", "dependencies", "source_version"):
            self.assertEqual(plan[field], preparation[field], field)
        self.assertEqual(plan["capability_name"], CODE_CHANGE_PLAN_NAME)
        self.assertEqual(plan["target_module"], "execution.code_change_plan_capability")
        self.assertEqual(plan["purpose"], "Plan code changes safely.")

    def test_optional_purpose_and_source_version_may_be_absent(self):
        _, preparation = self.ready_preparation(purpose=None)
        preparation = dict(preparation, source_version=None)
        plan = build_capability_registration_plan(preparation)
        self.assertEqual(plan["status"], PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION)
        self.assertIsNone(plan["purpose"])
        self.assertIsNone(plan["source_version"])

    def test_plan_is_json_serializable(self):
        _, preparation = self.ready_preparation()
        self.assertIsInstance(json.dumps(build_capability_registration_plan(preparation)), str)

    def test_plan_does_not_alias_the_preparation(self):
        _, preparation = self.ready_preparation()
        plan = build_capability_registration_plan(preparation)
        plan["input_schema"]["injected"] = True
        plan["dependencies"].append("injected.module")
        plan["source_version"]["id"] = -1
        self.assertNotIn("injected", preparation["input_schema"])
        self.assertNotIn("injected.module", preparation["dependencies"])
        self.assertNotEqual(preparation["source_version"]["id"], -1)

    def test_plan_carries_no_permission_flags(self):
        # Creating a plan is never permission to register/activate.
        _, preparation = self.ready_preparation()
        plan = build_capability_registration_plan(preparation)
        for key in plan:
            self.assertNotIn("allowed", key)
            self.assertNotIn("enabled", key)
            self.assertNotIn("activate", key)


# --------------------------------------------------------------------
# Missing required registration information
# --------------------------------------------------------------------
class MissingInformationTests(Base):
    def _invalid(self, **overrides):
        _, preparation = self.ready_preparation()
        plan = build_capability_registration_plan(dict(preparation, **overrides))
        self.assertEqual(plan["status"], PLAN_STATUS_INVALID, overrides)
        self.assert_nothing_planned(plan)
        return plan

    def test_missing_capability_name_is_invalid(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                plan = self._invalid(capability_name=value)
                self.assertTrue(any("capability_name" in e for e in plan["errors"]))

    def test_missing_interface_name_is_invalid(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                plan = self._invalid(interface_name=value)
                self.assertTrue(any("interface" in e for e in plan["errors"]))

    def test_missing_target_module_is_invalid(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                plan = self._invalid(target_module=value)
                self.assertTrue(any("target_module" in e for e in plan["errors"]))

    def test_missing_schemas_or_dependencies_are_invalid(self):
        self._invalid(input_schema=None)
        self._invalid(output_schema="not a schema")
        self._invalid(dependencies=None)
        self._invalid(dependencies=["ok.module", ""])

    def test_missing_approval_reference_is_invalid(self):
        for value in (None, "", "  "):
            with self.subTest(value=value):
                plan = self._invalid(approval_request_id=value)
                self.assertTrue(any("approval" in e.lower() for e in plan["errors"]))

    def test_malformed_optional_fields_are_invalid(self):
        self._invalid(purpose=123)
        self._invalid(source_version="v1")


# --------------------------------------------------------------------
# The explicit human approval reference is preserved (and re-confirmable)
# --------------------------------------------------------------------
class ApprovalReferenceTests(Base):
    def test_approval_reference_is_preserved(self):
        request, preparation = self.ready_preparation()
        plan = build_capability_registration_plan(preparation)
        self.assertEqual(plan["approval_request_id"], request["request_id"])
        self.assertEqual(plan["source_version"]["id"], request["version"]["id"])
        self.assertEqual(plan["source_version"]["version_label"],
                         request["version"]["version_label"])

    def test_plan_records_which_preparation_it_came_from(self):
        request, preparation = self.ready_preparation()
        plan = build_capability_registration_plan(preparation)
        self.assertEqual(plan["registration_preparation"], {
            "status": REGISTRATION_STATUS_READY_FOR_REGISTRATION,
            "approval_request_id": request["request_id"],
            "created_at": preparation["created_at"],
        })

    def test_recheck_with_manager_confirms_explicit_approval(self):
        request, preparation = self.ready_preparation()
        plan = build_capability_registration_plan(preparation, self.manager)
        self.assertEqual(plan["status"], PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION)
        self.assertEqual(plan["approval_request_id"], request["request_id"])
        self.assertEqual(self.manager.get_status(request["request_id"])["status"],
                         APPROVAL_STATUS_APPROVED)

    def test_forged_ready_preparation_for_pending_request_stays_blocked(self):
        # A dict can claim READY_FOR_REGISTRATION; ApprovalManager is
        # the authority, and this request was never approved.
        _, real = self.ready_preparation()
        pending = self.registered_request()
        forged = dict(real, approval_request_id=pending["request_id"])
        plan = build_capability_registration_plan(forged, self.manager)
        self.assertEqual(plan["status"], PLAN_STATUS_BLOCKED)
        self.assert_nothing_planned(plan)

    def test_forged_ready_preparation_for_rejected_request_stays_blocked(self):
        _, real = self.ready_preparation()
        rejected = self.registered_request()
        self.manager.reject(rejected["request_id"])
        forged = dict(real, approval_request_id=rejected["request_id"])
        plan = build_capability_registration_plan(forged, self.manager)
        self.assertEqual(plan["status"], PLAN_STATUS_BLOCKED)

    def test_recheck_unknown_approval_request_is_invalid(self):
        _, preparation = self.ready_preparation()
        forged = dict(preparation, approval_request_id="never-created-in-manager")
        plan = build_capability_registration_plan(forged, self.manager)
        self.assertEqual(plan["status"], PLAN_STATUS_INVALID)
        self.assert_nothing_planned(plan)

    def test_recheck_capability_mismatch_is_invalid(self):
        _, preparation = self.ready_preparation()
        plan = build_capability_registration_plan(
            dict(preparation, capability_name="some_other_capability"), self.manager)
        self.assertEqual(plan["status"], PLAN_STATUS_INVALID)
        self.assertTrue(any("ApprovalManager" in e for e in plan["errors"]))

    def test_recheck_version_mismatch_is_invalid(self):
        _, preparation = self.ready_preparation()
        tampered = dict(preparation, source_version={"id": 99999, "version_label": "x"})
        plan = build_capability_registration_plan(tampered, self.manager)
        self.assertEqual(plan["status"], PLAN_STATUS_INVALID)
        self.assertTrue(any("source_version" in e for e in plan["errors"]))

    def test_blocked_preparation_stays_blocked_even_with_manager(self):
        _, preparation = self.blocked_preparation()
        plan = build_capability_registration_plan(preparation, self.manager)
        self.assertEqual(plan["status"], PLAN_STATUS_BLOCKED)


# --------------------------------------------------------------------
# Planning only - nothing is registered, activated, executed, changed
# --------------------------------------------------------------------
class NoSideEffectsTests(Base):
    def test_plan_creation_does_not_register_the_capability(self):
        _, preparation = self.ready_preparation()
        registered_before = self.capability_system.all()
        handlers_before = list(self.handlers.list_registered())
        plan = build_capability_registration_plan(preparation, self.manager)
        self.assertEqual(plan["status"], PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION)
        self.assertEqual(self.capability_system.all(), registered_before)
        self.assertEqual(list(self.handlers.list_registered()), handlers_before)
        self.assertFalse([c for c in self.capability_system.all()
                          if c["name"] == CODE_CHANGE_PLAN_NAME])

    def test_plan_creation_does_not_activate_the_capability(self):
        _, preparation = self.ready_preparation()
        build_capability_registration_plan(preparation, self.manager)
        self.assertFalse([c for c in self.capability_system.all() if c.get("enabled")])
        self.assertFalse([c for c in self.capability_system.all()
                          if c.get("status") not in (None, "planned")])

    def test_no_version_snapshot_is_created_or_rolled_back(self):
        _, preparation = self.ready_preparation()
        history_before = self.versions.history()
        current_before = self.versions.current_version()
        build_capability_registration_plan(preparation, self.manager)
        self.assertEqual(self.versions.history(), history_before)
        self.assertEqual(self.versions.current_version(), current_before)

    def test_approval_manager_is_only_ever_read(self):
        recording = _RecordingManager(self.memory)
        request = self.registered_request()
        recording.approve(request["request_id"])
        preparation = self.prepare(request)
        self.assertEqual(preparation["status"], REGISTRATION_STATUS_READY_FOR_REGISTRATION)
        before = recording.get_status(request["request_id"])
        recording.calls.clear()
        plan = build_capability_registration_plan(preparation, recording)
        self.assertEqual(plan["status"], PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION)
        # get_status itself delegates to get_request internally; both
        # are reads. Nothing that creates or decides may ever be called.
        self.assertIn("get_status", recording.calls)
        self.assertLessEqual(set(recording.calls), {"get_status", "get_request"})
        self.assertEqual(recording.get_status(request["request_id"]), before)

    def test_no_source_file_is_modified(self):
        _, preparation = self.ready_preparation()
        with open(self.path, "rb") as handle:
            content_before = handle.read()
        mtime_before = os.path.getmtime(self.path)
        files_before = sorted(os.listdir(self.sandbox))
        build_capability_registration_plan(preparation, self.manager)
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), content_before)
        self.assertEqual(os.path.getmtime(self.path), mtime_before)
        self.assertEqual(sorted(os.listdir(self.sandbox)), files_before)

    def test_input_preparation_is_not_mutated(self):
        _, preparation = self.ready_preparation()
        before = copy.deepcopy(preparation)
        build_capability_registration_plan(preparation, self.manager)
        self.assertEqual(preparation, before)

    def test_module_contains_no_register_activate_execute_or_write_calls(self):
        # Structural guarantee: parse the module (docstrings excluded)
        # and confirm it can't register, enable, execute, version,
        # decide approval, or write files - `get_status` is the one
        # ApprovalManager method it may call.
        with open(plan_module.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        forbidden_attrs = {
            "register", "register_capability", "replace", "replace_capability",
            "unregister", "set_enabled", "create_version", "rollback_to",
            "create_request", "approve", "reject", "execute", "run",
            "set_state", "write", "write_text", "system", "popen",
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
            set(ALL_PLAN_STATUSES),
            {"BLOCKED", "INVALID", "READY_FOR_APPROVED_REGISTRATION"})
        self.assertEqual(PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION,
                         "READY_FOR_APPROVED_REGISTRATION")


class AgentLoopIntegrationTests(Base):
    def _loop(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        return AgentLoop(goals, plans, PlanExecutionController(plans))

    def test_agent_loop_thin_passthrough(self):
        _, preparation = self.ready_preparation()
        plan = self._loop().build_capability_registration_plan(preparation, self.manager)
        self.assertEqual(plan["status"], PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION)

    def test_agent_loop_passthrough_keeps_blocked_blocked(self):
        _, preparation = self.blocked_preparation()
        plan = self._loop().build_capability_registration_plan(preparation)
        self.assertEqual(plan["status"], PLAN_STATUS_BLOCKED)


if __name__ == "__main__":
    unittest.main()
