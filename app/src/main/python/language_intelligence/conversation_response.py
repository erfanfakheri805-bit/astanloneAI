"""
Language Intelligence - Unified Conversation Response
====================================================================
Prompt 431. `ConversationResponse` is the one small, immutable value a
higher-level caller can consume for the final conversational response
without knowing anything about ResponseGeneration internals (backends,
runtimes, the six `ResponseGenerationResult` statuses, ...).

It is NOT a new generation system and NOT a second result model: it is a
read-only, copied view built deterministically from what already exists -
the `ResponseGenerationResult` (response_generation.py) a backend or
`LanguageIntelligenceCore.generate_response()` returned, its Prompt 428
`ResponseGenerationOutcome` (the four statuses SUCCESS / FALLBACK / FAILED
/ UNRESOLVED, language/locale, failure reason, fallback_used) and its
Prompt 430 `ResponseGenerationValidation`. No project abstraction for a
final conversational response existed before, so nothing was extended or
duplicated; the outcome remains the internal derivation step and this class
is its stable, immutable public face.

    ResponseGenerationResult -> ResponseGenerationOutcome (+ validation)
                             -> ConversationResponse

`build_conversation_response(result, request=None)` is pure and
deterministic: no backend call, no inference, no network, no text is ever
written. `response_text` is exactly what the outcome carries - None for
FAILED and UNRESOLVED, and for a FALLBACK whose result carries none. A
result that Prompt 430 validation reports INVALID (e.g. a STATUS_GENERATED
result with no text) keeps its honest status (never promoted to SUCCESS)
and is marked `valid=False` with the validation's issue codes.

Fields
------------------------------------------------------------------------
    response_text, status, language, locale, backend_kind, fallback_used,
    failure_reason, metadata       the Prompt 428 outcome's own values
    valid, validation_issues       Prompt 430 validation (issue codes)
    generation_status, reason, generation_backend_kind,
    fallback_backend_kind, selected_backend_kind, inference_status,
    error_code                     straight copies of the underlying
                                   `ResponseGenerationResult` fields, so
                                   nothing it carried is lost
                                   (`backend_kind` is the backend the
                                   response is attributed to - the
                                   fallback backend on FALLBACK -
                                   `generation_backend_kind` is the one
                                   that produced/attempted the result).
    correction_application_result_usable
                                   Prompt 578: the Prompt 428 outcome's
                                   own `correction_application_result_usable`
                                   (itself Prompt 577, forwarded from
                                   `LearnedResponseDecision`/Prompt 576),
                                   copied through unchanged. False by
                                   default (no outcome, or a legacy
                                   outcome built before Prompt 577).
    normalized_input               Prompt 612: the Prompt 428 outcome's
                                   own `normalized_input` (itself Prompt
                                   611, forwarded from Prompt 426's
                                   `ResponseGenerationContext.
                                   normalized_input` - Prompt 610 - which
                                   is itself forwarded verbatim from
                                   `LanguageUnderstandingResult.
                                   normalized_input`, Prompt 609), copied
                                   through unchanged - never normalized,
                                   stripped, collapsed, or otherwise
                                   transformed again here. None by
                                   default (no outcome, or a legacy
                                   outcome built before Prompt 611).
                                   Kept independent of `response_text`
                                   and of the underlying request's own
                                   `original_message`/`original_input` -
                                   neither is read or reused for this
                                   field.

Classification (Prompt 432)
------------------------------------------------------------------------
`classification` is NORMAL / FALLBACK / FAILURE / UNRESOLVED, derived from
`status` alone (SUCCESS -> NORMAL, FALLBACK -> FALLBACK, FAILED -> FAILURE,
UNRESOLVED -> UNRESOLVED) by `classify_status()`. It is always computed from
`status` in the constructor - never passed in, so it can never disagree with
it - and `status` and every other field are unchanged.

Immutability
------------------------------------------------------------------------
Attributes cannot be set or deleted after construction. `metadata` and
`failure_reason` are read-only mappings over deep copies, and
`validation_issues` is a tuple of codes, so a caller can never reach the
core's `ResponseGenerationResult` / outcome / validation state through it;
`to_dict()` returns fresh copies each call.
"""

import copy
from types import MappingProxyType

from .response_generation import ResponseGenerationRequest, ResponseGenerationResult
from .response_generation_outcome import (
    build_response_generation_outcome,
    STATUS_SUCCESS, STATUS_FALLBACK, STATUS_FAILED, STATUS_UNRESOLVED,
)
from .response_generation_validation import validate_response_generation_result


# Prompt 432: a convenience classification of `status`, for higher-level
# consumers. Not a second status system: it is a fixed, one-to-one function
# of the existing `status` and never changes or reinterprets it.
CLASSIFICATION_NORMAL = "NORMAL"
CLASSIFICATION_FALLBACK = "FALLBACK"
CLASSIFICATION_FAILURE = "FAILURE"
CLASSIFICATION_UNRESOLVED = "UNRESOLVED"

ALL_CLASSIFICATIONS = (
    CLASSIFICATION_NORMAL, CLASSIFICATION_FALLBACK, CLASSIFICATION_FAILURE,
    CLASSIFICATION_UNRESOLVED,
)

_CLASSIFICATION_BY_STATUS = {
    STATUS_SUCCESS: CLASSIFICATION_NORMAL,
    STATUS_FALLBACK: CLASSIFICATION_FALLBACK,
    STATUS_FAILED: CLASSIFICATION_FAILURE,
    STATUS_UNRESOLVED: CLASSIFICATION_UNRESOLVED,
}


