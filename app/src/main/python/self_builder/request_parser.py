"""
Self-Builder - Persian build-request analysis
=============================================
Turns an ordinary Persian sentence such as

    «یک مبدل از کیلومتر به مایل بساز»
    «فرمول مساحت دایره را یاد بگیر: π × r ^ 2»
    «من یک قابلیت جدید نیاز دارم»

into a structured `BuildRequest` (archetype + slots), or says what is missing.
It is fixed grammar over small closed word lists (the unit table, the formula
and text-operation vocabularies) - not a language model: a sentence outside
that grammar yields `unsupported` / `needs_clarification`, never a guess.

Status of a parse:
  not_a_request        no build/need marker at all (the sentence is something else)
  ready                archetype + all required slots present
  needs_clarification  a build request whose archetype or slots are incomplete
                       (`missing` says what; the conversation layer asks)
  unsupported          a build request for something outside the archetypes

Normalisation (Arabic/Persian letter variants, ZWNJ, digits, punctuation) comes
from fa_text.canon, which builds on the project's Persian NLU normalisation.
"""

import re

from . import expr as expr_mod
from . import fa_text, policy, repair, textops, units

STATUS_NOT_REQUEST = "not_a_request"
STATUS_READY = "ready"
STATUS_CLARIFY = "needs_clarification"
STATUS_UNSUPPORTED = "unsupported"

_BUILD_TOKENS = frozenset({"بساز", "بسازی", "بسازید", "بسازین", "بسازم", "بسازد", "ساخته"})
_BUILD_NOUN_VERB = frozenset({"درست", "ایجاد", "اضافه", "طراحی", "پیاده", "پیادهسازی", "تعریف", "ثبت"})
_AUX = frozenset({"کن", "کنی", "کنید", "کنین", "کردن", "شود", "بشود", "بشه", "بکن", "بکنی", "بکنید"})
_LEARN = frozenset({"یادبگیر", "یادبگیری", "یادبگیرید", "یادبگیرین"})
_WANT = frozenset({"میخواهم", "میخوام", "میخواستم", "خواستم", "خواهم", "میخوایم", "میخواهیم"})
_NEED = frozenset({"نیاز", "لازم", "احتیاج"})
_HAVE = frozenset({"داشتهباشی", "داشتهباشید", "داشتهباش", "داشتهباشد", "بلدباشی", "بلدباشید"})
_CAP_NOUNS = frozenset({"قابلیت", "توانایی", "امکان", "ابزار", "مبدل", "فرمول", "ماشینحساب", "ماشین", "تبدیل",
                        "محاسبه", "محاسبهگر", "تبدیلکننده", "قابلیتی", "قابلیتها"})
_CONNECTOR_WORDS = frozenset({"که", "را", "رو", "یک", "یه", "لطفا", "لطف", "یکی", "برای", "من", "به", "از", "ی"})

_CONVERT_WORDS = frozenset({"مبدل", "تبدیل", "تبدیلکننده", "مبدلی", "تبدیلی"})
_FORMULA_WORDS = frozenset({"فرمول", "فرمولی", "ماشینحساب", "ماشینحسابی", "محاسبهگر", "محاسبهگری"})
_TEXT_TOOL_WORDS = frozenset({"ابزار", "ابزاری"})
# Subjects no supported archetype can implement (network, messaging, files, devices, money, program code ...).
# A build request that names one of them and carries no concrete unit pair / formula / text operation is
# answered honestly as "not supported" instead of being steered into a clarification question.
_UNSUPPORTED_TOPICS = frozenset({
    "اینترنت", "آنلاین", "وب", "وبسایت", "سایت", "سرور", "شبکه", "وایفای", "دانلود", "آپلود", "api", "لینک",
    "مرورگر", "ایمیل", "پیامک", "sms", "تلگرام", "واتساپ", "اینستاگرام", "تماس", "فایل", "فایلها", "پوشه",
    "پوشهها", "دوربین", "میکروفون", "بلوتوث", "gps", "پرداخت", "بانک", "حسابداری", "پایتون", "اسکریپت", "کد",
    "کدها", "دستور", "شل", "ترمینال", "برنامه", "برنامهای", "نرمافزار", "اپلیکیشن", "بازی", "ربات", "پایگاه",
    "دیتابیس"})
_TERMINATORS = frozenset({"است", "هست", "هستش", "باشد", "باشه", "میشود", "میشه", "بشود", "بشه"})
_EXAMPLE_MARKERS = frozenset({"مثلا", "مثال", "نمونه", "مثلن"})
_EQUIV_WORDS = frozenset({"برابر", "معادل", "مساوی", "میشود", "میشه", "بشود", "بشه", "هست", "است"})

