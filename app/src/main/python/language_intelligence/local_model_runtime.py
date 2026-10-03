"""
Language Intelligence - Local Model Runtime (the boundary)
==============================================================
Prompt 398. `LocalModelRuntime` is the ONE interface between this
project and whatever engine will actually execute an on-device language
model (a llama.cpp binding, an ONNX/TFLite runtime, ...). Nothing above
it - LocalLanguageModelBackend, LanguageIntelligenceCore, Core, Memory,
Context, Knowledge, Reasoning, Planning, Execution, the Agent Loop -
knows or cares which engine is behind it:

    LanguageIntelligenceCore
      -> LocalLanguageModelBackend          (local_model_backend.py)
        -> LocalModelRuntime                 (THIS module)
          -> a concrete runtime's hooks      (none exists yet - see below)
            -> the local model

Separation of concerns (Prompt 398, item 2):

    MODEL CONFIGURATION  local_model_config.LocalModelConfig
    MODEL LOADING        load() / unload() / ensure_loaded()  -> ModelLoadResult
    INFERENCE REQUEST    inference.InferenceRequest
    INFERENCE RESULT     inference.InferenceResult
    ERROR HANDLING       every failure becomes a typed InferenceResult /
                         ModelLoadResult; generate() and load() never
                         raise for a model/runtime/request problem
    RESOURCE LIMITS      context length, output tokens, timeout,
                         cancellation, memory budget, availability -
                         enforced HERE, once, so every future runtime
                         gets identical behavior
    MODEL RUNTIME        the hooks below - the only part a concrete
                         engine implements

Template-method design. `load()` and `generate()` are final in spirit:
they do all validation, limit checking, state tracking, timing, error
translation, and output verification. A concrete runtime subclass
implements ONLY these hooks:

    runtime_name                 (property) short label
    dependency_status()          -> (available: bool, message: str)
    _load_model(config)          load the model; raise ModelLoadError /
                                 ResourceLimitExceeded on failure
    _unload_model()              optional; free the model
    _run_inference(request, params, config, control) -> RuntimeOutput
                                 poll `control.check()` regularly so
                                 timeout/cancellation can interrupt it
    _estimate_prompt_tokens(request)   optional; override with the
                                 engine's real tokenizer count

What exists TODAY: this base class and `UnavailableLocalModelRuntime`
(unavailable_runtime.py), which honestly reports that no engine is
installed. No real engine, model, or model file exists in this project
- see docs/local_model_runtime.md for exactly what is required.

Behavior notes:
  * Loading is LAZY and EXPLICIT-FAILURE: generate() loads the model on
    first use (load time is NOT counted against the inference timeout).
    A failed load is remembered; generate() will not silently retry it -
    call load() again to retry (no automatic retry anywhere).
  * Timeout and cancellation are COOPERATIVE: the runtime cannot kill a
    native call it does not control. A hook that observes
    `control.check()` is interrupted promptly; one that ignores it and
    finishes late is reported as STATUS_TIMEOUT
    (ERROR_COMPLETED_AFTER_DEADLINE) and its late output is discarded.
  * One inference at a time (an internal lock serializes calls).
  * Token counts used for the context check are ESTIMATES unless a
    subclass overrides `_estimate_prompt_tokens`.
  * No network access, no downloading, no cloud call happens here.
"""

import json
import math
import os
import threading
import time

from .local_model_config import LocalModelConfig
from .inference import (
    InferenceRequest, InferenceResult, GenerationParameters,
    ModelReadiness, READINESS_MODEL_READY, READINESS_MODEL_NOT_CONFIGURED,
    READINESS_MODEL_UNAVAILABLE, READINESS_MODEL_LOAD_FAILED, ALL_READINESS_STATUSES,
    STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE, STATUS_MODEL_LOAD_FAILED,
    STATUS_INFERENCE_FAILED, STATUS_INVALID_REQUEST, STATUS_RESOURCE_LIMIT,
    STATUS_TIMEOUT, STATUS_CANCELLED,
    ERROR_NO_CONFIGURATION, ERROR_MODEL_DISABLED, ERROR_INVALID_CONFIGURATION,
    ERROR_RUNTIME_DEPENDENCY_MISSING, ERROR_MODEL_FILE_NOT_FOUND,
    ERROR_MODEL_EXCEEDS_MEMORY_LIMIT, ERROR_OUT_OF_MEMORY, ERROR_LOAD_FAILED,
    ERROR_INVALID_REQUEST, ERROR_CONTEXT_LENGTH_EXCEEDED,
    ERROR_MAX_OUTPUT_TOKENS_EXCEEDED, ERROR_TIMEOUT_EXCEEDS_LIMIT,
    ERROR_OUTPUT_EXCEEDS_LIMIT, ERROR_TIMED_OUT, ERROR_COMPLETED_AFTER_DEADLINE,
    ERROR_CANCELLED, ERROR_INFERENCE_FAILED, ERROR_EMPTY_OUTPUT,
    ERROR_INVALID_RUNTIME_OUTPUT, ERROR_STRUCTURED_OUTPUT_INVALID,
    STRUCTURED_FORMAT_JSON,
)

