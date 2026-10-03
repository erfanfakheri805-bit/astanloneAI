"""
Tests for ProposalApplier (planning/proposal_applier.py) - applying a
single, already-validated ADD_CAPABILITY_REQUIREMENT,
REMOVE_CAPABILITY_REQUIREMENT, PROVIDE_INPUT, PROVIDE_OUTPUT, or
REORDER_STEP change to a Plan.

Run directly:
    python -m unittest tests.test_proposal_applier -v
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
    CHANGE_REMOVE_CAPABILITY_REQUIREMENT,
    CHANGE_PROVIDE_INPUT,
    CHANGE_PROVIDE_OUTPUT,
    CHANGE_REORDER_STEP,
    CHANGE_ADD_DEPENDENCY,
    CHANGE_REMOVE_DEPENDENCY,
    CHANGE_MODIFY_STEP,
)
from planning.proposal_applier import (
    ProposalApplier,
    RESULT_APPLIED,
    RESULT_ALREADY_PRESENT,
    RESULT_NOT_PRESENT,
    RESULT_UNSUPPORTED_CHANGE_TYPE,
    RESULT_UNKNOWN_TARGET_STEP,
    RESULT_INVALID_CAPABILITY,
    RESULT_INPUT_ALREADY_PRESENT,
    RESULT_INVALID_INPUT_DATA,
    RESULT_OUTPUT_ALREADY_PRESENT,
    RESULT_INVALID_OUTPUT_DATA,
    RESULT_INVALID_POSITION,
    RESULT_INVALID_DEPENDENCY,
    RESULT_UNKNOWN_DEPENDENCY_STEP,
    RESULT_SELF_DEPENDENCY,
    RESULT_DEPENDENCY_ALREADY_PRESENT,
    RESULT_DEPENDENCY_CYCLE,
    RESULT_DEPENDENCY_NOT_PRESENT,
)


def _make_plan(required_capabilities=None, input_data=None, output_data=None):
    step = PlanStep(
        step_id="plan-1-step-1",
        description="Do the thing",
        required_capabilities=required_capabilities,
        status=STATUS_PENDING,
        input_data=input_data,
        output_data=output_data,
    )
    return Plan("plan-1", "goal-1", steps=[step])


def _make_multi_step_plan():
    """A 3-step plan (A -> B -> C, via dependencies) for REORDER_STEP
    tests, where step order in `plan.steps` is independent of the
    dependency chain between them."""
    step_a = PlanStep(step_id="plan-1-step-1", description="Step A")
    step_b = PlanStep(step_id="plan-1-step-2", description="Step B", dependencies=["plan-1-step-1"])
    step_c = PlanStep(step_id="plan-1-step-3", description="Step C", dependencies=["plan-1-step-2"])
    return Plan("plan-1", "goal-1", steps=[step_a, step_b, step_c])


class TestAddCapabilityRequirement(unittest.TestCase):
    def setUp(self):
        self.applier = ProposalApplier()

    def test_adds_capability_not_already_present(self):
        plan = _make_plan(required_capabilities=["existing_cap"])
        change = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="needs it", source_blocker="blocker-1",
            proposed_data={"capability": "new_cap"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(result["reason_code"], RESULT_APPLIED)
        step = plan.steps[0]
        self.assertEqual(step.required_capabilities, ["existing_cap", "new_cap"])

    def test_does_not_add_duplicate_capability(self):
        plan = _make_plan(required_capabilities=["already_there"])
        change = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="needs it", source_blocker="blocker-1",
            proposed_data={"capability": "already_there"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(result["reason_code"], RESULT_ALREADY_PRESENT)
        step = plan.steps[0]
        self.assertEqual(step.required_capabilities, ["already_there"])

    def test_accepts_a_plain_dict_shaped_like_a_proposed_change(self):
        plan = _make_plan()
        change = {
            "change_id": "change-99",
            "change_type": CHANGE_ADD_CAPABILITY_REQUIREMENT,
            "target_step_id": "plan-1-step-1",
            "proposed_data": {"capability": "dict_cap"},
        }

        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(plan.steps[0].required_capabilities, ["dict_cap"])


class TestRemoveCapabilityRequirement(unittest.TestCase):
    def setUp(self):
        self.applier = ProposalApplier()

    def test_removes_capability_that_is_present(self):
        plan = _make_plan(required_capabilities=["cap_a", "cap_b"])
        change = ProposedChange(
            CHANGE_REMOVE_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="no longer needed", source_blocker="blocker-2",
            proposed_data={"capability": "cap_a"}, confidence=1.0,
        )

        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(result["reason_code"], RESULT_APPLIED)
        self.assertEqual(plan.steps[0].required_capabilities, ["cap_b"])

    def test_removing_a_capability_not_present_is_a_safe_no_op(self):
        plan = _make_plan(required_capabilities=["cap_b"])
        change = ProposedChange(
            CHANGE_REMOVE_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="no longer needed", source_blocker="blocker-2",
            proposed_data={"capability": "missing_cap"}, confidence=1.0,
        )

        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(result["reason_code"], RESULT_NOT_PRESENT)
        self.assertEqual(plan.steps[0].required_capabilities, ["cap_b"])


class TestProvideInput(unittest.TestCase):
    def setUp(self):
        self.applier = ProposalApplier()

    def test_successful_input_application(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_PROVIDE_INPUT, "plan-1-step-1",
            reason="has completed dependency output", source_blocker="blocker-4",
            proposed_data={"input_data": {"query": "tokyo flights", "count": 3}},
            confidence=0.8,
        )

        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(result["reason_code"], RESULT_APPLIED)
        self.assertEqual(
            plan.steps[0].get_input(), {"query": "tokyo flights", "count": 3},
        )

    def test_existing_input_is_not_overwritten(self):
        plan = _make_plan(input_data={"original": True})
        change = ProposedChange(
            CHANGE_PROVIDE_INPUT, "plan-1-step-1",
            reason="has completed dependency output", source_blocker="blocker-4",
            proposed_data={"input_data": {"replacement": True}},
            confidence=0.8,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_INPUT_ALREADY_PRESENT)
        self.assertEqual(plan.steps[0].get_input(), {"original": True})

    def test_rejects_missing_input_data_in_proposed_data(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_PROVIDE_INPUT, "plan-1-step-1",
            reason="has completed dependency output", source_blocker="blocker-4",
            proposed_data={}, confidence=0.8,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_INVALID_INPUT_DATA)
        self.assertIsNone(plan.steps[0].get_input())


class TestProvideOutput(unittest.TestCase):
    def setUp(self):
        self.applier = ProposalApplier()

    def test_successful_output_application(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_PROVIDE_OUTPUT, "plan-1-step-1",
            reason="step is completed and declares expected_output",
            source_blocker="blocker-5",
            proposed_data={"output_data": {"result": "booked", "confirmation": 42}},
            confidence=0.7,
        )

        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(result["reason_code"], RESULT_APPLIED)
        self.assertEqual(
            plan.steps[0].get_output(), {"result": "booked", "confirmation": 42},
        )

    def test_existing_output_is_not_overwritten(self):
        plan = _make_plan(output_data={"original": True})
        change = ProposedChange(
            CHANGE_PROVIDE_OUTPUT, "plan-1-step-1",
            reason="step is completed and declares expected_output",
            source_blocker="blocker-5",
            proposed_data={"output_data": {"replacement": True}},
            confidence=0.7,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_OUTPUT_ALREADY_PRESENT)
        self.assertEqual(plan.steps[0].get_output(), {"original": True})

    def test_invalid_target_and_change_fail_safely(self):
        plan = _make_plan()

        # Unknown target step.
        unknown_step_change = ProposedChange(
            CHANGE_PROVIDE_OUTPUT, "no-such-step",
            reason="step is completed and declares expected_output",
            source_blocker="blocker-5",
            proposed_data={"output_data": {"a": 1}}, confidence=0.7,
        )
        unknown_step_result = self.applier.apply_change(plan, unknown_step_change)
        self.assertFalse(unknown_step_result["success"])
        self.assertEqual(unknown_step_result["reason_code"], RESULT_UNKNOWN_TARGET_STEP)

        # Missing output_data in proposed_data.
        missing_data_change = ProposedChange(
            CHANGE_PROVIDE_OUTPUT, "plan-1-step-1",
            reason="step is completed and declares expected_output",
            source_blocker="blocker-5",
            proposed_data={}, confidence=0.7,
        )
        missing_data_result = self.applier.apply_change(plan, missing_data_change)
        self.assertFalse(missing_data_result["success"])
        self.assertEqual(missing_data_result["reason_code"], RESULT_INVALID_OUTPUT_DATA)
        self.assertIsNone(plan.steps[0].get_output())


class TestReorderStep(unittest.TestCase):
    def setUp(self):
        self.applier = ProposalApplier()

    def test_successful_reordering(self):
        plan = _make_multi_step_plan()
        change = ProposedChange(
            CHANGE_REORDER_STEP, "plan-1-step-1",
            reason="run step A last", source_blocker="blocker-6",
            proposed_data={"new_position": 2}, confidence=0.6,
        )

        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(result["reason_code"], RESULT_APPLIED)
        self.assertEqual(
            [s.step_id for s in plan.steps],
            ["plan-1-step-2", "plan-1-step-3", "plan-1-step-1"],
        )

    def test_invalid_step_id(self):
        plan = _make_multi_step_plan()
        original_order = [s.step_id for s in plan.steps]
        change = ProposedChange(
            CHANGE_REORDER_STEP, "no-such-step",
            reason="run step A last", source_blocker="blocker-6",
            proposed_data={"new_position": 1}, confidence=0.6,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_UNKNOWN_TARGET_STEP)
        self.assertEqual([s.step_id for s in plan.steps], original_order)

    def test_invalid_position(self):
        plan = _make_multi_step_plan()
        original_order = [s.step_id for s in plan.steps]

        # Out of range (too high).
        too_high = ProposedChange(
            CHANGE_REORDER_STEP, "plan-1-step-1",
            reason="run step A last", source_blocker="blocker-6",
            proposed_data={"new_position": 3}, confidence=0.6,
        )
        too_high_result = self.applier.apply_change(plan, too_high)
        self.assertFalse(too_high_result["success"])
        self.assertEqual(too_high_result["reason_code"], RESULT_INVALID_POSITION)

        # Negative.
        negative = ProposedChange(
            CHANGE_REORDER_STEP, "plan-1-step-1",
            reason="run step A last", source_blocker="blocker-6",
            proposed_data={"new_position": -1}, confidence=0.6,
        )
        negative_result = self.applier.apply_change(plan, negative)
        self.assertFalse(negative_result["success"])
        self.assertEqual(negative_result["reason_code"], RESULT_INVALID_POSITION)

        # Nothing moved for either rejected attempt.
        self.assertEqual([s.step_id for s in plan.steps], original_order)

    def test_dependencies_remain_unchanged_after_reorder(self):
        plan = _make_multi_step_plan()
        original_dependencies = {s.step_id: list(s.dependencies) for s in plan.steps}

        change = ProposedChange(
            CHANGE_REORDER_STEP, "plan-1-step-3",
            reason="run step C first", source_blocker="blocker-6",
            proposed_data={"new_position": 0}, confidence=0.6,
        )
        self.applier.apply_change(plan, change)

        for step in plan.steps:
            self.assertEqual(step.dependencies, original_dependencies[step.step_id])


class TestRejections(unittest.TestCase):
    def setUp(self):
        self.applier = ProposalApplier()

    def test_rejects_unsupported_change_type(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_MODIFY_STEP, "plan-1-step-1",
            reason="unrelated", source_blocker="blocker-3",
            proposed_data={}, confidence=0.5,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_UNSUPPORTED_CHANGE_TYPE)
        # Nothing about the step changed.
        self.assertEqual(plan.steps[0].required_capabilities, [])

    def test_rejects_unknown_target_step(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "no-such-step",
            reason="needs it", source_blocker="blocker-1",
            proposed_data={"capability": "new_cap"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_UNKNOWN_TARGET_STEP)

    def test_rejects_provide_input_with_unknown_target_step(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_PROVIDE_INPUT, "no-such-step",
            reason="has completed dependency output", source_blocker="blocker-4",
            proposed_data={"input_data": {"a": 1}}, confidence=0.8,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_UNKNOWN_TARGET_STEP)

    def test_rejects_missing_capability_in_proposed_data(self):
        plan = _make_plan()
        change = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="needs it", source_blocker="blocker-1",
            proposed_data={}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_INVALID_CAPABILITY)
        self.assertEqual(plan.steps[0].required_capabilities, [])

    def test_does_not_touch_dependencies_status_or_step_count(self):
        plan = _make_plan()
        plan.steps[0].dependencies = ["some-dep"]
        plan.steps[0].status = STATUS_PENDING
        original_step_count = len(plan.steps)

        change = ProposedChange(
            CHANGE_ADD_CAPABILITY_REQUIREMENT, "plan-1-step-1",
            reason="needs it", source_blocker="blocker-1",
            proposed_data={"capability": "new_cap"}, confidence=0.9,
        )
        self.applier.apply_change(plan, change)

        self.assertEqual(plan.steps[0].dependencies, ["some-dep"])
        self.assertEqual(plan.steps[0].status, STATUS_PENDING)
        self.assertEqual(len(plan.steps), original_step_count)


class TestAddDependency(unittest.TestCase):
    def setUp(self):
        self.applier = ProposalApplier()

    def test_adds_dependency_successfully(self):
        plan = _make_multi_step_plan()
        # plan-1-step-3 currently only depends on plan-1-step-2; add a
        # second, unrelated dependency on plan-1-step-1.
        change = ProposedChange(
            CHANGE_ADD_DEPENDENCY, "plan-1-step-3",
            reason="also needs step 1 first", source_blocker="blocker-1",
            proposed_data={"dependency_step_id": "plan-1-step-1"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(result["reason_code"], RESULT_APPLIED)
        step_c = next(s for s in plan.steps if s.step_id == "plan-1-step-3")
        self.assertIn("plan-1-step-1", step_c.dependencies)
        self.assertIn("plan-1-step-2", step_c.dependencies)

    def test_rejects_duplicate_dependency(self):
        plan = _make_multi_step_plan()
        # plan-1-step-2 already depends on plan-1-step-1.
        change = ProposedChange(
            CHANGE_ADD_DEPENDENCY, "plan-1-step-2",
            reason="already there", source_blocker="blocker-1",
            proposed_data={"dependency_step_id": "plan-1-step-1"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_DEPENDENCY_ALREADY_PRESENT)
        step_b = next(s for s in plan.steps if s.step_id == "plan-1-step-2")
        self.assertEqual(step_b.dependencies, ["plan-1-step-1"])

    def test_rejects_self_dependency(self):
        plan = _make_multi_step_plan()
        change = ProposedChange(
            CHANGE_ADD_DEPENDENCY, "plan-1-step-1",
            reason="bad self reference", source_blocker="blocker-1",
            proposed_data={"dependency_step_id": "plan-1-step-1"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_SELF_DEPENDENCY)
        step_a = next(s for s in plan.steps if s.step_id == "plan-1-step-1")
        self.assertEqual(step_a.dependencies, [])

    def test_rejects_dependency_cycle(self):
        plan = _make_multi_step_plan()
        # Chain is A -> B -> C (C depends on B depends on A). Making A
        # depend on C would close the loop.
        change = ProposedChange(
            CHANGE_ADD_DEPENDENCY, "plan-1-step-1",
            reason="would create a cycle", source_blocker="blocker-1",
            proposed_data={"dependency_step_id": "plan-1-step-3"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_DEPENDENCY_CYCLE)
        step_a = next(s for s in plan.steps if s.step_id == "plan-1-step-1")
        self.assertEqual(step_a.dependencies, [])

    def test_rejects_unknown_dependency_step(self):
        plan = _make_multi_step_plan()
        change = ProposedChange(
            CHANGE_ADD_DEPENDENCY, "plan-1-step-1",
            reason="no such step", source_blocker="blocker-1",
            proposed_data={"dependency_step_id": "no-such-step"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_UNKNOWN_DEPENDENCY_STEP)
        step_a = next(s for s in plan.steps if s.step_id == "plan-1-step-1")
        self.assertEqual(step_a.dependencies, [])

    def test_rejects_unknown_target_step(self):
        plan = _make_multi_step_plan()
        change = ProposedChange(
            CHANGE_ADD_DEPENDENCY, "no-such-step",
            reason="unknown target", source_blocker="blocker-1",
            proposed_data={"dependency_step_id": "plan-1-step-1"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_UNKNOWN_TARGET_STEP)

    def test_rejects_missing_dependency_field(self):
        plan = _make_multi_step_plan()
        change = ProposedChange(
            CHANGE_ADD_DEPENDENCY, "plan-1-step-1",
            reason="nothing supplied", source_blocker="blocker-1",
            proposed_data={}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_INVALID_DEPENDENCY)

    def test_does_not_touch_status_input_output_or_capabilities(self):
        plan = _make_multi_step_plan()
        step_d = PlanStep(step_id="plan-1-step-4", description="Step D")
        plan.steps.append(step_d)
        step_d.required_capabilities = ["cap"]
        step_d.status = STATUS_PENDING
        original_step_count = len(plan.steps)

        change = ProposedChange(
            CHANGE_ADD_DEPENDENCY, "plan-1-step-4",
            reason="add unrelated, non-cyclical dependency", source_blocker="blocker-1",
            proposed_data={"dependency_step_id": "plan-1-step-1"}, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(step_d.dependencies, ["plan-1-step-1"])
        self.assertEqual(step_d.required_capabilities, ["cap"])
        self.assertEqual(step_d.status, STATUS_PENDING)
        self.assertIsNone(step_d.get_input())
        self.assertIsNone(step_d.get_output())
        self.assertEqual(len(plan.steps), original_step_count)


class TestRemoveDependency(unittest.TestCase):
    def setUp(self):
        self.applier = ProposalApplier()

    def test_successful_dependency_removal(self):
        plan = _make_multi_step_plan()
        # plan-1-step-2 depends on plan-1-step-1.
        change = ProposedChange(
            CHANGE_REMOVE_DEPENDENCY, "plan-1-step-2",
            reason="no longer needed", source_blocker="blocker-1",
            proposed_data={"remove_dependency": "plan-1-step-1"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(result["reason_code"], RESULT_APPLIED)
        step_b = next(s for s in plan.steps if s.step_id == "plan-1-step-2")
        self.assertNotIn("plan-1-step-1", step_b.dependencies)

    def test_dependency_not_found(self):
        plan = _make_multi_step_plan()
        change = ProposedChange(
            CHANGE_REMOVE_DEPENDENCY, "plan-1-step-2",
            reason="not actually a dependency", source_blocker="blocker-1",
            proposed_data={"remove_dependency": "plan-1-step-3"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_DEPENDENCY_NOT_PRESENT)
        step_b = next(s for s in plan.steps if s.step_id == "plan-1-step-2")
        self.assertEqual(step_b.dependencies, ["plan-1-step-1"])

    def test_invalid_target_step(self):
        plan = _make_multi_step_plan()
        change = ProposedChange(
            CHANGE_REMOVE_DEPENDENCY, "no-such-step",
            reason="unknown target", source_blocker="blocker-1",
            proposed_data={"remove_dependency": "plan-1-step-1"}, confidence=0.9,
        )

        result = self.applier.apply_change(plan, change)

        self.assertFalse(result["success"])
        self.assertEqual(result["reason_code"], RESULT_UNKNOWN_TARGET_STEP)

    def test_other_dependencies_remain_unchanged(self):
        step_a = PlanStep(step_id="plan-1-step-1", description="Step A")
        step_b = PlanStep(step_id="plan-1-step-2", description="Step B")
        step_c = PlanStep(
            step_id="plan-1-step-3", description="Step C",
            dependencies=["plan-1-step-1", "plan-1-step-2"],
        )
        plan = Plan("plan-1", "goal-1", steps=[step_a, step_b, step_c])
        original_step_count = len(plan.steps)

        change = ProposedChange(
            CHANGE_REMOVE_DEPENDENCY, "plan-1-step-3",
            reason="only remove one of two", source_blocker="blocker-1",
            proposed_data={"remove_dependency": "plan-1-step-1"}, confidence=0.9,
        )
        result = self.applier.apply_change(plan, change)

        self.assertTrue(result["success"])
        self.assertEqual(step_c.dependencies, ["plan-1-step-2"])
        self.assertEqual(step_c.status, STATUS_PENDING)
        self.assertIsNone(step_c.get_input())
        self.assertIsNone(step_c.get_output())
        self.assertEqual(step_c.required_capabilities, [])
        self.assertEqual(len(plan.steps), original_step_count)


if __name__ == "__main__":
    unittest.main()
