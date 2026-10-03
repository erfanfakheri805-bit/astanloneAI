"""
Tests for Prompt 519 - Validate Filtered Diagnostic Snapshot Comparisons.

`validate_learned_knowledge_filtered_summary_snapshot_comparison()`
(learning/learned_knowledge_statistics.py) validates the dict
`compare_learned_knowledge_filtered_summary_snapshots()` (Prompt 518)
returns: structure, source snapshots, section classification, numeric
deltas, categorical states, chronological ordering, and consistency with
the source snapshots. It is deterministic and read-only: it repairs,
reorders, and mutates nothing, and nothing reads its result to change
behavior.

Covers (numbers match the Prompt 519 test list):
    1.  fully valid filtered snapshot comparison
    2.  missing required field
    3.  invalid earlier snapshot
    4.  invalid later snapshot
    5.  invalid source snapshot reference
    6.  shared section classification
    7.  earlier-only section
    8.  later-only section
    9.  unavailable section
    10. contradictory section classification
    11. valid numeric delta
    12. incorrect numeric delta
    13. non-finite numeric value
    14. zero evaluations
    15. identical snapshots
    16. changed categorical state
    17. unchanged categorical state
    18. appeared state
    19. disappeared state
    20. insufficient-data state
    21. unsupported categorical state
    22. reversed chronological ordering
    23. missing ordering metadata
    24. contradictory ordering metadata
    25. inconsistent source/comparison values
    26. empty comparison
    27. different selected-section sets
    28. deterministic repeated validation
    29. validation does not mutate source snapshots
    30. validation does not mutate the comparison result
    plus: Prompt 510 validator and Prompt 518 comparison unchanged.

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_summary_snapshot_comparison_validation -v
"""

import copy
import math
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
    REPORT_VALIDITY_INVALID,
    FILTERED_COMPARISON_PRESENT_BOTH, FILTERED_COMPARISON_PRESENT_ONLY_EARLIER,
    FILTERED_COMPARISON_PRESENT_ONLY_LATER, FILTERED_COMPARISON_UNAVAILABLE_BOTH,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
    validate_learned_knowledge_filtered_summary_snapshot_comparison as check,
    validate_learned_knowledge_diagnostic_snapshot_comparison as check509,
)

_ALL = [
    "evaluation_counts", "rates", "dominant_rejection_reason",
    "comparison_changes", "trend", "validation_statuses",
]
_SMALL = ["evaluation_counts", "rates", "dominant_rejection_reason"]


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


def _summary(counts_list=None):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for counts in (counts_list or [{"accepted": 1}, {"accepted": 3}, {"irrelevant": 2}]):
        history.record_statistics(_stats(**counts))
    comparisons = [history.compare_sequences(i, i + 1) for i in range(1, len(history))]
    built = report(snapshots=history, comparisons=comparisons)
    validation = validate(built, snapshots=history, comparisons=comparisons)
    return fmt(built, validation)


def _invalid_summary():
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record_statistics(_stats(accepted=1))
    broken = copy.deepcopy(report(snapshots=history))
    broken["structural_status"] = "unknown"
    validation = validate(broken)
    assert not validation["valid"]
    return fmt(broken, validation)


def _pair(early_sections, early_counts, late_sections, late_counts):
    """Two real Prompt 517 snapshots from ONE history (sequences 1, 2)."""
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    earlier = history.record_filtered_summary(filt(_summary(early_counts), early_sections))
    later = history.record_filtered_summary(filt(_summary(late_counts), late_sections))
    return earlier, later


_EARLY = [{"accepted": 1}, {"accepted": 3}, {"irrelevant": 2}]
_LATE = [{"accepted": 2}, {"accepted": 3}, {"irrelevant": 2}, {"accepted": 1}]


def _standard():
    """(earlier, later, comparison) - every section shared."""
    earlier, later = _pair(_ALL, _EARLY, _ALL, _LATE)
    return earlier, later, compare(earlier, later)


class Prompt519TestCase(unittest.TestCase):
    def assertValid(self, result):
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["well_formed"], result["errors"])
        self.assertEqual(result["errors"], [])

    def assertHasError(self, result, code, kind=None):
        self.assertIn(code, result["errors"], result["errors"])
        self.assertFalse(result["valid"])
        if kind:
            self.assertIn(code, result[kind])

    def assertPrefixError(self, result, prefix, kind=None):
        matching = [e for e in result["errors"] if e.startswith(prefix)]
        self.assertTrue(matching, (prefix, result["errors"]))
        self.assertFalse(result["valid"])
        if kind:
            self.assertTrue(any(e.startswith(prefix) for e in result[kind]))


