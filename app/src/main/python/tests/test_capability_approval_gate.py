"""
Tests for self_upgrade.capability_approval_gate
.evaluate_self_upgrade_approval_gate (Prompt 372) - a read-only
continuation gate that always re-checks a PENDING_APPROVAL
HumanApprovalRequest against the authoritative ApprovalManager record,
and only ever sets activation_allowed/registration_allowed True for
READY_FOR_ACTIVATION.

Run directly:
    python -m unittest tests.test_capability_approval_gate -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import shutil
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_upgrade.capability_approval_gate import (
    evaluate_self_upgrade_approval_gate,
    GATE_STATUS_READY_FOR_ACTIVATION,
    GATE_STATUS_UPGRADE_REJECTED,
    GATE_STATUS_WAITING_FOR_APPROVAL,
    GATE_STATUS_INVALID,
    GATE_STATUS_BLOCKED,
    ALL_GATE_STATUSES,
)
from self_upgrade.capability_approval_manager import ApprovalManager
from self_upgrade.capability_human_approval import (
    request_capability_human_approval,
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_BLOCKED,
    APPROVAL_STATUS_INVALID,
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
from agent.agent_loop import AgentLoop
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController

BROKEN = "def demo():\n    return missing_name\n"
TEST = ("import unittest\nfrom demo_capability import demo\n\n"
        "class T(unittest.TestCase):\n    def test_demo(self):\n"
        "        self.assertEqual(demo(), 1)\n")
TARGET = "test_demo_capability"


class Chain(unittest.TestCase):
    """Builds a real PENDING_APPROVAL HumanApprovalRequest already
    registered with a real ApprovalManager, exactly like
    tests.test_capability_approval_manager does."""

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
        self.memory = MemorySystem(tempfile.mktemp(suffix=".db"))
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

    def registered_request(self):
        verification = verify_capability_correction(
            self.previous, self._correct(), self.sandbox, TARGET,
            allowed_dirs=[self.sandbox])
        request = request_capability_human_approval(
            verification, self.versions, allowed_dirs=[self.sandbox])
        self.assertEqual(request["status"], APPROVAL_STATUS_PENDING)
        created = self.manager.create_request(request)
        self.assertEqual(created["status"], APPROVAL_STATUS_PENDING)
        return request


class PendingRejectedApprovedTests(Chain):
    def test_pending_approval_blocks_continuation(self):
        request = self.registered_request()
        result = evaluate_self_upgrade_approval_gate(request, self.manager)
        self.assertEqual(result["gate_status"], GATE_STATUS_WAITING_FOR_APPROVAL)
        self.assertFalse(result["activation_allowed"])
        self.assertFalse(result["registration_allowed"])

    def test_rejected_blocks_continuation(self):
        request = self.registered_request()
        self.manager.reject(request["request_id"])
        result = evaluate_self_upgrade_approval_gate(request, self.manager)
        self.assertEqual(result["gate_status"], GATE_STATUS_UPGRADE_REJECTED)
        self.assertFalse(result["activation_allowed"])
        self.assertFalse(result["registration_allowed"])

    def test_explicit_approved_allows_continuation(self):
        request = self.registered_request()
        self.manager.approve(request["request_id"])
        result = evaluate_self_upgrade_approval_gate(request, self.manager)
        self.assertEqual(result["gate_status"], GATE_STATUS_READY_FOR_ACTIVATION)
        self.assertTrue(result["activation_allowed"])
        self.assertTrue(result["registration_allowed"])
        self.assertEqual(result["capability_name"], "demo_capability")
        self.assertEqual(result["version"]["id"], request["version"]["id"])

    def test_successful_tests_alone_do_not_allow_continuation(self):
        # registered_request() is only reachable because the
        # underlying capability's tests already passed verification -
        # yet without an explicit approve() call it must still block.
        request = self.registered_request()
        result = evaluate_self_upgrade_approval_gate(request, self.manager)
        self.assertNotEqual(result["gate_status"], GATE_STATUS_READY_FOR_ACTIVATION)
        self.assertFalse(result["activation_allowed"])


class MismatchAndInvalidInputTests(Chain):
    def test_mismatched_capability_is_rejected(self):
        request = self.registered_request()
        self.manager.approve(request["request_id"])
        tampered = dict(request, capability_name="some_other_capability")
        result = evaluate_self_upgrade_approval_gate(tampered, self.manager)
        self.assertEqual(result["gate_status"], GATE_STATUS_INVALID)
        self.assertFalse(result["activation_allowed"])
        self.assertTrue(result["errors"])

    def test_mismatched_version_is_rejected(self):
        request = self.registered_request()
        self.manager.approve(request["request_id"])
        tampered = copy.deepcopy(request)
        tampered["version"] = {"id": (request["version"]["id"] or 0) + 999}
        result = evaluate_self_upgrade_approval_gate(tampered, self.manager)
        self.assertEqual(result["gate_status"], GATE_STATUS_INVALID)
        self.assertFalse(result["activation_allowed"])

    def test_unregistered_request_id_is_invalid(self):
        request = self.registered_request()
        never_registered = dict(request, request_id="never-created-in-manager")
        result = evaluate_self_upgrade_approval_gate(never_registered, self.manager)
        self.assertEqual(result["gate_status"], GATE_STATUS_INVALID)
        self.assertFalse(result["activation_allowed"])

    def test_invalid_human_approval_request_passes_through_invalid(self):
        request = self.registered_request()
        invalid_request = dict(request, status=APPROVAL_STATUS_INVALID, errors=["bad"])
        result = evaluate_self_upgrade_approval_gate(invalid_request, self.manager)
        self.assertEqual(result["gate_status"], GATE_STATUS_INVALID)
        self.assertFalse(result["activation_allowed"])

    def test_blocked_human_approval_request_passes_through_blocked(self):
        request = self.registered_request()
        blocked_request = dict(request, status=APPROVAL_STATUS_BLOCKED, errors=["outside workspace"])
        result = evaluate_self_upgrade_approval_gate(blocked_request, self.manager)
        self.assertEqual(result["gate_status"], GATE_STATUS_BLOCKED)
        self.assertFalse(result["activation_allowed"])

    def test_malformed_request_is_invalid(self):
        result = evaluate_self_upgrade_approval_gate(None, self.manager)
        self.assertEqual(result["gate_status"], GATE_STATUS_INVALID)

    def test_missing_approval_manager_is_invalid(self):
        request = self.registered_request()
        result = evaluate_self_upgrade_approval_gate(request, None)
        self.assertEqual(result["gate_status"], GATE_STATUS_INVALID)
        self.assertFalse(result["activation_allowed"])


class NoSideEffectsTests(Chain):
    def test_no_activation_occurs(self):
        # There is no activation concept anywhere in this module to
        # trigger - confirmed structurally: the result never contains
        # anything beyond the documented ApprovalGateResult keys.
        request = self.registered_request()
        self.manager.approve(request["request_id"])
        result = evaluate_self_upgrade_approval_gate(request, self.manager)
        expected_keys = {
            "request_id", "capability_name", "approval_status", "gate_status",
            "version", "activation_allowed", "registration_allowed", "reason", "errors",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_no_registration_occurs(self):
        request = self.registered_request()
        self.manager.approve(request["request_id"])
        evaluate_self_upgrade_approval_gate(request, self.manager)
        # Nothing about the capability's own file changed.
        with open(self.path, encoding="utf-8") as handle:
            self.assertIn("return 1", handle.read())

    def test_no_source_files_modified(self):
        request = self.registered_request()
        before = os.path.getmtime(self.path)
        self.manager.approve(request["request_id"])
        evaluate_self_upgrade_approval_gate(request, self.manager)
        after = os.path.getmtime(self.path)
        self.assertEqual(before, after)

    def test_existing_approval_manager_behavior_unchanged(self):
        request = self.registered_request()
        before = self.manager.get_status(request["request_id"])
        evaluate_self_upgrade_approval_gate(request, self.manager)
        after = self.manager.get_status(request["request_id"])
        self.assertEqual(before, after)  # gate never approves/rejects/mutates

    def test_all_gate_statuses_are_exactly_five(self):
        self.assertEqual(
            set(ALL_GATE_STATUSES),
            {GATE_STATUS_READY_FOR_ACTIVATION, GATE_STATUS_UPGRADE_REJECTED,
             GATE_STATUS_WAITING_FOR_APPROVAL, GATE_STATUS_INVALID, GATE_STATUS_BLOCKED},
        )


class AgentLoopIntegrationTests(Chain):
    def test_agent_loop_thin_passthrough(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        loop = AgentLoop(goals, plans, PlanExecutionController(plans))
        request = self.registered_request()
        self.manager.approve(request["request_id"])
        result = loop.evaluate_self_upgrade_approval_gate(request, self.manager)
        self.assertEqual(result["gate_status"], GATE_STATUS_READY_FOR_ACTIVATION)


if __name__ == "__main__":
    unittest.main()
