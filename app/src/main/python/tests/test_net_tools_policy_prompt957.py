"""Prompt 957 - net_tools: URL validation, address classification, policy, HTML text, charsets, status, gates.

Pure logic only: no sockets, no DNS, no files.
"""
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from net_tools import (CallableGate, FetchPolicy, NETWORK, StaticGate, classify_ip, decode_body, html_to_text,
                       network_status, parse_url)
from net_tools.policy import ParsedUrl, UrlError, is_public_ip
from net_tools.redirects import resolve_location

HTTP_OK = FetchPolicy(allow_http=True)

# (url, expected_code, expected_detail_or_None); "ok" means a ParsedUrl comes back
URL_CASES = [
    ("https://example.com", "ok", None),
    ("https://example.com/path/to?x=1&y=2", "ok", None),
    ("https://EXAMPLE.com./Path", "ok", None),
    ("https://example.com:8443/x#fragment", "ok", None),
    ("https://مثال.ایران/صفحه?q=سلام", "ok", None),
    ("https://8.8.8.8/dns", "ok", None),
    ("https://[2606:4700::1111]:444/x", "ok", None),
    ("https://sub.domain.example.org/a/b/c.html", "ok", None),
    ("https://example.com/%D8%B3", "ok", None),
    ("javascript:alert(1)", "unsupported_scheme", "javascript"),
    ("file:///etc/passwd", "unsupported_scheme", "file"),
    ("ftp://example.com/x", "unsupported_scheme", "ftp"),
    ("data:text/html,<b>x</b>", "unsupported_scheme", "data"),
    ("https://user:secret@example.com/", "invalid_url", "userinfo_not_allowed"),
    ("https://example.com@evil.example/", "invalid_url", "userinfo_not_allowed"),
    ("https://exa mple.com/", "invalid_url", "forbidden_character"),
    ("https://example.com/\nHost: evil", "invalid_url", "forbidden_character"),
    ("https://example.com/\r\n", "invalid_url", "forbidden_character"),
    ("https://example.com/a\x00b", "invalid_url", "forbidden_character"),
    ("https://example.com\\@evil.example/", "invalid_url", "forbidden_character"),
    ("https://example.com/\u202eevil", "invalid_url", "forbidden_character"),
    ("https://example.com/ x", "invalid_url", "forbidden_character"),
    ("https://example.com/" + "a" * 3000, "invalid_url", "too_long"),
    ("", "invalid_url", "empty_or_not_text"),
    ("example.com", "invalid_url", "no_scheme"),
    ("https:example.com", "invalid_url", "missing_authority"),
    ("https:///x", "invalid_url", "empty_host"),
    ("https://example.com:0/", "invalid_url", "bad_port"),
    ("https://example.com:65536/", "invalid_url", "bad_port"),
    ("https://example.com:80a/", "invalid_url", "bad_port"),
    ("https://example.com/%zz", "invalid_url", "bad_percent_escape"),
    ("https://-bad.example.com/", "invalid_url", "bad_host_name"),
    ("https://exa_mple.com/", "invalid_url", "bad_host_name"),
    ("https://1.2.3.4.5/", "invalid_url", "bad_numeric_host"),
    ("https://256.1.1.1/", "invalid_url", "bad_numeric_host"),
    ("https://[::1%25eth0]/", "invalid_url", "ipv6_zone_not_allowed"),
    ("https://[::1/", "invalid_url", "bad_ipv6_literal"),
    ("http://127.0.0.1", "blocked_address", "loopback"),
    ("http://127.0.0.1:8080/admin", "blocked_address", "loopback"),
    ("http://169.254.169.254/latest/meta-data", "blocked_address", "metadata"),
    ("http://[::1]/", "blocked_address", "loopback"),
    ("http://0x7f.1", "blocked_address", "loopback"),
    ("http://2130706433", "blocked_address", "loopback"),
    ("http://0177.0.0.1/", "blocked_address", "loopback"),
    ("http://127.1/", "blocked_address", "loopback"),
    ("http://localhost", "blocked_address", "localhost"),
    ("http://LOCALHOST:3000/", "blocked_address", "localhost"),
    ("http://api.localhost/", "blocked_address", "localhost"),
    ("http://[::ffff:10.0.0.1]", "blocked_address", "private"),
    ("http://[::ffff:7f00:1]/", "blocked_address", "loopback"),
    ("http://192.168.1.1/", "blocked_address", "private"),
    ("http://10.1.2.3/", "blocked_address", "private"),
    ("http://172.16.0.9/", "blocked_address", "private"),
    ("http://100.64.0.1/", "blocked_address", "carrier_grade_nat"),
    ("http://0.0.0.0/", "blocked_address", "unspecified"),
    ("http://224.0.0.1/", "blocked_address", "multicast"),
    ("http://[fe80::1]/", "blocked_address", "link_local"),
    ("http://[fd00:ec2::254]/", "blocked_address", "metadata"),
    ("http://printer/", "blocked_address", "single_label_host"),
    ("http://invoker.local/", "blocked_address", "internal_name"),
    ("http://db.internal/", "blocked_address", "internal_name"),
    ("http://metadata.google.internal/", "blocked_address", "internal_name"),
]

