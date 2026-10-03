"""
Language Intelligence - Structured Response Planning
==========================================================
Prompt 425. One focused capability: turn what the existing
language-understanding pipeline ALREADY extracted into a small,
structured description of what a response must contain - WITHOUT
writing the response.

    LanguageUnderstandingResult  (Prompts 397-424, untouched)
      -> ResponsePlanner.plan(understanding)
      -> ResponsePlan               (this module)
      -> (later) ResponseGeneration consumes it

This is a deterministic planning layer, not text generation. A plan says
"a greeting is required" or "information about {topic: python} is
required and has NOT been retrieved"; it never says "Hello!" and never
contains `response_text`. `ResponseGeneration` (response_generation.py)
is not replaced and not changed in behaviour: a backend that generates
text simply finds the plan on `understanding.response_plan`.

Nothing is invented (the hard rule of this module)
---------------------------------------------------
`plan()` is a pure function of ONE `LanguageUnderstandingResult` (or its
`to_dict()`). It reads no store, no knowledge, no memory, no context
object and no clock; it writes nothing. So it cannot add a fact, an
intent, a variable, a knowledge item or a meaning that the understanding
result does not already carry. Concretely:

    original_message  `original_input`, verbatim (never normalized).
    detected_language `detected_language`, as the Understanding Engine
                      reported it.
    locale            the first locale the existing results state, in
                      this fixed order: meaning resolution (Prompt 424),
                      sentence structure (422), pattern match (421), the
                      bound meaning's own locale. None when none does -
                      a locale is never derived from the language.
    meaning           the ONE meaning EXPLICITLY bound to the matched
                      learned pattern (Prompt 424), only when that
                      resolution is RESOLVED.
    matched_pattern / variables / pattern_candidates
                      the Prompt 421 match, as found.
    active_topic / references / context
                      `active_topic`, `referenced_items`,
                      `conversation_context` of the understanding,
                      copied - never recomputed.

Statuses
--------
    RESOLVED    exactly one explicitly learned meaning/intention applies.
    AMBIGUOUS   several learned meanings remain undecided: several bound
                meanings the Prompt 420 disambiguator could not tell apart
                (`meaning_candidates`), several learned patterns matching
                equally (`pattern_candidates`), or - when no intention
                is resolved at all - a word/phrase with several learned
                meanings nothing distinguishes (`expression_meanings`).
                Every candidate is kept; none is picked. The plan says
                clarification may be required (`needs_clarification`).
    UNRESOLVED  no learned intention applies: no pattern matched, the
                pattern's structure is not determined, the pattern has no
                bound meaning, or nothing was learned at all. The
                existing unresolved state is preserved: `reason` is the
                reason the existing pipeline gave (verbatim), and the
                understanding's own intent / confidence /
                needs_clarification are echoed in `understanding_state`.
                No response action and no required item is ever made up
                for an UNRESOLVED or AMBIGUOUS plan.

A word-level ambiguity inside a message whose intention IS resolved does
not turn the plan AMBIGUOUS (the intention is known); it is kept in
`expression_meanings` and as an unresolved requirement, and it sets
`needs_clarification`.

The response action
-------------------
`response_action` is the basic requirement of a RESOLVED plan, and it
comes only from what was explicitly taught, in this order:

    1. `response_action` in the stored value of the bound MEANING item
       (`{"response_action": "greet"}` - source "learned_meaning");
    2. `response_action` in the stored `meaning` value of the matched
       PATTERN (Prompt 423 `teach(..., meaning={...})` - source
       "learned_pattern"). The same open, caller-shaped value already
       carries the pattern's `locale` (Prompt 421), so no new storage is
       added. A taught action is passed through as taught (trimmed);
    3. the bound meaning's NAME, looked up exactly (case-insensitive,
       spaces/hyphens as underscores) in the tiny fixed table below -
       source "meaning_name". This is a lookup, not a classifier:

           greet                greet, greeting
           provide_information  ask_question, information_request,
                                request_information

Anything else has no action: `response_action` is None and an unresolved
requirement (`response_action` / `no_response_action_defined`) says so,
instead of a guess. The action vocabulary is NOT the `intent` vocabulary
of language_understanding_result.py: there, `provide_information` means
the USER states something (a statement); here it means the RESPONSE must
supply known information. The heuristic `intent` never selects an action.

Required items and knowledge
----------------------------
    greet                 one `greeting` item.
    provide_information   one `information` item describing what is
                          needed - the original message and extracted
                          variables as the query, the active topic, the
                          resolved/unresolved references, and the
                          Knowledge concepts the resolved expressions
                          are already linked to - with
                          `retrieval.performed == False`. The plan asks
                          for the information; retrieving it stays with
                          the existing Knowledge/Memory/Reasoning systems.
    another taught action no required item (nothing is assumed).

Unresolved requirements
-----------------------
`unresolved_requirements` lists what the plan could not settle, each
`{"kind", "reason", "detail"}`: an undecided meaning or pattern
(`meaning`), a pattern structure with an undetermined variable boundary
(`sentence_structure`), an ambiguous or unresolved message reference
(`reference`), an ambiguous expression (`expression_meaning`), or a
missing action (`response_action`). `needs_clarification` is True for
AMBIGUOUS plans, for the ambiguity/reference reasons in
`CLARIFICATION_REASONS`, and - for UNRESOLVED plans - when the
understanding itself says it needs clarification.

Integration: `LanguageIntelligenceCore` (language_intelligence_core.py)
plans every understanding it returns, from whichever backend produced it
(deterministic, or deterministic fallback of the Local Language Model
path), and stores the plan dict on `understanding.response_plan`.

Prompt 573 addendum - correction_application_result
-----------------------------------------------------
`ResponsePlan` is the existing, smallest response-decision/planning
object that already receives a `LanguageUnderstandingResult` and decides
what a response must contain. This module already carried
`understanding.correction_application_candidate` nowhere - and nothing
about `understanding.correction_application_result` (Prompt 474,
populated by Prompt 570's application operation, exposed since Prompt
571) either - so a plan built from a real correction had no way to let
a later response-decision step even see that result.

This addendum adds ONE additive field, `correction_application_result`,
to `ResponsePlan`: it is read from the understanding (added to
`_READ_FIELDS` below) and forwarded onto the plan unchanged, in
`ResponsePlanner.plan()`. It defaults to `None` and is never
independently set. Nothing about `status`, `response_action`,
`required_items`, `unresolved_requirements`, or any other decision this
module makes is affected: the field is read AFTER every decision above
it is already final, and none of those computations consult it. No
second application, retrieval, or selection happens here or anywhere
because of this addendum - the result is read exactly once, from
wherever `_attach_correction_application_result` (core.py, Prompt 572)
already placed it.

Prompt 574 addendum - correction_application_result_usable
--------------------------------------------------------------
Prompt 573 gave `ResponsePlan` the raw `correction_application_result`
dict, but nothing yet told a downstream planning decision whether that
result is actually a successfully applicable/verified correction, as
opposed to `None`, a `FAILED` attempt, or a structurally incomplete
one. This addendum answers exactly that - and ONLY that - one
question, as a second additive field:

    correction_application_result_usable   `True` only when
                              `correction_application_result` (this
                              module's own Prompt 573 field, just
                              above) represents a result the EXISTING
                              `is_correction_application_result_usable()`
                              (correction_application_result_usability.py,
                              Prompt 484) would itself call usable:
                              `status == "APPLIED"`, `applied is True`,
                              a `match_count` that is an `int` greater
                              than zero, and `text_before` /
                              `text_after` / `matched_text` /
                              `replacement_text` all present (not
                              `None`). `False` for `None`, `NOT_APPLIED`,
                              `FAILED`, or any result missing one of
                              those fields - never guessed, never
                              "close enough". Defaults to `False` for
                              every existing caller/understanding that
                              carries no result (the common case), so
                              existing behavior is unchanged.

This is the SAME question Prompt 484's `is_correction_application_
result_usable()` already answers over a `ResponseGenerationContext`'s
`CorrectionApplicationResult` OBJECT - reused here as the same
criteria, not a second, competing definition of "usable" - just
evaluated against the dict form `_READ_FIELDS`/`plan()` already
carries `correction_application_result` in (the SAME "read from the
understanding's own `to_dict()` shape" rule every other field this
planner reads already follows), since `ResponsePlan` never holds live
objects. `is_correction_application_result_usable()` itself is neither
modified nor duplicated as a class/status/validator - Prompt 480's
`validate_applied_correction_result()` and Prompt 482's
`verify_correction_application_result()` are untouched and uncalled
here. No new result states are invented; no correction is applied,
retried, retrieved, or selected; the user's message and the
`CorrectionApplicationResult` itself are never modified; and neither
`status`, `response_action`, `required_items`,
`unresolved_requirements`, nor any other planning decision reads this
new field - it is purely additional, informational output for a LATER,
still-unwritten step to consult.
"""

