"""
Tests for ExecutionContextBuilder (execution/execution_context_builder.py)
- the read-only bridge that collects a step's already-COMPLETED direct
dependencies' outputs from the existing Plan Data Flow layer
(PlanManager/DataFlowManager) and wraps them into an ExecutionContext's
`previous_outputs`, plus its integration into StepExecutionPreparation
(execution/step_execution_preparation.py) via `build_context`/
`get_dependency_outputs`/`prepare_with_context`.

Covers: a step with no dependencies, one completed dependency, multiple
completed dependencies, a dependency without output, an incomplete
dependency, an unrelated completed step, explicit step input plus
previous outputs staying separate, a missing plan, a missing step,
correct ExecutionContext creation, correct source_steps, never
inventing an output, and backward compatibility with
StepExecutionPreparation.prepare()/ExecutionEngine.

Run directly:
    python -m unittest tests.test_execution_context_builder -v
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
from planning.data_flow_manager import DataFlowManager
from planning.plan import (
    STATUS_PENDING, STATUS_READY, STATUS_IN_PROGRESS, STATUS_COMPLETED,
    STATUS_FAILED,
)
from execution.execution_context import ExecutionContext
from execution.execution_context_builder import (
    ExecutionContextBuilder,
    DEPENDENCY_WARNINGS_METADATA_KEY,
)
from execution.step_execution_preparation import StepExecutionPreparation
from execution.step_execution_controller import StepExecutionController
from execution.capability_handlers import CapabilityHandlerRegistry


class ExecutionContextBuilderTestBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.builder = ExecutionContextBuilder(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)


class TestConstruction(unittest.TestCase):
    def test_requires_plan_manager_instance(self):
        with self.assertRaises(TypeError):
            ExecutionContextBuilder(object())

    def test_rejects_bad_data_flow_manager_type(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        with self.assertRaises(TypeError):
            ExecutionContextBuilder(plans, data_flow_manager=object())

    def test_default_data_flow_manager_is_created_when_omitted(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        builder = ExecutionContextBuilder(plans)
        self.assertIsInstance(builder.data_flow_manager, DataFlowManager)

    def test_accepts_shared_data_flow_manager(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        shared = DataFlowManager(plans)
        builder = ExecutionContextBuilder(plans, data_flow_manager=shared)
        self.assertIs(builder.data_flow_manager, shared)


class TestNoDependencies(ExecutionContextBuilderTestBase):
    def test_step_with_no_dependencies_has_empty_outputs(self):
        step = self.plans.add_step(self.plan.plan_id, "Do a thing", status=STATUS_READY)
        result = self.builder.get_dependency_outputs(self.plan.plan_id, step.step_id)
        self.assertTrue(result["success"])
        self.assertEqual(result["outputs"], {})
        self.assertEqual(result["source_steps"], [])
        self.assertEqual(result["warnings"], [])

    def test_build_context_with_no_dependencies(self):
        step = self.plans.add_step(self.plan.plan_id, "Do a thing", status=STATUS_READY)
        context = self.builder.build_context(self.plan.plan_id, step.step_id)
        self.assertIsInstance(context, ExecutionContext)
        self.assertEqual(context.get_previous_outputs(), {})


class TestOneCompletedDependency(ExecutionContextBuilderTestBase):
    def test_single_completed_dependency_output_included(self):
        dep = self.plans.add_step(
            self.plan.plan_id, "Produce a value", status=STATUS_COMPLETED,
            output_data={"value": 42},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume the value",
            dependencies=[dep.step_id], status=STATUS_READY,
        )
        result = self.builder.get_dependency_outputs(self.plan.plan_id, step.step_id)
        self.assertTrue(result["success"])
        self.assertEqual(result["outputs"], {dep.step_id: {"value": 42}})
        self.assertEqual(result["source_steps"], [dep.step_id])
        self.assertEqual(result["warnings"], [])


class TestMultipleCompletedDependencies(ExecutionContextBuilderTestBase):
    def test_multiple_completed_dependencies_all_included(self):
        dep_a = self.plans.add_step(
            self.plan.plan_id, "Produce A", status=STATUS_COMPLETED,
            output_data={"a": 1},
        )
        dep_b = self.plans.add_step(
            self.plan.plan_id, "Produce B", status=STATUS_COMPLETED,
            output_data={"b": 2},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume A and B",
            dependencies=[dep_a.step_id, dep_b.step_id], status=STATUS_READY,
        )
        result = self.builder.get_dependency_outputs(self.plan.plan_id, step.step_id)
        self.assertTrue(result["success"])
        self.assertEqual(
            result["outputs"], {dep_a.step_id: {"a": 1}, dep_b.step_id: {"b": 2}}
        )
        self.assertEqual(result["source_steps"], [dep_a.step_id, dep_b.step_id])
        self.assertEqual(result["warnings"], [])


class TestDependencyWithoutOutput(ExecutionContextBuilderTestBase):
    def test_completed_dependency_with_no_output_is_excluded(self):
        dep = self.plans.add_step(
            self.plan.plan_id, "Complete with no output", status=STATUS_COMPLETED,
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume it",
            dependencies=[dep.step_id], status=STATUS_READY,
        )
        result = self.builder.get_dependency_outputs(self.plan.plan_id, step.step_id)
        self.assertTrue(result["success"])
        self.assertEqual(result["outputs"], {})
        self.assertEqual(result["source_steps"], [])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn(dep.step_id, result["warnings"][0])

    def test_no_invented_output_ever_appears(self):
        dep = self.plans.add_step(
            self.plan.plan_id, "Complete with no output", status=STATUS_COMPLETED,
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume it",
            dependencies=[dep.step_id], status=STATUS_READY,
        )
        context = self.builder.build_context(self.plan.plan_id, step.step_id)
        self.assertNotIn(dep.step_id, context.get_previous_outputs())
        self.assertEqual(context.get_previous_outputs(), {})


class TestIncompleteDependency(ExecutionContextBuilderTestBase):
    def test_in_progress_dependency_is_excluded(self):
        dep = self.plans.add_step(
            self.plan.plan_id, "Still running", status=STATUS_IN_PROGRESS,
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume it",
            dependencies=[dep.step_id], status=STATUS_PENDING,
        )
        result = self.builder.get_dependency_outputs(self.plan.plan_id, step.step_id)
        self.assertTrue(result["success"])
        self.assertEqual(result["outputs"], {})
        self.assertEqual(result["source_steps"], [])
        self.assertEqual(len(result["warnings"]), 1)

    def test_failed_dependency_output_never_treated_as_available(self):
        dep = self.plans.add_step(
            self.plan.plan_id, "Failed step", status=STATUS_FAILED,
            output_data={"partial": True},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume it",
            dependencies=[dep.step_id], status=STATUS_PENDING,
        )
        result = self.builder.get_dependency_outputs(self.plan.plan_id, step.step_id)
        self.assertEqual(result["outputs"], {})
        self.assertEqual(result["source_steps"], [])

    def test_missing_dependency_step_is_excluded_with_warning(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Depends on nothing real",
            dependencies=["never-created-step"], status=STATUS_PENDING,
        )
        result = self.builder.get_dependency_outputs(self.plan.plan_id, step.step_id)
        self.assertTrue(result["success"])
        self.assertEqual(result["outputs"], {})
        self.assertEqual(len(result["warnings"]), 1)


class TestUnrelatedCompletedStep(ExecutionContextBuilderTestBase):
    def test_unrelated_completed_step_never_included(self):
        unrelated = self.plans.add_step(
            self.plan.plan_id, "Completed but unrelated", status=STATUS_COMPLETED,
            output_data={"unrelated": True},
        )
        dep = self.plans.add_step(
            self.plan.plan_id, "Real dependency", status=STATUS_COMPLETED,
            output_data={"real": True},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume only the real dependency",
            dependencies=[dep.step_id], status=STATUS_READY,
        )
        result = self.builder.get_dependency_outputs(self.plan.plan_id, step.step_id)
        self.assertEqual(result["outputs"], {dep.step_id: {"real": True}})
        self.assertNotIn(unrelated.step_id, result["outputs"])
        self.assertNotIn(unrelated.step_id, result["source_steps"])


class TestExplicitInputPlusPreviousOutputs(ExecutionContextBuilderTestBase):
    def test_explicit_input_data_and_previous_outputs_stay_separate(self):
        dep = self.plans.add_step(
            self.plan.plan_id, "Produce a value", status=STATUS_COMPLETED,
            output_data={"value": 42},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume the value",
            dependencies=[dep.step_id], status=STATUS_READY,
            input_data={"explicit": "input"},
        )
        context = self.builder.build_context(self.plan.plan_id, step.step_id)
        self.assertEqual(context.get_input(), {"explicit": "input"})
        self.assertEqual(context.get_previous_outputs(), {dep.step_id: {"value": 42}})
        # Neither ever bleeds into the other.
        self.assertNotIn("value", context.get_input())
        self.assertNotIn("explicit", context.get_previous_outputs())
        # The step's own stored input_data is left completely untouched.
        self.assertEqual(step.get_input(), {"explicit": "input"})


class TestMissingPlanOrStep(ExecutionContextBuilderTestBase):
    def test_get_dependency_outputs_missing_plan(self):
        result = self.builder.get_dependency_outputs("no-such-plan", "no-such-step")
        self.assertFalse(result["success"])
        self.assertEqual(result["outputs"], {})
        self.assertEqual(result["source_steps"], [])
        self.assertEqual(len(result["warnings"]), 1)

    def test_get_dependency_outputs_missing_step(self):
        result = self.builder.get_dependency_outputs(self.plan.plan_id, "no-such-step")
        self.assertFalse(result["success"])
        self.assertEqual(result["outputs"], {})
        self.assertEqual(len(result["warnings"]), 1)

    def test_build_context_missing_plan_raises(self):
        with self.assertRaises(ValueError):
            self.builder.build_context("no-such-plan", "no-such-step")

    def test_build_context_missing_step_raises(self):
        with self.assertRaises(ValueError):
            self.builder.build_context(self.plan.plan_id, "no-such-step")


class TestCorrectExecutionContextCreation(ExecutionContextBuilderTestBase):
    def test_context_identifiers_match_request(self):
        dep = self.plans.add_step(
            self.plan.plan_id, "Produce a value", status=STATUS_COMPLETED,
            output_data={"value": 1},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume it",
            dependencies=[dep.step_id], status=STATUS_READY,
        )
        context = self.builder.build_context(
            self.plan.plan_id, step.step_id,
            capability_name="search_web", execution_id="ctx-fixed-1",
        )
        self.assertIsInstance(context, ExecutionContext)
        self.assertEqual(context.plan_id, self.plan.plan_id)
        self.assertEqual(context.step_id, step.step_id)
        self.assertEqual(context.capability_name, "search_web")
        self.assertEqual(context.execution_id, "ctx-fixed-1")

    def test_context_generates_execution_id_when_omitted(self):
        step = self.plans.add_step(self.plan.plan_id, "Do a thing", status=STATUS_READY)
        context = self.builder.build_context(self.plan.plan_id, step.step_id)
        self.assertTrue(context.execution_id)

    def test_dependency_warnings_attached_as_metadata(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Depends on nothing real",
            dependencies=["never-created-step"], status=STATUS_PENDING,
        )
        context = self.builder.build_context(self.plan.plan_id, step.step_id)
        warnings = context.get_metadata().get(DEPENDENCY_WARNINGS_METADATA_KEY)
        self.assertIsNotNone(warnings)
        self.assertEqual(len(warnings), 1)

    def test_no_dependency_warnings_metadata_when_nothing_to_warn_about(self):
        step = self.plans.add_step(self.plan.plan_id, "Do a thing", status=STATUS_READY)
        context = self.builder.build_context(self.plan.plan_id, step.step_id)
        self.assertNotIn(DEPENDENCY_WARNINGS_METADATA_KEY, context.get_metadata())


class TestCorrectSourceSteps(ExecutionContextBuilderTestBase):
    def test_source_steps_matches_outputs_keys_in_dependency_order(self):
        dep_a = self.plans.add_step(
            self.plan.plan_id, "Produce A", status=STATUS_COMPLETED, output_data={"a": 1},
        )
        dep_b = self.plans.add_step(
            self.plan.plan_id, "Produce B", status=STATUS_COMPLETED, output_data={"b": 2},
        )
        dep_c_incomplete = self.plans.add_step(
            self.plan.plan_id, "Still running", status=STATUS_IN_PROGRESS,
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume A, B, C",
            dependencies=[dep_a.step_id, dep_c_incomplete.step_id, dep_b.step_id],
            status=STATUS_PENDING,
        )
        result = self.builder.get_dependency_outputs(self.plan.plan_id, step.step_id)
        # dep_c_incomplete is skipped; order among the two real
        # contributors follows step.dependencies order.
        self.assertEqual(result["source_steps"], [dep_a.step_id, dep_b.step_id])
        self.assertEqual(set(result["outputs"].keys()), set(result["source_steps"]))


class TestNoAutomaticExecutionOrPropagation(ExecutionContextBuilderTestBase):
    def test_build_context_does_not_change_any_step_status(self):
        dep = self.plans.add_step(
            self.plan.plan_id, "Produce a value", status=STATUS_COMPLETED,
            output_data={"value": 1},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume it",
            dependencies=[dep.step_id], status=STATUS_READY,
        )
        self.builder.build_context(self.plan.plan_id, step.step_id)
        self.assertEqual(dep.status, STATUS_COMPLETED)
        self.assertEqual(step.status, STATUS_READY)

    def test_build_context_does_not_write_target_input_data(self):
        dep = self.plans.add_step(
            self.plan.plan_id, "Produce a value", status=STATUS_COMPLETED,
            output_data={"value": 1},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume it",
            dependencies=[dep.step_id], status=STATUS_READY,
        )
        self.builder.build_context(self.plan.plan_id, step.step_id)
        # propagate_step_output is a separate, never-auto-invoked path;
        # building a context must never write it into the step itself.
        self.assertIsNone(step.get_input())


class TestStepExecutionPreparationIntegration(unittest.TestCase):
    """Backward compatibility + integration coverage for
    StepExecutionPreparation.build_context/get_dependency_outputs/
    prepare_with_context (execution/step_execution_preparation.py)."""

    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.handlers = CapabilityHandlerRegistry()
        self.prep = StepExecutionPreparation(self.plans, capability_handlers=self.handlers)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def test_prepare_return_shape_unchanged(self):
        step = self.plans.add_step(self.plan.plan_id, "Do a thing", status=STATUS_READY)
        result = self.prep.prepare(self.plan.plan_id, step.step_id)
        self.assertEqual(
            set(result.keys()),
            {
                "prepared", "plan_id", "step_id", "status", "capabilities",
                "input_data", "failed_checks", "warnings",
            },
        )
        self.assertNotIn("context", result)

    def test_prepare_with_context_successful_step_gets_dependency_outputs(self):
        dep = self.plans.add_step(
            self.plan.plan_id, "Produce a value", status=STATUS_COMPLETED,
            output_data={"value": 99},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume it",
            dependencies=[dep.step_id], status=STATUS_READY,
        )
        result = self.prep.prepare_with_context(self.plan.plan_id, step.step_id)
        self.assertTrue(result["prepared"])
        self.assertIsInstance(result["context"], ExecutionContext)
        self.assertEqual(
            result["context"].get_previous_outputs(), {dep.step_id: {"value": 99}}
        )

    def test_prepare_with_context_failed_preparation_has_no_context(self):
        step = self.plans.add_step(
            self.plan.plan_id, "Depends on nothing real",
            dependencies=["never-created-step"], status=STATUS_READY,
        )
        result = self.prep.prepare_with_context(self.plan.plan_id, step.step_id)
        self.assertFalse(result["prepared"])
        self.assertIsNone(result["context"])

    def test_get_dependency_outputs_delegates_correctly(self):
        dep = self.plans.add_step(
            self.plan.plan_id, "Produce a value", status=STATUS_COMPLETED,
            output_data={"value": 7},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume it",
            dependencies=[dep.step_id], status=STATUS_READY,
        )
        result = self.prep.get_dependency_outputs(self.plan.plan_id, step.step_id)
        self.assertTrue(result["success"])
        self.assertEqual(result["outputs"], {dep.step_id: {"value": 7}})

    def test_build_context_delegates_correctly(self):
        step = self.plans.add_step(self.plan.plan_id, "Do a thing", status=STATUS_READY)
        context = self.prep.build_context(self.plan.plan_id, step.step_id)
        self.assertIsInstance(context, ExecutionContext)
        self.assertEqual(context.plan_id, self.plan.plan_id)
        self.assertEqual(context.step_id, step.step_id)

    def test_rejects_bad_context_builder_type(self):
        with self.assertRaises(TypeError):
            StepExecutionPreparation(self.plans, context_builder=object())

    def test_accepts_shared_context_builder(self):
        shared = ExecutionContextBuilder(self.plans)
        prep = StepExecutionPreparation(self.plans, context_builder=shared)
        self.assertIs(prep.context_builder, shared)

    def test_existing_single_argument_handler_still_works_unaffected(self):
        """Backward compatibility: an existing handler that only
        expects (step,) - never a context - keeps working exactly as
        before, entirely unaffected by this stage's additions."""
        calls = []

        def legacy_handler(step):
            calls.append(step.step_id)
            return {"ok": True}

        step = self.plans.add_step(
            self.plan.plan_id, "Do a thing",
            required_capabilities=["legacy_cap"], status=STATUS_READY,
        )
        self.handlers.register("legacy_cap", legacy_handler)
        result = self.prep.prepare(self.plan.plan_id, step.step_id)
        self.assertTrue(result["prepared"])
        # prepare() itself never calls the handler either way.
        self.assertEqual(calls, [])


