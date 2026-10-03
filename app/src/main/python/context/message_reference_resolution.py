"""
Conversation Context - Message-Level Reference Resolution (Prompt 392)
========================================================================
A small, deterministic step that sits between Relevance Selection
(context/relevance.py, Prompts 389-390) and Response Construction
(core/core.py's `_construct_fallback_reply`, Prompt 391): given the
*current* user message and the RelevantContextResult already selected
for it, decide whether the message contains a simple conversational
reference ("it", "that boss", "the game I mentioned", ...) and, if so,
which of the already-selected turns it most plausibly points back to.

This is explicitly NOT a rebuild of the NLU system
(understanding/relation_extraction.py) or of the entity-level
reference resolver already used there
(context/reference_resolution.py, which resolves a relation's
subject/object word-by-word for learning/reasoning). Those keep doing
exactly what they did before this stage. This module instead answers a
narrower, conversational question: "does this whole message *refer
back* to something recent, and if so, what recent thing?" - so a reply
can be built that acknowledges it, even for messages
(understanding/sentence_analysis.py:SENTENCE_COMMAND, e.g. "Give me
three ideas for it.") that the existing strict quote-back logic in
Core._recall_from_relevant_context never looks at, because that logic
only ever fires for SENTENCE_QUESTION.

Nothing here re-selects context: it only reads the `selected` list a
RelevantContextResult already produced. No candidates selected means
no resolution is attempted at all (requirement: "if there is no
relevant context, preserve the existing behavior") - this module never
falls back to scanning the whole conversation on its own.

REFERENCE DETECTION
--------------------
Three small, fixed sources of reference phrases - not a generative or
learned list, same "small and reliable rather than exhaustive"
convention as GENERIC_REFERENCE_NOUNS in reference_resolution.py:

    1. Bare pronouns already recognized by reference_resolution.py
       ("it", "this", "that", "they", "them") plus "he"/"she", which
       that module has no need for (it works on relation subjects/
       objects, not conversational replies).
    2. A short, fixed list of whole phrases: "the previous one", "the
       previous idea", "that one", "the one you mentioned", "what i
       said before".
    3. One generalized pattern for "the <thing> I/you mentioned"
       (covers "the game I mentioned", "the app I mentioned", and any
       similar short noun phrase) - a single regex, not a hardcoded
       list of nouns.

RESOLUTION
----------
Once a reference is detected, the candidate is simply the
already-selected turn ranked #1 by context/relevance.py - never a
fresh, second lookup. If the top two candidates are within
`_AMBIGUITY_MARGIN` of each other, the reference is reported as
ambiguous instead of guessing between them (same margin-based
"too close to call" rule reference_resolution.py already uses for its
own, separate purpose).
"""

import re

from understanding.normalization import normalize
from .reference_resolution import SINGULAR_PRONOUNS, PLURAL_PRONOUNS

_WORD_RE = re.compile(r"[A-Za-z0-9_']+")

# "he"/"she" are only needed for whole-message conversational
# reference detection (this module), not for the NLU-level relation
# subject/object resolution reference_resolution.py performs - so they
# are added here rather than to that module's own pronoun sets.
_EXTRA_PRONOUNS = {"he", "she"}
_ALL_PRONOUNS = SINGULAR_PRONOUNS | PLURAL_PRONOUNS | _EXTRA_PRONOUNS

# Checked as substrings of the normalized (lowercased, whitespace-
# collapsed) message - deliberately small; see module docstring.
_FIXED_PHRASES = (
    "the previous one",
    "the previous idea",
    "what i said before",
    "that one",
    "the one you mentioned",
)

# "the game I mentioned" / "the voice app you mentioned" / ... - a
# short (<=4 word) noun phrase between "the" and "I mentioned"/"you
# mentioned". Bounded so it can't accidentally swallow an entire
# unrelated sentence that happens to contain "mentioned" much later.
_MENTIONED_RE = re.compile(
    r"\bthe\s+[a-z][a-z\-]*(?:\s+[a-z][a-z\-]*){0,3}\s+(?:i|you)\s+mentioned\b"
)

# Same style/purpose as reference_resolution.py's own
# _AMBIGUITY_MARGIN: how much stronger the top-ranked selected turn
# must be than the next one before it is treated as *the* referent
# rather than left ambiguous.
_AMBIGUITY_MARGIN = 0.2

# Confidence is a fixed, deterministic value from one of two signals -
# never a learned/randomized score:
#   - the selected turn was ranked #1 *because* relevance.py itself
#     recognized this message's reference word ("reference:it" in its
#     `reasons`) - the strong-signal case.
#   - the selected turn merely happened to outrank everything else on
#     shared terms alone - still usable, but a weaker signal that this
#     particular turn is what the reference points to.
_CONFIDENCE_WITH_REFERENCE_SIGNAL = 0.9
_CONFIDENCE_WITHOUT_REFERENCE_SIGNAL = 0.6


