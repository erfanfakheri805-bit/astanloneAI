"""
Tests for Core's conversational Goal creation (core/core.py's
_handle_goal_or_conversation, backed by
planning/goal_detection.is_goal_oriented) and for Core.create_goal's
connection to the Plan system (an empty Plan started for every Goal
created through Core).

Run directly:
    python -m unittest tests.test_core -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planning.goal import Goal
from planning.plan import Plan
from planning.goal_detection import is_goal_oriented
from core.core import Core


def _make_core():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
    skills_dir = os.path.join(tmpdir.name, "skills")
    core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)
    return core, tmpdir


# ----------------------------------------------------------------------
# Prompt 301: Core conversation flow -> Goal system
# ----------------------------------------------------------------------
class TestGoalOrientedInputCreatesAGoal(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_goal_oriented_input_creates_a_goal(self):
        self.assertEqual(len(self.core.goals), 0)
        reply = self.core.process_input("I want to learn Python")

        self.assertEqual(len(self.core.goals), 1)
        goal = self.core.goals.all_goals()[0]
        self.assertIsInstance(goal, Goal)
        self.assertIn("GOAL CREATED", reply)
        self.assertIn(goal.goal_id, reply)

    def test_several_goal_trigger_phrases_all_create_a_goal(self):
        phrases = [
            "I want to learn Python",
            "I need to fix the bug",
            "please help me plan a trip",
            "help me write an email",
            "my goal is to finish the report",
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                core, tmpdir = _make_core()
                try:
                    core.process_input(phrase)
                    self.assertEqual(len(core.goals), 1)
                finally:
                    tmpdir.cleanup()


class TestOriginalTextIsPreserved(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_original_text_matches_the_users_exact_wording(self):
        text = "I want to learn Python quickly"
        self.core.process_input(text)

        goal = self.core.goals.all_goals()[0]
        self.assertEqual(goal.original_text, text)

    def test_original_text_preserves_original_whitespace(self):
        text = "  I want to   learn   Python  "
        self.core.process_input(text)

        goal = self.core.goals.all_goals()[0]
        self.assertEqual(goal.original_text, text)


class TestNormalQuestionDoesNotCreateAGoal(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_normal_question_does_not_create_a_goal(self):
        reply = self.core.process_input("What is Python?")

        self.assertEqual(len(self.core.goals), 0)
        self.assertNotIn("GOAL CREATED", reply)


class TestNormalStatementDoesNotCreateAGoal(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_normal_statement_does_not_create_a_goal(self):
        reply = self.core.process_input("Python is a programming language.")

        self.assertEqual(len(self.core.goals), 0)
        self.assertNotIn("GOAL CREATED", reply)

    def test_unknown_input_does_not_create_a_goal(self):
        reply = self.core.process_input("qwerty zzznoxyzzz unmapped concept")

        self.assertEqual(len(self.core.goals), 0)
        self.assertIsInstance(reply, str)


class TestIsGoalOrientedHelper(unittest.TestCase):
    def test_recognizes_trigger_phrases_case_insensitively(self):
        self.assertTrue(is_goal_oriented("I WANT TO learn Python"))
        self.assertTrue(is_goal_oriented("Help me plan a trip"))

    def test_does_not_recognize_ordinary_text(self):
        self.assertFalse(is_goal_oriented("What is Python?"))
        self.assertFalse(is_goal_oriented("Python is a programming language."))
        self.assertFalse(is_goal_oriented(""))
        self.assertFalse(is_goal_oriented(None))

    def test_does_not_match_mid_word(self):
        # "help mexico" must not match the "help me " trigger.
        self.assertFalse(is_goal_oriented("help mexico with its economy"))


class TestExistingAELBehaviorStillWorksAfterGoalRouting(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ael_commands_are_unaffected_by_goal_detection(self):
        reply = self.core.process_input("TEACH sun IS a star")
        self.assertTrue(reply.startswith("[AEL"))
        self.assertEqual(len(self.core.goals), 0)

        ask_reply = self.core.process_input("ASK sun")
        self.assertTrue(ask_reply.startswith("[AEL"))
        self.assertEqual(len(self.core.goals), 0)

    def test_ael_takes_priority_even_if_text_contains_goal_phrasing(self):
        # An AEL keyword at the start always routes to AEL, regardless
        # of what follows - goal detection never runs for AEL input.
        reply = self.core.process_input("TEACH i want to learn IS a goal-like phrase")
        self.assertTrue(reply.startswith("[AEL"))
        self.assertEqual(len(self.core.goals), 0)


class TestExistingConversationTestsRemainCompatible(unittest.TestCase):
    """Re-confirms the pre-existing "existing conversation flow is
    unaffected" contract (already covered directly in
    tests/test_goal_manager.py, tests/test_plan_manager.py, and
    tests/test_planner.py) now that goal-oriented routing exists."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_hello_creates_neither_a_goal_nor_a_plan(self):
        reply = self.core.process_input("hello")
        self.assertIsInstance(reply, str)
        self.assertEqual(len(self.core.goals), 0)
        self.assertEqual(len(self.core.plans), 0)

    def test_empty_input_still_returns_the_existing_fallback(self):
        reply = self.core.process_input("")
        self.assertEqual(reply, "Say something and I'll try to respond.")
        self.assertEqual(len(self.core.goals), 0)


