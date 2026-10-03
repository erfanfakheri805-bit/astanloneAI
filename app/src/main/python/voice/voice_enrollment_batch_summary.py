"""
Voice Enrollment Batch Summary (Prompt 797, Section 10 - Jarvis Final: Voice, Integration & Controlled Improvement)
===================================================================================================================
A small immutable summary of a completed voice-enrollment batch (Prompt 796). It only counts what the batch result preserved: how many outputs and
failures it holds and how often each exact output status and each exact output code occurs. It never runs, re-runs or re-interprets anything.

    create_voice_enrollment_batch_summary(batch_result)
        -> VoiceEnrollmentBatchSummary(output_count, failure_count, total_count, status_counts, code_counts, success)

INPUT CONTRACT (exact type only; nothing is coerced)
`batch_result` must be exactly a `VoiceEnrollmentBatchResult` (Prompt 796).

CODES (only these two; prefix VOICE_ENROLLMENT_BATCH_SUMMARY_)
1. `INVALID_RESULT`   `batch_result` is not exactly a `VoiceEnrollmentBatchResult` (None, a dict, a look-alike, a spoofed `__class__`, an output, a plan...).
                      Nothing is read from it.
2. `MALFORMED_RESULT` exact type, but the content is not what a real batch produces, so no honest count exists: `outputs` is not a tuple or cannot be read;
                      an output is not exactly a `VoiceEnrollmentResult` (Prompt 790) or its `status` or `code` is not exactly a `str`; the result holds both
                      outputs AND failures (a real batch holds one or the other); its failures cannot be read. The first problem rejects the whole summary;
                      nothing is repaired, skipped or partially counted.
Either code gives the REJECTED summary: every count 0, both mappings empty, `success=False` and `codes()` == [that code]; the same value for every input of
that kind.

VALID INPUT (`codes()` == [])
- `output_count`  = number of outputs; `failure_count` = number of failures; `total_count` = `output_count + failure_count`.
- `status_counts` / `code_counts` = how many outputs carry each exact `status` / `code` string. Keys are compared exactly (no trimming or case folding),
  every count is >= 1, and each mapping adds up to `output_count`. Both are ordered by key ascending (plain string order), never first-seen order.
- `success` = `batch_result.ok is True`. It says nothing about any output's status; read `status_counts` for that. An empty valid batch gives all counts 0,
  empty mappings and success=True.

NO REINTERPRETATION, NO RETENTION
Outputs are read only through their public `status` and `code`; `metadata` (and request_id/profile_id) is never read. The summary keeps no batch result and no
output, only `int`, `bool` and `str` values and tuples of them.

RESULT
`VoiceEnrollmentBatchSummary` is immutable (`__slots__`), cannot be built directly or subclassed (`TypeError`), compares and hashes by value (exact type
only), returns itself from copy/deepcopy and refuses pickling. `status_counts`, `code_counts`, `codes()` and `to_dict()` are fresh plain data on every call.
The function never raises for bad inputs and is deterministic.

WHAT THIS MODULE DOES NOT DO
It imports and calls no batch runner, pipeline, dispatcher, executor or result factory, and has no audio capture, recording, recognition, enrollment or
biometric processing, no I/O, networking, filesystem, persistence, database, subprocess, AI model or external/cloud service. No clock or randomness, no
module-level mutable state. Its only imports are the Prompt 796 batch result type and the Prompt 790 result type. Not wired into `process_input()`, Core,
the Planner, the Agent Loop, Android or runtime voice processing.
"""

from .voice_enrollment_batch import VoiceEnrollmentBatchResult
from .voice_enrollment_result import VoiceEnrollmentResult

_PREFIX = "VOICE_ENROLLMENT_BATCH_SUMMARY_"
CODE_INVALID_RESULT = _PREFIX + "INVALID_RESULT"
CODE_MALFORMED_RESULT = _PREFIX + "MALFORMED_RESULT"
CODES = (CODE_INVALID_RESULT, CODE_MALFORMED_RESULT)

_CREATE_TOKEN = object()


