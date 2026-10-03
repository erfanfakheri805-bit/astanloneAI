"""
Tests for Prompt 404 - Inference Request Size Control.

Covers the construction of the request sent from the language layer
(language_intelligence/local_model_mapping.py:build_inference_request)
to the local model runtime (local_model_runtime.py), tying the
conversation slice it selects to the model's OWN configured
`context_length` / `max_output_tokens` (local_model_config.py, Prompts
398/401) instead of only a fixed ceiling (Prompt 403).

IMPORTANT - about the test double: `StubRuntime` below is a TEST DOUBLE
at the runtime boundary, exactly like the one in
test_local_model_backend_integration.py. Its "output" is whatever
string a test scripts into it; it performs NO real inference. No model
is downloaded, no network is used, no real tokenizer is involved -
sizing uses the project's existing, deliberately-approximate character
estimate (see local_model_runtime.py's own docstring for why).

Run directly:
    python -m unittest tests.test_inference_request_size_control -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context.relevance import RelevantContextResult
from understanding.engine import UnderstandingEngine
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.local_model_config import (
    LocalModelConfig, DEFAULT_CONTEXT_LENGTH, DEFAULT_MAX_OUTPUT_TOKENS,
)
from language_intelligence.local_model_runtime import (
    LocalModelRuntime, RuntimeOutput,
)
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.response_generation import STATUS_GENERATED, STATUS_MODEL_FAILED
from language_intelligence.inference import (
    STATUS_RESOURCE_LIMIT, ERROR_CONTEXT_LENGTH_EXCEEDED, ERROR_MAX_OUTPUT_TOKENS_EXCEEDED,
    GenerationParameters,
)
from language_intelligence.local_model_mapping import (
    build_inference_request, resolve_request_size_limits, conversation_char_budget,
)


# ----------------------------------------------------------------------
# Test doubles (NOT a language model - see module docstring)
# ----------------------------------------------------------------------
class StubRuntime(LocalModelRuntime):
    """Records the exact InferenceRequest it was handed and returns a
    scripted RuntimeOutput. No inference is performed."""

    def __init__(self, config=None):
        super().__init__(config=config)
        self.requests = []
        self.load_calls = 0
        self.output = RuntimeOutput("stub-output", "stop", prompt_tokens=7, output_tokens=2)

    @property
    def runtime_name(self):
        return "stub-runtime"

    def _load_model(self, config):
        self.load_calls += 1
        return None

    def _run_inference(self, request, params, config, control):
        self.requests.append(request)
        return self.output


def _config(context_length=DEFAULT_CONTEXT_LENGTH, max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
           **overrides):
    values = dict(model_id="test-model", model_path=".", context_length=context_length,
                 max_output_tokens=max_output_tokens, timeout_seconds=30.0)
    values.update(overrides)
    return LocalModelConfig(**values)


def _item(index, rank, user, assistant):
    return {
        "turn": {"user": user, "assistant": assistant},
        "index": index, "rank": rank, "score": float(rank),
        "matched_terms": [], "reasons": [], "covers_message_terms": False,
    }


def _relevant(selected):
    return RelevantContextResult(message="msg", message_terms=[], selected=selected)


def _understanding(text, relevant_context=None):
    return DeterministicFallbackBackend(UnderstandingEngine()).understand(
        text, relevant_context=relevant_context
    )


# ======================================================================
class TestSmallRequestPassesUnchanged(unittest.TestCase):
    """1. small request passes unchanged"""

    def test_short_message_with_a_couple_of_short_turns_is_untouched(self):
        turns = [_item(0, 1, "short turn one", "ok"), _item(1, 2, "short turn two", "sure")]
        understanding = _understanding("A short question.", relevant_context=_relevant(turns))
        request = build_inference_request(
            understanding, max_context_turns=4, context_length=2048, max_output_tokens=256)
        self.assertEqual(request.user_input, "A short question.")
        self.assertEqual(len(request.conversation), 4)  # both turns, user+assistant each
        self.assertEqual(request.conversation[0].content, "short turn one")

    def test_end_to_end_small_request_succeeds(self):
        runtime = StubRuntime(_config())
        backend = LocalLanguageModelBackend(runtime)
        response = backend.generate_response(_understanding("Hello there."))
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(runtime.requests[0].user_input, "Hello there.")


# ======================================================================
class TestOversizedContextIsReduced(unittest.TestCase):
    """2. oversized context is reduced"""

    def test_conversation_slice_shrinks_for_a_small_context_model(self):
        turns = [_item(i, i + 1, f"turn {i} " * 30, f"reply {i} " * 30) for i in range(10)]
        understanding = _understanding("Continue please.", relevant_context=_relevant(turns))

        roomy = build_inference_request(
            understanding, max_context_turns=4, context_length=8192, max_output_tokens=256)
        tight = build_inference_request(
            understanding, max_context_turns=4, context_length=256, max_output_tokens=64)

        roomy_chars = sum(len(m.content) for m in roomy.conversation)
        tight_chars = sum(len(m.content) for m in tight.conversation)
        self.assertLess(tight_chars, roomy_chars)

    def test_budget_shrinks_as_context_length_shrinks(self):
        big = conversation_char_budget("hi", None, 8192, 256, max_turns=4)
        small = conversation_char_budget("hi", None, 256, 64, max_turns=4)
        self.assertGreater(big, small)
        self.assertGreaterEqual(small, 0)


# ======================================================================
class TestCurrentUserMessageIsPreserved(unittest.TestCase):
    """3. current user message is preserved"""

    def test_user_message_is_never_shortened_even_under_a_tiny_context(self):
        raw = "word " * 200  # long on purpose
        turns = [_item(0, 1, "some prior turn", "ok")]
        understanding = _understanding(raw, relevant_context=_relevant(turns))
        request = build_inference_request(
            understanding, max_context_turns=4, context_length=70, max_output_tokens=64)
        self.assertEqual(request.user_input, raw)

    def test_user_message_is_never_modified_by_size_control(self):
        raw = "  spacing   and   punctuation!!  "
        understanding = _understanding(raw)
        request = build_inference_request(
            understanding, max_context_turns=4, context_length=64, max_output_tokens=32)
        self.assertEqual(request.user_input, raw)


# ======================================================================
class TestHigherPriorityContextIsPreservedFirst(unittest.TestCase):
    """4. higher-priority context is preserved before lower-priority context"""

    def test_most_relevant_turn_survives_a_tight_budget_over_an_older_one(self):
        turns = [
            _item(0, 2, "an older, less relevant turn " * 20, "ok " * 20),
            _item(1, 1, "the most relevant turn", "sure"),
        ]
        understanding = _understanding("Follow-up question.", relevant_context=_relevant(turns))
        request = build_inference_request(
            understanding, max_context_turns=4, context_length=300, max_output_tokens=64)
        contents = [m.content for m in request.conversation]
        self.assertIn("the most relevant turn", contents)
        self.assertNotIn("an older, less relevant turn " * 20, contents)

    def test_language_context_and_system_prompt_are_never_dropped_for_budget(self):
        understanding = _understanding("Hello there, how are you?")
        request = build_inference_request(
            understanding, system_prompt="Be concise.",
            max_context_turns=4, context_length=64, max_output_tokens=32)
        self.assertEqual(request.system_prompt, "Be concise.")
        self.assertIsNotNone(request.language_context)


# ======================================================================
class TestRequestNeverExceedsConfiguredContextLimit(unittest.TestCase):
    """5. request never exceeds configured context limit"""

    def test_estimated_prompt_size_stays_within_context_length(self):
        turns = [_item(i, i + 1, f"turn {i} " * 50, f"reply {i} " * 50) for i in range(8)]
        understanding = _understanding("A question.", relevant_context=_relevant(turns))
        context_length, max_output_tokens = 512, 128
        request = build_inference_request(
            understanding, max_context_turns=4,
            context_length=context_length, max_output_tokens=max_output_tokens)
        runtime = StubRuntime(_config(context_length=context_length,
                                      max_output_tokens=max_output_tokens))
        estimate = runtime._estimate_prompt_tokens(request)
        self.assertLessEqual(estimate + max_output_tokens, context_length)

    def test_end_to_end_generation_succeeds_once_bounded(self):
        turns = [_item(i, i + 1, f"turn {i} " * 50, f"reply {i} " * 50) for i in range(8)]
        runtime = StubRuntime(_config(context_length=512, max_output_tokens=128))
        backend = LocalLanguageModelBackend(runtime, max_context_turns=4)
        response = backend.generate_response(
            _understanding("A question.", relevant_context=_relevant(turns)))
        self.assertEqual(response.status, STATUS_GENERATED)


# ======================================================================
class TestMaximumOutputLimitIsRespected(unittest.TestCase):
    """6. maximum output limit is respected"""

    def test_resolve_request_size_limits_never_lets_output_reach_context_length(self):
        context_length, max_output_tokens = resolve_request_size_limits(100, 100)
        self.assertLess(max_output_tokens, context_length)

    def test_unknown_limits_fall_back_to_local_model_config_defaults(self):
        context_length, max_output_tokens = resolve_request_size_limits(None, None)
        self.assertEqual(context_length, DEFAULT_CONTEXT_LENGTH)
        self.assertEqual(max_output_tokens, DEFAULT_MAX_OUTPUT_TOKENS)

    def test_a_request_asking_for_more_output_than_configured_is_rejected(self):
        runtime = StubRuntime(_config(context_length=2048, max_output_tokens=64))
        backend = LocalLanguageModelBackend(
            runtime, generation_parameters=GenerationParameters(max_output_tokens=999))
        response = backend.generate_response(_understanding("Hello."))
        self.assertEqual(response.status, STATUS_MODEL_FAILED)
        self.assertEqual(response.error_code, ERROR_MAX_OUTPUT_TOKENS_EXCEEDED)
        self.assertEqual(runtime.requests, [])  # never ran; discovered before loading/running


# ======================================================================
class TestImpossibleRequestReturnsStructuredFailure(unittest.TestCase):
    """7. impossible request returns a structured failure"""

    def test_user_message_alone_too_large_for_the_context_is_a_resource_limit_failure(self):
        runtime = StubRuntime(_config(context_length=70, max_output_tokens=64))
        backend = LocalLanguageModelBackend(runtime)
        response = backend.generate_response(_understanding("word " * 200))
        self.assertEqual(response.status, STATUS_MODEL_FAILED)
        self.assertEqual(response.inference_status, STATUS_RESOURCE_LIMIT)
        self.assertEqual(response.error_code, ERROR_CONTEXT_LENGTH_EXCEEDED)
        self.assertIsNone(response.response_text)
        # Never crashed, never loaded/ran the model, never fabricated text.
        self.assertEqual(runtime.load_calls, 0)
        self.assertEqual(runtime.requests, [])

    def test_impossible_request_does_not_silently_discard_the_user_message(self):
        # Construction itself never refuses to build the request or
        # rewrites the message - it stays verbatim on the (failed) request
        # the runtime saw would not fit, once one is actually built.
        raw = "word " * 200
        understanding = _understanding(raw)
        request = build_inference_request(
            understanding, max_context_turns=4, context_length=70, max_output_tokens=64)
        self.assertEqual(request.user_input, raw)


# ======================================================================
class TestExistingNormalConversationBehaviorRemainsCompatible(unittest.TestCase):
    """8. existing normal conversation behavior remains compatible"""

    def test_no_limits_given_behaves_like_before_prompt_404(self):
        turns = [_item(0, 1, "Python is great.", "Agreed.")]
        understanding = _understanding("Tell me more.", relevant_context=_relevant(turns))
        request = build_inference_request(understanding, max_context_turns=4)
        contents = [m.content for m in request.conversation]
        self.assertIn("Python is great.", contents)

    def test_end_to_end_conversation_with_no_configured_model_is_unaffected(self):
        backend = LocalLanguageModelBackend()
        response = backend.generate_response(_understanding("Hello."))
        self.assertEqual(response.status, "model_not_configured")

    def test_ordinary_short_conversation_still_generates_successfully(self):
        runtime = StubRuntime(_config())
        backend = LocalLanguageModelBackend(runtime, max_context_turns=4)
        turns = [_item(0, 1, "We talked about Android.", "Got it.")]
        response = backend.generate_response(
            _understanding("What did we talk about?", relevant_context=_relevant(turns)))
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(
            runtime.requests[0].conversation[0].content, "We talked about Android.")


if __name__ == "__main__":
    unittest.main()
