"""
Tests for AgentLoop (agent/agent_loop.py) - a small, deterministic
coordinator of Goal evaluation and existing Plan execution, built
entirely on the existing GoalManager/PlanManager/GoalCompletionEvaluator/
PlanExecutionController/ExecutionEventLog stack, never a second copy of
any of their logic.

Covers: an already-satisfied goal, one successful execution, a
partially-completed plan, a goal completed after execution, a failed
plan, a blocked plan, no executable steps remaining, a missing goal, a
missing plan, a plan/goal mismatch, max_iterations=1, max_iterations>1,
invalid max_iterations, stopping after satisfaction, stopping after
failure, stopping after a blocked state, no automatic retry, no new
plan creation, event logging, and deterministic behavior.

Run directly:
    python -m unittest tests.test_agent_loop -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.plan import STATUS_FAILED as STEP_STATUS_FAILED, STATUS_COMPLETED as STEP_STATUS_COMPLETED
from planning.goal_completion import (
    GoalCompletionEvaluator,
    STATE_SATISFIED,
    STATE_NOT_SATISFIED,
    STATE_PARTIALLY_SATISFIED,
    STATE_BLOCKED,
    STATE_FAILED,
    STATE_UNKNOWN,
)

from execution.plan_execution_controller import PlanExecutionController
from execution.execution_event_log import ExecutionEventLog
from execution.execution_event import (
    EVENT_AGENT_LOOP_STARTED,
    EVENT_AGENT_ITERATION_STARTED,
    EVENT_AGENT_EVALUATION_COMPLETED,
    EVENT_AGENT_EXECUTION_COMPLETED,
    EVENT_AGENT_LOOP_COMPLETED,
    EVENT_AGENT_LOOP_STOPPED,
    EVENT_AGENT_LOOP_FAILED,
)

from agent.agent_loop import (
    AgentLoop,
    STATUS_SATISFIED,
    STATUS_FAILED,
    STATUS_BLOCKED,
    STATUS_NOT_SATISFIED,
    STATUS_UNKNOWN,
    STATUS_MAX_ITERATIONS_REACHED,
    STATUS_INVALID,
    ALL_AGENT_LOOP_STATUSES,
)
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED, RESULT_INVALID
from planning.adaptive_plan_analyzer import (
    AdaptivePlanAnalyzer,
    ANALYSIS_INCOMPLETE,
    ANALYSIS_UNKNOWN,
    BLOCKER_FAILED_STEP,
)
from planning.adaptive_plan_proposal import (
    AdaptivePlanProposal,
    PROPOSAL_NO_CHANGE_NEEDED,
    PROPOSAL_CHANGE_RECOMMENDED,
    CHECK_CONFIDENCE_VALID,
    CHANGE_REMOVE_DEPENDENCY,
)
from planning.proposal_applier import ProposalApplier, RESULT_APPLIED, RESULT_UNSUPPORTED_CHANGE_TYPE
from planning.proposal_history import ProposalHistory
from learning.learning_record_store import LearningRecordStore
from learning.learning_record import LearningRecord


class AgentLoopTestBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.controller = PlanExecutionController(self.plans)
        self.loop = AgentLoop(self.goals, self.plans, self.controller)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _add_step(self, description="Do the thing", **kwargs):
        return self.plans.add_step(self.plan.plan_id, description, **kwargs)

    def _register_handler(self, capability_name, handler):
        self.controller.capability_handlers.register(capability_name, handler)


# --------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------
class TestConstruction(unittest.TestCase):
    def test_requires_goal_manager(self):
        plans = PlanManager(GoalManager())
        controller = PlanExecutionController(plans)
        with self.assertRaises(TypeError):
            AgentLoop("not-a-goal-manager", plans, controller)

    def test_requires_plan_manager(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        with self.assertRaises(TypeError):
            AgentLoop(goals, "not-a-plan-manager", controller)

    def test_requires_plan_execution_controller(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            AgentLoop(goals, plans, "not-a-controller")

    def test_rejects_wrong_type_evaluator(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        with self.assertRaises(TypeError):
            AgentLoop(goals, plans, controller, goal_completion_evaluator="nope")

    def test_rejects_wrong_type_event_log(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        with self.assertRaises(TypeError):
            AgentLoop(goals, plans, controller, event_log="nope")

    def test_defaults_to_controllers_event_log(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        loop = AgentLoop(goals, plans, controller)
        self.assertIs(loop.event_log, controller.event_log)

    def test_accepts_explicit_evaluator_and_event_log(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        evaluator = GoalCompletionEvaluator(goals, plans)
        event_log = ExecutionEventLog()
        loop = AgentLoop(goals, plans, controller, goal_completion_evaluator=evaluator, event_log=event_log)
        self.assertIs(loop.event_log, event_log)


# --------------------------------------------------------------------
# Missing goal / missing plan / mismatch
# --------------------------------------------------------------------
class TestMissingGoal(AgentLoopTestBase):
    def test_unknown_goal_id_returns_invalid(self):
        result = self.loop.run("goal-does-not-exist", self.plan.plan_id)
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertEqual(result["iterations"], 0)
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["executed_steps"], [])


class TestMissingPlan(AgentLoopTestBase):
    def test_unknown_plan_id_returns_invalid(self):
        result = self.loop.run(self.goal.goal_id, "plan-does-not-exist")
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertEqual(result["iterations"], 0)
        self.assertIsNotNone(result["error"])


class TestPlanGoalMismatch(AgentLoopTestBase):
    def test_plan_belonging_to_a_different_goal_is_refused(self):
        other_goal = self.goals.create_goal("A different goal")
        result = self.loop.run(other_goal.goal_id, self.plan.plan_id)
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertIn("goal it isn't attached to", result["error"])


# --------------------------------------------------------------------
# Invalid max_iterations
# --------------------------------------------------------------------
class TestInvalidMaxIterations(AgentLoopTestBase):
    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=-1)

    def test_bool_raises(self):
        with self.assertRaises(ValueError):
            self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=True)

    def test_float_raises(self):
        with self.assertRaises(ValueError):
            self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1.5)

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=None)

    def test_infinite_raises(self):
        with self.assertRaises(ValueError):
            self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=float("inf"))


# --------------------------------------------------------------------
# Already-satisfied goal
# --------------------------------------------------------------------
class TestAlreadySatisfiedGoal(AgentLoopTestBase):
    def test_stops_immediately_without_executing(self):
        step = self._add_step("Only step")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STEP_STATUS_COMPLETED)

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], STATUS_SATISFIED)
        self.assertEqual(result["goal_status"], STATE_SATISFIED)
        self.assertEqual(result["executed_steps"], [])
        self.assertEqual(len(self.controller.history), 0)
        self.assertEqual(result["iterations"], 1)


# --------------------------------------------------------------------
# One successful execution / goal completed after execution
# --------------------------------------------------------------------
class TestOneSuccessfulExecution(AgentLoopTestBase):
    def test_single_step_plan_completes_in_one_iteration(self):
        step = self._add_step("Only step")

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], STATUS_SATISFIED)
        self.assertEqual(result["goal_status"], STATE_SATISFIED)
        self.assertEqual(result["executed_steps"], [step.step_id])
        self.assertEqual(result["completed_steps"], [step.step_id])
        self.assertEqual(result["iterations"], 1)

    def test_step_output_is_preserved(self):
        step = self._add_step("Produces output", required_capabilities=["make_thing"])
        self._register_handler("make_thing", lambda ctx: {"value": 42})

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertIn(step.step_id, result["outputs"])


class TestGoalCompletedAfterExecution(AgentLoopTestBase):
    def test_two_step_plan_completes_within_one_call(self):
        step1 = self._add_step("First")
        step2 = self._add_step("Second", dependencies=[step1.step_id])

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], STATUS_SATISFIED)
        self.assertEqual(set(result["completed_steps"]), {step1.step_id, step2.step_id})


# --------------------------------------------------------------------
# Partially-completed plan
# --------------------------------------------------------------------
class TestPartiallyCompletedPlan(AgentLoopTestBase):
    def test_pre_completed_step_alongside_a_remaining_step(self):
        step1 = self._add_step("Already done")
        step2 = self._add_step("Still to do", dependencies=[step1.step_id])
        self.plans.update_step_status(self.plan.plan_id, step1.step_id, STEP_STATUS_COMPLETED)

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], STATUS_SATISFIED)
        self.assertEqual(result["executed_steps"], [step2.step_id])
        self.assertIn(step1.step_id, result["completed_steps"])
        self.assertIn(step2.step_id, result["completed_steps"])


# --------------------------------------------------------------------
# Failed plan
# --------------------------------------------------------------------
class TestFailedPlan(AgentLoopTestBase):
    def test_failing_step_stops_the_loop(self):
        step = self._add_step("Will fail", required_capabilities=["boom"])

        def failing_handler(step_arg):
            raise RuntimeError("kaboom")

        self._register_handler("boom", failing_handler)

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertEqual(result["executed_steps"], [step.step_id])
        self.assertEqual(result["failed_steps"], [step.step_id])
        self.assertIsNotNone(result["error"])

    def test_already_failed_goal_state_stops_without_executing(self):
        step = self._add_step("Pre-failed")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STEP_STATUS_FAILED)

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertEqual(result["executed_steps"], [])


class TestNoAutomaticRetry(AgentLoopTestBase):
    def test_failed_step_is_not_retried_within_the_same_run(self):
        step = self._add_step("Will fail", required_capabilities=["boom"])
        attempts = {"count": 0}

        def failing_handler(step_arg):
            attempts["count"] += 1
            raise RuntimeError("kaboom")

        self._register_handler("boom", failing_handler)

        self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=5)

        self.assertEqual(attempts["count"], 1)
        self.assertEqual(step.status, STEP_STATUS_FAILED)

    def test_calling_run_again_after_failure_still_does_not_retry(self):
        step = self._add_step("Will fail", required_capabilities=["boom"])
        self._register_handler("boom", lambda s: (_ for _ in ()).throw(RuntimeError("x")))

        first = self.loop.run(self.goal.goal_id, self.plan.plan_id)
        second = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertFalse(first["success"])
        self.assertFalse(second["success"])
        self.assertEqual(second["status"], STATUS_FAILED)
        self.assertEqual(second["executed_steps"], [])


# --------------------------------------------------------------------
# Blocked plan
# --------------------------------------------------------------------
class TestBlockedPlan(AgentLoopTestBase):
    def test_unresolved_dependency_reports_blocked(self):
        self._add_step("Stuck", dependencies=["missing-step"])

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertEqual(result["executed_steps"], [])
        self.assertEqual(len(self.controller.history), 0)

    def test_stopping_after_blocked_state_does_not_execute(self):
        self._add_step("Stuck", dependencies=["missing-step"])
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=5)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertEqual(result["iterations"], 1)


# --------------------------------------------------------------------
# No executable steps remain
# --------------------------------------------------------------------
class TestNoExecutableStepsRemain(AgentLoopTestBase):
    def test_empty_plan_reports_unknown(self):
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], STATUS_UNKNOWN)
        self.assertEqual(result["goal_status"], STATE_UNKNOWN)
        self.assertEqual(result["executed_steps"], [])

    def test_missing_handler_leaves_goal_not_satisfied(self):
        self._add_step("Needs a handler", required_capabilities=["draw_image"])
        # No handler registered at all - PlanExecutionCoordinator will
        # never find this step executable.

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertEqual(result["executed_steps"], [])


# --------------------------------------------------------------------
# max_iterations = 1
# --------------------------------------------------------------------
class TestMaxIterationsOne(AgentLoopTestBase):
    def test_default_max_iterations_is_one(self):
        step1 = self._add_step("First")
        step2 = self._add_step("Second", dependencies=[step1.step_id])
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["iterations"], 1)
        # Both steps completed within that single iteration, since
        # PlanExecutionController.execute_plan itself already runs a
        # whole cascade of eligible steps per call.
        self.assertEqual(result["status"], STATUS_SATISFIED)

    def test_max_iterations_one_stops_even_if_more_steps_would_remain(self):
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)
        step1 = self._add_step("First")
        step2 = self._add_step("Second", dependencies=[step1.step_id])

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        self.assertEqual(result["iterations"], 1)
        self.assertEqual(result["status"], STATUS_MAX_ITERATIONS_REACHED)
        self.assertEqual(result["executed_steps"], [step1.step_id])


# --------------------------------------------------------------------
# max_iterations > 1
# --------------------------------------------------------------------
class TestMaxIterationsGreaterThanOne(AgentLoopTestBase):
    def test_continues_across_iterations_while_steps_remain(self):
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)
        step1 = self._add_step("First")
        step2 = self._add_step("Second", dependencies=[step1.step_id])
        step3 = self._add_step("Third", dependencies=[step2.step_id])

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=5)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], STATUS_SATISFIED)
        self.assertEqual(result["iterations"], 3)
        self.assertEqual(
            result["executed_steps"], [step1.step_id, step2.step_id, step3.step_id]
        )

    def test_stops_as_soon_as_satisfied_without_using_full_budget(self):
        step = self._add_step("Only step")
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=10)
        self.assertEqual(result["iterations"], 1)
        self.assertEqual(result["status"], STATUS_SATISFIED)

    def test_never_creates_a_new_plan(self):
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)
        step1 = self._add_step("First")
        step2 = self._add_step("Second", dependencies=[step1.step_id])

        plan_count_before = len(self.plans)
        loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=5)
        plan_count_after = len(self.plans)

        self.assertEqual(plan_count_before, plan_count_after)


# --------------------------------------------------------------------
# No recursive run() / deterministic behavior
# --------------------------------------------------------------------
class TestDeterministicBehavior(AgentLoopTestBase):
    def test_same_setup_yields_the_same_result_shape(self):
        step1 = self._add_step("First")
        step2 = self._add_step("Second", dependencies=[step1.step_id])

        goals2 = GoalManager()
        plans2 = PlanManager(goals2)
        controller2 = PlanExecutionController(plans2)
        loop2 = AgentLoop(goals2, plans2, controller2)
        goal2 = goals2.create_goal("Ship a small feature")
        plan2 = plans2.create_plan(goal2.goal_id)
        s1 = plans2.add_step(plan2.plan_id, "First")
        plans2.add_step(plan2.plan_id, "Second", dependencies=[s1.step_id])

        result1 = self.loop.run(self.goal.goal_id, self.plan.plan_id)
        result2 = loop2.run(goal2.goal_id, plan2.plan_id)

        self.assertEqual(result1["status"], result2["status"])
        self.assertEqual(result1["goal_status"], result2["goal_status"])
        self.assertEqual(result1["iterations"], result2["iterations"])
        self.assertEqual(len(result1["executed_steps"]), len(result2["executed_steps"]))

    def test_run_method_never_calls_itself_recursively(self):
        import inspect
        from agent import agent_loop as mod

        source = inspect.getsource(mod.AgentLoop.run)
        # The method body should never reference its own name being
        # called on self - i.e. no "self.run(" anywhere inside run().
        self.assertNotIn("self.run(", source)

    def test_module_uses_no_dangerous_builtins(self):
        import inspect
        from agent import agent_loop as mod

        source = inspect.getsource(mod)
        for banned in ("eval(", "exec(", "subprocess", "os.system", "__import__"):
            self.assertNotIn(banned, source)


# --------------------------------------------------------------------
# Event logging
# --------------------------------------------------------------------
class TestEventLogging(AgentLoopTestBase):
    def test_loop_started_event_is_recorded(self):
        self._add_step("Only step")
        self.loop.run(self.goal.goal_id, self.plan.plan_id)
        events = self.loop.event_log.list_for_plan(self.plan.plan_id)
        types = [e.event_type for e in events]
        self.assertIn(EVENT_AGENT_LOOP_STARTED, types)

    def test_iteration_and_evaluation_events_are_recorded(self):
        self._add_step("Only step")
        self.loop.run(self.goal.goal_id, self.plan.plan_id)
        events = self.loop.event_log.list_for_plan(self.plan.plan_id)
        types = [e.event_type for e in events]
        self.assertIn(EVENT_AGENT_ITERATION_STARTED, types)
        self.assertIn(EVENT_AGENT_EVALUATION_COMPLETED, types)
        self.assertIn(EVENT_AGENT_EXECUTION_COMPLETED, types)

    def test_completed_event_is_recorded_on_satisfaction(self):
        self._add_step("Only step")
        self.loop.run(self.goal.goal_id, self.plan.plan_id)
        events = self.loop.event_log.list_for_plan(self.plan.plan_id)
        types = [e.event_type for e in events]
        self.assertIn(EVENT_AGENT_LOOP_COMPLETED, types)

    def test_failed_event_is_recorded_on_plan_failure(self):
        self._add_step("Will fail", required_capabilities=["boom"])
        self._register_handler("boom", lambda s: (_ for _ in ()).throw(RuntimeError("x")))
        self.loop.run(self.goal.goal_id, self.plan.plan_id)
        events = self.loop.event_log.list_for_plan(self.plan.plan_id)
        types = [e.event_type for e in events]
        self.assertIn(EVENT_AGENT_LOOP_FAILED, types)

    def test_stopped_event_is_recorded_on_blocked_state(self):
        self._add_step("Stuck", dependencies=["missing-step"])
        self.loop.run(self.goal.goal_id, self.plan.plan_id)
        events = self.loop.event_log.list_for_plan(self.plan.plan_id)
        types = [e.event_type for e in events]
        self.assertIn(EVENT_AGENT_LOOP_STOPPED, types)

    def test_failed_event_is_recorded_for_invalid_input(self):
        self.loop.run("no-such-goal", "no-such-plan")
        events = self.loop.event_log.list_for_plan("no-such-plan")
        types = [e.event_type for e in events]
        self.assertIn(EVENT_AGENT_LOOP_FAILED, types)

    def test_failed_event_uses_fallback_plan_id_when_plan_id_is_not_a_string(self):
        self.loop.run(self.goal.goal_id, None)
        events = self.loop.event_log.list_for_plan("agent-loop-unknown-plan")
        types = [e.event_type for e in events]
        self.assertIn(EVENT_AGENT_LOOP_FAILED, types)

    def test_events_share_the_execution_stacks_event_log(self):
        self._add_step("Only step")
        self.loop.run(self.goal.goal_id, self.plan.plan_id)
        # Step-level events (from StepExecutionController/ExecutionEngine)
        # and AgentLoop-level events both live in the same log.
        events = self.controller.event_log.list_for_plan(self.plan.plan_id)
        types = {e.event_type for e in events}
        self.assertIn(EVENT_AGENT_LOOP_STARTED, types)
        self.assertTrue(any(t not in (
            EVENT_AGENT_LOOP_STARTED, EVENT_AGENT_ITERATION_STARTED,
            EVENT_AGENT_EVALUATION_COMPLETED, EVENT_AGENT_EXECUTION_COMPLETED,
            EVENT_AGENT_LOOP_COMPLETED, EVENT_AGENT_LOOP_STOPPED, EVENT_AGENT_LOOP_FAILED,
        ) for t in types))


# --------------------------------------------------------------------
# Fixed vocabulary
# --------------------------------------------------------------------
class TestStatusVocabulary(unittest.TestCase):
    def test_all_statuses_are_unique_strings(self):
        self.assertEqual(len(ALL_AGENT_LOOP_STATUSES), len(set(ALL_AGENT_LOOP_STATUSES)))
        for status in ALL_AGENT_LOOP_STATUSES:
            self.assertIsInstance(status, str)


# --------------------------------------------------------------------
# Adaptive plan analysis integration (planning/adaptive_plan_analyzer.py)
# --------------------------------------------------------------------
class TestRequestAnalysis(AgentLoopTestBase):
    def test_analyzer_is_optional_and_defaults_to_none(self):
        self.assertIsNone(self.loop._analyzer)

    def test_rejects_wrong_type_analyzer(self):
        with self.assertRaises(TypeError):
            AgentLoop(self.goals, self.plans, self.controller, analyzer="not an analyzer")

    def test_request_analysis_without_analyzer_raises(self):
        with self.assertRaises(ValueError):
            self.loop.request_analysis(self.goal.goal_id, self.plan.plan_id)

    def test_request_analysis_delegates_to_analyzer(self):
        self._add_step()  # left pending -> goal not satisfied
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.request_analysis(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["analysis_status"], ANALYSIS_INCOMPLETE)
        self.assertEqual(result["goal_id"], self.goal.goal_id)
        self.assertEqual(result["plan_id"], self.plan.plan_id)

    def test_run_never_calls_analyzer_automatically(self):
        """run()'s own decision logic is unchanged/backward compatible -
        it never consults or requires an analyzer."""
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        result = loop.run(self.goal.goal_id, self.plan.plan_id)
        self.assertIn(result["status"], ALL_AGENT_LOOP_STATUSES)

    def test_request_analysis_is_read_only(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        before = self.plans.describe_plan(self.plan.plan_id)
        loop.request_analysis(self.goal.goal_id, self.plan.plan_id)
        after = self.plans.describe_plan(self.plan.plan_id)
        self.assertEqual(before, after)


# --------------------------------------------------------------------
# Correction-triggered plan analysis (Prompt 322) - connects
# AgentLoop.evaluate_correction_decision (agent/test_result_evaluation.py)
# to the existing AdaptivePlanAnalyzer via request_analysis above -
# never a second/duplicate analyzer.
# --------------------------------------------------------------------
def _passed_test_result(**overrides):
    result = {"success": True, "timed_out": False}
    result.update(overrides)
    return result


def _failed_test_result(**overrides):
    result = {"success": False, "timed_out": False}
    result.update(overrides)
    return result


class TestRequestCorrectionAnalysis(AgentLoopTestBase):
    # ------------------------------------------------------------------
    # 1. "correction_required = true" allows Plan analysis.
    # ------------------------------------------------------------------
    def test_correction_required_true_performs_analysis(self):
        self._add_step()  # left pending -> plan incomplete, a real blocker
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.request_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertTrue(result["correction"]["correction_required"])
        self.assertTrue(result["analysis_performed"])
        self.assertIsNotNone(result["analysis"])

    # ------------------------------------------------------------------
    # 2. Analyzer results are exposed through AgentLoop.
    # ------------------------------------------------------------------
    def test_exposed_analysis_matches_request_analysis(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.request_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        direct = loop.request_analysis(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["analysis"], direct)
        self.assertEqual(result["analysis"]["analysis_status"], ANALYSIS_INCOMPLETE)
        self.assertEqual(result["analysis"]["goal_id"], self.goal.goal_id)
        self.assertEqual(result["analysis"]["plan_id"], self.plan.plan_id)

    def test_exposed_correction_matches_evaluate_correction_decision(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        test_result = _failed_test_result()

        result = loop.request_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, test_result
        )

        self.assertEqual(
            result["correction"], loop.evaluate_correction_decision(test_result)
        )

    # ------------------------------------------------------------------
    # 3. "correction_required = false" does not trigger correction
    #    analysis.
    # ------------------------------------------------------------------
    def test_correction_required_false_skips_analysis(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.request_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, _passed_test_result()
        )

        self.assertFalse(result["correction"]["correction_required"])
        self.assertFalse(result["analysis_performed"])
        self.assertIsNone(result["analysis"])

    def test_correction_required_false_needs_no_analyzer(self):
        # No analyzer supplied at all - a PASSED result must never even
        # attempt to reach it, so this must not raise.
        loop = AgentLoop(self.goals, self.plans, self.controller)
        try:
            result = loop.request_correction_analysis(
                self.goal.goal_id, self.plan.plan_id, _passed_test_result()
            )
        except ValueError as exc:  # pragma: no cover - failure path
            self.fail(f"request_correction_analysis required an analyzer for a "
                      f"passed result: {exc!r}")
        self.assertFalse(result["analysis_performed"])

    def test_correction_required_true_without_analyzer_raises(self):
        loop = AgentLoop(self.goals, self.plans, self.controller)
        with self.assertRaises(ValueError):
            loop.request_correction_analysis(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )

    # ------------------------------------------------------------------
    # 4. Missing Plan data is handled safely.
    # ------------------------------------------------------------------
    def test_unknown_plan_id_is_handled_safely(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        try:
            result = loop.request_correction_analysis(
                self.goal.goal_id, "no-such-plan", _failed_test_result()
            )
        except Exception as exc:  # pragma: no cover - failure path
            self.fail(f"request_correction_analysis raised for an unknown "
                      f"plan_id: {exc!r}")

        self.assertTrue(result["analysis_performed"])
        self.assertEqual(result["analysis"]["analysis_status"], ANALYSIS_UNKNOWN)

    def test_unknown_goal_id_is_handled_safely(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.request_correction_analysis(
            "no-such-goal", self.plan.plan_id, _failed_test_result()
        )

        self.assertEqual(result["analysis"]["analysis_status"], ANALYSIS_UNKNOWN)

    def test_malformed_test_result_is_still_handled_safely(self):
        """An INVALID classification (malformed test_result) still
        requires correction, so analysis still runs against the real,
        existing goal_id/plan_id - never against invented data."""
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.request_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, {"nonsense": True}
        )

        self.assertTrue(result["correction"]["correction_required"])
        self.assertTrue(result["analysis_performed"])
        self.assertEqual(result["analysis"]["analysis_status"], ANALYSIS_INCOMPLETE)

    # ------------------------------------------------------------------
    # 5. No Plan modification occurs during analysis.
    # ------------------------------------------------------------------
    def test_no_plan_modification_when_correction_required(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        before = self.plans.describe_plan(self.plan.plan_id)
        loop.request_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before, after)

    def test_no_plan_modification_when_correction_not_required(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        before = self.plans.describe_plan(self.plan.plan_id)
        loop.request_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, _passed_test_result()
        )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before, after)

    def test_no_step_is_executed_by_correction_analysis(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        loop.request_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        evaluation = GoalCompletionEvaluator(self.goals, self.plans).evaluate(
            self.goal.goal_id, self.plan.plan_id
        )
        self.assertEqual(evaluation["completed_steps"], [])

    # ------------------------------------------------------------------
    # 6. Existing tests remain compatible.
    # ------------------------------------------------------------------
    def test_run_never_calls_correction_analysis_automatically(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertNotIn("correction", result)
        self.assertNotIn("analysis_performed", result)
        self.assertNotIn("analysis", result)

    def test_request_analysis_still_works_unaffected(self):
        self._add_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.request_analysis(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["analysis_status"], ANALYSIS_INCOMPLETE)


# --------------------------------------------------------------------
# Analyzer -> Proposal connection for corrections (Prompt 323) -
# connects AgentLoop.request_correction_analysis (Prompt 322) to the
# existing AdaptivePlanProposal via request_proposal above - never a
# second/duplicate proposal system.
# --------------------------------------------------------------------
class TestRequestCorrectionProposal(AgentLoopTestBase):
    def _fail_the_step(self):
        step = self._add_step()
        from planning.plan import STATUS_FAILED as STEP_STATUS_FAILED
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STEP_STATUS_FAILED)
        return step

    # ------------------------------------------------------------------
    # 1. Analyzer blockers can produce a correction proposal.
    # ------------------------------------------------------------------
    def test_blockers_trigger_a_proposal(self):
        self._fail_the_step()  # a real BLOCKER_FAILED_STEP
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )

        # Confirm the analyzer really did find a blocker before
        # checking the proposal that blocker should trigger.
        analysis = loop.request_analysis(self.goal.goal_id, self.plan.plan_id)
        self.assertTrue(any(b["type"] == BLOCKER_FAILED_STEP for b in analysis["blockers"]))

        result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertTrue(result["proposal_performed"])
        self.assertIsNotNone(result["proposal"])
        self.assertEqual(result["proposal"]["status"], PROPOSAL_CHANGE_RECOMMENDED)

    def test_incomplete_work_without_a_named_blocker_still_triggers_a_proposal(self):
        self._add_step()  # left pending -> incomplete, no explicit blocker
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )

        result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertTrue(result["proposal_performed"])
        self.assertEqual(result["proposal"]["status"], PROPOSAL_NO_CHANGE_NEEDED)

    # ------------------------------------------------------------------
    # 2. The proposal is exposed through AgentLoop.
    # ------------------------------------------------------------------
    def test_exposed_proposal_matches_request_proposal(self):
        self._fail_the_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )

        result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        direct = loop.request_proposal(self.goal.goal_id, self.plan.plan_id)

        # Each call to the underlying AdaptivePlanProposal mints its own
        # proposal_id/created_at, and each ProposedChange its own
        # change_id (see that module's own id/timestamp generation) -
        # everything else about the two calls' own structured content,
        # including each change's type/target/reason, is identical.
        self.assertEqual(result["proposal"]["status"], direct["status"])
        self.assertEqual(result["proposal"]["goal_id"], direct["goal_id"])
        self.assertEqual(result["proposal"]["plan_id"], direct["plan_id"])
        self.assertEqual(
            [(c["change_type"], c["target_step_id"], c["reason"])
             for c in result["proposal"]["proposed_changes"]],
            [(c["change_type"], c["target_step_id"], c["reason"])
             for c in direct["proposed_changes"]],
        )
        self.assertEqual(result["proposal"]["goal_id"], self.goal.goal_id)
        self.assertEqual(result["proposal"]["plan_id"], self.plan.plan_id)

    def test_exposed_correction_analysis_matches_request_correction_analysis(self):
        self._fail_the_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )
        test_result = _failed_test_result()

        result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, test_result
        )

        self.assertEqual(
            result["correction_analysis"],
            loop.request_correction_analysis(self.goal.goal_id, self.plan.plan_id, test_result),
        )

    # ------------------------------------------------------------------
    # No proposal for a passing result or a fully satisfied plan.
    # ------------------------------------------------------------------
    def test_passed_result_never_triggers_a_proposal(self):
        self._fail_the_step()  # would produce a blocker if reached
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )

        result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _passed_test_result()
        )

        self.assertFalse(result["proposal_performed"])
        self.assertIsNone(result["proposal"])

    def test_passed_result_needs_no_proposal_generator(self):
        loop = AgentLoop(self.goals, self.plans, self.controller)
        try:
            result = loop.request_correction_proposal(
                self.goal.goal_id, self.plan.plan_id, _passed_test_result()
            )
        except ValueError as exc:  # pragma: no cover - failure path
            self.fail(f"request_correction_proposal required a proposal_generator "
                      f"for a passed result: {exc!r}")
        self.assertFalse(result["proposal_performed"])

    def test_blockers_without_a_proposal_generator_raises(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        self._fail_the_step()
        with self.assertRaises(ValueError):
            loop.request_correction_proposal(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )

    # ------------------------------------------------------------------
    # 3. No Plan changes occur while generating the proposal.
    # ------------------------------------------------------------------
    def test_no_plan_modification_when_a_proposal_is_generated(self):
        self._fail_the_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )

        before = self.plans.describe_plan(self.plan.plan_id)
        loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before, after)

    def test_no_plan_modification_when_no_proposal_is_generated(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )

        before = self.plans.describe_plan(self.plan.plan_id)
        loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _passed_test_result()
        )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before, after)

    # ------------------------------------------------------------------
    # 4. No execution occurs while generating the proposal.
    # ------------------------------------------------------------------
    def test_no_step_is_executed_while_generating_the_proposal(self):
        self._add_step()  # left pending, never executed
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )

        loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        evaluation = GoalCompletionEvaluator(self.goals, self.plans).evaluate(
            self.goal.goal_id, self.plan.plan_id
        )
        self.assertEqual(evaluation["completed_steps"], [])

    # ------------------------------------------------------------------
    # 5. Missing analyzer data is handled safely.
    # ------------------------------------------------------------------
    def test_unknown_plan_id_is_handled_safely(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )

        try:
            result = loop.request_correction_proposal(
                self.goal.goal_id, "no-such-plan", _failed_test_result()
            )
        except Exception as exc:  # pragma: no cover - failure path
            self.fail(f"request_correction_proposal raised for an unknown "
                      f"plan_id: {exc!r}")

        self.assertEqual(
            result["correction_analysis"]["analysis"]["analysis_status"], ANALYSIS_UNKNOWN
        )
        self.assertFalse(result["proposal_performed"])
        self.assertIsNone(result["proposal"])

    def test_unknown_goal_id_is_handled_safely(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )

        result = loop.request_correction_proposal(
            "no-such-goal", self.plan.plan_id, _failed_test_result()
        )

        self.assertFalse(result["proposal_performed"])
        self.assertIsNone(result["proposal"])

    def test_malformed_test_result_is_handled_safely(self):
        self._fail_the_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )

        try:
            result = loop.request_correction_proposal(
                self.goal.goal_id, self.plan.plan_id, {"nonsense": True}
            )
        except Exception as exc:  # pragma: no cover - failure path
            self.fail(f"request_correction_proposal raised for a malformed "
                      f"test_result: {exc!r}")

        self.assertTrue(result["proposal_performed"])
        self.assertEqual(result["proposal"]["status"], PROPOSAL_CHANGE_RECOMMENDED)

    # ------------------------------------------------------------------
    # 6. Existing tests remain compatible.
    # ------------------------------------------------------------------
    def test_run_never_calls_correction_proposal_automatically(self):
        self._fail_the_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        self.assertNotIn("proposal", result)
        self.assertNotIn("proposal_performed", result)
        self.assertNotIn("correction_analysis", result)

    def test_request_proposal_still_works_unaffected(self):
        self._add_step()
        proposer = AdaptivePlanProposal(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, proposal_generator=proposer)

        result = loop.request_proposal(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["status"], PROPOSAL_NO_CHANGE_NEEDED)

    def test_request_correction_analysis_still_works_unaffected(self):
        self._fail_the_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)

        result = loop.request_correction_analysis(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        self.assertTrue(result["correction"]["correction_required"])


# --------------------------------------------------------------------
# Proposal validation connection (Prompt 324) - connects
# AgentLoop.request_correction_proposal (Prompt 323) to the existing
# AdaptivePlanProposal.validate_proposal - never a second/duplicate
# validator, and never an apply step.
# --------------------------------------------------------------------
class TestRequestCorrectionValidation(AgentLoopTestBase):
    def _fail_the_step(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STEP_STATUS_FAILED)
        return step

    def _loop_with_collaborators(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )
        return loop

    # ------------------------------------------------------------------
    # 1. A valid proposal passes validation.
    # ------------------------------------------------------------------
    def test_a_real_generated_proposal_passes_validation(self):
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        result = loop.request_correction_validation(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertTrue(result["validation_performed"])
        self.assertTrue(result["validation"]["valid"])
        self.assertEqual(result["validation"]["failed_checks"], [])
        self.assertTrue(result["ready_for_application"])

    # ------------------------------------------------------------------
    # 2. An invalid proposal is rejected.
    # ------------------------------------------------------------------
    def test_an_invalid_proposal_is_rejected(self):
        """Real, deterministically-generated proposals are always
        internally consistent, so an invalid one is simulated here
        the same way the project's own AdaptivePlanProposal test suite
        does - by taking a real, previously-generated proposal and
        corrupting one field - while still exercising the real,
        existing `validate_proposal` (never a stubbed-out one) to
        confirm it actually catches the corruption."""
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        real_result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        corrupted_result = copy.deepcopy(real_result)
        corrupted_result["proposal"]["proposed_changes"][0]["confidence"] = "not a number"

        with mock.patch.object(loop, "request_correction_proposal", return_value=corrupted_result):
            result = loop.request_correction_validation(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )

        self.assertTrue(result["validation_performed"])
        self.assertFalse(result["validation"]["valid"])
        self.assertTrue(
            any(f["check"] == CHECK_CONFIDENCE_VALID for f in result["validation"]["failed_checks"])
        )

    # ------------------------------------------------------------------
    # 3. Validation does not modify the Plan.
    # ------------------------------------------------------------------
    def test_validation_of_a_valid_proposal_does_not_modify_the_plan(self):
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        before = self.plans.describe_plan(self.plan.plan_id)
        loop.request_correction_validation(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before, after)

    def test_validation_of_an_invalid_proposal_does_not_modify_the_plan(self):
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        real_result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        corrupted_result = copy.deepcopy(real_result)
        corrupted_result["proposal"]["proposed_changes"][0]["confidence"] = -5.0

        before = self.plans.describe_plan(self.plan.plan_id)
        with mock.patch.object(loop, "request_correction_proposal", return_value=corrupted_result):
            loop.request_correction_validation(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before, after)

    def test_no_step_is_executed_during_validation(self):
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        loop.request_correction_validation(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        evaluation = GoalCompletionEvaluator(self.goals, self.plans).evaluate(
            self.goal.goal_id, self.plan.plan_id
        )
        self.assertEqual(evaluation["completed_steps"], [])

    # ------------------------------------------------------------------
    # 4. An invalid proposal cannot proceed to application.
    # ------------------------------------------------------------------
    def test_invalid_proposal_is_not_marked_ready_for_application(self):
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        real_result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        corrupted_result = copy.deepcopy(real_result)
        corrupted_result["proposal"]["proposed_changes"][0]["target_step_id"] = "step-does-not-exist"

        with mock.patch.object(loop, "request_correction_proposal", return_value=corrupted_result):
            result = loop.request_correction_validation(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )

        self.assertFalse(result["ready_for_application"])
        self.assertFalse(result["validation"]["valid"])

    def test_no_proposal_is_never_marked_ready_for_application(self):
        loop = self._loop_with_collaborators()

        result = loop.request_correction_validation(
            self.goal.goal_id, self.plan.plan_id, _passed_test_result()
        )

        self.assertFalse(result["validation_performed"])
        self.assertIsNone(result["validation"])
        self.assertFalse(result["ready_for_application"])

    def test_nothing_is_applied_by_requesting_validation(self):
        """Even a proposal marked ready_for_application is never
        itself applied by this method - applying remains a separate,
        not-yet-built, explicitly-invoked step."""
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        before = self.plans.describe_plan(self.plan.plan_id)
        result = loop.request_correction_validation(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertTrue(result["ready_for_application"])
        self.assertEqual(before, after)

    # ------------------------------------------------------------------
    # 5. AgentLoop receives the structured validation result.
    # ------------------------------------------------------------------
    def test_exposed_validation_matches_direct_validate_proposal_call(self):
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        result = loop.request_correction_validation(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        direct = loop._proposal_generator.validate_proposal(result["correction_proposal"]["proposal"])

        self.assertEqual(result["validation"], direct)

    def test_validation_result_has_the_documented_shape(self):
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        result = loop.request_correction_validation(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertIn("correction_proposal", result)
        self.assertIn("validation_performed", result)
        self.assertIn("validation", result)
        self.assertIn("ready_for_application", result)
        self.assertIn("valid", result["validation"])
        self.assertIn("failed_checks", result["validation"])
        self.assertIn("warnings", result["validation"])

    def test_exposed_correction_proposal_matches_request_correction_proposal(self):
        self._fail_the_step()
        loop = self._loop_with_collaborators()
        test_result = _failed_test_result()

        result = loop.request_correction_validation(
            self.goal.goal_id, self.plan.plan_id, test_result
        )

        # request_correction_proposal is deterministic given the same
        # already-recorded Plan/Goal state - a fresh call reports the
        # same status/goal_id/plan_id/analysis, modulo the fresh
        # proposal_id/created_at/change_id AdaptivePlanProposal always
        # mints per call (see TestRequestCorrectionProposal's own
        # equivalent check).
        direct = loop.request_correction_proposal(self.goal.goal_id, self.plan.plan_id, test_result)
        self.assertEqual(
            result["correction_proposal"]["proposal_performed"], direct["proposal_performed"]
        )
        self.assertEqual(
            result["correction_proposal"]["proposal"]["status"], direct["proposal"]["status"]
        )

    # ------------------------------------------------------------------
    # 6. Existing tests remain compatible.
    # ------------------------------------------------------------------
    def test_run_never_calls_correction_validation_automatically(self):
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        self.assertNotIn("validation", result)
        self.assertNotIn("validation_performed", result)
        self.assertNotIn("ready_for_application", result)
        self.assertNotIn("correction_proposal", result)

    def test_request_correction_proposal_still_works_unaffected(self):
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        self.assertTrue(result["proposal_performed"])
        self.assertEqual(result["proposal"]["status"], PROPOSAL_CHANGE_RECOMMENDED)

    def test_validate_proposal_still_works_unaffected_directly(self):
        self._fail_the_step()
        loop = self._loop_with_collaborators()
        proposal = loop.request_proposal(self.goal.goal_id, self.plan.plan_id)

        validation = loop._proposal_generator.validate_proposal(proposal)
        self.assertTrue(validation["valid"])


# --------------------------------------------------------------------
# ProposalApplier integration for corrections (Prompt 325) - connects
# AgentLoop.request_correction_validation (Prompt 324) to the existing
# ProposalApplier (planning/proposal_applier.py) via
# AgentLoop.apply_correction_proposal - never a second/duplicate
# application system.
# --------------------------------------------------------------------
class TestApplyCorrectionProposal(AgentLoopTestBase):
    def _fail_the_step(self):
        step = self._add_step()
        from planning.plan import STATUS_FAILED as STEP_STATUS_FAILED
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STEP_STATUS_FAILED)
        return step

    def _dangling_dependency_step(self):
        """A step with a dependency on a step_id that doesn't exist in
        this plan - the one blocker type (BLOCKER_MISSING_STEP) whose
        proposed change (CHANGE_REMOVE_DEPENDENCY) is actually one of
        ProposalApplier's SUPPORTED_CHANGE_TYPES, so applying it really
        does succeed and mutate the Plan (unlike BLOCKER_FAILED_STEP's
        own CHANGE_MODIFY_STEP, which validate_proposal accepts as
        well-formed but ProposalApplier does not support applying)."""
        step = self._add_step("Review the code", dependencies=["plan-999-step-1"])
        self.plans.refresh_step_status(self.plan.plan_id, step.step_id)
        return step

    def _loop_with_collaborators(self, proposal_history=None):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        applier = ProposalApplier()
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
            proposal_applier=applier, proposal_history=proposal_history,
        )
        return loop

    # ------------------------------------------------------------------
    # 1. A valid proposal can be applied through AgentLoop.
    # ------------------------------------------------------------------
    def test_a_valid_proposal_is_applied(self):
        step = self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertTrue(result["correction_validation"]["ready_for_application"])
        self.assertTrue(result["application_performed"])
        self.assertTrue(result["application"]["success"])
        self.assertEqual(result["application"]["reason_code"], RESULT_APPLIED)
        self.assertEqual(result["application"]["change_type"], CHANGE_REMOVE_DEPENDENCY)
        self.assertEqual(result["application"]["target_step_id"], step.step_id)

    def test_rejects_wrong_type_proposal_applier(self):
        with self.assertRaises(TypeError):
            AgentLoop(self.goals, self.plans, self.controller, proposal_applier="not an applier")

    def test_rejects_wrong_type_proposal_history(self):
        with self.assertRaises(TypeError):
            AgentLoop(self.goals, self.plans, self.controller, proposal_history="not a history")

    def test_apply_without_applier_raises_when_a_change_is_ready(self):
        self._dangling_dependency_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )
        with self.assertRaises(ValueError):
            loop.apply_correction_proposal(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )

    def test_no_applier_needed_when_nothing_is_ready(self):
        # A PASSED result needs no proposal/validation/application at
        # all - this must not raise even without a proposal_applier.
        loop = AgentLoop(self.goals, self.plans, self.controller)
        try:
            result = loop.apply_correction_proposal(
                self.goal.goal_id, self.plan.plan_id, _passed_test_result()
            )
        except ValueError as exc:  # pragma: no cover - failure path
            self.fail(f"apply_correction_proposal required an applier for a "
                      f"passed result: {exc!r}")
        self.assertFalse(result["application_performed"])

    # ------------------------------------------------------------------
    # 2. An invalid proposal is not applied.
    # ------------------------------------------------------------------
    def test_invalid_proposal_is_not_applied(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        real_result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        corrupted_result = copy.deepcopy(real_result)
        corrupted_result["proposal"]["proposed_changes"][0]["confidence"] = "not a number"

        with mock.patch.object(loop, "request_correction_proposal", return_value=corrupted_result):
            result = loop.apply_correction_proposal(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )

        self.assertFalse(result["correction_validation"]["ready_for_application"])
        self.assertFalse(result["application_performed"])
        self.assertIsNone(result["application"])

    def test_invalid_proposal_leaves_the_plan_unmodified(self):
        step = self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        real_result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        corrupted_result = copy.deepcopy(real_result)
        corrupted_result["proposal"]["proposed_changes"][0]["target_step_id"] = "step-does-not-exist"

        before = self.plans.describe_plan(self.plan.plan_id)
        with mock.patch.object(loop, "request_correction_proposal", return_value=corrupted_result):
            loop.apply_correction_proposal(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before, after)
        self.assertIn("plan-999-step-1", self.plans.get_step(self.plan.plan_id, step.step_id).dependencies)

    def test_no_proposal_is_never_applied(self):
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _passed_test_result()
        )

        self.assertFalse(result["application_performed"])
        self.assertIsNone(result["application"])

    # ------------------------------------------------------------------
    # 3. Exactly one proposal change is applied per operation.
    # ------------------------------------------------------------------
    def test_only_the_first_change_is_applied_when_several_are_proposed(self):
        first = self._dangling_dependency_step()
        second = self._add_step("Also review", dependencies=["plan-999-step-2"])
        self.plans.refresh_step_status(self.plan.plan_id, second.step_id)
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        proposal = result["correction_validation"]["correction_proposal"]["proposal"]

        self.assertGreaterEqual(len(proposal["proposed_changes"]), 2)
        self.assertTrue(result["application_performed"])
        self.assertEqual(result["application"]["target_step_id"], first.step_id)
        # The second step's own dangling dependency is untouched -
        # only one change was ever applied.
        self.assertIn(
            "plan-999-step-2",
            self.plans.get_step(self.plan.plan_id, second.step_id).dependencies,
        )

    def test_no_second_apply_happens_automatically(self):
        """A single call to apply_correction_proposal never loops over
        every proposed change - a caller wanting the next one calls
        again, against the freshly re-validated proposal that call
        produces."""
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        with mock.patch.object(
            loop._proposal_applier, "apply_change", wraps=loop._proposal_applier.apply_change
        ) as spy:
            loop.apply_correction_proposal(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )
            self.assertEqual(spy.call_count, 1)

    # ------------------------------------------------------------------
    # 4. The application result is returned correctly.
    # ------------------------------------------------------------------
    def test_application_result_matches_a_direct_apply_change_call(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        change = result["correction_validation"]["correction_proposal"]["proposal"]["proposed_changes"][0]
        plan = self.plans.get_plan(self.plan.plan_id)
        direct = ProposalApplier().apply_change(plan, change)

        # Compare everything except the already-mutated plan's own
        # side effects on a second, independent apply attempt (a
        # second REMOVE_DEPENDENCY of the same, already-removed
        # dependency would itself report not_present) - so instead
        # confirm the shape/success/change fields the first call
        # already reported.
        self.assertTrue(result["application"]["success"])
        self.assertEqual(result["application"]["change_type"], direct["change_type"])
        self.assertEqual(result["application"]["target_step_id"], direct["target_step_id"])
        self.assertEqual(set(result["application"].keys()), set(direct.keys()))

    def test_application_result_has_the_documented_shape(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertIn("correction_validation", result)
        self.assertIn("application_performed", result)
        self.assertIn("application", result)
        for key in (
            "success", "reason_code", "reason", "plan_id", "change_id",
            "change_type", "target_step_id",
        ):
            self.assertIn(key, result["application"])

    def test_unsupported_change_type_is_reported_not_raised(self):
        """BLOCKER_FAILED_STEP's own CHANGE_MODIFY_STEP passes
        validate_proposal (it is a recognized, well-formed
        change_type) but ProposalApplier does not support applying it
        - apply_correction_proposal must surface that as a failed,
        structured application result, never raise and never pretend
        it succeeded."""
        self._fail_the_step()
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertTrue(result["correction_validation"]["ready_for_application"])
        self.assertTrue(result["application_performed"])
        self.assertFalse(result["application"]["success"])
        self.assertEqual(result["application"]["reason_code"], RESULT_UNSUPPORTED_CHANGE_TYPE)

    # ------------------------------------------------------------------
    # 5. The Plan reflects the validated change after successful
    #    application.
    # ------------------------------------------------------------------
    def test_plan_reflects_the_applied_change(self):
        step = self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        self.assertIn(
            "plan-999-step-1",
            self.plans.get_step(self.plan.plan_id, step.step_id).dependencies,
        )

        loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertNotIn(
            "plan-999-step-1",
            self.plans.get_step(self.plan.plan_id, step.step_id).dependencies,
        )

    def test_unsuccessful_application_leaves_the_plan_unmodified(self):
        self._fail_the_step()  # produces an unsupported CHANGE_MODIFY_STEP
        loop = self._loop_with_collaborators()

        before = self.plans.describe_plan(self.plan.plan_id)
        loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before, after)

    # ------------------------------------------------------------------
    # Proposal history integration.
    # ------------------------------------------------------------------
    def test_successful_application_is_recorded_in_proposal_history(self):
        self._dangling_dependency_step()
        history = ProposalHistory()
        loop = self._loop_with_collaborators(proposal_history=history)

        result = loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        records = history.get_all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["change_type"], CHANGE_REMOVE_DEPENDENCY)
        self.assertEqual(records[0]["result"], result["application"])

    def test_failed_application_is_not_recorded_in_proposal_history(self):
        self._fail_the_step()  # produces an unsupported CHANGE_MODIFY_STEP
        history = ProposalHistory()
        loop = self._loop_with_collaborators(proposal_history=history)

        loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertEqual(history.get_all(), [])

    def test_proposal_history_is_optional(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()  # no proposal_history supplied
        self.assertIsNone(loop.proposal_history)

        try:
            result = loop.apply_correction_proposal(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )
        except Exception as exc:  # pragma: no cover - failure path
            self.fail(f"apply_correction_proposal raised without a proposal_history: {exc!r}")
        self.assertTrue(result["application"]["success"])

    # ------------------------------------------------------------------
    # 6. Existing tests remain compatible.
    # ------------------------------------------------------------------
    def test_run_never_calls_apply_correction_proposal_automatically(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        self.assertNotIn("application", result)
        self.assertNotIn("application_performed", result)
        self.assertNotIn("correction_validation", result)

    def test_apply_correction_proposal_never_executes_a_step(self):
        step = self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        evaluation = GoalCompletionEvaluator(self.goals, self.plans).evaluate(
            self.goal.goal_id, self.plan.plan_id
        )
        self.assertEqual(evaluation["completed_steps"], [])

    def test_request_correction_validation_still_works_unaffected(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.request_correction_validation(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        self.assertTrue(result["ready_for_application"])

    def test_proposal_applier_is_optional_and_defaults_to_none(self):
        self.assertIsNone(self.loop._proposal_applier)

    def test_proposal_history_defaults_to_none_on_plain_agent_loop(self):
        self.assertIsNone(self.loop.proposal_history)


# --------------------------------------------------------------------
# Controlled step re-execution for an applied correction (Prompt 326) -
# connects AgentLoop.apply_correction_proposal (Prompt 325) to the
# existing StepExecutionController via
# AgentLoop.apply_correction_and_reexecute - never a second/duplicate
# execution system.
# --------------------------------------------------------------------
class TestApplyCorrectionAndReexecute(AgentLoopTestBase):
    def _fail_the_step(self):
        step = self._add_step()
        from planning.plan import STATUS_FAILED as STEP_STATUS_FAILED
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STEP_STATUS_FAILED)
        return step

    def _dangling_dependency_step(self, description="Review the code"):
        """A step with a dependency on a step_id that doesn't exist in
        this plan - BLOCKED_STEP -> CHANGE_REMOVE_DEPENDENCY (one of
        ProposalApplier's supported change types), so applying it
        really does mutate the Plan and unblock the step - READY (and
        so re-executable) once its status is refreshed."""
        step = self._add_step(description, dependencies=["plan-999-step-1"])
        self.plans.refresh_step_status(self.plan.plan_id, step.step_id)
        return step

    def _loop_with_collaborators(self, proposal_history=None):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        applier = ProposalApplier()
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
            proposal_applier=applier, proposal_history=proposal_history,
        )
        return loop

    # ------------------------------------------------------------------
    # 1. A successfully applied correction can trigger one controlled
    #    re-execution.
    # ------------------------------------------------------------------
    def test_successful_application_triggers_one_reexecution(self):
        step = self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertTrue(result["application"]["application"]["success"])
        self.assertTrue(result["reexecution_performed"])
        self.assertIsNotNone(result["reexecution_result"])
        self.assertTrue(result["reexecution_result"]["success"])
        self.assertEqual(result["reexecution_result"]["step_id"], step.step_id)

    def test_reexecution_actually_completes_the_step(self):
        step = self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status, STEP_STATUS_COMPLETED
        )

    # ------------------------------------------------------------------
    # 2. The affected step is the only step re-executed.
    # ------------------------------------------------------------------
    def test_only_the_affected_step_is_reexecuted(self):
        affected = self._dangling_dependency_step("Review the code")
        unrelated = self._add_step("An unrelated, independently READY step")
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertEqual(result["reexecution_result"]["step_id"], affected.step_id)
        # The unrelated, already-READY step was never touched by this
        # call - still PENDING/READY, never COMPLETED.
        self.assertNotEqual(
            self.plans.get_step(self.plan.plan_id, unrelated.step_id).status,
            STEP_STATUS_COMPLETED,
        )

    def test_no_second_step_executed_in_the_same_call(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        with mock.patch.object(
            loop._controller.step_controller, "execute_step",
            wraps=loop._controller.step_controller.execute_step,
        ) as spy:
            loop.apply_correction_and_reexecute(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )
            self.assertEqual(spy.call_count, 1)

    # ------------------------------------------------------------------
    # 3. A second automatic re-execution is prevented.
    # ------------------------------------------------------------------
    def test_second_call_does_not_reexecute_the_already_completed_step(self):
        """Calling apply_correction_and_reexecute a second time (for a
        freshly generated correction operation) never re-executes the
        already-COMPLETED step a second time - a COMPLETED step is not
        STATUS_READY, so the existing preparation gate itself refuses
        it, exactly as it would for any other already-terminal step."""
        step = self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        first = loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        self.assertTrue(first["reexecution_performed"])
        self.assertTrue(first["reexecution_result"]["success"])

        second = loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        # No new correction proposal is generated once the plan is
        # already complete/no longer blocked, so nothing is applied or
        # re-executed a second time.
        self.assertFalse(second["reexecution_performed"])
        self.assertIsNone(second["reexecution_result"])
        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status, STEP_STATUS_COMPLETED
        )

    def test_run_never_calls_apply_correction_and_reexecute_automatically(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        self.assertNotIn("reexecution_performed", result)
        self.assertNotIn("reexecution_result", result)

    # ------------------------------------------------------------------
    # 4. A failed correction application does not trigger
    #    re-execution.
    # ------------------------------------------------------------------
    def test_unsupported_change_type_does_not_trigger_reexecution(self):
        """BLOCKER_FAILED_STEP's own CHANGE_MODIFY_STEP passes
        validate_proposal but ProposalApplier does not support
        applying it - a failed application must never trigger
        re-execution."""
        step = self._fail_the_step()
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertTrue(result["application"]["application_performed"])
        self.assertFalse(result["application"]["application"]["success"])
        self.assertFalse(result["reexecution_performed"])
        self.assertIsNone(result["reexecution_result"])
        # The still-FAILED step was never touched by re-execution.
        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status, STEP_STATUS_FAILED
        )

    def test_no_proposal_never_triggers_reexecution(self):
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _passed_test_result()
        )

        self.assertFalse(result["application"]["application_performed"])
        self.assertFalse(result["reexecution_performed"])
        self.assertIsNone(result["reexecution_result"])

    def test_invalid_proposal_never_triggers_reexecution(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        real_result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        corrupted_result = copy.deepcopy(real_result)
        corrupted_result["proposal"]["proposed_changes"][0]["confidence"] = "not a number"

        with mock.patch.object(loop, "request_correction_proposal", return_value=corrupted_result):
            result = loop.apply_correction_and_reexecute(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )

        self.assertFalse(result["application"]["application_performed"])
        self.assertFalse(result["reexecution_performed"])
        self.assertIsNone(result["reexecution_result"])

    # ------------------------------------------------------------------
    # 5. The new execution result is preserved separately.
    # ------------------------------------------------------------------
    def test_reexecution_result_is_kept_separate_from_application_result(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertNotEqual(result["application"], result["reexecution_result"])
        self.assertNotIn("execution_id", result["application"]["application"])
        self.assertIn("execution_id", result["reexecution_result"])

    def test_reexecution_result_has_the_documented_shape(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        for key in (
            "success", "plan_id", "step_id", "execution_id", "step_status",
            "output", "error", "warnings", "events_recorded", "context", "data_flow",
        ):
            self.assertIn(key, result["reexecution_result"])

    def test_original_history_entry_is_not_overwritten(self):
        """The step's earlier FAILED attempt (if any real execution
        history exists for it) is never discarded - the new
        ExecutionResult is simply another, later entry, same
        convention ExecutionHistory already follows for every step."""
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        history_entries = self.controller.history.list_for_step(
            self.plan.plan_id, result["reexecution_result"]["step_id"],
        )
        self.assertIn(result["reexecution_result"]["execution_id"], [h.execution_id for h in history_entries])

    # ------------------------------------------------------------------
    # 6. Existing tests remain compatible.
    # ------------------------------------------------------------------
    def test_apply_correction_proposal_still_works_unaffected(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        self.assertTrue(result["application"]["success"])

    def test_execute_next_step_still_works_unaffected(self):
        self._add_step()
        result = self.loop.execute_next_step(self.plan.plan_id)
        self.assertTrue(result["executed"])

    def test_reexecute_requires_no_new_collaborator_types(self):
        # apply_correction_and_reexecute never requires anything beyond
        # what apply_correction_proposal already required.
        self._dangling_dependency_step()
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        applier = ProposalApplier()
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer, proposal_applier=applier,
        )
        result = loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        self.assertTrue(result["reexecution_performed"])


# --------------------------------------------------------------------
# Connecting the controlled re-execution result to the existing
# evaluation flow (Prompt 327) - AgentLoop.
# apply_correction_reexecute_and_evaluate connects
# apply_correction_and_reexecute (Prompt 326) to the existing
# evaluate_test_result (agent/test_result_evaluation.py) and
# GoalCompletionEvaluator (planning/goal_completion.py) systems -
# never a second/duplicate evaluation system.
# --------------------------------------------------------------------
class TestApplyCorrectionReexecuteAndEvaluate(AgentLoopTestBase):
    def _fail_the_step(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STEP_STATUS_FAILED)
        return step

    def _dangling_dependency_step(self, description="Review the code", required_capabilities=None):
        """Same BLOCKED_STEP -> CHANGE_REMOVE_DEPENDENCY setup
        `TestApplyCorrectionAndReexecute` already uses, extended with
        an optional `required_capabilities` so a registered handler
        can shape what the re-execution actually produces (a real
        `python_test_runner`-shaped output, or a raised exception)."""
        step = self._add_step(
            description, dependencies=["plan-999-step-1"],
            required_capabilities=required_capabilities,
        )
        self.plans.refresh_step_status(self.plan.plan_id, step.step_id)
        return step

    def _loop_with_collaborators(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        applier = ProposalApplier()
        return AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer, proposal_applier=applier,
        )

    # ------------------------------------------------------------------
    # 1. A successful re-execution is evaluated correctly.
    # ------------------------------------------------------------------
    def test_successful_reexecution_is_evaluated_as_passed(self):
        self._dangling_dependency_step(required_capabilities=["python_test_runner"])
        self._register_handler("python_test_runner", lambda ctx: _passed_test_result())
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_reexecute_and_evaluate(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertTrue(result["reexecution"]["reexecution_performed"])
        self.assertTrue(result["reexecution"]["reexecution_result"]["success"])
        self.assertTrue(result["evaluation_performed"])
        self.assertEqual(
            result["final_evaluation"]["reexecution_test_evaluation"]["classification"],
            RESULT_PASSED,
        )
        self.assertEqual(
            result["final_evaluation"]["goal_evaluation"]["status"], STATE_SATISFIED,
        )

    def test_reexecution_with_failed_test_output_is_classified_failed(self):
        """The re-executed capability call itself completes cleanly
        (COMPLETED, success=True at the step-execution level) but the
        test it ran reports failure - the test-result evaluation
        reused here classifies that the same way
        evaluate_test_result/evaluate_correction_decision already do
        for the original test_result, never conflating "the capability
        call completed" with "the test passed"."""
        self._dangling_dependency_step(required_capabilities=["python_test_runner"])
        self._register_handler("python_test_runner", lambda ctx: _failed_test_result())
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_reexecute_and_evaluate(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertTrue(result["reexecution"]["reexecution_performed"])
        self.assertTrue(result["reexecution"]["reexecution_result"]["success"])
        self.assertTrue(result["evaluation_performed"])
        self.assertEqual(
            result["final_evaluation"]["reexecution_test_evaluation"]["classification"],
            RESULT_FAILED,
        )

    # ------------------------------------------------------------------
    # 2. A failed re-execution is evaluated correctly.
    # ------------------------------------------------------------------
    def test_failed_reexecution_is_still_evaluated(self):
        """A re-execution that itself FAILS (the capability call
        raised) is still connected to the existing evaluation flow -
        evaluation is never skipped just because the new attempt
        failed, so the loop's final evaluation state always reflects
        what actually happened."""
        self._dangling_dependency_step(required_capabilities=["boom"])

        def failing_handler(ctx):
            raise RuntimeError("kaboom")

        self._register_handler("boom", failing_handler)
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_reexecute_and_evaluate(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertTrue(result["reexecution"]["reexecution_performed"])
        self.assertFalse(result["reexecution"]["reexecution_result"]["success"])
        self.assertTrue(result["evaluation_performed"])
        # No python_test_runner-shaped output exists for a failed
        # capability call (output is None) - reused classifier reports
        # that honestly as INVALID, never guessed at as PASSED/FAILED.
        self.assertEqual(
            result["final_evaluation"]["reexecution_test_evaluation"]["classification"],
            RESULT_INVALID,
        )
        self.assertEqual(
            result["final_evaluation"]["goal_evaluation"]["status"], STATE_FAILED,
        )

    def test_no_reexecution_means_no_evaluation(self):
        """`reexecution_performed=False` (an unsupported change type,
        no proposal ready, or an invalid proposal) means nothing was
        re-executed, so nothing is evaluated either - "evaluate its
        result" only applies once there actually is a new result."""
        self._fail_the_step()  # produces an unsupported CHANGE_MODIFY_STEP
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_reexecute_and_evaluate(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        self.assertFalse(result["reexecution"]["reexecution_performed"])
        self.assertFalse(result["evaluation_performed"])
        self.assertIsNone(result["final_evaluation"])

    # ------------------------------------------------------------------
    # 3. Original and re-execution results remain separate.
    # ------------------------------------------------------------------
    def test_original_and_reexecution_results_remain_separate(self):
        self._dangling_dependency_step(required_capabilities=["python_test_runner"])
        self._register_handler("python_test_runner", lambda ctx: _passed_test_result())
        loop = self._loop_with_collaborators()

        original_application = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        result = loop.apply_correction_reexecute_and_evaluate(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        # The original correction-application result is preserved,
        # completely unmodified, alongside the new re-execution result
        # and the new evaluation - never merged into one another.
        self.assertNotEqual(
            result["reexecution"]["application"], result["reexecution"]["reexecution_result"],
        )
        self.assertNotIn("execution_id", result["reexecution"]["application"]["application"])
        self.assertIn("execution_id", result["reexecution"]["reexecution_result"])
        self.assertNotEqual(
            result["reexecution"]["reexecution_result"],
            result["final_evaluation"]["reexecution_test_evaluation"],
        )
        self.assertNotEqual(
            result["reexecution"]["reexecution_result"],
            result["final_evaluation"]["goal_evaluation"],
        )
        # The earlier, independently-read application result (from a
        # completely separate call) is unaffected by this one.
        self.assertFalse(original_application["proposal_performed"] is None)

    # ------------------------------------------------------------------
    # 4. The final evaluation is exposed through AgentLoop.
    # ------------------------------------------------------------------
    def test_final_evaluation_is_exposed_with_the_documented_shape(self):
        self._dangling_dependency_step(required_capabilities=["python_test_runner"])
        self._register_handler("python_test_runner", lambda ctx: _passed_test_result())
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_reexecute_and_evaluate(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )

        for key in ("reexecution", "evaluation_performed", "final_evaluation"):
            self.assertIn(key, result)
        for key in ("reexecution_test_evaluation", "goal_evaluation"):
            self.assertIn(key, result["final_evaluation"])
        self.assertIn("classification", result["final_evaluation"]["reexecution_test_evaluation"])
        self.assertIn("test_result", result["final_evaluation"]["reexecution_test_evaluation"])
        self.assertIn("status", result["final_evaluation"]["goal_evaluation"])

    # ------------------------------------------------------------------
    # 5. No second correction/re-execution is triggered automatically.
    # ------------------------------------------------------------------
    def test_no_second_correction_or_reexecution_is_triggered(self):
        self._dangling_dependency_step(required_capabilities=["python_test_runner"])
        self._register_handler("python_test_runner", lambda ctx: _passed_test_result())
        loop = self._loop_with_collaborators()

        with mock.patch.object(
            loop, "apply_correction_proposal", wraps=loop.apply_correction_proposal,
        ) as apply_spy, mock.patch.object(
            loop._controller.step_controller, "execute_step",
            wraps=loop._controller.step_controller.execute_step,
        ) as execute_spy:
            loop.apply_correction_reexecute_and_evaluate(
                self.goal.goal_id, self.plan.plan_id, _failed_test_result()
            )

        self.assertEqual(apply_spy.call_count, 1)
        self.assertEqual(execute_spy.call_count, 1)

    def test_run_never_calls_apply_correction_reexecute_and_evaluate_automatically(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        self.assertNotIn("evaluation_performed", result)
        self.assertNotIn("final_evaluation", result)

    # ------------------------------------------------------------------
    # 6. Existing tests remain compatible.
    # ------------------------------------------------------------------
    def test_apply_correction_and_reexecute_still_works_unaffected(self):
        self._dangling_dependency_step()
        loop = self._loop_with_collaborators()

        result = loop.apply_correction_and_reexecute(
            self.goal.goal_id, self.plan.plan_id, _failed_test_result()
        )
        self.assertTrue(result["reexecution_performed"])
        # The plain apply_correction_and_reexecute result shape is
        # unchanged - no new keys were added to it.
        self.assertEqual(
            set(result.keys()), {"application", "reexecution_performed", "reexecution_result"},
        )

    def test_evaluate_test_result_still_works_unaffected(self):
        result = self.loop.evaluate_test_result(_passed_test_result())
        self.assertEqual(result["classification"], RESULT_PASSED)

    def test_goal_completion_evaluator_still_works_unaffected(self):
        self._add_step()
        evaluation = GoalCompletionEvaluator(self.goals, self.plans).evaluate(
            self.goal.goal_id, self.plan.plan_id
        )
        self.assertIn("status", evaluation)


# --------------------------------------------------------------------
# Adaptive plan proposal integration (planning/adaptive_plan_proposal.py)
# --------------------------------------------------------------------
class TestRequestProposal(AgentLoopTestBase):
    def test_proposal_generator_is_optional_and_defaults_to_none(self):
        self.assertIsNone(self.loop._proposal_generator)

    def test_rejects_wrong_type_proposal_generator(self):
        with self.assertRaises(TypeError):
            AgentLoop(self.goals, self.plans, self.controller, proposal_generator="not a proposer")

    def test_request_proposal_without_generator_raises(self):
        with self.assertRaises(ValueError):
            self.loop.request_proposal(self.goal.goal_id, self.plan.plan_id)

    def test_request_proposal_delegates_to_proposal_generator(self):
        self._add_step()  # left pending -> goal not satisfied, but no blockers
        proposer = AdaptivePlanProposal(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, proposal_generator=proposer)

        result = loop.request_proposal(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["status"], PROPOSAL_NO_CHANGE_NEEDED)
        self.assertEqual(result["goal_id"], self.goal.goal_id)
        self.assertEqual(result["plan_id"], self.plan.plan_id)

    def test_run_never_calls_proposal_generator_automatically(self):
        self._add_step()
        proposer = AdaptivePlanProposal(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, proposal_generator=proposer)
        result = loop.run(self.goal.goal_id, self.plan.plan_id)
        self.assertIn(result["status"], ALL_AGENT_LOOP_STATUSES)

    def test_request_proposal_never_applies_or_mutates_plan(self):
        step = self._add_step()
        from planning.plan import STATUS_FAILED
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_FAILED)
        proposer = AdaptivePlanProposal(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, proposal_generator=proposer)

        before = self.plans.describe_plan(self.plan.plan_id)
        loop.request_proposal(self.goal.goal_id, self.plan.plan_id)
        after = self.plans.describe_plan(self.plan.plan_id)
        self.assertEqual(before, after)


# --------------------------------------------------------------------
# Prompt 307: existing Learning system (LearningRecordStore) ->
# existing AgentLoop
# --------------------------------------------------------------------
class TestLearningRecordStoreConstruction(unittest.TestCase):
    def test_rejects_wrong_type_learning_record_store(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        with self.assertRaises(TypeError):
            AgentLoop(goals, plans, controller, learning_record_store="nope")

    def test_defaults_to_none(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        loop = AgentLoop(goals, plans, controller)
        self.assertIsNone(loop.learning_records)

    def test_accepts_an_explicit_store(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        store = LearningRecordStore()
        loop = AgentLoop(goals, plans, controller, learning_record_store=store)
        self.assertIs(loop.learning_records, store)


class TestAgentLoopCanAccessExistingLearningRecords(AgentLoopTestBase):
    def setUp(self):
        super().setUp()
        self.store = LearningRecordStore()
        self.loop = AgentLoop(
            self.goals, self.plans, self.controller, learning_record_store=self.store,
        )

    def _add_record(self, plan_id, step_id, outcome="success", confidence=1.0):
        record = LearningRecord(
            source="execution_system",
            pattern=f"step:{step_id}",
            outcome=outcome,
            confidence=confidence,
            metadata={"plan_id": plan_id, "step_id": step_id, "execution_id": "execution-1"},
        )
        self.store.add(record)
        return record

    def test_relevant_learning_records_are_readable_via_the_shared_store(self):
        step = self._add_step()
        self._add_record(self.plan.plan_id, step.step_id)

        # Same instance the loop itself reads - no second, private store.
        self.assertIs(self.loop.learning_records, self.store)
        self.assertEqual(len(self.loop.learning_records.get_all()), 1)


class TestLearningDataAvailableInResult(AgentLoopTestBase):
    def setUp(self):
        super().setUp()
        self.store = LearningRecordStore()
        self.loop = AgentLoop(
            self.goals, self.plans, self.controller, learning_record_store=self.store,
        )

    def _add_record(self, plan_id, step_id, outcome="success", confidence=1.0):
        record = LearningRecord(
            source="execution_system",
            pattern=f"step:{step_id}",
            outcome=outcome,
            confidence=confidence,
            metadata={"plan_id": plan_id, "step_id": step_id, "execution_id": "execution-1"},
        )
        self.store.add(record)
        return record

    def test_result_exposes_relevant_records_for_this_plan(self):
        step = self._add_step()
        self._add_record(self.plan.plan_id, step.step_id)

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(len(result["learning_context"]), 1)
        entry = result["learning_context"][0]
        self.assertEqual(entry["metadata"]["plan_id"], self.plan.plan_id)
        self.assertEqual(entry["outcome"], "success")

    def test_result_excludes_records_for_a_different_plan(self):
        step = self._add_step()
        other_goal = self.goals.create_goal("A different goal")
        other_plan = self.plans.create_plan(other_goal.goal_id)
        self._add_record(other_plan.plan_id, "some-other-step")

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["learning_context"], [])

    def test_learning_context_entries_are_plain_dicts(self):
        step = self._add_step()
        self._add_record(self.plan.plan_id, step.step_id)

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        for entry in result["learning_context"]:
            self.assertIsInstance(entry, dict)
            self.assertNotIsInstance(entry, LearningRecord)


class TestAgentLoopStillRespectsIterationLimit(AgentLoopTestBase):
    """Adding learning-record access must not loosen max_iterations'
    own validation or budget enforcement (Prompt 307 requirement:
    'preserve the existing AgentLoop iteration limits and safety
    rules')."""

    def setUp(self):
        super().setUp()
        self.store = LearningRecordStore()
        self.loop = AgentLoop(
            self.goals, self.plans, self.controller, learning_record_store=self.store,
        )

    def test_invalid_max_iterations_still_raises(self):
        self._add_step()
        with self.assertRaises(ValueError):
            self.loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=0)

    def test_still_stops_at_max_iterations_with_steps_remaining(self):
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(
            self.goals, self.plans, controller, learning_record_store=self.store,
        )
        first = self._add_step("First step")
        second = self._add_step("Second step", dependencies=[first.step_id])

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        self.assertEqual(result["iterations"], 1)
        self.assertEqual(result["status"], STATUS_MAX_ITERATIONS_REACHED)

    def test_run_is_never_called_recursively_with_learning_wired(self):
        import inspect
        source = inspect.getsource(AgentLoop.run)
        self.assertNotIn("self.run(", source)


class TestMissingLearningDataIsHandledSafely(AgentLoopTestBase):
    def test_no_store_supplied_returns_empty_learning_context(self):
        """self.loop (from AgentLoopTestBase) was built with no
        learning_record_store at all."""
        self._add_step()
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)
        self.assertEqual(result["learning_context"], [])

    def test_empty_store_returns_empty_learning_context(self):
        store = LearningRecordStore()
        loop = AgentLoop(self.goals, self.plans, self.controller, learning_record_store=store)
        self._add_step()

        result = loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["learning_context"], [])

    def test_invalid_input_still_reports_empty_learning_context(self):
        store = LearningRecordStore()
        loop = AgentLoop(self.goals, self.plans, self.controller, learning_record_store=store)

        result = loop.run("unknown-goal", "unknown-plan")

        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertEqual(result["learning_context"], [])


class TestExistingExecutionBehaviorRemainsUnchanged(AgentLoopTestBase):
    """Re-confirms run()'s own decision logic (goal_status, success,
    executed_steps, etc.) is identical whether or not a
    learning_record_store was supplied."""

    def test_single_step_completion_is_identical_with_and_without_a_store(self):
        step = self._add_step()

        def handler(plan_step):
            return {"done": True}

        self._register_handler("noop", handler)
        # No capability required, so it completes trivially either way.
        loop_without = AgentLoop(self.goals, self.plans, self.controller)
        result_without = loop_without.run(self.goal.goal_id, self.plan.plan_id)

        # Fresh, identical setup, this time with a learning store wired in.
        goals2 = GoalManager()
        plans2 = PlanManager(goals2)
        controller2 = PlanExecutionController(plans2)
        goal2 = goals2.create_goal("Ship a small feature")
        plan2 = plans2.create_plan(goal2.goal_id)
        plans2.add_step(plan2.plan_id, "Do the thing")
        store = LearningRecordStore()
        loop_with = AgentLoop(goals2, plans2, controller2, learning_record_store=store)
        result_with = loop_with.run(goal2.goal_id, plan2.plan_id)

        for key in (
            "success", "status", "iterations", "goal_status",
            "executed_steps", "completed_steps", "failed_steps",
            "blocked_steps", "outputs", "error",
        ):
            self.assertEqual(result_without[key], result_with[key])

    def test_run_never_writes_to_the_learning_record_store(self):
        step = self._add_step()
        store = LearningRecordStore()
        loop = AgentLoop(self.goals, self.plans, self.controller, learning_record_store=store)

        loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(len(store.get_all()), 0)

    def test_run_never_mutates_a_record_it_reads(self):
        step = self._add_step()
        store = LearningRecordStore()
        record = LearningRecord(
            source="execution_system", pattern=f"step:{step.step_id}",
            outcome="success", confidence=1.0,
            metadata={"plan_id": self.plan.plan_id, "step_id": step.step_id},
        )
        store.add(record)
        loop = AgentLoop(self.goals, self.plans, self.controller, learning_record_store=store)

        loop.run(self.goal.goal_id, self.plan.plan_id)

        stored = store.get(record.record_id)
        self.assertEqual(stored.outcome, "success")
        self.assertEqual(stored.confidence, 1.0)


class TestExistingAgentLoopTestsRemainCompatible(AgentLoopTestBase):
    """Re-confirms a handful of pre-existing scenarios (satisfied,
    failed, max_iterations>1) still behave exactly as before now that
    every result also carries a learning_context key."""

    def test_already_satisfied_goal_now_also_reports_empty_learning_context(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STEP_STATUS_COMPLETED)

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATUS_SATISFIED)
        self.assertEqual(result["learning_context"], [])

    def test_unknown_goal_id_result_shape_includes_learning_context(self):
        result = self.loop.run("does-not-exist", "also-does-not-exist")
        self.assertIn("learning_context", result)
        self.assertEqual(result["learning_context"], [])


# --------------------------------------------------------------------
# Prompt 308: existing GoalCompletionEvaluator -> existing AgentLoop
# --------------------------------------------------------------------
class TestAgentLoopEvaluatesGoalCompletionAfterExecution(AgentLoopTestBase):
    def test_evaluator_is_consulted_both_before_and_after_execution(self):
        """AgentLoop must call the existing GoalCompletionEvaluator
        again after an execution cycle, not only before it - never a
        second, disagreeing implementation of completion logic."""
        from unittest.mock import patch

        self._add_step()
        real_evaluate = self.loop._evaluator.evaluate

        with patch.object(
            self.loop._evaluator, "evaluate", side_effect=real_evaluate
        ) as spy:
            result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        # Once before execution (goal not yet satisfied) and once
        # again after PlanExecutionController.execute_plan ran.
        self.assertGreaterEqual(spy.call_count, 2)
        for call in spy.call_args_list:
            self.assertEqual(call.args, (self.goal.goal_id, self.plan.plan_id))
        self.assertEqual(result["status"], STATUS_SATISFIED)

    def test_no_evaluator_of_its_own_is_constructed_when_execution_happens(self):
        """The evaluator instance used before and after execution is
        the exact same object - AgentLoop never builds a second
        GoalCompletionEvaluator mid-run."""
        self._add_step()
        evaluator_before = self.loop._evaluator
        self.loop.run(self.goal.goal_id, self.plan.plan_id)
        self.assertIs(self.loop._evaluator, evaluator_before)


class TestSatisfiedIsReportedCorrectly(AgentLoopTestBase):
    def test_goal_status_is_satisfied_after_a_completed_step(self):
        self._add_step()
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["goal_status"], STATE_SATISFIED)
        self.assertEqual(result["status"], STATUS_SATISFIED)
        self.assertTrue(result["success"])

    def test_already_satisfied_goal_reports_satisfied_without_executing(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STEP_STATUS_COMPLETED)

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["goal_status"], STATE_SATISFIED)
        self.assertEqual(result["executed_steps"], [])


