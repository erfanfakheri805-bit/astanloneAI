"""
Image Operation Pipeline (Prompt 756, Section 8 - Multimedia)
=============================================================
One small deterministic pipeline that connects the existing image-operation contracts. It adds no image-operation semantics of its own; every
decision is taken by the public function of an earlier prompt, and this module only chains them and reports what happened.

    process_image_operation(request, image_registry) -> ImageOperationPipelineResult(ok, request, plan, dispatch_result, output_validation, failures)

    request -> registry validation -> plan creation -> dispatch -> output validation
               (Prompt 749)           (Prompt 750)     (Prompt 755)  (Prompt 753)

STAGES (in order; the first stage that fails stops the pipeline)
1. `validate_image_operation_request(request, image_registry)`. On failure: ok=False, plan / dispatch_result / output_validation are None, and no
   plan is created and nothing is dispatched. `request` holds the request object only when it was a valid `ImageOperationRequest` (the exact
   object that was passed in, also when the image was not found); an invalid request input is never stored.
2. `create_image_operation_plan(validation_result)`. On failure: ok=False, dispatch_result and output_validation are None.
3. `dispatch_image_operation(plan)`. The exact plan and the exact dispatch result are always kept. If the dispatch did not succeed (no output exists)
   ok=False and output validation is NOT attempted.
4. `validate_image_operation_output(plan, output)` with the output held by the dispatched metadata result. The exact validation result is kept.
   ok=True only when the dispatch succeeded AND the output validation succeeded.

Every held object is the very object the earlier public function returned (identity preserved, nothing is copied or rebuilt).

FAILURE CODES (only these six; prefix IMAGE_OPERATION_PIPELINE_)
    INVALID_REQUEST            the request validation reported IMAGE_OPERATION_VALIDATION_INVALID_REQUEST
    INVALID_REGISTRY           the request validation reported IMAGE_OPERATION_VALIDATION_INVALID_IMAGE_REGISTRY
    VALIDATION_FAILED          any other request-validation failure (e.g. IMAGE_NOT_FOUND)
    PLAN_FAILED                the plan could not be created
    DISPATCH_FAILED            the dispatch (or the executor result it holds) did not succeed
    OUTPUT_VALIDATION_FAILED   the dispatched output did not match the plan
Each failure is a fresh `{"code", "field", "message"}` dict. There is one pipeline failure per failure reported by the stage that failed, in that
stage's order, so the original codes are exposed: the exact upstream code is quoted in the message as "[<upstream code>]" and nothing is dropped
or re-ordered. Upstream codes are never invented, renamed or hidden; the failing stage's own result stays available (`dispatch_result`,
`output_validation`) for full detail.

RESULT
`ImageOperationPipelineResult` is immutable (`__slots__`, read-only), cannot be built directly or subclassed (`TypeError`), compares and hashes
by value (exact type only), returns itself from copy/deepcopy and refuses pickling (like the other multimedia results). `failures`, `codes()`
and `to_dict()` ({"ok", "request", "plan", "dispatch_result", "output_validation", "failures"}, each held object as its own `to_dict()`) are fresh
on every call. The function never raises for bad inputs, mutates nothing it is given and is deterministic.

WHAT THIS MODULE DOES NOT DO
No image processing, decoding or pixels, no automatic operation selection (the dispatcher only knows "metadata"), no filesystem, network,
database, AI model or external service, no clock or randomness, no module-level mutable state. It re-implements none of the checks of Prompts
748-755. Not wired into `process_input()`, Core, the Planner, the Agent Loop or Section 7.
"""

from .image_operation_dispatcher import dispatch_image_operation
from .image_operation_output_validator import validate_image_operation_output
from .image_operation_plan import ImageOperationPlan, create_image_operation_plan
from .image_operation_validator import FAILURE_INVALID_IMAGE_REGISTRY, FAILURE_INVALID_REQUEST, validate_image_operation_request

_PREFIX = "IMAGE_OPERATION_PIPELINE_"
FAILURE_PIPELINE_INVALID_REQUEST = _PREFIX + "INVALID_REQUEST"
FAILURE_PIPELINE_INVALID_REGISTRY = _PREFIX + "INVALID_REGISTRY"
FAILURE_PIPELINE_VALIDATION_FAILED = _PREFIX + "VALIDATION_FAILED"
FAILURE_PIPELINE_PLAN_FAILED = _PREFIX + "PLAN_FAILED"
FAILURE_PIPELINE_DISPATCH_FAILED = _PREFIX + "DISPATCH_FAILED"
FAILURE_PIPELINE_OUTPUT_VALIDATION_FAILED = _PREFIX + "OUTPUT_VALIDATION_FAILED"
FAILURE_CODES = (FAILURE_PIPELINE_INVALID_REQUEST, FAILURE_PIPELINE_INVALID_REGISTRY, FAILURE_PIPELINE_VALIDATION_FAILED,
                 FAILURE_PIPELINE_PLAN_FAILED, FAILURE_PIPELINE_DISPATCH_FAILED, FAILURE_PIPELINE_OUTPUT_VALIDATION_FAILED)

_CREATE_TOKEN = object()


def _failure(code, field, message):
    return (code, field, message)


