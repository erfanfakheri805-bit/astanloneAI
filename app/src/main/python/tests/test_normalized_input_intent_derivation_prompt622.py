"""
Tests for Prompt 622 - Section 2: Language Intelligence and Request
Understanding - verifying the contract between normalized request text
and the existing intent-classification result.

Trace performed by this prompt:

    UnderstandingEngine.understand()          (understanding/engine.py)
      -> normalize(raw_text)                  (understanding/
         normalization.py) produces NormalizationResult.normalized_text
      -> every later stage in understand() (language detection,
         tokenization, sentence-type analysis) runs on that SAME
         `normalized_text` local variable
      -> UnderstandingResult.normalized_text  (understanding/result.py) -
         that same value, unchanged
      -> DeterministicFallbackBackend.understand()
         (language_intelligence/deterministic_fallback_backend.py):

             result = self._understanding_engine.understand(raw_text, ...)
             intent = self._classify_intent(
                 result.normalized_text, result.sentence_type)
             ...
             return LanguageUnderstandingResult(
                 ...,
                 normalized_input=result.normalized_text,
                 intent=intent,
                 ...,
             )

Finding (confirmed by direct inspection of both modules above, and by
the spy-based tests in this file): `result.normalized_text` is read
into `intent` and into `normalized_input` from the exact same
attribute access on the exact same `result` object, in the same method
call, with nothing in between that could re-derive or re-normalize
either value. `_classify_intent` consumes precisely the value exposed
as `LanguageUnderstandingResult.normalized_input` - never a
hand-me-down copy, never a second normalization pass.

Per this prompt's requirement 3, the existing contract is already
correct, so THIS FILE ADDS NO PRODUCTION CHANGES - it only locks the
relationship down with focused regression coverage, distinct from
Prompt 621's own coverage of the same finding: this file's central
technique is monkeypatching the `_classify_intent` boundary itself
(requirement 9) to directly observe, during a REAL `understand()` call,
exactly what value and object reach the classifier - rather than only
recomputing intent separately afterward.

Run directly:
    python -m unittest tests.test_normalized_input_intent_derivation_prompt622 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine
from understanding.sentence_analysis import (
    SENTENCE_QUESTION, SENTENCE_STATEMENT, SENTENCE_COMMAND, SENTENCE_UNKNOWN,
)

from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_understanding_result import (
    LanguageUnderstandingResult, INTENT_ASK_QUESTION, INTENT_PROVIDE_INFORMATION,
    INTENT_REQUEST_ACTION, INTENT_GOAL_REQUEST, INTENT_UNKNOWN,
)


def _make_backend():
    return DeterministicFallbackBackend(UnderstandingEngine())


class _SpyingClassifyIntent:
    """Context manager that replaces
    `DeterministicFallbackBackend._classify_intent` with a spy that
    records the exact arguments it was called with (as held object
    references, not re-derived copies) while still delegating to the
    real implementation, then restores the original staticmethod on
    exit. Used to observe the real request-understanding/intent
    boundary from inside an ordinary `understand()` call, per this
    prompt's requirement to spy/monkeypatch that boundary directly."""

    def __init__(self):
        self.calls = []
        self._original = None

    def __enter__(self):
        self._original = DeterministicFallbackBackend.__dict__["_classify_intent"]
        real = self._original.__func__

        def spy(normalized_text, sentence_type):
            self.calls.append((normalized_text, sentence_type))
            return real(normalized_text, sentence_type)

        DeterministicFallbackBackend._classify_intent = staticmethod(spy)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        DeterministicFallbackBackend._classify_intent = self._original
        return False


class _RequestUnderstandingCase(unittest.TestCase):
    def _understand(self, raw_text):
        return _make_backend().understand(raw_text)


