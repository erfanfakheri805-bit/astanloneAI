"""Prompt 959 (stage B, «مغز خودکار») - net_tools.download_resumable: a big file that survives a bad network.

Two kinds of evidence: a fake CDN transport (scripted cuts, redirects with Hugging Face's own headers, ignored Range ...) and a REAL loopback
HTTP server through the real `HttpClientTransport` (the `Range` request header really goes over a socket and a `206` really comes back).
No traffic leaves the machine.
"""
import hashlib
import os
import socketserver
import sys
import tempfile
import threading
import unittest
from collections import namedtuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from net_tools import (CallableGate, FetchPolicy, HttpClientTransport, NETWORK, StaticGate, StreamResponse, TransportError, TransportRequest)
from net_tools.resumable import (RESUMABLE_CODES, discard_partial, download_resumable, partial_path, partial_size)

GATE = StaticGate([NETWORK])
DATA = bytes((i * 7 + (i >> 8)) % 251 for i in range(300_000))
SHA = hashlib.sha256(DATA).hexdigest()
URL = "https://huggingface.co/litert-community/x/resolve/main/m.litertlm"
CDN = "https://cas-bridge.xethub.hf.co/blob/m"
Usage = namedtuple("Usage", "total used free")
PLENTY = lambda _p: Usage(10 ** 12, 0, 10 ** 12)  # noqa: E731
LOOPBACK = FetchPolicy(allow_http=True, allow_private_addresses=True, timeout_s=2.0)


def sleeps_total(box):
    return round(sum(box), 2)


class FakeCdn:
    """A transport that behaves like Hugging Face + its CDN. `plan` scripts the CDN connections one by one:
    ("ok",) | ("cut", n) (n body bytes, then a network error) | ("refuse",) | ("status", code) | ("short",) (ends without an error, too early)."""

    def __init__(self, data=DATA, *, plan=(("ok",),), redirect=True, linked_etag=None, linked_size=None, ignore_range=False,
                 content_type="application/octet-stream", bad_range=None, chunk=1500, cdn_host="cas-bridge.xethub.hf.co", no_length=False):
        self.data, self.plan, self.redirect = data, list(plan), redirect
        self.linked_etag, self.linked_size, self.ignore_range = linked_etag, linked_size, ignore_range
        self.content_type, self.bad_range, self.chunk, self.cdn_host = content_type, bad_range, chunk, cdn_host
        self.no_length = no_length
        self.requests, self.cdn_requests, self.closed, self.read = [], [], 0, 0

    def _stream(self, status, headers, chunks, declared, error=None):
        outer = self

        def gen():
            for part in chunks:
                outer.read += len(part)
                yield part
            if error is not None:
                raise error

        def close():
            outer.closed += 1

        merged = {"content-type": self.content_type}
        merged.update(headers)
        return StreamResponse(status, merged, "93.184.216.34", gen, close, declared)

    def stream(self, request):
        self.requests.append(request)
        if self.redirect and request.host == "huggingface.co":
            headers = {"location": "https://%s/blob/m" % self.cdn_host}
            if self.linked_etag is not None:
                headers["x-linked-etag"] = self.linked_etag
            if self.linked_size is not None:
                headers["x-linked-size"] = str(self.linked_size)
            return self._stream(302, headers, [], None)
        self.cdn_requests.append(request)
        step = self.plan.pop(0) if len(self.plan) > 1 else self.plan[0]
        kind = step[0]
        if kind == "refuse":
            raise TransportError("offline", "network_unreachable")
        if kind == "status":
            return self._stream(step[1], {}, [], None)
        total = len(self.data)
        wanted = request.headers.get("Range")
        start = 0
        if wanted and not self.ignore_range:
            start = int(wanted.split("=", 1)[1].split("-", 1)[0])
            if start >= total:
                return self._stream(416, {"content-range": "bytes */%d" % total}, [], None)
            body = self.data[start:]
            headers = {"content-range": self.bad_range or "bytes %d-%d/%d" % (start, total - 1, total), "content-length": str(len(body))}
            status = 206
        else:
            body = self.data
            headers = {} if self.no_length else {"content-length": str(len(body))}
            status = 200
        declared, error = (None if self.no_length else len(body)), None
        if kind == "cut":
            body, error = body[:step[1]], TransportError("timeout", "read")
        elif kind == "short":
            body = body[:len(body) // 2]
        parts = [body[i:i + self.chunk] for i in range(0, len(body), self.chunk)]
        return self._stream(status, headers, parts, declared, error)

    def __call__(self, request):  # pragma: no cover
        raise AssertionError("a resumable download must use .stream")


class ResumableCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "own")
        os.mkdir(self.root)
        self.sleeps = []

    def files(self):
        found = []
        for base, _dirs, names in os.walk(self.root):
            found.extend(os.path.relpath(os.path.join(base, n), self.root) for n in names)
        return sorted(found)

    def get(self, transport, **kw):
        kw.setdefault("gate", GATE)
        kw.setdefault("expected_sha256", SHA)
        kw.setdefault("size_hint", len(DATA))
        kw.setdefault("max_bytes", len(DATA) + 1000)
        kw.setdefault("free_space_fn", PLENTY)
        kw.setdefault("sleep", self.sleeps.append)
        url = kw.pop("url", URL)
        rel = kw.pop("rel", "brain.litertlm")
        return download_resumable(url, self.root, rel, transport=transport, **kw)


