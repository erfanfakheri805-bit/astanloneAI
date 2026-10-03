"""
Language Intelligence - Inference Request / Result
======================================================
Prompt 398. The data shapes that cross the `LocalModelRuntime`
boundary (local_model_runtime.py): what a caller asks for
(`InferenceRequest`) and exactly what came back (`InferenceResult`).

Failures are first-class values here, never hidden behind a fake
answer. `InferenceResult.status` is one of the STATUS_* constants:

    STATUS_SUCCESS              real text produced by a loaded model
    STATUS_MODEL_NOT_CONFIGURED no (valid, enabled) model configuration
    STATUS_MODEL_UNAVAILABLE    configured, but no runtime library is
                                available to run it / model not loadable
                                right now
    STATUS_MODEL_LOAD_FAILED    loading the model was attempted and failed
    STATUS_INFERENCE_FAILED     the model was loaded but generation failed
                                (incl. empty output, structured-output
                                requirement not met)
    STATUS_INVALID_REQUEST      the request itself is malformed
    STATUS_RESOURCE_LIMIT       a configured limit would be / was exceeded
                                (context length, output tokens, memory,
                                requested timeout above the configured cap)
    STATUS_TIMEOUT              the wall-clock limit ran out
    STATUS_CANCELLED            the caller cancelled

`text` is None for every status except STATUS_SUCCESS - the same
"never a value unless the status says so" rule ResponseGenerationResult
and ReasoningResult already follow. `error_code` is a short machine-
readable string (see ERROR_* below), `error_message` a human sentence.
"""

import uuid

from .language_context import LanguageContext
from .response_generation_context import ResponseGenerationContext
from .response_generation_request import BackendGenerationRequest

STATUS_SUCCESS = "success"
STATUS_MODEL_NOT_CONFIGURED = "model_not_configured"
STATUS_MODEL_UNAVAILABLE = "model_unavailable"
STATUS_MODEL_LOAD_FAILED = "model_load_failed"
STATUS_INFERENCE_FAILED = "inference_failed"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_RESOURCE_LIMIT = "resource_limit"
STATUS_TIMEOUT = "timeout"
STATUS_CANCELLED = "cancelled"

ALL_INFERENCE_STATUSES = (
    STATUS_SUCCESS, STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE,
    STATUS_MODEL_LOAD_FAILED, STATUS_INFERENCE_FAILED, STATUS_INVALID_REQUEST,
    STATUS_RESOURCE_LIMIT, STATUS_TIMEOUT, STATUS_CANCELLED,
)

# Error codes (stable, machine-readable).
ERROR_NO_CONFIGURATION = "no_configuration"
ERROR_MODEL_DISABLED = "model_disabled"
ERROR_INVALID_CONFIGURATION = "invalid_configuration"
ERROR_RUNTIME_DEPENDENCY_MISSING = "runtime_dependency_missing"
ERROR_MODEL_NOT_LOADED = "model_not_loaded"
ERROR_MODEL_FILE_NOT_FOUND = "model_file_not_found"
ERROR_MODEL_EXCEEDS_MEMORY_LIMIT = "model_file_exceeds_memory_limit"
ERROR_OUT_OF_MEMORY = "out_of_memory"
ERROR_LOAD_FAILED = "load_failed"
ERROR_INVALID_REQUEST = "invalid_request"
ERROR_CONTEXT_LENGTH_EXCEEDED = "context_length_exceeded"
ERROR_MAX_OUTPUT_TOKENS_EXCEEDED = "max_output_tokens_exceeded"
ERROR_TIMEOUT_EXCEEDS_LIMIT = "timeout_exceeds_configured_limit"
ERROR_OUTPUT_EXCEEDS_LIMIT = "output_exceeds_token_limit"
ERROR_TIMED_OUT = "timed_out"
ERROR_COMPLETED_AFTER_DEADLINE = "completed_after_deadline"
ERROR_CANCELLED = "cancelled"
ERROR_INFERENCE_FAILED = "inference_failed"
ERROR_EMPTY_OUTPUT = "empty_output"
ERROR_INVALID_RUNTIME_OUTPUT = "invalid_runtime_output"
ERROR_STRUCTURED_OUTPUT_INVALID = "structured_output_invalid"

ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ALL_ROLES = (ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT)

