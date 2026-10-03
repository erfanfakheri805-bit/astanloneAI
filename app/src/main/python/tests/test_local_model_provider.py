"""
Tests for Prompt 400 - the Local Model Provider / adapter layer
(language_intelligence/local_model_provider.py and the backend's use of it).

IMPORTANT - about the test doubles: `ScriptedProvider` and `TinyRuntime`
below are TEST DOUBLES at the provider / runtime boundary. Their output is
whatever a test scripts into them; they are NOT language models and perform
NO inference. No model is downloaded, no network is used.

Run directly:
    python -m unittest tests.test_local_model_provider -v
(from app/src/main/python/)
"""

import os
import re
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import language_intelligence
from understanding.engine import UnderstandingEngine
from core.core import Core

from language_intelligence.backend import (
    BACKEND_KIND_DETERMINISTIC_FALLBACK, BACKEND_KIND_LOCAL_MODEL,
)
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.response_generation import (
    STATUS_DEFERRED, STATUS_GENERATED, STATUS_MODEL_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_FAILED,
)
from language_intelligence.local_model_config import LocalModelConfig
from language_intelligence.inference import (
    InferenceResult, STATUS_SUCCESS, STATUS_MODEL_NOT_CONFIGURED as INF_NOT_CONFIGURED,
    STATUS_MODEL_UNAVAILABLE as INF_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED,
    STATUS_INFERENCE_FAILED, STATUS_TIMEOUT, STATUS_CANCELLED, STATUS_RESOURCE_LIMIT,
    STATUS_INVALID_REQUEST,
    ERROR_NO_CONFIGURATION, ERROR_LOAD_FAILED, ERROR_TIMED_OUT, ERROR_CONTEXT_LENGTH_EXCEEDED,
    ERROR_INFERENCE_FAILED,
)
from language_intelligence.local_model_runtime import (
    LocalModelRuntime, ModelAvailability, ModelLoadResult, RuntimeOutput,
    ModelLoadError, InferenceExecutionError, CancellationToken,
    LOAD_OK, LOAD_FAILED, STATE_READY, STATE_UNLOADED, STATE_NOT_CONFIGURED,
    STATE_RUNTIME_UNAVAILABLE,
)
from language_intelligence.unavailable_runtime import UnavailableLocalModelRuntime
from language_intelligence.local_model_provider import (
    LocalModelProvider, RuntimeBackedProvider, ProviderRegistry, ModelInfo,
    ProviderRegistryError, UnknownProviderError,
)
from language_intelligence.local_model_backend import (
    LocalLanguageModelBackend, LocalModelBackendError,
)


# ----------------------------------------------------------------------
# Test doubles (NOT language models)
# ----------------------------------------------------------------------
class ScriptedProvider(LocalModelProvider):
    """TEST PROVIDER at the provider boundary: no runtime, no model.
    Returns exactly what a test scripts."""

    def __init__(self, provider_id="scripted", installed=True):
        self._id = provider_id
        self.installed = installed
        self.result = InferenceResult.success("provider-double-output", model_id="scripted-model",
                                              runtime_name="scripted-engine")
        self.load_result = ModelLoadResult(LOAD_OK, "ok", None, "scripted-model", "scripted-engine")
        self.requests = []
        self.load_calls = 0
        self.unload_calls = 0
        self.loaded = False

    @property
    def provider_id(self):
        return self._id

    def availability(self):
        if not self.installed:
            return ModelAvailability(False, False, False, False, False, False,
                                     STATE_NOT_CONFIGURED, ERROR_NO_CONFIGURATION,
                                     "scripted provider has no model")
        return ModelAvailability(True, True, True, True, self.loaded, True,
                                 STATE_READY if self.loaded else STATE_UNLOADED,
                                 model_id="scripted-model", runtime_name="scripted-engine")

    def model_info(self):
        return ModelInfo(self._id, model_id="scripted-model" if self.installed else None,
                         model_format="other", context_length=256, max_output_tokens=32,
                         loaded=self.loaded)

    def load(self):
        self.load_calls += 1
        self.loaded = self.load_result.ok
        return self.load_result

    def generate(self, request, cancellation_token=None):
        self.requests.append(request)
        self.loaded = True
        return self.result

    def unload(self):
        self.unload_calls += 1
        self.loaded = False
        return True

    def resource_status(self):
        return {"state": "ready" if self.loaded else "unloaded", "loaded": self.loaded,
                "limits": None}


