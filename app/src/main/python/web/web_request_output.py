"""
Web Request Output (Prompt 779, Section 9 - Web / Service Work)
===============================================================
The output contract of the Web Request execution layer. It follows `WebRequestExecutionResult` (Prompt 778) and turns it into a small, immutable,
value-comparable output object. It executes nothing.

    create_web_request_output(execution_result) -> WebRequestOutput(status, code, metadata)

BEHAVIOR
1. `execution_result` must be exactly a `WebRequestExecutionResult` (None, a dict, a look-alike, ... is not). Anything else gives a REJECTED output with
   code `WEB_REQUEST_OUTPUT_INVALID_EXECUTION_RESULT` and `metadata` None; nothing is read from the input.
2. A valid execution result gives an output carrying its `status`, `code` and `metadata` values unchanged (the very same `str` / `int` objects, same key order).
   When the execution result has no metadata (`None`), the output's metadata is `None` too. The execution result object itself is NOT retained.

OUTPUT
`WebRequestOutput` has exactly three fields: `status`, `code` and `metadata` (a FRESH dict on every access, or None). `to_dict()` returns FRESH plain data
{"status", "code", "metadata"}. The output is immutable (`__slots__`, assignment/deletion raises), cannot be constructed directly or subclassed, compares and
hashes by value (exact type only), returns itself from copy/deepcopy (so the copy is equal) and refuses pickling (`TypeError`).

WHAT THIS MODULE DOES NOT DO
No networking, no filesystem access, no subprocess, no persistence, no database, no AI model or external service call. It does not interpret, validate or
normalize status, code or metadata values. No clock or randomness, no module-level mutable state. Its only import is the Prompt 778 execution result type.
Not wired into `process_input()`, Core, the Planner, the Agent Loop or any earlier section.
"""

from .web_request_executor import WebRequestExecutionResult

STATUS_REJECTED = "REJECTED"

CODE_INVALID_EXECUTION_RESULT = "WEB_REQUEST_OUTPUT_INVALID_EXECUTION_RESULT"
CODES = (CODE_INVALID_EXECUTION_RESULT,)

_CREATE_TOKEN = object()


class WebRequestOutput:
    """Immutable output of `create_web_request_output()`. Obtain it only from that function."""

    __slots__ = ("_status", "_code", "_items")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebRequestOutput cannot be subclassed.")

    def __init__(self, _token, status, code, items):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use create_web_request_output() to obtain a WebRequestOutput.")
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_items", items)

    def __setattr__(self, key, value):
        raise AttributeError("WebRequestOutput is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebRequestOutput is immutable.")

    @property
    def status(self):
        return self._status

    @property
    def code(self):
        return self._code

    @property
    def metadata(self):
        """A FRESH dict of the preserved metadata values, or None when there was no metadata."""
        if self._items is None:
            return None
        return dict(self._items)

    def to_dict(self):
        """Fresh plain data: {"status", "code", "metadata"}. Mutating it never affects this output."""
        return {"status": self._status, "code": self._code, "metadata": self.metadata}

    def _key(self):
        return (self._status, self._code, self._items)

    def __eq__(self, other):
        if type(other) is not WebRequestOutput:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebRequestOutput is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebRequestOutput(status=%r, code=%r)" % (self._status, self._code)


def create_web_request_output(execution_result):
    """Build a `WebRequestOutput` from an exact `WebRequestExecutionResult`. Performs no I/O of any kind.
    Deterministic, never raises for bad inputs, changes nothing it is given."""
    if type(execution_result) is not WebRequestExecutionResult:
        return WebRequestOutput(_CREATE_TOKEN, STATUS_REJECTED, CODE_INVALID_EXECUTION_RESULT, None)
    metadata = execution_result.metadata
    items = None if metadata is None else tuple(metadata.items())
    return WebRequestOutput(_CREATE_TOKEN, execution_result.status, execution_result.code, items)