FINISH_STOP = "stop"
FINISH_LENGTH = "length"

STRUCTURED_FORMAT_JSON = "json"
ALL_STRUCTURED_FORMATS = (STRUCTURED_FORMAT_JSON,)


# Prompt 407 - readiness. A four-way summary of the runtime's ModelAvailability
# (local_model_runtime.py; no new observation is made, nothing is loaded, nothing is inferred):
#   MODEL_READY           can_infer: a generate() call may be attempted (the
#                         model loads lazily on it; `loaded` says whether it
#                         already is)
#   MODEL_NOT_CONFIGURED  no valid, enabled configuration (incl. disabled)
#   MODEL_LOAD_FAILED     a load was attempted and failed (not retried until
#                         load() is called explicitly)
#   MODEL_UNAVAILABLE     configured, but it cannot run now: engine library
#                         missing, model file missing / over the memory budget
READINESS_MODEL_READY = "MODEL_READY"
READINESS_MODEL_NOT_CONFIGURED = "MODEL_NOT_CONFIGURED"
READINESS_MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
READINESS_MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
ALL_READINESS_STATUSES = (
    READINESS_MODEL_READY, READINESS_MODEL_NOT_CONFIGURED,
    READINESS_MODEL_UNAVAILABLE, READINESS_MODEL_LOAD_FAILED,
)


class ModelReadiness:
    """Result of a readiness check: `status` is one of the READINESS_*
    constants, `ready` is True only for MODEL_READY (so the object is
    truthy exactly when an inference request may be attempted), and
    `error_code` / `message` are the existing ModelAvailability's (None /
    "" when ready). Produced by `model_readiness()` from a
    ModelAvailability - it never runs inference."""

    def __init__(self, status, error_code=None, message="", loaded=False,
                 model_id=None, runtime_name=None):
        self.status = status
        self.error_code = error_code
        self.message = message
        self.loaded = loaded
        self.model_id = model_id
        self.runtime_name = runtime_name

    @property
    def ready(self):
        return self.status == READINESS_MODEL_READY

    def __bool__(self):
        return self.ready

    def __repr__(self):
        return f"ModelReadiness(status={self.status!r}, error_code={self.error_code!r})"

    def to_dict(self):
        return {
            "status": self.status, "ready": self.ready, "error_code": self.error_code,
            "message": self.message, "loaded": self.loaded,
            "model_id": self.model_id, "runtime_name": self.runtime_name,
        }


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class ConversationMessage:
    """One prior turn handed to the model as conversation context."""

    def __init__(self, role, content):
        self.role = role
        self.content = content

    def __repr__(self):
        return f"ConversationMessage(role={self.role!r}, chars={len(str(self.content))})"

    def to_dict(self):
        return {"role": self.role, "content": self.content}


class GenerationParameters:
    """Per-request generation settings. Every field is optional: None
    means "use the loaded model configuration's default". Values a
    runtime does not support are simply ignored by that runtime - the
    request never fails just because a knob is unsupported."""

    def __init__(self, max_output_tokens=None, temperature=None, top_p=None,
                 seed=None, stop_sequences=None):
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.seed = seed
        self.stop_sequences = list(stop_sequences) if stop_sequences else []

    def validate(self):
        problems = []
        if self.max_output_tokens is not None and (
                not _is_int(self.max_output_tokens) or self.max_output_tokens < 1):
            problems.append("parameters.max_output_tokens: must be None or an int >= 1")
        if self.temperature is not None and (
                not _is_number(self.temperature) or not 0.0 <= self.temperature <= 2.0):
            problems.append("parameters.temperature: must be None or a number in [0.0, 2.0]")
        if self.top_p is not None and (
                not _is_number(self.top_p) or not 0.0 < self.top_p <= 1.0):
            problems.append("parameters.top_p: must be None or a number in (0.0, 1.0]")
        if self.seed is not None and not _is_int(self.seed):
            problems.append("parameters.seed: must be None or an int")
        if not all(isinstance(s, str) and s for s in self.stop_sequences):
            problems.append("parameters.stop_sequences: must be non-empty strings")
        return problems

    def to_dict(self):
        return {
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "seed": self.seed,
            "stop_sequences": list(self.stop_sequences),
        }


