"""
net_tools.post - ONE JSON POST, permission-first (Prompt 959, stage A)
======================================================================
The only thing this adds next to `fetch_text` is a request WITH a body, for the user's own cloud brain (an API the user chose,
with a key the user typed). It keeps every guarantee of the GET path and adds the ones a key needs:

* the URL must be valid, `https` and public (`parse_url`) - the same SSRF rules as a page fetch;
* the permission gate must allow "network" BEFORE the transport is called;
* **redirects are never followed** (a 3xx is an error), so a key can never be sent to a host the user did not choose;
* only `content-type: application/json` plus the few API headers the transport allows (authorization, x-api-key, x-goog-api-key,
  anthropic-version) are sent; the answer must be JSON and is size-limited;
* a non-2xx answer keeps a SHORT, scrubbed error text (so "bad key" and "quota used up" can be told apart) - `scrub()` removes any
  secret the caller names, and the text is cut at `ERROR_TEXT_CHARS`;
* nothing here ever raises for a network or user error, and no message ever contains the request body or a header value.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Callable, Dict, Iterable, Mapping, Optional, Tuple

from .fetch import FETCH_CODES, _allowed, decode_body, message_for
from .permission import PermissionGate
from .policy import FetchPolicy, ParsedUrl, UrlError, parse_url
from .transport import MAX_POST_BYTES, HttpClientTransport, TransportError, TransportRequest

__all__ = ["PostResult", "post_json", "scrub", "error_summary", "post_message_for", "POST_CODES", "ERROR_TEXT_CHARS"]

POST_CODES = FETCH_CODES + ("bad_json", "request_too_large")
ERROR_TEXT_CHARS = 400
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_TOTAL_S = 75.0
DEFAULT_MAX_BYTES = 262144

_EXTRA: Dict[str, Tuple[str, str]] = {
    "ok": ("پاسخ دریافت شد.", "The answer was received."),
    "bad_json": ("پاسخ سرویس قابل‌فهم نبود.", "The service's answer could not be understood."),
    "request_too_large": ("درخواست از حد مجاز بزرگ‌تر است.", "The request is larger than the allowed limit."),
}
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_KEYISH = re.compile(r"(?:sk-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,}|[A-Za-z0-9_\-]{32,})")


def post_message_for(code: str, status: Optional[int] = None) -> Tuple[str, str]:
    if code in _EXTRA:
        return _EXTRA[code]
    return message_for(code, status)


@dataclass(frozen=True)
class PostResult:
    ok: bool
    code: str
    status: Optional[int]
    host: str
    path: str                 # path only (no query): it is what the audit line keeps
    data: object              # the parsed JSON (dict / list) on success, else None
    error_text: str           # short, scrubbed text of a non-2xx answer; "" otherwise
    bytes_read: int
    elapsed_s: float
    message_fa: str
    message_en: str
    detail: str = ""

    def to_dict(self) -> dict:
        out = asdict(self)
        out.pop("data", None)  # the answer itself is for the caller, never for logs
        return out


def scrub(text: object, secrets: Iterable[str] = ()) -> str:
    """Remove the named secrets (and anything shaped like a long key) from `text`; control characters become spaces."""
    clean = "".join(ch if (ch in "\n\t" or ord(ch) >= 32 and ord(ch) != 0x7F) else " " for ch in str(text or ""))
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= 4:
            clean = clean.replace(secret, "[key]")
            if len(secret) >= 8:  # APIs often echo only a prefix or a masked form of the key
                clean = clean.replace(secret[:8], "[key]")
    return _KEYISH.sub("[key]", clean)


def error_summary(body_text: str, secrets: Iterable[str] = ()) -> str:
    """The human-readable part of an API error body (`{"error": {"message": ...}}` and its common variants), scrubbed and short."""
    text = (body_text or "").strip()
    found = ""
    try:
        data = json.loads(text) if text[:1] in "[{" else None
    except ValueError:
        data = None
    for item in (data if isinstance(data, list) else [data]):
        if isinstance(item, dict):
            err = item.get("error", item)
            if isinstance(err, dict):
                found = str(err.get("message") or err.get("status") or err.get("code") or err.get("type") or "")
            elif isinstance(err, str):
                found = err
            if not found:
                found = str(item.get("message") or "")
        if found:
            break
    return scrub(found or text, secrets).strip()[:ERROR_TEXT_CHARS]


def _failure(code: str, parsed: Optional[ParsedUrl], started: float, clock: Callable[[], float], *, detail: str = "",
             status: Optional[int] = None, error_text: str = "", bytes_read: int = 0) -> PostResult:
    fa, en = post_message_for(code, status)
    host = parsed.host if parsed else ""
    path = parsed.path[:80] if parsed else ""
    return PostResult(False, code, status, host, path, None, error_text, bytes_read, round(max(0.0, clock() - started), 3),
                      fa, en, detail)


def post_json(url: str, payload: object, *, headers: Optional[Mapping[str, str]] = None, gate: PermissionGate,
              policy: Optional[FetchPolicy] = None, transport: Optional[Callable[[TransportRequest], object]] = None,
              clock: Callable[[], float] = time.monotonic, secrets: Iterable[str] = (),
              timeout_s: Optional[float] = None, total_timeout_s: Optional[float] = None,
              max_bytes: Optional[int] = None) -> PostResult:
    """POST `payload` (JSON) to `url`. Never raises for network/user errors; see the module docstring for the guarantees."""
    started = clock()
    try:
        return _post(url, payload, dict(headers or {}), gate, policy or FetchPolicy(), transport, clock, started,
                     tuple(s for s in secrets if isinstance(s, str)), timeout_s, total_timeout_s, max_bytes)
    except Exception as exc:  # last line of defence; never leak exception text (it could hold a header)
        return _failure("unknown_error", None, started, clock, detail=type(exc).__name__)


def _post(url, payload, headers, gate, policy, transport, clock, started, secrets, timeout_s, total_timeout_s,
          max_bytes) -> PostResult:
    parsed = parse_url(url, policy)
    if isinstance(parsed, UrlError):
        return _failure(parsed.code, None, started, clock, detail=parsed.detail)
    if not _allowed(gate):
        return _failure("permission_denied", parsed, started, clock)
    try:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        return _failure("bad_json", parsed, started, clock, detail="request")
    if not 0 < len(body) <= MAX_POST_BYTES:
        return _failure("request_too_large", parsed, started, clock)
    sent = {str(k): str(v) for k, v in headers.items()}
    sent["Content-Type"] = "application/json"
    idle = float(timeout_s) if timeout_s else DEFAULT_TIMEOUT_S           # an answer from a language model is slower than a web page
    total = float(total_timeout_s) if total_timeout_s else max(idle, DEFAULT_TOTAL_S)
    request = TransportRequest("POST", parsed.url, parsed.host, parsed.port, parsed.scheme, parsed.path_query, sent,
                               idle, max_bytes or max(policy.max_bytes, DEFAULT_MAX_BYTES), "reject", total, body, True)
    send = transport if transport is not None else HttpClientTransport(policy)
    try:
        resp = send(request)
    except TransportError as err:
        code = err.code if err.code in FETCH_CODES else "unknown_error"
        return _failure(code, parsed, started, clock, detail=err.detail)
    status = int(getattr(resp, "status", 0) or 0)
    raw = getattr(resp, "body", b"") or b""
    response_headers = getattr(resp, "headers", None) or {}
    if 300 <= status < 400:
        return _failure("http_error", parsed, started, clock, status=status, detail="redirect", bytes_read=len(raw))
    if not 200 <= status < 300:
        text = decode_body(raw[:16384], "", False) if raw else ""
        return _failure("http_error", parsed, started, clock, status=status, bytes_read=len(raw),
                        error_text=error_summary(text, secrets))
    content_type = str(response_headers.get("content-type", ""))
    media = content_type.split(";", 1)[0].strip().lower()
    if media != "application/json" and not media.endswith("+json"):
        return _failure("unsupported_content_type", parsed, started, clock, status=status, detail=media[:60] or "missing",
                        bytes_read=len(raw))
    if getattr(resp, "truncated", False):
        return _failure("too_large", parsed, started, clock, status=status, bytes_read=len(raw))
    charset = re.search(r"charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:\-]{1,40})", content_type, re.I)
    try:
        data = json.loads(decode_body(raw, charset.group(1) if charset else "", False))
    except (ValueError, RecursionError):
        return _failure("bad_json", parsed, started, clock, status=status, bytes_read=len(raw))
    if not isinstance(data, (dict, list)):
        return _failure("bad_json", parsed, started, clock, status=status, bytes_read=len(raw), detail="shape")
    fa, en = post_message_for("ok")
    return PostResult(True, "ok", status, parsed.host, parsed.path[:80], data, "", len(raw),
                      round(max(0.0, clock() - started), 3), fa, en)
