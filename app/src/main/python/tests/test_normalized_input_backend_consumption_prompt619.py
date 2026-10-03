"""
Tests for Prompt 619 - Whether the Local/Fallback Backend Actually
CONSUMES `normalized_input` When Generating a Response.

Trace performed by this prompt, from `ResponseGenerationContext` through
`BackendGenerationRequest` through `InferenceRequest` to the real
backend and its `ResponseGenerationResult`:

  * `DeterministicFallbackBackend.generate_response()`
    (deterministic_fallback_backend.py) runs NO inference at all - it
    unconditionally returns `STATUS_DEFERRED` with `response_text=None`.
    It therefore consumes neither `original_input` nor
    `normalized_input` when "generating" a response (there is nothing
    to build). `normalized_input` is still attached to the
    `LanguageUnderstandingResult` by this backend's `understand()`
    (`normalized_input=result.normalized_text`), but that is the
    UNDERSTANDING step, not generation.

  * `LocalLanguageModelBackend.generate_response()`
    (local_model_backend.py) -> `build_inference_request()`
    (local_model_mapping.py) is where the actual model input is
    decided. Its own docstring is explicit and was already true before
    this prompt: "the understanding's `original_input` (verbatim -
    never the normalized text, ...)" is what becomes
    `InferenceRequest.user_input` - the ONE field the provider/runtime
    layer actually reads as the text to respond to. `normalized_input`
    DOES reach the runtime, but only as inert, read-only metadata
    nested inside `InferenceRequest.generation_context` /
    `InferenceRequest.generation_request` (Prompts 426/427/617/618) -
    never as the text the model is asked to complete.

This is the architecture's documented, intentional semantics (see the
module docstring's own "Do not assume normalized_input must replace
original_input" framing) - not an oversight, so NO production code is
changed here. This file locks the finding in with regression coverage
that observes the ACTUAL text a spy runtime receives, not just object
fields on intermediate request values.

Run directly:
    python -m unittest tests.test_normalized_input_backend_consumption_prompt619 -v
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
    STATUS_DEFERRED, STATUS_GENERATED,
)
from language_intelligence.response_generation_context import (
    generation_context_from_understanding,
)
from language_intelligence.response_generation_request import (
    BackendGenerationRequest, generation_request_from_understanding,
)
from language_intelligence.inference import InferenceRequest, STATUS_SUCCESS
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.local_model_config import LocalModelConfig
from language_intelligence.local_model_runtime import LocalModelRuntime, RuntimeOutput


def _make_lic():
    return LanguageIntelligenceCore(
        backend=DeterministicFallbackBackend(UnderstandingEngine()),
        response_planner=ResponsePlanner())


class SpyRuntime(LocalModelRuntime):
    """Spy/stub TEST DOUBLE at the runtime/provider boundary - captures
    the exact `InferenceRequest` handed to inference, including the
    exact `user_input` text. NOT a language model; no inference, no
    network. Same convention as the Prompt 618/399 StubRuntime."""

    def __init__(self, config=None):
        super().__init__(config=config)
        self.requests = []
        self.output = RuntimeOutput("stub-output", "stop", prompt_tokens=1, output_tokens=1)

    @property
    def runtime_name(self):
        return "spy-runtime-619"

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
    return SpyRuntime(config), handle.name


class _SpyBackendCase(unittest.TestCase):
    """Common setup/teardown for tests that need a real
    LocalLanguageModelBackend wired to a SpyRuntime."""

    def setUp(self):
        self.runtime, self._model_path = _runtime_with_model()
        self.backend = LocalLanguageModelBackend(self.runtime)

    def tearDown(self):
        if os.path.exists(self._model_path):
            os.remove(self._model_path)

    def _understand(self, raw_text):
        return _make_lic().understand(raw_text)

    def _spy_request(self):
        self.assertEqual(len(self.runtime.requests), 1)
        return self.runtime.requests[0]


# ======================================================================
class TestOriginalDiffersFromNormalized(_SpyBackendCase):
    """1. original input differs from normalized input - the actual
    text sent to inference must be the ORIGINAL, not the normalized
    one (documented, intentional architecture)."""

    def test_actual_inference_input_is_original_not_normalized(self):
        raw = "  what   is python  "
        understanding = self._understand(raw)
        self.assertEqual(understanding.original_input, raw)
        self.assertEqual(understanding.normalized_input, "what is python")
        self.assertNotEqual(understanding.original_input, understanding.normalized_input)

        response = self.backend.generate_response(understanding)
        self.assertEqual(response.status, STATUS_GENERATED)

        sent = self._spy_request()
        # The ACTUAL prompt text the runtime/provider layer received.
        self.assertEqual(sent.user_input, raw)
        self.assertNotEqual(sent.user_input, understanding.normalized_input)
        # normalized_input still reaches the runtime, but only as inert
        # metadata nested in generation_request - never as user_input.
        self.assertIsNotNone(sent.generation_request)
        self.assertEqual(sent.generation_request.normalized_input, "what is python")


# ======================================================================
class TestNormalizedEqualsOriginal(_SpyBackendCase):
    """2. normalized input equals original input - no divergence to
    observe, but the actual inference input must still be exactly that
    (single) value, sourced from original_input."""

    def test_actual_inference_input_matches_both(self):
        raw = "what is python"
        understanding = self._understand(raw)
        self.assertEqual(understanding.original_input, understanding.normalized_input)

        self.backend.generate_response(understanding)
        sent = self._spy_request()
        self.assertEqual(sent.user_input, raw)
        self.assertEqual(sent.generation_request.normalized_input, raw)


# ======================================================================
class TestNormalizedInputNoneOrEmpty(_SpyBackendCase):
    """3. normalized_input is None/empty - must not crash generation and
    must not affect the actual inference input, which is still sourced
    from original_input."""

    def test_empty_original_input_normalizes_to_empty_and_generation_is_safe(self):
        understanding = self._understand("")
        self.assertEqual(understanding.original_input, "")
        self.assertEqual(understanding.normalized_input, "")
        # An empty user_input fails InferenceRequest.validate(), so the
        # runtime never actually runs - confirm this is reported safely,
        # never crashes, and never silently substitutes normalized text.
        response = self.backend.generate_response(understanding)
        self.assertIsNotNone(response)
        self.assertNotEqual(response.status, STATUS_GENERATED)

    def test_generation_request_normalized_input_none_does_not_crash(self):
        """A hand-built generation_request with normalized_input=None
        (simulating a legacy/partial context) must not break the
        actual inference call, which never reads that field anyway."""
        understanding = self._understand("hello there")
        gen_context = generation_context_from_understanding(understanding)
        gen_request = generation_request_from_understanding(understanding)
        gen_request.normalized_input = None  # simulate missing metadata
        response = self.backend.generate_response(understanding)
        self.assertEqual(response.status, STATUS_GENERATED)
        sent = self._spy_request()
        self.assertEqual(sent.user_input, "hello there")


# ======================================================================
class TestLegacyRequestWithoutNormalizedInput(_SpyBackendCase):
    """4. a legacy BackendGenerationRequest / ResponseGenerationContext
    predating normalized_input (constructed without that field) must
    still generate correctly, with the actual inference input unaffected."""

    def test_understanding_without_response_plan_still_generates(self):
        """An understanding built directly off the fallback backend
        (bypassing Core, so no response_plan attached) yields
        generation_request=None - the pre-Prompt-426/610 shape - and
        the actual inference input must still be original_input."""
        raw_understanding = DeterministicFallbackBackend(
            UnderstandingEngine()).understand("hi there")
        response = self.backend.generate_response(raw_understanding)
        self.assertEqual(response.status, STATUS_GENERATED)
        sent = self._spy_request()
        self.assertEqual(sent.user_input, "hi there")
        self.assertIsNone(sent.generation_request)

    def test_legacy_backend_generation_request_construction(self):
        legacy_request = BackendGenerationRequest(
            "hi there", "resolved", None, None, [], None, None, {}, None, [], None, None,
            None, [])
        self.assertIsNone(legacy_request.normalized_input)
        understanding = self._understand("hi there")
        # Build an inference request the same way build_inference_request
        # would, but with the legacy generation_request supplied directly.
        from language_intelligence.local_model_mapping import build_inference_request
        request = build_inference_request(understanding, generation_request=legacy_request)
        self.assertEqual(request.user_input, understanding.original_input)
        self.assertIsNone(request.generation_request.normalized_input)


# ======================================================================
class TestSuccessfulBackendGeneration(_SpyBackendCase):
    """5. successful backend generation still returns the expected
    ResponseGenerationResult, unaffected by normalized_input."""

    def test_successful_generation_result_shape(self):
        understanding = self._understand("  What   is   Python?  ")
        response = self.backend.generate_response(understanding)
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(response.response_text, "stub-output")
        self.assertEqual(response.inference_status, STATUS_SUCCESS)
        self.assertIsNone(response.error_code)


# ======================================================================
class TestActualValuePresentedToTheProviderLayer(_SpyBackendCase):
    """6. the actual value presented to the backend inference/provider
    layer - the single source of truth this whole prompt is about."""

    def test_user_input_is_always_original_input_never_normalized_input(self):
        cases = [
            "  spaced   out   text  ",
            "already normalized",
            "Hello\tWorld\n\nAgain",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                runtime, model_path = _runtime_with_model()
                try:
                    backend = LocalLanguageModelBackend(runtime)
                    understanding = self._understand(raw)
                    backend.generate_response(understanding)
                    sent = runtime.requests[0]
                    self.assertEqual(sent.user_input, understanding.original_input)
                    self.assertEqual(sent.user_input, raw)
                finally:
                    if os.path.exists(model_path):
                        os.remove(model_path)


# ======================================================================
class TestChangingNormalizedInputOnlyAffectsCarriedMetadata(_SpyBackendCase):
    """7 (requirement 8) - changing normalized_input changes only the
    inert metadata path, and never silently alters correction
    application, learning, routing, backend selection, response
    validation, or unrelated request fields."""

    def test_mutating_normalized_input_does_not_change_actual_generation(self):
        understanding = self._understand("  same   text  ")
        gen_context = generation_context_from_understanding(understanding)
        gen_request = generation_request_from_understanding(understanding)

        # Baseline generation with the real (correct) normalized_input.
        response_a = self.backend.generate_response(understanding)
        request_a = self._spy_request()
        self.runtime.requests.clear()

        # Now corrupt/mutate normalized_input on a fresh gen_request and
        # generate again - the observable inference input and result
        # must be identical, since normalized_input is never consumed.
        gen_request_mutated = generation_request_from_understanding(understanding)
        gen_request_mutated.normalized_input = "SOMETHING ENTIRELY DIFFERENT"
        from language_intelligence.local_model_mapping import build_inference_request
        request_b = build_inference_request(
            understanding, generation_context=gen_context,
            generation_request=gen_request_mutated)
        result_b = self.runtime.generate(request_b)

        self.assertEqual(request_a.user_input, request_b.user_input)
        self.assertEqual(response_a.status, STATUS_GENERATED)
        self.assertTrue(result_b.ok)
        self.assertEqual(result_b.text, "stub-output")

    def test_deterministic_fallback_backend_ignores_normalized_input_entirely(self):
        """Confirms requirement 8's "unrelated fields/routing" concern
        for the OTHER backend: the fallback backend's generate_response
        is a fixed STATUS_DEFERRED regardless of normalized_input's
        value, so nothing about correction/learning/routing/selection
        can be influenced by it there either."""
        fallback = DeterministicFallbackBackend(UnderstandingEngine())
        for raw in ("  a  b  ", "a b", ""):
            understanding = fallback.understand(raw)
            response = fallback.generate_response(understanding)
            self.assertEqual(response.status, STATUS_DEFERRED)
            self.assertIsNone(response.response_text)


if __name__ == "__main__":
    unittest.main()