class ValidComparisonTests(Prompt519TestCase):
    def test_01_fully_valid_comparison(self):
        earlier, later, comparison = _standard()
        self.assertTrue(comparison["valid"])
        result = check(comparison)
        self.assertValid(result)
        self.assertEqual(result["warnings"], [])
        for key in ("structural_errors", "section_errors", "numeric_errors",
                    "categorical_errors", "ordering_errors", "source_snapshot_errors"):
            self.assertEqual(result[key], [])
        self.assertValid(check(comparison, earlier, later))

    def test_06_shared_section_classification(self):
        earlier, later, comparison = _standard()
        for section in _ALL:
            self.assertEqual(comparison["sections"][section]["presence"], FILTERED_COMPARISON_PRESENT_BOTH)
        self.assertValid(check(comparison, earlier, later))

    def test_07_earlier_only_section(self):
        earlier, later = _pair(_ALL, _EARLY, _SMALL, _LATE)
        comparison = compare(earlier, later)
        self.assertEqual(comparison["sections"]["trend"]["presence"], FILTERED_COMPARISON_PRESENT_ONLY_EARLIER)
        result = check(comparison, earlier, later)
        self.assertValid(result)
        self.assertIn("insufficient_data:trend", result["unavailable"])

    def test_08_later_only_section(self):
        earlier, later = _pair(_SMALL, _EARLY, _ALL, _LATE)
        comparison = compare(earlier, later)
        self.assertEqual(comparison["sections"]["trend"]["presence"], FILTERED_COMPARISON_PRESENT_ONLY_LATER)
        result = check(comparison, earlier, later)
        self.assertValid(result)
        self.assertIn("insufficient_data:trend", result["unavailable"])

    def test_09_unavailable_section(self):
        earlier, later = _pair(_SMALL, _EARLY, _SMALL, _LATE)
        comparison = compare(earlier, later)
        self.assertEqual(comparison["sections"]["trend"]["presence"], FILTERED_COMPARISON_UNAVAILABLE_BOTH)
        result = check(comparison, earlier, later)
        self.assertValid(result)
        self.assertIn("section_unavailable_in_both:trend", result["unavailable"])

    def test_11_valid_numeric_delta(self):
        _, _, comparison = _standard()
        entry = comparison["numeric"]["total_evaluations"]
        self.assertEqual(entry["delta"], entry["later"] - entry["earlier"])
        self.assertValid(check(comparison))

    def test_14_zero_evaluations(self):
        earlier, later = _pair(_SMALL, [{}], _SMALL, [{}])
        comparison = compare(earlier, later)
        self.assertEqual(comparison["numeric"]["total_evaluations"]["earlier"], 0)
        self.assertEqual(comparison["numeric"]["total_evaluations"]["delta"], 0)
        result = check(comparison, earlier, later)
        self.assertValid(result)
        self.assertFalse(comparison["numeric"]["total_evaluations"]["changed"])

    def test_15_identical_snapshots(self):
        earlier, later = _pair(_ALL, _EARLY, _ALL, _EARLY)
        comparison = compare(earlier, later)
        self.assertTrue(comparison["identical"])
        self.assertEqual(comparison["changed_sections"], [])
        self.assertValid(check(comparison, earlier, later))
        # the very same snapshot on both sides is valid too (with a warning)
        same = compare(earlier, earlier)
        result = check(same, earlier, earlier)
        self.assertValid(result)
        self.assertIn("same_snapshot_compared", result["warnings"])

    def test_26_empty_comparison(self):
        for empty in ({}, None, [], "x", 5):
            result = check(empty)
            self.assertFalse(result["valid"])
            self.assertFalse(result["well_formed"])
        self.assertHasError(check({}), "missing_field:valid", "structural_errors")
        self.assertHasError(check(None), "comparison_not_a_dict", "structural_errors")

    def test_26b_no_selected_sections_is_a_legitimate_empty_comparison(self):
        earlier, later = _pair([], _EARLY, [], _LATE)
        comparison = compare(earlier, later)
        self.assertEqual(comparison["common_sections"], [])
        result = check(comparison, earlier, later)
        self.assertValid(result)
        self.assertIn("no_shared_sections", result["unavailable"])
        self.assertIn("no_comparable_numeric_metrics", result["unavailable"])

    def test_27_different_selected_section_sets(self):
        earlier, later = _pair(["evaluation_counts", "trend"], _EARLY,
                               ["rates", "trend", "dominant_rejection_reason"], _LATE)
        comparison = compare(earlier, later)
        result = check(comparison, earlier, later)
        self.assertValid(result)
        self.assertIn("insufficient_data:evaluation_counts", result["unavailable"])
        self.assertIn("insufficient_data:rates", result["unavailable"])
        self.assertEqual(comparison["numeric"], {})