class TestNotSatisfiedIsReportedCorrectly(AgentLoopTestBase):
    def test_goal_status_is_not_satisfied_when_nothing_completes(self):
        """An empty Plan has nothing to complete - GoalCompletionEvaluator
        reports STATE_UNKNOWN (total == 0), and AgentLoop preserves
        that exact state rather than reinterpreting it as satisfied."""
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["goal_status"], STATE_UNKNOWN)
        self.assertEqual(result["status"], STATUS_UNKNOWN)

    def test_goal_status_is_partially_satisfied_when_some_but_not_all_steps_complete(self):
        """Two independent (no-dependency) steps, but the controller
        itself is capped at one step per run() call - so after this
        one AgentLoop iteration, one step is COMPLETED and the other
        is still un-run (remaining), which is exactly
        GoalCompletionEvaluator's own PARTIALLY_SATISFIED rule (some,
        not all, steps COMPLETED, and something still unresolved)."""
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)
        self._add_step("First step")
        self._add_step("Second step")

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        self.assertEqual(result["goal_status"], STATE_PARTIALLY_SATISFIED)
        self.assertEqual(result["status"], STATUS_MAX_ITERATIONS_REACHED)
        self.assertEqual(len(result["completed_steps"]), 1)


class TestBlockedOrFailedStatesArePreservedCorrectly(AgentLoopTestBase):
    def test_blocked_goal_status_is_preserved(self):
        # A dependency on a step_id that can never exist/complete keeps
        # this step BLOCKED forever - purely from PlanManager's own
        # dependency-resolution logic, reused unchanged by
        # GoalCompletionEvaluator._classify_steps.
        self._add_step("Needs a step that will never exist", dependencies=["no-such-step"])

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["goal_status"], STATE_BLOCKED)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertTrue(result["success"])

    def test_failed_goal_status_is_preserved(self):
        step = self._add_step("Will fail")

        def failing_handler(plan_step):
            raise ValueError("boom")

        step.required_capabilities = ["explode"]
        self._register_handler("explode", failing_handler)
        self.plans.refresh_step_status(self.plan.plan_id, step.step_id)

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["goal_status"], STATE_FAILED)
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertFalse(result["success"])

    def test_previously_failed_goal_state_is_reported_without_retry(self):
        step = self._add_step("Already failed")
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STEP_STATUS_FAILED)

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["goal_status"], STATE_FAILED)
        self.assertEqual(result["executed_steps"], [])