# text operation rules: op -> list of alternatives; each alternative is a list
# of token sets that must ALL be hit (one token per set). Evaluated in this
# order; matched tokens are consumed.
_COUNTING = frozenset({"تعداد", "شمارش", "بشمار", "بشمارد", "بشمارید", "شمارنده", "بشماری", "شمار", "بشمارم"})
_TEXT_OP_RULES = (
    ("count_chars_no_space", [[frozenset({"حروف", "نویسه", "کاراکتر", "کاراکترها", "نویسهها", "حرف"}),
                               frozenset({"بدون"}), frozenset({"فاصله", "فاصلهها"}), _COUNTING]]),
    ("strip_spaces", [[frozenset({"فاصله", "فاصلهها"}), frozenset({"اضافی", "اضافه", "زائد", "زاید", "اضافهها"})],
                      [frozenset({"فشردهسازی", "فشرده"}), frozenset({"فاصله", "فاصلهها"})]]),
    ("fix_mi_prefix", [[frozenset({"نیم"}), frozenset({"فاصله", "فاصلهگذار", "فاصلهها"})],
                       [frozenset({"نیمفاصله", "نیمفاصلهگذار"})]]),
    ("remove_spaces", [[frozenset({"حذف", "پاک", "بردار", "بردارد", "برداره", "حذفکند"}),
                        frozenset({"فاصله", "فاصلهها"})]]),
    ("count_chars", [[frozenset({"حروف", "نویسه", "کاراکتر", "کاراکترها", "نویسهها", "حرف", "کاراکترها"}), _COUNTING]]),
    ("count_words", [[frozenset({"کلمات", "کلمه", "واژه", "واژهها", "کلمهها"}), _COUNTING],
                     [frozenset({"کلمهشمار", "کلمهشماری"})]]),
    ("to_fa_digits", [[frozenset({"ارقام", "اعداد", "عدد", "رقم"}), frozenset({"فارسی"})]]),
    ("to_en_digits", [[frozenset({"ارقام", "اعداد", "عدد", "رقم"}), frozenset({"انگلیسی", "لاتین"})]]),
    ("fix_arabic_letters", [[frozenset({"عربی"}), frozenset({"ی", "ک", "حروف", "کاف", "یا"})]]),
    ("reverse", [[frozenset({"معکوس", "برعکس", "وارونه"})]]),
    ("upper", [[frozenset({"بزرگ"}), frozenset({"حروف", "متن", "لاتین"})], [frozenset({"اپرکیس", "uppercase"})]]),
    ("lower", [[frozenset({"کوچک"}), frozenset({"حروف", "متن", "لاتین"})], [frozenset({"لوورکیس", "lowercase"})]]),
)


class BuildRequest:
    """Result of analysing one sentence. Plain data (see to_dict)."""

    def __init__(self, status, kind=None, slots=None, missing=None, evidence=None, note=None):
        self.status = status
        self.kind = kind
        self.slots = slots or {}
        self.missing = list(missing or [])
        self.evidence = list(evidence or [])
        self.note = note

    @property
    def is_request(self):
        return self.status != STATUS_NOT_REQUEST

    def to_dict(self):
        return {"status": self.status, "kind": self.kind, "slots": dict(self.slots),
                "missing": list(self.missing), "evidence": list(self.evidence), "note": self.note}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("status", STATUS_NOT_REQUEST), d.get("kind"), d.get("slots"), d.get("missing"),
                   d.get("evidence"), d.get("note"))


# ------------------------------------------------------------- tokenising --

def _squash(tokens):
    """Tokens with spaces removed inside known compound words, so
    'ماشین حساب' / 'یاد بگیر' / 'داشته باشی' become single comparable tokens."""
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        pair = tokens[i] + tokens[i + 1] if i + 1 < n else None
        pair3 = tokens[i] + tokens[i + 1] + tokens[i + 2] if i + 2 < n else None
        if pair3 in _HAVE:
            out.append(pair3)
            i += 3
        elif pair in ("ماشینحساب", "یادبگیر", "یادبگیری", "یادبگیرید", "یادبگیرین", "بلدباشی", "بلدباشید",
                      "نیمفاصله", "نیمفاصلهگذار", "تبدیلکننده", "محاسبهگر", "کلمهشمار", "پیادهسازی",
                      "فشردهسازی", "داشتهباشی", "داشتهباشید", "داشتهباش", "داشتهباشد", "ماشینحسابی"):
            out.append(pair)
            i += 2
        else:
            out.append(tokens[i])
            i += 1
    return out


def _tokens(text):
    return _squash(fa_text.words(text))


def _has(tokens, vocabulary):
    return any(t in vocabulary for t in tokens)


def _has_build_verb(tokens):
    if _has(tokens, _BUILD_TOKENS):
        return True
    for i, t in enumerate(tokens):
        if t in _BUILD_NOUN_VERB and any(tokens[j] in _AUX for j in range(i + 1, min(i + 3, len(tokens)))):
            return True
    return False


