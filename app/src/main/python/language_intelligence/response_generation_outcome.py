"""
Language Intelligence - Structured Response-Generation Outcome
====================================================================
Prompt 428. A small, additional structured view over an already-produced
`ResponseGenerationResult` (response_generation.py) that answers one
narrow question directly: did response generation SUCCEED, FALL BACK,
FAIL, or remain UNRESOLVED?

Why a new, separate class rather than a new status on the existing
`ResponseGenerationResult`
------------------------------------------------------------------------
`ResponseGenerationResult` already has six precise statuses
(STATUS_DEFERRED, STATUS_GENERATED, STATUS_NOT_IMPLEMENTED,
STATUS_MODEL_NOT_CONFIGURED, STATUS_MODEL_UNAVAILABLE,
STATUS_MODEL_FAILED - response_generation.py) that every existing
backend, `LanguageIntelligenceCore`, and every existing caller/test
already produces and branches on. Replacing or renaming them would be
exactly the "rewrite an existing system" this stage must not do; adding
a second, competing status vocabulary onto the SAME field would be the
"second, disagreeing system" this package's own conventions forbid (see
this package's __init__.py). Prompt 427 faced the identical naming
question for its own request object and answered it the same way this
module does: a distinctly-named, ADDITIVE, read-only structure built
FROM the existing result (`BackendGenerationRequest`, not a second
`ResponseGenerationRequest`) - never a replacement, never a second place
a caller must remember to keep in sync.

`ResponseGenerationOutcome` is that same shape of thing for the RESULT
side: `build_response_generation_outcome()` is a pure function of an
already-produced `ResponseGenerationResult` (response_generation.py -
whatever a backend, or `LanguageIntelligenceCore.generate_response()`,
already returned), plus the same `ResponseGenerationRequest`
(response_generation.py, Prompts 425-427) `generate_response()` was
called for, when a caller has one, for `language`/`locale`. It never
calls a backend, never runs inference, and never mutates the `result`
or `request` it is given.

The four statuses, and exactly how they are derived
------------------------------------------------------------------------
    STATUS_SUCCESS    `result.is_generated` (Prompt 413's own test -
                      status STATUS_GENERATED with a real, non-empty
                      `response_text`). `generated_text` carries that
                      text verbatim; `backend_kind` is the backend that
                      produced it; `fallback_used` is False.

    STATUS_FALLBACK   the result is a model failure
                      (`status in MODEL_FAILURE_STATUSES`) AND a
                      fallback backend has been marked as handling the
                      request instead (`result.fallback_backend_kind`
                      is not None - set by `LanguageIntelligenceCore`,
                      Prompt 406/414, exactly when a fallback backend is
                      configured and takes over for a failing or
                      not-ready primary). `fallback_used` is True;
                      `backend_kind` is that fallback backend's own
                      kind. `generated_text` is whatever `result.
                      response_text` actually carries - today, always
                      None, because neither Prompt 406's post-failure
                      marking nor Prompt 414's pre-call block ever
                      themselves calls the fallback backend's own
                      `generate_response()` (see response_generation.py's
                      own module docstring: the deterministic fallback
                      backend "deliberately does NOT generate reply text
                      itself"). This module never invents text to fill
                      that gap - it only ever reports what is already
                      there.

    STATUS_FAILED     the result is a model failure
                      (`status in MODEL_FAILURE_STATUSES`) and NO
                      fallback backend is available for it
                      (`result.fallback_backend_kind` is None) - a
                      genuine, unrecoverable failure as far as this
                      layer is concerned. `failure_reason` is a small,
                      structured dict of exactly what the underlying
                      result already carries (`error_code`,
                      `inference_status`, `reason`) - never a new
                      diagnosis, never a guess. `generated_text` stays
                      None: no response is ever invented for a failure.

    STATUS_UNRESOLVED  every other case: `STATUS_DEFERRED` (this
                      layer's own honest "I do not generate text; the
                      caller's existing pipeline does" -
                      response_generation.py) or `STATUS_NOT_IMPLEMENTED`.
                      The request remains unresolved as far as this
                      structured result is concerned - nothing is
                      guessed at, and `generated_text` / `failure_reason`
                      stay None.

These four are exhaustive and mutually exclusive over
`ResponseGenerationResult.ALL_STATUSES` - every existing status maps to
exactly one of them, and no fifth status is invented.

Preserved, never recomputed
------------------------------------------------------------------------
`backend_kind`, `metadata` (Prompt 399's own small, safe runtime
metadata - model id, runtime name, timing, token counts - copied
through unchanged) and, on SUCCESS, `generated_text` are read straight
from the `result` this module is given; on FALLBACK, `backend_kind`
names the fallback backend and `generated_text` is still read straight
from `result.response_text` (see STATUS_FALLBACK above). `language` /
`locale` are read, read-only, from the SAME `ResponseGenerationContext`
the `request` already exposes as `generation_context` (Prompt 426,
itself built from the `ResponsePlan` Prompts 425/421/401 already
produced) - never a second language/locale detector, and never
anything beyond what that existing, bounded bridge already carries.
With no `request` given (or a `request` with no `response_plan`
attached), `language`/`locale` are simply None - nothing is guessed.

Verified-correction usage (Prompt 499)
------------------------------------------------------------------------
`used_verified_correction` (bool, default False) exposes, on this final
structured result, whether the response-generation PREPARATION for
`request` actually used a verified corrected response target as its
input. The value is read straight from the existing preparation state -
the `used_verified_correction` flag `request.generation_request` already
carries (Prompt 498, set only where Prompt 497 substitutes the target) -
never inferred from whether a verified correction instruction, or any
other correction data, merely exists. With no `request` (or one with no
plan, hence no generation request) it is False. It is observability
only: `generated_text` and every other field are exactly what they were.
The existing `metadata` dict is deliberately NOT reused: it is the
underlying result's own runtime metadata (model id, timing, token counts;
None when no local model was involved) and is copied through unchanged.

No mutation
------------------------------------------------------------------------
This module only ever READS `result` and `request` - it never sets an
attribute on either, never mutates `result.metadata`, and never touches
`request.understanding` or `request.context`. Building an outcome for
the same `result`/`request` twice returns two independent objects; a
`ResponseGenerationOutcome`'s own `metadata` is a fresh, shallow copy
(same convention `ResponseGenerationResult.__init__` itself already
uses for `metadata`), so mutating one outcome's `metadata` dict can
never reach the underlying result's.

This module implements no natural-language generation itself, adds no
new backend, no new planning/context system and no new store; it is a
read-only summary layer over what Prompts 397-427 already produce. No
backend, `LanguageIntelligenceCore`, or existing `ResponseGenerationResult`
/ `ResponseGenerationRequest` field is changed by this module.

Normalized input (Prompt 611)
------------------------------------------------------------------------
`normalized_input` is read, read-only, from the SAME `request.
generation_context` dict `language`/`locale` above already come from
(Prompt 426's `ResponseGenerationContext`, itself forwarded verbatim
from `ResponsePlan.normalized_input` - Prompt 610 - which is itself
forwarded verbatim from `LanguageUnderstandingResult.normalized_input`
- Prompt 609). This module never normalizes, strips, collapses, or
otherwise transforms it again; it only reads the one value the
generation context already carries. With no `request` (or a `request`
with no `response_plan` attached, hence no generation context), it is
simply None - the SAME "no request means no value" posture
`language`/`locale` already use. `original_message` (the plan/context's
own separate, untouched field) is never read or reused here for this
purpose - it stays exactly what it already is, independent of
`normalized_input`.
"""