class StructuredOutputRequirement:
    """Optional: the caller needs the model's output to be parseable
    structured data. Only `json` is defined. `required_keys` (top-level
    keys of a JSON object) is the one check applied on top of "is
    valid JSON" - this is deliberately NOT a JSON-Schema validator.

    Whether the runtime can *constrain* generation to the format is a
    runtime capability; either way LocalModelRuntime verifies the
    finished output and reports STATUS_INFERENCE_FAILED /
    ERROR_STRUCTURED_OUTPUT_INVALID if it does not comply."""

    def __init__(self, output_format=STRUCTURED_FORMAT_JSON, required_keys=None):
        self.output_format = output_format
        self.required_keys = list(required_keys) if required_keys else []

    def validate(self):
        problems = []
        if self.output_format not in ALL_STRUCTURED_FORMATS:
            problems.append(
                f"structured_output.output_format: must be one of {list(ALL_STRUCTURED_FORMATS)}"
            )
        if not all(isinstance(k, str) and k for k in self.required_keys):
            problems.append("structured_output.required_keys: must be non-empty strings")
        return problems

    def to_dict(self):
        return {"output_format": self.output_format, "required_keys": list(self.required_keys)}


class InferenceRequest:
    """`system_prompt` - optional system/context instructions.
    `user_input` - the text to respond to (required, non-empty).
    `conversation` - optional prior turns, oldest first
    (list of ConversationMessage or {"role","content"} dicts).
    `parameters` - GenerationParameters (or None for all defaults).
    `structured_output` - optional StructuredOutputRequirement.
    `timeout_seconds` - optional per-request limit; may only be
    LOWER than the model configuration's own timeout.
    `language_context` - optional LanguageContext (Prompt 401): the
    language situation of `user_input` (detected language, scripts,
    requested/conversation/response language). It travels NEXT TO the
    text and never replaces it: `user_input` is always the user's
    original message, and nothing here turns the context into prompt
    text - how (or whether) a model uses it is up to the provider /
    runtime. None = no language information available.
    `generation_context` - optional `ResponseGenerationContext`
    (response_generation_context.py, Prompt 426): the bounded,
    read-only bridge from the existing structured `ResponsePlan` -
    resolved meaning/intention, response action, matched pattern,
    variables, active topic, references, context, language, locale,
    unresolved requirements. Like `language_context`, it travels NEXT
    TO the text and never replaces it, and it never contains response
    text itself; how (or whether) a model uses it is up to the
    provider / runtime. None = no plan was available to build one
    from.
    `generation_request` - optional `BackendGenerationRequest`
    (response_generation_request.py, Prompt 427): `generation_context`
    above PLUS `sentence_structure` (Prompt 422) - the one additional
    field a backend needs that `ResponseGenerationContext` alone does
    not carry (see response_generation_request.py's own module
    docstring). Same rules as `generation_context`: travels next to
    the text, never contains response text, never required. None = no
    plan was available to build one from.
    A request is only a description; constructing one never validates
    or raises - call `validate()` (the runtime always does)."""

    def __init__(self, user_input, system_prompt=None, conversation=None,
                 parameters=None, structured_output=None, timeout_seconds=None,
                 request_id=None, language_context=None, generation_context=None,
                 generation_request=None):
        self.user_input = user_input
        self.system_prompt = system_prompt
        self.conversation = self._coerce_conversation(conversation)
        self.parameters = parameters if parameters is not None else GenerationParameters()
        self.structured_output = structured_output
        self.timeout_seconds = timeout_seconds
        self.request_id = request_id if request_id else uuid.uuid4().hex
        self.language_context = language_context
        self.generation_context = generation_context
        self.generation_request = generation_request

    @staticmethod
    def _coerce_conversation(conversation):
        if conversation is None:
            return []
        if not isinstance(conversation, (list, tuple)):
            return conversation  # left as-is; validate() reports it
        coerced = []
        for item in conversation:
            if isinstance(item, ConversationMessage):
                coerced.append(item)
            elif isinstance(item, dict):
                coerced.append(ConversationMessage(item.get("role"), item.get("content")))
            else:
                coerced.append(item)  # validate() reports it
        return coerced

    def validate(self):
        """Return a list of "field: reason" problems (empty = valid)."""
        problems = []
        if not isinstance(self.user_input, str) or not self.user_input.strip():
            problems.append("user_input: must be a non-empty string")
        if self.system_prompt is not None and not isinstance(self.system_prompt, str):
            problems.append("system_prompt: must be None or a string")

        if not isinstance(self.conversation, list):
            problems.append("conversation: must be a list of messages")
        else:
            for i, msg in enumerate(self.conversation):
                if not isinstance(msg, ConversationMessage):
                    problems.append(f"conversation[{i}]: must be a message with role/content")
                elif msg.role not in ALL_ROLES:
                    problems.append(f"conversation[{i}].role: must be one of {list(ALL_ROLES)}")
                elif not isinstance(msg.content, str):
                    problems.append(f"conversation[{i}].content: must be a string")

        if not isinstance(self.parameters, GenerationParameters):
            problems.append("parameters: must be a GenerationParameters")
        else:
            problems.extend(self.parameters.validate())

        if self.structured_output is not None:
            if not isinstance(self.structured_output, StructuredOutputRequirement):
                problems.append("structured_output: must be a StructuredOutputRequirement")
            else:
                problems.extend(self.structured_output.validate())

        if self.timeout_seconds is not None and (
                not _is_number(self.timeout_seconds) or self.timeout_seconds <= 0):
            problems.append("timeout_seconds: must be None or a number > 0")

        if self.language_context is not None and not isinstance(
                self.language_context, LanguageContext):
            problems.append("language_context: must be None or a LanguageContext")

        if self.generation_context is not None and not isinstance(
                self.generation_context, ResponseGenerationContext):
            problems.append("generation_context: must be None or a ResponseGenerationContext")

        if self.generation_request is not None and not isinstance(
                self.generation_request, BackendGenerationRequest):
            problems.append("generation_request: must be None or a BackendGenerationRequest")
        return problems

    def input_char_count(self):
        """Total characters the model would have to read. Only
        meaningful for a request that passed validate()."""
        total = len(self.user_input) + len(self.system_prompt or "")
        total += sum(len(m.content) for m in self.conversation)
        return total

    def to_dict(self):
        return {
            "request_id": self.request_id,
            "system_prompt": self.system_prompt,
            "user_input": self.user_input,
            "conversation": [m.to_dict() if isinstance(m, ConversationMessage) else m
                             for m in self.conversation]
            if isinstance(self.conversation, list) else self.conversation,
            "parameters": self.parameters.to_dict()
            if isinstance(self.parameters, GenerationParameters) else self.parameters,
            "structured_output": self.structured_output.to_dict()
            if isinstance(self.structured_output, StructuredOutputRequirement) else None,
            "timeout_seconds": self.timeout_seconds,
            "language_context": self.language_context.to_dict()
            if isinstance(self.language_context, LanguageContext) else None,
            "generation_context": self.generation_context.to_dict()
            if isinstance(self.generation_context, ResponseGenerationContext) else None,
            "generation_request": self.generation_request.to_dict()
            if isinstance(self.generation_request, BackendGenerationRequest) else None,
        }


