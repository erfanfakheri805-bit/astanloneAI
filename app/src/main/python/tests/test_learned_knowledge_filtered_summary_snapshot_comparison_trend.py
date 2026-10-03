"""
Tests for Prompt 520 - Filtered Diagnostic Snapshot Comparison Trend Summary.

`summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend()`
(learning/learned_knowledge_statistics.py) summarizes an ORDERED collection
of Prompt 518 filtered-snapshot comparisons, judging each with the Prompt
519 validator and reusing the Prompt 511 trend envelope and state
vocabulary. It is descriptive, deterministic and read-only.

Covers (numbers match the Prompt 520 test list):
    1 empty collection            2 one valid comparison
    3 two valid                   4 multiple valid
    5 all valid                   6 all invalid
    7 mixed valid / invalid       8 increasing numeric
    9 decreasing numeric          10 unchanged numeric
    11 insufficient numeric data  12 zero evaluations
    13-16 categorical unchanged / changed / appeared / disappeared
    17 categorical insufficient data
    18 different section sets     19 section appearing later
    20 section disappearing later 21 unavailable section
    22 invalid comparison source  23 chronological order preserved
    24 reversed chronology        25 no fabricated values
    26 deterministic              27 comparisons unchanged
    28 snapshots unchanged        29 no prediction/recommendation/score
    30 Prompt 511 trend behavior unchanged

Run directly:
    python -m unittest tests.test_learned_knowledge_filtered_summary_snapshot_comparison_trend -v
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
    TREND_INCREASED, TREND_DECREASED, TREND_INSUFFICIENT_DATA,
    CHANGE_UNCHANGED, CHANGE_CHANGED, CHANGE_BECAME_EMPTY, CHANGE_BECAME_AVAILABLE,
    AVAILABILITY_CONSISTENT, AVAILABILITY_INTERMITTENT, AVAILABILITY_ONLY_EARLIER,
    AVAILABILITY_ONLY_LATER, AVAILABILITY_UNAVAILABLE, AVAILABILITY_INVALID,
    COMPARISON_DIRECTION,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    format_learned_knowledge_diagnostic_summary as fmt,
    filter_learned_knowledge_diagnostic_summary as filt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
    summarize_learned_knowledge_filtered_summary_snapshot_comparison_trend as trend,
    summarize_learned_knowledge_diagnostic_snapshot_comparison_trend as trend511,
)

_ALL = ["evaluation_counts", "rates", "dominant_rejection_reason",
        "comparison_changes", "trend", "validation_statuses"]
_SMALL = ["evaluation_counts", "rates", "dominant_rejection_reason"]
_NUMERIC = ["total_evaluations", "accepted_count", "rejected_count", "no_candidate_count",
            "acceptance_rate", "rejection_rate"]


def _gtrace(status, reason):
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(status, reason))


_TRACES = {"accepted": _gtrace(STATUS_PASSED, REASON_OK),
           "irrelevant": _gtrace("REJECTED", REASON_NOT_RELEVANT),
           "low_reliability": _gtrace("REJECTED", REASON_INSUFFICIENT_RELIABILITY)}


def _stats(**counts):
    stats = LearnedKnowledgeDecisionStatistics()
    for name, count in counts.items():
        for _ in range(count):
            stats.record(_TRACES[name])
    return stats


def _summary(counts):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for step in ({"accepted": 1}, counts):
        history.record_statistics(_stats(**step))
    comparisons = [history.compare_sequences(1, 2)]
    built = report(snapshots=history, comparisons=comparisons)
    return fmt(built, validate(built, snapshots=history, comparisons=comparisons))


def _snapshots(specs):
    """Real Prompt 517 snapshots (sequences 1..n) from ONE history;
    `specs` is `[(sections, counts), ...]`."""
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    return [history.record_filtered_summary(filt(_summary(counts), sections))
            for sections, counts in specs]


def _chain(specs):
    snaps = _snapshots(specs)
    return snaps, [compare(snaps[i], snaps[i + 1]) for i in range(len(snaps) - 1)]


def _numeric_specs(totals, sections=_SMALL):
    return [(sections, {"accepted": n}) for n in totals]


_NO_FORBIDDEN = ("predict", "forecast", "recommend", "score", "rank", "grade", "rating",
                 "improv", "worsen", "health", "quality", "winner", "loser", "next_value")


def _all_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            for inner in _all_keys(item):
                yield inner
    elif isinstance(value, (list, tuple)):
        for item in value:
            for inner in _all_keys(item):
                yield inner


class EnvelopeTests(unittest.TestCase):
    def test_01_empty_collection(self):
        for empty in (None, [], ()):
            result = trend(empty)
            self.assertTrue(result["valid"])
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["direction"], COMPARISON_DIRECTION)
            self.assertEqual((result["total_comparisons"], result["eligible_count"],
                              result["ineligible_count"]), (0, 0, 0))
            self.assertEqual(result["chronological_range"], {"earlier": None, "later": None})
            self.assertEqual(result["validation_status"]["state"], TREND_INSUFFICIENT_DATA)
            for field in _NUMERIC:
                self.assertEqual(result["numeric"][field]["state"], TREND_INSUFFICIENT_DATA)
                self.assertIsNone(result["numeric"][field]["start"])
            self.assertIn("no_comparisons", result["unavailable"])
            for entry in result["section_availability"].values():
                self.assertEqual(entry["availability"], AVAILABILITY_UNAVAILABLE)
        self.assertFalse(trend(5)["valid"])
        self.assertEqual(trend("abc")["errors"], ["comparisons_not_a_sequence"])

    def test_02_one_valid_comparison(self):
        _, comps = _chain(_numeric_specs([1, 3]))
        result = trend(comps)
        self.assertEqual((result["total_comparisons"], result["eligible_count"]), (1, 1))
        entry = result["numeric"]["total_evaluations"]
        self.assertEqual((entry["state"], entry["start"], entry["end"], entry["delta"]),
                         (TREND_INCREASED, 1, 3, 2))
        self.assertEqual(result["chronological_range"]["earlier"]["sequence"], 1)
        self.assertEqual(result["chronological_range"]["later"]["sequence"], 2)

    def test_03_two_valid_comparisons(self):
        _, comps = _chain(_numeric_specs([1, 2, 5]))
        result = trend(comps)
        self.assertEqual(result["eligible_count"], 2)
        entry = result["numeric"]["total_evaluations"]
        self.assertEqual((entry["start"], entry["end"], entry["delta"]), (1, 5, 4))
        self.assertEqual(entry["available_in"], [0, 1])
        self.assertEqual(result["chronological_range"]["later"]["sequence"], 3)

    def test_04_05_multiple_all_valid(self):
        _, comps = _chain(_numeric_specs([1, 2, 3, 4, 5], _ALL))
        result = trend(comps)
        self.assertEqual((result["total_comparisons"], result["eligible_count"],
                          result["ineligible_count"]), (4, 4, 0))
        self.assertEqual(result["ineligible_comparisons"], [])
        self.assertEqual(result["validation_status"],
                         {"state": CHANGE_UNCHANGED, "start": "valid", "end": "valid"})
        self.assertEqual(result["numeric"]["total_evaluations"]["availability"], AVAILABILITY_CONSISTENT)
        self.assertEqual(result["unavailable"], [])

    def test_06_all_invalid(self):
        comps = [compare({"snapshot_id": "x"}, {"snapshot_id": "y"}), {}, None, "junk"]
        result = trend(comps)
        self.assertEqual((result["total_comparisons"], result["eligible_count"],
                          result["ineligible_count"]), (4, 0, 4))
        self.assertEqual([e["index"] for e in result["ineligible_comparisons"]], [0, 1, 2, 3])
        self.assertIn("source_snapshot_invalid:earlier", result["ineligible_comparisons"][0]["errors"])
        self.assertIn("no_eligible_comparisons", result["unavailable"])
        for field in _NUMERIC:
            self.assertEqual(result["numeric"][field]["state"], TREND_INSUFFICIENT_DATA)
        for entry in result["section_availability"].values():
            self.assertEqual(entry["availability"], AVAILABILITY_INVALID)
        self.assertEqual(result["validation_status"]["start"], "invalid")
        self.assertEqual(result["validation_status"]["end"], "invalid")

    def test_07_mixed_valid_and_invalid(self):
        _, comps = _chain(_numeric_specs([1, 2, 4]))
        mixed = [comps[0], {"valid": True}, comps[1]]
        result = trend(mixed)
        self.assertEqual((result["eligible_count"], result["ineligible_count"]), (2, 1))
        self.assertEqual(result["ineligible_comparisons"][0]["index"], 1)
        self.assertIn("missing_field:errors", result["ineligible_comparisons"][0]["errors"])
        entry = result["numeric"]["total_evaluations"]
        self.assertEqual((entry["start"], entry["end"]), (1, 4))
        self.assertEqual(entry["available_in"], [0, 2])  # input positions preserved
        self.assertEqual(result["validation_status"]["state"], CHANGE_UNCHANGED)

    def test_22_invalid_comparison_source(self):
        snaps, comps = _chain(_numeric_specs([1, 2, 3]))
        bad = compare(snaps[0], {"snapshot_id": "broken"})
        history = LearnedKnowledgeFilteredSummarySnapshotHistory()
        invalid_snapshot = history.record_filtered_summary(filt(_invalid_summary(), _ALL))
        own_invalid = compare(snaps[0], invalid_snapshot)
        self.assertTrue(own_invalid["valid"])
        result = trend([comps[0], bad, own_invalid])
        self.assertEqual(result["eligible_count"], 1)
        errors = {e["index"]: e["errors"] for e in result["ineligible_comparisons"]}
        self.assertIn("source_snapshot_invalid:later", errors[1])
        self.assertIn("source_snapshot_validation_status_invalid:later", errors[2])


def _invalid_summary():
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    history.record_statistics(_stats(accepted=1))
    built = copy.deepcopy(report(snapshots=history))
    built["structural_status"] = "unknown"
    return fmt(built, validate(built))


class NumericTests(unittest.TestCase):
    def test_08_increasing(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        entry = trend(comps)["numeric"]["total_evaluations"]
        self.assertEqual(entry["state"], TREND_INCREASED)
        self.assertEqual(entry["delta"], 2)

    def test_09_decreasing(self):
        _, comps = _chain(_numeric_specs([5, 4, 2]))
        entry = trend(comps)["numeric"]["total_evaluations"]
        self.assertEqual((entry["state"], entry["start"], entry["end"], entry["delta"]),
                         (TREND_DECREASED, 5, 2, -3))

    def test_10_unchanged(self):
        _, comps = _chain(_numeric_specs([3, 3, 3]))
        result = trend(comps)
        for field in ("total_evaluations", "accepted_count", "acceptance_rate"):
            self.assertEqual(result["numeric"][field]["state"], CHANGE_UNCHANGED)
        self.assertEqual(result["numeric"]["total_evaluations"]["delta"], 0)

    def test_08b_rates_and_counts_together(self):
        specs = [(_SMALL, {"accepted": 1}), (_SMALL, {"accepted": 1, "irrelevant": 1}),
                 (_SMALL, {"accepted": 1, "irrelevant": 3})]
        result = trend(_chain(specs)[1])
        self.assertEqual(result["numeric"]["acceptance_rate"]["state"], TREND_DECREASED)
        self.assertEqual(result["numeric"]["rejection_rate"]["state"], TREND_INCREASED)
        self.assertEqual(result["numeric"]["rejected_count"]["state"], TREND_INCREASED)
        self.assertEqual(result["numeric"]["no_candidate_count"]["state"], CHANGE_UNCHANGED)

    def test_11_insufficient_numeric_data(self):
        _, comps = _chain([(["trend"], {"accepted": 1}), (["trend"], {"accepted": 2})])
        result = trend(comps)
        for field in _NUMERIC:
            entry = result["numeric"][field]
            self.assertEqual(entry["state"], TREND_INSUFFICIENT_DATA)
            self.assertEqual((entry["start"], entry["end"], entry["delta"]), (None, None, None))
            self.assertEqual(entry["availability"], AVAILABILITY_UNAVAILABLE)
            self.assertEqual(entry["available_in"], [])
            self.assertIn("insufficient_data:%s" % field, result["unavailable"])

    def test_12_zero_evaluations(self):
        _, comps = _chain([(_SMALL, {}), (_SMALL, {}), (_SMALL, {})])
        result = trend(comps)
        self.assertEqual(result["eligible_count"], 2)
        entry = result["numeric"]["total_evaluations"]
        self.assertEqual((entry["state"], entry["start"], entry["end"], entry["delta"]),
                         (CHANGE_UNCHANGED, 0, 0, 0))
        self.assertEqual(result["numeric"]["acceptance_rate"]["state"], CHANGE_UNCHANGED)
        self.assertEqual(result["unavailable"][:0], [])
        self.assertEqual(result["categorical"]["dominant_rejection_reason"]["state"], CHANGE_UNCHANGED)


class CategoricalTests(unittest.TestCase):
    def _reason(self, first, second):
        return trend(_chain([(_SMALL, first), (_SMALL, second)])[1])["categorical"]["dominant_rejection_reason"]

    def test_13_unchanged(self):
        entry = self._reason({"irrelevant": 2}, {"irrelevant": 3})
        self.assertEqual(entry["state"], CHANGE_UNCHANGED)
        self.assertEqual(entry["observed_states"], [{"index": 0, "change": CHANGE_UNCHANGED}])

    def test_14_changed(self):
        entry = self._reason({"irrelevant": 2}, {"low_reliability": 2})
        self.assertEqual(entry["state"], CHANGE_CHANGED)
        self.assertEqual((entry["start"], entry["end"]),
                         ("rejected_irrelevant", "rejected_low_reliability"))

    def test_15_appeared(self):
        entry = self._reason({"accepted": 2}, {"irrelevant": 2})
        self.assertEqual(entry["state"], CHANGE_BECAME_AVAILABLE)
        self.assertEqual(entry["observed_states"][0]["change"], CHANGE_BECAME_AVAILABLE)

    def test_16_disappeared(self):
        entry = self._reason({"irrelevant": 2}, {"accepted": 2})
        self.assertEqual(entry["state"], CHANGE_BECAME_EMPTY)
        self.assertIsNone(entry["end"])

    def test_16b_observed_states_keep_each_comparison_distinction(self):
        specs = [(_SMALL, {"accepted": 1}), (_SMALL, {"irrelevant": 1}),
                 (_SMALL, {"low_reliability": 1}), (_SMALL, {"accepted": 1})]
        entry = trend(_chain(specs)[1])["categorical"]["dominant_rejection_reason"]
        self.assertEqual([s["change"] for s in entry["observed_states"]],
                         [CHANGE_BECAME_AVAILABLE, CHANGE_CHANGED, CHANGE_BECAME_EMPTY])
        self.assertEqual(entry["state"], CHANGE_UNCHANGED)  # first start None, last end None

    def test_17_categorical_insufficient_data(self):
        _, comps = _chain([(["rates"], {"accepted": 1}), (["rates"], {"accepted": 2})])
        result = trend(comps)
        for section in ("dominant_rejection_reason", "comparison_changes", "trend", "validation_statuses"):
            entry = result["categorical"][section]
            self.assertEqual(entry["state"], TREND_INSUFFICIENT_DATA)
            self.assertEqual(entry["observed_states"], [])
            self.assertIn("insufficient_data:%s" % section, result["unavailable"])
        self.assertIsNone(result["categorical"]["dominant_rejection_reason"]["start"])

    def test_composite_sections_equality_only(self):
        _, comps = _chain([(_ALL, {"accepted": 1}), (_ALL, {"accepted": 2}), (_ALL, {"accepted": 2})])
        result = trend(comps)
        for section in ("comparison_changes", "trend", "validation_statuses"):
            self.assertIn(result["categorical"][section]["state"], (CHANGE_UNCHANGED, CHANGE_CHANGED))
            self.assertNotIn("start", result["categorical"][section])
            self.assertEqual(result["categorical"][section]["availability"], AVAILABILITY_CONSISTENT)


class SectionAvailabilityTests(unittest.TestCase):
    def test_18_different_section_sets(self):
        specs = [(["evaluation_counts", "trend"], {"accepted": 1}),
                 (["rates", "trend", "dominant_rejection_reason"], {"accepted": 2}),
                 (["trend"], {"accepted": 3})]
        result = trend(_chain(specs)[1])
        self.assertEqual(result["eligible_count"], 2)
        avail = result["section_availability"]
        self.assertEqual(avail["trend"]["availability"], AVAILABILITY_CONSISTENT)
        self.assertEqual(avail["evaluation_counts"]["availability"], AVAILABILITY_UNAVAILABLE)
        self.assertEqual(avail["evaluation_counts"]["presence_counts"]["present_only_earlier"], 1)
        self.assertEqual(avail["rates"]["presence_counts"]["present_only_later"], 1)
        self.assertEqual(result["numeric"]["total_evaluations"]["state"], TREND_INSUFFICIENT_DATA)

    def test_19_section_appearing_later(self):
        specs = [(["rates"], {"accepted": 1}), (["rates"], {"accepted": 2}),
                 (["rates", "evaluation_counts"], {"accepted": 3}),
                 (["rates", "evaluation_counts"], {"accepted": 5})]
        result = trend(_chain(specs)[1])
        self.assertEqual(result["eligible_count"], 3)
        entry = result["numeric"]["total_evaluations"]
        self.assertEqual(entry["availability"], AVAILABILITY_ONLY_LATER)
        self.assertEqual(entry["available_in"], [2])
        self.assertEqual((entry["state"], entry["start"], entry["end"]), (TREND_INCREASED, 3, 5))
        self.assertEqual(result["section_availability"]["rates"]["availability"], AVAILABILITY_CONSISTENT)

    def test_20_section_disappearing_later(self):
        specs = [(["rates", "evaluation_counts"], {"accepted": 1}),
                 (["rates", "evaluation_counts"], {"accepted": 2}),
                 (["rates"], {"accepted": 3}), (["rates"], {"accepted": 4})]
        result = trend(_chain(specs)[1])
        entry = result["numeric"]["total_evaluations"]
        self.assertEqual(entry["availability"], AVAILABILITY_ONLY_EARLIER)
        self.assertEqual(entry["available_in"], [0])
        self.assertEqual((entry["start"], entry["end"]), (1, 2))  # only what was compared
        self.assertEqual(result["section_availability"]["evaluation_counts"]["availability"],
                         AVAILABILITY_ONLY_EARLIER)

    def test_intermittent_availability(self):
        both, one = ["rates", "evaluation_counts"], ["rates"]
        specs = [(both, {"accepted": 1}), (both, {"accepted": 2}), (one, {"accepted": 3}),
                 (both, {"accepted": 4}), (both, {"accepted": 6})]
        result = trend(_chain(specs)[1])
        entry = result["numeric"]["total_evaluations"]
        self.assertEqual(entry["availability"], AVAILABILITY_INTERMITTENT)
        self.assertEqual(entry["available_in"], [0, 3])
        self.assertEqual((entry["start"], entry["end"]), (1, 6))

    def test_21_unavailable_section(self):
        result = trend(_chain([(_SMALL, {"accepted": 1}), (_SMALL, {"accepted": 2})])[1])
        self.assertEqual(result["section_availability"]["trend"]["availability"], AVAILABILITY_UNAVAILABLE)
        self.assertEqual(result["section_availability"]["trend"]["presence_counts"]["unavailable_in_both"], 1)
        self.assertEqual(result["categorical"]["trend"]["state"], TREND_INSUFFICIENT_DATA)

    def test_25_no_fabricated_missing_values(self):
        specs = [(["rates"], {"accepted": 1}), (["rates"], {"accepted": 2}),
                 (["rates", "evaluation_counts"], {"accepted": 3})]
        result = trend(_chain(specs)[1])
        entry = result["numeric"]["total_evaluations"]
        # the only comparison touching evaluation_counts has it on one side
        # only, so nothing is compared and nothing is invented
        self.assertEqual(entry["available_in"], [])
        self.assertEqual(entry["state"], TREND_INSUFFICIENT_DATA)
        self.assertEqual((entry["start"], entry["end"], entry["delta"]), (None, None, None))
        self.assertEqual(result["section_availability"]["evaluation_counts"]["presence_counts"]
                         ["present_only_later"], 1)
        # a metric with no data anywhere has no invented value
        _, comps = _chain([(["trend"], {"accepted": 1}), (["trend"], {"accepted": 2})])
        for field in _NUMERIC:
            self.assertEqual(trend(comps)["numeric"][field]["delta"], None)
        # values reported are exactly values some comparison recorded
        real = _chain(_numeric_specs([1, 2, 4]))[1]
        entry = trend(real)["numeric"]["total_evaluations"]
        recorded = {c["numeric"]["total_evaluations"][role] for c in real for role in ("earlier", "later")}
        self.assertIn(entry["start"], recorded)
        self.assertIn(entry["end"], recorded)


class ChronologyTests(unittest.TestCase):
    def test_23_order_preserved(self):
        snaps, comps = _chain(_numeric_specs([1, 2, 3, 4]))
        original = list(comps)
        result = trend([comps[0], {"bad": 1}, comps[1], comps[2]])
        self.assertEqual(comps, original)
        self.assertEqual(result["numeric"]["total_evaluations"]["available_in"], [0, 2, 3])
        self.assertEqual(result["ineligible_comparisons"][0]["index"], 1)
        self.assertEqual(result["chronological_range"]["earlier"], {"snapshot_id": snaps[0]["snapshot_id"], "sequence": 1})
        self.assertEqual(result["chronological_range"]["later"]["sequence"], 4)
        self.assertTrue(result["chronology"]["ordered"])
        self.assertEqual(result["chronology"]["reversed"], [])

    def test_24_reversed_chronology_handled_safely(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        result = trend(list(reversed(comps)))
        self.assertFalse(result["chronology"]["ordered"])
        self.assertEqual(result["chronology"]["reversed"], [{"index": 1, "previous_index": 0}])
        self.assertEqual(result["eligible_count"], 2)
        # not silently corrected: no trend is reported from an untrusted order
        self.assertEqual(result["numeric"]["total_evaluations"]["state"], TREND_INSUFFICIENT_DATA)
        self.assertIn("chronology_not_ordered", result["unavailable"])
        self.assertEqual(result["numeric"]["total_evaluations"]["availability"], AVAILABILITY_CONSISTENT)
        self.assertEqual(result["chronological_range"]["earlier"]["sequence"], 2)  # as supplied

    def test_24b_a_reversed_comparison_is_ineligible(self):
        snaps, comps = _chain(_numeric_specs([1, 2]))
        reversed_comparison = compare(snaps[1], snaps[0])
        result = trend([reversed_comparison, comps[0]])
        self.assertEqual(result["ineligible_comparisons"][0]["errors"], ["reversed_ordering"])
        self.assertEqual(result["eligible_count"], 1)
        self.assertTrue(result["chronology"]["ordered"])

    def test_24c_overlapping_comparisons_from_same_baseline_are_ordered(self):
        snaps = _snapshots(_numeric_specs([1, 2, 4]))
        comps = [compare(snaps[0], snaps[1]), compare(snaps[0], snaps[2])]
        result = trend(comps)
        self.assertTrue(result["chronology"]["ordered"])
        self.assertEqual(result["numeric"]["total_evaluations"]["end"], 4)


class IsolationTests(unittest.TestCase):
    def test_26_deterministic(self):
        _, comps = _chain(_numeric_specs([1, 2, 3, 3]))
        mixed = [comps[0], {}, comps[1], comps[2]]
        results = [trend(mixed) for _ in range(5)]
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(trend(_chain(_numeric_specs([1, 2, 3, 3]))[1][:1]),
                         trend(_chain(_numeric_specs([1, 2, 3, 3]))[1][:1]))

    def test_27_source_comparisons_unchanged(self):
        _, comps = _chain(_numeric_specs([1, 2, 3]))
        mixed = comps + [{}, {"valid": False}]
        before = copy.deepcopy(mixed)
        holder = tuple(mixed)
        result = trend(mixed)
        trend(holder)
        self.assertEqual(mixed, before)
        result["numeric"]["total_evaluations"]["available_in"].append(99)
        result["chronological_range"]["earlier"]["sequence"] = 99
        self.assertEqual(mixed, before)
        self.assertNotEqual(trend(mixed)["numeric"]["total_evaluations"]["available_in"][-1], 99)

    def test_28_snapshots_unchanged(self):
        snaps, comps = _chain(_numeric_specs([1, 2, 3]))
        before = copy.deepcopy(snaps)
        trend(comps)
        self.assertEqual(snaps, before)

    def test_29_no_prediction_recommendation_or_score_fields(self):
        _, comps = _chain(_numeric_specs([1, 2, 3, 4]))
        for candidate in (comps, [], [{}], list(reversed(comps))):
            keys = set(_all_keys(trend(candidate)))
            for word in _NO_FORBIDDEN:
                self.assertFalse([k for k in keys if word in k.lower()], (word, keys))
        states = set()
        result = trend(comps)
        for entry in list(result["numeric"].values()) + list(result["categorical"].values()):
            states.add(entry["state"])
        self.assertLessEqual(states, {TREND_INCREASED, TREND_DECREASED, CHANGE_UNCHANGED,
                                      CHANGE_CHANGED, CHANGE_BECAME_AVAILABLE, CHANGE_BECAME_EMPTY,
                                      TREND_INSUFFICIENT_DATA})

    def test_result_shape(self):
        result = trend([])
        self.assertEqual(list(result), [
            "valid", "errors", "direction", "total_comparisons", "eligible_count",
            "ineligible_count", "ineligible_comparisons", "chronological_range", "chronology",
            "numeric", "categorical", "section_availability", "validation_status", "unavailable"])
        self.assertEqual(list(result["numeric"]), _NUMERIC)
        self.assertEqual(list(result["section_availability"]), _ALL)

    def test_never_raises_on_junk(self):
        for junk in ([1, "x", None, [], {}], [{"valid": True, "sections": 3}],
                     [{"valid": True, "numeric": None}], ({"valid": False},)):
            self.assertTrue(trend(junk)["valid"])


class Prompt511RegressionTests(unittest.TestCase):
    def test_30_prompt_511_trend_unchanged(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        for n in (1, 2, 4):
            history.record_statistics(_stats(accepted=n))
        comps = [history.compare_sequences(1, 2), history.compare_sequences(2, 3)]
        before = copy.deepcopy(comps)
        result = trend511(comps)
        self.assertEqual(comps, before)
        self.assertTrue(result["valid"])
        self.assertEqual((result["total_comparisons"], result["eligible_count"]), (2, 2))
        self.assertEqual(result["numeric"]["total_evaluations"],
                         {"state": TREND_INCREASED, "start": 1, "end": 4, "delta": 3})
        self.assertEqual(sorted(result), sorted([
            "valid", "errors", "direction", "total_comparisons", "eligible_count",
            "ineligible_count", "ineligible_comparisons", "chronological_range", "numeric",
            "dominant_rejection_reason", "validation_status"]))
        # the Prompt 509 comparisons are not eligible for the filtered trend
        self.assertEqual(trend(comps)["eligible_count"], 0)


if __name__ == "__main__":
    unittest.main()
