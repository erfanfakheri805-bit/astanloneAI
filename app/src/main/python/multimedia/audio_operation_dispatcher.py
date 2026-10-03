"""
Audio Operation Dispatcher (Prompt 768, Section 8 - Multimedia)
===============================================================
A small deterministic dispatcher that routes an `AudioOperationPlan` to the one operation implementation that exists: the metadata-only
executor of Prompt 767. It selects nothing automatically, processes no audio and touches no file. The generic Prompt 764 executor is untouched.

    dispatch_audio_operation(plan) -> AudioOperationDispatchResult(ok, plan, result, failures)

ORDER
1. `plan` must be exactly an `AudioOperationPlan`  -> else ok=False, plan=None, result=None, `AUDIO_OPERATION_DISPATCHER_INVALID_PLAN`.
   The object is never read.
2. Only the exact string "metadata" is supported (no trimming, case-folding or aliases). Any other `plan.operation` gives ok=False, the SAME plan
   object, result=None, `AUDIO_OPERATION_DISPATCHER_UNSUPPORTED_OPERATION`. The metadata executor is NOT called.
3. "metadata": the plan is passed to the public Prompt 767 `execute_audio_operation_metadata(plan)` and the
   `AudioOperationMetadataExecutionResult` it returns is held UNCHANGED in `result` (same object). The plan identity is preserved.

`ok` mirrors the routed result: ok=True only when the executor result is ok. Dispatcher failures are only the two codes below; whatever the executor
reports (e.g. its own `..._OUTPUT_CREATION_FAILED`) stays inside `result` (`result.codes()`), is never copied, renamed or re-coded, and the dispatcher's
own `failures` is then empty.

FAILURE CODES (only these two; prefix AUDIO_OPERATION_DISPATCHER_)
INVALID_PLAN (field "plan") and UNSUPPORTED_OPERATION (field "operation"); each failure is {"code", "field", "message"}.

RESULT
Immutable (`__slots__`, read-only), cannot be built directly or subclassed (`TypeError`), compares and hashes by value (exact type only), returns
itself from copy/deepcopy and refuses pickling. `failures`, `codes()` and `to_dict()` ({"ok", "plan", "result", "failures"}, `result` as the
executor result's own `to_dict()`) are fresh on every call. The function never raises for bad inputs, never mutates the plan and is deterministic.

WHAT THIS MODULE DOES NOT DO
No audio processing, decoding or any other operation than "metadata", no automatic operation selection, no audio bytes, paths, filesystem, network,
database, AI model or external service, no clock or randomness, no module-level mutable state. Its only imports are the Prompt 763 plan type and the
Prompt 767 executor function. Not wired into `process_input()`, Core, the Planner, the Agent Loop, the Prompt 764 executor or Section 7.
"""

from .audio_operation_metadata_executor import execute_audio_operation_metadata
from .audio_operation_plan import AudioOperationPlan

SUPPORTED_OPERATION = "metadata"

_PREFIX = "AUDIO_OPERATION_DISPATCHER_"
FAILURE_INVALID_PLAN = _PREFIX + "INVALID_PLAN"
FAILURE_UNSUPPORTED_OPERATION = _PREFIX + "UNSUPPORTED_OPERATION"
FAILURE_CODES = (FAILURE_INVALID_PLAN, FAILURE_UNSUPPORTED_OPERATION)

_CREATE_TOKEN = object()


def _failure(code, field, message):
    return (code, field, message)


class AudioOperationDispatchResult:
    """Immutable outcome of `dispatch_audio_operation()`. Obtain it only from that function."""

    __slots__ = ("_plan", "_result", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioOperationDispatchResult cannot be subclassed.")

    def __init__(self, _token, plan, result, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use dispatch_audio_operation() to obtain an AudioOperationDispatchResult.")
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_result", result)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("AudioOperationDispatchResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioOperationDispatchResult is immutable.")

    @property
    def ok(self):
        return self._result is not None and not self._failures and self._result.ok

    @property
    def plan(self):
        return self._plan

    @property
    def result(self):
        return self._result

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "plan", "result", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok,
                "plan": self._plan.to_dict() if self._plan is not None else None,
                "result": self._result.to_dict() if self._result is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._plan, self._result, self._failures)

    def __eq__(self, other):
        if type(other) is not AudioOperationDispatchResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioOperationDispatchResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "AudioOperationDispatchResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def dispatch_audio_operation(plan):
    """Route an exact `AudioOperationPlan` to its operation implementation (only "metadata" exists) and return an `AudioOperationDispatchResult`.
    Deterministic, never raises for bad inputs, never mutates the plan, performs no audio processing and no I/O."""
    if type(plan) is not AudioOperationPlan:
        return AudioOperationDispatchResult(_CREATE_TOKEN, None, None, [_failure(
            FAILURE_INVALID_PLAN, "plan", "plan must be exactly an AudioOperationPlan.")])
    if plan.operation != SUPPORTED_OPERATION:
        return AudioOperationDispatchResult(_CREATE_TOKEN, plan, None, [_failure(
            FAILURE_UNSUPPORTED_OPERATION, "operation", "Only the %r operation is supported; got %r." % (SUPPORTED_OPERATION, plan.operation))])
    return AudioOperationDispatchResult(_CREATE_TOKEN, plan, execute_audio_operation_metadata(plan), ())
