"""Prompt 957 - net_tools.download_file: verified, atomic, destination-safe (network MOCKED by fake stream transports)."""
import hashlib
import os
import sys
import tempfile
import unittest
from collections import namedtuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from net_tools import (FetchPolicy, NETWORK, StaticGate, StreamResponse, TransportError, download_file)
from net_tools.download import resolve_destination

GATE = StaticGate([NETWORK])
DATA = b"model-bytes-" * 1000
SHA = hashlib.sha256(DATA).hexdigest()
URL = "https://files.example.org/model.bin"
Usage = namedtuple("Usage", "total used free")
PLENTY = lambda _path: Usage(10 ** 12, 0, 10 ** 12)  # noqa: E731


def stream_of(chunks, status=200, headers=None, error=None, declared=None):
    state = {"closed": 0}

    def gen():
        for chunk in chunks:
            yield chunk
        if error is not None:
            raise error

    def close():
        state["closed"] += 1

    h = {"content-type": "application/octet-stream"}
    h.update(headers or {})
    resp = StreamResponse(status, h, "93.184.216.34", gen, close, declared)
    resp.state = state
    return resp


class FakeStreamTransport:
    def __init__(self, *items):
        self.items, self.requests, self.streams = list(items), [], []

    def stream(self, request):
        self.requests.append(request)
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, BaseException):
            raise item
        self.streams.append(item)
        return item

    def __call__(self, request):  # pragma: no cover - downloads must use .stream
        raise AssertionError("download_file must call .stream, not the buffered path")


def split(data, size=1500):
    return [data[i:i + size] for i in range(0, len(data), size)]


class DownloadTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "models")
        os.mkdir(self.root)

    def files(self):
        found = []
        for base, _dirs, names in os.walk(self.root):
            found.extend(os.path.relpath(os.path.join(base, n), self.root) for n in names)
        return sorted(found)

    def get(self, transport, rel="m/model.bin", sha=SHA, max_bytes=len(DATA) + 100, **kw):
        kw.setdefault("free_space_fn", PLENTY)
        return download_file(kw.pop("url", URL), self.root, rel, gate=kw.pop("gate", GATE), expected_sha256=sha,
                             max_bytes=max_bytes, transport=transport, **kw)


class SuccessTests(DownloadTestCase):
    def test_verified_download_lands_atomically_with_no_partial(self):
        t = FakeStreamTransport(stream_of(split(DATA), declared=len(DATA)))
        seen = []
        r = self.get(t, progress=lambda done, total: seen.append((done, total)))
        self.assertTrue(r.ok, r)
        self.assertEqual((r.code, r.bytes_written, r.sha256), ("ok", len(DATA), SHA))
        self.assertEqual(r.path, os.path.join(os.path.realpath(self.root), "m", "model.bin"))
        with open(r.path, "rb") as fh:
            self.assertEqual(fh.read(), DATA)
        self.assertEqual(self.files(), [os.path.join("m", "model.bin")])
        self.assertEqual(seen[-1], (len(DATA), len(DATA)))
        self.assertEqual(t.streams[0].state["closed"], 1)
        req = t.requests[0]
        self.assertEqual((req.method, req.scheme, req.host, req.max_bytes), ("GET", "https", "files.example.org", len(DATA) + 100))
        self.assertGreater(req.total_timeout_s, 1)

    def test_uppercase_expected_hash_is_accepted(self):
        r = self.get(FakeStreamTransport(stream_of(split(DATA))), sha=SHA.upper())
        self.assertTrue(r.ok, r)

    def test_exceptions_from_the_progress_callback_are_swallowed(self):
        def bad(_done, _total):
            raise RuntimeError("ui crashed")
        self.assertTrue(self.get(FakeStreamTransport(stream_of(split(DATA))), progress=bad).ok)

    def test_redirects_are_followed_and_the_redirect_response_is_released(self):
        first = stream_of([], status=302, headers={"location": "https://cdn.example.org/blob"})
        t = FakeStreamTransport(first, stream_of(split(DATA)))
        r = self.get(t)
        self.assertTrue(r.ok, r)
        self.assertEqual(first.state["closed"], 1)
        self.assertEqual(t.requests[1].url, "https://cdn.example.org/blob")

    def test_existing_destination_is_replaced_only_after_verification(self):
        os.mkdir(os.path.join(self.root, "m"))
        target = os.path.join(self.root, "m", "model.bin")
        with open(target, "wb") as fh:
            fh.write(b"old")
        bad = self.get(FakeStreamTransport(stream_of(split(b"corrupt" * 50))))
        self.assertEqual(bad.code, "hash_mismatch")
        with open(target, "rb") as fh:
            self.assertEqual(fh.read(), b"old")  # a failed download never damages what is already there
        self.assertEqual(self.files(), [os.path.join("m", "model.bin")])
        self.assertTrue(self.get(FakeStreamTransport(stream_of(split(DATA)))).ok)
        with open(target, "rb") as fh:
            self.assertEqual(fh.read(), DATA)


