"""
net_tools - a small, REAL, permission-aware web retrieval path (Prompt 957)
===========================================================================
The app's core features are offline. This optional package reads a web page as
text or downloads one verified file, and only when the user has granted the
"network" permission. It refuses private/internal addresses (SSRF), limits
time and size, validates redirects at every hop and reports failures with a
stable code plus a short Persian and English message. It never claims a
connection that was not made.

    fetch_text(url, gate=..., policy=..., transport=...)   -> FetchResult
    download_file(url, dest_root, rel_dest, gate=..., expected_sha256=..., max_bytes=...) -> DownloadResult
    network_status(probe)                                   -> NetworkStatus (unknown without evidence)

Importing this package has no side effects (no sockets, files or threads).
"""

from .download import DOWNLOAD_CODES, DownloadResult, download_file
from .fetch import FETCH_CODES, FetchResult, decode_body, fetch_text, message_for
from .html_text import html_to_text
from .permission import NETWORK, CallableGate, PermissionGate, StaticGate
from .policy import FetchPolicy, ParsedUrl, UrlError, classify_ip, parse_url
from .status import NetworkStatus, network_status
from .transport import (HttpClientTransport, StreamResponse, TransportError, TransportRequest,
                        TransportResponse, make_ssl_context)

__all__ = [
    "DOWNLOAD_CODES", "DownloadResult", "download_file", "FETCH_CODES", "FetchResult", "decode_body", "fetch_text",
    "message_for", "html_to_text", "NETWORK", "CallableGate", "PermissionGate", "StaticGate",
    "FetchPolicy", "ParsedUrl", "UrlError", "classify_ip", "parse_url", "NetworkStatus", "network_status",
    "HttpClientTransport", "StreamResponse", "TransportError", "TransportRequest", "TransportResponse",
    "make_ssl_context",
]
