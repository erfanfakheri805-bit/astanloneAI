"""
Language Intelligence - Learned Response Pattern Variable Binding
================================================================
Prompt 435. One focused capability: once Prompt 434 has selected ONE
learned response pattern, bind the variables that pattern needs to the
values the current message and the language-understanding pipeline have
ALREADY produced - or say plainly which variables could not be bound:

    LanguageUnderstandingResult                   (Prompt 397-424)
      -> ResponsePlan                             (response_planning.py, 425)
      -> LearnedLanguageGuidance                  (language_guidance.py, 433)
      -> LearnedResponsePatternSelection          (learned_response_pattern_selection.py, 434)
      -> LearnedResponsePatternBinding            (this module, 435)
      -> ResponseGenerationContext.response_pattern_binding
         (response_generation_context.py)
      -> BackendGenerationRequest.response_pattern_binding
         (response_generation_request.py)
      -> existing response generation

This module generates NO response text (a `template` is never filled in,
rendered or interpreted), stores NOTHING, learns NOTHING, reads NO store
and matches NOTHING: it does not choose a pattern (that is Prompt 434's
decision, taken as given) and it is not a second pattern matcher.
`LearnedResponsePatternBinder.bind()` is a pure function of the
plan/context dict, the guidance and the selection it is handed.

When it binds
-------------
Only when the selection is RESOLVED (exactly one selected pattern). The
selection's other states are preserved, never bound:

    selection AMBIGUOUS                  -> AMBIGUOUS, every candidate kept
    selection NOT_FOUND                  -> NOT_FOUND
    no selection at all / a RESOLVED
    selection that carries no usable
    pattern                              -> NOT_FOUND (nothing to bind)

Which variables a pattern needs (no new storage, nothing inferred)
-------------------------------------------------------------------
A learned response pattern is an entry of the `response_patterns` list
of a learned item's open stored value (Prompt 434). The binder reads
what that entry already says about its variables - nothing else:

    required_variables   a list of variable names the pattern needs
    variables            the names the pattern declares it works on
                         (Prompt 434's `variables` condition)
    template             each `{{name}}` placeholder it contains (the
                         template is only READ for names, never rendered)

The required variables are those three, de-duplicated, in that order.
A pattern that names none needs none: it is RESOLVED with nothing bound.

Where each value comes from (bounded, in this fixed order per variable)
------------------------------------------------------------------------
By default a variable takes the value the pipeline EXTRACTED for that
exact name:

    1. `ResponsePlan.variables`     (the matched learned pattern's
                                     extracted variables)
    2. the recognized sentence structure's `variable` components
       (`language_guidance.sentence_structure`, only when MATCHED)

An entry may instead route a variable to ONE named piece of context it
already carries, with `variable_sources` (`{"name": "<source>"}`); a
variable so routed is bound from that source only:

    active_topic     the active topic's text
    context_topic    the conversation context's own topic text
    reference        the verbatim text a RESOLVED reference points at
    expression       a RESOLVED learned expression of the message
    meaning          the resolved learned (pattern) meaning's name
    language         the context's language, as it reports it
    locale           the context's locale, as it reports it

An unknown source name binds nothing. Nothing else is consulted: no
store, no conversation history, no memory or knowledge lookup.

Nothing guessed, ever
----------------------
A value is bound only if it is present and non-blank. A variable with no
value stays missing; a variable whose sources hold several DIFFERENT
values (two resolved references, two resolved expressions, an extracted
value that disagrees with the structure's) is reported as conflicting -
and is missing too - because picking one would be a guess. No value is
defaulted, normalized, trimmed, translated or substituted; a bound value
is the source's own, deep-copied, exactly.

Statuses
--------
    RESOLVED    every required variable was bound. `bound_variables`
                holds them all; `selected_pattern` is preserved.
    UNRESOLVED  one or more required variables could not be bound.
                `missing_variables` names them, `conflicting_variables`
                says which of those were conflicts, and every variable
                that WAS bound is kept in `bound_variables`.
    AMBIGUOUS   the selection was AMBIGUOUS - preserved, nothing bound.
    NOT_FOUND   the selection was NOT_FOUND / unavailable - preserved,
                nothing bound.

Result (`LearnedResponsePatternBinding.to_dict()`): `status`, `reason`,
`original_message` (the message, exactly), `selected_pattern` and
`pattern_id` (the selection's, unchanged), `candidates` (AMBIGUOUS only),
`required_variables`, `bound_variables`, `missing_variables`,
`conflicting_variables`, `variable_sources` (which source each bound
variable came from), `meaning` (the plan's resolved meaning, unchanged),
`language`, `locale`, `confidence`, `source` (the selection's, unchanged)
and `truncated`.

Bounded and deterministic
--------------------------
At most `MAX_REQUIRED_VARIABLES` variables are examined; any beyond that
are reported missing (never examined, never bound) and `truncated` is
True. The same input always gives the same result: fixed source order,
taught order for names, no randomness, no clock, no confidence ranking.

No mutable-state leakage
-------------------------
Everything read is deep-copied first and `to_dict()` returns a fresh deep
copy on every call, so a caller can never reach the plan, the guidance,
the selection, the context or any store through a binding - or the other
way round.

Integration
-----------
`build_generation_context()` (response_generation_context.py) runs the
binder right after the selector, from the SAME plan, guidance and
selection, and stores the result as
`ResponseGenerationContext.response_pattern_binding`;
`build_generation_request()` (response_generation_request.py) carries it
into `BackendGenerationRequest.response_pattern_binding` unchanged. Both
fields are additive. Nothing about `ResponseGenerationResult`,
`ConversationResponse`, the local model runtime/provider, model loading,
readiness, resource limits, timeout/cancellation or backend selection
changes, and a context with no learned response pattern simply carries a
NOT_FOUND binding.
"""

