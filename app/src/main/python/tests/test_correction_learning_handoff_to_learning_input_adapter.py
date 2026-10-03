"""
Tests for Prompt 460 - Convert Correction Handoff to Learning Input.

`convert_accepted_correction_handoff_to_learning_input()`
(language_intelligence/correction_learning_handoff_to_learning_input_adapter.py)
converts an ACCEPTED `CorrectionLearningHandoffResult` (Prompt 458)
back into the EXISTING learning-input dict (Prompt 455's shape) it was
built from. It performs no learning and reuses Prompt 459's validation
unchanged.

    - accepted handoff -> valid learning input
    - rejected handoff -> not converted
    - failed handoff -> not converted
    - invalid handoff -> not converted
    - original correction information is preserved
    - language/locale information is preserved when available

Run directly:
    python -m unittest tests.test_correction_learning_handoff_to_learning_input_adapter -v
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
from language_intelligence.correction_learning_handoff_result import (
    STATUS_ACCEPTED,
    STATUS_REJECTED,
    STATUS_FAILED,
    CorrectionLearningHandoffResult,
)
from language_intelligence.correction_learning_handoff_result import (
    handoff_correction_learning_input_with_result,
)
from language_intelligence.correction_learning_handoff_to_learning_input_adapter import (
    convert_accepted_correction_handoff_to_learning_input,
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


class TestAcceptedHandoffProducesAValidLearningInput(unittest.TestCase):
    """accepted handoff -> valid learning input."""

    def test_returns_a_dict(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)
        self.assertEqual(handoff_result.status, STATUS_ACCEPTED)

        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        self.assertIsInstance(converted, dict)

    def test_matches_the_original_learning_input(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        self.assertEqual(converted, learning_input)

    def test_returns_a_copy_not_the_same_object(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        self.assertIsNot(converted, learning_input)
        converted["key"] = "mutated"
        self.assertEqual(learning_input["key"], "dgo")


class TestRejectedHandoffIsNotConverted(unittest.TestCase):
    """rejected handoff -> not converted."""

    def test_returns_none(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        del learning_input["key"]
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)
        self.assertEqual(handoff_result.status, STATUS_REJECTED)

        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        self.assertIsNone(converted)

    def test_directly_constructed_rejected_result_returns_none(self):
        learning_input = _valid_learning_input()
        handoff_result = CorrectionLearningHandoffResult(STATUS_REJECTED)
        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        self.assertIsNone(converted)


class TestFailedHandoffIsNotConverted(unittest.TestCase):
    """failed handoff -> not converted."""

    def test_returns_none(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(confidence="not a number")
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)
        self.assertEqual(handoff_result.status, STATUS_FAILED)

        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        self.assertIsNone(converted)

    def test_directly_constructed_failed_result_returns_none(self):
        learning_input = _valid_learning_input()
        handoff_result = CorrectionLearningHandoffResult(
            STATUS_FAILED, reason="some existing failure text")
        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        self.assertIsNone(converted)


class TestInvalidHandoffIsNotConverted(unittest.TestCase):
    """invalid handoff -> not converted."""

    def test_none_handoff_result(self):
        learning_input = _valid_learning_input()
        converted = convert_accepted_correction_handoff_to_learning_input(
            None, learning_input)
        self.assertIsNone(converted)

    def test_plain_dict_is_not_a_handoff_result(self):
        learning_input = _valid_learning_input()
        fake = {"status": STATUS_ACCEPTED, "accepted": True,
                "source": "USER_CORRECTION", "reason": None}
        converted = convert_accepted_correction_handoff_to_learning_input(
            fake, learning_input)
        self.assertIsNone(converted)

    def test_structurally_invalid_accepted_result_is_not_converted(self):
        # accepted flag inconsistent with status - structurally
        # INVALID per Prompt 459's validation, even though status
        # itself is ACCEPTED.
        learning_input = _valid_learning_input()
        handoff_result = CorrectionLearningHandoffResult(STATUS_ACCEPTED)
        handoff_result.accepted = False
        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        self.assertIsNone(converted)

    def test_non_dict_learning_input_is_not_converted(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)
        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, "not a dict")
        self.assertIsNone(converted)

    def test_none_learning_input_is_not_converted(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)
        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, None)
        self.assertIsNone(converted)


class TestOriginalCorrectionInformationIsPreserved(unittest.TestCase):
    """original correction information is preserved."""

    def test_all_existing_fields_survive_conversion(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        self.assertEqual(converted["key"], "dgo")
        self.assertEqual(converted["meaning"], "dog")
        self.assertEqual(converted["item_type"], learning_input["item_type"])
        self.assertEqual(converted["confidence"], learning_input["confidence"])
        self.assertEqual(converted["source"], learning_input["source"])
        self.assertEqual(converted["source_context"], learning_input["source_context"])

    def test_mutable_meaning_is_not_shared(self):
        store, _memory = _store()
        learning_input = _valid_learning_input(meaning={"text": "dog"})
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        converted["meaning"]["text"] = "mutated"
        self.assertEqual(learning_input["meaning"], {"text": "dog"})

    def test_neither_argument_is_mutated_by_conversion(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)
        before_input = copy.deepcopy(learning_input)
        before_result = handoff_result.to_dict()

        convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)

        self.assertEqual(learning_input, before_input)
        self.assertEqual(handoff_result.to_dict(), before_result)


class TestLanguageAndLocaleInformationIsPreservedWhenAvailable(unittest.TestCase):
    """language/locale information is preserved when available."""

    def test_language_is_preserved(self):
        store, _memory = _store()
        learning_input = _valid_learning_input()
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        self.assertEqual(converted["language"], learning_input["language"])
        self.assertEqual(converted["language"], "en")

    def test_no_locale_field_is_invented(self):
        # locale was never part of learn_item()'s existing keyword
        # shape (Prompt 455's own documented decision) - this module
        # does not add one either.
        store, _memory = _store()
        learning_input = _valid_learning_input()
        self.assertNotIn("locale", learning_input)
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, store)

        converted = convert_accepted_correction_handoff_to_learning_input(
            handoff_result, learning_input)
        self.assertNotIn("locale", converted)


if __name__ == "__main__":
    unittest.main()
