"""Prompt 957 - net_tools: fetch_text and redirects (network fully MOCKED by fake transports)."""
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from net_tools import FetchPolicy, FetchResult, NETWORK, StaticGate, TransportError, TransportResponse, fetch_text

GATE = StaticGate([NETWORK])
PERSIAN_PAGE = "<html><head><title>خبر امروز</title></head><body><h1>سلام</h1><p>این یک آزمایش است.</p></body></html>"


def reply(status=200, body=b"", ctype="text/html; charset=utf-8", headers=None, truncated=False):
    h = {} if ctype is None else {"content-type": ctype}
    h.update(headers or {})
    return TransportResponse(status, h, body, truncated, "93.184.216.34")


def page(text=PERSIAN_PAGE, **kw):
    return reply(body=text.encode("utf-8"), **kw)


class FakeTransport:
    """Callable transport: replays `items` in order (the last one repeats); an exception item is raised."""

    def __init__(self, *items):
        self.items, self.requests = list(items), []

    def __call__(self, request):
        self.requests.append(request)
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, BaseException):
            raise item
        return item


class RaisingGate:
    def allowed(self, permission):
        raise RuntimeError("gate exploded")


class PermissionFirstTests(unittest.TestCase):
    def test_no_permission_means_the_transport_is_never_called(self):
        for gate in (StaticGate(), StaticGate(["microphone"]), RaisingGate(), None, object()):
            with self.subTest(gate=type(gate).__name__):
                t = FakeTransport(page())
                r = fetch_text("https://example.com/", gate=gate, transport=t)
                self.assertEqual((r.ok, r.code), (False, "permission_denied"))
                self.assertEqual(len(t.requests), 0)
                self.assertIn("اجازه", r.message_fa)
                self.assertTrue(r.message_en)

    def test_invalid_urls_never_reach_the_transport(self):
        t = FakeTransport(page())
        for url in ("javascript:alert(1)", "https://user:pw@example.com/", "http://example.com/", "https://127.0.0.1/",
                    "https://localhost/", "not a url", "", None, 12):
            with self.subTest(url=url):
                r = fetch_text(url, gate=GATE, transport=t)
                self.assertFalse(r.ok)
                self.assertIn(r.code, ("invalid_url", "unsupported_scheme", "blocked_address"))
        self.assertEqual(len(t.requests), 0)

    def test_url_is_validated_before_permission(self):
        r = fetch_text("javascript:1", gate=StaticGate(), transport=FakeTransport(page()))
        self.assertEqual(r.code, "unsupported_scheme")


class SuccessTests(unittest.TestCase):
    def test_html_page_becomes_text_and_request_is_built_from_the_policy(self):
        t = FakeTransport(page())
        policy = FetchPolicy(timeout_s=3.0, max_bytes=5000, oversize="truncate")
        r = fetch_text("https://Example.com:8443/a/b?x=1#frag", gate=GATE, policy=policy, transport=t)
        self.assertTrue(r.ok, r)
        self.assertEqual((r.code, r.status, r.title), ("ok", 200, "خبر امروز"))
        self.assertEqual(r.text, "سلام\n\nاین یک آزمایش است.")
        self.assertEqual(r.final_url, "https://example.com:8443/a/b?x=1")
        self.assertEqual((r.redirects, r.truncated), (0, False))
        self.assertEqual(r.bytes_read, len(PERSIAN_PAGE.encode("utf-8")))
        self.assertEqual(r.message_fa, "صفحه خوانده شد.")
        (req,) = t.requests
        self.assertEqual((req.method, req.host, req.port, req.scheme, req.path_query),
                         ("GET", "example.com", 8443, "https", "/a/b?x=1"))
        self.assertEqual((req.timeout_s, req.max_bytes, req.oversize), (3.0, 5000, "truncate"))

    def test_other_allowed_types_are_returned_as_text(self):
        for ctype, body in (("application/json", b'{"a": [1, 2]}'), ("text/plain; charset=utf-8", b"line1\r\nline2"),
                            ("text/csv", b"a,b\n1,2"), ("text/markdown", b"# t"), ("application/xml", b"<a/>"),
                            ("text/xml; charset=utf-8", b"<a>x</a>")):
            with self.subTest(ctype=ctype):
                r = fetch_text("https://example.com/f", gate=GATE, transport=FakeTransport(reply(body=body, ctype=ctype)))
                self.assertTrue(r.ok, r)
                self.assertEqual(r.text, body.decode().replace("\r\n", "\n"))
                self.assertEqual(r.title, "")

    def test_result_is_a_plain_serialisable_object(self):
        r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(page()))
        self.assertIsInstance(r, FetchResult)
        d = r.to_dict()
        self.assertEqual(d["code"], "ok")
        self.assertEqual(set(d), {"ok", "code", "status", "url", "final_url", "content_type", "title", "text", "truncated",
                                  "bytes_read", "redirects", "elapsed_s", "message_fa", "message_en", "detail"})

    def test_elapsed_time_uses_the_injected_clock(self):
        ticks = iter([10.0, 12.5, 12.5, 12.5, 12.5])
        r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(page()), clock=lambda: next(ticks))
        self.assertEqual(r.elapsed_s, 2.5)


