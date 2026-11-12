"""
brain_v2.store - tiny private-file helpers for the cloud brain's own files
==========================================================================
Everything the cloud brain keeps (settings, the key, the short chat history, the answer memory) lives in ONE folder of
the application's private data (`<hub root>/brain_v2/`). These helpers make sure that

* a file is written atomically (temp file in the same folder -> flush -> fsync -> `os.replace`): a crash in the middle leaves
  the previous file untouched, never a half-written one;
* the file is created with mode 0600 (owner only) - on Android the folder is also private to the app, this is the second lock;
* a file that is a symlink, too large, or not valid UTF-8 / JSON is refused (`ValueError`), and `set_aside()` moves a damaged
  file out of the way so a fresh one can be started (the old bytes are kept for inspection, never silently deleted).
"""

import json
import os

from brain_hub import atomic

__all__ = ["write_private_text", "write_private_json", "read_text", "read_json", "set_aside", "remove"]

PRIVATE_MODE = 0o600


def write_private_text(path, text, mode=PRIVATE_MODE):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    temp = "%s.%d.tmp" % (path, os.getpid())
    data = str(text).encode("utf-8")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    atomic.fsync_dir(directory)


def write_private_json(path, obj, mode=PRIVATE_MODE):
    write_private_text(path, json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n", mode)


def read_text(path, max_bytes):
    """The text of a regular file of at most `max_bytes`; FileNotFoundError when missing, ValueError for anything odd."""
    if os.path.islink(path):
        raise ValueError("a link is not accepted")
    if os.path.getsize(path) > max_bytes:
        raise ValueError("file too large")
    with open(path, "rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("file too large")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("not text") from exc


def read_json(path, max_bytes):
    try:
        return json.loads(read_text(path, max_bytes))
    except RecursionError as exc:
        raise ValueError("too deep") from exc


def set_aside(path):
    return atomic.set_aside(path)


def remove(path):
    """Delete a file if it exists (a symlink is removed itself, never followed). True when nothing is left behind."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True
