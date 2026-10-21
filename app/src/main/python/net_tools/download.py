"""
net_tools.download - save one file from https, verified, or save nothing
=======================================================================
`download_file(...)` writes a remote file under `dest_root/rel_dest` only if
EVERYTHING checks out:

* https only (plain http only with an explicit policy), permission "network"
  granted, an expected SHA-256 supplied by the caller (REQUIRED);
* the destination is a clean relative path under `dest_root` (no `..`, no
  absolute path, no odd characters, no symlink on the way);
* enough free space (>= 1.1 x `max_bytes`);
* the body streams into `<dest>.partial` next to the destination while being
  hashed, never beyond `max_bytes`, under one wall-clock deadline; HTML answers
  (captive portals, error pages) are refused;
* only a matching hash leads to fsync + atomic `os.replace`.

Any failure deletes the partial file and leaves nothing at the destination.
The result's `ok` is True only when the verified file is in place.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import asdict, dataclass
from typing import Callable, Optional, Tuple

from .fetch import build_request, message_for
from .permission import NETWORK, PermissionGate
from .policy import FetchPolicy, UrlError, parse_url
from .redirects import HopFailure, walk
from .transport import HttpClientTransport, TransportError

__all__ = ["DownloadResult", "download_file", "download_message", "resolve_destination", "DOWNLOAD_CODES"]

DOWNLOAD_CODES = (
    "ok", "invalid_url", "unsupported_scheme", "blocked_address", "permission_denied", "invalid_hash",
    "invalid_destination", "insufficient_space", "dns_failure", "offline", "connect_refused", "timeout", "tls_error",
    "too_large", "unsupported_content_type", "unsupported_encoding", "http_error", "too_many_redirects",
    "protocol_error", "hash_mismatch", "io_error", "unknown_error",
)
_EXTRA_MESSAGES = {
    "ok": ("فایل دانلود و صحت آن تأیید شد.", "The file was downloaded and verified."),
    "invalid_hash": ("هش SHA-256 مورد انتظار معتبر نیست؛ بدون آن دانلود انجام نمی‌شود.",
                     "The expected SHA-256 is not valid; nothing is downloaded without it."),
    "invalid_destination": ("مسیر ذخیره امن نیست و رد شد.", "The destination path is not safe and was refused."),
    "insufficient_space": ("فضای خالی برای دانلود کافی نیست.", "There is not enough free space for this download."),
    "hash_mismatch": ("هش فایل دانلودشده با مقدار مورد انتظار نمی‌خواند؛ فایل دور ریخته شد.",
                      "The downloaded file does not match the expected hash; it was discarded."),
    "io_error": ("نوشتن فایل روی دستگاه ناموفق بود.", "Writing the file on this device failed."),
}


def download_message(code: str) -> Tuple[str, str]:
    """(Persian, English) sentence for a download result code; an unknown code gets the generic one."""
    return _EXTRA_MESSAGES.get(code) or message_for(code)


_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_REFUSED_TYPES = ("text/html", "application/xhtml+xml")
_MAX_BYTES_LIMIT = 8 * 2 ** 30
_CHUNK_ACCEPT = "*/*"


@dataclass(frozen=True)
class DownloadResult:
    ok: bool
    code: str
    path: str
    bytes_written: int
    sha256: str
    message_fa: str
    message_en: str
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _result(code: str, *, path: str = "", written: int = 0, digest: str = "", detail: str = "",
            status: Optional[int] = None) -> DownloadResult:
    fa, en = _EXTRA_MESSAGES.get(code) or message_for(code, status)
    return DownloadResult(code == "ok", code, path if code == "ok" else "", written, digest, fa, en, detail)


def resolve_destination(dest_root: str, rel_dest: str) -> str:
    """Absolute destination path for `rel_dest` under `dest_root`; raises ValueError(reason) when unsafe."""
    if not isinstance(dest_root, str) or not dest_root or "\x00" in dest_root:
        raise ValueError("bad_root")
    if not isinstance(rel_dest, str) or not rel_dest or len(rel_dest) > 240 or "\x00" in rel_dest or "\\" in rel_dest:
        raise ValueError("bad_relative_path")
    if rel_dest.startswith("/") or (len(rel_dest) > 1 and rel_dest[1] == ":"):
        raise ValueError("absolute_path")
    parts = rel_dest.split("/")
    for part in parts:
        if part in ("", ".", "..") or not _COMPONENT_RE.match(part):
            raise ValueError("bad_component")
    if parts[-1].endswith(".partial"):
        raise ValueError("reserved_suffix")
    root = os.path.realpath(dest_root)
    if not os.path.isdir(root):
        raise ValueError("root_missing")
    current = root
    for part in parts:
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise ValueError("symlink_in_path")
    if os.path.commonpath([root, current]) != root or current == root:
        raise ValueError("outside_root")
    if os.path.isdir(current):
        raise ValueError("is_directory")
    return current


def _free_bytes(usage: object) -> int:
    free = getattr(usage, "free", None)
    return int(free if free is not None else usage[2])  # type: ignore[index]


def _fsync_dir(path: str) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def download_file(url: str, dest_root: str, rel_dest: str, *, gate: PermissionGate, expected_sha256: str,
                  max_bytes: int, policy: Optional[FetchPolicy] = None, transport=None,
                  progress: Optional[Callable[[int, Optional[int]], None]] = None,
                  free_space_fn: Callable[[str], object] = shutil.disk_usage,
                  deadline_s: float = 900.0) -> DownloadResult:
    """Download `url` to `dest_root/rel_dest`, verified against `expected_sha256`.

    Never raises for runtime (network / disk / user-input) errors; a wrong `max_bytes` is a programming error
    and raises ValueError.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= _MAX_BYTES_LIMIT:
        raise ValueError("max_bytes must be an integer between 1 and 8 GiB")
    try:
        return _download(url, dest_root, rel_dest, gate, expected_sha256, max_bytes, policy or FetchPolicy(),
                         transport, progress, free_space_fn, deadline_s)
    except Exception as exc:  # last line of defence
        return _result("unknown_error", detail=type(exc).__name__)