# Runtime states (see LocalModelRuntime.state).
STATE_NOT_CONFIGURED = "not_configured"
STATE_RUNTIME_UNAVAILABLE = "runtime_unavailable"
STATE_UNLOADED = "unloaded"
STATE_READY = "ready"
STATE_LOAD_FAILED = "load_failed"

# Load result statuses.
LOAD_OK = "loaded"
LOAD_NOT_CONFIGURED = "not_configured"
LOAD_RUNTIME_UNAVAILABLE = "runtime_unavailable"
LOAD_FAILED = "load_failed"
LOAD_RESOURCE_LIMIT = "resource_limit"

# Coarse, deliberately labeled ESTIMATE (see module docstring).
_CHARS_PER_TOKEN_ESTIMATE = 3
_PER_MESSAGE_OVERHEAD_TOKENS = 4
_BYTES_PER_MIB = 1024 * 1024


# ----------------------------------------------------------------------
# Exceptions a concrete runtime's hooks may raise. Public callers of
# load()/generate() never see these - they are translated to results.
# ----------------------------------------------------------------------
class LocalModelError(Exception):
    default_code = ERROR_INFERENCE_FAILED

    def __init__(self, message="", code=None):
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code


class ModelLoadError(LocalModelError):
    default_code = ERROR_LOAD_FAILED


class InferenceExecutionError(LocalModelError):
    default_code = ERROR_INFERENCE_FAILED


class ResourceLimitExceeded(LocalModelError):
    default_code = ERROR_OUT_OF_MEMORY


class InferenceTimeout(LocalModelError):
    default_code = ERROR_TIMED_OUT


class InferenceCancelled(LocalModelError):
    default_code = ERROR_CANCELLED


class CancellationToken:
    """Thread-safe cancel flag. Give one to generate(); call cancel()
    from any thread to ask the running inference to stop."""

    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    def is_cancelled(self):
        return self._event.is_set()


class InferenceControl:
    """Handed to `_run_inference`. Call `check()` regularly (e.g. once
    per generated token): it raises InferenceCancelled / InferenceTimeout
    when the caller cancelled or the deadline passed."""

    def __init__(self, token, deadline, clock):
        self._token = token
        self._deadline = deadline
        self._clock = clock

    def is_cancelled(self):
        return self._token is not None and self._token.is_cancelled()

    def is_timed_out(self):
        return self._clock() >= self._deadline

    def remaining_seconds(self):
        return max(0.0, self._deadline - self._clock())

    def check(self):
        if self.is_cancelled():
            raise InferenceCancelled("inference cancelled by the caller")
        if self.is_timed_out():
            raise InferenceTimeout("inference exceeded its time limit")


class RuntimeOutput:
    """What `_run_inference` returns. Token counts are None unless the
    engine really reported them - never guessed."""

    def __init__(self, text, finish_reason=None, prompt_tokens=None, output_tokens=None):
        self.text = text
        self.finish_reason = finish_reason
        self.prompt_tokens = prompt_tokens
        self.output_tokens = output_tokens