class FailureMappingTests(unittest.TestCase):
    def test_every_transport_error_maps_to_a_clear_code_and_message(self):
        for code in ("dns_failure", "offline", "connect_refused", "timeout", "tls_error", "blocked_address", "too_large",
                     "protocol_error", "unsupported_encoding"):
            with self.subTest(code=code):
                r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(TransportError(code, "d")))
                self.assertEqual((r.ok, r.code, r.detail), (False, code, "d"))
                self.assertTrue(r.message_fa and r.message_en)
                self.assertEqual((r.text, r.title, r.status), ("", "", None))

    def test_spec_messages(self):
        def msg(code):
            return fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(TransportError(code))).message_fa
        self.assertEqual(msg("timeout"), "پاسخی در زمان مجاز نرسید.")
        self.assertEqual(msg("too_large"), "پاسخ از حد مجاز بزرگ‌تر بود.")
        self.assertEqual(msg("offline"), "اینترنت در دسترس نیست یا نام سایت پیدا نشد.")
        self.assertEqual(msg("dns_failure"), msg("offline"))

    def test_unknown_transport_code_and_stray_exceptions_become_unknown_error_without_leaking(self):
        r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(TransportError("weird_code", "x")))
        self.assertEqual(r.code, "unknown_error")
        r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(RuntimeError("password=hunter2")))
        self.assertEqual((r.ok, r.code, r.detail), (False, "unknown_error", "RuntimeError"))
        self.assertNotIn("hunter2", repr(r.to_dict()))

    def test_http_error_statuses(self):
        for status in (400, 403, 404, 429, 500, 503, 304):
            with self.subTest(status=status):
                r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(reply(status, b"<html>err</html>")))
                self.assertEqual((r.ok, r.code, r.status), (False, "http_error", status))
                self.assertEqual(r.text, "")
        r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(reply(404)))
        self.assertIn("۴۰۴", r.message_fa)


class ContentTypeAndCharsetTests(unittest.TestCase):
    def test_disallowed_and_missing_content_types_are_refused(self):
        for ctype in ("application/octet-stream", "image/png", "application/pdf", "application/zip", "video/mp4", "", None,
                      "text/html-but-not", "application/x-msdownload"):
            with self.subTest(ctype=ctype):
                r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(reply(body=b"data", ctype=ctype)))
                self.assertEqual((r.ok, r.code), (False, "unsupported_content_type"))
                self.assertEqual(r.text, "")

    def test_content_type_matching_ignores_case_parameters_and_spaces(self):
        r = fetch_text("https://example.com/", gate=GATE,
                       transport=FakeTransport(reply(body=b"hi", ctype="  Text/PLAIN ; Charset=UTF-8 ")))
        self.assertTrue(r.ok, r)

    def test_policy_can_narrow_the_allowlist(self):
        policy = FetchPolicy(allowed_content_types=("application/json",))
        r = fetch_text("https://example.com/", gate=GATE, policy=policy, transport=FakeTransport(page()))
        self.assertEqual(r.code, "unsupported_content_type")

    def test_utf8_and_windows_1256_persian_pages(self):
        text = "سلام دنيا، اين يك آزمايش است"
        html = "<html><body><p>%s</p></body></html>" % text
        r = fetch_text("https://example.com/", gate=GATE,
                       transport=FakeTransport(reply(body=html.encode("cp1256"), ctype="text/html; charset=windows-1256")))
        self.assertEqual(r.text, text)
        r = fetch_text("https://example.com/", gate=GATE,
                       transport=FakeTransport(reply(body=html.encode("utf-8"), ctype="text/html; charset=utf-8")))
        self.assertEqual(r.text, text)
        r = fetch_text("https://example.com/", gate=GATE,
                       transport=FakeTransport(reply(body=html.encode("utf-8"), ctype="text/html; charset=bogus-9")))
        self.assertEqual(r.text, text)
        meta = ('<html><head><meta charset="windows-1256"></head><body><p>%s</p></body></html>' % text).encode("cp1256")
        r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(reply(body=meta, ctype="text/html")))
        self.assertEqual(r.text, text)