IP_CASES = [
    ("8.8.8.8", "public"), ("1.1.1.1", "public"), ("93.184.216.34", "public"), ("2606:4700::1111", "public"),
    ("127.0.0.1", "loopback"), ("127.255.255.254", "loopback"), ("::1", "loopback"),
    ("10.0.0.1", "private"), ("172.16.5.5", "private"), ("172.31.255.255", "private"), ("192.168.0.1", "private"),
    ("fc00::1", "private"), ("fd12:3456::1", "private"),
    ("169.254.1.1", "link_local"), ("fe80::1", "link_local"), ("fe80::1%eth0", "link_local"),
    ("169.254.169.254", "metadata"), ("fd00:ec2::254", "metadata"),
    ("224.0.0.1", "multicast"), ("ff02::1", "multicast"),
    ("0.0.0.0", "unspecified"), ("::", "unspecified"),
    ("100.64.0.1", "carrier_grade_nat"), ("100.127.255.255", "carrier_grade_nat"), ("100.100.100.200", "carrier_grade_nat"),
    ("240.0.0.1", "reserved"), ("255.255.255.255", "reserved"),
    ("::ffff:127.0.0.1", "loopback"), ("::ffff:10.1.1.1", "private"), ("::ffff:169.254.169.254", "metadata"),
    ("::ffff:8.8.8.8", "public"),
    ("2002:7f00:0001::", "loopback"), ("2002:0a00:0001::", "private"), ("2002:0808:0808::", "public"),
    ("64:ff9b::7f00:1", "loopback"), ("64:ff9b::a00:1", "private"), ("64:ff9b::808:808", "public"),
    ("2001:0:4136:e378:8000:63bf:3fff:fdd2", "private"),   # Teredo whose client address is TEST-NET
    ("2001:0:808:808:0:0:fefd:fcfb", "reserved"),         # Teredo, both embedded addresses public -> never a normal host
    ("2001:0:808:808:0:0:80ff:fffe", "loopback"),         # Teredo carrying 127.0.0.1
    ("2001:db8::1", "private"),
    ("not-an-ip", "invalid"), ("", "invalid"), ("999.1.1.1", "invalid"),
]


