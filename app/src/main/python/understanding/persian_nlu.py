"""
Understanding - Persian NLU v1 (Prompt 824)
=============================================
A small, deterministic, fully local recognizer for a handful of ordinary
Persian conversational inputs. It is NOT a language model and does NOT
claim general Persian understanding: it knows a fixed set of sentence
patterns and nothing else. Anything it does not recognize is reported as
`INTENT_UNKNOWN`, which Core (core/core.py) sends to the existing
fallback exactly as before.

Same input -> same result, always: no randomness, no clock, no network,
no state kept between calls, no external dependency (stdlib only).

Recognized (after `normalize_persian`):

  introduce_name   "من عرفان هستم"            -> fact user.name = عرفان
                   "اسم من عرفانه" / "اسمم عرفان است" / "نام من عرفان هست"
  like             "من پیتزا رو دوست دارم"     -> fact user.likes = پیتزا
  dislike          "من پیتزا رو دوست ندارم"    -> fact user.dislikes = پیتزا
  ask_user_name    "اسم من چیه؟"               (asks for the stored name)
  request          "لطفا یه جوک بگو", "میشه کمک کنی؟"
  question         "پایتون چیه؟", "چرا آسمون آبیه؟"
  unknown          everything else (including ordinary statements)

Result: `PersianNLUResult` with `intent`, `entities`, `facts`,
`confidence`, plus `normalized_text` and `matched_rule` for inspection.

Known limitations (v1, on purpose):
  * "من X هستم" cannot tell a name from a state ("من خسته هستم"); a small
    fixed stop-list of common states/adjectives is rejected, nothing more.
  * Colloquial "اسم من Xه" strips one trailing "ه" (the spoken copula);
    a name that itself ends in "ه" (e.g. فرزانه) is therefore shortened.
    That form is reported with lower confidence.
  * Question/request detection is a fixed word list, not parsing.
"""

import re
import unicodedata

INTENT_INTRODUCE_NAME = "introduce_name"
INTENT_LIKE = "like"
INTENT_DISLIKE = "dislike"
INTENT_ASK_USER_NAME = "ask_user_name"
INTENT_REQUEST = "request"
INTENT_QUESTION = "question"
INTENT_UNKNOWN = "unknown"

# Intents that carry a fact for the Memory/Learning system.
FACT_INTENTS = (INTENT_INTRODUCE_NAME, INTENT_LIKE, INTENT_DISLIKE)

PREDICATE_NAME = "name"
PREDICATE_LIKES = "likes"
PREDICATE_DISLIKES = "dislikes"

# --- normalization ----------------------------------------------------
_CHAR_MAP = {
    "\u064a": "\u06cc",  # ARABIC YEH -> PERSIAN YEH
    "\u0649": "\u06cc",  # ALEF MAKSURA -> PERSIAN YEH
    "\u0643": "\u06a9",  # ARABIC KAF -> PERSIAN KEHEH
    "\u0629": "\u0647",  # TEH MARBUTA -> HEH
    "\u06c0": "\u0647",  # HEH WITH YEH ABOVE -> HEH
    "\u0623": "\u0627",  # ALEF WITH HAMZA ABOVE -> ALEF
    "\u0625": "\u0627",  # ALEF WITH HAMZA BELOW -> ALEF
    "\u061f": "?",       # ARABIC QUESTION MARK
    "\u060c": ",",       # ARABIC COMMA
    "\u200c": " ",       # ZWNJ -> space ("می‌خوام" == "می خوام")
    "\u200f": "",        # RTL mark
    "\u200e": "",        # LTR mark
    "\u0640": "",        # TATWEEL
}
for _i, _d in enumerate("۰۱۲۳۴۵۶۷۸۹"):
    _CHAR_MAP[_d] = str(_i)
for _i, _d in enumerate("٠١٢٣٤٥٦٧٨٩"):
    _CHAR_MAP[_d] = str(_i)

_DIACRITICS_RE = re.compile("[\u064b-\u065f\u0670]")
_TRAILING_PUNCT_RE = re.compile(r"[\s\.\!,;:\u2026]+$")


def normalize_persian(raw_text):
    """Canonical form used for matching only (the original text is never
    altered elsewhere). NFKC, Arabic->Persian letter variants, diacritics
    and tatweel removed, Persian/Arabic digits -> ASCII, ZWNJ -> space,
    whitespace collapsed. Never raises; None -> ''."""
    if raw_text is None:
        return ""
    text = unicodedata.normalize("NFKC", str(raw_text))
    text = _DIACRITICS_RE.sub("", text)
    text = "".join(_CHAR_MAP.get(ch, ch) for ch in text)
    return " ".join(text.split())


