"""
Persian conversation brain - intent classification
==================================================
`classify(text, ctx)` turns one normalized Persian message into an `Intent`:

  GREETING      hello / wellbeing / thanks / farewell (optionally followed by
                the real request: "سلام، ۱۰ کیلومتر چند مایل است؟")
  QUESTION      a question (about capabilities, the user's memory, taught
                knowledge, ...)
  REQUEST       something to be done: build a capability, compute, ...
  COMMAND       control of the capability registry: list, details, history,
                status, help, roll back, switch off
  STATEMENT     an assertion about the world ("پایتون یک زبان برنامه‌نویسی است")
  TEACHING      an explicit instruction to remember ("یاد بگیر که ...")
  CONTINUATION  yes / no / cancel / "go on" / the answer to a question the
                brain asked (only meaningful with a pending question)
  REFERENCE     "the same one, for 20" - refers back to the last capability
  FEEDBACK      "آفرین" / "اشتباه بود"
  UNKNOWN       anything else (the brain then lets the application's existing
                Persian NLU / reasoning / fallback handle the message)

It is a deterministic cascade over normalized tokens and the closed word
lists of lexicon.py (plus the project's own Persian NLU for the generic
question/request shapes) - never a table of whole sentences. The classifier
is pure: what it needs to know about the conversation arrives in `Context`.
"""

import re

from self_builder import fa_text, request_parser, units
from understanding import persian_nlu

from . import lexicon as lx
from . import normalization as nz

GREETING = "GREETING"
QUESTION = "QUESTION"
REQUEST = "REQUEST"
COMMAND = "COMMAND"
STATEMENT = "STATEMENT"
TEACHING = "TEACHING"
CONTINUATION = "CONTINUATION"
REFERENCE = "REFERENCE"
FEEDBACK = "FEEDBACK"
UNKNOWN = "UNKNOWN"

KINDS = (GREETING, QUESTION, REQUEST, COMMAND, STATEMENT, TEACHING, CONTINUATION, REFERENCE, FEEDBACK, UNKNOWN)

