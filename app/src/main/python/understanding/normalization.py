"""
Understanding Engine - Input Normalization
============================================
First stage of the Understanding Engine pipeline (see engine.py). Turns
whatever the user typed into a safe, predictable string for the stages
that follow, while preserving the original text unchanged.

This is deliberately conservative: it never rewrites words, never
strips punctuation that later stages need (question marks, sentence
periods), and never raises on odd input. Unicode text (including
Persian) is normalized to a single canonical form (NFKC) so downstream
regex/character-range checks behave consistently regardless of how the
input was encoded/typed.
"""

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")


class NormalizationResult:
    """Holds both the untouched original text and its normalized form.
    Callers that need the user's exact original wording (logging,
    display) should use `original_text`; every later Understanding
    Engine stage operates on `normalized_text`."""

    __slots__ = ("original_text", "normalized_text")

    def __init__(self, original_text, normalized_text):
        self.original_text = original_text
        self.normalized_text = normalized_text

    def to_dict(self):
        return {"original_text": self.original_text, "normalized_text": self.normalized_text}


def normalize(raw_text):
    """Normalize `raw_text` for analysis. Never raises: None or
    non-string input becomes an empty string rather than an error."""
    if raw_text is None:
        original = ""
    else:
        original = raw_text if isinstance(raw_text, str) else str(raw_text)

    # Canonical Unicode form first, so later character-range checks
    # (e.g. Persian detection) see a consistent representation.
    text = unicodedata.normalize("NFKC", original)

    # Trim, then collapse any run of whitespace (spaces, tabs, newlines,
    # repeated spaces) down to a single space. This does not touch
    # punctuation, so "What is Python?" keeps its "?" and
    # "Python is a programming language." keeps its ".".
    text = text.strip()
    text = _WHITESPACE_RE.sub(" ", text)

    return NormalizationResult(original_text=original, normalized_text=text)
