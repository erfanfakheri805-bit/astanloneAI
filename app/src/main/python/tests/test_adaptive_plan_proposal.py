"""
Tests for AdaptivePlanProposal (planning/adaptive_plan_proposal.py) -
deterministic, read-only conversion of AdaptivePlanAnalyzer blockers
into a structured, never-applied proposal for improving a Plan.

Run directly:
    python -m unittest tests.test_adaptive_plan_proposal -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.plan import STATUS_COMPLETED, STATUS_FAILED, STATUS_BLOCKED, STATUS_IN_PROGRESS
from planning.goal_completion import GoalCompletionEvaluator
from planning.adaptive_plan_analyzer import AdaptivePlanAnalyzer
from planning.adaptive_plan_proposal import (
    AdaptivePlanProposal,
    ProposedChange,
    PlanProposal,
    ALL_PROPOSAL_STATUSES,
    ALL_CHANGE_TYPES,
    PROPOSAL_NO_CHANGE_NEEDED,
    PROPOSAL_CHANGE_RECOMMENDED,
    PROPOSAL_BLOCKED,
    PROPOSAL_UNKNOWN,
    CHANGE_MODIFY_STEP,
    CHANGE_PROVIDE_INPUT,
    CHANGE_PROVIDE_OUTPUT,
    CHANGE_REMOVE_DEPENDENCY,
    CHECK_STRUCTURE,
    CHECK_STATUS_VALID,
    CHECK_CHANGE_TYPE_VALID,
    CHECK_TARGET_STEP_VALID,
    CHECK_PROPOSED_DATA_SAFE,
    CHECK_CONFIDENCE_VALID,
)

from execution.execution_history import ExecutionHistory
from execution.execution_result import ExecutionResult
from execution.capability_handlers import CapabilityHandlerRegistry


class FakeCapabilitySystem:
    """Minimal stand-in for capabilities.capability_system.CapabilitySystem
    (same convention as tests/test_capability_handlers.py's own fake)."""

    def __init__(self, registered=None):
        self._registered = dict(registered) if registered else {}

    def all(self):
        return [
            {"name": name, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
            for name, enabled in self._registered.items()
        ]


class ProposalTestBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.evaluator = GoalCompletionEvaluator(self.goals, self.plans)
        self.analyzer = AdaptivePlanAnalyzer(self.goals, self.plans, self.evaluator)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)
        self.proposer = AdaptivePlanProposal(self.goals, self.plans, self.analyzer)

    def _add_step(self, description="Do the thing", **kwargs):
        return self.plans.add_step(self.plan.plan_id, description, **kwargs)


# --------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------
class ConstructionTests(unittest.TestCase):
    def test_requires_goal_manager(self):
        plans = PlanManager(GoalManager())
        with self.assertRaises(TypeError):
            AdaptivePlanProposal("nope", plans)

    def test_requires_plan_manager(self):
        goals = GoalManager()
        with self.assertRaises(TypeError):
            AdaptivePlanProposal(goals, "nope")

    def test_rejects_wrong_type_analyzer(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            AdaptivePlanProposal(goals, plans, analyzer="nope")

    def test_builds_own_analyzer_when_omitted(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        proposer = AdaptivePlanProposal(goals, plans)
        self.assertIsInstance(proposer._analyzer, AdaptivePlanAnalyzer)


# --------------------------------------------------------------------
# Controlled vocabularies / record classes
# --------------------------------------------------------------------
class VocabularyTests(unittest.TestCase):
    def test_proposal_statuses_are_fixed(self):
        self.assertEqual(
            set(ALL_PROPOSAL_STATUSES),
            {PROPOSAL_NO_CHANGE_NEEDED, PROPOSAL_CHANGE_RECOMMENDED, PROPOSAL_BLOCKED, PROPOSAL_UNKNOWN},
        )

    def test_change_types_include_all_required(self):
        for change_type in (
            "ADD_STEP", "MODIFY_STEP", "REMOVE_STEP", "ADD_DEPENDENCY", "REMOVE_DEPENDENCY",
            "ADD_CAPABILITY_REQUIREMENT", "REMOVE_CAPABILITY_REQUIREMENT",
            "PROVIDE_INPUT", "PROVIDE_OUTPUT", "REORDER_STEP",
        ):
            self.assertIn(change_type, ALL_CHANGE_TYPES)

    def test_proposed_change_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            ProposedChange("NOT_A_TYPE", "step-1", "reason", "blocker-1")

    def test_proposed_change_rejects_bad_confidence(self):
        with self.assertRaises(ValueError):
            ProposedChange(CHANGE_MODIFY_STEP, "step-1", "reason", "blocker-1", confidence=1.5)
        with self.assertRaises(TypeError):
            ProposedChange(CHANGE_MODIFY_STEP, "step-1", "reason", "blocker-1", confidence="high")

    def test_proposed_change_to_dict_shape(self):
        change = ProposedChange(
            CHANGE_MODIFY_STEP, "step-1", "reason", "blocker-1",
            proposed_data={"a": 1}, confidence=0.5,
        )
        self.assertEqual(
            set(change.to_dict().keys()),
            {"change_id", "change_type", "target_step_id", "reason", "source_blocker", "proposed_data", "confidence"},
        )

    def test_plan_proposal_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            PlanProposal("g-1", "p-1", "NOT_A_STATUS", "reason")

    def test_plan_proposal_to_dict_shape(self):
        proposal = PlanProposal("g-1", "p-1", PROPOSAL_NO_CHANGE_NEEDED, "reason")
        expected_keys = {
            "proposal_id", "goal_id", "plan_id", "status", "reason", "source_blockers",
            "proposed_changes", "affected_steps", "required_capabilities", "warnings", "created_at",
        }
        self.assertEqual(set(proposal.to_dict().keys()), expected_keys)


# --------------------------------------------------------------------
# Missing goal / plan / mismatch
# --------------------------------------------------------------------
class GuardTests(ProposalTestBase):
    def test_missing_goal_is_unknown(self):
        result = self.proposer.propose("goal-does-not-exist", self.plan.plan_id)
        self.assertEqual(result["status"], PROPOSAL_UNKNOWN)
        self.assertEqual(result["proposed_changes"], [])

    def test_missing_plan_is_unknown(self):
        result = self.proposer.propose(self.goal.goal_id, "plan-does-not-exist")
        self.assertEqual(result["status"], PROPOSAL_UNKNOWN)

    def test_goal_plan_mismatch_is_unknown(self):
        other_goal = self.goals.create_goal("Something else")
        result = self.proposer.propose(other_goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["status"], PROPOSAL_UNKNOWN)

    def test_result_shape_always_the_same_keys(self):
        expected_keys = {
            "proposal_id", "goal_id", "plan_id", "status", "reason", "source_blockers",
            "proposed_changes", "affected_steps", "required_capabilities", "warnings", "created_at",
        }
        result = self.proposer.propose("nope", "nope")
        self.assertEqual(set(result.keys()), expected_keys)


# --------------------------------------------------------------------
# Satisfied goal / no change needed
# --------------------------------------------------------------------
class NoChangeTests(ProposalTestBase):
    def test_satisfied_goal_is_no_change_needed(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)

        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["status"], PROPOSAL_NO_CHANGE_NEEDED)
        self.assertEqual(result["proposed_changes"], [])
        self.assertIn("satisfied", result["reason"].lower())

    def test_pending_plan_with_no_blockers_is_no_change_needed(self):
        self._add_step()  # left pending, nothing observably blocking it
        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["status"], PROPOSAL_NO_CHANGE_NEEDED)
        self.assertEqual(result["proposed_changes"], [])


# --------------------------------------------------------------------
# Missing capability / missing handler
# --------------------------------------------------------------------
class CapabilityProposalTests(ProposalTestBase):
    def test_missing_capability_produces_warning_not_a_change(self):
        self._add_step("Review the code", required_capabilities=["code_analysis"])
        capability_system = FakeCapabilitySystem()
        proposer = AdaptivePlanProposal(
            self.goals, self.plans, AdaptivePlanAnalyzer(
                self.goals, self.plans, self.evaluator, capability_system=capability_system,
            ),
        )
        result = proposer.propose(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["proposed_changes"], [])
        self.assertEqual(result["status"], PROPOSAL_BLOCKED)
        self.assertIn("code_analysis", result["required_capabilities"])
        self.assertTrue(any("capability" in w.lower() for w in result["warnings"]))

    def test_missing_handler_produces_warning_not_a_change(self):
        self._add_step("Review the code", required_capabilities=["code_analysis"])
        capability_system = FakeCapabilitySystem({"code_analysis": True})
        handlers = CapabilityHandlerRegistry()  # no handler registered
        analyzer = AdaptivePlanAnalyzer(
            self.goals, self.plans, self.evaluator,
            capability_system=capability_system, capability_handlers=handlers,
        )
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer)
        result = proposer.propose(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["proposed_changes"], [])
        self.assertEqual(result["status"], PROPOSAL_BLOCKED)
        self.assertTrue(any("handler" in w.lower() for w in result["warnings"]))


