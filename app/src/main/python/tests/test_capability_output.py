"""
Tests for CapabilityOutput (execution/capability_output.py) - a
standardized, validated output contract for executable capabilities -
and its integration with ExecutionResult (execution_result.py) and
ExecutionContext/ExecutionEngine (execution_context.py,
execution_engine.py).

Covers: successful/failed construction, validate(), invalid
capability_name/execution_id/success, every allowed output primitive
type (str/int/float/bool/None/list/dict), nested structured output,
an unsupported object (top-level and nested), warnings, metadata,
to_dict(), is_successful(), get_output(), integration with
ExecutionResult (attach/get_capability_output(s), backward-compatible
to_dict), integration with ExecutionContext data flow (a
CapabilityOutput's normalized output usable as a previous output),
and backward compatibility with existing capability handlers that
still return their own plain output format.

Run directly:
    python -m unittest tests.test_capability_output -v
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
from planning.plan import STATUS_READY, STATUS_COMPLETED

from execution.capability import CapabilityExecutionResult, CapabilityValidationResult
from execution.capability_output import (
    CapabilityOutput,
    ALL_OUTPUT_TYPES,
    OUTPUT_TYPE_NONE, OUTPUT_TYPE_BOOL, OUTPUT_TYPE_INT, OUTPUT_TYPE_FLOAT,
    OUTPUT_TYPE_STR, OUTPUT_TYPE_LIST, OUTPUT_TYPE_DICT,
    unwrap_for_previous_output,
)
from execution.execution_result import ExecutionResult, STATUS_COMPLETED as EXEC_STATUS_COMPLETED
from execution.execution_context import ExecutionContext
from execution.execution_engine import ExecutionEngine


class _Unserializable:
    """A plain object that can never pass structured-data safety -
    same helper other tests in this project already use for this
    purpose (see tests/test_step_io.py, tests/test_execution_context.py)."""
    pass


# ----------------------------------------------------------------------
# Construction: success / failure
# ----------------------------------------------------------------------
class TestSuccessfulConstruction(unittest.TestCase):
    def test_minimal_successful_output(self):
        result = CapabilityOutput.succeeded("send_email", execution_id="exec-1", output="sent")
        self.assertTrue(result.success)
        self.assertEqual(result.capability_name, "send_email")
        self.assertEqual(result.execution_id, "exec-1")
        self.assertEqual(result.output, "sent")
        self.assertEqual(result.output_type, OUTPUT_TYPE_STR)
        self.assertIsNone(result.error)
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.metadata, {})
        self.assertTrue(result.created_at)

    def test_execution_id_is_generated_when_omitted(self):
        first = CapabilityOutput.succeeded("send_email", output="a")
        second = CapabilityOutput.succeeded("send_email", output="b")
        self.assertTrue(first.execution_id)
        self.assertTrue(second.execution_id)
        self.assertNotEqual(first.execution_id, second.execution_id)

    def test_direct_construction_matches_succeeded_convenience(self):
        result = CapabilityOutput(
            success=True, capability_name="send_email", execution_id="exec-1", output="sent",
        )
        self.assertTrue(result.success)
        self.assertIsNone(result.error)


class TestFailedConstruction(unittest.TestCase):
    def test_minimal_failed_output(self):
        result = CapabilityOutput.failed(
            "send_email", error="SMTP connection refused", execution_id="exec-2",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.capability_name, "send_email")
        self.assertEqual(result.execution_id, "exec-2")
        self.assertEqual(result.error, "SMTP connection refused")

    def test_failed_requires_a_non_empty_error(self):
        with self.assertRaises(ValueError):
            CapabilityOutput.failed("send_email", error="")
        with self.assertRaises(ValueError):
            CapabilityOutput.failed("send_email", error=None)

    def test_failed_can_still_carry_partial_output(self):
        result = CapabilityOutput.failed(
            "send_email", error="partial failure", output={"attempted": 2},
        )
        self.assertFalse(result.success)
        self.assertEqual(result.output, {"attempted": 2})


# ----------------------------------------------------------------------
# Invalid capability_name / execution_id / success
# ----------------------------------------------------------------------
class TestInvalidIdentifiers(unittest.TestCase):
    def test_missing_capability_name_raises(self):
        with self.assertRaises(ValueError):
            CapabilityOutput(success=True, capability_name="", execution_id="exec-1")

    def test_whitespace_only_capability_name_raises(self):
        with self.assertRaises(ValueError):
            CapabilityOutput(success=True, capability_name="   ", execution_id="exec-1")

    def test_non_string_capability_name_raises(self):
        with self.assertRaises(ValueError):
            CapabilityOutput(success=True, capability_name=123, execution_id="exec-1")

    def test_none_capability_name_raises(self):
        with self.assertRaises(ValueError):
            CapabilityOutput(success=True, capability_name=None, execution_id="exec-1")

    def test_empty_execution_id_raises(self):
        with self.assertRaises(ValueError):
            CapabilityOutput(success=True, capability_name="cap", execution_id="")

    def test_whitespace_only_execution_id_raises(self):
        with self.assertRaises(ValueError):
            CapabilityOutput(success=True, capability_name="cap", execution_id="   ")

    def test_non_string_execution_id_raises(self):
        with self.assertRaises(ValueError):
            CapabilityOutput(success=True, capability_name="cap", execution_id=42)

    def test_missing_execution_id_is_generated_not_an_error(self):
        result = CapabilityOutput(success=True, capability_name="cap")
        self.assertTrue(result.execution_id)


class TestInvalidSuccessValue(unittest.TestCase):
    def test_non_boolean_success_raises(self):
        with self.assertRaises(TypeError):
            CapabilityOutput(success="true", capability_name="cap", execution_id="exec-1")
        with self.assertRaises(TypeError):
            CapabilityOutput(success=1, capability_name="cap", execution_id="exec-1")
        with self.assertRaises(TypeError):
            CapabilityOutput(success=None, capability_name="cap", execution_id="exec-1")

    def test_actual_bool_values_are_accepted(self):
        CapabilityOutput(success=True, capability_name="cap", execution_id="exec-1")
        CapabilityOutput(success=False, capability_name="cap", execution_id="exec-1", error="x")


# ----------------------------------------------------------------------
# Every allowed output primitive type
# ----------------------------------------------------------------------
class TestOutputPrimitiveTypes(unittest.TestCase):
    def test_string_output(self):
        result = CapabilityOutput.succeeded("cap", output="hello")
        self.assertEqual(result.output, "hello")
        self.assertEqual(result.output_type, OUTPUT_TYPE_STR)

    def test_integer_output(self):
        result = CapabilityOutput.succeeded("cap", output=42)
        self.assertEqual(result.output, 42)
        self.assertEqual(result.output_type, OUTPUT_TYPE_INT)

    def test_float_output(self):
        result = CapabilityOutput.succeeded("cap", output=3.14)
        self.assertEqual(result.output, 3.14)
        self.assertEqual(result.output_type, OUTPUT_TYPE_FLOAT)

    def test_boolean_output(self):
        result = CapabilityOutput.succeeded("cap", output=True)
        self.assertIs(result.output, True)
        self.assertEqual(result.output_type, OUTPUT_TYPE_BOOL)

    def test_none_output(self):
        result = CapabilityOutput.succeeded("cap", output=None)
        self.assertIsNone(result.output)
        self.assertEqual(result.output_type, OUTPUT_TYPE_NONE)

    def test_list_output(self):
        result = CapabilityOutput.succeeded("cap", output=[1, "two", 3.0, None, True])
        self.assertEqual(result.output, [1, "two", 3.0, None, True])
        self.assertEqual(result.output_type, OUTPUT_TYPE_LIST)

    def test_dictionary_output(self):
        result = CapabilityOutput.succeeded("cap", output={"a": 1, "b": "two"})
        self.assertEqual(result.output, {"a": 1, "b": "two"})
        self.assertEqual(result.output_type, OUTPUT_TYPE_DICT)

    def test_nested_structured_output(self):
        nested = {"items": [{"id": 1, "tags": ["a", "b"]}, {"id": 2, "tags": []}], "count": 2}
        result = CapabilityOutput.succeeded("cap", output=nested)
        self.assertEqual(result.output, nested)
        self.assertEqual(result.output_type, OUTPUT_TYPE_DICT)
        self.assertEqual(result.warnings, [])

    def test_explicit_output_type_override_is_respected(self):
        result = CapabilityOutput.succeeded("cap", output="3.14", output_type="decimal_string")
        self.assertEqual(result.output_type, "decimal_string")

    def test_all_output_types_constant_matches_allowed_vocabulary(self):
        self.assertEqual(
            ALL_OUTPUT_TYPES,
            {
                OUTPUT_TYPE_NONE, OUTPUT_TYPE_BOOL, OUTPUT_TYPE_INT, OUTPUT_TYPE_FLOAT,
                OUTPUT_TYPE_STR, OUTPUT_TYPE_LIST, OUTPUT_TYPE_DICT,
            },
        )


# ----------------------------------------------------------------------
# Unsupported / invalid nested objects - safe, never a crash
# ----------------------------------------------------------------------
class TestUnsupportedObjects(unittest.TestCase):
    def test_unsupported_top_level_object_is_replaced_with_none(self):
        result = CapabilityOutput.succeeded("cap", output=_Unserializable())
        self.assertIsNone(result.output)
        self.assertEqual(result.output_type, OUTPUT_TYPE_NONE)
        self.assertTrue(result.warnings)
        self.assertIn("_Unserializable", result.warnings[0])

    def test_unsupported_object_never_raises(self):
        try:
            CapabilityOutput.succeeded("cap", output=lambda: "not safe")
        except Exception as exc:  # pragma: no cover - failure path for the assertion below
            self.fail(f"Unsupported output raised instead of being safely represented: {exc}")

    def test_invalid_nested_object_is_replaced_in_place(self):
        output = {"good": 1, "bad": _Unserializable(), "list": [1, _Unserializable(), 3]}
        result = CapabilityOutput.succeeded("cap", output=output)
        self.assertEqual(result.output["good"], 1)
        self.assertIsNone(result.output["bad"])
        self.assertEqual(result.output["list"], [1, None, 3])
        self.assertEqual(len(result.warnings), 2)

    def test_non_string_dict_key_is_dropped_with_a_warning(self):
        result = CapabilityOutput.succeeded("cap", output={1: "one", "two": 2})
        self.assertEqual(result.output, {"two": 2})
        self.assertTrue(result.warnings)

    def test_unsupported_output_makes_validation_fail(self):
        result = CapabilityOutput.succeeded("cap", output=_Unserializable())
        validation = result.validate()
        self.assertFalse(validation.valid)
        self.assertTrue(any(entry["field"] == "output" for entry in validation.errors))

    def test_unsupported_output_makes_is_successful_false(self):
        result = CapabilityOutput.succeeded("cap", output=_Unserializable())
        self.assertFalse(result.is_successful())

    def test_never_evaluates_a_string_as_code(self):
        # A string that looks like code must be preserved verbatim,
        # never executed or evaluated.
        result = CapabilityOutput.succeeded("cap", output="__import__('os').system('echo hi')")
        self.assertEqual(result.output, "__import__('os').system('echo hi')")
        self.assertEqual(result.output_type, OUTPUT_TYPE_STR)


# ----------------------------------------------------------------------
# Warnings
# ----------------------------------------------------------------------
class TestWarnings(unittest.TestCase):
    def test_explicit_warnings_are_preserved(self):
        result = CapabilityOutput.succeeded(
            "cap", output="ok", warnings=["rate limit near threshold"],
        )
        self.assertEqual(result.warnings, ["rate limit near threshold"])

    def test_explicit_and_normalization_warnings_are_both_kept(self):
        result = CapabilityOutput.succeeded(
            "cap", output=_Unserializable(), warnings=["slow response"],
        )
        self.assertIn("slow response", result.warnings)
        self.assertEqual(len(result.warnings), 2)

    def test_warnings_must_be_a_list_of_strings(self):
        with self.assertRaises(TypeError):
            CapabilityOutput.succeeded("cap", output="ok", warnings="not-a-list")
        with self.assertRaises(TypeError):
            CapabilityOutput.succeeded("cap", output="ok", warnings=[1, 2])

    def test_no_warnings_by_default(self):
        result = CapabilityOutput.succeeded("cap", output="ok")
        self.assertEqual(result.warnings, [])


# ----------------------------------------------------------------------
# Metadata
# ----------------------------------------------------------------------
class TestMetadata(unittest.TestCase):
    def test_metadata_defaults_to_empty_dict(self):
        result = CapabilityOutput.succeeded("cap", output="ok")
        self.assertEqual(result.metadata, {})

    def test_metadata_is_preserved(self):
        result = CapabilityOutput.succeeded("cap", output="ok", metadata={"attempt": 1})
        self.assertEqual(result.metadata, {"attempt": 1})

    def test_metadata_must_be_a_dict(self):
        with self.assertRaises(TypeError):
            CapabilityOutput.succeeded("cap", output="ok", metadata="not-a-dict")

    def test_unsupported_metadata_value_is_replaced_and_warned(self):
        result = CapabilityOutput.succeeded(
            "cap", output="ok", metadata={"handler": _Unserializable()},
        )
        self.assertIsNone(result.metadata["handler"])
        self.assertTrue(result.warnings)
        self.assertFalse(result.validate().valid)


# ----------------------------------------------------------------------
# validate()
# ----------------------------------------------------------------------
class TestValidate(unittest.TestCase):
    def test_valid_output_passes_validation(self):
        result = CapabilityOutput.succeeded("cap", output={"a": 1})
        validation = result.validate()
        self.assertIsInstance(validation, CapabilityValidationResult)
        self.assertTrue(validation.valid)
        self.assertEqual(validation.errors, [])

    def test_valid_failed_output_still_passes_validation(self):
        result = CapabilityOutput.failed("cap", error="boom")
        self.assertTrue(result.validate().valid)

    def test_manually_corrupted_output_type_fails_validation(self):
        result = CapabilityOutput.succeeded("cap", output="ok")
        result.output_type = "not-a-real-type"
        validation = result.validate()
        self.assertFalse(validation.valid)
        self.assertTrue(any(entry["field"] == "output_type" for entry in validation.errors))

    def test_manually_corrupted_error_field_fails_validation(self):
        result = CapabilityOutput.succeeded("cap", output="ok")
        result.error = 12345
        validation = result.validate()
        self.assertFalse(validation.valid)
        self.assertTrue(any(entry["field"] == "error" for entry in validation.errors))

    def test_validate_never_raises(self):
        result = CapabilityOutput.succeeded("cap", output="ok")
        result.warnings = "not-a-list"
        try:
            validation = result.validate()
        except Exception as exc:  # pragma: no cover
            self.fail(f"validate() raised instead of returning a structured failure: {exc}")
        self.assertFalse(validation.valid)


# ----------------------------------------------------------------------
# is_successful()
# ----------------------------------------------------------------------
class TestIsSuccessful(unittest.TestCase):
    def test_true_for_a_clean_successful_output(self):
        result = CapabilityOutput.succeeded("cap", output="ok")
        self.assertTrue(result.is_successful())

    def test_false_when_success_is_false(self):
        result = CapabilityOutput.failed("cap", error="boom")
        self.assertFalse(result.is_successful())

    def test_false_when_success_true_but_error_is_also_set(self):
        result = CapabilityOutput(
            success=True, capability_name="cap", execution_id="exec-1",
            output="partial", error="but something went wrong",
        )
        self.assertFalse(result.is_successful())

    def test_false_when_validation_fails_even_if_success_true(self):
        result = CapabilityOutput.succeeded("cap", output=_Unserializable())
        self.assertTrue(result.success)
        self.assertFalse(result.is_successful())


# ----------------------------------------------------------------------
# get_output()
# ----------------------------------------------------------------------
class TestGetOutput(unittest.TestCase):
    def test_returns_the_normalized_output(self):
        result = CapabilityOutput.succeeded("cap", output={"a": 1})
        self.assertEqual(result.get_output(), {"a": 1})

    def test_returns_a_defensive_copy_for_dicts(self):
        result = CapabilityOutput.succeeded("cap", output={"a": 1})
        copy_one = result.get_output()
        copy_one["a"] = 999
        self.assertEqual(result.output, {"a": 1})
        self.assertEqual(result.get_output(), {"a": 1})

    def test_returns_a_defensive_copy_for_lists(self):
        result = CapabilityOutput.succeeded("cap", output=[1, 2, 3])
        copy_one = result.get_output()
        copy_one.append(4)
        self.assertEqual(result.output, [1, 2, 3])

    def test_returns_none_when_output_is_none(self):
        result = CapabilityOutput.succeeded("cap", output=None)
        self.assertIsNone(result.get_output())


# ----------------------------------------------------------------------
# to_dict()
# ----------------------------------------------------------------------
class TestToDict(unittest.TestCase):
    def test_to_dict_contains_every_field(self):
        result = CapabilityOutput.succeeded(
            "cap", execution_id="exec-1", output={"a": 1}, warnings=["w1"], metadata={"k": "v"},
        )
        data = result.to_dict()
        self.assertEqual(
            set(data.keys()),
            {
                "success", "capability_name", "execution_id", "output", "output_type",
                "error", "warnings", "metadata", "created_at",
            },
        )
        self.assertTrue(data["success"])
        self.assertEqual(data["capability_name"], "cap")
        self.assertEqual(data["execution_id"], "exec-1")
        self.assertEqual(data["output"], {"a": 1})
        self.assertEqual(data["output_type"], OUTPUT_TYPE_DICT)
        self.assertIsNone(data["error"])
        self.assertEqual(data["warnings"], ["w1"])
        self.assertEqual(data["metadata"], {"k": "v"})
        self.assertTrue(data["created_at"])

    def test_to_dict_is_deterministic_across_calls(self):
        result = CapabilityOutput.succeeded("cap", output={"a": 1})
        self.assertEqual(result.to_dict(), result.to_dict())

    def test_to_dict_output_is_a_copy_not_a_live_reference(self):
        result = CapabilityOutput.succeeded("cap", output={"a": 1})
        data = result.to_dict()
        data["output"]["a"] = 999
        self.assertEqual(result.output, {"a": 1})


# ----------------------------------------------------------------------
# Integration with ExecutionResult
# ----------------------------------------------------------------------
class TestExecutionResultIntegration(unittest.TestCase):
    def test_attach_and_retrieve_a_capability_output(self):
        execution_result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        capability_output = CapabilityOutput.succeeded(
            "send_email", execution_id=execution_result.execution_id, output="sent",
        )
        execution_result.attach_capability_output("send_email", capability_output)

        self.assertIs(
            execution_result.get_capability_output("send_email"), capability_output
        )
        self.assertIsNone(execution_result.get_capability_output("unknown"))

    def test_get_capability_outputs_returns_a_defensive_copy(self):
        execution_result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        capability_output = CapabilityOutput.succeeded("cap", output="ok")
        execution_result.attach_capability_output("cap", capability_output)

        copy_one = execution_result.get_capability_outputs()
        copy_one["cap"] = None
        self.assertIsNotNone(execution_result.get_capability_output("cap"))

    def test_attach_rejects_a_non_capability_output(self):
        execution_result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        with self.assertRaises(TypeError):
            execution_result.attach_capability_output("cap", "not-a-capability-output")

    def test_attach_rejects_an_empty_capability_name(self):
        execution_result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        capability_output = CapabilityOutput.succeeded("cap", output="ok")
        with self.assertRaises(ValueError):
            execution_result.attach_capability_output("", capability_output)

    def test_to_dict_omits_capability_outputs_key_when_none_attached(self):
        execution_result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        self.assertNotIn("capability_outputs", execution_result.to_dict())

    def test_to_dict_includes_capability_outputs_when_attached(self):
        execution_result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        capability_output = CapabilityOutput.succeeded("cap", output="ok")
        execution_result.attach_capability_output("cap", capability_output)

        data = execution_result.to_dict()
        self.assertIn("capability_outputs", data)
        self.assertEqual(data["capability_outputs"]["cap"], capability_output.to_dict())

    def test_backward_compatible_field_set_is_unchanged_by_default(self):
        # Same exact-field check test_execution_result.py already
        # applies - never gains a new key when CapabilityOutput is
        # never used.
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        self.assertEqual(
            set(result.to_dict().keys()),
            {
                "execution_id", "plan_id", "step_id", "status", "output", "error",
                "started_at", "finished_at", "duration", "metadata",
            },
        )

    def test_from_capability_execution_result_success(self):
        execution_result_source = CapabilityExecutionResult(success=True, output={"sent": True})
        capability_output = CapabilityOutput.from_capability_execution_result(
            "send_email", "exec-9", execution_result_source,
        )
        self.assertTrue(capability_output.is_successful())
        self.assertEqual(capability_output.output, {"sent": True})
        self.assertEqual(capability_output.execution_id, "exec-9")

    def test_from_capability_execution_result_failure(self):
        execution_result_source = CapabilityExecutionResult(success=False, error="bad input")
        capability_output = CapabilityOutput.from_capability_execution_result(
            "send_email", "exec-9", execution_result_source,
        )
        self.assertFalse(capability_output.is_successful())
        self.assertEqual(capability_output.error, "bad input")

    def test_from_capability_execution_result_rejects_wrong_type(self):
        with self.assertRaises(TypeError):
            CapabilityOutput.from_capability_execution_result("cap", "exec-1", "not-a-result")


# ----------------------------------------------------------------------
# Integration with ExecutionContext
# ----------------------------------------------------------------------
class TestExecutionContextIntegration(unittest.TestCase):
    def test_unwrap_for_previous_output_returns_normalized_output(self):
        capability_output = CapabilityOutput.succeeded("cap", output={"a": 1})
        self.assertEqual(unwrap_for_previous_output(capability_output), {"a": 1})

    def test_unwrap_for_previous_output_passes_through_non_capability_output(self):
        self.assertEqual(unwrap_for_previous_output("plain-value"), "plain-value")
        self.assertEqual(unwrap_for_previous_output({"already": "safe"}), {"already": "safe"})
        self.assertIsNone(unwrap_for_previous_output(None))

    def test_unwrapped_output_can_be_used_as_a_previous_output(self):
        capability_output = CapabilityOutput.succeeded("cap", output={"sent": True})
        context = ExecutionContext(plan_id="plan-1", step_id="plan-1-step-1")
        context.add_previous_output("first", unwrap_for_previous_output(capability_output))
        self.assertEqual(context.get_previous_outputs(), {"first": {"sent": True}})


# ----------------------------------------------------------------------
# End-to-end integration with ExecutionEngine.execute_capability_step
# and backward compatibility with existing capability handlers
# ----------------------------------------------------------------------
class TestExecutionEngineEndToEnd(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.engine = ExecutionEngine(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _ready_step(self, **kwargs):
        step = self.plans.add_step(self.plan.plan_id, "Do a thing", **kwargs)
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STATUS_READY)
        return step

    def test_handler_returning_capability_output_is_attached_to_result(self):
        step = self._ready_step(required_capabilities=["send_email"])

        def handler(plan_step, context):
            return CapabilityOutput.succeeded(
                "send_email", execution_id=context.execution_id, output="sent",
            )

        self.engine.capability_handlers.register("send_email", handler)
        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        attached = result.get_capability_output("send_email")
        self.assertIsInstance(attached, CapabilityOutput)
        self.assertTrue(attached.is_successful())
        self.assertEqual(
            self.plans.get_step(self.plan.plan_id, step.step_id).status, STATUS_COMPLETED,
        )

    def test_capability_output_flows_as_previous_output_to_next_handler(self):
        step = self._ready_step(required_capabilities=["first", "second"])
        captured = {}

        def first_handler(plan_step, context):
            return CapabilityOutput.succeeded(
                "first", execution_id=context.execution_id, output={"id": 7},
            )

        def second_handler(plan_step, context):
            captured["previous"] = context.get_previous_outputs()
            return "second-output"

        self.engine.capability_handlers.register("first", first_handler)
        self.engine.capability_handlers.register("second", second_handler)

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(captured["previous"], {"first": {"id": 7}})

    def test_existing_plain_handler_output_is_completely_unaffected(self):
        step = self._ready_step(required_capabilities=["send_email"])
        self.engine.capability_handlers.register(
            "send_email", lambda plan_step: f"sent for {plan_step.step_id}"
        )

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.status, EXEC_STATUS_COMPLETED)
        self.assertEqual(result.output, {"send_email": f"sent for {step.step_id}"})
        self.assertEqual(result.get_capability_outputs(), {})
        self.assertNotIn("capability_outputs", result.to_dict())

    def test_mixed_handlers_only_attach_the_capability_output_ones(self):
        step = self._ready_step(required_capabilities=["first", "second"])
        self.engine.capability_handlers.register("first", lambda s: "plain-output")

        def second_handler(plan_step, context):
            return CapabilityOutput.succeeded(
                "second", execution_id=context.execution_id, output="standardized",
            )

        self.engine.capability_handlers.register("second", second_handler)

        result = self.engine.execute_capability_step(self.plan.plan_id, step.step_id)

        self.assertEqual(result.output["first"], "plain-output")
        self.assertIsInstance(result.output["second"], CapabilityOutput)
        self.assertIsNone(result.get_capability_output("first"))
        self.assertIsNotNone(result.get_capability_output("second"))


if __name__ == "__main__":
    unittest.main()
