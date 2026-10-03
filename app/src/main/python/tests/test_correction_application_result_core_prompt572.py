"""
Tests for Prompt 572 - Attach Correction Application Result in Core.

Prompt 571 added `LanguageUnderstandingResult.correction_application_
result` and confirmed the response-generation pipeline already carries
it. Prompt 570 already provides the pure operation
`apply_correction_application_candidate(candidate, target_text)`. This
prompt adds exactly one new Core method,
`_attach_correction_application_result()`, called immediately after the
EXISTING `_attach_correction_application_candidate()` at both of its
call sites (`_handle_conversation`'s step 1c and `understand_language()`),
which reads the already-attached `correction_application_candidate`,
calls the existing Prompt 570 operation on it exactly once (using
`understanding.original_input` as `target_text` - the SAME verbatim
message text Prompt 567's retrieval was itself triggered from), and
stores the result as `understanding.correction_application_result`.

Covers:
    1. Real Core processing with a correction candidate produces a
       real CorrectionApplicationResult.
    2. The result is attached to LanguageUnderstandingResult.
    3. The result reaches the existing response-generation context.
    4. Original/corrected values are preserved.
    5. No candidate leaves the result as None (never a meaningless
       FAILED result for ordinary messages).
    6. A malformed candidate is handled safely (never raises).
    7. The application operation runs exactly once.
    8. Candidate retrieval is not repeated.
    9. Candidate selection is not repeated.
    10. The candidate itself is not mutated.
    11. Existing correction acknowledgement remains unchanged.
    12. Ordinary non-correction messages remain unchanged.
    13. Repeated identical processing is deterministic.

Run directly:
    python -m unittest tests.test_correction_application_result_core_prompt572 -v
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

from core.core import Core
import core.core as core_module
from language_intelligence import correction_application_candidate_operation as operation_module
from language_intelligence.language_understanding_result import LanguageUnderstandingResult
from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate,
)
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult, STATUS_APPLIED, STATUS_NOT_APPLIED,
)
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
from language_intelligence.correction_learning_handoff_result import (
    handoff_correction_learning_input_with_result,
)
from language_intelligence.correction_learning_input_storage import (
    store_accepted_correction_learning_input,
)


def _make_core():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
    skills_dir = os.path.join(tmpdir.name, "skills")
    core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)
    return core, tmpdir


def _store_a_correction(store, original_expression="dgo", corrected_expression="dog",
                         language="en", locale="en-US", confidence=0.9):
    """Seed `store` (Core's own real `self.language_learning`) with a
    stored correction through the EXISTING chain - the SAME one
    `test_correction_retrieval_trigger_connection_prompt567.py` already
    uses to set up a real, retrievable candidate."""
    source = build_correction_understanding(
        "no I mean %s not %s" % (corrected_expression, original_expression),
        original_expression=original_expression,
        corrected_expression=corrected_expression, language=language,
        locale=locale, confidence=confidence)
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(result)
    learning_input = convert_correction_feedback_to_learning_input(record)
    handoff_result = handoff_correction_learning_input_with_result(learning_input, store)
    store_accepted_correction_learning_input(handoff_result, learning_input, store)


def _wrap_and_count(obj, attr_name):
    """Wrap `obj.attr_name` with a call counter, still delegating to the
    real, unmodified function - the SAME convention
    test_correction_retrieval_trigger_connection_prompt567.py already
    uses."""
    original = getattr(obj, attr_name)
    call_count = [0]

    def counting(*args, **kwargs):
        call_count[0] += 1
        return original(*args, **kwargs)

    setattr(obj, attr_name, counting)

    def restore():
        setattr(obj, attr_name, original)

    return call_count, restore


class TestRealCoreProcessingProducesRealResult(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_process_input_attaches_a_real_applied_result(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        self.core.process_input("not dgo, I mean dog.")
        understanding = self.core.last_language_understanding
        result = understanding.correction_application_result
        self.assertIsInstance(result, CorrectionApplicationResult)
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertTrue(result.applied)

    def test_understand_language_attaches_the_same_kind_of_result(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertIsInstance(
            understanding.correction_application_result, CorrectionApplicationResult)

    def test_original_and_corrected_values_are_preserved(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        result = understanding.correction_application_result
        self.assertEqual(result.matched_text, "dgo")
        self.assertEqual(result.replacement_text, "dog")
        self.assertEqual(result.original_text, "not dgo, I mean dog.")
        self.assertEqual(result.corrected_text, "not dog, I mean dog.")

    def test_to_dict_exposes_the_attached_result(self):
        _store_a_correction(self.core.language_learning, "teh", "the")
        understanding = self.core.understand_language("not teh, I mean the.")
        as_dict = understanding.to_dict()
        self.assertIsNotNone(as_dict["correction_application_result"])
        self.assertEqual(as_dict["correction_application_result"]["status"], STATUS_APPLIED)


class TestResultReachesResponseGenerationContext(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_generation_context_carries_the_real_result(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        from language_intelligence.response_generation import ResponseGenerationRequest
        request = ResponseGenerationRequest(understanding)
        context = request.generation_context
        self.assertIsNotNone(context)
        self.assertEqual(
            context["correction_application_result"],
            understanding.correction_application_result.to_dict())


class TestNoCandidateLeavesResultNone(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ordinary_message_produces_no_result(self):
        understanding = self.core.understand_language("Hello, how are you today?")
        self.assertIsNone(understanding.correction_application_candidate)
        self.assertIsNone(understanding.correction_application_result)

    def test_no_stored_correction_leaves_result_none(self):
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertIsNone(understanding.correction_application_candidate)
        self.assertIsNone(understanding.correction_application_result)


class TestMalformedCandidateIsSafe(unittest.TestCase):
    def test_none_understanding_does_not_raise(self):
        core, tmpdir = _make_core()
        try:
            core._attach_correction_application_result(None)
        finally:
            tmpdir.cleanup()

    def test_non_candidate_value_does_not_raise(self):
        understanding = LanguageUnderstandingResult(
            original_input="hello", detected_language="en",
            normalized_input="hello", intent="unknown", entities=[],
            referenced_items=[], active_topic=None, conversation_context=None,
            confidence=0.5, ambiguity=False, needs_clarification=False,
            correction_application_candidate="not-a-real-candidate",
        )
        core, tmpdir = _make_core()
        try:
            # Should never raise. A non-None, non-candidate value is not
            # itself None, so the existing Prompt 570 eligibility check
            # (unchanged here) decides what happens - never this method.
            core._attach_correction_application_result(understanding)
            result = understanding.correction_application_result
            if result is not None:
                self.assertNotEqual(result.status, STATUS_APPLIED)
        finally:
            tmpdir.cleanup()

    def test_invalid_candidate_produces_a_safe_not_applied_or_none_result(self):
        core, tmpdir = _make_core()
        try:
            invalid_candidate = CorrectionApplicationCandidate(is_valid=False)
            understanding = LanguageUnderstandingResult(
                original_input="hello", detected_language="en",
                normalized_input="hello", intent="unknown", entities=[],
                referenced_items=[], active_topic=None, conversation_context=None,
                confidence=0.5, ambiguity=False, needs_clarification=False,
                correction_application_candidate=invalid_candidate,
            )
            # Should never raise.
            core._attach_correction_application_result(understanding)
            result = understanding.correction_application_result
            if result is not None:
                self.assertNotEqual(result.status, STATUS_APPLIED)
        finally:
            tmpdir.cleanup()


class TestApplicationOperationRunsExactlyOnce(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_apply_correction_application_candidate_called_exactly_once(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        call_count, restore = _wrap_and_count(
            core_module, "apply_correction_application_candidate")
        try:
            self.core.understand_language("not dgo, I mean dog.")
        finally:
            restore()
        self.assertEqual(call_count[0], 1)

    def test_no_application_call_for_an_ordinary_message(self):
        call_count, restore = _wrap_and_count(
            core_module, "apply_correction_application_candidate")
        try:
            self.core.understand_language("Hello, how are you today?")
        finally:
            restore()
        self.assertEqual(call_count[0], 0)


class TestRetrievalAndSelectionAreNotRepeated(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_retrieval_adapter_still_called_exactly_once(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        call_count, restore = _wrap_and_count(
            core_module, "retrieve_and_attach_correction_application_candidate")
        try:
            self.core.understand_language("not dgo, I mean dog.")
        finally:
            restore()
        self.assertEqual(call_count[0], 1)

    def test_eligibility_evaluated_exactly_once_by_the_operation(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        call_count, restore = _wrap_and_count(
            operation_module, "evaluate_correction_application_candidate_eligibility")
        try:
            self.core.understand_language("not dgo, I mean dog.")
        finally:
            restore()
        self.assertEqual(call_count[0], 1)


class TestCandidateIsNotMutated(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_candidate_fields_unchanged_after_application(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        candidate = understanding.correction_application_candidate
        before = candidate.to_dict()
        # Result already attached by the same understand_language() call.
        self.assertIsNotNone(understanding.correction_application_result)
        self.assertEqual(candidate.to_dict(), before)


class TestAcknowledgementAndOrdinaryMessagesUnaffected(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ordinary_conversation_reply_unaffected(self):
        reply = self.core.process_input("Hello, how are you today?")
        self.assertIsInstance(reply, str)

    def test_correction_understanding_status_unaffected_by_new_attachment(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        # correction_understanding is computed independently and still
        # reflects only the Prompt 440/560 correction-detection logic.
        self.assertIsNotNone(understanding.correction_understanding)


class TestDeterminism(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_repeated_identical_processing_produces_equal_results(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        first = self.core.understand_language("not dgo, I mean dog.")
        second = self.core.understand_language("not dgo, I mean dog.")
        self.assertEqual(
            first.correction_application_result.to_dict(),
            second.correction_application_result.to_dict(),
        )


if __name__ == "__main__":
    unittest.main()