# --------------------------------------------------------------------
# Unresolved dependency / missing step dependency
# --------------------------------------------------------------------
class DependencyProposalTests(ProposalTestBase):
    def test_unresolved_dependency_produces_warning_not_a_change(self):
        first = self._add_step("Write the code")
        second = self._add_step("Review the code", dependencies=[first.step_id])
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)

        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        change_types = [c["change_type"] for c in result["proposed_changes"] if c["target_step_id"] == second.step_id]
        self.assertNotIn("ADD_DEPENDENCY", change_types)
        self.assertNotIn(CHANGE_REMOVE_DEPENDENCY, change_types)
        self.assertTrue(any("dependency" in w.lower() for w in result["warnings"]))

    def test_missing_step_dependency_produces_remove_dependency_change(self):
        step = self._add_step("Review the code", dependencies=["plan-999-step-1"])
        self.plans.refresh_step_status(self.plan.plan_id, step.step_id)

        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        remove_changes = [c for c in result["proposed_changes"] if c["change_type"] == CHANGE_REMOVE_DEPENDENCY]
        self.assertEqual(len(remove_changes), 1)
        self.assertEqual(remove_changes[0]["target_step_id"], step.step_id)
        self.assertEqual(remove_changes[0]["proposed_data"]["remove_dependency"], "plan-999-step-1")
        self.assertEqual(remove_changes[0]["confidence"], 1.0)
        self.assertEqual(result["status"], PROPOSAL_CHANGE_RECOMMENDED)