import copy
import re

from .language_understanding_result import LanguageUnderstandingResult
from .learned_meaning_disambiguation import (
    STATUS_RESOLVED as MEANING_RESOLVED, STATUS_AMBIGUOUS as MEANING_AMBIGUOUS,
)
from .learned_pattern_matching import (
    STATUS_MATCHED, STATUS_AMBIGUOUS as PATTERN_AMBIGUOUS, REASON_INDETERMINATE_STRUCTURE,
)
from .learned_pattern_meaning import REASON_PATTERN_NOT_MATCHED
from .correction_application_result import STATUS_APPLIED as CORRECTION_STATUS_APPLIED

STATUS_RESOLVED = "RESOLVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_UNRESOLVED = "UNRESOLVED"
ALL_STATUSES = (STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED)

# The response actions the planner itself can name. A response action
# taught explicitly (see the module docstring) is passed through as
# taught and need not be one of these.
ACTION_GREET = "greet"
ACTION_PROVIDE_INFORMATION = "provide_information"
ALL_RESPONSE_ACTIONS = (ACTION_GREET, ACTION_PROVIDE_INFORMATION)

# Where a response action came from.
SOURCE_LEARNED_MEANING = "learned_meaning"
SOURCE_LEARNED_PATTERN = "learned_pattern"
SOURCE_MEANING_NAME = "meaning_name"

