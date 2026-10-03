"""
Tests for Prompt 458 - Correction Learning Handoff Result.

`handoff_correction_learning_input_with_result()`
(language_intelligence/correction_learning_handoff_result.py) wraps
the EXISTING Prompt 457 handoff (`handoff_correction_learning_input()`)
and reports its outcome as a small `CorrectionLearningHandoffResult`
instead of a return-value-or-raise. It adds no new eligibility rule
and no new learning-layer behavior.

    1. a valid correction learning input produces ACCEPTED when the
       existing learning handoff succeeds
    2. an ineligible input produces REJECTED
    3. a learning-layer failure produces FAILED
    4. `accepted` matches `status` correctly
    5. `source` remains USER_CORRECTION
    6. existing failure/rejection reasons are preserved when available
    7. no learning information is invented
    8. existing learning behavior (Prompt 457's own function) remains
       unchanged

Run directly:
    python -m unittest tests.test_correction_learning_handoff_result -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from language_intelligence.correction_understanding import (
    build_correction_understanding,
)
from language_intelligence.correction_understanding_result import (
    map_correction_understanding_to_result,
)
from language_intelligence.correction_feedback_record import (
    map_correction_understanding_result_to_feedback_record,
    SOURCE_USER_CORRECTION,
)
from language_intelligence.correction_feedback_learning_input_adapter import (
    convert_correction_feedback_to_learning_input,
)
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.correction_learning_input_handoff import (
    handoff_correction_learning_input,
)
from language_intelligence.correction_learning_handoff_result import (
    CorrectionLearningHandoffResult,
    STATUS_ACCEPTED,
    STATUS_REJECTED,
    STATUS_FAILED,
    handoff_correction_learning_input_with_result,
)


def _store():
    db_path = tempfile.mktemp(suffix=".db")
    memory = MemorySystem(db_path)
    return LanguageLearningStore(memory), memory


def _valid_learning_input(**overrides):
    source = build_correction_understanding(
        "no I mean dog not dgo", original_expression="dgo",
        corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(result)
    learning_input = convert_correction_feedback_to_learning_input(record)
    learning_input.update(overrides)
    return learning_input


class TestValidInputProducesAccepted(unittest.TestCase):
    """1. A valid correction learning input produces ACCEPTED when the
    existing learning handoff succeeds."""

    def test_status_is_accepted(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        result = handoff_correction_learning_input_with_result(learning_input, store)
        self.assertEqual(result.status, STATUS_ACCEPTED)

    def test_item_is_actually_stored(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_correction_learning_input_with_result(learning_input, store)
        stored = store.get_item("en", "correction", "dgo")
        self.assertIsNotNone(stored)


class TestIneligibleInputProducesRejected(unittest.TestCase):
    """2. An ineligible input produces REJECTED."""

    def test_none_input(self):
        store, _memory = _store()
        result = handoff_correction_learning_input_with_result(None, store)
        self.assertEqual(result.status, STATUS_REJECTED)

    def test_missing_key(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        del learning_input["key"]
        result = handoff_correction_learning_input_with_result(learning_input, store)
        self.assertEqual(result.status, STATUS_REJECTED)

    def test_missing_language(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(language=None)
        result = handoff_correction_learning_input_with_result(learning_input, store)
        self.assertEqual(result.status, STATUS_REJECTED)

    def test_rejected_input_is_never_stored(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(meaning=None)
        handoff_correction_learning_input_with_result(learning_input, store)
        self.assertIsNone(store.get_item("en", "correction", "dgo"))


class TestLearningLayerFailureProducesFailed(unittest.TestCase):
    """3. A learning-layer failure produces FAILED."""

    def test_invalid_confidence_type_produces_failed(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(confidence="not a number")
        result = handoff_correction_learning_input_with_result(learning_input, store)
        self.assertEqual(result.status, STATUS_FAILED)

    def test_wrong_store_type_produces_failed(self):
        learning_input = _valid_learning_input()
        result = handoff_correction_learning_input_with_result(learning_input, object())
        self.assertEqual(result.status, STATUS_FAILED)


class TestAcceptedMatchesStatus(unittest.TestCase):
    """4. `accepted` matches the status correctly."""

    def test_accepted_true_only_for_accepted_status(self):
        store, _memory = _store()

        accepted = handoff_correction_learning_input_with_result(
            _valid_learning_input(), store)
        rejected = handoff_correction_learning_input_with_result(None, store)
        failed = handoff_correction_learning_input_with_result(
            _valid_learning_input(confidence="not a number"), store)

        self.assertTrue(accepted.accepted)
        self.assertFalse(rejected.accepted)
        self.assertFalse(failed.accepted)

    def test_accepted_is_a_bool(self):
        store, _memory = _store()
        result = handoff_correction_learning_input_with_result(
            _valid_learning_input(), store)
        self.assertIsInstance(result.accepted, bool)


class TestSourceRemainsUserCorrection(unittest.TestCase):
    """5. `source` remains USER_CORRECTION."""

    def test_source_on_accepted(self):
        store, _memory = _store()
        result = handoff_correction_learning_input_with_result(
            _valid_learning_input(), store)
        self.assertEqual(result.source, SOURCE_USER_CORRECTION)

    def test_source_on_rejected(self):
        store, _memory = _store()
        result = handoff_correction_learning_input_with_result(None, store)
        self.assertEqual(result.source, SOURCE_USER_CORRECTION)

    def test_source_on_failed(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(confidence="not a number")
        result = handoff_correction_learning_input_with_result(learning_input, store)
        self.assertEqual(result.source, SOURCE_USER_CORRECTION)


class TestExistingReasonsArePreservedWhenAvailable(unittest.TestCase):
    """6. Existing failure/rejection reasons are preserved when
    available."""

    def test_failed_reason_matches_the_underlying_exception_text(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(confidence="not a number")

        try:
            handoff_correction_learning_input(learning_input, store)
            raised = None
        except (ValueError, TypeError) as exc:
            raised = str(exc)

        result = handoff_correction_learning_input_with_result(learning_input, store)
        self.assertIsNotNone(raised)
        self.assertEqual(result.reason, raised)

    def test_accepted_reason_is_none(self):
        store, _memory = _store()
        result = handoff_correction_learning_input_with_result(
            _valid_learning_input(), store)
        self.assertIsNone(result.reason)

    def test_rejected_reason_is_none_when_none_is_available(self):
        # is_correction_learning_input_eligible() (Prompt 456) reports
        # only a boolean, with no reason text to reuse - so nothing is
        # invented here.
        store, _memory = _store()
        result = handoff_correction_learning_input_with_result(None, store)
        self.assertIsNone(result.reason)


class TestNoLearningInformationIsInvented(unittest.TestCase):
    """7. No learning information is invented."""

    def test_result_carries_only_the_four_documented_fields(self):
        store, _memory = _store()
        result = handoff_correction_learning_input_with_result(
            _valid_learning_input(), store)
        self.assertEqual(
            set(result.to_dict().keys()), {"status", "accepted", "source", "reason"})

    def test_stored_item_still_carries_exactly_the_input_fields(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_correction_learning_input_with_result(learning_input, store)
        stored = store.get_item("en", "correction", "dgo")
        self.assertEqual(stored["meaning"], learning_input["meaning"])
        self.assertEqual(stored["source"], learning_input["source"])
        self.assertEqual(stored["examples"], [])
        self.assertEqual(stored["relationships"], [])

    def test_original_learning_input_is_not_mutated(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        before = copy.deepcopy(learning_input)
        handoff_correction_learning_input_with_result(learning_input, store)
        self.assertEqual(learning_input, before)


class TestExistingLearningBehaviorIsUnchanged(unittest.TestCase):
    """8. Existing learning behavior remains unchanged - Prompt 457's
    own `handoff_correction_learning_input()` keeps its exact
    original return-value-or-raise contract."""

    def test_direct_handoff_still_returns_none_for_ineligible_input(self):
        store, _memory = _store()
        self.assertIsNone(handoff_correction_learning_input(None, store))

    def test_direct_handoff_still_returns_a_dict_for_an_eligible_input(self):
        store, _memory = _store()
        result = handoff_correction_learning_input(_valid_learning_input(), store)
        self.assertIsInstance(result, dict)

    def test_direct_handoff_still_raises_on_learning_layer_failure(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(confidence="not a number")
        with self.assertRaises(TypeError):
            handoff_correction_learning_input(learning_input, store)

    def test_wrapping_does_not_change_what_gets_stored(self):
        store_a, _memory_a = _store()
        store_b, _memory_b = _store()
        learning_input = _valid_learning_input()

        direct = handoff_correction_learning_input(
            copy.deepcopy(learning_input), store_a)
        handoff_correction_learning_input_with_result(
            copy.deepcopy(learning_input), store_b)
        via_wrapper = store_b.get_item("en", "correction", "dgo")

        for field in ("id", "created_at", "updated_at"):
            direct.pop(field)
            via_wrapper.pop(field)
        self.assertEqual(direct, via_wrapper)


class TestResultConstruction(unittest.TestCase):
    """Small, direct checks on the result object itself."""

    def test_rejects_an_unknown_status(self):
        with self.assertRaises(ValueError):
            CorrectionLearningHandoffResult("NOT_A_REAL_STATUS")

    def test_equality_by_value(self):
        a = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        b = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