class TinyRuntime(LocalModelRuntime):
    """TEST DOUBLE runtime (scripted output only)."""

    def __init__(self, config=None):
        super().__init__(config=config)
        self.load_error = None
        self.infer_error = None
        self.load_calls = 0

    @property
    def runtime_name(self):
        return "tiny-runtime"

    def _load_model(self, config):
        self.load_calls += 1
        if self.load_error:
            raise self.load_error

    def _run_inference(self, request, params, config, control):
        if self.infer_error:
            raise self.infer_error
        return RuntimeOutput("tiny-runtime-output", "stop", 5, 2)


def _config(path, **overrides):
    values = dict(model_id="tiny-model", model_path=path, context_length=512,
                  max_output_tokens=64, timeout_seconds=10.0)
    values.update(overrides)
    return LocalModelConfig(**values)


class _Files:
    def setUp(self):
        self._files = []

    def tearDown(self):
        for path in self._files:
            if os.path.exists(path):
                os.remove(path)

    def model_file(self):
        handle = tempfile.NamedTemporaryFile(suffix=".gguf", delete=False)
        handle.write(b"\0" * 16)
        handle.close()
        self._files.append(handle.name)
        return handle.name

    def tiny_runtime(self, **overrides):
        return TinyRuntime(_config(self.model_file(), **overrides))

    @staticmethod
    def understanding(text="What is Python?"):
        return DeterministicFallbackBackend(UnderstandingEngine()).understand(text)


# ======================================================================
class TestProviderRegistration(unittest.TestCase):
    """1. provider registration"""

    def test_register_and_list(self):
        registry = ProviderRegistry()
        a, b = ScriptedProvider("a"), ScriptedProvider("b")
        self.assertIs(registry.register(a), a)
        registry.register(b)
        self.assertEqual(registry.provider_ids(), ["a", "b"])
        self.assertIs(registry.get("b"), b)

    def test_duplicate_id_is_rejected(self):
        registry = ProviderRegistry()
        registry.register(ScriptedProvider("a"))
        with self.assertRaises(ProviderRegistryError):
            registry.register(ScriptedProvider("a"))
        self.assertEqual(registry.provider_ids(), ["a"])

    def test_non_provider_and_blank_id_are_rejected(self):
        registry = ProviderRegistry()
        with self.assertRaises(TypeError):
            registry.register(object())
        with self.assertRaises(TypeError):
            registry.register(UnavailableLocalModelRuntime())   # a runtime is not a provider
        with self.assertRaises(ProviderRegistryError):
            registry.register(ScriptedProvider("  "))
        self.assertEqual(registry.provider_ids(), [])

    def test_runtime_backed_provider_id_defaults_to_runtime_name(self):
        self.assertEqual(RuntimeBackedProvider(TinyRuntime()).provider_id, "tiny-runtime")
        self.assertEqual(RuntimeBackedProvider(TinyRuntime(), provider_id="light").provider_id,
                         "light")


