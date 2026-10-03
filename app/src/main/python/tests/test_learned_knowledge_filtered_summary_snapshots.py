"""
Tests for Prompt 517 - Filtered Diagnostic Summary Snapshots.

`LearnedKnowledgeFilteredSummarySnapshotHistory`
(learning/learned_knowledge_statistics.py) keeps bounded, isolated,
point-in-time snapshots of the dict `filter_learned_knowledge_diagnostic_
summary()` (Prompt 516) returns. It shares the Prompt 508 snapshot
storage (`_BoundedDiagnosticSnapshotStore`) rather than adding a second
history system, and stores only diagnostic section data.

Covers:
    1.  snapshot from a valid filtered summary
    2.  snapshot from an invalid filtered summary
    3.  one selected section
    4.  multiple selected sections
    5.  unavailable-section information
    6.  multiple snapshots
    7.  latest snapshot
    8.  recent snapshots
    9.  deterministic ordering
    10. identity / sequence behavior
    11. retention behavior
    12. source summary mutation after creation
    13. retrieved-snapshot mutation isolation
    14. numeric values preserved
    15. trend states preserved
    16. categorical states preserved
    17. validation status preserved
    18. empty diagnostic data
    19. zero-evaluation data
    20. deterministic snapshot creation
    21. no raw user content stored
    22. no learned knowledge duplicated
    23. Prompt 508 snapshot behavior intact
    24. Prompt 516 filtering unchanged
    25. regression coverage for Prompts 500-516

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_summary_snapshots -v
"""

import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK, REASON_NOT_RELEVANT, REASON_INSUFFICIENT_RELIABILITY,
    LearnedKnowledgeGateResult, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    DEFAULT_MAX_SNAPSHOT_HISTORY,
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    LearnedKnowledgeFilteredSummarySnapshotHistory,
    SNAPSHOT_KIND_FILTERED_SUMMARY,
    SNAPSHOT_VALIDATION_VALID, SNAPSHOT_VALIDATION_INVALID,
    REPORT_VALIDITY_VALID, REPORT_VALIDITY_INVALID,
    summarize_learned_knowledge_diagnostic_snapshot_comparison_trend as trend,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate_comparison,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
)

_SNAPSHOT_KEYS = [
    "snapshot_id", "sequence", "snapshot_kind", "creation_context", "validation_status",
    "validation_errors", "included_sections", "unavailable_sections", "unknown_section_count",
    "metrics",
]
_ALL_SECTIONS = [
    "evaluation_counts", "rates", "dominant_rejection_reason",
    "comparison_changes", "trend", "validation_statuses",
]
_ID_PREFIX = "learned_knowledge_snapshot_"
_MARKER = "SECRET-USER-TEXT-do-not-store"


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


def _pipeline(counts_list=None):
    history = _history(counts_list or [{"accepted": 1}, {"accepted": 3}, {"irrelevant": 2}])
    comparisons = _chain(history)
    built = report(snapshots=history, comparisons=comparisons)
    return history, comparisons, built, validate(built, snapshots=history, comparisons=comparisons)


def _summary(counts_list=None):
    _, _, built, validation = _pipeline(counts_list)
    return fmt(built, validation)


def _filtered(sections, counts_list=None):
    return filt(_summary(counts_list), sections)


def _partial_summary():
    history = _history([{"accepted": 2, "irrelevant": 1}])
    built = report(snapshots=history)
    return fmt(built, validate(built, snapshots=history))


def _invalid_summary(errors=None):
    _, _, built, _ = _pipeline()
    broken = copy.deepcopy(built)
    broken["structural_status"] = "unknown"
    validation = validate(broken)
    assert not validation["valid"]
    if errors is not None:
        validation = {"valid": False, "well_formed": False, "errors": errors, "warnings": []}
    return fmt(broken, validation)


def _invalid_status_history_and_comparison():
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record({}, {"valid": False, "errors": ["boom"]})
    history.record_statistics(_stats(accepted=2))
    comparison = history.compare_sequences(1, 2)
    assert validate_comparison(comparison)["valid"] is False
    return history, comparison


def _walk(value):
    """Every object nested inside `value` (lists/dicts), for identity checks."""
    yield value
    if isinstance(value, dict):
        for item in value.values():
            for inner in _walk(item):
                yield inner
    elif isinstance(value, list):
        for item in value:
            for inner in _walk(item):
                yield inner


class Prompt517TestCase(unittest.TestCase):

    def assertSnapshotShape(self, snapshot):
        self.assertEqual(list(snapshot.keys()), _SNAPSHOT_KEYS)
        self.assertEqual(snapshot["snapshot_kind"], SNAPSHOT_KIND_FILTERED_SUMMARY)
        self.assertEqual(snapshot["creation_context"], {"source": "filtered_diagnostic_summary"})
        self.assertIn(snapshot["validation_status"], (SNAPSHOT_VALIDATION_VALID, SNAPSHOT_VALIDATION_INVALID))
        for key in ("validation_errors", "included_sections", "unavailable_sections"):
            self.assertIsInstance(snapshot[key], list)
        self.assertIsInstance(snapshot["metrics"], dict)