class ModelLoadResult:
    def __init__(self, status, message="", error_code=None, model_id=None,
                 runtime_name=None, elapsed_seconds=0.0):
        self.status = status
        self.message = message
        self.error_code = error_code
        self.model_id = model_id
        self.runtime_name = runtime_name
        self.elapsed_seconds = elapsed_seconds

    @property
    def ok(self):
        return self.status == LOAD_OK

    def __repr__(self):
        return f"ModelLoadResult(status={self.status!r}, error_code={self.error_code!r})"

    def to_dict(self):
        return {
            "status": self.status, "message": self.message,
            "error_code": self.error_code, "model_id": self.model_id,
            "runtime_name": self.runtime_name,
            "elapsed_seconds": round(self.elapsed_seconds, 4),
        }


class ModelAvailability:
    """Structured, read-only answer to "can this runtime serve a request
    right now?" (Prompt 399). Returned by `LocalModelRuntime.availability()`
    and `LocalLanguageModelBackend.check_availability()`; it replaces
    scattered boolean checks with one value whose every field is a real,
    cheap observation - producing one never loads the model, never
    touches the network and never runs inference.

        configured         a valid model configuration is present
                           (a valid-but-disabled one counts as configured)
        enabled            that configuration is enabled
        runtime_available  the engine library this runtime needs is present
        loadable           the model could be handed to the engine now:
                           already loaded, or the local model path exists
                           and fits the declared memory budget, and the last
                           load attempt did not fail. Not a guarantee - the
                           engine may still reject the file when it loads.
        loaded             the model is currently loaded
        can_infer          configured + enabled + runtime_available +
                           loadable: a generate() call may be attempted
                           (it will load lazily if needed)
        state              the runtime STATE_* constant
        error_code/message why `can_infer` is False (None/"" when True)
    """

    def __init__(self, configured, enabled, runtime_available, loadable, loaded,
                 can_infer, state, error_code=None, message="", model_id=None,
                 runtime_name=None):
        self.configured = configured
        self.enabled = enabled
        self.runtime_available = runtime_available
        self.loadable = loadable
        self.loaded = loaded
        self.can_infer = can_infer
        self.state = state
        self.error_code = error_code
        self.message = message
        self.model_id = model_id
        self.runtime_name = runtime_name

    @property
    def ok(self):
        return self.can_infer

    def __bool__(self):
        return self.can_infer

    def __repr__(self):
        return (f"ModelAvailability(state={self.state!r}, can_infer={self.can_infer!r}, "
                f"error_code={self.error_code!r})")

    def to_dict(self):
        return {
            "configured": self.configured, "enabled": self.enabled,
            "runtime_available": self.runtime_available, "loadable": self.loadable,
            "loaded": self.loaded, "can_infer": self.can_infer, "state": self.state,
            "error_code": self.error_code, "message": self.message,
            "model_id": self.model_id, "runtime_name": self.runtime_name,
        }


# Prompt 407 - readiness: ModelReadiness / READINESS_* live in inference.py
# (backend-agnostic data shapes); this summarises a ModelAvailability as one.
def model_readiness(availability):
    """Summarise a `ModelAvailability` as a `ModelReadiness`. Pure."""
    if availability.can_infer:
        status = READINESS_MODEL_READY
    elif availability.state == STATE_NOT_CONFIGURED:
        status = READINESS_MODEL_NOT_CONFIGURED
    elif availability.state == STATE_LOAD_FAILED:
        status = READINESS_MODEL_LOAD_FAILED
    else:
        status = READINESS_MODEL_UNAVAILABLE
    return ModelReadiness(
        status, availability.error_code, availability.message, bool(availability.loaded),
        availability.model_id, availability.runtime_name)


