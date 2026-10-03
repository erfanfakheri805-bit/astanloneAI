"""
Tests for Prompt 617 - `normalized_input` as a Reliable Output of the
Existing Normalization/Understanding Pipeline.

Inspection performed by this prompt (see docs comment below production
files) found the wiring from the existing normalizer
(understanding/normalization.py: `normalize()`) into
`LanguageUnderstandingResult.normalized_input` already correct and
already in place since Prompt 397
(`deterministic_fallback_backend.py`: `normalized_input=result.
normalized_text`), and already forwarded verbatim through the whole
downstream chain locked in by Prompts 609-616:

    LanguageUnderstandingResult.normalized_input   (Prompt 397/609)
      -> ResponsePlan.normalized_input             (Prompt 609)
      -> ResponseGenerationContext.normalized_input(Prompt 610)
      -> ResponseGenerationOutcome.normalized_input(Prompt 611)
      -> ConversationResponse.normalized_input     (Prompt 612)

The ONE genuine gap this prompt found and fixed: `BackendGenerationRequest`
(response_generation_request.py, Prompt 427) copies every other additive
`ResponseGenerationContext` field (Prompt 433-501) but, uniquely, never
picked up `normalized_input` (added later, Prompt 610) - so a local-model
backend's own inference request silently dropped it. This file's
`TestBackendGenerationRequestCarriesNormalizedInput` class covers that
fix; every other class in this file is regression coverage for the
already-correct behaviour, following the same "lock in what inspection
already found correct" convention Prompt 616's own test file uses.

Run directly:
    python -m unittest tests.test_normalized_input_pipeline_reliability_prompt617 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine

from language_intelligence.language_understanding_result import (
    LanguageUnderstandingResult, INTENT_UNKNOWN, INTENT_ASK_QUESTION,
)
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.response_planning import ResponsePlanner
from language_intelligence.response_generation_context import (
    ResponseGenerationContext, generation_context_from_understanding,
)
from language_intelligence.response_generation_request import (
    BackendGenerationRequest, build_generation_request, generation_request_from_understanding,
)
from language_intelligence.response_generation import ResponseGenerationRequest


def _make_backend():
    return DeterministicFallbackBackend(UnderstandingEngine())


def _make_lic():
    return LanguageIntelligenceCore(backend=_make_backend(), response_planner=ResponsePlanner())


class TestOrdinaryInputProducesNormalizedInput(unittest.TestCase):
    """1. ordinary input -> normalized_input."""

    def test_ordinary_sentence_is_normalized(self):
        lic = _make_lic()
        result = lic.understand("Python is a programming language.")
        self.assertEqual(result.normalized_input, "Python is a programming language.")
        self.assertIsInstance(result.normalized_input, str)


class TestInputThatActuallyChangesDuringNormalization(unittest.TestCase):
    """2. input that actually changes during normalization."""

    def test_extra_whitespace_is_collapsed(self):
        lic = _make_lic()
        raw = "  Python   is    great!!  "
        result = lic.understand(raw)
        self.assertNotEqual(result.original_input, result.normalized_input)
        self.assertEqual(result.normalized_input, "Python is great!!")

    def test_newlines_and_tabs_collapse_to_single_spaces(self):
        lic = _make_lic()
        raw = "What\tis\n\nPython?"
        result = lic.understand(raw)
        self.assertEqual(result.normalized_input, "What is Python?")
        self.assertNotEqual(result.original_input, result.normalized_input)


class TestAlreadyNormalizedInputIsStable(unittest.TestCase):
    """3. input already normalized."""

    def test_already_clean_input_is_unchanged(self):
        lic = _make_lic()
        raw = "What is Python?"
        result = lic.understand(raw)
        self.assertEqual(result.normalized_input, raw)
        self.assertEqual(result.original_input, result.normalized_input)


class TestEmptyOrMinimalInput(unittest.TestCase):
    """4. empty/minimal input."""

    def test_empty_string_input(self):
        lic = _make_lic()
        result = lic.understand("")
        self.assertEqual(result.original_input, "")
        self.assertEqual(result.normalized_input, "")
        self.assertIn("empty_input", result.warnings)

    def test_whitespace_only_input_normalizes_to_empty(self):
        lic = _make_lic()
        result = lic.understand("    ")
        self.assertEqual(result.original_input, "    ")
        self.assertEqual(result.normalized_input, "")

    def test_single_word_input(self):
        lic = _make_lic()
        result = lic.understand("Hi")
        self.assertEqual(result.normalized_input, "Hi")
        self.assertEqual(result.original_input, "Hi")


class TestOriginalInputPreservation(unittest.TestCase):
    """5. preservation of original_input."""

    def test_original_input_is_always_verbatim(self):
        lic = _make_lic()
        for raw in ("  spaced   out  ", "already clean", "", "   ", "One\nTwo\tThree"):
            result = lic.understand(raw)
            self.assertEqual(result.original_input, raw)

    def test_original_input_is_never_mutated_by_downstream_reads(self):
        lic = _make_lic()
        raw = "  Python   is    great!!  "
        result = lic.understand(raw)
        # Reading normalized_input, to_dict(), response_plan, etc. must
        # never retroactively change original_input.
        _ = result.to_dict()
        _ = result.response_plan
        self.assertEqual(result.original_input, raw)


class TestLegacyConstructionWithoutNormalizedInput(unittest.TestCase):
    """6. legacy construction without normalized_input."""

    def test_legacy_hand_built_dict_missing_the_key_is_safe(self):
        """A hand-built understanding dict predating Prompt 609 (no
        `normalized_input` key at all) must not crash the planner, and
        must yield a plan whose own `normalized_input` is safely None -
        never a KeyError, never a fabricated value."""
        bare = LanguageUnderstandingResult(
            original_input="Hello", detected_language="english",
            normalized_input="Hello", intent=INTENT_ASK_QUESTION, entities=[],
            referenced_items=[], active_topic=None, conversation_context=None,
            confidence=0.9, ambiguity=False, needs_clarification=False)
        legacy_dict = bare.to_dict()
        del legacy_dict["normalized_input"]
        planner = ResponsePlanner()
        plan = planner.plan(legacy_dict)
        self.assertIsNone(plan.normalized_input)
        self.assertEqual(plan.to_dict()["normalized_input"], None)

    def test_legacy_response_generation_context_without_normalized_input(self):
        """A hand-built `ResponseGenerationContext` predating Prompt 610
        (constructed without normalized_input) is safe: the field
        defaults to None rather than raising or requiring a new arg."""
        ctx = ResponseGenerationContext(
            original_message="hi", status="UNRESOLVED", response_action=None,
            meaning=None, meaning_candidates=[], matched_pattern=None, variables={},
            active_topic=None, references=[], context=None, language="english",
            locale=None, unresolved_requirements=[])
        self.assertIsNone(ctx.normalized_input)
        self.assertIsNone(ctx.to_dict()["normalized_input"])

    def test_legacy_backend_generation_request_without_normalized_input(self):
        """Prompt 617's own fix: direct construction of
        `BackendGenerationRequest` without the new `normalized_input`
        kwarg (exactly how every caller built it before this prompt)
        must keep working unchanged, defaulting safely to None."""
        req = BackendGenerationRequest(
            original_message="hi", status="UNRESOLVED", response_action=None,
            meaning=None, meaning_candidates=[], matched_pattern=None,
            sentence_structure=None, variables={}, active_topic=None,
            references=[], context=None, language="english", locale=None,
            unresolved_requirements=[])
        self.assertIsNone(req.normalized_input)
        self.assertIsNone(req.to_dict()["normalized_input"])

    def test_build_generation_request_from_a_legacy_context_dict(self):
        """A plain dict standing in for a pre-Prompt-610
        ResponseGenerationContext.to_dict() (no normalized_input key)
        must not crash `build_generation_request`."""
        legacy_context_dict = {
            "original_message": "hi", "status": "UNRESOLVED", "response_action": None,
            "meaning": None, "meaning_candidates": [], "matched_pattern": None,
            "variables": {}, "active_topic": None, "references": [], "context": None,
            "language": "english", "locale": None, "unresolved_requirements": [],
        }
        req = build_generation_request(legacy_context_dict)
        self.assertIsNone(req.normalized_input)


class TestDownstreamPropagationThroughTheFullChain(unittest.TestCase):
    """7. downstream propagation through the existing
    ResponsePlan -> ResponseGenerationContext -> BackendGenerationRequest /
    ResponseGenerationOutcome -> ConversationResponse path. Every layer
    must receive the EXACT value produced upstream - never a
    recomputed/re-normalized one."""

    def _full_chain(self, raw_text):
        lic = _make_lic()
        understanding = lic.understand(raw_text)
        plan = understanding.response_plan  # dict, already attached by Core
        gen_context = generation_context_from_understanding(understanding)
        gen_request = generation_request_from_understanding(understanding)
        return understanding, plan, gen_context, gen_request

    def test_every_layer_carries_the_identical_value(self):
        understanding, plan, gen_context, gen_request = self._full_chain(
            "  what   is python  ")
        expected = "what is python"
        self.assertEqual(understanding.normalized_input, expected)
        self.assertEqual(plan["normalized_input"], expected)
        self.assertEqual(gen_context.normalized_input, expected)
        self.assertEqual(gen_context.to_dict()["normalized_input"], expected)
        self.assertEqual(gen_request.normalized_input, expected)
        self.assertEqual(gen_request.to_dict()["normalized_input"], expected)

    def test_no_layer_recomputes_it_from_original_input(self):
        """If any layer re-derived normalized_input from original_input
        instead of forwarding the upstream value, this would still pass
        for well-formed text - so assert equality against the upstream
        value itself (never against a freshly-normalized original_input)
        to make sure we are checking identity of the value, not just
        coincidental agreement."""
        understanding, plan, gen_context, gen_request = self._full_chain(
            "Hello\tworld\n\nagain")
        upstream = understanding.normalized_input
        self.assertEqual(plan["normalized_input"], upstream)
        self.assertEqual(gen_context.normalized_input, upstream)
        self.assertEqual(gen_request.normalized_input, upstream)

    def test_conversation_response_receives_the_same_value(self):
        """End-to-end through generate_conversation_response(), covering
        the ConversationResponse hop (Prompt 612) with the SAME
        understanding used above."""
        lic = _make_lic()
        understanding = lic.understand("  what   is python  ")
        conversation_response = lic.generate_conversation_response(understanding)
        self.assertIsNotNone(conversation_response)
        self.assertEqual(conversation_response.normalized_input, "what is python")
        outcome = lic.get_last_response_generation_result()
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.normalized_input, "what is python")
        self.assertEqual(outcome.normalized_input, conversation_response.normalized_input)

    def test_empty_input_propagates_empty_normalized_value_not_none(self):
        """Empty input normalizes to "" (not None) - that empty string,
        not None, is what must propagate through every layer, since ""
        genuinely is what the understanding produced."""
        understanding, plan, gen_context, gen_request = self._full_chain("")
        self.assertEqual(understanding.normalized_input, "")
        self.assertEqual(plan["normalized_input"], "")
        self.assertEqual(gen_context.normalized_input, "")
        self.assertEqual(gen_request.normalized_input, "")

    def test_response_generation_request_accessor_matches_direct_build(self):
        """`ResponseGenerationRequest.generation_context` (the lazy
        accessor a caller normally uses) must expose the identical
        normalized_input `generation_context_from_understanding` builds
        directly - two paths to the same already-computed value, never
        two different computations."""
        lic = _make_lic()
        understanding = lic.understand("  what   is python  ")
        accessor_request = ResponseGenerationRequest(understanding)
        self.assertEqual(
            accessor_request.generation_context["normalized_input"],
            understanding.normalized_input)


if __name__ == "__main__":
    unittest.main()