# ----------------------------------------------------------------------
# 1. valid filtered summary
# ----------------------------------------------------------------------
class TestValidFilteredSummary(Prompt517TestCase):

    def test_snapshot_records_the_selection_and_values(self):
        filtered = _filtered(_ALL_SECTIONS)
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        snapshot = history.record_filtered_summary(filtered)
        self.assertSnapshotShape(snapshot)
        self.assertEqual(snapshot["snapshot_id"], _ID_PREFIX + "000001")
        self.assertEqual(snapshot["sequence"], 1)
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_VALID)
        self.assertEqual(snapshot["validation_errors"], [])
        self.assertEqual(snapshot["included_sections"], filtered["included_sections"])
        self.assertEqual(snapshot["unavailable_sections"], [])
        self.assertEqual(snapshot["unknown_section_count"], 0)
        self.assertEqual(snapshot["metrics"], filtered["metrics"])

    def test_returned_copy_equals_what_is_stored(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        returned = history.record_filtered_summary(_filtered(["rates"]))
        self.assertEqual(history.get_latest(), returned)
        self.assertEqual(len(history), 1)


# ----------------------------------------------------------------------
# 2. invalid filtered summary
# ----------------------------------------------------------------------
class TestInvalidFilteredSummary(Prompt517TestCase):

    def test_invalid_filtered_summary_stays_invalid_with_its_errors(self):
        errors = ["mismatched_field:trend", "count_negative:comparison"]
        filtered = filt(_invalid_summary(errors), ["rates", "trend", "nope"])
        self.assertEqual(filtered["report_validity"], REPORT_VALIDITY_INVALID)
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertSnapshotShape(snapshot)
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_INVALID)
        self.assertEqual(snapshot["validation_errors"], errors)
        self.assertEqual(snapshot["included_sections"], [])
        self.assertEqual(snapshot["unavailable_sections"], ["rates", "trend"])
        self.assertEqual(snapshot["unknown_section_count"], 1)
        self.assertEqual(snapshot["metrics"], {"rates": None, "trend": None})

    def test_invalid_snapshot_is_not_repaired_or_presented_as_valid(self):
        filtered = filt(_invalid_summary(), _ALL_SECTIONS)
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_INVALID)
        self.assertTrue(all(value is None for value in snapshot["metrics"].values()))

    def test_malformed_inputs_become_invalid_snapshots_without_raising(self):
        good = _filtered(["rates"])
        cases = {
            "not_a_dict": None,
            "list": [],
            "empty_dict": {},
        }
        for name, bad in cases.items():
            with self.subTest(case=name):
                snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(bad)
                self.assertSnapshotShape(snapshot)
                self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_INVALID)
                self.assertEqual(snapshot["included_sections"], [])
                self.assertEqual(snapshot["metrics"], {})
                self.assertIsNone(snapshot["unknown_section_count"])
                self.assertTrue(snapshot["validation_errors"])
        for field in ("included_sections", "unavailable_sections", "unknown_sections",
                      "validation_errors", "metrics", "report_validity"):
            with self.subTest(missing=field):
                broken = copy.deepcopy(good)
                del broken[field]
                snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(broken)
                self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_INVALID)
                self.assertEqual(snapshot["metrics"], {})

    def test_inconsistent_filtered_summaries_are_rejected_not_repaired(self):
        good = _filtered(["rates", "trend"])
        tampered = {
            "valid_with_errors": dict(copy.deepcopy(good), validation_errors=["x"]),
            "unavailable_with_data": dict(copy.deepcopy(good), unavailable_sections=["trend"]),
            "included_without_metrics": dict(copy.deepcopy(good), metrics={"rates": good["metrics"]["rates"]}),
            "included_wrong_shape": dict(copy.deepcopy(good), metrics={"rates": "text", "trend": good["metrics"]["trend"]}),
            "unknown_section_name": dict(copy.deepcopy(good), included_sections=["rates", "bogus"]),
            "non_string_name": dict(copy.deepcopy(good), included_sections=["rates", 3]),
            "overlapping": dict(copy.deepcopy(good), unavailable_sections=["rates"]),
            "invalid_yet_included": dict(copy.deepcopy(good), report_validity="invalid"),
            "bad_validity": dict(copy.deepcopy(good), report_validity="maybe"),
        }
        for name, bad in tampered.items():
            with self.subTest(case=name):
                snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(bad)
                self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_INVALID)
                self.assertEqual(snapshot["included_sections"], [])
                self.assertEqual(snapshot["metrics"], {})

    def test_errors_the_summary_carried_come_first_then_the_reason(self):
        bad = dict(_filtered(["rates"]), validation_errors=["e1"])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(bad)
        self.assertEqual(snapshot["validation_errors"][0], "e1")
        self.assertIn("filtered_summary_valid_with_validation_errors", snapshot["validation_errors"])