class CleanDownloadTests(ResumableCase):
    def test_verified_download_lands_with_no_partial(self):
        fake = FakeCdn()
        seen = []
        r = self.get(fake, progress=lambda phase, done, total: seen.append((phase, done, total)))
        self.assertTrue(r.ok, r)
        self.assertEqual((r.code, r.bytes_have, r.total, r.sha256, r.attempts, r.resumable), ("ok", len(DATA), len(DATA), SHA, 1, False))
        with open(r.path, "rb") as fh:
            self.assertEqual(fh.read(), DATA)
        self.assertEqual(self.files(), ["brain.litertlm"])
        self.assertEqual(seen[-1][0], "verify")
        self.assertIn(("download", len(DATA), len(DATA)), seen)
        self.assertGreater(fake.closed, 0)
        self.assertEqual(fake.cdn_requests[0].headers.get("Range"), None)
        self.assertEqual(fake.requests[0].host, "huggingface.co")

    def test_a_crashing_progress_callback_changes_nothing(self):
        def bad(*_a):
            raise RuntimeError("ui crashed")
        self.assertTrue(self.get(FakeCdn(), progress=bad).ok)

    def test_every_code_has_a_persian_and_an_english_text(self):
        from net_tools.resumable import _text
        for code in RESUMABLE_CODES:
            fa, en = _text(code, 403)
            self.assertTrue(fa.strip() and en.strip(), code)
            self.assertTrue(any("\u0600" <= ch <= "\u06ff" for ch in fa), code)


