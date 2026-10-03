"""
Language Intelligence - Backend Generation Request
========================================================
Prompt 427. One focused capability: turn the existing, bounded
`ResponseGenerationContext` (Prompt 426) into a structured, read-only
request the SELECTED backend can consume directly - the next link in:

    LanguageUnderstandingResult
      -> ResponsePlan                         (response_planning.py, 425)
      -> ResponseGenerationContext            (response_generation_context.py, 426)
      -> BackendGenerationRequest             (this module, 427)
      -> LanguageIntelligenceBackend.generate_response()
         (DeterministicFallbackBackend / LocalLanguageModelBackend)

This still implements NO natural-language generation and NO new
planning system. Every field below already exists somewhere in the
pipeline (the `ResponseGenerationContext` or, for sentence structure
alone, `understanding.learned_sentence_structure` - Prompt 422); this
module only re-packages what is already there into the shape a
backend's own inference-request construction expects.

On the name "BackendGenerationRequest"
----------------------------------------
The project already has a `ResponseGenerationRequest`
(response_generation.py, Prompt 421) - a thin ACCESSOR over
`(understanding, context)` used to read `response_plan` /
`generation_context` off an understanding lazily. This module's type is
a different thing: a bounded, fully-materialized VALUE handed to a
backend's own request construction, one step further down the chain.
Reusing the same class name for both would make every import and
isinstance check in this codebase ambiguous, so this module's type is
named `BackendGenerationRequest` instead. `ResponseGenerationRequest`
itself gained a THIRD lazy property in Prompt 427,
`.generation_request`, that builds exactly this object - see
response_generation.py.

What it carries (all copied, nothing recomputed)
------------------------------------------------------
    original_message, status, response_action, meaning,
    meaning_candidates, matched_pattern, variables, active_topic,
    references, context, language, locale, unresolved_requirements
                            - identical to `ResponseGenerationContext`
                              (response_generation_context.py); read
                              from ITS `to_dict()`, never recomputed
    normalized_input        Prompt 617: `ResponseGenerationContext.
                            normalized_input` (itself Prompt 610,
                            forwarded verbatim from `ResponsePlan.
                            normalized_input` - Prompt 609 - which is
                            itself forwarded verbatim from
                            `LanguageUnderstandingResult.
                            normalized_input`, the existing
                            Understanding Engine's own normalization,
                            understanding/normalization.py), carried
                            through unchanged - the ONE field this
                            class was missing from that already-forwarded
                            set (every other Prompt 433-501 additive
                            field below was already present here).
                            Never recomputed or re-normalized here.
                            `None` when the context carries none (a
                            hand-built context/dict predating Prompt
                            609, or omitted on direct construction) -
                            the SAME "additive, forwarded verbatim"
                            posture `learned_knowledge_context` below
                            already uses.
                              from a `ResponsePlan` or `understanding`
                              directly.
    sentence_structure      the ONE field not already on
                            `ResponseGenerationContext`:
                            `understanding.learned_sentence_structure`
                            (Prompt 422's own bounded structure
                            extraction), copied verbatim. None when the
                            understanding carries none. This module
                            reads it directly from `understanding`
                            because Prompt 425's `ResponsePlan`
                            deliberately does not carry the full
                            structure (only, when unresolved, that
                            structure was the missing requirement -
                            see response_planning.py's
                            KIND_SENTENCE_STRUCTURE) - so a
                            `ResponseGenerationContext` alone cannot
                            supply it. Nothing here re-extracts or
                            re-derives it; a caller with no
                            `understanding` (only a bare
                            `ResponseGenerationContext`) simply gets
                            `sentence_structure=None`.
    language_guidance      Prompt 433: `ResponseGenerationContext.
                            language_guidance` (a `LearnedLanguageGuidance.
                            to_dict()` - language_guidance.py), carried
                            through unchanged. Already built from the
                            SAME `response_plan` (and, when the context
                            was built from an understanding,
                            `sentence_structure`); never rebuilt here.
    response_pattern_selection  Prompt 434: `ResponseGenerationContext.
                            response_pattern_selection` (a
                            `LearnedResponsePatternSelection.to_dict()` -
                            learned_response_pattern_selection.py),
                            carried through unchanged. Already selected
                            from the SAME `response_plan` and guidance;
                            never re-selected here.
    response_pattern_binding  Prompt 435: `ResponseGenerationContext.
                            response_pattern_binding` (a
                            `LearnedResponsePatternBinding.to_dict()` -
                            learned_response_pattern_binding.py),
                            carried through unchanged. Already bound from
                            the SAME `response_plan`, guidance and
                            selection; never re-bound here.
    used_verified_correction  Prompt 498: bool, default False - True only
                            when `ResponseGenerationRequest.
                            generation_request` (response_generation.py)
                            actually used a verified corrected response
                            target as `original_message` (Prompt 497).
                            Observability only; no text is changed by it.
    response_pattern_rendering  Prompt 436: `ResponseGenerationContext.
                            response_pattern_rendering` (a
                            `LearnedResponsePatternRendering.to_dict()` -
                            learned_response_pattern_rendering.py),
                            carried through unchanged. Already rendered
                            from the binding above - deterministic
                            learned-response output the existing response
                            generation can read; never re-rendered here.

No mutable-state leakage
-------------------------
Same discipline as `ResponseGenerationContext`: `build_generation_request()`
reads only `generation_context.to_dict()` (already a deep copy) and a
deep copy of `sentence_structure`; `BackendGenerationRequest` stores its
own deep copy of everything it is given and `to_dict()` returns a fresh
deep copy on every call. Mutating a built request - or its `to_dict()` -
can never reach the `ResponseGenerationContext`, the `ResponsePlan`, the
`LanguageUnderstandingResult`, conversation state, or any memory/
knowledge object; and mutating any of those after the fact never
changes a request already built from them.

Bounded
-------
Nothing here selects, ranks or trims anything: every field is exactly
what `ResponseGenerationContext` (itself exactly what `ResponsePlan`,
itself exactly what the existing understanding pipeline) already
bounded - see response_generation_context.py and response_planning.py.
`sentence_structure` is the Prompt 422 extractor's own single-message
structure, never conversation history, never a memory or knowledge
dump.

Ambiguous / unresolved states
------------------------------
Preserved exactly as `ResponseGenerationContext` preserves them:
`status` is copied as-is, `response_action` is only ever non-None when
the context's already was (a RESOLVED plan with an explicit action -
see response_planning.py), and `meaning_candidates` /
`unresolved_requirements` are carried through unpicked, unfiltered.

Backend integration
-----------------------
`local_model_backend.py`'s `generate_response()` builds this (via
`generation_request_from_understanding`) and forwards it into
`build_inference_request()` (local_model_mapping.py), which attaches it
to `InferenceRequest.generation_request` (inference.py) - additional
structured input alongside the already-existing `generation_context`
field (426) and the prompt/conversation this function already builds;
nothing about model loading, readiness, resource guards, timeout/
cancellation or fallback selection changes because of it.
`ResponseGenerationRequest.generation_request` (response_generation.py)
makes the SAME object available through the one existing accessor for
ANY backend, the deterministic fallback backend included - it still
returns STATUS_DEFERRED and generates no text; nothing requires it to
read this field.
"""

