"""
Tests for Prompt 565 - Safely Connect Correction Retrieval to Language
Understanding.

Prompt 563's own audit
(diagnostics/section2_correction_retrieval_application_audit_prompt563.py)
found no existing, deterministic trigger anywhere in this codebase for
"when should an ordinary message's understanding look up a
previously-stored correction" - and Prompt 565's own instructions
forbid inventing one here. Per Prompt 565 section 6, since no safe
trigger exists, these tests replace items 1-5 of the original list
with tests proving the new boundary/adapter
(language_intelligence/correction_retrieval_understanding_adapter.py)
is correct and that no retrieval occurs prematurely - i.e. that
nothing in this project calls it automatically.

Covers:
    1. The existing chain, composed by this adapter, produces a valid
       candidate from a real stored correction.
    2. The candidate contains the expected correction data.
    3. No candidate is produced (and none is attached) when no
       matching correction exists.
    4. Ordinary/unrelated backend understanding never triggers a
       lookup or produces a candidate on its own.
    5. Exactly one store lookup happens per adapter call.
    6. Existing correction acknowledgement (Prompt 560) is unaffected.
    7. Ambiguous/unresolved corrections remain safe (never attached).
    8. `LanguageUnderstandingResult.to_dict()` preserves an attached
       candidate correctly.
    9. Existing behavior/tests are unaffected (spot checks).
    10. Determinism across repeated equivalent operations.
    Plus: type validation, and the "never overwrites an existing
    candidate" adapter rule.

Run directly:
    python -m unittest tests.test_correction_retrieval_understanding_adapter_prompt565 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from understanding.engine import UnderstandingEngine
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_understanding_result import LanguageUnderstandingResult
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.language_context import canonical_language
from language_intelligence.correction_understanding import build_correction_understanding
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
from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate,
)
from language_intelligence.correction_retrieval_understanding_adapter import (
    build_correction_application_candidate_from_store,
    attach_correction_application_candidate,
    retrieve_and_attach_correction_application_candidate,
)


def _store():
    db_path = tempfile.mktemp(suffix=".db")
    memory = MemorySystem(db_path)
    return LanguageLearningStore(memory), memory


def _valid_learning_input(original_expression="dgo", corrected_expression="dog",
                           language="en", locale="en-US", confidence=0.9, **overrides):
    source = build_correction_understanding(
        "no I mean %s not %s" % (corrected_expression, original_expression),
        original_expression=original_expression,
        corrected_expression=corrected_expression, language=language,
        locale=locale, confidence=confidence)
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(result)
    learning_input = convert_correction_feedback_to_learning_input(record)
    learning_input.update(overrides)
    return learning_input


def _store_a_correction(store, **overrides):
    learning_input = _valid_learning_input(**overrides)
    handoff_result = handoff_correction_learning_input_with_result(learning_input, store)
    stored = store_accepted_correction_learning_input(handoff_result, learning_input, store)
    return learning_input, stored


def _make_backend():
    return DeterministicFallbackBackend(UnderstandingEngine())


def _minimal_result(**overrides):
    kwargs = dict(
        original_input="hello there",
        detected_language="en",
        normalized_input="hello there",
        intent="unknown",
        entities=[],
        referenced_items=[],
        active_topic=None,
        conversation_context=None,
        confidence=0.5,
        ambiguity=False,
        needs_clarification=False,
    )
    kwargs.update(overrides)
    return LanguageUnderstandingResult(**kwargs)


class TestValidCandidateFromRealStoredCorrection(unittest.TestCase):
    """1 & 2. The existing chain, composed by this adapter, produces a
    valid candidate with the expected data from a real stored
    correction."""

    def test_valid_candidate_produced(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo", corrected_expression="dog")
        candidate = build_correction_application_candidate_from_store(store, "dgo", language="en")
        self.assertIsInstance(candidate, CorrectionApplicationCandidate)
        self.assertTrue(candidate.is_valid)

    def test_candidate_data_matches_stored_correction(self):
        store, _memory = _store()
        _store_a_correction(
            store, original_expression="teh", corrected_expression="the",
            language="en", confidence=0.75)
        candidate = build_correction_application_candidate_from_store(store, "teh", language="en")
        self.assertEqual(candidate.original_expression, "teh")
        self.assertEqual(candidate.corrected_expression_or_meaning, "the")
        self.assertEqual(candidate.language, canonical_language("en"))

    def test_attaching_the_candidate_via_adapter(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo", corrected_expression="dog")
        result = _minimal_result()
        retrieve_and_attach_correction_application_candidate(result, store, "dgo", language="en")
        self.assertIsNotNone(result.correction_application_candidate)
        self.assertTrue(result.correction_application_candidate.is_valid)
        self.assertEqual(result.correction_application_candidate.original_expression, "dgo")


class TestNoCandidateWhenNoMatch(unittest.TestCase):
    """3. No candidate is produced/attached when no matching correction
    exists."""

    def test_no_match_produces_invalid_candidate(self):
        store, _memory = _store()
        candidate = build_correction_application_candidate_from_store(
            store, "nonexistent", language="en")
        self.assertFalse(candidate.is_valid)
        self.assertIsNone(candidate.original_expression)

    def test_no_match_leaves_result_candidate_none(self):
        store, _memory = _store()
        result = _minimal_result()
        retrieve_and_attach_correction_application_candidate(
            result, store, "nonexistent", language="en")
        self.assertIsNone(result.correction_application_candidate)


class TestOrdinaryInputNeverTriggersLookup(unittest.TestCase):
    """4. Ordinary unrelated input never triggers inappropriate
    correction retrieval - nothing in the backend or Core calls this
    adapter automatically."""

    def test_backend_never_populates_the_field_on_its_own(self):
        backend = _make_backend()
        for text in ("hello", "car", "teh", "Python is a programming language.",
                     "no I meant car"):
            result = backend.understand(text)
            self.assertIsNone(result.correction_application_candidate)

    def test_adapter_module_not_imported_by_backend_or_core(self):
        import language_intelligence.deterministic_fallback_backend as backend_module
        import language_intelligence.language_intelligence_core as core_module
        self.assertNotIn(
            "correction_retrieval_understanding_adapter", dir(backend_module))
        self.assertNotIn(
            "correction_retrieval_understanding_adapter", dir(core_module))


class TestRetrievalHappensAtMostOnce(unittest.TestCase):
    """5. Retrieval happens at most once for a single adapter call."""

    def test_exactly_one_get_item_call(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo", corrected_expression="dog")
        calls = []
        original_find_items = store.find_items

        def counting_find_items(*args, **kwargs):
            calls.append((args, kwargs))
            return original_find_items(*args, **kwargs)

        store.find_items = counting_find_items
        build_correction_application_candidate_from_store(store, "dgo", language="en")
        self.assertEqual(len(calls), 1)


class TestExistingCorrectionAcknowledgementUnchanged(unittest.TestCase):
    """6. Existing correction acknowledgement behavior (Prompt 560)
    remains unchanged - this adapter is never invoked from the
    understanding/acknowledgement path."""

    def test_correction_message_understanding_unaffected(self):
        backend = _make_backend()
        result = backend.understand("not dgo, I mean dog.")
        self.assertIsNone(result.correction_application_candidate)
        self.assertIsNotNone(result.correction_understanding)

    def test_ordinary_message_understanding_unaffected(self):
        backend = _make_backend()
        result = backend.understand("What is Python?")
        self.assertIsNone(result.correction_application_candidate)


class TestAmbiguousAndUnresolvedRemainSafe(unittest.TestCase):
    """7. Ambiguous/unresolved corrections remain safe - never attached
    as a usable candidate."""

    def test_ambiguous_match_not_attached(self):
        store, _memory = _store()
        # Two records for the same key under different languages ->
        # more than one exact match -> AMBIGUOUS in the existing chain.
        _store_a_correction(
            store, original_expression="chat", corrected_expression="cat",
            language="en")
        _store_a_correction(
            store, original_expression="chat", corrected_expression="chat (fr)",
            language="fr")
        candidate = build_correction_application_candidate_from_store(store, "chat")
        self.assertFalse(candidate.is_valid)

        result = _minimal_result()
        retrieve_and_attach_correction_application_candidate(result, store, "chat")
        self.assertIsNone(result.correction_application_candidate)


class TestToDictPreservesCandidate(unittest.TestCase):
    """8. LanguageUnderstandingResult.to_dict() preserves the attached
    candidate correctly."""

    def test_to_dict_reflects_attached_candidate(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo", corrected_expression="dog")
        result = _minimal_result()
        retrieve_and_attach_correction_application_candidate(result, store, "dgo", language="en")
        as_dict = result.to_dict()
        self.assertIsNotNone(as_dict["correction_application_candidate"])
        self.assertEqual(
            as_dict["correction_application_candidate"],
            result.correction_application_candidate.to_dict(),
        )


class TestExistingTestsContinueToPass(unittest.TestCase):
    """9. Spot-check other existing behavior remains unaffected."""

    def test_real_backend_understanding_otherwise_unaffected(self):
        backend = _make_backend()
        result = backend.understand("Python is a programming language.")
        self.assertTrue(any(e["text"].lower() == "python" for e in result.entities))
        self.assertFalse(result.ambiguity)

    def test_existing_field_default_still_none(self):
        result = _minimal_result()
        self.assertIsNone(result.correction_application_candidate)


class TestDeterminism(unittest.TestCase):
    """10. Determinism across repeated equivalent operations."""

    def test_repeated_lookup_produces_equal_candidate(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo", corrected_expression="dog")
        candidate_a = build_correction_application_candidate_from_store(store, "dgo", language="en")
        candidate_b = build_correction_application_candidate_from_store(store, "dgo", language="en")
        self.assertEqual(candidate_a, candidate_b)

    def test_repeated_attach_produces_equal_result_dict(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo", corrected_expression="dog")
        result_a = _minimal_result()
        result_b = _minimal_result()
        retrieve_and_attach_correction_application_candidate(result_a, store, "dgo", language="en")
        retrieve_and_attach_correction_application_candidate(result_b, store, "dgo", language="en")
        self.assertEqual(result_a.to_dict(), result_b.to_dict())


class TestAdapterTypeValidation(unittest.TestCase):
    """Type validation for the new adapter functions."""

    def test_attach_rejects_non_understanding_object(self):
        with self.assertRaises(TypeError):
            attach_correction_application_candidate("not a result", None)

    def test_attach_rejects_non_candidate_object(self):
        result = _minimal_result()
        with self.assertRaises(TypeError):
            attach_correction_application_candidate(result, "not a candidate")

    def test_attach_none_candidate_is_a_noop(self):
        result = _minimal_result()
        returned = attach_correction_application_candidate(result, None)
        self.assertIs(returned, result)
        self.assertIsNone(result.correction_application_candidate)


class TestAdapterNeverOverwritesExistingCandidate(unittest.TestCase):
    """The adapter never overwrites a candidate a result already
    carries - mirrors _attach_response_plan()'s own rule for
    response_plan."""

    def test_existing_candidate_preserved(self):
        store, _memory = _store()
        _store_a_correction(store, original_expression="dgo", corrected_expression="dog")
        existing_candidate = build_correction_application_candidate_from_store(
            store, "dgo", language="en")
        result = _minimal_result(correction_application_candidate=existing_candidate)

        _store_a_correction(store, original_expression="teh", corrected_expression="the")
        retrieve_and_attach_correction_application_candidate(result, store, "teh", language="en")

        self.assertIs(result.correction_application_candidate, existing_candidate)
        self.assertEqual(result.correction_application_candidate.original_expression, "dgo")


if __name__ == "__main__":
    unittest.main()
