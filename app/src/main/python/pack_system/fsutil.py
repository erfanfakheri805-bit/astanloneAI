"""
pack_system.fsutil - small, strict file helpers (stdlib only; the boot path must not depend on anything else)
=============================================================================================================
`write_json_atomic` / `read_json_bounded` / `write_text_atomic` follow the same rules as the hub's helpers: a temp file
in the same directory, fsync, `os.replace`; links and oversized files are refused; nothing is created at import time.
"""

import hashlib
import json
import os
import shutil

__all__ = ["write_json_atomic", "read_json_bounded", "write_text_atomic", "set_aside", "sha256_text", "sha256_bytes",
           "remove_tree", "fsync_dir", "make_readonly"]


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def write_text_atomic(path, text):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(temp, "wb") as handle:
            handle.write(text.encode("utf-8"))
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


def write_json_atomic(path, obj):
    write_text_atomic(path, json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n")


def read_json_bounded(path, max_bytes):
    """The parsed JSON of a regular file of at most `max_bytes`; ValueError otherwise (FileNotFoundError when absent)."""
    if os.path.islink(path):
        raise ValueError("a link is not accepted")
    if os.path.getsize(path) > max_bytes:
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
    """Move a damaged file or folder to `<path>.corrupt.<n>`; the new base name, or '' when that failed."""
    number = 1
    while os.path.exists("%s.corrupt.%d" % (path, number)):
        number += 1
    target = "%s.corrupt.%d" % (path, number)
    try:
        os.replace(path, target)
    except OSError:
        return ""
    return os.path.basename(target)


def make_readonly(root):
    """Best effort: strip write permission from every file under `root` (Android 14 wants code files read-only)."""
    for base, _dirs, names in os.walk(root):
        for name in names:
            try:
                os.chmod(os.path.join(base, name), 0o444)
            except OSError:
                pass


def remove_tree(path):
    """Delete a folder tree (also when its files were made read-only). Never raises; True when it is gone."""
    if not os.path.lexists(path):
        return True

    def _onexc(func, target, _exc):
        try:
            os.chmod(target, 0o700)
            func(target)
        except OSError:
            pass
    try:
        shutil.rmtree(path, onexc=_onexc)
    except OSError:
        pass
    return not os.path.lexists(path)
