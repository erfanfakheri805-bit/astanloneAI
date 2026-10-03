"""
Reasoning Query Parsing
=========================
Turns a natural-language reasoning question ("What is Python?", "What
is Python used for?", "Does Python use indentation?", "Is Python a
programming language?") into a small structured `QueryParse` the
Reasoning Engine can actually act on - subject, wanted relation type
(if any), and object (for a yes/no-style verification question).

Same spirit, and same style, as understanding/relation_extraction.py:
a short ordered list of explicit regex patterns tried in turn, not a
general grammar. A caller that just hands in a bare entity name
("Python") gets INTENT_GENERIC with that name as the subject - the
same shape ASK <name> already uses in AEL - so reason() works equally
well as a drop-in for a plain lookup and for an actual question.

This module never touches storage or context; resolving a reference
word ("it", "this") found as the subject/object here is
reasoning_engine.py's job (it reuses context/reference_resolution.py,
the same mechanism the Understanding Engine already uses - see that
module for why this deliberately stays "not real coreference
resolution").
"""

import re

INTENT_WHAT_IS = "what_is"
INTENT_RELATION_QUERY = "relation_query"      # "What does X use?" - open object
INTENT_VERIFY_RELATION = "verify_relation"    # "Does X use Y?" - yes/no over a specific object
INTENT_VERIFY_IS_A = "verify_is_a"            # "Is X a Y?" - yes/no, relation fixed to IS_A
INTENT_GENERIC = "generic"                    # bare name / anything else - ASK-style lookup

# Surface verb -> stored relation_type. Ordered so multi-word phrases
# ("depends on") are tried before any shorter phrase that could be a
# prefix of one.
_RELATION_WORDS = [
    ("depends on", "DEPENDS_ON"),
    ("depend on", "DEPENDS_ON"),
    ("contains", "CONTAINS"),
    ("contain", "CONTAINS"),
    ("uses", "USES"),
    ("use", "USES"),
    ("has", "HAS"),
    ("have", "HAS"),
]
_RELATION_WORD_PATTERN = "|".join(re.escape(w) for w, _ in _RELATION_WORDS)


def _relation_for_word(word):
    word = word.strip().lower()
    for surface, relation_type in _RELATION_WORDS:
        if word == surface:
            return relation_type
    return None


def _strip(text):
    return (text or "").strip().rstrip("?！？").strip()


class QueryParse:
    def __init__(self, intent, subject, relation=None, obj=None, raw_text=""):
        self.intent = intent
        self.subject = subject
        self.relation = relation
        self.object = obj
        self.raw_text = raw_text

    def __repr__(self):
        return (
            f"QueryParse(intent={self.intent!r}, subject={self.subject!r}, "
            f"relation={self.relation!r}, object={self.object!r})"
        )

    def to_dict(self):
        return {
            "intent": self.intent,
            "subject": self.subject,
            "relation": self.relation,
            "object": self.object,
            "raw_text": self.raw_text,
        }


# Ordered most-specific-first, same convention as
# understanding/relation_extraction.py's RELATION_PATTERNS.
_PATTERN_VERIFY_RELATION = re.compile(
    rf"^does\s+(?P<subject>.+?)\s+(?P<verb>{_RELATION_WORD_PATTERN})\s+(?P<object>.+?)$",
    re.IGNORECASE,
)
_PATTERN_VERIFY_IS_A = re.compile(r"^is\s+(?P<subject>.+?)\s+an?\s+(?P<object>.+?)$", re.IGNORECASE)
_PATTERN_USED_FOR = re.compile(r"^what\s+is\s+(?P<subject>.+?)\s+used\s+for$", re.IGNORECASE)
_PATTERN_WHAT_IS_CALLED = re.compile(r"^what\s+is\s+(?P<subject>.+?)\s+called$", re.IGNORECASE)
_PATTERN_RELATION_QUERY = re.compile(
    rf"^what\s+does\s+(?P<subject>.+?)\s+(?P<verb>{_RELATION_WORD_PATTERN})$", re.IGNORECASE,
)
_PATTERN_WHAT_IS = re.compile(r"^what\s+is\s+(?P<subject>.+?)$", re.IGNORECASE)


