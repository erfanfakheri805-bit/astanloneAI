"""
Self-Builder - persistent store
===============================
One SQLite file (`<root>/self_builder.db`) holds everything the Self-Builder
must remember across restarts:

  capabilities          the registry: one row per capability
  capability_versions   every version ever applied (spec, file names, hashes,
                        validation + test reports, status) - nothing is
                        overwritten, so every older version can be restored
  upgrade_log           one row per attempted upgrade: request, plan, changes,
                        every generate/validate/test/repair attempt, result,
                        rollback information, error
  checkpoints           the recoverable "before" state of each upgrade
  audit_log             append-only, hash-chained event log
  usage / feedback      per-version call counters and user feedback
  meta                  schema version

Schema changes go through numbered migrations (`MIGRATIONS`): each one runs in
its own transaction, only adds structure, and records the new version.

Concurrency: the application server is threaded, so every call is serialised
by one re-entrant lock; mutations run inside `transaction()`
(BEGIN IMMEDIATE ... COMMIT / ROLLBACK).
"""

import contextlib
import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone

from . import policy
from .errors import StoreError

GENESIS_HASH = "0" * 64


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads(text, default=None):
    if text is None:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


_SCHEMA_1 = """
        CREATE TABLE IF NOT EXISTS capabilities(
            capability_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            active_version INTEGER,
            latest_version INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS capability_versions(
            capability_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            fingerprint TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            spec_file TEXT NOT NULL,
            spec_sha256 TEXT NOT NULL,
            module_file TEXT NOT NULL,
            module_sha256 TEXT NOT NULL,
            tests_file TEXT NOT NULL,
            tests_sha256 TEXT NOT NULL,
            inputs_json TEXT NOT NULL,
            outputs_json TEXT NOT NULL,
            dependencies_json TEXT NOT NULL,
            permissions_json TEXT NOT NULL,
            validation_json TEXT NOT NULL,
            test_report_json TEXT NOT NULL,
            status TEXT NOT NULL,
            parent_version INTEGER,
            upgrade_id INTEGER,
            checkpoint_id INTEGER,
            rollback_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            PRIMARY KEY(capability_id, version)
        );
        CREATE TABLE IF NOT EXISTS upgrade_log(
            upgrade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            capability_id TEXT,
            request_text TEXT,
            plan_json TEXT NOT NULL,
            changes_json TEXT NOT NULL,
            attempts_json TEXT NOT NULL,
            validation_json TEXT NOT NULL,
            test_json TEXT NOT NULL,
            result TEXT NOT NULL,
            version INTEGER,
            rollback_json TEXT,
            error_code TEXT,
            error_detail TEXT,
            created_at TEXT NOT NULL,
            finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS checkpoints(
            checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            upgrade_id INTEGER NOT NULL,
            capability_id TEXT NOT NULL,
            from_version INTEGER,
            to_version INTEGER,
            files_json TEXT NOT NULL,
            registry_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log(
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            event TEXT NOT NULL,
            capability_id TEXT,
            version INTEGER,
            upgrade_id INTEGER,
            detail_json TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            entry_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS usage(
            capability_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            calls INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0,
            last_used_at TEXT,
            PRIMARY KEY(capability_id, version)
        );
        CREATE TABLE IF NOT EXISTS feedback(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            capability_id TEXT,
            version INTEGER,
            polarity TEXT NOT NULL,
            text TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_versions_status ON capability_versions(capability_id, status);
        CREATE INDEX IF NOT EXISTS idx_upgrade_log_cap ON upgrade_log(capability_id);
        CREATE INDEX IF NOT EXISTS idx_audit_cap ON audit_log(capability_id);
        """


def _run_script(conn, script):
    """Run a ';'-separated DDL script statement by statement (sqlite3's
    executescript() would COMMIT the surrounding transaction first)."""
    for statement in script.split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)


def _migration_1(conn):
    _run_script(conn, _SCHEMA_1)


# version -> function(conn). Add `_migration_2` etc. here to evolve the schema;
# every migration must be idempotent and must not drop or rewrite data.
MIGRATIONS = {1: _migration_1}


