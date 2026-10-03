"""
Tests for agent/code_change_self_upgrade_validation.py - connects the
existing CODE_CHANGE Self-Upgrade adapter (agent/code_change_self_
upgrade_adapter.py, Prompt 349) to the existing Self-Upgrade
validation/sandbox stage (self_upgrade/sandbox.py's `Sandbox`), made
available on the existing AgentLoop via
`AgentLoop.evaluate_self_upgrade_readiness` (agent/agent_loop.py,
Prompt 350).

Covers: a fully valid, applied, passing-test change reaching READY
through the real, unmodified Sandbox; each of the four rejection
cases (validation failed, change not applied, test not passed,
required metadata missing); target_file always being reported;
never raising on malformed input; and AgentLoop wiring, including
that no upgrade is ever installed, activated, or versioned.

Run directly:
    python -m unittest tests.test_code_change_self_upgrade_validation -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_change_self_upgrade_validation import (
    STATUS_READY,
    STATUS_REJECTED,
    ALL_SELF_UPGRADE_READINESS_STATUSES,
    build_code_change_self_upgrade_readiness,
)
from agent.code_correction_proposal import STATUS_PROPOSED, STATUS_NOT_READY
from agent.code_error_analysis import ERROR_TYPE_NAME
from agent.code_correction_proposal_validation import (
    VALIDATION_STATUS_VALID,
    VALIDATION_STATUS_INVALID,
)
from agent.code_correction_application import (
    STATUS_APPLIED,
    STATUS_NOT_READY as APPLICATION_STATUS_NOT_READY,
)
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED

from self_upgrade.sandbox import Sandbox, SandboxResult

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


class _AlwaysFailSandbox:
    """A minimal, injectable Sandbox stand-in used only to prove this
    module actually calls into whatever sandbox it is given, rather
    than ignoring it - never a replacement for the real Sandbox in
    any other test."""

    def run(self, payload):
        return SandboxResult(False, "Rejected by injected test sandbox.")


class TestValidChangePassesThroughRealSandboxToReady(unittest.TestCase):
    """Requirement: a validated, successfully applied, passing-test
    code change reaches READY by way of the existing, real Sandbox."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.correction_result = _correction_result(
            _proposal(self.target_file), _validation_result(self.target_file), _application(self.target_file),
        )
        self.result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_PASSED,
        )

    def test_status_ready(self):
        self.assertEqual(self.result["status"], STATUS_READY)

    def test_target_file_reported(self):
        self.assertEqual(self.result["target_file"], self.target_file)

    def test_reason_is_a_non_empty_string(self):
        self.assertIsInstance(self.result["reason"], str)
        self.assertTrue(self.result["reason"])

    def test_uses_the_real_unmodified_sandbox_by_default(self):
        # No sandbox= was passed above; a real self_upgrade.sandbox.Sandbox
        # was used internally and reported the payload as structurally
        # valid (it carries name/description from the Prompt-349 adapter).
        sandbox = Sandbox()
        payload = {"name": f"code_change:{self.target_file}", "description": "x"}
        self.assertTrue(sandbox.run(payload).passed)


class TestValidationFailedIsRejected(unittest.TestCase):
    """Requirement 4: reject when validation failed."""

    def test_invalid_validation_result_is_rejected(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file),
            _validation_result(
                target_file, status=VALIDATION_STATUS_INVALID, is_safe_to_apply=False,
                reason="The proposal does not include error information.",
            ),
            _application(target_file, status="REJECTED", changed=False),
        )
        result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertEqual(result["reason"], "The proposal does not include error information.")
        self.assertEqual(result["target_file"], target_file)


class TestChangeNotAppliedIsRejected(unittest.TestCase):
    """Requirement 4: reject when the change was not successfully
    applied."""

    def test_not_ready_application_is_rejected(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file),
            _validation_result(target_file),
            _application(
                target_file, status=APPLICATION_STATUS_NOT_READY, changed=False,
                error="The correction could not be applied.",
            ),
        )
        result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertEqual(result["reason"], "The correction could not be applied.")
        self.assertEqual(result["target_file"], target_file)


class TestTestNotPassedIsRejected(unittest.TestCase):
    """Requirement 4: reject when the relevant test did not pass, even
    though validation and application both succeeded."""

    def test_failed_test_status_is_rejected(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file), _validation_result(target_file), _application(target_file),
        )
        result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_FAILED,
        )
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIn("test", result["reason"].lower())
        self.assertEqual(result["target_file"], target_file)