class SizeTests(unittest.TestCase):
    def test_transport_truncation_is_reported(self):
        r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(page(truncated=True)))
        self.assertTrue(r.ok)
        self.assertTrue(r.truncated)

    def test_text_is_capped_to_max_text_chars(self):
        body = ("<p>" + "ا" * 5000 + "</p>").encode("utf-8")
        r = fetch_text("https://example.com/", gate=GATE, policy=FetchPolicy(max_text_chars=1000),
                       transport=FakeTransport(reply(body=body)))
        self.assertEqual((r.ok, r.truncated, len(r.text)), (True, True, 1000))
        r = fetch_text("https://example.com/", gate=GATE, policy=FetchPolicy(max_text_chars=1000),
                       transport=FakeTransport(reply(body=b"x" * 5000, ctype="text/plain")))
        self.assertEqual((r.truncated, len(r.text)), (True, 1000))

    def test_too_large_from_the_transport_is_reported_as_such(self):
        r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(TransportError("too_large", "body")))
        self.assertEqual(r.code, "too_large")


class RedirectTests(unittest.TestCase):
    def redirect(self, location, status=302):
        return reply(status, b"", None, {"location": location})

    def test_relative_absolute_and_protocol_relative_redirects_are_followed(self):
        for location, expected in (("/next", "https://example.com/next"), ("https://other.example/p", "https://other.example/p"),
                                   ("//cdn.example/x", "https://cdn.example/x"), ("rel", "https://example.com/dir/rel")):
            with self.subTest(location=location):
                t = FakeTransport(self.redirect(location), page())
                r = fetch_text("https://example.com/dir/start", gate=GATE, transport=t)
                self.assertTrue(r.ok, r)
                self.assertEqual((r.redirects, r.final_url, len(t.requests)), (1, expected, 2))
                self.assertEqual(t.requests[1].url, expected)

    def test_every_redirect_status_is_followed(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(self.redirect("/n", status), page()))
                self.assertTrue(r.ok)

    def test_redirect_limit(self):
        loop = FakeTransport(self.redirect("/again"))
        r = fetch_text("https://example.com/", gate=GATE, policy=FetchPolicy(max_redirects=3), transport=loop)
        self.assertEqual((r.ok, r.code), (False, "too_many_redirects"))
        self.assertEqual(len(loop.requests), 4)  # first request + 3 followed redirects
        none = FakeTransport(self.redirect("/n"), page())
        r = fetch_text("https://example.com/", gate=GATE, policy=FetchPolicy(max_redirects=0), transport=none)
        self.assertEqual(r.code, "too_many_redirects")
        self.assertEqual(len(none.requests), 1)

    def test_https_to_http_downgrade_is_refused(self):
        t = FakeTransport(self.redirect("http://example.com/plain"), page())
        r = fetch_text("https://example.com/", gate=GATE, policy=FetchPolicy(allow_http=True), transport=t)
        self.assertEqual((r.ok, r.code, r.detail), (False, "unsupported_scheme", "https_to_http_downgrade"))
        self.assertEqual(len(t.requests), 1)
        # without allow_http the plain-http target is refused too (by the URL rules)
        r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(self.redirect("http://example.com/p"), page()))
        self.assertEqual(r.code, "unsupported_scheme")

    def test_redirect_into_a_private_or_internal_address_is_refused(self):
        for target in ("https://127.0.0.1/admin", "https://10.0.0.5/", "https://[::1]/", "https://169.254.169.254/latest/meta-data",
                       "https://localhost/", "https://2130706433/", "https://invoker.local/", "https://[::ffff:192.168.0.1]/"):
            with self.subTest(target=target):
                t = FakeTransport(self.redirect(target), page())
                r = fetch_text("https://example.com/", gate=GATE, transport=t)
                self.assertEqual((r.ok, r.code), (False, "blocked_address"))
                self.assertEqual(len(t.requests), 1)  # the private target was never contacted

    def test_redirect_to_other_schemes_or_garbage_is_refused(self):
        for target, code in (("javascript:alert(1)", "unsupported_scheme"), ("file:///etc/passwd", "unsupported_scheme"),
                             ("ftp://example.com/x", "unsupported_scheme"), ("https://user:pw@example.com/", "invalid_url"),
                             ("https://exa mple.com/", "invalid_url"), ("/" + "a" * 4000, "invalid_url")):
            with self.subTest(target=target[:40]):
                r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(self.redirect(target), page()))
                self.assertEqual((r.ok, r.code), (False, code))

    def test_redirect_without_location_is_an_http_error(self):
        r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(reply(302, b"", None)))
        self.assertEqual((r.ok, r.code, r.status), (False, "http_error", 302))

    def test_304_and_300_are_not_followed(self):
        for status in (300, 304):
            r = fetch_text("https://example.com/", gate=GATE, transport=FakeTransport(reply(status, b"", None, {"location": "/x"})))
            self.assertEqual((r.code, r.status), ("http_error", status))


if __name__ == "__main__":
    unittest.main()