class FailureLeavesNothingTests(DownloadTestCase):
    def assert_nothing_written(self):
        self.assertEqual(self.files(), [])

    def test_hash_mismatch(self):
        r = self.get(FakeStreamTransport(stream_of(split(DATA + b"tampered"))), max_bytes=len(DATA) + 1000)
        self.assertEqual((r.ok, r.code, r.path), (False, "hash_mismatch", ""))
        self.assertEqual(r.sha256, hashlib.sha256(DATA + b"tampered").hexdigest())
        self.assertIn("دور ریخته", r.message_fa)
        self.assert_nothing_written()

    def test_too_large_while_streaming(self):
        r = self.get(FakeStreamTransport(stream_of(split(DATA))), max_bytes=len(DATA) - 1)
        self.assertEqual((r.ok, r.code), (False, "too_large"))
        self.assert_nothing_written()

    def test_declared_length_over_the_limit_is_refused_before_writing(self):
        t = FakeStreamTransport(stream_of(split(DATA), declared=len(DATA)))
        r = self.get(t, max_bytes=1000)
        self.assertEqual((r.ok, r.code, r.detail), (False, "too_large", "content_length"))
        self.assert_nothing_written()
        t = FakeStreamTransport(stream_of(split(DATA), headers={"content-length": str(len(DATA))}))
        self.assertEqual(self.get(t, max_bytes=1000).code, "too_large")

    def test_interrupted_stream(self):
        for code in ("timeout", "protocol_error", "offline", "tls_error"):
            with self.subTest(code=code):
                r = self.get(FakeStreamTransport(stream_of(split(DATA)[:3], error=TransportError(code, "cut"))))
                self.assertEqual((r.ok, r.code), (False, code))
                self.assert_nothing_written()

    def test_connection_failures(self):
        for code in ("dns_failure", "connect_refused", "blocked_address"):
            with self.subTest(code=code):
                r = self.get(FakeStreamTransport(TransportError(code)))
                self.assertEqual((r.ok, r.code), (False, code))
                self.assert_nothing_written()

    def test_stray_exceptions_do_not_leak_or_leave_files(self):
        r = self.get(FakeStreamTransport(RuntimeError("token=abc123")))
        self.assertEqual((r.ok, r.code), (False, "unknown_error"))
        self.assertNotIn("abc123", repr(r.to_dict()))
        self.assert_nothing_written()

    def test_html_answers_are_refused(self):
        for ctype in ("text/html", "text/html; charset=utf-8", "TEXT/HTML", "application/xhtml+xml"):
            with self.subTest(ctype=ctype):
                r = self.get(FakeStreamTransport(stream_of([b"<html>login to wifi</html>"], headers={"content-type": ctype})))
                self.assertEqual((r.ok, r.code), (False, "unsupported_content_type"))
                self.assert_nothing_written()

    def test_compressed_answers_are_refused(self):
        r = self.get(FakeStreamTransport(stream_of(split(DATA), headers={"content-encoding": "gzip"})))
        self.assertEqual((r.ok, r.code), (False, "unsupported_encoding"))
        self.assert_nothing_written()

    def test_non_200_statuses(self):
        for status in (206, 403, 404, 500):
            with self.subTest(status=status):
                r = self.get(FakeStreamTransport(stream_of(split(DATA), status=status)))
                self.assertEqual((r.ok, r.code), (False, "http_error"))
                self.assert_nothing_written()

    def test_redirect_into_a_private_address_is_refused(self):
        hop = stream_of([], status=302, headers={"location": "https://192.168.1.10/model.bin"})
        t = FakeStreamTransport(hop, stream_of(split(DATA)))
        r = self.get(t)
        self.assertEqual((r.ok, r.code), (False, "blocked_address"))
        self.assertEqual(len(t.requests), 1)
        self.assert_nothing_written()

    def test_failed_downloads_close_the_stream(self):
        s = stream_of(split(DATA), headers={"content-encoding": "br"})
        self.get(FakeStreamTransport(s))
        self.assertEqual(s.state["closed"], 1)