# --------------------------------------------------------------------
# Missing input / missing output
# --------------------------------------------------------------------
class DataFlowProposalTests(ProposalTestBase):
    def test_missing_input_produces_provide_input_change(self):
        first = self._add_step("Write the code")
        second = self._add_step("Review the code", dependencies=[first.step_id])
        first_obj = self.plans.get_step(self.plan.plan_id, first.step_id)
        first_obj.set_output({"diff": "..."})
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_COMPLETED)
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)
        self.plans.update_step_status(self.plan.plan_id, second.step_id, STATUS_IN_PROGRESS)

        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        provide_changes = [c for c in result["proposed_changes"] if c["change_type"] == CHANGE_PROVIDE_INPUT]
        self.assertEqual(len(provide_changes), 1)
        self.assertEqual(provide_changes[0]["target_step_id"], second.step_id)
        self.assertEqual(provide_changes[0]["proposed_data"]["candidate_source_steps"], [first.step_id])
        self.assertEqual(provide_changes[0]["confidence"], 0.9)  # exactly one completed dependency

    def test_missing_output_produces_provide_output_change(self):
        step = self._add_step("Write the report", expected_output="report.txt")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)

        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        provide_changes = [c for c in result["proposed_changes"] if c["change_type"] == CHANGE_PROVIDE_OUTPUT]
        self.assertEqual(len(provide_changes), 1)
        self.assertEqual(provide_changes[0]["target_step_id"], step.step_id)
        self.assertEqual(provide_changes[0]["proposed_data"]["expected_output"], "report.txt")
        self.assertEqual(provide_changes[0]["confidence"], 0.5)