class UrlValidationTests(unittest.TestCase):
    def test_table_has_enough_cases(self):
        self.assertGreaterEqual(len(URL_CASES), 30)

    def test_url_table(self):
        for url, code, detail in URL_CASES:
            with self.subTest(url=url[:70]):
                result = parse_url(url, HTTP_OK)
                if code == "ok":
                    self.assertIsInstance(result, ParsedUrl, result)
                else:
                    self.assertIsInstance(result, UrlError, "%r was accepted" % url)
                    self.assertEqual(result.code, code)
                    if detail:
                        self.assertEqual(result.detail, detail)

    def test_default_policy_refuses_plain_http_even_to_public_hosts(self):
        err = parse_url("http://example.com/")
        self.assertEqual((err.code, err.detail), ("unsupported_scheme", "plain_http_not_allowed"))
        self.assertIsInstance(parse_url("http://example.com/", HTTP_OK), ParsedUrl)

    def test_private_addresses_pass_only_with_the_test_only_flag(self):
        lax = FetchPolicy(allow_http=True, allow_private_addresses=True)
        for url in ("http://127.0.0.1:9/", "http://localhost:9/", "http://[::1]:9/", "http://10.0.0.1/"):
            with self.subTest(url=url):
                self.assertIsInstance(parse_url(url, lax), ParsedUrl)
                self.assertEqual(parse_url(url, HTTP_OK).code, "blocked_address")

    def test_non_string_input_is_an_error_not_an_exception(self):
        for value in (None, 5, b"https://example.com", ["https://example.com"]):
            with self.subTest(value=value):
                self.assertEqual(parse_url(value).code, "invalid_url")

    def test_normalisation(self):
        p = parse_url("HTTPS://Example.COM:443/A?b=1#frag")
        self.assertEqual((p.scheme, p.host, p.port, p.path_query), ("https", "example.com", 443, "/A?b=1"))
        self.assertEqual(p.url, "https://example.com/A?b=1")  # default port and fragment dropped
        self.assertEqual(parse_url("https://example.com:8443").url, "https://example.com:8443/")
        self.assertEqual(parse_url("https://example.com?q=1").path_query, "/?q=1")
        self.assertEqual(parse_url("https://[2606:4700::1111]:444/x").authority, "[2606:4700::1111]:444")

    def test_persian_host_is_punycode_and_persian_query_is_percent_encoded(self):
        p = parse_url("https://مثال.ایران/صفحه?q=سلام")
        self.assertTrue(p.host.isascii() and p.host.startswith("xn--"))
        self.assertTrue(p.path_query.isascii())
        self.assertIn("%D8%B5%D9%81%D8%AD%D9%87", p.path_query)

    def test_numeric_hosts_are_never_treated_as_names(self):
        self.assertEqual(parse_url("http://2130706433/", HTTP_OK).detail, "loopback")
        self.assertEqual(parse_url("http://3232235777/", HTTP_OK).detail, "private")   # 192.168.1.1
        ok = parse_url("http://134744072/", HTTP_OK)                                    # 8.8.8.8
        self.assertIsInstance(ok, ParsedUrl)
        self.assertEqual(ok.host, "8.8.8.8")

    def test_length_limit_follows_the_policy(self):
        short = FetchPolicy(max_url_length=64)
        self.assertEqual(parse_url("https://example.com/" + "a" * 60, short).detail, "too_long")
        self.assertIsInstance(parse_url("https://example.com/" + "a" * 20, short), ParsedUrl)


class ClassifyIpTests(unittest.TestCase):
    def test_table(self):
        for ip, expected in IP_CASES:
            with self.subTest(ip=ip):
                self.assertEqual(classify_ip(ip), expected)

    def test_is_public_helper_and_ip_objects(self):
        import ipaddress
        self.assertTrue(is_public_ip("8.8.8.8"))
        self.assertFalse(is_public_ip("10.0.0.1"))
        self.assertEqual(classify_ip(ipaddress.ip_address("127.0.0.1")), "loopback")


