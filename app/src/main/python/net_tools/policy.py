"""
net_tools.policy - fetch limits, strict URL parsing and address classification
==============================================================================
Everything here is pure (no sockets, no DNS, no files). It decides, BEFORE any
network traffic, whether a URL may be contacted at all.

* `FetchPolicy` - immutable limits (timeout, size, redirects, content types).
* `parse_url`   - strict parser: only http/https, no userinfo, no whitespace
  or control characters, ports 1..65535, Persian (IDN) host names converted
  with the idna codec, legacy numeric IPv4 spellings (`2130706433`, `0x7f.1`,
  octal parts) and IPv6 literals normalised and refused when non-public.
* `classify_ip` - "public" or the reason an address must not be contacted
  (loopback, private, link_local, multicast, reserved, unspecified,
  carrier_grade_nat, metadata). IPv4-mapped, 6to4, Teredo and NAT64 addresses
  are judged by the IPv4 address they carry.

Host names are also checked against names that always mean "this device or
this private network" (localhost, *.local, *.internal, single-label names)
so such a name never even reaches DNS. The transport repeats the address check
on every resolved and on the connected peer address (DNS-rebinding defence).
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Tuple, Union

__all__ = [
    "DEFAULT_CONTENT_TYPES", "FetchPolicy", "ParsedUrl", "UrlError",
    "classify_ip", "parse_url", "is_public_ip",
]

DEFAULT_CONTENT_TYPES: Tuple[str, ...] = (
    "text/html", "text/plain", "application/json", "application/xml", "text/xml",
    "application/xhtml+xml", "text/markdown", "text/csv",
)

_OVERSIZE_MODES = ("reject", "truncate")
_UA_RE = re.compile(r"^[\x21-\x7e](?:[\x20-\x7e]{0,98}[\x21-\x7e])?$")
_CT_RE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")


def _num(name: str, value, low, high, kind):
    accepted = (int,) if kind is int else (int, float)
    if isinstance(value, bool) or not isinstance(value, accepted):
        raise ValueError("%s must be %s" % (name, "an integer" if kind is int else "a number"))
    if kind is float:
        value = float(value)
        if value != value:  # NaN
            raise ValueError("%s must not be NaN" % name)
    return kind(min(max(value, low), high))


@dataclass(frozen=True)
class FetchPolicy:
    """Immutable limits for one fetch. Out-of-range numbers are clamped, wrong types raise ValueError.

    `allow_private_addresses` exists ONLY so tests can talk to a loopback server.
    Turning it on lets a request reach this device and the private network
    behind the user's router (SSRF). Never enable it in the app.
    """

    timeout_s: float = 8.0
    max_bytes: int = 262144
    max_redirects: int = 3
    allow_http: bool = False
    allow_private_addresses: bool = False
    allowed_content_types: Tuple[str, ...] = DEFAULT_CONTENT_TYPES
    oversize: str = "reject"
    max_url_length: int = 2048
    user_agent: str = "StandaloneAI-LocalFirst/1.0"
    max_text_chars: int = 100000

    def __post_init__(self) -> None:
        s = object.__setattr__
        s(self, "timeout_s", _num("timeout_s", self.timeout_s, 0.5, 30.0, float))
        s(self, "max_bytes", _num("max_bytes", self.max_bytes, 1024, 8 * 2 ** 20, int))
        s(self, "max_redirects", _num("max_redirects", self.max_redirects, 0, 5, int))
        s(self, "max_url_length", _num("max_url_length", self.max_url_length, 64, 8192, int))
        s(self, "max_text_chars", _num("max_text_chars", self.max_text_chars, 100, 2_000_000, int))
        for name in ("allow_http", "allow_private_addresses"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError("%s must be a bool" % name)
        if self.oversize not in _OVERSIZE_MODES:
            raise ValueError("oversize must be 'reject' or 'truncate'")
        if not isinstance(self.user_agent, str) or not _UA_RE.match(self.user_agent):
            raise ValueError("user_agent must be 1..100 printable ASCII characters")
        types = self.allowed_content_types
        if isinstance(types, str) or not hasattr(types, "__iter__"):
            raise ValueError("allowed_content_types must be a sequence of media types")
        clean = []
        for item in types:
            if not isinstance(item, str) or not _CT_RE.match(item.strip().lower()):
                raise ValueError("invalid media type in allowed_content_types")
            clean.append(item.strip().lower())
        s(self, "allowed_content_types", tuple(dict.fromkeys(clean)))

    def with_timeout(self, seconds: float) -> "FetchPolicy":
        """A copy whose timeout is `seconds` (clamped by the same rules)."""
        data = {f: getattr(self, f) for f in self.__dataclass_fields__}
        data["timeout_s"] = seconds
        return FetchPolicy(**data)


# --------------------------------------------------------------------------- addresses

_METADATA_V4 = ipaddress.ip_address("169.254.169.254")
_METADATA_V6 = ipaddress.ip_address("fd00:ec2::254")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _classify(addr) -> str:
    if addr.version == 6:
        if addr.ipv4_mapped is not None:
            return _classify(addr.ipv4_mapped)
        if addr.sixtofour is not None:
            return _classify(addr.sixtofour)
        if addr.teredo is not None:
            for part in addr.teredo:  # (server, client): both must be public
                reason = _classify(part)
                if reason != "public":
                    return reason
            return "reserved"  # the Teredo range itself is never a normal public host
        if addr in _NAT64:
            return _classify(ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF))
    if addr == _METADATA_V4 or addr == _METADATA_V6:
        return "metadata"
    if addr.is_unspecified:
        return "unspecified"
    if addr.is_loopback:
        return "loopback"
    if addr.is_multicast:
        return "multicast"
    if addr.is_link_local:
        return "link_local"
    if addr.version == 4 and addr in _CGNAT:
        return "carrier_grade_nat"
    if addr.is_reserved:
        return "reserved"
    if addr.is_private:
        return "private"
    if not addr.is_global:
        return "reserved"
    return "public"


def classify_ip(ip: Union[str, ipaddress.IPv4Address, ipaddress.IPv6Address]) -> str:
    """'public' or the reason this address must not be contacted. Unparseable input fails closed ('invalid')."""
    try:
        text = str(ip)
        if text.count("%") == 1:  # IPv6 scope id such as fe80::1%eth0
            text = text.split("%", 1)[0]
        addr = ipaddress.ip_address(text)
    except ValueError:
        return "invalid"
    return _classify(addr)


def is_public_ip(ip: str) -> bool:
    return classify_ip(ip) == "public"


# --------------------------------------------------------------------------- URL parsing

@dataclass(frozen=True)
class ParsedUrl:
    """A validated, normalised http(s) URL. `host` is ASCII (IDN converted) or a normalised IP literal."""

    scheme: str
    host: str
    port: int
    path_query: str
    is_ip_literal: bool
    url: str

    @property
    def authority(self) -> str:
        host = "[%s]" % self.host if ":" in self.host else self.host
        default = 443 if self.scheme == "https" else 80
        return host if self.port == default else "%s:%d" % (host, self.port)

    @property
    def path(self) -> str:
        return self.path_query.split("?", 1)[0]


@dataclass(frozen=True)
class UrlError:
    """Why a URL was refused: code is invalid_url | unsupported_scheme | blocked_address."""

    code: str
    detail: str = ""


_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?$")
_NUM_LABEL_RE = re.compile(r"^(?:[0-9]+|0[xX][0-9a-fA-F]*)$")
_PCT_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_URL_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    "-._~:/?#[]@!$&'()*+,;=%")
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa", ".lan", ".intranet", ".corp")
_ALLOWED_FORMAT_CHARS = frozenset("\u200c")  # ZWNJ is legitimate in Persian text


def _legacy_ipv4(host: str) -> Optional[ipaddress.IPv4Address]:
    """inet_aton-style parsing (decimal, octal 0nnn, hex 0xnn; 1-4 parts). None when malformed."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    values = []
    for part in parts:
        if not _NUM_LABEL_RE.match(part):
            return None
        try:
            if part[:2] in ("0x", "0X"):
                if len(part) == 2:
                    return None
                values.append(int(part[2:], 16))
            elif len(part) > 1 and part[0] == "0":
                values.append(int(part, 8))
            else:
                values.append(int(part, 10))
        except ValueError:  # e.g. digit 8 or 9 in an octal part
            return None
    *head, last = values
    if any(v > 255 for v in head) or last >= 256 ** (5 - len(values)):
        return None
    number = last
    for i, v in enumerate(head):
        number += v << (8 * (3 - i))
    return ipaddress.IPv4Address(number)


