"""
Tests for agent/code_change_upgrade_result.py - a small, structured
result that summarizes the complete CODE_CHANGE self-upgrade flow
(readiness -> Prompt 350, audit -> Prompt 351, version snapshot ->
Prompt 352, rollback -> Prompt 353), made available on the existing
AgentLoop via `AgentLoop.build_code_change_upgrade_result` (agent/
agent_loop.py, Prompt 354).

Covers: each of the four deterministic `final_status` outcomes -
SUCCESS (test passed, validated, sandboxed, snapshotted), FAILED (a
rollback attempt itself could not complete, or a READY change could
not be snapshotted), ROLLED_BACK (test failed/timed out and the
existing rollback succeeded), and REJECTED (test passed but
validation/application/sandbox rejected the change); the result never
re-derives any of the four already-computed inputs it reads from;
never retries a change or starts another upgrade; is a plain,
serializable dict; never raises on malformed input; and AgentLoop
wiring.

Run directly:
    python -m unittest tests.test_code_change_upgrade_result -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_change_upgrade_result import (
    FINAL_STATUS_SUCCESS,
    FINAL_STATUS_FAILED,
    FINAL_STATUS_ROLLED_BACK,
    FINAL_STATUS_REJECTED,
    ALL_CODE_CHANGE_UPGRADE_FINAL_STATUSES,
    build_code_change_upgrade_result,
)
from agent.code_change_self_upgrade_validation import (
    build_code_change_self_upgrade_readiness,
)
from agent.code_change_version_snapshot import build_code_change_version_snapshot
from agent.code_change_rollback import build_code_change_rollback_decision
from agent.code_correction_proposal import STATUS_PROPOSED
from agent.code_error_analysis import ERROR_TYPE_NAME
from agent.code_correction_proposal_validation import (
    VALIDATION_STATUS_VALID,
    VALIDATION_STATUS_INVALID,
)
from agent.code_correction_application import STATUS_APPLIED
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED, RESULT_TIMEOUT

from memory.memory_system import MemorySystem
from self_upgrade.version_system import VersionSystem

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController
from agent.agent_loop import AgentLoop


def _proposal(target_file, status=STATUS_PROPOSED):
    return {
        "target_file": target_file,
        "error_type": ERROR_TYPE_NAME,
        "reason": "NameError detected",
        "change_description": "Define the missing name.",
        "status": status,
        "ready_to_apply": False,
        "apply_capability": "code_change_plan",
        "learned_patterns": [],
        "learned_pattern_used": False,
    }


def _validation_result(target_file, status=VALIDATION_STATUS_VALID, is_safe_to_apply=True, reason="valid"):
    return {
        "status": status,
        "target_file": target_file,
        "reason": reason,
        "is_safe_to_apply": is_safe_to_apply,
    }


def _application(target_file, status=STATUS_APPLIED, changed=True, error=None):
    return {
        "status": status,
        "target_file": target_file,
        "changed": changed,
        "error": error,
    }


def _correction_result(proposal, validation_result, application):
    return {
        "proposal": proposal,
        "validation_result": validation_result,
        "application": application,
    }


def _new_version_system():
    return VersionSystem(MemorySystem(tempfile.mktemp(suffix=".db")))


class TestFinalStatusSuccess(unittest.TestCase):
    """A validated, applied, passing-test change that clears the
    existing sandbox check and is successfully snapshotted -> SUCCESS,
    the change is KEPT and never rolled back."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.versions = _new_version_system()
        self.correction_result = _correction_result(
            _proposal(self.target_file), _validation_result(self.target_file), _application(self.target_file),
        )
        self.readiness_result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.snapshot_result = build_code_change_version_snapshot(
            self.correction_result, RESULT_PASSED, self.readiness_result, None, self.versions,
        )
        self.rollback_result = build_code_change_rollback_decision(
            RESULT_PASSED, self.target_file, self.snapshot_result["version"], self.versions,
        )
        self.result = build_code_change_upgrade_result(
            self.correction_result, self.readiness_result, self.snapshot_result, self.rollback_result,
        )

    def test_final_status_success(self):
        self.assertEqual(self.result["final_status"], FINAL_STATUS_SUCCESS)

    def test_component_statuses_reused_verbatim(self):
        self.assertEqual(self.result["validation_status"], VALIDATION_STATUS_VALID)
        self.assertEqual(self.result["change_status"], "KEPT")
        self.assertEqual(self.result["test_status"], RESULT_PASSED)
        self.assertEqual(self.result["version_status"], "CREATED")
        self.assertFalse(self.result["rollback_required"])
        self.assertEqual(self.result["rollback_status"], "NOT_REQUIRED")

    def test_target_file_reported(self):
        self.assertEqual(self.result["target_file"], self.target_file)

    def test_result_has_exactly_the_eight_required_fields(self):
        self.assertEqual(
            set(self.result.keys()),
            {
                "target_file", "validation_status", "change_status", "test_status",
                "version_status", "rollback_required", "rollback_status", "final_status",
            },
        )

    def test_result_is_plain_and_serializable(self):
        import json
        json.dumps(self.result)  # never raises on a plain, serializable result


