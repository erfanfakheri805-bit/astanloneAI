"""
Language Intelligence - Learned Language Guidance
======================================================
Prompt 433. One focused capability: connect the language items the
system has already learned (Prompt 416-424: learned meanings, learned
expressions, learned sentence patterns, learned pattern meanings,
resolved language relationships, recognized sentence structure) to the
response-generation path, as one small, bounded, read-only field:

    LanguageUnderstandingResult
      (learned_meanings / disambiguated_meanings / learned_pattern_match /
       learned_sentence_structure / learned_pattern_meaning - Prompt
       418-424, already attached by the backend)
      -> ResponsePlan                          (response_planning.py, 425)
      -> LearnedLanguageGuidance                (this module, 433)
      -> ResponseGenerationContext.language_guidance
         (response_generation_context.py)
      -> BackendGenerationRequest.language_guidance
         (response_generation_request.py)
      -> existing response generation

This module implements NO natural-language generation and NO new
learned-language storage, matching, resolution or disambiguation. Every
field it reports already exists somewhere on the `ResponsePlan` (itself
already read, never recomputed, from the understanding's Prompt 418-424
fields - see response_planning.py) or, for sentence structure alone, on
`understanding.learned_sentence_structure` directly - the exact same
field `BackendGenerationRequest.sentence_structure`
(response_generation_request.py) already reads, for the exact same
reason: `ResponsePlan` deliberately does not carry the full structure.
This module only reads, filters and re-shapes what is already there
into one small, labeled structure a response-generation path can
consult without re-deriving it from several separate fields itself.

Reuse map (this stage adds no storage, no matcher, no resolver, no
disambiguator and no relevance/selection mechanism of its own)
------------------------------------------------------------------
    learned pattern meaning   `ResponsePlan.meaning` / `.meaning_candidates`
                              (response_planning.py) - already the ONE
                              meaning the Prompt 424 binder resolved (or
                              every candidate the Prompt 420
                              disambiguator could not decide between).
                              REUSED verbatim; never re-bound, re-matched
                              or re-disambiguated here.
    learned expressions /
    learned meanings          `ResponsePlan.expression_meanings` - the
                              planner's own already-bounded (Prompt 425's
                              `MAX_EXPRESSION_MEANINGS`), already-filtered
                              (only expressions from the CURRENT
                              message's `entities` that have a learned
                              meaning - see response_planning.py's own
                              `_expression_meanings`) compact entries.
                              This IS the existing deterministic
                              relevance/context-selection mechanism the
                              spec asks this stage to reuse: nothing here
                              re-scans the message, re-extracts entities
                              or re-scores relevance a second way.
    resolved language
    relationships              carried inside each meaning entry's own
                              `related` list (meaning_resolution.py) -
                              copied through unchanged, never re-walked.
    recognized sentence
    structure                  `understanding.learned_sentence_structure`
                              (learned_sentence_structure.py, Prompt 422) -
                              read directly from the understanding, the
                              one field a `ResponsePlan` does not carry
                              (see response_generation_request.py's own
                              module docstring for exactly why), and
                              never re-extracted.

Nothing guessed, ever
----------------------
`build_language_guidance()` never invents a meaning, a candidate or a
structure that the plan/understanding did not already report:

    NOT_FOUND / no bound meaning at all   -> `pattern_meaning` is None
    AMBIGUOUS bound meaning                -> `pattern_meaning` is
                                             {"status": AMBIGUOUS,
                                              "meaning": None,
                                              "candidates": [...]}  -
                                             every candidate kept, none
                                             picked
    RESOLVED bound meaning                 -> {"status": RESOLVED,
                                              "meaning": {...},
                                              "candidates": []}
    no learned pattern matched at all
    (`learned_sentence_structure` status
    NOT_FOUND)                             -> `sentence_structure` is
                                             None
    an indeterminate variable boundary
    (`NOT_RESOLVED`)                       -> preserved exactly as the
                                             Prompt 422 extractor
                                             reported it, unresolved
                                             component(s) included -
                                             never split, never guessed
    several patterns/structures line up
    equally (`AMBIGUOUS`)                  -> preserved with every
                                             candidate, no components
                                             picked

`expression_meanings` follows the identical rule one level up: Prompt
425's own `_expression_meanings` already excludes any expression with
no learned meaning (NOT_FOUND) from what it reports, so this module
does too, automatically, by reusing that field rather than the raw
`learned_meanings`/`disambiguated_meanings` understanding fields.

Bounded
-------
Nothing here selects, ranks or trims anything itself:
`expression_meanings` is exactly the planner's own already-bounded list
(`MAX_EXPRESSION_MEANINGS` in response_planning.py); `pattern_meaning`
candidates are exactly the Prompt 424 binder's own already-bounded list
(`DEFAULT_MAX_MEANINGS` / `MAX_MEANINGS_LIMIT` in
learned_pattern_meaning.py, carried through the Prompt 420
disambiguator); `sentence_structure.components` is bounded by the
matched pattern's own (finite) template length. No conversation
history, no memory database, and no full copy of the language-learning
store is read or duplicated here, and none is added by this stage.

No mutable-state leakage
-------------------------
Same discipline as `ResponseGenerationContext` / `BackendGenerationRequest`:
`build_language_guidance()` reads only `response_plan.to_dict()` (already
a deep copy - see response_planning.py) plus a deep copy of
`sentence_structure`; `LearnedLanguageGuidance` stores its own deep copy
of what it is given and `to_dict()` returns a fresh deep copy on every
call. Mutating a built guidance object - or its `to_dict()` - can never
reach the `ResponsePlan`, the `LanguageUnderstandingResult`, conversation
state, or any memory/knowledge/language-learning object; and mutating
any of those after the fact never changes a guidance already built from
them.

Integration
-----------
`ResponseGenerationContext.language_guidance`
(response_generation_context.py) and, from there,
`BackendGenerationRequest.language_guidance`
(response_generation_request.py) expose this for ANY backend, built from
whatever `response_plan` (and, when available, `learned_sentence_structure`)
is already attached to the understanding - existing callers that never
look at this field are completely unaffected. Nothing about model
loading, readiness, resource guards, timeout/cancellation, backend
selection or conversation state changes because of it, and it never
generates response text itself - its only responsibility is to hand the
already-learned language information forward, structured and bounded,
for the existing response-generation process to use.
"""

