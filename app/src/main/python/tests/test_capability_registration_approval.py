"""
Tests for self_upgrade.capability_registration_approval
.request_capability_registration_approval (Prompt 375) - builds a
structured, PENDING_APPROVAL registration approval request from a
READY_FOR_APPROVED_REGISTRATION CapabilityRegistrationPlan
(Prompt 374), reusing the existing HumanApprovalRequest shape,
ApprovalManager and approval states:
CapabilityRegistrationPlan -> RegistrationApprovalRequest.

Covers: a ready plan producing a pending request; BLOCKED/INVALID (and
malformed/tampered) plans producing no valid request (and being refused
by the existing ApprovalManager); the request starting pending, never
being approved by creation, and following the existing approve/reject
lifecycle only through explicit ApprovalManager calls; correct
capability information; the registration plan and version/snapshot
references being preserved; and that creating the request never
registers, activates, executes, versions, or modifies anything.

Plans are produced by the real Prompt 374 function on top of the same
real approval chain the Prompt 373/374 tests use.

Run directly:
    python -m unittest tests.test_capability_registration_approval -v
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
from self_upgrade import capability_registration_approval as approval_module
from self_upgrade.capability_human_approval import (
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_BLOCKED,
    APPROVAL_STATUS_INVALID,
)
from self_upgrade.capability_registration_approval import (
    request_capability_registration_approval,
    REQUEST_TYPE_CAPABILITY_REGISTRATION,
)
from self_upgrade.capability_registration_plan import (
    build_capability_registration_plan,
    PLAN_STATUS_BLOCKED,
    PLAN_STATUS_INVALID,
    PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION,
)
from tests.test_capability_registration_plan import Base as PlanBase
from tests.test_capability_registration_preparation import CODE_CHANGE_PLAN_NAME

REQUEST_KEYS = {
    "request_id", "request_type", "capability_name", "interface_name",
    "target_module", "purpose", "registration_plan", "source_version",
    "version", "summary", "status", "errors", "created_at",
}
REQUEST_FIELDS = (
    "interface_name", "target_module", "purpose", "registration_plan",
    "source_version", "version", "summary",
)


class Base(PlanBase):
    """Adds real Prompt 374 plans in each of its three states."""

    def ready_plan(self, purpose="Plan code changes safely."):
        request, preparation = self.ready_preparation(purpose=purpose)
        plan = build_capability_registration_plan(preparation, self.manager)
        self.assertEqual(plan["status"], PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION)
        return request, plan

    def blocked_plan(self):
        _, preparation = self.blocked_preparation()
        plan = build_capability_registration_plan(preparation)
        self.assertEqual(plan["status"], PLAN_STATUS_BLOCKED)
        return plan

    def invalid_plan(self):
        _, preparation = self.invalid_preparation()
        plan = build_capability_registration_plan(preparation)
        self.assertEqual(plan["status"], PLAN_STATUS_INVALID)
        return plan

    def stored_state(self, request_id):
        return self.memory.get_state(f"capability_approval:{request_id}")

    def assert_no_valid_request(self, request, expected_status):
        self.assertEqual(request["status"], expected_status)
        self.assertNotEqual(request["status"], APPROVAL_STATUS_PENDING)
        for field in REQUEST_FIELDS:
            self.assertIsNone(request[field], field)
        self.assertTrue(request["errors"])
        # The existing ApprovalManager refuses it: nothing is stored.
        created = self.manager.create_request(request)
        self.assertTrue(created["errors"])
        self.assertIsNone(self.stored_state(request["request_id"]))
        self.assertTrue(self.manager.get_status(request["request_id"])["errors"])


# --------------------------------------------------------------------
# READY_FOR_APPROVED_REGISTRATION -> pending request
# --------------------------------------------------------------------
class ReadyPlanRequestTests(Base):
    def test_ready_plan_creates_a_pending_registration_approval_request(self):
        _, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        self.assertEqual(request["status"], APPROVAL_STATUS_PENDING)
        self.assertEqual(request["request_type"], "capability_registration")
        self.assertEqual(request["errors"], [])

    def test_request_has_exactly_the_documented_keys(self):
        _, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        self.assertEqual(set(request.keys()), REQUEST_KEYS)

    def test_request_type_constant(self):
        self.assertEqual(REQUEST_TYPE_CAPABILITY_REGISTRATION, "capability_registration")

    def test_request_contains_the_correct_capability_information(self):
        _, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        self.assertEqual(request["capability_name"], CODE_CHANGE_PLAN_NAME)
        self.assertEqual(request["capability_name"], plan["capability_name"])
        self.assertEqual(request["interface_name"], plan["interface_name"])
        self.assertEqual(request["target_module"], "execution.code_change_plan_capability")
        self.assertEqual(request["purpose"], "Plan code changes safely.")
        self.assertTrue(request["request_id"])
        self.assertIn(CODE_CHANGE_PLAN_NAME, request["summary"])

    def test_each_request_gets_its_own_id(self):
        _, plan = self.ready_plan()
        first = request_capability_registration_approval(plan)
        second = request_capability_registration_approval(plan)
        self.assertNotEqual(first["request_id"], second["request_id"])

    def test_request_is_json_serializable(self):
        _, plan = self.ready_plan()
        self.assertIsInstance(json.dumps(request_capability_registration_approval(plan)), str)

    def test_purpose_and_source_version_are_optional(self):
        _, plan = self.ready_plan(purpose=None)
        plan = dict(plan, source_version=None)
        request = request_capability_registration_approval(plan)
        self.assertEqual(request["status"], APPROVAL_STATUS_PENDING)
        self.assertIsNone(request["purpose"])
        self.assertIsNone(request["source_version"])
        self.assertIsNone(request["version"])


# --------------------------------------------------------------------
# BLOCKED / INVALID plans create no valid request
# --------------------------------------------------------------------
class NonReadyPlanTests(Base):
    def test_blocked_plan_gives_no_valid_request(self):
        request = request_capability_registration_approval(self.blocked_plan())
        self.assert_no_valid_request(request, APPROVAL_STATUS_BLOCKED)

    def test_invalid_plan_gives_no_valid_request(self):
        request = request_capability_registration_approval(self.invalid_plan())
        self.assert_no_valid_request(request, APPROVAL_STATUS_INVALID)

    def test_malformed_or_unrecognized_plans_give_no_valid_request(self):
        _, plan = self.ready_plan()
        for bad in (None, "READY_FOR_APPROVED_REGISTRATION", 42, [plan], {},
                    dict(plan, status="READY_FOR_REGISTRATION"), dict(plan, status=None)):
            with self.subTest(bad=bad):
                request = request_capability_registration_approval(bad)
                self.assert_no_valid_request(request, APPROVAL_STATUS_INVALID)

    def test_ready_plan_missing_required_information_is_invalid(self):
        _, plan = self.ready_plan()
        cases = dict(
            capability_name=None, interface_name="", target_module="   ",
            input_schema=None, dependencies=None, approval_request_id=None,
            registration_preparation=None, purpose=123, source_version="v1",
        )
        for field, value in cases.items():
            with self.subTest(field=field):
                request = request_capability_registration_approval(dict(plan, **{field: value}))
                self.assert_no_valid_request(request, APPROVAL_STATUS_INVALID)

    def test_plan_not_derived_from_a_ready_preparation_is_invalid(self):
        _, plan = self.ready_plan()
        ref = dict(plan["registration_preparation"], status="BLOCKED")
        request = request_capability_registration_approval(dict(plan, registration_preparation=ref))
        self.assert_no_valid_request(request, APPROVAL_STATUS_INVALID)

    def test_non_ready_result_keeps_the_reason(self):
        request = request_capability_registration_approval(self.blocked_plan())
        self.assertTrue(any("BLOCKED" in e for e in request["errors"]))
        self.assertEqual(request["request_type"], REQUEST_TYPE_CAPABILITY_REGISTRATION)


# --------------------------------------------------------------------
# Pending start; existing lifecycle; approval never inferred
# --------------------------------------------------------------------
class PendingLifecycleTests(Base):
    def test_request_starts_pending_and_is_admitted_by_the_existing_manager(self):
        _, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        created = self.manager.create_request(request)
        self.assertEqual(created["errors"], [])
        self.assertEqual(created["status"], APPROVAL_STATUS_PENDING)
        self.assertEqual(created["capability_name"], CODE_CHANGE_PLAN_NAME)
        self.assertEqual(self.manager.get_status(request["request_id"])["status"],
                         APPROVAL_STATUS_PENDING)

    def test_creating_the_request_never_approves_anything(self):
        _, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        # Building it stores nothing and decides nothing...
        self.assertIsNone(self.stored_state(request["request_id"]))
        self.assertTrue(self.manager.get_status(request["request_id"])["errors"])
        # ...and even once stored it stays pending until explicitly approved.
        self.manager.create_request(request)
        self.assertEqual(self.manager.get_status(request["request_id"])["status"],
                         APPROVAL_STATUS_PENDING)
        self.assertIsNone(self.stored_state(request["request_id"])["decision_timestamp"])

    def test_only_an_explicit_approve_call_approves_it(self):
        _, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        self.manager.create_request(request)
        result = self.manager.approve(request["request_id"])
        self.assertEqual(result["status"], APPROVAL_STATUS_APPROVED)
        self.assertEqual(self.manager.get_status(request["request_id"])["status"],
                         APPROVAL_STATUS_APPROVED)

    def test_explicit_reject_follows_the_existing_lifecycle(self):
        _, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        self.manager.create_request(request)
        self.assertEqual(self.manager.reject(request["request_id"])["status"],
                         APPROVAL_STATUS_REJECTED)
        again = self.manager.approve(request["request_id"])  # never transitions again
        self.assertEqual(again["status"], APPROVAL_STATUS_REJECTED)
        self.assertTrue(again["errors"])

    def test_registration_request_is_distinguishable_from_the_upgrade_approval(self):
        upgrade_request, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        self.assertEqual(request["request_type"], REQUEST_TYPE_CAPABILITY_REGISTRATION)
        self.assertNotEqual(upgrade_request.get("request_type"),
                            REQUEST_TYPE_CAPABILITY_REGISTRATION)
        self.assertNotEqual(request["request_id"], upgrade_request["request_id"])

    def test_earlier_capability_approval_is_not_reused_as_registration_approval(self):
        # The earlier upgrade approval is already APPROVED - yet the new
        # registration request still starts PENDING and is a separate record.
        upgrade_request, plan = self.ready_plan()
        self.assertEqual(self.manager.get_status(upgrade_request["request_id"])["status"],
                         APPROVAL_STATUS_APPROVED)
        request = request_capability_registration_approval(plan)
        self.assertEqual(request["status"], APPROVAL_STATUS_PENDING)
        self.manager.create_request(request)
        self.assertEqual(self.manager.get_status(request["request_id"])["status"],
                         APPROVAL_STATUS_PENDING)


# --------------------------------------------------------------------
# References are preserved
# --------------------------------------------------------------------
class PreservedReferencesTests(Base):
    def test_registration_plan_reference_is_preserved(self):
        upgrade_request, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        self.assertEqual(request["registration_plan"], plan)
        embedded = request["registration_plan"]
        self.assertEqual(embedded["status"], PLAN_STATUS_READY_FOR_APPROVED_REGISTRATION)
        self.assertEqual(embedded["approval_request_id"], upgrade_request["request_id"])
        self.assertEqual(embedded["registration_preparation"], plan["registration_preparation"])
        self.assertEqual(embedded["input_schema"], plan["input_schema"])
        self.assertEqual(embedded["output_schema"], plan["output_schema"])
        self.assertEqual(embedded["dependencies"], plan["dependencies"])

    def test_source_version_reference_is_preserved_when_available(self):
        upgrade_request, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        self.assertEqual(request["source_version"], plan["source_version"])
        self.assertEqual(request["source_version"]["id"], upgrade_request["version"]["id"])
        self.assertEqual(request["version"], request["source_version"])
        self.assertEqual(request["registration_plan"]["source_version"], plan["source_version"])

    def test_references_survive_storage_and_the_explicit_decision(self):
        upgrade_request, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        created = self.manager.create_request(request)
        self.assertEqual(created["version"]["id"], upgrade_request["version"]["id"])
        approved = self.manager.approve(request["request_id"])
        self.assertEqual(approved["version"]["id"], upgrade_request["version"]["id"])
        stored = self.stored_state(request["request_id"])
        self.assertEqual(stored["request_type"], REQUEST_TYPE_CAPABILITY_REGISTRATION)
        self.assertEqual(stored["registration_plan"], plan)
        self.assertEqual(stored["source_version"], plan["source_version"])
        self.assertEqual(stored["interface_name"], plan["interface_name"])
        self.assertEqual(stored["target_module"], plan["target_module"])
        self.assertEqual(stored["status"], APPROVAL_STATUS_APPROVED)

    def test_request_does_not_alias_the_plan(self):
        _, plan = self.ready_plan()
        before = copy.deepcopy(plan)
        request = request_capability_registration_approval(plan)
        self.assertEqual(plan, before)  # input never mutated
        request["registration_plan"]["input_schema"]["injected"] = True
        request["registration_plan"]["dependencies"].append("injected.module")
        request["source_version"]["id"] = -1
        self.assertNotIn("injected", plan["input_schema"])
        self.assertNotIn("injected.module", plan["dependencies"])
        self.assertNotEqual(plan["source_version"]["id"], -1)


# --------------------------------------------------------------------
# Request only - nothing is registered, activated, executed, changed
# --------------------------------------------------------------------
class NoSideEffectsTests(Base):
    def test_creating_the_request_does_not_register_the_capability(self):
        _, plan = self.ready_plan()
        registered_before = self.capability_system.all()
        handlers_before = list(self.handlers.list_registered())
        request = request_capability_registration_approval(plan)
        self.manager.create_request(request)  # even once stored for approval
        self.assertEqual(request["status"], APPROVAL_STATUS_PENDING)
        self.assertEqual(self.capability_system.all(), registered_before)
        self.assertEqual(list(self.handlers.list_registered()), handlers_before)
        self.assertFalse([c for c in self.capability_system.all()
                          if c["name"] == CODE_CHANGE_PLAN_NAME])

    def test_creating_the_request_does_not_activate_the_capability(self):
        _, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        self.manager.create_request(request)
        self.assertFalse([c for c in self.capability_system.all() if c.get("enabled")])
        self.assertFalse([c for c in self.capability_system.all()
                          if c.get("status") not in (None, "planned")])

    def test_no_version_snapshot_is_created_or_rolled_back(self):
        _, plan = self.ready_plan()
        history_before = self.versions.history()
        current_before = self.versions.current_version()
        request_capability_registration_approval(plan)
        self.assertEqual(self.versions.history(), history_before)
        self.assertEqual(self.versions.current_version(), current_before)

    def test_earlier_approval_record_is_left_untouched(self):
        upgrade_request, plan = self.ready_plan()
        before = self.stored_state(upgrade_request["request_id"])
        request_capability_registration_approval(plan)
        self.assertEqual(self.stored_state(upgrade_request["request_id"]), before)
        self.assertEqual(before["status"], APPROVAL_STATUS_APPROVED)

    def test_no_source_file_is_modified(self):
        _, plan = self.ready_plan()
        with open(self.path, "rb") as handle:
            content_before = handle.read()
        mtime_before = os.path.getmtime(self.path)
        files_before = sorted(os.listdir(self.sandbox))
        request_capability_registration_approval(plan)
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), content_before)
        self.assertEqual(os.path.getmtime(self.path), mtime_before)
        self.assertEqual(sorted(os.listdir(self.sandbox)), files_before)

    def test_module_contains_no_register_activate_execute_store_or_write_calls(self):
        # Structural guarantee: parse the module (docstrings excluded)
        # and confirm it can't register, enable, execute, version,
        # store/decide approvals, or write files - and never even
        # imports ApprovalManager.
        with open(approval_module.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        forbidden_attrs = {
            "register", "register_capability", "replace", "replace_capability",
            "unregister", "set_enabled", "create_version", "rollback_to",
            "create_request", "approve", "reject", "get_status", "execute", "run",
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
                self.assertNotEqual(node.module, "self_upgrade.capability_approval_manager")


class AgentLoopIntegrationTests(Base):
    def _loop(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        return AgentLoop(goals, plans, PlanExecutionController(plans))

    def test_agent_loop_thin_passthrough(self):
        _, plan = self.ready_plan()
        request = self._loop().request_capability_registration_approval(plan)
        self.assertEqual(request["status"], APPROVAL_STATUS_PENDING)
        self.assertEqual(request["request_type"], REQUEST_TYPE_CAPABILITY_REGISTRATION)

    def test_agent_loop_passthrough_creates_nothing_for_a_blocked_plan(self):
        request = self._loop().request_capability_registration_approval(self.blocked_plan())
        self.assertEqual(request["status"], APPROVAL_STATUS_BLOCKED)


if __name__ == "__main__":
    unittest.main()
