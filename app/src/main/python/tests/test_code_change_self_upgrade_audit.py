"""
Tests for agent/code_change_self_upgrade_audit.py - a small, local,
deterministic audit record for a CODE_CHANGE Self-Upgrade readiness
check that has already finished (agent/code_change_self_upgrade_
validation.py's `build_code_change_self_upgrade_readiness`, Prompt
350, reused unchanged), made available on the existing AgentLoop via
`AgentLoop.record_self_upgrade_audit`/`AgentLoop.latest_self_upgrade_
audit` (agent/agent_loop.py, Prompt 351).

Covers: successful (READY) audit creation; rejected-change audit
creation; latest-audit retrieval (including the empty-log case); that
audit records never install/activate/version anything; and AgentLoop
wiring.

Run directly:
    python -m unittest tests.test_code_change_self_upgrade_audit -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_change_self_upgrade_audit import (
    CodeChangeAuditLog,
    build_code_change_audit_record,
)
from agent.code_change_self_upgrade_validation import (
    STATUS_READY,
    STATUS_REJECTED,
    build_code_change_self_upgrade_readiness,
)
from agent.code_correction_proposal import STATUS_PROPOSED
from agent.code_error_analysis import ERROR_TYPE_NAME
from agent.code_correction_proposal_validation import (
    VALIDATION_STATUS_VALID,
    VALIDATION_STATUS_INVALID,
)
from agent.code_correction_application import STATUS_APPLIED
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED

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


def _ready_correction_result(target_file):
    return _correction_result(
        _proposal(target_file), _validation_result(target_file), _application(target_file),
    )


def _rejected_correction_result(target_file):
    return _correction_result(
        _proposal(target_file),
        _validation_result(
            target_file, status=VALIDATION_STATUS_INVALID, is_safe_to_apply=False,
            reason="The proposal does not include error information.",
        ),
        _application(target_file, status="REJECTED", changed=False),
    )


class TestSuccessfulAuditCreation(unittest.TestCase):
    """Requirement 8: focused test for successful audit creation."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.correction_result = _ready_correction_result(self.target_file)
        self.readiness_result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.log = CodeChangeAuditLog()
        self.record = self.log.record(
            self.correction_result, "undefined_name", "42", RESULT_PASSED, self.readiness_result,
        )

    def test_readiness_is_ready(self):
        self.assertEqual(self.readiness_result["status"], STATUS_READY)

    def test_audit_record_has_exactly_the_six_required_fields(self):
        self.assertEqual(
            set(self.record.keys()),
            {
                "target_file", "original_fragment", "replacement",
                "validation_status", "test_status", "result_status",
            },
        )

    def test_audit_record_field_values(self):
        self.assertEqual(self.record["target_file"], self.target_file)
        self.assertEqual(self.record["original_fragment"], "undefined_name")
        self.assertEqual(self.record["replacement"], "42")
        self.assertEqual(self.record["validation_status"], VALIDATION_STATUS_VALID)
        self.assertEqual(self.record["test_status"], RESULT_PASSED)
        self.assertEqual(self.record["result_status"], STATUS_READY)

    def test_audit_record_is_stored_in_the_log(self):
        self.assertEqual(self.log.list_all(), [self.record])
        self.assertEqual(len(self.log), 1)


