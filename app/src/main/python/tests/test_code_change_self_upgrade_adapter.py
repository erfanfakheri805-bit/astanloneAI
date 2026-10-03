"""
Tests for agent/code_change_self_upgrade_adapter.py - connects the
existing, already-validated code-correction result
(AgentLoop.apply_code_correction, Prompt 343) to the existing
Self-Upgrade pipeline (self_upgrade/upgrade_system.py's UpgradeSystem),
made available on the existing AgentLoop via
`AgentLoop.build_self_upgrade_input` (agent/agent_loop.py, Prompt 349).

Covers: a valid, successfully-applied change producing an ACCEPTED
Self-Upgrade input that clearly identifies itself as CODE_CHANGE and
preserves target_file/proposal/validation_result/change_result; an
invalid (never validated) proposal being REJECTED and never reaching
the Self-Upgrade pipeline; a failed/not-applied change being REJECTED
the same way; and target-file/change metadata being preserved
unchanged end to end. Also covers AgentLoop.build_self_upgrade_input
wiring, and that no input ever raises.

Run directly:
    python -m unittest tests.test_code_change_self_upgrade_adapter -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_change_self_upgrade_adapter import (
    STATUS_ACCEPTED,
    STATUS_REJECTED,
    ALL_SELF_UPGRADE_ADAPTER_STATUSES,
    UPGRADE_TYPE_CODE_CHANGE,
    build_self_upgrade_input_from_code_correction,
)
from agent.code_correction_proposal import STATUS_PROPOSED, STATUS_NOT_READY
from agent.code_error_analysis import ERROR_TYPE_NAME
from agent.code_correction_proposal_validation import (
    VALIDATION_STATUS_VALID,
    VALIDATION_STATUS_INVALID,
    VALIDATION_STATUS_NOT_READY,
)
from agent.code_correction_application import (
    STATUS_APPLIED,
    STATUS_NOT_READY as APPLICATION_STATUS_NOT_READY,
    STATUS_REJECTED as APPLICATION_STATUS_REJECTED,
    STATUS_ERROR as APPLICATION_STATUS_ERROR,
)

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


class TestValidAppliedChangeBecomesSelfUpgradeInput(unittest.TestCase):
    """Requirement: a validated and successfully applied change is
    converted into a Self-Upgrade input, clearly identified as
    CODE_CHANGE."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.proposal = _proposal(self.target_file)
        self.validation_result = _validation_result(self.target_file)
        self.application = _application(self.target_file)
        self.correction_result = _correction_result(
            self.proposal, self.validation_result, self.application,
        )
        self.result = build_self_upgrade_input_from_code_correction(self.correction_result)

    def test_status_is_accepted(self):
        self.assertEqual(self.result["status"], STATUS_ACCEPTED)

    def test_self_upgrade_input_is_present_and_shaped_for_propose_upgrade(self):
        upgrade_input = self.result["self_upgrade_input"]
        self.assertIsNotNone(upgrade_input)
        self.assertIn("name", upgrade_input)
        self.assertIn("description", upgrade_input)
        self.assertIn("payload", upgrade_input)

    def test_identifies_as_code_change(self):
        payload = self.result["self_upgrade_input"]["payload"]
        self.assertEqual(payload["change_type"], "CODE_CHANGE")
        self.assertEqual(payload["change_type"], UPGRADE_TYPE_CODE_CHANGE)

    def test_preserves_target_file(self):
        payload = self.result["self_upgrade_input"]["payload"]
        self.assertEqual(payload["target_file"], self.target_file)

    def test_preserves_original_proposal_unchanged(self):
        payload = self.result["self_upgrade_input"]["payload"]
        self.assertEqual(payload["proposal"], self.proposal)
        self.assertIs(payload["proposal"], self.proposal)

    def test_preserves_validation_result_unchanged(self):
        payload = self.result["self_upgrade_input"]["payload"]
        self.assertEqual(payload["validation_result"], self.validation_result)
        self.assertIs(payload["validation_result"], self.validation_result)

    def test_preserves_change_result_unchanged(self):
        payload = self.result["self_upgrade_input"]["payload"]
        self.assertEqual(payload["change_result"], self.application)
        self.assertIs(payload["change_result"], self.application)

    def test_payload_carries_name_and_description_for_sandbox(self):
        # self_upgrade.sandbox.Sandbox.REQUIRED_PAYLOAD_FIELDS requires
        # "name" and "description" inside the payload itself.
        payload = self.result["self_upgrade_input"]["payload"]
        self.assertTrue(payload.get("name"))
        self.assertTrue(payload.get("description"))