# The one, small, fixed name lookup (see the module docstring). Exact
# match only; deliberately not extensible by inference.
_MEANING_NAME_ACTIONS = {
    "greet": ACTION_GREET,
    "greeting": ACTION_GREET,
    "ask_question": ACTION_PROVIDE_INFORMATION,
    "information_request": ACTION_PROVIDE_INFORMATION,
    "request_information": ACTION_PROVIDE_INFORMATION,
}

# Required-item kinds.
ITEM_GREETING = "greeting"
ITEM_INFORMATION = "information"

# Unresolved-requirement kinds.
KIND_MEANING = "meaning"
KIND_SENTENCE_STRUCTURE = "sentence_structure"
KIND_REFERENCE = "reference"
KIND_EXPRESSION_MEANING = "expression_meaning"
KIND_RESPONSE_ACTION = "response_action"

# Reasons this module adds. Every other `reason` a plan carries is the
# existing pipeline's own, verbatim.
REASON_NO_LEARNED_UNDERSTANDING = "no_learned_understanding_available"
REASON_PATTERN_MEANING_NOT_AVAILABLE = "pattern_meaning_not_available"
REASON_AMBIGUOUS_EXPRESSION_MEANING = "ambiguous_expression_meaning"
REASON_AMBIGUOUS_MEANING = "ambiguous_meaning"
REASON_AMBIGUOUS_PATTERN = "ambiguous_pattern"
REASON_AMBIGUOUS_REFERENCE = "ambiguous_reference"
REASON_UNRESOLVED_REFERENCE = "unresolved_reference"
REASON_NO_RESPONSE_ACTION = "no_response_action_defined"

# Requirement reasons that mean "asking the user could settle this".
CLARIFICATION_REASONS = (
    REASON_AMBIGUOUS_MEANING, REASON_AMBIGUOUS_PATTERN, REASON_AMBIGUOUS_REFERENCE,
    REASON_UNRESOLVED_REFERENCE, REASON_AMBIGUOUS_EXPRESSION_MEANING,
)

WARNING_INVALID_RESPONSE_ACTION = "invalid_response_action_ignored"

# The only understanding fields the planner reads (each copied before use,
# so a plan never shares a mutable object with the understanding it was
# made from).
#
# Prompt 573: "correction_application_result" is additive. It is NOT used
# to decide `status`, `response_action`, `required_items`, or anything
# else this planner computes - it is forwarded verbatim (already a plain
# dict once `understanding.to_dict()` has run, per Prompt 474/571's own
# `to_dict()` convention) so the response decision/planning layer has
# structured awareness of an already-produced
# `CorrectionApplicationResult` (Prompt 474/570) without this module
# inventing, re-deriving, or re-running anything about it. `None` for
# every existing caller/understanding that does not carry one - the
# common case - so existing behavior is unchanged.
_READ_FIELDS = (
    "original_input", "normalized_input", "detected_language", "intent", "confidence",
    "ambiguity", "needs_clarification", "source_backend", "referenced_items", "active_topic",
    "conversation_context", "learned_meanings", "disambiguated_meanings",
    "learned_pattern_match", "learned_sentence_structure", "learned_pattern_meaning",
    "correction_application_result",
)

# Fixed bounds, same spirit as the other language-intelligence stages:
# the plan's size never depends on how much was learned.
MAX_EXPRESSION_MEANINGS = 20
MAX_CONCEPT_REFERENCES = 20