def _has_want_or_need(tokens):
    if _has(tokens, _WANT) or _has(tokens, _HAVE):
        return True
    for i, t in enumerate(tokens):
        if t in _NEED and i + 1 < len(tokens) and tokens[i + 1] in ("دارم", "داریم", "هست", "است", "دارد"):
            return True
    return False


def build_markers(text):
    """Which request markers a sentence carries: subset of
    {'build_verb', 'learn', 'want_need', 'capability_noun', 'new_capability'}."""
    tokens = _tokens(text)
    found = set()
    if _has_build_verb(tokens):
        found.add("build_verb")
    if _has(tokens, _LEARN):
        found.add("learn")
    if _has_want_or_need(tokens):
        found.add("want_need")
    if _has(tokens, _CAP_NOUNS):
        found.add("capability_noun")
    for i, t in enumerate(tokens):
        if t in ("قابلیت", "قابلیتی", "توانایی", "امکان") and any(
                x in ("جدید", "جدیدی", "تازه", "دیگر", "دیگری", "جدیدتر") for x in tokens[i + 1:i + 3]):
            found.add("new_capability")
    return found


# ---------------------------------------------------------- archetype hints --

_DIGIT_NOUNS = frozenset({"ارقام", "اعداد", "عدد", "رقم", "اعدادی", "ارقامی"})
_FA_WORDS = frozenset({"فارسی"})
_EN_WORDS = frozenset({"انگلیسی", "لاتین"})


def _digit_rule(tokens, consumed, hits):
    """'ارقام فارسی را به انگلیسی' converts TO English; the language that
    follows 'به' (or the only language named) is the target."""
    noun = next((i for i, t in enumerate(tokens) if t in _DIGIT_NOUNS and i not in consumed), None)
    if noun is None:
        return
    fa_i = [i for i, t in enumerate(tokens) if t in _FA_WORDS and i not in consumed]
    en_i = [i for i, t in enumerate(tokens) if t in _EN_WORDS and i not in consumed]
    if not fa_i and not en_i:
        return
    target = None
    for i in sorted(fa_i + en_i):
        if tokens[i - 1:i] == ["به"] or (i >= 2 and tokens[i - 2] == "به"):
            target = "fa" if i in fa_i else "en"
            break
    if target is None:
        if fa_i and not en_i:
            target = "fa"
        elif en_i and not fa_i:
            target = "en"
        else:
            # both languages and no "به": in "ارقام انگلیسی را فارسی کند" the language
            # AFTER the object marker "را" is the target; anything else is ambiguous
            first, last = min(fa_i + en_i), max(fa_i + en_i)
            if any(first < i < last and t in ("را", "رو") for i, t in enumerate(tokens)):
                target = "fa" if last in fa_i else "en"
            else:
                return  # no direction word: leave to the clarification
    consumed.add(noun)
    consumed.update(fa_i + en_i)
    hits.append(("to_fa_digits" if target == "fa" else "to_en_digits", noun))


def _detect_ops(tokens):
    """[(op_id, first_index)] of text operations mentioned, in sentence order."""
    consumed = set()
    hits = []
    _digit_rule(tokens, consumed, hits)
    for op_id, alternatives in _TEXT_OP_RULES:
        if op_id in ("to_fa_digits", "to_en_digits"):
            continue
        for alt in alternatives:
            picks = []
            used = set()
            ok = True
            for needed in alt:
                idx = next((i for i, t in enumerate(tokens) if t in needed and i not in consumed and i not in used),
                           None)
                if idx is None:
                    ok = False
                    break
                picks.append(idx)
                used.add(idx)
            if ok:
                consumed.update(picks)
                hits.append((op_id, min(picks)))
                break
    hits.sort(key=lambda h: h[1])
    return hits


def detect_text_ops(text):
    """Text operations named in `text`, in sentence order (public helper
    also used to match invocations of existing text tools)."""
    return [op for op, _ in _detect_ops(_tokens(text))]


