"""
Tests for ProposalPatternAnalyzer (planning/proposal_pattern_analyzer.py)
- simple statistics over already-successful ProposalHistory records.

Run directly:
    python -m unittest tests.test_proposal_pattern_analyzer -v
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
from planning.proposal_pattern_analyzer import ProposalPatternAnalyzer


def _make_plan():
    step_1 = PlanStep(step_id="plan-1-step-1", description="Step 1", status=STATUS_PENDING)
    step_2 = PlanStep(step_id="plan-1-step-2", description="Step 2", status=STATUS_PENDING)
    return Plan("plan-1", "goal-1", steps=[step_1, step_2])


class TestProposalPatternAnalyzer(unittest.TestCase):
    def setUp(self):
        self.history = ProposalHistory()
        self.applier = ProposalApplier()
        self.analyzer = ProposalPatternAnalyzer()

    def _apply_and_record(self, plan, proposal_id, target_step_id, change_type, proposed_data,
                           source_blocker="blocker-1"):
        change = ProposedChange(
            change_type, target_step_id,
            reason="test change", source_blocker=source_blocker,
            proposed_data=proposed_data, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)
        self.history.record(proposal_id, change_type, target_step_id, result)
        return result

    def test_empty_history(self):
        stats = self.analyzer.analyze(self.history)

        self.assertEqual(stats["total_successful_changes"], 0)
        self.assertEqual(stats["by_change_type"], {})
        self.assertEqual(stats["by_target_step_id"], {})

    def test_one_recorded_change(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )

        stats = self.analyzer.analyze(self.history)

        self.assertEqual(stats["total_successful_changes"], 1)
        self.assertEqual(stats["by_change_type"], {CHANGE_ADD_CAPABILITY_REQUIREMENT: 1})
        self.assertEqual(stats["by_target_step_id"], {"plan-1-step-1": 1})

    def test_multiple_change_types(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )
        self._apply_and_record(
            plan, "proposal-2", "plan-1-step-2", CHANGE_PROVIDE_INPUT,
            {"input_data": {"x": 1}},
        )

        stats = self.analyzer.analyze(self.history)

        self.assertEqual(stats["total_successful_changes"], 2)
        self.assertEqual(
            stats["by_change_type"],
            {CHANGE_ADD_CAPABILITY_REQUIREMENT: 1, CHANGE_PROVIDE_INPUT: 1},
        )
        self.assertEqual(
            stats["by_target_step_id"],
            {"plan-1-step-1": 1, "plan-1-step-2": 1},
        )

    def test_multiple_changes_on_same_step(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )
        self._apply_and_record(
            plan, "proposal-2", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_b"},
        )
        self._apply_and_record(
            plan, "proposal-3", "plan-1-step-1", CHANGE_PROVIDE_INPUT,
            {"input_data": {"x": 1}},
        )

        stats = self.analyzer.analyze(self.history)

        self.assertEqual(stats["total_successful_changes"], 3)
        self.assertEqual(
            stats["by_change_type"],
            {CHANGE_ADD_CAPABILITY_REQUIREMENT: 2, CHANGE_PROVIDE_INPUT: 1},
        )
        self.assertEqual(stats["by_target_step_id"], {"plan-1-step-1": 3})

    def test_failed_changes_are_excluded_from_statistics(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )
        # This targets a step that does not exist, so ProposalApplier
        # rejects it and ProposalHistory.record stores nothing for it.
        self._apply_and_record(
            plan, "proposal-2", "no-such-step", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_b"},
        )

        stats = self.analyzer.analyze(self.history)

        self.assertEqual(stats["total_successful_changes"], 1)
        self.assertEqual(stats["by_change_type"], {CHANGE_ADD_CAPABILITY_REQUIREMENT: 1})
        self.assertEqual(stats["by_target_step_id"], {"plan-1-step-1": 1})


class TestMostFrequentChangeType(unittest.TestCase):
    def setUp(self):
        self.history = ProposalHistory()
        self.applier = ProposalApplier()
        self.analyzer = ProposalPatternAnalyzer()

    def _apply_and_record(self, plan, proposal_id, target_step_id, change_type, proposed_data,
                           source_blocker="blocker-1"):
        change = ProposedChange(
            change_type, target_step_id,
            reason="test change", source_blocker=source_blocker,
            proposed_data=proposed_data, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)
        self.history.record(proposal_id, change_type, target_step_id, result)
        return result

    def test_empty_history_returns_none(self):
        self.assertIsNone(self.analyzer.most_frequent_change_type(self.history))

    def test_one_change_type(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )

        result = self.analyzer.most_frequent_change_type(self.history)

        self.assertEqual(result, CHANGE_ADD_CAPABILITY_REQUIREMENT)

    def test_multiple_change_types(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_PROVIDE_INPUT,
            {"input_data": {"x": 1}},
        )
        self._apply_and_record(
            plan, "proposal-2", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )
        self._apply_and_record(
            plan, "proposal-3", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_b"},
        )

        result = self.analyzer.most_frequent_change_type(self.history)

        self.assertEqual(result, CHANGE_ADD_CAPABILITY_REQUIREMENT)

    def test_deterministic_result_when_counts_are_equal(self):
        plan = _make_plan()
        # CHANGE_PROVIDE_INPUT is recorded first, so it should win the
        # tie against CHANGE_ADD_CAPABILITY_REQUIREMENT (also count 1)
        # recorded second.
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_PROVIDE_INPUT,
            {"input_data": {"x": 1}},
        )
        self._apply_and_record(
            plan, "proposal-2", "plan-1-step-2", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )

        result = self.analyzer.most_frequent_change_type(self.history)

        self.assertEqual(result, CHANGE_PROVIDE_INPUT)


class TestGetChangeTypeCounts(unittest.TestCase):
    def setUp(self):
        self.history = ProposalHistory()
        self.applier = ProposalApplier()
        self.analyzer = ProposalPatternAnalyzer()

    def _apply_and_record(self, plan, proposal_id, target_step_id, change_type, proposed_data,
                           source_blocker="blocker-1"):
        change = ProposedChange(
            change_type, target_step_id,
            reason="test change", source_blocker=source_blocker,
            proposed_data=proposed_data, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)
        self.history.record(proposal_id, change_type, target_step_id, result)
        return result

    def test_empty_history(self):
        self.assertEqual(self.analyzer.get_change_type_counts(self.history), {})

    def test_one_change_type(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )

        counts = self.analyzer.get_change_type_counts(self.history)

        self.assertEqual(counts, {CHANGE_ADD_CAPABILITY_REQUIREMENT: 1})

    def test_multiple_change_types(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )
        self._apply_and_record(
            plan, "proposal-2", "plan-1-step-2", CHANGE_PROVIDE_INPUT,
            {"input_data": {"x": 1}},
        )

        counts = self.analyzer.get_change_type_counts(self.history)

        self.assertEqual(
            counts,
            {CHANGE_ADD_CAPABILITY_REQUIREMENT: 1, CHANGE_PROVIDE_INPUT: 1},
        )

    def test_repeated_changes_of_the_same_type(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )
        self._apply_and_record(
            plan, "proposal-2", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_b"},
        )
        self._apply_and_record(
            plan, "proposal-3", "plan-1-step-2", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_c"},
        )

        counts = self.analyzer.get_change_type_counts(self.history)

        self.assertEqual(counts, {CHANGE_ADD_CAPABILITY_REQUIREMENT: 3})


class TestGetStepChangeCounts(unittest.TestCase):
    def setUp(self):
        self.history = ProposalHistory()
        self.applier = ProposalApplier()
        self.analyzer = ProposalPatternAnalyzer()

    def _apply_and_record(self, plan, proposal_id, target_step_id, change_type, proposed_data,
                           source_blocker="blocker-1"):
        change = ProposedChange(
            change_type, target_step_id,
            reason="test change", source_blocker=source_blocker,
            proposed_data=proposed_data, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)
        self.history.record(proposal_id, change_type, target_step_id, result)
        return result

    def test_step_with_no_history(self):
        counts = self.analyzer.get_step_change_counts(self.history, "plan-1-step-1")

        self.assertEqual(counts, {})

    def test_one_change_for_a_step(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )

        counts = self.analyzer.get_step_change_counts(self.history, "plan-1-step-1")

        self.assertEqual(counts, {CHANGE_ADD_CAPABILITY_REQUIREMENT: 1})

    def test_multiple_change_types_for_one_step(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )
        self._apply_and_record(
            plan, "proposal-2", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_b"},
        )
        self._apply_and_record(
            plan, "proposal-3", "plan-1-step-1", CHANGE_PROVIDE_INPUT,
            {"input_data": {"x": 1}},
        )

        counts = self.analyzer.get_step_change_counts(self.history, "plan-1-step-1")

        self.assertEqual(
            counts,
            {CHANGE_ADD_CAPABILITY_REQUIREMENT: 2, CHANGE_PROVIDE_INPUT: 1},
        )

    def test_changes_belonging_to_another_step_are_ignored(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )
        self._apply_and_record(
            plan, "proposal-2", "plan-1-step-2", CHANGE_PROVIDE_INPUT,
            {"input_data": {"x": 1}},
        )

        counts = self.analyzer.get_step_change_counts(self.history, "plan-1-step-1")

        self.assertEqual(counts, {CHANGE_ADD_CAPABILITY_REQUIREMENT: 1})


class TestGetSummary(unittest.TestCase):
    def setUp(self):
        self.history = ProposalHistory()
        self.applier = ProposalApplier()
        self.analyzer = ProposalPatternAnalyzer()

    def _apply_and_record(self, plan, proposal_id, target_step_id, change_type, proposed_data,
                           source_blocker="blocker-1"):
        change = ProposedChange(
            change_type, target_step_id,
            reason="test change", source_blocker=source_blocker,
            proposed_data=proposed_data, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)
        self.history.record(proposal_id, change_type, target_step_id, result)
        return result

    def test_empty_history(self):
        summary = self.analyzer.get_summary(self.history)

        self.assertEqual(
            summary,
            {
                "total_successful_changes": 0,
                "change_type_counts": {},
                "most_frequent_change_type": None,
            },
        )

    def test_one_successful_change(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )

        summary = self.analyzer.get_summary(self.history)

        self.assertEqual(
            summary,
            {
                "total_successful_changes": 1,
                "change_type_counts": {CHANGE_ADD_CAPABILITY_REQUIREMENT: 1},
                "most_frequent_change_type": CHANGE_ADD_CAPABILITY_REQUIREMENT,
            },
        )

    def test_multiple_change_types(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )
        self._apply_and_record(
            plan, "proposal-2", "plan-1-step-2", CHANGE_PROVIDE_INPUT,
            {"input_data": {"x": 1}},
        )
        self._apply_and_record(
            plan, "proposal-3", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_b"},
        )

        summary = self.analyzer.get_summary(self.history)

        self.assertEqual(
            summary,
            {
                "total_successful_changes": 3,
                "change_type_counts": {
                    CHANGE_ADD_CAPABILITY_REQUIREMENT: 2,
                    CHANGE_PROVIDE_INPUT: 1,
                },
                "most_frequent_change_type": CHANGE_ADD_CAPABILITY_REQUIREMENT,
            },
        )

    def test_repeated_change_type(self):
        plan = _make_plan()
        self._apply_and_record(
            plan, "proposal-1", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_a"},
        )
        self._apply_and_record(
            plan, "proposal-2", "plan-1-step-1", CHANGE_ADD_CAPABILITY_REQUIREMENT,
            {"capability": "cap_b"},
        )

        summary = self.analyzer.get_summary(self.history)

        self.assertEqual(
            summary,
            {
                "total_successful_changes": 2,
                "change_type_counts": {CHANGE_ADD_CAPABILITY_REQUIREMENT: 2},
                "most_frequent_change_type": CHANGE_ADD_CAPABILITY_REQUIREMENT,
            },
        )


if __name__ == "__main__":
    unittest.main()
