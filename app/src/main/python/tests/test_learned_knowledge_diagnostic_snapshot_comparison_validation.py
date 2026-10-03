"""
Tests for Prompt 510 - Validate Diagnostic Snapshot Comparisons.

`validate_learned_knowledge_diagnostic_snapshot_comparison()`
(learning/learned_knowledge_statistics.py) is a deterministic, read-only
structural/consistency check over the result of Prompt 509's
`compare_learned_knowledge_diagnostic_snapshots()`. It returns
`{"valid", "well_formed", "errors", "warnings"}`, never repairs or
regenerates anything, never mutates a comparison or snapshot, and
nothing reads its result to change behavior.

Run directly:
    python -m unittest tests.test_learned_knowledge_diagnostic_snapshot_comparison_validation -v
"""

import copy
import math
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.verified_correction_response_instruction import (
    VerifiedCorrectionResponseInstruction,
)
from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK, REASON_NOT_SELECTED, REASON_NOT_RELEVANT,
    REASON_INSUFFICIENT_RELIABILITY,
    DECISION_ACCEPTED, DECISION_REJECTED_IRRELEVANT, DECISION_REJECTED_LOW_RELIABILITY,
    LearnedKnowledgeGateResult,
    evaluate_learned_knowledge_gate, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    COMPARISON_DIRECTION,
    CHANGE_UNCHANGED, CHANGE_CHANGED, CHANGE_BECAME_EMPTY, CHANGE_BECAME_AVAILABLE,
    CHANGE_NOT_COMPARABLE,
    summarize_learned_knowledge_decisions,
    analyze_learned_knowledge_statistics,
    validate_learned_knowledge_statistics_analysis,
    build_learned_knowledge_analysis_summary,
    compare_learned_knowledge_diagnostic_snapshots as compare,
    validate_learned_knowledge_diagnostic_snapshot_comparison as validate,
)

from tests.test_pre_inference_readiness_guard import GuardCase, _core
from tests.test_local_inference_response_generation import TextRuntime

QUESTION = "Tell me about Rust"

NUMERIC_FIELDS = ["total_evaluations", "accepted_count", "rejected_count",
                  "no_candidate_count", "acceptance_rate", "rejection_rate"]
COUNT_FIELDS = NUMERIC_FIELDS[:4]
RATE_FIELDS = NUMERIC_FIELDS[4:]
VALID_TOP_LEVEL = [
    "valid", "errors", "direction", "earlier", "later", "chronological",
    "comparable", "identical", "changed_fields", "numeric",
    "dominant_rejection_reason", "validation_status",
]
INVALID_TOP_LEVEL = [
    "valid", "direction", "errors", "invalid_inputs", "earlier_errors",
    "later_errors", "earlier_validation_information", "later_validation_information",
]


def _instruction():
    return VerifiedCorrectionResponseInstruction(
        source_text="I has a dgo", corrected_text="I has a dog",
        matched_text="dgo", replacement_text="dog", match_count=1)


def _trace(status, reason, **numbers):
    return build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(status, reason, **numbers))


ACCEPTED = _trace(STATUS_PASSED, REASON_OK)
IRRELEVANT = _trace("REJECTED", REASON_NOT_RELEVANT)
LOW_RELIABILITY = _trace("REJECTED", REASON_INSUFFICIENT_RELIABILITY)
NO_CANDIDATE = _trace("REJECTED", REASON_NOT_SELECTED)


def _stats(accepted=0, irrelevant=0, low_reliability=0, no_candidate=0):
    stats = LearnedKnowledgeDecisionStatistics()
    for trace, count in ((ACCEPTED, accepted), (IRRELEVANT, irrelevant),
                         (LOW_RELIABILITY, low_reliability), (NO_CANDIDATE, no_candidate)):
        for _ in range(count):
            stats.record(trace)
    return stats


def _snapshot(sequence=1, **counts):
    """A real Prompt 508 snapshot (sequence adjustable for identity tests)."""
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for _ in range(sequence - 1):
        history.record_statistics(LearnedKnowledgeDecisionStatistics())
    return history.record_statistics(_stats(**counts))


def _status_invalid_snapshot(sequence=1):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for _ in range(sequence - 1):
        history.record_statistics(LearnedKnowledgeDecisionStatistics())
    return history.record({}, {"valid": False, "errors": ["boom"]})


def _comparison(earlier_counts=None, later_counts=None):
    earlier_counts = earlier_counts if earlier_counts is not None else {"accepted": 1, "irrelevant": 1}
    later_counts = later_counts if later_counts is not None else {"accepted": 3, "low_reliability": 1}
    return compare(_snapshot(1, **earlier_counts), _snapshot(2, **later_counts))


def _mutated(comparison, mutate):
    clone = copy.deepcopy(comparison)
    mutate(clone)
    return clone


class Case(GuardCase):

    def new_core(self):
        core, _tmp = _core(self)
        return core

    def teach(self, core, name="Rust", description="A systems programming language.",
              confidence=None):
        core.learning.teach(name, description, source="user", confidence=confidence)
        return core