class StructureAndSourceTests(Prompt519TestCase):
    def test_02_missing_required_field(self):
        _, _, comparison = _standard()
        for field in ("errors", "direction", "earlier", "later", "chronological",
                      "earlier_validation_status", "later_validation_status",
                      "common_sections", "identical", "changed_sections", "numeric", "sections"):
            broken = copy.deepcopy(comparison)
            del broken[field]
            result = check(broken)
            self.assertHasError(result, "missing_field:%s" % field, "structural_errors")
            self.assertFalse(result["well_formed"])

    def test_02b_missing_section_entry(self):
        _, _, comparison = _standard()
        del comparison["sections"]["rates"]
        self.assertHasError(check(comparison), "missing_section_entry:rates", "structural_errors")

    def test_03_invalid_earlier_snapshot(self):
        earlier, later, _ = _standard()
        bad = {"snapshot_id": "x"}
        comparison = compare(bad, later)
        self.assertFalse(comparison["valid"])
        result = check(comparison, bad, later)
        self.assertHasError(result, "source_snapshot_invalid:earlier", "source_snapshot_errors")
        self.assertTrue(result["well_formed"])
        self.assertNotIn("source_snapshot_invalid:later", result["errors"])

    def test_04_invalid_later_snapshot(self):
        earlier, _, _ = _standard()
        comparison = compare(earlier, "nonsense")
        result = check(comparison, earlier, "nonsense")
        self.assertHasError(result, "source_snapshot_invalid:later", "source_snapshot_errors")
        self.assertTrue(result["well_formed"])

    def test_04b_snapshot_with_invalid_own_status_never_fully_valid(self):
        good, _ = _pair(_ALL, _EARLY, _ALL, _LATE)
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        invalid = history.record_filtered_summary(filt(_invalid_summary(), _ALL))
        self.assertEqual(invalid["validation_status"], "invalid")
        comparison = compare(good, invalid)
        self.assertTrue(comparison["valid"])
        result = check(comparison, good, invalid)
        self.assertHasError(result, "source_snapshot_validation_status_invalid:later",
                            "source_snapshot_errors")
        self.assertTrue(result["well_formed"])

    def test_05_invalid_source_snapshot_reference(self):
        _, _, comparison = _standard()
        for bad in ({"snapshot_id": "", "sequence": 1}, {"snapshot_id": 7, "sequence": 1},
                    "learned_knowledge_snapshot_000001", None, {"sequence": 1}):
            broken = copy.deepcopy(comparison)
            broken["earlier"] = bad
            result = check(broken)
            self.assertHasError(result, "invalid_source_reference:earlier", "source_snapshot_errors")
            self.assertFalse(result["well_formed"])

    def test_05b_referenced_snapshot_missing(self):
        earlier, later, comparison = _standard()
        result = check(comparison, None, later)
        self.assertHasError(result, "source_snapshot_missing:earlier", "source_snapshot_errors")

    def test_05c_valid_comparison_but_source_invalid(self):
        earlier, later, comparison = _standard()
        result = check(comparison, {"snapshot_id": "x"}, later)
        self.assertHasError(result, "comparison_valid_but_source_invalid:earlier")
        self.assertFalse(result["well_formed"])

    def test_05d_source_identity_mismatch(self):
        earlier, later, comparison = _standard()
        result = check(comparison, later, earlier)
        self.assertHasError(result, "source_mismatch:earlier:identity", "source_snapshot_errors")
        self.assertHasError(result, "source_mismatch:later:identity")

    def test_05e_invalid_branch_source_errors_must_match_sources(self):
        earlier, later, _ = _standard()
        comparison = compare({"snapshot_id": "x"}, later)
        result = check(comparison, earlier, later)
        self.assertHasError(result, "source_errors_mismatch:earlier")

    def test_05f_invalid_branch_internal_inconsistency(self):
        comparison = compare({"snapshot_id": "x"}, {"snapshot_id": "y"})
        comparison["invalid_inputs"] = ["later"]
        result = check(comparison)
        self.assertHasError(result, "inconsistent_invalid_inputs", "structural_errors")
        broken = compare({"snapshot_id": "x"}, {"snapshot_id": "y"})
        del broken["earlier_errors"]
        self.assertHasError(check(broken), "missing_field:earlier_errors")

    def test_direction_and_errors_fields(self):
        _, _, comparison = _standard()
        broken = copy.deepcopy(comparison)
        broken["direction"] = "earlier_minus_later"
        self.assertHasError(check(broken), "invalid_direction")
        broken = copy.deepcopy(comparison)
        broken["errors"] = ["x"]
        self.assertHasError(check(broken), "invalid_errors_for_valid_comparison")
        broken = copy.deepcopy(comparison)
        broken["valid"] = "yes"
        self.assertHasError(check(broken), "invalid_type:valid")


