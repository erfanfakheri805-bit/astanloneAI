"""
Self-Builder - workspace lock
=============================
Everything that CHANGES the workspace - a build (staging files, promoting
them, registering the version), a rollback, a disable, the start-up
reconciliation that clears leftovers - runs while holding ONE lock per
workspace root. Two builds can therefore never share a staging file, and the
start-up clean-up of a second process can never delete the staged files of a
build that is still running in the first one. Reading (calling a capability,
listing, history) needs no lock.

The lock is an exclusive transaction on a tiny, empty SQLite file
(`<root>/self_builder.lock`):

  * it works between threads, between services and between processes;
  * the operating system releases it when the holder disappears, so an app
    that is killed in the middle of a build can never leave it locked
    (no pid files, no stale-lock heuristics);
  * nothing is ever written into that file.

A connection is opened when the lock is taken and closed when it is released,
so the lock object holds no resource between two builds.
"""

import contextlib
import sqlite3
import threading
import time

from . import policy
from .errors import ApplyError


class WorkspaceLock:
    """Re-entrant (per thread) exclusive lock of one workspace root."""

    def __init__(self, path):
        self._path = path
        self._thread_lock = threading.RLock()
        self._conn = None
        self._depth = 0

    def _timeout(self, timeout):
        return float(policy.LOCK_TIMEOUT_SECONDS if timeout is None else timeout)

    def acquire(self, timeout=None):
        """True when the lock is held by the calling thread afterwards;
        False when another thread/service/process kept it for `timeout` seconds."""
        timeout = self._timeout(timeout)
        started = time.monotonic()
        if not self._thread_lock.acquire(timeout=max(timeout, 0.0)):
            return False
        try:
            if self._depth == 0:
                remaining = max(timeout - (time.monotonic() - started), 0.0)
                conn = sqlite3.connect(self._path, timeout=remaining, isolation_level=None, check_same_thread=False)
                try:
                    conn.execute("BEGIN EXCLUSIVE")
                except sqlite3.OperationalError:
                    conn.close()
                    self._thread_lock.release()
                    return False
                except BaseException:
                    conn.close()
                    raise
                self._conn = conn
            self._depth += 1
            return True
        except BaseException:
            if self._depth == 0:
                self._thread_lock.release()
            raise

    def release(self):
        if self._depth <= 0:
            raise RuntimeError("the workspace lock is not held")
        self._depth -= 1
        try:
            if self._depth == 0:
                conn, self._conn = self._conn, None
                try:
                    conn.execute("ROLLBACK")      # nothing was written: this only releases the lock
                except sqlite3.Error:
                    pass
                finally:
                    conn.close()
        finally:
            self._thread_lock.release()

    @contextlib.contextmanager
    def held(self, timeout=None):
        """`with lock.held():` - raises ApplyError(E_BUILD_BUSY) when the lock cannot be had in time."""
        if not self.acquire(timeout):
            raise ApplyError("another change of the capability registry is still running",
                             code="E_BUILD_BUSY", waited_seconds=self._timeout(timeout))
        try:
            yield self
        finally:
            self.release()

    def held_here(self):
        """Does the calling thread hold the lock right now?"""
        if self._depth <= 0:
            return False
        # the re-entrant lock can only be acquired again by its owner
        if self._thread_lock.acquire(blocking=False):
            self._thread_lock.release()
            return True
        return False


__all__ = ["WorkspaceLock"]