def _as_dict(value):
    return value if isinstance(value, dict) else None


def _as_list(value):
    return list(value) if isinstance(value, (list, tuple)) else []


def _name_key(name):
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def _correction_application_result_usable(result):
    """Prompt 574: `True` only when `result` (the dict form of a
    `CorrectionApplicationResult`, exactly as `to_dict()`
    (correction_application_result.py) produces it - the SAME shape
    `_READ_FIELDS`'s own `correction_application_result` entry already
    carries) satisfies the EXACT SAME criteria
    `is_correction_application_result_usable()`
    (correction_application_result_usability.py, Prompt 484) already
    checks on the live object: `status == STATUS_APPLIED`, `applied is
    True`, a `match_count` that is an `int` greater than zero, and
    `text_before` / `text_after` / `matched_text` / `replacement_text`
    all present (not `None`). Not a re-implementation of a different
    rule - the identical, already-defined rule, evaluated against the
    dict this module already has rather than the object Prompt 484's
    function requires.

    `None`, a non-dict value, a `NOT_APPLIED` or `FAILED` result, or
    any result missing one of the required fields all return `False` -
    never guessed, never raised. Pure and deterministic; never mutates
    `result`."""
    if not isinstance(result, dict):
        return False
    if result.get("status") != CORRECTION_STATUS_APPLIED:
        return False
    if result.get("applied") is not True:
        return False
    match_count = result.get("match_count")
    if not isinstance(match_count, int) or match_count <= 0:
        return False
    if result.get("text_before") is None:
        return False
    if result.get("text_after") is None:
        return False
    if result.get("matched_text") is None:
        return False
    if result.get("replacement_text") is None:
        return False
    return True


