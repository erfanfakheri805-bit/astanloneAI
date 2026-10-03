"""
Language Intelligence - Learned Response Pattern Rendering
==========================================================
Prompt 436. One focused capability: once Prompt 434 has selected ONE
learned response pattern and Prompt 435 has bound every variable that
pattern needs, turn the pattern's own `template` plus those bound values
into a response text - or say plainly why no text can be rendered:

    LanguageUnderstandingResult                   (Prompt 397-424)
      -> ResponsePlan                             (response_planning.py, 425)
      -> LearnedLanguageGuidance                  (language_guidance.py, 433)
      -> LearnedResponsePatternSelection          (learned_response_pattern_selection.py, 434)
      -> LearnedResponsePatternBinding            (learned_response_pattern_binding.py, 435)
      -> LearnedResponsePatternRendering          (this module, 436)
      -> ResponseGenerationContext.response_pattern_rendering
         (response_generation_context.py)
      -> BackendGenerationRequest.response_pattern_rendering
         (response_generation_request.py)
      -> existing response generation

This module is a plain string substitution. It calls no AI model, uses no
probabilistic generation and no network, stores NOTHING, learns NOTHING,
reads NO store, selects NO pattern and binds NO variable (both are taken
as given from Prompts 434 / 435), interprets NOTHING and creates no
language knowledge. `LearnedResponsePatternRenderer.render()` is a pure
function of the binding it is handed.

What it renders
---------------
Only a RESOLVED binding: exactly one selected pattern whose required
variables were all bound. The pattern is the one the binding preserved
(`selected_pattern["pattern"]`), exactly as taught; its `template` is a
text containing `{{name}}` placeholders (the same placeholder syntax
Prompt 435 reads names from). Every placeholder is replaced by the
bound value of that exact name, and nothing else is touched: the text
between placeholders is copied character for character, a `{{...}}` that
appears INSIDE a bound value is never expanded (substitution is a single
pass), and no whitespace, casing, punctuation or language is adjusted.
The rendered text therefore consists of the template's own text and the
bound values - never anything else.

Statuses (same vocabulary as Prompt 434 / 435)
-----------------------------------------------
    RESOLVED    the template was rendered: `rendered_text` is set,
                `failure_reason` is None.
    UNRESOLVED  a placeholder has no usable bound value: the binding
                itself is UNRESOLVED, or the template names a variable
                the binding did not bind (or bound to blank / a value
                that is not text or a number, which cannot be placed in
                a sentence without guessing). `missing_variables` names
                every such variable. NO text - not even a partial or a
                guessed one - is produced.
    AMBIGUOUS   the binding was AMBIGUOUS: preserved (every candidate
                kept), nothing rendered.
    NOT_FOUND   the binding was NOT_FOUND / unavailable, there is no
                binding at all, or the selected pattern is empty /
                invalid (no usable id, or no non-blank text `template`):
                nothing rendered, nothing invented.

A pattern with a template but no placeholders needs no variables and is
RESOLVED with its template as the text.

Result (`LearnedResponsePatternRendering.to_dict()`): `status`,
`rendered_text`, `pattern_id`, `bound_variables` (the binding's, exactly,
unchanged), `missing_variables`, `language`, `locale` (the binding's,
unchanged), `failure_reason` (None on success; on AMBIGUOUS / NOT_FOUND
the binding's own reason is preserved when it has one), `candidates`
(AMBIGUOUS only), `original_message`, `confidence`, `source` (the
selection's, unchanged) and `metadata`. `metadata` carries only what
already exists: `output_kind` (`OUTPUT_KIND` when text was rendered,
else None - rendered text is deterministic learned-response output, not
model output), `template_variables`, `variable_sources`, `origin` and
`matched_on` (the selection's), the pattern's own `metadata` dict when it
was taught one, `binding_status`, `binding_reason` and `truncated`.

Deterministic
-------------
The same binding always gives the same result: placeholders are
substituted in one left-to-right pass, missing names are reported in
template order, no randomness, no clock.

No mutable-state leakage
-------------------------
Everything read is deep-copied first and `to_dict()` returns a fresh deep
copy on every call, so a caller can never reach the binding, the
selection, the plan or any store through a rendering - or the other way
round.

Integration
-----------
`build_generation_context()` (response_generation_context.py) runs the
renderer right after the binder, from the binding just built, and stores
the result as `ResponseGenerationContext.response_pattern_rendering`;
`build_generation_request()` (response_generation_request.py) carries it
into `BackendGenerationRequest.response_pattern_rendering` unchanged, so
the existing response-generation layer can read the rendered text as
structured information without rendering anything itself. Both fields are
additive. Nothing about `ResponseGenerationResult`, `ConversationResponse`,
the local model runtime/provider/backend, model loading, readiness,
resource limits, timeout/cancellation or backend selection changes, and
a context with no learned response pattern simply carries a NOT_FOUND
rendering.
"""