class ImageOperationPipelineResult:
    """Immutable outcome of `process_image_operation()`. Obtain it only from that function."""

    __slots__ = ("_request", "_plan", "_dispatch_result", "_output_validation", "_failures")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("ImageOperationPipelineResult cannot be subclassed.")

    def __init__(self, _token, request, plan, dispatch_result, output_validation, failures):
        if _token is not _CREATE_TOKEN:
            raise TypeError("Use process_image_operation() to obtain an ImageOperationPipelineResult.")
        object.__setattr__(self, "_request", request)
        object.__setattr__(self, "_plan", plan)
        object.__setattr__(self, "_dispatch_result", dispatch_result)
        object.__setattr__(self, "_output_validation", output_validation)
        object.__setattr__(self, "_failures", tuple(failures))

    def __setattr__(self, key, value):
        raise AttributeError("ImageOperationPipelineResult is immutable.")

    def __delattr__(self, key):
        raise AttributeError("ImageOperationPipelineResult is immutable.")

    @property
    def ok(self):
        """True only when the dispatch succeeded and the output validation succeeded."""
        return (not self._failures and self._dispatch_result is not None and self._dispatch_result.ok
                and self._output_validation is not None and self._output_validation.ok)

    @property
    def request(self):
        """The exact `ImageOperationRequest` that was passed in when it was a valid one, otherwise None."""
        return self._request

    @property
    def plan(self):
        """The exact plan the pipeline created, or None when no plan was created."""
        return self._plan

    @property
    def dispatch_result(self):
        """The exact `ImageOperationDispatchResult`, or None when nothing was dispatched."""
        return self._dispatch_result

    @property
    def output_validation(self):
        """The exact `ImageOperationOutputValidationResult`, or None when no output was validated."""
        return self._output_validation

    @property
    def failures(self):
        """Tuple of fresh `{"code", "field", "message"}` dicts; mutating them never affects this result."""
        return tuple({"code": c, "field": f, "message": m} for c, f, m in self._failures)

    def codes(self):
        return [c for c, _f, _m in self._failures]

    def to_dict(self):
        """Fresh plain data: {"ok", "request", "plan", "dispatch_result", "output_validation", "failures"}. Mutating it never affects this result."""
        return {"ok": self.ok,
                "request": self._request.to_dict() if self._request is not None else None,
                "plan": self._plan.to_dict() if self._plan is not None else None,
                "dispatch_result": self._dispatch_result.to_dict() if self._dispatch_result is not None else None,
                "output_validation": self._output_validation.to_dict() if self._output_validation is not None else None,
                "failures": [{"code": c, "field": f, "message": m} for c, f, m in self._failures]}

    def _key(self):
        return (self._request, self._plan, self._dispatch_result, self._output_validation, self._failures)

    def __eq__(self, other):
        if type(other) is not ImageOperationPipelineResult:
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("ImageOperationPipelineResult is not pickled; use to_dict() to serialize it.")

    def __repr__(self):
        return "ImageOperationPipelineResult(ok=%r, codes=%r)" % (self.ok, self.codes())


def _wrap(code, field, stage, upstream):
    """One pipeline failure per upstream failure (stage order kept); the upstream code is quoted in the message."""
    return [_failure(code, field, "%s failed [%s]." % (stage, u)) for u in upstream] or [
        _failure(code, field, "%s failed." % stage)]


def process_image_operation(request, image_registry):
    """Run request -> registry validation -> plan -> dispatch -> output validation using the public functions of Prompts 749, 750, 755 and 753.
    Deterministic, never raises for bad inputs, mutates nothing it is given. Returns an `ImageOperationPipelineResult`."""
    validation = validate_image_operation_request(request, image_registry)
    if not validation.ok:
        mapped = {FAILURE_INVALID_REQUEST: FAILURE_PIPELINE_INVALID_REQUEST, FAILURE_INVALID_IMAGE_REGISTRY: FAILURE_PIPELINE_INVALID_REGISTRY}
        failures = [_failure(mapped.get(f["code"], FAILURE_PIPELINE_VALIDATION_FAILED), f["field"],
                             "Request validation failed [%s]." % f["code"]) for f in validation.failures]
        if not failures:
            failures = [_failure(FAILURE_PIPELINE_VALIDATION_FAILED, "request", "Request validation failed.")]
        return ImageOperationPipelineResult(_CREATE_TOKEN, validation.request, None, None, None, failures)

    request = validation.request
    plan_result = create_image_operation_plan(validation)
    plan = plan_result.plan
    if not plan_result.ok or type(plan) is not ImageOperationPlan:
        return ImageOperationPipelineResult(_CREATE_TOKEN, request, None, None, None,
                                            _wrap(FAILURE_PIPELINE_PLAN_FAILED, "plan", "Plan creation", plan_result.codes()))

    dispatch = dispatch_image_operation(plan)
    output = dispatch.result.output if dispatch.result is not None else None
    if not dispatch.ok or output is None:
        upstream = dispatch.codes() + (dispatch.result.codes() if dispatch.result is not None else [])
        return ImageOperationPipelineResult(_CREATE_TOKEN, request, plan, dispatch, None,
                                            _wrap(FAILURE_PIPELINE_DISPATCH_FAILED, "dispatch_result", "Dispatch", upstream))

    output_validation = validate_image_operation_output(plan, output)
    if not output_validation.ok:
        return ImageOperationPipelineResult(_CREATE_TOKEN, request, plan, dispatch, output_validation,
                                            _wrap(FAILURE_PIPELINE_OUTPUT_VALIDATION_FAILED, "output_validation", "Output validation",
                                                  output_validation.codes()))
    return ImageOperationPipelineResult(_CREATE_TOKEN, request, plan, dispatch, output_validation, ())