# --------------------------------------------------------------------
# Failed step / blocked step
# --------------------------------------------------------------------
class StepStatusProposalTests(ProposalTestBase):
    def test_failed_step_without_execution_history_produces_low_confidence_modify(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)

        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        modify_changes = [c for c in result["proposed_changes"] if c["change_type"] == CHANGE_MODIFY_STEP]
        self.assertEqual(len(modify_changes), 1)
        self.assertEqual(modify_changes[0]["confidence"], 0.3)
        self.assertEqual(result["status"], PROPOSAL_CHANGE_RECOMMENDED)

    def test_failed_step_with_execution_history_produces_higher_confidence_modify(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)

        history = ExecutionHistory()
        exec_result = ExecutionResult(self.plan.plan_id, step.step_id)
        exec_result.mark_failed("capability threw an exception")
        history.record(exec_result)

        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans, self.evaluator, execution_history=history)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer)
        result = proposer.propose(self.goal.goal_id, self.plan.plan_id)
        modify_changes = [c for c in result["proposed_changes"] if c["change_type"] == CHANGE_MODIFY_STEP]
        self.assertEqual(len(modify_changes), 1)
        self.assertEqual(modify_changes[0]["confidence"], 0.7)
        self.assertIn("error_evidence", modify_changes[0]["proposed_data"])

    def test_blocked_step_with_specific_blocker_does_not_double_propose(self):
        first = self._add_step("Write the code")
        second = self._add_step("Review the code", dependencies=[first.step_id])
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)

        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        modify_changes = [c for c in result["proposed_changes"] if c["target_step_id"] == second.step_id]
        # BLOCKED_STEP is a summary blocker; the specific
        # UNRESOLVED_DEPENDENCY warning already covers it, so no
        # redundant MODIFY_STEP proposal should appear.
        self.assertEqual(modify_changes, [])


# --------------------------------------------------------------------
# Goal not satisfied
# --------------------------------------------------------------------
class GoalNotSatisfiedProposalTests(ProposalTestBase):
    def test_goal_not_satisfied_produces_warning_not_a_change(self):
        self._add_step()  # left pending
        self.plans.get_plan(self.plan.plan_id).status = STATUS_COMPLETED

        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        self.assertTrue(any("evidence" in w.lower() for w in result["warnings"]))


# --------------------------------------------------------------------
# Unknown blocker type (defensive fallback)
# --------------------------------------------------------------------
class UnknownBlockerFallbackTests(ProposalTestBase):
    def test_unrecognized_blocker_type_falls_back_to_warning(self):
        first = self._add_step("Write the code")
        second = self._add_step("Review the code", dependencies=[first.step_id])
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)

        analysis = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        fake_blocker = dict(analysis["blockers"][0])
        fake_blocker["type"] = "SOME_FUTURE_BLOCKER_TYPE"
        fake_blocker["blocker_id"] = "blocker-fake-1"

        change, warning = self.proposer._propose_for_blocker(
            fake_blocker, [fake_blocker], {}, {}, {},
        )
        self.assertIsNone(change)
        self.assertIsNotNone(warning)


# --------------------------------------------------------------------
# Multiple blockers / multiple proposed changes
# --------------------------------------------------------------------
class MultipleBlockerTests(ProposalTestBase):
    def test_multiple_blockers_produce_multiple_changes_and_warnings(self):
        failed = self._add_step("Write the code")
        self.plans.update_step_status(self.plan.plan_id, failed.step_id, STATUS_FAILED)

        report = self._add_step("Write the report", expected_output="report.txt")
        self.plans.update_step_status(self.plan.plan_id, report.step_id, STATUS_COMPLETED)

        blocked = self._add_step("Review the code", dependencies=["plan-999-step-1"])
        self.plans.refresh_step_status(self.plan.plan_id, blocked.step_id)

        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        self.assertGreaterEqual(len(result["proposed_changes"]), 3)
        change_types = {c["change_type"] for c in result["proposed_changes"]}
        self.assertIn(CHANGE_MODIFY_STEP, change_types)
        self.assertIn(CHANGE_PROVIDE_OUTPUT, change_types)
        self.assertIn(CHANGE_REMOVE_DEPENDENCY, change_types)
        self.assertEqual(result["status"], PROPOSAL_CHANGE_RECOMMENDED)
        self.assertEqual(len(result["source_blockers"]), len(set(result["source_blockers"])))
        self.assertIn(failed.step_id, result["affected_steps"])
        self.assertIn(report.step_id, result["affected_steps"])
        self.assertIn(blocked.step_id, result["affected_steps"])