class InferenceResult:
    """Use the `success()` / `failure()` constructors rather than the
    raw initializer."""

    def __init__(self, status, text=None, structured_output=None, error_code=None,
                 error_message="", runtime_name=None, model_id=None, request_id=None,
                 elapsed_seconds=0.0, prompt_tokens=None, output_tokens=None,
                 finish_reason=None, details=None):
        self.status = status
        self.text = text
        self.structured_output = structured_output
        self.error_code = error_code
        self.error_message = error_message
        self.runtime_name = runtime_name
        self.model_id = model_id
        self.request_id = request_id
        self.elapsed_seconds = elapsed_seconds
        self.prompt_tokens = prompt_tokens      # exact if the runtime reported it
        self.output_tokens = output_tokens      # else None - never invented
        self.finish_reason = finish_reason
        self.details = details if details is not None else {}

    @classmethod
    def success(cls, text, **kwargs):
        return cls(STATUS_SUCCESS, text=text, **kwargs)

    @classmethod
    def failure(cls, status, error_code, error_message, **kwargs):
        if status == STATUS_SUCCESS:
            raise ValueError("failure() cannot be used with STATUS_SUCCESS")
        return cls(status, error_code=error_code, error_message=error_message, **kwargs)

    @property
    def ok(self):
        return self.status == STATUS_SUCCESS

    def __repr__(self):
        return (
            f"InferenceResult(status={self.status!r}, error_code={self.error_code!r}, "
            f"runtime_name={self.runtime_name!r})"
        )

    def to_dict(self):
        return {
            "status": self.status,
            "text": self.text,
            "structured_output": self.structured_output,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "runtime_name": self.runtime_name,
            "model_id": self.model_id,
            "request_id": self.request_id,
            "elapsed_seconds": round(self.elapsed_seconds, 4),
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "finish_reason": self.finish_reason,
            "details": self.details,
        }