# ----------------------------------------------------------------------
# 3-5. one / multiple / unavailable sections
# ----------------------------------------------------------------------
class TestSelectedSections(Prompt517TestCase):

    def test_one_selected_section(self):
        filtered = _filtered(["trend"])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertEqual(snapshot["included_sections"], ["trend"])
        self.assertEqual(list(snapshot["metrics"]), ["trend"])
        self.assertEqual(snapshot["metrics"]["trend"], filtered["metrics"]["trend"])

    def test_multiple_selected_sections_keep_the_fixed_section_order(self):
        filtered = _filtered(["validation_statuses", "trend", "evaluation_counts"])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertEqual(snapshot["included_sections"], ["evaluation_counts", "trend", "validation_statuses"])
        self.assertEqual(list(snapshot["metrics"]), ["evaluation_counts", "trend", "validation_statuses"])
        for section in snapshot["included_sections"]:
            self.assertEqual(snapshot["metrics"][section], filtered["metrics"][section])

    def test_unavailable_sections_stay_unavailable_and_are_not_fabricated(self):
        filtered = filt(_partial_summary(), ["rates", "trend", "comparison_changes"])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_VALID)
        self.assertEqual(snapshot["included_sections"], ["rates"])
        self.assertEqual(snapshot["unavailable_sections"], ["comparison_changes", "trend"])
        self.assertIsNone(snapshot["metrics"]["comparison_changes"])
        self.assertIsNone(snapshot["metrics"]["trend"])
        self.assertEqual(list(snapshot["metrics"]), ["rates", "comparison_changes", "trend"])

    def test_unknown_names_are_counted_not_stored(self):
        filtered = _filtered(["rates", "zzz", "yyy", "zzz"])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertEqual(snapshot["unknown_section_count"], 2)
        self.assertNotIn("zzz", json.dumps(snapshot))
        self.assertNotIn("yyy", json.dumps(snapshot))

    def test_dominant_reason_none_is_kept_as_a_value(self):
        filtered = _filtered(["dominant_rejection_reason"], [{"accepted": 3}])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertEqual(snapshot["included_sections"], ["dominant_rejection_reason"])
        self.assertIsNone(snapshot["metrics"]["dominant_rejection_reason"])