# ======================================================================
class TestClassifierReceivesExactNormalizedInputViaSpy(_RequestUnderstandingCase):
    """Spy on the real `_classify_intent` boundary during an ordinary
    `understand()` call and confirm it is invoked with exactly the
    value that ends up on `normalized_input` - the same object, held
    and compared, not just an equal-looking recomputation."""

    def test_spy_observes_same_object_as_normalized_input_when_text_changes(self):
        raw = "   what   is   python?   "
        with _SpyingClassifyIntent() as spy:
            understanding = _make_backend().understand(raw)
        self.assertEqual(len(spy.calls), 1)
        observed_text, observed_sentence_type = spy.calls[0]
        # Held-reference identity, not id(): the same string object
        # travels from the classifier call to the exposed field.
        self.assertIs(observed_text, understanding.normalized_input)
        self.assertEqual(observed_text, "what is python?")
        self.assertEqual(observed_sentence_type, SENTENCE_QUESTION)
        self.assertEqual(understanding.intent, INTENT_ASK_QUESTION)

    def test_spy_observes_same_object_as_normalized_input_when_text_unchanged(self):
        raw = "python is a programming language."
        with _SpyingClassifyIntent() as spy:
            understanding = _make_backend().understand(raw)
        observed_text, _ = spy.calls[0]
        self.assertIs(observed_text, understanding.normalized_input)
        self.assertEqual(understanding.normalized_input, raw)
        self.assertEqual(understanding.intent, INTENT_PROVIDE_INFORMATION)

    def test_spy_sees_goal_oriented_intent_category(self):
        raw = "I need to refactor this function."
        with _SpyingClassifyIntent() as spy:
            understanding = _make_backend().understand(raw)
        observed_text, observed_sentence_type = spy.calls[0]
        self.assertIs(observed_text, understanding.normalized_input)
        self.assertEqual(observed_sentence_type, SENTENCE_STATEMENT)
        self.assertEqual(understanding.intent, INTENT_GOAL_REQUEST)

    def test_spy_sees_request_action_intent_category(self):
        raw = "Explain indentation."
        with _SpyingClassifyIntent() as spy:
            understanding = _make_backend().understand(raw)
        observed_text, observed_sentence_type = spy.calls[0]
        self.assertIs(observed_text, understanding.normalized_input)
        self.assertEqual(observed_sentence_type, SENTENCE_COMMAND)
        self.assertEqual(understanding.intent, INTENT_REQUEST_ACTION)

    def test_spy_sees_unknown_intent_category_for_empty_input(self):
        with _SpyingClassifyIntent() as spy:
            understanding = _make_backend().understand("")
        # Empty normalized text short-circuits before sentence analysis
        # runs, but the classifier boundary is still the sole source of
        # `intent`, called (per _classify_intent's own contract) with
        # whatever normalized_text/sentence_type the engine produced.
        self.assertEqual(len(spy.calls), 1)
        observed_text, observed_sentence_type = spy.calls[0]
        self.assertIs(observed_text, understanding.normalized_input)
        self.assertEqual(observed_text, "")
        self.assertEqual(observed_sentence_type, SENTENCE_UNKNOWN)
        self.assertEqual(understanding.intent, INTENT_UNKNOWN)

    def test_spy_called_exactly_once_per_understand_call(self):
        """The classifier boundary is consulted exactly once per
        `understand()` call - never a second, competing classification
        pass over the same or a re-derived text."""
        with _SpyingClassifyIntent() as spy:
            _make_backend().understand("What is Python?")
        self.assertEqual(len(spy.calls), 1)


# ======================================================================
class TestOriginalInputPreservedAlongsideSpiedClassification(_RequestUnderstandingCase):
    """`original_input` must remain the untouched raw text even while
    the classifier boundary is being observed - confirms the spy does
    not disturb the original-input/normalized-input separation."""

    def test_original_input_untouched_while_spying(self):
        raw = "   What   is   Python?   "
        with _SpyingClassifyIntent():
            understanding = _make_backend().understand(raw)
        self.assertEqual(understanding.original_input, raw)
        self.assertNotEqual(understanding.original_input, understanding.normalized_input)

    def test_original_input_equals_normalized_input_when_already_clean(self):
        raw = "what is python"
        with _SpyingClassifyIntent():
            understanding = _make_backend().understand(raw)
        self.assertEqual(understanding.original_input, raw)
        self.assertEqual(understanding.normalized_input, raw)


