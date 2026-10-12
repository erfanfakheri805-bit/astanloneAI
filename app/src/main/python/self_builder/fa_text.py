"""
Self-Builder / Persian brain - shared Persian text helpers
==========================================================
Pure, deterministic, stdlib-only helpers for ordinary Persian input:

  canon()        canonical form used for matching (builds on the project's
                 existing understanding.persian_nlu.normalize_persian: NFKC,
                 Arabic -> Persian letters, diacritics/tatweel removed,
                 Persian/Arabic digits -> ASCII, ZWNJ -> space; plus the
                 Arabic decimal/thousands separators and invisible/bidi
                 control characters)
  words()        tokens of a canonical string
  key()          whitespace/ZWNJ/punctuation-insensitive matching key
                 ("سانتی‌متر" == "سانتی متر" == "سانتیمتر")
  parse_number() / scan_numbers()   digits and Persian number words
  fa_number()    Persian-digit formatting for replies

Nothing here talks to storage or the network, and nothing is learned: it is
fixed grammar over a small closed word list, not a language model.
"""

import re

from understanding.persian_nlu import normalize_persian

_INVISIBLE_RE = re.compile("[​‍⁠﻿‪-‮⁦-⁩؜]")
# A "-" glued to the front of a number is its sign ("-40", "(-5)") unless a word character or a
# dot precedes it ("10-5", "x-2", "1403-05-10" are not negative numbers).
_TOKEN_RE = re.compile(r"(?:(?<![\w.])-(?=[0-9]))?[0-9]+(?:\.[0-9]+)?|[^\W\d_]+(?:['\-][^\W\d_]+)*",
                       re.UNICODE)
_MINUS_RE = re.compile(r"[\u2212\uFE63\uFF0D](?=\s?[0-9\u06F0-\u06F9\u0660-\u0669])")
_KEY_STRIP_RE = re.compile(r"[\W_]+", re.UNICODE)
_NUMBER_RE = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?$")

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_FA_DIGIT_TABLE = {ord(str(i)): _FA_DIGITS[i] for i in range(10)}


def canon(text):
    """Canonical matching form of `text` ('' for None)."""
    if text is None:
        return ""
    s = _INVISIBLE_RE.sub("", str(text))
    s = s.replace("٫", ".").replace("٬", "")  # Arabic decimal / thousands separators
    s = _MINUS_RE.sub("-", s)                  # a real minus sign (U+2212 & friends) before a number
    s = normalize_persian(s)
    return s


def words(text):
    """Word/number tokens of the canonical form, lower-cased (numbers as '2.5')."""
    return [t.lower() for t in _TOKEN_RE.findall(canon(text))]


def key(text):
    """Matching key: canonical, lower-cased, with every space/punctuation removed."""
    return _KEY_STRIP_RE.sub("", canon(text).lower())


def has_persian_script(text):
    return bool(text) and bool(re.search("[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]", str(text)))


# ---------------------------------------------------------------- numbers --

_UNIT_WORDS = {
    "صفر": 0, "یک": 1, "یه": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6, "شیش": 6,
    "هفت": 7, "هشت": 8, "نه": 9, "ده": 10, "یازده": 11, "دوازده": 12, "سیزده": 13,
    "چهارده": 14, "پانزده": 15, "پونزده": 15, "شانزده": 16, "شونزده": 16, "هفده": 17,
    "هجده": 18, "نوزده": 19,
}
_TENS_WORDS = {
    "بیست": 20, "سی": 30, "چهل": 40, "پنجاه": 50, "شصت": 60, "هفتاد": 70, "هشتاد": 80, "نود": 90,
}
_HUNDRED_WORDS = {
    "صد": 100, "یکصد": 100, "دویست": 200, "سیصد": 300, "چهارصد": 400, "پانصد": 500,
    "ششصد": 600, "شیشصد": 600, "هفتصد": 700, "هشتصد": 800, "نهصد": 900,
}
_SCALE_WORDS = {"هزار": 1_000, "میلیون": 1_000_000, "میلیارد": 1_000_000_000}
_HALF_WORDS = frozenset({"نیم"})
_CONNECTOR = "و"

# class: 1 = 0..19, 2 = tens, 3 = hundreds, 4 = thousand/million/billion
_WORD_CLASS = {}
for _w in _UNIT_WORDS:
    _WORD_CLASS[_w] = 1