class Store:
    def __init__(self, db_path, migrations=None):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._tx_depth = 0
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        try:
            try:
                self._conn.execute("PRAGMA synchronous = FULL")
                self._conn.execute("PRAGMA foreign_keys = ON")
            except sqlite3.DatabaseError as e:
                raise StoreError(f"database unusable: {e}", code="E_STORE_OPEN") from None
            self._migrations = dict(MIGRATIONS if migrations is None else migrations)
            self._migrate()
        except BaseException:
            self._conn.close()          # a store that could not be opened must not keep the file open
            raise

    # ------------------------------------------------------------ plumbing
    @contextlib.contextmanager
    def transaction(self):
        """Serialised BEGIN IMMEDIATE ... COMMIT (ROLLBACK on any exception).
        Re-entrant: an inner `with` joins the outer transaction."""
        with self._lock:
            if self._tx_depth > 0:
                self._tx_depth += 1
                try:
                    yield self
                finally:
                    self._tx_depth -= 1
                return
            self._conn.execute("BEGIN IMMEDIATE")
            self._tx_depth = 1
            try:
                yield self
            except BaseException:
                self._tx_depth = 0
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            else:
                self._tx_depth = 0
                self._conn.execute("COMMIT")

    def execute(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params)

    def query(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    # ----------------------------------------------------------- migrations
    def schema_version(self):
        row = None
        try:
            row = self.query_one("SELECT value FROM meta WHERE key = 'schema_version'")
        except sqlite3.OperationalError:
            return 0
        return int(row["value"]) if row else 0

    def _migrate(self):
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            current = self.schema_version()
            target = max(self._migrations) if self._migrations else 0
            if current > target:
                raise StoreError(f"database schema {current} is newer than this build supports ({target})",
                                 code="E_STORE_NEWER_SCHEMA", found=current, supported=target)
            for version in sorted(v for v in self._migrations if v > current):
                with self.transaction():
                    self._migrations[version](self._conn)
                    self._conn.execute(
                        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(version),))

    # ---------------------------------------------------------------- audit
    def last_audit_hash(self):
        row = self.query_one("SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1")
        return row["entry_hash"] if row else GENESIS_HASH

    def audit(self, event, capability_id=None, version=None, upgrade_id=None, detail=None):
        """Append one hash-chained audit entry (call inside the same
        transaction as the change it records)."""
        with self._lock:
            ts = now_iso()
            detail_json = dumps(detail or {})
            prev = self.last_audit_hash()
            body = dumps([ts, event, capability_id, version, upgrade_id, detail_json])
            entry_hash = hashlib.sha256((prev + body).encode("utf-8")).hexdigest()
            cur = self._conn.execute(
                "INSERT INTO audit_log(ts, event, capability_id, version, upgrade_id, detail_json, "
                "prev_hash, entry_hash) VALUES (?,?,?,?,?,?,?,?)",
                (ts, event, capability_id, version, upgrade_id, detail_json, prev, entry_hash))
            return cur.lastrowid

    def verify_audit_chain(self):
        """(ok, bad_seq, count): recomputes the whole chain."""
        prev = GENESIS_HASH
        count = 0
        for row in self.query("SELECT * FROM audit_log ORDER BY seq"):
            body = dumps([row["ts"], row["event"], row["capability_id"], row["version"],
                          row["upgrade_id"], row["detail_json"]])
            expected = hashlib.sha256((prev + body).encode("utf-8")).hexdigest()
            if row["prev_hash"] != prev or row["entry_hash"] != expected:
                return False, row["seq"], count
            prev = row["entry_hash"]
            count += 1
        return True, None, count

    def audit_entries(self, limit=50, capability_id=None):
        if capability_id:
            rows = self.query("SELECT * FROM audit_log WHERE capability_id = ? ORDER BY seq DESC LIMIT ?",
                              (capability_id, int(limit)))
        else:
            rows = self.query("SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?", (int(limit),))
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- counters
    def counts(self):
        out = {}
        for table in ("capabilities", "capability_versions", "upgrade_log", "audit_log", "checkpoints"):
            out[table] = self.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"]
        return out
