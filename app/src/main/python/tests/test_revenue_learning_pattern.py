"""
Tests for RevenueLearningPattern (financial/revenue_learning_pattern.py).

Covers: building a pattern from an already-computed
RevenueLearningAnalyzer analysis dict via from_analysis(), exact
task_id/opportunity_id preservation, is_valid(), success-rate
preservation, reliability initialization (starts equal to
success_rate), is_successful()/is_failed() detection,
is_reliable()/its threshold, to_dict() serialization, get_summary()
(required fields, values matching the pattern, independent returned
dict, original pattern left unchanged), and that the original
analysis dict is never modified by from_analysis().

This stage only defines the pattern's shape and how one is built from
an already-computed analysis - it does not select or execute any
strategy, and is not wired into any automatic decision system yet.

Run directly:
    python -m unittest tests.test_revenue_learning_pattern -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_learning_pattern import RevenueLearningPattern


def _make_analysis(**overrides):
    fields = dict(
        total_records=4,
        successful_records=3,
        failed_records=1,
        success_rate=0.75,
        unique_task_count=1,
        unique_opportunity_count=1,
        latest_learning_id="learning-test-1",
        latest_task_id="task-test-1",
        latest_opportunity_id="opp-test-1",
        latest_status="completed",
        has_data=True,
    )
    fields.update(overrides)
    return fields


def _make_pattern(**overrides):
    fields = dict(
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        total_records=4,
        successful_records=3,
        failed_records=1,
        success_rate=0.75,
        reliability=0.75,
        pattern_id="pattern-test-1",
    )
    fields.update(overrides)
    return RevenueLearningPattern(**fields)


# ----------------------------------------------------------------------
# 1. Creation from analysis
# ----------------------------------------------------------------------
class TestCreationFromAnalysis(unittest.TestCase):
    def test_builds_pattern_from_analysis(self):
        analysis = _make_analysis()
        pattern = RevenueLearningPattern.from_analysis("task-a", "opp-a", analysis)
        self.assertIsInstance(pattern, RevenueLearningPattern)
        self.assertEqual(pattern.task_id, "task-a")
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertEqual(pattern.total_records, 4)
        self.assertEqual(pattern.successful_records, 3)
        self.assertEqual(pattern.failed_records, 1)

    def test_preserves_exact_task_and_opportunity_ids(self):
        analysis = _make_analysis(latest_task_id="some-other-task")
        pattern = RevenueLearningPattern.from_analysis("task-x", "opp-y", analysis)
        # Ids come from the caller's arguments, never from the
        # analysis dict's own latest_* fields.
        self.assertEqual(pattern.task_id, "task-x")
        self.assertEqual(pattern.opportunity_id, "opp-y")

    def test_rejects_non_dict_analysis(self):
        with self.assertRaises(TypeError):
            RevenueLearningPattern.from_analysis("task-a", "opp-a", "not-a-dict")

    def test_handles_missing_keys_with_defaults(self):
        pattern = RevenueLearningPattern.from_analysis("task-a", "opp-a", {})
        self.assertEqual(pattern.total_records, 0)
        self.assertEqual(pattern.successful_records, 0)
        self.assertEqual(pattern.failed_records, 0)
        self.assertEqual(pattern.success_rate, 0.0)


# ----------------------------------------------------------------------
# 2. Validation
# ----------------------------------------------------------------------
class TestValidation(unittest.TestCase):
    def test_valid_pattern_passes(self):
        pattern = _make_pattern()
        self.assertTrue(pattern.is_valid())

    def test_invalid_when_counts_do_not_sum(self):
        pattern = _make_pattern(total_records=5, successful_records=3, failed_records=1)
        self.assertFalse(pattern.is_valid())

    def test_invalid_when_success_rate_out_of_bounds(self):
        pattern = _make_pattern(success_rate=1.5)
        self.assertFalse(pattern.is_valid())

    def test_invalid_when_reliability_out_of_bounds(self):
        pattern = _make_pattern(reliability=-0.1)
        self.assertFalse(pattern.is_valid())

    def test_invalid_when_task_id_empty(self):
        pattern = _make_pattern(task_id="")
        self.assertFalse(pattern.is_valid())

    def test_invalid_when_counts_negative(self):
        pattern = _make_pattern(total_records=-1, successful_records=0, failed_records=0)
        self.assertFalse(pattern.is_valid())


# ----------------------------------------------------------------------
# 3. Success-rate preservation
# ----------------------------------------------------------------------
class TestSuccessRatePreservation(unittest.TestCase):
    def test_success_rate_copied_unchanged_from_analysis(self):
        analysis = _make_analysis(success_rate=0.6)
        pattern = RevenueLearningPattern.from_analysis("task-a", "opp-a", analysis)
        self.assertEqual(pattern.success_rate, 0.6)


# ----------------------------------------------------------------------
# 4. Reliability initialization
# ----------------------------------------------------------------------
class TestReliabilityInitialization(unittest.TestCase):
    def test_reliability_starts_equal_to_success_rate(self):
        analysis = _make_analysis(success_rate=0.42)
        pattern = RevenueLearningPattern.from_analysis("task-a", "opp-a", analysis)
        self.assertEqual(pattern.reliability, pattern.success_rate)
        self.assertEqual(pattern.reliability, 0.42)


# ----------------------------------------------------------------------
# 5. Successful pattern detection
# ----------------------------------------------------------------------
class TestSuccessfulPatternDetection(unittest.TestCase):
    def test_is_successful_true_when_full_success_rate(self):
        pattern = _make_pattern(total_records=2, successful_records=2, failed_records=0, success_rate=1.0)
        self.assertTrue(pattern.is_successful())

    def test_is_successful_false_when_no_records(self):
        pattern = _make_pattern(total_records=0, successful_records=0, failed_records=0, success_rate=1.0)
        self.assertFalse(pattern.is_successful())

    def test_is_successful_false_when_partial_success(self):
        pattern = _make_pattern(total_records=2, successful_records=1, failed_records=1, success_rate=0.5)
        self.assertFalse(pattern.is_successful())


# ----------------------------------------------------------------------
# 6. Failed pattern detection
# ----------------------------------------------------------------------
class TestFailedPatternDetection(unittest.TestCase):
    def test_is_failed_true_when_zero_success_rate(self):
        pattern = _make_pattern(total_records=2, successful_records=0, failed_records=2, success_rate=0.0)
        self.assertTrue(pattern.is_failed())

    def test_is_failed_false_when_no_records(self):
        pattern = _make_pattern(total_records=0, successful_records=0, failed_records=0, success_rate=0.0)
        self.assertFalse(pattern.is_failed())

    def test_is_failed_false_when_partial_success(self):
        pattern = _make_pattern(total_records=2, successful_records=1, failed_records=1, success_rate=0.5)
        self.assertFalse(pattern.is_failed())


# ----------------------------------------------------------------------
# 7. Reliability threshold
# ----------------------------------------------------------------------
class TestReliabilityThreshold(unittest.TestCase):
    def test_is_reliable_default_threshold(self):
        pattern = _make_pattern(reliability=0.8)
        self.assertTrue(pattern.is_reliable())

    def test_is_reliable_false_below_default_threshold(self):
        pattern = _make_pattern(reliability=0.5)
        self.assertFalse(pattern.is_reliable())

    def test_is_reliable_custom_threshold(self):
        pattern = _make_pattern(reliability=0.5)
        self.assertTrue(pattern.is_reliable(min_reliability=0.4))
        self.assertFalse(pattern.is_reliable(min_reliability=0.6))

    def test_is_reliable_deterministic(self):
        pattern = _make_pattern(reliability=0.75)
        first = pattern.is_reliable(min_reliability=0.7)
        second = pattern.is_reliable(min_reliability=0.7)
        self.assertEqual(first, second)
        self.assertTrue(first)


# ----------------------------------------------------------------------
# 8. Safe serialization
# ----------------------------------------------------------------------
class TestSafeSerialization(unittest.TestCase):
    def test_to_dict_shape(self):
        pattern = _make_pattern(metadata={"note": "seasonal"})
        data = pattern.to_dict()
        self.assertEqual(data, {
            "pattern_id": "pattern-test-1",
            "task_id": "task-test-1",
            "opportunity_id": "opp-test-1",
            "total_records": 4,
            "successful_records": 3,
            "failed_records": 1,
            "success_rate": 0.75,
            "reliability": 0.75,
            "created_at": pattern.created_at,
            "metadata": {"note": "seasonal"},
        })

    def test_to_dict_metadata_is_independent_copy(self):
        pattern = _make_pattern(metadata={"note": "seasonal"})
        data = pattern.to_dict()
        data["metadata"]["note"] = "changed"
        self.assertEqual(pattern.metadata["note"], "seasonal")


# ----------------------------------------------------------------------
# 9. Original analysis remains unchanged
# ----------------------------------------------------------------------
class TestOriginalAnalysisUnchanged(unittest.TestCase):
    def test_from_analysis_does_not_mutate_input_dict(self):
        analysis = _make_analysis()
        original_copy = dict(analysis)
        RevenueLearningPattern.from_analysis("task-a", "opp-a", analysis)
        self.assertEqual(analysis, original_copy)


# ----------------------------------------------------------------------
# 10. get_summary()
# ----------------------------------------------------------------------
class TestGetSummary(unittest.TestCase):
    def test_summary_contains_all_required_fields(self):
        pattern = _make_pattern()
        summary = pattern.get_summary()
        self.assertEqual(
            set(summary.keys()),
            {
                "pattern_id",
                "task_id",
                "opportunity_id",
                "total_records",
                "successful_records",
                "failed_records",
                "success_rate",
                "reliability",
            },
        )

    def test_values_match_the_pattern(self):
        pattern = _make_pattern(
            pattern_id="pattern-summary-1",
            task_id="task-summary-1",
            opportunity_id="opp-summary-1",
            total_records=10,
            successful_records=8,
            failed_records=2,
            success_rate=0.8,
            reliability=0.8,
        )
        summary = pattern.get_summary()
        self.assertEqual(summary["pattern_id"], pattern.pattern_id)
        self.assertEqual(summary["task_id"], pattern.task_id)
        self.assertEqual(summary["opportunity_id"], pattern.opportunity_id)
        self.assertEqual(summary["total_records"], pattern.total_records)
        self.assertEqual(
            summary["successful_records"], pattern.successful_records
        )
        self.assertEqual(summary["failed_records"], pattern.failed_records)
        self.assertEqual(summary["success_rate"], pattern.success_rate)
        self.assertEqual(summary["reliability"], pattern.reliability)

    def test_returned_dictionary_is_independent(self):
        pattern = _make_pattern()
        summary = pattern.get_summary()
        summary["pattern_id"] = "changed"
        summary["total_records"] = 999
        self.assertNotEqual(pattern.pattern_id, "changed")
        self.assertNotEqual(pattern.total_records, 999)
        # A second call returns a fresh dict, unaffected by mutating
        # the first one.
        second = pattern.get_summary()
        self.assertEqual(second["pattern_id"], pattern.pattern_id)
        self.assertEqual(second["total_records"], pattern.total_records)

    def test_original_pattern_remains_unchanged(self):
        pattern = _make_pattern(
            pattern_id="pattern-summary-2",
            task_id="task-summary-2",
            opportunity_id="opp-summary-2",
            total_records=4,
            successful_records=3,
            failed_records=1,
            success_rate=0.75,
            reliability=0.75,
        )
        pattern.get_summary()
        self.assertEqual(pattern.pattern_id, "pattern-summary-2")
        self.assertEqual(pattern.task_id, "task-summary-2")
        self.assertEqual(pattern.opportunity_id, "opp-summary-2")
        self.assertEqual(pattern.total_records, 4)
        self.assertEqual(pattern.successful_records, 3)
        self.assertEqual(pattern.failed_records, 1)
        self.assertEqual(pattern.success_rate, 0.75)
        self.assertEqual(pattern.reliability, 0.75)
        self.assertTrue(pattern.is_valid())


if __name__ == "__main__":
    unittest.main()
