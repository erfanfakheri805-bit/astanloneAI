"""
Language Intelligence - Language Context
=============================================
Prompt 401 (multilingual / Persian readiness). `LanguageContext` is the
structured, read-only description of the language situation of ONE user
message that travels next to the message - never instead of it - to the
local model layer:

    user message (verbatim)
      -> LanguageContext                (THIS module)
      -> LanguageUnderstandingResult.language_context
      -> InferenceRequest.language_context
      -> LocalModelProvider -> LocalModelRuntime -> (future) local model

It answers "what language situation is this message in?" so a future
multilingual model (with real Persian ability) can be told, without any
preprocessing of the user's text. It is NOT language intelligence: no
text is generated, translated, corrected or rewritten anywhere here.

What it carries
---------------
    original_text          the message, verbatim - the ONLY text meant
                           for the model. Never normalized, translated,
                           trimmed or "fixed" (Persian ZWNJ, Arabic vs
                           Persian yeh/kaf, digits, code layout, URLs
                           and filenames all stay exactly as typed).
    normalized_text        the Understanding Engine's NFKC +
                           whitespace-collapsed form, when the caller
                           supplied it, else None. ANALYSIS ONLY: NFKC
                           rewrites compatibility characters (x², ﬁ,
                           fullwidth forms) and collapsing whitespace
                           flattens code, so it must never replace
                           original_text.
    detected_language      the label of understanding/language_detection
                           (english / persian / unknown). Script-level:
                           see that module for what it cannot tell.
    detection_confidence   unknown | low | high. `unknown` = no
                           dominant language; `low` = more than one
                           script in the prose (e.g. Persian + English)
                           so the dominant label is only a summary;
                           `high` = a single script.
    detection_method       always "script_heuristic" here. A future
                           model-based detector would say so instead.
    scripts                scripts present in the PROSE, most letters
                           first ("arabic", "latin", ...). Code spans
                           and URLs are excluded. Several entries =
                           mixed-script input; the dominant language is
                           never presented as the whole story.
    conversation_language  language the conversation has established
                           (recent user turns), or None.
    requested_language     language the user explicitly asked for, or
                           None.
    default_language       configured default, or None.
    response_language      the preferred language of the reply, or None
                           when nothing at all is known - the model then
                           decides from the message itself.
    response_language_source  why: explicit_request | conversation |
                           detected | default | none.

Response language priority (see resolve_response_language):
    1. explicit request        (caller-supplied `requested_language`, else
                                a conservative recognizer over the text)
    2. conversation language   (majority of the last few user turns)
    3. detection of this message (a known language; mixed-script
                                messages are labeled `low` confidence
                                but still used - a Persian sentence with
                                an English technical term must still be
                                answered in Persian)
    4. configured default
A language is never switched by a single off-language message: the
conversation language is the majority of the recent user turns, so it
only changes once the conversation itself has changed.

Language identifiers are the project's existing labels (english,
persian) plus passthrough for others. `canonical_language` maps common
codes/names ("fa", "fas", "farsi", "en-US", ...) onto them so a model
that declares "fa" and a message detected as "persian" compare equal.

Everything here is pure and deterministic: no state, no I/O, no network,
no randomness, no download; the conversation context is only read.
"""

import re
from collections import Counter

from understanding.language_detection import (
    detect_language, script_letter_counts, ranked_scripts, prose_text,
    LANGUAGE_ENGLISH, LANGUAGE_PERSIAN, LANGUAGE_UNKNOWN,
)

CONFIDENCE_UNKNOWN = "unknown"
CONFIDENCE_LOW = "low"
CONFIDENCE_HIGH = "high"
ALL_CONFIDENCES = (CONFIDENCE_UNKNOWN, CONFIDENCE_LOW, CONFIDENCE_HIGH)

DETECTION_METHOD_SCRIPT_HEURISTIC = "script_heuristic"

