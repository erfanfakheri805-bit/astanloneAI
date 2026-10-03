"""
Web Request Batch Summary (Prompt 785, Section 9 - Web / Service Work)
======================================================================
A small immutable summary of a completed web request batch (Prompt 784). It only counts what the batch result preserved: how many outputs and failures
it holds and how often each exact output status and each exact output code occurs. It never runs, re-runs or re-interprets anything, and it adds no
web-request semantics.

    create_web_request_batch_summary(batch_result) -> WebRequestBatchSummary(total_count, output_count, failure_count, status_counts, code_counts, success)

INPUT CONTRACT (exact type only; nothing is coerced)
- `batch_result` must be exactly a `WebRequestBatchResult` (Prompt 784).

CODES (only these two; prefix WEB_REQUEST_BATCH_SUMMARY_)
1. `INVALID_RESULT`   `batch_result` is not exactly a `WebRequestBatchResult` (None, a dict, a look-alike, an output, a plan, ...). Nothing is read from it.
2. `MALFORMED_RESULT` `batch_result` is the exact type but its content is not what a real batch produces, so no honest count exists. This is the case when
                      - an output is not exactly a `WebRequestOutput` (Prompt 779), or its `status` or `code` is not exactly a `str`;
                      - the result holds both outputs AND failures (a real batch holds one or the other: a rejected batch has no outputs);
                      - its failures cannot be read.
                      The first problem found rejects the whole summary; nothing is repaired, skipped or partially counted.
Either code gives the REJECTED summary: `success=False`, every count 0, both mappings empty and `codes()` == [that code]. It is the same value for every
input of that kind (deterministic).

VALID INPUT (no code, `codes()` == [])
- `output_count`  = number of outputs the batch result holds.
- `failure_count` = number of failures it holds (0 for a run batch; for a rejected batch one per reported failure).
- `total_count`   = `output_count + failure_count`: the number of entries the batch result recorded. A rejected batch records its failures only (the valid
                    items beside a bad one are not recorded), so for it this is the failure count, not the size of the caller's tuple.
- `status_counts` = how many outputs carry each exact `status` string; `code_counts` the same for each exact `code` string. Keys are compared exactly (no
                    trimming, case folding or grouping) and every count is >= 1, so the counts of each mapping add up to `output_count`.
- `success`       = `batch_result.ok is True`, i.e. the batch input was valid and was run. Like `ok` itself, it says NOTHING about the status of any output
                    (today every output of a valid batch is NOT_IMPLEMENTED); read `status_counts` for that. An empty valid batch gives all counts 0, empty
                    mappings and success=True.

ORDER
Both mappings are ordered by key, ascending (plain string order), whatever the order of the outputs: the same multiset of outputs always gives the same
summary. This is the only ordering rule; first-seen order is never used.

NO REINTERPRETATION
Outputs are read only through their public `status` and `code`; their `metadata` is never read. Nothing is modified, re-coded, re-validated or executed.
The summary never reads the batch result's failure codes or messages and never touches a plan.

NO RETENTION
Neither the batch result nor any output is kept: the summary holds only `int`, `bool` and `str` values and tuples of them.

RESULT
`WebRequestBatchSummary` is immutable (`__slots__`, assignment/deletion raises), cannot be built directly or subclassed (`TypeError`), compares and hashes by
value (exact type only), returns itself from copy/deepcopy and refuses pickling (like the other Section 9 results). `status_counts`, `code_counts`,
`codes()` and `to_dict()` ({"total_count", "output_count", "failure_count", "status_counts", "code_counts", "success", "codes"}) are fresh plain data on every
call, so mutating them never affects the summary. The function never raises for bad inputs, only reads the batch result and its outputs, and is
deterministic.

WHAT THIS MODULE DOES NOT DO
It imports and calls no dispatcher, executor, pipeline or output factory (nothing is ever executed, so there is no duplicate execution), and has no
networking, filesystem access, subprocess, persistence, database, AI model or external service. No clock or randomness, no module-level mutable state. Its
only imports are the Prompt 784 batch result type and the Prompt 779 output type. Not wired into `process_input()`, Core, the Planner, the Agent Loop or any
earlier section.
"""

from .web_request_batch import WebRequestBatchResult
from .web_request_output import WebRequestOutput