# ----------------------------------------------------------------------
# Prompt 412 - one standardized result for every inference attempt
# ----------------------------------------------------------------------
# `InferenceResult` IS the standardized local-inference result: its nine
# STATUS_* values (success, model_not_configured, model_unavailable,
# model_load_failed, inference_failed, invalid_request, resource_limit,
# timeout, cancelled), `error_code`, `error_message`, ids, timing, token
# counts and `details` already cover everything a caller (and Prompt 406's
# fallback) needs. Nothing parallel is added. What was not guaranteed was
# that EVERY attempt yields one: a provider that raised, returned another
# type, a status outside the nine, or "success" without text broke that
# silently until the backend mapped it. These two functions close that
# gap at the runtime -> provider -> backend boundary, so from there on a
# value is always a valid InferenceResult (or the very same object).

_SUCCESS_WITHOUT_TEXT = "the local model runtime reported success without usable text"


def _invalid_output_failure(message, source=None, **ids):
    kwargs = dict(ids)
    if isinstance(source, InferenceResult):
        for name in ("runtime_name", "model_id", "request_id", "elapsed_seconds",
                     "prompt_tokens", "output_tokens", "finish_reason"):
            if kwargs.get(name) is None:
                kwargs[name] = getattr(source, name)
    return InferenceResult.failure(
        STATUS_INFERENCE_FAILED, ERROR_INVALID_RUNTIME_OUTPUT, message, **kwargs)


def standardize_inference_result(result, runtime_name=None, model_id=None, request_id=None):
    """Return `result` itself when it is already a valid `InferenceResult`
    (status among ALL_INFERENCE_STATUSES; success only with non-empty
    text; no text on a failure). Otherwise return a structured
    STATUS_INFERENCE_FAILED / ERROR_INVALID_RUNTIME_OUTPUT failure that
    keeps whatever identity the bad value carried (or the optional
    arguments). Pure, never raises, never invents text, never turns a
    failure into a success."""
    ids = dict(runtime_name=runtime_name, model_id=model_id, request_id=request_id)
    if not isinstance(result, InferenceResult):
        return _invalid_output_failure(
            "the local model runtime did not return an InferenceResult", **ids)
    if result.status not in ALL_INFERENCE_STATUSES:
        return _invalid_output_failure(
            "the local model runtime reported an unknown status", result, **ids)
    if result.status == STATUS_SUCCESS:
        if not isinstance(result.text, str) or not result.text.strip():
            return _invalid_output_failure(_SUCCESS_WITHOUT_TEXT, result, **ids)
        return result
    if result.text is not None or result.structured_output is not None:
        # a failure never carries output: same result, output removed
        return InferenceResult(
            result.status, error_code=result.error_code, error_message=result.error_message,
            runtime_name=result.runtime_name, model_id=result.model_id,
            request_id=result.request_id, elapsed_seconds=result.elapsed_seconds,
            prompt_tokens=result.prompt_tokens, output_tokens=result.output_tokens,
            finish_reason=result.finish_reason, details=result.details)
    return result


def inference_failure_from_exception(exc, runtime_name=None, model_id=None, request_id=None):
    """A runtime/provider that raised (its contract is "never raises")
    as a structured STATUS_INFERENCE_FAILED / ERROR_INFERENCE_FAILED
    result. Only the exception TYPE NAME is kept - never its message,
    arguments or traceback."""
    return InferenceResult.failure(
        STATUS_INFERENCE_FAILED, ERROR_INFERENCE_FAILED,
        f"the local model runtime raised {type(exc).__name__} instead of returning a result",
        runtime_name=runtime_name, model_id=model_id, request_id=request_id)
