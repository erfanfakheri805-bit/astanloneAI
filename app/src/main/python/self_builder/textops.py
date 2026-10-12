"""
Self-Builder - text operations
==============================
The closed set of text operations the "text_tool" archetype can compose.
Each operation is a plain pure function written here (reviewed, tested code);
a generated text-tool module only ever *calls* them by name through the
sandbox's pre-bound helpers - it never contains string-processing logic of
its own.

An operation either maps text -> text ("chainable") or text -> number
("terminal": it must be the last step of a tool).
"""

import re

from . import policy
from .mathcore import MathFailure

_FA_TO_EN = {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_AR_TO_EN = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_EN_TO_FA = {ord(str(i)): c for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_ARABIC_LETTERS = {ord("ي"): "ی", ord("ى"): "ی", ord("ك"): "ک", ord("ة"): "ه"}
_MI_PREFIX_RE = re.compile(r"(?<!\S)(ن?می)[ ]+(?=[\u0600-\u06ff])")


def count_chars(s):
    return float(len(s))


def count_chars_no_space(s):
    return float(len("".join(s.split())))


def count_words(s):
    return float(len(s.split()))


def reverse(s):
    return s[::-1]


def upper(s):
    return s.upper()


def lower(s):
    return s.lower()


def strip_spaces(s):
    return " ".join(s.split())


def remove_spaces(s):
    return "".join(s.split())


def to_fa_digits(s):
    return s.translate(_EN_TO_FA)


def to_en_digits(s):
    return s.translate(_FA_TO_EN).translate(_AR_TO_EN)


def fix_arabic_letters(s):
    return s.translate(_ARABIC_LETTERS)


def fix_mi_prefix(s):
    """'می خواهم' -> 'می‌خواهم' (a ZWNJ after the verb prefix)."""
    return _MI_PREFIX_RE.sub("\\1\u200c", s)


# id -> (function, output kind, Persian label, Persian trigger phrases)
OPS = {
    "count_words": (count_words, "number", "شمارش کلمات", ["تعداد کلمات", "شمارش کلمات", "کلمه شمار", "شمارنده کلمات"]),
    "count_chars": (count_chars, "number", "شمارش نویسه‌ها", ["تعداد حروف", "تعداد نویسه", "تعداد کاراکتر", "شمارش حروف", "شمارش کاراکتر"]),
    "count_chars_no_space": (count_chars_no_space, "number", "شمارش نویسه‌ها بدون فاصله",
                             ["تعداد حروف بدون فاصله", "تعداد کاراکتر بدون فاصله"]),
    "reverse": (reverse, "text", "معکوس کردن متن", ["معکوس کردن", "برعکس کردن", "معکوس متن", "برعکس متن", "معکوس کن"]),
    "upper": (upper, "text", "حروف بزرگ لاتین", ["حروف بزرگ", "بزرگ کردن حروف", "اپرکیس"]),
    "lower": (lower, "text", "حروف کوچک لاتین", ["حروف کوچک", "کوچک کردن حروف", "لوورکیس"]),
    "strip_spaces": (strip_spaces, "text", "حذف فاصله‌های اضافی", ["حذف فاصله های اضافی", "فاصله های اضافی", "فشرده سازی فاصله"]),
    "remove_spaces": (remove_spaces, "text", "حذف همه فاصله‌ها", ["حذف همه فاصله ها", "حذف فاصله ها", "حذف فاصله"]),
    "to_fa_digits": (to_fa_digits, "text", "تبدیل ارقام به فارسی", ["ارقام فارسی", "اعداد فارسی", "تبدیل ارقام به فارسی", "تبدیل اعداد به فارسی"]),
    "to_en_digits": (to_en_digits, "text", "تبدیل ارقام به انگلیسی", ["ارقام انگلیسی", "اعداد انگلیسی", "تبدیل ارقام به انگلیسی", "تبدیل اعداد به انگلیسی"]),
    "fix_arabic_letters": (fix_arabic_letters, "text", "اصلاح ی و ک عربی", ["ی و ک عربی", "حروف عربی", "اصلاح ی و ک"]),
    "fix_mi_prefix": (fix_mi_prefix, "text", "اصلاح نیم‌فاصلهٔ «می»", ["نیم فاصله", "اصلاح نیم فاصله", "نیم فاصله گذار"]),
}
MAX_CHAIN = 3
HELPER_PREFIX = "_sb_text_"


def op_ids():
    return list(OPS)


def op_kind(op_id):
    return OPS[op_id][1]


def op_label(op_id):
    return OPS[op_id][2]


def apply_ops(op_ids_list, text):
    """Reference application of a chain of operations to `text`."""
    value = text
    for op_id in op_ids_list:
        value = OPS[op_id][0](value)
    return value


def text_input(inputs, name):
    """A named text input of a capability call (type and length checked)."""
    if not isinstance(inputs, dict) or name not in inputs:
        raise MathFailure("bad_input", f"missing input: {name}")
    value = inputs[name]
    if not isinstance(value, str):
        raise MathFailure("bad_input", "text expected")
    if len(value) > policy.MAX_INVOKE_TEXT_CHARS:
        raise MathFailure("bad_input", "text is too long")
    return value