class TestMissingGoalDataIsHandledSafely(AgentLoopTestBase):
    def test_unknown_goal_id_reports_unknown_goal_status(self):
        result = self.loop.run("goal-does-not-exist", self.plan.plan_id)

        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertEqual(result["goal_status"], STATE_UNKNOWN)
        self.assertFalse(result["success"])

    def test_unknown_plan_id_reports_unknown_goal_status(self):
        result = self.loop.run(self.goal.goal_id, "plan-does-not-exist")

        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertEqual(result["goal_status"], STATE_UNKNOWN)

    def test_plan_goal_mismatch_reports_unknown_goal_status_without_evaluating(self):
        from unittest.mock import patch

        other_goal = self.goals.create_goal("A different goal")
        with patch.object(self.loop._evaluator, "evaluate") as spy:
            result = self.loop.run(other_goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertEqual(result["goal_status"], STATE_UNKNOWN)
        spy.assert_not_called()


class TestExistingAgentLoopAndFullSuiteRemainCompatible(AgentLoopTestBase):
    """Re-confirms the pre-existing evaluator-integration scenarios
    still behave exactly as before."""

    def test_two_step_plan_still_completes_and_reports_satisfied(self):
        self._add_step("First")
        self._add_step("Second")

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["goal_status"], STATE_SATISFIED)
        self.assertEqual(result["status"], STATUS_SATISFIED)

    def test_max_iterations_limit_is_still_enforced(self):
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)
        self._add_step("First")
        self._add_step("Second")

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        self.assertEqual(result["iterations"], 1)
        with self.assertRaises(ValueError):
            loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=0)