class SectionClassificationTests(Prompt519TestCase):
    def test_10_contradictory_classification_common_list(self):
        earlier, later = _pair(_ALL, _EARLY, _SMALL, _LATE)
        comparison = compare(earlier, later)
        # the section is earlier-only, but also listed as shared
        broken = copy.deepcopy(comparison)
        broken["common_sections"] = list(_ALL)
        result = check(broken)
        self.assertPrefixError(result, "contradictory_section_classification:trend", "section_errors")
        self.assertFalse(result["well_formed"])

    def test_10b_shared_but_not_listed(self):
        _, _, comparison = _standard()
        comparison["common_sections"].remove("rates")
        self.assertPrefixError(check(comparison), "contradictory_section_classification:rates",
                               "section_errors")

    def test_10c_one_sided_section_carrying_the_other_side(self):
        earlier, later = _pair(_ALL, _EARLY, _SMALL, _LATE)
        comparison = compare(earlier, later)
        comparison["sections"]["trend"]["later"] = {"source": "x"}
        self.assertPrefixError(check(comparison), "contradictory_section_classification:trend",
                               "section_errors")
        earlier, later = _pair(_SMALL, _EARLY, _SMALL, _LATE)
        comparison = compare(earlier, later)
        comparison["sections"]["trend"]["earlier"] = 5
        self.assertPrefixError(check(comparison), "contradictory_section_classification:trend")

    def test_10d_numeric_field_without_shared_section(self):
        earlier, later = _pair(["rates"], _EARLY, ["rates"], _LATE)
        comparison = compare(earlier, later)
        comparison["numeric"]["total_evaluations"] = {
            "earlier": 1, "later": 2, "delta": 1, "changed": True}
        self.assertPrefixError(
            check(comparison),
            "contradictory_section_classification:total_evaluations", "section_errors")

    def test_10e_changed_sections_contradictions(self):
        earlier, later = _pair(_ALL, _EARLY, _SMALL, _LATE)
        comparison = compare(earlier, later)
        comparison["changed_sections"].append("trend")
        self.assertPrefixError(check(comparison), "contradictory_section_classification:trend")
        earlier, later, comparison = _standard()
        comparison["changed_sections"] = []
        self.assertPrefixError(check(comparison), "changed_sections_mismatch:", "section_errors")

    def test_10f_unsupported_presence_and_unknown_section(self):
        _, _, comparison = _standard()
        broken = copy.deepcopy(comparison)
        broken["sections"]["rates"]["presence"] = "both_and_earlier"
        self.assertHasError(check(broken), "unsupported_presence_state:rates", "section_errors")
        broken = copy.deepcopy(comparison)
        broken["sections"]["made_up"] = {"presence": FILTERED_COMPARISON_UNAVAILABLE_BOTH}
        self.assertHasError(check(broken), "unknown_section:made_up", "section_errors")

    def test_10g_identical_flag(self):
        _, _, comparison = _standard()
        comparison["identical"] = True
        self.assertHasError(check(comparison), "inconsistent_identical")

    def test_25_inconsistent_source_classification(self):
        earlier, later, comparison = _standard()
        # claim `trend` is earlier-only although it also exists in the later source
        broken = copy.deepcopy(comparison)
        broken["sections"]["trend"] = {
            "presence": FILTERED_COMPARISON_PRESENT_ONLY_EARLIER,
            "earlier": broken["sections"]["trend"]["earlier"], "later": None}
        broken["common_sections"].remove("trend")
        broken["changed_sections"] = [s for s in broken["changed_sections"] if s != "trend"]
        result = check(broken, earlier, later)
        self.assertHasError(result, "earlier_only_section_in_later_source:trend", "section_errors")
        # ... and the mirror images
        broken["sections"]["trend"] = {
            "presence": FILTERED_COMPARISON_PRESENT_ONLY_LATER, "earlier": None,
            "later": comparison["sections"]["trend"]["later"]}
        result = check(broken, earlier, later)
        self.assertHasError(result, "later_only_section_in_earlier_source:trend")
        # shared claim for a section absent from a source
        small_earlier, small_later = _pair(_SMALL, _EARLY, _ALL, _LATE)
        bogus = compare(earlier, later)
        result = check(bogus, small_earlier, small_later)
        self.assertHasError(result, "shared_section_not_in_source:trend:earlier", "section_errors")
        # unavailable claim for a section a source has
        broken = copy.deepcopy(comparison)
        broken["sections"]["trend"] = {"presence": FILTERED_COMPARISON_UNAVAILABLE_BOTH,
                                       "earlier": None, "later": None}
        broken["common_sections"].remove("trend")
        result = check(broken, earlier, later)
        self.assertHasError(result, "unavailable_section_in_source:trend:earlier")

    def test_25b_recorded_values_must_come_from_sources(self):
        earlier, later, comparison = _standard()
        broken = copy.deepcopy(comparison)
        entry = broken["numeric"]["total_evaluations"]
        entry["later"] = entry["later"] + 5
        entry["delta"] = entry["later"] - entry["earlier"]
        broken["sections"]["evaluation_counts"]["fields"]["total_evaluations"] = copy.deepcopy(entry)
        result = check(broken, earlier, later)
        self.assertHasError(result, "source_mismatch:later:total_evaluations", "numeric_errors")
        # the delta is internally consistent, so it is only the source check that fails
        self.assertEqual(result["structural_errors"], [])
        broken = copy.deepcopy(comparison)
        broken["sections"]["dominant_rejection_reason"]["earlier"] = "made_up"
        broken["sections"]["dominant_rejection_reason"]["change"] = "changed"
        result = check(broken, earlier, later)
        self.assertHasError(result, "source_mismatch:earlier:dominant_rejection_reason",
                            "categorical_errors")


