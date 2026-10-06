"""
Understanding Engine - Tokenization
=====================================
A small, reusable, general-purpose tokenizer for natural-language
input (English and Persian). This is intentionally separate from
`ael/tokenizer.py`, which tokenizes the small formal AEL command
grammar (TEACH/RELATE/SKILL/...) - that tokenizer must keep working
exactly as-is and is not touched by this module.

This tokenizer recognizes four token kinds:

- QUOTED     a "double" or 'single' quoted expression (quotes stripped)
- NUMBER     an integer or decimal number
- WORD       a run of letters (Latin or Persian) and digits/underscore/
             apostrophe starting with a letter
- PUNCT      any other single non-whitespace character

It is deliberately not tied to any single example sentence: it is
driven by a small ordered list of regex rules that later stages
(SENTENCE_SPEC) can extend without rewriting the tokenizer itself.
"""

import re

TOKEN_QUOTED = "QUOTED"
TOKEN_NUMBER = "NUMBER"
TOKEN_WORD = "WORD"
TOKEN_PUNCT = "PUNCT"

# Ordered (name, pattern) rules - order matters, first match wins for a
# given position. Keeping this as a list (not a dict) is what makes it
# easy to extend later without touching the scanning logic below.
_TOKEN_RULES = [
    (TOKEN_QUOTED, r'"[^"]*"|\'[^\']*\''),
    (TOKEN_NUMBER, r"\d+(?:\.\d+)?"),
    (TOKEN_WORD, r"[A-Za-z\u0600-\u06FF][A-Za-z0-9_\u0600-\u06FF']*"),
    (TOKEN_PUNCT, r"[^\sA-Za-z0-9\u0600-\u06FF]"),
]

_MASTER_RE = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_RULES)
)


class Token:
    """A single tokenized unit. `value` has quote characters already
    stripped for QUOTED tokens."""

    __slots__ = ("type", "value")

    def __init__(self, type_, value):
        self.type = type_
        self.value = value

    def __repr__(self):
        return f"Token({self.type!r}, {self.value!r})"

    def __eq__(self, other):
        return isinstance(other, Token) and self.type == other.type and self.value == other.value

    def to_dict(self):
        return {"type": self.type, "value": self.value}


def tokenize(text):
    """Split `text` into a list of Token objects. Never raises: empty
    or whitespace-only input simply yields an empty list."""
    tokens = []
    if not text:
        return tokens

    for match in _MASTER_RE.finditer(text):
        kind = match.lastgroup
        value = match.group()
        if kind == TOKEN_QUOTED:
            value = value[1:-1]
        tokens.append(Token(kind, value))

    return tokens
