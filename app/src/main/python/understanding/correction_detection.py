"""
Understanding Engine - Explicit Correction Detection
========================================================
Prompt 440. A small, deterministic detector for ONE fixed, explicit
textual correction marker - the same "single regex pattern, tried
once, never a guess" posture as relation_extraction.py's own
RELATION_PATTERNS (see that module's docstring: "These patterns are
examples, not a real grammar - each one is a single regex tried in
order against the normalized sentence").

Recognized pattern (case-insensitive), and nothing else:

    not <original>, i mean <corrected>
    not <original>, i meant <corrected>

e.g. "not dgo, I mean dog." -> original_expression="dgo",
corrected_expression="dog". A message that does not match this one
fixed marker detects nothing - never a partial guess, never inferred
from tone, context or general conversation.

This module does not decide what the detected pieces MEAN, does not
build a CorrectionUnderstanding, and does not judge whether the
correction is fully specified - it only reports the two spans the
fixed pattern captured. `language_intelligence.correction_understanding.
build_correction_understanding()` (Prompt 439) is what turns this raw
candidate into a structured, status-bearing result; that happens one
layer up (deterministic_fallback_backend.py), never here, so this
module has no dependency on language_intelligence.

Intentionally narrow scope (consistent with keeping this stage small):
only this one English marker is recognized today. Adding another
marker or a Persian equivalent later means appending one more pattern,
exactly like extending RELATION_PATTERNS - nothing else has to change.
"""

import re

_CORRECTION_RE = re.compile(
    r"^not\s+(?P<original>.+?)\s*,\s*i\s+(?:mean|meant)\s+(?P<corrected>.+?)[.!]*$",
    re.IGNORECASE,
)


class CorrectionCandidate:
    """Plain, read-only record of the two spans the fixed pattern
    captured - exactly as written, never normalized further, never
    interpreted."""

    __slots__ = ("original_expression", "corrected_expression")

    def __init__(self, original_expression, corrected_expression):
        self.original_expression = original_expression
        self.corrected_expression = corrected_expression

    def to_dict(self):
        return {
            "original_expression": self.original_expression,
            "corrected_expression": self.corrected_expression,
        }

    def __repr__(self):
        return (f"CorrectionCandidate(original_expression={self.original_expression!r}, "
                f"corrected_expression={self.corrected_expression!r})")


def detect_explicit_correction(normalized_text):
    """Return a `CorrectionCandidate` for the one fixed marker this
    module recognizes, or None. Deterministic and side-effect free;
    never raises for None/empty input."""
    if not normalized_text:
        return None
    match = _CORRECTION_RE.match(normalized_text.strip())
    if not match:
        return None
    original = match.group("original").strip()
    corrected = match.group("corrected").strip()
    if not original or not corrected:
        return None
    return CorrectionCandidate(original, corrected)
