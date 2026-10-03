"""
Language Intelligence Core
=============================
`LanguageIntelligenceCore` is the small boundary object Prompt 397
asks for: the one place `Core` (core/core.py) goes to turn a natural-
language message into a structured `LanguageUnderstandingResult`, and
the one place a future real language model would be plugged in -
without Core, Memory, Context, Planning, Execution, or Self-Upgrade
ever needing to change.

    raw_text + already-computed context pieces
        -> LanguageIntelligenceCore.understand(...)
        -> self.backend.understand(...)          (see backend.py)
        -> LanguageUnderstandingResult

    LanguageUnderstandingResult
        -> LanguageIntelligenceCore.generate_response(...)
        -> self.backend.generate_response(...)
        -> ResponseGenerationResult

This class holds exactly one backend instance (constructor argument,
required - no implicit default here, so it is always obvious from the
call site which backend is in play) and calls exactly the two methods
`LanguageIntelligenceBackend` declares. It never touches memory,
knowledge, context, or storage itself - see Core's own integration in
core/core.py for where this fits into the existing conversation path
(module docstring there under "Language Intelligence Core
integration").

Why the caller supplies `context`/`relevant_context`/
`resolved_reference`/`active_topic` instead of this class computing
them itself: those are already Core's own, already-tested systems
(context/relevance.py, context/message_reference_resolution.py,
context/active_topic.py) - computing them a second way here would be
exactly the kind of duplicate system this project's conventions (and
Prompt 397 itself) explicitly forbid. This class is deliberately just
a router to whichever backend is configured, plus the one shared
result shape both backends return.

Prompt 406 - local-model failure and fallback handling
------------------------------------------------------
With an optional `fallback_backend` (normally the
`DeterministicFallbackBackend`), a failing primary backend - typically a
`LocalLanguageModelBackend` - never breaks the conversation flow:

    understand()          primary raises (the local backend always does
                          today: not configured / unavailable /
                          "understanding not implemented yet")
                          -> the SAME arguments go to the fallback
                          backend's understand(); the message and
                          context are passed through untouched and the
                          result's `source_backend` names the fallback.
    generate_response()   primary returns a model failure (or raises)
                          -> that structured failure is returned as is
                          (`status`, `inference_status`, `error_code`,
                          `response_text=None`) with
                          `fallback_backend_kind` set. Core then does
                          what it always did with any result that is not
                          STATUS_GENERATED: the existing deterministic
                          pipeline produces the reply. Nothing here
                          writes text, so no fallback output can be
                          taken for model output.

Prompt 414 - backend selection
------------------------------
`select_backend()` makes the routing explicit and inspectable. With a local-model
primary AND a fallback backend, a model that is not ready (MODEL_NOT_CONFIGURED /
MODEL_UNAVAILABLE / MODEL_LOAD_FAILED) selects the deterministic fallback: the
primary's `generate_response()` is not called at all, and the response is the
structured "local model not used" failure (the Prompt 409 readiness result,
unchanged in status / inference_status / error_code / reason). A ready model
selects the local backend; if its inference then fails, Prompt 406's handling
applies as before. Every response carries `selected_backend_kind`, and the
latest decision is `last_backend_selection`. Nothing else changed: same
fallback backend, same fallback marking, no second controller.

Prompt 425 - structured response planning
-----------------------------------------
Every `LanguageUnderstandingResult` this core returns - from the primary
backend or from Prompt 406's fallback for it - is planned by the core's
`ResponsePlanner` (response_planning.py) and the plan's `to_dict()` is
attached as `understanding.response_plan`; the `ResponsePlan` itself is
`last_response_plan`. The plan lists what a response must contain
(greeting, information needed, ...) and never any response text, so it
does not change which backend answers, `generate_response()`, or the
fallback: `ResponseGeneration` can read the plan from the understanding
it already receives. Planning is not a backend method (no backend, the
Local Language Model one included, needed to change), and a planner
failure is recorded as a `response_plan_error` warning - it never breaks
understanding. `plan_response()` plans an understanding on demand.

Prompt 429 - exposing the structured response-generation outcome
----------------------------------------------------------------
Every `generate_response()` also builds the Prompt 428 structured
`ResponseGenerationOutcome` (response_generation_outcome.py: SUCCESS /
FALLBACK / FAILED / UNRESOLVED, with generated text, backend kind,
language/locale, failure reason and fallback_used) from the very
`ResponseGenerationResult` it returns, and keeps it as
`last_response_generation_result` (same `last_*` pattern as
`last_backend_selection` / `last_response_plan`), read through
`get_last_response_generation_result()`. `generate_response()` itself
still returns the same `ResponseGenerationResult` object as before, so
every existing caller is unaffected; `generate_response_outcome()` is a
thin convenience that returns the outcome directly. The outcome is only
ever DERIVED from the result and a read-only `ResponseGenerationRequest`
wrapper over the arguments: nothing is generated, selected or mutated
here, and a failure to build it never changes or breaks the response.

Prompt 430 - validation
-----------------------
Each `generate_response()` also runs the deterministic
`validate_response_generation_result()` (response_generation_validation.py)
over the returned result and its outcome and keeps the
`ResponseGenerationValidation` as `last_response_generation_validation`
(`get_last_response_generation_validation()`). It only reports: the returned
result, the outcome, the reply text, backend selection and fallback marking
are exactly as before, and nothing is validated by calling a backend again.

Prompt 431 - unified conversation response
------------------------------------------
Each `generate_response()` also derives the immutable `ConversationResponse`
(conversation_response.py) from the same result, outcome and validation and
keeps it as `last_conversation_response`
(`get_last_conversation_response()`); `generate_conversation_response()`
returns it directly. `generate_response()` and everything it returns are
unchanged, so callers that use `ResponseGenerationResult` / response text
keep working; no unrelated system has to migrate.

Prompt 437 - learned response source
------------------------------------
Before routing, `generate_response()` asks `decide_learned_response()`
(learned_response_decision.py) whether a valid learned response - uniquely
selected, bound, rendered (Prompt 434-436) and valid under the Prompt 430
rules - already exists. If so it is the result (STATUS_GENERATED, text
exactly as rendered, `backend_kind` "learned_response", `metadata.
response_source`) and no backend is selected or called; otherwise routing
(backend selection, local model, deterministic fallback) runs unchanged.
The decision is `last_learned_response_decision`.

Prompt 577 - correction_application_result_usable reaches the outcome
-----------------------------------------------------------------------
That same `last_learned_response_decision` already carries
`correction_application_result_usable` (Prompt 576, itself forwarded
from `ResponsePlan`/`ResponseGenerationContext`, Prompts 574/575).
`generate_response()` now reads it off the decision it just made (used
or not) and forwards it, unchanged, onto the `ResponseGenerationOutcome`
(response_generation_outcome.py) it builds - so downstream code already
reading that existing outcome structure can tell "a verified correction
application result is available" without a second lookup. Nothing else
about routing, the learned-response decision, or the outcome's other
fields is affected; missing/legacy/False cases simply forward False,
exactly as before this prompt.

Exactly one primary call per method call: no retry, no second attempt,
no loop - a repeated failure is reported again, not hidden. Without a
`fallback_backend` (the default, and today's Core) every method behaves
exactly as before Prompt 406, exceptions included.
"""

