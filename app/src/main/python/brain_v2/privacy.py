"""
brain_v2.privacy - what must NEVER leave the phone, checked before every request
================================================================================
`check(text, share_private)` is the one gate between the user's words and the cloud. It looks for two classes of content:

* SECRET - never sent, whatever the settings say: API keys and tokens, private keys, bank card numbers, Sheba (IBAN) numbers,
  one-time codes / second passwords / CVV2 / PINs / passwords written together with their value, recovery phrases;
* PERSONAL - sent only when the user said so (`share_private`): e-mail addresses, phone numbers, national-ID numbers, wallet
  addresses.

A blocked message is not sent, not stored in the short history, and the chat says WHICH kind was found (never the value).
The check is deliberately conservative: a false alarm costs one "I kept this on the phone" reply, a miss could cost money.
It is a deterministic set of patterns, not a model - it cannot recognise every private thing a person can write, which the
chat also says ("do not type things you would not say aloud").
"""

import re
from dataclasses import dataclass

from self_builder import fa_text

__all__ = ["Verdict", "check", "looks_like_key", "contains_text", "LABELS_FA"]

LABELS_FA = {
    "key": "کلید یا توکن", "private_key": "کلید خصوصی", "card": "شمارهٔ کارت بانکی", "sheba": "شمارهٔ شبا", "credential": "رمز یا کد امنیتی",
    "recovery": "عبارت بازیابی کیف پول", "email": "ایمیل", "phone": "شمارهٔ تلفن", "national_id": "کد ملی", "wallet": "آدرس کیف پول",
}
SECRET_KINDS = ("key", "private_key", "card", "sheba", "credential", "recovery")
PERSONAL_KINDS = ("email", "phone", "national_id", "wallet")

_TOKEN_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_\-])(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"(?<![A-Za-z0-9_\-])(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{30,}"),
    re.compile(r"(?<![A-Za-z0-9_\-])xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9_\-])ey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),     # a JWT
    re.compile(r"(?<![A-Za-z0-9_\-])(?=[A-Za-z0-9_\-]*[A-Za-z])(?=[A-Za-z0-9_\-]*[0-9])[A-Za-z0-9_\-]{32,}(?![A-Za-z0-9_\-])"),
)
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_RECOVERY_RE = re.compile(r"(?:seed phrase|recovery phrase|mnemonic|عبارت بازیابی|عبارت یاد ?آور|کلمات بازیابی|سید فریز)", re.I)
_LETTER = r"[^\W\d_]"          # any letter (Persian or Latin)
_CREDENTIAL_WORD = (r"(?:(?<!" + _LETTER + r")رمز(?:م|مو|ت|ش|ی)?(?!" + _LETTER + r")|"       # «رمز», «رمزم» - not «رمزارز» / «رمزنگاری»
                    r"رمز\s*(?:پویا|دوم|یک\s*بار\s*مصرف|یکبار\s*مصرف|عبور|ورود|کارت|اینترنت\s*بانک|همراه)|پسورد|پسوورد|"
                    r"(?<![A-Za-z])(?:password|passcode|passwd|otp|cvv2?|cvc2?|pin)(?![A-Za-z])|(?<!" + _LETTER + r")پین(?!" + _LETTER + r")|"
                    r"کد\s*(?:تایید|تأیید|فعال\s*سازی|امنیتی|یکبار\s*مصرف|"
                    r"یک\s*بار\s*مصرف|ورود|احراز|پیامکی|اعتبارسنجی)|verification\s*code|security\s*code)")
_CREDENTIAL_DIGITS = re.compile(_CREDENTIAL_WORD + r"[^\n]{0,40}?(?<![A-Za-z0-9])[0-9]{4,10}(?![A-Za-z0-9])", re.I)
_CREDENTIAL_DIGITS_BEFORE = re.compile(r"(?<![A-Za-z0-9])[0-9]{4,10}(?![A-Za-z0-9])[^\n]{0,40}?" + _CREDENTIAL_WORD, re.I)
_CREDENTIAL_TOKEN = re.compile(_CREDENTIAL_WORD + r"[^\n]{0,40}?(?<![A-Za-z0-9])(?=[A-Za-z0-9@#$%^&*!._\-]*[0-9])"
                               r"(?=[A-Za-z0-9@#$%^&*!._\-]*[A-Za-z])[A-Za-z0-9@#$%^&*!._\-]{6,40}(?![A-Za-z0-9])", re.I)
