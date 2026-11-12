"""
brain_v2.cloud - ONE request to the user's own cloud brain, and the honest reading of its answer
================================================================================================
`ask(...)` builds the request for the provider's wire format, hands it to an injected `post` (the hardened JSON POST of
`net_tools`, which already checks the permission, the address and the size), and turns whatever comes back into a
`CloudResult`: the text on success, a STABLE failure code plus a plain Persian reason otherwise. It never raises.

The reasons are specific on purpose (bad key / unknown model / used-up quota / unreachable / region) because the user cannot
read a log: «مغز ابری جواب نداد» alone would send him guessing. A provider's own error message is shown too (short, scrubbed of
the key by `net_tools.post`).
"""

import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import providers

__all__ = ["CloudResult", "ask", "build_request", "parse_answer", "classify", "plain", "raw_text", "reason", "MAX_ANSWER_CHARS",
           "MAX_TOKENS_CHAT", "MAX_TOKENS_AUTHOR", "MAX_AUTHOR_CHARS", "FAILURE_CODES"]

MAX_ANSWER_CHARS = 6000
MAX_TOKENS_CHAT = 1500
MAX_TOKENS_AUTHOR = 6000            # a pack is longer than a chat answer
MAX_AUTHOR_CHARS = 60_000
ANTHROPIC_VERSION = "2023-06-01"
FAILURE_CODES = ("unreachable", "timeout", "bad_key", "region", "no_model", "quota", "bad_request", "provider_down", "bad_answer",
                 "empty", "blocked", "internal")
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

_REASONS = {
    "unreachable": ("به مغز ابری نرسیدم: اینترنت قطع است یا این سرویس از شبکهٔ فعلی در دسترس نیست. اگر در ایران هستی، ممکن است برای این سرویس فیلترشکن لازم باشد.",
                    "I could not reach the cloud brain: the internet is down or this service is not reachable from this network."),
    "timeout": ("مغز ابری در زمان مجاز جواب نداد؛ کمی بعد دوباره امتحان کن (اینترنت ضعیف یا نیاز به فیلترشکن هم همین نشانه را می‌دهد).",
                "The cloud brain did not answer in time."),
    "bad_key": ("سرویس کلید را قبول نکرد (نادرست، غیرفعال، یا مال سرویس دیگری است). بگو «کلید مغز ابری را عوض کن» و کلید درست را بفرست.",
                "The service rejected the key (wrong, disabled, or for another service)."),
    "region": ("سرویس گفت از این کشور یا شبکه پذیرفته نمی‌شود. با فیلترشکن امتحان کن یا سرویس دیگری را برگزین (بگو «مغز ابری را فعال کن»).",
               "The service says it is not available from this country or network."),
    "no_model": ("سرویس مدلِ «%s» را نمی‌شناسد (نام مدل‌ها عوض می‌شود). نام درست را از سایت سرویس بردار و بگو «مدل مغز ابری را ... کن».",
                 "The service does not know the configured model."),
    "quota": ("سقف استفاده یا اعتبار حسابت در سرویس تمام شده؛ کمی بعد دوباره امتحان کن یا اعتبار و سقف حساب را در سایت سرویس ببین.",
              "The usage limit or credit of your account at the service is used up."),
    "bad_request": ("سرویس درخواست را نپذیرفت.", "The service did not accept the request."),
    "provider_down": ("سرویس مشکل موقت دارد (کد %s)؛ کمی بعد دوباره امتحان کن.", "The service has a temporary problem (code %s)."),
    "bad_answer": ("پاسخ سرویس قابل‌فهم نبود.", "The service's answer could not be understood."),
    "empty": ("سرویس جواب خالی داد؛ سؤال را کوتاه‌تر یا دقیق‌تر بپرس.", "The service gave an empty answer."),
    "blocked": ("اینترنت برنامه یا اجازهٔ مغز ابری الان خاموش است؛ چیزی ارسال نشد.", "The app's internet or the cloud-brain permission is off; nothing was sent."),
    "internal": ("خطای غیرمنتظره‌ای رخ داد؛ چیزی ارسال نشد.", "An unexpected error happened; nothing was sent."),
}


@dataclass(frozen=True)
class CloudResult:
    ok: bool
    text: str
    code: str                     # "ok" or one of FAILURE_CODES
    status: Optional[int]
    host: str
    elapsed_s: float
    reason_fa: str
    reason_en: str
    truncated: bool = False       # the service stopped because of the length limit (the text is usable but cut)
    detail: str = ""              # the provider's own short, key-free error message (failures only)
    in_chars: int = 0
    out_chars: int = 0


def reason(code, model="", status=None):
    """(Persian, English) reason for a failure code."""
    fa, en = _REASONS.get(code, _REASONS["internal"])
    if code == "no_model":
        return fa % (model or "؟"), en
    if code == "provider_down":
        return fa % str(status or "").translate(_FA_DIGITS), en % (status or "")
    return fa, en