def _archetype_hint(tokens, raw, allow_bare=False):
    """Best guess of the archetype named in a sentence, with the evidence.
    `allow_bare`: the sentence answers a clarification question, so a text
    operation on its own ("شمارش کلمات") is enough to name the text tool."""
    ev = []
    has_convert = _has(tokens, _CONVERT_WORDS)
    unit_hits = units.find_units(fa_text.words(raw))
    if _has(tokens, _FORMULA_WORDS):
        ev.append("formula_word")
        return policy.ARCHETYPE_FORMULA, ev
    if not unit_hits and _detect_ops(tokens) and (
            allow_bare or _has(tokens, _TEXT_TOOL_WORDS) or "متن" in tokens or "متنی" in tokens
            or _has(tokens, _CAP_NOUNS) or _has_build_verb(tokens)):
        ev.append("text_ops")
        return policy.ARCHETYPE_TEXT_TOOL, ev
    if has_convert or (len(unit_hits) >= 2 and "به" in tokens):
        ev.append("convert_word" if has_convert else "two_units")
        return policy.ARCHETYPE_UNIT_CONVERSION, ev
    if _detect_ops(tokens) and (_has(tokens, _TEXT_TOOL_WORDS) or "متن" in tokens or "متنی" in tokens
                                or _has(tokens, _CAP_NOUNS) or _has_build_verb(tokens)):
        ev.append("text_ops")
        return policy.ARCHETYPE_TEXT_TOOL, ev
    if _has(tokens, _TEXT_TOOL_WORDS) and ("متن" in tokens or "متنی" in tokens):
        ev.append("text_tool_word")
        return policy.ARCHETYPE_TEXT_TOOL, ev
    if "=" in raw and re.search(r"[A-Za-z0-9_)(+\-*/^×÷]", raw.split("=", 1)[1]) and (_has_build_verb(tokens) or
                                                                                         _has(tokens, _LEARN)):
        ev.append("equation")
        return policy.ARCHETYPE_FORMULA, ev
    return None, ev


# -------------------------------------------------------------- unit slots --

def _unit_slots(raw, tokens_plain):
    """Slots of a unit-conversion request: from/to (table units or custom
    names with a factor) and an optional example. Returns (slots, missing)."""
    slots = {}
    plain = fa_text.words(raw)
    hits = units.find_units(plain)

    # 1) an explicit equivalence: "هر ۱ اینچ ۲٫۵۴ سانتی متر است" / "۱ اینچ = ۲٫۵۴ سانتی متر"
    equiv = _parse_equivalence(raw)
    if equiv:
        slots.update(equiv)
        return slots, []

    chosen = None
    # 2) "از X به Y" / "X به Y"
    for a, b in zip(hits, hits[1:]):
        between = plain[a[1]:b[0]]
        if between and between[-1] == "به" and len(between) <= 3:
            chosen = (a[2], b[2])
            break
    if chosen is None and len(hits) >= 2:
        # "به Y ... از X" order, or "X و Y"
        for i, (s, e, u) in enumerate(hits):
            before = plain[max(0, s - 2):s]
            if "به" in before:
                to_u = u
                from_u = next((h[2] for j, h in enumerate(hits) if j != i), None)
                if from_u is not None:
                    chosen = (from_u, to_u)
                    break
    if chosen is not None:
        if chosen[0].id == chosen[1].id:
            slots["from_unit"] = chosen[0].id
            return slots, ["to_unit"]
        slots["from_unit"], slots["to_unit"] = chosen[0].id, chosen[1].id
        return slots, []
    if len(hits) == 1:
        s, e, u = hits[0]
        before = plain[max(0, s - 2):s]
        if "به" in before:
            slots["to_unit"] = u.id
            return slots, ["from_unit"]
        slots["from_unit"] = u.id
        return slots, ["to_unit"]
    if len(hits) >= 2:
        # two units but no direction word: ambiguous
        slots["candidate_units"] = [h[2].id for h in hits[:2]]
        return slots, ["direction"]
    return slots, ["from_unit", "to_unit"]


_EQ_STOP = frozenset({"است", "هست", "هستش", "میشود", "میشه", "باشد", "باشه", "بشود", "بشه", "بساز", "بسازی",
                      "بسازید", "را", "رو", "که", "و", "مثلا", "مثال"})
_EQ_SKIP = frozenset({"هر", "برابر", "معادل", "مساوی", "با", "میشود", "میشه", "بشود", "بشه", "هست", "است", "یک",
                      "یه", "مقدار", "ضریب", "تبدیل"})


def _name_phrase(tokens):
    """Unit name made of the leading non-skip tokens (<= 3 words)."""
    out = []
    for t in tokens:
        if t in _EQ_STOP and out:
            break
        if t in _EQ_SKIP or fa_text.parse_number(t) is not None or fa_text.is_number_word(t):
            if out:
                break
            continue
        out.append(t)
        if len(out) == 3:
            break
    return " ".join(out)