from .backend import LanguageIntelligenceBackend, BACKEND_KIND_LOCAL_MODEL
from .backend_selection import BackendSelection
from .language_understanding_result import LanguageUnderstandingResult
from .response_planning import ResponsePlanner
from .inference import (
    STATUS_INFERENCE_FAILED, ERROR_INFERENCE_FAILED,
    ModelReadiness, READINESS_MODEL_NOT_CONFIGURED, READINESS_MODEL_UNAVAILABLE,
)
from .response_generation import (
    ResponseGenerationRequest, ResponseGenerationResult, STATUS_MODEL_FAILED,
    MODEL_FAILURE_STATUSES,
)
from .response_generation_outcome import build_response_generation_outcome
from .response_generation_validation import validate_response_generation_result
from .conversation_response import build_conversation_response
from .learned_response_decision import decide_learned_response


def _failure_from_exception(exc, backend_kind):
    """A primary backend that raised broke its own contract
    (generate_response never raises); report only the exception TYPE."""
    return ResponseGenerationResult(
        status=STATUS_MODEL_FAILED, response_text=None,
        reason=f"the language backend raised {type(exc).__name__} instead of "
               f"returning a result",
        backend_kind=backend_kind, inference_status=STATUS_INFERENCE_FAILED,
        error_code=ERROR_INFERENCE_FAILED,
    )