import copy
import re

from .learned_response_pattern_selection import (
    LearnedResponsePatternSelection, LearnedResponsePatternSelector,
    STATUS_RESOLVED as SELECTION_RESOLVED, STATUS_AMBIGUOUS as SELECTION_AMBIGUOUS,
    STATUS_NOT_FOUND as SELECTION_NOT_FOUND,
    _as_dict, _as_list, _entry_id,
)
from .language_guidance import STATUS_RESOLVED as GUIDANCE_RESOLVED

STATUS_RESOLVED = "RESOLVED"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_NOT_FOUND = "NOT_FOUND"
ALL_STATUSES = (STATUS_RESOLVED, STATUS_UNRESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND)

REASON_ALL_BOUND = "all_required_variables_bound"
REASON_NO_VARIABLES_REQUIRED = "no_variables_required"
REASON_VARIABLES_MISSING = "required_variables_missing"
REASON_NO_SELECTION = "no_response_pattern_selection"
REASON_PATTERN_UNAVAILABLE = "selected_pattern_unavailable"

# Where a bound variable's value came from (`variable_sources[name]`).
SOURCE_EXTRACTED = "extracted"
SOURCE_ACTIVE_TOPIC = "active_topic"
SOURCE_CONTEXT_TOPIC = "context_topic"
SOURCE_REFERENCE = "reference"
SOURCE_EXPRESSION = "expression"
SOURCE_MEANING = "meaning"
SOURCE_LANGUAGE = "language"
SOURCE_LOCALE = "locale"
ROUTABLE_SOURCES = (
    SOURCE_ACTIVE_TOPIC, SOURCE_CONTEXT_TOPIC, SOURCE_REFERENCE, SOURCE_EXPRESSION,
    SOURCE_MEANING, SOURCE_LANGUAGE, SOURCE_LOCALE,
)

# The keys of a taught entry the binder reads (see the module docstring).
REQUIRED_VARIABLES_KEY = "required_variables"
VARIABLES_KEY = "variables"
TEMPLATE_KEY = "template"
VARIABLE_SOURCES_KEY = "variable_sources"

