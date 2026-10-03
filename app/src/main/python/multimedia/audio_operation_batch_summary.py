"""
Audio Operation Batch Summary (Prompt 771, Section 8 - Multimedia)
==================================================================
A small deterministic summary of a completed audio-operation batch (Prompt 770). It only counts success and failure over the result objects the
batch preserved. It never reads a request, a plan, a dispatch result or any pipeline failure code, and it adds no audio-operation semantics.

    create_audio_operation_batch_summary(batch_result) -> AudioOperationBatchSummary(total, successful, failed, success)

INPUT CONTRACT (exact type only; nothing is coerced)
- `batch_result` must be exactly an `AudioOperationBatchResult` (Prompt 770).

INVALID INPUT
`success=False`, `total=0`, `successful=0`, `failed=0` and the single summary-level code `AUDIO_OPERATION_BATCH_SUMMARY_INVALID_RESULT`.

VALID INPUT
- `total      = len(batch_result.results)`
- `successful = number of results whose `ok` is exactly True`
- `failed     = total - successful`
- `success    = True` only when `batch_result.ok is True` and `failed == 0`. An empty valid batch gives total=0, successful=0, failed=0, success=True.
`success` reflects the batch result's overall `ok` state: it is True only when `batch_result.ok is True` AND `failed == 0`. (This deliberately differs from the
image summary of Prompt 758, which ignored `batch_result.ok`: a batch whose own input was invalid has `ok=False` and no results, so it summarises as
total=0, successful=0, failed=0, success=False, while an empty VALID batch is still a success.) `successful` is counted from the preserved `results` only.
The summary does not read `batch_result.failures`, `codes()` or `to_dict()`, and it does not inspect or reinterpret individual pipeline failure codes. A valid summary has no codes (`codes()` is `[]`).

RESULT
`AudioOperationBatchSummary` is immutable (`__slots__`, read-only), cannot be built directly or subclassed (`TypeError`), compares and hashes by value
(exact type only), returns itself from copy/deepcopy and refuses pickling (like the other multimedia results). `codes()` and `to_dict()`
({"total", "successful", "failed", "success", "codes"}) are fresh on every call. The function never raises for bad inputs, only reads the batch result
and its contained results, changes nothing, and is deterministic.

WHAT THIS MODULE DOES NOT DO
No filesystem, audio decoding or samples, network, database, AI model or external service, no clock or randomness, no concurrency, threading, retries or
scheduling, no automatic operation selection, no module-level mutable state. Its only import is the Prompt 770 batch result type. Not wired into
`process_input()`, Core, the Planner, the Agent Loop or Section 7.
"""

from .audio_operation_batch import AudioOperationBatchResult

CODE_INVALID_RESULT = "AUDIO_OPERATION_BATCH_SUMMARY_INVALID_RESULT"

_CREATE_TOKEN = object()


class AudioOperationBatchSummary:
    """Immutable counts for one `AudioOperationBatchResult`. Obtain it only from `create_audio_operation_batch_summary()`."""

    __slots__ = ("_total", "_successful", "_failed", "_success", "_codes")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioOperationBatchSummary cannot be subclassed.")

    def __init__(self, _token, total, successful, failed, success, codes):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_audio_operation_batch_summary() to obtain an AudioOperationBatchSummary.")
        object.__setattr__(self, "_total", total)
        object.__setattr__(self, "_successful", successful)
        object.__setattr__(self, "_failed", failed)
        object.__setattr__(self, "_success", success)
        object.__setattr__(self, "_codes", tuple(codes))

    def __setattr__(self, key, value):
        raise AttributeError("AudioOperationBatchSummary is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioOperationBatchSummary is immutable.")

    @property
    def total(self):
        """Number of results in the batch (0 for invalid input)."""
        return self._total

    @property
    def successful(self):
        """Number of results whose `ok` is exactly True (0 for invalid input)."""
        return self._successful

    @property
    def failed(self):
        """`total - successful` (0 for invalid input)."""
        return self._failed

    @property
    def success(self):
        """True only for a valid input whose batch result is ok and has no failed result (an empty valid batch is a success)."""
        return self._success

    def codes(self):
        return list(self._codes)

    def to_dict(self):
        """Fresh plain data: {"total", "successful", "failed", "success", "codes"}. Mutating it never affects this summary."""
        return {"total": self._total, "successful": self._successful, "failed": self._failed, "success": self._success,
                "codes": list(self._codes)}

    def _key(self):
        return (self._total, self._successful, self._failed, self._success, self._codes)

    def __eq__(self, other):
        if type(other) is not AudioOperationBatchSummary:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioOperationBatchSummary is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "AudioOperationBatchSummary(total=%r, successful=%r, failed=%r, success=%r, codes=%r)" % (
            self._total, self._successful, self._failed, self._success, list(self._codes))


def create_audio_operation_batch_summary(batch_result):
    """Count successful and failed results of an `AudioOperationBatchResult`. Deterministic, never raises for bad inputs, changes nothing."""
    if type(batch_result) is not AudioOperationBatchResult:
        return AudioOperationBatchSummary(_CREATE_TOKEN, 0, 0, 0, False, (CODE_INVALID_RESULT,))
    results = batch_result.results
    total = len(results)
    successful = sum(1 for result in results if result.ok is True)
    failed = total - successful
    return AudioOperationBatchSummary(_CREATE_TOKEN, total, successful, failed, batch_result.ok is True and failed == 0, ())