class TestProviderSelection(unittest.TestCase):
    """2. provider selection, 3. unknown provider"""

    def test_first_registered_is_the_default(self):
        registry = ProviderRegistry()
        a, b = ScriptedProvider("a"), ScriptedProvider("b")
        registry.register(a)
        registry.register(b)
        self.assertEqual(registry.default_id, "a")
        self.assertIs(registry.select(), a)
        self.assertIs(registry.select("b"), b)

    def test_explicit_default_and_set_default(self):
        registry = ProviderRegistry()
        a, b = ScriptedProvider("a"), ScriptedProvider("b")
        registry.register(a)
        registry.register(b, default=True)
        self.assertIs(registry.select(), b)
        registry.set_default("a")
        self.assertIs(registry.select(), a)

    def test_unknown_provider_is_explicit(self):
        registry = ProviderRegistry()
        registry.register(ScriptedProvider("a"))
        for lookup in (registry.get, registry.select):
            with self.assertRaises(UnknownProviderError) as ctx:
                lookup("missing")
            self.assertEqual(ctx.exception.provider_id, "missing")
            self.assertIn("'a'", str(ctx.exception))
        with self.assertRaises(LookupError):
            registry.select("missing")
        with self.assertRaises(UnknownProviderError):
            registry.set_default("missing")

    def test_unhashable_lookup_is_unknown_not_a_crash(self):
        with self.assertRaises(UnknownProviderError):
            ProviderRegistry().get(["a"])

    def test_empty_registry_has_no_default(self):
        with self.assertRaises(ProviderRegistryError):
            ProviderRegistry().select()

    def test_backend_built_from_registry_uses_the_selected_provider(self):
        registry = ProviderRegistry()
        a, b = ScriptedProvider("a"), ScriptedProvider("b")
        b.result = InferenceResult.success("from b")
        registry.register(a)
        registry.register(b)
        response = LocalLanguageModelBackend.from_registry(registry, "b").generate_response(
            _Files.understanding())
        self.assertEqual(response.response_text, "from b")
        self.assertEqual(a.requests, [])
        self.assertEqual(len(b.requests), 1)

    def test_backend_from_registry_with_unknown_id_raises(self):
        with self.assertRaises(UnknownProviderError):
            LocalLanguageModelBackend.from_registry(ProviderRegistry(), "nope")

    def test_swapping_providers_needs_no_change_above_the_backend(self):
        understanding = _Files.understanding()
        registry = ProviderRegistry()
        for name, text in (("one", "answer one"), ("two", "answer two")):
            provider = ScriptedProvider(name)
            provider.result = InferenceResult.success(text)
            registry.register(provider)
        for name, text in (("one", "answer one"), ("two", "answer two")):
            core = LanguageIntelligenceCore(
                backend=LocalLanguageModelBackend.from_registry(registry, name))
            self.assertEqual(core.generate_response(understanding).response_text, text)


# ======================================================================
class TestProviderAvailability(_Files, unittest.TestCase):
    """4. provider availability"""

    def test_runtime_backed_states(self):
        self.assertEqual(RuntimeBackedProvider(TinyRuntime()).availability().state,
                         STATE_NOT_CONFIGURED)
        self.assertEqual(RuntimeBackedProvider(UnavailableLocalModelRuntime(
            _config("/x/m.gguf"))).availability().state, STATE_RUNTIME_UNAVAILABLE)
        runtime = self.tiny_runtime()
        availability = RuntimeBackedProvider(runtime).availability()
        self.assertEqual(availability.state, STATE_UNLOADED)
        self.assertTrue(availability.can_infer)
        self.assertEqual(runtime.load_calls, 0)               # never loads

    def test_backend_reports_the_providers_availability(self):
        provider = ScriptedProvider(installed=False)
        backend = LocalLanguageModelBackend(provider=provider)
        self.assertFalse(backend.check_availability().can_infer)
        provider.installed = True
        self.assertTrue(backend.check_availability().can_infer)

    def test_resource_status_reports_configured_limits_only(self):
        self.assertIsNone(RuntimeBackedProvider(TinyRuntime()).resource_status()["limits"])
        status = RuntimeBackedProvider(self.tiny_runtime(max_memory_mb=100)).resource_status()
        self.assertEqual(status["limits"]["context_length"], 512)
        self.assertEqual(status["limits"]["max_memory_mb"], 100)
        self.assertIsNone(status["limits"]["cpu_threads"])    # unset stays None
        self.assertFalse(status["loaded"])


class TestProviderModelMetadata(_Files, unittest.TestCase):
    """5. provider model metadata"""

    def test_no_model_configured_reports_unknowns_not_guesses(self):
        info = RuntimeBackedProvider(UnavailableLocalModelRuntime()).model_info()
        self.assertIsInstance(info, ModelInfo)
        self.assertEqual(info.provider_id, "unavailable")
        for field in ("model_id", "model_format", "supported_languages",
                      "context_length", "max_output_tokens"):
            self.assertIsNone(getattr(info, field), field)
        self.assertFalse(info.loaded)
        self.assertTrue(info.is_local)

    def test_configured_model_reports_only_what_is_configured(self):
        runtime = self.tiny_runtime()
        info = RuntimeBackedProvider(runtime).model_info()
        self.assertEqual(info.model_id, "tiny-model")
        self.assertEqual(info.model_format, "gguf")
        self.assertEqual((info.context_length, info.max_output_tokens), (512, 64))
        self.assertIsNone(info.supported_languages)          # never guessed
        self.assertEqual(info.runtime_name, "tiny-runtime")
        self.assertFalse(info.loaded)

    def test_loaded_flag_follows_the_runtime(self):
        provider = RuntimeBackedProvider(self.tiny_runtime())
        provider.load()
        self.assertTrue(provider.model_info().loaded)
        provider.unload()
        self.assertFalse(provider.model_info().loaded)

    def test_info_to_dict_and_known_languages(self):
        info = ModelInfo("p", model_id="m", supported_languages=["en", "fa"])
        self.assertEqual(info.to_dict()["supported_languages"], ["en", "fa"])
        self.assertIsNone(ModelInfo("p").to_dict()["supported_languages"])

    def test_backend_exposes_model_info(self):
        self.assertEqual(LocalLanguageModelBackend(provider=ScriptedProvider()).model_info()
                         .model_id, "scripted-model")
        self.assertIsNone(LocalLanguageModelBackend().model_info().model_id)


