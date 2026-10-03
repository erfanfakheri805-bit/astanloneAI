"""
Language Intelligence - Learned Meaning Disambiguation
==========================================================
Prompt 420. When the Learned Meaning Resolution system (Prompt 418,
meaning_resolution.py) reports more than one learned meaning for the
same expression, something has to decide - deterministically, without
guessing - which of those candidates the current message is actually
using, or admit that it cannot tell yet. This module is that "something".

It is NOT a second meaning resolver: it never touches the
LanguageLearningStore or the LanguageRelationshipStore itself. It takes
a `MeaningResolutionResult` (or its `to_dict()`) that
`MeaningResolver.resolve()` - REUSED, never re-implemented - already
produced, and narrows/labels it using only information the project
already computes elsewhere:

    language/locale            - the same `language` MeaningResolver.
                                 resolve() was (or would be) called
                                 with, or an explicit `preferred_language`
                                 hint (e.g. the current conversation's
                                 detected language)
    current message context    - the other candidate expressions found
                                 in the same message (`nearby_expressions`
                                 - REUSED from the Understanding Engine's
                                 own `entities`, never re-extracted)
    active topic                - `context.active_topic.ActiveTopicResult`
                                 (Prompt 393) or its `.to_dict()`, REUSED
    conversation context         - `context.conversation_context.
                                 ConversationContext` (or anything with
                                 the same `get_recent_turns()` read
                                 interface), REUSED
    resolved references          - `context.message_reference_resolution.
                                 ResolvedReference` (Prompt 392) or its
                                 `.to_dict()`, REUSED
    stored context/usage examples - each candidate's OWN already-stored
                                 `examples` / `source_context` (Prompt
                                 416) - REUSED, never new data

Do NOT invent semantic interpretation
--------------------------------------
The only thing this module does with all of the above is turn each
piece into a small, deterministic bag of words
(`understanding.term_extraction.extract_candidate_terms` - REUSED, the
exact same tokenizer/stopword list `context/active_topic.py` already
uses) and count how many of those words a candidate's own stored
meaning/examples/source_context also contains. That count is the
"simple bounded deterministic matching mechanism" the spec calls for
when no project-wide relevance score already exists - a plain,
inspectable integer, never a probability, never a confidence value
that claims more precision than a word-overlap count actually has.
There is no machine-learning classifier, no fuzzy matching and no
embedding anywhere in this module.

Statuses
--------
Reuses `STATUS_RESOLVED` / `STATUS_NOT_FOUND` from meaning_resolution.py
(so a caller checking against those two constants still works exactly
as before) and adds exactly one more, `STATUS_AMBIGUOUS`, for the one
case Prompt 418 could not represent on its own: several learned
meanings exist and nothing available distinguishes them.

    STATUS_RESOLVED    exactly one candidate applies - because only one
                       was ever learned (Prompt 418's existing case), or
                       because language/context deterministically
                       singled one out
    STATUS_AMBIGUOUS   more than one candidate applies and nothing
                       available (language, context terms, or the
                       context terms that ARE available) distinguishes
                       between them; `candidates` still carries every one
                       of them, never collapsed and never guessed at
    STATUS_NOT_FOUND   the underlying resolution itself was NOT_FOUND
                       (unchanged from meaning_resolution.py)

Decision order (first match wins; fixed, no scoring model beyond the
one small word-overlap count described above):

    1. Zero learned meanings                  -> NOT_FOUND (passthrough)
    2. Exactly one learned meaning             -> RESOLVED, that one
    3. Several meanings, a preferred/explicit
       language narrows them to exactly one    -> RESOLVED, that one
    4. Several meanings, no context terms are
       available at all                        -> AMBIGUOUS
    5. Several meanings, every candidate's
       word-overlap score is 0                 -> AMBIGUOUS
    6. Several meanings, exactly one candidate
       has the (positive) top score            -> RESOLVED, that one
    7. Several meanings, more than one shares
       the top score (a tie)                   -> AMBIGUOUS

Original message preservation: nothing in this module ever reads,
rewrites or returns the raw message text - only the already-extracted
expression string the resolution carries, and small word sets derived
from context. The caller's original message is never touched here.

Integration: `deterministic_fallback_backend.py` (Prompt 419's own
integration point) is the only other module that calls this one - see
its `_disambiguate_learned_meanings`. Nothing in the Understanding
Engine, Conversation Context, Active Topic or Reference Resolution
modules themselves is changed; each is only ever read through its own
existing public shape (`.to_dict()`, `get_recent_turns()`, plain
attributes).
"""