SOURCE_EXPLICIT_REQUEST = "explicit_request"
SOURCE_CONVERSATION = "conversation"
SOURCE_DETECTED = "detected"
SOURCE_DEFAULT = "default"
SOURCE_NONE = "none"
ALL_RESPONSE_SOURCES = (
    SOURCE_EXPLICIT_REQUEST, SOURCE_CONVERSATION, SOURCE_DETECTED,
    SOURCE_DEFAULT, SOURCE_NONE,
)

# How many of the most recent user turns decide the conversation language.
CONVERSATION_LANGUAGE_WINDOW = 3

# canonical language -> codes/names that mean it (lowercase).
_LANGUAGE_ALIASES = {
    LANGUAGE_ENGLISH: ("en", "eng", "english"),
    LANGUAGE_PERSIAN: ("fa", "fas", "per", "persian", "farsi"),
    "arabic": ("ar", "ara", "arabic"),
    "french": ("fr", "fra", "fre", "french"),
    "german": ("de", "deu", "ger", "german"),
    "spanish": ("es", "spa", "spanish"),
}
_ALIAS_TO_LANGUAGE = {alias: lang for lang, aliases in _LANGUAGE_ALIASES.items()
                      for alias in aliases}
_NO_LANGUAGE_LABELS = ("unknown", "und", "auto")


def canonical_language(value):
    """Normalize a language code/name to the project's identifier, or
    None when `value` names no language ("", None, "unknown", a
    non-string). "fa", "FAS", "Farsi", "fa-IR" -> "persian"; "en_US"
    -> "english". A language this table does not know is passed through
    lowercased (never dropped or guessed), so "fi" stays "fi"."""
    if not isinstance(value, str):
        return None
    key = value.strip().lower().replace("_", "-")
    if not key or key in _NO_LANGUAGE_LABELS:
        return None
    if key in _ALIAS_TO_LANGUAGE:
        return _ALIAS_TO_LANGUAGE[key]
    base = key.split("-", 1)[0]
    return _ALIAS_TO_LANGUAGE.get(base, key)


# ----------------------------------------------------------------------
# Explicit "answer in <language>" recognition
# ----------------------------------------------------------------------
# Deliberately conservative: only clear imperatives that name a language
# the table below knows. A miss is harmless (the priority chain simply
# continues); a false hit would change the reply language, so questions
# ("how do you say hi in Persian?"), negations ("don't answer in
# English") and descriptions ("I answer in English at work") do NOT
# match. The primary channel is the explicit `requested_language`
# argument (e.g. a UI setting); this is a convenience over the text.
_EN_NAMES = {
    "english": LANGUAGE_ENGLISH, "persian": LANGUAGE_PERSIAN, "farsi": LANGUAGE_PERSIAN,
    "arabic": "arabic", "french": "french", "german": "german", "spanish": "spanish",
}
# Persian-script names; [یي] / [کك] accept both Persian and Arabic forms
# of yeh/kaf because both occur in real Persian text.
_FA_NAMES = {
    LANGUAGE_ENGLISH: r"انگل[یي]س[یي]",
    LANGUAGE_PERSIAN: r"(?:فارس|پارس)[یي]",
    "arabic": r"عرب[یي]",
    "french": r"فرانس(?:وی|وي|ه)",
    "german": r"آلمان[یي]",
    "spanish": r"اسپانیای[یي]",
}

_EN_REQUEST_RE = re.compile(
    r"(?:^|[.!?;:,\n])\s*"
    r"(?:(?:please|kindly|and|also|now|then)\s+)*"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?"
    r"(?:answer|reply|respond|speak|talk)\b"
    r"(?:\s+(?:to\s+me|me|back|again|always|only|from\s+now\s+on|please))*"
    r"\s+(?:in|using)\s+(?:the\s+)?(?:language\s+)?"
    r"(?P<lang>" + "|".join(_EN_NAMES) + r")\b",
    re.IGNORECASE)

