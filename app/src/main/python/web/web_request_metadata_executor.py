"""
Web Request Metadata Executor (Prompt 781, Section 9 - Web / Service Work)
==========================================================================
A deliberately small, METADATA-ONLY executor. It follows `WebRequestOutput` (Prompt 779) and its validator (Prompt 780) and copies an output's values into an
immutable result. It never executes a request.

    execute_web_request_metadata(output) -> WebRequestMetadataExecutionResult(status, code, metadata)

BEHAVIOR
1. `output` must be exactly a `WebRequestOutput` that passes `validate_web_request_output()` (exact `str` status and code, metadata `None` or an exact dict).
   Anything else (None, a dict, a look-alike, a malformed output, ...) gives a REJECTED result with code `WEB_REQUEST_METADATA_EXECUTOR_INVALID_OUTPUT` and
   `metadata` None. Nothing is retained from an invalid input.
2. A valid output gives a result carrying the output's `status`, `code` and `metadata` values unchanged (the very same `str` / `int` / other value objects,
   same key order). The metadata dict is COPIED (a shallow copy of its key/value pairs); `metadata=None` stays `None`. Metadata contents are NOT interpreted,
   validated, normalized or transformed. The `WebRequestOutput` object itself is NOT retained.

RESULT
`WebRequestMetadataExecutionResult` has exactly three fields: `status`, `code` and `metadata` (a FRESH dict on every access, or None). `to_dict()` returns FRESH
plain data {"status", "code", "metadata"}. The result is immutable (`__slots__`, assignment/deletion raises), cannot be constructed directly or subclassed,
compares and hashes by value (exact type only), returns itself from copy/deepcopy (so the copy is equal) and refuses pickling (`TypeError`). Repeated
execution of the same input is deterministic.

WHAT THIS MODULE DOES NOT DO
No networking, no filesystem access, no subprocess, no persistence, no database, no AI model or external service call, and no request is ever executed. It
does not interpret the status, code or metadata values. No clock or randomness, no module-level mutable state. Its only import is the Prompt 780 output
validator. Not wired into `process_input()`, Core, the Planner, the Agent Loop or any earlier section.
"""

from .web_request_output_validator import validate_web_request_output

STATUS_REJECTED = "REJECTED"

CODE_INVALID_OUTPUT = "WEB_REQUEST_METADATA_EXECUTOR_INVALID_OUTPUT"
CODES = (CODE_INVALID_OUTPUT,)

_CREATE_TOKEN = object()


class WebRequestMetadataExecutionResult:
    """Immutable outcome of `execute_web_request_metadata()`. Obtain it only from that function."""

    __slots__ = ("_status", "_code", "_items")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebRequestMetadataExecutionResult cannot be subclassed.")

    def __init__(self, _token, status, code, items):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use execute_web_request_metadata() to obtain a WebRequestMetadataExecutionResult.")
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_items", items)

    def __setattr__(self, key, value):
        raise AttributeError("WebRequestMetadataExecutionResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebRequestMetadataExecutionResult is immutable.")

    @property
    def status(self):
        return self._status

    @property
    def code(self):
        return self._code

    @property
    def metadata(self):
        """A FRESH dict of the copied metadata values, or None when there was no metadata."""
        if self._items is None:
            return None
        return dict(self._items)

    def to_dict(self):
        """Fresh plain data: {"status", "code", "metadata"}. Mutating it never affects this result."""
        return {"status": self._status, "code": self._code, "metadata": self.metadata}

    def _key(self):
        return (self._status, self._code, self._items)

    def __eq__(self, other):
        if type(other) is not WebRequestMetadataExecutionResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebRequestMetadataExecutionResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebRequestMetadataExecutionResult(status=%r, code=%r)" % (self._status, self._code)


def execute_web_request_metadata(output):
    """Copy the status, code and metadata of an exact, valid `WebRequestOutput` into an immutable result. Performs no I/O of any kind.
    Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `WebRequestMetadataExecutionResult`."""
    checked = validate_web_request_output(output)
    if not checked.ok:
        return WebRequestMetadataExecutionResult(_CREATE_TOKEN, STATUS_REJECTED, CODE_INVALID_OUTPUT, None)
    valid = checked.output
    metadata = valid.metadata
    items = None if metadata is None else tuple(metadata.items())
    return WebRequestMetadataExecutionResult(_CREATE_TOKEN, valid.status, valid.code, items)
