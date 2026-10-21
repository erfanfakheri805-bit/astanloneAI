"""
net_tools.fetch - read one web page as text, permission-first
=============================================================
`fetch_text(url, gate=..., policy=..., transport=...)` NEVER raises for network
or user errors; it returns a `FetchResult` whose `code` says exactly what
happened and whose `message_fa` / `message_en` can be shown to the user as is.

Order of checks (each one can stop the call, and nothing after it runs):
1. the URL must be valid and public (`parse_url`);
2. the permission gate must allow "network" - otherwise the transport is NOT
   called at all;
3. the transport runs inside a manual redirect loop (every hop re-validated);
4. 2xx is success, anything else is `http_error`;
5. the content type must be on the allowlist (a missing header is refused);
6. the body is decoded with the declared charset (UTF-8 and windows-1256 are
   tested; unknown charsets fall back to UTF-8);
7. HTML becomes readable text, other allowed types are returned as text.
"""

from __future__ import annotations

import codecs
import re
import time
from dataclasses import asdict, dataclass
from typing import Callable, Dict, Optional, Tuple

from .html_text import html_to_text
from .permission import NETWORK, PermissionGate
from .policy import FetchPolicy, ParsedUrl, UrlError, parse_url
from .redirects import HopFailure, walk
from .transport import HttpClientTransport, TransportError, TransportRequest

__all__ = ["FetchResult", "fetch_text", "decode_body", "message_for", "FETCH_CODES", "build_request"]

FETCH_CODES = (
    "ok", "invalid_url", "unsupported_scheme", "blocked_address", "permission_denied", "dns_failure", "offline",
    "connect_refused", "timeout", "tls_error", "too_large", "unsupported_content_type", "unsupported_encoding",
    "http_error", "too_many_redirects", "protocol_error", "unknown_error",
)

_MESSAGES: Dict[str, Tuple[str, str]] = {
    "ok": ("صفحه خوانده شد.", "The page was read."),
    "invalid_url": ("آدرس معتبر نیست.", "The address is not valid."),
    "unsupported_scheme": ("فقط آدرس‌های امن (https) پشتیبانی می‌شود.", "Only secure (https) addresses are supported."),
    "blocked_address": ("این آدرس به همین دستگاه یا یک شبکهٔ داخلی اشاره دارد و برای امنیت بسته شد.",
                        "This address points to this device or a private network and was blocked for safety."),
    "permission_denied": ("اجازهٔ دسترسی به اینترنت داده نشده؛ ابتدا باید خودت آن را تأیید کنی.",
                          "Internet access has not been granted; you have to approve it first."),
    "dns_failure": ("اینترنت در دسترس نیست یا نام سایت پیدا نشد.", "The network is unavailable or the site name was not found."),
    "offline": ("اینترنت در دسترس نیست یا نام سایت پیدا نشد.", "The network is unavailable or the site name was not found."),
    "connect_refused": ("اتصال به سایت برقرار نشد.", "The connection to the site could not be made."),
    "timeout": ("پاسخی در زمان مجاز نرسید.", "No answer arrived in time."),
    "tls_error": ("گواهی امنیتی سایت تأیید نشد؛ اتصال برقرار نشد.", "The site's security certificate could not be verified; no connection was made."),
    "too_large": ("پاسخ از حد مجاز بزرگ‌تر بود.", "The response was larger than the allowed limit."),
    "unsupported_content_type": ("نوع محتوای این آدرس پشتیبانی نمی‌شود.", "The content type of this address is not supported."),
    "unsupported_encoding": ("سایت پاسخ فشرده یا رمزنگاری‌شدهٔ پشتیبانی‌نشده فرستاد.", "The site sent a compressed or encoded response that is not supported."),
    "http_error": ("سایت خطا برگرداند.", "The site returned an error."),
    "too_many_redirects": ("آدرس بیش از حد به جاهای دیگر هدایت شد.", "The address redirected too many times."),
    "protocol_error": ("پاسخ سایت ناقص یا نامعتبر بود.", "The site's answer was incomplete or invalid."),
    "unknown_error": ("خطای ناشناخته‌ای هنگام خواندن صفحه رخ داد.", "An unknown error happened while reading the page."),
}
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_CHARSET_RE = re.compile(r"charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:\-]{1,40})", re.I)
_META_RE = re.compile(rb"<meta[^>]{0,400}?charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:\-]{1,40})", re.I)
_SAFE_CODECS = frozenset({
    "utf-8", "ascii", "utf-16", "utf-16-le", "utf-16-be", "iso8859-1", "iso8859-2", "iso8859-6", "iso8859-9",
    "iso8859-15", "cp1250", "cp1251", "cp1252", "cp1253", "cp1254", "cp1256", "koi8-r", "gb2312", "gbk",
    "gb18030", "big5", "shift_jis", "euc-jp", "euc-kr", "mac-roman",
})