_FA_ANSWER = r"(?:جواب|پاسخ)\s+(?:بده|بدید|بدهید)"
_FA_TALK = r"(?:صحبت|حرف)\s+(?:کن|کنید|بزن|بزنید)"
_FA_OTHER = r"(?:توضیح\s+(?:بده|بدید|بدهید)|بنویس(?:ید)?|بگو(?:یید)?)"
_FA_VERB = r"(?:" + "|".join((_FA_ANSWER, _FA_TALK, _FA_OTHER)) + r")"
_FA_LANG = r"(?:" + "|".join(f"(?P<{lang}>{name})" for lang, name in _FA_NAMES.items()) + r")"
_FA_POLITE = r"(?:(?:لطفا|لطفاً)\s+)?"

_FA_REQUEST_RES = (
    # به انگلیسی جواب بده / با فارسی صحبت کن
    re.compile(r"(?<!\S)(?:به|با)\s+(?:زبان\s+)?" + _FA_LANG + r"\s+" + _FA_POLITE + _FA_VERB),
    # انگلیسی جواب بده
    re.compile(r"(?<!\S)(?:زبان\s+)?" + _FA_LANG + r"\s+" + _FA_POLITE + _FA_VERB),
    # جواب (خودت را) به انگلیسی بده
    re.compile(r"(?<!\S)(?:جواب|پاسخ)(?:\s+(?:را|رو))?(?:\s+(?:خود|خودت))?"
               r"(?:\s+(?:را|رو))?\s+(?:به|با)\s+(?:زبان\s+)?" + _FA_LANG),
)


def detect_requested_language(text):
    """The language the user explicitly asked the reply to be in, as a
    canonical identifier, or None when the text makes no such request.
    Code spans and URLs are ignored. If several requests appear, the
    last one wins (the most recent instruction)."""
    prose = prose_text(text)
    if not prose:
        return None

    found = []                                   # (position, language)
    for match in _EN_REQUEST_RE.finditer(prose):
        found.append((match.start("lang"), _EN_NAMES[match.group("lang").lower()]))
    for pattern in _FA_REQUEST_RES:
        for match in pattern.finditer(prose):
            for lang in _FA_NAMES:
                if match.group(lang):
                    found.append((match.start(lang), lang))
    return max(found)[1] if found else None


# ----------------------------------------------------------------------
# Conversation language + resolution
# ----------------------------------------------------------------------
def conversation_language(context, window=CONVERSATION_LANGUAGE_WINDOW):
    """Language the conversation has established: the most common known
    language among the last `window` USER turns of `context` (a
    ConversationContext, read-only); on a tie the most recent of the
    tied languages. Assistant turns are ignored (a reply may come from a
    fallback in another language and says nothing about the user).
    Turns whose language is unknown are ignored. None when there is no
    context or no known language."""
    getter = getattr(context, "get_recent_turns", None)
    if getter is None or not isinstance(window, int) or isinstance(window, bool) or window < 1:
        return None
    known = []
    for turn in getter(window):
        if isinstance(turn, dict) and isinstance(turn.get("user"), str):
            language = detect_language(turn["user"])
            if language != LANGUAGE_UNKNOWN:
                known.append(language)
    if not known:
        return None
    counts = Counter(known)
    best = max(counts.values())
    for language in reversed(known):
        if counts[language] == best:
            return language
    return None


def resolve_response_language(requested_language=None, conversation_lang=None,
                              detected_language=None, default_language=None):
    """Apply the response-language priority (module docstring) and
    return `(language_or_None, source)`. Every argument may be None /
    unknown; identifiers are canonicalized. Nothing is ever invented:
    with nothing known the result is `(None, SOURCE_NONE)`."""
    candidates = (
        (requested_language, SOURCE_EXPLICIT_REQUEST),
        (conversation_lang, SOURCE_CONVERSATION),
        (detected_language, SOURCE_DETECTED),
        (default_language, SOURCE_DEFAULT),
    )
    for value, source in candidates:
        language = canonical_language(value)
        if language is not None:
            return language, source
    return None, SOURCE_NONE


