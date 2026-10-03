"""
Tests for self_upgrade.capability_approval_manager.ApprovalManager
(Prompt 371) - stores HumanApprovalRequests and resolves them only via
explicit approve(request_id)/reject(request_id) calls; nothing here
ever infers, auto-approves, auto-rejects, activates, or registers.

Run directly:
    python -m unittest tests.test_capability_approval_manager -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_upgrade.capability_approval_manager import ApprovalManager
from self_upgrade.capability_human_approval import (
    request_capability_human_approval,
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
)
from self_upgrade.capability_correction_verification import verify_capability_correction
from self_upgrade.capability_correction_apply import apply_capability_correction
from self_upgrade.capability_correction_analysis import build_capability_correction_analysis
from self_upgrade.capability_evaluation import evaluate_capability_test_result
from self_upgrade.capability_test_execution import run_capability_tests
from self_upgrade.capability_file_apply import STATUS_APPLIED
from code_generation.generated_code_validator import VALIDATION_VALID
from self_upgrade.version_system import VersionSystem
from memory.memory_system import MemorySystem

BROKEN = "def demo():\n    return missing_name\n"
TEST = ("import unittest\nfrom demo_capability import demo\n\n"
        "class T(unittest.TestCase):\n    def test_demo(self):\n"
        "        self.assertEqual(demo(), 1)\n")
TARGET = "test_demo_capability"


def make_memory():
    return MemorySystem(tempfile.mktemp(suffix=".db"))


class Chain(unittest.TestCase):
    """Builds a real PENDING_APPROVAL HumanApprovalRequest, exactly
    like tests.test_capability_human_approval does, so the manager is
    tested against the real upstream shape, not a hand-built stub."""

    def setUp(self):
        self.sandbox = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.sandbox, ignore_errors=True))
        self.path = os.path.join(self.sandbox, "demo_capability.py")
        self._write(self.path, BROKEN)
        self._write(os.path.join(self.sandbox, TARGET + ".py"), TEST)
        apply_result = dict(
            capability_name="demo_capability", target_module="generated.demo_capability",
            status=STATUS_APPLIED, file_path=self.path, bytes_written=1,
            validation_result={"status": VALIDATION_VALID}, error=None)
        self.previous = run_capability_tests(apply_result, self.sandbox, TARGET)
        self.memory = make_memory()
        self.versions = VersionSystem(self.memory)
        self.manager = ApprovalManager(self.memory)

    @staticmethod
    def _write(path, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _correct(self, new_text="return 1"):
        analysis = build_capability_correction_analysis(
            evaluate_capability_test_result(self.previous), allowed_dirs=[self.sandbox])
        return apply_capability_correction(
            analysis, [{"old_text": "return missing_name", "new_text": new_text}],
            allowed_dirs=[self.sandbox])

    def pending_request(self):
        verification = verify_capability_correction(
            self.previous, self._correct(), self.sandbox, TARGET,
            allowed_dirs=[self.sandbox])
        request = request_capability_human_approval(
            verification, self.versions, allowed_dirs=[self.sandbox])
        self.assertEqual(request["status"], APPROVAL_STATUS_PENDING)
        return request


class CreateAndBasicLifecycleTests(Chain):
    def test_new_request_starts_pending_approval(self):
        request = self.pending_request()
        result = self.manager.create_request(request)
        self.assertEqual(result["status"], APPROVAL_STATUS_PENDING)
        self.assertEqual(result["request_id"], request["request_id"])
        self.assertEqual(result["capability_name"], "demo_capability")
        self.assertIsNone(result["decision_timestamp"])
        self.assertEqual(result["errors"], [])

    def test_explicit_approval_changes_status_to_approved(self):
        request = self.pending_request()
        self.manager.create_request(request)
        result = self.manager.approve(request["request_id"])
        self.assertEqual(result["status"], APPROVAL_STATUS_APPROVED)
        self.assertIsNotNone(result["decision_timestamp"])
        self.assertEqual(result["errors"], [])
        # And it is durably stored, not just returned once.
        stored = self.manager.get_status(request["request_id"])
        self.assertEqual(stored["status"], APPROVAL_STATUS_APPROVED)

    def test_explicit_rejection_changes_status_to_rejected(self):
        request = self.pending_request()
        self.manager.create_request(request)
        result = self.manager.reject(request["request_id"])
        self.assertEqual(result["status"], APPROVAL_STATUS_REJECTED)
        self.assertIsNotNone(result["decision_timestamp"])
        stored = self.manager.get_status(request["request_id"])
        self.assertEqual(stored["status"], APPROVAL_STATUS_REJECTED)

    def test_request_metadata_is_preserved(self):
        request = self.pending_request()
        self.manager.create_request(request)
        result = self.manager.approve(request["request_id"])
        self.assertEqual(result["version"]["id"], request["version"]["id"])
        stored = self.manager.get_request(request["request_id"])
        self.assertEqual(stored["capability_name"], "demo_capability")
        self.assertEqual(stored["version"]["id"], request["version"]["id"])


class InvalidAndRepeatedTransitionTests(Chain):
    def test_approval_without_a_valid_request_is_rejected(self):
        result = self.manager.approve("does-not-exist")
        self.assertIsNone(result["status"])
        self.assertTrue(result["errors"])

    def test_rejection_without_a_valid_request_is_rejected(self):
        result = self.manager.reject("does-not-exist")
        self.assertIsNone(result["status"])
        self.assertTrue(result["errors"])

    def test_approved_cannot_silently_transition_again(self):
        request = self.pending_request()
        self.manager.create_request(request)
        self.manager.approve(request["request_id"])

        second = self.manager.reject(request["request_id"])
        self.assertEqual(second["status"], APPROVAL_STATUS_APPROVED)  # unchanged
        self.assertTrue(second["errors"])

        third = self.manager.approve(request["request_id"])
        self.assertEqual(third["status"], APPROVAL_STATUS_APPROVED)  # still unchanged
        self.assertTrue(third["errors"])

    def test_rejected_cannot_silently_transition_again(self):
        request = self.pending_request()
        self.manager.create_request(request)
        self.manager.reject(request["request_id"])

        second = self.manager.approve(request["request_id"])
        self.assertEqual(second["status"], APPROVAL_STATUS_REJECTED)  # unchanged
        self.assertTrue(second["errors"])

    def test_create_does_not_overwrite_an_existing_decision(self):
        request = self.pending_request()
        self.manager.create_request(request)
        self.manager.approve(request["request_id"])

        again = self.manager.create_request(request)
        self.assertEqual(again["status"], APPROVAL_STATUS_APPROVED)  # unchanged
        self.assertTrue(again["errors"])

    def test_malformed_request_is_rejected(self):
        self.assertTrue(self.manager.create_request(None)["errors"])
        self.assertTrue(self.manager.create_request({})["errors"])

    def test_non_pending_human_approval_request_is_rejected(self):
        request = self.pending_request()
        request = dict(request, status="INVALID")
        result = self.manager.create_request(request)
        self.assertTrue(result["errors"])
        self.assertIsNone(self.manager.get_request(request["request_id"])["status"])


class NoAutomaticDecisionTests(Chain):
    def test_creating_a_request_never_auto_approves(self):
        request = self.pending_request()
        result = self.manager.create_request(request)
        self.assertNotEqual(result["status"], APPROVAL_STATUS_APPROVED)
        self.assertNotEqual(result["status"], APPROVAL_STATUS_REJECTED)

    def test_test_success_alone_cannot_approve_a_request(self):
        # The underlying verification was VERIFIED (tests passed), but
        # ApprovalManager.approve/reject take only a request_id - there
        # is no parameter through which a test result could reach a
        # decision, and create_request alone never decides anything.
        request = self.pending_request()
        result = self.manager.create_request(request)
        self.assertEqual(result["status"], APPROVAL_STATUS_PENDING)
        # Confirms approve() has no keyword for injecting a verdict.
        import inspect
        params = list(inspect.signature(self.manager.approve).parameters)
        self.assertEqual(params, ["request_id"])


class ExistingBehaviorUnchangedTests(Chain):
    def test_existing_version_system_untouched(self):
        request = self.pending_request()
        before = self.versions.current_version()
        self.manager.create_request(request)
        self.manager.approve(request["request_id"])
        after = self.versions.current_version()
        self.assertEqual(before["id"], after["id"])

    def test_memory_state_table_only_touched_via_its_own_api(self):
        request = self.pending_request()
        self.manager.create_request(request)
        raw = self.memory.get_state(f"capability_approval:{request['request_id']}")
        self.assertEqual(raw["status"], APPROVAL_STATUS_PENDING)


class GetStoredRecordTests(Chain):
    """get_stored_record (Prompt 376) - a read-only getter for the
    complete stored record, added so a later step (self_upgrade.
    capability_registration_decision) can read extra fields (e.g. a
    RegistrationApprovalRequest's request_type/registration_plan)
    without a second storage system. Never mutates anything."""

    def test_unknown_request_id_returns_none(self):
        self.assertIsNone(self.manager.get_stored_record("does-not-exist"))

    def test_returns_the_full_record_including_extra_fields(self):
        request = self.pending_request()
        request["request_type"] = "capability_registration"  # an extra field
        self.manager.create_request(request)
        record = self.manager.get_stored_record(request["request_id"])
        self.assertEqual(record["request_type"], "capability_registration")
        self.assertEqual(record["status"], APPROVAL_STATUS_PENDING)
        self.assertEqual(record["version"]["id"], request["version"]["id"])

    def test_reflects_decisions_and_never_mutates_state(self):
        request = self.pending_request()
        self.manager.create_request(request)
        self.manager.approve(request["request_id"])
        record = self.manager.get_stored_record(request["request_id"])
        self.assertEqual(record["status"], APPROVAL_STATUS_APPROVED)
        record["status"] = "TAMPERED"  # mutating the returned copy...
        self.assertEqual(self.manager.get_status(request["request_id"])["status"],
                         APPROVAL_STATUS_APPROVED)  # ...never touches stored state


if __name__ == "__main__":
    unittest.main()