def classify_status(status):
    """The classification for a Prompt 428 outcome status (SUCCESS ->
    NORMAL, FALLBACK -> FALLBACK, FAILED -> FAILURE, UNRESOLVED ->
    UNRESOLVED); None for anything else. Pure lookup."""
    return _CLASSIFICATION_BY_STATUS.get(status)


def _frozen_mapping(value):
    return MappingProxyType(copy.deepcopy(dict(value))) if value else None


def _plain(value):
    return copy.deepcopy(dict(value)) if value else None


class ConversationResponse:
    _FIELDS = (
        "response_text", "status", "language", "locale", "backend_kind", "fallback_used",
        "failure_reason", "metadata", "valid", "validation_issues", "generation_status",
        "reason", "generation_backend_kind", "fallback_backend_kind", "selected_backend_kind",
        "inference_status", "error_code",
        "classification",
        "correction_application_result_usable",
        "normalized_input",
    )
    __slots__ = _FIELDS

    def __init__(self, response_text=None, status=None, language=None, locale=None,
                 backend_kind=None, fallback_used=False, failure_reason=None, metadata=None,
                 valid=True, validation_issues=(), generation_status=None, reason="",
                 generation_backend_kind=None, fallback_backend_kind=None,
                 selected_backend_kind=None, inference_status=None, error_code=None,
                 correction_application_result_usable=False, normalized_input=None):
        values = {
            "response_text": response_text, "status": status, "language": language,
            "locale": locale, "backend_kind": backend_kind, "fallback_used": bool(fallback_used),
            "failure_reason": _frozen_mapping(failure_reason), "metadata": _frozen_mapping(metadata),
            "valid": bool(valid), "validation_issues": tuple(validation_issues),
            "generation_status": generation_status, "reason": reason,
            "generation_backend_kind": generation_backend_kind,
            "fallback_backend_kind": fallback_backend_kind,
            "selected_backend_kind": selected_backend_kind,
            "inference_status": inference_status, "error_code": error_code,
            "classification": classify_status(status),
            "correction_application_result_usable": bool(correction_application_result_usable),
            # Prompt 612: additive, defaults to None for legacy direct
            # construction - forwarded verbatim, never derived or
            # re-normalized here. See class docstring's `normalized_input`
            # entry.
            "normalized_input": normalized_input,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise AttributeError("ConversationResponse is immutable")

    def __delattr__(self, name):
        raise AttributeError("ConversationResponse is immutable")

    def __repr__(self):
        return (f"ConversationResponse(status={self.status!r}, backend_kind={self.backend_kind!r}, "
                f"fallback_used={self.fallback_used}, valid={self.valid})")

    def to_dict(self):
        """Plain JSON-shaped dict of fresh copies - mutating it never
        reaches this object or any internal state."""
        data = {name: getattr(self, name) for name in self._FIELDS}
        data["failure_reason"] = _plain(self.failure_reason)
        data["metadata"] = _plain(self.metadata)
        data["validation_issues"] = list(self.validation_issues)
        return data


def build_conversation_response(result, request=None, outcome=None, validation=None):
    """`ConversationResponse` for an already-produced
    `ResponseGenerationResult` (and, optionally, the
    `ResponseGenerationRequest` it was produced for - only read, for
    language/locale). `outcome` / `validation` are used as given when a
    caller (`LanguageIntelligenceCore`) already built them from this same
    `result`; otherwise they are built here with the existing functions.
    Raises TypeError for a `result` that is not a `ResponseGenerationResult`
    or a `request` that is neither None nor a `ResponseGenerationRequest`.
    Pure: never mutates `result`, `request`, `outcome` or `validation`.

    Prompt 578: `correction_application_result_usable` is read straight off
    `outcome` (`ResponseGenerationOutcome.correction_application_result_usable`,
    Prompt 577) and forwarded unchanged onto the returned
    `ConversationResponse` - never recomputed here. False when `outcome`
    carries no such attribute (a legacy outcome built before Prompt 577).

    Prompt 612: `normalized_input` is likewise read straight off `outcome`
    (`ResponseGenerationOutcome.normalized_input`, Prompt 611) and
    forwarded unchanged onto the returned `ConversationResponse` - never
    normalized, stripped, collapsed, or otherwise transformed here. None
    when `outcome` carries no such attribute (a legacy outcome built
    before Prompt 611), the SAME safe-forwarding pattern
    `correction_application_result_usable` above already uses."""
    if not isinstance(result, ResponseGenerationResult):
        raise TypeError("result must be a ResponseGenerationResult")
    if request is not None and not isinstance(request, ResponseGenerationRequest):
        raise TypeError("request must be a ResponseGenerationRequest or None")
    if outcome is None:
        outcome = build_response_generation_outcome(result, request=request)
    if validation is None:
        validation = validate_response_generation_result(result, outcome=outcome)
    correction_usable = bool(
        getattr(outcome, "correction_application_result_usable", False))
    normalized_input = getattr(outcome, "normalized_input", None)
    return ConversationResponse(
        response_text=outcome.generated_text, status=outcome.status, language=outcome.language,
        locale=outcome.locale, backend_kind=outcome.backend_kind, fallback_used=outcome.fallback_used,
        failure_reason=outcome.failure_reason, metadata=outcome.metadata, valid=validation.valid,
        validation_issues=validation.issue_codes, generation_status=result.status,
        reason=result.reason, generation_backend_kind=result.backend_kind,
        fallback_backend_kind=result.fallback_backend_kind,
        selected_backend_kind=result.selected_backend_kind,
        inference_status=result.inference_status, error_code=result.error_code,
        correction_application_result_usable=correction_usable,
        normalized_input=normalized_input)
