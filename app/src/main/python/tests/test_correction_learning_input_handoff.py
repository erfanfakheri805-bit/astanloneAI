"""
Tests for Prompt 457 - Correction Learning Input Handoff.

`handoff_correction_learning_input()`
(language_intelligence/correction_learning_input_handoff.py) is the
one small, controlled handoff from a Prompt 455 learning input to the
EXISTING learning layer (`LanguageLearningStore.learn_item()`, Prompt
416), gated by the EXISTING eligibility check (Prompt 456). It adds no
new learning logic; `store` remains entirely responsible for what
actually happens to a learned item. Only:

    1. an eligible correction learning input reaches the existing
       learning-layer interface (learn_item() is actually called and
       the item is actually stored)
    2. an ineligible input is rejected before reaching the learning
       layer (learn_item() is never called; nothing is stored)
    3. no learning data is invented during the handoff (the stored
       item carries exactly what the learning input carried, nothing
       more)
    4. existing learning-layer behavior remains unchanged (calling
       learn_item() directly and via the handoff, for the same input,
       produces the same result)
    5. the original learning input is not unexpectedly mutated
    6. failure from the existing learning layer follows its existing
       error/result convention (learn_item()'s own exceptions
       propagate unchanged - no new error shape is invented)

A small counting subclass of `LanguageLearningStore` is used as a
boundary test double - same "test double only at the boundary, still
delegates to the real implementation" convention already used
elsewhere (see tests/test_pre_inference_readiness_guard.py's
`CountingRuntime`).

Run directly:
    python -m unittest tests.test_correction_learning_input_handoff -v
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
)
from language_intelligence.correction_feedback_learning_input_adapter import (
    convert_correction_feedback_to_learning_input,
)
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.language_context import canonical_language
from language_intelligence.correction_learning_input_handoff import (
    handoff_correction_learning_input,
)


class CountingLanguageLearningStore(LanguageLearningStore):
    """TEST DOUBLE at the store boundary - always delegates to the real
    LanguageLearningStore implementation; only adds a call counter."""

    def __init__(self, memory):
        super().__init__(memory)
        self.learn_item_calls = 0

    def learn_item(self, *args, **kwargs):
        self.learn_item_calls += 1
        return super().learn_item(*args, **kwargs)


def _store():
    db_path = tempfile.mktemp(suffix=".db")
    memory = MemorySystem(db_path)
    return CountingLanguageLearningStore(memory), memory


def _valid_learning_input(**overrides):
    source = build_correction_understanding(
        "no I mean dog not dgo", original_expression="dgo",
        corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(result)
    learning_input = convert_correction_feedback_to_learning_input(record)
    learning_input.update(overrides)
    return learning_input


class TestEligibleInputReachesTheLearningLayer(unittest.TestCase):
    """1. An eligible correction learning input reaches the existing
    learning-layer interface."""

    def test_learn_item_is_called(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_correction_learning_input(learning_input, store)
        self.assertEqual(store.learn_item_calls, 1)

    def test_item_is_actually_stored(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        result = handoff_correction_learning_input(learning_input, store)
        self.assertIsNotNone(result)
        stored = store.get_item("en", result["item_type"], "dgo")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["key"], "dgo")


class TestIneligibleInputIsRejectedBeforeReachingTheLearningLayer(unittest.TestCase):
    """2. An ineligible input is rejected before reaching the learning
    layer."""

    def test_none_input_never_calls_learn_item(self):
        store, _memory = _store()
        result = handoff_correction_learning_input(None, store)
        self.assertIsNone(result)
        self.assertEqual(store.learn_item_calls, 0)

    def test_missing_key_never_calls_learn_item(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        del learning_input["key"]
        result = handoff_correction_learning_input(learning_input, store)
        self.assertIsNone(result)
        self.assertEqual(store.learn_item_calls, 0)

    def test_missing_language_never_calls_learn_item(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(language=None)
        result = handoff_correction_learning_input(learning_input, store)
        self.assertIsNone(result)
        self.assertEqual(store.learn_item_calls, 0)

    def test_nothing_is_stored_for_an_ineligible_input(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(meaning=None)
        handoff_correction_learning_input(learning_input, store)
        self.assertIsNone(store.get_item("en", "correction", "dgo"))


class TestNoLearningDataIsInvented(unittest.TestCase):
    """3. No learning data is invented during the handoff."""

    def test_stored_item_carries_exactly_the_input_fields(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        result = handoff_correction_learning_input(learning_input, store)
        # language is canonicalized by learn_item() itself (existing,
        # unchanged behavior - see language_learning_store.py's own
        # _resolve_language()), not by this handoff.
        self.assertEqual(result["language"],
                         canonical_language(learning_input["language"]))
        self.assertEqual(result["item_type"], learning_input["item_type"])
        self.assertEqual(result["key"], learning_input["key"])
        self.assertEqual(result["meaning"], learning_input["meaning"])
        self.assertEqual(result["confidence"], learning_input["confidence"])
        self.assertEqual(result["source"], learning_input["source"])
        self.assertEqual(result["source_context"], learning_input["source_context"])
        # No relationships/examples/learning_method are invented - they
        # fall back to learn_item()'s own existing empty defaults.
        self.assertEqual(result["examples"], [])
        self.assertEqual(result["relationships"], [])
        self.assertIsNone(result["learning_method"])


class TestExistingLearningLayerBehaviorIsUnchanged(unittest.TestCase):
    """4. Existing learning-layer behavior remains unchanged."""

    def test_handoff_result_matches_a_direct_learn_item_call(self):
        store_a, _memory_a = _store()
        store_b, _memory_b = _store()
        learning_input = _valid_learning_input()

        direct = store_a.learn_item(**learning_input)
        via_handoff = handoff_correction_learning_input(
            copy.deepcopy(learning_input), store_b)

        for field in ("id", "created_at", "updated_at"):
            direct.pop(field)
            via_handoff.pop(field)
        self.assertEqual(direct, via_handoff)

    def test_re_handing_off_the_same_input_updates_rather_than_duplicates(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        first = handoff_correction_learning_input(learning_input, store)
        second = handoff_correction_learning_input(learning_input, store)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["version"], 2)


class TestOriginalLearningInputIsNotMutated(unittest.TestCase):
    """5. The original learning input is not unexpectedly mutated."""

    def test_dict_unchanged_after_eligible_handoff(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        before = copy.deepcopy(learning_input)
        handoff_correction_learning_input(learning_input, store)
        self.assertEqual(learning_input, before)

    def test_dict_unchanged_after_ineligible_handoff(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(key="")
        before = copy.deepcopy(learning_input)
        handoff_correction_learning_input(learning_input, store)
        self.assertEqual(learning_input, before)

    def test_mutable_meaning_not_shared_with_stored_item(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(meaning={"text": "dog"})
        result = handoff_correction_learning_input(learning_input, store)
        result["meaning"]["text"] = "mutated"
        self.assertEqual(learning_input["meaning"], {"text": "dog"})


class TestLearningLayerFailureFollowsItsExistingConvention(unittest.TestCase):
    """6. Failure from the existing learning layer follows its
    existing error/result convention."""

    def test_invalid_confidence_type_raises_the_same_error_learn_item_raises(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(confidence="not a number")
        with self.assertRaises(TypeError):
            handoff_correction_learning_input(learning_input, store)

    def test_wrong_store_type_raises_type_error(self):
        learning_input = _valid_learning_input()
        with self.assertRaises(TypeError):
            handoff_correction_learning_input(learning_input, object())

    def test_direct_learn_item_call_raises_the_same_error(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(confidence="not a number")
        with self.assertRaises(TypeError):
            store.learn_item(**learning_input)


if __name__ == "__main__":
    unittest.main()
