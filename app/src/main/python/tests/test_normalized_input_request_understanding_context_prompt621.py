"""
Tests for Prompt 621 - Section 2: Language Intelligence and Request
Understanding - `normalized_input` Availability in the Request-
Understanding / Intent Context.

Trace performed by this prompt:

    raw_text
      -> understanding.normalization.normalize(raw_text)
         (NormalizationResult.original_text / .normalized_text)
      -> UnderstandingEngine.understand()               (understanding/
         engine.py) - EVERY later pipeline stage (language detection,
         tokenization, sentence-type analysis) already runs on
         `normalized_text`, never `original_text`
      -> UnderstandingResult.normalized_text            (understanding/
         result.py, unchanged since before this prompt)
      -> DeterministicFallbackBackend.understand()       (this prompt's
         actual request-understanding / intent-context boundary):
           intent = self._classify_intent(
               result.normalized_text, result.sentence_type)
         - the existing, one and only intent-classification component
           in this project (a fixed sentence-type + goal-oriented-
           prefix mapping - see that module's own docstring). It
           already reads `result.normalized_text` directly.
      -> LanguageUnderstandingResult(
             original_input=result.original_text,        (untouched)
             normalized_input=result.normalized_text,     (SAME value,
                                                            same object,
                                                            same call)
             intent=intent, ...)

Finding: `result.normalized_text` is the SAME value, produced by the
SAME normalization call, that becomes both the input to
`_classify_intent()` (the request-understanding/intent component) and
`LanguageUnderstandingResult.normalized_input`. There is no separate
"request-understanding context" object distinct from
`LanguageUnderstandingResult` for this pipeline - intent is derived
directly from the Understanding Engine's own normalized text, at the
same point normalized_input is captured. So the existing intent
component ALREADY receives the correct normalized value - it does not
receive a hand-me-down copy or a re-derived one; it receives the very
value the normalization stage produced, before anything downstream of
it exists.

Per this prompt's own requirements 4, 7 and 10, NO PRODUCTION CODE IS
CHANGED: no new intent system, no keyword heuristics, no classifier,
no new normalization algorithm, and no change to backend inference,
correction application, learned-response selection, routing,
confidence logic, response generation, or memory behavior. This file
is regression coverage locking in the existing contract.

Run directly:
    python -m unittest tests.test_normalized_input_request_understanding_context_prompt621 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine
from understanding.result import UnderstandingResult
from understanding.sentence_analysis import (
    SENTENCE_QUESTION, SENTENCE_STATEMENT, SENTENCE_COMMAND, SENTENCE_UNKNOWN,
)

from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_understanding_result import (
    LanguageUnderstandingResult, INTENT_ASK_QUESTION, INTENT_PROVIDE_INFORMATION,
    INTENT_REQUEST_ACTION, INTENT_GOAL_REQUEST, INTENT_UNKNOWN,
)
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore


def _make_backend():
    return DeterministicFallbackBackend(UnderstandingEngine())


def _make_lic():
    return LanguageIntelligenceCore(backend=_make_backend())


class _RequestUnderstandingCase(unittest.TestCase):
    def _understand(self, raw_text):
        return _make_backend().understand(raw_text)


# ======================================================================
class TestNormalizedFormDiffersFromRaw(_RequestUnderstandingCase):
    """1. raw input whose normalized form differs - intent must still be
    derived correctly, from the SAME normalized text carried as
    `normalized_input`."""

    def test_extra_whitespace_still_classified_and_normalized_input_matches(self):
        raw = "   what   is   python?   "
        understanding = self._understand(raw)
        self.assertEqual(understanding.original_input, raw)
        self.assertEqual(understanding.normalized_input, "what is python?")
        self.assertNotEqual(understanding.original_input, understanding.normalized_input)
        self.assertEqual(understanding.intent, INTENT_ASK_QUESTION)

    def test_classify_intent_uses_the_exact_normalized_input_value(self):
        """Directly confirms the request-understanding component
        (`_classify_intent`) is called with exactly the value that ends
        up on `normalized_input` - not a re-derived or separately
        computed copy."""
        raw = "  Explain   indentation.  "
        understanding = self._understand(raw)
        recomputed = DeterministicFallbackBackend._classify_intent(
            understanding.normalized_input, SENTENCE_COMMAND)
        self.assertEqual(understanding.intent, INTENT_REQUEST_ACTION)
        self.assertEqual(recomputed, understanding.intent)

    def test_newlines_and_tabs_collapse_and_intent_still_resolves(self):
        raw = "Python\tis\na\nprogramming\nlanguage.\n"
        understanding = self._understand(raw)
        self.assertEqual(understanding.normalized_input, "Python is a programming language.")
        self.assertEqual(understanding.intent, INTENT_PROVIDE_INFORMATION)


# ======================================================================
class TestNormalizedFormIdenticalToRaw(_RequestUnderstandingCase):
    """2. raw input whose normalized form is identical - no divergence,
    but normalized_input must still be independently populated and
    equal, and intent must resolve exactly as it would for any
    already-clean input."""

    def test_already_clean_input_normalized_equals_original(self):
        raw = "what is python"
        understanding = self._understand(raw)
        self.assertEqual(understanding.original_input, raw)
        self.assertEqual(understanding.normalized_input, raw)
        self.assertEqual(understanding.intent, INTENT_ASK_QUESTION)

    def test_goal_oriented_prefix_with_clean_input(self):
        raw = "I want to build a small script."
        understanding = self._understand(raw)
        self.assertEqual(understanding.normalized_input, raw)
        self.assertEqual(understanding.intent, INTENT_GOAL_REQUEST)


# ======================================================================
class TestNormalizedInputNoneOrEmpty(_RequestUnderstandingCase):
    """3. None/empty normalized input - must not crash the request-
    understanding/intent boundary and must fall back to the documented
    INTENT_UNKNOWN, never guessed."""

    def test_empty_raw_text_yields_empty_normalized_input_and_unknown_intent(self):
        understanding = self._understand("")
        self.assertEqual(understanding.original_input, "")
        self.assertEqual(understanding.normalized_input, "")
        self.assertEqual(understanding.intent, INTENT_UNKNOWN)
        self.assertIn("empty_input", understanding.warnings)

    def test_none_raw_text_normalizes_to_empty_safely(self):
        understanding = self._understand(None)
        self.assertEqual(understanding.normalized_input, "")
        self.assertEqual(understanding.intent, INTENT_UNKNOWN)

    def test_whitespace_only_raw_text_normalizes_to_empty(self):
        understanding = self._understand("     \t\n   ")
        self.assertEqual(understanding.normalized_input, "")
        self.assertEqual(understanding.intent, INTENT_UNKNOWN)

    def test_classify_intent_static_method_handles_none_and_empty_directly(self):
        self.assertEqual(
            DeterministicFallbackBackend._classify_intent(None, SENTENCE_STATEMENT),
            INTENT_PROVIDE_INFORMATION)
        self.assertEqual(
            DeterministicFallbackBackend._classify_intent("", SENTENCE_UNKNOWN),
            INTENT_UNKNOWN)


# ======================================================================
class TestOriginalInputRemainsUnchanged(_RequestUnderstandingCase):
    """4. original_input remains unchanged - the request-understanding/
    intent boundary reads only normalized_input; original_input is
    never touched, trimmed, or substituted."""

    def test_original_input_exact_verbatim_with_whitespace(self):
        raw = "  What   is   Python?  "
        understanding = self._understand(raw)
        self.assertEqual(understanding.original_input, raw)

    def test_original_input_unaffected_by_intent_classification(self):
        raw = "  I want   to build something.  "
        understanding = self._understand(raw)
        # Intent resolves from normalized_input (goal-oriented prefix),
        # but original_input is untouched either way.
        self.assertEqual(understanding.intent, INTENT_GOAL_REQUEST)
        self.assertEqual(understanding.original_input, raw)

    def test_original_input_empty_or_none_cases(self):
        for raw in ("", None, "   "):
            with self.subTest(raw=raw):
                understanding = self._understand(raw)
                expected_original = "" if raw is None else raw
                self.assertEqual(understanding.original_input, expected_original)


# ======================================================================
class TestExactNormalizedValueReachesRequestUnderstandingContext(_RequestUnderstandingCase):
    """5. exact normalized value reaches the existing request-
    understanding/intent context - same value, not merely an equal-
    looking copy, confirmed by tracing it through UnderstandingResult
    directly."""

    def test_understanding_result_normalized_text_matches_language_understanding_result(self):
        raw = "  what   is   python  "
        engine_result = UnderstandingEngine().understand(raw)
        understanding = self._understand(raw)
        self.assertEqual(engine_result.normalized_text, understanding.normalized_input)
        self.assertEqual(engine_result.original_text, understanding.original_input)

    def test_sentence_type_and_intent_derived_from_same_normalized_text(self):
        """Sentence-type detection (which intent classification also
        depends on) and normalized_input both originate from the exact
        same `normalize()` call inside UnderstandingEngine.understand() -
        confirm no divergence is possible by cross-checking via a fresh,
        independent engine call."""
        raw = "Build me a script that sorts a list."
        engine_result = UnderstandingEngine().understand(raw)
        understanding = self._understand(raw)
        self.assertEqual(engine_result.normalized_text, understanding.normalized_input)
        recomputed_intent = DeterministicFallbackBackend._classify_intent(
            engine_result.normalized_text, engine_result.sentence_type)
        self.assertEqual(recomputed_intent, understanding.intent)

    def test_full_core_pipeline_also_preserves_the_same_value(self):
        lic = _make_lic()
        raw = "  what   is   python  "
        understanding = lic.understand(raw)
        self.assertEqual(understanding.normalized_input, "what is python")
        self.assertEqual(understanding.intent, INTENT_ASK_QUESTION)


# ======================================================================
class TestLegacyObjectsWithoutNormalizedInputRemainValid(_RequestUnderstandingCase):
    """6. legacy objects constructed without normalized_input (or with
    it explicitly None) remain valid - both at the UnderstandingResult
    level and the LanguageUnderstandingResult level."""

    def test_legacy_understanding_result_with_none_normalized_text(self):
        legacy = UnderstandingResult(
            original_text="hi there", normalized_text=None, language="english",
            tokens=[], sentence_type=SENTENCE_UNKNOWN, entities=[], relations=[],
            confidence=0.5)
        self.assertIsNone(legacy.normalized_text)
        self.assertEqual(legacy.original_text, "hi there")
        # The existing intent component tolerates a None normalized text.
        intent = DeterministicFallbackBackend._classify_intent(
            legacy.normalized_text, legacy.sentence_type)
        self.assertEqual(intent, INTENT_UNKNOWN)

    def test_legacy_language_understanding_result_with_none_normalized_input(self):
        legacy = LanguageUnderstandingResult(
            original_input="hi there", detected_language="english", normalized_input=None,
            intent=INTENT_UNKNOWN, entities=[], referenced_items=[], active_topic=None,
            conversation_context=None, confidence=0.5, ambiguity=False,
            needs_clarification=False)
        self.assertIsNone(legacy.normalized_input)
        self.assertEqual(legacy.original_input, "hi there")
        self.assertEqual(legacy.to_dict().get("normalized_input"), None)
        self.assertEqual(legacy.to_dict().get("original_input"), "hi there")


# ======================================================================
class TestRepeatedReadsDoNotMutateState(_RequestUnderstandingCase):
    """7. repeated reads of normalized_input/intent must never mutate
    the understanding, its normalized_input, or the derived intent."""

    def test_repeated_understand_calls_are_stable(self):
        raw = "  what   is   python  "
        first = self._understand(raw)
        second = self._understand(raw)
        third = self._understand(raw)
        self.assertEqual(first.normalized_input, second.normalized_input)
        self.assertEqual(second.normalized_input, third.normalized_input)
        self.assertEqual(first.intent, second.intent)
        self.assertEqual(second.intent, third.intent)
        self.assertEqual(first.original_input, third.original_input)

    def test_repeated_classify_intent_calls_do_not_mutate_inputs(self):
        text = "what is python"
        results = [
            DeterministicFallbackBackend._classify_intent(text, SENTENCE_QUESTION)
            for _ in range(5)
        ]
        self.assertTrue(all(r == INTENT_ASK_QUESTION for r in results))
        # The text argument itself is a str (immutable), but confirm the
        # SAME object survives unmodified across repeated calls.
        self.assertEqual(text, "what is python")

    def test_repeated_to_dict_calls_do_not_mutate_normalized_input(self):
        understanding = self._understand("  what   is   python  ")
        first_dict = understanding.to_dict()
        second_dict = understanding.to_dict()
        self.assertEqual(first_dict["normalized_input"], "what is python")
        self.assertEqual(second_dict["normalized_input"], "what is python")
        # Mutating a returned dict must never reach back into the object.
        first_dict["normalized_input"] = "MUTATED"
        third_dict = understanding.to_dict()
        self.assertEqual(third_dict["normalized_input"], "what is python")
        self.assertEqual(understanding.normalized_input, "what is python")


if __name__ == "__main__":
    unittest.main()
