"""
Tests for the ExecutionResult model (execution/ foundation).

Covers: safe construction (and its guards), the STATUS_* vocabulary
and mark_* status-handling helpers, timestamp/duration derivation,
dictionary serialization, and that execution ids are always unique -
this stage adds only the structured result record, no actual
execution, so there's nothing here about running a step.

Run directly:
    python -m unittest tests.test_execution_result -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.execution_result import (
    ExecutionResult,
    STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED,
    ALL_STATUSES,
)


class TestConstruction(unittest.TestCase):
    def test_default_construction_has_expected_fields(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")

        self.assertTrue(result.execution_id)
        self.assertEqual(result.plan_id, "plan-1")
        self.assertEqual(result.step_id, "plan-1-step-1")
        self.assertEqual(result.status, STATUS_PENDING)
        self.assertIsNone(result.output)
        self.assertIsNone(result.error)
        self.assertIsNone(result.started_at)
        self.assertIsNone(result.finished_at)
        self.assertEqual(result.metadata, {})

    def test_construction_rejects_missing_plan_id(self):
        with self.assertRaises(ValueError):
            ExecutionResult(plan_id=None, step_id="plan-1-step-1")

    def test_construction_rejects_missing_step_id(self):
        with self.assertRaises(ValueError):
            ExecutionResult(plan_id="plan-1", step_id=None)

    def test_construction_rejects_empty_plan_id(self):
        with self.assertRaises(ValueError):
            ExecutionResult(plan_id="", step_id="plan-1-step-1")

    def test_construction_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1", status="bogus")

    def test_failed_construction_creates_nothing_half_built(self):
        # A ValueError during construction must not leave a partially
        # constructed object reachable anywhere - simply asserting the
        # raise (above tests) already covers this, but confirm no
        # exception escapes as anything other than ValueError.
        try:
            ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1", status="bogus")
            self.fail("Expected ValueError")
        except ValueError:
            pass
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"Expected ValueError, got {type(exc)}: {exc}")

    def test_explicit_execution_id_is_honored(self):
        result = ExecutionResult(
            plan_id="plan-1", step_id="plan-1-step-1", execution_id="custom-exec-id"
        )
        self.assertEqual(result.execution_id, "custom-exec-id")

    def test_metadata_defaults_to_independent_dict(self):
        first = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        second = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-2")
        first.metadata["k"] = "v"
        self.assertEqual(second.metadata, {})


class TestUniqueExecutionIds(unittest.TestCase):
    def test_two_results_get_different_ids_by_default(self):
        first = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        second = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-2")
        self.assertNotEqual(first.execution_id, second.execution_id)

    def test_many_results_all_get_distinct_ids(self):
        results = [
            ExecutionResult(plan_id="plan-1", step_id=f"plan-1-step-{i}") for i in range(25)
        ]
        ids = [r.execution_id for r in results]
        self.assertEqual(len(ids), len(set(ids)))


class TestSuccessfulResult(unittest.TestCase):
    def test_mark_completed_sets_status_output_and_finished_at(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        result.mark_running()
        result.mark_completed(output="all good")

        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertEqual(result.output, "all good")
        self.assertIsNone(result.error)
        self.assertTrue(result.started_at)
        self.assertTrue(result.finished_at)

    def test_mark_completed_without_output_leaves_existing_output_untouched(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1", output="earlier")
        result.mark_completed()
        self.assertEqual(result.output, "earlier")

    def test_mark_completed_does_not_overwrite_existing_finished_at(self):
        result = ExecutionResult(
            plan_id="plan-1", step_id="plan-1-step-1", finished_at="2026-01-01T00:00:00+00:00"
        )
        result.mark_completed(output="ok")
        self.assertEqual(result.finished_at, "2026-01-01T00:00:00+00:00")


class TestFailedResult(unittest.TestCase):
    def test_mark_failed_sets_status_error_and_finished_at(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        result.mark_running()
        result.mark_failed("something went wrong")

        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.error, "something went wrong")
        self.assertTrue(result.finished_at)

    def test_error_information_is_preserved_verbatim(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        error_detail = "ValueError: invalid capability 'code_analysis'"
        result.mark_failed(error_detail)
        self.assertEqual(result.error, error_detail)
        self.assertEqual(result.to_dict()["error"], error_detail)


class TestCancelledResult(unittest.TestCase):
    def test_mark_cancelled_sets_status_and_finished_at(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        result.mark_running()
        result.mark_cancelled()

        self.assertEqual(result.status, STATUS_CANCELLED)
        self.assertTrue(result.finished_at)

    def test_mark_cancelled_can_record_a_reason_in_error(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        result.mark_cancelled(reason="superseded by a newer plan")
        self.assertEqual(result.status, STATUS_CANCELLED)
        self.assertEqual(result.error, "superseded by a newer plan")

    def test_mark_cancelled_without_reason_leaves_error_none(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        result.mark_cancelled()
        self.assertIsNone(result.error)


class TestMissingOrEmptyOutput(unittest.TestCase):
    def test_output_defaults_to_none(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        self.assertIsNone(result.output)
        self.assertIsNone(result.to_dict()["output"])

    def test_empty_string_output_is_preserved_not_coerced_to_none(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1", output="")
        self.assertEqual(result.output, "")

    def test_empty_dict_output_is_preserved(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1", output={})
        self.assertEqual(result.output, {})


class TestTimestampsAndDuration(unittest.TestCase):
    def test_duration_is_none_when_no_timestamps_set(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        self.assertIsNone(result.duration)

    def test_duration_is_none_when_only_started_at_set(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        result.mark_running()
        self.assertIsNone(result.duration)

    def test_duration_computed_from_explicit_timestamps(self):
        result = ExecutionResult(
            plan_id="plan-1",
            step_id="plan-1-step-1",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:05+00:00",
        )
        self.assertEqual(result.duration, 5.0)

    def test_duration_is_none_for_unparseable_timestamps(self):
        result = ExecutionResult(
            plan_id="plan-1",
            step_id="plan-1-step-1",
            started_at="not-a-timestamp",
            finished_at="also-not-a-timestamp",
        )
        self.assertIsNone(result.duration)

    def test_mark_running_then_mark_completed_produces_started_before_finished(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        result.mark_running()
        result.mark_completed(output="done")
        self.assertIsNotNone(result.duration)
        self.assertGreaterEqual(result.duration, 0.0)


class TestDictionarySerialization(unittest.TestCase):
    def test_to_dict_contains_every_field(self):
        result = ExecutionResult(
            plan_id="plan-1",
            step_id="plan-1-step-1",
            status=STATUS_RUNNING,
            output=None,
            error=None,
            metadata={"attempt": 1},
        )
        data = result.to_dict()

        self.assertEqual(
            set(data.keys()),
            {
                "execution_id", "plan_id", "step_id", "status", "output", "error",
                "started_at", "finished_at", "duration", "metadata",
            },
        )
        self.assertEqual(data["plan_id"], "plan-1")
        self.assertEqual(data["step_id"], "plan-1-step-1")
        self.assertEqual(data["status"], STATUS_RUNNING)
        self.assertEqual(data["metadata"], {"attempt": 1})

    def test_to_dict_metadata_is_a_copy_not_a_live_reference(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1", metadata={"a": 1})
        data = result.to_dict()
        data["metadata"]["a"] = 999
        self.assertEqual(result.metadata, {"a": 1})

    def test_to_dict_reflects_current_status_after_mark_calls(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        result.mark_running()
        self.assertEqual(result.to_dict()["status"], STATUS_RUNNING)
        result.mark_completed(output="ok")
        self.assertEqual(result.to_dict()["status"], STATUS_COMPLETED)


class TestStatusHandling(unittest.TestCase):
    def test_all_statuses_are_the_expected_five(self):
        self.assertEqual(
            set(ALL_STATUSES),
            {STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED},
        )

    def test_set_status_accepts_every_recognized_status(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        for status in ALL_STATUSES:
            result.set_status(status)
            self.assertEqual(result.status, status)

    def test_set_status_rejects_unknown_status_and_leaves_status_untouched(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        result.set_status(STATUS_RUNNING)
        with self.assertRaises(ValueError):
            result.set_status("bogus")
        self.assertEqual(result.status, STATUS_RUNNING)

    def test_mark_helpers_return_self_for_chaining(self):
        result = ExecutionResult(plan_id="plan-1", step_id="plan-1-step-1")
        self.assertIs(result.mark_running(), result)
        self.assertIs(result.mark_completed(output="ok"), result)


if __name__ == "__main__":
    unittest.main()
