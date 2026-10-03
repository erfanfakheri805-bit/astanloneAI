"""
Tests for self_upgrade.capability_registration_decision
.resolve_registration_decision (Prompt 376) - the explicit-human-
decision gate after a RegistrationApprovalRequest (Prompt 375) has been
stored with the existing ApprovalManager (Prompt 371):
PENDING_APPROVAL -> ApprovalManager.approve/.reject (explicit human
decision) -> resolve_registration_decision -> READY_FOR_REGISTRATION
(only on an explicit APPROVED decision of the correct, registration-
typed request).

Covers: a pending request staying pending; an explicit approval
producing READY_FOR_REGISTRATION; an explicit rejection producing
REJECTED; a BLOCKED/INVALID Prompt-375 request (never stored) never
becoming READY_FOR_REGISTRATION; approving one request never resolving
a different request_id as ready; that resolving never registers or
activates the capability; that the registration plan and source
version/snapshot references are preserved; and that all of Prompt
371/375's existing tests keep passing untouched.

Run directly:
    python -m unittest tests.test_capability_registration_decision -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import ast
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_upgrade import capability_registration_decision as decision_module
from self_upgrade.capability_human_approval import (
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_BLOCKED,
    APPROVAL_STATUS_INVALID,
)
from self_upgrade.capability_registration_approval import (
    request_capability_registration_approval,
)
from self_upgrade.capability_registration_decision import (
    resolve_registration_decision,
    REGISTRATION_DECISION_STATUS_READY,
    REGISTRATION_DECISION_STATUS_NOT_FOUND,
    REGISTRATION_DECISION_STATUS_WRONG_TYPE,
)
from tests.test_capability_registration_approval import Base
from tests.test_capability_registration_preparation import CODE_CHANGE_PLAN_NAME

DECISION_KEYS = {
    "request_id", "capability_name", "status", "registration_plan",
    "source_version", "decision_timestamp", "errors",
}


class Setup(Base):
    """Adds a stored (but not yet decided) registration approval
    request on top of the real Prompt 374/375 chain `Base` builds."""

    def stored_registration_request(self):
        _, plan = self.ready_plan()
        request = request_capability_registration_approval(plan)
        self.assertEqual(request["status"], APPROVAL_STATUS_PENDING)
        created = self.manager.create_request(request)
        self.assertEqual(created["errors"], [])
        return request, plan


# --------------------------------------------------------------------
# A pending request remains pending
# --------------------------------------------------------------------
class PendingTests(Setup):
    def test_pending_registration_request_remains_pending(self):
        request, _ = self.stored_registration_request()
        result = resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(result["status"], APPROVAL_STATUS_PENDING)
        self.assertEqual(result["errors"], [])
        self.assertIsNone(result["registration_plan"])
        self.assertIsNone(result["source_version"])

    def test_result_has_exactly_the_documented_keys(self):
        request, _ = self.stored_registration_request()
        result = resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(set(result.keys()), DECISION_KEYS)


# --------------------------------------------------------------------
# Explicit approval -> READY_FOR_REGISTRATION
# --------------------------------------------------------------------
class ApprovedTests(Setup):
    def test_explicit_approval_gives_ready_for_registration(self):
        request, plan = self.stored_registration_request()
        approved = self.manager.approve(request["request_id"])
        self.assertEqual(approved["status"], APPROVAL_STATUS_APPROVED)

        result = resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(result["status"], REGISTRATION_DECISION_STATUS_READY)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["capability_name"], CODE_CHANGE_PLAN_NAME)
        self.assertIsNotNone(result["decision_timestamp"])

    def test_approving_the_underlying_ApprovalManager_record_stays_approved(self):
        # READY_FOR_REGISTRATION is a computed result, never spliced
        # into ApprovalManager's own PENDING_APPROVAL->APPROVED/REJECTED
        # state machine.
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(self.manager.get_status(request["request_id"])["status"],
                         APPROVAL_STATUS_APPROVED)
        self.assertEqual(self.stored_state(request["request_id"])["status"],
                         APPROVAL_STATUS_APPROVED)

    def test_repeated_resolution_is_stable(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        first = resolve_registration_decision(request["request_id"], self.manager)
        second = resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(first, second)


# --------------------------------------------------------------------
# Explicit rejection -> REJECTED, never READY_FOR_REGISTRATION
# --------------------------------------------------------------------
class RejectedTests(Setup):
    def test_explicit_rejection_gives_rejected(self):
        request, _ = self.stored_registration_request()
        rejected = self.manager.reject(request["request_id"])
        self.assertEqual(rejected["status"], APPROVAL_STATUS_REJECTED)

        result = resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(result["status"], APPROVAL_STATUS_REJECTED)
        self.assertNotEqual(result["status"], REGISTRATION_DECISION_STATUS_READY)
        self.assertTrue(result["errors"])
        self.assertIsNone(result["registration_plan"])
        self.assertIsNone(result["source_version"])

    def test_approving_after_rejection_never_transitions_it(self):
        request, _ = self.stored_registration_request()
        self.manager.reject(request["request_id"])
        again = self.manager.approve(request["request_id"])  # ApprovalManager: no-op
        self.assertEqual(again["status"], APPROVAL_STATUS_REJECTED)
        result = resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(result["status"], APPROVAL_STATUS_REJECTED)


# --------------------------------------------------------------------
# BLOCKED / INVALID Prompt-375 requests can never become
# READY_FOR_REGISTRATION - they are never even stored.
# --------------------------------------------------------------------
class BlockedAndInvalidTests(Setup):
    def test_blocked_registration_request_cannot_become_ready(self):
        request = request_capability_registration_approval(self.blocked_plan())
        self.assertEqual(request["status"], APPROVAL_STATUS_BLOCKED)
        created = self.manager.create_request(request)  # refused, never stored
        self.assertTrue(created["errors"])
        self.assertIsNone(self.stored_state(request["request_id"]))

        result = resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(result["status"], REGISTRATION_DECISION_STATUS_NOT_FOUND)
        self.assertNotEqual(result["status"], REGISTRATION_DECISION_STATUS_READY)
        self.assertTrue(result["errors"])

    def test_invalid_registration_request_cannot_become_ready(self):
        request = request_capability_registration_approval(self.invalid_plan())
        self.assertEqual(request["status"], APPROVAL_STATUS_INVALID)
        self.manager.create_request(request)  # refused, never stored

        result = resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(result["status"], REGISTRATION_DECISION_STATUS_NOT_FOUND)
        self.assertNotEqual(result["status"], REGISTRATION_DECISION_STATUS_READY)


# --------------------------------------------------------------------
# request_id scoping and cross-type safety
# --------------------------------------------------------------------
class RequestIdScopingTests(Setup):
    def test_approval_for_the_wrong_request_id_is_rejected(self):
        request_a, _ = self.stored_registration_request()
        request_b, _ = self.stored_registration_request()
        self.manager.approve(request_a["request_id"])  # only A is approved

        result_a = resolve_registration_decision(request_a["request_id"], self.manager)
        result_b = resolve_registration_decision(request_b["request_id"], self.manager)
        self.assertEqual(result_a["status"], REGISTRATION_DECISION_STATUS_READY)
        self.assertEqual(result_b["status"], APPROVAL_STATUS_PENDING)
        self.assertNotEqual(result_b["status"], REGISTRATION_DECISION_STATUS_READY)

    def test_unknown_request_id_is_not_found(self):
        result = resolve_registration_decision("does-not-exist", self.manager)
        self.assertEqual(result["status"], REGISTRATION_DECISION_STATUS_NOT_FOUND)
        self.assertTrue(result["errors"])

    def test_the_earlier_capability_upgrade_approval_is_never_treated_as_registration(self):
        upgrade_request, plan = self.ready_plan()  # already APPROVED (see Base)
        self.assertEqual(self.manager.get_status(upgrade_request["request_id"])["status"],
                         APPROVAL_STATUS_APPROVED)
        result = resolve_registration_decision(upgrade_request["request_id"], self.manager)
        self.assertEqual(result["status"], REGISTRATION_DECISION_STATUS_WRONG_TYPE)
        self.assertNotEqual(result["status"], REGISTRATION_DECISION_STATUS_READY)
        self.assertTrue(result["errors"])

    def test_malformed_request_id_is_invalid(self):
        for bad in (None, "", "   ", 42, [], {}):
            with self.subTest(bad=bad):
                result = resolve_registration_decision(bad, self.manager)
                self.assertEqual(result["status"], APPROVAL_STATUS_INVALID)
                self.assertTrue(result["errors"])

    def test_missing_approval_manager_is_invalid(self):
        request, _ = self.stored_registration_request()
        for bad_manager in (None, object()):
            with self.subTest(bad_manager=bad_manager):
                result = resolve_registration_decision(request["request_id"], bad_manager)
                self.assertEqual(result["status"], APPROVAL_STATUS_INVALID)
                self.assertTrue(result["errors"])


# --------------------------------------------------------------------
# References are preserved; no side effects
# --------------------------------------------------------------------
class PreservedReferencesAndNoSideEffectsTests(Setup):
    def test_registration_plan_reference_is_preserved(self):
        request, plan = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        result = resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(result["registration_plan"], plan)
        self.assertEqual(result["registration_plan"]["capability_name"], CODE_CHANGE_PLAN_NAME)

    def test_source_version_snapshot_reference_is_preserved(self):
        request, plan = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        result = resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(result["source_version"], plan["source_version"])
        self.assertEqual(result["source_version"]["id"], request["source_version"]["id"])

    def test_result_does_not_alias_stored_state(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        result = resolve_registration_decision(request["request_id"], self.manager)
        result["registration_plan"]["input_schema"]["injected"] = True
        stored = self.stored_state(request["request_id"])
        self.assertNotIn("injected", stored["registration_plan"]["input_schema"])

    def test_resolving_does_not_register_the_capability(self):
        request, _ = self.stored_registration_request()
        registered_before = self.capability_system.all()
        handlers_before = list(self.handlers.list_registered())
        self.manager.approve(request["request_id"])
        result = resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(result["status"], REGISTRATION_DECISION_STATUS_READY)
        self.assertEqual(self.capability_system.all(), registered_before)
        self.assertEqual(list(self.handlers.list_registered()), handlers_before)
        self.assertFalse([c for c in self.capability_system.all()
                          if c["name"] == CODE_CHANGE_PLAN_NAME])

    def test_resolving_does_not_activate_the_capability(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        resolve_registration_decision(request["request_id"], self.manager)
        self.assertFalse([c for c in self.capability_system.all() if c.get("enabled")])

    def test_no_version_snapshot_is_created_or_rolled_back(self):
        request, _ = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        history_before = self.versions.history()
        current_before = self.versions.current_version()
        resolve_registration_decision(request["request_id"], self.manager)
        self.assertEqual(self.versions.history(), history_before)
        self.assertEqual(self.versions.current_version(), current_before)

    def test_module_contains_no_register_activate_execute_or_decide_calls(self):
        # Structural guarantee, mirroring Prompt 375's own test: this
        # module may only ever *read* an ApprovalManager record - it
        # can never register, enable, execute, version, or decide one.
        with open(decision_module.__file__, encoding="utf-8") as handle:
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


if __name__ == "__main__":
    unittest.main()