# --- lexicons ---------------------------------------------------------
_NOT_A_NAME = frozenset((
    "خسته", "گرسنه", "تشنه", "خوب", "بد", "ناراحت", "خوشحال", "مریض", "بیکار",
    "آماده", "مطمئن", "ایرانی", "دانشجو", "معلم", "پزشک", "دکتر", "مهندس",
    "اینجا", "آنجا", "همینجا", "کی", "چی", "کجا", "کدام", "کدوم", "عصبانی",
    "بیدار", "خوابیده", "تنها", "راضی", "نگران", "سرحال", "بی حوصله",
))
_STRIP_ADVERBS = frozenset(("خیلی", "واقعا", "حسابی", "بسیار", "زیاد"))
_NAME_PREFIXES = ("اسم من", "نام من", "اسمم", "نامم")
_COPULAS = ("است", "هست", "هستش", "ه")
_QUESTION_WORDS = frozenset((
    "چی", "چیه", "چیست", "چرا", "چطور", "چگونه", "کی", "کیه", "کجا", "کجاست",
    "کدام", "کدوم", "آیا", "چند", "چقدر", "چه", "کیست", "چجوری", "چطوری",
))
_REQUEST_PREFIXES = (
    "لطفا", "میشه", "می شه", "میتونی", "می تونی", "میتوانی", "می توانی",
    "ممکنه", "ممکن است", "بتونی", "لطف کن", "خواهش میکنم", "خواهش می کنم",
)
_REQUEST_ENDINGS = (
    "بگو", "بنویس", "بساز", "بده", "بکن", "کن", "بفرست", "بخون", "بیار",
    "بگیر", "نشون بده", "نشان بده", "پیدا کن", "کمک کن", "توضیح بده",
    "ترجمه کن", "برام بگو", "بهم بگو", "یادم بنداز", "بگرد", "باز کن",
)

_NAME_STATEMENT_RE = re.compile(r"^من (.+) هستم$")
_LIKE_RE = re.compile(r"^من (.+?) (?:رو |را )?دوست (دارم|ندارم)$")
_ASK_NAME_RE = re.compile(
    r"^(?:اسم من|نام من|اسمم|نامم) (?:چیه|چی هست|چی بود|چیست|چی)$")


class PersianNLUResult:
    """Structured, immutable-by-convention NLU outcome."""

    __slots__ = ("intent", "entities", "facts", "confidence",
                 "normalized_text", "matched_rule")

    def __init__(self, intent, entities, facts, confidence, normalized_text, matched_rule):
        self.intent = intent
        self.entities = entities
        self.facts = facts
        self.confidence = confidence
        self.normalized_text = normalized_text
        self.matched_rule = matched_rule

    @property
    def is_recognized(self):
        return self.intent != INTENT_UNKNOWN

    def to_dict(self):
        return {
            "intent": self.intent,
            "entities": dict(self.entities),
            "facts": [dict(f) for f in self.facts],
            "confidence": self.confidence,
            "normalized_text": self.normalized_text,
            "matched_rule": self.matched_rule,
        }

    def __eq__(self, other):
        return isinstance(other, PersianNLUResult) and self.to_dict() == other.to_dict()

    def __repr__(self):
        return f"PersianNLUResult({self.to_dict()!r})"


def _result(intent, text, rule, entities=None, facts=None, confidence=0.0):
    return PersianNLUResult(intent, entities or {}, facts or [], confidence, text, rule)


def _fact(predicate, value):
    return {"subject": "user", "predicate": predicate, "value": value}


def _clean_item(phrase):
    tokens = [t for t in phrase.split(" ") if t]
    while tokens and tokens[0] in _STRIP_ADVERBS:
        tokens.pop(0)
    return " ".join(tokens)


def _name_from_tokens(tokens, colloquial_ok):
    """Returns (name, confidence) or None. 1-2 tokens only."""
    if tokens and tokens[-1] in ("است", "هست", "هستش"):
        tokens = tokens[:-1]
        colloquial = False
    else:
        colloquial = colloquial_ok
    if not tokens or len(tokens) > 2:
        return None
    confidence = 0.95
    if colloquial and len(tokens) == 1 and tokens[0].endswith("ه") and len(tokens[0]) > 2:
        tokens = [tokens[0][:-1]]
        confidence = 0.85
    name = " ".join(tokens)
    if not name or name in _NOT_A_NAME or any(ch.isdigit() for ch in name):
        return None
    return name, confidence


_ARABIC_SCRIPT_RE = re.compile("[\u0600-\u06ff]")


def prepare_persian(raw_text):
    """Shared pre-processing for every recognizer. Returns
    (text, body, asks, has_persian_script):

      text   - `normalize_persian(raw_text)`
      body   - `text` without trailing punctuation / question marks
               ('' when there are no Arabic-script letters at all)
      asks   - True when the message ends with a question mark
      has_persian_script - False for input with no Arabic-script letters
    """
    text = normalize_persian(raw_text)
    if not _ARABIC_SCRIPT_RE.search(text):
        return text, "", False, False
    body = _TRAILING_PUNCT_RE.sub("", text)
    asks = body.endswith("?") or text.endswith("?")
    body = body.rstrip("? ").strip()
    return text, body, asks, True


# --- v1 rules ---------------------------------------------------------
# Each rule is `rule(text, body, asks) -> PersianNLUResult | None`. None
# means "does not match, try the next rule". The ordered tuple V1_RULES
# below is the v1 behavior; `analyze_persian` walks it, and the NLU
# pipeline (understanding/nlu_pipeline.py) registers each rule as its own
# component in the same order.