_PREFIX = "WEB_REQUEST_BATCH_SUMMARY_"
CODE_INVALID_RESULT = _PREFIX + "INVALID_RESULT"
CODE_MALFORMED_RESULT = _PREFIX + "MALFORMED_RESULT"
CODES = (CODE_INVALID_RESULT, CODE_MALFORMED_RESULT)

_CREATE_TOKEN = object()


class WebRequestBatchSummary:
    """Immutable aggregate counts for one `WebRequestBatchResult`. Obtain it only from `create_web_request_batch_summary()`."""

    __slots__ = ("_total_count", "_output_count", "_failure_count", "_status_counts", "_code_counts", "_success", "_codes")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebRequestBatchSummary cannot be subclassed.")

    def __init__(self, _token, total_count, output_count, failure_count, status_counts, code_counts, success, codes):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_web_request_batch_summary() to obtain a WebRequestBatchSummary.")
        object.__setattr__(self, "_total_count", total_count)
        object.__setattr__(self, "_output_count", output_count)
        object.__setattr__(self, "_failure_count", failure_count)
        object.__setattr__(self, "_status_counts", tuple(status_counts))
        object.__setattr__(self, "_code_counts", tuple(code_counts))
        object.__setattr__(self, "_success", success)
        object.__setattr__(self, "_codes", tuple(codes))

    def __setattr__(self, key, value):
        raise AttributeError("WebRequestBatchSummary is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebRequestBatchSummary is immutable.")

    @property
    def total_count(self):
        """`output_count + failure_count`: the number of entries the batch result recorded (0 for rejected input)."""
        return self._total_count

    @property
    def output_count(self):
        """Number of outputs the batch result holds (0 for rejected input)."""
        return self._output_count

    @property
    def failure_count(self):
        """Number of failures the batch result holds (0 for rejected input)."""
        return self._failure_count

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
        """True only when the batch result is ok (its input was valid and was run). Says nothing about any output's status."""
        return self._success

    def codes(self):
        return list(self._codes)

    def to_dict(self):
        """Fresh plain data (fixed key order). Mutating it never affects this summary."""
        return {"total_count": self._total_count, "output_count": self._output_count, "failure_count": self._failure_count,
                "status_counts": dict(self._status_counts), "code_counts": dict(self._code_counts), "success": self._success,
                "codes": list(self._codes)}

    def _key(self):
        return (self._total_count, self._output_count, self._failure_count, self._status_counts, self._code_counts, self._success, self._codes)

    def __eq__(self, other):
        if type(other) is not WebRequestBatchSummary:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebRequestBatchSummary is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebRequestBatchSummary(total_count=%r, output_count=%r, failure_count=%r, success=%r, codes=%r)" % (
            self._total_count, self._output_count, self._failure_count, self._success, list(self._codes))


def _rejected(code):
    return WebRequestBatchSummary(_CREATE_TOKEN, 0, 0, 0, (), (), False, (code,))


def create_web_request_batch_summary(batch_result):
    """Count the outputs, failures, output statuses and output codes of an exact `WebRequestBatchResult`. Performs no I/O of any kind and runs nothing.
    Deterministic, never raises for bad inputs, retains and changes nothing it is given. Returns a `WebRequestBatchSummary`."""
    if type(batch_result) is not WebRequestBatchResult:
        return _rejected(CODE_INVALID_RESULT)
    outputs = batch_result.outputs
    try:
        failure_count = len(batch_result.failures)
    except Exception:
        return _rejected(CODE_MALFORMED_RESULT)
    if failure_count and outputs:
        return _rejected(CODE_MALFORMED_RESULT)
    status_counts = {}
    code_counts = {}
    for output in outputs:
        if type(output) is not WebRequestOutput:
            return _rejected(CODE_MALFORMED_RESULT)
        status = output.status
        code = output.code
        if type(status) is not str or type(code) is not str:
            return _rejected(CODE_MALFORMED_RESULT)
        status_counts[status] = status_counts.get(status, 0) + 1
        code_counts[code] = code_counts.get(code, 0) + 1
    output_count = len(outputs)
    return WebRequestBatchSummary(_CREATE_TOKEN, output_count + failure_count, output_count, failure_count,
                                  sorted(status_counts.items()), sorted(code_counts.items()), batch_result.ok is True, ())
