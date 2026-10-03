"""
Tests for Prompt 618 - Verifying the `normalized_input` Handoff at the
`BackendGenerationRequest` -> `InferenceRequest` Boundary.

Inspection performed by this prompt found the boundary already correct,
so NO production code was changed - this file is regression coverage
locking that finding in place.

The boundary itself lives in `local_model_mapping.build_inference_request()`
(language_intelligence/local_model_mapping.py):

    return InferenceRequest(
        ...
        generation_request=generation_request,
    )

and `InferenceRequest.__init__` (language_intelligence/inference.py):

    self.generation_request = generation_request

Neither line reconstructs, copies, or re-derives the
`BackendGenerationRequest` it is given - the exact object passed in
becomes `InferenceRequest.generation_request`. Because Prompt 617 already
made `BackendGenerationRequest.normalized_input` carry the upstream
`ResponseGenerationContext.normalized_input` verbatim (see
test_normalized_input_pipeline_reliability_prompt617.py), and this
boundary forwards that WHOLE object unmodified (same reference, no field
extraction, no `to_dict()` round-trip), `normalized_input` necessarily
survives the `BackendGenerationRequest` -> `InferenceRequest` hop exactly
as it was upstream:

    LanguageUnderstandingResult.normalized_input     (Prompt 397/609)
      -> ResponsePlan.normalized_input               (Prompt 609)
      -> ResponseGenerationContext.normalized_input  (Prompt 610)
      -> BackendGenerationRequest.normalized_input   (Prompt 617)
      -> InferenceRequest.generation_request         (this boundary,
                                                       Prompt 427/618 -
                                                       the WHOLE object,
                                                       so .normalized_input
                                                       on it is unchanged)

Run directly:
    python -m unittest tests.test_normalized_input_inference_boundary_prompt618 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.engine import UnderstandingEngine

from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.response_planning import ResponsePlanner
from language_intelligence.response_generation import (
    STATUS_GENERATED, STATUS_MODEL_NOT_CONFIGURED as RESP_NOT_CONFIGURED,
)
from language_intelligence.response_generation_context import (
    generation_context_from_understanding,
)
from language_intelligence.response_generation_request import (
    BackendGenerationRequest, build_generation_request, generation_request_from_understanding,
)
from language_intelligence.inference import InferenceRequest, STATUS_SUCCESS
from language_intelligence.local_model_mapping import build_inference_request
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.local_model_config import LocalModelConfig
from language_intelligence.local_model_runtime import LocalModelRuntime, RuntimeOutput


def _make_lic():
    return LanguageIntelligenceCore(
        backend=DeterministicFallbackBackend(UnderstandingEngine()),
        response_planner=ResponsePlanner())


def _minimal_backend_request(normalized_input="__unset__", original_message="hello world"):
    """A directly-constructed `BackendGenerationRequest` with every field
    at a minimal, harmless value except `normalized_input` - isolates the
    one field under test from everything else in the object."""
    kwargs = dict(
        original_message=original_message, status="resolved", response_action=None,
        meaning=None, meaning_candidates=[], matched_pattern=None, sentence_structure=None,
        variables={}, active_topic=None, references=[], context=None, language=None,
        locale=None, unresolved_requirements=[],
    )
    if normalized_input != "__unset__":
        kwargs["normalized_input"] = normalized_input
    return BackendGenerationRequest(**kwargs)


class StubRuntime(LocalModelRuntime):
    """TEST DOUBLE at the runtime boundary (same convention as
    test_local_model_backend_integration.py's StubRuntime). Returns what
    a test scripts; NOT a language model, no inference, no network."""

    def __init__(self, config=None):
        super().__init__(config=config)
        self.requests = []
        self.output = RuntimeOutput("stub-output", "stop", prompt_tokens=1, output_tokens=1)

    @property
    def runtime_name(self):
        return "stub-runtime-618"

    def dependency_status(self):
        return True, ""

    def _load_model(self, config):
        pass

    def _run_inference(self, request, params, config, control):
        self.requests.append(request)
        return self.output


def _runtime_with_model():
    handle = tempfile.NamedTemporaryFile(suffix=".gguf", delete=False)
    handle.write(b"\0" * 16)
    handle.close()
    config = LocalModelConfig(model_id="test-model", model_path=handle.name,
                              context_length=512, max_output_tokens=64,
                              timeout_seconds=10.0)
    return StubRuntime(config), handle.name


# ======================================================================
class TestChangedNormalizedInputSurvivesUnchanged(unittest.TestCase):
    """1. a changed normalized input survives unchanged to InferenceRequest."""

    def test_direct_build_inference_request(self):
        gen_request = _minimal_backend_request(normalized_input="what is python",
                                                original_message="  what   is python  ")
        understanding = type("U", (), {"original_input": "  what   is python  ",
                                        "language_context": None})()
        request = build_inference_request(understanding, generation_request=gen_request)
        self.assertIsInstance(request, InferenceRequest)
        self.assertEqual(request.generation_request.normalized_input, "what is python")
        self.assertNotEqual(request.generation_request.normalized_input, gen_request.original_message)

    def test_full_pipeline_via_understanding(self):
        lic = _make_lic()
        understanding = lic.understand("  what   is python  ")
        self.assertEqual(understanding.normalized_input, "what is python")
        gen_context = generation_context_from_understanding(understanding)
        gen_request = generation_request_from_understanding(understanding)
        request = build_inference_request(understanding, generation_context=gen_context,
                                          generation_request=gen_request)
        self.assertEqual(request.generation_request.normalized_input, "what is python")


# ======================================================================
class TestAlreadyNormalizedInputSurvivesUnchanged(unittest.TestCase):
    """2. an already-normalized input survives unchanged."""

    def test_direct_build_inference_request(self):
        gen_request = _minimal_backend_request(normalized_input="what is python",
                                                original_message="what is python")
        understanding = type("U", (), {"original_input": "what is python",
                                        "language_context": None})()
        request = build_inference_request(understanding, generation_request=gen_request)
        self.assertEqual(request.generation_request.normalized_input, "what is python")

    def test_full_pipeline_via_understanding(self):
        lic = _make_lic()
        raw = "what is python"
        understanding = lic.understand(raw)
        self.assertEqual(understanding.normalized_input, raw)
        gen_request = generation_request_from_understanding(understanding)
        request = build_inference_request(understanding, generation_request=gen_request)
        self.assertEqual(request.generation_request.normalized_input, raw)


# ======================================================================
class TestEmptyOrNoneNormalizedInputStaysSafe(unittest.TestCase):
    """3. empty/None normalized input remains safe (no crash, no
    substitution with something else)."""

    def test_empty_string_is_preserved_as_empty_string(self):
        gen_request = _minimal_backend_request(normalized_input="", original_message="")
        understanding = type("U", (), {"original_input": "", "language_context": None})()
        request = build_inference_request(understanding, generation_request=gen_request)
        self.assertEqual(request.generation_request.normalized_input, "")
        self.assertIsNotNone(request.generation_request.normalized_input)

    def test_none_normalized_input_stays_none(self):
        gen_request = _minimal_backend_request(normalized_input=None)
        understanding = type("U", (), {"original_input": "hello", "language_context": None})()
        request = build_inference_request(understanding, generation_request=gen_request)
        self.assertIsNone(request.generation_request.normalized_input)

    def test_generation_request_itself_none_does_not_crash(self):
        understanding = type("U", (), {"original_input": "hello", "language_context": None})()
        request = build_inference_request(understanding, generation_request=None)
        self.assertIsNone(request.generation_request)

    def test_empty_input_through_full_pipeline(self):
        lic = _make_lic()
        understanding = lic.understand("")
        self.assertEqual(understanding.normalized_input, "")
        gen_request = generation_request_from_understanding(understanding)
        request = build_inference_request(understanding, generation_request=gen_request)
        self.assertEqual(request.generation_request.normalized_input, "")


# ======================================================================
class TestOriginalInputRemainsDistinctAndUnchanged(unittest.TestCase):
    """4. original_input remains distinct and unchanged from
    normalized_input at (and beyond) this boundary."""

    def test_user_input_is_original_not_normalized(self):
        lic = _make_lic()
        raw = "  what   is python  "
        understanding = lic.understand(raw)
        gen_context = generation_context_from_understanding(understanding)
        gen_request = generation_request_from_understanding(understanding)
        request = build_inference_request(understanding, generation_context=gen_context,
                                          generation_request=gen_request)
        # InferenceRequest.user_input is the understanding's original_input
        # (per build_inference_request's own contract), never the
        # normalized text - and it stays distinct from the
        # normalized_input carried on generation_request.
        self.assertEqual(request.user_input, raw)
        self.assertEqual(understanding.original_input, raw)
        self.assertNotEqual(request.user_input, request.generation_request.normalized_input)

    def test_backend_request_original_message_unaffected_by_normalized_input(self):
        gen_request = _minimal_backend_request(
            normalized_input="changed", original_message="  UNCHANGED  ")
        understanding = type("U", (), {"original_input": "  UNCHANGED  ",
                                        "language_context": None})()
        request = build_inference_request(understanding, generation_request=gen_request)
        self.assertEqual(request.generation_request.original_message, "  UNCHANGED  ")
        self.assertEqual(request.generation_request.normalized_input, "changed")


# ======================================================================
class TestBackendGenerationRequestToInferenceRequestExactValue(unittest.TestCase):
    """5. BackendGenerationRequest -> InferenceRequest preserves the exact
    value (object identity, not a coincidentally-equal copy)."""

    def test_generation_request_is_the_identical_object(self):
        gen_request = _minimal_backend_request(normalized_input="exact value")
        understanding = type("U", (), {"original_input": "hello", "language_context": None})()
        request = build_inference_request(understanding, generation_request=gen_request)
        # Hold the actual reference and compare with `is` (never id()).
        self.assertIs(request.generation_request, gen_request)
        self.assertEqual(request.generation_request.normalized_input, "exact value")

    def test_mutating_the_source_after_the_call_is_visible(self):
        """Confirms this is a live reference, not a value copied at call
        time - the strongest possible evidence nothing was rebuilt."""
        gen_request = _minimal_backend_request(normalized_input="before")
        understanding = type("U", (), {"original_input": "hello", "language_context": None})()
        request = build_inference_request(understanding, generation_request=gen_request)
        gen_request.normalized_input = "after"
        self.assertEqual(request.generation_request.normalized_input, "after")

    def test_to_dict_also_agrees(self):
        """The dict view is consistent with the object view - checked in
        addition to, never instead of, the identity check above."""
        gen_request = _minimal_backend_request(normalized_input="exact value")
        understanding = type("U", (), {"original_input": "hello", "language_context": None})()
        request = build_inference_request(understanding, generation_request=gen_request)
        self.assertEqual(request.to_dict()["generation_request"]["normalized_input"],
                         "exact value")


# ======================================================================
class TestLegacyBackendGenerationRequestConstructionRemainsCompatible(unittest.TestCase):
    """6. legacy BackendGenerationRequest construction (predating Prompt
    617's normalized_input field) remains compatible."""

    def test_legacy_positional_construction_without_normalized_input(self):
        gen_request = BackendGenerationRequest(
            "hello", "resolved", None, None, [], None, None, {}, None, [], None, None, None, [])
        self.assertIsNone(gen_request.normalized_input)
        understanding = type("U", (), {"original_input": "hello", "language_context": None})()
        request = build_inference_request(understanding, generation_request=gen_request)
        self.assertIsNone(request.generation_request.normalized_input)

    def test_build_generation_request_from_legacy_dict_without_normalized_input(self):
        legacy_context_dict = {
            "original_message": "hi", "status": "resolved", "response_action": None,
            "meaning": None, "meaning_candidates": [], "matched_pattern": None,
            "variables": {}, "active_topic": None, "references": [], "context": None,
            "language": None, "locale": None, "unresolved_requirements": [],
            # no "normalized_input" key at all - simulates a hand-built
            # dict predating Prompt 610/617.
        }
        gen_request = build_generation_request(legacy_context_dict)
        self.assertIsNone(gen_request.normalized_input)
        understanding = type("U", (), {"original_input": "hi", "language_context": None})()
        request = build_inference_request(understanding, generation_request=gen_request)
        self.assertIsNone(request.generation_request.normalized_input)


# ======================================================================
class TestNormalBackendGenerationPathStillReturnsExpectedResult(unittest.TestCase):
    """7. the normal backend generation path still returns the expected
    ResponseGenerationResult, with normalized_input having correctly
    reached the runtime's InferenceRequest along the way."""

    def test_successful_generation_carries_normalized_input_to_the_runtime(self):
        runtime, model_path = _runtime_with_model()
        try:
            lic = _make_lic()
            understanding = lic.understand("  what   is python  ")
            backend = LocalLanguageModelBackend(runtime)
            response = backend.generate_response(understanding)
            self.assertEqual(response.status, STATUS_GENERATED)
            self.assertEqual(response.response_text, "stub-output")
            self.assertEqual(response.inference_status, STATUS_SUCCESS)
            self.assertEqual(len(runtime.requests), 1)
            sent = runtime.requests[0]
            self.assertIsInstance(sent, InferenceRequest)
            self.assertIsNotNone(sent.generation_request)
            self.assertEqual(sent.generation_request.normalized_input, "what is python")
            # user_input itself is still the ORIGINAL text, never normalized.
            self.assertEqual(sent.user_input, "  what   is python  ")
        finally:
            if os.path.exists(model_path):
                os.remove(model_path)

    def test_no_plan_attached_means_no_generation_request_but_still_generates(self):
        """Regression: an understanding without a response_plan attached
        (built directly off the fallback backend, bypassing Core) yields
        generation_request=None - the pre-Prompt-426 behaviour - and the
        normal path must still succeed."""
        runtime, model_path = _runtime_with_model()
        try:
            raw_understanding = DeterministicFallbackBackend(
                UnderstandingEngine()).understand("hi")
            backend = LocalLanguageModelBackend(runtime)
            response = backend.generate_response(raw_understanding)
            self.assertEqual(response.status, STATUS_GENERATED)
            self.assertEqual(len(runtime.requests), 1)
            self.assertIsNone(runtime.requests[0].generation_request)
        finally:
            if os.path.exists(model_path):
                os.remove(model_path)


if __name__ == "__main__":
    unittest.main()