# ======================================================================
class TestInferenceThroughProviders(_Files, unittest.TestCase):
    """6. successful inference through a test provider"""

    def test_test_provider_full_flow(self):
        provider = ScriptedProvider()
        core = LanguageIntelligenceCore(backend=LocalLanguageModelBackend(provider=provider))
        response = core.generate_response(self.understanding("What is Python?"))
        self.assertEqual(response.status, STATUS_GENERATED)
        self.assertEqual(response.response_text, "provider-double-output")
        self.assertEqual(response.backend_kind, BACKEND_KIND_LOCAL_MODEL)
        self.assertEqual(response.metadata["provider_id"], "scripted")
        self.assertEqual(response.metadata["model_id"], "scripted-model")
        self.assertEqual(provider.requests[0].user_input, "What is Python?")

    def test_runtime_backed_provider_delegates_to_the_runtime(self):
        runtime = self.tiny_runtime()
        provider = RuntimeBackedProvider(runtime)
        result = provider.generate(_request())
        self.assertEqual((result.status, result.text), (STATUS_SUCCESS, "tiny-runtime-output"))
        self.assertEqual(runtime.load_calls, 1)

    def test_backend_accepts_a_runtime_as_before(self):
        runtime = self.tiny_runtime()
        backend = LocalLanguageModelBackend(runtime)
        self.assertIs(backend.runtime, runtime)
        self.assertIsInstance(backend.provider, RuntimeBackedProvider)
        self.assertEqual(backend.generate_response(self.understanding()).response_text,
                         "tiny-runtime-output")

    def test_runtime_and_provider_together_is_an_error(self):
        with self.assertRaises(ValueError):
            LocalLanguageModelBackend(TinyRuntime(), provider=ScriptedProvider())
        with self.assertRaises(TypeError):
            LocalLanguageModelBackend(provider=TinyRuntime())

    def test_provider_without_a_runtime_has_no_runtime_property(self):
        self.assertIsNone(LocalLanguageModelBackend(provider=ScriptedProvider()).runtime)

    def test_load_and_unload_through_the_provider(self):
        provider = RuntimeBackedProvider(self.tiny_runtime())
        self.assertTrue(provider.load().ok)
        self.assertTrue(provider.unload())
        self.assertFalse(LocalModelProvider().unload())   # base default: unsupported