class PolicyTests(unittest.TestCase):
    def test_defaults_match_the_spec(self):
        p = FetchPolicy()
        self.assertEqual((p.timeout_s, p.max_bytes, p.max_redirects), (8.0, 262144, 3))
        self.assertFalse(p.allow_http)
        self.assertFalse(p.allow_private_addresses)
        self.assertEqual(p.oversize, "reject")
        self.assertEqual((p.max_url_length, p.max_text_chars), (2048, 100000))
        self.assertIn("text/html", p.allowed_content_types)
        self.assertNotIn("application/octet-stream", p.allowed_content_types)

    def test_numbers_are_clamped(self):
        p = FetchPolicy(timeout_s=999, max_bytes=1, max_redirects=99)
        self.assertEqual((p.timeout_s, p.max_bytes, p.max_redirects), (30.0, 1024, 5))
        q = FetchPolicy(timeout_s=0.0, max_bytes=10 ** 12, max_redirects=-4)
        self.assertEqual((q.timeout_s, q.max_bytes, q.max_redirects), (0.5, 8 * 2 ** 20, 0))

    def test_wrong_types_raise_value_error(self):
        for kwargs in ({"timeout_s": "5"}, {"max_bytes": 1.5}, {"max_redirects": True}, {"allow_http": 1},
                       {"allow_private_addresses": "yes"}, {"oversize": "explode"}, {"user_agent": "bad\r\nagent"},
                       {"user_agent": ""}, {"allowed_content_types": "text/html"}, {"allowed_content_types": ("nonsense",)},
                       {"timeout_s": float("nan")}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    FetchPolicy(**kwargs)

    def test_policy_is_immutable_and_with_timeout_copies(self):
        p = FetchPolicy()
        with self.assertRaises(Exception):
            p.timeout_s = 1.0  # type: ignore[misc]
        q = p.with_timeout(2.0)
        self.assertEqual((q.timeout_s, p.timeout_s), (2.0, 8.0))
        self.assertEqual(q.max_bytes, p.max_bytes)

    def test_content_types_are_normalised(self):
        p = FetchPolicy(allowed_content_types=(" Text/HTML ", "text/html", "application/json"))
        self.assertEqual(p.allowed_content_types, ("text/html", "application/json"))


class RedirectLocationTests(unittest.TestCase):
    base = parse_url("https://example.com/a/b/c?x=1")

    def test_resolution_forms(self):
        cases = {
            "https://other.example/z": "https://other.example/z",
            "//cdn.example/lib.js": "https://cdn.example/lib.js",
            "/root": "https://example.com/root",
            "sibling": "https://example.com/a/b/sibling",
            "../up": "https://example.com/a/up",
            "../../../../way/up": "https://example.com/way/up",
            "./same?q=2": "https://example.com/a/b/same?q=2",
            "?only=query": "https://example.com/a/b/c?only=query",
            "javascript:alert(1)": "javascript:alert(1)",
        }
        for location, expected in cases.items():
            with self.subTest(location=location):
                self.assertEqual(resolve_location(self.base, location), expected)

    def test_empty_or_oversized_location_is_empty(self):
        self.assertEqual(resolve_location(self.base, "   "), "")
        self.assertEqual(resolve_location(self.base, "/" + "a" * 5000), "")

    def test_utf8_location_header_read_as_latin1_is_repaired(self):
        raw = "/صفحه".encode("utf-8").decode("latin-1")
        self.assertEqual(resolve_location(self.base, raw), "https://example.com/صفحه")


class HtmlToTextTests(unittest.TestCase):
    def test_scripts_styles_and_head_are_dropped_title_is_kept(self):
        html = ("<html><head><title> سلام  دنیا </title><style>p{color:red}</style><meta charset=utf-8></head>"
                "<body><script>var secret=1;</script><h1>عنوان</h1><p>متن &amp; بیشتر</p><noscript>no js</noscript>"
                "<svg><title>icon</title><text>vector</text></svg><template><p>hidden</p></template></body></html>")
        title, text = html_to_text(html, 1000)
        self.assertEqual(title, "سلام دنیا")
        self.assertEqual(text, "عنوان\n\nمتن & بیشتر")
        for leaked in ("secret", "color:red", "no js", "icon", "vector", "hidden"):
            self.assertNotIn(leaked, text)

    def test_block_tags_make_lines_and_whitespace_collapses(self):
        _t, text = html_to_text("<div>a</div><div>b   \t c</div><p>d<br>e</p><ul><li>x</li><li>y</li></ul>", 1000)
        self.assertEqual(text.split("\n")[0], "a")
        self.assertIn("b c", text)
        self.assertIn("d\ne", text)
        self.assertNotIn("   ", text)
        self.assertNotIn("\n\n\n", text)

    def test_entities_and_numeric_references(self):
        _t, text = html_to_text("<p>&lt;b&gt; &quot;q&quot; &#1587;&#x644;&#1575;&#1605; &copy;</p>", 1000)
        self.assertEqual(text, '<b> "q" سلام ©')

    def test_broken_markup_does_not_raise_and_unclosed_head_does_not_swallow_the_body(self):
        for broken in ("<p>unclosed <b>bold <i>italic", "<div><<<>>> text </div", "<a href='x>link</a>", "</p></p></div>text",
                       "<!-- never closed comment <p>x", "<![CDATA[ weird", "<?php echo 1 ?>after", "\x00<p>nul</p>"):
            with self.subTest(markup=broken):
                title, text = html_to_text(broken, 1000)
                self.assertIsInstance(text, str)
                self.assertNotIn("\x00", text)
        _t, text = html_to_text("<html><head><title>T</title><body><p>بدنه</p></body>", 1000)
        self.assertEqual(text, "بدنه")

    def test_unclosed_script_hides_everything_after_it(self):
        _t, text = html_to_text("<p>before</p><script>alert(1); <p>after</p>", 1000)
        self.assertEqual(text, "before")

    def test_output_is_bounded(self):
        _t, text = html_to_text("<p>" + "کلمه " * 50000 + "</p>", 500)
        self.assertLessEqual(len(text), 500)
        self.assertGreater(len(text), 100)
        title, _ = html_to_text("<title>" + "x" * 5000 + "</title>", 100)
        self.assertLessEqual(len(title), 300)

    def test_persian_text_and_zwnj_are_preserved(self):
        sample = "می‌خواهم کتاب‌ها را بخوانم؛ ۱۲۳ ٤٥٦"
        _t, text = html_to_text("<p>%s</p>" % sample, 1000)
        self.assertEqual(text, sample)

    def test_bad_arguments(self):
        with self.assertRaises(TypeError):
            html_to_text(b"<p>x</p>", 10)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            html_to_text("<p>x</p>", 0)


class DecodeBodyTests(unittest.TestCase):
    PERSIAN = "سلام دنیا، این یک آزمایش است ۱۲۳"

    def test_utf8_and_windows_1256_persian(self):
        self.assertEqual(decode_body(self.PERSIAN.encode("utf-8"), "utf-8"), self.PERSIAN)
        self.assertEqual(decode_body(self.PERSIAN.encode("utf-8")), self.PERSIAN)
        # windows-1256 has the Arabic yeh/kaf (U+064A / U+0643), which is what legacy Persian pages used
        text = "سلام دنيا، اين يك آزمايش است پچگژ"
        legacy = text.encode("cp1256")
        self.assertEqual(decode_body(legacy, "windows-1256"), text)
        self.assertEqual(decode_body(legacy, "WINDOWS-1256"), text)
        self.assertEqual(decode_body(legacy, "cp1256"), text)
        self.assertNotEqual(decode_body(legacy, ""), text)  # no charset -> utf-8 guess, garbled

    def test_unknown_or_non_text_charsets_fall_back_to_utf8(self):
        data = self.PERSIAN.encode("utf-8")
        for name in ("made-up-charset", "hex", "base64", "rot13", "zlib", "idna", "unicode_escape", "x" * 30):
            with self.subTest(charset=name):
                self.assertEqual(decode_body(data, name), self.PERSIAN)

    def test_invalid_bytes_are_replaced_not_raised(self):
        text = decode_body(b"ok \xff\xfe\xfa end", "utf-8")
        self.assertTrue(text.startswith("ok ") and text.endswith(" end"))

    def test_bom_wins_and_meta_charset_is_sniffed_for_html(self):
        self.assertEqual(decode_body(b"\xef\xbb\xbf" + self.PERSIAN.encode("utf-8"), "windows-1256"), self.PERSIAN)
        page = b'<html><head><meta http-equiv="Content-Type" content="text/html; charset=windows-1256"></head><body>' + \
            "سلام".encode("cp1256") + b"</body></html>"
        self.assertIn("سلام", decode_body(page, "", True))
        self.assertNotIn("سلام", decode_body(page, "", False))


class StatusAndGateTests(unittest.TestCase):
    def test_network_status_is_unknown_without_evidence(self):
        for probe in (None, lambda: None):
            with self.subTest(probe=probe):
                s = network_status(probe)
                self.assertEqual(s.state, "unknown")
                self.assertTrue(s.message_fa and s.message_en)

    def test_probe_answers(self):
        self.assertEqual(network_status(lambda: True, clock=lambda: 5.0).state, "online")
        self.assertEqual(network_status(lambda: True, clock=lambda: 5.0).checked_at, 5.0)
        self.assertEqual(network_status(lambda: False).state, "offline")
        for odd in (1, "yes", 0, [], object()):
            with self.subTest(answer=odd):
                self.assertEqual(network_status(lambda odd=odd: odd).state, "unknown")

    def test_raising_probe_is_unknown_and_leaks_no_text(self):
        def boom():
            raise RuntimeError("secret-token-123")
        s = network_status(boom)
        self.assertEqual((s.state, s.source, s.detail), ("unknown", "probe_error", "RuntimeError"))
        self.assertNotIn("secret", repr(s.to_dict()))

    def test_static_gate(self):
        gate = StaticGate([NETWORK])
        self.assertTrue(gate.allowed("network"))
        self.assertFalse(gate.allowed("microphone"))
        self.assertFalse(gate.allowed(None))  # type: ignore[arg-type]
        self.assertFalse(StaticGate().allowed("network"))
        with self.assertRaises(ValueError):
            StaticGate([5])  # type: ignore[list-item]
        with self.assertRaises(AttributeError):
            gate.extra = 1  # type: ignore[attr-defined]

    def test_callable_gate_fails_closed(self):
        self.assertTrue(CallableGate(lambda p: True).allowed("network"))
        self.assertFalse(CallableGate(lambda p: 1).allowed("network"))      # only literal True counts
        self.assertFalse(CallableGate(lambda p: "yes").allowed("network"))

        def broken(_p):
            raise RuntimeError("x")
        self.assertFalse(CallableGate(broken).allowed("network"))
        with self.assertRaises(ValueError):
            CallableGate("not callable")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
