"""
Conversation Context - Relevance Selection
============================================
Given the current user message and the recent turns kept by
ConversationContext (see conversation_context.py:get_recent_turns), pick
out the turns that actually bear on that message.

Deliberately small and deterministic - no semantic model. Every point a
turn scores comes from one of three inspectable signals, and each is
reported back in the result's `reasons`:

    shared terms   a meaningful word (understanding/term_extraction.py:
                   stopwords dropped, lowercased) that appears in both the
                   message and the turn's *user* text - +1 each
    shared name    a shared term the message itself writes capitalized
                   ("Python", "Echo") - +1 more. A crude, honest stand-in
                   for "named entity": it only rewards a match, and never
                   creates one
    reference      the message contains "it"/"this"/"that"/"they"/... (the
                   sets in reference_resolution.py). Such a message points
                   back at whatever was said last, so the most recent turn
                   gets +1. This only *selects* that turn - resolving what
                   "it" actually means stays reference_resolution.py's job

A turn with no signal scores 0 and is left out, so an unrelated message
selects nothing rather than something unrelated.

Only the user's side is matched. The assistant's replies are Core's own
templates (the fallback reply, for one, spells out "TEACH sun IS a star
..."), so matching them would make an unrelated turn look relevant to any
message that mentions "sun". Selected turns still carry both sides.

Output order: `selected` is chronological (oldest first), as the turns
were given. Relevance is reported separately, as each item's `rank`
(1 = most relevant; equal scores go to the more recent turn).

Limits worth knowing: term extraction is ASCII-word based (the same as the
rest of Core's lookup), so a message in a non-Latin script yields no terms
and selects nothing; and matching is whole-word, so "programming" does not
match "program".
"""

import re

from understanding.normalization import normalize
from understanding.term_extraction import extract_candidate_terms, STOPWORDS
from understanding.sentence_analysis import QUESTION_WORDS_EN, COMMAND_VERBS_EN
from .reference_resolution import SINGULAR_PRONOUNS, PLURAL_PRONOUNS

_WORD_RE = re.compile(r"[A-Za-z0-9_']+")
_REFERENCE_WORDS = SINGULAR_PRONOUNS | PLURAL_PRONOUNS

_WEIGHT_SHARED_TERM = 1.0
_WEIGHT_SHARED_NAME = 1.0
_WEIGHT_REFERENCE = 1.0

# Words that are capitalized only because of where they sit in a sentence
# (or because they're question/command openers), so never count as names.
_NOT_NAMES = STOPWORDS | QUESTION_WORDS_EN | COMMAND_VERBS_EN


class RelevantContextResult:
    """Structured result of one selection - same plain, JSON-shaped
    convention as UnderstandingResult / ReasoningResult.

    `selected` is a chronological list of items, each:
        {"turn": {"user", "assistant"},   copy of the turn
         "index": int,                    its position in the turns given
         "rank": int,                     1 = most relevant
         "score": float,
         "matched_terms": [str],          in the message's word order
         "reasons": [str],                e.g. "shared_terms:python"
         "covers_message_terms": bool}    every meaningful word of the
                                          message appears in this turn
    `selected_count` is len(selected); an empty selection means nothing
    in the recent context was relevant."""

    def __init__(self, message, message_terms, selected):
        self.message = message
        self.message_terms = message_terms
        self.selected = selected
        self.selected_count = len(selected)

    def __repr__(self):
        return (
            f"RelevantContextResult(message={self.message!r}, "
            f"selected_count={self.selected_count})"
        )

    def to_dict(self):
        return {
            "message": self.message,
            "message_terms": list(self.message_terms),
            "selected_count": self.selected_count,
            "selected": self.selected,
        }


def select_relevant_turns(message, turns):
    """Select, from `turns` (a list of {"user", "assistant"} dicts,
    oldest-first), those relevant to `message`. Never raises: a
    None/blank message, or no turns, gives an empty selection."""
    text = normalize(message).normalized_text
    words = _WORD_RE.findall(text.lower())
    references = [w for w in words if w in _REFERENCE_WORDS]
    message_terms = [t for t in extract_candidate_terms(text) if t not in _REFERENCE_WORDS]
    names = {w.lower() for w in _WORD_RE.findall(text) if w[0].isupper() and w.lower() not in _NOT_NAMES}

    turns = list(turns or [])
    selected = []
    for index, turn in enumerate(turns):
        turn = turn or {}
        user_text = normalize(turn.get("user")).normalized_text
        turn_terms = set(extract_candidate_terms(user_text))
        matched = [t for t in message_terms if t in turn_terms]

        score = 0.0
        reasons = []
        if matched:
            score += _WEIGHT_SHARED_TERM * len(matched)
            reasons.append("shared_terms:" + ",".join(matched))
            shared_names = [t for t in matched if t in names]
            if shared_names:
                score += _WEIGHT_SHARED_NAME * len(shared_names)
                reasons.append("shared_name:" + ",".join(shared_names))
        if references and index == len(turns) - 1:
            score += _WEIGHT_REFERENCE
            reasons.append("reference:" + references[0])

        if score > 0:
            selected.append({
                "turn": {"user": turn.get("user"), "assistant": turn.get("assistant")},
                "index": index,
                "rank": 0,
                "score": score,
                "matched_terms": matched,
                "reasons": reasons,
                "covers_message_terms": bool(message_terms) and len(matched) == len(message_terms),
            })

    # Rank by score, most recent first among equals; `selected` itself
    # stays in chronological order.
    for rank, item in enumerate(sorted(selected, key=lambda i: (-i["score"], -i["index"])), start=1):
        item["rank"] = rank

    return RelevantContextResult(text, message_terms, selected)