class TestInvalidProposalIsRejected(unittest.TestCase):
    """Requirement: an invalid or not-ready proposal must never enter
    the Self-Upgrade pipeline."""

    def test_invalid_validation_result_is_rejected(self):
        target_file = "/tmp/allowed/generated.py"
        proposal = _proposal(target_file)
        validation_result = _validation_result(
            target_file, status=VALIDATION_STATUS_INVALID, is_safe_to_apply=False,
            reason="The proposal does not include error information.",
        )
        application = _application(target_file, status=APPLICATION_STATUS_REJECTED, changed=False,
                                    error="The correction proposal was not validated as safe to apply.")
        correction_result = _correction_result(proposal, validation_result, application)

        result = build_self_upgrade_input_from_code_correction(correction_result)

        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIsNone(result["self_upgrade_input"])
        self.assertEqual(
            result["reason"], "The proposal does not include error information.",
        )

    def test_not_ready_proposal_validation_is_rejected(self):
        target_file = "/tmp/allowed/generated.py"
        proposal = _proposal(target_file, status=STATUS_NOT_READY)
        validation_result = _validation_result(
            target_file, status=VALIDATION_STATUS_NOT_READY, is_safe_to_apply=False,
            reason="The correction proposal is not ready for validation (status='NOT_READY').",
        )
        application = _application(target_file, status=APPLICATION_STATUS_REJECTED, changed=False)
        correction_result = _correction_result(proposal, validation_result, application)

        result = build_self_upgrade_input_from_code_correction(correction_result)

        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIsNone(result["self_upgrade_input"])


class TestFailedChangeIsRejected(unittest.TestCase):
    """Requirement: a valid proposal whose change was never actually,
    successfully applied must never enter the Self-Upgrade pipeline."""

    def test_not_ready_application_is_rejected(self):
        target_file = "/tmp/allowed/generated.py"
        proposal = _proposal(target_file)
        validation_result = _validation_result(target_file)
        application = _application(
            target_file, status=APPLICATION_STATUS_NOT_READY, changed=False,
            error="The correction could not be applied.",
        )
        correction_result = _correction_result(proposal, validation_result, application)

        result = build_self_upgrade_input_from_code_correction(correction_result)

        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIsNone(result["self_upgrade_input"])
        self.assertEqual(result["reason"], "The correction could not be applied.")

    def test_error_application_is_rejected(self):
        target_file = "/tmp/allowed/generated.py"
        proposal = _proposal(target_file)
        validation_result = _validation_result(target_file)
        application = _application(
            target_file, status=APPLICATION_STATUS_ERROR, changed=False, error="File does not exist.",
        )
        correction_result = _correction_result(proposal, validation_result, application)

        result = build_self_upgrade_input_from_code_correction(correction_result)

        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIsNone(result["self_upgrade_input"])

    def test_applied_but_unchanged_flag_is_rejected(self):
        # Defensive: status APPLIED with changed=False should never
        # happen from the real pipeline, but this adapter must still
        # never treat it as a success.
        target_file = "/tmp/allowed/generated.py"
        proposal = _proposal(target_file)
        validation_result = _validation_result(target_file)
        application = _application(target_file, status=STATUS_APPLIED, changed=False)
        correction_result = _correction_result(proposal, validation_result, application)

        result = build_self_upgrade_input_from_code_correction(correction_result)

        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIsNone(result["self_upgrade_input"])


