"""
Tests for Prompt 412 - Standardized Local Inference Result.

`inference.InferenceResult` is the ONE structured result of every inference
attempt (nine statuses). This stage guarantees it at the runtime -> provider
-> backend boundary (`standardize_inference_result`) and preserves a failure's
useful error information in the backend's response. Test doubles only at the
runtime boundary - no model.

Run directly:
    python -m unittest tests.test_standardized_inference_result -v
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.backend import BACKEND_KIND_LOCAL_MODEL, BACKEND_KIND_DETERMINISTIC_FALLBACK
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.local_model_mapping import (
    map_inference_result, map_runtime_exception, map_runtime_misbehavior, failure_details,
)
from language_intelligence.local_model_provider import LocalModelProvider, RuntimeBackedProvider
from language_intelligence.local_model_runtime import (
    CancellationToken, LocalModelError, ModelLoadError, RuntimeOutput,
)
from language_intelligence.inference import (
    ALL_INFERENCE_STATUSES, GenerationParameters, InferenceRequest, InferenceResult,
    standardize_inference_result, inference_failure_from_exception,
    STATUS_SUCCESS, STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED,
    STATUS_INFERENCE_FAILED, STATUS_INVALID_REQUEST, STATUS_RESOURCE_LIMIT, STATUS_TIMEOUT,
    STATUS_CANCELLED,
    ERROR_NO_CONFIGURATION, ERROR_RUNTIME_DEPENDENCY_MISSING, ERROR_LOAD_FAILED,
    ERROR_INFERENCE_FAILED, ERROR_INVALID_REQUEST, ERROR_MAX_OUTPUT_TOKENS_EXCEEDED,
    ERROR_TIMED_OUT, ERROR_CANCELLED, ERROR_INVALID_RUNTIME_OUTPUT,
)
from language_intelligence.response_generation import (
    ResponseGenerationResult, STATUS_GENERATED, STATUS_MODEL_FAILED, STATUS_MODEL_NOT_CONFIGURED as R_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE as R_UNAVAILABLE,
)
from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT, _core
from tests.test_local_inference_timeout_cancellation import FakeClock, ScriptedRuntime


class Double(ScriptedRuntime):
    """ScriptedRuntime plus scripted load / inference errors and dependency state."""

    def __init__(self, config, clock=None):
        super().__init__(config, clock or FakeClock())
        self.dependency_ok = True
        self.load_error = None
        self.infer_error = None

    def dependency_status(self):
        return (True, "") if self.dependency_ok else (False, "engine missing")

    def _load_model(self, config):
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error

    def _run_inference(self, request, params, config, control):
        if self.infer_error is not None:
            self.inferences += 1
            raise self.infer_error
        return super()._run_inference(request, params, config, control)


class StdCase(GuardCase):
    def double(self, **overrides):
        return Double(self.config(**overrides))

    def scenario(self, name):
        """(runtime, provider_request_or_None, token, backend_kwargs, expected inference status, code)"""
        if name == "success":
            return self.double(), None, None, {}, STATUS_SUCCESS, None
        if name == "not_configured":
            return Double(None), None, None, {}, STATUS_MODEL_NOT_CONFIGURED, ERROR_NO_CONFIGURATION
        if name == "unavailable":
            rt = self.double(); rt.dependency_ok = False
            return rt, None, None, {}, STATUS_MODEL_UNAVAILABLE, ERROR_RUNTIME_DEPENDENCY_MISSING
        if name == "load_failed":
            rt = self.double(); rt.load_error = ModelLoadError("corrupt weights")
            return rt, None, None, {}, STATUS_MODEL_LOAD_FAILED, ERROR_LOAD_FAILED
        if name == "inference_failed":
            rt = self.double(); rt.infer_error = LocalModelError("engine crashed")
            return rt, None, None, {}, STATUS_INFERENCE_FAILED, ERROR_INFERENCE_FAILED
        if name == "resource_limit":
            return (self.double(max_output_tokens=64), None, None,
                    {"generation_parameters": GenerationParameters(max_output_tokens=65)},
                    STATUS_RESOURCE_LIMIT, ERROR_MAX_OUTPUT_TOKENS_EXCEEDED)
        if name == "timeout":
            rt = self.double(timeout_seconds=5.0); rt.spend, rt.poll = 6.0, True
            return rt, None, None, {}, STATUS_TIMEOUT, ERROR_TIMED_OUT
        if name == "cancelled":
            token = CancellationToken(); token.cancel()
            return self.double(), None, token, {}, STATUS_CANCELLED, ERROR_CANCELLED
        raise KeyError(name)

    ALL = ("success", "not_configured", "unavailable", "load_failed", "inference_failed",
           "resource_limit", "timeout", "cancelled")


class TestSuccessIsTheStandardResult(StdCase):
    """1 + 3."""

    def test_runtime_returns_a_standard_success(self):
        rt = self.double()
        result = rt.generate(InferenceRequest("hello"))
        self.assertIsInstance(result, InferenceResult)
        self.assertEqual((result.status, result.text, result.ok), (STATUS_SUCCESS, MODEL_TEXT, True))
        self.assertEqual((result.model_id, result.runtime_name), ("test-model", "scripted-runtime"))
        self.assertEqual((result.prompt_tokens, result.output_tokens, result.finish_reason), (7, 5, "stop"))
        self.assertTrue(result.request_id)

    def test_provider_hands_the_same_result_object_through(self):
        provider = RuntimeBackedProvider(self.double())
        result = provider.generate(InferenceRequest("hello"))
        self.assertEqual(result.text, MODEL_TEXT)
        self.assertIs(standardize_inference_result(result), result)

    def test_backend_response_preserves_text_identity_and_metadata(self):
        response = LocalLanguageModelBackend(runtime=self.double()).generate_response(self.understanding())
        self.assertEqual((response.status, response.inference_status), (STATUS_GENERATED, STATUS_SUCCESS))
        self.assertEqual(response.response_text, MODEL_TEXT)
        meta = response.metadata
        self.assertEqual((meta["model_id"], meta["runtime_name"]), ("test-model", "scripted-runtime"))
        self.assertEqual((meta["prompt_tokens"], meta["output_tokens"], meta["finish_reason"]),
                         (7, 5, "stop"))
        self.assertIn("provider_id", meta)
        self.assertNotIn("details", meta)


class TestEveryCategoryIsRepresented(StdCase):
    """2. each failure category comes back as a standard InferenceResult AND a standard response"""

    def test_runtime_and_provider_level(self):
        for name in self.ALL:
            with self.subTest(category=name):
                rt, _, token, kwargs, status, code = self.scenario(name)
                params = kwargs.get("generation_parameters")
                request = InferenceRequest("hello", parameters=params)
                result = RuntimeBackedProvider(rt).generate(request, token)
                self.assertIsInstance(result, InferenceResult)
                self.assertEqual((result.status, result.error_code), (status, code))
                self.assertIn(result.status, ALL_INFERENCE_STATUSES)
                self.assertEqual(result.ok, status == STATUS_SUCCESS)
                self.assertEqual(result.text is not None, status == STATUS_SUCCESS)

    def test_invalid_request(self):
        result = RuntimeBackedProvider(self.double()).generate(InferenceRequest(""))
        self.assertEqual((result.status, result.error_code), (STATUS_INVALID_REQUEST, ERROR_INVALID_REQUEST))
        self.assertIsNone(result.text)
        self.assertTrue(result.details.get("problems"))

    def test_backend_level(self):
        expected_response = {
            STATUS_SUCCESS: STATUS_GENERATED, STATUS_MODEL_NOT_CONFIGURED: R_NOT_CONFIGURED,
            STATUS_MODEL_UNAVAILABLE: R_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED: R_UNAVAILABLE,
            STATUS_INFERENCE_FAILED: STATUS_MODEL_FAILED, STATUS_RESOURCE_LIMIT: STATUS_MODEL_FAILED,
            STATUS_TIMEOUT: STATUS_MODEL_FAILED, STATUS_CANCELLED: STATUS_MODEL_FAILED,
        }
        for name in self.ALL:
            with self.subTest(category=name):
                rt, _, token, kwargs, status, code = self.scenario(name)
                backend = LocalLanguageModelBackend(runtime=rt, **kwargs)
                if name == "load_failed":  # the one permitted attempt, then reported as not ready
                    backend.generate_response(self.understanding())
                response = backend.generate_response(self.understanding(), cancellation_token=token)
                self.assertIsInstance(response, ResponseGenerationResult)
                self.assertEqual(response.status, expected_response[status])
                self.assertEqual(response.inference_status, status)
                self.assertEqual(response.error_code, code)
                self.assertEqual(response.response_text is not None, status == STATUS_SUCCESS)

    def test_every_status_is_covered_by_this_module(self):
        covered = {self.scenario(n)[4] for n in self.ALL} | {STATUS_INVALID_REQUEST}
        self.assertEqual(covered, set(ALL_INFERENCE_STATUSES))


class TestFailureInformationIsPreserved(StdCase):
    """4."""

    def test_error_code_reason_ids_and_details(self):
        backend = LocalLanguageModelBackend(
            runtime=self.double(max_output_tokens=64),
            generation_parameters=GenerationParameters(max_output_tokens=65))
        response = backend.generate_response(self.understanding())
        self.assertEqual(response.error_code, ERROR_MAX_OUTPUT_TOKENS_EXCEEDED)
        self.assertIn("65", response.reason)
        self.assertEqual(response.metadata["model_id"], "test-model")
        self.assertEqual(response.metadata["details"], {"requested": 65, "limit": 64})
        self.assertEqual(response.to_dict()["metadata"]["details"], {"requested": 65, "limit": 64})

    def test_details_keep_only_safe_scalars(self):
        result = InferenceResult.failure(
            STATUS_INFERENCE_FAILED, "c", "m",
            details={"limit": 3, "note": "x" * 500, "output_preview": "MODEL OUTPUT",
                     "problems": ["a"], "nested": {"a": 1}})
        kept = failure_details(result)
        self.assertEqual(set(kept), {"limit", "note"})
        self.assertEqual(len(kept["note"]), 200)
        self.assertNotIn("MODEL OUTPUT", str(map_inference_result(result, "b").to_dict()))

    def test_failure_without_details_adds_no_details_key(self):
        response = LocalLanguageModelBackend(runtime=Double(None)).generate_response(self.understanding())
        self.assertNotIn("details", response.metadata)
        self.assertEqual(response.error_code, ERROR_NO_CONFIGURATION)


class TestTimeoutAndCancellationStayDistinguishable(StdCase):
    """5."""

    def test_distinct_statuses_codes_and_responses(self):
        out = {}
        for name in ("timeout", "cancelled"):
            rt, _, token, kwargs, *_ = self.scenario(name)
            out[name] = LocalLanguageModelBackend(runtime=rt).generate_response(
                self.understanding(), cancellation_token=token)
        self.assertEqual((out["timeout"].inference_status, out["timeout"].error_code),
                         (STATUS_TIMEOUT, ERROR_TIMED_OUT))
        self.assertEqual((out["cancelled"].inference_status, out["cancelled"].error_code),
                         (STATUS_CANCELLED, ERROR_CANCELLED))
        self.assertNotEqual(out["timeout"].inference_status, out["cancelled"].inference_status)
        self.assertEqual(out["timeout"].status, out["cancelled"].status)  # same family, finer fields differ


class TestContractBreachesBecomeStructuredFailures(StdCase):
    """the boundary always yields a valid InferenceResult"""

    def test_standardize_pure_cases(self):
        bad_type = standardize_inference_result({"status": "success", "text": "x"}, runtime_name="r")
        self.assertEqual((bad_type.status, bad_type.error_code, bad_type.runtime_name),
                         (STATUS_INFERENCE_FAILED, ERROR_INVALID_RUNTIME_OUTPUT, "r"))
        unknown = standardize_inference_result(InferenceResult("something_new", model_id="m"))
        self.assertEqual((unknown.status, unknown.model_id), (STATUS_INFERENCE_FAILED, "m"))
        for text in (None, "", "  ", 42):
            empty = standardize_inference_result(InferenceResult(STATUS_SUCCESS, text=text, model_id="m"))
            self.assertEqual((empty.status, empty.error_code, empty.text, empty.model_id),
                             (STATUS_INFERENCE_FAILED, ERROR_INVALID_RUNTIME_OUTPUT, None, "m"))
        leaked = standardize_inference_result(
            InferenceResult(STATUS_TIMEOUT, text="late output", error_code=ERROR_TIMED_OUT))
        self.assertEqual((leaked.status, leaked.text, leaked.error_code),
                         (STATUS_TIMEOUT, None, ERROR_TIMED_OUT))

    def test_exception_keeps_only_the_type_name(self):
        result = inference_failure_from_exception(RuntimeError("secret /data/model.bin"), runtime_name="r")
        self.assertEqual((result.status, result.error_code), (STATUS_INFERENCE_FAILED, ERROR_INFERENCE_FAILED))
        self.assertIn("RuntimeError", result.error_message)
        self.assertNotIn("secret", str(result.to_dict()))

    def test_runtime_that_raises_or_returns_junk_is_standardized_by_the_provider(self):
        class Raising(Double):
            def generate(self, request, cancellation_token=None):
                raise RuntimeError("secret detail")

        class Junk(Double):
            def generate(self, request, cancellation_token=None):
                return "plain text"

        for cls in (Raising, Junk):
            with self.subTest(runtime=cls.__name__):
                result = RuntimeBackedProvider(cls(self.config())).generate(InferenceRequest("hi"))
                self.assertIsInstance(result, InferenceResult)
                self.assertFalse(result.ok)
                self.assertEqual(result.runtime_name, "scripted-runtime")
                self.assertNotIn("secret", str(result.to_dict()))
                response = LocalLanguageModelBackend(runtime=cls(self.config())).generate_response(
                    self.understanding())
                self.assertEqual(response.status, STATUS_MODEL_FAILED)
                self.assertIsNone(response.response_text)
                self.assertNotIn("secret", str(response.to_dict()))

    def test_success_without_text_is_no_longer_labelled_success(self):
        mapped = map_inference_result(InferenceResult(STATUS_SUCCESS, text=" "), BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual((mapped.status, mapped.inference_status, mapped.error_code),
                         (STATUS_MODEL_FAILED, STATUS_INFERENCE_FAILED, ERROR_INVALID_RUNTIME_OUTPUT))


class TestFallbackStillWorks(StdCase):
    """6."""

    def test_every_failure_category_reaches_the_fallback(self):
        control, _ = _core(self)
        expected = control.process_input(MESSAGE)
        for name in self.ALL[1:]:
            with self.subTest(category=name):
                rt, _, token, kwargs, status, _code = self.scenario(name)
                core, _ = _core(self)
                li = LanguageIntelligenceCore(
                    LocalLanguageModelBackend(runtime=rt, **kwargs),
                    fallback_backend=DeterministicFallbackBackend(core.understanding))
                core.language_intelligence = li
                if name == "cancelled":
                    response = core.generate_language_response(
                        core.understand_language(MESSAGE), cancellation_token=token)
                else:
                    self.assertEqual(core.process_input(MESSAGE), expected)
                    response = core.get_last_language_response()
                self.assertEqual(response.inference_status, status)
                self.assertIsNone(response.response_text)
                self.assertEqual(response.fallback_backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)

    def test_success_still_uses_the_model_and_no_fallback(self):
        core, _ = _core(self)
        core.language_intelligence = LanguageIntelligenceCore(
            LocalLanguageModelBackend(runtime=self.double()),
            fallback_backend=DeterministicFallbackBackend(core.understanding))
        self.assertEqual(core.process_input(MESSAGE), MODEL_TEXT)
        self.assertIsNone(core.get_last_language_response().fallback_backend_kind)


class TestExistingCallersDoNotBreak(StdCase):
    """7."""

    def test_valid_results_pass_through_map_unchanged(self):
        ok = InferenceResult.success("real", model_id="m", runtime_name="r", prompt_tokens=3)
        mapped = map_inference_result(ok, "local_model")
        self.assertEqual((mapped.status, mapped.response_text, mapped.metadata["prompt_tokens"]),
                         (STATUS_GENERATED, "real", 3))

    def test_old_helpers_still_exist_and_return_structured_failures(self):
        exc = map_runtime_exception(RuntimeError("secret"), "local_model")
        self.assertEqual((exc.status, exc.error_code), (STATUS_MODEL_FAILED, ERROR_INFERENCE_FAILED))
        self.assertIn("RuntimeError", exc.reason)
        self.assertNotIn("secret", str(exc.to_dict()))
        mis = map_runtime_misbehavior("local_model", ERROR_INVALID_RUNTIME_OUTPUT, "why")
        self.assertEqual((mis.status, mis.reason), (STATUS_MODEL_FAILED, "why"))

    def test_response_result_shape_is_unchanged(self):
        # additive since Prompt 414 (selected_backend_kind): every earlier key is still there
        self.assertLessEqual({"status", "response_text", "reason", "backend_kind", "inference_status",
                              "error_code", "metadata", "fallback_backend_kind"},
                             set(ResponseGenerationResult(STATUS_GENERATED).to_dict()))
        self.assertEqual(set(InferenceResult.success("x").to_dict()),
                         {"status", "text", "structured_output", "error_code", "error_message",
                          "runtime_name", "model_id", "request_id", "elapsed_seconds", "prompt_tokens",
                          "output_tokens", "finish_reason", "details"})

    def test_custom_provider_returning_a_valid_result_is_untouched(self):
        class Custom(LocalModelProvider):
            @property
            def provider_id(self):
                return "custom"

            def availability(self):
                return Double(GuardCase.config(self)).availability()

            def resource_status(self):
                return {"state": "ready", "loaded": False, "limits": None}

            def generate(self, request, cancellation_token=None):
                return InferenceResult.success("from custom", model_id="c", runtime_name="cr")

        Custom.config = lambda: None
        response = LocalLanguageModelBackend(provider=Custom()).generate_response(self.understanding())
        self.assertEqual((response.status, response.response_text), (STATUS_GENERATED, "from custom"))

    def test_custom_provider_returning_junk_is_a_structured_failure(self):
        class Junk(LocalModelProvider):
            @property
            def provider_id(self):
                return "junk"

            def availability(self):
                raise RuntimeError("unknown")

            def generate(self, request, cancellation_token=None):
                return None

        response = LocalLanguageModelBackend(provider=Junk()).generate_response(self.understanding())
        self.assertEqual((response.status, response.error_code, response.metadata["provider_id"]),
                         (STATUS_MODEL_FAILED, ERROR_INVALID_RUNTIME_OUTPUT, "junk"))
        self.assertIsNone(response.response_text)


if __name__ == "__main__":
    unittest.main()
