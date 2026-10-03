"""
Tests for Prompt 530 - Validate Snapshot Validation Consistency.

The Unified Diagnostic Report validator
(`validate_learned_knowledge_diagnostic_report()`) already judged the
report's LATEST snapshot with the existing snapshot structure check.
Prompt 530 holds every snapshot of a given source to that same check, so
that a snapshot's validation state (`"valid"` / `"invalid"`) can never
contradict its data, and does the same for Prompt 517 filtered summary
snapshots (new optional `filtered_snapshots` argument):

  * `snapshot_inconsistent:<index>:<snapshot code>`
  * `filtered_snapshot_inconsistent:<index>:<filtered snapshot code>`
  * `filtered_comparison_source_inconsistent:<index>:<519 code>`
  * `claims_valid_but_source_invalid:filtered_comparison_sources`
  * `invalid_source:filtered_snapshots`

Valid, invalid, unavailable and missing states are preserved: an honestly
recorded invalid snapshot, absent / empty sources and zero-evaluation
snapshots are judged exactly as before. Nothing is repaired or mutated.

Run directly:
    python -m unittest tests.test_learned_knowledge_snapshot_validation_consistency -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    LearnedKnowledgeFilteredSummarySnapshotHistory,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
)
from tests.test_learned_knowledge_report_trend_comparison_consistency import (
    OK, _consecutive, _filtered_consecutive, _filtered_snapshots, _history, _stats,
)

SNAP = "snapshot_inconsistent:"
FSNAP = "filtered_snapshot_inconsistent:"
FSRC = "filtered_comparison_source_inconsistent:"
FCLAIM = "claims_valid_but_source_invalid:filtered_comparison_sources"


def _snapshots(steps=(1, 2, 4, 8)):
    return _history(steps).get_all()


def _new_errors(result):
    return [code for code in result["errors"]
            if code.startswith((SNAP, FSNAP, FSRC)) or code in (FCLAIM, "invalid_source:filtered_snapshots")]


class Prompt530TestCase(unittest.TestCase):
    def check(self, snapshots, **sources):
        """The result of validating a report built from `snapshots`
        against those very snapshots (so that only the snapshot state
        checks can object)."""
        return validate(report(snapshots=snapshots), snapshots=snapshots, **sources)


class ValidSnapshotTests(Prompt530TestCase):
    def test_valid_snapshots_are_valid(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(validate(built, snapshots=history, comparisons=comparisons), OK)
        self.assertEqual(validate(built), OK)

    def test_valid_snapshots_given_as_a_list(self):
        self.assertEqual(self.check(_snapshots()), OK)

    def test_valid_snapshot_carries_the_required_structure(self):
        for snapshot in _snapshots():
            self.assertEqual(snapshot["validation_status"], "valid")
            self.assertEqual(snapshot["validation_errors"], [])
            for field in ("snapshot_id", "sequence", "total_evaluations", "accepted_count",
                          "rejected_count", "no_candidate_count", "acceptance_rate",
                          "rejection_rate", "dominant_rejection_reason"):
                self.assertIn(field, snapshot)

    def test_deterministic_and_read_only(self):
        snapshots = _snapshots()
        snapshots[1]["acceptance_rate"] = 0.5
        built = report(snapshots=snapshots)
        before = (copy.deepcopy(built), copy.deepcopy(snapshots))
        first = validate(built, snapshots=snapshots)
        second = validate(built, snapshots=snapshots)
        self.assertEqual(first, second)
        self.assertFalse(first["valid"])
        self.assertEqual((built, snapshots), before)


class MalformedSnapshotTests(Prompt530TestCase):
    def test_earlier_snapshot_missing_a_field(self):
        snapshots = _snapshots()
        del snapshots[0]["sequence"]
        result = self.check(snapshots)
        self.assertFalse(result["valid"])
        self.assertIn(SNAP + "0:missing_field:sequence", result["errors"])

    def test_snapshot_that_is_not_a_dict(self):
        snapshots = _snapshots()
        snapshots[1] = "not a snapshot"
        result = self.check(snapshots)
        self.assertIn(SNAP + "1:snapshot_not_a_dict", result["errors"])

    def test_missing_snapshot_entry(self):
        snapshots = [None] + _snapshots()
        result = self.check(snapshots)
        self.assertIn(SNAP + "0:snapshot_missing", result["errors"])

    def test_malformed_identity_and_status(self):
        snapshots = _snapshots()
        snapshots[0]["snapshot_id"] = " "
        snapshots[1]["validation_status"] = "maybe"
        errors = self.check(snapshots)["errors"]
        self.assertIn(SNAP + "0:invalid_snapshot_id", errors)
        self.assertIn(SNAP + "1:invalid_validation_status", errors)

    def test_latest_snapshot_is_reported_once_by_the_existing_check(self):
        snapshots = _snapshots()
        del snapshots[-1]["accepted_count"]
        errors = self.check(snapshots)["errors"]
        self.assertIn("snapshots.latest:missing_field:accepted_count", errors)
        self.assertEqual([code for code in errors if code.startswith(SNAP)], [])


class InvalidSnapshotMarkedValidTests(Prompt530TestCase):
    def test_contradictory_analysis_data_marked_valid(self):
        snapshots = _snapshots()
        snapshots[1]["acceptance_rate"] = 0.123
        result = self.check(snapshots)
        self.assertFalse(result["valid"])
        self.assertIn(SNAP + "1:analysis:inconsistent_acceptance_rate", result["errors"])

    def test_counts_that_do_not_add_up_marked_valid(self):
        snapshots = _snapshots()
        snapshots[0]["total_evaluations"] += 5
        errors = self.check(snapshots)["errors"]
        self.assertTrue(any(code.startswith(SNAP + "0:analysis:") for code in errors), errors)

    def test_valid_snapshot_carrying_validation_errors(self):
        snapshots = _snapshots()
        snapshots[2]["validation_errors"] = ["boom"]
        self.assertIn(SNAP + "2:valid_snapshot_has_validation_errors",
                      self.check(snapshots)["errors"])

    def test_snapshot_without_analysis_values_marked_valid(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record({}, {"valid": True, "errors": []})
        history.record_statistics(_stats(2))
        errors = self.check(history.get_all())["errors"]
        self.assertIn(SNAP + "0:analysis:invalid_count_type:total_evaluations", errors)

    def test_report_claiming_valid_for_an_invalid_source_latest(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_stats(1))
        history.record({}, {"valid": False, "errors": ["boom"]})
        honest = report(snapshots=history)
        forged = copy.deepcopy(honest)
        forged["snapshots"]["latest"] = _snapshots()[0]
        forged["snapshots"]["latest"]["snapshot_id"] = honest["snapshots"]["latest"]["snapshot_id"]
        forged["snapshots"]["latest"]["sequence"] = 2
        result = validate(forged, snapshots=history)
        self.assertIn("claims_valid_but_source_invalid:snapshot", result["errors"])


class ValidSnapshotMarkedInvalidTests(Prompt530TestCase):
    def test_valid_data_with_an_invalid_status(self):
        snapshots = _snapshots()
        snapshots[0]["validation_status"] = "invalid"
        errors = self.check(snapshots)["errors"]
        self.assertIn(SNAP + "0:invalid_snapshot_has_analysis_field:total_evaluations", errors)
        self.assertIn(SNAP + "0:invalid_snapshot_has_analysis_field:acceptance_rate", errors)

    def test_latest_snapshot_valid_data_with_an_invalid_status(self):
        snapshots = _snapshots()
        snapshots[-1]["validation_status"] = "invalid"
        errors = self.check(snapshots)["errors"]
        self.assertIn("snapshots.latest:invalid_snapshot_has_analysis_field:total_evaluations", errors)

    def test_honestly_invalid_snapshot_is_preserved(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_stats(1))
        history.record({}, {"valid": False, "errors": ["boom"]})
        history.record_statistics(_stats(3))
        snapshots = history.get_all()
        self.assertEqual(snapshots[1]["validation_status"], "invalid")
        result = self.check(snapshots)
        self.assertEqual(_new_errors(result), [])
        self.assertEqual(result, validate(report(snapshots=snapshots)))


class UnavailableSnapshotTests(Prompt530TestCase):
    def test_no_snapshots_is_an_unavailable_state_not_an_error(self):
        built = report()
        self.assertFalse(built["snapshots"]["available"])
        for source in (None, [], LearnedKnowledgeDiagnosticSnapshotHistory()):
            self.assertEqual(validate(built, snapshots=source), OK)
        self.assertEqual(validate(built), OK)

    def test_unavailable_snapshots_with_fabricated_latest(self):
        built = report()
        built["snapshots"]["latest"] = _snapshots()[0]
        self.assertIn("fabricated_value_for_unavailable_component:snapshots.latest",
                      validate(built)["errors"])

    def test_single_snapshot_history_only_has_the_latest(self):
        snapshots = _snapshots((3,))
        self.assertEqual(self.check(snapshots), OK)

    def test_wrong_source_type_is_left_to_the_existing_check(self):
        result = validate(report(snapshots=_history()), snapshots="nope")
        self.assertIn("invalid_source:snapshots", result["errors"])
        self.assertEqual([c for c in result["errors"] if c.startswith(SNAP)], [])

    def test_source_history_object_is_not_modified(self):
        history = _history()
        before = history.get_all()
        validate(report(snapshots=history), snapshots=history)
        self.assertEqual(history.get_all(), before)


class FilteredSnapshotTests(Prompt530TestCase):
    def _pipeline(self):
        history = _history()
        comparisons = _consecutive(history)
        filtered = _filtered_snapshots()
        filtered_comparisons = _filtered_consecutive(filtered)
        built = report(snapshots=history, comparisons=comparisons,
                       filtered_comparisons=filtered_comparisons)
        return history, comparisons, filtered, filtered_comparisons, built

    def test_valid_filtered_snapshots(self):
        history, comparisons, filtered, filtered_comparisons, built = self._pipeline()
        self.assertEqual(validate(
            built, snapshots=history, comparisons=comparisons,
            filtered_comparisons=filtered_comparisons, filtered_snapshots=filtered), OK)

    def test_filtered_snapshots_given_as_a_history(self):
        _, _, _, _, built = self._pipeline()
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        for snapshot in _filtered_snapshots():
            history.record_filtered_summary(
                {"valid": False, "errors": []} if False else _filtered_summary_of(snapshot))
        self.assertEqual(validate(built, filtered_snapshots=history), OK)

    def test_filtered_valid_snapshot_marked_invalid(self):
        _, _, filtered, _, built = self._pipeline()
        broken = copy.deepcopy(filtered)
        broken[1]["validation_status"] = "invalid"
        result = validate(built, filtered_snapshots=broken)
        self.assertFalse(result["valid"])
        self.assertIn(FSNAP + "1:invalid_snapshot_has_included_sections", result["errors"])

    def test_filtered_invalid_snapshot_marked_valid(self):
        _, _, filtered, _, built = self._pipeline()
        broken = copy.deepcopy(filtered)
        broken[0]["validation_errors"] = ["filtered_summary_not_a_dict"]
        self.assertIn(FSNAP + "0:valid_snapshot_has_validation_errors",
                      validate(built, filtered_snapshots=broken)["errors"])

    def test_malformed_filtered_snapshot(self):
        _, _, filtered, _, built = self._pipeline()
        broken = copy.deepcopy(filtered)
        del broken[2]["metrics"]
        broken[3] = None
        errors = validate(built, filtered_snapshots=broken)["errors"]
        self.assertIn(FSNAP + "2:missing_field:metrics", errors)
        self.assertIn(FSNAP + "3:snapshot_missing", errors)

    def test_valid_filtered_comparison_contradicting_its_snapshots(self):
        history, comparisons, filtered, filtered_comparisons, built = self._pipeline()
        broken = copy.deepcopy(filtered)
        broken[1]["included_sections"] = broken[1]["included_sections"][:-1]
        result = validate(built, filtered_comparisons=filtered_comparisons,
                          filtered_snapshots=broken)
        self.assertFalse(result["valid"])
        self.assertTrue(any(code.startswith(FSRC + "0:") for code in result["errors"]), result)
        self.assertIn(FCLAIM, result["errors"])

    def test_honestly_invalid_filtered_snapshot_is_preserved(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        history.record_filtered_summary(None)
        snapshots = history.get_all()
        self.assertEqual(snapshots[0]["validation_status"], "invalid")
        self.assertEqual(validate(report(), filtered_snapshots=snapshots), OK)

    def test_unavailable_or_wrong_filtered_source(self):
        _, _, _, _, built = self._pipeline()
        for source in (None, [], (), LearnedKnowledgeFilteredSummarySnapshotHistory()):
            self.assertEqual(validate(built, filtered_snapshots=source), OK)
        self.assertEqual(validate(built, filtered_snapshots=5)["errors"],
                         ["invalid_source:filtered_snapshots"])

    def test_filtered_comparison_missing_its_snapshots_is_not_judged(self):
        _, _, filtered, filtered_comparisons, built = self._pipeline()
        unrelated = copy.deepcopy(filtered)
        for snapshot in unrelated:
            snapshot["snapshot_id"] = "unrelated-%d" % snapshot["sequence"]
        result = validate(built, filtered_comparisons=filtered_comparisons,
                          filtered_snapshots=unrelated)
        self.assertEqual([c for c in result["errors"] if c.startswith(FSRC)], [])

    def test_existing_calls_without_filtered_snapshots_are_unchanged(self):
        history, comparisons, _, filtered_comparisons, built = self._pipeline()
        self.assertEqual(validate(built, snapshots=history, comparisons=comparisons,
                                  filtered_comparisons=filtered_comparisons), OK)


def _filtered_summary_of(snapshot):
    """A Prompt 516 summary from which a snapshot equal to `snapshot`
    (apart from its id) is recorded - only used to fill a history."""
    from tests.test_learned_knowledge_report_trend_comparison_consistency import (
        _SUMMARY_ALL, _filtered_summary, filt)
    return filt(_filtered_summary(snapshot["metrics"]["evaluation_counts"]["total_evaluations"]),
                _SUMMARY_ALL)


class EmptyAndZeroEvaluationTests(Prompt530TestCase):
    def test_zero_evaluation_snapshots_are_valid(self):
        snapshots = _snapshots((0, 0, 0))
        for snapshot in snapshots:
            self.assertEqual(snapshot["total_evaluations"], 0)
            self.assertEqual(snapshot["acceptance_rate"], 0.0)
        self.assertEqual(self.check(snapshots), OK)

    def test_empty_statistics_snapshot(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(LearnedKnowledgeDecisionStatistics())
        history.record_statistics(LearnedKnowledgeDecisionStatistics())
        self.assertEqual(self.check(history.get_all()), OK)

    def test_zero_evaluation_snapshot_with_a_nonzero_count_is_reported(self):
        snapshots = _snapshots((0, 0, 0))
        snapshots[0]["accepted_count"] = 3
        errors = self.check(snapshots)["errors"]
        self.assertTrue(any(code.startswith(SNAP + "0:analysis:") for code in errors), errors)

    def test_zero_evaluation_rates_of_none_are_not_invented(self):
        snapshots = _snapshots((0, 0, 0))
        snapshots[0]["acceptance_rate"] = 1.0
        errors = self.check(snapshots)["errors"]
        self.assertTrue(any(code.startswith(SNAP + "0:analysis:") for code in errors), errors)

    def test_empty_report_and_sources(self):
        built = report()
        self.assertEqual(validate(built, snapshots=[], filtered_snapshots=[]), OK)

    def test_odd_entries_never_raise(self):
        # Odd entries before the latest snapshot. (A source whose LAST
        # entry is not a dict is not handled by the existing report
        # builder and is outside this change.)
        built = report(snapshots=_history())
        last = _snapshots()[-1]
        for odd in ([None], [{}], ["x", 1], [{"validation_status": "valid"}], [[], {}]):
            result = validate(built, snapshots=odd + [last], filtered_snapshots=odd)
            self.assertIsInstance(result["errors"], list)
            self.assertFalse(result["valid"])


if __name__ == "__main__":
    unittest.main()