class ResponsePlan:
    """Plain, JSON-shaped result of `ResponsePlanner.plan()` - the
    structured requirements of a response, never the response itself.

        original_message      the user's message, verbatim
        normalized_input      Prompt 609: the existing understanding's own
                              `normalized_input` (already produced by the
                              Understanding Engine's normalization -
                              understanding/normalization.py - and carried
                              unchanged on `LanguageUnderstandingResult`
                              since Prompt 397), forwarded here verbatim.
                              Never recomputed or re-normalized by this
                              module; kept separate from
                              `original_message` above, exactly as
                              `language_understanding_result.py` keeps
                              `normalized_input` separate from
                              `original_input`. `None` only for a
                              hand-built understanding/dict that itself
                              carries no `normalized_input` (legacy
                              construction) - the SAME "additive, forwarded
                              verbatim" posture `correction_application_result`
                              below already uses.
        detected_language     as the Understanding Engine reported it
        locale                see the module docstring; None if none stated
        status                RESOLVED / AMBIGUOUS / UNRESOLVED
        reason                why: the existing pipeline's reason,
                              verbatim, or one of this module's REASON_*
        needs_clarification   True when the user could settle something
                              the plan could not (see the docstring)
        response_action       "greet" / "provide_information" / a taught
                              action / None (RESOLVED plans only)
        response_action_source  SOURCE_* or None
        meaning               the one resolved bound meaning (a Prompt
                              424 candidate dict) or None
        meaning_candidates    every bound meaning still undecided
                              (AMBIGUOUS via the binder); [] otherwise
        matched_pattern       `{"pattern_id", "pattern_text", "language",
                              "locale", "confidence", "source",
                              "meaning"}` of the matched learned pattern,
                              or None
        pattern_candidates    every learned pattern that matched equally
                              (or lined up, when the structure is not
                              determined); [] when one pattern matched
        variables             the matched pattern's extracted variables
        expression_meanings   compact `{"expression", "status",
                              "resolved_meaning", "candidates", "reason"}`
                              entries for expressions with a learned
                              meaning (RESOLVED or AMBIGUOUS)
        active_topic          the understanding's active topic dict / None
        references            the understanding's `referenced_items`
        context               the understanding's `conversation_context`
        required_items        what a response must contain (see docstring)
        unresolved_requirements  what the plan could not settle
        understanding_state   the existing pipeline's own state, echoed:
                              intent, confidence, ambiguity,
                              needs_clarification, source_backend,
                              learned_pattern_status,
                              learned_meaning_status
        warnings              anomalies met while planning (never raised)
        correction_application_result  Prompt 573: the existing
                              `CorrectionApplicationResult.to_dict()`
                              (Prompt 474/570/571) already attached to
                              the understanding this plan was built
                              from, carried through unchanged - or
                              `None` when the understanding carries
                              none (the common case). Purely
                              informational: it plays no part in
                              `status`, `response_action`,
                              `required_items`, or any other decision
                              this class/`ResponsePlanner` makes.
        correction_application_result_usable  Prompt 574: `True` only
                              when `correction_application_result`
                              (just above) is a successfully
                              applicable/verified correction by the
                              EXISTING Prompt 484 usability criteria -
                              see the module docstring's Prompt 574
                              addendum. `False` for `None`,
                              `NOT_APPLIED`, `FAILED`, or an incomplete
                              result. Also plays no part in `status`,
                              `response_action`, `required_items`, or
                              any other decision this class/
                              `ResponsePlanner` makes - purely
                              additional, informational output.
    """

    def __init__(self, original_message, detected_language, locale, status, reason,
                 needs_clarification, response_action, response_action_source, meaning,
                 meaning_candidates, matched_pattern, pattern_candidates, variables,
                 expression_meanings, active_topic, references, context, required_items,
                 unresolved_requirements, understanding_state, warnings,
                 correction_application_result=None, normalized_input=None):
        self.original_message = original_message
        # Prompt 609: additive, defaults to None for legacy construction -
        # see the class docstring's `normalized_input` entry. Forwarded
        # verbatim from the understanding; never derived or re-normalized
        # here.
        self.normalized_input = normalized_input
        self.detected_language = detected_language
        self.locale = locale
        self.status = status
        self.reason = reason
        self.needs_clarification = needs_clarification
        self.response_action = response_action
        self.response_action_source = response_action_source
        self.meaning = meaning
        self.meaning_candidates = meaning_candidates
        self.matched_pattern = matched_pattern
        self.pattern_candidates = pattern_candidates
        self.variables = variables
        self.expression_meanings = expression_meanings
        self.active_topic = active_topic
        self.references = references
        self.context = context
        self.required_items = required_items
        self.unresolved_requirements = unresolved_requirements
        self.understanding_state = understanding_state
        self.warnings = warnings
        # Prompt 573: additive, defaults to None, never independently set -
        # see the class docstring's `correction_application_result` entry.
        self.correction_application_result = correction_application_result
        # Prompt 574: derived, never independently set - the SAME "derived,
        # never independent" posture `CorrectionApplicationResult.applied`
        # (correction_application_result.py) already uses for its own
        # status-derived field. Always exactly what
        # `_correction_application_result_usable()` computes from
        # `correction_application_result` above - see the class
        # docstring's `correction_application_result_usable` entry.
        self.correction_application_result_usable = (
            _correction_application_result_usable(correction_application_result))

    @property
    def resolved(self):
        return self.status == STATUS_RESOLVED

    @property
    def ambiguous(self):
        return self.status == STATUS_AMBIGUOUS

    @property
    def unresolved(self):
        return self.status == STATUS_UNRESOLVED

    @property
    def meaning_name(self):
        return self.meaning.get("meaning_name") if self.meaning else None

    @property
    def matched_pattern_text(self):
        return self.matched_pattern.get("pattern_text") if self.matched_pattern else None

    def __repr__(self):
        return (f"ResponsePlan(status={self.status!r}, response_action={self.response_action!r}, "
                f"meaning_name={self.meaning_name!r}, reason={self.reason!r})")

    def to_dict(self):
        return copy.deepcopy({
            "original_message": self.original_message,
            # Prompt 609: forwarded verbatim - see the class docstring.
            "normalized_input": self.normalized_input,
            "detected_language": self.detected_language,
            "locale": self.locale,
            "status": self.status,
            "resolved": self.resolved,
            "ambiguous": self.ambiguous,
            "reason": self.reason,
            "needs_clarification": self.needs_clarification,
            "response_action": self.response_action,
            "response_action_source": self.response_action_source,
            "meaning": self.meaning,
            "meaning_name": self.meaning_name,
            "meaning_candidates": self.meaning_candidates,
            "matched_pattern": self.matched_pattern,
            "pattern_candidates": self.pattern_candidates,
            "variables": self.variables,
            "expression_meanings": self.expression_meanings,
            "active_topic": self.active_topic,
            "references": self.references,
            "context": self.context,
            "required_items": self.required_items,
            "unresolved_requirements": self.unresolved_requirements,
            "understanding_state": self.understanding_state,
            "warnings": self.warnings,
            # Prompt 573: same "already a dict, or carried through as-is"
            # convention `language_understanding_result.py` uses for this
            # same field.
            "correction_application_result": (
                self.correction_application_result.to_dict()
                if hasattr(self.correction_application_result, "to_dict")
                else self.correction_application_result
            ),
            # Prompt 574: derived from the field just above - see this
            # class's own docstring entry.
            "correction_application_result_usable": self.correction_application_result_usable,
        })