# ----------------------------------------------------------------------
class LanguageContext:
    """See the module docstring. A plain, JSON-shaped value holder with
    `to_dict()` (same convention as the rest of the project); it never
    validates by raising and never alters its text."""

    def __init__(self, original_text, normalized_text=None, detected_language=LANGUAGE_UNKNOWN,
                 detection_confidence=CONFIDENCE_UNKNOWN,
                 detection_method=DETECTION_METHOD_SCRIPT_HEURISTIC, scripts=(),
                 conversation_language=None, requested_language=None, default_language=None,
                 response_language=None, response_language_source=SOURCE_NONE):
        self.original_text = original_text
        self.normalized_text = normalized_text
        self.detected_language = detected_language
        self.detection_confidence = detection_confidence
        self.detection_method = detection_method
        self.scripts = tuple(scripts)
        self.conversation_language = conversation_language
        self.requested_language = requested_language
        self.default_language = default_language
        self.response_language = response_language
        self.response_language_source = response_language_source

    @property
    def mixed_script(self):
        """True when the prose uses more than one script (e.g. Persian
        with English terms)."""
        return len(self.scripts) > 1

    def __repr__(self):
        return (f"LanguageContext(detected_language={self.detected_language!r}, "
                f"scripts={self.scripts!r}, response_language={self.response_language!r}, "
                f"source={self.response_language_source!r})")

    def to_dict(self):
        return {
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "detected_language": self.detected_language,
            "detection_confidence": self.detection_confidence,
            "detection_method": self.detection_method,
            "scripts": list(self.scripts),
            "mixed_script": self.mixed_script,
            "conversation_language": self.conversation_language,
            "requested_language": self.requested_language,
            "default_language": self.default_language,
            "response_language": self.response_language,
            "response_language_source": self.response_language_source,
        }


def build_language_context(original_text, normalized_text=None, conversation=None,
                           requested_language=None, default_language=None,
                           conversation_window=CONVERSATION_LANGUAGE_WINDOW):
    """Build the `LanguageContext` for one message. Never raises and
    never modifies its inputs.

    `original_text`   the user's message (kept verbatim; None -> "").
    `normalized_text` optional analysis-only normalized form (kept as
                      given, never used for detection or sent to a model).
    `conversation`    optional ConversationContext (read-only) - the
                      source of the conversation language.
    `requested_language`  explicit language request from the caller (a
                      UI setting, an upstream parser). When None, the
                      text itself is checked by `detect_requested_language`.
    `default_language`    configured fallback language, or None."""
    if original_text is None:
        original = ""
    else:
        original = original_text if isinstance(original_text, str) else str(original_text)

    counts = script_letter_counts(original)
    scripts = ranked_scripts(counts)
    detected = detect_language(original)
    if detected == LANGUAGE_UNKNOWN:
        confidence = CONFIDENCE_UNKNOWN
    elif len(scripts) > 1:
        confidence = CONFIDENCE_LOW
    else:
        confidence = CONFIDENCE_HIGH

    requested = canonical_language(requested_language)
    if requested is None:
        requested = detect_requested_language(original)
    conversation_lang = conversation_language(conversation, conversation_window)
    default = canonical_language(default_language)
    response_language, source = resolve_response_language(
        requested, conversation_lang, detected, default)

    return LanguageContext(
        original_text=original, normalized_text=normalized_text,
        detected_language=detected, detection_confidence=confidence,
        detection_method=DETECTION_METHOD_SCRIPT_HEURISTIC, scripts=scripts,
        conversation_language=conversation_lang, requested_language=requested,
        default_language=default, response_language=response_language,
        response_language_source=source)