# Prompt 631: request-form lead-ins that mean "What is X?". Without
# these, "Tell me about Python" / "Explain Python" / "What's Python"
# fell through to INTENT_GENERIC with the WHOLE sentence as the subject,
# so the knowledge lookup for "Python" never happened. They are
# rewritten to the plain "what is X" form (INTENT_WHAT_IS) only when
# nothing else matched first; raw_text keeps the user's original text.
# OPT-IN (`parse_query(..., request_forms=True)`): Core.process_input()
# relies on these phrasings falling through to its own "Here's what I
# know about ..." reply, so the default parse is unchanged.
_PATTERN_POLITE_PREFIX = re.compile(
    r"^(?:(?:please|kindly|pls|plz)\b[\s,]*)+", re.IGNORECASE,
)
_PATTERN_REQUEST_WHAT_IS = re.compile(
    r"^(?:"
    r"tell\s+me\s+about|tell\s+me\s+more\s+about|explain|define|describe|"
    r"what(?:'s|\u2019s|s)|"
    r"(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:tell\s+me\s+about|explain|define|describe)"
    r")\s+(?P<subject>.+?)$",
    re.IGNORECASE,
)
_PATTERN_TELL_ME_WHAT_IS = re.compile(
    r"^tell\s+me\s+what\s+(?P<subject>.+?)\s+(?:is|are)$", re.IGNORECASE,
)


def _drop_polite_prefix(text):
    """Remove leading please/kindly/pls/plz. Returns `text` unchanged
    when nothing would remain or when the politeness word is itself the
    subject ("Please is a word")."""
    stripped = _PATTERN_POLITE_PREFIX.sub("", text).strip()
    if not stripped or stripped == text:
        return text
    if re.match(r"^(?:please|kindly|pls|plz)\s+(?:is|are|was|were)\b", text, re.IGNORECASE):
        return text
    return stripped


def _rewrite_request_form(text):
    """Return an equivalent "what is X" string for a request-form
    question, or None if `text` is not one. Only ever used as a
    fallback after every existing pattern failed to match."""
    stripped = _drop_polite_prefix(text)
    match = _PATTERN_TELL_ME_WHAT_IS.match(stripped) or _PATTERN_REQUEST_WHAT_IS.match(stripped)
    if match:
        subject = match.group("subject").strip()
        if subject:
            return subject
    return None


def parse_query(raw_text, request_forms=False):
    """Parse `raw_text` into a QueryParse. Never raises and never
    returns None - unparseable/unrecognized input always falls back to
    INTENT_GENERIC with the (stripped) whole text as the subject, so
    callers never need a special case for "didn't match anything"."""
    text = _strip(raw_text)
    if not text:
        return QueryParse(INTENT_GENERIC, subject="", raw_text=raw_text or "")

    if request_forms:
        text = _drop_polite_prefix(text)

    match = _PATTERN_VERIFY_RELATION.match(text)
    if match:
        relation = _relation_for_word(match.group("verb"))
        return QueryParse(
            INTENT_VERIFY_RELATION, subject=match.group("subject").strip(),
            relation=relation, obj=match.group("object").strip(), raw_text=raw_text,
        )

    match = _PATTERN_VERIFY_IS_A.match(text)
    if match:
        return QueryParse(
            INTENT_VERIFY_IS_A, subject=match.group("subject").strip(),
            relation="IS_A", obj=match.group("object").strip(), raw_text=raw_text,
        )

    match = _PATTERN_USED_FOR.match(text)
    if match:
        return QueryParse(
            INTENT_RELATION_QUERY, subject=match.group("subject").strip(),
            relation="USED_FOR", raw_text=raw_text,
        )

    match = _PATTERN_WHAT_IS_CALLED.match(text)
    if match:
        return QueryParse(
            INTENT_RELATION_QUERY, subject=match.group("subject").strip(),
            relation="IS_CALLED", raw_text=raw_text,
        )

    match = _PATTERN_RELATION_QUERY.match(text)
    if match:
        relation = _relation_for_word(match.group("verb"))
        return QueryParse(
            INTENT_RELATION_QUERY, subject=match.group("subject").strip(),
            relation=relation, raw_text=raw_text,
        )

    match = _PATTERN_WHAT_IS.match(text)
    if match:
        return QueryParse(INTENT_WHAT_IS, subject=match.group("subject").strip(), raw_text=raw_text)

    request_subject = _rewrite_request_form(text) if request_forms else None
    if request_subject:
        return QueryParse(INTENT_WHAT_IS, subject=request_subject, raw_text=raw_text)

    return QueryParse(INTENT_GENERIC, subject=text, raw_text=raw_text)
