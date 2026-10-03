"""
Tests for AdaptivePlanAnalyzer (planning/adaptive_plan_analyzer.py) -
deterministic, read-only analysis of why an existing Plan has not
satisfied its Goal, built entirely on GoalManager/PlanManager/
GoalCompletionEvaluator, with optional capability/execution-history
collaborators.

Run directly:
    python -m unittest tests.test_adaptive_plan_analyzer -v
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
from planning.plan import (
    STATUS_PENDING, STATUS_READY, STATUS_BLOCKED, STATUS_IN_PROGRESS,
    STATUS_COMPLETED, STATUS_FAILED,
)
from planning.goal_completion import GoalCompletionEvaluator
from planning.adaptive_plan_analyzer import (
    AdaptivePlanAnalyzer,
    Blocker,
    ANALYSIS_COMPLETE,
    ANALYSIS_INCOMPLETE,
    ANALYSIS_BLOCKED,
    ANALYSIS_FAILED,
    ANALYSIS_UNKNOWN,
    ALL_ANALYSIS_STATUSES,
    ALL_BLOCKER_TYPES,
    ALL_SEVERITIES,
    BLOCKER_MISSING_STEP,
    BLOCKER_FAILED_STEP,
    BLOCKER_BLOCKED_STEP,
    BLOCKER_MISSING_CAPABILITY,
    BLOCKER_UNAVAILABLE_CAPABILITY,
    BLOCKER_MISSING_HANDLER,
    BLOCKER_UNRESOLVED_DEPENDENCY,
    BLOCKER_MISSING_INPUT,
    BLOCKER_MISSING_OUTPUT,
    BLOCKER_EXECUTION_FAILURE,
    BLOCKER_GOAL_NOT_SATISFIED,
    BLOCKER_INVALID_REQUEST,
)

from execution.execution_history import ExecutionHistory
from execution.execution_result import ExecutionResult
from execution.execution_event_log import ExecutionEventLog
from execution.execution_event import (
    ExecutionEvent, EVENT_EXECUTION_FAILED, SEVERITY_ERROR,
)
from execution.capability_handlers import CapabilityHandlerRegistry


class FakeCapabilitySystem:
    """Minimal stand-in for capabilities.capability_system.CapabilitySystem
    - exposes only the read-only `.all()` registry lookup this project's
    own capability-aware code already uses (same convention already
    used by tests/test_capability_handlers.py's own FakeCapabilitySystem).
    """

    def __init__(self, registered=None):
        self._registered = dict(registered) if registered else {}

    def all(self):
        return [
            {"name": name, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
            for name, enabled in self._registered.items()
        ]


class AnalyzerTestBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.evaluator = GoalCompletionEvaluator(self.goals, self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)
        self.analyzer = AdaptivePlanAnalyzer(self.goals, self.plans, self.evaluator)

    def _add_step(self, description="Do the thing", **kwargs):
        return self.plans.add_step(self.plan.plan_id, description, **kwargs)


# --------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------
class ConstructionTests(unittest.TestCase):
    def test_requires_goal_manager(self):
        plans = PlanManager(GoalManager())
        with self.assertRaises(TypeError):
            AdaptivePlanAnalyzer("not a goal manager", plans)

    def test_requires_plan_manager(self):
        goals = GoalManager()
        with self.assertRaises(TypeError):
            AdaptivePlanAnalyzer(goals, "not a plan manager")

    def test_builds_own_evaluator_when_omitted(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        analyzer = AdaptivePlanAnalyzer(goals, plans)
        self.assertIsInstance(analyzer._evaluator, GoalCompletionEvaluator)

    def test_rejects_wrong_type_evaluator(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            AdaptivePlanAnalyzer(goals, plans, goal_completion_evaluator="nope")

    def test_rejects_wrong_type_capability_handlers(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            AdaptivePlanAnalyzer(goals, plans, capability_handlers="nope")

    def test_rejects_wrong_type_execution_history(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            AdaptivePlanAnalyzer(goals, plans, execution_history="nope")

    def test_rejects_wrong_type_event_log(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            AdaptivePlanAnalyzer(goals, plans, event_log="nope")


# --------------------------------------------------------------------
# Controlled vocabularies
# --------------------------------------------------------------------
class VocabularyTests(unittest.TestCase):
    def test_analysis_statuses_are_fixed(self):
        self.assertEqual(
            set(ALL_ANALYSIS_STATUSES),
            {ANALYSIS_COMPLETE, ANALYSIS_INCOMPLETE, ANALYSIS_BLOCKED, ANALYSIS_FAILED, ANALYSIS_UNKNOWN},
        )

    def test_blocker_types_are_fixed(self):
        self.assertEqual(
            set(ALL_BLOCKER_TYPES),
            {
                BLOCKER_MISSING_STEP, BLOCKER_FAILED_STEP, BLOCKER_BLOCKED_STEP,
                BLOCKER_MISSING_CAPABILITY, BLOCKER_UNAVAILABLE_CAPABILITY,
                BLOCKER_MISSING_HANDLER, BLOCKER_UNRESOLVED_DEPENDENCY,
                BLOCKER_MISSING_INPUT, BLOCKER_MISSING_OUTPUT,
                BLOCKER_EXECUTION_FAILURE, BLOCKER_GOAL_NOT_SATISFIED,
                BLOCKER_INVALID_REQUEST,
            },
        )

    def test_blocker_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            Blocker("blocker-1", "NOT_A_REAL_TYPE", "desc", source="x")

    def test_blocker_rejects_unknown_severity(self):
        with self.assertRaises(ValueError):
            Blocker("blocker-1", BLOCKER_FAILED_STEP, "desc", source="x", severity="extreme")

    def test_blocker_to_dict_shape(self):
        blocker = Blocker(
            "blocker-1", BLOCKER_FAILED_STEP, "desc", source="x", step_id="s-1",
            evidence=["e1"],
        )
        d = blocker.to_dict()
        self.assertEqual(
            set(d.keys()),
            {"blocker_id", "type", "description", "source", "step_id", "severity", "evidence"},
        )
        self.assertIn(d["severity"], ALL_SEVERITIES)


# --------------------------------------------------------------------
# Missing goal / missing plan / mismatch (requirements 1-3)
# --------------------------------------------------------------------
class GuardTests(AnalyzerTestBase):
    def test_missing_goal_is_unknown(self):
        result = self.analyzer.analyze("goal-does-not-exist", self.plan.plan_id)
        self.assertEqual(result["analysis_status"], ANALYSIS_UNKNOWN)
        self.assertEqual(result["blockers"], [])
        self.assertTrue(result["warnings"])

    def test_missing_plan_is_unknown(self):
        result = self.analyzer.analyze(self.goal.goal_id, "plan-does-not-exist")
        self.assertEqual(result["analysis_status"], ANALYSIS_UNKNOWN)
        self.assertEqual(result["blockers"], [])

    def test_goal_plan_mismatch_is_unknown(self):
        other_goal = self.goals.create_goal("Something else entirely")
        result = self.analyzer.analyze(other_goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["analysis_status"], ANALYSIS_UNKNOWN)

    def test_result_shape_always_the_same_keys(self):
        expected_keys = {
            "goal_id", "plan_id", "goal_status", "plan_status", "analysis_status",
            "blockers", "completed_steps", "incomplete_steps", "failed_steps",
            "blocked_steps", "missing_capabilities", "missing_handlers",
            "unresolved_dependencies", "missing_outputs", "evidence", "warnings",
        }
        result = self.analyzer.analyze("nope", "nope")
        self.assertEqual(set(result.keys()), expected_keys)


# --------------------------------------------------------------------
# Fully completed plan
# --------------------------------------------------------------------
class CompletedPlanTests(AnalyzerTestBase):
    def test_fully_completed_plan_is_complete_with_no_blockers(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)

        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["analysis_status"], ANALYSIS_COMPLETE)
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["completed_steps"], [step.step_id])
        self.assertEqual(result["incomplete_steps"], [])
        self.assertEqual(result["failed_steps"], [])
        self.assertEqual(result["blocked_steps"], [])


# --------------------------------------------------------------------
# Incomplete plan (remaining steps)
# --------------------------------------------------------------------
class IncompletePlanTests(AnalyzerTestBase):
    def test_pending_step_is_incomplete_not_a_blocker(self):
        step = self._add_step()
        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["analysis_status"], ANALYSIS_INCOMPLETE)
        self.assertEqual(result["incomplete_steps"], [step.step_id])
        # A merely-pending step (nothing observed preventing it) is not
        # itself a blocker - requirement "do not invent blockers".
        self.assertEqual(result["blockers"], [])


# --------------------------------------------------------------------
# Failed step
# --------------------------------------------------------------------
class FailedStepTests(AnalyzerTestBase):
    def test_failed_step_produces_failed_step_blocker(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)

        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["analysis_status"], ANALYSIS_FAILED)
        self.assertEqual(result["failed_steps"], [step.step_id])
        types = [b["type"] for b in result["blockers"]]
        self.assertIn(BLOCKER_FAILED_STEP, types)

    def test_execution_failure_blocker_uses_execution_history(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)

        history = ExecutionHistory()
        exec_result = ExecutionResult(self.plan.plan_id, step.step_id)
        exec_result.mark_failed("capability threw an exception")
        history.record(exec_result)

        analyzer = AdaptivePlanAnalyzer(
            self.goals, self.plans, self.evaluator, execution_history=history,
        )
        result = analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        types = [b["type"] for b in result["blockers"]]
        self.assertIn(BLOCKER_EXECUTION_FAILURE, types)
        exec_blocker = next(b for b in result["blockers"] if b["type"] == BLOCKER_EXECUTION_FAILURE)
        self.assertTrue(any("capability threw an exception" in e for e in exec_blocker["evidence"]))

    def test_execution_failure_blocker_includes_event_log_evidence(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)

        history = ExecutionHistory()
        exec_result = ExecutionResult(self.plan.plan_id, step.step_id)
        exec_result.mark_failed("boom")
        history.record(exec_result)

        event_log = ExecutionEventLog()
        event_log.record(ExecutionEvent(
            event_type=EVENT_EXECUTION_FAILED, plan_id=self.plan.plan_id,
            step_id=step.step_id, execution_id=exec_result.execution_id,
            message="Handler raised an exception.", severity=SEVERITY_ERROR,
        ))

        analyzer = AdaptivePlanAnalyzer(
            self.goals, self.plans, self.evaluator,
            execution_history=history, event_log=event_log,
        )
        result = analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        exec_blocker = next(b for b in result["blockers"] if b["type"] == BLOCKER_EXECUTION_FAILURE)
        self.assertTrue(any("Handler raised an exception." in e for e in exec_blocker["evidence"]))


# --------------------------------------------------------------------
# Blocked step / unresolved dependency / missing step
# --------------------------------------------------------------------
class BlockedStepTests(AnalyzerTestBase):
    def test_blocked_step_produces_blocked_step_blocker(self):
        first = self._add_step("Write the code")
        second = self._add_step("Review the code", dependencies=[first.step_id])
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)

        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["blocked_steps"], [second.step_id])
        types = [b["type"] for b in result["blockers"] if b["step_id"] == second.step_id]
        self.assertIn(BLOCKER_BLOCKED_STEP, types)
        self.assertIn(BLOCKER_UNRESOLVED_DEPENDENCY, types)

    def test_missing_step_dependency_is_flagged(self):
        step = self._add_step("Review the code", dependencies=["plan-999-step-1"])
        self.plans.refresh_step_status(self.plan.plan_id, step.step_id)

        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        types = [b["type"] for b in result["blockers"] if b["step_id"] == step.step_id]
        self.assertIn(BLOCKER_MISSING_STEP, types)
        entries = [
            e for e in result["unresolved_dependencies"]
            if e["step_id"] == step.step_id and e["reason"] == "missing_step"
        ]
        self.assertEqual(len(entries), 1)

    def test_analysis_status_is_blocked_when_nothing_else_can_progress(self):
        first = self._add_step("Write the code")
        second = self._add_step("Review the code", dependencies=[first.step_id])
        self.plans.update_step_status(self.plan.plan_id, second.step_id, STATUS_BLOCKED)
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_FAILED)
        # first FAILED (terminal, not "remaining"), second BLOCKED and
        # will never resolve since its only dependency failed.
        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        # A failed step anywhere makes the overall picture FAILED, not
        # BLOCKED - same priority order GoalCompletionEvaluator itself
        # already applies.
        self.assertEqual(result["analysis_status"], ANALYSIS_FAILED)


# --------------------------------------------------------------------
# Missing capability / unavailable capability / missing handler
# --------------------------------------------------------------------
class CapabilityTests(AnalyzerTestBase):
    def test_missing_capability_is_flagged(self):
        step = self._add_step("Review the code", required_capabilities=["code_analysis"])
        capability_system = FakeCapabilitySystem()  # nothing registered at all

        analyzer = AdaptivePlanAnalyzer(
            self.goals, self.plans, self.evaluator, capability_system=capability_system,
        )
        result = analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        types = [b["type"] for b in result["blockers"] if b["step_id"] == step.step_id]
        self.assertIn(BLOCKER_MISSING_CAPABILITY, types)
        self.assertIn("code_analysis", result["missing_capabilities"])

    def test_unavailable_capability_is_flagged(self):
        step = self._add_step("Review the code", required_capabilities=["code_analysis"])
        capability_system = FakeCapabilitySystem({"code_analysis": False})

        analyzer = AdaptivePlanAnalyzer(
            self.goals, self.plans, self.evaluator, capability_system=capability_system,
        )
        result = analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        types = [b["type"] for b in result["blockers"] if b["step_id"] == step.step_id]
        self.assertIn(BLOCKER_UNAVAILABLE_CAPABILITY, types)
        self.assertIn("code_analysis", result["missing_capabilities"])

    def test_missing_handler_is_flagged_when_capability_available(self):
        step = self._add_step("Review the code", required_capabilities=["code_analysis"])
        capability_system = FakeCapabilitySystem({"code_analysis": True})
        handlers = CapabilityHandlerRegistry()  # no handler registered

        analyzer = AdaptivePlanAnalyzer(
            self.goals, self.plans, self.evaluator,
            capability_system=capability_system, capability_handlers=handlers,
        )
        result = analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        types = [b["type"] for b in result["blockers"] if b["step_id"] == step.step_id]
        self.assertIn(BLOCKER_MISSING_HANDLER, types)
        self.assertIn("code_analysis", result["missing_handlers"])

    def test_ready_capability_and_handler_produces_no_capability_blockers(self):
        step = self._add_step("Review the code", required_capabilities=["code_analysis"])
        capability_system = FakeCapabilitySystem({"code_analysis": True})
        handlers = CapabilityHandlerRegistry()
        handlers.register("code_analysis", lambda s: "ok")

        analyzer = AdaptivePlanAnalyzer(
            self.goals, self.plans, self.evaluator,
            capability_system=capability_system, capability_handlers=handlers,
        )
        result = analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        types = [b["type"] for b in result["blockers"] if b["step_id"] == step.step_id]
        self.assertNotIn(BLOCKER_MISSING_CAPABILITY, types)
        self.assertNotIn(BLOCKER_UNAVAILABLE_CAPABILITY, types)
        self.assertNotIn(BLOCKER_MISSING_HANDLER, types)

    def test_no_capability_system_or_handlers_adds_warning_not_a_crash(self):
        self._add_step("Review the code", required_capabilities=["code_analysis"])
        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        self.assertTrue(any("capability" in w.lower() for w in result["warnings"]))


# --------------------------------------------------------------------
# Missing output / missing input
# --------------------------------------------------------------------
class DataFlowTests(AnalyzerTestBase):
    def test_missing_output_on_completed_step_is_flagged(self):
        step = self._add_step("Write the report", expected_output="report.txt")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)

        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        types = [b["type"] for b in result["blockers"] if b["step_id"] == step.step_id]
        self.assertIn(BLOCKER_MISSING_OUTPUT, types)
        self.assertEqual(result["missing_outputs"], [{"step_id": step.step_id, "expected_output": "report.txt"}])
        # A blocker was actually observed, so this is not COMPLETE
        # despite every step being COMPLETED.
        self.assertEqual(result["analysis_status"], ANALYSIS_INCOMPLETE)

    def test_completed_step_with_output_is_not_flagged(self):
        step = self._add_step("Write the report", expected_output="report.txt")
        self.plans.set_step_input(self.plan.plan_id, step.step_id, {"noop": True})
        step_obj = self.plans.get_step(self.plan.plan_id, step.step_id)
        step_obj.set_output({"path": "report.txt"})
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)

        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["missing_outputs"], [])
        self.assertEqual(result["analysis_status"], ANALYSIS_COMPLETE)

    def test_missing_input_when_dependency_completed_but_never_propagated(self):
        first = self._add_step("Write the code")
        second = self._add_step("Review the code", dependencies=[first.step_id])
        first_obj = self.plans.get_step(self.plan.plan_id, first.step_id)
        first_obj.set_output({"diff": "..."})
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_COMPLETED)
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)
        self.plans.update_step_status(self.plan.plan_id, second.step_id, STATUS_IN_PROGRESS)

        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        types = [b["type"] for b in result["blockers"] if b["step_id"] == second.step_id]
        self.assertIn(BLOCKER_MISSING_INPUT, types)

    def test_propagated_input_is_not_flagged_as_missing(self):
        first = self._add_step("Write the code")
        second = self._add_step("Review the code", dependencies=[first.step_id])
        first_obj = self.plans.get_step(self.plan.plan_id, first.step_id)
        first_obj.set_output({"diff": "..."})
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_COMPLETED)
        self.plans.propagate_step_output(self.plan.plan_id, first.step_id, second.step_id)
        self.plans.update_step_status(self.plan.plan_id, second.step_id, STATUS_IN_PROGRESS)

        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        types = [b["type"] for b in result["blockers"] if b["step_id"] == second.step_id]
        self.assertNotIn(BLOCKER_MISSING_INPUT, types)


# --------------------------------------------------------------------
# Plan completed but goal unsatisfied
# --------------------------------------------------------------------
class PlanCompletedGoalUnsatisfiedTests(AnalyzerTestBase):
    def test_plan_marked_completed_with_incomplete_steps_is_flagged(self):
        step = self._add_step()  # left PENDING
        self.plans.get_plan(self.plan.plan_id).status = STATUS_COMPLETED

        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        types = [b["type"] for b in result["blockers"]]
        self.assertIn(BLOCKER_GOAL_NOT_SATISFIED, types)
        blocker = next(b for b in result["blockers"] if b["type"] == BLOCKER_GOAL_NOT_SATISFIED)
        self.assertIsNone(blocker["step_id"])
        self.assertEqual(result["plan_status"], STATUS_COMPLETED)


# --------------------------------------------------------------------
# analyze_plan (goal-independent)
# --------------------------------------------------------------------
class AnalyzePlanTests(AnalyzerTestBase):
    def test_analyze_plan_missing_plan_is_unknown(self):
        result = self.analyzer.analyze_plan("plan-does-not-exist")
        self.assertEqual(result["analysis_status"], ANALYSIS_UNKNOWN)
        self.assertIsNone(result["goal_id"])

    def test_analyze_plan_uses_plans_own_goal_id(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)
        result = self.analyzer.analyze_plan(self.plan.plan_id)
        self.assertEqual(result["goal_id"], self.goal.goal_id)
        self.assertEqual(result["analysis_status"], ANALYSIS_FAILED)

    def test_analyze_plan_matches_analyze_for_same_plan(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)
        via_goal = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        via_plan = self.analyzer.analyze_plan(self.plan.plan_id)
        self.assertEqual(via_goal["analysis_status"], via_plan["analysis_status"])
        self.assertEqual(via_goal["completed_steps"], via_plan["completed_steps"])


# --------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------
class DeterminismTests(AnalyzerTestBase):
    def test_repeated_calls_return_identical_results(self):
        first = self._add_step("Write the code")
        second = self._add_step(
            "Review the code", dependencies=[first.step_id],
            required_capabilities=["code_analysis"],
        )
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)

        result_a = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        result_b = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result_a, result_b)

    def test_blocker_ids_stable_across_calls(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)
        ids_a = [b["blocker_id"] for b in self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)["blockers"]]
        ids_b = [b["blocker_id"] for b in self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)["blockers"]]
        self.assertEqual(ids_a, ids_b)


# --------------------------------------------------------------------
# Read-only behavior
# --------------------------------------------------------------------
class ReadOnlyTests(AnalyzerTestBase):
    def test_analyze_never_mutates_plan_or_steps(self):
        first = self._add_step("Write the code")
        second = self._add_step("Review the code", dependencies=[first.step_id])
        self.plans.update_step_status(self.plan.plan_id, first.step_id, STATUS_FAILED)
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)

        before_plan = self.plans.describe_plan(self.plan.plan_id)
        before_goal = self.goals.describe_goal(self.goal.goal_id)

        self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)

        after_plan = self.plans.describe_plan(self.plan.plan_id)
        after_goal = self.goals.describe_goal(self.goal.goal_id)
        self.assertEqual(before_plan, after_plan)
        self.assertEqual(before_goal, after_goal)

    def test_analyze_never_creates_new_plans_or_goals(self):
        self._add_step()
        goal_count_before = len(self.goals)
        plan_count_before = len(self.plans)
        self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(len(self.goals), goal_count_before)
        self.assertEqual(len(self.plans), plan_count_before)


# --------------------------------------------------------------------
# Evidence correctness
# --------------------------------------------------------------------
class EvidenceTests(AnalyzerTestBase):
    def test_failed_step_blocker_evidence_references_actual_status(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)
        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        blocker = next(b for b in result["blockers"] if b["type"] == BLOCKER_FAILED_STEP)
        self.assertTrue(any("FAILED" in e for e in blocker["evidence"]))

    def test_unresolved_dependency_evidence_names_actual_dependency_status(self):
        first = self._add_step("Write the code")
        second = self._add_step("Review the code", dependencies=[first.step_id])
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)
        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        blocker = next(b for b in result["blockers"] if b["type"] == BLOCKER_UNRESOLVED_DEPENDENCY)
        self.assertTrue(any(STATUS_PENDING in e for e in blocker["evidence"]))

    def test_evidence_and_warnings_include_evaluator_output(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_COMPLETED)
        evaluation = self.evaluator.evaluate(self.goal.goal_id, self.plan.plan_id)
        result = self.analyzer.analyze(self.goal.goal_id, self.plan.plan_id)
        for line in evaluation["evidence"]:
            self.assertIn(line, result["evidence"])


if __name__ == "__main__":
    unittest.main()
