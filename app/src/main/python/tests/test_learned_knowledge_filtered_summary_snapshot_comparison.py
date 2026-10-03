"""
Tests for Prompt 518 - Filtered Diagnostic Snapshot Comparison.

`compare_learned_knowledge_filtered_summary_snapshots(earlier, later)`
(learning/learned_knowledge_statistics.py) compares two Prompt 517
filtered-summary snapshots, reusing the Prompt 509 comparison
vocabulary and numeric-entry shape. It is deterministic and read-only:
it mutates neither snapshot, nor any history, statistics, trace,
learned record, or response path, and nothing reads its result to
change behavior.

Covers:
    1.  identical sections, identical values
    2.  identical sections, different values
    3.  increased numeric metric
    4.  decreased numeric metric
    5.  unchanged numeric metric
    6.  section present only in earlier snapshot
    7.  section present only in later snapshot
    8.  section unavailable in both snapshots
    9.  different selected-section sets
    10. identical snapshots
    11. invalid earlier snapshot (structurally malformed)
    12. invalid later snapshot (structurally malformed)
    13. both snapshots invalid (structurally malformed)
    14. zero-evaluation snapshots
    15. missing optional categorical value (dominant_rejection_reason)
    16. changed categorical value
    17. unchanged categorical value
    18. deterministic comparison output
    19. earlier snapshot is not mutated
    20. later snapshot is not mutated
    21. comparison result is isolated from source objects
    22. Prompt 509 comparison behavior unchanged
    23. Prompt 517 snapshot behavior unchanged
    24. regression coverage for Prompts 500-517 (well-formed-but-invalid
        filtered snapshots preserved as such)

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_summary_snapshot_comparison -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK, REASON_NOT_RELEVANT, REASON_INSUFFICIENT_RELIABILITY,
    LearnedKnowledgeGateResult, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    LearnedKnowledgeFilteredSummarySnapshotHistory,
    SNAPSHOT_VALIDATION_VALID, SNAPSHOT_VALIDATION_INVALID,
    REPORT_VALIDITY_INVALID,
    COMPARISON_DIRECTION,
    CHANGE_UNCHANGED, CHANGE_CHANGED, CHANGE_BECAME_EMPTY, CHANGE_BECAME_AVAILABLE,
    FILTERED_COMPARISON_PRESENT_BOTH, FILTERED_COMPARISON_PRESENT_ONLY_EARLIER,
    FILTERED_COMPARISON_PRESENT_ONLY_LATER, FILTERED_COMPARISON_UNAVAILABLE_BOTH,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
)

_ALL_SECTIONS = [
    "evaluation_counts", "rates", "dominant_rejection_reason",
    "comparison_changes", "trend", "validation_statuses",
]


def _gtrace(status, reason, **numbers):
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(status, reason, **numbers))


ACCEPTED = _gtrace(STATUS_PASSED, REASON_OK)
IRRELEVANT = _gtrace("REJECTED", REASON_NOT_RELEVANT)
LOW_RELIABILITY = _gtrace("REJECTED", REASON_INSUFFICIENT_RELIABILITY)


def _stats(accepted=0, irrelevant=0, low_reliability=0):
    stats = LearnedKnowledgeDecisionStatistics()
    for gate_trace, count in ((ACCEPTED, accepted), (IRRELEVANT, irrelevant), (LOW_RELIABILITY, low_reliability)):
        for _ in range(count):
            stats.record(gate_trace)
    return stats


def _history(counts_list):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for counts in counts_list:
        history.record_statistics(_stats(**counts))
    return history


def _chain(history):
    return [history.compare_sequences(i, i + 1) for i in range(1, len(history))]


def _summary(counts_list=None):
    history = _history(counts_list or [{"accepted": 1}, {"accepted": 3}, {"irrelevant": 2}])
    comparisons = _chain(history)
    built = report(snapshots=history, comparisons=comparisons)
    validation = validate(built, snapshots=history, comparisons=comparisons)
    return fmt(built, validation)


def _filtered_snapshot(sections, counts_list=None):
    """A real, valid Prompt 517 filtered-summary snapshot."""
    filtered = filt(_summary(counts_list), sections)
    return LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)


def _invalid_summary():
    history = _history([{"accepted": 1}])
    built = report(snapshots=history)
    broken = copy.deepcopy(built)
    broken["structural_status"] = "unknown"
    validation = validate(broken)
    assert not validation["valid"]
    return fmt(broken, validation)


def _invalid_filtered_snapshot(sections):
    """A well-formed Prompt 517 snapshot whose own validation is invalid
    (as opposed to a structurally malformed input)."""
    filtered = filt(_invalid_summary(), sections)
    assert filtered["report_validity"] == REPORT_VALIDITY_INVALID
    return LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)


class Prompt518TestCase(unittest.TestCase):
    pass


# ----------------------------------------------------------------------
# 1/10/18. identical sections, identical values / identical snapshots / determinism
# ----------------------------------------------------------------------
class TestIdentical(Prompt518TestCase):

    def test_identical_filtered_snapshots_are_reported_as_identical(self):
        snap = _filtered_snapshot(_ALL_SECTIONS)
        snap2 = copy.deepcopy(snap)
        snap2["snapshot_id"] = "learned_knowledge_snapshot_000002"
        snap2["sequence"] = 2
        result = compare(snap, snap2)
        self.assertTrue(result["valid"])
        self.assertTrue(result["identical"])
        self.assertEqual(result["changed_sections"], [])
        self.assertEqual(result["common_sections"], _ALL_SECTIONS)

    def test_same_object_compared_to_itself_is_identical(self):
        snap = _filtered_snapshot(["rates"])
        result = compare(snap, snap)
        self.assertTrue(result["identical"])
        for entry in result["numeric"].values():
            self.assertEqual(entry["delta"], 0)
            self.assertFalse(entry["changed"])

    def test_deterministic_output_for_equal_inputs(self):
        a = _filtered_snapshot(_ALL_SECTIONS, [{"accepted": 2}, {"accepted": 5}])
        b = _filtered_snapshot(_ALL_SECTIONS, [{"accepted": 1}, {"accepted": 9}])
        self.assertEqual(compare(a, b), compare(copy.deepcopy(a), copy.deepcopy(b)))
        self.assertEqual(compare(a, b), compare(a, b))


# ----------------------------------------------------------------------
# 2/3/4/5. numeric deltas
# ----------------------------------------------------------------------
class TestNumericDeltas(Prompt518TestCase):

    def test_different_values_same_sections(self):
        earlier = _filtered_snapshot(["evaluation_counts"], [{"accepted": 1}])
        later = _filtered_snapshot(["evaluation_counts"], [{"accepted": 1}, {"accepted": 3}])
        result = compare(earlier, later)
        self.assertTrue(result["valid"])
        self.assertFalse(result["identical"])
        self.assertIn("evaluation_counts", result["changed_sections"])

    def test_increased_metric(self):
        earlier = _filtered_snapshot(["evaluation_counts"], [{"accepted": 1}])
        later = _filtered_snapshot(["evaluation_counts"], [{"accepted": 1}, {"accepted": 4}])
        result = compare(earlier, later)
        entry = result["numeric"]["total_evaluations"]
        self.assertGreater(entry["delta"], 0)
        self.assertTrue(entry["changed"])
        self.assertEqual(entry["delta"], entry["later"] - entry["earlier"])

    def test_decreased_metric_via_reversed_arguments(self):
        a = _filtered_snapshot(["evaluation_counts"], [{"accepted": 1}])
        b = _filtered_snapshot(["evaluation_counts"], [{"accepted": 1}, {"accepted": 4}])
        # b (more evaluations) as earlier, a (fewer) as later -> negative delta
        result = compare(b, a)
        entry = result["numeric"]["total_evaluations"]
        self.assertLess(entry["delta"], 0)
        self.assertTrue(entry["changed"])

    def test_unchanged_metric(self):
        earlier = _filtered_snapshot(["evaluation_counts"], [{"accepted": 2}])
        later = _filtered_snapshot(["evaluation_counts"], [{"accepted": 2}])
        result = compare(earlier, later)
        entry = result["numeric"]["total_evaluations"]
        self.assertEqual(entry["delta"], 0)
        self.assertFalse(entry["changed"])
        self.assertNotIn("evaluation_counts", result["changed_sections"])

    def test_direction_is_later_minus_earlier(self):
        self.assertEqual(compare(
            _filtered_snapshot(["rates"]), _filtered_snapshot(["rates"]))["direction"],
            COMPARISON_DIRECTION)
        self.assertEqual(COMPARISON_DIRECTION, "later_minus_earlier")


# ----------------------------------------------------------------------
# 6/7/8/9. section presence
# ----------------------------------------------------------------------
class TestSectionPresence(Prompt518TestCase):

    def test_section_present_only_in_earlier(self):
        earlier = _filtered_snapshot(["rates", "trend"])
        later = _filtered_snapshot(["rates"])
        result = compare(earlier, later)
        self.assertEqual(result["sections"]["trend"]["presence"],
                          FILTERED_COMPARISON_PRESENT_ONLY_EARLIER)
        self.assertIsNone(result["sections"]["trend"]["later"])
        self.assertIsNotNone(result["sections"]["trend"]["earlier"])
        self.assertNotIn("trend", result["common_sections"])

    def test_section_present_only_in_later(self):
        earlier = _filtered_snapshot(["rates"])
        later = _filtered_snapshot(["rates", "trend"])
        result = compare(earlier, later)
        self.assertEqual(result["sections"]["trend"]["presence"],
                          FILTERED_COMPARISON_PRESENT_ONLY_LATER)
        self.assertIsNone(result["sections"]["trend"]["earlier"])
        self.assertIsNotNone(result["sections"]["trend"]["later"])

    def test_section_unavailable_in_both(self):
        earlier = _filtered_snapshot(["rates"])
        later = _filtered_snapshot(["rates"])
        result = compare(earlier, later)
        self.assertEqual(result["sections"]["trend"]["presence"],
                          FILTERED_COMPARISON_UNAVAILABLE_BOTH)
        self.assertIsNone(result["sections"]["trend"]["earlier"])
        self.assertIsNone(result["sections"]["trend"]["later"])

    def test_different_selected_section_sets(self):
        earlier = _filtered_snapshot(["evaluation_counts", "rates"])
        later = _filtered_snapshot(["rates", "dominant_rejection_reason"])
        result = compare(earlier, later)
        self.assertEqual(result["common_sections"], ["rates"])
        self.assertEqual(result["sections"]["evaluation_counts"]["presence"],
                          FILTERED_COMPARISON_PRESENT_ONLY_EARLIER)
        self.assertEqual(result["sections"]["dominant_rejection_reason"]["presence"],
                          FILTERED_COMPARISON_PRESENT_ONLY_LATER)
        self.assertEqual(result["sections"]["trend"]["presence"],
                          FILTERED_COMPARISON_UNAVAILABLE_BOTH)

    def test_only_present_in_both_sections_are_in_numeric(self):
        earlier = _filtered_snapshot(["evaluation_counts"])
        later = _filtered_snapshot(["rates"])
        result = compare(earlier, later)
        self.assertEqual(result["numeric"], {})


# ----------------------------------------------------------------------
# 11/12/13. invalid (structurally malformed) inputs
# ----------------------------------------------------------------------
class TestInvalidInputs(Prompt518TestCase):

    def test_invalid_earlier_input(self):
        result = compare(None, _filtered_snapshot(["rates"]))
        self.assertFalse(result["valid"])
        self.assertEqual(result["invalid_inputs"], ["earlier"])
        self.assertEqual(result["errors"], ["earlier_snapshot_invalid"])
        self.assertEqual(result["earlier_errors"], ["snapshot_missing"])
        self.assertEqual(result["later_errors"], [])

    def test_invalid_later_input(self):
        result = compare(_filtered_snapshot(["rates"]), {"not": "a snapshot"})
        self.assertFalse(result["valid"])
        self.assertEqual(result["invalid_inputs"], ["later"])
        self.assertEqual(result["errors"], ["later_snapshot_invalid"])
        self.assertEqual(result["earlier_errors"], [])
        self.assertTrue(result["later_errors"])

    def test_both_invalid_inputs(self):
        result = compare("nope", 12345)
        self.assertFalse(result["valid"])
        self.assertEqual(result["invalid_inputs"], ["earlier", "later"])
        self.assertEqual(result["errors"], ["earlier_snapshot_invalid", "later_snapshot_invalid"])
        self.assertEqual(result["earlier_validation_information"], None)
        self.assertEqual(result["later_validation_information"], None)

    def test_invalid_input_result_keys(self):
        result = compare(None, None)
        self.assertEqual(list(result.keys()), [
            "valid", "direction", "errors", "invalid_inputs", "earlier_errors",
            "later_errors", "earlier_validation_information", "later_validation_information",
        ])


# ----------------------------------------------------------------------
# 24. well-formed-but-invalid filtered snapshots (own validation failed)
# ----------------------------------------------------------------------
class TestOwnValidationInvalid(Prompt518TestCase):

    def test_invalid_filtered_snapshot_contributes_nothing_present(self):
        earlier = _invalid_filtered_snapshot(["rates", "trend"])
        later = _filtered_snapshot(["rates"])
        result = compare(earlier, later)
        self.assertTrue(result["valid"])  # structurally fine snapshots
        self.assertEqual(result["earlier_validation_status"], SNAPSHOT_VALIDATION_INVALID)
        self.assertEqual(result["later_validation_status"], SNAPSHOT_VALIDATION_VALID)
        self.assertEqual(result["common_sections"], [])
        self.assertEqual(result["sections"]["rates"]["presence"],
                          FILTERED_COMPARISON_PRESENT_ONLY_LATER)

    def test_both_own_validation_invalid(self):
        earlier = _invalid_filtered_snapshot(["rates"])
        later = _invalid_filtered_snapshot(["trend"])
        result = compare(earlier, later)
        self.assertTrue(result["valid"])
        self.assertEqual(result["earlier_validation_status"], SNAPSHOT_VALIDATION_INVALID)
        self.assertEqual(result["later_validation_status"], SNAPSHOT_VALIDATION_INVALID)
        self.assertEqual(result["common_sections"], [])
        self.assertTrue(result["identical"])


# ----------------------------------------------------------------------
# 14. zero-evaluation snapshots
# ----------------------------------------------------------------------
class TestZeroEvaluations(Prompt518TestCase):

    def test_zero_evaluation_snapshots_compare_safely(self):
        earlier = _filtered_snapshot(["evaluation_counts", "rates"], [{}])
        later = _filtered_snapshot(["evaluation_counts", "rates"], [{}])
        result = compare(earlier, later)
        self.assertTrue(result["valid"])
        self.assertTrue(result["identical"])
        for field in ("total_evaluations", "accepted_count", "rejected_count",
                      "no_candidate_count", "acceptance_rate", "rejection_rate"):
            self.assertEqual(result["numeric"][field]["earlier"], 0)
            self.assertEqual(result["numeric"][field]["later"], 0)
            self.assertEqual(result["numeric"][field]["delta"], 0)
            self.assertFalse(result["numeric"][field]["changed"])


# ----------------------------------------------------------------------
# 15/16/17. categorical value (dominant_rejection_reason)
# ----------------------------------------------------------------------
class TestCategorical(Prompt518TestCase):

    def test_missing_optional_categorical_value_both_none(self):
        earlier = _filtered_snapshot(["dominant_rejection_reason"], [{"accepted": 1}])
        later = _filtered_snapshot(["dominant_rejection_reason"], [{"accepted": 3}])
        result = compare(earlier, later)
        entry = result["sections"]["dominant_rejection_reason"]
        self.assertIsNone(entry["earlier"])
        self.assertIsNone(entry["later"])
        self.assertEqual(entry["change"], CHANGE_UNCHANGED)
        self.assertFalse(entry["changed"])

    def test_unchanged_categorical_value(self):
        earlier = _filtered_snapshot(["dominant_rejection_reason"], [{"irrelevant": 2}])
        later = _filtered_snapshot(["dominant_rejection_reason"], [{"irrelevant": 5}])
        result = compare(earlier, later)
        entry = result["sections"]["dominant_rejection_reason"]
        self.assertEqual(entry["earlier"], entry["later"])
        self.assertEqual(entry["change"], CHANGE_UNCHANGED)
        self.assertFalse(entry["changed"])

    def test_changed_categorical_value(self):
        earlier = _filtered_snapshot(["dominant_rejection_reason"], [{"irrelevant": 3}])
        later = _filtered_snapshot(["dominant_rejection_reason"], [{"low_reliability": 3}])
        result = compare(earlier, later)
        entry = result["sections"]["dominant_rejection_reason"]
        self.assertEqual(entry["change"], CHANGE_CHANGED)
        self.assertTrue(entry["changed"])

    def test_categorical_became_available_and_empty(self):
        earlier = _filtered_snapshot(["dominant_rejection_reason"], [{"accepted": 1}])
        later = _filtered_snapshot(["dominant_rejection_reason"], [{"irrelevant": 1}])
        result = compare(earlier, later)
        self.assertEqual(result["sections"]["dominant_rejection_reason"]["change"],
                          CHANGE_BECAME_AVAILABLE)
        result_back = compare(later, earlier)
        self.assertEqual(result_back["sections"]["dominant_rejection_reason"]["change"],
                          CHANGE_BECAME_EMPTY)


# ----------------------------------------------------------------------
# compound sections (comparison_changes / trend / validation_statuses)
# ----------------------------------------------------------------------
class TestCompoundSections(Prompt518TestCase):

    def test_validation_statuses_equality_only(self):
        snap = _filtered_snapshot(["validation_statuses"])
        snap2 = copy.deepcopy(snap)
        snap2["sequence"] = 2
        result = compare(snap, snap2)
        self.assertEqual(result["sections"]["validation_statuses"]["change"], CHANGE_UNCHANGED)
        self.assertFalse(result["sections"]["validation_statuses"]["changed"])

    def test_trend_changed_when_values_differ(self):
        earlier = _filtered_snapshot(["trend"], [{"accepted": 1}, {"accepted": 2}])
        later = _filtered_snapshot(["trend"], [{"accepted": 1}, {"accepted": 9}])
        result = compare(earlier, later)
        entry = result["sections"]["trend"]
        if entry["earlier"] != entry["later"]:
            self.assertEqual(entry["change"], CHANGE_CHANGED)
            self.assertTrue(entry["changed"])
        else:
            self.assertEqual(entry["change"], CHANGE_UNCHANGED)


# ----------------------------------------------------------------------
# 19/20/21. isolation / non-mutation
# ----------------------------------------------------------------------
class TestIsolation(Prompt518TestCase):

    def test_earlier_snapshot_not_mutated(self):
        earlier = _filtered_snapshot(_ALL_SECTIONS, [{"accepted": 1}])
        later = _filtered_snapshot(_ALL_SECTIONS, [{"accepted": 5}])
        before = copy.deepcopy(earlier)
        compare(earlier, later)
        self.assertEqual(earlier, before)

    def test_later_snapshot_not_mutated(self):
        earlier = _filtered_snapshot(_ALL_SECTIONS, [{"accepted": 1}])
        later = _filtered_snapshot(_ALL_SECTIONS, [{"accepted": 5}])
        before = copy.deepcopy(later)
        compare(earlier, later)
        self.assertEqual(later, before)

    def test_comparison_result_is_isolated_from_sources(self):
        earlier = _filtered_snapshot(_ALL_SECTIONS, [{"accepted": 1}])
        later = _filtered_snapshot(_ALL_SECTIONS, [{"accepted": 5}])
        result = compare(earlier, later)
        result["numeric"]["total_evaluations"]["delta"] = "tampered"
        result["sections"]["rates"]["fields"]["acceptance_rate"]["earlier"] = "tampered"
        result2 = compare(earlier, later)
        self.assertNotEqual(result2["numeric"]["total_evaluations"]["delta"], "tampered")
        self.assertNotEqual(
            result2["sections"]["rates"]["fields"]["acceptance_rate"]["earlier"], "tampered")

    def test_mutating_earlier_after_comparison_does_not_change_result(self):
        earlier = _filtered_snapshot(["evaluation_counts"], [{"accepted": 2}])
        later = _filtered_snapshot(["evaluation_counts"], [{"accepted": 6}])
        result = compare(earlier, later)
        earlier["metrics"]["evaluation_counts"]["total_evaluations"] = 999999
        self.assertNotEqual(result["numeric"]["total_evaluations"]["earlier"], 999999)


# ----------------------------------------------------------------------
# 22/23. regression - Prompt 509/517 behavior unchanged
# ----------------------------------------------------------------------
class TestRegression(Prompt518TestCase):

    def test_prompt_509_comparison_still_importable_and_working(self):
        history = _history([{"accepted": 1}, {"accepted": 3}])
        result = history.compare_sequences(1, 2)
        self.assertTrue(result["valid"])
        self.assertEqual(result["direction"], COMPARISON_DIRECTION)

    def test_prompt_517_recording_still_works_unchanged(self):
        filtered = filt(_summary(), ["rates"])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertEqual(snapshot["included_sections"], ["rates"])
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_VALID)


if __name__ == "__main__":
    unittest.main()