import json

from understanding.term_extraction import extract_candidate_terms

from .meaning_resolution import STATUS_RESOLVED, STATUS_NOT_FOUND

STATUS_AMBIGUOUS = "AMBIGUOUS"
ALL_STATUSES = (STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND)

# Reasons - fixed, inspectable strings, same "debugging string" convention
# used throughout context/ and language_intelligence/ (ActiveTopicResult.
# reason, ResolvedReference.reason, MeaningResolutionResult.reason).
REASON_NOT_FOUND = "underlying_resolution_not_found"
REASON_SINGLE_MEANING = "single_learned_meaning"
REASON_LANGUAGE_NARROWED = "language_narrowed_to_single_candidate"
REASON_NO_CONTEXT_TERMS = "insufficient_context_no_terms_available"
REASON_NO_CANDIDATE_MATCHED = "no_candidate_matched_available_context"
REASON_CONTEXT_MATCHED = "context_matched_unique_candidate"
REASON_CONTEXT_TIED = "context_insufficient_to_distinguish"

# Small, fixed bounds - keeps this stage's cost independent of how much
# conversation/context history happens to exist, same spirit as
# meaning_resolution.py's own MAX_MATCHED_ITEMS / MAX_RELATED_LIMIT.
DEFAULT_MAX_CONTEXT_TURNS = 3
MAX_CONTEXT_TERMS = 50


def _terms(text):
    """Deterministic bag of words for one piece of text - empty set for
    anything blank/None. Never raises on a non-string (coerced to
    str first) since some inputs (a stored `meaning`) are caller-shaped
    JSON, not guaranteed text."""
    if text is None:
        return set()
    text = text if isinstance(text, str) else str(text)
    if not text.strip():
        return set()
    return set(extract_candidate_terms(text))


def _stringify_meaning(value):
    """A stored `meaning` is an arbitrary JSON-safe value (Prompt 416) -
    never interpreted, only turned into text so its words can be
    compared like any other stored text. A dict/list is serialized
    (stable, deterministic); anything already text-like passes through
    unchanged."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _as_dict_or_none(value):
    """Accept either a plain dict (already `.to_dict()`-shaped) or an
    object exposing `.to_dict()` - the same duck-typed convention the
    rest of this package's `context=...` arguments already follow."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return None


def _recent_turns(conversation_context, max_turns):
    """`conversation_context` may be a real ConversationContext (has
    `get_recent_turns`), a plain list of `{"user": ..., "assistant":
    ...}` dicts, or None. Always returns a plain list, oldest-first,
    bounded to `max_turns`."""
    if conversation_context is None:
        return []
    get_recent = getattr(conversation_context, "get_recent_turns", None)
    if callable(get_recent):
        return get_recent(limit=max_turns) or []
    if isinstance(conversation_context, (list, tuple)):
        turns = list(conversation_context)
        return turns[-max_turns:] if max_turns else turns
    return []


def collect_context_terms(active_topic=None, conversation_context=None, resolved_reference=None,
                           nearby_expressions=None, max_turns=DEFAULT_MAX_CONTEXT_TURNS,
                           max_terms=MAX_CONTEXT_TERMS):
    """The bounded, deterministic bag of words this stage is allowed to
    use for disambiguation - see the module docstring's "current
    message context" list. Every argument is optional and read-only;
    nothing here is ever written back to any of them. Returns a
    (regular, unordered) set of lowercase terms, capped at `max_terms`
    so a very long conversation can never make one lookup unbounded."""
    terms = set()

    topic_dict = _as_dict_or_none(active_topic)
    if topic_dict is not None:
        terms |= _terms(topic_dict.get("topic"))
    elif isinstance(active_topic, str):
        terms |= _terms(active_topic)

    ref_dict = _as_dict_or_none(resolved_reference)
    if ref_dict is not None:
        terms |= _terms(ref_dict.get("resolved_context"))

    for turn in _recent_turns(conversation_context, max_turns):
        if isinstance(turn, dict):
            terms |= _terms(turn.get("user"))

    for expression in (nearby_expressions or []):
        terms |= _terms(expression)

    if len(terms) > max_terms:
        # Deterministic truncation: sorted() gives the same subset every
        # time for the same input set, never an arbitrary/undefined one.
        terms = set(sorted(terms)[:max_terms])
    return terms