class ArgumentAndPermissionTests(DownloadTestCase):
    def test_expected_hash_is_required_and_checked_before_any_network_use(self):
        t = FakeStreamTransport(stream_of(split(DATA)))
        for sha in (None, "", "abc", SHA[:-1], SHA + "0", "g" * 64, 12345, b"x" * 64):
            with self.subTest(sha=sha):
                r = self.get(t, sha=sha)
                self.assertEqual((r.ok, r.code), (False, "invalid_hash"))
        self.assertEqual(len(t.requests), 0)
        self.assertEqual(self.files(), [])

    def test_no_permission_means_no_network_and_no_files(self):
        for gate in (StaticGate(), None, object()):
            with self.subTest(gate=type(gate).__name__):
                t = FakeStreamTransport(stream_of(split(DATA)))
                r = self.get(t, gate=gate)
                self.assertEqual((r.ok, r.code), (False, "permission_denied"))
                self.assertEqual(len(t.requests), 0)
        self.assertEqual(self.files(), [])

    def test_plain_http_and_private_urls_are_refused(self):
        t = FakeStreamTransport(stream_of(split(DATA)))
        for url, code in (("http://files.example.org/m.bin", "unsupported_scheme"), ("https://127.0.0.1/m.bin", "blocked_address"),
                          ("https://localhost/m.bin", "blocked_address"), ("file:///etc/passwd", "unsupported_scheme"),
                          ("https://user:pw@files.example.org/m.bin", "invalid_url"), ("", "invalid_url")):
            with self.subTest(url=url):
                self.assertEqual(self.get(t, url=url).code, code)
        self.assertEqual(len(t.requests), 0)
        ok = self.get(FakeStreamTransport(stream_of(split(DATA))), url="http://files.example.org/m.bin",
                      policy=FetchPolicy(allow_http=True))
        self.assertTrue(ok.ok)

    def test_bad_max_bytes_is_a_programming_error(self):
        for bad in (0, -1, 1.5, "10", True, None, 9 * 2 ** 30):
            with self.subTest(max_bytes=bad):
                with self.assertRaises(ValueError):
                    self.get(FakeStreamTransport(stream_of([b""])), max_bytes=bad)

    def test_transport_without_stream_is_refused_not_misused(self):
        r = self.get(lambda request: None)
        self.assertEqual((r.ok, r.code), (False, "unknown_error"))