class TestProviderFailures(_Files, unittest.TestCase):
    """7. load failure, 8. inference failure, 9. timeout/resource propagation"""

    def test_load_failure_propagates(self):
        runtime = self.tiny_runtime()
        runtime.load_error = ModelLoadError("corrupt weights")
        provider = RuntimeBackedProvider(runtime)
        self.assertEqual(provider.load().status, LOAD_FAILED)
        response = LocalLanguageModelBackend(provider=provider).generate_response(
            self.understanding())
        self.assertEqual((response.status, response.inference_status, response.error_code),
                         (STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED, ERROR_LOAD_FAILED))
        self.assertIsNone(response.response_text)
        self.assertEqual(provider.availability().state, "load_failed")

    def test_inference_failure_propagates(self):
        runtime = self.tiny_runtime()
        runtime.infer_error = InferenceExecutionError("engine crashed")
        response = LocalLanguageModelBackend(provider=RuntimeBackedProvider(runtime)) \
            .generate_response(self.understanding())
        self.assertEqual((response.status, response.inference_status, response.error_code),
                         (STATUS_MODEL_FAILED, STATUS_INFERENCE_FAILED, ERROR_INFERENCE_FAILED))
        self.assertIn("engine crashed", response.reason)

    def test_every_provider_failure_status_keeps_its_identity(self):
        cases = [
            (INF_NOT_CONFIGURED, STATUS_MODEL_NOT_CONFIGURED),
            (INF_UNAVAILABLE, STATUS_MODEL_UNAVAILABLE),
            (STATUS_MODEL_LOAD_FAILED, STATUS_MODEL_UNAVAILABLE),
            (STATUS_INFERENCE_FAILED, STATUS_MODEL_FAILED),
            (STATUS_TIMEOUT, STATUS_MODEL_FAILED),
            (STATUS_CANCELLED, STATUS_MODEL_FAILED),
            (STATUS_RESOURCE_LIMIT, STATUS_MODEL_FAILED),
            (STATUS_INVALID_REQUEST, STATUS_MODEL_FAILED),
        ]
        for inference_status, response_status in cases:
            with self.subTest(inference_status=inference_status):
                provider = ScriptedProvider()
                provider.result = InferenceResult.failure(inference_status, "the_code", "msg")
                response = LocalLanguageModelBackend(provider=provider).generate_response(
                    self.understanding())
                self.assertEqual(response.status, response_status)
                self.assertEqual(response.inference_status, inference_status)
                self.assertEqual(response.error_code, "the_code")
                self.assertIsNone(response.response_text)

    def test_timeout_and_resource_limits_from_a_real_runtime_pass_through(self):
        provider = RuntimeBackedProvider(self.tiny_runtime(context_length=70))
        response = LocalLanguageModelBackend(provider=provider).generate_response(
            self.understanding("word " * 200))
        self.assertEqual((response.inference_status, response.error_code),
                         (STATUS_RESOURCE_LIMIT, ERROR_CONTEXT_LENGTH_EXCEEDED))

        token = CancellationToken()
        token.cancel()
        result = RuntimeBackedProvider(self.tiny_runtime()).generate(_request(), token)
        self.assertEqual(result.status, STATUS_CANCELLED)

    def test_timeout_status_through_a_provider(self):
        provider = ScriptedProvider()
        provider.result = InferenceResult.failure(STATUS_TIMEOUT, ERROR_TIMED_OUT, "too slow")
        response = LocalLanguageModelBackend(provider=provider).generate_response(
            self.understanding())
        self.assertEqual((response.status, response.error_code),
                         (STATUS_MODEL_FAILED, ERROR_TIMED_OUT))

    def test_no_model_reports_explicitly_never_text(self):
        for backend in (LocalLanguageModelBackend(),
                        LocalLanguageModelBackend(provider=RuntimeBackedProvider(
                            UnavailableLocalModelRuntime(_config("/x/m.gguf"))))):
            response = backend.generate_response(self.understanding())
            self.assertIn(response.status, (STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE))
            self.assertIsNone(response.response_text)

    def test_misbehaving_provider_is_contained(self):
        class Raising(ScriptedProvider):
            def generate(self, request, cancellation_token=None):
                raise RuntimeError("secret detail")

            def availability(self):
                raise RuntimeError("secret detail")

            def model_info(self):
                raise RuntimeError("secret detail")

        backend = LocalLanguageModelBackend(provider=Raising("bad"))
        response = backend.generate_response(self.understanding())
        self.assertEqual(response.status, STATUS_MODEL_FAILED)
        self.assertNotIn("secret", response.reason)
        self.assertFalse(backend.check_availability().can_infer)
        self.assertEqual(backend.model_info().provider_id, "bad")
        with self.assertRaises(LocalModelBackendError):
            backend.understand("hi")

    def test_understand_uses_provider_availability_and_never_loads(self):
        provider = ScriptedProvider()
        with self.assertRaises(NotImplementedError):
            LocalLanguageModelBackend(provider=provider).understand("hello")
        self.assertEqual(provider.load_calls, 0)
        self.assertEqual(provider.requests, [])
        with self.assertRaises(LocalModelBackendError) as ctx:
            LocalLanguageModelBackend(provider=ScriptedProvider(installed=False)).understand("x")
        self.assertEqual(ctx.exception.status, STATUS_MODEL_NOT_CONFIGURED)