class ResolvedReference:
    """Structured result of one message-level reference resolution
    attempt. Mirrors the shape used elsewhere in this project
    (ReferenceResolution, RelevantContextResult): plain fields, a
    `to_dict()`, and a `reason` string for debugging/inspection -
    never a fabricated resolution when the signal isn't there.

    `resolved_context` is the verbatim user text of the turn the
    reference was resolved to (or None if unresolved/ambiguous/absent)
    - never a paraphrase or a guess, same "verbatim or nothing"
    convention Core._recall_from_relevant_context already follows."""

    def __init__(self, has_reference, reference_text, resolved_context, confidence, ambiguous, reason):
        self.has_reference = has_reference
        self.reference_text = reference_text
        self.resolved_context = resolved_context
        self.confidence = confidence
        self.ambiguous = ambiguous
        self.reason = reason

    def __repr__(self):
        return (
            f"ResolvedReference(has_reference={self.has_reference}, "
            f"reference_text={self.reference_text!r}, "
            f"resolved_context={self.resolved_context!r}, "
            f"confidence={self.confidence:.2f}, ambiguous={self.ambiguous})"
        )

    def to_dict(self):
        return {
            "has_reference": self.has_reference,
            "reference_text": self.reference_text,
            "resolved_context": self.resolved_context,
            "confidence": round(self.confidence, 4),
            "ambiguous": self.ambiguous,
            "reason": self.reason,
        }


def _detect_reference(text):
    """Return the matched reference phrase (lowercased, as found in
    the normalized message), or None if `text` contains no recognized
    reference at all. Checked in a fixed order - fixed phrases first,
    then the generalized "mentioned" pattern, then bare pronouns - so
    a message matching more than one source still reports a single,
    deterministic `reference_text`."""
    normalized = normalize(text).normalized_text.lower()
    if not normalized:
        return None

    for phrase in _FIXED_PHRASES:
        if phrase in normalized:
            return phrase

    match = _MENTIONED_RE.search(normalized)
    if match:
        return match.group(0)

    for word in _WORD_RE.findall(normalized):
        if word in _ALL_PRONOUNS:
            return word

    return None


def resolve_conversational_reference(text, relevant_context):
    """Attempt to resolve a conversational reference in `text` against
    `relevant_context` (a context/relevance.py RelevantContextResult -
    already selected; this function never (re)selects context itself).

    Always returns a ResolvedReference, never raises, and never
    fabricates a resolution:
      - `text` has no recognized reference at all
            -> has_reference=False, resolved_context=None
      - a reference is present but `relevant_context` selected nothing
        (nothing relevant was recently said, or `relevant_context`
        itself is None)
            -> has_reference=True, resolved_context=None,
               ambiguous=False (there's nothing to be ambiguous
               *between* - see reason "no_relevant_context")
      - a reference is present and the top two selected turns are too
        close to call
            -> has_reference=True, resolved_context=None,
               ambiguous=True
      - a reference is present and one selected turn clearly outranks
        the rest
            -> has_reference=True, resolved_context=<that turn's
               verbatim user text>, ambiguous=False
    """
    reference_text = _detect_reference(text)
    if reference_text is None:
        return ResolvedReference(False, None, None, 0.0, False, "no_reference")

    selected = list(relevant_context.selected) if relevant_context is not None else []
    if not selected:
        return ResolvedReference(True, reference_text, None, 0.0, False, "no_relevant_context")

    ranked = sorted(selected, key=lambda item: item["rank"])
    top = ranked[0]
    second_score = ranked[1]["score"] if len(ranked) > 1 else 0.0

    if len(ranked) > 1 and (top["score"] - second_score) < _AMBIGUITY_MARGIN:
        return ResolvedReference(True, reference_text, None, 0.0, True, "insufficient_margin")

    resolved_context_text = (top.get("turn") or {}).get("user")
    if not resolved_context_text:
        return ResolvedReference(True, reference_text, None, 0.0, False, "no_relevant_context")

    reasons = top.get("reasons") or []
    has_reference_signal = any(r.startswith("reference:") for r in reasons)
    confidence = (
        _CONFIDENCE_WITH_REFERENCE_SIGNAL if has_reference_signal else _CONFIDENCE_WITHOUT_REFERENCE_SIGNAL
    )

    return ResolvedReference(
        True,
        reference_text,
        resolved_context_text,
        confidence,
        False,
        ";".join(reasons) or "top_ranked_context",
    )