# --------------------------------------------------------------------
# Prompt 309: existing PlanExecutionCoordinator -> existing AgentLoop
#
# AgentLoop.run()'s result now carries a "next_step" field, populated
# via the existing PlanExecutionCoordinator.get_next_ready_step
# (execution/plan_execution_coordinator.py) - reused unchanged, through
# the existing PlanExecutionController's own coordinator (never a
# second, disagreeing one). This is a read-only lookahead: it may
# identify the next READY, executable step when the Goal is not
# satisfied, but it never executes that step, never creates a new
# PlanStep, and never modifies the Plan.
# --------------------------------------------------------------------
class TestAgentLoopIdentifiesNextReadyStep(AgentLoopTestBase):
    def test_unsatisfied_goal_identifies_the_next_ready_step(self):
        """Requirement 1 (positive case) + requirement 5: two
        independent steps, but the controller is capped at one step
        per run() call, so after one AgentLoop iteration the first
        step is COMPLETED, the Goal is not yet satisfied, and the
        second, still-untouched step is correctly identified as the
        next READY, executable one - without this operation executing
        it."""
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)
        first = self._add_step("First step")
        second = self._add_step("Second step")

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        self.assertEqual(result["status"], STATUS_MAX_ITERATIONS_REACHED)
        self.assertNotEqual(result["status"], STATUS_SATISFIED)
        self.assertEqual(result["executed_steps"], [first.step_id])
        self.assertIsNotNone(result["next_step"])
        self.assertEqual(result["next_step"]["step_id"], second.step_id)
        self.assertTrue(result["next_step"]["executable"])

    def test_satisfied_goal_does_not_select_another_step(self):
        """Requirement 2: once the Goal is satisfied, AgentLoop stops
        without selecting (or executing) any further step, even
        though a caller could add more steps to this same Plan
        later."""
        self._add_step()

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATUS_SATISFIED)
        self.assertIsNone(result["next_step"])

    def test_blocked_step_is_not_selected(self):
        """Requirement 3: a step BLOCKED on a dependency that can
        never resolve is never identified as the next step - the
        existing PlanExecutionCoordinator.get_next_ready_step only
        ever considers STATUS_READY steps, and this AgentLoop-level
        lookahead never re-derives or bypasses that."""
        self._add_step("Needs a step that will never exist", dependencies=["no-such-step"])

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertIsNotNone(result["next_step"])
        self.assertIsNone(result["next_step"]["step_id"])
        self.assertFalse(result["next_step"]["executable"])

    def test_step_with_missing_capabilities_is_not_selected(self):
        """Requirement 4: a READY step whose required capability has
        no registered handler is never identified as executable -
        respects the existing capability-readiness check
        PlanExecutionCoordinator already applies."""
        self._add_step("Needs a capability", required_capabilities=["net_fetch"])
        # Deliberately never registered via self._register_handler.

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertIsNotNone(result["next_step"])
        self.assertIsNone(result["next_step"]["step_id"])
        self.assertFalse(result["next_step"]["executable"])
        self.assertTrue(result["next_step"]["warnings"])

    def test_no_step_is_executed_by_identifying_the_next_step(self):
        """Requirement 5: identifying the next step is strictly
        read-only. The step this lookahead identifies as executable
        remains untouched (still READY, no output recorded) by this
        same run() call - executing it is still a separate action for
        a later run()/execute_plan call to perform."""
        controller = PlanExecutionController(self.plans, max_steps_per_run=1)
        loop = AgentLoop(self.goals, self.plans, controller)
        self._add_step("First step")
        second = self._add_step("Second step")

        result = loop.run(self.goal.goal_id, self.plan.plan_id, max_iterations=1)

        self.assertEqual(result["next_step"]["step_id"], second.step_id)
        self.assertNotIn(second.step_id, result["executed_steps"])
        self.assertNotIn(second.step_id, result["outputs"])
        # The identified step's own status is untouched by the
        # lookahead - still exactly what PlanManager already left it
        # as (READY - eligible, but never run by this call).
        from planning.plan import STATUS_READY as STEP_STATUS_READY
        self.assertEqual(second.status, STEP_STATUS_READY)

    def test_invalid_input_reports_no_next_step(self):
        """An unknown goal_id/plan_id never even reaches a confirmed,
        real Plan, so there is nothing real to ask
        PlanExecutionCoordinator about."""
        result = self.loop.run("goal-does-not-exist", self.plan.plan_id)
        self.assertEqual(result["status"], STATUS_INVALID)
        self.assertIsNone(result["next_step"])

    def test_uses_the_controllers_shared_coordinator_not_a_second_one(self):
        """The lookahead must reuse the exact same
        PlanExecutionCoordinator (and therefore the exact same
        CapabilityHandlerRegistry/ExecutableCapabilityRegistry)
        execute_plan itself already uses - never a second,
        independently-constructed coordinator that could disagree."""
        from unittest.mock import patch

        self._add_step("Needs a capability", required_capabilities=["net_fetch"])
        real_get_next = self.controller.coordinator.get_next_ready_step

        with patch.object(
            self.controller.coordinator, "get_next_ready_step", side_effect=real_get_next,
        ) as spy:
            result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertGreaterEqual(spy.call_count, 1)
        self.assertIsNotNone(result["next_step"])

    def test_next_step_result_shape(self):
        step = self._add_step("Needs a capability", required_capabilities=["net_fetch"])
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        for key in ("step_id", "executable", "reason", "warnings"):
            self.assertIn(key, result["next_step"])
        self.assertIsInstance(result["next_step"]["warnings"], list)
        # Never the raw PlanStep object - stays plain/JSON-shaped, same
        # convention as every other AgentLoop result field.
        self.assertNotIn("step", result["next_step"])