# --------------------------------------------------------------------
# validate_proposal
# --------------------------------------------------------------------
class ValidateProposalTests(ProposalTestBase):
    def test_valid_proposal_passes(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)
        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        validation = self.proposer.validate_proposal(result)
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["failed_checks"], [])

    def test_valid_proposal_object_passes(self):
        proposal = PlanProposal(self.goal.goal_id, self.plan.plan_id, PROPOSAL_NO_CHANGE_NEEDED, "reason")
        validation = self.proposer.validate_proposal(proposal)
        self.assertTrue(validation["valid"])

    def test_not_a_dict_fails_structure(self):
        validation = self.proposer.validate_proposal("not a proposal")
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["failed_checks"][0]["check"], CHECK_STRUCTURE)

    def test_missing_keys_fail_structure(self):
        validation = self.proposer.validate_proposal({"status": PROPOSAL_NO_CHANGE_NEEDED})
        self.assertFalse(validation["valid"])
        self.assertTrue(any(f["check"] == CHECK_STRUCTURE for f in validation["failed_checks"]))

    def test_invalid_status_fails(self):
        proposal = PlanProposal(self.goal.goal_id, self.plan.plan_id, PROPOSAL_NO_CHANGE_NEEDED, "reason").to_dict()
        proposal["status"] = "NOT_A_REAL_STATUS"
        validation = self.proposer.validate_proposal(proposal)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(f["check"] == CHECK_STATUS_VALID for f in validation["failed_checks"]))

    def test_invalid_change_type_fails(self):
        step = self._add_step()
        proposal = PlanProposal(
            self.goal.goal_id, self.plan.plan_id, PROPOSAL_CHANGE_RECOMMENDED, "reason",
            proposed_changes=[ProposedChange(CHANGE_MODIFY_STEP, step.step_id, "r", "b-1")],
        ).to_dict()
        proposal["proposed_changes"][0]["change_type"] = "NOT_A_REAL_TYPE"
        validation = self.proposer.validate_proposal(proposal)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(f["check"] == CHECK_CHANGE_TYPE_VALID for f in validation["failed_checks"]))

    def test_invalid_target_step_fails(self):
        proposal = PlanProposal(
            self.goal.goal_id, self.plan.plan_id, PROPOSAL_CHANGE_RECOMMENDED, "reason",
            proposed_changes=[ProposedChange(CHANGE_MODIFY_STEP, "step-does-not-exist", "r", "b-1")],
        ).to_dict()
        validation = self.proposer.validate_proposal(proposal)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(f["check"] == CHECK_TARGET_STEP_VALID for f in validation["failed_checks"]))

    def test_valid_target_step_passes(self):
        step = self._add_step()
        proposal = PlanProposal(
            self.goal.goal_id, self.plan.plan_id, PROPOSAL_CHANGE_RECOMMENDED, "reason",
            proposed_changes=[ProposedChange(CHANGE_MODIFY_STEP, step.step_id, "r", "b-1")],
        ).to_dict()
        validation = self.proposer.validate_proposal(proposal)
        self.assertTrue(validation["valid"])

    def test_unsafe_proposed_data_fails(self):
        step = self._add_step()
        proposal = PlanProposal(
            self.goal.goal_id, self.plan.plan_id, PROPOSAL_CHANGE_RECOMMENDED, "reason",
            proposed_changes=[ProposedChange(CHANGE_MODIFY_STEP, step.step_id, "r", "b-1")],
        ).to_dict()
        proposal["proposed_changes"][0]["proposed_data"] = {"bad": object()}
        validation = self.proposer.validate_proposal(proposal)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(f["check"] == CHECK_PROPOSED_DATA_SAFE for f in validation["failed_checks"]))

    def test_invalid_confidence_fails(self):
        step = self._add_step()
        proposal = PlanProposal(
            self.goal.goal_id, self.plan.plan_id, PROPOSAL_CHANGE_RECOMMENDED, "reason",
            proposed_changes=[ProposedChange(CHANGE_MODIFY_STEP, step.step_id, "r", "b-1")],
        ).to_dict()
        proposal["proposed_changes"][0]["confidence"] = "very confident"
        validation = self.proposer.validate_proposal(proposal)
        self.assertFalse(validation["valid"])
        self.assertTrue(any(f["check"] == CHECK_CONFIDENCE_VALID for f in validation["failed_checks"]))

    def test_out_of_range_confidence_fails(self):
        step = self._add_step()
        proposal = PlanProposal(
            self.goal.goal_id, self.plan.plan_id, PROPOSAL_CHANGE_RECOMMENDED, "reason",
            proposed_changes=[ProposedChange(CHANGE_MODIFY_STEP, step.step_id, "r", "b-1")],
        ).to_dict()
        proposal["proposed_changes"][0]["confidence"] = 2.0
        validation = self.proposer.validate_proposal(proposal)
        self.assertFalse(validation["valid"])