class TestMetadataPreservation(unittest.TestCase):
    """Requirement: target file and change metadata are preserved,
    exactly and completely, end to end."""

    def test_distinct_target_files_are_each_preserved(self):
        for target_file in ("/tmp/allowed/a.py", "/tmp/allowed/nested/b.py"):
            proposal = _proposal(target_file)
            validation_result = _validation_result(target_file)
            application = _application(target_file)
            correction_result = _correction_result(proposal, validation_result, application)

            result = build_self_upgrade_input_from_code_correction(correction_result)

            payload = result["self_upgrade_input"]["payload"]
            self.assertEqual(payload["target_file"], target_file)
            self.assertIn(target_file, result["self_upgrade_input"]["name"])

    def test_proposal_and_change_result_metadata_fields_untouched(self):
        target_file = "/tmp/allowed/generated.py"
        proposal = _proposal(target_file)
        proposal["custom_field"] = "should survive untouched"
        validation_result = _validation_result(target_file)
        application = _application(target_file)
        application["custom_field"] = "also survives untouched"
        correction_result = _correction_result(proposal, validation_result, application)

        result = build_self_upgrade_input_from_code_correction(correction_result)

        payload = result["self_upgrade_input"]["payload"]
        self.assertEqual(payload["proposal"]["custom_field"], "should survive untouched")
        self.assertEqual(payload["change_result"]["custom_field"], "also survives untouched")


class TestNeverRaises(unittest.TestCase):
    def test_none_input(self):
        result = build_self_upgrade_input_from_code_correction(None)
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIsNone(result["self_upgrade_input"])

    def test_non_dict_input(self):
        result = build_self_upgrade_input_from_code_correction("not a correction result")
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIsNone(result["self_upgrade_input"])

    def test_missing_validation_result_key(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = {
            "proposal": _proposal(target_file),
            "application": _application(target_file),
        }
        result = build_self_upgrade_input_from_code_correction(correction_result)
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIsNone(result["self_upgrade_input"])

    def test_missing_application_key(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = {
            "proposal": _proposal(target_file),
            "validation_result": _validation_result(target_file),
        }
        result = build_self_upgrade_input_from_code_correction(correction_result)
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIsNone(result["self_upgrade_input"])


class TestAllSelfUpgradeAdapterStatuses(unittest.TestCase):
    def test_fixed_two_way_vocabulary(self):
        self.assertEqual(
            ALL_SELF_UPGRADE_ADAPTER_STATUSES, (STATUS_ACCEPTED, STATUS_REJECTED),
        )


class TestAgentLoopBuildSelfUpgradeInput(unittest.TestCase):
    """Requirement: make the adapter available on the existing
    AgentLoop, without creating a new Self-Upgrade system and without
    installing/activating anything automatically."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.loop = AgentLoop(goals, plans, controller)

    def test_accepts_valid_applied_change(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file), _validation_result(target_file), _application(target_file),
        )
        result = self.loop.build_self_upgrade_input(correction_result)
        self.assertEqual(result["status"], STATUS_ACCEPTED)
        self.assertEqual(
            result["self_upgrade_input"]["payload"]["change_type"], "CODE_CHANGE",
        )

    def test_rejects_failed_change(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file),
            _validation_result(target_file),
            _application(target_file, status=APPLICATION_STATUS_NOT_READY, changed=False),
        )
        result = self.loop.build_self_upgrade_input(correction_result)
        self.assertEqual(result["status"], STATUS_REJECTED)
        self.assertIsNone(result["self_upgrade_input"])

    def test_does_not_install_or_touch_self_upgrade_system(self):
        # AgentLoop.build_self_upgrade_input never constructs or calls
        # a real UpgradeSystem - it only returns the prepared input.
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file), _validation_result(target_file), _application(target_file),
        )
        result = self.loop.build_self_upgrade_input(correction_result)
        self.assertNotIn("upgrade", result)
        self.assertFalse(hasattr(self.loop, "upgrades"))


if __name__ == "__main__":
    unittest.main()
