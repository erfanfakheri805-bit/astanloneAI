"""Prompt 957 - net_tools.HttpClientTransport against a REAL loopback server, fake resolvers and fake sockets.

No traffic leaves the machine. TLS certificates cannot be tested here, so only the TLS context flags, the handshake
arguments and the failure mapping (a TLS client against a plain-text server) are exercised.
"""
import errno
import os
import socket
import socketserver
import ssl
import sys
import threading
import time
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from net_tools import (FetchPolicy, HttpClientTransport, NETWORK, StaticGate, TransportError, TransportRequest,
                       fetch_text, make_ssl_context)

GATE = StaticGate([NETWORK])
LOOPBACK = FetchPolicy(allow_http=True, allow_private_addresses=True, timeout_s=2.0)


def raw_response(status=200, headers=None, body=b"", reason="OK", length=True):
    lines = ["HTTP/1.1 %d %s" % (status, reason)]
    merged = [] if headers is None else list(headers)
    if length and not any(k.lower() == "content-length" for k, _v in merged):
        merged.append(("Content-Length", str(len(body))))
    merged.append(("Connection", "close"))
    for key, value in merged:
        lines.append("%s: %s" % (key, value))
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def static(status=200, headers=None, body=b"", **kw):
    payload = raw_response(status, headers, body, **kw)

    def route(conn, _head, _stop):
        conn.sendall(payload)
    return route