import copy

from .learned_response_pattern_binding import (
    LearnedResponsePatternBinding,
    STATUS_RESOLVED as BINDING_RESOLVED, STATUS_UNRESOLVED as BINDING_UNRESOLVED,
    STATUS_AMBIGUOUS as BINDING_AMBIGUOUS, STATUS_NOT_FOUND as BINDING_NOT_FOUND,
    TEMPLATE_KEY, _PLACEHOLDER, _usable,
)
from .learned_response_pattern_selection import _as_dict, _as_list, _entry_id

STATUS_RESOLVED = "RESOLVED"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_NOT_FOUND = "NOT_FOUND"
ALL_STATUSES = (STATUS_RESOLVED, STATUS_UNRESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND)

REASON_VARIABLES_MISSING = "required_variables_missing"
REASON_VARIABLE_NOT_RENDERABLE = "variable_value_not_renderable"
REASON_NO_BINDING = "no_response_pattern_binding"
REASON_BINDING_UNAVAILABLE = "response_pattern_binding_unavailable"
REASON_PATTERN_UNAVAILABLE = "selected_pattern_unavailable"
REASON_NO_TEMPLATE = "pattern_has_no_template"
REASON_BINDING_AMBIGUOUS = "response_pattern_binding_ambiguous"

# `metadata["output_kind"]` of a rendering that produced text.
OUTPUT_KIND = "deterministic_learned_response"


def _renderable(value):
    """A bound value can be placed in a sentence only if it is non-blank
    text or a number. (Nothing is converted beyond `str()` of a number.)"""
    if isinstance(value, bool) or not _usable(value):
        return False
    return isinstance(value, (str, int, float))


class LearnedResponsePatternRendering:
    """Plain, JSON-shaped, read-only result of
    `LearnedResponsePatternRenderer.render()` - see the module docstring.
    Same conventions as `LearnedResponsePatternBinding`: a value holder
    with `to_dict()`, never anything that validates by raising."""

    def __init__(self, status, rendered_text, pattern_id, bound_variables, missing_variables,
                 language, locale, failure_reason, candidates, original_message, confidence,
                 source, metadata):
        self.status = status
        self.rendered_text = rendered_text
        self.pattern_id = pattern_id
        self.bound_variables = bound_variables
        self.missing_variables = missing_variables
        self.language = language
        self.locale = locale
        self.failure_reason = failure_reason
        self.candidates = candidates
        self.original_message = original_message
        self.confidence = confidence
        self.source = source
        self.metadata = metadata

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
        return (f"LearnedResponsePatternRendering(status={self.status!r}, "
                f"pattern_id={self.pattern_id!r}, missing={self.missing_variables})")

    def to_dict(self):
        """A fresh deep copy every call (see the module docstring "No
        mutable-state leakage")."""
        return copy.deepcopy({
            "status": self.status,
            "rendered_text": self.rendered_text,
            "pattern_id": self.pattern_id,
            "bound_variables": self.bound_variables,
            "missing_variables": self.missing_variables,
            "language": self.language,
            "locale": self.locale,
            "failure_reason": self.failure_reason,
            "candidates": self.candidates,
            "original_message": self.original_message,
            "confidence": self.confidence,
            "source": self.source,
            "metadata": self.metadata,
        })