# ----------------------------------------------------------------------
# 6-9. multiple, latest, recent, ordering
# ----------------------------------------------------------------------
class TestMultipleLatestRecentOrdering(Prompt517TestCase):

    def _filled(self, count=5):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        for i in range(count):
            history.record_filtered_summary(_filtered(["rates"], [{"accepted": i + 1}]))
        return history

    def test_multiple_snapshots_are_all_held(self):
        history = self._filled(4)
        self.assertEqual(len(history), 4)
        self.assertEqual([s["sequence"] for s in history.get_all()], [1, 2, 3, 4])

    def test_latest_snapshot(self):
        history = self._filled(3)
        self.assertEqual(history.get_latest()["sequence"], 3)
        self.assertEqual(history.get_latest(), history.get_all()[-1])

    def test_latest_of_empty_history_is_none(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        self.assertIsNone(history.get_latest())
        self.assertEqual(history.get_all(), [])
        self.assertEqual(history.get_recent(3), [])
        self.assertEqual(len(history), 0)

    def test_recent_snapshots_are_the_newest_but_still_oldest_first(self):
        history = self._filled(5)
        self.assertEqual([s["sequence"] for s in history.get_recent(2)], [4, 5])
        self.assertEqual([s["sequence"] for s in history.get_recent(99)], [1, 2, 3, 4, 5])
        self.assertEqual(history.get_recent(), history.get_all())
        for bad in (0, -1, "2", 1.5, True):
            with self.subTest(limit=bad):
                self.assertEqual(history.get_recent(bad), [])

    def test_retrieval_order_is_oldest_first_and_stable(self):
        history = self._filled(4)
        first = [s["snapshot_id"] for s in history.get_all()]
        self.assertEqual(first, [_ID_PREFIX + "00000%d" % n for n in (1, 2, 3, 4)])
        self.assertEqual([s["snapshot_id"] for s in history.get_all()], first)
        for snapshot in history.get_all():
            self.assertEqual(list(snapshot["metrics"]), ["rates"])

    def test_get_by_sequence(self):
        history = self._filled(3)
        self.assertEqual(history.get_by_sequence(2), history.get_all()[1])
        for missing in (0, 4, -1, None, "1", 1.0):
            with self.subTest(sequence=missing):
                self.assertIsNone(history.get_by_sequence(missing))


# ----------------------------------------------------------------------
# 10. identity / sequence
# ----------------------------------------------------------------------
class TestIdentityAndSequence(Prompt517TestCase):

    def test_ids_follow_the_prompt_508_convention(self):
        analysis_history = _history([{"accepted": 1}])
        filtered_history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        filtered_snapshot = filtered_history.record_filtered_summary(_filtered(["rates"]))
        analysis_snapshot = analysis_history.get_latest()
        self.assertEqual(filtered_snapshot["snapshot_id"], analysis_snapshot["snapshot_id"])
        self.assertEqual(filtered_snapshot["sequence"], analysis_snapshot["sequence"])
        self.assertNotIn("snapshot_kind", analysis_snapshot)
        self.assertEqual(filtered_snapshot["snapshot_kind"], "filtered_summary")

    def test_sequences_are_one_based_increasing_and_independent_per_history(self):
        first = LearnedKnowledgeFilteredSummarySnapshotHistory()
        second = LearnedKnowledgeFilteredSummarySnapshotHistory()
        analysis = _history([{"accepted": 1}, {"accepted": 2}])
        self.assertEqual(first.record_filtered_summary(_filtered(["rates"]))["sequence"], 1)
        self.assertEqual(first.record_filtered_summary(_filtered(["rates"]))["sequence"], 2)
        self.assertEqual(second.record_filtered_summary(_filtered(["rates"]))["sequence"], 1)
        self.assertEqual(len(analysis), 2)

    def test_invalid_snapshots_also_consume_a_sequence_number(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        history.record_filtered_summary(_filtered(["rates"]))
        self.assertEqual(history.record_filtered_summary(None)["sequence"], 2)
        self.assertEqual(history.record_filtered_summary(_filtered(["rates"]))["sequence"], 3)

    def test_sequence_numbers_are_never_reused_after_eviction(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory(max_snapshots=2)
        for _ in range(4):
            history.record_filtered_summary(_filtered(["rates"]))
        self.assertEqual([s["sequence"] for s in history.get_all()], [3, 4])
        self.assertEqual(history.record_filtered_summary(_filtered(["rates"]))["sequence"], 5)
        self.assertIsNone(history.get_by_sequence(1))


# ----------------------------------------------------------------------
# 11. retention
# ----------------------------------------------------------------------
class TestRetention(Prompt517TestCase):

    def test_default_capacity_is_the_prompt_508_capacity(self):
        self.assertEqual(LearnedKnowledgeFilteredSummarySnapshotHistory().max_snapshots, DEFAULT_MAX_SNAPSHOT_HISTORY)
        self.assertEqual(LearnedKnowledgeFilteredSummarySnapshotHistory().max_snapshots,
                         LearnedKnowledgeDiagnosticSnapshotHistory().max_snapshots)

    def test_invalid_capacity_falls_back_to_the_default(self):
        for bad in (0, -3, None, "5", 2.5, True):
            with self.subTest(capacity=bad):
                self.assertEqual(LearnedKnowledgeFilteredSummarySnapshotHistory(max_snapshots=bad).max_snapshots,
                                 DEFAULT_MAX_SNAPSHOT_HISTORY)

    def test_only_the_single_oldest_snapshot_is_dropped_first_in_first_out(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory(max_snapshots=3)
        for _ in range(3):
            history.record_filtered_summary(_filtered(["rates"]))
        self.assertEqual([s["sequence"] for s in history.get_all()], [1, 2, 3])
        history.record_filtered_summary(_filtered(["rates"]))
        self.assertEqual([s["sequence"] for s in history.get_all()], [2, 3, 4])
        self.assertEqual(len(history), 3)

    def test_history_never_exceeds_capacity(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory(max_snapshots=5)
        for _ in range(23):
            history.record_filtered_summary(_filtered(["rates"]))
            self.assertLessEqual(len(history), 5)
        self.assertEqual([s["sequence"] for s in history.get_all()], [19, 20, 21, 22, 23])

    def test_capacity_of_one_keeps_only_the_latest(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory(max_snapshots=1)
        history.record_filtered_summary(_filtered(["rates"]))
        history.record_filtered_summary(_filtered(["trend"]))
        self.assertEqual([s["included_sections"] for s in history.get_all()], [["trend"]])

    def test_retention_is_the_shared_prompt_508_implementation(self):
        # One implementation: both histories inherit the same storage methods.
        for name in ("_store_snapshot", "get_all", "get_latest", "get_recent", "_copy_of_sequence", "__len__"):
            self.assertIs(getattr(LearnedKnowledgeFilteredSummarySnapshotHistory, name),
                          getattr(LearnedKnowledgeDiagnosticSnapshotHistory, name))


# ----------------------------------------------------------------------
# 12-13. isolation
# ----------------------------------------------------------------------
class TestIsolation(Prompt517TestCase):

    def test_mutating_the_source_summary_after_creation_does_not_change_the_snapshot(self):
        filtered = _filtered(_ALL_SECTIONS)
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        history.record_filtered_summary(filtered)
        before = history.get_latest()
        filtered["metrics"]["rates"]["acceptance_rate"] = -1
        filtered["metrics"]["trend"]["chronological_range"]["earlier"] = "tampered"
        filtered["metrics"]["comparison_changes"]["changed_fields"].append("tampered")
        filtered["included_sections"].clear()
        filtered["validation_errors"].append("tampered")
        filtered["report_validity"] = "invalid"
        self.assertEqual(history.get_latest(), before)

    def test_returned_snapshot_shares_no_state_with_the_source(self):
        filtered = _filtered(_ALL_SECTIONS)
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        source_ids = {id(obj) for obj in _walk(filtered) if isinstance(obj, (dict, list))}
        for obj in _walk(snapshot):
            if isinstance(obj, (dict, list)):
                self.assertNotIn(id(obj), source_ids)

    def test_mutating_a_retrieved_snapshot_does_not_change_the_stored_one(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        history.record_filtered_summary(_filtered(_ALL_SECTIONS))
        pristine = history.get_latest()
        for retrieved in (history.get_latest(), history.get_all()[0], history.get_recent(1)[0],
                          history.get_by_sequence(1)):
            retrieved["metrics"]["rates"]["acceptance_rate"] = -1
            retrieved["metrics"]["trend"]["chronological_range"] = "tampered"
            retrieved["included_sections"].append("tampered")
            retrieved["validation_errors"].append("tampered")
            retrieved["creation_context"]["source"] = "tampered"
            retrieved["metrics"].clear()
        self.assertEqual(history.get_latest(), pristine)

    def test_the_returned_value_of_record_is_also_a_copy(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        returned = history.record_filtered_summary(_filtered(["rates"]))
        returned["metrics"]["rates"]["acceptance_rate"] = -1
        returned["included_sections"].append("tampered")
        self.assertNotEqual(history.get_latest()["metrics"]["rates"]["acceptance_rate"], -1)
        self.assertEqual(history.get_latest()["included_sections"], ["rates"])

    def test_repeated_retrieval_never_shares_mutable_state(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        history.record_filtered_summary(_filtered(_ALL_SECTIONS))
        first, second = history.get_latest(), history.get_latest()
        self.assertEqual(first, second)
        first_ids = {id(o) for o in _walk(first) if isinstance(o, (dict, list))}
        for obj in _walk(second):
            if isinstance(obj, (dict, list)):
                self.assertNotIn(id(obj), first_ids)
        self.assertIsNot(history.get_all()[0], history.get_all()[0])

    def test_earlier_snapshots_are_unaffected_by_later_ones(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        history.record_filtered_summary(_filtered(["rates"], [{"accepted": 1}]))
        first = history.get_all()[0]
        history.record_filtered_summary(_filtered(["rates"], [{"irrelevant": 4}]))
        self.assertEqual(history.get_all()[0], first)


# ----------------------------------------------------------------------
# 14-17. preserved values and statuses
# ----------------------------------------------------------------------
class TestValuesPreserved(Prompt517TestCase):

    def test_numeric_values_keep_type_and_precision(self):
        filtered = _filtered(["evaluation_counts", "rates"], [{"accepted": 1, "irrelevant": 2}])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        for section in ("evaluation_counts", "rates"):
            for key, value in filtered["metrics"][section].items():
                stored = snapshot["metrics"][section][key]
                self.assertIs(type(stored), type(value))
                self.assertEqual(repr(stored), repr(value))
        self.assertEqual(snapshot["metrics"]["rates"]["acceptance_rate"], 1 / 3)

    def test_comparison_and_trend_numbers_are_unchanged(self):
        filtered = _filtered(["comparison_changes", "trend"],
                             [{"accepted": 4}, {"accepted": 1, "irrelevant": 2}, {"irrelevant": 5}])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertEqual(repr(snapshot["metrics"]["comparison_changes"]["numeric"]),
                         repr(filtered["metrics"]["comparison_changes"]["numeric"]))
        self.assertEqual(snapshot["metrics"]["trend"], filtered["metrics"]["trend"])

    def test_trend_states_are_preserved(self):
        cases = {
            "increased": ([{"accepted": 1}, {"accepted": 2}, {"accepted": 3}], "total_evaluations"),
            "decreased": ([{"accepted": 5}, {"accepted": 3}, {"accepted": 1}], "accepted_count"),
            "unchanged": ([{"accepted": 2}, {"accepted": 4}, {"accepted": 6}], "no_candidate_count"),
        }
        for state, (counts, field) in cases.items():
            with self.subTest(state=state):
                snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(
                    _filtered(["trend"], counts))
                self.assertEqual(snapshot["metrics"]["trend"][field]["state"], state)

    def test_insufficient_data_trend_state_is_preserved(self):
        history, comparison = _invalid_status_history_and_comparison()
        built = report(snapshots=history, comparisons=[comparison])
        summary = fmt(built, validate(built, snapshots=history, comparisons=[comparison]))
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(
            filt(summary, ["trend"]))
        self.assertEqual(snapshot["metrics"]["trend"]["total_evaluations"]["state"], "insufficient data")
        self.assertEqual(snapshot["metrics"]["trend"]["dominant_rejection_reason"]["state"], "insufficient data")

    def test_categorical_states_are_preserved(self):
        cases = {
            "changed": [{"irrelevant": 3}, {"low_reliability": 3}],
            "appeared": [{"accepted": 3}, {"irrelevant": 3}],
            "disappeared": [{"irrelevant": 3}, {"accepted": 3}],
            "unchanged": [{"irrelevant": 3}, {"irrelevant": 5}],
        }
        for state, counts in cases.items():
            with self.subTest(state=state):
                snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(
                    _filtered(["comparison_changes"], counts))
                self.assertEqual(
                    snapshot["metrics"]["comparison_changes"]["dominant_rejection_reason_change"], state)

    def test_validation_statuses_section_and_status_are_preserved(self):
        filtered = _filtered(["validation_statuses"])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertEqual(snapshot["metrics"]["validation_statuses"], filtered["metrics"]["validation_statuses"])
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_VALID)
        invalid = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(
            filt(_invalid_summary(["e"]), ["rates"]))
        self.assertEqual(invalid["validation_status"], SNAPSHOT_VALIDATION_INVALID)

    def test_chronological_information_is_preserved(self):
        filtered = _filtered(["comparison_changes", "trend"],
                             [{"accepted": 1}, {"accepted": 3}, {"irrelevant": 2}, {"irrelevant": 4}])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        source, stored = filtered["metrics"], snapshot["metrics"]
        self.assertEqual(stored["trend"]["chronological_range"], source["trend"]["chronological_range"])
        self.assertEqual(stored["comparison_changes"]["earlier"], source["comparison_changes"]["earlier"])
        self.assertEqual(stored["comparison_changes"]["later"], source["comparison_changes"]["later"])
        self.assertEqual(stored["comparison_changes"]["changed_fields"], source["comparison_changes"]["changed_fields"])
        self.assertEqual(list(stored["trend"]), list(source["trend"]))
        self.assertEqual(list(stored["comparison_changes"]["numeric"]), list(source["comparison_changes"]["numeric"]))


# ----------------------------------------------------------------------
# 18-19. empty and zero-evaluation data
# ----------------------------------------------------------------------
class TestEmptyAndZeroData(Prompt517TestCase):

    def test_empty_diagnostic_data(self):
        built = report()
        summary = fmt(built, validate(built))
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(
            filt(summary, _ALL_SECTIONS))
        self.assertSnapshotShape(snapshot)
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_VALID)
        self.assertEqual(snapshot["included_sections"], ["validation_statuses"])
        self.assertEqual(snapshot["unavailable_sections"],
                         [s for s in _ALL_SECTIONS if s != "validation_statuses"])
        self.assertIsNone(snapshot["metrics"]["trend"])

    def test_empty_section_request_gives_an_empty_valid_snapshot(self):
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(_filtered([]))
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_VALID)
        self.assertEqual(snapshot["included_sections"], [])
        self.assertEqual(snapshot["unavailable_sections"], [])
        self.assertEqual(snapshot["metrics"], {})
        self.assertEqual(snapshot["unknown_section_count"], 0)

    def test_zero_evaluation_data(self):
        filtered = _filtered(["evaluation_counts", "rates", "dominant_rejection_reason"], [{}])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertEqual(snapshot["metrics"], filtered["metrics"])
        self.assertEqual(snapshot["metrics"]["evaluation_counts"]["total_evaluations"], 0)
        self.assertIsNone(snapshot["metrics"]["dominant_rejection_reason"])


# ----------------------------------------------------------------------
# 20. deterministic creation
# ----------------------------------------------------------------------
class TestDeterministicCreation(Prompt517TestCase):

    def test_same_summary_and_state_give_equal_snapshots(self):
        first = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(
            _filtered(["trend", "rates", "zz"]))
        second = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(
            _filtered(["trend", "rates", "zz"]))
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(first), json.dumps(second))

    def test_same_summary_twice_differs_only_in_identity(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        filtered = _filtered(_ALL_SECTIONS)
        one = history.record_filtered_summary(filtered)
        two = history.record_filtered_summary(filtered)
        for snapshot in (one, two):
            del snapshot["snapshot_id"], snapshot["sequence"]
        self.assertEqual(one, two)

    def test_whole_histories_built_the_same_way_are_equal(self):
        def build():
            history = LearnedKnowledgeFilteredSummarySnapshotHistory(max_snapshots=3)
            for counts in ([{"accepted": 1}], [{"accepted": 2}], [{"irrelevant": 2}], [{"accepted": 3}]):
                history.record_filtered_summary(_filtered(["rates", "trend"], counts))
            history.record_filtered_summary(None)
            return history.get_all()
        self.assertEqual(build(), build())

    def test_snapshots_contain_no_timestamps_or_run_specific_values(self):
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(_filtered(_ALL_SECTIONS))
        for banned in ("time", "date", "uuid", "pid", "random"):
            self.assertNotIn(banned, "".join(snapshot.keys()))


# ----------------------------------------------------------------------
# 21. no raw user content
# ----------------------------------------------------------------------
class TestNoRawUserContent(Prompt517TestCase):

    def test_extra_top_level_content_is_never_stored(self):
        filtered = _filtered(_ALL_SECTIONS)
        filtered["conversation"] = [{"role": "user", "text": _MARKER}]
        filtered["user_text"] = _MARKER
        filtered["summary_text"] = _MARKER
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertNotIn(_MARKER, json.dumps(snapshot))
        self.assertEqual(list(snapshot.keys()), _SNAPSHOT_KEYS)

    def test_extra_keys_inside_sections_are_dropped(self):
        filtered = _filtered(["evaluation_counts", "rates", "comparison_changes", "trend", "validation_statuses"])
        for section in filtered["metrics"]:
            filtered["metrics"][section]["raw_user_input"] = _MARKER
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertNotIn(_MARKER, json.dumps(snapshot))
        self.assertNotIn("raw_user_input", json.dumps(snapshot))
        for section in snapshot["included_sections"]:
            self.assertEqual(snapshot["metrics"][section],
                             {k: v for k, v in _filtered(_ALL_SECTIONS)["metrics"][section].items()})

    def test_requested_names_are_not_stored_even_when_they_look_like_user_text(self):
        filtered = _filtered(["rates", _MARKER, "another " + _MARKER])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertNotIn(_MARKER, json.dumps(snapshot))
        self.assertEqual(snapshot["unknown_section_count"], 2)

    def test_unavailable_section_values_that_carry_content_are_rejected(self):
        filtered = _filtered(["rates"])
        filtered["unavailable_sections"] = ["trend"]
        filtered["metrics"]["trend"] = {"leak": _MARKER}
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertNotIn(_MARKER, json.dumps(snapshot))
        self.assertEqual(snapshot["validation_status"], SNAPSHOT_VALIDATION_INVALID)

    def test_only_diagnostic_sections_are_ever_snapshotted(self):
        filtered = _filtered(["rates"])
        filtered["metrics"]["memory"] = {"note": _MARKER}
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertEqual(list(snapshot["metrics"]), ["rates"])
        self.assertNotIn(_MARKER, json.dumps(snapshot))


# ----------------------------------------------------------------------
# 22. no learned knowledge duplicated
# ----------------------------------------------------------------------
class TestNoLearnedKnowledgeDuplicated(Prompt517TestCase):

    def test_snapshot_contains_only_diagnostic_fields(self):
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(_filtered(_ALL_SECTIONS))
        self.assertEqual(set(snapshot["metrics"]), set(_ALL_SECTIONS))
        text = json.dumps(snapshot).lower()
        for banned in ("learned_record", "knowledge_entry", "trace", "conversation", "prompt", "memory"):
            self.assertNotIn(banned, text)

    def test_statistics_and_traces_are_not_touched(self):
        stats = _stats(accepted=2, irrelevant=1)
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(stats)
        before_stats = stats.summary()
        before_traces = (repr(ACCEPTED), copy.deepcopy(getattr(ACCEPTED, "__dict__", None)))
        built = report(snapshots=history)
        LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(
            filt(fmt(built, validate(built, snapshots=history)), _ALL_SECTIONS))
        self.assertEqual(stats.summary(), before_stats)
        self.assertEqual((repr(ACCEPTED), getattr(ACCEPTED, "__dict__", None)), before_traces)

    def test_snapshot_is_smaller_than_the_data_it_selects_from(self):
        filtered = _filtered(["rates"])
        snapshot = LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
        self.assertNotIn("comparison_changes", snapshot["metrics"])
        self.assertNotIn("summary_text", snapshot)


# ----------------------------------------------------------------------
# 23. Prompt 508 behavior intact
# ----------------------------------------------------------------------
class TestPrompt508Intact(Prompt517TestCase):

    def test_508_snapshot_shape_and_behavior_are_unchanged(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory(max_snapshots=2)
        first = history.record_statistics(_stats(accepted=2, irrelevant=1))
        self.assertEqual(list(first.keys()), [
            "snapshot_id", "sequence", "validation_status", "validation_errors",
            "total_evaluations", "accepted_count", "rejected_count", "no_candidate_count",
            "acceptance_rate", "rejection_rate", "dominant_rejection_reason"])
        history.record_statistics(_stats(accepted=1))
        history.record_statistics(_stats(irrelevant=3))
        self.assertEqual([s["sequence"] for s in history.get_all()], [2, 3])
        self.assertEqual(history.get_latest()["sequence"], 3)
        self.assertEqual([s["sequence"] for s in history.get_recent(1)], [3])
        self.assertEqual(len(history), 2)
        self.assertEqual(history.compare_latest()["valid"], True)

    def test_508_record_still_isolates_its_inputs(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        analysis_stats = _stats(accepted=1)
        history.record_statistics(analysis_stats)
        retrieved = history.get_latest()
        retrieved["total_evaluations"] = 99
        self.assertEqual(history.get_latest()["total_evaluations"], 1)

    def test_508_history_is_still_recognised_by_the_report_code_but_the_new_one_is_not(self):
        analysis = _history([{"accepted": 1}])
        filtered_history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        filtered_history.record_filtered_summary(_filtered(["rates"]))
        self.assertTrue(isinstance(analysis, LearnedKnowledgeDiagnosticSnapshotHistory))
        self.assertFalse(isinstance(filtered_history, LearnedKnowledgeDiagnosticSnapshotHistory))
        self.assertEqual(report(snapshots=analysis)["snapshots"]["count"], 1)
        # a filtered-summary history can never masquerade as analysis snapshots
        self.assertEqual(report(snapshots=filtered_history)["snapshots"],
                         {"available": False, "count": 0, "latest": None})

    def test_508_operations_are_refused_by_the_filtered_history(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        with self.assertRaises(NotImplementedError):
            history.record({}, {})
        with self.assertRaises(NotImplementedError):
            history.record_statistics(_stats(accepted=1))
        with self.assertRaises(NotImplementedError):
            history.compare_sequences(1, 2)
        with self.assertRaises(NotImplementedError):
            history.compare_latest()
        self.assertEqual(len(history), 0)

    def test_two_kinds_of_history_do_not_share_state(self):
        analysis = LearnedKnowledgeDiagnosticSnapshotHistory()
        filtered_history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        analysis.record_statistics(_stats(accepted=1))
        filtered_history.record_filtered_summary(_filtered(["rates"]))
        self.assertEqual(len(analysis), 1)
        self.assertEqual(len(filtered_history), 1)
        self.assertNotIn("snapshot_kind", analysis.get_latest())


# ----------------------------------------------------------------------
# 24. Prompt 516 unchanged
# ----------------------------------------------------------------------
class TestPrompt516Unchanged(Prompt517TestCase):

    def test_filter_output_is_unchanged_by_snapshotting(self):
        summary = _summary()
        before = filt(summary, ["trend", "rates", "zz"])
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        history.record_filtered_summary(before)
        self.assertEqual(filt(summary, ["trend", "rates", "zz"]), before)
        self.assertEqual(list(before.keys()), [
            "requested_sections", "included_sections", "unavailable_sections", "unknown_sections",
            "summary_text", "report_validity", "validation_errors", "metrics"])

    def test_filtered_summary_is_not_mutated_by_recording(self):
        for filtered in (_filtered(_ALL_SECTIONS), filt(_invalid_summary(["e"]), ["rates", "zz"]),
                         filt(_partial_summary(), ["trend"]), _filtered([])):
            before = copy.deepcopy(filtered)
            LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(filtered)
            self.assertEqual(filtered, before)

    def test_snapshot_can_be_taken_of_every_516_outcome(self):
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        outcomes = [
            _filtered(["rates"]), _filtered(["zz"]), _filtered([]),
            filt(_partial_summary(), ["trend", "rates"]), filt(_invalid_summary(), ["trend"]),
        ]
        for filtered in outcomes:
            self.assertSnapshotShape(history.record_filtered_summary(filtered))
        self.assertEqual(len(history), len(outcomes))


# ----------------------------------------------------------------------
# 25. regression coverage for Prompts 500-516
# ----------------------------------------------------------------------
class TestRegression500To516(Prompt517TestCase):

    def test_source_diagnostic_objects_are_untouched(self):
        history, comparisons, built, validation = _pipeline(
            [{"accepted": 1}, {"accepted": 3}, {"irrelevant": 2}, {"low_reliability": 2}])
        trend_summary = trend(comparisons)
        summary = fmt(built, validation)
        filtered = filt(summary, _ALL_SECTIONS + ["zz"])
        before = [copy.deepcopy(x) for x in
                  (history.get_all(), comparisons, trend_summary, built, validation, summary, filtered)]
        store = LearnedKnowledgeFilteredSummarySnapshotHistory()
        store.record_filtered_summary(filtered)
        store.get_latest()
        store.get_all()
        after = (history.get_all(), comparisons, trend_summary, built, validation, summary, filtered)
        for was, now in zip(before, after):
            self.assertEqual(now, was)

    def test_earlier_pipeline_stages_still_agree(self):
        history, comparisons, built, validation = _pipeline()
        self.assertTrue(validation["valid"])
        self.assertEqual(validate(built, snapshots=history, comparisons=comparisons), validation)
        self.assertEqual(fmt(built, validation)["report_validity"], REPORT_VALIDITY_VALID)
        self.assertTrue(all(validate_comparison(c)["valid"] for c in comparisons))

    def test_snapshot_history_and_statistics_unaffected(self):
        stats = _stats(accepted=2, irrelevant=1)
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(stats)
        before_history, before_stats = history.get_all(), stats.summary()
        built = report(snapshots=history)
        LearnedKnowledgeFilteredSummarySnapshotHistory().record_filtered_summary(
            filt(fmt(built, validate(built, snapshots=history)), ["rates"]))
        self.assertEqual(history.get_all(), before_history)
        self.assertEqual(stats.summary(), before_stats)

    def test_snapshotting_is_not_wired_into_any_non_diagnostic_module(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in files:
                if not name.endswith(".py") or name == "learned_knowledge_statistics.py":
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    self.assertNotIn("LearnedKnowledgeFilteredSummarySnapshotHistory", handle.read(),
                                     os.path.join(folder, name))


if __name__ == "__main__":
    unittest.main()
