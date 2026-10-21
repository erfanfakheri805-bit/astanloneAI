"""
Extension runtime - persistent storage (`hub.db` + private files)
=================================================================
Everything the extension manager must remember across restarts lives under ONE private root:

    <root>/hub.db            SQLite (WAL-safe, synchronous=FULL), numbered migrations, hash-chained audit log
    <root>/hub.lock          the cross-thread/process lock file (see self_builder.lock)
    <root>/modules/          <id>_v<N>.py      the extension source of each version      (never overwritten)
    <root>/manifests/        <id>_v<N>.json    its manifest without the source           (never overwritten)
    <root>/quarantine/       files that no registry row accounts for (kept as evidence, never executed)

It reuses the Self-Builder's `Store` class (transactions, migrations, hash-chained audit) with its own schema, so the
Self-Builder's own database and its schema-version contract stay untouched.
"""

import os
import re
import time

from self_builder.store import Store

HUB_DB = "hub.db"
HUB_LOCK = "hub.lock"
SUB_MODULES = "modules"
SUB_MANIFESTS = "manifests"
SUB_QUARANTINE = "quarantine"
_ID = r"[a-z][a-z0-9_]{2,39}"
_FILE_PATTERNS = {
    SUB_MODULES: re.compile(r"^" + _ID + r"_v[0-9]{1,5}\.py$"),
    SUB_MANIFESTS: re.compile(r"^" + _ID + r"_v[0-9]{1,5}\.json$"),
    SUB_QUARANTINE: re.compile(r"^q_[0-9A-Za-z_.\-]{3,160}$"),
}
MAX_FILE_BYTES = 300_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ext_capabilities(
    capability_id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
    status TEXT NOT NULL, active_version INTEGER, latest_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ext_versions(
    capability_id TEXT NOT NULL, version INTEGER NOT NULL, fingerprint TEXT NOT NULL,
    manifest_file TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, source_file TEXT NOT NULL, source_sha256 TEXT NOT NULL,
    permissions_json TEXT NOT NULL, report_json TEXT NOT NULL, origin TEXT NOT NULL, provenance_json TEXT NOT NULL,
    status TEXT NOT NULL, parent_version INTEGER, proposal_id TEXT, created_at TEXT NOT NULL,
    PRIMARY KEY(capability_id, version));
CREATE TABLE IF NOT EXISTS ext_proposals(
    proposal_id TEXT PRIMARY KEY, capability_id TEXT NOT NULL, planned_version INTEGER NOT NULL, action TEXT NOT NULL,
    manifest_json TEXT NOT NULL, fingerprint TEXT NOT NULL, report_json TEXT NOT NULL, origin TEXT NOT NULL,
    package_sha256 TEXT, status TEXT NOT NULL, created_at REAL NOT NULL, decided_at REAL, expires_at REAL NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS ext_grants(
    capability_id TEXT NOT NULL, permission TEXT NOT NULL, granted_at TEXT NOT NULL, granted_by TEXT NOT NULL,
    PRIMARY KEY(capability_id, permission));
CREATE TABLE IF NOT EXISTS ext_kv(
    capability_id TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(capability_id, key));
CREATE TABLE IF NOT EXISTS ext_usage(
    capability_id TEXT NOT NULL, version INTEGER NOT NULL, calls INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0, last_used_at TEXT, PRIMARY KEY(capability_id, version));
CREATE TABLE IF NOT EXISTS audit_log(
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, event TEXT NOT NULL, capability_id TEXT, version INTEGER,
    upgrade_id INTEGER, detail_json TEXT NOT NULL, prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_ext_versions_status ON ext_versions(capability_id, status);
CREATE INDEX IF NOT EXISTS idx_ext_proposals_status ON ext_proposals(status);
CREATE INDEX IF NOT EXISTS idx_hub_audit_cap ON audit_log(capability_id)
"""


def _migration_1(conn):
    for statement in _SCHEMA.split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)


MIGRATIONS = {1: _migration_1}


def open_store(root):
    return Store(os.path.join(root, HUB_DB), migrations=MIGRATIONS)


class FileError(Exception):
    pass


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


class HubFiles:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        for sub in _FILE_PATTERNS:
            os.makedirs(os.path.join(self.root, sub), exist_ok=True)

    def path(self, sub, name):
        pattern = _FILE_PATTERNS.get(sub)
        if pattern is None or not isinstance(name, str) or not pattern.match(name):
            raise FileError(f"file name not allowed: {sub!r}/{name!r}")
        full = os.path.join(self.root, sub, name)
        if os.path.islink(full):
            raise FileError(f"symbolic links are never followed: {name}")
        return full

    def exists(self, sub, name):
        return os.path.isfile(self.path(sub, name))

    def read(self, sub, name):
        with open(self.path(sub, name), "rb") as f:
            data = f.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise FileError(f"file too large: {name}")
        return data

    def write(self, sub, name, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise FileError(f"file too large: {name}")
        final = self.path(sub, name)
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

    def listdir(self, sub):
        if sub not in _FILE_PATTERNS:
            raise FileError(f"directory not allowed: {sub!r}")
        try:
            return sorted(n for n in os.listdir(os.path.join(self.root, sub)) if ".part" not in n)
        except FileNotFoundError:
            return []

    def quarantine(self, sub, name, reason):
        """Move a file no registry row accounts for out of the way (kept as evidence, never deleted, never loaded)."""
        src = os.path.join(self.root, sub, name)
        if os.path.islink(src):
            os.unlink(src)
            return None
        if not os.path.isfile(src):
            return None
        safe = lambda s, n: "".join(c if (c.isascii() and c.isalnum()) or c in "_.-" else "_" for c in s)[:n]
        base = f"q_{int(time.time())}_{safe(reason, 20) or 'x'}_{sub}_{safe(name, 90)}"
        qname = base
        for n in range(2, 1000):
            if not os.path.lexists(os.path.join(self.root, SUB_QUARANTINE, qname)):
                break
            qname = f"{base}_{n}"
        os.replace(src, os.path.join(self.root, SUB_QUARANTINE, qname))
        return qname

    def sweep_partials(self):
        removed = []
        for sub in tuple(_FILE_PATTERNS) + (None,):
            directory = self.root if sub is None else os.path.join(self.root, sub)
            try:
                names = os.listdir(directory)
            except FileNotFoundError:
                continue
            for name in names:
                if ".part" in name and os.path.isfile(os.path.join(directory, name)):
                    try:
                        os.unlink(os.path.join(directory, name))
                        removed.append(name)
                    except OSError:
                        pass
        return removed
