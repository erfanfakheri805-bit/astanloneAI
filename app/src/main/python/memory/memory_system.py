"""
Memory System
=============
Persistent local storage for the entire application.

Every other system (Knowledge, Concepts, Skills, Capabilities, Self-Upgrade,
Version, Reasoning) reads and writes through this module. Nothing is stored
as raw plain text blobs - each table has a real structured schema so the
data can grow and be queried meaningfully as the application evolves.

Storage engine: SQLite (Python standard library, no external dependency).
By default the database file lives under the platform's app-data
directory (see platform_layer/ - on desktop this resolves to data/
next to this package, unchanged from before Stage 2) and survives
application restarts. Pass db_path explicitly to override (Android
code and the test suite both do this).

Schema evolution goes through a small numbered migration system
(`_run_migrations`) instead of ad-hoc ALTER TABLE calls scattered around the
codebase. Every migration is written to be safe to run against an existing,
populated database: it only adds columns/tables/indexes, de-duplicates
before adding new uniqueness constraints, and never drops data. The applied
version is tracked under the `schema_version` key in the `config` table.
"""

import contextlib
import sqlite3
import json
import os
import sys
import threading
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from platform_layer import get_platform

# Bump this and add a corresponding _migration_N method (registered in
# _run_migrations) to evolve the schema further.
SCHEMA_VERSION = 6


def _now():
    return datetime.now(timezone.utc).isoformat()


def _default_db_path():
    """Resolved lazily (not at import time) so a set_platform() call
    made before MemorySystem() is constructed is honored."""
    return os.path.join(get_platform().app_data_dir(), "memory.db")


