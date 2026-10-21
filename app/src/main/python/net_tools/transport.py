"""
net_tools.transport - the only module that opens sockets
========================================================
`HttpClientTransport` is a small HTTP/1.1 GET client built on raw sockets plus
`http.client.HTTPResponse` (for parsing only). It is deliberately narrower than
`urllib`:

* resolves the host itself, REFUSES when ANY resolved address is non-public,
  and connects to an already-validated IP (no second lookup);
* re-checks `getpeername()` after connecting (DNS-rebinding / odd routing);
* HTTPS uses `ssl.create_default_context()` with `server_hostname` (certificate
  and host-name verification stay ON, TLS >= 1.2);
* one WALL-CLOCK deadline covers resolve + connect + handshake + headers +
  body, so a slow-drip server cannot hold a call past its deadline;
* `Accept-Encoding: identity` and any other `Content-Encoding` is refused, so a
  compressed bomb never expands in memory; reads at most `max_bytes + 1` bytes;
* no cookies, no credentials, no automatic redirects (3xx is returned as is);
  bodies are read for 2xx answers only.

Failures raise `TransportError(code, detail)`; `detail` is a short fixed token,
never exception text. A fake transport (any callable taking a
`TransportRequest`) can replace this class in tests; downloads additionally use
`.stream(request)`.
"""

from __future__ import annotations

import errno
import http.client
import io
import ipaddress
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Mapping, Optional, Tuple

from .policy import FetchPolicy, classify_ip

__all__ = [
    "TRANSPORT_CODES", "TransportError", "TransportRequest", "TransportResponse",
    "StreamResponse", "HttpClientTransport", "make_ssl_context",
]

TRANSPORT_CODES = (
    "dns_failure", "offline", "connect_refused", "timeout", "tls_error", "blocked_address",
    "too_large", "protocol_error", "unsupported_encoding", "unknown_error",
)
_ALLOWED_REQUEST_HEADERS = ("accept", "accept-language")
_DEFAULT_ACCEPT = "text/html,text/plain,application/json;q=0.9,application/xml;q=0.8,*/*;q=0.1"
_CHUNK = 65536
_MAX_HEADER_VALUE = 8192
_MAX_CANDIDATES = 4
_OFFLINE_ERRNOS = {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN}


