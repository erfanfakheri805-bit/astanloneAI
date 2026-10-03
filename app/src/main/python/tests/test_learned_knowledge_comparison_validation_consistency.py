"""
Tests for Prompt 529 - Validate Comparison Validation Consistency.

The Unified Diagnostic Report validator
(`validate_learned_knowledge_diagnostic_report()`) already re-ran the
Prompt 510 comparison validator on the report's latest comparison. Prompt
529 additionally holds every given comparison that says it is valid to
the source snapshots it names, by reusing the Prompt 510 validator's own
source cross-check:

  * `comparison_source_inconsistent:<index>:<510 source code>`
  * `claims_valid_but_source_invalid:comparison_sources`
        (the report's embedded comparison validation calls the latest
        comparison valid although its sources contradict it)

Valid, invalid, unavailable and missing states are preserved: a comparison
that honestly reports an invalid source snapshot, an unavailable
comparison, and a comparison whose snapshots are not among the given
sources are all judged exactly as before. Nothing is repaired or mutated.

Run directly:
    python -m unittest tests.test_learned_knowledge_comparison_validation_consistency -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDiagnosticSnapshotHistory,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate_comparison,
    validate_learned_knowledge_filtered_summary_snapshot_comparison as validate_filtered_comparison,
)
from tests.test_learned_knowledge_report_trend_comparison_consistency import (
    OK, _consecutive, _filtered_consecutive, _filtered_snapshots, _history, _stats,
)

SOURCE_CODE = "comparison_source_inconsistent:"
CLAIM_CODE = "claims_valid_but_source_invalid:comparison_sources"


def _history_with_invalid_snapshot():
    """Snapshots 1 (valid), 2 (own validation_status 'invalid'), 3 (valid)."""
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record_statistics(_stats(1))
    history.record({}, {"valid": False, "errors": ["boom"]})
    history.record_statistics(_stats(3))
    return history


def _with_earlier_changed(comparison, new_earlier):
    """A copy whose total_evaluations `earlier` value (and, so it stays
    internally consistent, its delta) differs from the real snapshot."""
    forged = copy.deepcopy(comparison)
    entry = forged["numeric"]["total_evaluations"]
    entry["earlier"] = new_earlier
    entry["delta"] = entry["later"] - new_earlier
    entry["changed"] = entry["delta"] != 0
    return forged


class Prompt529TestCase(unittest.TestCase):
    def source_errors(self, result):
        return [code for code in result["errors"] if code.startswith(SOURCE_CODE)]


class ValidComparisonTests(Prompt529TestCase):
    def test_valid_comparison_with_valid_validation(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(validate(built), OK)
        self.assertEqual(validate(built, snapshots=history, comparisons=comparisons), OK)
        self.assertEqual(validate_comparison(comparisons[-1]), OK)
        self.assertEqual(built["comparison_validation"]["result"], OK)

    def test_snapshots_given_as_list(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(
            validate(built, snapshots=history.get_all(), comparisons=comparisons), OK)

    def test_deterministic_and_read_only(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        before = (copy.deepcopy(built), copy.deepcopy(comparisons), history.get_all())
        first = validate(built, snapshots=history, comparisons=comparisons)
        second = validate(built, snapshots=history, comparisons=comparisons)
        self.assertEqual(first, second)
        self.assertEqual((built, comparisons, history.get_all()), before)


class InvalidSourceSnapshotTests(Prompt529TestCase):
    def test_honest_comparison_of_invalid_snapshot_is_preserved(self):
        history = _history_with_invalid_snapshot()
        comparisons = [history.compare_sequences(1, 2), history.compare_sequences(2, 3)]
        self.assertFalse(validate_comparison(comparisons[0])["valid"])
        built = report(snapshots=history, comparisons=comparisons)
        result = validate(built, snapshots=history, comparisons=comparisons)
        self.assertEqual(self.source_errors(result), [])
        self.assertEqual(result, validate(built))

    def test_invalid_source_snapshot_cannot_yield_valid_comparison(self):
        history = _history_with_invalid_snapshot()
        valid_pair = _history().compare_sequences(1, 2)
        forged = copy.deepcopy(valid_pair)
        forged["later"] = {"snapshot_id": history.get_all()[1]["snapshot_id"], "sequence": 2}
        # judged alone the forged comparison looks valid ...
        self.assertEqual(validate_comparison(forged), OK)
        # ... but its source snapshot is invalid.
        built = report(snapshots=history, comparisons=[forged])
        result = validate(built, snapshots=history, comparisons=[forged])
        self.assertFalse(result["valid"])
        self.assertIn(SOURCE_CODE + "0:source_mismatch:later:validation_status", result["errors"])
        self.assertIn(CLAIM_CODE, result["errors"])

    def test_snapshot_marked_invalid_in_source_but_valid_in_comparison(self):
        history = _history()
        comparisons = _consecutive(history)
        sources = history.get_all()
        sources[-1] = copy.deepcopy(sources[-1])
        sources[-1]["validation_status"] = "invalid"
        built = report(snapshots=history, comparisons=comparisons)
        result = validate(built, snapshots=sources, comparisons=comparisons)
        self.assertFalse(result["valid"])
        self.assertIn(SOURCE_CODE + "2:comparison_valid_but_source_invalid:later", result["errors"])
        self.assertIn(CLAIM_CODE, result["errors"])

    def test_malformed_source_snapshot_with_valid_comparison(self):
        history = _history()
        comparisons = _consecutive(history)
        sources = history.get_all()
        sources[0] = {"snapshot_id": sources[0]["snapshot_id"], "sequence": 1}
        result = validate(report(snapshots=history, comparisons=comparisons),
                          snapshots=sources, comparisons=comparisons)
        self.assertIn(SOURCE_CODE + "0:comparison_valid_but_source_invalid:earlier",
                      result["errors"])


class InvalidComparisonMarkedValidTests(Prompt529TestCase):
    def test_data_contradicting_sources_is_reported(self):
        history = _history()
        comparisons = _consecutive(history)
        forged = _with_earlier_changed(comparisons[-1], comparisons[-1]["numeric"]["total_evaluations"]["earlier"] + 5)
        listed = comparisons[:-1] + [forged]
        built = report(snapshots=history, comparisons=listed)
        result = validate(built, snapshots=history, comparisons=listed)
        self.assertFalse(result["valid"])
        self.assertTrue(self.source_errors(result), result)

    def test_earlier_comparison_in_the_list_is_also_held_to_its_sources(self):
        history = _history()
        comparisons = _consecutive(history)
        forged = copy.deepcopy(comparisons[0])
        forged["numeric"]["accepted_count"]["later"] += 1
        forged["numeric"]["accepted_count"]["delta"] += 1
        listed = [forged] + comparisons[1:]
        built = report(snapshots=history, comparisons=listed)
        result = validate(built, snapshots=history, comparisons=listed)
        self.assertIn(SOURCE_CODE + "0:source_mismatch:later:accepted_count", result["errors"])

    def test_embedded_result_calling_a_contradicted_comparison_valid(self):
        history = _history()
        comparisons = _consecutive(history)
        # Internally consistent (so valid on its own) but it describes the
        # 1 -> 2 change under the identities of snapshots 3 and 4.
        forged = copy.deepcopy(comparisons[0])
        forged["earlier"] = {"snapshot_id": history.get_all()[2]["snapshot_id"], "sequence": 3}
        forged["later"] = {"snapshot_id": history.get_all()[3]["snapshot_id"], "sequence": 4}
        self.assertEqual(validate_comparison(forged), OK)
        listed = comparisons[:-1] + [forged]
        built = report(snapshots=history, comparisons=listed)
        self.assertTrue(built["comparison_validation"]["result"]["valid"])
        result = validate(built, snapshots=history, comparisons=listed)
        self.assertIn(CLAIM_CODE, result["errors"])
        self.assertTrue(self.source_errors(result))

    def test_tampered_delta_marked_valid_is_reported_without_sources(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        tampered = copy.deepcopy(built)
        tampered["comparison"]["latest"]["numeric"]["total_evaluations"]["delta"] += 99
        result = validate(tampered)
        self.assertIn("claims_valid_but_source_invalid:comparison", result["errors"])


class ValidComparisonMarkedInvalidTests(Prompt529TestCase):
    def test_valid_comparison_with_invalid_validation_result(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        tampered = copy.deepcopy(built)
        tampered["comparison_validation"]["result"] = {
            "valid": False, "well_formed": True, "errors": ["made_up"], "warnings": []}
        for kwargs in ({}, {"snapshots": history, "comparisons": comparisons}):
            result = validate(tampered, **kwargs)
            self.assertFalse(result["valid"])
            self.assertIn("claims_invalid_but_source_valid:comparison", result["errors"])
        self.assertNotIn(CLAIM_CODE, validate(
            tampered, snapshots=history, comparisons=comparisons)["errors"])


class UnavailableComparisonTests(Prompt529TestCase):
    def test_unavailable_comparison_is_preserved(self):
        history = _history()
        built = report(snapshots=history)
        self.assertFalse(built["comparison"]["available"])
        self.assertFalse(built["comparison_validation"]["available"])
        self.assertEqual(validate(built), OK)
        self.assertEqual(validate(built, snapshots=history, comparisons=[]), OK)

    def test_unavailable_comparison_with_fabricated_validation(self):
        built = report(snapshots=_history())
        built["comparison_validation"]["result"] = copy.deepcopy(OK)
        result = validate(built)
        self.assertIn(
            "fabricated_value_for_unavailable_component:comparison_validation.result",
            result["errors"])

    def test_comparison_missing_its_snapshots_is_not_judged_against_them(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        other = _history((3, 6))
        other_sources = [copy.deepcopy(item) for item in other.get_all()]
        for item in other_sources:
            item["snapshot_id"] = "unrelated-%d" % item["sequence"]
        result = validate(built, snapshots=other_sources, comparisons=comparisons)
        self.assertEqual(self.source_errors(result), [])

    def test_invalid_comparison_from_missing_snapshot_is_preserved(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_stats(1))
        comparisons = [history.compare_latest()]
        self.assertFalse(comparisons[0]["valid"])
        built = report(snapshots=history, comparisons=comparisons)
        result = validate(built, snapshots=history, comparisons=comparisons)
        self.assertEqual(self.source_errors(result), [])
        self.assertEqual(result, validate(built))


class FilteredComparisonTests(Prompt529TestCase):
    def _pipeline(self):
        history = _history()
        comparisons = _consecutive(history)
        filtered = _filtered_consecutive(_filtered_snapshots())
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        return history, comparisons, filtered, built

    def test_valid_filtered_comparisons_with_valid_report(self):
        history, comparisons, filtered, built = self._pipeline()
        self.assertTrue(all(validate_filtered_comparison(item)["valid"] for item in filtered))
        self.assertEqual(validate(built, snapshots=history, comparisons=comparisons,
                                  filtered_comparisons=filtered), OK)

    def test_filtered_comparison_with_invalid_source_status_is_not_valid(self):
        history, comparisons, filtered, built = self._pipeline()
        forged = copy.deepcopy(filtered[-1])
        forged["later_validation_status"] = "invalid"
        self.assertFalse(validate_filtered_comparison(forged)["valid"])
        listed = filtered[:-1] + [forged]
        result = validate(built, snapshots=history, comparisons=comparisons,
                          filtered_comparisons=listed)
        self.assertFalse(result["valid"])
        self.assertTrue(any("filtered_trend" in code for code in result["errors"]), result)

    def test_filtered_data_contradicting_its_trend_is_reported(self):
        history, comparisons, filtered, built = self._pipeline()
        forged = copy.deepcopy(filtered[-1])
        forged["numeric"]["total_evaluations"]["delta"] += 7
        self.assertFalse(validate_filtered_comparison(forged)["valid"])
        listed = filtered[:-1] + [forged]
        result = validate(built, snapshots=history, comparisons=comparisons,
                          filtered_comparisons=listed)
        self.assertFalse(result["valid"])

    def test_report_without_filtered_data_is_unchanged(self):
        history = _history()
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assertEqual(validate(built, snapshots=history, comparisons=comparisons), OK)


class EmptyAndZeroDataTests(Prompt529TestCase):
    def test_zero_evaluation_comparisons_are_valid(self):
        history = _history(steps=(0, 0, 0))
        comparisons = _consecutive(history)
        built = report(snapshots=history, comparisons=comparisons)
        self.assertTrue(all(validate_comparison(item)["valid"] for item in comparisons))
        self.assertEqual(validate(built, snapshots=history, comparisons=comparisons), OK)

    def test_zero_data_contradicting_sources_is_reported(self):
        history = _history(steps=(0, 0, 0))
        comparisons = _consecutive(history)
        forged = copy.deepcopy(comparisons[-1])
        forged["numeric"]["total_evaluations"].update({"later": 4, "delta": 4, "changed": True})
        listed = comparisons[:-1] + [forged]
        built = report(snapshots=history, comparisons=listed)
        result = validate(built, snapshots=history, comparisons=listed)
        self.assertIn(SOURCE_CODE + "1:source_mismatch:later:total_evaluations", result["errors"])

    def test_empty_sources_and_empty_report(self):
        built = report()
        self.assertEqual(validate(built), OK)
        self.assertEqual(validate(built, snapshots=None, comparisons=None), OK)
        self.assertEqual(validate(built, snapshots=[], comparisons=[]), OK)

    def test_non_dict_and_odd_comparisons_never_raise(self):
        history = _history()
        built = report(snapshots=history, comparisons=_consecutive(history))
        for odd in ([None], [{}], ["x"], [{"valid": True}]):
            result = validate(built, snapshots=history, comparisons=odd)
            self.assertIsInstance(result["errors"], list)
            self.assertEqual(self.source_errors(result), [])


if __name__ == "__main__":
    unittest.main()