class LanguageIntelligenceCore:
    def __init__(self, backend, fallback_backend=None, response_planner=None):
        """`backend` must be a `LanguageIntelligenceBackend`
        (backend.py) - typically a `DeterministicFallbackBackend`
        today (see core/core.py). No default is provided on purpose:
        a caller always states explicitly which backend it wants.

        `fallback_backend` (Prompt 406, optional) - a different
        `LanguageIntelligenceBackend` that takes over when `backend`
        cannot handle a call (see the module docstring). None (default)
        = no fallback handling at all.

        `response_planner` (Prompt 425, optional) - the
        `response_planning.ResponsePlanner` that plans each
        understanding (Core passes its own `self.response_planner`).
        The planner is stateless and dependency-free, so None (default)
        simply uses a new one."""
        if fallback_backend is not None:
            if not isinstance(fallback_backend, LanguageIntelligenceBackend):
                raise TypeError("fallback_backend must be a LanguageIntelligenceBackend")
            if fallback_backend is backend:
                raise ValueError("fallback_backend must differ from backend")
        self.backend = backend
        self.fallback_backend = fallback_backend
        # Prompt 406: why the most recent understand() used the fallback
        # backend (exception type, plus the error code when it has one),
        # or None when the primary backend produced the understanding.
        self.last_understanding_fallback = None
        # Prompt 414: the BackendSelection made for the most recent
        # generate_response(), or None before the first one.
        self.last_backend_selection = None
        # Prompt 425: the planner, and the ResponsePlan made for the most
        # recent understand() (None before the first one, or if planning
        # failed / the backend returned something that is not a
        # LanguageUnderstandingResult).
        self.response_planner = response_planner if response_planner is not None else ResponsePlanner()
        self.last_response_plan = None
        # Prompt 429: the structured ResponseGenerationOutcome (Prompt 428)
        # built from the most recent generate_response() result, or None
        # before the first one / when that call returned no result.
        self.last_response_generation_result = None
        # Prompt 430: the ResponseGenerationValidation for that same result.
        self.last_response_generation_validation = None
        # Prompt 431: the immutable ConversationResponse for that same result.
        self.last_conversation_response = None
        # Prompt 437: the LearnedResponseDecision for the most recent
        # generate_response(), or None before the first one.
        self.last_learned_response_decision = None

    @property
    def backend_kind(self):
        return self.backend.backend_kind

    def understand(self, raw_text, context=None, relevant_context=None,
                    resolved_reference=None, active_topic=None, requested_language=None):
        """Return a `LanguageUnderstandingResult`
        (language_understanding_result.py) for `raw_text`, produced by
        this core's configured backend. See backend.py's
        `LanguageIntelligenceBackend.understand` for the exact
        argument contract. `requested_language` (Prompt 401) is only
        forwarded to the backend when given, so existing backends and
        callers are unaffected."""
        extra = {}
        if requested_language is not None:
            extra["requested_language"] = requested_language
        self.last_understanding_fallback = None
        use_fallback = False
        try:
            result = self.backend.understand(
                raw_text, context=context, relevant_context=relevant_context,
                resolved_reference=resolved_reference, active_topic=active_topic, **extra
            )
        except Exception as exc:  # noqa: BLE001 - a backend failure, see below
            if self.fallback_backend is None:
                raise
            code = getattr(exc, "error_code", None)
            self.last_understanding_fallback = (
                f"{type(exc).__name__}:{code}" if code else type(exc).__name__)
            use_fallback = True
        if use_fallback:
            result = self.fallback_backend.understand(
                raw_text, context=context, relevant_context=relevant_context,
                resolved_reference=resolved_reference, active_topic=active_topic, **extra
            )
        return self._attach_response_plan(result)

    def plan_response(self, understanding):
        """Prompt 425: the `ResponsePlan` (response_planning.py) for an
        already-produced `LanguageUnderstandingResult` - the structured
        requirements of a response, never response text. Deterministic,
        read-only, and independent of which backend is configured.
        Unlike the automatic planning inside `understand()`, a failure
        here is raised (TypeError for something that is not an
        understanding result)."""
        return self.response_planner.plan(understanding)

    def _attach_response_plan(self, result):
        """Plan `result` and store the plan dict on it (see the module
        docstring, Prompt 425). Never raises: a failure leaves
        `response_plan` unset and adds a warning. A result that already
        carries a plan keeps it."""
        self.last_response_plan = None
        if not isinstance(result, LanguageUnderstandingResult):
            return result
        if result.response_plan is not None:
            return result
        try:
            plan = self.response_planner.plan(result)
            result.response_plan = plan.to_dict()
            self.last_response_plan = plan
        except Exception as exc:  # noqa: BLE001 - planning must never break understanding
            result.warnings = list(result.warnings) + [f"response_plan_error: {exc}"]
        return result

    def generate_response(self, understanding, context=None, cancellation_token=None,
                          verified_correction_instruction=None):
        """Return a `ResponseGenerationResult` (response_generation.py)
        for an already-produced `LanguageUnderstandingResult`, produced
        by this core's configured backend. `cancellation_token`
        (Prompt 411, optional) is forwarded to the backend only when
        given, so backends and callers written before it are unaffected;
        a timed-out or cancelled model call is an ordinary model failure
        (see `MODEL_FAILURE_STATUSES`), so the fallback below applies.
        Prompt 429: the structured outcome of the returned result is also
        kept as `get_last_response_generation_result()`; the returned
        object and every behavior above are unchanged.
        Prompt 500: `verified_correction_instruction` (optional - a
        `VerifiedCorrectionResponseInstruction`, Prompt 490) is forwarded
        to the routed backend only when given, so backends and callers
        written before it are unaffected. A backend that responds to text
        (`LocalLanguageModelBackend`) then responds to the corrected
        target the instruction yields, and the result's / outcome's
        `used_verified_correction` is True; the learned-response
        decision and every not-called / blocked / failing path report
        False. Nothing is looked up, matched or corrected here."""
        self.last_response_generation_result = None
        self.last_response_generation_validation = None
        self.last_conversation_response = None
        response = self._learned_response(understanding, context)
        if response is None:
            response = self._route_response(
                understanding, context, cancellation_token, verified_correction_instruction)
        # Prompt 577: the SAME LearnedResponseDecision._learned_response()
        # just made (used or not, and regardless of which path produced
        # `response`) already carries correction_application_result_usable
        # (Prompt 576) - read it here, once, and forward it into the
        # outcome below. Never recomputed.
        correction_usable = bool(getattr(
            self.last_learned_response_decision,
            "correction_application_result_usable", False))
        outcome = self._build_outcome(
            response, understanding, context, verified_correction_instruction,
            correction_application_result_usable=correction_usable)
        self.last_response_generation_result = outcome
        self.last_response_generation_validation = self._validate(response, outcome)
        self.last_conversation_response = self._conversation_response(
            response, outcome, self.last_response_generation_validation)
        return response

    def _learned_response(self, understanding, context):
        """Prompt 437: the deterministic decision point before normal
        backend generation (learned_response_decision.py). A valid,
        already-rendered learned response is the result (no backend is
        selected or called); anything else returns None and the routing
        below runs exactly as before. Never raises: a decision that cannot
        be made is simply "not used"."""
        try:
            decision = decide_learned_response(understanding, context=context)
        except Exception:  # noqa: BLE001 - the decision never breaks generation
            self.last_learned_response_decision = None
            return None
        self.last_learned_response_decision = decision
        if not decision.used:
            return None
        self.last_backend_selection = None  # no backend was selected for this reply
        return decision.response

    def generate_conversation_response(self, understanding, context=None, cancellation_token=None):
        """Prompt 431: `generate_response()`, returning the immutable
        `ConversationResponse` (None only if the backend returned no
        `ResponseGenerationResult`). Same routing, fallback marking and
        `get_last_conversation_response()`."""
        self.generate_response(understanding, context=context,
                               cancellation_token=cancellation_token)
        return self.last_conversation_response

    def get_last_conversation_response(self):
        """Prompt 431: the `ConversationResponse` for the most recent
        `generate_response()`, or None before the first one."""
        return self.last_conversation_response

    @staticmethod
    def _conversation_response(response, outcome, validation):
        if not isinstance(response, ResponseGenerationResult):
            return None
        try:
            return build_conversation_response(response, outcome=outcome, validation=validation)
        except Exception:  # noqa: BLE001 - exposing it never breaks generation
            return None

    def generate_response_outcome(self, understanding, context=None, cancellation_token=None):
        """Prompt 429: `generate_response()`, returning the structured
        `ResponseGenerationOutcome` (Prompt 428) instead of the raw result
        (None only if the backend returned no `ResponseGenerationResult`).
        Same routing, same fallback marking, same
        `get_last_response_generation_result()`."""
        self.generate_response(understanding, context=context,
                               cancellation_token=cancellation_token)
        return self.last_response_generation_result

    def get_last_response_generation_result(self):
        """Prompt 429: the `ResponseGenerationOutcome` for the most recent
        `generate_response()`, or None before the first one. The same object
        is returned on every call until the next `generate_response()`."""
        return self.last_response_generation_result

    def get_last_response_generation_validation(self):
        """Prompt 430: the `ResponseGenerationValidation` of the most recent
        `generate_response()` (VALID/INVALID plus issues, carrying the
        original outcome unchanged), or None before the first one."""
        return self.last_response_generation_validation

    @staticmethod
    def _validate(response, outcome):
        try:
            return validate_response_generation_result(response, outcome=outcome)
        except Exception:  # noqa: BLE001 - validation never breaks generation
            return None

    @staticmethod
    def _build_outcome(response, understanding, context, verified_correction_instruction=None,
                       correction_application_result_usable=False):
        """Derive the Prompt 428 outcome from `response`. Read-only: the
        request is a plain holder over the caller's own arguments (used only
        for language/locale and, Prompt 500, the verified-correction
        preparation state) and nothing is mutated. The instruction is put
        on that request only when `response` says the backend actually
        used the corrected target, so the outcome's
        `used_verified_correction` never claims more than what happened. Never raises - if the
        request-based language/locale cannot be read, the outcome is built
        without them; if it cannot be built at all, None.

        `correction_application_result_usable` (Prompt 577): the caller's
        already-computed `LearnedResponseDecision.
        correction_application_result_usable` (Prompt 576) - forwarded
        straight onto the built outcome on every path below, never
        recomputed here."""
        if not isinstance(response, ResponseGenerationResult):
            return None
        correction_usable = bool(correction_application_result_usable)
        try:
            used = getattr(response, "used_verified_correction", False) is True
            request = ResponseGenerationRequest(
                understanding, context=context,
                verified_correction_instruction=(
                    verified_correction_instruction if used else None))
            return build_response_generation_outcome(
                response, request=request,
                correction_application_result_usable=correction_usable)
        except Exception:  # noqa: BLE001 - exposing the outcome never breaks generation
            pass
        try:
            return build_response_generation_outcome(
                response, correction_application_result_usable=correction_usable)
        except Exception:  # noqa: BLE001
            return None

    def _route_response(self, understanding, context, cancellation_token,
                        verified_correction_instruction=None):
        """The unchanged Prompt 406/411/414 routing that used to be the body
        of `generate_response()`."""
        extra = {}
        if cancellation_token is not None:
            extra["cancellation_token"] = cancellation_token
        if verified_correction_instruction is not None:
            extra["verified_correction_instruction"] = verified_correction_instruction
        selection = self.select_backend()
        self.last_backend_selection = selection
        if selection.not_ready_response is not None:
            # the local model is not ready: it is not called (Prompt 414)
            response = selection.not_ready_response
        elif self.fallback_backend is None:
            response = self.backend.generate_response(understanding, context=context, **extra)
            self._stamp_selection(response, selection)
            return response
        else:
            try:
                response = self.backend.generate_response(understanding, context=context, **extra)
            except Exception as exc:  # noqa: BLE001 - contract breach, reported not raised
                response = _failure_from_exception(exc, self._safe_backend_kind())
            if not isinstance(response, ResponseGenerationResult):
                response = _failure_from_exception(
                    TypeError(), self._safe_backend_kind())
        self._stamp_selection(response, selection)
        if response.status in MODEL_FAILURE_STATUSES:
            response.fallback_backend_kind = self.fallback_backend.backend_kind
        return response

    def select_backend(self):
        """Prompt 414: which backend answers the next request - a
        `BackendSelection` (backend_selection.py). With a local-model
        primary and a fallback backend: the local backend when the model is
        ready, the fallback backend when it is not (the structured reason is
        `not_ready_response`). Otherwise the primary, as before - there is
        nothing to choose. Read-only: never loads a model, never infers,
        never raises; the same state always gives the same selection."""
        readiness = self.check_model_readiness()
        kind = self._safe_backend_kind()
        if kind == BACKEND_KIND_LOCAL_MODEL and self.fallback_backend is not None:
            try:
                blocked = self.backend.not_ready_response()
            except Exception:  # noqa: BLE001 - unknown readiness never blocks
                blocked = None
            if blocked is not None:
                return BackendSelection(
                    self.fallback_backend.backend_kind, readiness=readiness,
                    not_ready_response=blocked, fallback_selected=True)
        return BackendSelection(kind, readiness=readiness)

    @staticmethod
    def _stamp_selection(response, selection):
        if isinstance(response, ResponseGenerationResult):
            response.selected_backend_kind = selection.selected_backend_kind

    def check_model_readiness(self):
        """Prompt 407: is the local model behind this core ready for an
        inference request? Returns a `ModelReadiness`
        (inference.py). Asks the primary backend's
        `check_readiness()` (LocalLanguageModelBackend has one); a backend
        without one - the deterministic fallback - has no local model, so
        it reports MODEL_NOT_CONFIGURED. Read-only: never loads a model,
        never runs inference, never raises."""
        check = getattr(self.backend, "check_readiness", None)
        if check is not None:
            try:
                return check()
            except Exception:  # noqa: BLE001 - a readiness question never raises
                return ModelReadiness(
                    READINESS_MODEL_UNAVAILABLE, ERROR_INFERENCE_FAILED,
                    "the backend could not report readiness")
        return ModelReadiness(
            READINESS_MODEL_NOT_CONFIGURED, None,
            "the configured language backend does not use a local model")

    def _safe_backend_kind(self):
        try:
            return self.backend.backend_kind
        except Exception:  # noqa: BLE001
            return None