import copy

from .response_generation_context import (
    ResponseGenerationContext, generation_context_from_understanding,
)
from .response_planning import STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED


class BackendGenerationRequest:
    """The bounded, read-only value handed to a backend's own request
    construction - see the module docstring. Same conventions as
    `ResponseGenerationContext` (response_generation_context.py) and
    `LanguageContext` (language_context.py): a value holder with
    `to_dict()`, never anything that validates by raising."""

    def __init__(self, original_message, status, response_action, meaning, meaning_candidates,
                 matched_pattern, sentence_structure, variables, active_topic, references,
                 context, language, locale, unresolved_requirements, language_guidance=None,
                 response_pattern_selection=None, response_pattern_binding=None,
                 response_pattern_rendering=None, used_verified_correction=False,
                 learned_knowledge_context=None, normalized_input=None):
        self.original_message = original_message
        self.status = status
        self.response_action = response_action
        self.meaning = meaning
        self.meaning_candidates = meaning_candidates
        self.matched_pattern = matched_pattern
        self.sentence_structure = sentence_structure
        self.variables = variables
        self.active_topic = active_topic
        self.references = references
        self.context = context
        self.language = language
        self.locale = locale
        self.unresolved_requirements = unresolved_requirements
        # Prompt 433: ResponseGenerationContext.language_guidance, carried
        # through unchanged (see this module's build_generation_request) -
        # None when the context had none. Additive; every field above is
        # unchanged.
        self.language_guidance = language_guidance
        # Prompt 434: ResponseGenerationContext.response_pattern_selection,
        # carried through unchanged - None when the context had none.
        # Additive; every field above is unchanged.
        self.response_pattern_selection = response_pattern_selection
        # Prompt 435: ResponseGenerationContext.response_pattern_binding,
        # carried through unchanged - None when the context had none.
        # Additive; every field above is unchanged.
        self.response_pattern_binding = response_pattern_binding
        # Prompt 436: ResponseGenerationContext.response_pattern_rendering,
        # carried through unchanged - None when the context had none.
        # Additive; every field above is unchanged.
        self.response_pattern_rendering = response_pattern_rendering
        # Prompt 498: observability only - True exactly when a verified
        # corrected response target was actually used as this request's
        # input (`original_message` holds it; set by
        # ResponseGenerationRequest.generation_request, Prompt 497),
        # False otherwise (the default). Never True merely because
        # correction data exists somewhere; never changes any other field
        # or any generated text. Additive; every field above is unchanged.
        self.used_verified_correction = used_verified_correction
        # Prompt 501: ResponseGenerationContext.learned_knowledge_context,
        # carried through unchanged - None when the context had none (the
        # common case). Additive; every field above is unchanged.
        self.learned_knowledge_context = learned_knowledge_context
        # Prompt 617: ResponseGenerationContext.normalized_input, carried
        # through unchanged - None when the context had none. Additive;
        # every field above is unchanged. See the module docstring's
        # `normalized_input` entry.
        self.normalized_input = normalized_input

    @property
    def resolved(self):
        return self.status == STATUS_RESOLVED

    @property
    def ambiguous(self):
        return self.status == STATUS_AMBIGUOUS

    @property
    def unresolved(self):
        return self.status == STATUS_UNRESOLVED

    def __repr__(self):
        return (f"BackendGenerationRequest(status={self.status!r}, "
                f"response_action={self.response_action!r})")

    def to_dict(self):
        """A fresh deep copy every call - see the module docstring "No
        mutable-state leakage"."""
        return copy.deepcopy({
            "original_message": self.original_message,
            "status": self.status,
            "response_action": self.response_action,
            "meaning": self.meaning,
            "meaning_candidates": self.meaning_candidates,
            "matched_pattern": self.matched_pattern,
            "sentence_structure": self.sentence_structure,
            "variables": self.variables,
            "active_topic": self.active_topic,
            "references": self.references,
            "context": self.context,
            "language": self.language,
            "locale": self.locale,
            "unresolved_requirements": self.unresolved_requirements,
            "language_guidance": self.language_guidance,
            "response_pattern_selection": self.response_pattern_selection,
            "response_pattern_binding": self.response_pattern_binding,
            "response_pattern_rendering": self.response_pattern_rendering,
            "used_verified_correction": self.used_verified_correction,
            "learned_knowledge_context": self.learned_knowledge_context,
            "normalized_input": self.normalized_input,
        })


