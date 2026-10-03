"""
Tests for self_upgrade.capability_registration_executor
.register_approved_capability (Prompt 377) - the first stage that
actually writes to the live Capability Registry
(capabilities.capability_system.CapabilitySystem): a READY_FOR_
REGISTRATION registration decision (Prompt 376) becomes one new,
disabled `capabilities` row: READY_FOR_REGISTRATION -> Registration
Executor -> REGISTERED.

Covers: an explicitly approved request registering successfully; a
pending or rejected approval, or an unknown/wrong-typed request_id,
never registering anything (BLOCKED); a structurally invalid plan or
missing required registration information never registering anything
(INVALID); identical re-registration being idempotent
(ALREADY_REGISTERED, no duplicate row); a conflicting existing
capability under the same name never being silently overwritten
(FAILED); that a successful registration never enables/activates the
capability and never adds or calls an execution handler; and that
existing CapabilitySystem/CapabilityHandlerRegistry behavior (seeded
planned capabilities, existing handlers) is left untouched.

Run directly:
    python -m unittest tests.test_capability_registration_executor -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import ast
import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_upgrade import capability_registration_executor as executor_module
from self_upgrade.capability_registration_executor import (
    register_approved_capability,
    REGISTRATION_RESULT_INVALID,
    REGISTRATION_RESULT_BLOCKED,
    REGISTRATION_RESULT_REGISTERED,
    REGISTRATION_RESULT_ALREADY_REGISTERED,
    REGISTRATION_RESULT_FAILED,
)
from self_upgrade.capability_registration_approval import (
    request_capability_registration_approval,
)
from tests.test_capability_registration_decision import Setup as DecisionSetup
from tests.test_capability_registration_preparation import CODE_CHANGE_PLAN_NAME

RESULT_KEYS = {
    "request_id", "capability_name", "interface_name", "target_module",
    "approval_request_id", "registration_plan", "source_version", "capability",
    "status", "errors",
}


class Setup(DecisionSetup):
    """Adds a helper to tamper with an already-stored registration
    request's payload directly through the same generic memory state
    API `ApprovalManager` itself uses (`capability_approval:<id>`) -
    used only to build otherwise-unreachable test fixtures (e.g. an
    APPROVED decision whose embedded plan has since become malformed),
    never anything the executor itself does."""

    def tamper_stored_plan(self, request_id, **plan_overrides):
        record = self.memory.get_state(f"capability_approval:{request_id}")
        record = copy.deepcopy(record)
        record["registration_plan"] = dict(record["registration_plan"], **plan_overrides)
        self.memory.set_state(f"capability_approval:{request_id}", record)


# --------------------------------------------------------------------
# Explicit approval -> REGISTERED
# --------------------------------------------------------------------
class RegisteredTests(Setup):
    def test_valid_explicitly_approved_request_registers(self):
        request, plan = self.stored_registration_request()
        self.manager.approve(request["request_id"])

        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_REGISTERED)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["capability_name"], CODE_CHANGE_PLAN_NAME)
        self.assertEqual(result["interface_name"], plan["interface_name"])
        self.assertEqual(result["target_module"], plan["target_module"])
        self.assertEqual(result["approval_request_id"], plan["approval_request_id"])
        self.assertIsNotNone(result["capability"])
        self.assertEqual(result["capability"]["name"], CODE_CHANGE_PLAN_NAME)

    def test_result_has_exactly_the_documented_keys(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(set(result.keys()), RESULT_KEYS)

    def test_registered_capability_is_written_to_the_registry(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        register_approved_capability(request["request_id"], self.manager, self.capability_system)
        rows = [c for c in self.capability_system.all() if c["name"] == CODE_CHANGE_PLAN_NAME]
        self.assertEqual(len(rows), 1)

    def test_source_version_reference_is_preserved(self):
        request, plan = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["source_version"], plan["source_version"])


# --------------------------------------------------------------------
# Non-approved / non-existent / wrong-typed requests -> BLOCKED
# --------------------------------------------------------------------
class BlockedTests(Setup):
    def test_pending_approval_is_blocked(self):
        request, _ = self.stored_registration_request()
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_BLOCKED)
        self.assertTrue(result["errors"])
        self.assertFalse([c for c in self.capability_system.all()
                          if c["name"] == CODE_CHANGE_PLAN_NAME])

    def test_rejected_approval_is_blocked(self):
        request, _ = self.stored_registration_request()
        self.manager.reject(request["request_id"])
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_BLOCKED)
        self.assertTrue(result["errors"])
        self.assertFalse([c for c in self.capability_system.all()
                          if c["name"] == CODE_CHANGE_PLAN_NAME])

    def test_missing_approval_request_is_blocked(self):
        result = register_approved_capability(
            "does-not-exist", self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_BLOCKED)
        self.assertTrue(result["errors"])

    def test_the_earlier_capability_upgrade_approval_is_blocked_not_registered(self):
        upgrade_request, _ = self.ready_plan()  # already APPROVED, but request_type is upgrade
        result = register_approved_capability(
            upgrade_request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_BLOCKED)
        self.assertTrue(result["errors"])


# --------------------------------------------------------------------
# A structurally invalid plan / missing information -> INVALID
# --------------------------------------------------------------------
class InvalidTests(Setup):
    def test_plan_no_longer_ready_is_invalid(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        self.tamper_stored_plan(request["request_id"], status="BLOCKED")
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_INVALID)
        self.assertTrue(result["errors"])
        self.assertFalse([c for c in self.capability_system.all()
                          if c["name"] == CODE_CHANGE_PLAN_NAME])

    def test_missing_capability_name_is_invalid(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        self.tamper_stored_plan(request["request_id"], capability_name=None)
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_INVALID)
        self.assertTrue(any("capability_name" in e for e in result["errors"]))

    def test_missing_interface_name_is_invalid(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        self.tamper_stored_plan(request["request_id"], interface_name="   ")
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_INVALID)
        self.assertTrue(any("interface_name" in e for e in result["errors"]))

    def test_missing_target_module_is_invalid(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        self.tamper_stored_plan(request["request_id"], target_module=None)
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_INVALID)
        self.assertTrue(any("target_module" in e for e in result["errors"]))

    def test_missing_registration_plan_is_invalid(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        record = self.memory.get_state(f"capability_approval:{request['request_id']}")
        record = dict(record, registration_plan=None)
        self.memory.set_state(f"capability_approval:{request['request_id']}", record)
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_INVALID)

    def test_malformed_inputs_to_the_executor_itself_are_invalid(self):
        for bad_id in (None, "", "   ", 42, []):
            with self.subTest(bad_id=bad_id):
                result = register_approved_capability(bad_id, self.manager, self.capability_system)
                self.assertEqual(result["status"], REGISTRATION_RESULT_INVALID)
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        for bad_manager in (None, object()):
            with self.subTest(bad_manager=bad_manager):
                result = register_approved_capability(
                    request["request_id"], bad_manager, self.capability_system)
                self.assertEqual(result["status"], REGISTRATION_RESULT_INVALID)
        for bad_registry in (None, object()):
            with self.subTest(bad_registry=bad_registry):
                result = register_approved_capability(
                    request["request_id"], self.manager, bad_registry)
                self.assertEqual(result["status"], REGISTRATION_RESULT_INVALID)


# --------------------------------------------------------------------
# Idempotency and conflicts
# --------------------------------------------------------------------
class IdempotencyAndConflictTests(Setup):
    def test_duplicate_identical_registration_is_already_registered(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        first = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(first["status"], REGISTRATION_RESULT_REGISTERED)

        second = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(second["status"], REGISTRATION_RESULT_ALREADY_REGISTERED)
        self.assertEqual(second["errors"], [])
        rows = [c for c in self.capability_system.all() if c["name"] == CODE_CHANGE_PLAN_NAME]
        self.assertEqual(len(rows), 1)  # no duplicate row

    def test_two_independently_approved_identical_requests_are_idempotent(self):
        request_a, plan = self.ready_plan()
        req_a = request_capability_registration_approval(plan)
        self.manager.create_request(req_a)
        self.manager.approve(req_a["request_id"])

        req_b = request_capability_registration_approval(plan)
        self.manager.create_request(req_b)
        self.manager.approve(req_b["request_id"])

        first = register_approved_capability(req_a["request_id"], self.manager, self.capability_system)
        second = register_approved_capability(req_b["request_id"], self.manager, self.capability_system)
        self.assertEqual(first["status"], REGISTRATION_RESULT_REGISTERED)
        self.assertEqual(second["status"], REGISTRATION_RESULT_ALREADY_REGISTERED)
        rows = [c for c in self.capability_system.all() if c["name"] == CODE_CHANGE_PLAN_NAME]
        self.assertEqual(len(rows), 1)

    def test_conflicting_existing_registration_fails(self):
        self.capability_system.register(
            CODE_CHANGE_PLAN_NAME, "A pre-existing, differently-described capability.")
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])

        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_FAILED)
        self.assertTrue(result["errors"])
        rows = [c for c in self.capability_system.all() if c["name"] == CODE_CHANGE_PLAN_NAME]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "A pre-existing, differently-described capability.")

    def test_conflict_with_a_seeded_planned_capability_fails(self):
        # A name already claimed by capabilities.capability_system's own
        # PLANNED_CAPABILITIES must never be silently overwritten either.
        self.capability_system.seed_planned_capabilities()
        request, plan = self.stored_registration_request()
        self.tamper_stored_plan(request["request_id"], capability_name="code_generation")
        self.manager.approve(request["request_id"])
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_FAILED)
        rows = [c for c in self.capability_system.all() if c["name"] == "code_generation"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "Generate source code on request.")


# --------------------------------------------------------------------
# Registration never activates or executes anything
# --------------------------------------------------------------------
class NoActivationOrExecutionTests(Setup):
    def test_successful_registration_does_not_activate_the_capability(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_REGISTERED)
        self.assertFalse(result["capability"]["enabled"])
        self.assertFalse([c for c in self.capability_system.all() if c.get("enabled")])

    def test_successful_registration_does_not_add_or_call_an_execution_handler(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        handlers_before = list(self.handlers.list_registered())
        register_approved_capability(request["request_id"], self.manager, self.capability_system)
        self.assertEqual(list(self.handlers.list_registered()), handlers_before)

    def test_registration_status_is_distinct_from_planned_and_active(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertNotIn(result["capability"]["status"], ("planned", "active"))

    def test_no_version_snapshot_is_created_or_rolled_back(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        history_before = self.versions.history()
        current_before = self.versions.current_version()
        register_approved_capability(request["request_id"], self.manager, self.capability_system)
        self.assertEqual(self.versions.history(), history_before)
        self.assertEqual(self.versions.current_version(), current_before)


# --------------------------------------------------------------------
# Existing registry / handler behavior remains compatible
# --------------------------------------------------------------------
class ExistingBehaviorCompatibleTests(Setup):
    def test_seeded_planned_capabilities_are_untouched_by_an_unrelated_registration(self):
        self.capability_system.seed_planned_capabilities()
        planned_before = self.capability_system.all()
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        register_approved_capability(request["request_id"], self.manager, self.capability_system)
        planned_after = [c for c in self.capability_system.all()
                         if c["name"] != CODE_CHANGE_PLAN_NAME]
        self.assertEqual(planned_after, planned_before)

    def test_manual_capability_system_register_still_works_unchanged(self):
        row = self.capability_system.register("manual_probe", "A manually registered capability.")
        self.assertEqual(row["name"], "manual_probe")
        self.assertFalse(row["enabled"])
        self.assertEqual(row["status"], "planned")

    def test_module_never_calls_activation_execution_or_decision_apis(self):
        # Structural guarantee: this module may only ever read a
        # decision and write one CapabilitySystem.register() row - it
        # can never enable, execute, register a handler, or decide an
        # approval itself.
        with open(executor_module.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        forbidden_attrs = {
            "set_enabled", "register_capability", "replace", "replace_capability",
            "unregister", "create_version", "rollback_to", "create_request",
            "approve", "reject", "execute", "run", "set_state", "write", "write_text",
            "system", "popen",
        }
        forbidden_names = {"exec", "eval", "open", "compile", "__import__"}
        forbidden_imports = {"subprocess", "shutil", "importlib", "sqlite3"}
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


if __name__ == "__main__":
    unittest.main()
