"""
Tests for Prompt 411 - Local Inference Timeout and Cancellation.

The runtime already enforces the configured timeout and honours a
CancellationToken; this stage lets a caller reach that mechanism through
Core -> LanguageIntelligenceCore -> LocalLanguageModelBackend -> provider ->
runtime. A timed-out / cancelled request is the existing structured failure
(never text), reaches Prompt 406's fallback, and never triggers a second
inference. Test doubles only at the runtime boundary (fake clock, scripted
`_run_inference`) - no model, no sleeping, no threads.

Run directly:
    python -m unittest tests.test_local_inference_timeout_cancellation -v
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.local_model_provider import RuntimeBackedProvider
from language_intelligence.local_model_runtime import (
    CancellationToken, LocalModelRuntime, RuntimeOutput,
)
from language_intelligence.inference import (
    STATUS_SUCCESS, STATUS_TIMEOUT, STATUS_CANCELLED,
    ERROR_TIMED_OUT, ERROR_COMPLETED_AFTER_DEADLINE, ERROR_CANCELLED,
)
from language_intelligence.response_generation import STATUS_GENERATED, STATUS_MODEL_FAILED
from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT, _core


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ScriptedRuntime(LocalModelRuntime):
    """TEST DOUBLE at the runtime boundary (not a model)."""

    def __init__(self, config, clock):
        super().__init__(config=config, clock=clock)
        self.clock = clock
        self.load_calls = 0
        self.inferences = 0
        self.spend = 0.0            # simulated seconds "inferring"
        self.poll = False           # observe control.check() like a cooperative engine
        self.cancel_during = None   # token cancelled while "running"
        self.late_calls = 0         # work done after control.check() should have stopped it

    @property
    def runtime_name(self):
        return "scripted-runtime"

    def dependency_status(self):
        return True, ""

    def _load_model(self, config):
        self.load_calls += 1

    def _run_inference(self, request, params, config, control):
        self.inferences += 1
        if self.cancel_during is not None:
            self.cancel_during.cancel()
        self.clock.advance(self.spend)
        if self.poll:
            control.check()
        self.late_calls += 1        # only reached if not interrupted
        return RuntimeOutput(MODEL_TEXT, "stop", prompt_tokens=7, output_tokens=5)


class TimeoutCase(GuardCase):
    def make(self, **overrides):
        clock = FakeClock()
        return ScriptedRuntime(self.config(**overrides), clock)

    def backend(self, runtime, **kwargs):
        return LocalLanguageModelBackend(runtime=runtime, **kwargs)


class TestNormalRequestStillSucceeds(TimeoutCase):
    """1."""

    def test_success_without_a_token(self):
        runtime = self.make()
        response = self.backend(runtime).generate_response(self.understanding())
        self.assertEqual((response.status, response.inference_status), (STATUS_GENERATED, STATUS_SUCCESS))
        self.assertEqual(response.response_text, MODEL_TEXT)
        self.assertEqual((runtime.load_calls, runtime.inferences), (1, 1))

    def test_success_with_an_uncancelled_token(self):
        runtime = self.make()
        response = self.backend(runtime).generate_response(
            self.understanding(), cancellation_token=CancellationToken())
        self.assertEqual(response.response_text, MODEL_TEXT)

    def test_finishing_exactly_at_the_configured_timeout_succeeds(self):
        runtime = self.make(timeout_seconds=10.0)
        runtime.spend = 10.0
        self.assertEqual(self.backend(runtime).generate_response(self.understanding()).status,
                         STATUS_GENERATED)


class TestTimeout(TimeoutCase):
    """2 + 4. exceeding the configured timeout -> the existing TIMEOUT failure, never a success"""

    def test_cooperative_runtime_is_interrupted_by_the_configured_timeout(self):
        runtime = self.make(timeout_seconds=5.0)
        runtime.spend, runtime.poll = 6.0, True
        response = self.backend(runtime).generate_response(self.understanding())
        self.assertEqual((response.status, response.inference_status, response.error_code),
                         (STATUS_MODEL_FAILED, STATUS_TIMEOUT, ERROR_TIMED_OUT))
        self.assertEqual(runtime.late_calls, 0)  # the inference was actually stopped
        self.assertIsNone(response.response_text)

    def test_runtime_that_ignores_the_deadline_has_its_late_output_discarded(self):
        runtime = self.make(timeout_seconds=5.0)
        runtime.spend = 6.0
        response = self.backend(runtime).generate_response(self.understanding())
        self.assertEqual((response.status, response.inference_status, response.error_code),
                         (STATUS_MODEL_FAILED, STATUS_TIMEOUT, ERROR_COMPLETED_AFTER_DEADLINE))
        self.assertIsNone(response.response_text)
        self.assertNotIn(MODEL_TEXT, str(response.to_dict()))

    def test_lower_backend_timeout_is_applied(self):
        runtime = self.make(timeout_seconds=30.0)
        runtime.spend, runtime.poll = 3.0, True
        response = self.backend(runtime, timeout_seconds=2.0).generate_response(self.understanding())
        self.assertEqual(response.inference_status, STATUS_TIMEOUT)

    def test_timeout_is_not_reported_as_success_anywhere(self):
        runtime = self.make(timeout_seconds=5.0)
        runtime.spend = 6.0
        response = self.backend(runtime).generate_response(self.understanding())
        self.assertNotEqual(response.status, STATUS_GENERATED)
        self.assertNotEqual(response.inference_status, STATUS_SUCCESS)
        self.assertIsNone(response.response_text)


class TestCancellation(TimeoutCase):
    """3 + 5. a cancelled request -> the existing CANCELLED failure, never a success"""

    def test_cancelled_before_start_never_loads_or_infers(self):
        runtime = self.make()
        token = CancellationToken()
        token.cancel()
        response = self.backend(runtime).generate_response(self.understanding(), cancellation_token=token)
        self.assertEqual((response.status, response.inference_status, response.error_code),
                         (STATUS_MODEL_FAILED, STATUS_CANCELLED, ERROR_CANCELLED))
        self.assertEqual((runtime.load_calls, runtime.inferences), (0, 0))
        self.assertIsNone(response.response_text)

    def test_cancelled_during_inference_interrupts_a_cooperative_runtime(self):
        runtime = self.make()
        token = CancellationToken()
        runtime.cancel_during, runtime.poll = token, True
        response = self.backend(runtime).generate_response(self.understanding(), cancellation_token=token)
        self.assertEqual((response.status, response.inference_status, response.error_code),
                         (STATUS_MODEL_FAILED, STATUS_CANCELLED, ERROR_CANCELLED))
        self.assertEqual(runtime.late_calls, 0)
        self.assertIsNone(response.response_text)

    def test_cancellation_a_runtime_ignores_still_discards_the_output(self):
        runtime = self.make()
        token = CancellationToken()
        runtime.cancel_during = token
        response = self.backend(runtime).generate_response(self.understanding(), cancellation_token=token)
        self.assertEqual(response.inference_status, STATUS_CANCELLED)
        self.assertIsNone(response.response_text)
        self.assertNotIn(MODEL_TEXT, str(response.to_dict()))

    def test_token_reaches_the_provider_only_when_given(self):
        seen = []

        class SpyProvider(RuntimeBackedProvider):
            def generate(self, request, cancellation_token=None):
                seen.append(cancellation_token)
                return super().generate(request, cancellation_token)

        token = CancellationToken()
        backend = LocalLanguageModelBackend(provider=SpyProvider(self.make()))
        backend.generate_response(self.understanding())
        backend.generate_response(self.understanding(), cancellation_token=token)
        self.assertEqual(seen, [None, token])

    def test_cancelling_one_request_does_not_affect_the_next(self):
        runtime = self.make()
        backend = self.backend(runtime)
        token = CancellationToken()
        token.cancel()
        backend.generate_response(self.understanding(), cancellation_token=token)
        self.assertEqual(backend.generate_response(self.understanding()).status, STATUS_GENERATED)
        self.assertEqual(runtime.inferences, 1)


class TestFallbackAfterTimeoutOrCancellation(TimeoutCase):
    """6."""

    def li(self, runtime, core):
        return LanguageIntelligenceCore(
            LocalLanguageModelBackend(runtime=runtime),
            fallback_backend=DeterministicFallbackBackend(core.understanding))

    def test_timeout_reaches_the_fallback_through_core(self):
        control, _ = _core(self)
        expected = control.process_input(MESSAGE)
        core, _ = _core(self)
        runtime = self.make(timeout_seconds=5.0)
        runtime.spend, runtime.poll = 6.0, True
        core.language_intelligence = self.li(runtime, core)
        self.assertEqual(core.process_input(MESSAGE), expected)
        response = core.get_last_language_response()
        self.assertEqual((response.status, response.inference_status),
                         (STATUS_MODEL_FAILED, STATUS_TIMEOUT))
        self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertIsNone(response.response_text)

    def test_cancellation_reaches_the_fallback_through_core(self):
        core, _ = _core(self)
        runtime = self.make()
        core.language_intelligence = self.li(runtime, core)
        understanding = core.understand_language(MESSAGE)
        token = CancellationToken()
        token.cancel()
        response = core.generate_language_response(understanding, cancellation_token=token)
        self.assertEqual((response.status, response.inference_status),
                         (STATUS_MODEL_FAILED, STATUS_CANCELLED))
        self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertEqual(runtime.inferences, 0)

    def test_deterministic_backend_accepts_and_ignores_a_token(self):
        core, _ = _core(self)
        li = LanguageIntelligenceCore(DeterministicFallbackBackend(core.understanding))
        understanding = self.understanding()
        token = CancellationToken()
        token.cancel()
        self.assertEqual(li.generate_response(understanding, cancellation_token=token).status,
                         li.generate_response(understanding).status)

    def test_without_a_fallback_the_failure_is_still_returned(self):
        runtime = self.make(timeout_seconds=5.0)
        runtime.spend = 6.0
        li = LanguageIntelligenceCore(LocalLanguageModelBackend(runtime=runtime))
        response = li.generate_response(self.understanding())
        self.assertEqual(response.inference_status, STATUS_TIMEOUT)
        self.assertIsNone(response.fallback_backend_kind)


class TestNoDuplicateInference(TimeoutCase):
    """7."""

    def test_timeout_runs_exactly_one_inference_and_is_not_retried(self):
        runtime = self.make(timeout_seconds=5.0)
        runtime.spend = 6.0
        self.backend(runtime).generate_response(self.understanding())
        self.assertEqual((runtime.load_calls, runtime.inferences), (1, 1))

    def test_cancelled_during_run_runs_exactly_one_inference(self):
        runtime = self.make()
        token = CancellationToken()
        runtime.cancel_during = token
        self.backend(runtime).generate_response(self.understanding(), cancellation_token=token)
        self.assertEqual(runtime.inferences, 1)

    def test_fallback_does_not_rerun_the_model(self):
        core, _ = _core(self)
        runtime = self.make(timeout_seconds=5.0)
        runtime.spend, runtime.poll = 6.0, True
        core.language_intelligence = LanguageIntelligenceCore(
            LocalLanguageModelBackend(runtime=runtime),
            fallback_backend=DeterministicFallbackBackend(core.understanding))
        core.process_input(MESSAGE)
        self.assertEqual(runtime.inferences, 1)

    def test_late_output_never_shows_up_in_a_later_result(self):
        runtime = self.make(timeout_seconds=5.0)
        runtime.spend = 6.0
        backend = self.backend(runtime)
        backend.generate_response(self.understanding())
        runtime.spend = 0.0
        second = backend.generate_response(self.understanding())
        self.assertEqual(second.response_text, MODEL_TEXT)
        self.assertEqual(runtime.inferences, 2)  # exactly one per request


if __name__ == "__main__":
    unittest.main()