class TestFinalStatusRolledBack(unittest.TestCase):
    """A change whose relevant test came back FAILED/TIMEOUT never
    reaches readiness (test not passed); the existing rollback then
    succeeds -> ROLLED_BACK."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.versions = _new_version_system()
        self.good_version = self.versions.create_version(None, "good", snapshot={"good": True})
        self.correction_result = _correction_result(
            _proposal(self.target_file), _validation_result(self.target_file), _application(self.target_file),
        )

    def test_failed_test_status_rolls_back(self):
        readiness_result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_FAILED,
        )
        snapshot_result = build_code_change_version_snapshot(
            self.correction_result, RESULT_FAILED, readiness_result, None, self.versions,
        )
        rollback_result = build_code_change_rollback_decision(
            RESULT_FAILED, self.target_file, self.good_version, self.versions,
        )
        result = build_code_change_upgrade_result(
            self.correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result["final_status"], FINAL_STATUS_ROLLED_BACK)
        self.assertEqual(result["change_status"], "ROLLED_BACK")
        self.assertTrue(result["rollback_required"])
        self.assertEqual(result["rollback_status"], "SUCCEEDED")
        # The readiness check never became READY (test not passed), and
        # no version snapshot was ever created for this failed change.
        self.assertNotEqual(result["version_status"], "CREATED")

    def test_timeout_test_status_rolls_back(self):
        readiness_result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_TIMEOUT,
        )
        snapshot_result = build_code_change_version_snapshot(
            self.correction_result, RESULT_TIMEOUT, readiness_result, None, self.versions,
        )
        rollback_result = build_code_change_rollback_decision(
            RESULT_TIMEOUT, self.target_file, self.good_version, self.versions,
        )
        result = build_code_change_upgrade_result(
            self.correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result["final_status"], FINAL_STATUS_ROLLED_BACK)
        self.assertEqual(result["test_status"], RESULT_TIMEOUT)


class TestFinalStatusFailed(unittest.TestCase):
    """A rollback that is required but cannot itself complete ->
    FAILED; likewise a READY, test-passing change that could not be
    snapshotted (no VersionSystem available) -> FAILED."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.correction_result = _correction_result(
            _proposal(self.target_file), _validation_result(self.target_file), _application(self.target_file),
        )

    def test_rollback_attempt_that_cannot_complete_is_failed(self):
        readiness_result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_FAILED,
        )
        snapshot_result = build_code_change_version_snapshot(
            self.correction_result, RESULT_FAILED, readiness_result, None, None,
        )
        # No versions system supplied -> rollback attempt cannot
        # complete, reported as ROLLBACK_FAILED, never raised.
        rollback_result = build_code_change_rollback_decision(
            RESULT_FAILED, self.target_file, {"id": 1}, None,
        )
        result = build_code_change_upgrade_result(
            self.correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result["final_status"], FINAL_STATUS_FAILED)
        self.assertEqual(result["change_status"], "ROLLBACK_FAILED")
        self.assertEqual(result["rollback_status"], "FAILED")

    def test_ready_change_that_could_not_be_snapshotted_is_failed(self):
        readiness_result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertEqual(readiness_result["status"], "READY")
        # No VersionSystem supplied -> the otherwise-READY change is
        # SKIPPED rather than snapshotted.
        snapshot_result = build_code_change_version_snapshot(
            self.correction_result, RESULT_PASSED, readiness_result, None, None,
        )
        self.assertEqual(snapshot_result["status"], "SKIPPED")
        rollback_result = build_code_change_rollback_decision(
            RESULT_PASSED, self.target_file, None, None,
        )
        self.assertEqual(rollback_result["change_status"], "KEPT")
        result = build_code_change_upgrade_result(
            self.correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result["final_status"], FINAL_STATUS_FAILED)

    def test_malformed_inputs_never_raise_and_default_to_failed(self):
        try:
            result = build_code_change_upgrade_result(None, None, None, None)
        except Exception as exc:  # pragma: no cover - defensive
            self.fail(f"build_code_change_upgrade_result raised: {exc!r}")
        self.assertEqual(result["final_status"], FINAL_STATUS_FAILED)
        self.assertIsNone(result["target_file"])
        self.assertIsNone(result["validation_status"])
        self.assertIsNone(result["change_status"])