class Server:
    """A tiny raw-socket HTTP server: `routes` maps a request path to `fn(conn, request_head, stop_event)`."""

    def __init__(self, routes):
        self.routes, self.hits, self.stop = routes, [], threading.Event()

    def __enter__(self):
        outer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                conn, data = self.request, b""
                conn.settimeout(3)
                try:
                    while b"\r\n\r\n" not in data and len(data) < 65536:
                        chunk = conn.recv(4096)
                        if not chunk:
                            return
                        data += chunk
                        if not data.startswith(b"GET "):  # e.g. a TLS ClientHello: answer like a real server would
                            conn.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
                            return
                    head = data.decode("latin-1")
                    outer.hits.append(head)
                    path = head.split(" ", 2)[1].split("?", 1)[0]
                    (outer.routes.get(path) or outer.routes["*"])(conn, head, outer.stop)
                except OSError:
                    pass

        class Srv(socketserver.ThreadingMixIn, socketserver.TCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Srv(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def url(self, path="/"):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def request(self, path="/", **kw):
        values = dict(method="GET", url=self.url(path), host="127.0.0.1", port=self.port, scheme="http", path_query=path,
                      headers={}, timeout_s=2.0, max_bytes=100000)
        values.update(kw)
        return TransportRequest(**values)


def slow_body(stop, conn, count=200, delay=0.05):
    for _ in range(count):
        if stop.is_set():
            return
        conn.sendall(b"x")
        time.sleep(delay)


def routes_table():
    def slow(conn, _head, stop):
        conn.sendall(raw_response(200, [("Content-Type", "text/plain"), ("Content-Length", "1000")]))
        slow_body(stop, conn)

    def slow_headers(conn, _head, stop):
        conn.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
        slow_body(stop, conn)

    def silent(conn, _head, stop):
        stop.wait(2)

    def chunked(conn, _head, _stop):
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nTransfer-Encoding: chunked\r\n"
                     b"Connection: close\r\n\r\n6\r\nhello \r\n5;ext=1\r\nworld\r\n0\r\n\r\n")

    def chunked_cut(conn, _head, _stop):
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nTransfer-Encoding: chunked\r\n\r\nA\r\nonly-part")

    def until_close(conn, _head, _stop):
        conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nbody until close")

    def echo(conn, head, _stop):
        conn.sendall(raw_response(200, [("Content-Type", "text/plain")], head.encode("latin-1")))

    return {
        "/page": static(200, [("Content-Type", "text/html; charset=utf-8")],
                        "<html><head><title>سلام</title></head><body><p>متن فارسی</p></body></html>".encode("utf-8")),
        "/big": static(200, [("Content-Type", "text/plain")], b"a" * 5000),
        "/lie_big": static(200, [("Content-Type", "text/plain"), ("Content-Length", "999999999")], b"short"),
        "/lie_small": static(200, [("Content-Type", "text/plain"), ("Content-Length", "5")], b"0123456789ABCDEF"),
        "/dup_length": static(200, [("Content-Type", "text/plain"), ("Content-Length", "3"), ("Content-Length", "4")], b"abcd", length=False),
        "/bad_length": static(200, [("Content-Type", "text/plain"), ("Content-Length", "12abc")], b"x", length=False),
        "/redir": static(302, [("Location", "/page")]),
        "/redir_abs": None,  # filled in per test (needs the port)
        "/gzip": static(200, [("Content-Type", "text/plain"), ("Content-Encoding", "gzip")], b"\x1f\x8b\x08\x00"),
        "/cookie": static(200, [("Content-Type", "text/plain"), ("Set-Cookie", "a=1"), ("X-Dup", "one"), ("X-Dup", "two")], b"ok"),
        "/missing": static(404, body=b"not here", reason="Not Found"),
        "/garbage": lambda conn, _h, _s: conn.sendall(b"THIS IS NOT HTTP\r\n\r\n"),
        "/longline": lambda conn, _h, _s: conn.sendall(b"HTTP/1.1 200 OK\r\nX: " + b"a" * 70000 + b"\r\n\r\n"),
        "/empty": lambda conn, _h, _s: None,
        "/slow": slow, "/slowheaders": slow_headers, "/silent": silent, "/chunked": chunked, "/chunked_cut": chunked_cut,
        "/until_close": until_close, "/echo": echo,
        "*": static(404, body=b"x", reason="Not Found"),
    }


class RealServerTestCase(unittest.TestCase):
    def setUp(self):
        self.srv = Server({k: v for k, v in routes_table().items() if v is not None})
        self.srv.__enter__()
        self.addCleanup(self.srv.__exit__, None, None, None)
        self.transport = HttpClientTransport(LOOPBACK)

    def get(self, path, **kw):
        return self.transport(self.srv.request(path, **kw))


class NormalRequestTests(RealServerTestCase):
    def test_page_through_fetch_text(self):
        r = fetch_text(self.srv.url("/page"), gate=GATE, policy=LOOPBACK)
        self.assertTrue(r.ok, r)
        self.assertEqual((r.title, r.text), ("سلام", "متن فارسی"))
        self.assertEqual(len(self.srv.hits), 1)

    def test_request_line_and_headers_are_minimal_and_safe(self):
        resp = self.get("/echo?q=%D8%B3")
        head = resp.body.decode("latin-1")
        self.assertTrue(head.startswith("GET /echo?q=%D8%B3 HTTP/1.1\r\n"), head)
        lowered = head.lower()
        self.assertIn("host: 127.0.0.1:%d\r\n" % self.srv.port, lowered)
        self.assertIn("user-agent: standaloneai-localfirst/1.0\r\n", lowered)
        self.assertIn("accept-encoding: identity\r\n", lowered)
        self.assertIn("connection: close\r\n", lowered)
        for forbidden in ("cookie", "authorization", "referer", "x-forwarded"):
            self.assertNotIn(forbidden, lowered)

    def test_only_allowlisted_extra_request_headers_are_sent(self):
        resp = self.get("/echo", headers={"Accept": "text/plain", "Accept-Language": "fa"})
        self.assertIn("accept: text/plain\r\n", resp.body.decode("latin-1").lower())
        self.assertIn("accept-language: fa\r\n", resp.body.decode("latin-1").lower())
        for headers in ({"Cookie": "a=1"}, {"Authorization": "Bearer x"}, {"Accept": "a\r\nX-Evil: 1"}):
            with self.subTest(headers=headers):
                with self.assertRaises(TransportError) as ctx:
                    self.get("/echo", headers=headers)
                self.assertEqual(ctx.exception.code, "protocol_error")

    def test_response_headers_are_lowercased_cookies_dropped_duplicates_joined(self):
        resp = self.get("/cookie")
        self.assertEqual((resp.status, resp.body), (200, b"ok"))
        self.assertNotIn("set-cookie", resp.headers)
        self.assertEqual(resp.headers["x-dup"], "one, two")
        self.assertTrue(all(k == k.lower() for k in resp.headers))
        self.assertEqual(resp.peer_ip, "127.0.0.1")

    def test_chunked_and_read_until_close_bodies(self):
        self.assertEqual(self.get("/chunked").body, b"hello world")
        self.assertEqual(self.get("/until_close").body, b"body until close")

    def test_error_statuses_return_without_a_body(self):
        resp = self.get("/missing")
        self.assertEqual((resp.status, resp.body), (404, b""))
        r = fetch_text(self.srv.url("/missing"), gate=GATE, policy=LOOPBACK)
        self.assertEqual((r.ok, r.code, r.status), (False, "http_error", 404))

    def test_redirects_are_returned_not_followed_by_the_transport_but_followed_by_fetch(self):
        resp = self.get("/redir")
        self.assertEqual((resp.status, resp.headers["location"], resp.body), (302, "/page", b""))
        self.assertEqual(len(self.srv.hits), 1)
        r = fetch_text(self.srv.url("/redir"), gate=GATE, policy=LOOPBACK)
        self.assertTrue(r.ok, r)
        self.assertEqual((r.redirects, r.final_url), (1, self.srv.url("/page")))


class SizeLimitTests(RealServerTestCase):
    def test_reject_mode(self):
        with self.assertRaises(TransportError) as ctx:
            self.get("/big", max_bytes=1024)
        self.assertEqual(ctx.exception.code, "too_large")
        r = fetch_text(self.srv.url("/big"), gate=GATE, policy=FetchPolicy(allow_http=True, allow_private_addresses=True, max_bytes=1024))
        self.assertEqual((r.ok, r.code), (False, "too_large"))

    def test_truncate_mode(self):
        resp = self.get("/big", max_bytes=1024, oversize="truncate")
        self.assertEqual((len(resp.body), resp.truncated), (1024, True))
        r = fetch_text(self.srv.url("/big"), gate=GATE, policy=FetchPolicy(
            allow_http=True, allow_private_addresses=True, max_bytes=1024, oversize="truncate"))
        self.assertEqual((r.ok, r.truncated, r.bytes_read), (True, True, 1024))

    def test_limits_apply_when_the_length_is_not_declared_up_front(self):
        for path in ("/until_close", "/chunked"):  # no Content-Length: only the read loop can notice
            with self.subTest(path=path, mode="reject"):
                with self.assertRaises(TransportError) as ctx:
                    self.get(path, max_bytes=5)
                self.assertEqual((ctx.exception.code, ctx.exception.detail), ("too_large", "body"))
            with self.subTest(path=path, mode="truncate"):
                resp = self.get(path, max_bytes=5, oversize="truncate")
                self.assertEqual((len(resp.body), resp.truncated), (5, True))
        self.assertEqual(self.get("/until_close", max_bytes=5, oversize="truncate").body, b"body ")

    def test_exact_limit_is_not_truncated(self):
        resp = self.get("/big", max_bytes=5000)
        self.assertEqual((len(resp.body), resp.truncated), (5000, False))
        with self.assertRaises(TransportError):
            self.get("/big", max_bytes=4999)

    def test_lying_content_length(self):
        with self.assertRaises(TransportError) as ctx:  # declared far over the limit: refused before reading
            self.get("/lie_big", max_bytes=1000)
        self.assertEqual((ctx.exception.code, ctx.exception.detail), ("too_large", "content_length"))
        with self.assertRaises(TransportError) as ctx:  # truncate mode still notices the body never arrives
            self.get("/lie_big", max_bytes=1000, oversize="truncate")
        self.assertEqual((ctx.exception.code, ctx.exception.detail), ("protocol_error", "incomplete_body"))
        self.assertEqual(self.get("/lie_small").body, b"01234")  # HTTP framing: only the declared 5 bytes belong to the body

    def test_malformed_or_conflicting_content_length(self):
        for path in ("/bad_length", "/dup_length"):
            with self.subTest(path=path):
                with self.assertRaises(TransportError) as ctx:
                    self.get(path)
                self.assertEqual(ctx.exception.code, "protocol_error")

    def test_compressed_responses_are_refused(self):
        with self.assertRaises(TransportError) as ctx:
            self.get("/gzip")
        self.assertEqual(ctx.exception.code, "unsupported_encoding")


class DeadlineTests(RealServerTestCase):
    def test_slow_drip_body_cannot_outlive_the_deadline(self):
        started = time.monotonic()
        with self.assertRaises(TransportError) as ctx:
            self.get("/slow", timeout_s=2.0, total_timeout_s=0.4)
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertLess(time.monotonic() - started, 1.5)

    def test_slow_drip_through_fetch_text_uses_the_policy_timeout(self):
        started = time.monotonic()
        r = fetch_text(self.srv.url("/slow"), gate=GATE, policy=FetchPolicy(
            allow_http=True, allow_private_addresses=True, timeout_s=0.5))
        self.assertEqual((r.ok, r.code), (False, "timeout"))
        self.assertLess(time.monotonic() - started, 2.0)

    def test_slow_drip_headers_cannot_outlive_the_deadline(self):
        started = time.monotonic()
        with self.assertRaises(TransportError) as ctx:
            self.get("/slowheaders", timeout_s=2.0, total_timeout_s=0.4)
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertLess(time.monotonic() - started, 1.5)

    def test_silent_server_times_out(self):
        started = time.monotonic()
        with self.assertRaises(TransportError) as ctx:
            self.get("/silent", timeout_s=0.3)
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertLess(time.monotonic() - started, 1.5)

    def test_stream_deadline_covers_the_body_too(self):
        started = time.monotonic()
        stream = self.transport.stream(self.srv.request("/slow", timeout_s=2.0, total_timeout_s=0.4))
        with stream, self.assertRaises(TransportError) as ctx:
            for _chunk in stream.iter_chunks():
                pass
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertLess(time.monotonic() - started, 1.5)


class MalformedResponseTests(RealServerTestCase):
    def test_garbage_empty_overlong_and_truncated_chunked_responses(self):
        for path in ("/garbage", "/empty", "/longline", "/chunked_cut"):
            with self.subTest(path=path):
                with self.assertRaises(TransportError) as ctx:
                    self.get(path)
                self.assertEqual(ctx.exception.code, "protocol_error")

    def test_only_get_over_http_or_https_is_supported_and_requests_are_sanitised(self):
        bad = [dict(method="POST"), dict(scheme="ftp"), dict(port=0), dict(port=70000), dict(path_query="no-slash"),
               dict(path_query="/a b"), dict(path_query="/a\r\nHost: evil"), dict(host="a b"), dict(host="a/b"), dict(host=""),
               dict(host="user@evil"), dict(timeout_s=0), dict(max_bytes=0)]
        for override in bad:
            with self.subTest(override=override):
                with self.assertRaises(TransportError) as ctx:
                    self.get("/page", **override)
                self.assertEqual(ctx.exception.code, "protocol_error")
        self.assertEqual(self.srv.hits, [])


class AddressRefusalTests(unittest.TestCase):
    def test_default_policy_refuses_a_loopback_server_before_connecting(self):
        with Server({"*": static(200, [("Content-Type", "text/plain")], b"secret admin page")}) as srv:
            transport = HttpClientTransport(FetchPolicy())
            with self.assertRaises(TransportError) as ctx:
                transport(srv.request("/"))
            self.assertEqual((ctx.exception.code, ctx.exception.detail), ("blocked_address", "loopback"))
            r = fetch_text(srv.url("/"), gate=GATE, policy=FetchPolicy(allow_http=True))
            self.assertEqual((r.ok, r.code, r.detail), (False, "blocked_address", "loopback"))
            r = fetch_text(srv.url("/"), gate=GATE)
            self.assertEqual(r.code, "unsupported_scheme")
            self.assertEqual(srv.hits, [], "the server must never have been contacted")

    def test_a_name_that_resolves_to_loopback_is_refused_without_connecting(self):
        with Server({"*": static(200, [("Content-Type", "text/plain")], b"internal")}) as srv:
            resolver = lambda host, port, type=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]  # noqa: E731
            transport = HttpClientTransport(FetchPolicy(), resolver=resolver)
            with self.assertRaises(TransportError) as ctx:
                transport(srv.request("/", host="innocent.example.org"))
            self.assertEqual((ctx.exception.code, ctx.exception.detail), ("blocked_address", "loopback"))
            self.assertEqual(srv.hits, [])

    def test_one_private_address_among_public_ones_poisons_the_whole_answer(self):
        calls = []

        def factory(*args):
            calls.append(args)
            raise AssertionError("no socket may be created")
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                   (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 443))]
        transport = HttpClientTransport(FetchPolicy(), resolver=lambda h, p, type=0: answers, socket_factory=factory)
        with self.assertRaises(TransportError) as ctx:
            transport(FakeServer.request(host="rebind.example.org"))
        self.assertEqual((ctx.exception.code, ctx.exception.detail), ("blocked_address", "private"))
        self.assertEqual(calls, [])

    def test_literal_private_ip_hosts_are_refused_without_resolving(self):
        resolved = []
        transport = HttpClientTransport(FetchPolicy(), resolver=lambda *a, **k: resolved.append(a) or [])
        for host in ("127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "fd00:ec2::254", "::ffff:192.168.1.1"):
            with self.subTest(host=host):
                with self.assertRaises(TransportError) as ctx:
                    transport(FakeServer.request(host=host))
                self.assertEqual(ctx.exception.code, "blocked_address")
        self.assertEqual(resolved, [])


class FakeSocket:
    """Stands in for a connected socket (no traffic)."""

    def __init__(self, peer=("93.184.216.34", 443), connect_error=None, log=None):
        self.peer, self.connect_error, self.log = peer, connect_error, log if log is not None else []
        self.closed = False

    def settimeout(self, value):
        self.log.append(("settimeout", value))

    def connect(self, address):
        self.log.append(("connect", address))
        if self.connect_error is not None:
            raise self.connect_error

    def getpeername(self):
        return self.peer

    def close(self):
        self.closed = True


class FakeServer:
    @staticmethod
    def request(host="example.org", port=443, scheme="https", **kw):
        values = dict(method="GET", url="%s://%s/" % (scheme, host), host=host, port=port, scheme=scheme, path_query="/",
                      headers={}, timeout_s=1.0, max_bytes=1000)
        values.update(kw)
        return TransportRequest(**values)


class ConnectionSafetyTests(unittest.TestCase):
    PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    def test_peer_address_is_rechecked_after_connecting(self):
        log, made = [], []

        def factory(family, kind):
            made.append(FakeSocket(peer=("10.0.0.1", 443), log=log))
            return made[-1]
        transport = HttpClientTransport(FetchPolicy(), resolver=lambda h, p, type=0: self.PUBLIC, socket_factory=factory)
        with self.assertRaises(TransportError) as ctx:
            transport(FakeServer.request())
        self.assertEqual((ctx.exception.code, ctx.exception.detail), ("blocked_address", "peer_private"))
        self.assertTrue(made[0].closed)
        self.assertEqual([entry for entry in log if entry[0] == "connect"], [("connect", ("93.184.216.34", 443))])

    def test_connects_to_the_validated_ip_with_a_single_resolution_and_verifies_tls_for_the_original_name(self):
        resolutions, log, handshakes = [], [], []

        def resolver(host, port, type=0):
            resolutions.append(host)
            return self.PUBLIC

        class Context:
            def wrap_socket(self, sock, server_hostname=None):
                handshakes.append(server_hostname)
                raise ssl.SSLCertVerificationError("certificate verify failed")
        transport = HttpClientTransport(FetchPolicy(), resolver=resolver, ssl_context_factory=Context,
                                        socket_factory=lambda f, k: FakeSocket(log=log))
        with self.assertRaises(TransportError) as ctx:
            transport(FakeServer.request(host="Example.org"))
        self.assertEqual(ctx.exception.code, "tls_error")
        self.assertEqual(resolutions, ["Example.org"])
        self.assertEqual(handshakes, ["Example.org"])
        self.assertIn(("connect", ("93.184.216.34", 443)), log)

    def test_next_validated_address_is_tried_when_the_first_refuses(self):
        two = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700::1111", 443, 0, 0)),
               (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        attempts = []

        def factory(family, kind):
            attempts.append(family)
            if family == socket.AF_INET6:
                return FakeSocket(connect_error=ConnectionRefusedError())
            return FakeSocket(peer=("93.184.216.34", 443), connect_error=OSError(errno.ENETUNREACH, "x"))
        transport = HttpClientTransport(FetchPolicy(), resolver=lambda h, p, type=0: two, socket_factory=factory)
        with self.assertRaises(TransportError) as ctx:
            transport(FakeServer.request())
        self.assertEqual(attempts, [socket.AF_INET6, socket.AF_INET])
        self.assertEqual(ctx.exception.code, "offline")  # the last failure is the one reported

    def test_connect_failures_are_mapped(self):
        cases = ((ConnectionRefusedError(), "connect_refused"), (socket.timeout("t"), "timeout"),
                 (OSError(errno.ENETUNREACH, "x"), "offline"), (OSError(errno.EHOSTUNREACH, "x"), "offline"),
                 (OSError(errno.ETIMEDOUT, "x"), "timeout"), (OSError(errno.EACCES, "denied"), "unknown_error"))
        for error, code in cases:
            with self.subTest(error=type(error).__name__, code=code):
                transport = HttpClientTransport(FetchPolicy(), resolver=lambda h, p, type=0: self.PUBLIC,
                                                socket_factory=lambda f, k, e=error: FakeSocket(connect_error=e))
                with self.assertRaises(TransportError) as ctx:
                    transport(FakeServer.request())
                self.assertEqual(ctx.exception.code, code)
                self.assertNotIn("denied", str(ctx.exception))

    def test_real_connection_refused(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        transport = HttpClientTransport(LOOPBACK)
        with self.assertRaises(TransportError) as ctx:
            transport(FakeServer.request(host="127.0.0.1", port=port, scheme="http"))
        self.assertEqual(ctx.exception.code, "connect_refused")


class ResolverFailureTests(unittest.TestCase):
    def run_with(self, resolver, **kw):
        transport = HttpClientTransport(FetchPolicy(), resolver=resolver)
        with self.assertRaises(TransportError) as ctx:
            transport(FakeServer.request(host="site.example.org", **kw))
        return ctx.exception

    def test_resolver_errors_are_mapped(self):
        def raises(error):
            def resolver(host, port, type=0):
                raise error
            return resolver
        self.assertEqual(self.run_with(raises(socket.gaierror(socket.EAI_NONAME, "nope"))).code, "dns_failure")
        self.assertEqual(self.run_with(raises(socket.gaierror(socket.EAI_AGAIN, "again"))).code, "offline")
        self.assertEqual(self.run_with(raises(OSError(errno.ENETUNREACH, "down"))).code, "offline")
        self.assertEqual(self.run_with(raises(RuntimeError("boom"))).code, "dns_failure")
        self.assertEqual(self.run_with(lambda h, p, type=0: []).code, "dns_failure")
        self.assertEqual(self.run_with(lambda h, p, type=0: [("junk",), (1, 2)]).code, "dns_failure")
        self.assertEqual(self.run_with(lambda h, p, type=0: [(socket.AF_UNIX, 1, 0, "", "/tmp/x")]).code, "dns_failure")

    def test_a_stalled_resolver_cannot_hold_the_call(self):
        stop = threading.Event()

        def slow(host, port, type=0):
            stop.wait(1.0)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        started = time.monotonic()
        try:
            err = self.run_with(slow, timeout_s=0.2)
        finally:
            stop.set()
        self.assertEqual(err.code, "timeout")
        self.assertLess(time.monotonic() - started, 0.9)


class TlsTests(unittest.TestCase):
    def test_context_keeps_certificate_and_hostname_verification_on(self):
        ctx = make_ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertGreaterEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_tls_against_a_plain_text_server_is_a_tls_error_not_a_hang(self):
        with Server({"*": static(200, [("Content-Type", "text/plain")], b"plain")}) as srv:
            transport = HttpClientTransport(LOOPBACK)
            started = time.monotonic()
            with self.assertRaises(TransportError) as ctx:
                transport(srv.request("/", scheme="https", timeout_s=1.5))
            self.assertEqual(ctx.exception.code, "tls_error")
            self.assertLess(time.monotonic() - started, 3.0)


class StreamTests(RealServerTestCase):
    def test_stream_yields_the_body_and_reports_headers(self):
        with self.transport.stream(self.srv.request("/big")) as stream:
            self.assertEqual((stream.status, stream.declared_length), (200, 5000))
            body = b"".join(stream.iter_chunks())
        self.assertEqual(body, b"a" * 5000)

    def test_stream_enforces_the_limit(self):
        with self.assertRaises(TransportError) as ctx:  # declared length over the limit: refused up front
            self.transport.stream(self.srv.request("/big", max_bytes=1024))
        self.assertEqual(ctx.exception.code, "too_large")
        with self.transport.stream(self.srv.request("/until_close", max_bytes=5)) as stream:
            with self.assertRaises(TransportError) as ctx:  # no Content-Length: caught while reading
                list(stream.iter_chunks())
            self.assertEqual(ctx.exception.code, "too_large")

    def test_stream_refuses_compressed_bodies_and_reports_error_statuses_without_a_body(self):
        with self.assertRaises(TransportError) as ctx:
            self.transport.stream(self.srv.request("/gzip"))
        self.assertEqual(ctx.exception.code, "unsupported_encoding")
        with self.transport.stream(self.srv.request("/missing")) as stream:
            self.assertEqual((stream.status, list(stream.iter_chunks())), (404, []))

    def test_closing_twice_is_harmless(self):
        stream = self.transport.stream(self.srv.request("/page"))
        stream.close()
        stream.close()


if __name__ == "__main__":
    unittest.main()
