"""
Voice Verification Batch (Prompt 805, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
============================================================================================================
A thin, deterministic batch entry point over the Prompt 804 pipeline. It validates a whole collection first and then delegates, one plan at a time;
it holds no pipeline, dispatcher, executor or verification logic of its own.

    run_voice_verification_batch(plans) -> VoiceVerificationBatchResult(ok, outputs, failures)

ORDER OF WORK
1. `plans` must be exactly a `tuple` (lists, subclasses, generators, ... are rejected): `VOICE_VERIFICATION_BATCH_INVALID_COLLECTION`. Nothing is iterated.
2. Every item must be exactly a `VoiceVerificationPlan` (`type(item) is VoiceVerificationPlan`; spoofed `__class__`, subclasses, look-alikes, None... are not).
   Each bad item gives `VOICE_VERIFICATION_BATCH_INVALID_ITEM` with field `plans[<index>]`; all bad items are reported together, in order.
   The whole collection is validated BEFORE the pipeline is called (atomic): if anything is invalid the pipeline is called ZERO times and `outputs` is `()`.
3. A valid collection calls the public `run_voice_verification_pipeline(plan)` EXACTLY ONCE per plan, in order. Each returned object is kept as-is (same identity,
   not inspected, copied or altered) in the same position in `outputs`. An empty tuple is a valid collection: zero calls, `ok` True, `outputs` `()`.
4. If the pipeline itself raises, the batch stops at that plan and returns `ok` False, `outputs` `()` and one `VOICE_VERIFICATION_BATCH_PIPELINE_ERROR` failure
   with field `plans[<index>]`; the exception is not retained.

RESULT CARRIER
`VoiceVerificationBatchResult` uses `__slots__`, refuses assignment/deletion, direct construction and subclassing (`TypeError`), compares and hashes by
value (exact type only), returns itself from copy/deepcopy and refuses pickling. `ok` is True only when there are no failures. `outputs` is a tuple;
`failures` is a tuple of FRESH `{"code", "field", "message"}` dicts on every read. It never keeps the input tuple or the plans.

FAILURE CODES (stable): `VOICE_VERIFICATION_BATCH_INVALID_COLLECTION`, `VOICE_VERIFICATION_BATCH_INVALID_ITEM`, `VOICE_VERIFICATION_BATCH_PIPELINE_ERROR`.

WHAT THIS MODULE DOES NOT DO
No audio capture, recording, voice recognition, speaker verification or biometric processing, no I/O, networking, filesystem, persistence, database, subprocess, AI model
or external/cloud service. No clock or randomness, no module-level mutable state. Existing voice modules are unchanged. Not wired into `process_input()`,
Core, the Planner, the Agent Loop, Android or runtime voice processing.
"""

from .voice_verification_pipeline import run_voice_verification_pipeline
from .voice_verification_plan import VoiceVerificationPlan

FAILURE_INVALID_COLLECTION = "VOICE_VERIFICATION_BATCH_INVALID_COLLECTION"
FAILURE_INVALID_ITEM = "VOICE_VERIFICATION_BATCH_INVALID_ITEM"
FAILURE_PIPELINE_ERROR = "VOICE_VERIFICATION_BATCH_PIPELINE_ERROR"
FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_ITEM, FAILURE_PIPELINE_ERROR)

_CREATE_TOKEN = object()


def _failure(code, field, message):
    return (code, field, message)


class VoiceVerificationBatchResult:
    """Immutable outcome of `run_voice_verification_batch()`. Obtain it only from that function."""

    __slots__ = ("_outputs", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceVerificationBatchResult cannot be subclassed.")

    def __init__(self, _token, outputs, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use run_voice_verification_batch() to obtain a VoiceVerificationBatchResult.")
        object.__setattr__(self, "_outputs", tuple(outputs))
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("VoiceVerificationBatchResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceVerificationBatchResult is immutable.")

    @property
    def ok(self):
        return not self._failures

    @property
    def outputs(self):
        """Tuple of the exact objects returned by the pipeline, in plan order."""
        return self._outputs

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def _key(self):
        return (self._outputs, self._failures)

    def __eq__(self, other):
        if type(other) is not VoiceVerificationBatchResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceVerificationBatchResult is not pickled.")

    def __repr__(self):
        return "VoiceVerificationBatchResult(ok=%r, outputs=%d, codes=%r)" % (self.ok, len(self._outputs), self.codes())


def _rejected(failures):
    return VoiceVerificationBatchResult(_CREATE_TOKEN, (), failures)


def run_voice_verification_batch(plans):
    """Validate `plans` (an exact tuple of exact `VoiceVerificationPlan`) completely, then call `run_voice_verification_pipeline(plan)` once per plan, in order.
    Invalid input means zero pipeline calls. Deterministic, performs no I/O, never raises for bad inputs."""
    if type(plans) is not tuple:
        return _rejected([_failure(FAILURE_INVALID_COLLECTION, "plans", "plans must be exactly a tuple.")])
    failures = [_failure(FAILURE_INVALID_ITEM, "plans[%d]" % i, "Each item must be exactly a VoiceVerificationPlan.")
                for i, item in enumerate(plans) if type(item) is not VoiceVerificationPlan]
    if failures:
        return _rejected(failures)
    outputs = []
    for i, plan in enumerate(plans):
        try:
            outputs.append(run_voice_verification_pipeline(plan))
        except Exception:
            return _rejected([_failure(FAILURE_PIPELINE_ERROR, "plans[%d]" % i, "The pipeline raised an error for this plan.")])
    return VoiceVerificationBatchResult(_CREATE_TOKEN, outputs, ())