def _parse_equivalence(raw):
    """'هر N1 A (برابر با)? N2 B' / 'N1 A = N2 B' -> slots with a custom factor."""
    canon_text = fa_text.canon(raw)
    if "=" in canon_text:
        left, _, right = canon_text.partition("=")
        parts = [fa_text.words(left), fa_text.words(right)]
        n1 = fa_text.scan_numbers(parts[0])
        n2 = fa_text.scan_numbers(parts[1])
        if n1 and n2:
            a = _name_phrase(parts[0][n1[-1][1]:])
            b = _name_phrase(parts[1][n2[0][1]:])
            if a and b:
                return _equiv_slots(n1[-1][2], a, n2[0][2], b)
        return None
    toks = fa_text.words(raw)
    nums = fa_text.scan_numbers(toks)
    if "هر" in toks or len(nums) >= 2:
        # first number may be implicit ("هر اینچ ۲٫۵۴ سانتی متر")
        if "هر" in toks:
            hi = toks.index("هر")
            first_after = hi + 1
            nums_after = [n for n in nums if n[0] >= first_after]
            if len(nums_after) >= 2:
                n1, n2 = nums_after[0], nums_after[1]
                if n1[0] == first_after:
                    a = _name_phrase(toks[n1[1]:n2[0]])
                    b = _name_phrase(toks[n2[1]:])
                    if a and b:
                        return _equiv_slots(n1[2], a, n2[2], b)
            elif len(nums_after) == 1:
                n2 = nums_after[0]
                a = _name_phrase(toks[first_after:n2[0]])
                b = _name_phrase(toks[n2[1]:])
                if a and b:
                    return _equiv_slots(1.0, a, n2[2], b)
        elif len(nums) >= 2 and ("برابر" in toks or "معادل" in toks or "مساوی" in toks or "میشود" in toks
                                 or "میشه" in toks):
            n1, n2 = nums[0], nums[1]
            a = _name_phrase(toks[n1[1]:n2[0]])
            b = _name_phrase(toks[n2[1]:])
            if a and b:
                return _equiv_slots(n1[2], a, n2[2], b)
    return None


def _equiv_slots(n1, name_a, n2, name_b):
    if n1 == 0:
        return None
    ua, ub = units.lookup_unit(name_a), units.lookup_unit(name_b)
    slots = {"factor": float(n2) / float(n1), "from_name": name_a, "to_name": name_b}
    if ua is not None:
        slots["from_unit"] = ua.id
    if ub is not None:
        slots["to_unit"] = ub.id
    return slots


# ----------------------------------------------------------- formula slots --

_TRAIL_WORDS = frozenset({"را", "رو", "بساز", "بسازی", "بسازید", "بسازین", "یادبگیر", "یاد", "بگیر", "بگیری",
                          "بگیرید", "لطفا", "کن", "کنی", "کنید", "درست", "ایجاد", "اضافه", "ثبت", "تعریف", "ممنون",
                          "مرسی", "باشد", "باش", "باشه"})
_TITLE_DROP = frozenset({"فرمول", "ماشین", "حساب", "ماشینحساب", "یک", "یه", "را", "رو", "برای", "محاسبه", "محاسبهگر",
                         "جدید", "جدیدی", "لطفا", "بساز", "بسازی", "یاد", "بگیر", "که", "نام", "اسم", "عنوان",
                         "زیر", "ی", "بنام", "بعنوان", "ثبت", "کن", "کند", "کنه", "بکند", "بکنه", "کنم", "بکنم",
                         "کنی", "کنید", "اسمش", "نامش", "بگذار", "بذار", "بزار", "بگذارید", "بگذاری", "نامگذاری",
                         "ماشینحسابی", "محاسبهگری", "فرمولی", "بده", "بدهد", "بدهی"})
_TITLE_EDGE = frozenset({"به", "از", "با", "برای", "را", "رو", "که", "یک", "یه", "ی", "و"})


def _quoted(raw):
    m = re.search(r"[«\"“]([^»\"”]+)[»\"”]", raw)
    return m.group(1).strip() if m else None


def _split_expression(raw):
    """(head, expression) around the first ':' or '=' (the formula body)."""
    s = raw
    for sep in (":", "："):
        if sep in s:
            head, _, body = s.partition(sep)
            return head, body
    if "=" in s:
        head, _, body = s.partition("=")
        return head, body
    return s, ""


def _trim_expression_tail(body):
    """Drop trailing request words ('را بساز', 'یاد بگیر') after the formula text."""
    pieces = body.strip().split()
    while pieces:
        last = fa_text.words(pieces[-1])
        if last and all(_squash([t])[0] in _TRAIL_WORDS or t in _TRAIL_WORDS for t in last):
            pieces.pop()
            continue
        break
    s = " ".join(pieces)
    s = re.sub(r"[\s.!؟?،]+$", "", s)
    return s.strip()


def _example_part(raw):
    """Split off a trailing example ('مثلا ...') -> (rest, example_text or None)."""
    toks = raw.split()
    for i, t in enumerate(toks):
        if _squash(fa_text.words(t))[:1] and fa_text.words(t)[:1] and fa_text.words(t)[0] in _EXAMPLE_MARKERS:
            return " ".join(toks[:i]), " ".join(toks[i + 1:])
    return raw, None