class ResponsePlanner:
    """Stateless and dependency-free: it owns no storage and calls no
    other system, so one instance is safe to reuse for every call."""

    def plan(self, understanding):
        """The `ResponsePlan` for `understanding` (a
        `LanguageUnderstandingResult`, or its `to_dict()`). Reads only
        that; see the module docstring for what is and is not derived.
        Never mutates `understanding`. A value that is neither raises
        TypeError."""
        if isinstance(understanding, LanguageUnderstandingResult):
            source = understanding.to_dict()
        elif isinstance(understanding, dict):
            source = understanding
        else:
            raise TypeError(
                "understanding must be a LanguageUnderstandingResult or its to_dict()")
        data = {name: copy.deepcopy(source.get(name)) for name in _READ_FIELDS}

        warnings = []
        meaning_res = _as_dict(data.get("learned_pattern_meaning"))
        match = _as_dict(data.get("learned_pattern_match"))
        if match is None and meaning_res is not None:
            match = _as_dict(meaning_res.get("pattern_match"))
        structure = _as_dict(data.get("learned_sentence_structure"))

        expressions = self._expression_meanings(data)
        status, reason = self._decide_status(meaning_res, match, expressions)

        meaning = None
        meaning_candidates = []
        if status == STATUS_RESOLVED:
            meaning = meaning_res["meaning"]
        elif status == STATUS_AMBIGUOUS and meaning_res is not None \
                and meaning_res.get("status") == MEANING_AMBIGUOUS:
            meaning_candidates = _as_list(meaning_res.get("candidates"))

        matched_pattern, pattern_candidates = self._pattern_parts(match)
        variables = dict(
            (meaning_res or {}).get("variables") or (match or {}).get("variables") or {})
        references = _as_list(data.get("referenced_items"))
        active_topic = _as_dict(data.get("active_topic"))
        original = data.get("original_input")

        action, action_source = None, None
        if status == STATUS_RESOLVED:
            action, action_source = self._response_action(
                meaning, (match or {}).get("meaning"), warnings)

        required_items = self._required_items(
            action, original, variables, matched_pattern, active_topic, references, expressions)
        requirements = self._requirements(
            status, reason, meaning, action, meaning_candidates, pattern_candidates, structure,
            references, expressions)

        understanding_state = {
            "intent": data.get("intent"),
            "confidence": data.get("confidence"),
            "ambiguity": data.get("ambiguity"),
            "needs_clarification": data.get("needs_clarification"),
            "source_backend": data.get("source_backend"),
            "learned_pattern_status": (match or {}).get("status"),
            "learned_meaning_status": (meaning_res or {}).get("status"),
        }
        needs_clarification = (
            status == STATUS_AMBIGUOUS
            or any(r["reason"] in CLARIFICATION_REASONS for r in requirements)
            or (status == STATUS_UNRESOLVED and bool(data.get("needs_clarification")))
        )

        return ResponsePlan(
            original_message=original,
            # Prompt 609: forwarded verbatim from the understanding - never
            # recomputed, never re-normalized, never influences status/
            # action/required_items/requirements above.
            normalized_input=data.get("normalized_input"),
            detected_language=data.get("detected_language"),
            locale=self._locale(meaning_res, structure, match, meaning),
            status=status, reason=reason, needs_clarification=needs_clarification,
            response_action=action, response_action_source=action_source,
            meaning=meaning, meaning_candidates=meaning_candidates,
            matched_pattern=matched_pattern, pattern_candidates=pattern_candidates,
            variables=variables, expression_meanings=expressions,
            active_topic=active_topic, references=references,
            context=_as_dict(data.get("conversation_context")),
            required_items=required_items, unresolved_requirements=requirements,
            understanding_state=understanding_state, warnings=warnings,
            # Prompt 573: forwarded verbatim from the understanding - never
            # recomputed, never applied, never influences status/action/
            # required_items/requirements above (all already decided
            # before this line).
            correction_application_result=data.get("correction_application_result"),
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    @staticmethod
    def _decide_status(meaning_res, match, expressions):
        """`(status, reason)` - the existing pipeline's state and reason,
        carried over rather than re-derived."""
        if meaning_res is not None:
            meaning_status = meaning_res.get("status")
            if meaning_status == MEANING_RESOLVED and _as_dict(meaning_res.get("meaning")):
                return STATUS_RESOLVED, meaning_res.get("reason")
            if meaning_status == MEANING_AMBIGUOUS:
                return STATUS_AMBIGUOUS, meaning_res.get("reason")
            if (meaning_status != MEANING_RESOLVED
                    and meaning_res.get("reason") != REASON_PATTERN_NOT_MATCHED):
                # the pattern matched but has no (applicable) bound meaning
                return ResponsePlanner._unresolved_or_expression_ambiguity(
                    meaning_res.get("reason"), expressions)
        if match is not None:
            match_status = match.get("status")
            if match_status == PATTERN_AMBIGUOUS:
                return STATUS_AMBIGUOUS, match.get("reason")
            if match_status == STATUS_MATCHED:
                # matched, but no meaning result exists to read a meaning from
                return ResponsePlanner._unresolved_or_expression_ambiguity(
                    REASON_PATTERN_MEANING_NOT_AVAILABLE, expressions)
            return ResponsePlanner._unresolved_or_expression_ambiguity(
                match.get("reason"), expressions)
        return ResponsePlanner._unresolved_or_expression_ambiguity(
            REASON_NO_LEARNED_UNDERSTANDING, expressions)

    @staticmethod
    def _unresolved_or_expression_ambiguity(reason, expressions):
        """No intention is resolved. Several learned meanings for one
        expression that nothing distinguishes are still an ambiguity."""
        if any(e["status"] == MEANING_AMBIGUOUS for e in expressions):
            return STATUS_AMBIGUOUS, REASON_AMBIGUOUS_EXPRESSION_MEANING
        return STATUS_UNRESOLVED, reason

    # ------------------------------------------------------------------
    # Pieces
    # ------------------------------------------------------------------
    @staticmethod
    def _locale(meaning_res, structure, match, meaning):
        for source in (meaning_res, structure, match, meaning):
            locale = (source or {}).get("locale")
            if locale:
                return locale
        return None

    @staticmethod
    def _pattern_parts(match):
        """`(matched_pattern, pattern_candidates)` from the Prompt 421 match."""
        if match is None:
            return None, []
        if match.get("status") == STATUS_MATCHED and match.get("matched_pattern_id") is not None:
            return {
                "pattern_id": match.get("matched_pattern_id"),
                "pattern_text": match.get("matched_pattern_text"),
                "language": match.get("language"),
                "locale": match.get("locale"),
                "confidence": match.get("confidence"),
                "source": match.get("source"),
                "meaning": match.get("meaning"),
            }, []
        return None, _as_list(match.get("candidates"))

    @staticmethod
    def _expression_meanings(data):
        """Compact entries for the message's expressions that have a
        learned meaning. Prefers the Prompt 420 disambiguation (REUSED as
        decided there); without a disambiguator, several learned meanings
        for one expression (Prompt 418 `ambiguous`) are reported as
        AMBIGUOUS, never collapsed."""
        entries = []
        disambiguated = _as_list(data.get("disambiguated_meanings"))
        if disambiguated:
            for item in disambiguated:
                item = _as_dict(item)
                if item is None or item.get("status") not in (MEANING_RESOLVED, MEANING_AMBIGUOUS):
                    continue
                entries.append({
                    "expression": item.get("expression"), "status": item.get("status"),
                    "resolved_meaning": item.get("resolved_meaning"),
                    "candidates": (
                        _as_list(item.get("candidates"))
                        if item.get("status") == MEANING_AMBIGUOUS else []),
                    "reason": item.get("reason"),
                })
        else:
            for item in _as_list(data.get("learned_meanings")):
                item = _as_dict(item)
                meanings = _as_list(item.get("meanings")) if item else []
                if not meanings:
                    continue
                if len(meanings) == 1:
                    entries.append({
                        "expression": item.get("expression"), "status": MEANING_RESOLVED,
                        "resolved_meaning": meanings[0], "candidates": [], "reason": None,
                    })
                else:
                    entries.append({
                        "expression": item.get("expression"), "status": MEANING_AMBIGUOUS,
                        "resolved_meaning": None, "candidates": meanings, "reason": None,
                    })
        return copy.deepcopy(entries[:MAX_EXPRESSION_MEANINGS])

    @staticmethod
    def _response_action(meaning, pattern_meaning, warnings):
        """`(action, source)`: explicitly taught first, then the fixed
        meaning-name lookup, else `(None, None)`. See the module docstring."""
        for source, holder in ((SOURCE_LEARNED_MEANING, (meaning or {}).get("meaning")),
                               (SOURCE_LEARNED_PATTERN, pattern_meaning)):
            if isinstance(holder, dict) and "response_action" in holder:
                value = holder["response_action"]
                if isinstance(value, str) and value.strip():
                    return value.strip(), source
                warnings.append(f"{WARNING_INVALID_RESPONSE_ACTION}: {source}")
        name = (meaning or {}).get("meaning_name")
        if isinstance(name, str):
            action = _MEANING_NAME_ACTIONS.get(_name_key(name))
            if action is not None:
                return action, SOURCE_MEANING_NAME
        return None, None

    @staticmethod
    def _required_items(action, original, variables, matched_pattern, active_topic, references,
                        expressions):
        if action == ACTION_GREET:
            return [{"kind": ITEM_GREETING, "action": ACTION_GREET}]
        if action == ACTION_PROVIDE_INFORMATION:
            return [{
                "kind": ITEM_INFORMATION,
                "action": ACTION_PROVIDE_INFORMATION,
                # what is needed - described, not retrieved
                "retrieval": {"from": ["knowledge", "memory"], "performed": False},
                "query": {
                    "message": original,
                    "variables": dict(variables),
                    "pattern_text": matched_pattern.get("pattern_text") if matched_pattern else None,
                },
                "topic": active_topic.get("topic") if active_topic else None,
                "references": copy.deepcopy(references),
                "concepts": ResponsePlanner._concept_references(expressions),
            }]
        return []

    @staticmethod
    def _concept_references(expressions):
        """Knowledge concepts already linked (Prompt 417/418) to a RESOLVED
        expression of the message - only decided meanings, never the
        undecided candidates of an ambiguous one."""
        concepts, seen = [], set()
        for entry in expressions:
            resolved = _as_dict(entry.get("resolved_meaning"))
            if entry.get("status") != MEANING_RESOLVED or resolved is None:
                continue
            for link in _as_list(resolved.get("related")):
                related = _as_dict((link or {}).get("related"))
                if related is None or related.get("kind") != "concept" or not related.get("concept"):
                    continue
                key = (entry.get("expression"), related["concept"], link.get("relation_type"))
                if key in seen:
                    continue
                seen.add(key)
                concepts.append({
                    "concept": related["concept"], "expression": entry.get("expression"),
                    "relation_type": link.get("relation_type"),
                })
                if len(concepts) >= MAX_CONCEPT_REFERENCES:
                    return concepts
        return concepts

    @staticmethod
    def _requirement(kind, reason, **detail):
        return {"kind": kind, "reason": reason, "detail": copy.deepcopy(detail)}

    def _requirements(self, status, reason, meaning, action, meaning_candidates,
                      pattern_candidates, structure, references, expressions):
        found = []
        if status == STATUS_AMBIGUOUS:
            if meaning_candidates:
                found.append(self._requirement(
                    KIND_MEANING, REASON_AMBIGUOUS_MEANING, plan_reason=reason,
                    candidates=[c.get("meaning_name") for c in meaning_candidates]))
            elif pattern_candidates:
                found.append(self._requirement(
                    KIND_MEANING, REASON_AMBIGUOUS_PATTERN, plan_reason=reason,
                    candidates=[c.get("pattern_text") for c in pattern_candidates]))
        elif status == STATUS_UNRESOLVED:
            found.append(self._requirement(KIND_MEANING, reason))

        if structure is not None:
            for component in _as_list(structure.get("components")):
                if isinstance(component, dict) and component.get("kind") == "unresolved":
                    found.append(self._requirement(
                        KIND_SENTENCE_STRUCTURE, REASON_INDETERMINATE_STRUCTURE,
                        text=component.get("text"), variable_names=component.get("variable_names"),
                        start=component.get("start"), end=component.get("end")))

        for item in references:
            item = _as_dict(item)
            if item is None:
                continue
            if item.get("ambiguous"):
                found.append(self._requirement(
                    KIND_REFERENCE, REASON_AMBIGUOUS_REFERENCE,
                    reference_text=item.get("reference_text")))
            elif item.get("resolved_context") is None:
                found.append(self._requirement(
                    KIND_REFERENCE, REASON_UNRESOLVED_REFERENCE,
                    reference_text=item.get("reference_text")))

        for entry in expressions:
            if entry["status"] == MEANING_AMBIGUOUS:
                found.append(self._requirement(
                    KIND_EXPRESSION_MEANING, REASON_AMBIGUOUS_EXPRESSION_MEANING,
                    expression=entry.get("expression"), candidate_count=len(entry["candidates"])))

        if status == STATUS_RESOLVED and action is None:
            found.append(self._requirement(
                KIND_RESPONSE_ACTION, REASON_NO_RESPONSE_ACTION,
                meaning_name=(meaning or {}).get("meaning_name")))
        return found