# Fixed bound: the binding's cost never depends on how much was taught.
MAX_REQUIRED_VARIABLES = 20

_PLACEHOLDER = re.compile(r"\{\{\s*([^{}\s][^{}]*?)\s*\}\}")


# ----------------------------------------------------------------------
# small helpers (pure, never raise)
# ----------------------------------------------------------------------
def _usable(value):
    """A value is bindable when it is present and, for text, non-blank.
    (Only presence is judged - the value itself is never altered.)"""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _distinct(values):
    """The usable `values`, deep-copied, identical ones folded, in order."""
    found = []
    for value in values:
        if _usable(value) and value not in found:
            found.append(copy.deepcopy(value))
    return found


def _name_list(value):
    return [n.strip() for n in _as_list(value) if isinstance(n, str) and n.strip()]


def _required_variables(entry):
    """The variable names one taught entry says it needs, de-duplicated,
    in the order of the module docstring."""
    names = _name_list(entry.get(REQUIRED_VARIABLES_KEY)) + _name_list(entry.get(VARIABLES_KEY))
    template = entry.get(TEMPLATE_KEY)
    if isinstance(template, str):
        names += [m.group(1).strip() for m in _PLACEHOLDER.finditer(template)]
    ordered = []
    for name in names:
        if name not in ordered:
            ordered.append(name)
    return ordered


class LearnedResponsePatternBinding:
    """Plain, JSON-shaped, read-only result of
    `LearnedResponsePatternBinder.bind()` - see the module docstring.
    Same conventions as `LearnedResponsePatternSelection`: a value holder
    with `to_dict()`, never anything that validates by raising."""

    def __init__(self, status, reason, original_message, selected_pattern, pattern_id,
                 candidates, required_variables, bound_variables, missing_variables,
                 conflicting_variables, variable_sources, meaning, language, locale,
                 confidence, source, truncated):
        self.status = status
        self.reason = reason
        self.original_message = original_message
        self.selected_pattern = selected_pattern
        self.pattern_id = pattern_id
        self.candidates = candidates
        self.required_variables = required_variables
        self.bound_variables = bound_variables
        self.missing_variables = missing_variables
        self.conflicting_variables = conflicting_variables
        self.variable_sources = variable_sources
        self.meaning = meaning
        self.language = language
        self.locale = locale
        self.confidence = confidence
        self.source = source
        self.truncated = truncated

    @property
    def resolved(self):
        return self.status == STATUS_RESOLVED

    @property
    def unresolved(self):
        return self.status == STATUS_UNRESOLVED

    @property
    def ambiguous(self):
        return self.status == STATUS_AMBIGUOUS

    @property
    def not_found(self):
        return self.status == STATUS_NOT_FOUND

    def __repr__(self):
        return (f"LearnedResponsePatternBinding(status={self.status!r}, "
                f"pattern_id={self.pattern_id!r}, bound={sorted(self.bound_variables)}, "
                f"missing={self.missing_variables})")

    def to_dict(self):
        """A fresh deep copy every call (see the module docstring "No
        mutable-state leakage")."""
        return copy.deepcopy({
            "status": self.status,
            "reason": self.reason,
            "original_message": self.original_message,
            "selected_pattern": self.selected_pattern,
            "pattern_id": self.pattern_id,
            "candidates": self.candidates,
            "required_variables": self.required_variables,
            "bound_variables": self.bound_variables,
            "missing_variables": self.missing_variables,
            "conflicting_variables": self.conflicting_variables,
            "variable_sources": self.variable_sources,
            "meaning": self.meaning,
            "language": self.language,
            "locale": self.locale,
            "confidence": self.confidence,
            "source": self.source,
            "truncated": self.truncated,
        })


