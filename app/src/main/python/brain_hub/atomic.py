"""
brain_hub.atomic - small, strict file helpers shared by the hub
================================================================
* `write_json_atomic(path, obj)`: temp file in the same directory -> flush -> fsync -> `os.replace` (an exception in
  between leaves the previous file untouched and removes the temp file); the directory entry is fsynced best-effort.
* `read_json_bounded(path, max_bytes)`: reads a JSON file that is a regular file (never a symlink), at most
  `max_bytes` long; raises `ValueError` for anything else (the caller decides to fail closed).
* `set_aside(path)`: moves a damaged file to `<path>.corrupt.<n>` and returns its new base name ('' when that failed).
Nothing here is created at import time.
"""

import json
import os

__all__ = ["write_json_atomic", "read_json_bounded", "set_aside", "fsync_dir"]


def fsync_dir(directory):
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_json_atomic(path, obj):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    data = (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")
    temp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    fsync_dir(directory)


def read_json_bounded(path, max_bytes):
    """The parsed JSON of a regular file of at most `max_bytes`; `ValueError` otherwise (missing file: FileNotFoundError)."""
    if os.path.islink(path):
        raise ValueError("a link is not accepted")
    size = os.path.getsize(path)
    if size > max_bytes:
        raise ValueError("file too large")
    with open(path, "rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("file too large")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, RecursionError) as exc:
        raise ValueError("unreadable JSON") from exc


def set_aside(path):
    number = 1
    while os.path.exists("%s.corrupt.%d" % (path, number)):
        number += 1
    target = "%s.corrupt.%d" % (path, number)
    try:
        os.replace(path, target)
    except OSError:
        return ""
    return os.path.basename(target)