def _encode_path(text: str) -> str:
    out = []
    for ch in text:
        if ch in _URL_SAFE:
            out.append(ch)
        else:
            out.extend("%%%02X" % b for b in ch.encode("utf-8"))
    return "".join(out)


def _bad_chars(url: str) -> bool:
    for ch in url:
        o = ord(ch)
        if o <= 0x20 or o == 0x7F or ch == "\\":
            return True
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cs", "Co", "Cn", "Zs", "Zl", "Zp") or (cat == "Cf" and ch not in _ALLOWED_FORMAT_CHARS):
            return True
    return False


def _host_ok_for_dns(host: str) -> Optional[str]:
    """Return a reason when the DNS name can never be a public site."""
    if host == "localhost" or host.endswith(".localhost"):
        return "localhost"
    if "." not in host:
        return "single_label_host"
    if any(host.endswith(s) for s in _BLOCKED_SUFFIXES):
        return "internal_name"
    if host in ("metadata.google.internal", "instance-data"):
        return "metadata"
    return None


def parse_url(url: object, policy: Optional[FetchPolicy] = None) -> Union[ParsedUrl, UrlError]:
    """Validate and normalise `url`. Never raises; returns `ParsedUrl` or `UrlError`."""
    policy = policy or FetchPolicy()
    if not isinstance(url, str) or not url:
        return UrlError("invalid_url", "empty_or_not_text")
    if len(url) > policy.max_url_length:
        return UrlError("invalid_url", "too_long")
    if _bad_chars(url):
        return UrlError("invalid_url", "forbidden_character")
    m = _SCHEME_RE.match(url)
    if not m:
        return UrlError("invalid_url", "no_scheme")
    scheme = m.group(1).lower()
    if scheme not in ("http", "https"):
        return UrlError("unsupported_scheme", scheme[:20])
    if scheme == "http" and not policy.allow_http:
        return UrlError("unsupported_scheme", "plain_http_not_allowed")
    rest = url[m.end():]
    if not rest.startswith("//"):
        return UrlError("invalid_url", "missing_authority")
    rest = rest[2:].split("#", 1)[0]
    cut = len(rest)
    for sep in "/?":
        pos = rest.find(sep)
        if 0 <= pos < cut:
            cut = pos
    authority, remainder = rest[:cut], rest[cut:]
    if not authority:
        return UrlError("invalid_url", "empty_host")
    if "@" in authority:
        return UrlError("invalid_url", "userinfo_not_allowed")
    host, port_text = authority, ""
    if authority.startswith("["):
        end = authority.find("]")
        if end < 0:
            return UrlError("invalid_url", "bad_ipv6_literal")
        host, tail = authority[1:end], authority[end + 1:]
        if tail:
            if not tail.startswith(":"):
                return UrlError("invalid_url", "bad_authority")
            port_text = tail[1:]
            if not port_text:
                return UrlError("invalid_url", "empty_port")
    elif ":" in authority:
        host, port_text = authority.rsplit(":", 1)
        if ":" in host or not port_text:
            return UrlError("invalid_url", "bad_authority")
    default_port = 443 if scheme == "https" else 80
    if port_text:
        if not (port_text.isascii() and port_text.isdigit() and len(port_text) <= 5):
            return UrlError("invalid_url", "bad_port")
        port = int(port_text)
        if not 1 <= port <= 65535:
            return UrlError("invalid_url", "bad_port")
    else:
        port = default_port
    is_ip = False
    if authority.startswith("["):
        if "%" in host:
            return UrlError("invalid_url", "ipv6_zone_not_allowed")
        try:
            addr = ipaddress.IPv6Address(host)
        except ValueError:
            return UrlError("invalid_url", "bad_ipv6_literal")
        host, is_ip = str(addr), True
    else:
        host = host.rstrip(".") if host.endswith(".") and not host.endswith("..") else host
        if not host:
            return UrlError("invalid_url", "empty_host")
        if host.isascii():
            host = host.lower()
        else:
            try:
                host = host.encode("idna").decode("ascii").lower()
            except (UnicodeError, ValueError):
                return UrlError("invalid_url", "bad_idn_host")
        last = host.rsplit(".", 1)[-1]
        if _NUM_LABEL_RE.match(last):  # numeric last label => an IPv4 spelling, never a name
            addr4 = _legacy_ipv4(host)
            if addr4 is None:
                return UrlError("invalid_url", "bad_numeric_host")
            host, is_ip = str(addr4), True
        else:
            if len(host) > 253 or not all(_LABEL_RE.match(lbl) for lbl in host.split(".")):
                return UrlError("invalid_url", "bad_host_name")
    if not policy.allow_private_addresses:
        if is_ip:
            reason = classify_ip(host)
            if reason != "public":
                return UrlError("blocked_address", reason)
        else:
            reason = _host_ok_for_dns(host)
            if reason:
                return UrlError("blocked_address", reason)
    if _PCT_RE.search(remainder):
        return UrlError("invalid_url", "bad_percent_escape")
    path_query = _encode_path(remainder)
    if not path_query:
        path_query = "/"
    elif path_query.startswith("?"):
        path_query = "/" + path_query
    if len(path_query) > policy.max_url_length:
        return UrlError("invalid_url", "too_long")
    shown = "[%s]" % host if is_ip and ":" in host else host
    netloc = shown if port == default_port else "%s:%d" % (shown, port)
    return ParsedUrl(scheme, host, port, path_query, is_ip, "%s://%s%s" % (scheme, netloc, path_query))
