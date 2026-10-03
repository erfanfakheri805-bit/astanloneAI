"""
Understanding Engine - Basic Language Detection
=================================================
A lightweight, fully local, fully deterministic language detector.
This is NOT a statistical language model - it is a *script* heuristic:
count the letters of each writing system in the prose of the text, and
pick whichever script is dominant.

    Arabic script  (Persian letters included)  -> LANGUAGE_PERSIAN
    Latin script                                -> LANGUAGE_ENGLISH
    anything else / no letters / an exact tie   -> LANGUAGE_UNKNOWN

That is enough to reliably tell English and Persian apart (the two
languages this application currently needs to distinguish) and to
honestly report "unknown" for anything else (numbers only, emoji,
punctuation-only input, or a script this heuristic was never taught
about) rather than guessing. It is a script-level label: it cannot tell
Persian from another Arabic-script language, or English from another
Latin-script language - only a real language model can. Callers that
need to carry that limitation forward should record the method as a
script heuristic (see language_intelligence/language_context.py).

Prompt 401 (multilingual / Persian readiness) tightened three things,
none of which changes the result for ordinary English or Persian prose:

  * Only LETTERS are counted. Digits (Latin, Arabic-Indic and Persian
    "۰-۹") and punctuation (including Persian/Arabic "؟ ، ؛") carry no
    language evidence; before, the Arabic block's digits and
    punctuation were counted as Persian letters.
  * Text that is not prose - fenced code blocks, `inline code` and
    URLs - is ignored, so a Persian question that quotes a code
    snippet is not labeled English just because the snippet is longer
    than the sentence around it. The text itself is never altered:
    masking only affects what is *counted*.
  * The dominant script is chosen among ALL scripts present, so a
    Cyrillic or Chinese sentence with one Latin word is "unknown"
    rather than "english".

Script names come from the Unicode character names
(unicodedata.name), so no hand-maintained range tables are needed and
any script can be reported, not only the two above.
"""

import re
import unicodedata

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)

# Letter categories that carry script evidence (Lm - modifier letters -
# and marks such as Arabic diacritics are deliberately not counted).
_LETTER_CATEGORIES = ("Lu", "Ll", "Lt", "Lo")

SCRIPT_ARABIC = "arabic"
SCRIPT_LATIN = "latin"

LANGUAGE_ENGLISH = "english"
LANGUAGE_PERSIAN = "persian"
LANGUAGE_UNKNOWN = "unknown"

_SCRIPT_TO_LANGUAGE = {
    SCRIPT_ARABIC: LANGUAGE_PERSIAN,
    SCRIPT_LATIN: LANGUAGE_ENGLISH,
}


def mask_non_prose(text):
    """Return `text` with fenced code blocks, `inline code` and URLs
    replaced by a space. For *analysis only* (what to count when
    detecting language); the caller's text is never modified."""
    if not text:
        return ""
    text = _CODE_FENCE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    return _URL_RE.sub(" ", text)


def prose_text(text):
    """NFKC-normalized, non-prose-masked view of `text` used for every
    language check (detection and explicit-request recognition), so all
    of them see the same characters the Understanding Engine sees."""
    if not isinstance(text, str) or not text:
        return ""
    return unicodedata.normalize("NFKC", mask_non_prose(text))


def script_letter_counts(text):
    """{script_name: letter_count} for the prose of `text`. Script
    names are lowercase first words of the Unicode character names
    ("arabic", "latin", "cyrillic", "cjk", "hangul", ...). Digits,
    punctuation, symbols, emoji and combining marks are not counted."""
    counts = {}
    for ch in prose_text(text):
        if unicodedata.category(ch) not in _LETTER_CATEGORIES:
            continue
        name = unicodedata.name(ch, "")
        if not name:
            continue
        script = name.split(" ", 1)[0].lower()
        counts[script] = counts.get(script, 0) + 1
    return counts


def ranked_scripts(counts):
    """Script names ordered by letter count (most first; ties by name,
    so the order is deterministic)."""
    return [name for name, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def detect_language(text):
    """Return LANGUAGE_ENGLISH, LANGUAGE_PERSIAN, or LANGUAGE_UNKNOWN
    for `text`, using a deterministic script-count heuristic."""
    if not text:
        return LANGUAGE_UNKNOWN

    counts = script_letter_counts(text)
    if not counts:
        return LANGUAGE_UNKNOWN

    ranked = ranked_scripts(counts)
    top = ranked[0]
    if len(ranked) > 1 and counts[ranked[1]] == counts[top]:
        return LANGUAGE_UNKNOWN
    return _SCRIPT_TO_LANGUAGE.get(top, LANGUAGE_UNKNOWN)