class ResumeTests(ResumableCase):
    def test_a_cut_in_the_middle_continues_from_the_same_byte(self):
        fake = FakeCdn(plan=[("cut", 100_000), ("ok",)])
        r = self.get(fake)
        self.assertTrue(r.ok, r)
        self.assertEqual(r.attempts, 2)
        second = fake.cdn_requests[1]
        self.assertEqual(second.headers["Range"], "bytes=%d-" % 100_000)
        with open(r.path, "rb") as fh:
            self.assertEqual(fh.read(), DATA)
        self.assertEqual(self.files(), ["brain.litertlm"])
        self.assertEqual(sleeps_total(self.sleeps), 2.0)          # the first back-off step
        self.assertEqual(fake.read, 100_000 + len(DATA) - 100_000)  # nothing was downloaded twice

    def test_many_cuts_never_give_up_while_bytes_keep_arriving(self):
        fake = FakeCdn(plan=[("cut", 30_000)] * 9 + [("ok",)])
        r = self.get(fake, attempts=2)                              # two failures IN A ROW would stop it - progress resets the count
        self.assertTrue(r.ok, r)
        self.assertEqual(r.attempts, 10)

    def test_no_progress_in_a_row_stops_with_interrupted_and_keeps_the_partial(self):
        fake = FakeCdn(plan=[("cut", 50_000), ("refuse",)])
        r = self.get(fake, attempts=3)
        self.assertEqual((r.ok, r.code, r.resumable, r.bytes_have), (False, "interrupted", True, 50_000), r)
        self.assertEqual(partial_size(self.root, "brain.litertlm"), 50_000)
        self.assertEqual(self.files(), ["brain.litertlm.partial"])
        self.assertIn("offline", r.detail)
        fake2 = FakeCdn()                                            # the network is back: a NEW call continues from the partial
        again = self.get(fake2)
        self.assertTrue(again.ok, again)
        self.assertEqual(fake2.cdn_requests[0].headers["Range"], "bytes=50000-")
        self.assertEqual(self.files(), ["brain.litertlm"])

    def test_cancel_keeps_the_partial_and_a_later_call_resumes(self):
        calls = {"n": 0}

        def stop():
            calls["n"] += 1
            return calls["n"] > 40
        r = self.get(FakeCdn(chunk=1000), should_cancel=stop)
        self.assertEqual((r.ok, r.code, r.resumable), (False, "cancelled", True), r)
        self.assertGreater(r.bytes_have, 0)
        self.assertLess(r.bytes_have, len(DATA))
        again = self.get(FakeCdn())
        self.assertTrue(again.ok, again)

    def test_cancel_while_waiting_between_attempts(self):
        state = {"after_first": False}

        def stop():
            return state["after_first"]

        def sleeper(seconds):
            state["after_first"] = True                              # the stop arrives during the back-off
        r = self.get(FakeCdn(plan=[("cut", 20_000), ("ok",)]), should_cancel=stop, sleep=sleeper)
        self.assertEqual((r.code, r.resumable), ("cancelled", True), r)

    def test_a_server_that_ignores_range_makes_the_file_start_again_never_append_twice(self):
        fake = FakeCdn(plan=[("cut", 60_000), ("ok",)], ignore_range=True)
        r = self.get(fake)
        self.assertTrue(r.ok, r)
        with open(r.path, "rb") as fh:
            self.assertEqual(fh.read(), DATA)

    def test_a_206_that_starts_somewhere_else_is_never_appended(self):
        fake = FakeCdn(plan=[("cut", 60_000), ("ok",)], bad_range="bytes 0-%d/%d" % (len(DATA) - 1, len(DATA)))
        r = self.get(fake, attempts=2)
        self.assertEqual((r.ok, r.code), (False, "interrupted"), r)
        self.assertIn("bad_content_range", r.detail)
        self.assertEqual(partial_size(self.root, "brain.litertlm"), 60_000)

    def test_a_complete_partial_goes_straight_to_verification(self):
        with open(os.path.join(self.root, "brain.litertlm.partial"), "wb") as fh:
            fh.write(DATA)
        fake = FakeCdn()
        r = self.get(fake)
        self.assertTrue(r.ok, r)
        self.assertEqual(fake.cdn_requests[0].headers["Range"], "bytes=%d-" % len(DATA))   # answered 416 -> nothing left to fetch
        self.assertEqual(fake.read, 0)

    def test_a_bogus_partial_larger_than_the_file_is_dropped(self):
        with open(os.path.join(self.root, "brain.litertlm.partial"), "wb") as fh:
            fh.write(DATA + b"extra-garbage")
        fake = FakeCdn(plan=[("ok",)])
        r = self.get(fake, max_bytes=len(DATA) + 5)                 # bigger than max_bytes: cannot be a piece of this file
        self.assertTrue(r.ok, r)
        self.assertIsNone(fake.cdn_requests[0].headers.get("Range"))

    def test_a_stream_that_ends_early_without_an_error_is_retried(self):
        fake = FakeCdn(plan=[("short",), ("ok",)])
        r = self.get(fake)
        self.assertTrue(r.ok, r)
        self.assertEqual(r.attempts, 2)

    def test_5xx_is_retried_and_404_is_not(self):
        r = self.get(FakeCdn(plan=[("status", 503), ("status", 429), ("ok",)]))
        self.assertTrue(r.ok, r)
        dead = self.get(FakeCdn(plan=[("status", 404)]), rel="other.litertlm")
        self.assertEqual((dead.ok, dead.code), (False, "http_error"), dead)
        self.assertIn("۴۰۴", dead.message_fa)


