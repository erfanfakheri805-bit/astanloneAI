"""
Understanding Engine - Relation Candidate Extraction
======================================================
A small, extensible set of local linguistic patterns that turn a
statement like "Python is a programming language." into a structured,
*candidate* relationship:

    subject = "Python", relation = "IS_A", object = "programming language"

These patterns are examples, not a real grammar - each one is a single
regex tried in order against the normalized sentence. Extending this
later means appending one more (RELATION_NAME, pattern) tuple to
RELATION_PATTERNS; nothing else has to change.

Every match is returned as a RelationCandidate with a deterministic
confidence score, never inserted anywhere automatically - see
learning/learning_input.py:build_learning_inputs and
learning/learning_system.py:learn_from_understanding for what happens
after extraction.
"""

import re

RELATION_IS_A = "IS_A"
RELATION_IS_CALLED = "IS_CALLED"
RELATION_USES = "USES"
RELATION_HAS = "HAS"
RELATION_CONTAINS = "CONTAINS"
RELATION_DEPENDS_ON = "DEPENDS_ON"

# Ordered on purpose: more specific multi-word patterns ("depends on",
# "is called"/"is named") before the more general "is a/an", so a
# sentence like "My project is called Echo Shift." (which has no
# article after "is") is captured by IS_CALLED rather than falling
# through unmatched - and so it never gets a chance to be misread by
# the "is a/an" pattern either, since that one requires an article.
RELATION_PATTERNS = [
    (RELATION_DEPENDS_ON, re.compile(r"^(?P<a>.+?)\s+depends\s+on\s+(?P<b>.+?)$", re.IGNORECASE)),
    (RELATION_IS_CALLED, re.compile(r"^(?P<a>.+?)\s+is\s+(?:called|named)\s+(?P<b>.+?)$", re.IGNORECASE)),
    (RELATION_IS_A, re.compile(r"^(?P<a>.+?)\s+is\s+an?\s+(?P<b>.+?)$", re.IGNORECASE)),
    (RELATION_USES, re.compile(r"^(?P<a>.+?)\s+uses\s+(?P<b>.+?)$", re.IGNORECASE)),
    (RELATION_CONTAINS, re.compile(r"^(?P<a>.+?)\s+contains\s+(?P<b>.+?)$", re.IGNORECASE)),
    (RELATION_HAS, re.compile(r"^(?P<a>.+?)\s+has\s+(?P<b>.+?)$", re.IGNORECASE)),
]

_LEADING_ARTICLE_RE = re.compile(r"^(a|an|the)\s+", re.IGNORECASE)
_TRAILING_PUNCT_RE = re.compile(r"[\s.!?؟،,]+$")

# Base confidence for a matched pattern before adjustments. Not a
# random number: it reflects that these are simple surface patterns
# which are usually but not always semantically correct.
_BASE_CONFIDENCE = 0.85


def _clean_term(raw):
    term = raw.strip()
    term = _LEADING_ARTICLE_RE.sub("", term)
    term = _TRAILING_PUNCT_RE.sub("", term)
    return term.strip()


class RelationCandidate:
    """A candidate (subject, relation, object) triple with a
    deterministic confidence score. `pattern` records which linguistic
    pattern produced it, for transparency/debugging."""

    def __init__(self, subject, relation, obj, pattern, confidence):
        self.subject = subject
        self.relation = relation
        self.object = obj
        self.pattern = pattern
        self.confidence = confidence

    def __repr__(self):
        return f"RelationCandidate({self.subject!r}, {self.relation!r}, {self.object!r}, confidence={self.confidence:.2f})"

    def to_dict(self):
        return {
            "subject": self.subject,
            "relation": self.relation,
            "object": self.object,
            "pattern": self.pattern,
            "confidence": round(self.confidence, 2),
        }


def extract_relation_candidates(normalized_text, sentence_type):
    """Return a list of RelationCandidate found in `normalized_text`.
    Only attempted for statements - questions and commands ("What is
    Python?", "Teach me Python.") are not treated as asserting a
    relationship, so this deliberately returns [] for those."""
    if sentence_type != "statement" or not normalized_text:
        return []

    stripped = _TRAILING_PUNCT_RE.sub("", normalized_text)
    if not stripped:
        return []

    candidates = []
    for relation, pattern in RELATION_PATTERNS:
        match = pattern.match(stripped)
        if not match:
            continue

        subject = _clean_term(match.group("a"))
        obj = _clean_term(match.group("b"))
        if len(subject) < 2 or len(obj) < 2:
            continue

        confidence = _BASE_CONFIDENCE
        # A subject with internal punctuation, or spanning many words,
        # is a weaker signal that this simple pattern captured the
        # sentence's real subject - lower confidence accordingly.
        if len(subject.split()) > 3:
            confidence -= 0.2
        if len(obj.split()) > 5:
            confidence -= 0.15
        confidence = max(0.1, min(1.0, confidence))

        candidates.append(RelationCandidate(subject, relation, obj, pattern=relation, confidence=confidence))

    return candidates