def _title_from_head(head):
    quoted = _quoted(head)
    if quoted:
        return quoted
    words = [w for w in re.split(r"\s+", head.replace("‌", " ").strip()) if w]
    kept = []
    for w in words:
        key_w = _squash(fa_text.words(w))
        if not key_w:
            continue
        if all(t in _TITLE_DROP or t in _BUILD_TOKENS or t in _BUILD_NOUN_VERB or t in _LEARN or t in _WANT
               or t in _AUX or t in _HAVE for t in key_w):
            continue
        kept.append(w)
    # explicit naming wins: "... به نام X" / "اسمش را بگذار X"
    m = re.search(r"(?:به\s*نام|با\s*نام|به\s*اسم|با\s*عنوان|به\s*عنوان|اسمش|نامش)\s+(?:را\s+|رو\s+)?"
                  r"(?:بگذار\s+|بذار\s+|بزار\s+|بگذارید\s+)?(.+)$", head.replace("‌", " "))
    if m:
        named = [w for w in m.group(1).split() if _squash(fa_text.words(w))
                 and not all(t in _TITLE_DROP or t in _BUILD_TOKENS or t in _BUILD_NOUN_VERB
                             for t in _squash(fa_text.words(w)))]
        while named and _squash(fa_text.words(named[0]))[:1] and _squash(fa_text.words(named[0]))[0] in _TITLE_EDGE:
            named.pop(0)
        while named and _squash(fa_text.words(named[-1]))[:1] and _squash(fa_text.words(named[-1]))[0] in _TITLE_EDGE:
            named.pop()
        if named:
            return " ".join(named)
    while kept and _squash(fa_text.words(kept[0]))[:1] and _squash(fa_text.words(kept[0]))[0] in _TITLE_EDGE:
        kept.pop(0)
    while kept and _squash(fa_text.words(kept[-1]))[:1] and _squash(fa_text.words(kept[-1]))[0] in _TITLE_EDGE:
        kept.pop()
    return " ".join(kept).strip()


def _formula_slots(raw):
    body_raw, example_text = _example_part(raw)
    head, body = _split_expression(body_raw)
    slots = {}
    title = _title_from_head(head)
    expression = _trim_expression_tail(body) if body.strip() else ""
    # the title may come after the expression: "... را به نام X بساز"
    if expression and not title:
        m = re.search(r"(?:به\s*نام|با\s*نام|به\s*اسم)\s+(.+)$", expression)
        if m:
            title = m.group(1).strip()
            expression = expression[:m.start()].strip()
    quoted_expr = None
    if not expression:
        q = re.findall(r"`([^`]+)`", raw)
        if q:
            quoted_expr = q[0]
    if quoted_expr:
        expression = quoted_expr
    missing = []
    if title:
        slots["title"] = title
    else:
        missing.append("title")
    if expression:
        slots["expression"] = expression
    else:
        missing.append("expression")
    if example_text:
        slots["example_text"] = example_text
    return slots, missing


def _decimals_in(token):
    return len(token.split(".")[1]) if "." in token else 0


def parse_formula_example(example_text, variable_names, variable_aliases):
    """Best-effort reading of 'مثلا r=2 بشود 12.57' / 'مثلا ۲ بشود ۱۲٫۵۷' ->
    {"inputs": {...} | None, "positional": [...] | None, "expected": x, "tolerance": t} or None.
    `variable_aliases`: {variable name: [normalized alias keys]}."""
    if not example_text:
        return None
    toks = fa_text.words(example_text)
    spans = fa_text.scan_numbers(toks)
    if len(spans) < 2:
        return None
    exp_start, exp_end, expected = spans[-1]
    exp_token = toks[exp_start] if exp_end - exp_start == 1 else ""
    decimals = _decimals_in(exp_token) if exp_token else 3
    tolerance = 0.5 * 10 ** (-decimals) + 1e-12
    input_spans = spans[:-1]
    named = {}
    positional = []
    for (s, e, value) in input_spans:
        label = None
        for look in range(1, 4):
            if s - look < 0:
                break
            cand = toks[s - look]
            for var, aliases in variable_aliases.items():
                if fa_text.key(cand) in aliases or cand == var:
                    label = var
                    break
            if label:
                break
        if label:
            named[label] = value
        positional.append(value)
    if named and len(named) == len(variable_names):
        return {"inputs": named, "positional": None, "expected": expected, "tolerance": tolerance}
    if len(positional) == len(variable_names):
        return {"inputs": None, "positional": positional, "expected": expected, "tolerance": tolerance}
    return None


def parse_unit_example(example_text):
    """'مثلا ۱۰ کیلومتر بشود ۶٫۲ مایل' -> {"value": 10, "expected": 6.2, "tolerance": ...} or None."""
    if not example_text:
        return None
    toks = fa_text.words(example_text)
    spans = fa_text.scan_numbers(toks)
    if len(spans) < 2:
        return None
    exp_start, exp_end, expected = spans[-1]
    exp_token = toks[exp_start] if exp_end - exp_start == 1 else ""
    decimals = _decimals_in(exp_token) if exp_token else 3
    return {"value": spans[0][2], "expected": expected, "tolerance": 0.5 * 10 ** (-decimals) + 1e-12}