class NumericTests(Prompt519TestCase):
    def _mutate(self, comparison, field, **changes):
        section = "evaluation_counts" if field in (
            "total_evaluations", "accepted_count", "rejected_count", "no_candidate_count") else "rates"
        comparison["numeric"][field].update(changes)
        comparison["sections"][section]["fields"][field] = copy.deepcopy(comparison["numeric"][field])
        return comparison

    def test_12_incorrect_delta(self):
        _, _, comparison = _standard()
        original = copy.deepcopy(comparison)
        self._mutate(comparison, "total_evaluations", delta=comparison["numeric"]["total_evaluations"]["delta"] + 1)
        result = check(comparison)
        self.assertHasError(result, "incorrect_delta:total_evaluations", "numeric_errors")
        self.assertFalse(result["well_formed"])
        self.assertNotEqual(comparison, original)  # never silently repaired
        rates = copy.deepcopy(original)
        self._mutate(rates, "acceptance_rate", delta=0.75)
        self.assertHasError(check(rates), "incorrect_delta:acceptance_rate")

    def test_12b_delta_sign_reversed(self):
        _, _, comparison = _standard()
        entry = comparison["numeric"]["accepted_count"]
        self.assertNotEqual(entry["delta"], 0)
        self._mutate(comparison, "accepted_count", delta=-entry["delta"])
        self.assertHasError(check(comparison), "incorrect_delta:accepted_count")

    def test_12c_delta_section_copy_disagrees_with_numeric(self):
        _, _, comparison = _standard()
        # Prompt 518 aliases the two entries; break the alias before editing one
        fields = comparison["sections"]["evaluation_counts"]["fields"]
        fields["total_evaluations"] = copy.deepcopy(fields["total_evaluations"])
        fields["total_evaluations"]["delta"] = 99
        result = check(comparison)
        self.assertHasError(result, "numeric_section_mismatch:total_evaluations", "numeric_errors")
        self.assertPrefixError(result, "incorrect_delta:evaluation_counts.total_evaluations")

    def test_13_non_finite_numeric_value(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            _, _, comparison = _standard()
            self._mutate(comparison, "acceptance_rate", later=bad, delta=None, changed=None)
            result = check(comparison)
            self.assertHasError(result, "non_finite_value:acceptance_rate.later", "numeric_errors")
        _, _, comparison = _standard()
        self._mutate(comparison, "acceptance_rate", delta=float("nan"))
        self.assertHasError(check(comparison), "non_finite_delta:acceptance_rate")

    def test_13b_invalid_value_types(self):
        for bad in ("3", True, [1]):
            _, _, comparison = _standard()
            self._mutate(comparison, "total_evaluations", earlier=bad, delta=None, changed=None)
            self.assertHasError(check(comparison), "invalid_value_type:total_evaluations.earlier")
        _, _, comparison = _standard()
        self._mutate(comparison, "total_evaluations", later=2.5, delta=None, changed=None)
        self.assertHasError(check(comparison), "invalid_value_type:total_evaluations.later")

    def test_13c_delta_or_flag_present_without_numeric_values(self):
        _, _, comparison = _standard()
        self._mutate(comparison, "total_evaluations", earlier=None)
        result = check(comparison)
        self.assertHasError(result, "delta_present_without_valid_values:total_evaluations")
        self.assertHasError(result, "changed_present_without_valid_values:total_evaluations")
        self.assertIn("numeric_value_unavailable:total_evaluations.earlier", result["unavailable"])

    def test_13d_unavailable_value_with_no_delta_is_not_an_error(self):
        _, _, comparison = _standard()
        self._mutate(comparison, "acceptance_rate", earlier=None, delta=None, changed=None)
        result = check(comparison)
        self.assertNotIn("delta_present_without_valid_values:acceptance_rate", result["errors"])
        self.assertIn("numeric_value_unavailable:acceptance_rate.earlier", result["unavailable"])

    def test_13e_changed_flag_consistency(self):
        _, _, comparison = _standard()
        self._mutate(comparison, "no_candidate_count", changed=True)
        result = check(comparison)
        self.assertHasError(result, "inconsistent_changed:no_candidate_count")
        _, _, comparison = _standard()
        self._mutate(comparison, "accepted_count", changed="yes")
        self.assertHasError(check(comparison), "invalid_changed_flag:accepted_count")

    def test_13f_zero_delta_and_zero_values_are_valid(self):
        _, _, comparison = _standard()
        entry = comparison["numeric"]["no_candidate_count"]
        self.assertEqual((entry["earlier"], entry["later"], entry["delta"], entry["changed"]),
                         (0, 0, 0, False))
        self.assertValid(check(comparison))

    def test_13g_missing_numeric_entry_and_unknown_field(self):
        _, _, comparison = _standard()
        del comparison["numeric"]["rejection_rate"]
        result = check(comparison)
        self.assertHasError(result, "missing_numeric_entry:rejection_rate", "numeric_errors")
        _, _, comparison = _standard()
        comparison["numeric"]["mystery"] = {"earlier": 1, "later": 1, "delta": 0, "changed": False}
        self.assertHasError(check(comparison), "unknown_numeric_field:mystery", "numeric_errors")
        _, _, comparison = _standard()
        del comparison["numeric"]["accepted_count"]["delta"]
        self.assertHasError(check(comparison), "missing_numeric_entry_field:accepted_count.delta")


class CategoricalTests(Prompt519TestCase):
    def _reason_pair(self, early_counts, late_counts):
        earlier, later = _pair(_SMALL, early_counts, _SMALL, late_counts)
        return earlier, later, compare(earlier, later)

    def test_16_changed_state(self):
        earlier, later, comparison = self._reason_pair([{"irrelevant": 2}], [{"low_reliability": 2}])
        entry = comparison["sections"]["dominant_rejection_reason"]
        self.assertEqual(entry["change"], "changed")
        self.assertValid(check(comparison, earlier, later))
        entry["change"] = "unchanged"
        entry["changed"] = False
        result = check(comparison)
        self.assertHasError(result, "inconsistent_categorical_state:dominant_rejection_reason",
                            "categorical_errors")

    def test_17_unchanged_state(self):
        earlier, later, comparison = self._reason_pair([{"irrelevant": 2}], [{"irrelevant": 3}])
        entry = comparison["sections"]["dominant_rejection_reason"]
        self.assertEqual(entry["change"], "unchanged")
        self.assertValid(check(comparison, earlier, later))
        entry["change"] = "changed"
        entry["changed"] = True
        self.assertHasError(check(comparison), "inconsistent_categorical_state:dominant_rejection_reason")

    def test_18_appeared_state(self):
        earlier, later, comparison = self._reason_pair([{"accepted": 2}], [{"irrelevant": 2}])
        entry = comparison["sections"]["dominant_rejection_reason"]
        self.assertEqual(entry["change"], "became_available")
        self.assertValid(check(comparison, earlier, later))
        # "appeared" although the value existed in both snapshots
        both = copy.deepcopy(comparison)
        both["sections"]["dominant_rejection_reason"]["earlier"] = "rejected_irrelevant"
        result = check(both)
        self.assertHasError(result, "inconsistent_categorical_state:dominant_rejection_reason",
                            "categorical_errors")

    def test_19_disappeared_state(self):
        earlier, later, comparison = self._reason_pair([{"irrelevant": 2}], [{"accepted": 2}])
        entry = comparison["sections"]["dominant_rejection_reason"]
        self.assertEqual(entry["change"], "became_empty")
        self.assertValid(check(comparison, earlier, later))
        both = copy.deepcopy(comparison)
        both["sections"]["dominant_rejection_reason"]["later"] = "rejected_irrelevant"
        result = check(both)
        self.assertHasError(result, "inconsistent_categorical_state:dominant_rejection_reason")

    def test_20_insufficient_data_state(self):
        # A section that exists on one side only cannot be compared: it is
        # reported as an insufficient-data condition, not as an error ...
        earlier, later = _pair(_SMALL, _EARLY, ["rates"], _LATE)
        comparison = compare(earlier, later)
        result = check(comparison, earlier, later)
        self.assertValid(result)
        self.assertIn("insufficient_data:dominant_rejection_reason", result["unavailable"])
        self.assertEqual(result["categorical_errors"], [])
        # ... and Prompt 518 never emits it as a categorical *state*
        _, _, standard = _standard()
        standard["sections"]["dominant_rejection_reason"]["change"] = "insufficient_data"
        self.assertHasError(check(standard), "unsupported_categorical_state:dominant_rejection_reason",
                            "categorical_errors")

    def test_21_unsupported_categorical_state(self):
        for bad in ("not_comparable", "improved", "", None, 3, ["changed"]):
            _, _, comparison = _standard()
            comparison["sections"]["dominant_rejection_reason"]["change"] = bad
            self.assertHasError(check(comparison),
                                "unsupported_categorical_state:dominant_rejection_reason",
                                "categorical_errors")
        # composite sections only support unchanged / changed
        _, _, comparison = _standard()
        comparison["sections"]["trend"]["change"] = "became_empty"
        self.assertHasError(check(comparison), "unsupported_categorical_state:trend")

    def test_21b_composite_state_consistent_with_values(self):
        _, _, comparison = _standard()
        entry = comparison["sections"]["trend"]
        self.assertNotEqual(entry["earlier"], entry["later"])
        entry["change"] = "unchanged"
        entry["changed"] = False
        self.assertHasError(check(comparison), "inconsistent_categorical_state:trend")
        _, _, comparison = _standard()
        entry = comparison["sections"]["validation_statuses"]
        self.assertEqual(entry["change"], "unchanged")
        entry["changed"] = True
        self.assertHasError(check(comparison), "inconsistent_changed:validation_statuses")

    def test_21c_categorical_entry_shape(self):
        _, _, comparison = _standard()
        del comparison["sections"]["dominant_rejection_reason"]["change"]
        self.assertHasError(check(comparison), "missing_section_field:dominant_rejection_reason.change",
                            "structural_errors")
        _, _, comparison = _standard()
        comparison["sections"]["dominant_rejection_reason"]["later"] = 42
        self.assertPrefixError(check(comparison), "invalid_categorical_value:dominant_rejection_reason.later")


class OrderingTests(Prompt519TestCase):
    def test_22_reversed_chronological_ordering(self):
        earlier, later, _ = _standard()
        reversed_comparison = compare(later, earlier)
        self.assertFalse(reversed_comparison["chronological"])
        result = check(reversed_comparison, later, earlier)
        self.assertHasError(result, "reversed_ordering", "ordering_errors")
        self.assertTrue(result["well_formed"])  # a faithful result of a reversed pair
        self.assertEqual(result["ordering_errors"], ["reversed_ordering"])

    def test_23_missing_ordering_metadata(self):
        earlier, later, comparison = _standard()
        del comparison["earlier"]["sequence"]
        result = check(comparison)
        self.assertHasError(result, "ordering_metadata_missing:earlier", "ordering_errors")
        self.assertIn("ordering_metadata_unavailable:earlier", result["unavailable"])
        # nothing is invented: no ordering verdict is made without the data
        self.assertNotIn("reversed_ordering", result["errors"])
        for value in ("1", 0, -3, 1.5, True, None):
            _, _, comparison = _standard()
            comparison["later"]["sequence"] = value
            result = check(comparison)
            self.assertHasError(result, "invalid_ordering_metadata:later", "ordering_errors")
            self.assertIn("ordering_metadata_unavailable:later", result["unavailable"])

    def test_24_contradictory_ordering_metadata(self):
        _, _, comparison = _standard()
        comparison["chronological"] = False
        result = check(comparison)
        self.assertHasError(result, "contradictory_ordering:chronological_flag", "ordering_errors")
        self.assertFalse(result["well_formed"])
        _, _, comparison = _standard()
        comparison["chronological"] = "yes"
        self.assertHasError(check(comparison), "invalid_type:chronological")
        # equal sequence but different snapshot ids
        _, _, comparison = _standard()
        comparison["later"]["sequence"] = comparison["earlier"]["sequence"]
        comparison["chronological"] = False
        self.assertHasError(check(comparison), "contradictory_ordering:same_sequence_different_snapshot_id")
        # same snapshot id at two different sequences
        _, _, comparison = _standard()
        comparison["later"]["snapshot_id"] = comparison["earlier"]["snapshot_id"]
        self.assertHasError(check(comparison), "contradictory_ordering:same_snapshot_id_different_sequence")

    def test_24b_ordering_checked_from_comparison_alone(self):
        _, _, comparison = _standard()
        self.assertTrue(comparison["chronological"])
        self.assertValid(check(comparison))


class DeterminismAndIsolationTests(Prompt519TestCase):
    def test_28_deterministic_repeated_validation(self):
        earlier, later, comparison = _standard()
        broken = copy.deepcopy(comparison)
        broken["numeric"]["total_evaluations"]["delta"] = 12345
        broken["sections"]["trend"]["change"] = "bogus"
        broken["chronological"] = False
        for candidate in (comparison, broken, {}, None):
            results = [check(candidate, earlier, later) for _ in range(5)]
            self.assertTrue(all(result == results[0] for result in results))
        # equal inputs built independently give equal results
        e2, l2, c2 = _standard()
        self.assertEqual(check(comparison, earlier, later), check(c2, e2, l2))

    def test_29_does_not_mutate_source_snapshots(self):
        earlier, later, comparison = _standard()
        before_e, before_l = copy.deepcopy(earlier), copy.deepcopy(later)
        check(comparison, earlier, later)
        broken = copy.deepcopy(comparison)
        broken["numeric"]["total_evaluations"]["delta"] = 99
        check(broken, earlier, later)
        check(comparison, later, earlier)
        check(comparison, None, {"x": 1})
        self.assertEqual(earlier, before_e)
        self.assertEqual(later, before_l)

    def test_30_does_not_mutate_comparison_result(self):
        _, _, comparison = _standard()
        candidates = [comparison]
        broken = copy.deepcopy(comparison)
        broken["numeric"]["total_evaluations"]["delta"] = 99
        broken["sections"]["rates"]["presence"] = "wat"
        broken["common_sections"].append("trend")
        broken["chronological"] = False
        candidates.append(broken)
        candidates.append(compare({"snapshot_id": "x"}, {"snapshot_id": "y"}))
        candidates.append(compare(_standard()[1], _standard()[0]))
        for candidate in candidates:
            snapshot = copy.deepcopy(candidate)
            check(candidate)
            self.assertEqual(candidate, snapshot)
            # repeated with sources
        earlier, later, comparison = _standard()
        snapshot = copy.deepcopy(comparison)
        check(comparison, earlier, later)
        self.assertEqual(comparison, snapshot)

    def test_result_is_independent_of_inputs(self):
        _, _, comparison = _standard()
        result = check(comparison)
        result["errors"].append("tampered")
        result["unavailable"].append("tampered")
        self.assertValid(check(comparison))

    def test_never_raises_on_malformed_input(self):
        _, _, comparison = _standard()
        junk = [1, "x", [], {"valid": True}, {"valid": False}, {"valid": True, "sections": 3, "numeric": 4,
                "common_sections": "x", "changed_sections": 5, "earlier": [], "later": 7,
                "chronological": {}, "identical": [], "earlier_validation_status": {}},
                {"valid": True, "sections": {"rates": []}, "numeric": {"x": 1, (1, 2): 2}}]
        for candidate in junk:
            result = check(candidate)
            self.assertFalse(result["valid"])
            check(candidate, {}, [])
        for field in list(comparison):
            broken = copy.deepcopy(comparison)
            broken[field] = object()
            check(broken)
            broken[field] = None
            check(broken)

    def test_result_shape(self):
        result = check({})
        self.assertEqual(list(result), [
            "valid", "well_formed", "errors", "warnings", "structural_errors", "section_errors",
            "numeric_errors", "categorical_errors", "ordering_errors", "source_snapshot_errors",
            "unavailable"])
        self.assertEqual(result["errors"], result["structural_errors"])

    def test_source_errors_are_kept_apart_from_structural_errors(self):
        earlier, later, comparison = _standard()
        comparison["sections"]["evaluation_counts"]["fields"]["total_evaluations"]["delta"] += 1
        result = check(compare({"snapshot_id": "x"}, later), {"snapshot_id": "x"}, later)
        self.assertEqual(result["structural_errors"], [])
        self.assertEqual(result["source_snapshot_errors"], ["source_snapshot_invalid:earlier"])
        self.assertTrue(result["well_formed"])


class RegressionTests(Prompt519TestCase):
    def test_prompt_510_validator_and_518_comparison_unchanged(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_stats(accepted=1))
        history.record_statistics(_stats(accepted=2))
        comparison = history.compare_sequences(1, 2)
        result = check509(comparison)
        self.assertEqual(list(result), ["valid", "well_formed", "errors", "warnings"])
        self.assertTrue(result["valid"])
        # the Prompt 509 comparison is rejected by the Prompt 519 validator (wrong shape), not repaired
        self.assertFalse(check(comparison)["valid"])
        earlier, later, filtered = _standard()
        self.assertEqual(filtered, compare(earlier, later))
        self.assertEqual(sorted(filtered), sorted([
            "valid", "errors", "direction", "earlier", "later", "chronological",
            "earlier_validation_status", "later_validation_status", "common_sections",
            "identical", "changed_sections", "numeric", "sections"]))

    def test_snapshot_history_unchanged(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        snapshot = history.record_filtered_summary(filt(_summary(), _ALL))
        self.assertEqual(snapshot["sequence"], 1)
        self.assertEqual(history.get_by_sequence(1), snapshot)
        self.assertFalse(math.isnan(0.0))


if __name__ == "__main__":
    unittest.main()