# ======================================================================
class TestMinimalAndEmptyInputClassification(_RequestUnderstandingCase):
    """Empty/minimal input must resolve deterministically to
    INTENT_UNKNOWN without the classifier boundary ever raising."""

    def test_none_input(self):
        understanding = self._understand(None)
        self.assertEqual(understanding.original_input, "")
        self.assertEqual(understanding.normalized_input, "")
        self.assertEqual(understanding.intent, INTENT_UNKNOWN)

    def test_whitespace_only_input(self):
        understanding = self._understand("   \n\t  ")
        self.assertEqual(understanding.normalized_input, "")
        self.assertEqual(understanding.intent, INTENT_UNKNOWN)

    def test_single_character_input(self):
        with _SpyingClassifyIntent() as spy:
            understanding = _make_backend().understand("?")
        # Whatever sentence type a single "?" resolves to, the
        # classifier boundary still receives exactly normalized_input.
        observed_text, _ = spy.calls[0]
        self.assertIs(observed_text, understanding.normalized_input)
        self.assertEqual(understanding.normalized_input, "?")
        self.assertIn(understanding.intent, (INTENT_ASK_QUESTION, INTENT_UNKNOWN))


# ======================================================================
class TestDeterminismAcrossRepeatedCalls(_RequestUnderstandingCase):
    """Repeated calls with the same raw text must yield the exact same
    normalized_input value and the exact same intent every time - the
    classifier boundary is a pure function of its two arguments."""

    def test_repeated_calls_yield_identical_results(self):
        raw = "  I need to   refactor   this function.  "
        results = [self._understand(raw) for _ in range(5)]
        normalized_values = {r.normalized_input for r in results}
        intents = {r.intent for r in results}
        self.assertEqual(len(normalized_values), 1)
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents.pop(), INTENT_GOAL_REQUEST)

    def test_spy_call_count_stable_across_repeated_understand_calls(self):
        raw = "What is Python?"
        backend = _make_backend()
        with _SpyingClassifyIntent() as spy:
            for _ in range(3):
                backend.understand(raw)
        self.assertEqual(len(spy.calls), 3)
        self.assertTrue(all(text == "What is Python?" for text, _ in spy.calls))
        self.assertTrue(all(st == SENTENCE_QUESTION for _, st in spy.calls))


# ======================================================================
class TestLegacyResultConstructionRemainsCompatible(_RequestUnderstandingCase):
    """Constructing `LanguageUnderstandingResult` directly, the way
    older callers/tests do, without touching `_classify_intent` at
    all, must remain fully valid - the classifier boundary is not the
    only supported way to produce this result shape."""

    def test_legacy_construction_with_all_positional_required_fields(self):
        legacy = LanguageUnderstandingResult(
            original_input="hi there",
            detected_language="english",
            normalized_input="hi there",
            intent=INTENT_UNKNOWN,
            entities=[],
            referenced_items=[],
            active_topic=None,
            conversation_context=None,
            confidence=0.5,
            ambiguity=False,
            needs_clarification=False,
        )
        self.assertEqual(legacy.normalized_input, "hi there")
        self.assertEqual(legacy.intent, INTENT_UNKNOWN)
        as_dict = legacy.to_dict()
        self.assertEqual(as_dict["normalized_input"], "hi there")
        self.assertEqual(as_dict["intent"], INTENT_UNKNOWN)

    def test_legacy_construction_intent_independently_supplied(self):
        """A caller may supply an intent that was NOT produced by
        `_classify_intent` at all (e.g. a stored/serialized result) -
        this class must not silently re-derive or overwrite it."""
        legacy = LanguageUnderstandingResult(
            original_input="Build a thing.",
            detected_language="english",
            normalized_input="Build a thing.",
            intent=INTENT_REQUEST_ACTION,
            entities=[],
            referenced_items=[],
            active_topic=None,
            conversation_context=None,
            confidence=0.7,
            ambiguity=False,
            needs_clarification=False,
        )
        self.assertEqual(legacy.intent, INTENT_REQUEST_ACTION)
        self.assertEqual(legacy.normalized_input, "Build a thing.")


if __name__ == "__main__":
    unittest.main()