# ------------------------------------------------------------------ public --

def _content_tokens(tokens):
    """Tokens that say WHAT is wanted (not just 'please build one')."""
    filler = _BUILD_TOKENS | _BUILD_NOUN_VERB | _AUX | _LEARN | _WANT | _NEED | _HAVE | _CONNECTOR_WORDS
    return [t for t in tokens if t not in filler]


def parse_build_request(text, allow_bare=False):
    """Analyse one sentence.

    `allow_bare=True` is used for the answer to a clarification question: the
    sentence needs no build verb ("تبدیل کیلومتر به مایل" is enough)."""
    raw = text if isinstance(text, str) else ""
    if not raw.strip() or len(raw) > policy.MAX_REQUEST_CHARS:
        return BuildRequest(STATUS_NOT_REQUEST)
    tokens = _tokens(raw)
    markers = build_markers(raw)
    kind, ev = _archetype_hint(tokens, raw, allow_bare)

    is_request = False
    if "build_verb" in markers:
        is_request = True
    elif "learn" in markers and kind is not None:
        is_request = True
    elif "want_need" in markers and (kind is not None or "capability_noun" in markers or "new_capability" in markers):
        is_request = True
    elif "new_capability" in markers and ("want_need" in markers or "build_verb" in markers):
        is_request = True
    if allow_bare and kind is not None:
        is_request = True
    if not is_request:
        return BuildRequest(STATUS_NOT_REQUEST, evidence=sorted(markers))
    # a build verb alone ("یک نرم‌افزار بساز") needs a capability-ish noun to count as ours
    evidence = sorted(markers) + ev

    topics = sorted({t for t in tokens if t in _UNSUPPORTED_TOPICS})
    if kind is None:
        if topics:
            return BuildRequest(STATUS_UNSUPPORTED, None, {}, [], evidence + ["topic:" + t for t in topics],
                                note="the subject is outside the supported archetypes")
        if "new_capability" in markers or "capability_noun" in markers or "want_need" in markers or allow_bare \
                or not _content_tokens(tokens):
            return BuildRequest(STATUS_CLARIFY, None, {}, ["kind"], evidence)
        return BuildRequest(STATUS_UNSUPPORTED, None, {}, [], evidence,
                            note="no supported archetype named")

    if kind == policy.ARCHETYPE_UNIT_CONVERSION:
        body, example_text = _example_part(raw)
        slots, missing = _unit_slots(body, tokens)
        if example_text:
            slots["example_text"] = example_text
        if missing and topics:
            return BuildRequest(STATUS_UNSUPPORTED, None, {}, [], evidence + ["topic:" + t for t in topics],
                                note="the subject is outside the supported archetypes")
        status = STATUS_READY if not missing else STATUS_CLARIFY
        return BuildRequest(status, kind, slots, missing, evidence)

    if kind == policy.ARCHETYPE_FORMULA:
        slots, missing = _formula_slots(raw)
        status = STATUS_READY if not missing else STATUS_CLARIFY
        return BuildRequest(status, kind, slots, missing, evidence)

    ops = [op for op, _ in _detect_ops(tokens)]
    if not ops:
        return BuildRequest(STATUS_CLARIFY, kind, {}, ["ops"], evidence)
    for i, op in enumerate(ops):
        if textops.op_kind(op) == "number" and i != len(ops) - 1:
            return BuildRequest(STATUS_CLARIFY, kind, {"ops": ops}, ["ops_order"], evidence,
                                note="a counting operation can only be the last step")
    if len(ops) > textops.MAX_CHAIN:
        return BuildRequest(STATUS_CLARIFY, kind, {"ops": ops}, ["ops_count"], evidence)
    return BuildRequest(STATUS_READY, kind, {"ops": ops}, [], evidence)