_CVV_RE = re.compile(r"(?<![A-Za-z])(?:cvv2?|cvc2?)(?![A-Za-z])[^\n]{0,20}?(?<![0-9])[0-9]{3,4}(?![0-9])", re.I)     # a 3-4 digit code
_CARD_RE = re.compile(r"(?<![0-9])(?:[0-9][ \-]?){12,18}[0-9](?![0-9])")
_SHEBA_RE = re.compile(r"(?<![A-Za-z0-9])IR(?:[ \-]?[0-9]){24}(?![0-9])", re.I)
_IRAN_BINS = ("603799", "589210", "627648", "627961", "603770", "628023", "627760", "502908", "627412", "622106", "502229", "627488",
              "621986", "639346", "639607", "502806", "502938", "603769", "610433", "585983", "589463", "627353", "628157", "505416",
              "636214", "639370", "606373", "504706", "636795", "505785", "627381", "505801", "504172", "639217", "622106", "581672")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63}){1,5}")
_PHONE_RE = re.compile(r"(?<![0-9])(?:\+98|0098|98|0)?[ \-]?9(?:[ \-]?[0-9]){9}(?![0-9])")
_LANDLINE_RE = re.compile(r"(?<![0-9])0[1-8][0-9][ \-]?[0-9]{8}(?![0-9])")
_NATIONAL_RE = re.compile(r"(?<![0-9])[0-9]{10}(?![0-9])")
_WALLET_RES = (re.compile(r"(?<![A-Za-z0-9])0x[0-9a-fA-F]{40}(?![A-Za-z0-9])"),
               re.compile(r"(?<![A-Za-z0-9])bc1[0-9a-z]{25,60}(?![A-Za-z0-9])"),
               re.compile(r"(?<![A-Za-z0-9])T[1-9A-HJ-NP-Za-km-z]{33}(?![A-Za-z0-9])"))
_KEY_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~+/=:\-]{15,299}$")


@dataclass(frozen=True)
class Verdict:
    ok: bool                 # may this text be sent?
    kind: str = ""           # "" | one of SECRET_KINDS / PERSONAL_KINDS
    label_fa: str = ""
    secret: bool = False     # True: blocked whatever the settings say


def _luhn(digits):
    total, flip = 0, False
    for ch in reversed(digits):
        n = ord(ch) - 48
        if flip:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        flip = not flip
    return total % 10 == 0


def _is_card(text):
    for match in _CARD_RE.finditer(text):
        digits = re.sub(r"[^0-9]", "", match.group(0))
        if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
            continue
        if _luhn(digits) or (len(digits) == 16 and digits[:6] in _IRAN_BINS):
            return True
    return False


def _valid_national_id(digits):
    if len(digits) != 10 or len(set(digits)) == 1:
        return False
    total = sum(int(digits[i]) * (10 - i) for i in range(9))
    rest = total % 11
    return int(digits[9]) == (rest if rest < 2 else 11 - rest)


def _canon(text):
    """Digits to ASCII, ZWNJ and bidi marks removed: the form every pattern above is written for."""
    return fa_text.canon(text).replace("‌", " ")


def _find(text, share_private):
    c = _canon(text)
    wallet = any(p.search(c) for p in _WALLET_RES)
    if wallet:                      # a public wallet address is personal, not a key: do not let the long-token rule call it a secret
        for pattern in _WALLET_RES:
            c = pattern.sub(" ", c)
    if _PRIVATE_KEY_RE.search(c):
        return "private_key"
    if any(p.search(c) for p in _TOKEN_PATTERNS):
        return "key"
    if _SHEBA_RE.search(c):
        return "sheba"
    if _is_card(c):
        return "card"
    if _CREDENTIAL_DIGITS.search(c) or _CREDENTIAL_DIGITS_BEFORE.search(c) or _CREDENTIAL_TOKEN.search(c) or _CVV_RE.search(c):
        return "credential"
    if _RECOVERY_RE.search(c) and len(c.split()) >= 10:
        return "recovery"
    if share_private:
        return ""
    if wallet:
        return "wallet"
    if _EMAIL_RE.search(c):
        return "email"
    if _PHONE_RE.search(c) or _LANDLINE_RE.search(c):
        return "phone"
    if any(_valid_national_id(m.group(0)) for m in _NATIONAL_RE.finditer(c)):
        return "national_id"
    return ""


def check(text, share_private=False):
    """Is `text` allowed to leave the phone? Secrets are refused always; personal details unless `share_private`."""
    kind = _find(str(text or ""), bool(share_private))
    if not kind:
        return Verdict(True)
    return Verdict(False, kind, LABELS_FA[kind], kind in SECRET_KINDS)


def looks_like_key(text):
    """Is the WHOLE message one key-shaped token (what a pasted API key looks like)?"""
    body = str(text or "").strip()
    if not _KEY_SHAPE.match(body):
        return False
    return bool(re.search(r"[A-Za-z]", body) and re.search(r"[0-9]", body)) or body.startswith(("sk-", "AIza"))


def contains_text(haystack, needle):
    """Does `haystack` contain the secret `needle`, even written with other digits / spacing tricks? (used to scrub logs)"""
    needle = str(needle or "")
    return len(needle) >= 8 and needle in str(haystack or "")