class RefusalTests(ResumableCase):
    def test_a_wrong_hash_installs_nothing_and_leaves_nothing(self):
        r = self.get(FakeCdn(data=b"x" * len(DATA)))
        self.assertEqual((r.ok, r.code, r.resumable), (False, "hash_mismatch", False), r)
        self.assertEqual(self.files(), [])

    def test_the_servers_own_etag_is_compared_with_the_pin_before_any_byte(self):
        fake = FakeCdn(linked_etag='"%s"' % ("ab" * 32), linked_size=len(DATA))
        r = self.get(fake)
        self.assertEqual((r.ok, r.code), (False, "remote_changed"), r)
        self.assertEqual(fake.read, 0)
        self.assertEqual(self.files(), [])

    def test_a_matching_etag_and_size_pass(self):
        r = self.get(FakeCdn(linked_etag='"%s"' % SHA, linked_size=len(DATA)))
        self.assertTrue(r.ok, r)

    def test_an_etag_that_is_not_a_sha256_is_ignored(self):
        self.assertTrue(self.get(FakeCdn(linked_etag='"abc123"', linked_size=len(DATA))).ok)

    def test_the_linked_size_must_equal_the_announced_length(self):
        r = self.get(FakeCdn(linked_size=len(DATA) + 5))
        self.assertEqual((r.ok, r.code), (False, "size_mismatch"), r)
        self.assertEqual(self.files(), [])

    def test_a_length_outside_the_expected_range_is_refused_before_any_byte(self):
        fake = FakeCdn(data=DATA * 3)
        r = self.get(fake, max_bytes=len(DATA) * 4)
        self.assertEqual((r.ok, r.code), (False, "size_mismatch"), r)
        self.assertEqual(fake.read, 0)

    def test_every_hop_must_be_on_the_allowed_host_list(self):
        fake = FakeCdn(cdn_host="evil.example.net")
        r = self.get(fake, allowed_hosts=("huggingface.co", "hf.co"))
        self.assertEqual((r.ok, r.code), (False, "host_not_allowed"), r)
        self.assertEqual(fake.cdn_requests, [])
        ok = self.get(FakeCdn(), allowed_hosts=("huggingface.co", "hf.co"))
        self.assertTrue(ok.ok, ok)
        first = self.get(FakeCdn(), url="https://example.org/m.litertlm", allowed_hosts=("hf.co",), rel="x.litertlm")
        self.assertEqual(first.code, "host_not_allowed")

    def test_an_html_answer_is_refused(self):
        r = self.get(FakeCdn(content_type="text/html; charset=utf-8"))
        self.assertEqual((r.ok, r.code), (False, "unsupported_content_type"), r)
        self.assertEqual(self.files(), [])

    def test_more_than_max_bytes_is_refused(self):
        r = self.get(FakeCdn(chunk=4000, no_length=True), max_bytes=len(DATA) - 10, size_hint=len(DATA) - 10, size_tolerance=1.0)
        self.assertEqual((r.ok, r.code), (False, "too_large"), r)
        self.assertEqual(self.files(), [])
        loud = self.get(FakeCdn(chunk=4000), max_bytes=len(DATA) - 10, size_hint=len(DATA) - 10, size_tolerance=1.0, rel="loud.litertlm")
        self.assertEqual(loud.code, "size_mismatch")           # an announced length beyond max_bytes is refused before any byte
        self.assertEqual(self.files(), [])

    def test_the_network_permission_is_checked_before_any_request_and_before_every_attempt(self):
        fake = FakeCdn()
        none = self.get(fake, gate=StaticGate([]))
        self.assertEqual((none.code, fake.requests), ("permission_denied", []))
        state = {"on": True}
        gate = CallableGate(lambda _p: state["on"])

        def revoke(_seconds):
            state["on"] = False
        fake2 = FakeCdn(plan=[("cut", 20_000), ("ok",)])
        r = self.get(fake2, gate=gate, sleep=revoke)
        self.assertEqual((r.code, r.resumable), ("permission_denied", True), r)
        self.assertEqual(len(fake2.cdn_requests), 1)

    def test_not_enough_free_space_is_said_before_the_download(self):
        fake = FakeCdn()
        r = self.get(fake, free_space_fn=lambda _p: Usage(1, 1, 1000))
        self.assertEqual((r.code, fake.requests), ("insufficient_space", []))

    def test_bad_arguments(self):
        for kw in (dict(expected_sha256="abc"), dict(expected_sha256=None)):
            self.assertEqual(self.get(FakeCdn(), **kw).code, "invalid_hash")
        for rel in ("../x.bin", "/abs.bin", "a/../b.bin", "x.partial", "bad name.bin"):
            self.assertEqual(self.get(FakeCdn(), rel=rel).code, "invalid_destination", rel)
        self.assertEqual(self.get(FakeCdn(), url="ftp://huggingface.co/a").code, "unsupported_scheme")
        self.assertEqual(self.get(FakeCdn(), url="https://127.0.0.1/a").code, "blocked_address")
        with self.assertRaises(ValueError):
            self.get(FakeCdn(), max_bytes=0)
        with self.assertRaises(ValueError):
            self.get(FakeCdn(), size_hint=len(DATA) + 5000)
        with self.assertRaises(ValueError):
            self.get(FakeCdn(), attempts=0)
        with self.assertRaises(ValueError):
            self.get(FakeCdn(), size_tolerance=2)

    def test_a_symlinked_partial_is_refused(self):
        target = os.path.join(self._tmp.name, "elsewhere")
        open(target, "wb").close()
        os.symlink(target, os.path.join(self.root, "brain.litertlm.partial"))
        r = self.get(FakeCdn())
        self.assertEqual((r.code, r.detail), ("invalid_destination", "symlink_partial"))

    def test_a_transport_without_stream_is_refused(self):
        self.assertEqual(self.get(lambda request: None).code, "unknown_error")