def merge_answer(pending, answer_text):
    """Apply a user's answer to a pending clarification. `pending`: dict with
    "kind" (or None), "slots", "missing". Returns a BuildRequest (possibly
    still incomplete)."""
    kind = pending.get("kind")
    slots = dict(pending.get("slots") or {})
    raw = answer_text or ""
    if kind is None:
        return parse_build_request(raw, allow_bare=True)
    if kind == policy.ARCHETYPE_UNIT_CONVERSION:
        plain = fa_text.words(raw)
        hits = units.find_units(plain)
        full, _ = _unit_slots(raw, _tokens(raw))
        merged = {k: v for k, v in slots.items() if k != "candidate_units"}
        candidates = slots.get("candidate_units") or []
        if "factor" in full or ("from_unit" in full and "to_unit" in full):
            merged.update({k: v for k, v in full.items() if k != "candidate_units"})
        elif len(hits) == 1:
            unit = hits[0][2].id
            if candidates and "direction" in (pending.get("missing") or []):
                others = [u for u in candidates if u != unit]
                if others:
                    # "از X" -> X is the source; "به X" -> X is the target
                    before = plain[max(0, hits[0][0] - 2):hits[0][0]]
                    if "به" in before:
                        merged["from_unit"], merged["to_unit"] = others[0], unit
                    else:
                        merged["from_unit"], merged["to_unit"] = unit, others[0]
            elif "from_unit" in merged and "to_unit" not in merged:
                merged["to_unit"] = unit
            elif "to_unit" in merged and "from_unit" not in merged:
                merged["from_unit"] = unit
            else:
                merged.update({k: v for k, v in full.items() if k != "candidate_units"})
        elif len(hits) >= 2:
            merged.update({k: v for k, v in full.items() if k != "candidate_units"})
        if "factor" in merged or ("from_unit" in merged and "to_unit" in merged):
            if "factor" not in merged and merged.get("from_unit") == merged.get("to_unit"):
                merged.pop("to_unit")
                return BuildRequest(STATUS_CLARIFY, kind, merged, ["to_unit"], ["answer"], note="same_unit")
            return BuildRequest(STATUS_READY, kind, merged, [], ["answer"])
        if candidates and "from_unit" not in merged and "to_unit" not in merged:
            return BuildRequest(STATUS_CLARIFY, kind, dict(merged, candidate_units=candidates), ["direction"],
                                ["answer"])
        missing = [m for m in ("from_unit", "to_unit") if m not in merged]
        return BuildRequest(STATUS_CLARIFY, kind, merged, missing, ["answer"])
    if kind == policy.ARCHETYPE_FORMULA:
        merged = dict(slots)
        missing = list(pending.get("missing") or [])
        stripped = raw.strip()
        if "expression" in missing and "title" not in missing:
            head, body = _split_expression(stripped)
            text_expr = body if body.strip() else stripped
            expression = _trim_expression_tail(text_expr)
            if expression:
                merged["expression"] = expression
        elif "title" in missing and "expression" not in missing:
            title = _title_from_head(stripped)
            if title:
                merged["title"] = title
        else:
            more, _ = _formula_slots(raw)
            if not more.get("expression") and ":" not in raw and "=" not in raw:
                # a bare answer while both slots are missing: treat it as the expression
                expression = _trim_expression_tail(stripped)
                if expression and re.search(r"[+\-*/^×÷]", expression):
                    more["expression"] = expression
                    more.pop("title", None)   # the text WAS the expression, not a name
            merged.update(more)
        missing = [m for m in ("title", "expression") if m not in merged]
        return BuildRequest(STATUS_READY if not missing else STATUS_CLARIFY, kind, merged, missing, ["answer"])
    # text tool
    ops = [op for op, _ in _detect_ops(_tokens(raw))]
    if not ops:
        return BuildRequest(STATUS_CLARIFY, kind, slots, ["ops"], ["answer"])
    return parse_build_request("ابزار متنی بساز " + raw, allow_bare=True)


# ----------------------------------------------------- spec assembly helper --

def assemble_spec_inputs(request):
    """Normalised keyword arguments for the spec constructors from a READY
    request's slots (the builder passes these on)."""
    kind = request.kind
    slots = request.slots
    if kind == policy.ARCHETYPE_UNIT_CONVERSION:
        from_u = units.UNITS.get(slots.get("from_unit"))
        to_u = units.UNITS.get(slots.get("to_unit"))
        example = parse_unit_example(slots.get("example_text"))
        examples = []
        if example:
            examples = [{"inputs": {"value": example["value"]}, "expected": example["expected"],
                         "tolerance": example["tolerance"]}]
        return {"from_unit": from_u, "to_unit": to_u, "from_name": slots.get("from_name"),
                "to_name": slots.get("to_name"), "factor": slots.get("factor"), "examples": examples}
    if kind == policy.ARCHETYPE_FORMULA:
        return {"title": slots.get("title"), "expression": slots.get("expression"),
                "example_text": slots.get("example_text")}
    return {"ops": list(slots.get("ops") or [])}


def analyze_for_upgrade(description):
    """Used by the upgrade bridge: is `description` a buildable request?"""
    req = parse_build_request(description, allow_bare=True)
    return req if req.status == STATUS_READY else None


__all__ = ["BuildRequest", "parse_build_request", "merge_answer", "build_markers", "detect_text_ops",
           "parse_formula_example", "parse_unit_example", "assemble_spec_inputs", "analyze_for_upgrade",
           "STATUS_READY", "STATUS_CLARIFY", "STATUS_UNSUPPORTED", "STATUS_NOT_REQUEST"]
