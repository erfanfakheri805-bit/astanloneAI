"""
Audio Operation Output Validator (Prompt 766, Section 8 - Multimedia)
=====================================================================
A small deterministic validator that checks whether an `AudioOperationOutput` (Prompt 765) matches an `AudioOperationPlan` (Prompt 763). It only
compares metadata values; it performs no audio processing, reads no audio data and touches no file. It mirrors `validate_image_operation_output()`
(Prompt 753) as a separate, unrelated audio function.

    validate_audio_operation_output(plan, output) -> AudioOperationOutputValidationResult(ok, plan, output, failures)

ORDER
1. `plan` must be exactly an `AudioOperationPlan`   -> else AUDIO_OPERATION_OUTPUT_VALIDATION_INVALID_PLAN. The result holds plan=None and
   output=None, and `output` is not examined or cross-validated (a valid output is NOT retained).
2. `output` must be exactly an `AudioOperationOutput` -> else AUDIO_OPERATION_OUTPUT_VALIDATION_INVALID_OUTPUT. The result keeps the exact valid
   plan and output=None. No cross-validation is done.
3. Otherwise these pairs are compared, always in this fixed order, and every mismatch is reported:
       output.audio_id      == plan.audio_id        AUDIO_ID_MISMATCH
       output.operation     == plan.operation       OPERATION_MISMATCH
       output.output_format == plan.target_format    FORMAT_MISMATCH
       output.duration_ms   == plan.duration_ms     DURATION_MS_MISMATCH
       output.sample_rate   == plan.sample_rate     SAMPLE_RATE_MISMATCH
4. `quality` exists only on the plan; the output model does not represent it, so it is neither validated nor inferred.
5. All five equal -> `ok=True`.

EXACT COMPARISON
Values are compared exactly (`==` on the documented fields): never trimmed, case-folded, coerced or converted, so "WAV" != "wav" and " a" != "a".
Object identity is never the criterion: two different but equal objects match.

RESULT
For valid supplied objects the result holds the very same objects (identity preserved), also when mismatches are reported. A top-level invalid
input is never retained (see ORDER). `failures` is a tuple of fresh `{"code", "field", "message"}` dicts; `codes()` and `to_dict()` return fresh
data. The result is immutable (`__slots__`, read-only), cannot be built directly or subclassed (`TypeError`), compares and hashes by value (exact
type only), returns itself from copy/deepcopy and refuses pickling. The validator never raises for bad inputs and mutates neither input.

WHAT THIS MODULE DOES NOT DO
No audio processing, decoding or encoding, no filesystem, network, database, AI model or external service, no clock or randomness, no
module-level mutable state. Its only imports are the Prompt 763 plan type and the Prompt 765 output type. Not wired into `process_input()`,
Core, the Planner, the Agent Loop, the Prompt 764 executor or Section 7.
"""

from .audio_operation_output import AudioOperationOutput
from .audio_operation_plan import AudioOperationPlan

_PREFIX = "AUDIO_OPERATION_OUTPUT_VALIDATION_"
FAILURE_INVALID_PLAN = _PREFIX + "INVALID_PLAN"
FAILURE_INVALID_OUTPUT = _PREFIX + "INVALID_OUTPUT"
FAILURE_AUDIO_ID_MISMATCH = _PREFIX + "AUDIO_ID_MISMATCH"
FAILURE_OPERATION_MISMATCH = _PREFIX + "OPERATION_MISMATCH"
FAILURE_FORMAT_MISMATCH = _PREFIX + "FORMAT_MISMATCH"
FAILURE_DURATION_MS_MISMATCH = _PREFIX + "DURATION_MS_MISMATCH"
FAILURE_SAMPLE_RATE_MISMATCH = _PREFIX + "SAMPLE_RATE_MISMATCH"
FAILURE_CODES = (FAILURE_INVALID_PLAN, FAILURE_INVALID_OUTPUT, FAILURE_AUDIO_ID_MISMATCH, FAILURE_OPERATION_MISMATCH,
                 FAILURE_FORMAT_MISMATCH, FAILURE_DURATION_MS_MISMATCH, FAILURE_SAMPLE_RATE_MISMATCH)

# (code, plan attribute, output attribute) in the fixed comparison order.
COMPARISONS = (
    (FAILURE_AUDIO_ID_MISMATCH, "audio_id", "audio_id"),
    (FAILURE_OPERATION_MISMATCH, "operation", "operation"),
    (FAILURE_FORMAT_MISMATCH, "target_format", "output_format"),
    (FAILURE_DURATION_MS_MISMATCH, "duration_ms", "duration_ms"),
    (FAILURE_SAMPLE_RATE_MISMATCH, "sample_rate", "sample_rate"),
)

_CREATE_TOKEN = object()


def _failure(code, field, message):
    return (code, field, message)


class AudioOperationOutputValidationResult:
    """Immutable outcome of `validate_audio_operation_output()`. Obtain it only from that function."""

    __slots__ = ("_plan", "_output", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("AudioOperationOutputValidationResult cannot be subclassed.")

    def __init__(self, _token, plan, output, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use validate_audio_operation_output() to obtain an AudioOperationOutputValidationResult.")
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_output", output)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("AudioOperationOutputValidationResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("AudioOperationOutputValidationResult is immutable.")

    @property
    def ok(self):
        return not self._failures

    @property
    def plan(self):
        return self._plan

    @property
    def output(self):
        return self._output

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "plan", "output", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok,
                "plan": self._plan.to_dict() if self._plan is not None else None,
                "output": self._output.to_dict() if self._output is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._plan, self._output, self._failures)

    def __eq__(self, other):
        if type(other) is not AudioOperationOutputValidationResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("AudioOperationOutputValidationResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "AudioOperationOutputValidationResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def validate_audio_operation_output(plan, output):
    """Check that `output` (exact AudioOperationOutput) matches `plan` (exact AudioOperationPlan), comparing exact field values only.
    Deterministic, never raises for bad inputs, mutates neither input. Returns an `AudioOperationOutputValidationResult`."""
    if type(plan) is not AudioOperationPlan:
        return AudioOperationOutputValidationResult(
            _CREATE_TOKEN, None, None, [_failure(FAILURE_INVALID_PLAN, "plan", "plan must be exactly an AudioOperationPlan.")])
    if type(output) is not AudioOperationOutput:
        return AudioOperationOutputValidationResult(
            _CREATE_TOKEN, plan, None, [_failure(FAILURE_INVALID_OUTPUT, "output", "output must be exactly an AudioOperationOutput.")])
    failures = []
    for code, plan_attr, output_attr in COMPARISONS:
        expected = getattr(plan, plan_attr)
        actual = getattr(output, output_attr)
        if actual != expected:
            failures.append(_failure(code, output_attr, "output.%s %r does not match plan.%s %r." % (output_attr, actual, plan_attr, expected)))
    return AudioOperationOutputValidationResult(_CREATE_TOKEN, plan, output, failures)
