"""
net_tools.resumable - download ONE big file that survives a bad network, verified, or install nothing wrong
=========================================================================================================
`download_resumable(...)` is the downloader for a model file of hundreds of megabytes or a few gigabytes (Prompt 959, stage B, «مغز خودکار»).
A phone's network drops, changes from Wi-Fi to mobile data and goes through a VPN; a single-shot download (`download_file`) would start again from
zero after every cut. This one keeps what it has and continues from that byte.

What it guarantees (the tests prove each point):

* the same safety as `download_file`: permission "network" granted first, https only, an expected SHA-256 REQUIRED, a clean destination path under
  `dest_root`, public addresses only (every redirect hop is re-validated), HTML answers (captive portals, error pages) refused, identity encoding
  only, never more than `max_bytes`, and an optional list of allowed host suffixes that EVERY hop must match;
* the bytes go to `<dest>.partial` and stay there between attempts, between calls and between app restarts; each new connection asks for
  `Range: bytes=<have>-` and checks that the answer (`206`, `Content-Range`) really starts where the file ends. A server that ignores Range (a plain
  `200`) makes it start the file again - it never appends a whole file to a partial one;
* the first answer's own statements are checked before a single byte is stored: Hugging Face's `x-linked-etag` (the file's SHA-256) must equal the
  expected hash and `x-linked-size` must equal the length the transfer announces, and the length must lie in the expected range - a changed file on
  the server is refused in the first second, not after two gigabytes;
* a failed attempt (timeout, offline, reset, 5xx, an incomplete body) is retried with back-off; progress resets the failure counter, so a slow but
  moving transfer is never given up. After `attempts` attempts in a row without a single new byte it stops with `interrupted` and KEEPS the partial;
* `should_cancel()` is checked between chunks and between attempts: the stop returns `cancelled` and keeps the partial (a cut socket from the
  emergency stop is recognised as the stop, not as a network failure);
* only a file whose SHA-256 equals the expected one is moved (atomically, fsync'd) to its final name. A wrong hash deletes the partial and installs
  nothing; the final name never holds anything unverified.

The result's `ok` is True only when the verified file is in place. Nothing here raises for network, disk or user-input problems.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass
from typing import Callable, Optional, Sequence, Tuple

from .download import DOWNLOAD_CODES, _EXTRA_MESSAGES, _fsync_dir, _free_bytes, resolve_destination
from .fetch import message_for
from .permission import NETWORK, PermissionGate
from .policy import FetchPolicy, UrlError, parse_url
from .redirects import HopFailure, walk
from .transport import HttpClientTransport, TransportError, TransportRequest

__all__ = ["ResumableResult", "download_resumable", "RESUMABLE_CODES", "partial_path", "partial_size", "discard_partial",
           "RESUMABLE_MESSAGES"]

RESUMABLE_CODES = tuple(DOWNLOAD_CODES) + ("cancelled", "interrupted", "remote_changed", "size_mismatch", "host_not_allowed")
RESUMABLE_MESSAGES = {
    "ok": ("فایل کامل دانلود شد و صحت آن تأیید شد.", "The file was downloaded in full and verified."),
    "cancelled": ("دانلود متوقف شد؛ آنچه گرفته شده نگه داشته شد و می‌شود از همان‌جا ادامه داد.",
                  "The download was stopped; what was fetched is kept and can continue from there."),
    "interrupted": ("اینترنت قطع یا ناپایدار بود و بعد از چند بار تلاش ادامه پیدا نکرد؛ آنچه گرفته شده نگه داشته شد و بعداً از همان‌جا ادامه می‌یابد.",
                    "The network was down or unstable and the download could not continue after several tries; what was fetched is kept."),
    "remote_changed": ("فایلی که روی سرور هست با فایلی که برنامه می‌شناسد یکی نیست (احتمالاً نسخهٔ تازه‌ای منتشر شده)؛ چیزی دانلود نشد.",
                       "The file on the server is not the one the app knows (a newer version was probably published); nothing was downloaded."),
    "size_mismatch": ("اندازهٔ فایل روی سرور با آنچه انتظار می‌رفت نمی‌خواند؛ دانلود انجام نشد.",
                      "The file's size on the server does not match what was expected; nothing was downloaded."),
    "hash_mismatch": ("هش فایل دانلودشده با مقدار مورد انتظار نمی‌خواند؛ فایل دور ریخته شد و چیزی نصب نشد.",
                      "The downloaded file does not match the expected hash; it was discarded and nothing was installed."),
    "host_not_allowed": ("آدرس دانلود به میزبانی خارج از فهرست مجاز می‌رفت و رد شد.",
                         "The download address led to a host outside the allowed list and was refused."),
    "insufficient_space": ("فضای خالی برای ادامهٔ دانلود کافی نیست؛ آنچه گرفته شده نگه داشته شد.",
                           "There is not enough free space to continue; what was fetched is kept."),
    "permission_denied": ("اجازهٔ اینترنت داده نشده (یا پس گرفته شد)؛ آنچه گرفته شده نگه داشته شد.",
                          "Internet access is not granted (or was withdrawn); what was fetched is kept."),
}
_TRANSIENT_TRANSPORT = frozenset({"dns_failure", "offline", "connect_refused", "timeout", "tls_error", "protocol_error", "unknown_error"})
_TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_DISCARDS = frozenset({"hash_mismatch", "remote_changed", "size_mismatch", "too_large", "invalid_url", "unsupported_scheme", "blocked_address",
                       "host_not_allowed", "unsupported_content_type", "unsupported_encoding", "invalid_destination"})
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ETAG_RE = re.compile(r'^(?:W/)?"?([0-9a-fA-F]{64})"?$')
_RANGE_RE = re.compile(r"^bytes (\d{1,13})-(\d{1,13})/(\d{1,13}|\*)$")
_STAR_RANGE_RE = re.compile(r"^bytes \*/(\d{1,13})$")
_REFUSED_TYPES = ("text/html", "application/xhtml+xml")
_MAX_BYTES_LIMIT = 16 * 2 ** 30
_HASH_CHUNK = 1 << 20
_PROGRESS_STEP = 256 * 1024
_SYNC_STEP = 64 * 2 ** 20
_SLICE_S = 0.25


@dataclass(frozen=True)
class ResumableResult:
    ok: bool
    code: str
    path: str
    bytes_have: int            # bytes of the file on disk now (the partial, or the whole file when `ok`)
    total: int                 # the announced size, or 0 when never learned
    sha256: str
    attempts: int
    resumable: bool            # a later call continues from `bytes_have`
    message_fa: str
    message_en: str
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def partial_path(dest_root: str, rel_dest: str) -> str:
    """Where the unfinished download of `rel_dest` lives (raises ValueError for an unsafe destination, like `resolve_destination`)."""
    return resolve_destination(dest_root, rel_dest) + ".partial"


def partial_size(dest_root: str, rel_dest: str) -> int:
    """How many bytes of an unfinished download are on disk (0 when none, unsafe or unreadable). Never raises."""
    try:
        path = partial_path(dest_root, rel_dest)
        return int(os.path.getsize(path)) if os.path.isfile(path) and not os.path.islink(path) else 0
    except (ValueError, OSError):
        return 0


def discard_partial(dest_root: str, rel_dest: str) -> bool:
    """Delete an unfinished download (and a leftover final file). True when nothing of it remains. Never raises."""
    try:
        final = resolve_destination(dest_root, rel_dest)
    except ValueError:
        return False
    clean = True
    for path in (final + ".partial", final):
        try:
            if os.path.lexists(path) and not os.path.isdir(path):
                os.unlink(path)
        except OSError:
            clean = False
    return clean


def _text(code: str, status: Optional[int] = None) -> Tuple[str, str]:
    return RESUMABLE_MESSAGES.get(code) or _EXTRA_MESSAGES.get(code) or message_for(code, status)


def download_resumable(url: str, dest_root: str, rel_dest: str, *, gate: PermissionGate, expected_sha256: str, size_hint: int,
                       max_bytes: int, policy: Optional[FetchPolicy] = None, transport=None,
                       progress: Optional[Callable[[str, int, int], None]] = None,
                       should_cancel: Optional[Callable[[], bool]] = None,
                       allowed_hosts: Optional[Sequence[str]] = None,
                       free_space_fn: Callable[[str], object] = shutil.disk_usage, attempts: int = 12,
                       backoff_s: Sequence[float] = (2.0, 5.0, 10.0, 20.0, 30.0, 60.0), connection_s: float = 1800.0,
                       overall_s: float = 12 * 3600.0, size_tolerance: float = 0.30,
                       sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> ResumableResult:
    """Download `url` to `dest_root/rel_dest`, resuming from `<dest>.partial`, verified against `expected_sha256`.

    `size_hint` is the approximate size the caller knows (a transfer announcing a length outside `size_hint * (1 +- size_tolerance)`, or beyond
    `max_bytes`, is refused). `progress(phase, done, total)` gets phase "download" or "verify". Never raises for runtime errors; a wrong
    argument type or range is a programming error and raises ValueError."""
    for name, value, low, high in (("max_bytes", max_bytes, 1, _MAX_BYTES_LIMIT), ("size_hint", size_hint, 1, _MAX_BYTES_LIMIT),
                                   ("attempts", attempts, 1, 200)):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError("%s must be an integer between %d and %d" % (name, low, high))
    if size_hint > max_bytes:
        raise ValueError("size_hint must not exceed max_bytes")
    if not isinstance(size_tolerance, (int, float)) or isinstance(size_tolerance, bool) or not 0 <= size_tolerance <= 1:
        raise ValueError("size_tolerance must be between 0 and 1")
    job = _Job(url, dest_root, rel_dest, gate, expected_sha256, size_hint, max_bytes, policy or FetchPolicy(), transport, progress,
               should_cancel, allowed_hosts, free_space_fn, attempts, tuple(float(x) for x in backoff_s) or (1.0,), float(connection_s),
               float(overall_s), float(size_tolerance), sleep, clock)
    try:
        return job.run()
    except Exception as exc:  # last line of defence: the partial (if any) stays, nothing wrong is installed
        return job.finish("unknown_error", detail=type(exc).__name__)


class _Fatal(Exception):
    def __init__(self, code: str, detail: str = "", status: Optional[int] = None) -> None:
        super().__init__(code)
        self.code, self.detail, self.status = code, detail, status


class _Retry(Exception):
    def __init__(self, detail: str = "") -> None:
        super().__init__(detail)
        self.detail = detail


class _Cancelled(Exception):
    pass


class _Job:
    def __init__(self, url, dest_root, rel_dest, gate, expected, size_hint, max_bytes, policy, transport, progress, should_cancel,
                 allowed_hosts, free_space_fn, attempts, backoff, connection_s, overall_s, tolerance, sleep, clock) -> None:
        self.url, self.dest_root, self.rel_dest, self.gate = url, dest_root, rel_dest, gate
        self.expected = expected.lower() if isinstance(expected, str) else ""
        self.expected_ok = isinstance(expected, str) and bool(_SHA_RE.match(expected))
        self.size_hint, self.max_bytes, self.policy, self.transport = size_hint, max_bytes, policy, transport
        self.progress_cb, self.cancel_cb = progress, should_cancel
        self.allowed_hosts = tuple(h.lower().lstrip(".") for h in (allowed_hosts or ()))
        self.free_space_fn, self.attempts_limit, self.backoff = free_space_fn, attempts, backoff
        self.connection_s, self.overall_s = max(1.0, connection_s), max(1.0, overall_s)
        self.low = int(size_hint * (1.0 - tolerance))
        self.high = min(max_bytes, int(size_hint * (1.0 + tolerance)) + 1)
        self.sleep, self.clock = sleep, clock
        self.final = ""
        self.partial = ""
        self.have = 0
        self.total = 0
        self.attempt = 0
        self._reported = 0
        self._synced = 0

    # ------------------------------------------------------------------ results
    def finish(self, code: str, *, detail: str = "", status: Optional[int] = None, digest: str = "") -> ResumableResult:
        if code in _DISCARDS and self.partial:
            self._remove(self.partial)
        have = self._size_of(self.final if code == "ok" else self.partial)
        resumable = code != "ok" and code not in _DISCARDS and self.partial != "" and have > 0
        fa, en = _text(code, status)
        return ResumableResult(code == "ok", code, self.final if code == "ok" else "", have, self.total, digest if code == "ok" else "",
                               self.attempt, resumable, fa, en, detail)

    @staticmethod
    def _size_of(path: str) -> int:
        try:
            return int(os.path.getsize(path)) if path and os.path.isfile(path) and not os.path.islink(path) else 0
        except OSError:
            return 0

    @staticmethod
    def _remove(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    def _cancelled(self) -> bool:
        if self.cancel_cb is None:
            return False
        try:
            return bool(self.cancel_cb())
        except Exception:
            return False

    def _report(self, phase: str, done: int, total: int, force: bool = False) -> None:
        if self.progress_cb is None:
            return
        if not force and phase == "download" and done - self._reported < _PROGRESS_STEP:
            return
        self._reported = done
        try:
            self.progress_cb(phase, int(done), int(total))
        except Exception:
            pass

    def _network_allowed(self) -> bool:
        try:
            return bool(self.gate.allowed(NETWORK)) is True
        except Exception:
            return False

    # ------------------------------------------------------------------ the run
    def run(self) -> ResumableResult:
        if not self.expected_ok:
            return self.finish("invalid_hash")
        parsed = parse_url(self.url, self.policy)
        if isinstance(parsed, UrlError):
            return self.finish(parsed.code, detail=parsed.detail)
        if not self._host_ok(parsed.host):
            return self.finish("host_not_allowed", detail=parsed.host)
        if not self._network_allowed():
            return self.finish("permission_denied")
        try:
            self.final = resolve_destination(self.dest_root, self.rel_dest)
        except ValueError as err:
            return self.finish("invalid_destination", detail=str(err))
        self.partial = self.final + ".partial"
        if os.path.islink(self.partial):
            return self.finish("invalid_destination", detail="symlink_partial")
        send = self.transport if self.transport is not None else HttpClientTransport(self.policy)
        if not hasattr(send, "stream"):
            return self.finish("unknown_error", detail="transport_without_stream")
        self.parsed, self.send = parsed, send
        try:
            if os.path.isfile(self.final):                      # a final file from an earlier run: trust only its hash
                return self._verify_and_commit(existing_final=True)
            self.have = self._size_of(self.partial)
            if self.have > self.max_bytes:                      # cannot be a piece of the file we want
                self._remove(self.partial)
                self.have = 0
            try:
                free = _free_bytes(self.free_space_fn(os.path.realpath(self.dest_root)))
            except Exception:
                return self.finish("io_error", detail="disk_usage")
            needed = max(0, int(self.size_hint * 1.03) - self.have)
            if free < needed:
                return self.finish("insufficient_space", detail="need_%d_free_%d" % (needed, free))
            os.makedirs(os.path.dirname(self.final), exist_ok=True)
            return self._loop()
        except _Cancelled:
            return self.finish("cancelled")
        except _Fatal as err:
            return self.finish(err.code, detail=err.detail, status=err.status)
        except OSError as err:
            return self.finish("insufficient_space" if err.errno == errno.ENOSPC else "io_error", detail="write")

    def _host_ok(self, host: str) -> bool:
        if not self.allowed_hosts:
            return True
        host = (host or "").lower()
        return any(host == suffix or host.endswith("." + suffix) for suffix in self.allowed_hosts)

    def _loop(self) -> ResumableResult:
        started = self.clock()
        failures = 0
        while True:
            if self._cancelled():
                return self.finish("cancelled")
            if not self._network_allowed():
                return self.finish("permission_denied")
            if self.clock() - started > self.overall_s:
                return self.finish("interrupted", detail="overall_deadline")
            self.attempt += 1
            before = self.have
            try:
                self._one_connection()
                break
            except _Cancelled:
                return self.finish("cancelled")
            except _Retry as retry:
                detail = retry.detail
            if self.have > before:
                failures = 0
            failures += 1
            if failures >= self.attempts_limit:
                return self.finish("interrupted", detail=detail)
            if not self._wait(self.backoff[min(failures - 1, len(self.backoff) - 1)]):
                return self.finish("cancelled")
        return self._verify_and_commit()

    def _wait(self, seconds: float) -> bool:
        """Sleep in short slices; False when the stop was requested meanwhile."""
        left = float(seconds)
        while left > 0:
            if self._cancelled():
                return False
            step = min(_SLICE_S, left)
            self.sleep(step)
            left -= step
        return not self._cancelled()

    # ------------------------------------------------------------------ one connection
    def _one_connection(self) -> None:
        first: dict = {}
        start_at = self.have

        def release(response) -> None:                          # a redirect answer: keep the first one's own statements about the file
            if not first:
                headers = getattr(response, "headers", None) or {}
                for key in ("x-linked-size", "x-linked-etag"):
                    if key in headers:
                        first[key] = str(headers[key])
            try:
                response.close()
            except Exception:
                pass

        def call(parsed):
            if not self._host_ok(parsed.host):
                raise _Fatal("host_not_allowed", parsed.host)
            headers = {"Accept": "*/*"}
            if start_at > 0:
                headers["Range"] = "bytes=%d-" % start_at
            request = TransportRequest("GET", parsed.url, parsed.host, parsed.port, parsed.scheme, parsed.path_query, headers,
                                       self.policy.timeout_s, self.max_bytes, self.policy.oversize, self.connection_s)
            return self.send.stream(request)

        stream = None
        try:
            try:
                stream, _final, _hops = walk(call, self.parsed, self.policy, release=release)
            except HopFailure as fail:
                self._failed_status(fail.status, fail.code, fail.detail)
            except TransportError as err:
                self._transport_error(err)
            self._copy(stream, first, start_at)
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    def _transport_error(self, err: TransportError) -> None:
        if self._cancelled():
            raise _Cancelled()
        if err.code in _TRANSIENT_TRANSPORT:
            raise _Retry("%s:%s" % (err.code, err.detail) if err.detail else err.code)
        code = err.code if err.code in RESUMABLE_CODES else "unknown_error"
        raise _Fatal(code, err.detail)

    @staticmethod
    def _failed_status(status: Optional[int], code: str, detail: str) -> None:
        if status in _TRANSIENT_STATUS:
            raise _Retry("http_%s" % status)
        raise _Fatal(code if code in RESUMABLE_CODES else "http_error", detail, status)

    def _copy(self, stream, first: dict, start_at: int) -> None:
        status = int(getattr(stream, "status", 0) or 0)
        headers = getattr(stream, "headers", None) or {}
        if status == 416:                                       # asked for bytes past the end: the file is complete, or the partial is bogus
            match = _STAR_RANGE_RE.match(str(headers.get("content-range", "")).strip())
            if match and int(match.group(1)) == start_at and start_at > 0:
                self.total = start_at
                return
            self._remove(self.partial)
            self.have = 0
            raise _Retry("range_not_satisfiable")
        if status in _TRANSIENT_STATUS:
            raise _Retry("http_%d" % status)
        if status not in (200, 206):
            raise _Fatal("http_error", "status_%d" % status, status)
        media = str(headers.get("content-type", "")).split(";", 1)[0].strip().lower()
        if media in _REFUSED_TYPES:
            raise _Fatal("unsupported_content_type", media)
        if str(headers.get("content-encoding", "")).strip().lower() not in ("", "identity"):
            raise _Fatal("unsupported_encoding", "content_encoding")
        declared = getattr(stream, "declared_length", None)
        if declared is None:
            raw = str(headers.get("content-length", "")).strip()
            declared = int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= 13 else None
        if status == 206:
            match = _RANGE_RE.match(str(headers.get("content-range", "")).strip())
            if not match or int(match.group(1)) != start_at or start_at == 0:
                raise _Retry("bad_content_range")
            last = int(match.group(2))
            if declared is not None and declared != last - start_at + 1:
                raise _Retry("range_length_mismatch")
            total = int(match.group(3)) if match.group(3).isdigit() else (last + 1)
            offset = start_at
        else:                                                    # a plain 200 is the WHOLE file, whatever was asked
            total = declared if declared is not None else 0
            offset = 0
        self._check_remote(first, total)
        if total:
            self.total = total
        mode = "ab" if offset else "wb"
        if offset and self._size_of(self.partial) != offset:
            raise _Retry("partial_changed")
        self.have = offset
        self._reported = offset
        self._synced = offset
        with open(self.partial, mode) as handle:
            try:
                for chunk in stream.iter_chunks():
                    if self._cancelled():
                        handle.flush()
                        raise _Cancelled()
                    if self.have + len(chunk) > self.max_bytes:
                        raise _Fatal("too_large", "stream")
                    handle.write(chunk)
                    self.have += len(chunk)
                    if self.have - self._synced >= _SYNC_STEP:
                        handle.flush()
                        os.fsync(handle.fileno())
                        self._synced = self.have
                    self._report("download", self.have, self.total)
            except TransportError as err:
                handle.flush()
                self._transport_error(err)
            handle.flush()
            os.fsync(handle.fileno())
        self._report("download", self.have, self.total, force=True)
        if self.total and self.have < self.total:
            raise _Retry("ended_early")
        if self.total and self.have > self.total:
            raise _Fatal("size_mismatch", "more_than_announced")

    def _check_remote(self, first: dict, total: int) -> None:
        """The first answer's statements about the file, checked BEFORE any byte is stored."""
        etag = _ETAG_RE.match(str(first.get("x-linked-etag", "")).strip())
        if etag and etag.group(1).lower() != self.expected:
            raise _Fatal("remote_changed", "linked_etag")
        raw = str(first.get("x-linked-size", "")).strip()
        linked = int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= 13 else None
        if linked is not None and total and linked != total:
            raise _Fatal("size_mismatch", "linked_size_%d_announced_%d" % (linked, total))
        known = linked if linked is not None else total
        if known and not self.low <= known <= self.high:
            raise _Fatal("size_mismatch", "announced_%d" % known)
        if linked is not None and not total:
            self.total = linked

    # ------------------------------------------------------------------ verification and the atomic move
    def _verify_and_commit(self, existing_final: bool = False) -> ResumableResult:
        path = self.final if existing_final else self.partial
        size = self._size_of(path)
        if not 0 < size <= self.max_bytes or (self.total and size != self.total):
            self._remove(path)
            return self.finish("size_mismatch", detail="on_disk_%d" % size)
        digest = hashlib.sha256()
        done = 0
        try:
            with open(path, "rb") as handle:
                while True:
                    if self._cancelled():
                        return self.finish("cancelled")
                    chunk = handle.read(_HASH_CHUNK)
                    if not chunk:
                        break
                    digest.update(chunk)
                    done += len(chunk)
                    if self.progress_cb is not None and (done % (16 * _HASH_CHUNK) == 0 or done == size):
                        self._report("verify", done, size, force=True)
        except OSError:
            return self.finish("io_error", detail="read")
        actual = digest.hexdigest()
        if actual != self.expected:
            self._remove(path)
            return self.finish("hash_mismatch", detail="got_%s" % actual[:12])
        if not existing_final:
            try:
                os.replace(self.partial, self.final)
                _fsync_dir(os.path.dirname(self.final))
            except OSError:
                return self.finish("io_error", detail="rename")
        self.have = size
        self.total = self.total or size
        return self.finish("ok", digest=actual)