def _candidate_terms(meaning_entry):
    """The stored, uninterpreted words available about one candidate:
    its own `meaning`, `examples`, and `source_context` - all Prompt
    416 data, never anything derived or guessed here."""
    parts = [_stringify_meaning(meaning_entry.get("meaning"))]
    for example in meaning_entry.get("examples") or []:
        parts.append(example if isinstance(example, str) else _stringify_meaning(example))
    source_context = meaning_entry.get("source_context")
    if source_context:
        parts.append(source_context if isinstance(source_context, str) else str(source_context))
    return _terms(" ".join(p for p in parts if p))


def _score(meaning_entry, context_terms):
    """Simple bounded deterministic matching: how many of the available
    context terms also appear in what is stored about this candidate.
    A plain overlap count - never a probability, never normalized into
    something that looks like a confidence."""
    if not context_terms:
        return 0
    return len(_candidate_terms(meaning_entry) & context_terms)


class DisambiguationResult:
    """Plain, JSON-shaped result - same `to_dict()` convention as
    MeaningResolutionResult and every other structured result in this
    project. Never constructed directly by a caller;
    `LearnedMeaningDisambiguator.disambiguate()` returns these.

        status              STATUS_RESOLVED / STATUS_AMBIGUOUS /
                            STATUS_NOT_FOUND
        expression          the expression exactly as the underlying
                            resolution carried it - never rewritten
        language            the resolution's own `language` (may be
                            None - see meaning_resolution.py)
        item_type           the resolution's own `item_type`
        candidates          every learned meaning the resolution found
                            (MeaningResolutionResult.meanings, REUSED
                            unchanged) - never collapsed, even when one
                            of them was selected below
        resolved_meaning    the one candidate this stage could
                            deterministically identify, or None when
                            AMBIGUOUS/NOT_FOUND - never a guess
        matched_items       passthrough of the resolution's own
                            `matched_items`
        reason              one of the REASON_* constants above
        context_terms_used  the bounded context word set actually
                            available for this decision (sorted, for a
                            stable/inspectable result), [] when none
        candidate_scores    {candidate id: overlap score}, {} when
                            context scoring never ran (single meaning,
                            language-narrowed, or no context terms)
        truncated           passthrough of the resolution's own
                            `truncated`
        limits              passthrough of the resolution's own
                            `limits`
    """

    def __init__(self, status, expression, language, item_type, candidates, resolved_meaning,
                 matched_items, reason, context_terms_used, candidate_scores, truncated, limits):
        self.status = status
        self.expression = expression
        self.language = language
        self.item_type = item_type
        self.candidates = candidates
        self.resolved_meaning = resolved_meaning
        self.matched_items = matched_items
        self.reason = reason
        self.context_terms_used = context_terms_used
        self.candidate_scores = candidate_scores
        self.truncated = truncated
        self.limits = limits

    @property
    def resolved(self):
        return self.status == STATUS_RESOLVED

    @property
    def ambiguous(self):
        return self.status == STATUS_AMBIGUOUS

    def __repr__(self):
        return (
            f"DisambiguationResult(status={self.status!r}, expression={self.expression!r}, "
            f"candidates={len(self.candidates)}, reason={self.reason!r})"
        )

    def to_dict(self):
        return {
            "status": self.status,
            "expression": self.expression,
            "language": self.language,
            "item_type": self.item_type,
            "candidates": self.candidates,
            "resolved_meaning": self.resolved_meaning,
            "matched_items": self.matched_items,
            "reason": self.reason,
            "context_terms_used": self.context_terms_used,
            "candidate_scores": self.candidate_scores,
            "truncated": self.truncated,
            "limits": self.limits,
        }


