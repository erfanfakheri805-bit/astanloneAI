"""
Tests for Prompt 466 - Expose Correction Lookup Context in Language
Understanding.

Covers the small, additive integration that exposes Prompt 465's
`CorrectionLookupContext`
(language_intelligence/correction_lookup_context.py) through the
existing `LanguageUnderstandingResult`
(language_intelligence/language_understanding_result.py):

    CorrectionLookupContext (Prompt 465, unchanged)
        -> LanguageUnderstandingResult.correction_lookup_context
           (Prompt 466, THIS module's subject - dict or None)

This field is purely informational: nothing in this test file (or in
the change under test) performs a correction lookup automatically,
applies a stored correction, or modifies the original message. A
`CorrectionLookupContext` is built directly (Prompt 465's own,
unchanged `build_correction_lookup_context()` /
`CorrectionLearningExactLookupResult`) and attached to a
`LanguageUnderstandingResult` by hand, exactly as a future, separately
scoped caller would.

Run directly:
    python -m unittest tests.test_correction_lookup_context_exposure -v
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
from language_intelligence.correction_lookup_context import (
    CorrectionLookupContext, build_correction_lookup_context,
)
from language_intelligence.correction_learning_exact_lookup_result import (
    CorrectionLearningExactLookupResult,
    STATUS_FOUND, STATUS_NOT_FOUND, STATUS_FAILED,
)


def _make_backend():
    return DeterministicFallbackBackend(UnderstandingEngine())


def _minimal_result(**overrides):
    """A minimal, directly-constructed LanguageUnderstandingResult -
    the same required positional fields the class docstring
    documents, with no correction_lookup_context unless overridden."""
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


def _found_lookup_result(records=None):
    return CorrectionLearningExactLookupResult(
        status=STATUS_FOUND,
        original_expression="dgo",
        records=records if records is not None else [
            {"corrected_expression": "dog", "language": "en", "source": "user_correction"},
        ],
    )


def _not_found_lookup_result():
    return CorrectionLearningExactLookupResult(
        status=STATUS_NOT_FOUND, original_expression="dgo", records=[],
    )


def _failed_lookup_result():
    return CorrectionLearningExactLookupResult(
        status=STATUS_FAILED, original_expression="dgo", records=[],
        reason="storage_unavailable",
    )


class TestExistingResultStillWorksWithoutCorrectionContext(unittest.TestCase):
    """Existing LanguageUnderstandingResult still works without a
    correction context - default backward compatibility."""

    def test_default_construction_has_none_correction_lookup_context(self):
        result = _minimal_result()
        self.assertIsNone(result.correction_lookup_context)

    def test_to_dict_includes_the_field_as_none_by_default(self):
        result = _minimal_result()
        as_dict = result.to_dict()
        self.assertIn("correction_lookup_context", as_dict)
        self.assertIsNone(as_dict["correction_lookup_context"])

    def test_real_backend_result_has_no_correction_lookup_context(self):
        # DeterministicFallbackBackend never sets this field - Prompt
        # 466 does not wire a lookup into the understanding flow.
        backend = _make_backend()
        result = backend.understand("Python is a programming language.")
        self.assertIsNone(result.correction_lookup_context)
        self.assertIsNone(result.to_dict()["correction_lookup_context"])


class TestACorrectionLookupContextCanBeAttached(unittest.TestCase):
    """A CorrectionLookupContext can be attached."""

    def test_context_can_be_passed_at_construction(self):
        context = build_correction_lookup_context(_found_lookup_result())
        result = _minimal_result(correction_lookup_context=context)
        self.assertIs(result.correction_lookup_context, context)

    def test_context_appears_in_to_dict(self):
        context = build_correction_lookup_context(_found_lookup_result())
        result = _minimal_result(correction_lookup_context=context)
        as_dict = result.to_dict()
        self.assertIsNotNone(as_dict["correction_lookup_context"])
        self.assertEqual(as_dict["correction_lookup_context"], context.to_dict())


class TestTheAttachedContextIsPreservedExactly(unittest.TestCase):
    """The attached context is preserved exactly - not modified."""

    def test_attached_context_object_identity_preserved(self):
        context = build_correction_lookup_context(_found_lookup_result())
        result = _minimal_result(correction_lookup_context=context)
        self.assertIs(result.correction_lookup_context, context)
        # constructing the result must not mutate the context at all
        self.assertEqual(result.correction_lookup_context.status, STATUS_FOUND)
        self.assertEqual(
            result.correction_lookup_context.original_expression, "dgo")

    def test_records_are_preserved_without_ranking_or_reduction(self):
        records = [
            {"corrected_expression": "dog", "language": "en", "source": "user_correction"},
            {"corrected_expression": "dogue", "language": "fr", "source": "user_correction"},
        ]
        context = build_correction_lookup_context(_found_lookup_result(records=records))
        result = _minimal_result(correction_lookup_context=context)
        self.assertEqual(len(result.correction_lookup_context.records), 2)
        self.assertEqual(
            [r["corrected_expression"] for r in result.correction_lookup_context.records],
            ["dog", "dogue"])

    def test_mutating_original_lookup_result_after_attach_does_not_change_result(self):
        lookup_result = _found_lookup_result()
        context = build_correction_lookup_context(lookup_result)
        result = _minimal_result(correction_lookup_context=context)
        lookup_result.records[0]["corrected_expression"] = "TAMPERED"
        self.assertEqual(
            result.correction_lookup_context.records[0]["corrected_expression"], "dog")


class TestFoundContextIsPreserved(unittest.TestCase):
    """FOUND context is preserved."""

    def test_found_status_and_fields_preserved(self):
        context = build_correction_lookup_context(_found_lookup_result())
        result = _minimal_result(correction_lookup_context=context)
        as_dict = result.to_dict()["correction_lookup_context"]
        self.assertEqual(as_dict["status"], STATUS_FOUND)
        self.assertEqual(as_dict["original_expression"], "dgo")
        self.assertEqual(len(as_dict["records"]), 1)
        self.assertEqual(as_dict["language"], "en")
        self.assertEqual(as_dict["source"], "user_correction")
        self.assertIsNone(as_dict["reason"])
        self.assertTrue(result.correction_lookup_context.has_match)


class TestNotFoundContextIsPreserved(unittest.TestCase):
    """NOT_FOUND context is preserved."""

    def test_not_found_status_and_empty_fields_preserved(self):
        context = build_correction_lookup_context(_not_found_lookup_result())
        result = _minimal_result(correction_lookup_context=context)
        as_dict = result.to_dict()["correction_lookup_context"]
        self.assertEqual(as_dict["status"], STATUS_NOT_FOUND)
        self.assertEqual(as_dict["original_expression"], "dgo")
        self.assertEqual(as_dict["records"], [])
        self.assertIsNone(as_dict["language"])
        self.assertIsNone(as_dict["source"])
        self.assertIsNone(as_dict["reason"])
        self.assertFalse(result.correction_lookup_context.has_match)


class TestFailedContextIsPreserved(unittest.TestCase):
    """FAILED context is preserved."""

    def test_failed_status_and_reason_preserved(self):
        context = build_correction_lookup_context(_failed_lookup_result())
        result = _minimal_result(correction_lookup_context=context)
        as_dict = result.to_dict()["correction_lookup_context"]
        self.assertEqual(as_dict["status"], STATUS_FAILED)
        self.assertEqual(as_dict["records"], [])
        self.assertIsNone(as_dict["language"])
        self.assertIsNone(as_dict["source"])
        self.assertEqual(as_dict["reason"], "storage_unavailable")
        self.assertFalse(result.correction_lookup_context.has_match)


class TestExistingLanguageUnderstandingFieldsRemainUnchanged(unittest.TestCase):
    """Existing LanguageUnderstandingResult fields remain unchanged."""

    def test_other_fields_unaffected_by_attaching_a_context(self):
        context = build_correction_lookup_context(_found_lookup_result())
        result = _minimal_result(
            original_input="Python is a programming language.",
            detected_language="en",
            confidence=0.9,
            correction_lookup_context=context,
        )
        self.assertEqual(result.original_input, "Python is a programming language.")
        self.assertEqual(result.detected_language, "en")
        self.assertEqual(result.confidence, 0.9)
        self.assertFalse(result.ambiguity)
        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.entities, [])
        self.assertIsNone(result.correction_understanding)

    def test_real_backend_understanding_otherwise_unaffected(self):
        backend = _make_backend()
        result = backend.understand("Python is a programming language.")
        self.assertTrue(any(e["text"].lower() == "python" for e in result.entities))
        self.assertEqual(result.original_input, "Python is a programming language.")
        self.assertFalse(result.ambiguity)
        self.assertIsNone(result.correction_lookup_context)


class TestExistingCallersRemainBackwardsCompatible(unittest.TestCase):
    """Existing callers remain backwards compatible."""

    def test_positional_construction_without_new_kwarg_still_works(self):
        # Same positional signature every pre-Prompt-466 caller used.
        result = LanguageUnderstandingResult(
            "hi", "en", "hi", "unknown", [], [], None, None, 0.5, False, False,
        )
        self.assertIsNone(result.correction_lookup_context)
        self.assertIn("correction_lookup_context", result.to_dict())

    def test_existing_keyword_only_fields_still_work_together(self):
        result = _minimal_result(
            warnings=["empty_input"],
            source_backend="deterministic_fallback",
            correction_understanding={"status": "NOT_CORRECTION"},
        )
        self.assertEqual(result.warnings, ["empty_input"])
        self.assertEqual(result.source_backend, "deterministic_fallback")
        self.assertEqual(result.correction_understanding, {"status": "NOT_CORRECTION"})
        self.assertIsNone(result.correction_lookup_context)

    def test_backend_produced_result_construction_unaffected(self):
        backend = _make_backend()
        result = backend.understand("What is Python?")
        self.assertIsInstance(result, LanguageUnderstandingResult)
        self.assertIn("correction_lookup_context", result.to_dict())


if __name__ == "__main__":
    unittest.main()