class MemorySystem:
    """Thread-safe wrapper around the persistent SQLite store."""

    def __init__(self, db_path=None):
        self.db_path = db_path or _default_db_path()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.RLock()
        self._atomic_depth = 0
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()
        self._run_migrations()

    # ------------------------------------------------------------------
    # Baseline schema (schema version 1) - always safe to re-run.
    # ------------------------------------------------------------------
    def _init_schema(self):
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'concept',
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    source TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_name TEXT NOT NULL,
                    to_name TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(from_name) REFERENCES knowledge(name),
                    FOREIGN KEY(to_name) REFERENCES knowledge(name)
                );

                CREATE TABLE IF NOT EXISTS skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    definition_path TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS capabilities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'planned',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS upgrades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    stage TEXT NOT NULL DEFAULT 'input',
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    upgrade_id INTEGER,
                    version_label TEXT NOT NULL,
                    snapshot TEXT,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(upgrade_id) REFERENCES upgrades(id)
                );

                CREATE TABLE IF NOT EXISTS conversation_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            # Seed the root application version if none exists yet.
            cur = self._conn.execute("SELECT COUNT(*) AS c FROM versions")
            if cur.fetchone()["c"] == 0:
                self._conn.execute(
                    "INSERT INTO versions (upgrade_id, version_label, snapshot, is_active, created_at) "
                    "VALUES (NULL, ?, ?, 1, ?)",
                    ("0.1.0-foundation", json.dumps({"note": "Initial foundation build"}), _now()),
                )

    # ------------------------------------------------------------------
    # Migrations (schema version 2+)
    # ------------------------------------------------------------------
    def _run_migrations(self):
        current = self.get_config("schema_version", 1)
        migrations = {
            2: self._migration_2, 3: self._migration_3, 4: self._migration_4,
            5: self._migration_5, 6: self._migration_6,
        }
        for version in sorted(migrations):
            if current < version:
                migrations[version]()
                self.set_config("schema_version", version)
                current = version

    def _column_exists(self, table, column):
        rows = self.query(f"PRAGMA table_info({table})")
        return any(r["name"] == column for r in rows)

    def _migration_2(self):
        """Adds knowledge.confidence, learning_events, error_log; de-dupes
        any pre-existing duplicate relationships and adds the indexes the
        Reasoning Engine and dev panel rely on. Every step is additive and
        idempotent - safe to run against a database created by the
        original 0.1.0 foundation schema, and safe to re-run."""
        with self._lock, self._conn:
            if not self._column_exists("knowledge", "confidence"):
                self._conn.execute(
                    "ALTER TABLE knowledge ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0"
                )

            # De-duplicate any relationships that predate the unique index
            # below, keeping the earliest occurrence of each (from, to, type).
            self._conn.execute(
                """
                DELETE FROM relationships
                WHERE id NOT IN (
                    SELECT MIN(id) FROM relationships
                    GROUP BY from_name, to_name, relation_type
                )
                """
            )

            self._conn.executescript(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_relationships_unique
                    ON relationships(from_name, to_name, relation_type);
                CREATE INDEX IF NOT EXISTS idx_relationships_from ON relationships(from_name);
                CREATE INDEX IF NOT EXISTS idx_relationships_to ON relationships(to_name);
                CREATE INDEX IF NOT EXISTS idx_knowledge_kind ON knowledge(kind);
                CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status);

                CREATE TABLE IF NOT EXISTS learning_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    detail TEXT,
                    source TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_learning_events_target ON learning_events(target);

                CREATE TABLE IF NOT EXISTS error_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation TEXT NOT NULL,
                    message TEXT NOT NULL,
                    context TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _migration_3(self):
        """Adds the provenance columns the Learning Engine's natural-
        language pipeline needs (learning/learning_system.py,
        learning/learning_input.py): where a piece of knowledge came
        from, and how confident/by what method it was learned. Extends
        the existing `knowledge` and `relationships` tables rather than
        creating a parallel provenance table - `knowledge` already had
        `source`/`confidence`/`created_at`, this only adds the two
        columns it was missing. `relationships` had none of this before,
        so it gains a matching set. Purely additive/idempotent, like
        _migration_2."""
        with self._lock, self._conn:
            if not self._column_exists("knowledge", "source_text"):
                self._conn.execute("ALTER TABLE knowledge ADD COLUMN source_text TEXT")
            if not self._column_exists("knowledge", "learning_method"):
                self._conn.execute("ALTER TABLE knowledge ADD COLUMN learning_method TEXT")

            if not self._column_exists("relationships", "confidence"):
                self._conn.execute("ALTER TABLE relationships ADD COLUMN confidence REAL")
            if not self._column_exists("relationships", "source_type"):
                self._conn.execute("ALTER TABLE relationships ADD COLUMN source_type TEXT")
            if not self._column_exists("relationships", "source_text"):
                self._conn.execute("ALTER TABLE relationships ADD COLUMN source_text TEXT")
            if not self._column_exists("relationships", "learning_method"):
                self._conn.execute("ALTER TABLE relationships ADD COLUMN learning_method TEXT")
            if not self._column_exists("relationships", "updated_at"):
                self._conn.execute("ALTER TABLE relationships ADD COLUMN updated_at TEXT")
                # Backfill: every pre-existing row's "last touched" time
                # is, honestly, its creation time - there is no better
                # information available for rows written before this
                # column existed.
                self._conn.execute(
                    "UPDATE relationships SET updated_at = created_at WHERE updated_at IS NULL"
                )

    def _migration_4(self):
        """Adds the `rules` table backing reasoning/rule_registry.py's
        RuleRegistry (Stage 6). A rule's `conditions` (a JSON-encoded list
        of [from, relation, to] triples) and `conclusion` (a single JSON
        [from, relation, to] triple) are stored as TEXT/JSON rather than a
        separate normalized table, matching how `skills` already stores its
        structured trigger/response definition on disk rather than in more
        tables (see skills/skill_system.py) - the rule set is expected to
        stay small (per rules.py's "NOT hundreds of hard-coded conditionals"
        design goal), so a normalized conditions table would add join
        complexity without a real benefit at this scale. Purely additive,
        like _migration_2/_migration_3 - no existing table is touched."""
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    conditions TEXT NOT NULL,
                    conclusion TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT 'system',
                    version INTEGER NOT NULL DEFAULT 1,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rules_enabled ON rules(enabled);
                CREATE INDEX IF NOT EXISTS idx_rules_priority ON rules(priority);
                """
            )

    def _migration_5(self):
        """Adds the `language_learning_items` table backing Prompt 416's
        language_intelligence/language_learning_store.py: a structured
        foundation for words, phrases and sentence patterns a future
        language-learning module can record, one language/locale at a
        time, without any language's grammar being hard-coded into this
        schema. This is NOT a second, parallel memory system - it is one
        more table on the exact same SQLite connection every other
        structured store in this file already uses (knowledge, skills,
        rules, ...), added the same purely-additive way as
        _migration_2/_migration_3/_migration_4.

        `item_key` is the learned text verbatim (a word, phrase, or
        sentence-pattern template); `normalized_key` is its case-folded,
        whitespace-collapsed form and backs the unique index below, so
        re-teaching the same (language, item_type, key) triple updates
        the existing row instead of creating a duplicate - the same
        "look up by a normalized identity, then UPDATE or INSERT" shape
        `knowledge.name` and the `relationships` unique index already
        use elsewhere in this schema. `meaning`, `examples` and
        `relationships` are stored as JSON text (like `rules.conditions`/
        `rules.conclusion` above) rather than further normalized tables,
        since their shape is deliberately caller-defined and
        language-agnostic, not fixed by this schema.
        """
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS language_learning_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    language TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    normalized_key TEXT NOT NULL,
                    meaning TEXT,
                    examples TEXT,
                    relationships TEXT,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT,
                    source_context TEXT,
                    learning_method TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_language_learning_items_unique
                    ON language_learning_items(language, item_type, normalized_key);
                CREATE INDEX IF NOT EXISTS idx_language_learning_items_language
                    ON language_learning_items(language);
                """
            )

    def _migration_6(self):
        """Adds the `language_item_relationships` table backing Prompt 417's
        language_intelligence/language_relationships.py: structured links
        between learned language items (Prompt 416) - and, optionally, a
        Knowledge System concept on either end.

        Why a new table instead of the existing `relationships` table:
        that one's foreign keys point at `knowledge(name)` only, so it
        cannot reference a `language_learning_items` row, and
        KnowledgeSystem.relate() auto-creates stub knowledge entries for
        unknown names - the opposite of what a link between *actual*
        learned items must do. This table keeps the same provenance
        columns (confidence / source / source_context / learning_method /
        timestamps) and the same idempotent look-up-then-refresh
        behaviour, and is one more table on the same SQLite connection -
        not a second memory system.

        No dangling references: each endpoint is a real foreign key
        (`language_learning_items(id)` for a language item,
        `knowledge(name)` for a concept), enforced by SQLite itself
        (`PRAGMA foreign_keys = ON`, set in __init__), and a CHECK
        constraint requires exactly one of the two per side.

        `relation_type` is a free-form label (never a closed vocabulary);
        `normalized_type` is its case-folded, whitespace-collapsed form
        and backs the unique index, exactly like `normalized_key` in
        `language_learning_items`. The unique index uses COALESCE because
        SQLite treats NULLs as distinct inside a plain unique index.
        `symmetric` marks a relationship whose two ends are
        interchangeable (e.g. synonym): such a row is stored once, in a
        canonical endpoint order, so (a, b) and (b, a) can never become
        two rows. `metadata` is caller-shaped JSON, like
        `language_learning_items.meaning`.
        """
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS language_item_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_item_id INTEGER REFERENCES language_learning_items(id),
                    from_concept TEXT REFERENCES knowledge(name),
                    to_item_id INTEGER REFERENCES language_learning_items(id),
                    to_concept TEXT REFERENCES knowledge(name),
                    relation_type TEXT NOT NULL,
                    normalized_type TEXT NOT NULL,
                    symmetric INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT,
                    source_context TEXT,
                    learning_method TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK ((from_item_id IS NULL) <> (from_concept IS NULL)),
                    CHECK ((to_item_id IS NULL) <> (to_concept IS NULL))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_language_item_relationships_unique
                    ON language_item_relationships(
                        COALESCE(from_item_id, 0), COALESCE(from_concept, ''),
                        COALESCE(to_item_id, 0), COALESCE(to_concept, ''),
                        normalized_type
                    );
                CREATE INDEX IF NOT EXISTS idx_language_item_relationships_from_item
                    ON language_item_relationships(from_item_id);
                CREATE INDEX IF NOT EXISTS idx_language_item_relationships_to_item
                    ON language_item_relationships(to_item_id);
                CREATE INDEX IF NOT EXISTS idx_language_item_relationships_from_concept
                    ON language_item_relationships(from_concept);
                CREATE INDEX IF NOT EXISTS idx_language_item_relationships_to_concept
                    ON language_item_relationships(to_concept);
                """
            )

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def _run(self, sql, params=()):
        with self._lock:
            if self._atomic_depth:
                # Prompt 645: inside an _atomic() scope the statement joins
                # the open transaction; the outermost scope commits/rolls back.
                return self._conn.execute(sql, params)
            with self._conn:
                cur = self._conn.execute(sql, params)
                return cur

    @contextlib.contextmanager
    def _atomic(self):
        """Prompt 645: minimal re-entrant transaction scope. Every _run()
        inside commits together when the OUTERMOST scope exits normally, or
        is rolled back together if anything raises out of it. Holds the
        connection lock for the scope's duration. Not a general framework:
        no savepoints, no schema/DDL use, nesting only joins the outer scope."""
        with self._lock:
            outermost = self._atomic_depth == 0
            self._atomic_depth += 1
            try:
                yield self
            except BaseException:
                if outermost:
                    self._conn.rollback()
                raise
            else:
                if outermost:
                    self._conn.commit()
            finally:
                self._atomic_depth -= 1

    def query(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Config / State (simple key-value, e.g. app version, settings)
    # ------------------------------------------------------------------
    def set_config(self, key, value):
        self._run(
            "INSERT INTO config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def get_config(self, key, default=None):
        row = self.query_one("SELECT value FROM config WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def set_state(self, key, value):
        self._run(
            "INSERT INTO state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def get_state(self, key, default=None):
        row = self.query_one("SELECT value FROM state WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    # ------------------------------------------------------------------
    # Conversation log (short persistent chat history)
    # ------------------------------------------------------------------
    def log_message(self, role, content):
        self._run(
            "INSERT INTO conversation_log (role, content, created_at) VALUES (?, ?, ?)",
            (role, content, _now()),
        )

    def recent_messages(self, limit=50):
        return list(reversed(self.query(
            "SELECT role, content, created_at FROM conversation_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )))

    # ------------------------------------------------------------------
    # Learning history (episodic memory of what was learned, and when)
    # ------------------------------------------------------------------
    def add_learning_event(self, event_type, target, detail=None, source=None):
        self._run(
            "INSERT INTO learning_events (event_type, target, detail, source, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (event_type, target, detail, source, _now()),
        )

    def recent_learning_events(self, limit=50):
        return list(reversed(self.query(
            "SELECT * FROM learning_events ORDER BY id DESC LIMIT ?", (limit,),
        )))

    # ------------------------------------------------------------------
    # Error history (substrate for failure-learning - see docs/ERROR_LEARNING)
    # ------------------------------------------------------------------
    def log_error(self, operation, message, context=None):
        self._run(
            "INSERT INTO error_log (operation, message, context, created_at) VALUES (?, ?, ?, ?)",
            (operation, message, context, _now()),
        )

    def recent_errors(self, limit=50):
        return list(reversed(self.query(
            "SELECT * FROM error_log ORDER BY id DESC LIMIT ?", (limit,),
        )))

    def counts(self):
        """Used by the developer panel."""
        def count(table, where="1=1"):
            row = self.query_one(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}")
            return row["c"] if row else 0

        return {
            "knowledge_count": count("knowledge"),
            "concept_count": count("knowledge", "kind = 'concept'"),
            "skill_count": count("skills"),
            "capability_count": count("capabilities"),
            "installed_upgrades": count("upgrades", "status = 'installed'"),
            "failed_upgrades": count("upgrades", "status = 'failed'"),
            "learning_event_count": count("learning_events"),
            "error_count": count("error_log"),
            "rule_count": count("rules"),
            "enabled_rule_count": count("rules", "enabled = 1"),
            "language_learning_item_count": count("language_learning_items"),
            "language_relationship_count": count("language_item_relationships"),
        }
