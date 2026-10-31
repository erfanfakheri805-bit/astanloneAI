"""
teacher.assistants - the outside assistants the app knows how to ask (ChatGPT, Claude, Gemini ...)
===================================================================================================
Plain data: for each assistant its Android package name(s) (to open or share into the installed app), its website (the
fallback when the app is not installed) and the names Persian speakers write for it.

The package names are listed in the manifest's `<queries>` too (Android 11+ hides other apps unless they are named there);
a test keeps the two lists identical. A wrong or outdated package name is harmless: the app is then simply reported as "not
visible" and the website route is offered instead.
"""

import re
from dataclasses import dataclass

__all__ = ["Assistant", "ASSISTANTS", "get", "find_assistant", "find_in_tokens", "all_packages", "squash"]


@dataclass(frozen=True)
class Assistant:
    assistant_id: str
    title: str
    packages: tuple
    site: str
    aliases: tuple          # already "squashed" (see `squash`)


_ZWNJ = "\u200c\u200d\u200e\u200f\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0640"
_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "أ": "ا", "إ": "ا", "ؤ": "و", "٠": "0", "١": "1", "٢": "2", "٣": "3",
                       "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9", "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
                       "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9"})
_JOIN_RE = re.compile(r"[\s\-_.'’`·]+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def squash(text):
    """`چت جی پی تی`, `چت‌جی‌پی‌تی`, `ChatGPT`, `chat-gpt` ... -> one comparable string."""
    text = str(text or "").lower().translate(_FOLD)
    text = "".join(ch for ch in text if ch not in _ZWNJ)
    return _JOIN_RE.sub("", text)


def _a(assistant_id, title, packages, site, *aliases):
    return Assistant(assistant_id, title, tuple(packages), site, tuple(sorted({squash(a) for a in aliases})))


ASSISTANTS = (
    _a("chatgpt", "ChatGPT", ("com.openai.chatgpt",), "https://chatgpt.com/", "chatgpt", "chat gpt", "gpt", "چت جی پی تی", "چت جی بی تی",
       "چت‌جی‌پی‌تی", "چاتجی‌پی‌تی", "جی پی تی", "جی بی تی", "چت جیپیتی", "چتجیبیتی", "chatgbt"),
    _a("claude", "Claude", ("com.anthropic.claude",), "https://claude.ai/", "claude", "claude ai", "کلود", "کلاد", "کلاود"),
    _a("gemini", "Gemini", ("com.google.android.apps.bard",), "https://gemini.google.com/", "gemini", "جمینای", "جیمینای", "جمینی",
       "جیمینی", "gemeni", "bard", "بارد"),
    _a("copilot", "Copilot", ("com.microsoft.copilot",), "https://copilot.microsoft.com/", "copilot", "کوپایلت", "کوپیلوت", "کوپایلوت"),
    _a("perplexity", "Perplexity", ("ai.perplexity.app.android",), "https://www.perplexity.ai/", "perplexity", "پرپلکسیتی", "پرپلکستی"),
    _a("deepseek", "DeepSeek", ("com.deepseek.chat",), "https://chat.deepseek.com/", "deepseek", "deep seek", "دیپ سیک", "دیپسیک"),
    _a("grok", "Grok", ("ai.x.grok",), "https://grok.com/", "grok", "گراک"),
)
_BY_ID = {a.assistant_id: a for a in ASSISTANTS}
_ALIAS = {alias: a.assistant_id for a in ASSISTANTS for alias in a.aliases}


def get(assistant_id):
    return _BY_ID.get(assistant_id)


def all_packages():
    return tuple(p for a in ASSISTANTS for p in a.packages)


def find_in_tokens(words):
    """`(assistant id, first index, one past the last index)` of the FIRST assistant named in the word list, or None.
    A name is 1-4 whole words long ("چت جی پی تی"); a word that merely contains a name ("بارداری") never matches."""
    words = [str(w) for w in list(words)[:200]]
    for i in range(len(words)):
        for n in range(1, 5):
            if i + n > len(words):
                break
            found = _ALIAS.get(squash("".join(words[i:i + n])))
            if found:
                return found, i, i + n
    return None


def find_assistant(text):
    """The id of the FIRST assistant named in `text` (as whole words, 1-4 words long), or None."""
    words = [w for w in _PUNCT_RE.sub(" ", str(text or "").lower().translate(_FOLD)).split() if w]
    found = find_in_tokens(words)
    return found[0] if found else None