def _download(url, dest_root, rel_dest, gate, expected, max_bytes, policy, transport, progress, free_space_fn,
              deadline_s) -> DownloadResult:
    if not isinstance(expected, str) or not _SHA_RE.match(expected):
        return _result("invalid_hash")
    expected = expected.lower()
    deadline_s = float(min(max(deadline_s, 1.0), 6 * 3600.0))
    parsed = parse_url(url, policy)
    if isinstance(parsed, UrlError):
        return _result(parsed.code, detail=parsed.detail)
    try:
        allowed = bool(gate.allowed(NETWORK)) is True
    except Exception:
        allowed = False
    if not allowed:
        return _result("permission_denied")
    try:
        final_path = resolve_destination(dest_root, rel_dest)
    except ValueError as err:
        return _result("invalid_destination", detail=str(err))
    root = os.path.realpath(dest_root)
    try:
        free = _free_bytes(free_space_fn(root))
    except Exception:
        return _result("io_error", detail="disk_usage")
    if free < max_bytes * 1.1:
        return _result("insufficient_space", detail="need_%d_free_%d" % (int(max_bytes * 1.1), free))
    send = transport if transport is not None else HttpClientTransport(policy)
    if not hasattr(send, "stream"):
        return _result("unknown_error", detail="transport_without_stream")

    def call(p):
        return send.stream(build_request(p, policy, accept=_CHUNK_ACCEPT, total_timeout_s=deadline_s, max_bytes=max_bytes))

    stream = None
    try:
        try:
            stream, _final, _hops = walk(call, parsed, policy, release=lambda r: r.close())
        except HopFailure as fail:
            return _result(fail.code, detail=fail.detail, status=fail.status)
        except TransportError as err:
            return _result(err.code if err.code in DOWNLOAD_CODES else "unknown_error", detail=err.detail)
        return _store(stream, final_path, expected, max_bytes, progress)
    finally:
        if stream is not None:
            stream.close()


def _store(stream, final_path: str, expected: str, max_bytes: int, progress) -> DownloadResult:
    status = int(getattr(stream, "status", 0) or 0)
    if status != 200:
        return _result("http_error", status=status)
    headers = getattr(stream, "headers", None) or {}
    media = str(headers.get("content-type", "")).split(";", 1)[0].strip().lower()
    if media in _REFUSED_TYPES:
        return _result("unsupported_content_type", detail=media)
    encoding = str(headers.get("content-encoding", "")).strip().lower()
    if encoding not in ("", "identity"):
        return _result("unsupported_encoding")
    declared = getattr(stream, "declared_length", None)
    if declared is None:
        raw = str(headers.get("content-length", "")).strip()
        declared = int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= 12 else None
    if declared is not None and declared > max_bytes:
        return _result("too_large", detail="content_length")
    partial = final_path + ".partial"
    parent = os.path.dirname(final_path)
    digest = hashlib.sha256()
    written, committed = 0, False
    try:
        os.makedirs(parent, exist_ok=True)
        if os.path.islink(partial):
            return _result("invalid_destination", detail="symlink_partial")
        with open(partial, "wb") as handle:
            for chunk in stream.iter_chunks():
                written += len(chunk)
                if written > max_bytes:
                    return _result("too_large", detail="stream")
                digest.update(chunk)
                handle.write(chunk)
                if progress is not None:
                    try:
                        progress(written, declared)
                    except Exception:
                        pass
            handle.flush()
            os.fsync(handle.fileno())
        actual = digest.hexdigest()
        if actual != expected:
            return _result("hash_mismatch", written=written, digest=actual)
        os.replace(partial, final_path)
        committed = True
        _fsync_dir(parent)
        return _result("ok", path=final_path, written=written, digest=actual)
    except TransportError as err:
        return _result(err.code if err.code in DOWNLOAD_CODES else "unknown_error", detail=err.detail)
    except OSError:
        return _result("io_error", detail="write")
    finally:
        if not committed:
            try:
                os.unlink(partial)
            except OSError:
                pass
