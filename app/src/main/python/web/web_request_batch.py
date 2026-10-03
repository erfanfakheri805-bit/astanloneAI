"""
Web Request Batch (Prompt 784, Section 9 - Web / Service Work)
==============================================================
A small immutable batch layer on top of the existing Web Request pipeline (Prompt 783). It runs the public `run_web_request_pipeline(plan)` once per
plan, in input order, and keeps every `WebRequestOutput`. It adds no web-request semantics and no per-plan logic of its own: everything about one plan
(dispatch, execution, output creation) is decided by the pipeline (Prompt 783) and the layers beneath it. It never performs a request.

    run_web_request_batch(plans) -> WebRequestBatchResult(ok, outputs, failures)

INPUT CONTRACT (exact types only; nothing is coerced, normalized, sorted, de-duplicated or copied)
- `plans` must be exactly a `tuple` (lists, sets, dicts, generators, strings, tuple subclasses such as named tuples, ... are rejected). An empty tuple
  is valid. A tuple is the one collection here that is ordered AND immutable, so the batch can neither be reordered nor changed while it runs.
- every item must be exactly a `WebRequestPlan` (Prompt 777). Look-alikes, dicts, subclass-free fakes and the chain's own outputs are rejected.
These two type checks are the batch's only own checks; they are needed here because the pipeline is only ever called with inputs that passed them.

FAILURE CODES (only these two; prefix WEB_REQUEST_BATCH_; each failure is `{"code", "field", "message"}`, as in the other Section 9 results)
1. `INVALID_COLLECTION` (field "plans")           `plans` is not exactly a tuple. Items are not examined at all.
2. `INVALID_PLAN`       (field "plans[<index>]")  one failure per item that is not exactly a `WebRequestPlan`, in input order (every bad item is reported
                                                  in one call). Only a valid tuple is examined; the message names the index, never the object.
   If either is reported: ok=False, outputs=() and `run_web_request_pipeline()` is NOT called at all (not even for the valid items). A rejected
   batch therefore has no partial effect, and no part of the offending input is read, copied or kept.

VALID INPUT
`run_web_request_pipeline()` is called exactly once per plan item, in input order (the same plan object appearing twice is two items and gives two
calls), with that very plan object and nothing else. The exact objects it returns (identity preserved) are stored, in order, in an immutable tuple
`outputs` with the same length as `plans`. They are never re-coded, re-validated, copied or re-interpreted; the batch does not look at their status,
code or metadata. `ok=True` for every valid batch, an empty one included (`outputs=()`, no pipeline call): `ok` says that the batch input was valid
and was run, NOT how any single plan came out. The per-plan status (today `NOT_IMPLEMENTED` for each valid plan) is read from `outputs`.

NO DUPLICATED LOGIC
The batch does not import or call the dispatcher, the executor or the output factory, and never reads a plan's values. Dispatch, execution and output
creation stay in Prompts 782 / 778 / 779; the single-plan pipeline stays Prompt 783.

NO RETENTION
Neither the input tuple nor any plan is kept: they live only in the call. The result holds only the returned outputs (plain immutable values built by the
pipeline) and, when rejected, plain `str` failure triples. The module has no module-level state of any kind.

RESULT
`WebRequestBatchResult` is immutable (`__slots__`, assignment/deletion raises), cannot be built directly or subclassed (`TypeError`), compares and hashes
by value (exact type only; equal outputs and failures in the same order), returns itself from copy/deepcopy and refuses pickling (like the other Section 9
results). `outputs` is a tuple of the exact `WebRequestOutput` objects; `failures`, `codes()` and `to_dict()` ({"ok", "outputs", "failures"}, `outputs` as a
list of each output's own `to_dict()`) are fresh plain data on every call, so mutating them never affects the result. The function never raises for bad
inputs, only reads the tuple and the plans, and is deterministic: the same plans give equal results.

WHAT THIS MODULE DOES NOT DO
No networking, no filesystem access, no subprocess, no persistence, no database, no AI model or external service call, and no request is ever executed.
No clock or randomness, no concurrency, threading, retries, scheduling or short-circuiting, no module-level mutable state. Its only imports are the
Prompt 777 plan type and the Prompt 783 pipeline function. Not wired into `process_input()`, Core, the Planner, the Agent Loop or any earlier section.
"""

from .web_request_pipeline import run_web_request_pipeline
from .web_request_plan import WebRequestPlan

_PREFIX = "WEB_REQUEST_BATCH_"
FAILURE_INVALID_COLLECTION = _PREFIX + "INVALID_COLLECTION"
FAILURE_INVALID_PLAN = _PREFIX + "INVALID_PLAN"
FAILURE_CODES = (FAILURE_INVALID_COLLECTION, FAILURE_INVALID_PLAN)

_CREATE_TOKEN = object()


def _failure(code, field, message):
    return (code, field, message)


class WebRequestBatchResult:
    """Immutable outcome of `run_web_request_batch()`. Obtain it only from that function."""

    __slots__ = ("_outputs", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebRequestBatchResult cannot be subclassed.")

    def __init__(self, _token, outputs, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use run_web_request_batch() to obtain a WebRequestBatchResult.")
        object.__setattr__(self, "_outputs", tuple(outputs))
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("WebRequestBatchResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebRequestBatchResult is immutable.")

    @property
    def ok(self):
        """True only when the batch input was valid and was run (an empty valid batch is ok). Says nothing about any single output's status."""
        return not self._failures

    @property
    def outputs(self):
        """Tuple of the exact `WebRequestOutput` objects the pipeline returned, in input order (empty when the input was invalid)."""
        return self._outputs

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "outputs", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok, "outputs": [o.to_dict() for o in self._outputs],
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._outputs, self._failures)

    def __eq__(self, other):
        if type(other) is not WebRequestBatchResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebRequestBatchResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebRequestBatchResult(ok=%r, outputs=%d, codes=%r)" % (self.ok, len(self._outputs), self.codes())


def run_web_request_batch(plans):
    """Run `run_web_request_pipeline()` once per plan, in order, and return a `WebRequestBatchResult`. `plans` must be exactly a tuple of exact
    `WebRequestPlan` objects. Performs no I/O of any kind. Deterministic, never raises for bad inputs, retains and changes nothing it is given."""
    if type(plans) is not tuple:
        return WebRequestBatchResult(_CREATE_TOKEN, (), [_failure(
            FAILURE_INVALID_COLLECTION, "plans", "plans must be exactly a tuple of WebRequestPlan objects.")])
    failures = [_failure(FAILURE_INVALID_PLAN, "plans[%d]" % index, "plans[%d] must be exactly a WebRequestPlan." % index)
                for index, item in enumerate(plans) if type(item) is not WebRequestPlan]
    if failures:
        return WebRequestBatchResult(_CREATE_TOKEN, (), failures)
    return WebRequestBatchResult(_CREATE_TOKEN, tuple(run_web_request_pipeline(plan) for plan in plans), ())