# ----------------------------------------------------------------------
# Prompt 403: focused/bounded context selection
# ----------------------------------------------------------------------
# No tokenizer here on purpose (see select_bounded_context's own
# docstring) - a plain character count is the smallest limit that
# still keeps an old/long conversation from producing an unbounded
# request. Small, fixed, and overridable per call - never a second,
# competing "memory system".
DEFAULT_FOCUSED_MAX_TURNS = 4
DEFAULT_FOCUSED_MAX_CHARS = 4000


def select_bounded_context(relevant_context, max_turns=DEFAULT_FOCUSED_MAX_TURNS,
                           max_chars=DEFAULT_FOCUSED_MAX_CHARS):
    """Bound an already-computed selection down to the small, focused
    slice of conversation history actually worth sending onward (e.g.
    to a local language model backend - see
    language_intelligence/local_model_mapping.py). This is purely a
    NARROWING step: it never re-scores, re-selects, or invents
    anything - `select_relevant_turns` above has already done the one
    real relevance judgement (recent relevant messages, shared terms/
    names, a message-final reference word); this function only decides
    how much of *that* result is worth actually sending, within two
    fixed limits: at most `max_turns` turns, and at most `max_chars`
    total characters across them combined.

    Accepts either a `RelevantContextResult` or the plain dict its own
    `to_dict()` returns (both carry the same `selected` shape), so this
    works equally from a live selection or from a
    `language_intelligence.LanguageUnderstandingResult`'s stored
    `conversation_context` field - no second copy of the selection
    logic anywhere. `None`, an empty result, or a selection with
    nothing in it all yield `[]` - the honest "no useful context"
    answer (never a guess, never the whole conversation as a
    fallback).

    Least-relevant turns (by `select_relevant_turns`' own `rank`) are
    dropped first, whole, when `max_turns`/`max_chars` would otherwise
    be exceeded - a turn's original text (Persian, English, mixed
    script, code, numbers, anything) is always sent complete or not at
    all, NEVER trimmed/translated/rewritten. The single most relevant
    turn is always kept even if it alone exceeds `max_chars`, since
    sending nothing is worse than one slightly-over-budget turn and
    this function truncates no text to make it fit. Output is
    chronological (oldest first) - same convention as
    `select_relevant_turns` itself - because a model reads history in
    the order it happened, not in relevance order.

    Because this only narrows what `select_relevant_turns` already
    selected (itself already scoped to `ConversationContext`'s own
    recent-turn window), the Active Conversation Topic and any
    resolved conversational reference are already reflected in what
    can appear here: a message-level reference resolves to precisely
    the rank-#1 selected turn (see
    context/message_reference_resolution.py's own docstring), and a
    message that continues the active topic shares terms with
    whichever turn(s) established it - exactly what earns a turn a
    score above zero in `select_relevant_turns` in the first place. So
    a turn relevant to the active topic or a resolved reference is
    dropped only when something even more relevant crowds it out of
    `max_turns`/`max_chars` - never singled out and discarded on
    purpose.
    """
    if isinstance(relevant_context, RelevantContextResult):
        selected = relevant_context.selected
    elif isinstance(relevant_context, dict):
        selected = relevant_context.get("selected") or []
    else:
        selected = []

    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
        return []
    has_char_budget = (
        isinstance(max_chars, (int, float)) and not isinstance(max_chars, bool) and max_chars > 0
    )

    usable = []
    for item in selected or []:
        if not isinstance(item, dict):
            continue
        turn = item.get("turn") or {}
        user_text, assistant_text = turn.get("user"), turn.get("assistant")
        if isinstance(user_text, str) and isinstance(assistant_text, str):
            usable.append({
                "index": item.get("index", 0),
                "rank": item.get("rank", 0),
                "user": user_text,
                "assistant": assistant_text,
            })
    # Most relevant first (lowest rank = most relevant); ties keep the
    # order select_relevant_turns already produced them in.
    usable.sort(key=lambda t: t["rank"])

    chosen = []
    total_chars = 0
    for item in usable:
        if len(chosen) >= max_turns:
            break
        turn_chars = len(item["user"]) + len(item["assistant"])
        if chosen and has_char_budget and total_chars + turn_chars > max_chars:
            continue  # this turn alone would blow the budget - skip it, keep trying smaller ones
        chosen.append(item)
        total_chars += turn_chars

    chosen.sort(key=lambda t: t["index"])  # restore chronological order
    return [{"user": t["user"], "assistant": t["assistant"]} for t in chosen]
