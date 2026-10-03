"""
Audio Operation Plan (Prompt 763, Section 8 - Multimedia)
=========================================================
A small deterministic planner that turns a VALIDATED audio operation request into an immutable EXECUTION DESCRIPTION. It only describes; it
executes nothing, decodes nothing and touches no file. It mirrors the architecture of `ImageOperationPlan` (Prompt 750) as a separate,
unrelated type.

    create_audio_operation_plan(validation_result) -> AudioOperationPlanResult(ok, plan, failures)
    AudioOperationPlan.to_dict() -> {"audio_id", "operation", "target_format", "duration_ms", "sample_rate", "quality"}

INPUT AND ORDER
1. `validation_result` must be exactly an `AudioOperationValidationResult` (Prompt 762). Anything else (None, a dict, a look-alike) gives
   `AUDIO_OPERATION_PLAN_INVALID_VALIDATION_RESULT`; nothing is read from it.
2. It must have `ok=True`. A failed validation gives `AUDIO_OPERATION_PLAN_VALIDATION_FAILED`; no plan is created.
3. On success the six request values are copied exactly from `validation_result.request`: the very same `str` and `int` objects (identity
   preserved), in the fixed order audio_id, operation, target_format, duration_ms, sample_rate, quality. Nothing is normalized, trimmed,
   case-folded, coerced, reordered or reinterpreted.

THE PLAN HOLDS ONLY THE SIX VALUES
It does not keep the `AudioAsset`, the registry, the request or the validation result, so it carries no link back to any of them. `operation`
and `target_format` stay free text; no operation is interpreted or checked here.

IMMUTABLE AND DETERMINISTIC
`AudioOperationPlan` and `AudioOperationPlanResult` use `__slots__`, refuse assignment/deletion, direct construction and subclassing
(`TypeError`), compare and hash by value (exact type only), return themselves from copy/deepcopy and refuse pickling. `to_dict()` returns FRESH
plain data on every call. The factory never raises for bad inputs and only reads what it is given.

WHAT THIS MODULE DOES NOT DO
No audio processing, decoding or encoding, file paths, filesystem, network, database, AI model or external service, no clock or randomness, no
module-level mutable state. Its only import is the Prompt 762 result type. Not wired into `process_input()`, Core, the Planner, the Agent Loop
or Section 7.
"""

from .audio_operation_validator import AudioOperationValidationResult

FIELDS = ("audio_id", "operation", "target_format", "duration_ms", "sample_rate", "quality")

FAILURE_INVALID_VALIDATION_RESULT = "AUDIO_OPERATION_PLAN_INVALID_VALIDATION_RESULT"
FAILURE_VALIDATION_FAILED = "AUDIO_OPERATION_PLAN_VALIDATION_FAILED"
FAILURE_CODES = (FAILURE_INVALID_VALIDATION_RESULT, FAILURE_VALIDATION_FAILED)

_CREATE_TOKEN = object()


def _failure(code, message):
    return (code, "validation_result", message)


class AudioOperationPlan:
    """Immutable execution description of one audio operation. Obtain it only from `create_audio_operation_plan()`."""

    __slots__ = ("_audio_id", "_operation", "_target_format", "_duration_ms", "_sample_rate", "_quality")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioOperationPlan cannot be subclassed.")

    def __init__(self, _token, audio_id, operation, target_format, duration_ms, sample_rate, quality):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_audio_operation_plan() to build an AudioOperationPlan.")
        object.__setattr__(self, "_audio_id", audio_id)
        object.__setattr__(self, "_operation", operation)
        object.__setattr__(self, "_target_format", target_format)
        object.__setattr__(self, "_duration_ms", duration_ms)
        object.__setattr__(self, "_sample_rate", sample_rate)
        object.__setattr__(self, "_quality", quality)

    def __setattr__(self, key, value):
        raise AttributeError("AudioOperationPlan is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioOperationPlan is immutable.")

    @property
    def audio_id(self):
        return self._audio_id

    @property
    def operation(self):
        return self._operation

    @property
    def target_format(self):
        return self._target_format

    @property
    def duration_ms(self):
        return self._duration_ms

    @property
    def sample_rate(self):
        return self._sample_rate

    @property
    def quality(self):
        return self._quality

    def to_dict(self):
        """A fresh plain dict (fixed field order). Mutating it never affects this plan."""
        return {"audio_id": self._audio_id, "operation": self._operation, "target_format": self._target_format,
                "duration_ms": self._duration_ms, "sample_rate": self._sample_rate, "quality": self._quality}

    def _key(self):
        return (self._audio_id, self._operation, self._target_format, self._duration_ms, self._sample_rate, self._quality)

    def __eq__(self, other):
        if type(other) is not AudioOperationPlan:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioOperationPlan is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return ("AudioOperationPlan(audio_id=%r, operation=%r, target_format=%r, duration_ms=%r, sample_rate=%r, quality=%r)"
                % self._key())


class AudioOperationPlanResult:
    """Immutable outcome of `create_audio_operation_plan()`: `plan` is set only when `ok`."""

    __slots__ = ("_plan", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioOperationPlanResult cannot be subclassed.")

    def __init__(self, _token, plan, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_audio_operation_plan() to obtain an AudioOperationPlanResult.")
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("AudioOperationPlanResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioOperationPlanResult is immutable.")

    @property
    def ok(self):
        return self._plan is not None and not self._failures

    @property
    def plan(self):
        return self._plan

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "plan", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok, "plan": self._plan.to_dict() if self._plan is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._plan, self._failures)

    def __eq__(self, other):
        if type(other) is not AudioOperationPlanResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioOperationPlanResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "AudioOperationPlanResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def create_audio_operation_plan(validation_result):
    """Build an immutable `AudioOperationPlan` from an exact, successful `AudioOperationValidationResult`.
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns an `AudioOperationPlanResult`."""
    if type(validation_result) is not AudioOperationValidationResult:
        return AudioOperationPlanResult(_CREATE_TOKEN, None, [_failure(
            FAILURE_INVALID_VALIDATION_RESULT, "validation_result must be exactly an AudioOperationValidationResult.")])
    if not validation_result.ok:
        return AudioOperationPlanResult(_CREATE_TOKEN, None, [_failure(
            FAILURE_VALIDATION_FAILED, "The audio operation request did not pass validation (codes: %s)." % ", ".join(validation_result.codes()))])
    request = validation_result.request
    plan = AudioOperationPlan(_CREATE_TOKEN, request.audio_id, request.operation, request.target_format,
                              request.duration_ms, request.sample_rate, request.quality)
    return AudioOperationPlanResult(_CREATE_TOKEN, plan, ())
