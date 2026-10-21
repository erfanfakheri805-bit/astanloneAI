"""
net_tools.redirects - manual, re-validated redirect following
=============================================================
The transport never follows redirects. This module does, one hop at a time:
every `Location` is resolved against the current URL, run through
`parse_url` again (so a redirect into a private address, a non-http scheme or
an https->http downgrade is refused exactly like a first request), and the
number of hops is limited by the policy.
"""

from __future__ import annotations

import re
from typing import Callable, Optional, Tuple

from .policy import FetchPolicy, ParsedUrl, UrlError, parse_url

__all__ = ["REDIRECT_STATUSES", "HopFailure", "resolve_location", "walk"]

REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


class HopFailure(Exception):
    """A refusal while following redirects; `code` is one of the FetchResult codes."""

    def __init__(self, code: str, detail: str = "", status: Optional[int] = None) -> None:
        super().__init__(code)
        self.code, self.detail, self.status = code, detail, status


def _remove_dot_segments(path: str) -> str:
    out = []
    for segment in path.split("/"):
        if segment == "..":
            if len(out) > 1:
                out.pop()
        elif segment != ".":
            out.append(segment)
    if path.endswith(("/.", "/..")):
        out.append("")
    result = "/".join(out)
    return result if result.startswith("/") else "/" + result


def resolve_location(base: ParsedUrl, location: str, max_length: int = 2048) -> str:
    """Resolve a `Location` header value against `base` (RFC 3986 section 5.2, simplified)."""
    location = location.strip()
    try:  # http.client decodes header bytes as latin-1; a UTF-8 Location needs the round trip
        location = location.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    if not location or len(location) > max_length:
        return ""
    if _SCHEME_RE.match(location):
        return location
    if location.startswith("//"):
        return "%s:%s" % (base.scheme, location)
    origin = "%s://%s" % (base.scheme, base.authority)
    if location.startswith("/"):
        path, sep, rest = location.partition("?")
        return origin + _remove_dot_segments(path) + sep + rest
    if location.startswith("?"):
        return origin + base.path + location
    directory = base.path.rsplit("/", 1)[0] + "/"
    path, sep, rest = location.partition("?")
    return origin + _remove_dot_segments(directory + path) + sep + rest


def walk(call: Callable[[ParsedUrl], object], start: ParsedUrl, policy: FetchPolicy,
         release: Optional[Callable[[object], None]] = None) -> Tuple[object, ParsedUrl, int]:
    """Run `call(parsed)` and follow redirects. Returns (response, final_parsed_url, redirects).

    `call` may raise TransportError (left to the caller). Refusals raise HopFailure.
    `release(response)` is invoked on every redirect response that is not returned.
    """
    current, redirects = start, 0
    while True:
        response = call(current)
        status = getattr(response, "status", None)
        if status not in REDIRECT_STATUSES:
            return response, current, redirects
        location = (getattr(response, "headers", None) or {}).get("location", "")
        if release is not None:
            release(response)
        if not location:
            raise HopFailure("http_error", "redirect_without_location", status)
        if redirects >= policy.max_redirects:
            raise HopFailure("too_many_redirects", "limit_%d" % policy.max_redirects, status)
        target = resolve_location(current, location, policy.max_url_length)
        parsed = parse_url(target, policy) if target else UrlError("invalid_url", "bad_location")
        if isinstance(parsed, UrlError):
            code = parsed.code if parsed.code in ("blocked_address", "unsupported_scheme") else "invalid_url"
            raise HopFailure(code, "redirect_" + parsed.detail, status)
        if current.scheme == "https" and parsed.scheme == "http":
            raise HopFailure("unsupported_scheme", "https_to_http_downgrade", status)
        current, redirects = parsed, redirects + 1
