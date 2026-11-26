"""
native_bridge.otp - finding the one-time code in a text message
===============================================================
Pure functions: no Android, no files, no network, no state.

`extract_code(text)` returns the code of a message that says it holds one - «کد تایید شما: 48291», «رمز پویا: 12345678»,
"Your verification code is 482913", "G-482913 is your Google verification code" - or "" when there is none.
`redact(text)` hides the code it would extract (for any log or note that must not keep it).

A number is taken for a code only when a KEYWORD («کد», «رمز», code, otp, ...) stands near it, and never when it looks like something
else: an amount («مبلغ 2500000 ریال»), a balance, a date («1403/09/20»), a time, a phone number, a tracking or order number
(«کد پیگیری», «کد ملی»). The rule is deliberately conservative - a message that is not recognised is simply not read; the user
can still read it in the SMS app himself. It is not a model and it cannot know every bank's wording.
"""

import re

__all__ = ["extract_code", "find_code", "redact", "normalize", "MIN_DIGITS", "MAX_DIGITS"]

MIN_DIGITS, MAX_DIGITS = 4, 8
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_INVISIBLE = {ord(ch): None for ch in "‌‍‎‏‪‫‬‭‮⁦⁧⁨⁩﻿"}

_KEYWORD = re.compile(r"(?i)(?:کد|رمز|پسورد|پسوورد|otp|code|passcode|password|pin|verification|verify|confirmation|"
                      r"تایید|تأیید|یکبار\s?مصرف|یک\s?بار\s?مصرف|پویا|احراز)")
_NUMBER = re.compile(r"(?<![0-9A-Za-z])[0-9]{%d,%d}(?![0-9A-Za-z])" % (MIN_DIGITS, MAX_DIGITS))
_GROUPED = re.compile(r"(?<![0-9])[0-9]{3}[ \-][0-9]{3}(?![0-9])")                       # «123 456» / «123-456»
_AMOUNT_AFTER = re.compile(r"^\s{0,2}(?:ریال|تومان|تومن|rial|rials|irr|usd|eur|دلار|یورو|درصد|%)", re.I)
_AMOUNT_BEFORE = re.compile(r"(?:مبلغ|مانده|موجودی|بدهی|amount|balance|مبلغِ|شماره\s?حساب|شماره\s?کارت|شبا|تاریخ|ساعت)\s*[:：]?\s*$", re.I)
# words that make a number something else when they stand between the keyword and the number (the keyword itself is part of the text
# that is searched, so «کد ملی» is caught but «کد تایید بانک ملی» is not)
_NOT_A_CODE_BETWEEN = re.compile(r"پیگیری|رهگیری|کد\s?ملی|شماره\s?ملی|کد\s?پستی|tracking|invoice|reference", re.I)
_SEPARATED = re.compile(r"[/:.,،٫]")
MAX_AFTER, MAX_BEFORE = 45, 25                  # characters between a keyword and its number


def normalize(text):
    """Latin digits, no invisible direction marks - the form every other function works on (same length is NOT promised)."""
    return str(text or "").translate(_INVISIBLE).translate(_DIGITS)


def _candidates(text):
    """(start, end, digits) of every number that could be a code, before the keyword rules."""
    found = []
    for match in _NUMBER.finditer(text):
        start, end = match.span()
        if start >= 2 and text[start - 1] in "/:.,،٫" and text[start - 2].isdigit():
            continue                                    # the tail of a date, a time, a decimal or a thousands group
        if end + 1 < len(text) and text[end] in "/:.,،٫" and text[end + 1].isdigit():
            continue                                    # the head of one
        found.append((start, end, match.group()))
    for match in _GROUPED.finditer(text):
        found.append((match.start(), match.end(), re.sub(r"[ \-]", "", match.group())))
    return found


def find_code(text):
    """`(code, start, end)` inside `normalize(text)`, or `("", -1, -1)`. The nearest keyword decides; ties go to the number AFTER it."""
    body = normalize(text)
    keywords = [match.span() for match in _KEYWORD.finditer(body)]
    if not keywords:
        return "", -1, -1
    best = None
    for start, end, digits in _candidates(body):
        if _AMOUNT_AFTER.match(body[end:end + 12]) or _AMOUNT_BEFORE.search(body[max(0, start - 16):start]):
            continue
        for k_start, k_end in keywords:
            if start >= k_end:
                gap, rank = start - k_end, 0
                if gap > MAX_AFTER or _NOT_A_CODE_BETWEEN.search(body[k_start:start]):
                    continue
            elif end <= k_start:
                gap, rank = k_start - end, 1
                if gap > MAX_BEFORE or _NOT_A_CODE_BETWEEN.search(body[end:k_end]):
                    continue
            else:
                continue
            key = (gap, rank)
            if best is None or key < best[0]:
                best = (key, digits, start, end)
    if best is None:
        return "", -1, -1
    return best[1], best[2], best[3]


def extract_code(text):
    return find_code(text)[0]


def redact(text):
    """The text with its code replaced by bullets (a message without a code is returned unchanged, apart from its digits)."""
    body = normalize(text)
    code, start, end = find_code(body)
    if not code:
        return body
    return body[:start] + "•" * (end - start) + body[end:]