import copy

from .response_planning import ResponsePlan

STATUS_RESOLVED = "RESOLVED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_NOT_FOUND = "NOT_FOUND"
ALL_STATUSES = (STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND)


def _as_dict(value):
    return value if isinstance(value, dict) else None


def _as_list(value):
    return list(value) if isinstance(value, (list, tuple)) else []


class LearnedLanguageGuidance:
    """Plain, JSON-shaped, read-only bridge object - see the module
    docstring. Same conventions as `ResponseGenerationContext`
    (response_generation_context.py) and `ResponsePlan`
    (response_planning.py): a value holder with `to_dict()`, never
    anything that validates by raising.

        pattern_meaning       {"status", "meaning", "candidates"} for the
                              learned sentence pattern's explicitly bound
                              meaning (Prompt 424), or None when nothing
                              is bound - see the module docstring's
                              "Nothing guessed, ever" section.
        expression_meanings   the message's own learned expressions/
                              meanings (Prompt 418-420), exactly as
                              `ResponsePlan.expression_meanings` already
                              bounded and filtered them; [] when none.
        sentence_structure     the recognized structure of the message
                              under a learned sentence pattern (Prompt
                              422), or None when no learned pattern
                              matched at all.
    """

    def __init__(self, pattern_meaning, expression_meanings, sentence_structure):
        self.pattern_meaning = pattern_meaning
        self.expression_meanings = expression_meanings
        self.sentence_structure = sentence_structure

    @property
    def is_empty(self):
        """True when this message carried no usable learned-language
        guidance at all - a caller may use this to skip attaching an
        empty structure to a prompt, without this module ever deciding
        that on its own."""
        return (
            self.pattern_meaning is None
            and not self.expression_meanings
            and self.sentence_structure is None
        )

    def __repr__(self):
        return (
            f"LearnedLanguageGuidance(pattern_meaning="
            f"{self.pattern_meaning['status'] if self.pattern_meaning else None!r}, "
            f"expression_meanings={len(self.expression_meanings)}, "
            f"sentence_structure="
            f"{self.sentence_structure['status'] if self.sentence_structure else None!r})"
        )

    def to_dict(self):
        """A fresh deep copy every call (see the module docstring "No
        mutable-state leakage") - mutating the returned dict can never
        change this object's own state, and this object's own state can
        never be reached through it."""
        return copy.deepcopy({
            "pattern_meaning": self.pattern_meaning,
            "expression_meanings": self.expression_meanings,
            "sentence_structure": self.sentence_structure,
        })