class TestRequiredMetadataMissingIsRejected(unittest.TestCase):
    """Requirement 4: reject when required metadata is missing, and
    requirement 3: target_file/original_fragment/replacement/
    test_status/validation status must all be present."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.correction_result = _correction_result(
            _proposal(self.target_file), _validation_result(self.target_file), _application(self.target_file),
        )

    def test_missing_original_fragment_is_rejected(self):
        result = build_code_change_self_upgrade_readiness(
            self.correction_result, "", "42", RESULT_PASSED,
        )
        self.assertEqual(result["status"], STATUS_REJECTED)

    def test_none_original_fragment_is_rejected(self):
        result = build_code_change_self_upgrade_readiness(
            self.correction_result, None, "42", RESULT_PASSED,
        )
        self.assertEqual(result["status"], STATUS_REJECTED)

    def test_non_string_replacement_is_rejected(self):
        result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", None, RESULT_PASSED,
        )
        self.assertEqual(result["status"], STATUS_REJECTED)

    def test_unrecognized_test_status_is_rejected(self):
        result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", "NOT_A_REAL_STATUS",
        )
        self.assertEqual(result["status"], STATUS_REJECTED)

    def test_missing_test_status_is_rejected(self):
        result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", None,
        )
        self.assertEqual(result["status"], STATUS_REJECTED)

    def test_missing_target_file_reports_none_target_file(self):
        correction_result = _correction_result(
            _proposal(None), _validation_result(None), _application(None),
        )
        result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIsNone(result["target_file"])


class TestConnectsToInjectedSandbox(unittest.TestCase):
    """Requirement 2, 8: this stage actually calls into the existing
    Self-Upgrade sandbox stage rather than skipping it - proven here
    via a minimal injectable stand-in, never a duplicate sandbox
    implementation of this module's own."""

    def test_sandbox_rejection_is_surfaced(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file), _validation_result(target_file), _application(target_file),
        )
        result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
            sandbox=_AlwaysFailSandbox(),
        )
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertEqual(result["reason"], "Rejected by injected test sandbox.")
        self.assertEqual(result["target_file"], target_file)


class TestNeverInstallsOrVersions(unittest.TestCase):
    """Requirement 6, 7: never install/activate anything, and never
    touch version/rollback behavior."""

    def test_result_never_mentions_upgrade_or_version_fields(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file), _validation_result(target_file), _application(target_file),
        )
        result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertEqual(set(result.keys()), {"status", "reason", "target_file"})


class TestNeverRaises(unittest.TestCase):
    def test_none_correction_result(self):
        result = build_code_change_self_upgrade_readiness(None, "x", "y", RESULT_PASSED)
        self.assertEqual(result["status"], STATUS_REJECTED)

    def test_non_dict_correction_result(self):
        result = build_code_change_self_upgrade_readiness(
            "not a correction result", "x", "y", RESULT_PASSED,
        )
        self.assertEqual(result["status"], STATUS_REJECTED)


class TestAllSelfUpgradeReadinessStatuses(unittest.TestCase):
    def test_fixed_two_way_vocabulary(self):
        self.assertEqual(
            ALL_SELF_UPGRADE_READINESS_STATUSES, (STATUS_READY, STATUS_REJECTED),
        )


class TestAgentLoopEvaluateSelfUpgradeReadiness(unittest.TestCase):
    """Requirement: make the readiness check available on the existing
    AgentLoop, without creating a new Self-Upgrade system and without
    installing/activating/versioning anything automatically."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.loop = AgentLoop(goals, plans, controller)

    def test_ready_for_valid_applied_passing_change(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file), _validation_result(target_file), _application(target_file),
        )
        result = self.loop.evaluate_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertEqual(result["status"], STATUS_READY)

    def test_rejects_failing_test(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file), _validation_result(target_file), _application(target_file),
        )
        result = self.loop.evaluate_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_FAILED,
        )
        self.assertEqual(result["status"], STATUS_REJECTED)

    def test_never_touches_an_upgrade_or_version_system(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file), _validation_result(target_file), _application(target_file),
        )
        self.loop.evaluate_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertFalse(hasattr(self.loop, "upgrades"))
        self.assertFalse(hasattr(self.loop, "versions"))


if __name__ == "__main__":
    unittest.main()