for _w in _TENS_WORDS:
    _WORD_CLASS[_w] = 2
for _w in _HUNDRED_WORDS:
    _WORD_CLASS[_w] = 3
for _w in _SCALE_WORDS:
    _WORD_CLASS[_w] = 4


def parse_number(token):
    """float for an ASCII-digit token ('2', '2.5', '-3'), else None."""
    if token is None:
        return None
    t = canon(token).replace(" ", "")
    if _NUMBER_RE.match(t):
        return float(t)
    return None


def is_number_word(token):
    return token in _WORD_CLASS or token in _HALF_WORDS


def _word_value(token):
    for table in (_UNIT_WORDS, _TENS_WORDS, _HUNDRED_WORDS):
        if token in table:
            return table[token]
    return None


def scan_numbers(tokens):
    """Find numbers in a token list (as produced by words()).

    Returns [(start, end, value)] with `end` exclusive. Digit tokens
    ('5', '2.5') and Persian number words ('پنج', 'صد و بیست', 'دو و نیم',
    'دو هزار و پانصد') are recognised. "و" only joins words of strictly
    decreasing magnitude class (so 'ده و بیست' is two numbers, 'صد و بیست' is
    120) and a trailing "و نیم" adds one half."""
    spans = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        num = parse_number(tok)
        if num is not None:
            end = i + 1
            if end + 1 < n and tokens[end] == _CONNECTOR and tokens[end + 1] in _HALF_WORDS:
                num += 0.5
                end += 2
            spans.append((i, end, num))
            i = end
            continue
        if tok in _HALF_WORDS:
            spans.append((i, i + 1, 0.5))
            i += 1
            continue
        if tok in _WORD_CLASS:
            total = 0
            current = 0
            last_class = 99
            last_scale = float("inf")
            j = i
            consumed_end = i
            while j < n:
                w = tokens[j]
                glue = False
                if w == _CONNECTOR and j + 1 < n and tokens[j + 1] in _WORD_CLASS:
                    glue = True
                    w = tokens[j + 1]
                if w not in _WORD_CLASS:
                    break
                cls = _WORD_CLASS[w]
                if j > i:
                    # Same group: strictly decreasing class. After a scale word a
                    # new (smaller) group may start; two scales never chain upward.
                    if cls == 4:
                        if _SCALE_WORDS[w] >= last_scale:
                            break
                    elif cls >= last_class and last_class != 4:
                        break
                if cls == 4:
                    group = current if current > 0 else 1
                    total += group * _SCALE_WORDS[w]
                    current = 0
                    last_scale = _SCALE_WORDS[w]
                    last_class = 4
                else:
                    current += _word_value(w)
                    last_class = cls
                j += 2 if glue else 1
                consumed_end = j
            value = total + current
            end = consumed_end
            if end + 1 < n and tokens[end] == _CONNECTOR and tokens[end + 1] in _HALF_WORDS:
                value += 0.5
                end += 2
            spans.append((i, end, float(value)))
            i = max(end, i + 1)
            continue
        i += 1
    return spans


# ------------------------------------------------------------- formatting --

def format_number(value, max_decimals=6):
    """ASCII text of a float without float noise: up to `max_decimals` places,
    trailing zeros removed; very large/small values use general format."""
    if value is None:
        return ""
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):
        return "نامعتبر"
    if v != 0 and (abs(v) >= 1e15 or abs(v) < 10 ** (-max_decimals)):
        return f"{v:.6g}"
    s = f"{v:.{max_decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


def to_fa_digits(text):
    """Persian digits (and the Persian decimal separator) for display."""
    return str(text).translate(_FA_DIGIT_TABLE).replace(".", "٫")


def fa_number(value, max_decimals=6):
    s = format_number(value, max_decimals)
    if "e" in s:  # general format for huge/tiny values: 1.5e+20 -> ۱٫۵×۱۰^۲۰
        mantissa, _, exponent = s.partition("e")
        sign = "-" if exponent.startswith("-") else ""
        digits = exponent.lstrip("+-").lstrip("0") or "0"
        return f"{to_fa_digits(mantissa)}×۱۰^{sign}{to_fa_digits(digits)}"
    return to_fa_digits(s)


def join_fa(items, conj="و"):
    """'الف، ب و ج' style list join."""
    items = [str(i) for i in items]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return "، ".join(items[:-1]) + f" {conj} " + items[-1]