class ExistingFileTests(ResumableCase):
    def test_a_final_file_with_the_right_hash_is_not_downloaded_again(self):
        with open(os.path.join(self.root, "brain.litertlm"), "wb") as fh:
            fh.write(DATA)
        fake = FakeCdn()
        r = self.get(fake)
        self.assertTrue(r.ok, r)
        self.assertEqual(fake.requests, [])

    def test_a_final_file_with_a_wrong_hash_is_removed_never_trusted(self):
        with open(os.path.join(self.root, "brain.litertlm"), "wb") as fh:
            fh.write(b"y" * len(DATA))
        r = self.get(FakeCdn(plan=[("refuse",)]), attempts=1)
        self.assertEqual(r.code, "hash_mismatch")
        self.assertEqual(self.files(), [])

    def test_discard_partial_removes_everything_of_it(self):
        self.get(FakeCdn(plan=[("cut", 10_000), ("refuse",)]), attempts=1)
        self.assertEqual(partial_size(self.root, "brain.litertlm"), 10_000)
        self.assertTrue(discard_partial(self.root, "brain.litertlm"))
        self.assertEqual((self.files(), partial_size(self.root, "brain.litertlm")), ([], 0))
        self.assertFalse(discard_partial(self.root, "../x"))
        self.assertEqual(partial_size(self.root, "../x"), 0)
        self.assertTrue(partial_path(self.root, "brain.litertlm").endswith("brain.litertlm.partial"))

    def test_the_overall_deadline_stops_a_never_ending_story(self):
        ticks = iter(range(0, 10_000, 100))
        r = self.get(FakeCdn(plan=[("cut", 1000)]), overall_s=250.0, clock=lambda: next(ticks), attempts=100)
        self.assertEqual((r.code, r.detail), ("interrupted", "overall_deadline"), r)