# ======================================================================
class TestFallbackIndependenceAndCoreCompatibility(_Files, unittest.TestCase):
    """11. deterministic fallback independent, 12. Core compatibility"""

    def test_fallback_still_defers_and_has_no_provider_metadata(self):
        backend = DeterministicFallbackBackend(UnderstandingEngine())
        response = LanguageIntelligenceCore(backend=backend).generate_response(
            backend.understand("Hello."))
        self.assertEqual(response.status, STATUS_DEFERRED)
        self.assertEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)
        self.assertIsNone(response.metadata)

    def test_provider_failure_is_never_replaced_by_fallback_output(self):
        provider = ScriptedProvider(installed=False)
        provider.result = InferenceResult.failure(INF_NOT_CONFIGURED, ERROR_NO_CONFIGURATION, "x")
        response = LocalLanguageModelBackend(provider=provider).generate_response(
            self.understanding("Hello."))
        self.assertNotEqual(response.status, STATUS_DEFERRED)
        self.assertNotEqual(response.backend_kind, BACKEND_KIND_DETERMINISTIC_FALLBACK)

    def test_provider_layer_never_references_the_deterministic_backend(self):
        base = os.path.dirname(language_intelligence.__file__)
        for name in ("local_model_provider.py", "local_model_backend.py"):
            code = _strip(_read(os.path.join(base, name)))
            self.assertNotIn("deterministic_fallback_backend", code)
            self.assertNotIn("DeterministicFallbackBackend", code)
        code = _strip(_read(os.path.join(base, "deterministic_fallback_backend.py")))
        self.assertNotIn("local_model_provider", code)

    def test_core_is_unchanged_and_backend_agnostic(self):
        source = _read(os.path.join(os.path.dirname(language_intelligence.__file__),
                                    "language_intelligence_core.py"))
        code = _strip(source)
        for name in ("provider", "Provider", "runtime", "Runtime"):
            self.assertNotIn(name, code)
        understanding = self.understanding("Hi.")
        deterministic = LanguageIntelligenceCore(
            backend=DeterministicFallbackBackend(UnderstandingEngine()))
        local = LanguageIntelligenceCore(backend=LocalLanguageModelBackend(
            provider=ScriptedProvider()))
        self.assertEqual(deterministic.generate_response(understanding).status, STATUS_DEFERRED)
        self.assertEqual(local.generate_response(understanding).status, STATUS_GENERATED)
        self.assertEqual(local.backend_kind, BACKEND_KIND_LOCAL_MODEL)

    def test_real_project_core_still_uses_the_deterministic_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Core(memory_db_path=os.path.join(tmp, "test_memory.sqlite3"),
                        skill_definitions_dir=os.path.join(tmp, "skills"))
            self.assertEqual(core.language_intelligence.backend_kind,
                             BACKEND_KIND_DETERMINISTIC_FALLBACK)
            self.assertEqual(core.generate_language_response(
                core.understand_language("Hi")).status, STATUS_DEFERRED)


class TestNoCloudNoFakeModel(unittest.TestCase):
    FORBIDDEN_IMPORTS = {
        "requests", "urllib", "urllib3", "http", "httpx", "socket", "ssl", "aiohttp",
        "openai", "anthropic", "google", "boto3", "ftplib", "smtplib", "websocket", "random",
    }

    def test_provider_module_is_on_device_only(self):
        source = _read(os.path.join(os.path.dirname(language_intelligence.__file__),
                                    "local_model_provider.py"))
        imported = {m.group(1) for m in re.finditer(
            r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", source, re.M)}
        self.assertEqual(imported & self.FORBIDDEN_IMPORTS, set())
        code = _strip(source).lower()
        self.assertNotIn("api_key", code)
        self.assertNotIn("apikey", code)

    def test_only_test_providers_produce_text_and_none_ship(self):
        # the shipped default has no model and can never produce text
        provider = RuntimeBackedProvider(UnavailableLocalModelRuntime(_config("/x/m.gguf")))
        result = provider.generate(_request())
        self.assertIsNone(result.text)
        self.assertNotEqual(result.status, STATUS_SUCCESS)


def _request(text="Hello there."):
    from language_intelligence.inference import InferenceRequest
    return InferenceRequest(user_input=text)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _strip(source):
    source = re.sub(r'"""[\s\S]*?"""', "", source)
    return re.sub(r"#.*", "", source)


if __name__ == "__main__":
    unittest.main()