_TOKEN_SPAN_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?|[^\W\d_]+(?:['\-][^\W\d_]+)*", re.UNICODE)
_EDGE_PUNCT = " \t\n,.!?;:،؛-–—…"

# fixed small helper lists local to the classifier
_FLAVOR = {"صبح": "morning", "ظهر": "noon", "عصر": "afternoon", "شب": "evening", "روز": "day", "وقت": "day"}
_AMBIGUOUS_GREETINGS = frozenset({("های",), ("هی",)})
_WELLBEING_WORDS = frozenset(w for ph in lx.WELLBEING_PHRASES for w in ph)
_VOCATIVE_NOUNS = frozenset({"دوست", "جان", "رفیق", "عزیز"})
_THANKS_WORDS = frozenset(w for ph in lx.THANKS_PHRASES for w in ph)
_THANKS_FILLER = frozenset({"خیلی", "زیاد", "از", "کمکت", "لطفت", "راهنماییت", "جوابت", "پاسخت", "زحمتت", "بابت",
                            "همه", "چیز", "عزیزم", "دوست", "من", "جان", "واقعا", "ی", "بسیار", "فراوان", "کمک",
                            "ت", "تو", "شما", "هم", "دوباره"})
_FAREWELL_WORDS = frozenset(w for ph in lx.FAREWELL_PHRASES for w in ph) | frozenset(
    {"خوش", "من", "دیگه", "پس", "عزیزم", "دوست", "جان", "الان", "خب", "باشه", "ممنون", "مرسی", "و"})
_FEEDBACK_WORDS = (frozenset(w for ph in (lx.POSITIVE_PHRASES | lx.NEGATIVE_PHRASES) for w in ph) | lx.NEGATIVE_WORDS
                   | frozenset({"خیلی", "واقعا", "این", "جواب", "جوابت", "کارت", "ت", "بود", "شد", "که", "را", "رو",
                                "دیگه", "هم", "عزیزم", "ممنون", "مرسی", "همین", "درست", "دقیقا", "نبود", "نیست",
                                "کردی", "گفتی", "دادی", "بسیار", "کار", "نکرد", "نه", "آره", "بله"}))
_COMPUTE_VERBS = frozenset({"حساب", "محاسبه", "تبدیل", "امتحان", "اجرا", "بزن", "تست", "بگو", "بده", "کن", "کنید"})
_REFERENCE_LEAD = frozenset({"و", "برای", "با", "پس", "اگر", "حالا", "همچنین"})
# what a short follow-up like «برای ۳۰ چی؟» may consist of besides its number (and at most one unit)
_FOLLOW_UP_WORDS = _REFERENCE_LEAD | frozenset({"چی", "چه", "چقدر", "چنده", "چند", "چطور", "چطوره", "میشه", "شه", "شود",
                                                "بشه", "باشه", "باشد", "هم", "است", "هست"})
_FIRST_PERSON = frozenset({"من", "ما", "خودم", "خودمان"})
_OBJECT_CLITICS = ("شون", "شو", "ش")   # «غیرفعالش کن» / «برگردونش» / «خاموششون کن»
_UNIT_STOP = frozenset({"ی", "های"})


class Intent:
    """One classification result (plain data)."""

    __slots__ = ("kind", "sub", "confidence", "evidence", "slots")

    def __init__(self, kind, sub=None, confidence=0.5, evidence=(), slots=None):
        self.kind = kind
        self.sub = sub
        self.confidence = confidence
        self.evidence = tuple(evidence)
        self.slots = dict(slots or {})

    def is_(self, kind, sub=None):
        return self.kind == kind and (sub is None or self.sub == sub)

    def to_dict(self):
        slots = {k: v for k, v in self.slots.items() if k != "request"}
        return {"kind": self.kind, "sub": self.sub, "confidence": self.confidence,
                "evidence": list(self.evidence), "slots": slots}

    def __repr__(self):
        return f"Intent({self.kind}/{self.sub}, {self.confidence:.2f}, {list(self.evidence)})"


class Context:
    """What the classifier needs to know about the conversation."""

    __slots__ = ("pending_type", "last_kind", "mentions_capability")

    def __init__(self, pending_type=None, last_kind=None, mentions_capability=False):
        self.pending_type = pending_type
        self.last_kind = last_kind
        self.mentions_capability = bool(mentions_capability)


# ---------------------------------------------------------------- helpers --

def _stems(toks):
    """The tokens plus, for tokens that carry a spoken object clitic («غیرفعالش» = «غیرفعال» + «ش»), the bare stem."""
    out = set(toks)
    for t in toks:
        for clitic in _OBJECT_CLITICS:
            if t.endswith(clitic) and len(t) - len(clitic) >= 3:
                out.add(t[:-len(clitic)])
                break
    return out


def _spans(norm):
    return [(m.group(0).lower(), m.start(), m.end()) for m in _TOKEN_SPAN_RE.finditer(norm)]


def _text_after(norm, spans, count):
    """The normalized text after the first `count` tokens (edge punctuation trimmed)."""
    if count <= 0:
        return norm.strip(_EDGE_PUNCT)
    if count >= len(spans):
        return ""
    return norm[spans[count - 1][2]:].strip(_EDGE_PUNCT)


def _has_number(toks):
    return bool(fa_text.scan_numbers(list(toks)))


def _all_in(toks, allowed):
    return bool(toks) and all(t in allowed for t in toks)


def _asks(norm, toks):
    return nz.ends_with_question(norm) or any(t in lx.QUESTION_WORDS for t in toks) or (bool(toks) and toks[0] == "آیا")


# ----------------------------------------------------------- pending words --

def answer_word(toks):
    """'confirm' | 'deny' | 'cancel' | None for a short reply to a pending question."""
    if not toks or len(toks) > 5:
        return None
    tset = set(toks)
    if (_stems(toks) & lx.CANCEL_WORDS) or lx.any_phrase(toks, lx.CANCEL_PHRASES):
        return "cancel"
    if len(toks) <= 4 and ((tset & lx.DENY_WORDS and _all_in(toks, lx.DENY_WORDS | lx.NEGATIVE_FILLER | lx.CONFIRM_TAIL
                                                              | {"لازم", "نیست", "نیازی", "خواد", "خوام", "شده"}))
                           or lx.any_phrase(toks, lx.DENY_PHRASES)):
        return "deny"
    if len(toks) <= 4 and tset & lx.CONFIRM_WORDS and not tset & lx.DENY_WORDS \
            and _all_in(toks, lx.CONFIRM_WORDS | lx.CONFIRM_TAIL | lx.NEGATIVE_FILLER):
        return "confirm"
    return None


# ------------------------------------------------------------------ social --

def _greeting_prefix(toks):
    """(number of leading greeting tokens, flavor) or (0, None)."""
    best, flavor = 0, None
    for ph in lx.GREETING_PHRASES:
        if lx.starts_with(toks, ph) and len(ph) > best:
            if ph in _AMBIGUOUS_GREETINGS and len(toks) > 3:
                continue
            best = len(ph)
            if ph[0] in _FLAVOR and "بخیر" in ph:
                flavor = _FLAVOR[ph[0]]
    if toks and toks[0] in lx.GREETING_WORDS and best == 0:
        best = 1
        while best < len(toks) and toks[best] in ("علیکم", "و", "درود"):
            best += 1
    return best, flavor


def _social(norm, toks, spans):
    """GREETING intent for greeting/thanks/farewell/wellbeing messages, or None."""
    if not toks:
        return None
    k, flavor = _greeting_prefix(toks)
    if k:
        j = k
        while j < len(toks) and (toks[j] in lx.GREETING_TAIL or toks[j] in _WELLBEING_WORDS):
            if toks[j] == "من" and j + 1 < len(toks) and not (j > k and toks[j - 1] in _VOCATIVE_NOUNS):
                break  # «سلام، من عرفان هستم»: this «من» begins a sentence; only «دوست من / جان من» is a greeting tail
            j += 1
        wellbeing = lx.any_phrase(toks[k:], lx.WELLBEING_PHRASES)
        if j == len(toks):  # nothing but the greeting (and tail words)
            return Intent(GREETING, "wellbeing" if wellbeing else "hello", 0.95, ["greeting_prefix"],
                          {"flavor": flavor})
        rest = _text_after(norm, spans, j)
        return Intent(GREETING, "hello", 0.9, ["greeting_prefix"],
                      {"flavor": flavor, "rest": rest, "wellbeing": wellbeing})
    if _has_number(toks):  # thanks / farewell / bare wellbeing never carry a number
        return None
    if len(toks) <= 6 and _all_in(toks, _WELLBEING_WORDS | lx.GREETING_TAIL) and \
            lx.any_phrase(toks, lx.WELLBEING_PHRASES):
        return Intent(GREETING, "wellbeing", 0.85, ["wellbeing_phrase"])
    if len(toks) <= 6 and lx.any_phrase(toks, lx.THANKS_PHRASES) and _all_in(toks, _THANKS_WORDS | _THANKS_FILLER):
        return Intent(GREETING, "thanks", 0.9, ["thanks_phrase"])
    if len(toks) <= 5 and lx.any_phrase(toks, lx.FAREWELL_PHRASES) and _all_in(toks, _FAREWELL_WORDS):
        return Intent(GREETING, "farewell", 0.9, ["farewell_phrase"])
    return None


# ---------------------------------------------------------------- feedback --

def _feedback(norm, toks):
    if not toks or len(toks) > 6 or _has_number(toks) or nz.ends_with_question(norm):
        return None
    if any(t in lx.QUESTION_WORDS for t in toks):
        return None
    if not _all_in(toks, _FEEDBACK_WORDS):  # "امروز هوا خوبه" is weather talk, not feedback
        return None
    tset = set(toks)
    negative = lx.any_phrase(toks, lx.NEGATIVE_PHRASES) or (len(toks) <= 4 and bool(tset & lx.NEGATIVE_WORDS))
    if negative:
        return Intent(FEEDBACK, "negative", 0.85, ["negative_feedback"])
    if lx.any_phrase(toks, lx.POSITIVE_PHRASES):
        return Intent(FEEDBACK, "positive", 0.85, ["positive_feedback"])
    return None


# ------------------------------------------------------------------- build --

_THING_WORDS = frozenset({"قابلیت", "توانایی", "امکان", "ابزار", "برنامه", "نرمافزار", "اپلیکیشن", "اپ", "ماژول",
                          "افزونه", "سیستم", "ربات", "مبدل", "فرمول", "ماشینحساب", "ماشین", "قابلیتی", "نرم"})
_STRICT_CAP_NOUNS = frozenset({"قابلیت", "توانایی", "امکان", "ابزار", "مبدل", "فرمول", "ماشینحساب", "محاسبهگر",
                               "تبدیلکننده", "قابلیتی", "قابلیتها", "ابزاری", "فرمولی", "مبدلی"})


def _squashed(toks):
    return request_parser._squash(list(toks))


def _build_intent(text, toks):
    """REQUEST/build (and /build_unsupported) for a request to build a capability, or None."""
    markers = request_parser.build_markers(text)
    strong = markers & {"build_verb", "learn", "new_capability"}
    if not strong and "want_need" in markers:
        # "من می‌خواهم ۱۰ کیلومتر را به مایل تبدیل کنم" is a computation, not "build me a converter"
        if _has_number(toks) and not (set(_squashed(toks)) & _STRICT_CAP_NOUNS):
            return None
    elif not strong and "want_need" not in markers:
        return None
    req = request_parser.parse_build_request(text)
    if req.status in (request_parser.STATUS_READY, request_parser.STATUS_CLARIFY):
        return Intent(REQUEST, "build", 0.9, ["build_markers:" + ",".join(sorted(markers))], {"request": req})
    if req.status == request_parser.STATUS_UNSUPPORTED and (set(_squashed(toks)) & _THING_WORDS):
        return Intent(REQUEST, "build_unsupported", 0.7, ["no_supported_archetype"], {"request": req})
    return None


# ----------------------------------------------------------------- command --

def _version_number(toks):
    """N of 'نسخه N' / 'ورژن N' (None when absent)."""
    for i, t in enumerate(toks):
        if t in lx.EXPLICIT_VERSION_WORDS and i + 1 < len(toks):
            v = fa_text.parse_number(toks[i + 1])
            if v is not None and v == int(v) and v >= 1:
                return int(v)
    for s, e, v in fa_text.scan_numbers(list(toks)):
        if s > 0 and toks[s - 1] in lx.EXPLICIT_VERSION_WORDS and v == int(v) and v >= 1:
            return int(v)
    return None


def _command(toks, ctx):
    tset = _stems(toks)
    cap_word = bool(tset & lx.CAP_WORDS)
    topic = cap_word or ctx.mentions_capability
    has_last = ctx.last_kind in ("invoke", "build", "describe", "rollback")
    if tset & lx.ROLLBACK_WORDS and (topic or tset & lx.ROLLBACK_CONTEXT or has_last or tset & lx.EXPLICIT_VERSION_WORDS):
        return Intent(COMMAND, "rollback", 0.85, ["rollback_word"], {"version": _version_number(toks)})
    if topic and (tset & {"غیرفعال", "خاموش", "حذف", "پاک"} or lx.contains(toks, ("غیر", "فعال"))):
        return Intent(COMMAND, "disable", 0.85, ["disable_word"], {})
    if (lx.any_phrase(toks, lx.HISTORY_PHRASES) or tuple(toks) in lx.HISTORY_BARE
            or (tset & lx.HISTORY_WORDS and (tset & lx.HISTORY_CONTEXT or topic))):
        return Intent(COMMAND, "history", 0.85, ["history_word"], {})
    if tset & lx.STATUS_WORDS and tset & lx.STATUS_CONTEXT:
        return Intent(COMMAND, "status", 0.8, ["status_word"], {})
    if tset & lx.DETAIL_WORDS and (topic or (has_last and len(toks) <= 4)):
        return Intent(COMMAND, "detail", 0.8, ["detail_word"], {})
    # «آیا قابلیت تبدیل متر به فوت را داری؟» names one concrete capability: that is a question about it, not a request
    # for the whole list («قابلیت‌هایت را نشان بده» / «چه قابلیت‌هایی داری؟»)
    names_two_units = len(units.find_units(list(toks))) >= 2
    if lx.any_phrase(toks, lx.CAP_LIST_QUESTION) or (cap_word and tset & lx.LIST_WORDS and not names_two_units):
        return Intent(COMMAND, "list", 0.85, ["capability_list"], {})
    if (tset & lx.HELP_WORDS and len(toks) <= 3) or lx.any_phrase(toks, lx.HELP_PHRASES):
        return Intent(COMMAND, "help", 0.8, ["help_word"], {})
    return None


# ----------------------------------------------------------------- teaching --

_TEACH_LEADS = tuple(sorted((lx.phrase(p) for p in lx.TEACH_LEAD), key=len, reverse=True))


def _teaching(norm, toks, spans):
    for lead in _TEACH_LEADS:
        if lx.starts_with(toks, lead):
            used = len(lead)
            if used < len(toks) and toks[used] == "که":
                used += 1
            body_tokens = toks[used:]
            body = _text_after(norm, spans, used)
            if len(body_tokens) < 3:
                return Intent(TEACHING, "incomplete", 0.8, ["teach_lead"], {"body": body})
            return Intent(TEACHING, "teach", 0.9, ["teach_lead"], {"body": body})
    return None


# ---------------------------------------------------------------- reference --

def _is_follow_up(toks, nums):
    """True when everything besides the number(s) is follow-up wording or ONE
    unit - «برای ۳۰ چی؟» / «۵۰ کیلومتر چی؟» follow up, «۱۰۰ کیلومتر چند مایل است؟» is a full question."""
    skip = set()
    for start, end, _value in nums:
        skip.update(range(start, end))
    found = units.find_units(list(toks))
    if len(found) > 1:
        return False
    for start, end, _unit in found:
        skip.update(range(start, end))
    return all(t in _FOLLOW_UP_WORDS for i, t in enumerate(toks) if i not in skip)


def _reference(toks, ctx):
    if ctx.last_kind not in ("invoke", "build", "describe"):
        return None
    tset = set(toks)
    nums = fa_text.scan_numbers(list(toks))
    if tset & lx.REFERENCE_WORDS and (nums or tset & _COMPUTE_VERBS):
        return Intent(REFERENCE, "recompute", 0.8, ["reference_word"], {})
    if ctx.last_kind == "invoke" and nums and len(toks) <= 5 and _is_follow_up(toks, nums) and (
            toks[0] in _REFERENCE_LEAD or tset & {"چی", "چه", "چقدر", "چند", "چنده"} or toks[-1] in ("چی", "چطور")):
        return Intent(REFERENCE, "recompute", 0.7, ["short_follow_up_with_number"], {})
    if ctx.last_kind == "invoke" and len(toks) <= 4 and lx.any_phrase(toks, lx.REPEAT_PHRASES):
        return Intent(REFERENCE, "repeat", 0.75, ["repeat_phrase"], {})
    return None


# ------------------------------------------------------------------ question --

def _question(norm, toks):
    if not _asks(norm, toks):
        return None
    tset = set(toks)
    if lx.any_phrase(toks, lx.LIKES_Q):
        return Intent(QUESTION, "likes", 0.9, ["likes_question"])
    if lx.any_phrase(toks, lx.CAP_LIST_QUESTION) or tset & lx.CAP_QUESTION_WORDS:
        return Intent(QUESTION, "capability", 0.6, ["capability_question_word"])
    subject = [t for t in toks if t not in lx.QUESTION_FILLER and t not in lx.QUESTION_WORDS]
    return Intent(QUESTION, "general", 0.6, ["question_form"], {"content": subject})


# ------------------------------------------------------------------- public --

def classify(text, ctx=None):
    """Classify one message (see the module docstring). Never raises."""
    ctx = ctx or Context()
    norm = nz.normalize(text)
    toks = fa_text.words(norm)
    if not toks:
        return Intent(UNKNOWN, "empty", 1.0)
    spans = _spans(norm)

    if ctx.pending_type:
        word = answer_word(toks)
        if word:
            return Intent(CONTINUATION, word, 0.95, ["pending:" + ctx.pending_type])

    social = _social(norm, toks, spans)
    if social is not None:
        return social

    feedback = _feedback(norm, toks)
    if feedback is not None:
        return feedback

    build = _build_intent(text, toks)
    if build is not None:
        return build

    command = _command(toks, ctx)
    if command is not None:
        return command

    teach = _teaching(norm, toks, spans)
    if teach is not None:
        return teach

    ref = _reference(toks, ctx)
    if ref is not None:
        return ref

    stripped = tuple(t for t in toks if t != "لطفا")
    if stripped in lx.MORE_PHRASES:
        return Intent(CONTINUATION, "more", 0.8, ["more_phrase"])

    question = _question(norm, toks)
    if question is not None:
        return question

    nlu = persian_nlu.analyze_persian(norm)
    if nlu.intent == persian_nlu.INTENT_REQUEST:
        return Intent(REQUEST, "generic", nlu.confidence, ["persian_nlu:" + str(nlu.matched_rule)])
    if nlu.intent == persian_nlu.INTENT_QUESTION:
        return Intent(QUESTION, "general", nlu.confidence, ["persian_nlu:" + str(nlu.matched_rule)],
                      {"content": [t for t in toks if t not in lx.QUESTION_FILLER and t not in lx.QUESTION_WORDS]})

    if len(toks) >= 3 and toks[-1] in lx.COPULAS and toks[0] not in _FIRST_PERSON:
        return Intent(STATEMENT, "assertion", 0.6, ["copula_ending"], {"sentence": norm.strip(_EDGE_PUNCT)})
    if len(toks) >= 3 and toks[-1] in lx.COPULAS:
        return Intent(STATEMENT, "first_person", 0.5, ["copula_ending", "first_person"],
                      {"sentence": norm.strip(_EDGE_PUNCT)})
    return Intent(UNKNOWN, "unmatched", 0.0)


__all__ = ["Intent", "Context", "classify", "answer_word", "KINDS", "GREETING", "QUESTION", "REQUEST", "COMMAND",
           "STATEMENT", "TEACHING", "CONTINUATION", "REFERENCE", "FEEDBACK", "UNKNOWN"]
