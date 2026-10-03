"""
Tests for Prompt 566 - Define a Safe Deterministic Correction
Retrieval Trigger.

Covers the eleven areas Prompt 566 section 6 lists:
    1. A clearly structured correction-like input produces the
       expected trigger representation.
    2. An ordinary unrelated message does not trigger correction
       retrieval.
    3. A generic "I mean" sentence does not automatically trigger it
       without sufficient evidence.
    4. An ambiguous correction remains conservative.
    5. An unresolved correction remains conservative.
    6. The trigger is deterministic.
    7. The trigger contains only the intended minimal information.
    8. The trigger itself performs no storage/database access.
    9. Existing correction acknowledgement behavior remains unchanged.
    10. Existing `LanguageUnderstandingResult` behavior remains
        unchanged.
    11. Existing Prompt 565 adapter tests remain unchanged and
        passing (see test_correction_retrieval_understanding_adapter_
        prompt565.py, run unmodified as part of the full suite).

Run directly:
    python -m unittest tests.test_correction_retrieval_trigger_prompt566 -v
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
from language_intelligence.correction_understanding import (
    build_correction_understanding,
    CorrectionUnderstandingResult,
    STATUS_RESOLVED,
    STATUS_AMBIGUOUS,
    STATUS_UNRESOLVED,
    STATUS_NOT_CORRECTION,
)
from language_intelligence.correction_retrieval_trigger import (
    CorrectionRetrievalTrigger,
    build_correction_retrieval_trigger,
    REASON_RESOLVED_CORRECTION_IDENTIFIED,
    REASON_NO_CORRECTION_SIGNAL,
    REASON_AMBIGUOUS_CORRECTION,
    REASON_UNRESOLVED_CORRECTION,
    REASON_NOT_CORRECTION,
    REASON_INVALID_INPUT,
    ALL_REASONS,
)


def _understand(text):
    """Run the real, unchanged Understanding Engine + Deterministic
    Fallback Backend chain and return the resulting
    `LanguageUnderstandingResult` - the SAME object shape
    `outcome.correction_understanding` is read from elsewhere in this
    project."""
    engine = UnderstandingEngine()
    backend = DeterministicFallbackBackend(engine)
    return backend.understand(text)


class TestResolvedCorrectionTriggers(unittest.TestCase):
    """Area 1: a clearly structured correction-like input produces the
    expected trigger representation."""

    def test_fixed_marker_message_produces_attempt_trigger(self):
        outcome = _understand("not dgo, I mean dog.")
        self.assertIsNotNone(outcome.correction_understanding)
        self.assertEqual(outcome.correction_understanding["status"], STATUS_RESOLVED)

        trigger = build_correction_retrieval_trigger(outcome.correction_understanding)

        self.assertTrue(trigger.should_attempt)
        self.assertEqual(trigger.reason, REASON_RESOLVED_CORRECTION_IDENTIFIED)
        self.assertEqual(trigger.original_expression, "dgo")

    def test_resolved_result_object_directly_produces_attempt_trigger(self):
        resolved = build_correction_understanding(
            "not dgo, I mean dog.", original_expression="dgo",
            corrected_expression="dog", language="en")
        self.assertEqual(resolved.status, STATUS_RESOLVED)

        trigger = build_correction_retrieval_trigger(resolved)

        self.assertTrue(trigger.should_attempt)
        self.assertEqual(trigger.reason, REASON_RESOLVED_CORRECTION_IDENTIFIED)
        self.assertEqual(trigger.original_expression, "dgo")
        self.assertEqual(trigger.language, "en")

    def test_resolved_via_corrected_meaning_instead_of_expression(self):
        resolved = build_correction_understanding(
            "not dgo, I mean a small furry animal", original_expression="dgo",
            corrected_meaning="a small furry animal")
        self.assertEqual(resolved.status, STATUS_RESOLVED)

        trigger = build_correction_retrieval_trigger(resolved)

        self.assertTrue(trigger.should_attempt)
        self.assertEqual(trigger.original_expression, "dgo")


class TestOrdinaryMessagesDoNotTrigger(unittest.TestCase):
    """Area 2: an ordinary unrelated message does not trigger
    correction retrieval."""

    def test_ordinary_message_has_no_correction_candidate(self):
        outcome = _understand("What is the weather like today?")
        self.assertIsNone(outcome.correction_understanding)

    def test_none_input_does_not_attempt(self):
        trigger = build_correction_retrieval_trigger(None)

        self.assertFalse(trigger.should_attempt)
        self.assertEqual(trigger.reason, REASON_NO_CORRECTION_SIGNAL)
        self.assertIsNone(trigger.original_expression)
        self.assertIsNone(trigger.language)

    def test_various_ordinary_messages_never_attempt(self):
        for text in (
            "Hello, how are you?",
            "Tell me a story about a fox.",
            "Please schedule a meeting for tomorrow.",
            "I like dogs.",
        ):
            with self.subTest(text=text):
                outcome = _understand(text)
                trigger = build_correction_retrieval_trigger(
                    outcome.correction_understanding)
                self.assertFalse(trigger.should_attempt)


class TestGenericConversationalPhrasesDoNotTrigger(unittest.TestCase):
    """Area 3: a generic "I mean" sentence does not automatically
    trigger it without sufficient evidence - Prompt 566 section 4's
    own named examples."""

    def test_named_non_triggering_examples(self):
        examples = (
            "I mean this is interesting.",
            "What do you mean?",
            "I meant to ask you something.",
            "Actually, tell me about dogs.",
            "No, that's not what I asked",
        )
        for text in examples:
            with self.subTest(text=text):
                outcome = _understand(text)
                # None of these match the one fixed explicit marker,
                # so no correction candidate/understanding is ever
                # produced for them in the first place.
                self.assertIsNone(outcome.correction_understanding)

                trigger = build_correction_retrieval_trigger(
                    outcome.correction_understanding)
                self.assertFalse(trigger.should_attempt)
                self.assertEqual(trigger.reason, REASON_NO_CORRECTION_SIGNAL)


class TestAmbiguousCorrectionStaysConservative(unittest.TestCase):
    """Area 4: an ambiguous correction remains conservative."""

    def test_ambiguous_status_does_not_attempt(self):
        ambiguous = build_correction_understanding(
            "not dgo, I mean dog or doge",
            original_expression="dgo",
            corrected_candidates=["dog", "doge"])
        self.assertEqual(ambiguous.status, STATUS_AMBIGUOUS)

        trigger = build_correction_retrieval_trigger(ambiguous)

        self.assertFalse(trigger.should_attempt)
        self.assertEqual(trigger.reason, REASON_AMBIGUOUS_CORRECTION)
        self.assertIsNone(trigger.original_expression)
        self.assertIsNone(trigger.language)


class TestUnresolvedCorrectionStaysConservative(unittest.TestCase):
    """Area 5: an unresolved correction remains conservative."""

    def test_unresolved_status_does_not_attempt(self):
        unresolved = build_correction_understanding(
            "not dgo", original_expression="dgo")
        self.assertEqual(unresolved.status, STATUS_UNRESOLVED)

        trigger = build_correction_retrieval_trigger(unresolved)

        self.assertFalse(trigger.should_attempt)
        self.assertEqual(trigger.reason, REASON_UNRESOLVED_CORRECTION)
        self.assertIsNone(trigger.original_expression)
        self.assertIsNone(trigger.language)

    def test_not_correction_status_does_not_attempt(self):
        not_correction = build_correction_understanding("hello there")
        self.assertEqual(not_correction.status, STATUS_NOT_CORRECTION)

        trigger = build_correction_retrieval_trigger(not_correction)

        self.assertFalse(trigger.should_attempt)
        self.assertEqual(trigger.reason, REASON_NOT_CORRECTION)


class TestDeterminism(unittest.TestCase):
    """Area 6: the trigger is deterministic."""

    def test_same_dict_input_produces_equal_trigger(self):
        data = {
            "status": STATUS_RESOLVED,
            "original_expression": "dgo",
            "corrected_expression": "dog",
            "corrected_meaning": None,
            "language": "en",
            "locale": None,
            "source_text": "not dgo, I mean dog.",
            "confidence": 0.0,
        }
        trigger_one = build_correction_retrieval_trigger(data)
        trigger_two = build_correction_retrieval_trigger(dict(data))

        self.assertEqual(trigger_one, trigger_two)
        self.assertEqual(trigger_one.to_dict(), trigger_two.to_dict())

    def test_repeated_calls_with_none_are_equal(self):
        self.assertEqual(
            build_correction_retrieval_trigger(None),
            build_correction_retrieval_trigger(None))

    def test_repeated_calls_with_result_object_are_equal(self):
        resolved = build_correction_understanding(
            "not dgo, I mean dog.", original_expression="dgo",
            corrected_expression="dog")
        trigger_one = build_correction_retrieval_trigger(resolved)
        trigger_two = build_correction_retrieval_trigger(resolved)
        self.assertEqual(trigger_one, trigger_two)


class TestMinimalContract(unittest.TestCase):
    """Area 7: the trigger contains only the intended minimal
    information."""

    def test_only_four_fields_exist(self):
        trigger = build_correction_retrieval_trigger(None)
        self.assertEqual(
            set(trigger.to_dict().keys()),
            {"should_attempt", "reason", "original_expression", "language"})
        self.assertEqual(
            CorrectionRetrievalTrigger.__slots__,
            ("should_attempt", "reason", "original_expression", "language"))

    def test_negative_trigger_carries_no_lookup_information(self):
        for status in (STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION):
            with self.subTest(status=status):
                data = {"status": status, "original_expression": "dgo",
                         "language": "en"}
                trigger = build_correction_retrieval_trigger(data)
                self.assertFalse(trigger.should_attempt)
                self.assertIsNone(trigger.original_expression)
                self.assertIsNone(trigger.language)

    def test_reason_is_always_one_of_the_known_constants(self):
        for candidate in (
            None,
            {"status": STATUS_RESOLVED, "original_expression": "dgo"},
            {"status": STATUS_AMBIGUOUS},
            {"status": STATUS_UNRESOLVED},
            {"status": STATUS_NOT_CORRECTION},
            {"status": "SOMETHING_UNKNOWN"},
            {},
        ):
            with self.subTest(candidate=candidate):
                trigger = build_correction_retrieval_trigger(candidate)
                self.assertIn(trigger.reason, ALL_REASONS)

    def test_invalid_type_raises_type_error(self):
        with self.assertRaises(TypeError):
            build_correction_retrieval_trigger(12345)
        with self.assertRaises(TypeError):
            build_correction_retrieval_trigger("not dgo, I mean dog.")

    def test_malformed_resolved_without_original_expression_is_conservative(self):
        data = {"status": STATUS_RESOLVED, "original_expression": None}
        trigger = build_correction_retrieval_trigger(data)
        self.assertFalse(trigger.should_attempt)
        self.assertEqual(trigger.reason, REASON_INVALID_INPUT)

    def test_missing_status_key_is_conservative(self):
        trigger = build_correction_retrieval_trigger({})
        self.assertFalse(trigger.should_attempt)
        self.assertEqual(trigger.reason, REASON_INVALID_INPUT)

    def test_unknown_status_value_is_conservative(self):
        trigger = build_correction_retrieval_trigger({"status": "NOT_A_REAL_STATUS"})
        self.assertFalse(trigger.should_attempt)
        self.assertEqual(trigger.reason, REASON_INVALID_INPUT)

    def test_copy_produces_an_equal_independent_object(self):
        resolved = build_correction_understanding(
            "not dgo, I mean dog.", original_expression="dgo",
            corrected_expression="dog")
        trigger = build_correction_retrieval_trigger(resolved)
        copied = trigger.copy()
        self.assertEqual(trigger, copied)
        self.assertIsNot(trigger, copied)

    def test_invalid_reason_construction_raises(self):
        with self.assertRaises(ValueError):
            CorrectionRetrievalTrigger(should_attempt=True, reason="not_a_real_reason")


class TestZeroRetrievalStorageSideEffects(unittest.TestCase):
    """Area 8: the trigger itself performs no storage/database
    access."""

    def test_module_does_not_import_retrieval_chain(self):
        import ast
        import language_intelligence.correction_retrieval_trigger as trigger_module

        source_path = trigger_module.__file__
        with open(source_path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=source_path)

        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        forbidden_imports = (
            "language_intelligence.correction_learning_exact_lookup_result",
            "language_intelligence.correction_lookup_context",
            "language_intelligence.correction_lookup_selection",
            "language_intelligence.correction_application_candidate",
            "language_intelligence.correction_retrieval_understanding_adapter",
            "language_intelligence.language_learning_store",
        )
        for forbidden in forbidden_imports:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, imported_modules)

        # The only real import this module makes is the existing
        # CorrectionUnderstandingResult/status-constant module.
        self.assertEqual(
            imported_modules, {"language_intelligence.correction_understanding"})

    def test_building_a_trigger_touches_no_store_argument(self):
        # build_correction_retrieval_trigger() takes exactly one
        # argument (correction_understanding) - there is no store,
        # database, or connection parameter to pass in the first
        # place.
        import inspect
        signature = inspect.signature(build_correction_retrieval_trigger)
        self.assertEqual(list(signature.parameters.keys()), ["correction_understanding"])


class TestExistingCorrectionAcknowledgementUnaffected(unittest.TestCase):
    """Area 9: existing correction acknowledgement behavior remains
    unchanged."""

    def test_resolved_correction_message_response_unaffected(self):
        outcome = _understand("not dgo, I mean dog.")
        self.assertIsNotNone(outcome.correction_understanding)
        self.assertEqual(outcome.correction_understanding["status"], STATUS_RESOLVED)
        self.assertEqual(outcome.correction_understanding["original_expression"], "dgo")
        self.assertEqual(outcome.correction_understanding["corrected_expression"], "dog")
        # Building a trigger from this result does not mutate it.
        before = dict(outcome.correction_understanding)
        build_correction_retrieval_trigger(outcome.correction_understanding)
        self.assertEqual(outcome.correction_understanding, before)


class TestLanguageUnderstandingResultUnaffected(unittest.TestCase):
    """Area 10: existing `LanguageUnderstandingResult` behavior
    remains unchanged - this module adds no new field to it and never
    imports it."""

    def test_correction_retrieval_trigger_module_does_not_import_language_understanding_result(self):
        import ast
        import language_intelligence.correction_retrieval_trigger as trigger_module

        source_path = trigger_module.__file__
        with open(source_path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=source_path)

        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        self.assertNotIn(
            "language_intelligence.language_understanding_result", imported_modules)

    def test_ordinary_understanding_result_shape_unaffected(self):
        outcome = _understand("What is the weather like today?")
        as_dict = outcome.to_dict()
        self.assertIn("correction_understanding", as_dict)
        self.assertIn("correction_lookup_context", as_dict)
        self.assertIn("correction_application_candidate", as_dict)
        self.assertIsNone(as_dict["correction_lookup_context"])
        self.assertIsNone(as_dict["correction_application_candidate"])


if __name__ == "__main__":
    unittest.main()
