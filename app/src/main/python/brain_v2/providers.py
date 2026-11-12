"""
brain_v2.providers - the cloud services the user can connect with HIS OWN key
=============================================================================
A provider is plain data: where its chat endpoint is, which wire format it speaks and which model is a sensible
default. Nothing is contacted from here. The user chooses the provider in the chat (never guessed from a pasted key), sees
the exact host in the consent question, and every request goes to that host only.

Two wire formats are enough for today's services:

* "openai"    - POST <base>chat/completions with `Authorization: Bearer <key>` (Gemini's OpenAI-compatible endpoint, OpenAI,
                OpenRouter and any other OpenAI-compatible service the user names);
* "anthropic" - POST https://api.anthropic.com/v1/messages with `x-api-key` and `anthropic-version`.

Model names change often (services retire and rename them), so a default is only a starting point: the chat has a command to
change it and a clear message when a service does not know the model. Defaults checked against the services' own pages in
November 2026.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from self_builder import fa_text

__all__ = ["Provider", "PRESETS", "CUSTOM", "ORDER", "get", "endpoint", "valid_custom_base", "parse_provider_word", "sniff_key",
           "valid_model", "valid_key", "host_of"]

CUSTOM = "custom"
_HOST_RE = re.compile(r"^(?=.{4,100}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,79}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~+/=:-]{15,299}$")


@dataclass(frozen=True)
class Provider:
    id: str
    title_fa: str
    wire: str                    # "openai" | "anthropic"
    base_url: str                # always https, always ends with "/"
    path: str                    # appended to base_url
    default_model: str
    tokens_field: str = "max_tokens"
    send_temperature: bool = True
    key_page: str = ""           # where the user creates a key (shown as text; never fetched)
    note_fa: str = ""


PRESETS = {
    "gemini": Provider("gemini", "Gemini (گوگل)", "openai", "https://generativelanguage.googleapis.com/v1beta/openai/",
                       "chat/completions", "gemini-3.8-flash", "max_tokens", True, "aistudio.google.com/apikey",
                       "گوگل برای استفادهٔ سبک یک سطح رایگان دارد (شرایطش را خودِ سرویس تعیین می‌کند)."),
    "openai": Provider("openai", "OpenAI (ChatGPT)", "openai", "https://api.openai.com/v1/", "chat/completions",
                       "gpt-5.4-mini", "max_completion_tokens", False, "platform.openai.com/api-keys",
                       "OpenAI به‌ازای مصرف پول می‌گیرد؛ اعتبار حساب باید شارژ شده باشد."),
    "openrouter": Provider("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1/", "chat/completions",
                           "openrouter/auto", "max_tokens", True, "openrouter.ai/keys",
                           "یک درگاه برای مدل‌های زیاد؛ نام مدل را از سایتش می‌توانی بردارید (بعضی مدل‌ها رایگان‌اند)."),
    "anthropic": Provider("anthropic", "Claude (Anthropic)", "anthropic", "https://api.anthropic.com/v1/", "messages",
                          "claude-haiku-5-5", "max_tokens", True, "console.anthropic.com/settings/keys",
                          "Anthropic به‌ازای مصرف پول می‌گیرد؛ اعتبار حساب باید شارژ شده باشد."),
    CUSTOM: Provider(CUSTOM, "سرویس دلخواه (سازگار با OpenAI)", "openai", "", "chat/completions", "", "max_tokens", True, "",
                     "آدرس پایهٔ سرویسی که خودت انتخاب می‌کنی (باید https و سازگار با OpenAI باشد)."),
}
ORDER = ("gemini", "openai", "openrouter", "anthropic", CUSTOM)

_NAMES = {
    "gemini": ("gemini", "جمینای", "جیمینای", "جمنای", "گوگل", "google", "1"),
    "openai": ("openai", "اوپنایآی", "اوپنای", "chatgpt", "gpt", "چتجیپیتی", "چت", "2"),
    "openrouter": ("openrouter", "اوپنراوتر", "راوتر", "3"),
    "anthropic": ("claude", "کلود", "anthropic", "آنتروپیک", "انتروپیک", "4"),
    CUSTOM: ("دلخواه", "custom", "آدرس", "5"),
}


def get(provider_id):
    return PRESETS.get(provider_id)


def valid_model(model):
    return isinstance(model, str) and bool(_MODEL_RE.match(model))


def valid_key(key):
    """A key is one token of printable ASCII (no spaces, quotes or control characters): header injection is impossible."""
    return isinstance(key, str) and bool(_KEY_RE.match(key))


def host_of(url):
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host if _HOST_RE.match(host) else ""


def valid_custom_base(url):
    """(clean base url ending with '/', host) or (None, reason). Only https, no credentials/query/fragment, a real DNS name."""
    text = str(url or "").strip().strip("<>\"'«»").rstrip(".,;،؛")
    if not text or len(text) > 200 or any(ord(c) < 33 or ord(c) == 127 for c in text):
        return None, "invalid"
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None, "invalid"
    if parts.scheme.lower() != "https":
        return None, "not_https"
    if parts.username or parts.password or parts.query or parts.fragment:
        return None, "invalid"
    host = (parts.hostname or "").lower()
    if not _HOST_RE.match(host):
        return None, "bad_host"       # an IP address, localhost, or a name without a dot is not accepted
    if port not in (None, 443):
        return None, "bad_port"
    path = parts.path or "/"
    for tail in ("/chat/completions", "/chat/completions/"):
        if path.endswith(tail):
            path = path[: -len(tail)] or "/"
    if not path.endswith("/"):
        path += "/"
    if "//" in path or ".." in path:
        return None, "invalid"
    return "https://%s%s" % (host, path), host


def endpoint(provider_id, base_url=""):
    """The full https URL of the chat endpoint, or '' when the provider is unknown or the custom base is not acceptable."""
    provider = PRESETS.get(provider_id)
    if provider is None:
        return ""
    if provider_id == CUSTOM:
        clean, _ = valid_custom_base(base_url)
        return clean + provider.path if clean else ""
    return provider.base_url + provider.path


def parse_provider_word(text):
    """The provider id a short answer names («گوگل», «۲», «claude» ...), else None. A longer sentence is never a choice."""
    toks = fa_text.words(text)
    if not toks or len(toks) > 4:
        return None
    flat = {fa_text.key(t) for t in toks} | {"".join(fa_text.key(t) for t in toks)}
    hits = [pid for pid, names in _NAMES.items() if flat & {fa_text.key(n) for n in names}]
    return hits[0] if len(hits) == 1 else None


def sniff_key(key):
    """Which preset a key LOOKS like (only used to say 'this looks like a Gemini key' when it does not fit the chosen service)."""
    text = str(key or "")
    if text.startswith("sk-ant-"):
        return "anthropic"
    if text.startswith("sk-or-"):
        return "openrouter"
    if text.startswith("AIza"):
        return "gemini"
    if text.startswith("sk-"):
        return "openai"
    return None