class LearnedResponsePatternRenderer:
    """Stateless and dependency-free: it owns no storage and calls no
    other system, so one instance is safe to reuse for every call."""

    def render(self, binding):
        """The `LearnedResponsePatternRendering` for `binding` - a
        `LearnedResponsePatternBinding` or its `to_dict()`. None (no
        binding) is NOT_FOUND; any other type raises TypeError, the same
        contract `build_generation_context()` already follows. Reads only
        the binding; never mutates it and never selects or binds
        anything itself."""
        if binding is None:
            data = {}
        elif isinstance(binding, LearnedResponsePatternBinding):
            data = binding.to_dict()
        elif isinstance(binding, dict):
            data = copy.deepcopy(binding)
        else:
            raise TypeError("binding must be a LearnedResponsePatternBinding or its to_dict()")

        status = data.get("status")
        bound = _as_dict(data.get("bound_variables")) or {}
        selected = _as_dict(data.get("selected_pattern"))
        pattern = _as_dict(selected.get("pattern")) if selected else None

        metadata = {
            "output_kind": None,
            "template_variables": [],
            "variable_sources": copy.deepcopy(_as_dict(data.get("variable_sources")) or {}),
            "origin": copy.deepcopy(selected.get("origin")) if selected else None,
            "matched_on": copy.deepcopy(selected.get("matched_on")) if selected else None,
            "binding_status": status,
            "binding_reason": data.get("reason"),
            "truncated": bool(data.get("truncated")),
        }
        if pattern and isinstance(pattern.get("metadata"), dict):
            metadata["pattern_metadata"] = copy.deepcopy(pattern["metadata"])

        def result(out_status, text=None, missing=(), reason=None, candidates=()):
            return LearnedResponsePatternRendering(
                status=out_status, rendered_text=text,
                pattern_id=data.get("pattern_id"), bound_variables=copy.deepcopy(bound),
                missing_variables=list(missing), language=copy.deepcopy(data.get("language")),
                locale=copy.deepcopy(data.get("locale")), failure_reason=reason,
                candidates=copy.deepcopy(list(candidates)),
                original_message=data.get("original_message"),
                confidence=copy.deepcopy(data.get("confidence")),
                source=copy.deepcopy(data.get("source")), metadata=metadata)

        if status == BINDING_AMBIGUOUS:
            # Preserved as the binding left it: nothing is rendered.
            return result(STATUS_AMBIGUOUS, reason=data.get("reason") or REASON_BINDING_AMBIGUOUS,
                          candidates=_as_list(data.get("candidates")))
        if status == BINDING_NOT_FOUND:
            return result(STATUS_NOT_FOUND, reason=data.get("reason") or REASON_BINDING_UNAVAILABLE)
        if status == BINDING_UNRESOLVED:
            return result(STATUS_UNRESOLVED, reason=REASON_VARIABLES_MISSING,
                          missing=_as_list(data.get("missing_variables")))
        if status != BINDING_RESOLVED:
            return result(STATUS_NOT_FOUND,
                          reason=REASON_BINDING_UNAVAILABLE if data else REASON_NO_BINDING)

        if pattern is None or _entry_id(pattern) is None:
            return result(STATUS_NOT_FOUND, reason=REASON_PATTERN_UNAVAILABLE)
        template = pattern.get(TEMPLATE_KEY)
        if not isinstance(template, str) or not template.strip():
            return result(STATUS_NOT_FOUND, reason=REASON_NO_TEMPLATE)

        names = []
        for match in _PLACEHOLDER.finditer(template):
            name = match.group(1).strip()
            if name not in names:
                names.append(name)
        metadata["template_variables"] = list(names)

        missing = [n for n in names if n not in bound]
        unrenderable = [n for n in names if n in bound and not _renderable(bound[n])]
        if missing or unrenderable:
            reason = REASON_VARIABLES_MISSING if missing else REASON_VARIABLE_NOT_RENDERABLE
            return result(STATUS_UNRESOLVED, reason=reason,
                          missing=[n for n in names if n in missing or n in unrenderable])

        # One left-to-right pass: a value is never re-scanned for placeholders.
        text = _PLACEHOLDER.sub(lambda m: str(bound[m.group(1).strip()]), template)
        metadata["output_kind"] = OUTPUT_KIND
        return result(STATUS_RESOLVED, text=text)


def render_learned_response_pattern(binding):
    """`LearnedResponsePatternRenderer().render(...)` as a plain function -
    the convenience `build_generation_context()` uses."""
    return LearnedResponsePatternRenderer().render(binding)


def response_pattern_rendering_from_understanding(understanding):
    """The rendering for the `response_plan` already attached to
    `understanding`, using the binding Prompt 435 builds from it. None
    when there is no plan to read yet - same as
    `response_pattern_binding_from_understanding`. Never plans, matches,
    selects, binds or resolves anything itself."""
    from .learned_response_pattern_binding import response_pattern_binding_from_understanding
    binding = response_pattern_binding_from_understanding(understanding)
    if binding is None:
        return None
    return render_learned_response_pattern(binding)