# --------------------------------------------------------------------
# Requirement 6: existing tests remain compatible - re-confirms every
# scenario already covered above (satisfied, not satisfied, blocked,
# failed, max_iterations, invalid input, multi-iteration, learning
# context, event logging, ...) still behaves exactly as before now
# that "next_step" has been added to the result shape.
# --------------------------------------------------------------------
class TestNextStepAdditionIsBackwardCompatible(AgentLoopTestBase):
    def test_existing_result_keys_are_all_still_present(self):
        self._add_step()
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)
        for key in (
            "success", "goal_id", "plan_id", "status", "iterations", "goal_status",
            "executed_steps", "completed_steps", "failed_steps", "blocked_steps",
            "outputs", "evidence", "warnings", "error", "learning_context",
        ):
            self.assertIn(key, result)

    def test_next_step_is_always_present_even_when_none(self):
        self._add_step()
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)
        self.assertIn("next_step", result)

    def test_full_agent_loop_suite_scenarios_unaffected(self):
        """A quick re-run of the plain two-step, fully-satisfied
        scenario (same as TestExistingAgentLoopAndFullSuiteRemainCompatible)
        to confirm the new field is purely additive."""
        self._add_step("First")
        self._add_step("Second")

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertEqual(result["goal_status"], STATE_SATISFIED)
        self.assertEqual(result["status"], STATUS_SATISFIED)
        self.assertIsNone(result["next_step"])


