"""
Persian conversation brain - normalization
==========================================
One place for turning raw typed Persian into the canonical form every other
module compares against. It builds on the project's own Persian NLU
normalization (understanding/persian_nlu.normalize_persian, via
self_builder.fa_text.canon): Unicode NFKC, Arabic -> Persian letter variants
(ي ك ة ى ...), diacritics and tatweel removed, Persian/Arabic digits -> ASCII,
ZWNJ -> space, invisible/bidi controls removed, Arabic punctuation mapped.

On top of that this module adds the conversational clean-up that typed chat
needs: elongated letters ("سلاااام"), runs of punctuation, the madda-less
spelling of "آ" for matching, and a matching key that ignores spaces/ZWNJ.
"""

import re

from self_builder import fa_text

_ELONGATION_RE = re.compile(r"([^\W\d_])\1{2,}", re.UNICODE)
_PUNCT_RUN_RE = re.compile(r"([!?.,;:])\1+")
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")


def collapse_elongation(text):
    """'سلاااام' -> 'سلام', 'خیلییییی' -> 'خیلی' (three or more equal letters -> one)."""
    return _ELONGATION_RE.sub(r"\1", text)


def normalize(text):
    """Canonical conversational form of `text` (never raises; None -> '')."""
    if text is None:
        return ""
    s = fa_text.canon(text)
    s = _EMOJI_RE.sub(" ", s)
    s = collapse_elongation(s)
    s = _PUNCT_RUN_RE.sub(r"\1", s)
    return " ".join(s.split())


def tokens(text):
    """Word/number tokens of the normalized text."""
    return fa_text.words(normalize(text))


def match_key(text):
    """Space/ZWNJ/punctuation-insensitive key that also ignores the madda
    ('آسمان' == 'اسمان'): used to find a taught name from a question."""
    return fa_text.key(normalize(text)).replace("آ", "ا")


def has_persian_script(text):
    return fa_text.has_persian_script(text)


def ends_with_question(norm):
    """Does the ALREADY NORMALIZED text end in a question mark - also «چی؟!» / «چی؟!!» / «چی؟.»"""
    return norm.rstrip(" !.").endswith("?")


def is_question_text(text):
    return ends_with_question(normalize(text))