class LearnedMeaningDisambiguator:
    """Composes no storage of its own - a small deterministic layer
    over a `MeaningResolutionResult` that `MeaningResolver.resolve()`
    already produced. Stateless: safe to reuse one instance for every
    call, same convention as `UnderstandingEngine`."""

    def disambiguate(self, resolution, language=None, active_topic=None, conversation_context=None,
                      resolved_reference=None, nearby_expressions=None, preferred_language=None,
                      max_context_turns=DEFAULT_MAX_CONTEXT_TURNS):
        """`resolution` is a `MeaningResolutionResult` (or its
        `.to_dict()`) already produced by `MeaningResolver.resolve()` -
        REUSED, never re-resolved here. `language` should be the same
        language the resolver was (or would be) called with;
        `preferred_language` is an independent hint (e.g. the current
        conversation's detected language) used only to narrow between
        several already-found candidates - see the module docstring's
        decision order. Every other argument is optional, read-only
        context - see `collect_context_terms`. Never raises for a
        malformed piece of context (a bad `active_topic`/
        `conversation_context` simply contributes no terms); the one
        exception is a malformed `resolution` itself (missing the
        fields `MeaningResolutionResult.to_dict()` always provides),
        which is a caller error like anywhere else in this package.

        Returns a DisambiguationResult. Never guesses: when the
        available information cannot single out one candidate, the
        result is STATUS_AMBIGUOUS with every candidate preserved."""
        resolution = _as_dict_or_none(resolution) or resolution
        status = resolution["status"]
        expression = resolution["expression"]
        result_language = resolution["language"]
        item_type = resolution["item_type"]
        meanings = resolution["meanings"]
        matched_items = resolution["matched_items"]
        truncated = resolution["truncated"]
        limits = resolution["limits"]

        if status == STATUS_NOT_FOUND or not meanings:
            return DisambiguationResult(
                STATUS_NOT_FOUND, expression, result_language, item_type, [], None,
                matched_items, REASON_NOT_FOUND, [], {}, truncated, limits,
            )

        if len(meanings) == 1:
            return DisambiguationResult(
                STATUS_RESOLVED, expression, result_language, item_type, meanings, meanings[0],
                matched_items, REASON_SINGLE_MEANING, [], {}, truncated, limits,
            )

        # Language awareness FIRST, before any context-term comparison -
        # the same written expression in two languages is never treated
        # as one candidate pool without regard to which language applies.
        candidates = meanings
        preferred = preferred_language if preferred_language is not None else language
        if preferred:
            narrowed = [m for m in candidates if m["language"] == preferred]
            if len(narrowed) == 1:
                return DisambiguationResult(
                    STATUS_RESOLVED, expression, result_language, item_type, meanings, narrowed[0],
                    matched_items, REASON_LANGUAGE_NARROWED, [], {}, truncated, limits,
                )
            if narrowed:
                candidates = narrowed  # still several within this one language

        context_terms = collect_context_terms(
            active_topic=active_topic, conversation_context=conversation_context,
            resolved_reference=resolved_reference, nearby_expressions=nearby_expressions,
            max_turns=max_context_turns,
        )
        if not context_terms:
            return DisambiguationResult(
                STATUS_AMBIGUOUS, expression, result_language, item_type, meanings, None,
                matched_items, REASON_NO_CONTEXT_TERMS, [], {}, truncated, limits,
            )

        scores = {m["id"]: _score(m, context_terms) for m in candidates}
        max_score = max(scores.values())
        sorted_terms = sorted(context_terms)
        if max_score == 0:
            return DisambiguationResult(
                STATUS_AMBIGUOUS, expression, result_language, item_type, meanings, None,
                matched_items, REASON_NO_CANDIDATE_MATCHED, sorted_terms, scores, truncated, limits,
            )

        top = [m for m in candidates if scores[m["id"]] == max_score]
        if len(top) == 1:
            return DisambiguationResult(
                STATUS_RESOLVED, expression, result_language, item_type, meanings, top[0],
                matched_items, REASON_CONTEXT_MATCHED, sorted_terms, scores, truncated, limits,
            )
        return DisambiguationResult(
            STATUS_AMBIGUOUS, expression, result_language, item_type, meanings, None,
            matched_items, REASON_CONTEXT_TIED, sorted_terms, scores, truncated, limits,
        )