class TestFinalStatusRejected(unittest.TestCase):
    """A change whose relevant test passed but whose validation was
    never safe to apply (or was never actually applied) is REJECTED by
    the existing readiness check - the test passing alone never forces
    a rollback, and never counts as success."""

    def test_invalid_validation_is_rejected(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file),
            _validation_result(target_file, status=VALIDATION_STATUS_INVALID, is_safe_to_apply=False, reason="unsafe"),
            _application(target_file, status=STATUS_APPLIED, changed=False),
        )
        versions = _new_version_system()
        readiness_result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertEqual(readiness_result["status"], "REJECTED")
        snapshot_result = build_code_change_version_snapshot(
            correction_result, RESULT_PASSED, readiness_result, None, versions,
        )
        self.assertEqual(snapshot_result["status"], "SKIPPED")
        rollback_result = build_code_change_rollback_decision(
            RESULT_PASSED, target_file, None, versions,
        )
        self.assertEqual(rollback_result["change_status"], "KEPT")
        result = build_code_change_upgrade_result(
            correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result["final_status"], FINAL_STATUS_REJECTED)
        self.assertEqual(result["validation_status"], VALIDATION_STATUS_INVALID)
        self.assertEqual(result["version_status"], "SKIPPED")


class TestNeverRetriesOrStartsAnotherUpgrade(unittest.TestCase):
    """Requirements 5, 6: reporting a FAILED/REJECTED/ROLLED_BACK
    result never re-applies the change, never re-runs a test, and
    never proposes or starts a new upgrade of its own."""

    def test_result_carries_no_retry_or_new_upgrade_fields(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file), _validation_result(target_file), _application(target_file),
        )
        versions = _new_version_system()
        readiness_result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_FAILED,
        )
        snapshot_result = build_code_change_version_snapshot(
            correction_result, RESULT_FAILED, readiness_result, None, versions,
        )
        good_version = versions.create_version(None, "good", snapshot={})
        rollback_result = build_code_change_rollback_decision(
            RESULT_FAILED, target_file, good_version, versions,
        )
        result = build_code_change_upgrade_result(
            correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertNotIn("retry", result)
        self.assertNotIn("new_upgrade", result)
        self.assertNotIn("proposal", result)


class TestFixedVocabulary(unittest.TestCase):
    def test_all_final_statuses(self):
        self.assertEqual(
            ALL_CODE_CHANGE_UPGRADE_FINAL_STATUSES,
            (FINAL_STATUS_SUCCESS, FINAL_STATUS_FAILED, FINAL_STATUS_ROLLED_BACK, FINAL_STATUS_REJECTED),
        )


class TestAgentLoopBuildCodeChangeUpgradeResult(unittest.TestCase):
    """Requirement: make the unified upgrade result available on the
    existing AgentLoop, without creating a second CODE_CHANGE, audit,
    validation, testing, version, or rollback system."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.versions = _new_version_system()
        self.loop = AgentLoop(goals, plans, controller, version_system=self.versions)
        self.target_file = "/tmp/allowed/generated.py"
        self.correction_result = _correction_result(
            _proposal(self.target_file), _validation_result(self.target_file), _application(self.target_file),
        )

    def test_success_flow_through_agent_loop(self):
        readiness_result = self.loop.evaluate_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        snapshot_result = self.loop.snapshot_self_upgrade_version(
            self.correction_result, RESULT_PASSED, readiness_result,
        )
        rollback_result = self.loop.decide_code_change_rollback(
            RESULT_PASSED, self.target_file, snapshot_result["version"],
        )
        result = self.loop.build_code_change_upgrade_result(
            self.correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result["final_status"], FINAL_STATUS_SUCCESS)

    def test_rolled_back_flow_through_agent_loop(self):
        good_version = self.versions.create_version(None, "good", snapshot={})
        readiness_result = self.loop.evaluate_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_FAILED,
        )
        snapshot_result = self.loop.snapshot_self_upgrade_version(
            self.correction_result, RESULT_FAILED, readiness_result,
        )
        rollback_result = self.loop.decide_code_change_rollback(
            RESULT_FAILED, self.target_file, good_version,
        )
        result = self.loop.build_code_change_upgrade_result(
            self.correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result["final_status"], FINAL_STATUS_ROLLED_BACK)

    def test_never_touches_a_second_upgrade_or_version_system(self):
        readiness_result = self.loop.evaluate_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        snapshot_result = self.loop.snapshot_self_upgrade_version(
            self.correction_result, RESULT_PASSED, readiness_result,
        )
        rollback_result = self.loop.decide_code_change_rollback(
            RESULT_PASSED, self.target_file, snapshot_result["version"],
        )
        self.loop.build_code_change_upgrade_result(
            self.correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertFalse(hasattr(self.loop, "upgrades"))
        self.assertIs(self.loop.versions, self.versions)


if __name__ == "__main__":
    unittest.main()