def build_request(provider, base_url, model, key, system, messages, *, max_tokens, temperature):
    """(url, payload, headers) for one non-streaming chat request; url is '' when the endpoint is not acceptable."""
    url = providers.endpoint(provider.id, base_url)
    if provider.wire == "anthropic":
        payload = {"model": model, "max_tokens": int(max_tokens), "system": system, "messages": list(messages)}
        if provider.send_temperature:
            payload["temperature"] = temperature
        return url, payload, {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    payload = {"model": model, "messages": [{"role": "system", "content": system}] + list(messages),
               provider.tokens_field: int(max_tokens)}
    if provider.send_temperature:
        payload["temperature"] = temperature
    return url, payload, {"Authorization": "Bearer " + key}


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str) and item.get("type", "text") == "text":
                parts.append(item["text"])
        return "".join(parts)
    return ""


def parse_answer(wire, data):
    """(text, truncated) from a provider's JSON; ValueError when the shape is not a chat answer."""
    if not isinstance(data, dict):
        raise ValueError("shape")
    if wire == "anthropic":
        return _text_of(data.get("content")), data.get("stop_reason") == "max_tokens"
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("message")
    return _text_of(message.get("content")), choices[0].get("finish_reason") == "length"


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FENCE_RE = re.compile(r"^\s*```[A-Za-z0-9_+-]*\s*$", re.M)
_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_BULLET_RE = re.compile(r"^(\s*)[*+]\s+", re.M)


def plain(text):
    """The answer as the chat shows it: no control characters, no Markdown noise, no run of blank lines, at most MAX_ANSWER_CHARS."""
    t = _CTRL_RE.sub("", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    t = _FENCE_RE.sub("", t)
    t = _HEADER_RE.sub("", t)
    t = _BULLET_RE.sub(lambda m: m.group(1) + "• ", t)
    t = t.replace("**", "").replace("__", "").replace("`", "")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t if len(t) <= MAX_ANSWER_CHARS else t[:MAX_ANSWER_CHARS].rstrip() + "…"


def raw_text(text):
    """The answer of an AUTHORING request: exactly what the brain wrote, except control characters and line-ending style. Source code must
    not go through `plain` (it would eat `__init__`, `**kwargs` and backticks). At most MAX_AUTHOR_CHARS; the caller checks `truncated`."""
    t = _CTRL_RE.sub("", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    return t.strip("\n \t")[:MAX_AUTHOR_CHARS]


def classify(post_result, model=""):
    """The stable failure code of a failed `PostResult`."""
    code, status = post_result.code, post_result.status
    hint = (post_result.error_text or "").lower()
    if code == "permission_denied":
        return "blocked"
    if code in ("dns_failure", "offline", "connect_refused", "tls_error", "blocked_address", "invalid_url", "unsupported_scheme"):
        return "unreachable"
    if code == "timeout":
        return "timeout"
    if code in ("bad_json", "unsupported_content_type", "too_large", "unsupported_encoding", "protocol_error", "request_too_large"):
        return "bad_answer" if code != "request_too_large" else "bad_request"
    if code == "http_error" and status:
        if any(w in hint for w in ("location is not supported", "region", "country", "not available in your", "not supported in your")):
            return "region"
        if status in (401,) or (status == 403):
            return "bad_key"
        if status == 404 or (status in (400, 422) and "model" in hint and any(w in hint for w in ("not found", "does not exist", "not supported", "unknown", "invalid"))):
            return "no_model"
        if status in (429, 402):
            return "quota"
        if status >= 500:
            return "provider_down"
        return "bad_request"
    return "internal"


def _failure(code, host, started, clock, *, model="", status=None, detail="", in_chars=0):
    fa, en = reason(code, model, status)
    return CloudResult(False, "", code, status, host, round(max(0.0, clock() - started), 3), fa, en, False, detail[:300], in_chars, 0)


def ask(post: Callable, provider, base_url, model, key, system, messages, *, max_tokens=MAX_TOKENS_CHAT, temperature=0.4,
        clock=None, raw=False) -> CloudResult:
    """Make one request. `post(url, payload, headers=..., secrets=[key])` is the injected hardened POST; never raises.
    `raw`: the answer is kept verbatim (authoring: code and pack text), not tidied for the chat."""
    clock = clock or time.monotonic
    started = clock()
    in_chars = sum(len(str(m.get("content", ""))) for m in messages) + len(system)
    try:
        url, payload, headers = build_request(provider, base_url, model, key, system, messages, max_tokens=max_tokens,
                                              temperature=temperature)
        if not url:
            return _failure("bad_request", "", started, clock, model=model, detail="endpoint", in_chars=in_chars)
        result = post(url, payload, headers=headers, secrets=[key])
        host = result.host
        if not result.ok:
            code = classify(result, model)
            return _failure(code, host, started, clock, model=model, status=result.status, detail=result.error_text, in_chars=in_chars)
        try:
            text, truncated = parse_answer(provider.wire, result.data)
        except ValueError:
            return _failure("bad_answer", host, started, clock, status=result.status, in_chars=in_chars)
        if raw:
            truncated = truncated or len(str(text or "")) > MAX_AUTHOR_CHARS + 2000
            text = raw_text(text)
        else:
            text = plain(text)
        if not text:
            return _failure("empty", host, started, clock, status=result.status, in_chars=in_chars)
        return CloudResult(True, text, "ok", result.status, host, round(max(0.0, clock() - started), 3), "", "", truncated, "",
                           in_chars, len(text))
    except Exception:                      # never let a provider's odd answer break the chat
        return _failure("internal", "", started, clock, model=model, in_chars=in_chars)