def build_generation_request(generation_context, sentence_structure=None):
    """The `BackendGenerationRequest` for `generation_context` (a
    `ResponseGenerationContext`, or its `to_dict()`) plus
    `sentence_structure` (already-existing data - see the module
    docstring; never computed here). Every `ResponseGenerationContext`
    field is copied verbatim; this function additionally deep-copies
    everything it stores, so the returned request shares no mutable
    structure with `generation_context` or `sentence_structure` even
    when a caller passes a live object it later mutates. A
    `generation_context` that is neither raises TypeError - the same
    contract `build_generation_context()` already follows."""
    if isinstance(generation_context, ResponseGenerationContext):
        data = generation_context.to_dict()
    elif isinstance(generation_context, dict):
        data = copy.deepcopy(generation_context)
    else:
        raise TypeError(
            "generation_context must be a ResponseGenerationContext or its to_dict()")

    return BackendGenerationRequest(
        original_message=data.get("original_message"),
        status=data.get("status"),
        response_action=data.get("response_action"),
        meaning=data.get("meaning"),
        meaning_candidates=list(data.get("meaning_candidates") or []),
        matched_pattern=data.get("matched_pattern"),
        sentence_structure=copy.deepcopy(sentence_structure),
        variables=dict(data.get("variables") or {}),
        active_topic=data.get("active_topic"),
        references=list(data.get("references") or []),
        context=data.get("context"),
        language=data.get("language"),
        locale=data.get("locale"),
        unresolved_requirements=list(data.get("unresolved_requirements") or []),
        # Prompt 433: already built by ResponseGenerationContext (from the
        # SAME response_plan) - carried through unchanged, never rebuilt.
        language_guidance=copy.deepcopy(data.get("language_guidance")),
        # Prompt 434: already selected by ResponseGenerationContext - carried
        # through unchanged, never re-selected.
        response_pattern_selection=copy.deepcopy(data.get("response_pattern_selection")),
        # Prompt 435: already bound by ResponseGenerationContext - carried
        # through unchanged, never re-bound.
        response_pattern_binding=copy.deepcopy(data.get("response_pattern_binding")),
        # Prompt 436: already rendered by ResponseGenerationContext - carried
        # through unchanged, never re-rendered.
        response_pattern_rendering=copy.deepcopy(data.get("response_pattern_rendering")),
        # Prompt 498: carried through when a caller round-trips a
        # `to_dict()`; only an actual True counts, anything else (absent,
        # None, truthy non-bool) is the default False.
        used_verified_correction=data.get("used_verified_correction") is True,
        # Prompt 501: already carried by ResponseGenerationContext - copied
        # through unchanged, never looked up or re-selected.
        learned_knowledge_context=copy.deepcopy(data.get("learned_knowledge_context")),
        # Prompt 617: already carried by ResponseGenerationContext (itself
        # Prompt 610, forwarded verbatim from the existing understanding's
        # normalized_input) - copied through unchanged, never recomputed
        # or re-normalized here.
        normalized_input=data.get("normalized_input"),
    )


def generation_request_from_understanding(understanding):
    """`BackendGenerationRequest` for the `response_plan` already
    attached to `understanding`, enriched with `understanding.
    learned_sentence_structure` (Prompt 422 - the one field a
    `ResponseGenerationContext` alone cannot supply; see the module
    docstring). None when `understanding` carries no plan (see
    `generation_context_from_understanding`,
    response_generation_context.py). Never plans, matches or extracts
    anything itself; never raises for a missing plan - only
    `build_generation_request`'s own TypeError for a value of the
    wrong type propagates."""
    context = generation_context_from_understanding(understanding)
    if context is None:
        return None
    sentence_structure = getattr(understanding, "learned_sentence_structure", None)
    return build_generation_request(context, sentence_structure=sentence_structure)