class TransportError(Exception):
    """A network-level failure with a stable `code` (see TRANSPORT_CODES) and a short fixed `detail`."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__("%s:%s" % (code, detail) if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class TransportRequest:
    method: str
    url: str
    host: str
    port: int
    scheme: str
    path_query: str
    headers: Mapping[str, str]
    timeout_s: float
    max_bytes: int
    oversize: str = "reject"
    total_timeout_s: Optional[float] = None  # overall wall-clock limit; defaults to timeout_s


@dataclass(frozen=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    truncated: bool
    peer_ip: Optional[str]


class StreamResponse:
    """A response whose body is read incrementally. Always `close()` it (or use `with`)."""

    def __init__(self, status: int, headers: Mapping[str, str], peer_ip: Optional[str],
                 chunks: Callable[[], Iterator[bytes]], close: Callable[[], None],
                 declared_length: Optional[int] = None) -> None:
        self.status = status
        self.headers = headers
        self.peer_ip = peer_ip
        self.declared_length = declared_length
        self._chunks = chunks
        self._close = close
        self._closed = False

    def iter_chunks(self) -> Iterator[bytes]:
        return self._chunks()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._close()

    def __enter__(self) -> "StreamResponse":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def make_ssl_context() -> ssl.SSLContext:
    """The TLS context used for https: certificate and host-name verification ON, TLS 1.2 or newer."""
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname:
        raise RuntimeError("TLS verification must stay enabled")
    return ctx


# --------------------------------------------------------------------------- helpers

def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    return isinstance(exc, ssl.SSLError) and "timed out" in str(exc).lower()


def _map_error(exc: BaseException, phase: str) -> TransportError:
    """Turn an exception from the socket/http layers into a TransportError (never keeps exception text)."""
    if isinstance(exc, TransportError):
        return exc
    if _is_timeout(exc):
        return TransportError("timeout", phase)
    if isinstance(exc, ssl.SSLError) or isinstance(exc, ssl.CertificateError):
        return TransportError("tls_error", phase)
    if isinstance(exc, ConnectionRefusedError):
        return TransportError("connect_refused", phase)
    if isinstance(exc, http.client.IncompleteRead):
        return TransportError("protocol_error", "incomplete_body")
    if isinstance(exc, (http.client.HTTPException, ValueError)):
        return TransportError("protocol_error", phase)
    if isinstance(exc, ConnectionError):
        return TransportError("protocol_error", "connection_reset" if phase != "connect" else "connect_failed")
    if isinstance(exc, OSError):
        if exc.errno in _OFFLINE_ERRNOS:
            return TransportError("offline", phase)
        if exc.errno == errno.ETIMEDOUT:
            return TransportError("timeout", phase)
        return TransportError("unknown_error", type(exc).__name__)
    return TransportError("unknown_error", type(exc).__name__)


def _as_ip(host: str) -> Optional[str]:
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


class _DeadlineReader(io.RawIOBase):
    """Raw reader over a socket: every recv is bounded by min(idle timeout, time left to the overall deadline)."""

    def __init__(self, sock: socket.socket, deadline: float, idle: float, clock: Callable[[], float]) -> None:
        super().__init__()
        self._sock, self._deadline, self._idle, self._clock = sock, deadline, idle, clock

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise socket.timeout("deadline")
        self._sock.settimeout(min(self._idle, remaining))
        return self._sock.recv_into(buffer)


class _SockShim:
    """Gives http.client.HTTPResponse the `makefile` it expects, backed by the deadline reader."""

    def __init__(self, reader: _DeadlineReader) -> None:
        self._reader = reader

    def makefile(self, mode: str = "rb", buffering=None):
        return io.BufferedReader(self._reader, 8192)


class _Connection:
    def __init__(self, sock: socket.socket, response: http.client.HTTPResponse, peer_ip: str) -> None:
        self.sock, self.response, self.peer_ip = sock, response, peer_ip

    def close(self) -> None:
        for closer in (self.response.close, self.sock.close):
            try:
                closer()
            except Exception:
                pass


# --------------------------------------------------------------------------- the transport

class HttpClientTransport:
    """HTTP/1.1 GET over raw sockets with the guarantees listed in the module docstring."""

    def __init__(self, policy: Optional[FetchPolicy] = None, resolver: Callable = socket.getaddrinfo,
                 clock: Callable[[], float] = time.monotonic,
                 ssl_context_factory: Callable[[], ssl.SSLContext] = make_ssl_context,
                 socket_factory: Callable[..., socket.socket] = socket.socket) -> None:
        self._policy = policy or FetchPolicy()
        self._resolver = resolver
        self._clock = clock
        self._ssl_factory = ssl_context_factory
        self._socket_factory = socket_factory

    # ---- public API -------------------------------------------------------

    def __call__(self, request: TransportRequest) -> TransportResponse:
        conn, deadline = self._open(request)
        try:
            resp = conn.response
            headers = self._headers(resp)
            status = int(resp.status)
            if not 200 <= status < 300:
                return TransportResponse(status, headers, b"", False, conn.peer_ip)
            declared = self._check_body_headers(headers, resp, request)
            body, truncated = self._read_all(resp, request, declared)
            return TransportResponse(status, headers, body, truncated, conn.peer_ip)
        except Exception as exc:
            raise _map_error(exc, "read") from None
        finally:
            conn.close()

    def stream(self, request: TransportRequest) -> StreamResponse:
        conn, deadline = self._open(request)
        try:
            resp = conn.response
            headers = self._headers(resp)
            status = int(resp.status)
            declared = None
            if 200 <= status < 300:
                declared = self._check_body_headers(headers, resp, request, streaming=True)
        except Exception as exc:
            conn.close()
            raise _map_error(exc, "read") from None
        limit = request.max_bytes

        def chunks() -> Iterator[bytes]:
            if not 200 <= status < 300:
                return
            total = 0
            while True:
                try:
                    data = resp.read1(min(_CHUNK, limit + 1 - total))
                except Exception as exc:
                    raise _map_error(exc, "read") from None
                if not data:
                    break
                total += len(data)
                if total > limit:
                    raise TransportError("too_large", "stream")
                yield data
            if declared is not None and total < declared:
                raise TransportError("protocol_error", "incomplete_body")

        return StreamResponse(status, headers, conn.peer_ip, chunks, conn.close, declared)

    # ---- connection set-up ------------------------------------------------

    def _open(self, req: TransportRequest) -> Tuple[_Connection, float]:
        self._validate(req)
        total = req.total_timeout_s if req.total_timeout_s else req.timeout_s
        deadline = self._clock() + float(total)
        idle = float(req.timeout_s)
        candidates = self._candidates(req, deadline, idle)
        sock, peer_ip = self._connect(candidates, deadline, idle)
        try:
            if req.scheme == "https":
                sock = self._handshake(sock, req.host, deadline, idle)
            self._send(sock, req, deadline, idle)
            reader = _DeadlineReader(sock, deadline, idle, self._clock)
            resp = http.client.HTTPResponse(_SockShim(reader), method=req.method)
            try:
                resp.begin()
            except Exception:
                resp.close()
                raise
            return _Connection(sock, resp, peer_ip), deadline
        except Exception as exc:
            try:
                sock.close()
            except Exception:
                pass
            raise _map_error(exc, "open") from None

    @staticmethod
    def _validate(req: TransportRequest) -> None:
        if req.method != "GET":
            raise TransportError("protocol_error", "method_not_supported")
        if req.scheme not in ("http", "https"):
            raise TransportError("protocol_error", "scheme_not_supported")
        if not isinstance(req.port, int) or not 1 <= req.port <= 65535:
            raise TransportError("protocol_error", "bad_port")
        if not req.path_query.startswith("/") or any(c in req.path_query for c in " \r\n\x00"):
            raise TransportError("protocol_error", "bad_path")
        if not req.host or any(c in req.host for c in " \r\n\x00/\\@"):
            raise TransportError("protocol_error", "bad_host")
        if req.timeout_s <= 0 or req.max_bytes <= 0:
            raise TransportError("protocol_error", "bad_limits")
        for name, value in dict(req.headers or {}).items():
            if name.lower() not in _ALLOWED_REQUEST_HEADERS or any(c in str(value) for c in "\r\n\x00"):
                raise TransportError("protocol_error", "bad_request_header")

    def _resolve(self, host: str, port: int, timeout: float) -> List[Tuple[int, str, tuple]]:
        box: Dict[str, object] = {}

        def work() -> None:
            try:
                box["result"] = self._resolver(host, port, type=socket.SOCK_STREAM)
            except Exception as exc:  # reported to the caller below
                box["error"] = exc

        worker = threading.Thread(target=work, name="net_tools-dns", daemon=True)
        worker.start()
        worker.join(max(timeout, 0.001))
        if worker.is_alive():
            raise TransportError("timeout", "dns")
        error = box.get("error")
        if error is not None:
            if isinstance(error, socket.gaierror):
                if error.errno == getattr(socket, "EAI_AGAIN", None):
                    raise TransportError("offline", "dns")
                raise TransportError("dns_failure", "")
            if isinstance(error, OSError) and error.errno in _OFFLINE_ERRNOS:
                raise TransportError("offline", "dns")
            raise TransportError("dns_failure", "")
        found: List[Tuple[int, str, tuple]] = []
        for item in box.get("result") or ():
            try:
                family, _t, _p, _c, sockaddr = item
                ip = str(sockaddr[0])
            except (TypeError, ValueError, IndexError):
                continue
            if family in (socket.AF_INET, socket.AF_INET6) and all(ip != f[1] for f in found):
                found.append((family, ip, tuple(sockaddr)))
        if not found:
            raise TransportError("dns_failure", "no_address")
        return found

    def _candidates(self, req: TransportRequest, deadline: float, idle: float) -> List[Tuple[int, str, tuple]]:
        literal = _as_ip(req.host)
        if literal is not None:
            if ":" in literal:
                found = [(socket.AF_INET6, literal, (literal, req.port, 0, 0))]
            else:
                found = [(socket.AF_INET, literal, (literal, req.port))]
        else:
            found = self._resolve(req.host, req.port, min(idle, deadline - self._clock()))
        if not self._policy.allow_private_addresses:
            for _family, ip, _addr in found:
                reason = classify_ip(ip)
                if reason != "public":
                    raise TransportError("blocked_address", reason)
        out: List[Tuple[int, str, tuple]] = []
        for family, ip, sockaddr in found:
            if family == socket.AF_INET6:
                sockaddr = (ip, req.port, 0, 0)  # connect to the validated text form, never a scope id
            else:
                sockaddr = (ip, req.port)
            out.append((family, ip, sockaddr))
        return out[:_MAX_CANDIDATES]

    def _connect(self, candidates: List[Tuple[int, str, tuple]], deadline: float, idle: float):
        last: Optional[TransportError] = None
        for index, (family, _ip, sockaddr) in enumerate(candidates):
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise TransportError("timeout", "connect")
            attempt = min(idle, max(0.05, remaining / (len(candidates) - index)))
            sock = self._socket_factory(family, socket.SOCK_STREAM)
            try:
                sock.settimeout(attempt)
                sock.connect(sockaddr)
                peer = str(sock.getpeername()[0])
                if not self._policy.allow_private_addresses:
                    reason = classify_ip(peer)
                    if reason != "public":
                        raise TransportError("blocked_address", "peer_" + reason)
                return sock, peer
            except TransportError:
                sock.close()
                raise
            except Exception as exc:
                sock.close()
                last = _map_error(exc, "connect")
        raise last or TransportError("unknown_error", "no_candidate")

    def _handshake(self, sock: socket.socket, host: str, deadline: float, idle: float) -> ssl.SSLSocket:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise TransportError("timeout", "tls")
        sock.settimeout(min(idle, remaining))
        context = self._ssl_factory()
        try:
            return context.wrap_socket(sock, server_hostname=host)
        except Exception as exc:
            mapped = _map_error(exc, "tls")
            if mapped.code in ("protocol_error", "unknown_error", "connect_refused"):
                mapped = TransportError("tls_error", "handshake")
            raise mapped from None

    def _send(self, sock: socket.socket, req: TransportRequest, deadline: float, idle: float) -> None:
        extra = {k.lower(): str(v) for k, v in dict(req.headers or {}).items()}
        default = 443 if req.scheme == "https" else 80
        shown = "[%s]" % req.host if ":" in req.host else req.host
        host_header = shown if req.port == default else "%s:%d" % (shown, req.port)
        lines = [
            "GET %s HTTP/1.1" % req.path_query,
            "Host: %s" % host_header,
            "User-Agent: %s" % self._policy.user_agent,
            "Accept: %s" % extra.get("accept", _DEFAULT_ACCEPT),
            "Accept-Encoding: identity",
            "Connection: close",
        ]
        if "accept-language" in extra:
            lines.append("Accept-Language: %s" % extra["accept-language"])
        data = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise TransportError("timeout", "send")
        sock.settimeout(min(idle, remaining))
        sock.sendall(data)

    # ---- response handling ------------------------------------------------

    @staticmethod
    def _headers(resp: http.client.HTTPResponse) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for name, value in resp.getheaders():
            key = name.lower()
            if key in ("set-cookie", "set-cookie2"):
                continue
            value = str(value)[:_MAX_HEADER_VALUE]
            out[key] = value if key not in out else (out[key] + ", " + value)[:_MAX_HEADER_VALUE]
        return out

    @staticmethod
    def _check_body_headers(headers: Mapping[str, str], resp, req: TransportRequest, streaming: bool = False) -> Optional[int]:
        encoding = headers.get("content-encoding", "").strip().lower()
        if encoding not in ("", "identity"):
            raise TransportError("unsupported_encoding", "content_encoding")
        declared: Optional[int] = None
        raw = headers.get("content-length")
        if raw is not None and "transfer-encoding" not in headers:
            if not raw.strip().isascii() or not raw.strip().isdigit() or len(raw.strip()) > 12:
                raise TransportError("protocol_error", "bad_content_length")
            declared = int(raw.strip())
            if declared > req.max_bytes and (req.oversize == "reject" or streaming):
                raise TransportError("too_large", "content_length")
        return declared

    @staticmethod
    def _read_all(resp, req: TransportRequest, declared: Optional[int]) -> Tuple[bytes, bool]:
        limit = req.max_bytes
        chunks: List[bytes] = []
        total = 0
        while total <= limit:
            data = resp.read1(min(_CHUNK, limit + 1 - total))
            if not data:
                break
            chunks.append(data)
            total += len(data)
        body = b"".join(chunks)
        if total > limit:
            if req.oversize == "reject":
                raise TransportError("too_large", "body")
            return body[:limit], True
        if declared is not None and total < declared:
            raise TransportError("protocol_error", "incomplete_body")
        return body, False
