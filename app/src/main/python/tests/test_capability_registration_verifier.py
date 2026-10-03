"""
Tests for self_upgrade.capability_registration_verifier
.verify_registered_capability (Prompt 378) - the stage right after
registration (self_upgrade.capability_registration_executor, Prompt
377): checks - never repairs - that a REGISTERED capability still
matches its approved registration information:
REGISTERED -> Registration Verification -> VERIFIED / FAILED.

Covers: a valid, untouched registration verifying cleanly; a missing
registry entry (NOT_REGISTERED); a registration_result with no usable
registration_plan / missing capability_name (INVALID); matching vs.
mismatched interface_name, target_module, input/output schema, and
source_version/snapshot reference (VERIFIED / FAILED); and that
verification never activates, executes, or modifies the registered
capability or the registry.

Run directly:
    python -m unittest tests.test_capability_registration_verifier -v
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

from self_upgrade import capability_registration_verifier as verifier_module
from self_upgrade.capability_registration_executor import (
    register_approved_capability,
    REGISTRATION_RESULT_REGISTERED,
)
from self_upgrade.capability_registration_verifier import (
    verify_registered_capability,
    VERIFICATION_STATUS_VERIFIED,
    VERIFICATION_STATUS_FAILED,
    VERIFICATION_STATUS_INVALID,
    VERIFICATION_STATUS_NOT_REGISTERED,
)
from tests.test_capability_registration_executor import Setup as ExecutorSetup
from tests.test_capability_registration_preparation import CODE_CHANGE_PLAN_NAME

RESULT_KEYS = {
    "request_id", "capability_name", "interface_name", "target_module",
    "approval_request_id", "source_version", "status", "mismatches",
    "errors", "verified_at",
}


class Setup(ExecutorSetup):
    """Adds a real REGISTERED `RegistrationResult` (Prompt 377) on top
    of the real Prompt 373-377 chain `ExecutorSetup` builds."""

    def registered_result(self):
        request, plan = self.stored_registration_request()
        self.manager.approve(request["request_id"])
        result = register_approved_capability(
            request["request_id"], self.manager, self.capability_system)
        self.assertEqual(result["status"], REGISTRATION_RESULT_REGISTERED)
        return result


# --------------------------------------------------------------------
# A valid, untouched registration verifies cleanly
# --------------------------------------------------------------------
class VerifiedTests(Setup):
    def test_valid_registered_capability_is_verified(self):
        result = self.registered_result()
        verification = verify_registered_capability(
            result, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_VERIFIED)
        self.assertEqual(verification["errors"], [])
        self.assertEqual(verification["mismatches"], [])
        self.assertEqual(verification["capability_name"], CODE_CHANGE_PLAN_NAME)
        self.assertEqual(verification["interface_name"], result["interface_name"])
        self.assertEqual(verification["target_module"], result["target_module"])
        self.assertEqual(verification["approval_request_id"], result["approval_request_id"])
        self.assertEqual(verification["source_version"], result["source_version"])

    def test_result_has_exactly_the_documented_keys(self):
        result = self.registered_result()
        verification = verify_registered_capability(
            result, self.manager, self.capability_system)
        self.assertEqual(set(verification.keys()), RESULT_KEYS)

    def test_matching_interface_name_is_verified(self):
        result = self.registered_result()
        # Sanity: verifying twice in a row (no tampering in between)
        # stays VERIFIED - interface_name genuinely matches.
        first = verify_registered_capability(result, self.manager, self.capability_system)
        second = verify_registered_capability(result, self.manager, self.capability_system)
        self.assertEqual(first["status"], VERIFICATION_STATUS_VERIFIED)
        self.assertEqual(second["status"], VERIFICATION_STATUS_VERIFIED)

    def test_already_registered_result_also_verifies(self):
        result = self.registered_result()
        replay = register_approved_capability(
            result["request_id"], self.manager, self.capability_system)
        verification = verify_registered_capability(
            replay, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_VERIFIED)


# --------------------------------------------------------------------
# Missing registry entry -> NOT_REGISTERED
# --------------------------------------------------------------------
class NotRegisteredTests(Setup):
    def test_missing_registry_entry_is_not_registered(self):
        result = self.registered_result()
        # Simulate the row having disappeared from the registry, without
        # this test module itself standing in for a repair/removal API.
        self.memory._run("DELETE FROM capabilities WHERE name = ?", (CODE_CHANGE_PLAN_NAME,))
        verification = verify_registered_capability(
            result, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_NOT_REGISTERED)
        self.assertTrue(verification["errors"])


# --------------------------------------------------------------------
# Missing / invalid expected registration information -> INVALID
# --------------------------------------------------------------------
class InvalidTests(Setup):
    def test_missing_expected_capability_name_is_invalid(self):
        result = self.registered_result()
        tampered = copy.deepcopy(result)
        tampered["registration_plan"]["capability_name"] = None
        verification = verify_registered_capability(
            tampered, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_INVALID)
        self.assertTrue(any("capability_name" in e for e in verification["errors"]))

    def test_missing_registration_plan_is_invalid(self):
        result = self.registered_result()
        tampered = dict(result, registration_plan=None)
        verification = verify_registered_capability(
            tampered, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_INVALID)

    def test_non_registered_status_is_invalid(self):
        result = self.registered_result()
        tampered = dict(result, status="REGISTERED_BUT_FORGED")
        verification = verify_registered_capability(
            tampered, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_INVALID)

    def test_malformed_registration_result_is_invalid(self):
        for bad in (None, "not-a-dict", 42, []):
            with self.subTest(bad=bad):
                verification = verify_registered_capability(
                    bad, self.manager, self.capability_system)
                self.assertEqual(verification["status"], VERIFICATION_STATUS_INVALID)

    def test_malformed_dependencies_are_invalid(self):
        result = self.registered_result()
        tampered = copy.deepcopy(result)
        tampered["registration_plan"]["approval_request_id"] = "   "
        verification = verify_registered_capability(
            tampered, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_INVALID)
        self.assertTrue(any("approval_request_id" in e for e in verification["errors"]))

    def test_malformed_inputs_to_this_function_itself_are_invalid(self):
        result = self.registered_result()
        for bad_manager in (None, object()):
            with self.subTest(bad_manager=bad_manager):
                verification = verify_registered_capability(
                    result, bad_manager, self.capability_system)
                self.assertEqual(verification["status"], VERIFICATION_STATUS_INVALID)
        for bad_registry in (None, object()):
            with self.subTest(bad_registry=bad_registry):
                verification = verify_registered_capability(
                    result, self.manager, bad_registry)
                self.assertEqual(verification["status"], VERIFICATION_STATUS_INVALID)


# --------------------------------------------------------------------
# Field mismatches -> FAILED
# --------------------------------------------------------------------
class MismatchTests(Setup):
    def test_mismatched_interface_name_fails(self):
        result = self.registered_result()
        tampered = copy.deepcopy(result)
        tampered["registration_plan"]["interface_name"] = "some.other.Interface"
        verification = verify_registered_capability(
            tampered, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_FAILED)
        self.assertTrue(any("interface_name" in m for m in verification["mismatches"]))

    def test_mismatched_target_module_fails(self):
        result = self.registered_result()
        tampered = copy.deepcopy(result)
        tampered["registration_plan"]["target_module"] = "some.other.module"
        verification = verify_registered_capability(
            tampered, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_FAILED)
        self.assertTrue(any("target_module" in m for m in verification["mismatches"]))

    def test_mismatched_input_schema_fails(self):
        result = self.registered_result()
        tampered = copy.deepcopy(result)
        tampered["registration_plan"]["input_schema"] = {"changed": True}
        verification = verify_registered_capability(
            tampered, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_FAILED)
        self.assertTrue(any("input_schema" in m for m in verification["mismatches"]))

    def test_mismatched_output_schema_fails(self):
        result = self.registered_result()
        tampered = copy.deepcopy(result)
        tampered["registration_plan"]["output_schema"] = {"changed": True}
        verification = verify_registered_capability(
            tampered, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_FAILED)
        self.assertTrue(any("output_schema" in m for m in verification["mismatches"]))

    def test_mismatched_source_version_fails(self):
        result = self.registered_result()
        tampered = copy.deepcopy(result)
        tampered["registration_plan"]["source_version"] = {"id": 999999,
                                                             "version_label": "forged"}
        verification = verify_registered_capability(
            tampered, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_FAILED)
        self.assertTrue(any("source_version" in m for m in verification["mismatches"]))

    def test_mismatched_approval_request_id_fails(self):
        result = self.registered_result()
        tampered = copy.deepcopy(result)
        tampered["registration_plan"]["approval_request_id"] = "approval-forged"
        verification = verify_registered_capability(
            tampered, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_FAILED)
        self.assertTrue(any("approval_request_id" in m for m in verification["mismatches"]))

    def test_current_decision_no_longer_ready_fails(self):
        # The stored approval record itself is later found rejected -
        # e.g. a separate correction/rollback flow reversed the human
        # decision after registration already happened.
        result = self.registered_result()
        record = self.memory.get_state(f"capability_approval:{result['request_id']}")
        record = dict(record, status="REJECTED")
        self.memory.set_state(f"capability_approval:{result['request_id']}", record)
        verification = verify_registered_capability(
            result, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_FAILED)
        self.assertTrue(verification["mismatches"])

    def test_directly_edited_registry_description_fails(self):
        result = self.registered_result()
        self.memory._run(
            "UPDATE capabilities SET description = ? WHERE name = ?",
            ("A hand-edited description.", CODE_CHANGE_PLAN_NAME))
        verification = verify_registered_capability(
            result, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_FAILED)
        self.assertTrue(any("description" in m for m in verification["mismatches"]))

    def test_directly_enabled_registry_row_fails(self):
        result = self.registered_result()
        self.capability_system.set_enabled(CODE_CHANGE_PLAN_NAME, True)
        verification = verify_registered_capability(
            result, self.manager, self.capability_system)
        self.assertEqual(verification["status"], VERIFICATION_STATUS_FAILED)
        self.assertTrue(any("enabled" in m for m in verification["mismatches"]))


# --------------------------------------------------------------------
# Verification never activates, executes, or modifies anything
# --------------------------------------------------------------------
class NoSideEffectTests(Setup):
    def test_verification_does_not_activate_the_capability(self):
        result = self.registered_result()
        verify_registered_capability(result, self.manager, self.capability_system)
        rows = [c for c in self.capability_system.all() if c["name"] == CODE_CHANGE_PLAN_NAME]
        self.assertFalse(rows[0]["enabled"])

    def test_verification_does_not_call_or_register_an_execution_handler(self):
        result = self.registered_result()
        handlers_before = list(self.handlers.list_registered())
        verify_registered_capability(result, self.manager, self.capability_system)
        self.assertEqual(list(self.handlers.list_registered()), handlers_before)

    def test_verification_does_not_modify_the_registry(self):
        result = self.registered_result()
        rows_before = self.capability_system.all()
        verify_registered_capability(result, self.manager, self.capability_system)
        rows_after = self.capability_system.all()
        self.assertEqual(rows_before, rows_after)

    def test_verification_does_not_change_the_approval_decision(self):
        result = self.registered_result()
        before = self.manager.get_status(result["request_id"])
        verify_registered_capability(result, self.manager, self.capability_system)
        after = self.manager.get_status(result["request_id"])
        self.assertEqual(before, after)

    def test_a_failed_verification_is_not_automatically_retried_or_repaired(self):
        result = self.registered_result()
        tampered = copy.deepcopy(result)
        tampered["registration_plan"]["interface_name"] = "some.other.Interface"
        verify_registered_capability(tampered, self.manager, self.capability_system)
        # The live registry row is left exactly as it was; nothing
        # attempted to "fix" the mismatch or re-register the capability.
        rows = [c for c in self.capability_system.all() if c["name"] == CODE_CHANGE_PLAN_NAME]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], result["capability"]["description"])

    def test_module_never_calls_activation_execution_or_decision_apis(self):
        # Structural guarantee: this module may only ever read a
        # decision and the registry - it can never enable, execute,
        # register/replace a capability, register a handler, approve or
        # reject an approval, or write to the registry/approval store.
        with open(verifier_module.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        forbidden_attrs = {
            "set_enabled", "register", "register_capability", "replace",
            "replace_capability", "unregister", "create_version", "rollback_to",
            "create_request", "approve", "reject", "execute", "run", "set_state",
            "write", "write_text", "system", "popen",
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