def _pattern_meaning_guidance(plan_data):
    """The explicitly bound pattern meaning the `ResponsePlanner`
    (response_planning.py, Prompt 424/425) already decided, reshaped as
    guidance - never re-bound, re-matched or re-disambiguated here.
    RESOLVED -> the one bound meaning; several bound meanings the Prompt
    420 disambiguator could not decide between -> AMBIGUOUS with every
    candidate preserved, none picked; no bound meaning at all (NOT_FOUND,
    or no learned pattern matched) -> None, no guidance invented."""
    meaning = plan_data.get("meaning")
    candidates = _as_list(plan_data.get("meaning_candidates"))
    if meaning is not None:
        return {"status": STATUS_RESOLVED, "meaning": meaning, "candidates": []}
    if candidates:
        return {"status": STATUS_AMBIGUOUS, "meaning": None, "candidates": candidates}
    return None


def _sentence_structure_guidance(sentence_structure):
    """The recognized structure of the message under a learned sentence
    pattern (learned_sentence_structure.py, Prompt 422), reshaped as
    guidance. NOT_FOUND (no learned pattern matched at all, or no
    structure was supplied) -> None, the same "no invented guidance"
    rule as everywhere else in this module; MATCHED / AMBIGUOUS /
    NOT_RESOLVED are preserved as reported, an unresolved component run
    included exactly as the extractor built it - never split, never
    guessed."""
    structure = _as_dict(sentence_structure)
    if structure is None or structure.get("status") == STATUS_NOT_FOUND:
        return None
    return {
        "status": structure.get("status"),
        "components": _as_list(structure.get("components")),
        "meaning": structure.get("meaning"),
        "language": structure.get("language"),
        "locale": structure.get("locale"),
        "confidence": structure.get("confidence"),
        "source": structure.get("source"),
        "candidates": _as_list(structure.get("candidates")),
        "reason": structure.get("reason"),
    }


def build_language_guidance(response_plan, sentence_structure=None):
    """The `LearnedLanguageGuidance` for `response_plan` (a
    `ResponsePlan`, or its `to_dict()`) plus `sentence_structure`
    (already-existing data - typically
    `understanding.learned_sentence_structure`, Prompt 422; never
    computed here - the same convention
    `response_generation_request.build_generation_request` already uses
    for its own `sentence_structure` field).

    Every piece is read from data the existing pipeline already
    produced: `response_plan`'s own `meaning` / `meaning_candidates` /
    `expression_meanings` (response_planning.py), and the Prompt 422
    structure extraction - nothing is guessed, matched or resolved a
    second time here. A `response_plan` that is neither a `ResponsePlan`
    nor a dict raises TypeError - the same contract
    `build_generation_context()` (response_generation_context.py)
    already follows."""
    if isinstance(response_plan, ResponsePlan):
        data = response_plan.to_dict()
    elif isinstance(response_plan, dict):
        data = copy.deepcopy(response_plan)
    else:
        raise TypeError("response_plan must be a ResponsePlan or its to_dict()")

    return LearnedLanguageGuidance(
        pattern_meaning=_pattern_meaning_guidance(data),
        expression_meanings=copy.deepcopy(_as_list(data.get("expression_meanings"))),
        sentence_structure=_sentence_structure_guidance(sentence_structure),
    )


def language_guidance_from_understanding(understanding):
    """`LearnedLanguageGuidance` for the `response_plan` already attached
    to `understanding`, enriched with
    `understanding.learned_sentence_structure` (Prompt 422) - the same
    understanding-only supplement `response_generation_request.py`
    already reads for its own `sentence_structure` field (see that
    module's own docstring for why a `ResponsePlan` alone cannot supply
    it). None when there is no plan to read yet - same as
    `generation_context_from_understanding`
    (response_generation_context.py). Never plans, matches or resolves
    anything itself; never raises for a missing plan - only
    `build_language_guidance`'s own TypeError for a plan of the wrong
    type propagates."""
    plan = getattr(understanding, "response_plan", None)
    if plan is None:
        return None
    sentence_structure = getattr(understanding, "learned_sentence_structure", None)
    return build_language_guidance(plan, sentence_structure=sentence_structure)