from .response_generation import (
    ResponseGenerationRequest,
    ResponseGenerationResult,
    MODEL_FAILURE_STATUSES,
)

STATUS_SUCCESS = "SUCCESS"
STATUS_FALLBACK = "FALLBACK"
STATUS_FAILED = "FAILED"
STATUS_UNRESOLVED = "UNRESOLVED"

ALL_OUTCOME_STATUSES = (STATUS_SUCCESS, STATUS_FALLBACK, STATUS_FAILED, STATUS_UNRESOLVED)


class ResponseGenerationOutcome:
    """Plain, JSON-shaped, read-only value - same `to_dict()` convention
    used throughout this package (`ResponseGenerationResult`,
    `ModelReadiness`, `BackendSelection`, ...). Never constructed
    directly by a caller other than `build_response_generation_outcome()`
    below.

        status           one of ALL_OUTCOME_STATUSES above.
        generated_text   the produced reply text, or None - see the
                         module docstring's per-status description.
                         Never fabricated: None on FAILED and
                         UNRESOLVED, and on FALLBACK whenever the
                         underlying result itself carries none.
        backend_kind     which backend this outcome is attributed to -
                         the backend that generated/attempted the
                         response (SUCCESS/FAILED/UNRESOLVED), or the
                         fallback backend that took over (FALLBACK).
        language         the preferred response language (Prompt 401,
                         via the request's `generation_context`,
                         Prompt 426), or None when no request/plan was
                         available to read it from.
        locale           likewise, the response locale, or None.
        failure_reason   a small structured dict
                         (`error_code`/`inference_status`/`reason`) on
                         FAILED, else None. Never a new diagnosis -
                         exactly what the underlying result already
                         carried.
        fallback_used    True exactly on FALLBACK, else False.
        metadata         the underlying result's own `metadata`
                         (Prompt 399), copied through unchanged, or
                         None.
        used_verified_correction
                         Prompt 499: True only when the request's
                         response-generation preparation actually used
                         a verified corrected response target (see the
                         module docstring); False otherwise (default).
        correction_application_result_usable
                         Prompt 577: True only when the
                         `LearnedResponseDecision`
                         (learned_response_decision.py, Prompt 437/576)
                         made alongside this outcome's underlying result
                         already says a verified correction application
                         result is usable - forwarded through exactly as
                         given, never recomputed here. False otherwise
                         (default): no decision available, a decision
                         built before Prompt 576, or the decision itself
                         says False.
        normalized_input
                         Prompt 611: the request's own `generation_context
                         ["normalized_input"]` (Prompt 426/610), forwarded
                         through unchanged - see the module docstring's
                         "Normalized input" section. None when there is
                         no request, no plan, or the context carries none.
                         Never normalized, stripped, collapsed, or
                         otherwise transformed here.
    """

    def __init__(self, status, generated_text=None, backend_kind=None, language=None,
                 locale=None, failure_reason=None, fallback_used=False, metadata=None,
                 used_verified_correction=False,
                 correction_application_result_usable=False,
                 normalized_input=None):
        if status not in ALL_OUTCOME_STATUSES:
            raise ValueError(f"status must be one of {list(ALL_OUTCOME_STATUSES)}")
        self.status = status
        self.generated_text = generated_text
        self.backend_kind = backend_kind
        self.language = language
        self.locale = locale
        self.failure_reason = dict(failure_reason) if failure_reason else None
        self.fallback_used = bool(fallback_used)
        self.metadata = dict(metadata) if metadata else None
        self.used_verified_correction = bool(used_verified_correction)
        self.correction_application_result_usable = bool(
            correction_application_result_usable)
        # Prompt 611: additive, defaults to None for legacy direct
        # construction - forwarded verbatim, never derived or
        # re-normalized here. See module docstring's "Normalized input"
        # section.
        self.normalized_input = normalized_input

    @property
    def succeeded(self):
        return self.status == STATUS_SUCCESS

    @property
    def failed(self):
        return self.status == STATUS_FAILED

    @property
    def unresolved(self):
        return self.status == STATUS_UNRESOLVED

    def __repr__(self):
        return (
            f"ResponseGenerationOutcome(status={self.status!r}, "
            f"backend_kind={self.backend_kind!r}, fallback_used={self.fallback_used})"
        )

    def to_dict(self):
        return {
            "status": self.status,
            "generated_text": self.generated_text,
            "backend_kind": self.backend_kind,
            "language": self.language,
            "locale": self.locale,
            "failure_reason": dict(self.failure_reason) if self.failure_reason else None,
            "fallback_used": self.fallback_used,
            "metadata": dict(self.metadata) if self.metadata else None,
            "used_verified_correction": self.used_verified_correction,
            "correction_application_result_usable":
                self.correction_application_result_usable,
            # Prompt 611: forwarded verbatim - see the module docstring.
            "normalized_input": self.normalized_input,
        }