class TestRejectedChangeAuditCreation(unittest.TestCase):
    """Requirement 8: focused test for rejected-change audit creation -
    an audit entry is recorded for a REJECTED readiness result exactly
    the same way as for a READY one."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.correction_result = _rejected_correction_result(self.target_file)
        self.readiness_result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.log = CodeChangeAuditLog()
        self.record = self.log.record(
            self.correction_result, "undefined_name", "42", RESULT_PASSED, self.readiness_result,
        )

    def test_readiness_is_rejected(self):
        self.assertEqual(self.readiness_result["status"], STATUS_REJECTED)

    def test_audit_record_reports_rejected_result_status(self):
        self.assertEqual(self.record["result_status"], STATUS_REJECTED)

    def test_audit_record_reports_invalid_validation_status(self):
        self.assertEqual(self.record["validation_status"], VALIDATION_STATUS_INVALID)

    def test_audit_record_still_carries_target_file_and_fragments(self):
        self.assertEqual(self.record["target_file"], self.target_file)
        self.assertEqual(self.record["original_fragment"], "undefined_name")
        self.assertEqual(self.record["replacement"], "42")

    def test_rejected_test_status_is_also_audited(self):
        correction_result = _ready_correction_result(self.target_file)
        readiness_result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_FAILED,
        )
        record = self.log.record(
            correction_result, "undefined_name", "42", RESULT_FAILED, readiness_result,
        )
        self.assertEqual(readiness_result["status"], STATUS_REJECTED)
        self.assertEqual(record["result_status"], STATUS_REJECTED)
        self.assertEqual(record["test_status"], RESULT_FAILED)

    def test_audit_record_never_installs_or_versions(self):
        # Recording never mutates correction_result/readiness_result,
        # and the record itself carries no upgrade/version fields.
        self.assertNotIn("upgrade", self.record)
        self.assertNotIn("version", self.record)


class TestLatestAuditRetrieval(unittest.TestCase):
    """Requirement 8: focused test for latest-audit retrieval."""

    def test_latest_is_none_on_an_empty_log(self):
        log = CodeChangeAuditLog()
        self.assertIsNone(log.latest())

    def test_latest_returns_the_most_recently_recorded_record(self):
        target_file = "/tmp/allowed/generated.py"
        log = CodeChangeAuditLog()

        first_correction = _ready_correction_result(target_file)
        first_readiness = build_code_change_self_upgrade_readiness(
            first_correction, "undefined_name", "42", RESULT_PASSED,
        )
        first_record = log.record(
            first_correction, "undefined_name", "42", RESULT_PASSED, first_readiness,
        )

        second_correction = _rejected_correction_result(target_file)
        second_readiness = build_code_change_self_upgrade_readiness(
            second_correction, "undefined_name", "43", RESULT_PASSED,
        )
        second_record = log.record(
            second_correction, "undefined_name", "43", RESULT_PASSED, second_readiness,
        )

        self.assertEqual(log.latest(), second_record)
        self.assertNotEqual(log.latest(), first_record)
        self.assertEqual(len(log), 2)

    def test_clear_empties_the_log(self):
        target_file = "/tmp/allowed/generated.py"
        log = CodeChangeAuditLog()
        correction_result = _ready_correction_result(target_file)
        readiness_result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        log.record(correction_result, "undefined_name", "42", RESULT_PASSED, readiness_result)
        log.clear()
        self.assertIsNone(log.latest())
        self.assertEqual(len(log), 0)


class TestBuildCodeChangeAuditRecordNeverRaises(unittest.TestCase):
    def test_none_correction_result(self):
        record = build_code_change_audit_record(None, "x", "y", RESULT_PASSED, {"status": STATUS_REJECTED, "reason": "r", "target_file": None})
        self.assertIsNone(record["validation_status"])
        self.assertIsNone(record["target_file"])
        self.assertEqual(record["result_status"], STATUS_REJECTED)

    def test_non_dict_readiness_result(self):
        record = build_code_change_audit_record({}, "x", "y", RESULT_PASSED, "not a dict")
        self.assertIsNone(record["result_status"])
        self.assertIsNone(record["target_file"])

    def test_none_readiness_result(self):
        record = build_code_change_audit_record({}, "x", "y", RESULT_PASSED, None)
        self.assertIsNone(record["result_status"])
        self.assertIsNone(record["target_file"])


class TestAgentLoopRecordSelfUpgradeAudit(unittest.TestCase):
    """Requirement: make the audit recording/retrieval available on
    the existing AgentLoop, without creating a new Self-Upgrade or
    version system and without installing/activating anything."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.loop = AgentLoop(goals, plans, controller)

    def test_records_a_ready_audit_and_retrieves_it_as_latest(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _ready_correction_result(target_file)
        result = self.loop.record_self_upgrade_audit(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertEqual(result["readiness"]["status"], STATUS_READY)
        self.assertEqual(result["audit_record"]["result_status"], STATUS_READY)
        self.assertEqual(self.loop.latest_self_upgrade_audit(), result["audit_record"])

    def test_records_a_rejected_audit(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _rejected_correction_result(target_file)
        result = self.loop.record_self_upgrade_audit(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertEqual(result["readiness"]["status"], STATUS_REJECTED)
        self.assertEqual(result["audit_record"]["result_status"], STATUS_REJECTED)
        self.assertEqual(self.loop.latest_self_upgrade_audit(), result["audit_record"])

    def test_latest_is_none_before_any_audit_is_recorded(self):
        self.assertIsNone(self.loop.latest_self_upgrade_audit())

    def test_never_touches_an_upgrade_or_version_system(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _ready_correction_result(target_file)
        self.loop.record_self_upgrade_audit(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertFalse(hasattr(self.loop, "upgrades"))
        self.assertFalse(hasattr(self.loop, "versions"))

    def test_custom_audit_log_can_be_injected(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        injected_log = CodeChangeAuditLog()
        loop = AgentLoop(goals, plans, controller, audit_log=injected_log)
        self.assertIs(loop.audit_log, injected_log)

    def test_rejects_non_audit_log_instance(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        with self.assertRaises(TypeError):
            AgentLoop(goals, plans, controller, audit_log="not an audit log")


if __name__ == "__main__":
    unittest.main()