def message_for(code: str, status: Optional[int] = None) -> Tuple[str, str]:
    fa, en = _MESSAGES.get(code, _MESSAGES["unknown_error"])
    if code == "http_error" and status:
        fa = "سایت خطا برگرداند (کد %s)." % str(status).translate(_FA_DIGITS)
        en = "The site returned an error (code %d)." % status
    return fa, en


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    code: str
    status: Optional[int]
    url: str
    final_url: str
    content_type: str
    title: str
    text: str
    truncated: bool
    bytes_read: int
    redirects: int
    elapsed_s: float
    message_fa: str
    message_en: str
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _failure(code: str, url: str, started: float, clock: Callable[[], float], *, detail: str = "",
             status: Optional[int] = None, final_url: str = "", redirects: int = 0,
             content_type: str = "", bytes_read: int = 0) -> FetchResult:
    fa, en = message_for(code, status)
    return FetchResult(False, code, status, url, final_url or url, content_type, "", "", False, bytes_read, redirects,
                       round(max(0.0, clock() - started), 3), fa, en, detail)


def build_request(parsed: ParsedUrl, policy: FetchPolicy, *, accept: Optional[str] = None,
                  total_timeout_s: Optional[float] = None, max_bytes: Optional[int] = None) -> TransportRequest:
    headers = {"Accept": accept} if accept else {}
    return TransportRequest("GET", parsed.url, parsed.host, parsed.port, parsed.scheme, parsed.path_query, headers,
                            policy.timeout_s, max_bytes or policy.max_bytes, policy.oversize, total_timeout_s)


def _allowed(gate: object) -> bool:
    try:
        return bool(gate.allowed(NETWORK)) is True  # type: ignore[union-attr]
    except Exception:
        return False  # a missing or broken gate means "not allowed"


def decode_body(body: bytes, header_charset: str = "", sniff_html: bool = False) -> str:
    """Decode with a BOM, else the declared charset, else (HTML) a <meta> charset, else UTF-8; never raises."""
    if body.startswith(b"\xef\xbb\xbf"):
        return body[3:].decode("utf-8", "replace")
    if body.startswith((b"\xff\xfe", b"\xfe\xff")):
        return body.decode("utf-16", "replace")
    name = (header_charset or "").strip().lower()
    if not name and sniff_html:
        m = _META_RE.search(body[:4096])
        name = m.group(1).decode("ascii", "ignore").lower() if m else ""
    codec = "utf-8"
    if name:
        try:
            normal = codecs.lookup(name).name
            if normal in _SAFE_CODECS:
                codec = normal
        except LookupError:
            pass
    try:
        return body.decode(codec, "replace")
    except (LookupError, ValueError):
        return body.decode("utf-8", "replace")


def fetch_text(url: str, *, gate: PermissionGate, policy: Optional[FetchPolicy] = None,
               transport: Optional[Callable[[TransportRequest], object]] = None,
               clock: Callable[[], float] = time.monotonic) -> FetchResult:
    """Read `url` as text. Never raises for network/user errors (see the module docstring)."""
    started = clock()
    shown = url[:300] if isinstance(url, str) else ""
    try:
        return _fetch(url, shown, gate, policy or FetchPolicy(), transport, clock, started)
    except Exception as exc:  # last line of defence; never leak exception text
        return _failure("unknown_error", shown, started, clock, detail=type(exc).__name__)


def _fetch(url, shown, gate, policy, transport, clock, started) -> FetchResult:
    parsed = parse_url(url, policy)
    if isinstance(parsed, UrlError):
        return _failure(parsed.code, shown, started, clock, detail=parsed.detail)
    if not _allowed(gate):
        return _failure("permission_denied", shown, started, clock)
    send = transport if transport is not None else HttpClientTransport(policy)
    try:
        resp, final, hops = walk(lambda p: send(build_request(p, policy)), parsed, policy)
    except HopFailure as fail:
        return _failure(fail.code, shown, started, clock, detail=fail.detail, status=fail.status)
    except TransportError as err:
        code = err.code if err.code in FETCH_CODES else "unknown_error"
        return _failure(code, shown, started, clock, detail=err.detail)
    status = int(getattr(resp, "status", 0) or 0)
    headers = getattr(resp, "headers", None) or {}
    body = getattr(resp, "body", b"") or b""
    common = dict(final_url=final.url, redirects=hops, bytes_read=len(body))
    if not 200 <= status < 300:
        return _failure("http_error", shown, started, clock, status=status, **common)
    content_type = str(headers.get("content-type", ""))
    media = content_type.split(";", 1)[0].strip().lower()
    if media not in policy.allowed_content_types:
        return _failure("unsupported_content_type", shown, started, clock, detail=media[:60] or "missing",
                        status=status, content_type=content_type[:100], **common)
    m = _CHARSET_RE.search(content_type)
    text = decode_body(body, m.group(1) if m else "", media in _HTML_TYPES)
    title = ""
    cap = policy.max_text_chars
    if media in _HTML_TYPES:
        title, text = html_to_text(text, cap + 1)
    else:
        text = collapse_plain(text)
    truncated = bool(getattr(resp, "truncated", False))
    if len(text) > cap:
        text, truncated = text[:cap], True
    fa, en = message_for("ok")
    return FetchResult(True, "ok", status, shown, final.url, content_type[:100], title, text, truncated, len(body),
                       hops, round(max(0.0, clock() - started), 3), fa, en)


def collapse_plain(text: str) -> str:
    """Plain-text bodies keep their layout; only control characters and CR are removed."""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch for ch in cleaned if ch in "\n\t" or ord(ch) >= 32 and ord(ch) != 0x7F).strip()