class LearnedResponsePatternBinder:
    """Stateless and dependency-free: it owns no storage and calls no
    other system, so one instance is safe to reuse for every call."""

    def bind(self, source, selection=None, language_guidance=None):
        """The `LearnedResponsePatternBinding` for `source` - a
        `ResponsePlan`, a `ResponseGenerationContext`, or the `to_dict()`
        of either - given `selection` (a `LearnedResponsePatternSelection`
        or its `to_dict()`), else the `response_pattern_selection` the
        source already carries, and `language_guidance` (a
        `LearnedLanguageGuidance` or its `to_dict()`), else the guidance
        the source already carries or is built from (exactly as
        `LearnedResponsePatternSelector.select` reads it). Reads only
        those; never mutates them and never selects a pattern itself. A
        `source` of any other type raises TypeError - the same contract
        `build_generation_context()` already follows."""
        data = LearnedResponsePatternSelector._source_data(source)
        guidance = LearnedResponsePatternSelector._guidance(data, language_guidance)
        selection = self._selection(data, selection)
        facts = self._facts(data, guidance)

        base = {
            "original_message": data.get("original_message"),
            "meaning": copy.deepcopy(data.get("meaning")),
            "language": self._first(selection.get("language"), facts[SOURCE_LANGUAGE][0]),
            "locale": self._first(selection.get("locale"), facts[SOURCE_LOCALE][0]),
            "confidence": selection.get("confidence"),
            "source": selection.get("source"),
        }

        def result(status, reason, selected=None, candidates=(), required=(), bound=None,
                   missing=(), conflicting=(), sources=None, truncated=False):
            return LearnedResponsePatternBinding(
                status=status, reason=reason, selected_pattern=copy.deepcopy(selected),
                pattern_id=selected.get("pattern_id") if selected else None,
                candidates=copy.deepcopy(list(candidates)), required_variables=list(required),
                bound_variables=bound or {}, missing_variables=list(missing),
                conflicting_variables=list(conflicting), variable_sources=sources or {},
                truncated=truncated, **base)

        status = selection.get("status")
        if status == SELECTION_AMBIGUOUS:
            # Preserved as the selection left it: nothing is bound.
            return result(STATUS_AMBIGUOUS, selection.get("reason"),
                          candidates=_as_list(selection.get("candidates")),
                          truncated=bool(selection.get("truncated")))
        selected = _as_dict(selection.get("selected_pattern"))
        if status == SELECTION_NOT_FOUND:
            return result(STATUS_NOT_FOUND, selection.get("reason"),
                          truncated=bool(selection.get("truncated")))
        pattern = _as_dict(selected.get("pattern")) if selected else None
        if (status != SELECTION_RESOLVED or pattern is None
                or _entry_id(pattern) is None):
            reason = REASON_NO_SELECTION if not selection else REASON_PATTERN_UNAVAILABLE
            return result(STATUS_NOT_FOUND, reason)

        required = _required_variables(pattern)
        routes = _as_dict(pattern.get(VARIABLE_SOURCES_KEY)) or {}
        truncated = bool(selection.get("truncated")) or len(required) > MAX_REQUIRED_VARIABLES

        bound, sources, missing, conflicting = {}, {}, [], []
        for index, name in enumerate(required):
            if index >= MAX_REQUIRED_VARIABLES:
                missing.append(name)  # never examined, so never bound
                continue
            kind, values = self._values(name, routes.get(name), facts)
            if len(values) == 1:
                bound[name], sources[name] = values[0], kind
            else:
                missing.append(name)
                if len(values) > 1:
                    conflicting.append(name)

        if missing:
            return result(STATUS_UNRESOLVED, REASON_VARIABLES_MISSING, selected, required=required,
                          bound=bound, missing=missing, conflicting=conflicting, sources=sources,
                          truncated=truncated)
        reason = REASON_ALL_BOUND if required else REASON_NO_VARIABLES_REQUIRED
        return result(STATUS_RESOLVED, reason, selected, required=required, bound=bound,
                      sources=sources, truncated=truncated)

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------
    @staticmethod
    def _first(preferred, fallback):
        return copy.deepcopy(preferred if preferred is not None else fallback)

    @staticmethod
    def _selection(data, selection):
        """The selection to bind against, as a dict: the one handed in,
        else the one the source carries, else {} (no selection)."""
        if isinstance(selection, LearnedResponsePatternSelection):
            return selection.to_dict()
        if isinstance(selection, dict):
            return copy.deepcopy(selection)
        return copy.deepcopy(_as_dict(data.get("response_pattern_selection"))) or {}

    @staticmethod
    def _facts(data, guidance):
        """What the pipeline already knows, ready to be looked up. A fact
        it lacks is simply absent - and so can never be bound."""
        topic = _as_dict(data.get("active_topic"))
        conversation = _as_dict((_as_dict(data.get("context")) or {}).get("topic"))

        references = []
        for item in _as_list(data.get("references")):
            item = _as_dict(item)
            if item and not item.get("ambiguous"):
                references.append(item.get("resolved_context"))

        structure_values = {}
        structure = _as_dict(guidance.get("sentence_structure"))
        if structure and structure.get("status") == "MATCHED":
            for component in _as_list(structure.get("components")):
                component = _as_dict(component)
                if component and component.get("kind") == "variable" and component.get("variable_name"):
                    structure_values.setdefault(component["variable_name"], []).append(
                        component.get("value"))

        expressions = []
        for entry in _as_list(guidance.get("expression_meanings")):
            entry = _as_dict(entry)
            if entry and entry.get("status") == GUIDANCE_RESOLVED:
                expressions.append(entry.get("expression"))

        pattern_meaning = _as_dict(guidance.get("pattern_meaning"))
        resolved = (_as_dict(pattern_meaning.get("meaning"))
                    if pattern_meaning and pattern_meaning.get("status") == GUIDANCE_RESOLVED
                    else None)
        return {
            "variables": _as_dict(data.get("variables")) or {},
            "structure": structure_values,
            SOURCE_ACTIVE_TOPIC: [topic.get("topic")] if topic else [],
            SOURCE_CONTEXT_TOPIC: [conversation.get("topic")] if conversation else [],
            SOURCE_REFERENCE: references,
            SOURCE_EXPRESSION: expressions,
            SOURCE_MEANING: [(resolved or {}).get("meaning_name")],
            SOURCE_LANGUAGE: [data.get("language", data.get("detected_language"))],
            SOURCE_LOCALE: [data.get("locale")],
        }

    @staticmethod
    def _values(name, route, facts):
        """`(source kind, distinct usable values)` for one variable: the
        one source it is routed to, else the extracted values."""
        if route is None:
            found = [facts["variables"].get(name)] + list(facts["structure"].get(name, []))
            return SOURCE_EXTRACTED, _distinct(found)
        if route not in ROUTABLE_SOURCES:  # unknown (or malformed) source: nothing to bind
            return route, []
        return route, _distinct(facts[route])


def bind_learned_response_pattern(source, selection=None, language_guidance=None):
    """`LearnedResponsePatternBinder().bind(...)` as a plain function -
    the convenience `build_generation_context()` uses."""
    return LearnedResponsePatternBinder().bind(source, selection, language_guidance)


def response_pattern_binding_from_understanding(understanding):
    """The binding for the `response_plan` already attached to
    `understanding`, using the guidance and the selection Prompt 433 /
    434 build from it. None when there is no plan to read yet - same as
    `response_pattern_selection_from_understanding`. Never plans,
    matches, selects or resolves anything itself."""
    from .language_guidance import language_guidance_from_understanding
    from .learned_response_pattern_selection import select_learned_response_pattern
    plan = getattr(understanding, "response_plan", None)
    if plan is None:
        return None
    guidance = language_guidance_from_understanding(understanding)
    return bind_learned_response_pattern(plan, select_learned_response_pattern(plan, guidance),
                                         guidance)
