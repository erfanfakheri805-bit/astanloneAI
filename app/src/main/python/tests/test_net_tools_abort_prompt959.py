"""
Prompt 959 (stage B, «مغز خودکار») - `net_tools.transport.abort_all`, the emergency stop of the network, against a REAL loopback socket.

A phone on a bad link can leave a download blocked in a read of a connection that will never deliver another byte; asking the downloader to stop
cannot free a thread that sits in `recv`. `abort_all()` shuts the sockets of every request in flight so that thread gets an ordinary network error
at once. Here the server really sends part of the file and then goes silent (the connection stays open), and the real `HttpClientTransport` is
stuck in it; no traffic leaves the machine.
"""
import os
import socketserver
import sys
import tempfile
import threading
import time
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from net_tools import FetchPolicy, HttpClientTransport
from net_tools.resumable import partial_path, partial_size
from net_tools.transport import abort_all, in_flight
from tests.test_net_tools_resumable_prompt959 import DATA, ResumableCase

WAIT = 15


class StallServer:
    """The first connection gets the head and `send` bytes of DATA and then silence (the socket stays open until the server stops); every later
    connection is served normally, with Range support. `heads` are the request heads in order."""

    def __init__(self, send=100_000):
        self.send, self.heads, self.lock = send, [], threading.Lock()
        self.sent, self.stop = threading.Event(), threading.Event()

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
                        stall = len(outer.heads) == 1
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
                    if stall:
                        conn.sendall(body[:outer.send])
                        outer.sent.set()
                        outer.stop.wait(WAIT)                           # the dead link: open, silent
                    else:
                        conn.sendall(body)
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

    def url(self):
        return "http://127.0.0.1:%d/m.bin" % self.port


def policy(seconds):
    return FetchPolicy(allow_http=True, allow_private_addresses=True, timeout_s=seconds)


class AbortAllTests(ResumableCase):
    def run_download(self, srv, cancel, seconds):
        box = {}

        def work():
            box["result"] = self.get(HttpClientTransport(policy(seconds)), url=srv.url(), policy=policy(seconds), should_cancel=cancel.is_set)

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self.addCleanup(thread.join, WAIT)
        return thread, box

    def wait_for(self, predicate, what):
        end = time.monotonic() + WAIT
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("timed out waiting for " + what)

    def partial(self):
        return partial_size(self.root, "brain.litertlm")

    def test_nothing_in_flight_means_nothing_to_cut(self):
        self.assertEqual(in_flight(), 0)
        self.assertEqual(abort_all(), 0)
        self.assertEqual(abort_all(), 0)

    def test_the_emergency_stop_frees_a_download_stuck_on_a_dead_connection_and_keeps_the_partial(self):
        with StallServer(send=100_000) as srv:
            cancel = threading.Event()
            thread, box = self.run_download(srv, cancel, seconds=30.0)
            self.assertTrue(srv.sent.wait(WAIT))
            self.wait_for(lambda: self.partial() >= 90_000 and in_flight() >= 1, "the bytes to arrive and the socket to be tracked")
            self.assertTrue(thread.is_alive(), "the download is stuck in the silent connection")
            began = time.monotonic()
            cancel.set()                                            # the downloader is told to stop ... but it cannot see that from inside recv
            self.assertGreaterEqual(abort_all(), 1)                 # ... so the connection is cut
            thread.join(WAIT)
            freed_in = time.monotonic() - began
        self.assertFalse(thread.is_alive(), "the cut did not free the stuck thread")
        self.assertLess(freed_in, 5.0, "freed by the cut, not by the 30-second read timeout")
        result = box["result"]
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "cancelled", result)
        self.assertTrue(0 < self.partial() < len(DATA), "what was fetched stays: %d bytes" % self.partial())
        self.assertTrue(os.path.isfile(partial_path(self.root, "brain.litertlm")))
        self.assertEqual(in_flight(), 0, "no socket stays registered after the stop")

    def test_without_the_cut_a_stopped_download_stays_stuck_until_the_read_times_out(self):
        """Why `abort_all` exists: telling the downloader to stop does not free a thread blocked in a silent connection."""
        with StallServer(send=100_000) as srv:
            cancel = threading.Event()
            thread, box = self.run_download(srv, cancel, seconds=2.5)
            self.assertTrue(srv.sent.wait(WAIT))
            self.wait_for(lambda: self.partial() >= 90_000, "the bytes to arrive")
            began = time.monotonic()
            cancel.set()
            time.sleep(1.0)
            self.assertTrue(thread.is_alive(), "still blocked after one second: only a cut or the timeout can free it")
            thread.join(WAIT)
            self.assertGreaterEqual(time.monotonic() - began, 1.5)
        self.assertEqual(box["result"].code, "cancelled")

    def test_after_an_emergency_stop_the_next_download_resumes_from_the_partial_and_finishes(self):
        with StallServer(send=100_000) as srv:
            cancel = threading.Event()
            thread, box = self.run_download(srv, cancel, seconds=30.0)
            self.assertTrue(srv.sent.wait(WAIT))
            self.wait_for(lambda: self.partial() >= 90_000 and in_flight() >= 1, "the bytes to arrive")
            cancel.set()
            abort_all()
            thread.join(WAIT)
            held = self.partial()
            self.assertGreater(held, 0)
            result = self.get(HttpClientTransport(policy(5.0)), url=srv.url(), policy=policy(5.0))
            heads = list(srv.heads)
        self.assertTrue(result.ok, result)
        ranges = [line for line in heads[-1].split("\r\n") if line.startswith("Range:")]
        self.assertEqual(ranges, ["Range: bytes=%d-" % held], "only the rest was asked for")
        with open(result.path, "rb") as handle:
            self.assertEqual(handle.read(), DATA)
        self.assertEqual(in_flight(), 0)
        self.assertFalse(os.path.exists(partial_path(self.root, "brain.litertlm")), "the finished file leaves no partial behind")

    def test_a_download_that_finishes_leaves_no_registered_socket(self):
        with StallServer(send=0) as srv:
            srv.heads.append("the first connection is the stalled one: use it up")
            result = self.get(HttpClientTransport(policy(5.0)), url=srv.url(), policy=policy(5.0))
        self.assertTrue(result.ok, result)
        self.assertEqual(in_flight(), 0)
        self.assertEqual(abort_all(), 0)


if __name__ == "__main__":
    unittest.main()
