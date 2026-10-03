"""
Image Operation Output Validator (Prompt 753, Section 8 - Multimedia)
=====================================================================
A small deterministic validator that checks whether an `ImageOperationOutput` (Prompt 752) matches an `ImageOperationPlan` (Prompt 750). It only
compares metadata values; it performs no image processing, reads no image bytes and touches no file.

    validate_image_operation_output(plan, output) -> ImageOperationOutputValidationResult(ok, plan, output, failures)

ORDER
1. `plan` must be exactly an `ImageOperationPlan`            -> else IMAGE_OPERATION_OUTPUT_VALIDATION_INVALID_PLAN
2. `output` must be exactly an `ImageOperationOutput`        -> else IMAGE_OPERATION_OUTPUT_VALIDATION_INVALID_OUTPUT
3. If either top-level input is invalid, NO cross-validation is done (both top-level problems are still reported, plan first).
4. Otherwise these pairs are compared, always in this fixed order, and every mismatch is reported:
       output.image_id      == plan.image_id        IMAGE_ID_MISMATCH
       output.operation     == plan.operation       OPERATION_MISMATCH
       output.output_format == plan.target_format   FORMAT_MISMATCH
       output.width         == plan.width           WIDTH_MISMATCH
       output.height        == plan.height          HEIGHT_MISMATCH
5. `quality` exists only on the plan; the output model does not represent it, so it is neither validated nor inferred.
6. All five equal -> `ok=True` and the result holds the very same plan and output objects (identity preserved).

EXACT COMPARISON
Values are compared exactly (`==` on the documented fields): never trimmed, case-folded, coerced or converted, so "WEBP" != "webp" and
" hero" != "hero". Object identity is never the criterion: two different but equal objects match.

RESULT
`plan` / `output` hold the supplied object when it is of the exact expected type (also when a mismatch is reported) and None when that
top-level input was invalid. `failures` is a tuple of fresh `{"code", "field", "message"}` dicts; `codes()` and `to_dict()` return fresh data.
The result is immutable (`__slots__`, read-only), cannot be built directly or subclassed (`TypeError`), compares and hashes by value
(exact type only), returns itself from copy/deepcopy and refuses pickling. The validator never raises for bad inputs and mutates neither input.

WHAT THIS MODULE DOES NOT DO
No image processing or decoding, no filesystem, network, database, AI model or external service, no clock or randomness, no module-level
mutable state. Its only imports are the Prompt 750 plan type and the Prompt 752 output type. Not wired into `process_input()`, Core, the
Planner, the Agent Loop, the Prompt 751 executor or Section 7.
"""

from .image_operation_output import ImageOperationOutput
from .image_operation_plan import ImageOperationPlan

_PREFIX = "IMAGE_OPERATION_OUTPUT_VALIDATION_"
FAILURE_INVALID_PLAN = _PREFIX + "INVALID_PLAN"
FAILURE_INVALID_OUTPUT = _PREFIX + "INVALID_OUTPUT"
FAILURE_IMAGE_ID_MISMATCH = _PREFIX + "IMAGE_ID_MISMATCH"
FAILURE_OPERATION_MISMATCH = _PREFIX + "OPERATION_MISMATCH"
FAILURE_FORMAT_MISMATCH = _PREFIX + "FORMAT_MISMATCH"
FAILURE_WIDTH_MISMATCH = _PREFIX + "WIDTH_MISMATCH"
FAILURE_HEIGHT_MISMATCH = _PREFIX + "HEIGHT_MISMATCH"
FAILURE_CODES = (FAILURE_INVALID_PLAN, FAILURE_INVALID_OUTPUT, FAILURE_IMAGE_ID_MISMATCH, FAILURE_OPERATION_MISMATCH,
                 FAILURE_FORMAT_MISMATCH, FAILURE_WIDTH_MISMATCH, FAILURE_HEIGHT_MISMATCH)

# (code, plan attribute, output attribute) in the fixed comparison order.
COMPARISONS = (
    (FAILURE_IMAGE_ID_MISMATCH, "image_id", "image_id"),
    (FAILURE_OPERATION_MISMATCH, "operation", "operation"),
    (FAILURE_FORMAT_MISMATCH, "target_format", "output_format"),
    (FAILURE_WIDTH_MISMATCH, "width", "width"),
    (FAILURE_HEIGHT_MISMATCH, "height", "height"),
)

_CREATE_TOKEN = object()


def _failure(code, field, message):
    return (code, field, message)


class ImageOperationOutputValidationResult:
    """Immutable outcome of `validate_image_operation_output()`. Obtain it only from that function."""

    __slots__ = ("_plan", "_output", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationOutputValidationResult cannot be subclassed.")

    def __init__(self, _token, plan, output, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use validate_image_operation_output() to obtain an ImageOperationOutputValidationResult.")
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_output", output)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationOutputValidationResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationOutputValidationResult is immutable.")

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
        if type(other) is not ImageOperationOutputValidationResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationOutputValidationResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationOutputValidationResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def validate_image_operation_output(plan, output):
    """Check that `output` (exact ImageOperationOutput) matches `plan` (exact ImageOperationPlan), comparing exact field values only.
    Deterministic, never raises for bad inputs, mutates neither input. Returns an `ImageOperationOutputValidationResult`."""
    plan_ok = type(plan) is ImageOperationPlan
    output_ok = type(output) is ImageOperationOutput
    failures = []
    if not plan_ok:
        failures.append(_failure(FAILURE_INVALID_PLAN, "plan", "plan must be exactly an ImageOperationPlan."))
    if not output_ok:
        failures.append(_failure(FAILURE_INVALID_OUTPUT, "output", "output must be exactly an ImageOperationOutput."))
    held_plan = plan if plan_ok else None
    held_output = output if output_ok else None
    if failures:
        return ImageOperationOutputValidationResult(_CREATE_TOKEN, held_plan, held_output, failures)
    for code, plan_attr, output_attr in COMPARISONS:
        expected = getattr(plan, plan_attr)
        actual = getattr(output, output_attr)
        if actual != expected:
            failures.append(_failure(code, output_attr, "output.%s %r does not match plan.%s %r." % (output_attr, actual, plan_attr, expected)))
    return ImageOperationOutputValidationResult(_CREATE_TOKEN, held_plan, held_output, failures)
