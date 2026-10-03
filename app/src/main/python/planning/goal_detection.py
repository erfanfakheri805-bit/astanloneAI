"""
Planning - Goal-Oriented Input Detection
===========================================
A tiny, deterministic, prefix-based classifier that decides whether a
piece of conversational text is *clearly* a goal-oriented request -
something Core should turn into a Goal (see planning/goal.py,
planning/goal_manager.py) - as opposed to an ordinary question or
statement Core's existing conversation handling already knows how to
deal with (see core/core.py's _handle_conversation).

This is deliberately conservative and simple on purpose:
  - a fixed, hand-picked lexicon of prefixes that unambiguously signal
    "the user wants something done" (never inferred, never scored,
    never randomized - same "crude but deterministic" convention as
    planning/goal_manager.py's own confidence estimate);
  - a plain case-insensitive `str.startswith` check against each
    prefix - no NLP heuristics, no external calls, no network/AI
    lookups of any kind, so this can never behave differently between
    two calls with the same input (requirement: "Goal creation must
    be deterministic and safe.").

False negatives beyond this lexicon are expected and acceptable - a
request phrased unusually simply falls through to the existing
conversation flow, same as it does today. What matters is that this
never mistakes an ordinary question ("What is Python?") or statement
("Python is a programming language.") for a goal-oriented request.
"""

# Fixed, ordered-for-readability (not priority - all are checked)
# lexicon of prefixes that clearly ask for something to be done,
# rather than merely stating or asking about something. Every entry
# ends with a trailing space (or punctuation) so a prefix never
# matches as part of a longer, unrelated word (e.g. "help mexico"
# does not match "help me").
GOAL_TRIGGER_PREFIXES = (
    "i want to ",
    "i want ",
    "i need to ",
    "i need ",
    "i would like to ",
    "i'd like to ",
    "please help me ",
    "can you help me ",
    "help me ",
    "my goal is ",
    "goal: ",
)


def is_goal_oriented(text):
    """Return True if `text` clearly reads as a goal-oriented request
    (starts with one of GOAL_TRIGGER_PREFIXES, case-insensitively),
    False otherwise - including for None, empty, or whitespace-only
    input. Never raises."""
    if not text:
        return False
    normalized = str(text).strip().lower()
    if not normalized:
        return False
    # A trailing space is appended so a bare "help me" (no trailing
    # content) still matches its own "help me " prefix, exactly like
    # "help me plan a trip" does - without this, only prefixes with no
    # trailing space of their own could ever match text that stops
    # right where the prefix does.
    candidate = normalized + " "
    return any(candidate.startswith(prefix) for prefix in GOAL_TRIGGER_PREFIXES)