def _structured_failure_reason(result):
    """A small, structured summary of exactly what `result` (a model
    failure) already carries - never a new diagnosis. None only when
    the result carries no error code, inference status, or reason at
    all (should not happen for a real model failure, but never assumed)."""
    if result.error_code is None and result.inference_status is None and not result.reason:
        return None
    return {
        "error_code": result.error_code,
        "inference_status": result.inference_status,
        "reason": result.reason or None,
    }


def _language_and_locale(request):
    """Read-only: `(language, locale)` from `request.generation_context`
    (Prompt 426, itself a deep copy - reading it can never mutate
    `request` or anything it was built from). `(None, None)` when there
    is no request, or no plan was available to build a context from."""
    if request is None:
        return None, None
    context = request.generation_context
    if context is None:
        return None, None
    return context.get("language"), context.get("locale")


def _normalized_input(request):
    """Prompt 611: read-only - `generation_context["normalized_input"]`
    (Prompt 426/610), the SAME dict `_language_and_locale` above already
    reads from. `None` when there is no request, or no plan was
    available to build a context from - the SAME "no request means no
    value" posture `_language_and_locale` already uses. Never
    normalizes, strips, collapses, or otherwise transforms the value."""
    if request is None:
        return None
    context = request.generation_context
    if context is None:
        return None
    return context.get("normalized_input")