class VoiceEnrollmentBatchSummary:
    """Immutable aggregate counts for one `VoiceEnrollmentBatchResult`. Obtain it only from `create_voice_enrollment_batch_summary()`."""

    __slots__ = ("_output_count", "_failure_count", "_total_count", "_status_counts", "_code_counts", "_success", "_codes")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("VoiceEnrollmentBatchSummary cannot be subclassed.")

    def __init__(self, _token, output_count, failure_count, total_count, status_counts, code_counts, success, codes):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_voice_enrollment_batch_summary() to obtain a VoiceEnrollmentBatchSummary.")
        object.__setattr__(self, "_output_count", output_count)
        object.__setattr__(self, "_failure_count", failure_count)
        object.__setattr__(self, "_total_count", total_count)
        object.__setattr__(self, "_status_counts", tuple(status_counts))
        object.__setattr__(self, "_code_counts", tuple(code_counts))
        object.__setattr__(self, "_success", success)
        object.__setattr__(self, "_codes", tuple(codes))

    def __setattr__(self, key, value):
        raise AttributeError("VoiceEnrollmentBatchSummary is immutable.")

    def __delattr__(self, key):
        raise AttributeError("VoiceEnrollmentBatchSummary is immutable.")

    @property
    def output_count(self):
        return self._output_count

    @property
    def failure_count(self):
        return self._failure_count

    @property
    def total_count(self):
        """`output_count + failure_count`."""
        return self._total_count

    @property
    def status_counts(self):
        """A FRESH dict {exact output status: count}, ordered by key ascending."""
        return dict(self._status_counts)

    @property
    def code_counts(self):
        """A FRESH dict {exact output code: count}, ordered by key ascending."""
        return dict(self._code_counts)

    @property
    def success(self):
        """True only when the batch result is ok. Says nothing about any output's status."""
        return self._success

    def codes(self):
        return list(self._codes)

    def to_dict(self):
        """Fresh plain data (fixed key order). Mutating it never affects this summary."""
        return {"output_count": self._output_count, "failure_count": self._failure_count, "total_count": self._total_count,
                "status_counts": dict(self._status_counts), "code_counts": dict(self._code_counts), "success": self._success,
                "codes": list(self._codes)}

    def _key(self):
        return (self._output_count, self._failure_count, self._total_count, self._status_counts, self._code_counts, self._success, self._codes)

    def __eq__(self, other):
        if type(other) is not VoiceEnrollmentBatchSummary:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("VoiceEnrollmentBatchSummary is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "VoiceEnrollmentBatchSummary(output_count=%r, failure_count=%r, total_count=%r, success=%r, codes=%r)" % (
            self._output_count, self._failure_count, self._total_count, self._success, list(self._codes))


def _rejected(code):
    return VoiceEnrollmentBatchSummary(_CREATE_TOKEN, 0, 0, 0, (), (), False, (code,))


def create_voice_enrollment_batch_summary(batch_result):
    """Count the outputs, failures, output statuses and output codes of an exact `VoiceEnrollmentBatchResult`. Runs nothing and performs no I/O.
    Deterministic, never raises for bad inputs, retains and changes nothing it is given. Returns a `VoiceEnrollmentBatchSummary`."""
    if type(batch_result) is not VoiceEnrollmentBatchResult:
        return _rejected(CODE_INVALID_RESULT)
    try:
        outputs = batch_result.outputs
        if type(outputs) is not tuple:
            return _rejected(CODE_MALFORMED_RESULT)
        failure_count = len(batch_result.failures)
        success = batch_result.ok is True
    except Exception:
        return _rejected(CODE_MALFORMED_RESULT)
    if failure_count and outputs:
        return _rejected(CODE_MALFORMED_RESULT)
    status_counts = {}
    code_counts = {}
    try:
        for output in outputs:
            if type(output) is not VoiceEnrollmentResult:
                return _rejected(CODE_MALFORMED_RESULT)
            status = output.status
            code = output.code
            if type(status) is not str or type(code) is not str:
                return _rejected(CODE_MALFORMED_RESULT)
            status_counts[status] = status_counts.get(status, 0) + 1
            code_counts[code] = code_counts.get(code, 0) + 1
    except Exception:
        return _rejected(CODE_MALFORMED_RESULT)
    output_count = len(outputs)
    return VoiceEnrollmentBatchSummary(_CREATE_TOKEN, output_count, failure_count, output_count + failure_count,
                                       sorted(status_counts.items()), sorted(code_counts.items()), success, ())