class DestinationTests(DownloadTestCase):
    BAD = ["../escape.bin", "a/../../escape.bin", "/abs/path.bin", "a//b.bin", "a/./b.bin", "a\\b.bin", "a/b\x00c.bin", "",
           ".", "..", "a/..", "model.bin.partial", "dir/x.partial", "C:/win.bin", "sp ace.bin", "a/" + "x" * 101,
           "ü.bin", "-lead.bin", "a/b/", "~/home.bin", "con:fuse"]

    def test_unsafe_relative_paths_are_rejected_before_the_network(self):
        t = FakeStreamTransport(stream_of(split(DATA)))
        for rel in self.BAD + ["x" * 300]:
            with self.subTest(rel=rel[:40]):
                r = self.get(t, rel=rel)
                self.assertEqual((r.ok, r.code), (False, "invalid_destination"))
        self.assertEqual(len(t.requests), 0)
        self.assertEqual(self.files(), [])
        self.assertFalse(os.path.exists(os.path.join(self._tmp.name, "escape.bin")))

    def test_each_kind_of_unsafe_path_is_refused_for_its_own_reason(self):
        t = FakeStreamTransport(stream_of(split(DATA)))
        for rel, reason in (("/abs/path.bin", "absolute_path"), ("C:/win.bin", "absolute_path"), ("../escape.bin", "bad_component"),
                            ("a//b.bin", "bad_component"), ("a\\b.bin", "bad_relative_path"), ("model.bin.partial", "reserved_suffix")):
            with self.subTest(rel=rel):
                r = self.get(t, rel=rel)
                self.assertEqual((r.ok, r.code, r.detail), (False, "invalid_destination", reason))
        self.assertEqual(len(t.requests), 0)

    def test_non_string_destinations_and_missing_root(self):
        t = FakeStreamTransport(stream_of(split(DATA)))
        for rel in (None, 5, b"x.bin", ["x.bin"]):
            self.assertEqual(self.get(t, rel=rel).code, "invalid_destination")
        r = download_file(URL, os.path.join(self._tmp.name, "missing"), "x.bin", gate=GATE, expected_sha256=SHA,
                          max_bytes=len(DATA), transport=t, free_space_fn=PLENTY)
        self.assertEqual(r.code, "invalid_destination")
        self.assertEqual(len(t.requests), 0)

    def test_symlinks_in_the_path_are_refused(self):
        outside = os.path.join(self._tmp.name, "outside")
        os.mkdir(outside)
        os.symlink(outside, os.path.join(self.root, "link_dir"))
        victim = os.path.join(outside, "victim.bin")
        with open(victim, "wb") as fh:
            fh.write(b"precious")
        os.symlink(victim, os.path.join(self.root, "link_file.bin"))
        t = FakeStreamTransport(stream_of(split(DATA)))
        for rel in ("link_dir/model.bin", "link_file.bin"):
            with self.subTest(rel=rel):
                r = self.get(t, rel=rel)
                self.assertEqual((r.ok, r.code, r.detail), (False, "invalid_destination", "symlink_in_path"))
        self.assertEqual(len(t.requests), 0)
        with open(victim, "rb") as fh:
            self.assertEqual(fh.read(), b"precious")
        self.assertEqual(os.listdir(outside), ["victim.bin"])

    def test_a_symlinked_partial_file_is_not_followed(self):
        outside = os.path.join(self._tmp.name, "outside.bin")
        with open(outside, "wb") as fh:
            fh.write(b"precious")
        os.symlink(outside, os.path.join(self.root, "model.bin.partial"))
        r = self.get(FakeStreamTransport(stream_of(split(DATA))), rel="model.bin")
        self.assertEqual((r.ok, r.code), (False, "invalid_destination"))
        with open(outside, "rb") as fh:
            self.assertEqual(fh.read(), b"precious")

    def test_destination_that_is_a_directory_is_refused(self):
        os.makedirs(os.path.join(self.root, "m", "model.bin"))
        self.assertEqual(self.get(FakeStreamTransport(stream_of(split(DATA)))).code, "invalid_destination")

    def test_resolve_destination_returns_a_path_under_the_root(self):
        full = resolve_destination(self.root, "a/b/c.bin")
        self.assertTrue(full.startswith(os.path.realpath(self.root) + os.sep))
        with self.assertRaises(ValueError):
            resolve_destination(self.root, "../x")


class SpaceTests(DownloadTestCase):
    def test_insufficient_space_is_refused_before_the_network(self):
        t = FakeStreamTransport(stream_of(split(DATA)))
        need = int((len(DATA) + 100) * 1.1)
        r = self.get(t, free_space_fn=lambda p: Usage(10 ** 9, 10 ** 9 - need + 1, need - 1))
        self.assertEqual((r.ok, r.code), (False, "insufficient_space"))
        self.assertEqual(len(t.requests), 0)
        self.assertEqual(self.files(), [])
        ok = self.get(FakeStreamTransport(stream_of(split(DATA))), free_space_fn=lambda p: Usage(10 ** 9, 0, need + 10))
        self.assertTrue(ok.ok)

    def test_free_space_function_receives_the_root_and_may_return_a_plain_tuple(self):
        calls = []

        def fake(path):
            calls.append(path)
            return (10 ** 12, 0, 10 ** 12)
        self.assertTrue(self.get(FakeStreamTransport(stream_of(split(DATA))), free_space_fn=fake).ok)
        self.assertEqual(calls, [os.path.realpath(self.root)])

    def test_failing_free_space_probe_is_an_io_error(self):
        def boom(_p):
            raise OSError("no")
        r = self.get(FakeStreamTransport(stream_of(split(DATA))), free_space_fn=boom)
        self.assertEqual((r.ok, r.code), (False, "io_error"))


if __name__ == "__main__":
    unittest.main()
