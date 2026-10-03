"""
Tests for ProposalHistory (planning/proposal_history.py) - recording
and retrieving already-applied ProposalApplier results.

Run directly:
    python -m unittest tests.test_proposal_history -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planning.plan import Plan, PlanStep, STATUS_PENDING
from planning.adaptive_plan_proposal import (
    ProposedChange,
    CHANGE_ADD_CAPABILITY_REQUIREMENT,
    CHANGE_PROVIDE_INPUT,
)
from planning.proposal_applier import ProposalApplier
from planning.proposal_history import ProposalHistory


def _make_plan():
    step = PlanStep(
        step_id="plan-1-step-1",
        description="Do the thing",
        status=STATUS_PENDING,
    )
    return Plan("plan-1", "goal-1", steps=[step])


class TestProposalHistory(unittest.TestCase):
    def setUp(self):
        self.history = ProposalHistory()
        self.applier = ProposalApplier()

    def test_record_and_retrieve_a_change(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="needs it", source_blocker="blocker-1",
            proposed_data={"capability": "new_cap"}, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)

        recorded = self.history.record(
            "proposal-1", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result,
        )

        self.assertIsNotNone(recorded)
        self.assertEqual(recorded["proposal_id"], "proposal-1")
        self.assertEqual(recorded["change_type"], CHANGE_ADD_CAPABILITY_REQUIREMENT)
        self.assertEqual(recorded["target_step_id"], "plan-1-step-1")
        self.assertEqual(recorded["result"], result)
        self.assertIn("timestamp", recorded)
        self.assertIsInstance(recorded["timestamp"], str)

        all_records = self.history.get_all()
        self.assertEqual(len(all_records), 1)
        self.assertEqual(all_records[0]["proposal_id"], "proposal-1")

    def test_filter_by_proposal_id(self):
        plan = _make_plan()
        change_1 = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="needs it", source_blocker="blocker-1",
            proposed_data={"capability": "cap_a"}, confidence=0.9,
        )
        result_1 = self.applier.apply_change(plan, change_1)
        self.history.record("proposal-1", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result_1)

        change_2 = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="needs it too", source_blocker="blocker-2",
            proposed_data={"capability": "cap_b"}, confidence=0.9,
        )
        result_2 = self.applier.apply_change(plan, change_2)
        self.history.record("proposal-2", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result_2)

        proposal_1_records = self.history.get_for_proposal("proposal-1")
        proposal_2_records = self.history.get_for_proposal("proposal-2")
        unknown_records = self.history.get_for_proposal("no-such-proposal")

        self.assertEqual(len(proposal_1_records), 1)
        self.assertEqual(proposal_1_records[0]["result"]["capability"], "cap_a")
        self.assertEqual(len(proposal_2_records), 1)
        self.assertEqual(proposal_2_records[0]["result"]["capability"], "cap_b")
        self.assertEqual(unknown_records, [])
        self.assertEqual(len(self.history.get_all()), 2)

    def test_clear_history(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="needs it", source_blocker="blocker-1",
            proposed_data={"capability": "new_cap"}, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)
        self.history.record("proposal-1", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result)
        self.assertEqual(len(self.history.get_all()), 1)

        self.history.clear()

        self.assertEqual(self.history.get_all(), [])
        self.assertEqual(self.history.get_for_proposal("proposal-1"), [])
        self.assertEqual(len(self.history), 0)

    def test_failed_changes_are_not_recorded(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "no-such-step",
            reason="unknown target", source_blocker="blocker-1",
            proposed_data={"capability": "new_cap"}, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)
        self.assertFalse(result["success"])

        recorded = self.history.record(
            "proposal-1", CHANGE_ADD_CAPABILITY_REQUIREMENT, "no-such-step", result,
        )

        self.assertIsNone(recorded)
        self.assertEqual(self.history.get_all(), [])
        self.assertEqual(self.history.get_for_proposal("proposal-1"), [])

    def test_returned_records_are_copies(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="needs it", source_blocker="blocker-1",
            proposed_data={"capability": "new_cap"}, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)
        self.history.record("proposal-1", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result)

        first_read = self.history.get_all()
        first_read[0]["proposal_id"] = "tampered"
        first_read[0]["result"]["capability"] = "tampered"

        second_read = self.history.get_all()
        self.assertEqual(second_read[0]["proposal_id"], "proposal-1")
        self.assertEqual(second_read[0]["result"]["capability"], "new_cap")

    def test_get_latest_for_step_no_change_returns_none(self):
        self.assertIsNone(self.history.get_latest_for_step("plan-1-step-1"))

    def test_get_latest_for_step_one_change_returns_that_record(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="needs it", source_blocker="blocker-1",
            proposed_data={"capability": "cap_a"}, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)
        self.history.record("proposal-1", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result)

        latest = self.history.get_latest_for_step("plan-1-step-1")

        self.assertIsNotNone(latest)
        self.assertEqual(latest["proposal_id"], "proposal-1")
        self.assertEqual(latest["result"]["capability"], "cap_a")

    def test_get_latest_for_step_multiple_changes_returns_latest(self):
        plan = _make_plan()
        change_1 = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="first", source_blocker="blocker-1",
            proposed_data={"capability": "cap_a"}, confidence=0.9,
        )
        result_1 = self.applier.apply_change(plan, change_1)
        self.history.record("proposal-1", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result_1)

        change_2 = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="second", source_blocker="blocker-2",
            proposed_data={"capability": "cap_b"}, confidence=0.9,
        )
        result_2 = self.applier.apply_change(plan, change_2)
        self.history.record("proposal-2", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result_2)

        latest = self.history.get_latest_for_step("plan-1-step-1")

        self.assertEqual(latest["proposal_id"], "proposal-2")
        self.assertEqual(latest["result"]["capability"], "cap_b")

    def test_get_latest_for_step_ignores_other_steps(self):
        step_1 = PlanStep(step_id="plan-1-step-1", description="Step 1", status=STATUS_PENDING)
        step_2 = PlanStep(step_id="plan-1-step-2", description="Step 2", status=STATUS_PENDING)
        plan = Plan("plan-1", "goal-1", steps=[step_1, step_2])

        change_1 = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="for step 1", source_blocker="blocker-1",
            proposed_data={"capability": "cap_a"}, confidence=0.9,
        )
        result_1 = self.applier.apply_change(plan, change_1)
        self.history.record("proposal-1", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result_1)

        change_2 = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-2",
            reason="for step 2, recorded after step 1's change", source_blocker="blocker-2",
            proposed_data={"capability": "cap_b"}, confidence=0.9,
        )
        result_2 = self.applier.apply_change(plan, change_2)
        self.history.record("proposal-2", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-2", result_2)

        latest_for_step_1 = self.history.get_latest_for_step("plan-1-step-1")

        self.assertEqual(latest_for_step_1["proposal_id"], "proposal-1")
        self.assertEqual(latest_for_step_1["result"]["capability"], "cap_a")

    def test_count_for_proposal_empty_history_returns_zero(self):
        self.assertEqual(self.history.count_for_proposal("proposal-1"), 0)

    def test_count_for_proposal_one_recorded_change_returns_one(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="needs it", source_blocker="blocker-1",
            proposed_data={"capability": "cap_a"}, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)
        self.history.record("proposal-1", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result)

        self.assertEqual(self.history.count_for_proposal("proposal-1"), 1)

    def test_count_for_proposal_multiple_changes_returns_correct_count(self):
        plan = _make_plan()
        change_1 = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="first", source_blocker="blocker-1",
            proposed_data={"capability": "cap_a"}, confidence=0.9,
        )
        result_1 = self.applier.apply_change(plan, change_1)
        self.history.record("proposal-1", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result_1)

        change_2 = ProposedChange(
            CHANGE_PROVIDE_INPUT, "plan-1-step-1",
            reason="second", source_blocker="blocker-2",
            proposed_data={"input_data": {"x": 1}}, confidence=0.9,
        )
        result_2 = self.applier.apply_change(plan, change_2)
        self.history.record("proposal-1", CHANGE_PROVIDE_INPUT, "plan-1-step-1", result_2)

        self.assertEqual(self.history.count_for_proposal("proposal-1"), 2)

    def test_count_for_proposal_ignores_other_proposals(self):
        plan = _make_plan()
        change_1 = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="for proposal-1", source_blocker="blocker-1",
            proposed_data={"capability": "cap_a"}, confidence=0.9,
        )
        result_1 = self.applier.apply_change(plan, change_1)
        self.history.record("proposal-1", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result_1)

        change_2 = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="for proposal-2", source_blocker="blocker-2",
            proposed_data={"capability": "cap_b"}, confidence=0.9,
        )
        result_2 = self.applier.apply_change(plan, change_2)
        self.history.record("proposal-2", CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1", result_2)

        self.assertEqual(self.history.count_for_proposal("proposal-1"), 1)


if __name__ == "__main__":
    unittest.main()