# ----------------------------------------------------------------------
# 1. fully valid comparison
# ----------------------------------------------------------------------
class TestFullyValid(unittest.TestCase):

    def test_fully_valid_comparison(self):
        result = validate(_comparison())
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_result_shape(self):
        result = validate(_comparison())
        self.assertEqual(list(result.keys()), ["valid", "well_formed", "errors", "warnings"])
        self.assertIsInstance(result["errors"], list)
        self.assertIsInstance(result["warnings"], list)

    def test_valid_when_checked_against_the_source_snapshots(self):
        earlier, later = _snapshot(1, accepted=1, irrelevant=1), _snapshot(2, accepted=3)
        result = validate(compare(earlier, later), earlier, later)
        self.assertIs(result["valid"], True)

    def test_history_comparisons_validate(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        stats = LearnedKnowledgeDecisionStatistics()
        for trace in (ACCEPTED, LOW_RELIABILITY, IRRELEVANT, LOW_RELIABILITY, NO_CANDIDATE):
            stats.record(trace)
            history.record_statistics(stats)
        self.assertIs(validate(history.compare_latest())["valid"], True)
        self.assertIs(validate(history.compare_sequences(1, 5))["valid"], True)
        self.assertIs(validate(history.compare_sequences(5, 1))["valid"], True)

    def test_many_real_comparisons_all_validate(self):
        combos = [{}, {"accepted": 2}, {"irrelevant": 3}, {"low_reliability": 1, "no_candidate": 4},
                  {"accepted": 1, "irrelevant": 1, "low_reliability": 1, "no_candidate": 1}]
        for a in combos:
            for b in combos:
                result = validate(compare(_snapshot(1, **a), _snapshot(2, **b)))
                self.assertEqual(result["errors"], [], msg=(a, b))


# ----------------------------------------------------------------------
# 2. missing required fields
# ----------------------------------------------------------------------
class TestMissingFields(unittest.TestCase):

    def test_each_top_level_field_is_required(self):
        for field in VALID_TOP_LEVEL:
            bad = _mutated(_comparison(), lambda c, f=field: c.pop(f))
            result = validate(bad)
            self.assertIs(result["valid"], False, msg=field)
            self.assertIs(result["well_formed"], False, msg=field)
            self.assertIn("missing_field:%s" % field, result["errors"], msg=field)

    def test_each_numeric_field_is_required(self):
        for field in NUMERIC_FIELDS:
            bad = _mutated(_comparison(), lambda c, f=field: c["numeric"].pop(f))
            self.assertIn("missing_numeric_field:%s" % field, validate(bad)["errors"], msg=field)

    def test_each_numeric_entry_key_is_required(self):
        for field in NUMERIC_FIELDS:
            for key in ("earlier", "later", "delta", "changed"):
                bad = _mutated(_comparison(), lambda c, f=field, k=key: c["numeric"][f].pop(k))
                self.assertIn("missing_numeric_entry_field:%s.%s" % (field, key),
                              validate(bad)["errors"], msg=(field, key))

    def test_dominant_reason_and_status_sections_need_every_key(self):
        for section in ("dominant_rejection_reason", "validation_status"):
            for key in ("earlier", "later", "change", "changed"):
                bad = _mutated(_comparison(), lambda c, s=section, k=key: c[s].pop(k))
                result = validate(bad)
                self.assertIs(result["valid"], False, msg=(section, key))
                self.assertIn("invalid_%s_comparison" % section, result["errors"])

    def test_identity_needs_both_keys(self):
        for role in ("earlier", "later"):
            for key in ("snapshot_id", "sequence"):
                bad = _mutated(_comparison(), lambda c, r=role, k=key: c[r].pop(k))
                self.assertIn("invalid_%s_identity" % role, validate(bad)["errors"])

    def test_missing_valid_flag_and_bad_valid_flag(self):
        self.assertEqual(validate({})["errors"], ["missing_field:valid"])
        for bad in ("yes", 1, None, [], 0):
            self.assertEqual(validate({"valid": bad})["errors"], ["invalid_type:valid"], msg=repr(bad))

    def test_invalid_branch_fields_are_required(self):
        base = compare(None, _snapshot(2, accepted=1))
        self.assertEqual(list(base.keys()), INVALID_TOP_LEVEL)
        for field in INVALID_TOP_LEVEL[1:]:
            bad = _mutated(base, lambda c, f=field: c.pop(f))
            result = validate(bad)
            self.assertIn("missing_field:%s" % field, result["errors"], msg=field)
            self.assertIs(result["well_formed"], False, msg=field)

    def test_non_dict_comparison(self):
        for bad in (None, 0, "x", [], [1], (1,), 1.5, object()):
            result = validate(bad)
            self.assertEqual(result, {"valid": False, "well_formed": False,
                                      "errors": ["comparison_not_a_dict"], "warnings": []})


# ----------------------------------------------------------------------
# 3/4/5. numeric deltas
# ----------------------------------------------------------------------
class TestNumericDeltas(unittest.TestCase):

    def test_invalid_delta_types(self):
        for field in NUMERIC_FIELDS:
            for bad_delta in ("1", None, True, False, [], {}, object()):
                bad = _mutated(_comparison(), lambda c, f=field, d=bad_delta: c["numeric"][f].update(delta=d))
                result = validate(bad)
                self.assertIs(result["valid"], False, msg=(field, bad_delta))
                self.assertIn("invalid_delta_type:%s" % field, result["errors"], msg=(field, bad_delta))

    def test_count_delta_must_be_an_integer(self):
        for field in COUNT_FIELDS:
            entry = _comparison()["numeric"][field]
            bad = _mutated(_comparison(), lambda c, f=field, e=entry: c["numeric"][f].update(delta=float(e["delta"])))
            self.assertIn("invalid_delta_type:%s" % field, validate(bad)["errors"], msg=field)

    def test_non_finite_deltas(self):
        for field in NUMERIC_FIELDS:
            for bad_delta in (float("nan"), float("inf"), float("-inf")):
                bad = _mutated(_comparison(), lambda c, f=field, d=bad_delta: c["numeric"][f].update(delta=d))
                result = validate(bad)
                self.assertIs(result["valid"], False, msg=(field, bad_delta))
                self.assertIn("non_finite_delta:%s" % field, result["errors"], msg=(field, bad_delta))

    def test_non_finite_values(self):
        for field in RATE_FIELDS:
            for role in ("earlier", "later"):
                for bad_value in (float("nan"), float("inf")):
                    bad = _mutated(_comparison(), lambda c, f=field, r=role, v=bad_value: c["numeric"][f].update({r: v}))
                    result = validate(bad)
                    self.assertIn("non_finite_value:%s.%s" % (field, role), result["errors"])
                    self.assertIs(result["valid"], False)

    def test_invalid_value_types(self):
        for field in NUMERIC_FIELDS:
            bad = _mutated(_comparison(), lambda c, f=field: c["numeric"][f].update({"later": "3"}))
            self.assertIn("invalid_value_type:%s.later" % field, validate(bad)["errors"])
        bad = _mutated(_comparison(), lambda c: c["numeric"]["accepted_count"].update({"earlier": 1.5}))
        self.assertIn("invalid_value_type:accepted_count.earlier", validate(bad)["errors"])
        bad = _mutated(_comparison(), lambda c: c["numeric"]["accepted_count"].update({"earlier": True}))
        self.assertIn("invalid_value_type:accepted_count.earlier", validate(bad)["errors"])

    def test_incorrect_delta_calculation(self):
        for field in COUNT_FIELDS:
            good = _comparison()["numeric"][field]["delta"]
            for wrong in (good + 1, good - 1, -good if good else 7):
                bad = _mutated(_comparison(), lambda c, f=field, d=wrong: c["numeric"][f].update(delta=d))
                self.assertIn("incorrect_delta:%s" % field, validate(bad)["errors"], msg=(field, wrong))
        for field in RATE_FIELDS:
            good = _comparison()["numeric"][field]["delta"]
            bad = _mutated(_comparison(), lambda c, f=field, d=good + 0.1: c["numeric"][f].update(delta=d))
            self.assertIn("incorrect_delta:%s" % field, validate(bad)["errors"], msg=field)

    def test_delta_with_reversed_direction_is_detected(self):
        """A delta computed as earlier - later is wrong."""
        checked = []
        for field in NUMERIC_FIELDS:
            entry = _comparison()["numeric"][field]
            if entry["delta"] == 0:      # earlier - later == later - earlier, nothing to detect
                continue
            checked.append(field)
            bad = _mutated(_comparison(), lambda c, f=field, e=entry: c["numeric"][f].update(delta=e["earlier"] - e["later"]))
            self.assertIn("incorrect_delta:%s" % field, validate(bad)["errors"], msg=field)
        self.assertGreaterEqual(len(checked), 4)

    def test_delta_uses_later_minus_earlier(self):
        result = _comparison()
        for field in NUMERIC_FIELDS:
            entry = result["numeric"][field]
            self.assertTrue(math.isclose(entry["delta"], entry["later"] - entry["earlier"]))
        self.assertEqual(validate(result)["errors"], [])

    def test_delta_within_float_tolerance_is_accepted(self):
        good = _comparison()
        for field in RATE_FIELDS:
            nudged = _mutated(good, lambda c, f=field: c["numeric"][f].update(
                delta=c["numeric"][f]["delta"] + 1e-12))
            self.assertEqual(validate(nudged)["errors"], [], msg=field)

    def test_changed_flag_must_be_a_bool_and_agree(self):
        for field in NUMERIC_FIELDS:
            bad = _mutated(_comparison(), lambda c, f=field: c["numeric"][f].update(changed="yes"))
            self.assertIn("invalid_changed_flag:%s" % field, validate(bad)["errors"])
            bad = _mutated(_comparison(), lambda c, f=field: c["numeric"][f].update(changed=not c["numeric"][f]["changed"]))
            self.assertIn("inconsistent_changed:%s" % field, validate(bad)["errors"])

    def test_numeric_section_must_be_a_dict_of_dicts(self):
        self.assertIn("invalid_numeric", validate(_mutated(_comparison(), lambda c: c.update(numeric=[])))["errors"])
        self.assertIn("invalid_numeric_entry:accepted_count",
                      validate(_mutated(_comparison(), lambda c: c["numeric"].update(accepted_count=5)))["errors"])

    def test_values_that_fail_the_prompt_506_analysis_rules_are_reported(self):
        # a rate above 1.0 with a matching delta is still an invalid analysis value
        def mutate(c):
            entry = c["numeric"]["acceptance_rate"]
            entry["later"] = 5.0
            entry["delta"] = 5.0 - entry["earlier"]
        result = validate(_mutated(_comparison(), mutate))
        self.assertIs(result["valid"], False)
        self.assertIn("later_analysis:rate_above_valid_range:acceptance_rate", result["errors"])

    def test_counts_exceeding_total_reported_via_prompt_506_rules(self):
        def mutate(c):
            entry = c["numeric"]["accepted_count"]
            entry["later"] = 99
            entry["delta"] = 99 - entry["earlier"]
        result = validate(_mutated(_comparison(), mutate))
        self.assertIn("later_analysis:counts_exceed_total_evaluations", result["errors"])


# ----------------------------------------------------------------------
# 6. categorical states
# ----------------------------------------------------------------------
class TestCategoricalStates(unittest.TestCase):

    def test_invalid_dominant_reason_state(self):
        for bad_state in ("improved", "", None, 1, "UNCHANGED", ["changed"]):
            bad = _mutated(_comparison(), lambda c, s=bad_state: c["dominant_rejection_reason"].update(change=s))
            result = validate(bad)
            self.assertIs(result["valid"], False, msg=repr(bad_state))
            self.assertIn("invalid_dominant_rejection_reason_state", result["errors"], msg=repr(bad_state))

    def test_only_prompt_509_states_are_accepted_for_the_dominant_reason(self):
        for state in (CHANGE_UNCHANGED, CHANGE_CHANGED, CHANGE_BECAME_EMPTY,
                      CHANGE_BECAME_AVAILABLE, CHANGE_NOT_COMPARABLE):
            bad = _mutated(_comparison(), lambda c, s=state: c["dominant_rejection_reason"].update(change=s))
            errors = validate(bad)["errors"]
            self.assertNotIn("invalid_dominant_rejection_reason_state", errors, msg=state)

    def test_invalid_validation_status_state(self):
        for bad_state in ("improved", "", None, 1, CHANGE_BECAME_EMPTY, CHANGE_BECAME_AVAILABLE,
                          CHANGE_NOT_COMPARABLE):
            bad = _mutated(_comparison(), lambda c, s=bad_state: c["validation_status"].update(change=s))
            self.assertIn("invalid_validation_status_state", validate(bad)["errors"], msg=repr(bad_state))

    def test_invalid_validation_status_values(self):
        for role in ("earlier", "later"):
            for bad_value in ("maybe", None, 1, ""):
                bad = _mutated(_comparison(), lambda c, r=role, v=bad_value: c["validation_status"].update({r: v}))
                self.assertIn("invalid_validation_status_value:%s" % role, validate(bad)["errors"])

    def test_invalid_dominant_reason_values(self):
        for role in ("earlier", "later"):
            bad = _mutated(_comparison(), lambda c, r=role: c["dominant_rejection_reason"].update({r: "made_up"}))
            self.assertIn("invalid_dominant_rejection_reason_value:%s" % role, validate(bad)["errors"])
            bad = _mutated(_comparison(), lambda c, r=role: c["dominant_rejection_reason"].update({r: 5}))
            self.assertIn("invalid_dominant_rejection_reason_value:%s" % role, validate(bad)["errors"])

    def test_invalid_changed_flags(self):
        bad = _mutated(_comparison(), lambda c: c["dominant_rejection_reason"].update(changed="yes"))
        self.assertIn("invalid_dominant_rejection_reason_changed_flag", validate(bad)["errors"])
        bad = _mutated(_comparison(), lambda c: c["validation_status"].update(changed=0))
        self.assertIn("invalid_validation_status_changed_flag", validate(bad)["errors"])

    def test_invalid_direction(self):
        for bad_direction in ("earlier_minus_later", "", None, 3):
            bad = _mutated(_comparison(), lambda c, d=bad_direction: c.update(direction=d))
            self.assertIn("invalid_direction", validate(bad)["errors"], msg=repr(bad_direction))
        bad = _mutated(compare(None, None), lambda c: c.update(direction="earlier_minus_later"))
        self.assertIn("invalid_direction", validate(bad)["errors"])

    def test_invalid_flags(self):
        for field, code in (("comparable", "invalid_comparable"), ("identical", "invalid_identical"),
                            ("chronological", "invalid_chronological")):
            bad = _mutated(_comparison(), lambda c, f=field: c.update({f: "true"}))
            self.assertIn(code, validate(bad)["errors"], msg=field)

    def test_invalid_changed_fields(self):
        for bad_value in (None, "total_evaluations", [1], ["a", None]):
            bad = _mutated(_comparison(), lambda c, v=bad_value: c.update(changed_fields=v))
            self.assertIn("invalid_changed_fields", validate(bad)["errors"], msg=repr(bad_value))

    def test_errors_field_of_a_valid_comparison_must_be_empty(self):
        for bad_value in (["x"], None, "", 0):
            bad = _mutated(_comparison(), lambda c, v=bad_value: c.update(errors=v))
            self.assertIn("invalid_errors_for_valid_comparison", validate(bad)["errors"])

    def test_invalid_identities(self):
        for role in ("earlier", "later"):
            for bad_identity in (None, "id", {"snapshot_id": "", "sequence": 1},
                                 {"snapshot_id": "x", "sequence": 0},
                                 {"snapshot_id": "x", "sequence": True},
                                 {"snapshot_id": "x", "sequence": 1, "extra": 1},
                                 {"snapshot_id": 5, "sequence": 1}):
                bad = _mutated(_comparison(), lambda c, r=role, i=bad_identity: c.update({r: i}))
                self.assertIn("invalid_%s_identity" % role, validate(bad)["errors"], msg=(role, bad_identity))


# ----------------------------------------------------------------------
# 7/8. invalid source snapshots
# ----------------------------------------------------------------------
class TestInvalidSources(unittest.TestCase):

    def test_invalid_earlier_source_snapshot(self):
        bad = _snapshot(1, accepted=1)
        del bad["accepted_count"]
        comparison = compare(bad, _snapshot(2, accepted=2))
        result = validate(comparison)
        self.assertEqual(result, {"valid": False, "well_formed": True,
                                  "errors": ["source_snapshot_invalid:earlier"], "warnings": []})

    def test_invalid_later_source_snapshot(self):
        bad = _snapshot(2, accepted=2)
        bad["acceptance_rate"] = 9.0
        result = validate(compare(_snapshot(1, accepted=1), bad))
        self.assertEqual(result["errors"], ["source_snapshot_invalid:later"])
        self.assertIs(result["valid"], False)
        self.assertIs(result["well_formed"], True)

    def test_missing_source_snapshot(self):
        result = validate(compare(None, _snapshot(2, accepted=2)))
        self.assertEqual(result["errors"], ["source_snapshot_invalid:earlier"])
        result = validate(compare(_snapshot(1, accepted=2), None))
        self.assertEqual(result["errors"], ["source_snapshot_invalid:later"])

    def test_both_source_snapshots_invalid(self):
        result = validate(compare(None, "nonsense"))
        self.assertEqual(result, {"valid": False, "well_formed": True, "errors": [
            "source_snapshot_invalid:earlier", "source_snapshot_invalid:later"], "warnings": []})

    def test_empty_history_comparison(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        result = validate(history.compare_latest())
        self.assertIs(result["valid"], False)
        self.assertIs(result["well_formed"], True)
        self.assertEqual(result["errors"], ["source_snapshot_invalid:earlier",
                                            "source_snapshot_invalid:later"])

    def test_single_snapshot_history_comparison(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(LearnedKnowledgeDecisionStatistics())
        self.assertEqual(validate(history.compare_latest())["errors"], ["source_snapshot_invalid:earlier"])

    def test_status_invalid_source_snapshot_means_not_fully_valid(self):
        result = validate(compare(_snapshot(1, accepted=1), _status_invalid_snapshot(2)))
        self.assertEqual(result, {"valid": False, "well_formed": True, "errors": [
            "source_snapshot_validation_status_invalid:later"], "warnings": []})
        result = validate(compare(_status_invalid_snapshot(1), _snapshot(2, accepted=1)))
        self.assertEqual(result["errors"], ["source_snapshot_validation_status_invalid:earlier"])

    def test_two_status_invalid_source_snapshots(self):
        result = validate(compare(_status_invalid_snapshot(1), _status_invalid_snapshot(2)))
        self.assertIs(result["valid"], False)
        self.assertIs(result["well_formed"], True)
        self.assertEqual(result["errors"], ["source_snapshot_validation_status_invalid:earlier",
                                            "source_snapshot_validation_status_invalid:later"])

    def test_an_invalid_comparison_is_never_reported_fully_valid(self):
        for earlier, later in ((None, None), (None, _snapshot(2)), (_snapshot(1), None), ({}, {}),
                               (_status_invalid_snapshot(1), _snapshot(2))):
            self.assertIs(validate(compare(earlier, later))["valid"], False)

    def test_invalid_branch_structure_is_checked(self):
        base = compare(None, _snapshot(2, accepted=1))
        cases = {
            "inconsistent_invalid_inputs": lambda c: c.update(invalid_inputs=["later"]),
            "inconsistent_errors": lambda c: c.update(errors=["later_snapshot_invalid"]),
            "invalid_comparison_without_invalid_input": lambda c: c.update(
                earlier_errors=[], invalid_inputs=[], errors=[]),
            "invalid_earlier_errors": lambda c: c.update(earlier_errors="snapshot_missing"),
            "invalid_later_errors": lambda c: c.update(later_errors=[1]),
            "invalid_invalid_inputs": lambda c: c.update(invalid_inputs=["neither"]),
            "inconsistent_earlier_validation_information": lambda c: c.update(
                earlier_validation_information={"validation_status": None, "validation_errors": None}),
            "invalid_later_validation_information": lambda c: c.update(later_validation_information=None),
            "invalid_direction": lambda c: c.update(direction="x"),
        }
        for code, mutate in cases.items():
            result = validate(_mutated(base, mutate))
            self.assertIs(result["valid"], False, msg=code)
            self.assertIn(code, result["errors"], msg=code)
            self.assertIs(result["well_formed"], False, msg=code)

    def test_invalid_validation_information_shapes(self):
        comparison = compare(_mutated(_status_invalid_snapshot(1), lambda s: s.update(sequence=0)), None)
        self.assertEqual(validate(comparison)["errors"],
                         ["source_snapshot_invalid:earlier", "source_snapshot_invalid:later"])
        for bad_info in ({"validation_status": "??", "validation_errors": None},
                         {"validation_status": None, "validation_errors": "x"},
                         {"validation_status": None}, [], "x"):
            bad = _mutated(comparison, lambda c, i=bad_info: c.update(earlier_validation_information=i))
            self.assertIn("invalid_earlier_validation_information", validate(bad)["errors"], msg=repr(bad_info))


# ----------------------------------------------------------------------
# 9/10. identical snapshots, zero evaluations
# ----------------------------------------------------------------------
class TestIdenticalAndZero(unittest.TestCase):

    def test_identical_snapshots(self):
        snap = _snapshot(1, accepted=3, irrelevant=1, low_reliability=2)
        comparison = compare(snap, copy.deepcopy(snap))
        self.assertIs(comparison["identical"], True)
        self.assertEqual(validate(comparison)["errors"], [])

    def test_identical_flag_contradicting_the_data_is_detected(self):
        comparison = compare(_snapshot(1, accepted=1), _snapshot(2, accepted=1))
        self.assertIs(comparison["identical"], True)
        bad = _mutated(comparison, lambda c: c.update(identical=False))
        self.assertIn("inconsistent_identical", validate(bad)["errors"])
        changed = _comparison()
        bad = _mutated(changed, lambda c: c.update(identical=True))
        self.assertIn("inconsistent_identical", validate(bad)["errors"])

    def test_zero_evaluation_snapshots(self):
        comparison = compare(_snapshot(1), _snapshot(2))
        self.assertEqual(comparison["numeric"]["total_evaluations"]["earlier"], 0)
        result = validate(comparison)
        self.assertEqual(result, {"valid": True, "well_formed": True, "errors": [], "warnings": []})

    def test_zero_to_nonzero_and_back(self):
        self.assertEqual(validate(compare(_snapshot(1), _snapshot(2, accepted=2, irrelevant=1)))["errors"], [])
        self.assertEqual(validate(compare(_snapshot(1, accepted=2, irrelevant=1), _snapshot(2)))["errors"], [])

    def test_empty_snapshot_values_are_not_invented(self):
        # a status-invalid ("empty") snapshot carries None values; a comparison claiming
        # numbers for it is inconsistent
        comparison = compare(_snapshot(1, accepted=1), _status_invalid_snapshot(2))
        bad = _mutated(comparison, lambda c: c["numeric"]["total_evaluations"].update({"later": 4}))
        self.assertIn("value_present_for_invalid_snapshot:total_evaluations.later", validate(bad)["errors"])
        bad = _mutated(comparison, lambda c: c["numeric"]["total_evaluations"].update(delta=3))
        self.assertIn("delta_present_when_not_comparable:total_evaluations", validate(bad)["errors"])
        bad = _mutated(comparison, lambda c: c["numeric"]["accepted_count"].update(changed=True))
        self.assertIn("changed_present_when_not_comparable:accepted_count", validate(bad)["errors"])


# ----------------------------------------------------------------------
# 11/12/13. dominant rejection reason cases
# ----------------------------------------------------------------------
class TestDominantReasonCases(unittest.TestCase):

    def test_appearing(self):
        comparison = compare(_snapshot(1, accepted=2), _snapshot(2, accepted=2, irrelevant=1))
        self.assertEqual(comparison["dominant_rejection_reason"]["change"], CHANGE_BECAME_AVAILABLE)
        self.assertEqual(validate(comparison)["errors"], [])

    def test_disappearing(self):
        comparison = compare(_snapshot(1, accepted=2, irrelevant=1), _snapshot(2, accepted=2))
        self.assertEqual(comparison["dominant_rejection_reason"]["change"], CHANGE_BECAME_EMPTY)
        self.assertEqual(validate(comparison)["errors"], [])

    def test_changing(self):
        comparison = compare(_snapshot(1, irrelevant=2), _snapshot(2, low_reliability=2))
        self.assertEqual(comparison["dominant_rejection_reason"]["change"], CHANGE_CHANGED)
        self.assertEqual(validate(comparison)["errors"], [])

    def test_unchanged(self):
        comparison = compare(_snapshot(1, low_reliability=2), _snapshot(2, low_reliability=3))
        self.assertEqual(comparison["dominant_rejection_reason"]["change"], CHANGE_UNCHANGED)
        self.assertEqual(validate(comparison)["errors"], [])

    def test_no_reason_on_either_side(self):
        comparison = compare(_snapshot(1, accepted=1), _snapshot(2, accepted=2))
        self.assertEqual(validate(comparison)["errors"], [])

    def test_every_wrong_state_for_each_scenario_is_detected(self):
        scenarios = {
            CHANGE_BECAME_AVAILABLE: compare(_snapshot(1, accepted=2), _snapshot(2, irrelevant=1)),
            CHANGE_BECAME_EMPTY: compare(_snapshot(1, irrelevant=1), _snapshot(2, accepted=2)),
            CHANGE_CHANGED: compare(_snapshot(1, irrelevant=2), _snapshot(2, low_reliability=2)),
            CHANGE_UNCHANGED: compare(_snapshot(1, irrelevant=2), _snapshot(2, irrelevant=2)),
        }
        for real_state, comparison in scenarios.items():
            self.assertEqual(comparison["dominant_rejection_reason"]["change"], real_state)
            for wrong_state in (CHANGE_UNCHANGED, CHANGE_CHANGED, CHANGE_BECAME_EMPTY,
                                CHANGE_BECAME_AVAILABLE, CHANGE_NOT_COMPARABLE):
                if wrong_state == real_state:
                    continue
                bad = _mutated(comparison, lambda c, s=wrong_state: c["dominant_rejection_reason"].update(change=s))
                self.assertIn("inconsistent_dominant_rejection_reason_change", validate(bad)["errors"],
                              msg=(real_state, wrong_state))

    def test_wrong_changed_flag_for_the_dominant_reason(self):
        comparison = compare(_snapshot(1, irrelevant=2), _snapshot(2, low_reliability=2))
        for wrong in (False, None):
            bad = _mutated(comparison, lambda c, w=wrong: c["dominant_rejection_reason"].update(changed=w))
            self.assertIn("inconsistent_dominant_rejection_reason_change", validate(bad)["errors"])

    def test_reported_reason_values_disagreeing_with_their_state(self):
        comparison = compare(_snapshot(1, irrelevant=2), _snapshot(2, low_reliability=2))
        bad = _mutated(comparison, lambda c: c["dominant_rejection_reason"].update(later=DECISION_REJECTED_IRRELEVANT))
        self.assertIn("inconsistent_dominant_rejection_reason_change", validate(bad)["errors"])

    def test_reason_present_for_a_status_invalid_snapshot_is_detected(self):
        comparison = compare(_snapshot(1, irrelevant=1), _status_invalid_snapshot(2))
        bad = _mutated(comparison, lambda c: c["dominant_rejection_reason"].update(later=DECISION_REJECTED_IRRELEVANT))
        self.assertIn("value_present_for_invalid_snapshot:dominant_rejection_reason.later",
                      validate(bad)["errors"])


# ----------------------------------------------------------------------
# 14/15. validation status
# ----------------------------------------------------------------------
class TestValidationStatusCases(unittest.TestCase):

    def test_unchanged_status(self):
        comparison = _comparison()
        self.assertEqual(comparison["validation_status"]["change"], CHANGE_UNCHANGED)
        self.assertEqual(validate(comparison)["errors"], [])

    def test_changed_status_is_well_formed_but_not_fully_valid(self):
        comparison = compare(_snapshot(1, accepted=1), _status_invalid_snapshot(2))
        self.assertEqual(comparison["validation_status"]["change"], CHANGE_CHANGED)
        result = validate(comparison)
        self.assertIs(result["well_formed"], True)
        self.assertIs(result["valid"], False)
        self.assertEqual(result["errors"], ["source_snapshot_validation_status_invalid:later"])

    def test_status_change_in_either_direction(self):
        for earlier, later in ((_snapshot(1), _status_invalid_snapshot(2)),
                               (_status_invalid_snapshot(1), _snapshot(2))):
            result = validate(compare(earlier, later))
            self.assertIs(result["well_formed"], True)

    def test_wrong_status_change_state_and_flag_are_detected(self):
        comparison = _comparison()
        bad = _mutated(comparison, lambda c: c["validation_status"].update(change=CHANGE_CHANGED, changed=True))
        self.assertIn("inconsistent_validation_status_change", validate(bad)["errors"])
        bad = _mutated(comparison, lambda c: c["validation_status"].update(changed=True))
        self.assertIn("inconsistent_validation_status_change", validate(bad)["errors"])
        changed = compare(_snapshot(1, accepted=1), _status_invalid_snapshot(2))
        bad = _mutated(changed, lambda c: c["validation_status"].update(change=CHANGE_UNCHANGED, changed=False))
        self.assertIn("inconsistent_validation_status_change", validate(bad)["errors"])

    def test_comparable_flag_must_match_the_statuses(self):
        bad = _mutated(_comparison(), lambda c: c.update(comparable=False))
        self.assertIn("inconsistent_comparable", validate(bad)["errors"])
        changed = compare(_snapshot(1, accepted=1), _status_invalid_snapshot(2))
        bad = _mutated(changed, lambda c: c.update(comparable=True))
        self.assertIn("inconsistent_comparable", validate(bad)["errors"])


# ----------------------------------------------------------------------
# 16. internal inconsistency detection
# ----------------------------------------------------------------------
class TestInternalInconsistencies(unittest.TestCase):

    def test_changed_fields_must_match_what_changed(self):
        comparison = _comparison()
        self.assertGreater(len(comparison["changed_fields"]), 1)
        cases = (
            lambda c: c["changed_fields"].pop(),
            lambda c: c["changed_fields"].append("validation_status"),
            lambda c: c["changed_fields"].reverse(),
            lambda c: c.update(changed_fields=[]),
            lambda c: c["changed_fields"].append("total_evaluations"),
        )
        for mutate in cases:
            bad = _mutated(comparison, mutate)
            self.assertIn("inconsistent_changed_fields", validate(bad)["errors"])

    def test_chronological_must_match_sequences(self):
        comparison = _comparison()
        self.assertIs(comparison["chronological"], True)
        bad = _mutated(comparison, lambda c: c.update(chronological=False))
        self.assertIn("inconsistent_chronological", validate(bad)["errors"])
        reversed_comparison = compare(_snapshot(2, accepted=1), _snapshot(1, accepted=2))
        self.assertIs(reversed_comparison["chronological"], False)
        self.assertEqual(validate(reversed_comparison)["errors"], [])
        bad = _mutated(reversed_comparison, lambda c: c.update(chronological=True))
        self.assertIn("inconsistent_chronological", validate(bad)["errors"])

    def test_earlier_and_later_values_swapped_is_detected(self):
        def swap(c):
            entry = c["numeric"]["accepted_count"]
            entry["earlier"], entry["later"] = entry["later"], entry["earlier"]
        bad = _mutated(_comparison(), swap)
        self.assertIn("incorrect_delta:accepted_count", validate(bad)["errors"])

    def test_values_disagreeing_with_the_real_source_snapshots(self):
        earlier, later = _snapshot(1, accepted=1, irrelevant=1), _snapshot(2, accepted=3, low_reliability=1)
        comparison = compare(earlier, later)
        # self-consistent but not what the snapshots say
        def forge(c):
            entry = c["numeric"]["accepted_count"]
            entry["later"] = entry["later"] + 1
            entry["delta"] = entry["delta"] + 1
            c["numeric"]["total_evaluations"]["later"] += 1
            c["numeric"]["total_evaluations"]["delta"] += 1
        forged = _mutated(comparison, forge)
        self.assertNotIn("incorrect_delta:accepted_count", validate(forged)["errors"])
        result = validate(forged, earlier, later)
        self.assertIn("source_mismatch:later:accepted_count", result["errors"])
        self.assertIn("source_mismatch:later:total_evaluations", result["errors"])
        self.assertIs(result["valid"], False)

    def test_source_cross_check_identity_reason_and_status(self):
        earlier, later = _snapshot(1, irrelevant=2), _snapshot(2, low_reliability=2)
        comparison = compare(earlier, later)
        bad = _mutated(comparison, lambda c: c["later"].update(snapshot_id="other"))
        self.assertIn("source_mismatch:later:identity", validate(bad, earlier, later)["errors"])
        bad = _mutated(comparison, lambda c: c["dominant_rejection_reason"].update(earlier=DECISION_REJECTED_LOW_RELIABILITY))
        self.assertIn("source_mismatch:earlier:dominant_rejection_reason", validate(bad, earlier, later)["errors"])

    def test_comparison_claims_valid_but_source_is_invalid(self):
        earlier, later = _snapshot(1, accepted=1), _snapshot(2, accepted=2)
        comparison = compare(earlier, later)
        broken = copy.deepcopy(earlier)
        del broken["accepted_count"]
        self.assertIn("comparison_valid_but_source_invalid:earlier",
                      validate(comparison, broken, later)["errors"])
        self.assertIn("comparison_valid_but_source_invalid:later",
                      validate(comparison, earlier, None)["errors"])

    def test_invalid_comparison_source_errors_cross_check(self):
        good = _snapshot(2, accepted=1)
        comparison = compare(None, good)
        self.assertEqual(validate(comparison, None, good)["errors"], ["source_snapshot_invalid:earlier"])
        # the caller's earlier snapshot is actually fine, so the comparison's report is wrong
        result = validate(comparison, _snapshot(1, accepted=1), good)
        self.assertIn("source_errors_mismatch:earlier", result["errors"])

    def test_multiple_problems_are_all_reported_in_a_fixed_order(self):
        def mutate(c):
            c["numeric"]["accepted_count"]["delta"] = 99
            c["numeric"]["rejected_count"]["changed"] = "no"
            c["direction"] = "x"
            c["identical"] = True
        result = validate(_mutated(_comparison(), mutate))
        for code in ("invalid_direction", "incorrect_delta:accepted_count",
                     "invalid_changed_flag:rejected_count", "inconsistent_identical"):
            self.assertIn(code, result["errors"])
        self.assertEqual(result["errors"], validate(_mutated(_comparison(), mutate))["errors"])
        self.assertLess(result["errors"].index("invalid_direction"),
                        result["errors"].index("incorrect_delta:accepted_count"))

    def test_a_bad_field_does_not_cascade_into_misleading_extra_errors(self):
        bad = _mutated(_comparison(), lambda c: c["numeric"]["accepted_count"].update(delta="x"))
        self.assertEqual(validate(bad)["errors"], ["invalid_delta_type:accepted_count"])
        bad = _mutated(_comparison(), lambda c: c["validation_status"].update(change="weird"))
        self.assertEqual(validate(bad)["errors"], ["invalid_validation_status_state"])


# ----------------------------------------------------------------------
# 17/18. determinism and purity
# ----------------------------------------------------------------------
class TestDeterminismAndPurity(unittest.TestCase):

    def test_deterministic_output(self):
        comparison = _comparison()
        self.assertEqual(validate(comparison), validate(comparison))
        self.assertEqual(validate(comparison), validate(copy.deepcopy(comparison)))
        bad = _mutated(comparison, lambda c: c["numeric"]["accepted_count"].update(delta=99))
        self.assertEqual(validate(bad), validate(copy.deepcopy(bad)))

    def test_output_is_independent_of_the_input(self):
        bad = _mutated(_comparison(), lambda c: c["numeric"]["accepted_count"].update(delta=99))
        result = validate(bad)
        expected = copy.deepcopy(result)
        bad["numeric"]["accepted_count"]["delta"] = 0
        bad["changed_fields"].append("x")
        self.assertEqual(result, expected)

    def test_returned_lists_are_fresh_each_call(self):
        first, second = validate(_comparison()), validate(_comparison())
        first["errors"].append("x")
        first["warnings"].append("y")
        self.assertEqual(second["errors"], [])
        self.assertEqual(validate(_comparison())["warnings"], [])

    def test_does_not_mutate_a_valid_comparison(self):
        earlier, later = _snapshot(1, accepted=1), _snapshot(2, accepted=3)
        comparison = compare(earlier, later)
        before = (copy.deepcopy(comparison), copy.deepcopy(earlier), copy.deepcopy(later))
        validate(comparison)
        validate(comparison, earlier, later)
        self.assertEqual((comparison, earlier, later), before)

    def test_does_not_mutate_invalid_or_malformed_comparisons(self):
        earlier, later = _snapshot(1, accepted=1), _status_invalid_snapshot(2)
        candidates = [
            compare(None, later), compare(earlier, later), compare(None, None),
            _mutated(_comparison(), lambda c: c["numeric"]["accepted_count"].update(delta=float("nan"))),
            _mutated(_comparison(), lambda c: c.pop("numeric")),
            _mutated(_comparison(), lambda c: c.update(changed_fields="bad")),
        ]
        for candidate in candidates:
            before = copy.deepcopy(candidate)
            validate(candidate)
            validate(candidate, earlier, later)
            validate(candidate, None, None)
            # nan != nan, so compare through repr for the non-finite case
            self.assertEqual(repr(candidate), repr(before))

    def test_does_not_mutate_the_snapshot_history(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        stats = LearnedKnowledgeDecisionStatistics()
        for trace in (ACCEPTED, LOW_RELIABILITY, IRRELEVANT):
            stats.record(trace)
            history.record_statistics(stats)
        before = history.get_all()
        validate(history.compare_latest())
        validate(history.compare_sequences(1, 3))
        validate(history.compare_sequences(1, 99))
        self.assertEqual(history.get_all(), before)
        self.assertEqual(history.record_statistics(stats)["sequence"], 4)

    def test_never_raises_on_hostile_input(self):
        hostile = [
            None, {}, {"valid": True}, {"valid": False}, {"valid": True, "numeric": None},
            {"valid": True, "numeric": {"accepted_count": None}},
            {"valid": True, "validation_status": {"earlier": [], "later": {}, "change": [], "changed": []}},
            {"valid": True, "dominant_rejection_reason": {"earlier": [], "later": {}, "change": {}, "changed": []}},
            {"valid": False, "earlier_errors": None, "later_errors": {}, "invalid_inputs": 5},
            {"valid": True, "earlier": {"snapshot_id": [], "sequence": []}, "later": 3},
        ]
        for value in hostile:
            result = validate(value)
            self.assertIs(result["valid"], False)
            self.assertEqual(list(result.keys()), ["valid", "well_formed", "errors", "warnings"])


# ----------------------------------------------------------------------
# 19. Prompt 509 comparison behavior unchanged
# ----------------------------------------------------------------------
class TestPrompt509Unchanged(unittest.TestCase):

    def test_valid_comparison_shape_and_values_unchanged(self):
        comparison = compare(_snapshot(1, accepted=1, irrelevant=1), _snapshot(2, accepted=3, low_reliability=1))
        self.assertEqual(list(comparison.keys()), VALID_TOP_LEVEL)
        self.assertEqual(comparison["direction"], COMPARISON_DIRECTION)
        self.assertEqual(comparison["numeric"]["accepted_count"],
                         {"earlier": 1, "later": 3, "delta": 2, "changed": True})
        self.assertEqual(comparison["dominant_rejection_reason"]["change"], CHANGE_CHANGED)
        self.assertEqual(comparison["validation_status"]["change"], CHANGE_UNCHANGED)

    def test_invalid_comparison_shape_unchanged(self):
        comparison = compare(None, "x")
        self.assertEqual(list(comparison.keys()), INVALID_TOP_LEVEL)
        self.assertEqual(comparison["errors"], ["earlier_snapshot_invalid", "later_snapshot_invalid"])

    def test_validating_does_not_change_what_the_comparison_generates(self):
        earlier, later = _snapshot(1, accepted=1), _snapshot(2, accepted=3)
        before = compare(earlier, later)
        validate(before, earlier, later)
        self.assertEqual(compare(earlier, later), before)

    def test_history_compare_methods_unchanged_and_unaffected(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory()
        history.record_statistics(_stats(accepted=1))
        history.record_statistics(_stats(accepted=3))
        first = history.compare_latest()
        validate(first)
        self.assertEqual(history.compare_latest(), first)
        self.assertEqual(history.compare_sequences(1, 2), first)


# ----------------------------------------------------------------------
# 20. regression coverage for Prompts 500-509, and no effect elsewhere
# ----------------------------------------------------------------------
class TestValidatorDoesNotAffectOtherSystems(Case):

    def _request(self, with_validation):
        core = self.teach(self.new_core(), confidence=0.9)
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        if with_validation:
            history = core.learned_knowledge_diagnostic_snapshot_history
            history.record_statistics(core.learned_knowledge_decision_statistics)
            history.record_statistics(core.learned_knowledge_decision_statistics)
            validate(history.compare_latest())
        reply = core.process_input(QUESTION)
        if with_validation:
            core.learned_knowledge_diagnostic_snapshot_history.record_statistics(
                core.learned_knowledge_decision_statistics)
            validate(core.learned_knowledge_diagnostic_snapshot_history.compare_latest())
        return core, reply, runtime.requests[0]

    def test_does_not_affect_response_generation(self):
        control, control_reply, control_request = self._request(False)
        core, reply, request = self._request(True)
        self.assertEqual(reply, control_reply)
        self.assertEqual(repr(request.generation_context), repr(control_request.generation_context))
        self.assertEqual(repr(request.generation_request), repr(control_request.generation_request))
        self.assertEqual(core.last_learned_knowledge_gate_trace.to_dict(),
                         control.last_learned_knowledge_gate_trace.to_dict())
        self.assertEqual(core.learned_knowledge_decision_statistics.summary(),
                         control.learned_knowledge_decision_statistics.summary())

    def test_validation_not_in_the_generation_request(self):
        _core_, _reply, request = self._request(True)
        for forbidden in ("well_formed", "source_snapshot_invalid", "incorrect_delta"):
            self.assertNotIn(forbidden, repr(request.generation_context))
            self.assertNotIn(forbidden, repr(request.generation_request))

    def test_does_not_modify_learned_records_statistics_or_traces(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.knowledge.relate("Rust", "memory safety", "HAS", confidence=0.95)
        core.understand_language(QUESTION)
        stats = core.learned_knowledge_decision_statistics
        history = core.learned_knowledge_diagnostic_snapshot_history
        history.record_statistics(stats)
        core.understand_language(QUESTION)
        history.record_statistics(stats)
        knowledge_before = copy.deepcopy(core.knowledge.all())
        relationships_before = copy.deepcopy(core.knowledge.relationships_for("Rust"))
        summary_before = copy.deepcopy(stats.summary())
        analysis_before = copy.deepcopy(stats.analyze())
        text_before = copy.deepcopy(stats.summarize_analysis())
        trace_before = copy.deepcopy(core.last_learned_knowledge_gate_trace.to_dict())
        snapshots_before = history.get_all()

        result = validate(history.compare_latest())
        self.assertIs(result["valid"], True)

        self.assertEqual(core.knowledge.all(), knowledge_before)
        self.assertEqual(core.knowledge.relationships_for("Rust"), relationships_before)
        self.assertEqual(stats.summary(), summary_before)
        self.assertEqual(stats.analyze(), analysis_before)
        self.assertEqual(stats.summarize_analysis(), text_before)
        self.assertEqual(core.last_learned_knowledge_gate_trace.to_dict(), trace_before)
        self.assertEqual(history.get_all(), snapshots_before)

    def test_nothing_validates_or_records_automatically(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        core.process_input(QUESTION)
        self.assertEqual(core.learned_knowledge_diagnostic_snapshot_history.get_all(), [])


class TestEarlierPromptsStillUnchanged(Case):

    def generate(self, core):
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        understanding = core.understand_language(QUESTION)
        result = core.language_intelligence.generate_response(
            understanding, context=core.context, verified_correction_instruction=_instruction())
        return runtime.requests[0], result

    def test_prompt_500_correction_behavior_unchanged(self):
        request, result = self.generate(self.teach(self.new_core(), confidence=0.9))
        self.assertIs(result.used_verified_correction, True)
        self.assertEqual(request.generation_request.original_message, "I has a dog")

    def test_prompt_502_gate_still_never_raises(self):
        weird = {"status": "SELECTED", "record": {"name": None}}
        self.assertEqual(evaluate_learned_knowledge_gate(weird).status, "REJECTED")

    def test_prompt_503_trace_field_still_populated_as_before(self):
        core = self.teach(self.new_core(), confidence=0.9)
        core.understand_language(QUESTION)
        self.assertEqual(core.last_learned_knowledge_gate_trace.decision, DECISION_ACCEPTED)

    def test_prompt_504_statistics_summary_shape_unchanged(self):
        summary = _stats(accepted=1, irrelevant=1).summary()
        self.assertEqual(
            sorted(summary.keys()),
            sorted(["total_evaluations", "total_accepted", "total_rejected", "total_no_candidate",
                    "total_gate_errors", "rejection_reasons", "acceptance_rate", "rejection_rate"]))

    def test_prompt_505_analysis_shape_unchanged(self):
        analysis = analyze_learned_knowledge_statistics(_stats(accepted=1, irrelevant=1))
        self.assertEqual(
            sorted(analysis.keys()),
            sorted(["total_evaluations", "accepted_count", "rejected_count", "no_candidate_count",
                    "acceptance_rate", "rejection_rate", "dominant_rejection_reason"]))
        self.assertEqual(analysis["dominant_rejection_reason"], DECISION_REJECTED_IRRELEVANT)

    def test_prompt_506_validation_unchanged(self):
        analysis = analyze_learned_knowledge_statistics(_stats(accepted=1, irrelevant=1))
        self.assertEqual(validate_learned_knowledge_statistics_analysis(analysis),
                         {"valid": True, "errors": [], "warnings": []})
        analysis["accepted_count"] = -1
        self.assertIn("negative_count:accepted_count",
                      validate_learned_knowledge_statistics_analysis(analysis)["errors"])

    def test_prompt_507_summary_unchanged(self):
        stats = _stats(accepted=2, low_reliability=1, no_candidate=1)
        analysis = stats.analyze()
        summary = build_learned_knowledge_analysis_summary(
            analysis, validate_learned_knowledge_statistics_analysis(analysis))
        self.assertTrue(summary["valid"])
        self.assertIn("4 evaluation(s)", summary["text"])

    def test_prompt_508_snapshot_history_unchanged(self):
        history = LearnedKnowledgeDiagnosticSnapshotHistory(max_snapshots=2)
        stats = _stats(accepted=2)
        first = history.record_statistics(stats)
        self.assertEqual(first["snapshot_id"], "learned_knowledge_snapshot_000001")
        history.record_statistics(stats)
        history.record_statistics(stats)
        self.assertEqual([s["sequence"] for s in history.get_all()], [2, 3])
        self.assertEqual(history.get_latest()["sequence"], 3)
        self.assertEqual(LearnedKnowledgeDiagnosticSnapshotHistory().get_all(), [])

    def test_prompt_509_comparison_unchanged(self):
        result = compare(_snapshot(1, accepted=1), _snapshot(2, accepted=2))
        self.assertIs(result["valid"], True)
        self.assertEqual(result["numeric"]["total_evaluations"]["delta"], 1)
        self.assertIs(compare(None, None)["valid"], False)


if __name__ == "__main__":
    unittest.main()
