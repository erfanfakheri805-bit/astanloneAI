"""
Tests for Prompt 564 - Carry an Existing CorrectionApplicationCandidate
Through Language Understanding.

Covers the small, additive integration that exposes Prompt 470's
`CorrectionApplicationCandidate`
(language_intelligence/correction_application_candidate.py) through the
existing `LanguageUnderstandingResult`
(language_intelligence/language_understanding_result.py):

    CorrectionApplicationCandidate (Prompt 470, unchanged)
        -> LanguageUnderstandingResult.correction_application_candidate
           (Prompt 564, THIS module's subject - dict or None)

This is the exact smallest-safe-path Prompt 563's own audit identified
as missing (see docs/section2_correction_retrieval_application_audit_
prompt563.md, "Smallest concrete missing foundation for the next
prompt", item 2): a place for an already-built
`CorrectionApplicationCandidate` to be carried on this result. Nothing
in this test file (or in the change under test) performs a correction
lookup or retrieval automatically, applies a stored correction, or
modifies the original message. A `CorrectionApplicationCandidate` is
built directly (Prompt 470's own, unchanged
`build_correction_application_candidate()` / `CorrectionSelectionResult`)
and attached to a `LanguageUnderstandingResult` by hand, exactly as a
future, separately scoped caller would.

Run directly:
    python -m unittest tests.test_correction_application_candidate_exposure -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_understanding_result import LanguageUnderstandingResult
from language_intelligence.correction_lookup_selection import (
    CorrectionSelectionResult,
    OUTCOME_SELECTED, OUTCOME_AMBIGUOUS, OUTCOME_NOT_FOUND, OUTCOME_FAILED,
)
from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate, build_correction_application_candidate,
)


def _make_backend():
    return DeterministicFallbackBackend(UnderstandingEngine())


def _minimal_result(**overrides):
    """A minimal, directly-constructed LanguageUnderstandingResult -
    the same required positional fields the class docstring
    documents, with no correction_application_candidate unless
    overridden."""
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


def _valid_record(key="dgo", meaning="dog", **overrides):
    record = {
        "id": 1, "language": "en", "item_type": "correction", "key": key,
        "meaning": meaning, "examples": [], "relationships": [],
        "confidence": 0.9, "source": "user_correction", "source_context": None,
        "learning_method": "explicit_correction", "version": 1,
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
    }
    record.update(overrides)
    return record


def _selected_candidate(record=None):
    record = record if record is not None else _valid_record()
    selection = CorrectionSelectionResult(OUTCOME_SELECTED, correction=record)
    return build_correction_application_candidate(selection)


def _invalid_candidate(outcome=OUTCOME_NOT_FOUND):
    selection = CorrectionSelectionResult(outcome)
    return build_correction_application_candidate(selection)


class TestExistingResultStillWorksWithoutCandidate(unittest.TestCase):
    """1. Existing LanguageUnderstandingResult construction still works
    without a candidate."""

    def test_default_construction_has_none_candidate(self):
        result = _minimal_result()
        self.assertIsNone(result.correction_application_candidate)

    def test_to_dict_includes_the_field_as_none_by_default(self):
        result = _minimal_result()
        as_dict = result.to_dict()
        self.assertIn("correction_application_candidate", as_dict)
        self.assertIsNone(as_dict["correction_application_candidate"])

    def test_real_backend_result_has_no_candidate(self):
        # DeterministicFallbackBackend never sets this field - Prompt
        # 564 does not wire retrieval into the understanding flow.
        backend = _make_backend()
        result = backend.understand("Python is a programming language.")
        self.assertIsNone(result.correction_application_candidate)
        self.assertIsNone(result.to_dict()["correction_application_candidate"])


class TestAResultCanSafelyCarryACandidate(unittest.TestCase):
    """2. A result can safely carry an existing CorrectionApplicationCandidate."""

    def test_valid_candidate_can_be_passed_at_construction(self):
        candidate = _selected_candidate()
        self.assertTrue(candidate.is_valid)
        result = _minimal_result(correction_application_candidate=candidate)
        self.assertIs(result.correction_application_candidate, candidate)

    def test_invalid_candidate_can_also_be_attached(self):
        candidate = _invalid_candidate()
        self.assertFalse(candidate.is_valid)
        result = _minimal_result(correction_application_candidate=candidate)
        self.assertIs(result.correction_application_candidate, candidate)

    def test_candidate_appears_in_to_dict(self):
        candidate = _selected_candidate()
        result = _minimal_result(correction_application_candidate=candidate)
        as_dict = result.to_dict()
        self.assertIsNotNone(as_dict["correction_application_candidate"])
        self.assertEqual(as_dict["correction_application_candidate"], candidate.to_dict())


class TestTheCandidateIsPreservedThroughTheResult(unittest.TestCase):
    """3. The candidate is preserved through the relevant result/adapter
    path."""

    def test_candidate_object_identity_preserved(self):
        candidate = _selected_candidate()
        result = _minimal_result(correction_application_candidate=candidate)
        self.assertIs(result.correction_application_candidate, candidate)
        self.assertTrue(result.correction_application_candidate.is_valid)
        self.assertEqual(
            result.correction_application_candidate.original_expression, "dgo")
        self.assertEqual(
            result.correction_application_candidate.corrected_expression_or_meaning, "dog")

    def test_all_seven_fields_preserved(self):
        record = _valid_record(
            key="teh", meaning="the", language="en", source="user_correction",
            confidence=0.75,
        )
        candidate = _selected_candidate(record)
        result = _minimal_result(correction_application_candidate=candidate)
        as_dict = result.to_dict()["correction_application_candidate"]
        self.assertTrue(as_dict["is_valid"])
        self.assertEqual(as_dict["original_expression"], "teh")
        self.assertEqual(as_dict["corrected_expression_or_meaning"], "the")
        self.assertEqual(as_dict["language"], "en")
        self.assertIsNone(as_dict["locale"])
        self.assertEqual(as_dict["source"], "user_correction")
        self.assertEqual(as_dict["confidence"], 0.75)

    def test_mutating_original_selection_after_attach_does_not_change_result(self):
        record = _valid_record()
        selection = CorrectionSelectionResult(OUTCOME_SELECTED, correction=record)
        candidate = build_correction_application_candidate(selection)
        result = _minimal_result(correction_application_candidate=candidate)
        record["meaning"] = "TAMPERED"
        self.assertEqual(
            result.correction_application_candidate.corrected_expression_or_meaning, "dog")


class TestNoCandidateIsAutomaticallyRetrieved(unittest.TestCase):
    """4. No correction candidate is automatically retrieved merely
    because the field now exists."""

    def test_backend_never_populates_the_field_on_its_own(self):
        backend = _make_backend()
        for text in ("hello", "car", "teh", "Python is a programming language."):
            result = backend.understand(text)
            self.assertIsNone(result.correction_application_candidate)

    def test_constructing_a_result_performs_no_lookup(self):
        # Constructing a result with no candidate never inspects any
        # store, correction data, or selection logic - it is a plain
        # data holder.
        result = _minimal_result(original_input="car")
        self.assertIsNone(result.correction_application_candidate)


class TestExistingCorrectionAcknowledgementUnchanged(unittest.TestCase):
    """5. Existing correction acknowledgement behavior remains
    unchanged."""

    def test_correction_understanding_field_unaffected(self):
        candidate = _selected_candidate()
        result = _minimal_result(
            correction_understanding={"status": "NOT_CORRECTION"},
            correction_application_candidate=candidate,
        )
        self.assertEqual(result.correction_understanding, {"status": "NOT_CORRECTION"})
        self.assertIs(result.correction_application_candidate, candidate)

    def test_correction_lookup_context_field_unaffected(self):
        candidate = _selected_candidate()
        result = _minimal_result(correction_application_candidate=candidate)
        self.assertIsNone(result.correction_lookup_context)

    def test_real_backend_correction_acknowledgement_message_unaffected(self):
        backend = _make_backend()
        result = backend.understand("no I meant car")
        self.assertIsNone(result.correction_application_candidate)


class TestExistingLanguageUnderstandingTestsRemainPassing(unittest.TestCase):
    """6. Existing language-understanding tests remain passing (spot
    check of other fields alongside the new one)."""

    def test_other_fields_unaffected_by_attaching_a_candidate(self):
        candidate = _selected_candidate()
        result = _minimal_result(
            original_input="Python is a programming language.",
            detected_language="en",
            confidence=0.9,
            correction_application_candidate=candidate,
        )
        self.assertEqual(result.original_input, "Python is a programming language.")
        self.assertEqual(result.detected_language, "en")
        self.assertEqual(result.confidence, 0.9)
        self.assertFalse(result.ambiguity)
        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.entities, [])

    def test_real_backend_understanding_otherwise_unaffected(self):
        backend = _make_backend()
        result = backend.understand("Python is a programming language.")
        self.assertTrue(any(e["text"].lower() == "python" for e in result.entities))
        self.assertEqual(result.original_input, "Python is a programming language.")
        self.assertFalse(result.ambiguity)


class TestDeterministicBehavior(unittest.TestCase):
    """7. Identical input/state remains deterministic."""

    def test_same_selection_produces_equal_candidate_and_equal_result_dict(self):
        record = _valid_record()
        candidate_a = _selected_candidate(dict(record))
        candidate_b = _selected_candidate(dict(record))
        self.assertEqual(candidate_a, candidate_b)
        result_a = _minimal_result(correction_application_candidate=candidate_a)
        result_b = _minimal_result(correction_application_candidate=candidate_b)
        self.assertEqual(result_a.to_dict(), result_b.to_dict())

    def test_backend_understanding_deterministic_with_field_present(self):
        backend = _make_backend()
        result_1 = backend.understand("Python is a programming language.")
        result_2 = backend.understand("Python is a programming language.")
        self.assertEqual(result_1.to_dict(), result_2.to_dict())


class TestNoCoreStoreAccessed(unittest.TestCase):
    """8. No Core database/store is accessed merely by constructing a
    language-understanding result."""

    def test_construction_with_candidate_touches_no_storage_module(self):
        # If constructing/attaching a candidate ever reached into a
        # store, importing language_understanding_result alone would
        # not be safe without Core configured. It already is safe
        # today (used stand-alone throughout this file); this test
        # documents that constructing a result, with or without a
        # candidate, still requires no store, database path, or Core
        # instance of any kind.
        candidate = _selected_candidate()
        result = LanguageUnderstandingResult(
            "car", "en", "car", "unknown", [], [], None, None, 0.5, False, False,
            correction_application_candidate=candidate,
        )
        self.assertIs(result.correction_application_candidate, candidate)


class TestExistingCallersRemainBackwardsCompatible(unittest.TestCase):
    """Backward compatibility: every existing constructor/caller keeps
    working exactly as before."""

    def test_positional_construction_without_new_kwarg_still_works(self):
        # Same positional signature every pre-Prompt-564 caller used.
        result = LanguageUnderstandingResult(
            "hi", "en", "hi", "unknown", [], [], None, None, 0.5, False, False,
        )
        self.assertIsNone(result.correction_application_candidate)
        self.assertIn("correction_application_candidate", result.to_dict())

    def test_existing_keyword_only_fields_still_work_together(self):
        result = _minimal_result(
            warnings=["empty_input"],
            source_backend="deterministic_fallback",
            correction_understanding={"status": "NOT_CORRECTION"},
        )
        self.assertEqual(result.warnings, ["empty_input"])
        self.assertEqual(result.source_backend, "deterministic_fallback")
        self.assertEqual(result.correction_understanding, {"status": "NOT_CORRECTION"})
        self.assertIsNone(result.correction_application_candidate)

    def test_correction_lookup_context_and_candidate_coexist(self):
        from language_intelligence.correction_lookup_context import (
            build_correction_lookup_context,
        )
        from language_intelligence.correction_learning_exact_lookup_result import (
            CorrectionLearningExactLookupResult, STATUS_FOUND,
        )
        lookup_result = CorrectionLearningExactLookupResult(
            status=STATUS_FOUND, original_expression="dgo",
            records=[{"corrected_expression": "dog", "language": "en",
                      "source": "user_correction"}],
        )
        lookup_context = build_correction_lookup_context(lookup_result)
        candidate = _selected_candidate()
        result = _minimal_result(
            correction_lookup_context=lookup_context,
            correction_application_candidate=candidate,
        )
        self.assertIs(result.correction_lookup_context, lookup_context)
        self.assertIs(result.correction_application_candidate, candidate)
        as_dict = result.to_dict()
        self.assertIsNotNone(as_dict["correction_lookup_context"])
        self.assertIsNotNone(as_dict["correction_application_candidate"])

    def test_backend_produced_result_construction_unaffected(self):
        backend = _make_backend()
        result = backend.understand("What is Python?")
        self.assertIsInstance(result, LanguageUnderstandingResult)
        self.assertIn("correction_application_candidate", result.to_dict())

    def test_ambiguous_and_failed_outcomes_produce_invalid_non_fabricated_candidate(self):
        for outcome in (OUTCOME_AMBIGUOUS, OUTCOME_NOT_FOUND, OUTCOME_FAILED):
            candidate = _invalid_candidate(outcome)
            self.assertFalse(candidate.is_valid)
            result = _minimal_result(correction_application_candidate=candidate)
            self.assertFalse(result.correction_application_candidate.is_valid)
            self.assertIsNone(result.correction_application_candidate.original_expression)


if __name__ == "__main__":
    unittest.main()