# --------------------------------------------------------------------
# Prompt 310: connect the existing AgentLoop next-step selection
# (Prompt 309's `_identify_next_step`, exposed read-only as
# "next_step") to controlled step execution via
# `AgentLoop.execute_next_step`. Reuses the existing
# `PlanExecutionCoordinator` (via `_identify_next_step`) and the
# existing `StepExecutionController` (via
# `PlanExecutionController.step_controller.execute_step`) unchanged -
# never a second, disagreeing implementation of either. This is a
# separate, explicitly-invoked action; it never changes `run()`'s own
# existing whole-plan-execution behavior (see the many
# `run()`-based tests above, all still passing unmodified).
# --------------------------------------------------------------------
class TestExecuteNextStep(AgentLoopTestBase):
    def test_ready_selected_step_can_be_executed(self):
        """1. A READY selected step can be executed by AgentLoop."""
        step = self._add_step("Only step")

        result = self.loop.execute_next_step(self.plan.plan_id)

        self.assertTrue(result["executed"])
        self.assertEqual(result["step_id"], step.step_id)
        self.assertTrue(result["success"])
        self.assertIsNotNone(result["execution_result"])
        self.assertEqual(result["execution_result"]["step_id"], step.step_id)
        from planning.plan import STATUS_COMPLETED as STEP_STATUS_COMPLETED_LOCAL
        self.assertEqual(step.status, STEP_STATUS_COMPLETED_LOCAL)

    def test_at_most_one_step_executes_per_call(self):
        """2. At most one step executes per iteration/call, even when
        a second, independent READY step also exists."""
        first = self._add_step("First step")
        second = self._add_step("Second step")

        result = self.loop.execute_next_step(self.plan.plan_id)

        self.assertTrue(result["executed"])
        # Exactly one of the two READY steps was executed.
        self.assertIn(result["step_id"], {first.step_id, second.step_id})
        from planning.plan import STATUS_READY as STEP_STATUS_READY_LOCAL
        executed_id = result["step_id"]
        untouched_id = second.step_id if executed_id == first.step_id else first.step_id
        untouched_step = self.plans.get_step(self.plan.plan_id, untouched_id)
        self.assertEqual(untouched_step.status, STEP_STATUS_READY_LOCAL)

    def test_blocked_step_is_never_executed(self):
        """3. A blocked step is never executed."""
        self._add_step("Stuck", dependencies=["missing-step"])

        result = self.loop.execute_next_step(self.plan.plan_id)

        self.assertFalse(result["executed"])
        self.assertIsNone(result["step_id"])
        self.assertIsNone(result["success"])
        self.assertIsNone(result["execution_result"])
        self.assertEqual(len(self.controller.history), 0)

    def test_step_with_missing_capabilities_is_never_executed(self):
        """4. A step with missing capabilities is never executed."""
        self._add_step("Needs a capability", required_capabilities=["net_fetch"])
        # Deliberately never registered via self._register_handler.

        result = self.loop.execute_next_step(self.plan.plan_id)

        self.assertFalse(result["executed"])
        self.assertIsNone(result["step_id"])
        self.assertIsNone(result["execution_result"])
        self.assertEqual(len(self.controller.history), 0)

    def test_failed_execution_does_not_trigger_automatic_retry(self):
        """5. Failed execution does not trigger automatic retry."""
        step = self._add_step("Will fail", required_capabilities=["boom"])
        attempts = {"count": 0}

        def failing_handler(step_arg):
            attempts["count"] += 1
            raise RuntimeError("kaboom")

        self._register_handler("boom", failing_handler)

        first = self.loop.execute_next_step(self.plan.plan_id)
        second = self.loop.execute_next_step(self.plan.plan_id)

        self.assertTrue(first["executed"])
        self.assertFalse(first["success"])
        self.assertEqual(attempts["count"], 1)

        # The now-FAILED step is no longer STATUS_READY, so a second
        # call never re-selects or re-executes it - no retry.
        self.assertFalse(second["executed"])
        self.assertIsNone(second["step_id"])
        self.assertEqual(attempts["count"], 1)
        self.assertEqual(step.status, STEP_STATUS_FAILED)

    def test_nothing_executed_when_goal_already_satisfied(self):
        """Selecting/executing the next step is still governed by the
        same READY/executable checks when there is nothing left to do
        - an empty or fully-completed plan never causes an execution."""
        result = self.loop.execute_next_step(self.plan.plan_id)
        self.assertFalse(result["executed"])
        self.assertIsNone(result["step_id"])

    def test_reuses_the_controllers_shared_coordinator_and_step_controller(self):
        """Reuses the existing PlanExecutionCoordinator and existing
        StepExecutionController - never a second, disagreeing
        implementation of either."""
        from unittest.mock import patch

        step = self._add_step("Only step")
        real_execute_step = self.controller.step_controller.execute_step

        with patch.object(
            self.controller.step_controller, "execute_step",
            side_effect=real_execute_step,
        ) as spy:
            result = self.loop.execute_next_step(self.plan.plan_id)

        spy.assert_called_once_with(
            self.plan.plan_id, step.step_id, capability_system=None,
        )
        self.assertTrue(result["executed"])

    def test_does_not_create_a_new_plan_step(self):
        before = len(self.plans.get_plan(self.plan.plan_id).steps)
        self._add_step("Only step")
        after_add = len(self.plans.get_plan(self.plan.plan_id).steps)
        self.loop.execute_next_step(self.plan.plan_id)
        after_execute = len(self.plans.get_plan(self.plan.plan_id).steps)
        self.assertEqual(after_add, before + 1)
        self.assertEqual(after_execute, after_add)


