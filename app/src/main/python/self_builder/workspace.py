"""
Self-Builder - workspace (the only place files are touched)
===========================================================
Every file the Self-Builder reads, writes, moves or removes goes through this
class, and every path goes through `Policy.resolve()` first: allowed
directory, allowed name pattern, allowed suffix, no symlinks, inside the root.

Writes are atomic (temp file in the same directory, fsync, `os.replace`) so a
crash can leave either the old file or the new file, never half of one; the
startup reconciliation (loader.py) deals with whatever a crash did leave.
"""

import json
import os
import time

from . import policy
from .errors import PolicyViolation
from .lock import WorkspaceLock
from .policy import Policy

_SUBDIRS = (
    policy.SUBDIR_STAGING, policy.SUBDIR_MODULES, policy.SUBDIR_TESTS,
    policy.SUBDIR_SPECS, policy.SUBDIR_CHECKPOINTS, policy.SUBDIR_QUARANTINE,
)


def _fsync_dir(path):
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


class Workspace:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        for sub in _SUBDIRS:
            os.makedirs(os.path.join(self.root, sub), exist_ok=True)
        self.lock = WorkspaceLock(Policy.resolve(self.root, None, policy.ROOT_FILE_LOCK))

    # ------------------------------------------------------------------ paths
    def path(self, subdir, name):
        return Policy.resolve(self.root, subdir, name)

    def db_path(self):
        return Policy.resolve(self.root, None, policy.ROOT_FILE_DB)

    def manifest_path(self):
        return Policy.resolve(self.root, None, policy.ROOT_FILE_MANIFEST)

    # ------------------------------------------------------------------ files
    def exists(self, subdir, name):
        return os.path.isfile(self.path(subdir, name))

    def read(self, subdir, name, limit=policy.MAX_TESTS_BYTES):
        with open(self.path(subdir, name), "rb") as f:
            data = f.read(limit + 1)
        if len(data) > limit:
            raise PolicyViolation(f"file larger than {limit} bytes: {name}", code="E_POLICY_SIZE")
        return data

    def write(self, subdir, name, data, operation):
        """Atomically create/replace one allowed file. `data`: bytes or str."""
        Policy.check_operation(operation)
        if isinstance(data, str):
            data = data.encode("utf-8")
        limit = policy.MAX_SOURCE_BYTES if subdir in (policy.SUBDIR_MODULES, policy.SUBDIR_STAGING) \
            and name.endswith(".py") else policy.MAX_TESTS_BYTES
        if len(data) > limit:
            raise PolicyViolation(f"file larger than {limit} bytes: {name}", code="E_POLICY_SIZE")
        final = self.path(subdir, name)
        tmp = final + f".part{os.getpid()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, final)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        _fsync_dir(os.path.dirname(final))
        return final

    def write_root_file(self, name, data, operation):
        Policy.check_operation(operation)
        if isinstance(data, str):
            data = data.encode("utf-8")
        final = Policy.resolve(self.root, None, name)
        tmp = final + f".part{os.getpid()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, final)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        _fsync_dir(self.root)
        return final

    def move(self, src_subdir, src_name, dst_subdir, dst_name, operation):
        Policy.check_operation(operation)
        src = self.path(src_subdir, src_name)
        dst = self.path(dst_subdir, dst_name)
        os.replace(src, dst)
        _fsync_dir(os.path.dirname(dst))
        return dst

    def remove(self, subdir, name):
        Policy.check_operation(policy.OP_REMOVE_STAGED if subdir == policy.SUBDIR_STAGING else policy.OP_RESTORE)
        path = self.path(subdir, name)
        try:
            os.unlink(path)
            return True
        except FileNotFoundError:
            return False

    def listdir(self, subdir):
        if subdir not in _SUBDIRS:
            raise PolicyViolation(f"directory not allowed: {subdir!r}", code="E_POLICY_DIR")
        directory = os.path.join(self.root, subdir)
        try:
            return sorted(n for n in os.listdir(directory) if ".part" not in n)
        except FileNotFoundError:
            return []

    def quarantine(self, subdir, name, reason):
        """Move an unexpected/untrusted file out of the way (never deleted)."""
        Policy.check_operation(policy.OP_QUARANTINE)
        src = os.path.join(self.root, subdir, name)
        if os.path.islink(src):
            os.unlink(src)  # a symlink is never followed or kept
            return None
        if not os.path.isfile(src):
            return None
        def plain(c):      # ASCII letters and digits only: a Persian or exotic file name must still be quarantinable
            return c.isascii() and c.isalnum()
        safe_reason = "".join(c for c in reason if plain(c) or c in "_-")[:24] or "unknown"
        safe_name = "".join(c if plain(c) or c in "_.-" else "_" for c in name)[:100]
        # the directory is part of the name: `tests/x_v1.json` and `specs/x_v1.json` are different files,
        # and a file that is quarantined twice in the same second must not replace the first copy either
        stem, ext = os.path.splitext(f"q_{int(time.time())}_{safe_reason}_{subdir}_{safe_name}")
        if ext not in policy.ALLOWED_SUFFIXES:     # a stray "evil.sh" is kept as evidence, under an allowed type
            stem, ext = stem + ext.replace(".", "_"), ".json"
        qname = stem + ext
        for n in range(2, 1000):
            if not os.path.lexists(os.path.join(self.root, policy.SUBDIR_QUARANTINE, qname)):
                break
            qname = f"{stem}_{n}{ext}"
        dst = self.path(policy.SUBDIR_QUARANTINE, qname)
        os.replace(src, dst)
        return qname

    def clear_staging(self):
        removed = []
        directory = os.path.join(self.root, policy.SUBDIR_STAGING)
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            try:
                if os.path.isfile(path) or os.path.islink(path):
                    os.unlink(path)
                    removed.append(name)
            except OSError:
                pass
        return removed

    def sweep_partials(self):
        """Remove leftover temp files (`*.part<pid>`) of an interrupted atomic
        write, in every Self-Builder directory. Returns the removed names."""
        removed = []
        for sub in _SUBDIRS + (None,):
            directory = self.root if sub is None else os.path.join(self.root, sub)
            try:
                names = os.listdir(directory)
            except FileNotFoundError:
                continue
            for name in names:
                if ".part" not in name:
                    continue
                path = os.path.join(directory, name)
                try:
                    if os.path.isfile(path) or os.path.islink(path):
                        os.unlink(path)
                        removed.append(name)
                except OSError:
                    pass
        return removed

    # --------------------------------------------------------------- manifest
    def write_manifest(self, manifest):
        text = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1)
        return self.write_root_file(policy.ROOT_FILE_MANIFEST, text, policy.OP_WRITE_MANIFEST)

    def read_manifest(self):
        path = self.manifest_path()
        try:
            with open(path, "rb") as f:
                return json.loads(f.read(policy.MAX_TESTS_BYTES * 4).decode("utf-8"))
        except (OSError, ValueError):
            return None