class TestPrompt312DependentStepOutputsInExecutionContext(unittest.TestCase):
    """Prompt 312: connect completed dependent-step outputs to the
    existing ExecutionContext.previous_outputs when preparing a READY
    step. Verifies the connection that already exists end-to-end -
    ExecutionContextBuilder.get_dependency_outputs/build_context,
    reached via StepExecutionPreparation.prepare_with_context and, in
    turn, StepExecutionController.execute_step - rather than adding a
    second, duplicate implementation of any of it."""

    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.controller = StepExecutionController(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def test_dependent_step_receives_completed_dependency_output(self):
        """1. A dependent step receives the output of its completed
        dependency."""
        dep = self.plans.add_step(
            self.plan.plan_id, "Produce a value", status=STATUS_COMPLETED,
            output_data={"value": 42},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume the value",
            dependencies=[dep.step_id], status=STATUS_READY,
        )

        prep_result = self.controller._preparation.prepare_with_context(
            self.plan.plan_id, step.step_id,
        )

        self.assertTrue(prep_result["prepared"])
        context = prep_result["context"]
        self.assertIsInstance(context, ExecutionContext)
        self.assertEqual(context.get_previous_outputs(), {dep.step_id: {"value": 42}})

    def test_multiple_completed_direct_dependencies_all_represented(self):
        """2. Multiple completed direct dependencies are represented
        correctly."""
        dep_a = self.plans.add_step(
            self.plan.plan_id, "Produce A", status=STATUS_COMPLETED,
            output_data={"a": 1},
        )
        dep_b = self.plans.add_step(
            self.plan.plan_id, "Produce B", status=STATUS_COMPLETED,
            output_data={"b": 2},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume A and B",
            dependencies=[dep_a.step_id, dep_b.step_id], status=STATUS_READY,
        )

        prep_result = self.controller._preparation.prepare_with_context(
            self.plan.plan_id, step.step_id,
        )

        previous_outputs = prep_result["context"].get_previous_outputs()
        self.assertEqual(
            previous_outputs, {dep_a.step_id: {"a": 1}, dep_b.step_id: {"b": 2}},
        )

    def test_explicit_step_input_stays_separate_from_dependency_outputs(self):
        """3. Explicit step input remains separate from dependency
        outputs."""
        dep = self.plans.add_step(
            self.plan.plan_id, "Produce a value", status=STATUS_COMPLETED,
            output_data={"value": 42},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume the value",
            dependencies=[dep.step_id], status=STATUS_READY,
            input_data={"explicit": "input"},
        )

        prep_result = self.controller._preparation.prepare_with_context(
            self.plan.plan_id, step.step_id,
        )
        context = prep_result["context"]

        self.assertEqual(context.get_input(), {"explicit": "input"})
        self.assertEqual(context.get_previous_outputs(), {dep.step_id: {"value": 42}})
        self.assertNotIn("explicit", context.get_previous_outputs())
        self.assertNotIn("value", context.get_input())
        # The step's own stored, explicit input_data is left untouched.
        self.assertEqual(step.get_input(), {"explicit": "input"})

    def test_incomplete_dependency_provides_no_invented_output(self):
        """4. Incomplete dependencies provide no invented output."""
        still_running = self.plans.add_step(
            self.plan.plan_id, "Still running", status=STATUS_IN_PROGRESS,
        )
        no_output_yet = self.plans.add_step(
            self.plan.plan_id, "Completed but produced nothing",
            status=STATUS_COMPLETED,
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Waits on both",
            dependencies=[still_running.step_id, no_output_yet.step_id],
            status=STATUS_PENDING,
        )

        prep_result = self.controller._preparation.prepare_with_context(
            self.plan.plan_id, step.step_id,
        )

        # Not READY (an unresolved dependency), so preparation itself
        # refuses - and, either way, no output is ever invented for
        # either dependency.
        self.assertFalse(prep_result["prepared"])
        self.assertIsNone(prep_result["context"])
        dependency_result = self.controller._preparation.get_dependency_outputs(
            self.plan.plan_id, step.step_id,
        )
        self.assertEqual(dependency_result["outputs"], {})
        self.assertNotIn(still_running.step_id, dependency_result["outputs"])
        self.assertNotIn(no_output_yet.step_id, dependency_result["outputs"])

    def test_preparing_a_step_does_not_execute_it(self):
        """5. Preparing a step does not execute it."""
        dep = self.plans.add_step(
            self.plan.plan_id, "Produce a value", status=STATUS_COMPLETED,
            output_data={"value": 1},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume it",
            dependencies=[dep.step_id], status=STATUS_READY,
        )

        self.controller._preparation.prepare_with_context(self.plan.plan_id, step.step_id)

        # Still READY - preparing/building a context never runs the
        # step, never touches its status, and records no execution.
        self.assertEqual(step.status, STATUS_READY)
        self.assertEqual(len(self.controller.history), 0)

    def test_existing_tests_remain_compatible_full_step_execution_still_works(self):
        """6. Existing tests remain compatible - the full, existing
        StepExecutionController.execute_step path (which itself calls
        prepare_with_context internally) keeps completing a step and
        recording its output exactly as before, dependency outputs
        included."""
        dep = self.plans.add_step(
            self.plan.plan_id, "Produce a value", status=STATUS_COMPLETED,
            output_data={"value": 7},
        )
        step = self.plans.add_step(
            self.plan.plan_id, "Consume it",
            dependencies=[dep.step_id], status=STATUS_READY,
        )

        result = self.controller.execute_step(self.plan.plan_id, step.step_id)

        self.assertTrue(result["success"])
        self.assertEqual(step.status, STATUS_COMPLETED)
        self.assertEqual(
            result["context"]["previous_outputs"], {dep.step_id: {"value": 7}},
        )


if __name__ == "__main__":
    unittest.main()