# ----------------------------------------------------------------------
# Prompt 302: Goal system -> Plan system
# ----------------------------------------------------------------------
class TestGoalCreatedFromCoreProducesAPlan(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_core_create_goal_also_creates_a_plan(self):
        self.assertEqual(len(self.core.plans), 0)
        goal = self.core.create_goal("Refactor the parser")

        self.assertEqual(len(self.core.plans), 1)
        plan = self.core.plans.all_plans()[0]
        self.assertIsInstance(plan, Plan)
        self.assertEqual(plan.goal_id, goal.goal_id)

    def test_goal_created_via_conversation_also_produces_a_plan(self):
        self.core.process_input("I want to learn Python")

        self.assertEqual(len(self.core.goals), 1)
        self.assertEqual(len(self.core.plans), 1)
        goal = self.core.goals.all_goals()[0]
        plan = self.core.plans.all_plans()[0]
        self.assertEqual(plan.goal_id, goal.goal_id)


class TestPlanReferencesTheCorrectGoalId(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_plan_goal_id_matches_the_created_goal(self):
        goal = self.core.create_goal("Plan a birthday party")
        plan = self.core.plans.all_plans()[0]
        self.assertEqual(plan.goal_id, goal.goal_id)

    def test_each_goal_gets_its_own_correctly_linked_plan(self):
        goal_one = self.core.create_goal("Refactor the parser")
        goal_two = self.core.create_goal("Write documentation")

        plans_by_goal_id = {plan.goal_id: plan for plan in self.core.plans.all_plans()}
        self.assertEqual(len(plans_by_goal_id), 2)
        self.assertIn(goal_one.goal_id, plans_by_goal_id)
        self.assertIn(goal_two.goal_id, plans_by_goal_id)


class TestNewPlanInitiallyContainsNoSteps(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_auto_created_plan_has_no_steps(self):
        self.core.create_goal("Refactor the parser")
        plan = self.core.plans.all_plans()[0]
        self.assertEqual(plan.steps, [])

    def test_auto_created_plan_is_not_executed_or_started(self):
        from planning.plan import STATUS_PENDING

        self.core.create_goal("Refactor the parser")
        plan = self.core.plans.all_plans()[0]
        self.assertEqual(plan.status, STATUS_PENDING)


class TestNormalNonGoalInputDoesNotCreateAPlan(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_question_creates_no_plan(self):
        self.core.process_input("What is Python?")
        self.assertEqual(len(self.core.plans), 0)

    def test_statement_creates_no_plan(self):
        self.core.process_input("Python is a programming language.")
        self.assertEqual(len(self.core.plans), 0)

    def test_ael_input_creates_no_plan(self):
        self.core.process_input("TEACH sun IS a star")
        self.assertEqual(len(self.core.plans), 0)


class TestExistingAELBehaviorStillWorksAfterPlanWiring(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ael_teach_and_ask_still_work(self):
        teach_reply = self.core.process_input("TEACH sun IS a star")
        self.assertTrue(teach_reply.startswith("[AEL OK]"))

        ask_reply = self.core.process_input("ASK sun")
        self.assertTrue(ask_reply.startswith("[AEL OK]"))
        self.assertEqual(len(self.core.plans), 0)


class TestExistingPlanTestsRemainCompatible(unittest.TestCase):
    """Re-confirms create_plan()/add_plan_step()/the Planner's own
    plan_first_step() family (already covered directly in
    tests/test_plan_manager.py and tests/test_planner.py) still work
    exactly as before, now that create_goal() also starts an empty
    Plan of its own."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_explicit_create_plan_still_creates_an_additional_plan(self):
        goal = self.core.create_goal("Refactor the parser")
        # One auto-created empty plan already exists for this goal;
        # an explicit create_plan() call still creates its own,
        # separate Plan, exactly as before this stage.
        explicit_plan = self.core.create_plan(
            goal.goal_id, required_capabilities=["code_analysis"]
        )
        step = self.core.add_plan_step(explicit_plan.plan_id, "Read the existing parser")

        self.assertEqual(len(self.core.plans), 2)
        described = self.core.describe_plan(explicit_plan.plan_id)
        self.assertEqual(described["goal_id"], goal.goal_id)
        self.assertEqual(described["steps"][0]["step_id"], step.step_id)

    def test_planner_first_step_reuses_the_auto_created_empty_plan(self):
        goal = self.core.create_goal("Create a calculator")
        # create_goal() above already started one empty Plan; the
        # Planner's own reuse-oldest-plan behaviour means this simply
        # adds a first step to that same Plan rather than creating a
        # second one.
        plan = self.core.plan_first_step(goal.goal_id)

        self.assertEqual(len(self.core.plans), 1)
        self.assertEqual(plan.goal_id, goal.goal_id)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(
            plan.steps[0].description,
            "Understand the requirements of the requested calculator",
        )


# ----------------------------------------------------------------------
# Prompt 304: Plan's first PlanStep -> existing execution preparation
# ----------------------------------------------------------------------
class TestFirstStepReachableThroughCore(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_existing_goal_can_reach_its_first_step_through_core(self):
        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_first_step(goal.goal_id)

        self.assertEqual(plan.goal_id, goal.goal_id)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].step_id, f"{plan.plan_id}-step-1")


class TestFirstStepPassedToExecutionPreparation(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_prepare_first_step_uses_the_correct_plan_and_step(self):
        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_first_step(goal.goal_id)
        step = plan.steps[0]

        result = self.core.prepare_first_step(goal.goal_id)

        self.assertEqual(result["plan_id"], plan.plan_id)
        self.assertEqual(result["step_id"], step.step_id)

    def test_prepare_first_step_matches_calling_preparation_directly(self):
        """Core.prepare_first_step must be a thin connection to the
        existing StepExecutionPreparation, not a second copy of it -
        calling core.step_preparation.prepare directly with the same
        plan_id/step_id gives the identical structured result."""
        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_first_step(goal.goal_id)
        step = plan.steps[0]
        self.core.plans.refresh_step_status(plan.plan_id, step.step_id, self.core.capabilities)
        direct = self.core.step_preparation.prepare(
            plan.plan_id, step.step_id, self.core.capabilities
        )

        result = self.core.prepare_first_step(goal.goal_id)

        self.assertEqual(result, direct)


class TestValidStepPreparationSucceeds(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_valid_first_step_is_reported_as_prepared(self):
        goal = self.core.create_goal("Create a calculator")
        result = self.core.prepare_first_step(goal.goal_id)

        self.assertTrue(result["prepared"])
        self.assertEqual(result["failed_checks"], [])


class TestUnknownGoalIdIsHandledSafely(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_unknown_goal_id_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.core.prepare_first_step("does-not-exist")

    def test_unknown_goal_id_creates_no_plan(self):
        with self.assertRaises(ValueError):
            self.core.prepare_first_step("does-not-exist")
        self.assertEqual(len(self.core.plans), 0)


class TestNoExecutionOccursDuringPreparation(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_preparation_does_not_change_step_status_to_in_progress_or_completed(self):
        from planning.plan import STATUS_READY

        goal = self.core.create_goal("Create a calculator")
        result = self.core.prepare_first_step(goal.goal_id)

        plan = self.core.plans.all_plans()[0]
        self.assertEqual(plan.steps[0].status, STATUS_READY)
        self.assertEqual(result["status"], STATUS_READY)

    def test_preparation_does_not_write_output_data(self):
        goal = self.core.create_goal("Create a calculator")
        self.core.prepare_first_step(goal.goal_id)

        plan = self.core.plans.all_plans()[0]
        self.assertIsNone(plan.steps[0].output_data)

    def test_calling_prepare_first_step_twice_does_not_duplicate_or_execute(self):
        goal = self.core.create_goal("Create a calculator")

        self.core.prepare_first_step(goal.goal_id)
        self.core.prepare_first_step(goal.goal_id)

        self.assertEqual(len(self.core.plans), 1)
        plan = self.core.plans.all_plans()[0]
        self.assertEqual(len(plan.steps), 1)


class TestExistingPreparationAndPlannerTestsRemainCompatible(unittest.TestCase):
    """Re-confirms plan_first_step (Prompt 303) and the standalone
    StepExecutionPreparation module (tests/test_step_execution_preparation.py)
    still behave exactly as before, now that Core also wires a
    prepare_first_step connection between them."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_plan_first_step_still_works_unaffected(self):
        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_first_step(goal.goal_id)

        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(
            plan.steps[0].description,
            "Understand the requirements of the requested calculator",
        )

    def test_ael_still_works_alongside_execution_preparation_wiring(self):
        teach_reply = self.core.process_input("TEACH sun IS a star")
        self.assertTrue(teach_reply.startswith("[AEL OK]"))
        self.assertEqual(len(self.core.plans), 0)


# ----------------------------------------------------------------------
# Prompt 305: First PlanStep -> existing controlled step execution flow
# ----------------------------------------------------------------------
class TestFirstStepExecutableThroughCore(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_existing_goal_can_execute_its_first_step_through_core(self):
        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_first_step(goal.goal_id)
        step = plan.steps[0]

        result = self.core.execute_first_step(goal.goal_id)

        self.assertEqual(result["plan_id"], plan.plan_id)
        self.assertEqual(result["step_id"], step.step_id)


class TestValidExecutionReturnsTheStructuredResult(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_delegates_to_the_existing_step_controller_unchanged(self):
        """Core.execute_first_step must be a thin connection to the
        existing StepExecutionController, not a second copy of it -
        it should call self.step_controller.execute_step exactly once
        with the correct plan_id/step_id, and return its result as-is."""
        from unittest.mock import patch

        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_first_step(goal.goal_id)
        step = plan.steps[0]
        expected = {"success": True, "sentinel": "existing-controller-result"}

        with patch.object(
            self.core.step_controller, "execute_step", return_value=expected
        ) as mock_execute:
            result = self.core.execute_first_step(goal.goal_id)

        mock_execute.assert_called_once_with(
            plan.plan_id, step.step_id, self.core.capabilities
        )
        self.assertEqual(result, expected)

    def test_result_has_the_existing_structured_shape(self):
        goal = self.core.create_goal("Create a calculator")

        result = self.core.execute_first_step(goal.goal_id)

        for key in (
            "success", "plan_id", "step_id", "execution_id", "step_status",
            "output", "error", "warnings", "events_recorded", "context",
        ):
            self.assertIn(key, result)


class TestStepReachesCorrectFinalStatusAfterSuccess(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_successful_execution_completes_the_step(self):
        from planning.plan import STATUS_COMPLETED

        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_first_step(goal.goal_id)
        step = plan.steps[0]

        result = self.core.execute_first_step(goal.goal_id)

        self.assertTrue(result["success"])
        self.assertEqual(result["step_status"], STATUS_COMPLETED)
        self.assertEqual(step.status, STATUS_COMPLETED)
        self.assertIsNotNone(result["execution_id"])


class TestFailedExecutionIsReportedSafely(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_a_raising_handler_is_reported_as_a_failure_not_an_exception(self):
        from planning.plan import STATUS_FAILED

        goal = self.core.create_goal("Draw a picture")
        plan = self.core.plan_first_step(goal.goal_id)
        step = plan.steps[0]
        step.required_capabilities = ["draw_image"]
        self.core.capabilities.register(
            "draw_image", "Draw an image", enabled=True, status="active"
        )

        def failing_handler(plan_step):
            raise ValueError("could not draw")

        self.core.step_controller.capability_handlers.register("draw_image", failing_handler)

        result = self.core.execute_first_step(goal.goal_id)

        self.assertFalse(result["success"])
        self.assertEqual(result["step_status"], STATUS_FAILED)
        self.assertEqual(step.status, STATUS_FAILED)
        self.assertIn("could not draw", result["error"])

    def test_unknown_goal_id_raises_value_error_instead_of_executing_anything(self):
        with self.assertRaises(ValueError):
            self.core.execute_first_step("does-not-exist")
        self.assertEqual(len(self.core.plans), 0)


class TestSecondStepIsNotAutomaticallyExecuted(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_execute_first_step_does_not_add_or_run_a_second_step(self):
        from planning.plan import STATUS_COMPLETED

        goal = self.core.create_goal("Create a calculator")
        self.core.execute_first_step(goal.goal_id)

        plan = self.core.plans.all_plans()[0]
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].status, STATUS_COMPLETED)

    def test_execute_first_step_never_calls_plan_second_step_itself(self):
        """A plan with an explicit second step (added directly, as a
        stand-in for one plan_second_step would add) is left alone -
        execute_first_step only ever touches the plan's first step.
        Completing the first step does refresh the second step's own
        READY/BLOCKED status from the plan's dependency graph (the
        existing PlanManager.refresh_after_step_change behavior
        StepExecutionController.execute_step already triggers on
        success - unchanged by this connection), but that is a status
        recomputation only: the second step is never actually run."""
        from planning.plan import STATUS_READY

        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_first_step(goal.goal_id)
        second_step = self.core.plans.add_step(
            plan.plan_id, "A second step nobody asked to run yet",
            dependencies=[plan.steps[0].step_id],
        )

        self.core.execute_first_step(goal.goal_id)

        self.assertEqual(second_step.status, STATUS_READY)
        self.assertIsNone(second_step.output_data)


class TestExistingExecutionAndPreparationTestsRemainCompatible(unittest.TestCase):
    """Re-confirms prepare_first_step (Prompt 304), plan_first_step
    (Prompt 303), and the standalone StepExecutionController/
    ExecutionEngine modules still behave exactly as before, now that
    Core also wires an execute_first_step connection between them."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_prepare_first_step_still_works_unaffected(self):
        goal = self.core.create_goal("Create a calculator")
        result = self.core.prepare_first_step(goal.goal_id)

        self.assertTrue(result["prepared"])
        self.assertEqual(result["failed_checks"], [])

    def test_ael_still_works_alongside_execution_wiring(self):
        teach_reply = self.core.process_input("TEACH sun IS a star")
        self.assertTrue(teach_reply.startswith("[AEL OK]"))
        self.assertEqual(len(self.core.plans), 0)


# ----------------------------------------------------------------------
# Prompt 306: Execution result -> existing Learning system
# ----------------------------------------------------------------------
class TestSuccessfulExecutionCreatesALearningRecord(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_successful_execution_creates_exactly_one_record(self):
        goal = self.core.create_goal("Create a calculator")

        self.core.execute_first_step(goal.goal_id)

        records = self.core.learning_records.get_all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].outcome, "success")
        self.assertEqual(records[0].confidence, 1.0)


class TestFailedExecutionCreatesALearningRecord(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_failed_execution_creates_exactly_one_record(self):
        goal = self.core.create_goal("Draw a picture")
        plan = self.core.plan_first_step(goal.goal_id)
        step = plan.steps[0]
        step.required_capabilities = ["draw_image"]
        self.core.capabilities.register(
            "draw_image", "Draw an image", enabled=True, status="active"
        )

        def failing_handler(plan_step):
            raise ValueError("could not draw")

        self.core.step_controller.capability_handlers.register("draw_image", failing_handler)

        self.core.execute_first_step(goal.goal_id)

        records = self.core.learning_records.get_all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].outcome, "failure")
        self.assertEqual(records[0].confidence, 0.0)

    def test_a_preparation_failure_creates_no_record(self):
        """A step that never actually ran (a preparation-gate failure,
        execution_id=None) has no real ExecutionResult to learn from -
        no record is created for it."""
        goal = self.core.create_goal("Draw a picture")
        plan = self.core.plan_first_step(goal.goal_id)
        step = plan.steps[0]
        step.required_capabilities = ["draw_image"]
        # Deliberately never registered/enabled - preparation itself
        # will fail (missing capability/handler), so ExecutionEngine
        # is never even reached.

        result = self.core.execute_first_step(goal.goal_id)

        self.assertFalse(result["success"])
        self.assertIsNone(result["execution_id"])
        self.assertEqual(len(self.core.learning_records.get_all()), 0)


class TestLearningRecordReferencesCorrectExecutionInfo(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_record_metadata_matches_the_execution_result(self):
        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_first_step(goal.goal_id)
        step = plan.steps[0]

        result = self.core.execute_first_step(goal.goal_id)

        records = self.core.learning_records.get_all()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.metadata["plan_id"], plan.plan_id)
        self.assertEqual(record.metadata["step_id"], step.step_id)
        self.assertEqual(record.metadata["execution_id"], result["execution_id"])
        self.assertEqual(record.source, "execution_system")

    def test_failure_record_metadata_includes_the_error(self):
        goal = self.core.create_goal("Draw a picture")
        plan = self.core.plan_first_step(goal.goal_id)
        step = plan.steps[0]
        step.required_capabilities = ["draw_image"]
        self.core.capabilities.register(
            "draw_image", "Draw an image", enabled=True, status="active"
        )

        def failing_handler(plan_step):
            raise ValueError("could not draw")

        self.core.step_controller.capability_handlers.register("draw_image", failing_handler)

        self.core.execute_first_step(goal.goal_id)

        record = self.core.learning_records.get_all()[0]
        self.assertIn("could not draw", record.metadata["error"])


class TestRecordIsStoredInTheExistingLearningRecordStore(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_learning_records_is_a_learning_record_store(self):
        from learning.learning_record_store import LearningRecordStore

        self.assertIsInstance(self.core.learning_records, LearningRecordStore)

    def test_record_is_retrievable_from_the_store_by_id(self):
        goal = self.core.create_goal("Create a calculator")
        self.core.execute_first_step(goal.goal_id)

        record = self.core.learning_records.get_all()[0]
        fetched = self.core.learning_records.get(record.record_id)
        self.assertEqual(fetched.record_id, record.record_id)
        self.assertEqual(fetched.outcome, record.outcome)

    def test_no_duplicate_store_is_created_across_calls(self):
        goal = self.core.create_goal("Create a calculator")
        store_before = self.core.learning_records
        self.core.execute_first_step(goal.goal_id)
        self.assertIs(self.core.learning_records, store_before)


class TestNonExecutionConversationCreatesNoExecutionLearningRecord(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ael_input_creates_no_learning_record(self):
        self.core.process_input("TEACH sun IS a star")
        self.assertEqual(len(self.core.learning_records.get_all()), 0)

    def test_plain_question_creates_no_learning_record(self):
        self.core.process_input("What is the capital of France?")
        self.assertEqual(len(self.core.learning_records.get_all()), 0)

    def test_creating_a_goal_alone_creates_no_learning_record(self):
        """Creating a Goal (and its empty Plan) is not an execution -
        no learning record until a step is actually executed."""
        self.core.create_goal("Create a calculator")
        self.assertEqual(len(self.core.learning_records.get_all()), 0)

    def test_preparing_a_step_alone_creates_no_learning_record(self):
        goal = self.core.create_goal("Create a calculator")
        self.core.prepare_first_step(goal.goal_id)
        self.assertEqual(len(self.core.learning_records.get_all()), 0)


class TestExistingExecutionTestsRemainCompatible(unittest.TestCase):
    """Re-confirms execute_first_step (Prompt 305) and everything it
    already returns/does are unaffected by also connecting execution
    results into the Learning system."""

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_execute_first_step_result_shape_is_unchanged(self):
        goal = self.core.create_goal("Create a calculator")
        result = self.core.execute_first_step(goal.goal_id)

        for key in (
            "success", "plan_id", "step_id", "execution_id", "step_status",
            "output", "error", "warnings", "events_recorded", "context",
        ):
            self.assertIn(key, result)

    def test_step_still_reaches_completed_on_success(self):
        from planning.plan import STATUS_COMPLETED

        goal = self.core.create_goal("Create a calculator")
        plan = self.core.plan_first_step(goal.goal_id)
        self.core.execute_first_step(goal.goal_id)

        self.assertEqual(plan.steps[0].status, STATUS_COMPLETED)

    def test_ael_still_works_alongside_learning_wiring(self):
        teach_reply = self.core.process_input("TEACH sun IS a star")
        self.assertTrue(teach_reply.startswith("[AEL OK]"))
        self.assertEqual(len(self.core.plans), 0)


if __name__ == "__main__":
    unittest.main()