# ------------------------------------------------------------------ the REAL transport against a loopback server with Range support
class RangeServer:
    """Serves DATA at /m.bin with Range support; the first `cuts` connections are cut after `cut_at` body bytes."""

    def __init__(self, cuts=1, cut_at=120_000):
        self.cuts, self.cut_at, self.heads, self.lock = cuts, cut_at, [], threading.Lock()

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
                    head = data.decode("latin-1")
                    with outer.lock:
                        outer.heads.append(head)
                        cut = len(outer.heads) <= outer.cuts
                    start = 0
                    for line in head.split("\r\n"):
                        if line.lower().startswith("range:"):
                            start = int(line.split("=", 1)[1].split("-", 1)[0])
                    body = DATA[start:]
                    lines = ["HTTP/1.1 %s" % ("206 Partial Content" if start else "200 OK"), "Content-Type: application/octet-stream",
                             "Content-Length: %d" % len(body), "Connection: close"]
                    if start:
                        lines.append("Content-Range: bytes %d-%d/%d" % (start, len(DATA) - 1, len(DATA)))
                    conn.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
                    conn.sendall(body[:outer.cut_at] if cut else body)
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
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def url(self):
        return "http://127.0.0.1:%d/m.bin" % self.port


class RealTransportTests(ResumableCase):
    def test_range_really_goes_over_the_socket_and_the_206_really_comes_back(self):
        with RangeServer(cuts=1, cut_at=120_000) as srv:
            r = self.get(HttpClientTransport(LOOPBACK), url=srv.url(), policy=LOOPBACK)
            heads = list(srv.heads)
        self.assertTrue(r.ok, r)
        self.assertEqual(r.attempts, 2)
        self.assertNotIn("Range:", heads[0])
        second = [line for line in heads[1].split("\r\n") if line.startswith("Range:")]
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0], "Range: bytes=120000-")
        with open(r.path, "rb") as fh:
            self.assertEqual(fh.read(), DATA)

    def test_two_cuts_in_a_row_still_finish(self):
        with RangeServer(cuts=2, cut_at=70_000) as srv:
            r = self.get(HttpClientTransport(LOOPBACK), url=srv.url(), policy=LOOPBACK)
        self.assertTrue(r.ok, r)
        self.assertEqual(r.attempts, 3)

    def test_the_transport_accepts_only_a_plain_range_on_a_get(self):
        with RangeServer(cuts=0) as srv:
            transport = HttpClientTransport(LOOPBACK)

            def request(**kw):
                values = dict(method="GET", url=srv.url(), host="127.0.0.1", port=srv.port, scheme="http", path_query="/m.bin",
                              headers={}, timeout_s=2.0, max_bytes=len(DATA) + 10)
                values.update(kw)
                return TransportRequest(**values)
            good = transport.stream(request(headers={"Range": "bytes=299990-"}))
            try:
                self.assertEqual((good.status, b"".join(good.iter_chunks())), (206, DATA[299990:]))
            finally:
                good.close()
            before = len(srv.heads)
            for bad in ("bytes=abc-", "items=0-1", "bytes=0-1,5-6", "bytes=-5", "bytes=1-2\r\nHost: evil", "bytes=" + "9" * 20 + "-"):
                with self.assertRaises(TransportError) as ctx:
                    transport.stream(request(headers={"Range": bad}))
                self.assertEqual(ctx.exception.detail, "bad_request_header", bad)
            with self.assertRaises(TransportError) as ctx:      # a POST can never carry it
                transport(request(method="POST", body=b"{}", headers={"Content-Type": "application/json", "Range": "bytes=0-"}))
            self.assertEqual(ctx.exception.detail, "bad_request_header")
            self.assertEqual(len(srv.heads), before, "nothing may have been sent for a refused header")


if __name__ == "__main__":
    unittest.main()
