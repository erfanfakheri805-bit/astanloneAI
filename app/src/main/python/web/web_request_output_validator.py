"""
Web Request Output Validation (Prompt 780, Section 9 - Web / Service Work)
==========================================================================
A small deterministic validator for the `WebRequestOutput` contract (Prompt 779). It follows the architecture of the earlier Section 9 validator
(Prompt 776) as a separate, unrelated type, and executes nothing.

    validate_web_request_output(output) -> WebRequestOutputValidationResult(ok, output, failures)

RULES
1. `output` must be exactly a `WebRequestOutput` (a subclass-free type check; None, a dict, a look-alike, ... is `INVALID_OUTPUT`). Nothing is read
   from an invalid input and it is never stored.
2. For an exact `WebRequestOutput` the three public values are checked, in this order, and every problem is reported together:
   - `status` must be an exact `str`            (otherwise `INVALID_STATUS`)
   - `code` must be an exact `str`              (otherwise `INVALID_CODE`)
   - `metadata` must be `None` or an exact `dict` (otherwise `INVALID_METADATA`; a metadata read that raises counts as invalid)
3. Nothing else is examined: the string contents, the metadata keys and the metadata values are NOT interpreted, normalized or compared with anything.

FAILURE CODES (stable, prefix `WEB_REQUEST_OUTPUT_VALIDATOR_`): `INVALID_OUTPUT`, `INVALID_STATUS`, `INVALID_CODE`, `INVALID_METADATA`.

RESULT
`WebRequestOutputValidationResult` is immutable and has `ok`, `output`, `failures`, `codes()` and `to_dict()`. On success `output` is the very object that was
passed in (identity preserved). On ANY failure `output` is None: an invalid or malformed object is never retained. `failures` is a tuple of fresh
`{"code", "field", "message"}` dicts. `to_dict()` returns FRESH plain data {"ok", "output", "failures"} (`output` is the output's own fresh `to_dict()` or None).
The result compares and hashes by value (exact type only), cannot be constructed directly or subclassed, returns itself from copy/deepcopy (so the copy is
equal) and refuses pickling (`TypeError`). Validation is deterministic, never raises for bad inputs and never changes what it is given.

WHAT THIS MODULE DOES NOT DO
No networking, no filesystem access, no subprocess, no persistence, no database, no AI model or external service call. It reads no project state other than
the one output it is given. No clock or randomness, no module-level mutable state. Its only import is the Prompt 779 output type. Not wired into
`process_input()`, Core, the Planner, the Agent Loop or any earlier section.
"""

from .web_request_output import WebRequestOutput

FAILURE_INVALID_OUTPUT = "WEB_REQUEST_OUTPUT_VALIDATOR_INVALID_OUTPUT"
FAILURE_INVALID_STATUS = "WEB_REQUEST_OUTPUT_VALIDATOR_INVALID_STATUS"
FAILURE_INVALID_CODE = "WEB_REQUEST_OUTPUT_VALIDATOR_INVALID_CODE"
FAILURE_INVALID_METADATA = "WEB_REQUEST_OUTPUT_VALIDATOR_INVALID_METADATA"
FAILURE_CODES = (FAILURE_INVALID_OUTPUT, FAILURE_INVALID_STATUS, FAILURE_INVALID_CODE, FAILURE_INVALID_METADATA)

_CREATE_TOKEN = object()


def _failure(code, message, field):
    return (code, field, message)


class WebRequestOutputValidationResult:
    """Immutable outcome of `validate_web_request_output()`. Obtain it only from that function."""

    __slots__ = ("_output", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("WebRequestOutputValidationResult cannot be subclassed.")

    def __init__(self, _token, output, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use validate_web_request_output() to obtain a WebRequestOutputValidationResult.")
        object.__setattr__(self, "_output", output)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("WebRequestOutputValidationResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("WebRequestOutputValidationResult is immutable.")

    @property
    def ok(self):
        return not self._failures

    @property
    def output(self):
        """The `WebRequestOutput` that was passed in (same object) when it is valid, otherwise None."""
        return self._output

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "output", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok,
                "output": self._output.to_dict() if self._output is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._output, self._failures)

    def __eq__(self, other):
        if type(other) is not WebRequestOutputValidationResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("WebRequestOutputValidationResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "WebRequestOutputValidationResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def validate_web_request_output(output):
    """Check that `output` is an exact `WebRequestOutput` whose status and code are exact strings and whose metadata is None or an exact dict.
    Performs no I/O of any kind. Deterministic, never raises for bad inputs, changes nothing it is given. Returns a `WebRequestOutputValidationResult`."""
    if type(output) is not WebRequestOutput:
        return WebRequestOutputValidationResult(_CREATE_TOKEN, None, [_failure(
            FAILURE_INVALID_OUTPUT, "output must be exactly a WebRequestOutput.", "output")])
    failures = []
    try:
        status_ok = type(output.status) is str
    except Exception:
        status_ok = False
    try:
        code_ok = type(output.code) is str
    except Exception:
        code_ok = False
    try:
        metadata = output.metadata
        metadata_ok = metadata is None or type(metadata) is dict
    except Exception:
        metadata_ok = False
    if not status_ok:
        failures.append(_failure(FAILURE_INVALID_STATUS, "status must be an exact str.", "status"))
    if not code_ok:
        failures.append(_failure(FAILURE_INVALID_CODE, "code must be an exact str.", "code"))
    if not metadata_ok:
        failures.append(_failure(FAILURE_INVALID_METADATA, "metadata must be None or an exact dict.", "metadata"))
    if failures:
        return WebRequestOutputValidationResult(_CREATE_TOKEN, None, failures)
    return WebRequestOutputValidationResult(_CREATE_TOKEN, output, ())