def _rule_name_hastam(text, body, asks):
    # "من X هستم"
    m = _NAME_STATEMENT_RE.match(body)
    if m and not asks:
        got = _name_from_tokens(m.group(1).split(" "), colloquial_ok=False)
        if got:
            name, conf = got
            return _result(INTENT_INTRODUCE_NAME, text, "name_hastam",
                           {"name": name}, [_fact(PREDICATE_NAME, name)], conf)
    return None


def _rule_name_esm_man(text, body, asks):
    # "اسم من X" / "اسم من Xه"
    if not asks:
        for prefix in _NAME_PREFIXES:
            if body.startswith(prefix + " "):
                got = _name_from_tokens(body[len(prefix) + 1:].split(" "), colloquial_ok=True)
                if got:
                    name, conf = got
                    return _result(INTENT_INTRODUCE_NAME, text, "name_esm_man",
                                   {"name": name}, [_fact(PREDICATE_NAME, name)], conf)
                break
    return None


def _rule_like_dislike(text, body, asks):
    m = _LIKE_RE.match(body)
    if m and not asks:
        item = _clean_item(m.group(1))
        if item and len(item.split(" ")) <= 3:
            negative = m.group(2) == "ندارم"
            intent = INTENT_DISLIKE if negative else INTENT_LIKE
            predicate = PREDICATE_DISLIKES if negative else PREDICATE_LIKES
            return _result(intent, text, "like_dislike", {"item": item},
                           [_fact(predicate, item)], 0.9)
    return None


def _rule_ask_user_name(text, body, asks):
    if _ASK_NAME_RE.match(body):
        return _result(INTENT_ASK_USER_NAME, text, "ask_user_name", {}, [], 0.9)
    return None


def _rule_request_prefix(text, body, asks):
    for prefix in _REQUEST_PREFIXES:
        if body == prefix or body.startswith(prefix + " "):
            return _result(INTENT_REQUEST, text, "request_prefix",
                           {"marker": prefix}, [], 0.7)
    return None


def _rule_request_ending(text, body, asks):
    for ending in _REQUEST_ENDINGS:
        if body == ending or body.endswith(" " + ending):
            return _result(INTENT_REQUEST, text, "request_ending",
                           {"marker": ending}, [], 0.6)
    return None


def _rule_question(text, body, asks):
    # question mark or a question word
    marker = next((t for t in body.split(" ") if t in _QUESTION_WORDS), None)
    if asks or marker:
        entities = {"marker": marker} if marker else {}
        return _result(INTENT_QUESTION, text, "question_mark" if asks else "question_word",
                       entities, [], 0.7 if marker else 0.5)
    return None


V1_RULES = (
    ("name_hastam", _rule_name_hastam),
    ("name_esm_man", _rule_name_esm_man),
    ("like_dislike", _rule_like_dislike),
    ("ask_user_name", _rule_ask_user_name),
    ("request_prefix", _rule_request_prefix),
    ("request_ending", _rule_request_ending),
    ("question", _rule_question),
)


def analyze_persian(raw_text):
    """Analyze one message. Pure function; never raises. Input with no
    Arabic-script (Persian) letters at all is always `unknown` - this
    component never claims to understand English or any other language.

    This is the original, fixed v1 recognizer and is kept exactly as the
    reference behavior: the NLU pipeline's default registry reproduces it
    rule for rule (see understanding/nlu_pipeline.py)."""
    text, body, asks, has_script = prepare_persian(raw_text)
    if not has_script or not body:
        return _result(INTENT_UNKNOWN, text, None)
    for _name, rule in V1_RULES:
        got = rule(text, body, asks)
        if got is not None:
            return got
    return _result(INTENT_UNKNOWN, text, None)


class PersianNLU:
    """Thin object wrapper so Core can hold one component and tests can
    substitute it.

    `analyze(text)` keeps its v1 contract - stateless, returns a
    `PersianNLUResult` - but now delegates to an NLU pipeline
    (understanding/nlu_pipeline.py) whose registry holds the recognizers.
    The default pipeline reproduces `analyze_persian` exactly; further
    components can be added through `registry` without touching this file.

    `analyze_in_context(text, context)` additionally returns the full
    structured analysis (question / request / negation / correction /
    conversational-context details) and records the turn into `context`.
    """

    def __init__(self, pipeline=None):
        if pipeline is None:
            from .nlu_pipeline import default_pipeline
            pipeline = default_pipeline()
        self.pipeline = pipeline

    @property
    def registry(self):
        return self.pipeline.registry

    def analyze(self, raw_text):
        return self.pipeline.analyze_intent(raw_text)

    def analyze_structured(self, raw_text, context=None):
        """Full structured analysis; does NOT modify `context`."""
        return self.pipeline.analyze(raw_text, context)

    def analyze_in_context(self, raw_text, context):
        """Structured analysis, then record the turn into `context`
        (when given)."""
        analysis = self.pipeline.analyze(raw_text, context)
        if context is not None:
            context.record(analysis)
        return analysis
