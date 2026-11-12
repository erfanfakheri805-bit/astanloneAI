"""Prompt 959 (stage A) - the narrow JSON POST of net_tools: the transport against a REAL loopback server, and `post_json` with fakes.

No traffic leaves the machine. The loopback server answers on 127.0.0.1, so these tests use the test-only policy flags
(`allow_http`, `allow_private_addresses`); the default policy is tested to refuse such a server.
"""
import json
import os
import socket
import socketserver
import sys
import threading
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from net_tools import (FetchPolicy, HttpClientTransport, NETWORK, StaticGate, TransportError, TransportRequest,
                       TransportResponse, error_summary, post_json, scrub)
from net_tools.transport import MAX_ERROR_BODY_BYTES, MAX_POST_BYTES

GATE = StaticGate([NETWORK])
NOGATE = StaticGate([])
LOOPBACK = FetchPolicy(allow_http=True, allow_private_addresses=True, timeout_s=2.0)
KEY = "sk-test-0123456789abcdefghijklmnop"


def reply(status=200, body=b"", ctype="application/json", extra=()):
    head = ["HTTP/1.1 %d X" % status, "Content-Length: %d" % len(body), "Connection: close"]
    if ctype:
        head.append("Content-Type: %s" % ctype)
    head.extend("%s: %s" % kv for kv in extra)
    return ("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + body


class PostServer:
    """Reads one request (head + body) and answers with `answer(head, body)`; keeps everything it saw."""

    def __init__(self, answer):
        self.answer, self.seen = answer, []

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
                    head, _, rest = data.partition(b"\r\n\r\n")
                    text = head.decode("latin-1")
                    length = 0
                    for line in text.split("\r\n")[1:]:
                        if line.lower().startswith("content-length:"):
                            length = int(line.split(":", 1)[1])
                    while len(rest) < length:
                        more = conn.recv(4096)
                        if not more:
                            break
                        rest += more
                    outer.seen.append((text, rest))
                    conn.sendall(outer.answer(text, rest))
                except OSError:
                    pass

        class Srv(socketserver.ThreadingMixIn, socketserver.TCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Srv(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def url(self, path="/v1/chat"):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def request(self, path="/v1/chat", **kw):
        base = dict(method="POST", url=self.url(path), host="127.0.0.1", port=self.port, scheme="http", path_query=path,
                    headers={"Content-Type": "application/json"}, timeout_s=2.0, max_bytes=65536, body=b'{"a":1}')
        base.update(kw)
        return TransportRequest(**base)


class TransportPostTests(unittest.TestCase):
    def setUp(self):
        self.transport = HttpClientTransport(LOOPBACK)

    def test_a_post_sends_the_body_and_only_the_api_headers(self):
        with PostServer(lambda h, b: reply(200, b'{"ok":true}')) as srv:
            headers = {"Content-Type": "application/json", "Authorization": "Bearer " + KEY, "X-Api-Key": "k", "anthropic-version": "2023-06-01"}
            resp = self.transport(srv.request(headers=headers, body='{"msg":"سلام"}'.encode("utf-8")))
        self.assertEqual((resp.status, json.loads(resp.body)), (200, {"ok": True}))
        head, body = srv.seen[0]
        lines = head.split("\r\n")
        self.assertTrue(lines[0].startswith("POST /v1/chat HTTP/1.1"))
        low = [line.lower() for line in lines]
        self.assertIn("content-length: %d" % len('{"msg":"سلام"}'.encode("utf-8")), low)
        self.assertIn("content-type: application/json", low)
        self.assertIn("accept-encoding: identity", low)
        self.assertIn("authorization: bearer " + KEY.lower(), low)
        self.assertFalse(any(line.startswith(("cookie", "referer", "origin")) for line in low))
        self.assertIn("user-agent: standaloneai-localfirst/1.0", low)
        self.assertEqual(json.loads(body.decode("utf-8")), {"msg": "سلام"})

    def test_requests_that_are_not_well_formed_are_refused_before_connecting(self):
        with PostServer(lambda h, b: reply(200, b"{}")) as srv:
            bad = [dict(body=b""), dict(body=b"x" * (MAX_POST_BYTES + 1)), dict(body="text"),
                   dict(headers={"Content-Type": "text/plain"}), dict(headers={}),
                   dict(headers={"Content-Type": "application/json", "Cookie": "a=b"}),
                   dict(headers={"Content-Type": "application/json", "Authorization": "x\r\nHost: evil"}),
                   dict(headers={"Content-Type": "application/json", "Authorization": "x" * 9000}),
                   dict(method="PUT"), dict(method="DELETE")]
            for override in bad:
                with self.subTest(override=override):
                    with self.assertRaises(TransportError) as ctx:
                        self.transport(srv.request(**override))
                    self.assertEqual(ctx.exception.code, "protocol_error")
            with self.assertRaises(TransportError) as ctx:   # a GET may not carry a body nor key headers
                self.transport(srv.request(method="GET", body=b"x"))
            self.assertEqual(ctx.exception.detail, "body_on_get")
            with self.assertRaises(TransportError) as ctx:
                self.transport(srv.request(method="GET", body=b"", headers={"Authorization": "Bearer x"}))
            self.assertEqual(ctx.exception.detail, "bad_request_header")
            self.assertEqual(srv.seen, [], "nothing may have been sent")

    def test_an_error_body_is_read_only_when_asked_and_only_for_a_post(self):
        body = b'{"error":{"message":"Incorrect API key"}}'
        with PostServer(lambda h, b: reply(401, body)) as srv:
            plain = self.transport(srv.request())
            asked = self.transport(srv.request(read_error_body=True))
            got = self.transport(srv.request(method="GET", body=b"", headers={}))
        self.assertEqual((plain.status, plain.body), (401, b""))
        self.assertEqual((asked.status, asked.body), (401, body))
        self.assertEqual((got.status, got.body), (401, b""))

    def test_the_error_body_is_bounded(self):
        with PostServer(lambda h, b: reply(500, b"e" * (MAX_ERROR_BODY_BYTES * 3))) as srv:
            resp = self.transport(srv.request(read_error_body=True))
        self.assertEqual(resp.status, 500)
        self.assertLessEqual(len(resp.body), MAX_ERROR_BODY_BYTES)

    def test_a_redirect_is_returned_as_is_never_followed(self):
        with PostServer(lambda h, b: reply(307, b"", extra=[("Location", "http://127.0.0.1:1/steal")])) as srv:
            resp = self.transport(srv.request(read_error_body=True))
        self.assertEqual(resp.status, 307)
        self.assertEqual(len(srv.seen), 1)

    def test_the_default_policy_refuses_a_loopback_server_for_a_post_too(self):
        with PostServer(lambda h, b: reply(200, b"{}")) as srv:
            with self.assertRaises(TransportError) as ctx:
                HttpClientTransport(FetchPolicy(allow_http=True)).__call__(srv.request())
            self.assertEqual((ctx.exception.code, ctx.exception.detail), ("blocked_address", "loopback"))
            self.assertEqual(srv.seen, [])


class PostJsonTests(unittest.TestCase):
    URL = "https://api.example.com/v1/chat/completions"

    def fake(self, status=200, body=b'{"ok":1}', headers=None, truncated=False, boom=None):
        calls = []

        def transport(request):
            calls.append(request)
            if boom:
                raise boom
            return TransportResponse(status, headers if headers is not None else {"content-type": "application/json"},
                                     body, truncated, "93.184.216.34")
        transport.calls = calls
        return transport

    def post(self, transport, url=URL, payload=None, **kw):
        kw.setdefault("gate", GATE)
        return post_json(url, {"q": "سلام"} if payload is None else payload, transport=transport, **kw)

    def test_success_parses_the_json_and_builds_a_post_request(self):
        t = self.fake(body='{"a":"پاسخ"}'.encode("utf-8"))
        r = self.post(t, headers={"Authorization": "Bearer " + KEY})
        self.assertEqual((r.ok, r.code, r.status, r.host, r.path), (True, "ok", 200, "api.example.com", "/v1/chat/completions"))
        self.assertEqual(r.data, {"a": "پاسخ"})
        req = t.calls[0]
        self.assertEqual((req.method, req.scheme, req.port, req.read_error_body), ("POST", "https", 443, True))
        self.assertEqual(json.loads(req.body.decode("utf-8")), {"q": "سلام"})
        self.assertEqual(req.headers["Content-Type"], "application/json")
        self.assertEqual(req.headers["Authorization"], "Bearer " + KEY)
        self.assertGreaterEqual(req.timeout_s, 30.0)
        self.assertGreaterEqual(req.total_timeout_s, 60.0)
        self.assertNotIn(KEY, json.dumps(r.to_dict(), ensure_ascii=False), "the result must never hold a key")
        self.assertNotIn("data", r.to_dict())

    def test_without_the_network_permission_the_transport_is_never_called(self):
        t = self.fake()
        for gate in (NOGATE, None, object()):
            r = self.post(t, gate=gate)
            self.assertEqual((r.ok, r.code), (False, "permission_denied"))
        self.assertEqual(t.calls, [])

    def test_the_address_rules_are_the_same_as_for_a_page(self):
        t = self.fake()
        for url, code in (("http://api.example.com/x", "unsupported_scheme"), ("https://127.0.0.1/x", "blocked_address"),
                          ("https://localhost/x", "blocked_address"), ("https://192.168.1.5/x", "blocked_address"),
                          ("https://user:pw@api.example.com/x", "invalid_url"), ("not a url", "invalid_url"), (None, "invalid_url")):
            with self.subTest(url=url):
                r = self.post(t, url=url)
                self.assertEqual((r.ok, r.code), (False, code))
        self.assertEqual(t.calls, [])

    def test_a_redirect_is_an_error_and_is_not_followed(self):
        t = self.fake(status=302, body=b"", headers={"location": "https://evil.example/"})
        r = self.post(t)
        self.assertEqual((r.ok, r.code, r.status, r.detail), (False, "http_error", 302, "redirect"))
        self.assertEqual(len(t.calls), 1)
        self.assertNotIn("evil", json.dumps(r.to_dict()))

    def test_an_error_status_keeps_a_short_scrubbed_reason(self):
        body = json.dumps({"error": {"message": "Incorrect API key provided: %s. See docs." % KEY}}).encode()
        r = self.post(self.fake(status=401, body=body), secrets=[KEY])
        self.assertEqual((r.ok, r.code, r.status), (False, "http_error", 401))
        self.assertIn("Incorrect API key", r.error_text)
        self.assertNotIn(KEY, r.error_text)
        self.assertNotIn(KEY[:8], r.error_text)
        self.assertIn("[key]", r.error_text)
        self.assertNotIn(KEY, json.dumps(r.to_dict(), ensure_ascii=False))

    def test_a_long_key_like_string_is_scrubbed_even_when_not_named(self):
        body = json.dumps({"error": {"message": "bad key AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q"}}).encode()
        r = self.post(self.fake(status=403, body=body))
        self.assertNotIn("AIzaSy", r.error_text)

    def test_error_summary_understands_the_common_shapes(self):
        cases = [('{"error":{"message":"m1"}}', "m1"), ('{"error":"m2"}', "m2"), ('[{"error":{"message":"m3"}}]', "m3"),
                 ('{"message":"m4"}', "m4"), ('{"error":{"status":"RESOURCE_EXHAUSTED"}}', "RESOURCE_EXHAUSTED"),
                 ("plain text oops", "plain text oops"), ("", ""), ("{broken", "{broken")]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(error_summary(raw), want)
        self.assertEqual(len(error_summary(json.dumps({"error": {"message": "word " * 1000}}))), 400)
        self.assertEqual(scrub("a\x00b\x07c"), "a b c")

    def test_the_answer_must_be_json_of_a_sensible_size(self):
        cases = [(dict(headers={"content-type": "text/html"}), "unsupported_content_type"),
                 (dict(headers={}), "unsupported_content_type"),
                 (dict(body=b"{not json"), "bad_json"), (dict(body=b"5"), "bad_json"), (dict(body=b'"s"'), "bad_json"),
                 (dict(body=b"[" * 100000), "bad_json"), (dict(truncated=True), "too_large")]
        for kw, code in cases:
            with self.subTest(kw=kw):
                r = self.post(self.fake(**kw))
                self.assertEqual((r.ok, r.code), (False, code))
        ok = self.post(self.fake(headers={"content-type": "application/vnd.api+json; charset=utf-8"}, body=b'[1,2]'))
        self.assertEqual((ok.ok, ok.data), (True, [1, 2]))

    def test_a_request_that_cannot_be_serialised_or_is_too_big_is_refused_without_calling(self):
        t = self.fake()
        self.assertEqual(self.post(t, payload={"x": object()}).code, "bad_json")
        self.assertEqual(self.post(t, payload={"x": "y" * (MAX_POST_BYTES + 10)}).code, "request_too_large")
        self.assertEqual(self.post(t, payload={"x": float("nan")}).code, "bad_json")   # NaN is not JSON
        self.assertEqual(t.calls, [])

    def test_transport_errors_map_to_stable_codes_and_unknown_errors_leak_nothing(self):
        for code in ("timeout", "tls_error", "offline", "dns_failure", "connect_refused", "too_large", "blocked_address"):
            with self.subTest(code=code):
                r = self.post(self.fake(boom=TransportError(code, "x")))
                self.assertEqual((r.ok, r.code), (False, code))
        r = self.post(self.fake(boom=TransportError("weird_code")))
        self.assertEqual(r.code, "unknown_error")
        r = self.post(self.fake(boom=RuntimeError("Authorization: Bearer " + KEY)), headers={"Authorization": "Bearer " + KEY})
        self.assertEqual((r.ok, r.code, r.detail), (False, "unknown_error", "RuntimeError"))
        self.assertNotIn(KEY, json.dumps(r.to_dict(), ensure_ascii=False))
        self.assertNotIn(KEY, r.message_fa + r.message_en)

    def test_http_error_message_names_the_status(self):
        r = self.post(self.fake(status=429, body=b""))
        self.assertIn("۴۲۹", r.message_fa)
        self.assertIn("429", r.message_en)


class EndToEndOverLoopbackTests(unittest.TestCase):
    def test_post_json_through_the_real_transport(self):
        def answer(head, body):
            ok = json.loads(body.decode("utf-8")) == {"model": "m", "messages": [{"role": "user", "content": "سلام"}]}
            return reply(200, json.dumps({"ok": ok}).encode())
        with PostServer(answer) as srv:
            r = post_json(srv.url(), {"model": "m", "messages": [{"role": "user", "content": "سلام"}]}, headers={"Authorization": "Bearer " + KEY},
                          gate=GATE, policy=LOOPBACK, secrets=[KEY])
        self.assertEqual((r.ok, r.data), (True, {"ok": True}))

    def test_a_bad_key_answer_through_the_real_transport(self):
        with PostServer(lambda h, b: reply(401, json.dumps({"error": {"message": "bad key " + KEY}}).encode())) as srv:
            r = post_json(srv.url(), {"a": 1}, headers={"Authorization": "Bearer " + KEY}, gate=GATE, policy=LOOPBACK, secrets=[KEY])
        self.assertEqual((r.ok, r.status), (False, 401))
        self.assertNotIn(KEY, r.error_text)

    def test_a_silent_server_times_out_inside_the_deadline(self):
        import time

        def silent(head, body):
            time.sleep(3)
            return b""
        with PostServer(silent) as srv:
            started = time.monotonic()
            r = post_json(srv.url(), {"a": 1}, gate=GATE, policy=LOOPBACK, timeout_s=0.3, total_timeout_s=0.6)
        self.assertEqual((r.ok, r.code), (False, "timeout"))
        self.assertLess(time.monotonic() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