# --------------------------------------------------------------------
# 6. Existing AgentLoop and full-suite tests remain compatible: adding
# `execute_next_step` must not change anything about `run()`'s own
# existing behavior. Re-runs a representative slice of the scenarios
# already covered above.
# --------------------------------------------------------------------
class TestExecuteNextStepIsBackwardCompatible(AgentLoopTestBase):
    def test_run_still_completes_a_two_step_plan_in_one_call(self):
        step1 = self._add_step("First")
        step2 = self._add_step("Second", dependencies=[step1.step_id])

        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], STATUS_SATISFIED)
        self.assertEqual(set(result["completed_steps"]), {step1.step_id, step2.step_id})

    def test_run_and_execute_next_step_can_coexist(self):
        """Calling execute_next_step does not disturb a subsequent
        run() call's own, unchanged whole-plan-execution behavior."""
        step1 = self._add_step("First")
        step2 = self._add_step("Second", dependencies=[step1.step_id])

        next_step_result = self.loop.execute_next_step(self.plan.plan_id)
        self.assertTrue(next_step_result["executed"])
        self.assertEqual(next_step_result["step_id"], step1.step_id)

        run_result = self.loop.run(self.goal.goal_id, self.plan.plan_id)
        self.assertTrue(run_result["success"])
        self.assertEqual(run_result["status"], STATUS_SATISFIED)
        self.assertEqual(run_result["executed_steps"], [step2.step_id])

    def test_agent_loop_result_shape_unaffected_by_new_method(self):
        self._add_step("Only step")
        result = self.loop.run(self.goal.goal_id, self.plan.plan_id)
        for key in (
            "success", "goal_id", "plan_id", "status", "iterations", "goal_status",
            "executed_steps", "completed_steps", "failed_steps", "blocked_steps",
            "outputs", "evidence", "warnings", "error", "learning_context", "next_step",
        ):
            self.assertIn(key, result)


if __name__ == "__main__":
    unittest.main()