def _used_verified_correction(request):
    """Prompt 499: read-only - the `used_verified_correction` flag from
    the request's own preparation state (`request.generation_request`,
    Prompt 498), False when there is no request or no generation
    request. Only an actual True counts; never inferred from the mere
    presence of correction data."""
    if request is None:
        return False
    generated = request.generation_request
    if generated is None:
        return False
    return generated.get("used_verified_correction") is True


def build_response_generation_outcome(result, request=None,
                                       correction_application_result_usable=False):
    """Build a `ResponseGenerationOutcome` from an already-produced
    `ResponseGenerationResult` (`result` - whatever a backend's
    `generate_response()`, or `LanguageIntelligenceCore.
    generate_response()`, already returned) and, optionally, the
    `ResponseGenerationRequest` (`request`) it was produced for - used
    only to read `language`/`locale` and (Prompt 499) the request's
    `used_verified_correction` preparation state (see the module
    docstring).

    `correction_application_result_usable` (Prompt 577, optional, default
    False): forwarded straight through onto the returned outcome (see
    `ResponseGenerationOutcome.correction_application_result_usable`)
    unchanged - this function never reads it from anywhere else and
    never derives it itself. The caller (`LanguageIntelligenceCore`)
    already has it on the `LearnedResponseDecision` it made for the SAME
    understanding/result (Prompt 437/576); passing it in here is the
    only thing this parameter does.

    Pure and read-only: never calls a backend, never runs inference,
    never mutates `result` or `request`. Raises TypeError for a `result`
    that is not a `ResponseGenerationResult`, or a `request` that is
    neither `None` nor a `ResponseGenerationRequest` - the same
    "describe what was already produced, do not guess" posture as every
    other bridge in this package."""
    if not isinstance(result, ResponseGenerationResult):
        raise TypeError("result must be a ResponseGenerationResult")
    if request is not None and not isinstance(request, ResponseGenerationRequest):
        raise TypeError("request must be a ResponseGenerationRequest or None")

    language, locale = _language_and_locale(request)
    metadata = result.metadata
    used_correction = _used_verified_correction(request)
    correction_usable = bool(correction_application_result_usable)
    # Prompt 611: forwarded verbatim from the SAME request generation
    # context language/locale already come from - never recomputed.
    normalized_input = _normalized_input(request)

    if result.is_generated:
        return ResponseGenerationOutcome(
            STATUS_SUCCESS, generated_text=result.response_text, backend_kind=result.backend_kind,
            language=language, locale=locale, failure_reason=None, fallback_used=False,
            metadata=metadata, used_verified_correction=used_correction,
            correction_application_result_usable=correction_usable,
            normalized_input=normalized_input,
        )

    if result.status in MODEL_FAILURE_STATUSES:
        if result.fallback_backend_kind is not None:
            return ResponseGenerationOutcome(
                STATUS_FALLBACK, generated_text=result.response_text,
                backend_kind=result.fallback_backend_kind, language=language, locale=locale,
                failure_reason=None, fallback_used=True, metadata=metadata,
                used_verified_correction=used_correction,
                correction_application_result_usable=correction_usable,
                normalized_input=normalized_input,
            )
        return ResponseGenerationOutcome(
            STATUS_FAILED, generated_text=None, backend_kind=result.backend_kind,
            language=language, locale=locale, failure_reason=_structured_failure_reason(result),
            fallback_used=False, metadata=metadata,
            used_verified_correction=used_correction,
            correction_application_result_usable=correction_usable,
            normalized_input=normalized_input,
        )

    return ResponseGenerationOutcome(
        STATUS_UNRESOLVED, generated_text=None, backend_kind=result.backend_kind,
        language=language, locale=locale, failure_reason=None, fallback_used=False,
        metadata=metadata, used_verified_correction=used_correction,
        correction_application_result_usable=correction_usable,
        normalized_input=normalized_input,
    )