# --------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------
class DeterminismTests(ProposalTestBase):
    def test_confidence_values_are_deterministic_across_calls(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)

        result_a = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        result_b = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        confidences_a = [c["confidence"] for c in result_a["proposed_changes"]]
        confidences_b = [c["confidence"] for c in result_b["proposed_changes"]]
        self.assertEqual(confidences_a, confidences_b)

    def test_missing_input_confidence_depends_on_dependency_count(self):
        first = self._add_step("Write the code")
        second = self._add_step("Also write code")
        third = self._add_step("Review", dependencies=[first.step_id, second.step_id])
        for s in (first, second):
            obj = self.plans.get_step(self.plan.plan_id, s.step_id)
            obj.set_output({"ok": True})
            self.plans.update_step_status(self.plan.plan_id, s.step_id, STATUS_COMPLETED)
        self.plans.refresh_step_status(self.plan.plan_id, third.step_id)
        self.plans.update_step_status(self.plan.plan_id, third.step_id, STATUS_IN_PROGRESS)

        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        provide_changes = [c for c in result["proposed_changes"] if c["change_type"] == CHANGE_PROVIDE_INPUT]
        self.assertEqual(len(provide_changes), 1)
        # Two completed dependencies -> ambiguous which to propagate -
        # lower, but still fixed/deterministic, confidence.
        self.assertEqual(provide_changes[0]["confidence"], 0.6)


# --------------------------------------------------------------------
# Read-only behavior
# --------------------------------------------------------------------
class ReadOnlyTests(ProposalTestBase):
    def test_propose_never_mutates_plan_or_steps(self):
        first = self._add_step("Write the code")
        second = self._add_step("Review the code", dependencies=[first.step_id])
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_FAILED)
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)

        before_plan = self.plans.describe_plan(self.plan.plan_id)
        before_goal = self.goals.describe_goal(self.goal.goal_id)

        self.proposer.propose(self.goal.goal_id, self.plan.plan_id)

        after_plan = self.plans.describe_plan(self.plan.plan_id)
        after_goal = self.goals.describe_goal(self.goal.goal_id)
        self.assertEqual(before_plan, after_plan)
        self.assertEqual(before_goal, after_goal)

    def test_propose_never_creates_new_plans_or_goals(self):
        self._add_step()
        goal_count_before = len(self.goals)
        plan_count_before = len(self.plans)
        self.proposer.propose(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(len(self.goals), goal_count_before)
        self.assertEqual(len(self.plans), plan_count_before)

    def test_propose_never_registers_capabilities(self):
        self._add_step("Review the code", required_capabilities=["code_analysis"])
        capability_system = FakeCapabilitySystem()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans, self.evaluator, capability_system=capability_system)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer)
        proposer.propose(self.goal.goal_id, self.plan.plan_id)
        # Still empty - nothing was registered as a side effect.
        self.assertEqual(capability_system.all(), [])

    def test_validate_proposal_is_read_only(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)
        result = self.proposer.propose(self.goal.goal_id, self.plan.plan_id)

        before_plan = self.plans.describe_plan(self.plan.plan_id)
        self.proposer.validate_proposal(result)
        after_plan = self.plans.describe_plan(self.plan.plan_id)
        self.assertEqual(before_plan, after_plan)


if __name__ == "__main__":
    unittest.main()