class LocalModelRuntime:
    def __init__(self, config=None, clock=None):
        """`config` - optional LocalModelConfig (may be given later via
        configure()). `clock` - monotonic-seconds callable; injectable
        so timeout behavior is testable without sleeping."""
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._config = None
        self._not_configured = (ERROR_NO_CONFIGURATION, "no model configuration was provided")
        self._loaded = False
        self._load_failure = None  # (status, error_code, message) of last failed load
        if config is not None:
            self.configure(config)

    # ------------------------------------------------------------------
    # Hooks a concrete runtime implements
    # ------------------------------------------------------------------
    @property
    def runtime_name(self):
        raise NotImplementedError

    def dependency_status(self):
        """Return (available, message). `available` is False when the
        engine library this runtime needs is not present."""
        return True, ""

    def _load_model(self, config):
        raise NotImplementedError

    def _unload_model(self):
        return None

    def _run_inference(self, request, params, config, control):
        raise NotImplementedError

    def _estimate_prompt_tokens(self, request):
        messages = len(request.conversation) + 1 + (1 if request.system_prompt else 0)
        return (math.ceil(request.input_char_count() / _CHARS_PER_TOKEN_ESTIMATE)
                + messages * _PER_MESSAGE_OVERHEAD_TOKENS)

    # ------------------------------------------------------------------
    # Configuration and state
    # ------------------------------------------------------------------
    @property
    def config(self):
        return self._config

    def configure(self, config):
        """Replace the configuration (unloading any loaded model).
        Never raises: an invalid/disabled config leaves the runtime in
        STATE_NOT_CONFIGURED with the reason recorded."""
        with self._lock:
            self._unload_if_loaded()
            self._config = None
            self._load_failure = None
            if config is None:
                self._not_configured = (ERROR_NO_CONFIGURATION,
                                        "no model configuration was provided")
                return
            if not isinstance(config, LocalModelConfig):
                self._not_configured = (ERROR_INVALID_CONFIGURATION,
                                        "configuration is not a LocalModelConfig")
                return
            validation = config.validate()
            if not validation.valid:
                self._not_configured = (ERROR_INVALID_CONFIGURATION,
                                        "invalid model configuration: "
                                        + "; ".join(validation.problems))
                return
            if not config.enabled:
                self._not_configured = (ERROR_MODEL_DISABLED,
                                        "the configured model is disabled")
                return
            self._config = config
            self._not_configured = None

    @property
    def state(self):
        return self.readiness()[0]

    def readiness(self):
        """Read-only, side-effect-free: return (state, error_code,
        message) describing whether generate() could work right now.
        `error_code`/`message` are None/"" for STATE_UNLOADED and
        STATE_READY. Never loads anything."""
        with self._lock:
            if self._config is None:
                code, message = self._not_configured
                return STATE_NOT_CONFIGURED, code, message
            available, dep_message = self.dependency_status()
            if not available:
                return STATE_RUNTIME_UNAVAILABLE, ERROR_RUNTIME_DEPENDENCY_MISSING, dep_message
            if self._loaded:
                return STATE_READY, None, ""
            if self._load_failure is not None:
                _status, code, message = self._load_failure
                return STATE_LOAD_FAILED, code, message
            return STATE_UNLOADED, None, ""

    def availability(self):
        """Structured, side-effect-free availability (see
        `ModelAvailability`). Never loads the model, never raises. The
        `loadable` check is the same cheap local-file preflight load()
        performs (path exists, file fits `max_memory_mb`) - it does not
        read the model."""
        with self._lock:
            state, code, message = self.readiness()
            name = self.runtime_name
            if self._config is None:
                disabled = self._not_configured[0] == ERROR_MODEL_DISABLED
                return ModelAvailability(
                    configured=disabled, enabled=False, runtime_available=False,
                    loadable=False, loaded=False, can_infer=False, state=state,
                    error_code=code, message=message, model_id=None, runtime_name=name)
            model_id = self._config.model_id
            if state == STATE_RUNTIME_UNAVAILABLE:
                return ModelAvailability(True, True, False, False, self._loaded, False,
                                         state, code, message, model_id, name)
            if state == STATE_READY:
                return ModelAvailability(True, True, True, True, True, True,
                                         state, None, "", model_id, name)
            if state == STATE_LOAD_FAILED:
                return ModelAvailability(True, True, True, False, False, False,
                                         state, code, message, model_id, name)
            # STATE_UNLOADED: is the model location usable right now?
            try:
                self._preflight_model_location(self._config)
            except LocalModelError as exc:
                return ModelAvailability(True, True, True, False, False, False,
                                         state, exc.code, exc.message, model_id, name)
            except OSError as exc:
                return ModelAvailability(True, True, True, False, False, False, state,
                                         ERROR_MODEL_FILE_NOT_FOUND,
                                         f"model location could not be checked: "
                                         f"{type(exc).__name__}", model_id, name)
            return ModelAvailability(True, True, True, True, False, True,
                                     state, None, "", model_id, name)

    def describe(self):
        """Plain-dict diagnostic snapshot (read-only, no side effects)."""
        with self._lock:
            available, dep_message = self.dependency_status()
            return {
                "runtime_name": self.runtime_name,
                "state": self.state,
                "model_id": self._config.model_id if self._config else None,
                "runtime_dependency_available": available,
                "runtime_dependency_message": dep_message,
                "not_configured_reason": self._not_configured[1] if self._not_configured else None,
                "last_load_failure": self._load_failure[2] if self._load_failure else None,
            }

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self):
        """Load the configured model now (explicit; retries a previously
        failed load). Returns a ModelLoadResult; never raises."""
        with self._lock:
            return self._load_locked(retry_failed=True)

    def ensure_loaded(self):
        """Like load() but a no-op when already loaded, and it does NOT
        retry a previously failed load."""
        with self._lock:
            return self._load_locked(retry_failed=False)

    def unload(self):
        with self._lock:
            self._unload_if_loaded()
            self._load_failure = None

    def _load_locked(self, retry_failed):
        started = self._clock()
        name = self.runtime_name

        def result(status, message="", code=None):
            model_id = self._config.model_id if self._config else None
            return ModelLoadResult(status, message, code, model_id, name,
                                   self._clock() - started)

        if self._config is None:
            code, message = self._not_configured
            return result(LOAD_NOT_CONFIGURED, message, code)
        available, dep_message = self.dependency_status()
        if not available:
            return result(LOAD_RUNTIME_UNAVAILABLE, dep_message, ERROR_RUNTIME_DEPENDENCY_MISSING)
        if self._loaded:
            return result(LOAD_OK, "model already loaded")
        if self._load_failure is not None and not retry_failed:
            status, code, message = self._load_failure
            return result(status, message, code)

        self._load_failure = None
        try:
            self._preflight_model_location(self._config)
            self._load_model(self._config)
        except ResourceLimitExceeded as exc:
            return self._record_load_failure(result, LOAD_RESOURCE_LIMIT, exc.code, exc.message)
        except ModelLoadError as exc:
            return self._record_load_failure(result, LOAD_FAILED, exc.code, exc.message)
        except MemoryError:
            return self._record_load_failure(result, LOAD_RESOURCE_LIMIT, ERROR_OUT_OF_MEMORY,
                                             "out of memory while loading the model")
        except Exception as exc:  # noqa: BLE001 - translate, never leak
            return self._record_load_failure(
                result, LOAD_FAILED, ERROR_LOAD_FAILED,
                f"unexpected error while loading the model: {type(exc).__name__}: {exc}")
        self._loaded = True
        return result(LOAD_OK, "model loaded")

    def _record_load_failure(self, make_result, status, code, message):
        self._loaded = False
        self._load_failure = (status, code, message)
        return make_result(status, message, code)

    def _preflight_model_location(self, config):
        """Runtime-agnostic, cheap, real checks before handing the path
        to an engine: it must exist locally, and (for a plain file) its
        size must fit the declared memory budget - a file cannot occupy
        less memory than its own size, so this never rejects a model
        that would have fit."""
        path = config.model_path
        if not os.path.exists(path):
            raise ModelLoadError(f"model path does not exist: {path}", ERROR_MODEL_FILE_NOT_FOUND)
        if config.max_memory_mb is not None and os.path.isfile(path):
            size_mb = os.path.getsize(path) / _BYTES_PER_MIB
            if size_mb > config.max_memory_mb:
                raise ResourceLimitExceeded(
                    f"model file is {size_mb:.1f} MiB, above the configured "
                    f"max_memory_mb={config.max_memory_mb}",
                    ERROR_MODEL_EXCEEDS_MEMORY_LIMIT)

    def _unload_if_loaded(self):
        if self._loaded:
            try:
                self._unload_model()
            except Exception:  # noqa: BLE001 - unloading is best-effort
                pass
        self._loaded = False

    # ------------------------------------------------------------------
    # Prompt 410 - request limits (one implementation, used twice)
    # ------------------------------------------------------------------
    def _limit_violation(self, request, config):
        """The configured-limit checks `generate()` has always made before
        loading, as one pure function: None when `request` is within
        `config`'s output-token, timeout and context limits, else
        `(STATUS_RESOURCE_LIMIT, error_code, message, details)`. Never
        loads, never infers. The request must already be valid."""
        params = request.parameters
        max_output = params.max_output_tokens or config.max_output_tokens
        if max_output > config.max_output_tokens:
            return (STATUS_RESOURCE_LIMIT, ERROR_MAX_OUTPUT_TOKENS_EXCEEDED,
                    f"requested max_output_tokens={max_output} exceeds the configured "
                    f"limit {config.max_output_tokens}",
                    dict(requested=max_output, limit=config.max_output_tokens))
        timeout = request.timeout_seconds or config.timeout_seconds
        if timeout > config.timeout_seconds:
            return (STATUS_RESOURCE_LIMIT, ERROR_TIMEOUT_EXCEEDS_LIMIT,
                    f"requested timeout {timeout}s exceeds the configured limit "
                    f"{config.timeout_seconds}s",
                    dict(requested=timeout, limit=config.timeout_seconds))
        prompt_estimate = self._estimate_prompt_tokens(request)
        if prompt_estimate + max_output > config.context_length:
            return (STATUS_RESOURCE_LIMIT, ERROR_CONTEXT_LENGTH_EXCEEDED,
                    f"prompt (~{prompt_estimate} tokens, estimated) plus "
                    f"max_output_tokens={max_output} exceeds context_length="
                    f"{config.context_length}",
                    dict(prompt_tokens_estimate=prompt_estimate,
                         max_output_tokens=max_output,
                         context_length=config.context_length))
        return None

    def check_request_limits(self, request):
        """Prompt 410: None when `request` is within the configured limits
        (or when the question is not this check's to answer - a malformed
        request or a model with no configuration is reported by
        `generate()` / the readiness check, unchanged); otherwise the
        SAME `STATUS_RESOURCE_LIMIT` `InferenceResult` `generate()` would
        return. Read-only and deterministic: never loads the model, never
        runs inference, never raises."""
        try:
            if not isinstance(request, InferenceRequest) or request.validate():
                return None
            with self._lock:
                config = self._config
                if config is None:
                    return None
                violation = self._limit_violation(request, config)
                if violation is None:
                    return None
                status, code, message, details = violation
                return InferenceResult.failure(
                    status, code, message, runtime_name=self.runtime_name,
                    model_id=config.model_id, request_id=request.request_id,
                    details=details)
        except Exception:  # noqa: BLE001 - an unanswerable check never blocks
            return None

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def generate(self, request, cancellation_token=None):
        """Run one inference. ALWAYS returns an InferenceResult; every
        problem is a typed status, never an exception and never a
        substitute answer."""
        request_id = getattr(request, "request_id", None)
        started = self._clock()

        def fail(status, code, message, **details):
            model_id = self._config.model_id if self._config else None
            return InferenceResult.failure(
                status, code, message, runtime_name=self.runtime_name, model_id=model_id,
                request_id=request_id, elapsed_seconds=self._clock() - started,
                details=details)

        # 1. the request itself
        if not isinstance(request, InferenceRequest):
            return fail(STATUS_INVALID_REQUEST, ERROR_INVALID_REQUEST,
                        "request must be an InferenceRequest")
        problems = request.validate()
        if problems:
            return fail(STATUS_INVALID_REQUEST, ERROR_INVALID_REQUEST,
                        "invalid request: " + "; ".join(problems), problems=problems)

        with self._lock:
            # 2. configuration and runtime availability
            if self._config is None:
                code, message = self._not_configured
                return fail(STATUS_MODEL_NOT_CONFIGURED, code, message)
            config = self._config
            available, dep_message = self.dependency_status()
            if not available:
                return fail(STATUS_MODEL_UNAVAILABLE, ERROR_RUNTIME_DEPENDENCY_MISSING,
                            dep_message)

            # 3. limits (cheap - checked BEFORE any expensive load)
            params = request.parameters
            max_output = params.max_output_tokens or config.max_output_tokens
            timeout = request.timeout_seconds or config.timeout_seconds
            violation = self._limit_violation(request, config)
            if violation is not None:
                return fail(*violation[:3], **violation[3])

            if cancellation_token is not None and cancellation_token.is_cancelled():
                return fail(STATUS_CANCELLED, ERROR_CANCELLED,
                            "cancelled before the model was started")

            # 4. load (lazy; failed loads are not silently retried)
            loaded = self._load_locked(retry_failed=False)
            if not loaded.ok:
                if loaded.status == LOAD_RESOURCE_LIMIT:
                    return fail(STATUS_RESOURCE_LIMIT, loaded.error_code, loaded.message)
                if loaded.status == LOAD_RUNTIME_UNAVAILABLE:
                    return fail(STATUS_MODEL_UNAVAILABLE, loaded.error_code, loaded.message)
                return fail(STATUS_MODEL_LOAD_FAILED, loaded.error_code, loaded.message)

            # 5. run - the inference clock starts AFTER loading
            run_started = self._clock()
            deadline = run_started + timeout
            control = InferenceControl(cancellation_token, deadline, self._clock)
            resolved = GenerationParameters(
                max_output_tokens=max_output,
                temperature=params.temperature if params.temperature is not None
                else config.temperature,
                top_p=params.top_p if params.top_p is not None else config.top_p,
                seed=params.seed, stop_sequences=params.stop_sequences)
            try:
                output = self._run_inference(request, resolved, config, control)
            except InferenceTimeout as exc:
                return fail(STATUS_TIMEOUT, exc.code, exc.message or "inference timed out")
            except InferenceCancelled as exc:
                return fail(STATUS_CANCELLED, exc.code, exc.message or "inference cancelled")
            except ResourceLimitExceeded as exc:
                return fail(STATUS_RESOURCE_LIMIT, exc.code, exc.message)
            except MemoryError:
                return fail(STATUS_RESOURCE_LIMIT, ERROR_OUT_OF_MEMORY,
                            "out of memory during inference")
            except LocalModelError as exc:
                return fail(STATUS_INFERENCE_FAILED, exc.code, exc.message)
            except Exception as exc:  # noqa: BLE001 - translate, never leak
                return fail(STATUS_INFERENCE_FAILED, ERROR_INFERENCE_FAILED,
                            f"unexpected inference error: {type(exc).__name__}: {exc}")

            # 6. verify what came back
            if self._clock() > deadline:
                return fail(STATUS_TIMEOUT, ERROR_COMPLETED_AFTER_DEADLINE,
                            f"inference finished after its {timeout}s limit; output discarded")
            if cancellation_token is not None and cancellation_token.is_cancelled():
                return fail(STATUS_CANCELLED, ERROR_CANCELLED,
                            "cancelled during inference; output discarded")
            return self._verify_output(output, request, max_output, fail, started, config)

    def _verify_output(self, output, request, max_output, fail, started, config):
        if not isinstance(output, RuntimeOutput) or not isinstance(output.text, str):
            return fail(STATUS_INFERENCE_FAILED, ERROR_INVALID_RUNTIME_OUTPUT,
                        "the runtime did not return a RuntimeOutput with text")
        if not output.text.strip():
            return fail(STATUS_INFERENCE_FAILED, ERROR_EMPTY_OUTPUT,
                        "the model produced empty output")
        if output.output_tokens is not None and output.output_tokens > max_output:
            return fail(STATUS_RESOURCE_LIMIT, ERROR_OUTPUT_EXCEEDS_LIMIT,
                        f"the runtime reported {output.output_tokens} output tokens, above "
                        f"the limit {max_output}")

        structured = None
        requirement = request.structured_output
        if requirement is not None and requirement.output_format == STRUCTURED_FORMAT_JSON:
            problem, structured = self._check_json(output.text, requirement)
            if problem:
                return fail(STATUS_INFERENCE_FAILED, ERROR_STRUCTURED_OUTPUT_INVALID, problem,
                            output_preview=output.text[:200])

        return InferenceResult.success(
            output.text, structured_output=structured, runtime_name=self.runtime_name,
            model_id=config.model_id, request_id=request.request_id,
            elapsed_seconds=self._clock() - started, prompt_tokens=output.prompt_tokens,
            output_tokens=output.output_tokens, finish_reason=output.finish_reason)

    @staticmethod
    def _check_json(text, requirement):
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            return f"output is not valid JSON: {exc}", None
        if requirement.required_keys:
            if not isinstance(parsed, dict):
                return "output JSON is not an object, but required_keys were specified", None
            missing = [k for k in requirement.required_keys if k not in parsed]
            if missing:
                return f"output JSON is missing required keys: {missing}", None
        return None, parsed
