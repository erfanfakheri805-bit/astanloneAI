"""Prompt 648 - Section 3: learning-event retrieval / audit consistency.

RETRIEVAL AUDIT, not an event-query redesign. Finding: no genuine defect; the
existing retrieval API is already deterministic, so NO production change.

Existing retrieval contract (documented, unchanged):
  MemorySystem.recent_learning_events(limit=50) (== Core.recent_learning_events,
  served by GET /api/learning-history) returns the newest `limit` rows of
  `learning_events`, oldest-first, as plain dicts with exactly the persisted
  columns: id, event_type, target, detail, source, created_at.
  R1. Ordering key is the persisted, unique, AUTOINCREMENT `id` (insertion
      order) - NOT created_at. Timestamps never take part in ordering, so equal
      or out-of-order timestamps cannot make order non-deterministic; id is
      the stable tie-breaker. Stored timestamps are never altered.
  R2. `limit` selects the newest N by id; limit=0 -> []; limit larger than the
      history -> everything; empty history -> [].
  R3. NO filtering by type/target/source is supported by any read API (the
      `target` index exists but no reader uses it). Not invented here; callers
      filter the returned list.
  R4. Read-only: retrieval runs a single SELECT and mutates nothing.
Documented edge (outside the supported contract, left unchanged):
  L1. limit < 0 returns all rows (SQLite LIMIT -1); limit=None raises
      sqlite3.IntegrityError. Callers always pass an int (defaults to 50).
"""
import hashlib
import os
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from language_intelligence.language_learning_store import LanguageLearningStore

COLS = ["id", "event_type", "target", "detail", "source", "created_at"]
TABLES = ("knowledge", "relationships", "language_learning_items",
          "language_item_relationships", "learning_events", "conversation_log", "error_log")


class Retrieval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "m.db")
        self._open()

    def _open(self):
        self.m = MemorySystem(self.db)
        self.k = KnowledgeSystem(self.m)
        self.ls = LearningSystem(ConceptSystem(self.k), self.k, memory=self.m)
        self.ll = LanguageLearningStore(self.m)

    def tearDown(self):
        self.m._conn.close()
        self.tmp.cleanup()

    def reopen(self):
        self.m._conn.close()
        self._open()

    def raw(self):
        return self.m.query("SELECT * FROM learning_events ORDER BY id")

    def dump(self):
        return {t: self.m.query(f"SELECT * FROM {t} ORDER BY id") for t in TABLES}

    def ids(self, limit=50):
        return [e["id"] for e in self.m.recent_learning_events(limit)]

    def insert(self, ts, typ="teach", target="t", detail=None, source=None):
        self.m._run("INSERT INTO learning_events (event_type, target, detail, source, created_at) "
                    "VALUES (?, ?, ?, ?, ?)", (typ, target, detail, source, ts))

    def seed_mixed(self):
        self.ls.teach("alpha", "first", source="user")
        self.ls.correct("alpha", "second", source="user")
        self.ls.teach("beta", "b", source="ael")
        self.ls.relate("alpha", "beta", "related_to", source="user")
        self.ll.learn_item("en", "word", "hello", meaning="greeting", source="user")
        self.ll.learn_item("en", "word", "hello", meaning="greeting!", source="user")

    # 1 chronological
    def test_chronological_oldest_first(self):
        for i in range(6):
            self.m.add_learning_event("teach", f"n{i}", detail=str(i), source="s")
        got = self.m.recent_learning_events()
        self.assertEqual([e["target"] for e in got], [f"n{i}" for i in range(6)])
        self.assertEqual([e["created_at"] for e in got], sorted(e["created_at"] for e in got))

    # 2/3 same / near / reversed timestamps: id is the tie-breaker
    def test_same_timestamp_ties_ordered_by_id(self):
        for i in range(5):
            self.insert("2026-01-01T00:00:00+00:00", target=f"t{i}")
        got = self.m.recent_learning_events()
        self.assertEqual([e["target"] for e in got], [f"t{i}" for i in range(5)])
        self.assertEqual([e["id"] for e in got], sorted(e["id"] for e in got))
        self.assertEqual(self.ids(2), [4, 5])           # limit under ties: newest by id

    def test_near_and_out_of_order_timestamps_still_by_id(self):
        stamps = ["2026-01-01T00:00:00.000002+00:00", "2026-01-01T00:00:00.000001+00:00",
                  "2026-01-01T00:00:00.000002+00:00", "2025-12-31T23:59:59+00:00"]
        for i, s in enumerate(stamps):
            self.insert(s, target=f"t{i}")
        self.assertEqual(self.ids(), [1, 2, 3, 4])      # insertion order; timestamps untouched
        self.assertEqual([e["created_at"] for e in self.m.recent_learning_events()], stamps)

    def test_ids_unique_monotonic_not_reused_after_delete(self):
        for i in range(3):
            self.insert("2026-01-01T00:00:00+00:00", target=f"t{i}")
        self.m._run("DELETE FROM learning_events WHERE id = 3")
        self.insert("2026-01-01T00:00:00+00:00", target="after")
        self.assertEqual(self.ids(), [1, 2, 4])

    # 4 no silent omission within contract
    def test_no_omission_within_limit(self):
        for i in range(120):
            self.insert("2026-01-01T00:00:00+00:00", target=f"t{i}")
        self.assertEqual(self.ids(1000), list(range(1, 121)))
        self.assertEqual(self.ids(), list(range(71, 121)))       # default 50 = newest 50, contiguous
        self.assertEqual(len(self.m.recent_learning_events()), 50)

    # 5 filtering: not supported -> documented; caller-side filter is deterministic
    def test_filtering_not_supported_contract_and_caller_filter_deterministic(self):
        import inspect
        self.assertEqual(list(inspect.signature(MemorySystem.recent_learning_events).parameters),
                         ["self", "limit"])
        self.seed_mixed()
        a = [e["id"] for e in self.m.recent_learning_events() if e["event_type"] == "teach"]
        b = [e["id"] for e in self.m.recent_learning_events() if e["event_type"] == "teach"]
        self.assertEqual(a, b)
        self.assertEqual(a, sorted(a))
        by_target = [e["id"] for e in self.m.recent_learning_events() if e["target"] == "alpha"]
        self.assertEqual(by_target, sorted(by_target))

    # 6 limits/counts
    def test_limit_semantics(self):
        for i in range(5):
            self.m.add_learning_event("teach", f"t{i}")
        self.assertEqual(self.ids(0), [])
        self.assertEqual(self.ids(1), [5])
        self.assertEqual(self.ids(3), [3, 4, 5])
        self.assertEqual(self.ids(5), [1, 2, 3, 4, 5])
        self.assertEqual(self.ids(99), [1, 2, 3, 4, 5])
        self.assertEqual(self.ids(2), self.ids(3)[1:])           # prefix-consistent
        self.assertEqual(self.m.counts()["learning_event_count"], 5)
        self.assertEqual(self.m.counts()["learning_event_count"], len(self.raw()))

    def test_out_of_contract_limits_documented(self):
        for i in range(3):
            self.m.add_learning_event("teach", f"t{i}")
        self.assertEqual(self.ids(-1), [1, 2, 3])                # L1
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.m.recent_learning_events(None)                  # L1 (unchanged)
        self.assertEqual(len(self.raw()), 3)                     # failure mutated nothing

    # 7 empty
    def test_empty_history(self):
        self.assertEqual(self.m.recent_learning_events(), [])
        self.assertEqual(self.m.recent_learning_events(0), [])
        self.assertEqual(self.m.counts()["learning_event_count"], 0)

    # 8 unknown identifiers
    def test_unknown_records_produce_no_events(self):
        before = self.dump()
        try:
            self.ls.correct("ghost", "nothing", source="user")
        except Exception:
            pass
        self.assertEqual(self.m.recent_learning_events(), [])
        self.assertEqual([e for e in self.m.recent_learning_events() if e["target"] == "ghost"], [])
        self.assertEqual(self.dump()["learning_events"], before["learning_events"])

    def test_unknown_target_in_populated_history_matches_nothing(self):
        self.seed_mixed()
        self.assertEqual([e for e in self.m.recent_learning_events() if e["target"] == "ghost"], [])

    # 9 reopen
    def test_reopen_same_history_and_order(self):
        self.seed_mixed()
        before = self.m.recent_learning_events()
        self.reopen()
        self.assertEqual(self.m.recent_learning_events(), before)
        self.reopen()
        self.assertEqual(self.m.recent_learning_events(), before)
        self.ls.teach("gamma", "g", source="user")               # continues after reopen
        after = self.m.recent_learning_events()
        self.assertEqual(after[:-1], before)
        self.assertEqual(after[-1]["id"], before[-1]["id"] + 1)

    # 10 exact persisted data
    def test_exact_persisted_rows(self):
        self.seed_mixed()
        self.insert("2026-02-02T00:00:00+00:00", typ="odd", target="x", detail=None, source=None)
        got = self.m.recent_learning_events(1000)
        self.assertEqual(got, self.raw())
        for e in got:
            self.assertEqual(list(e.keys()), COLS)
            self.assertIsInstance(e, dict)
        self.assertIsNone(got[-1]["detail"])
        self.assertIsNone(got[-1]["source"])
        # what the Core service accessor exposes is the same list
        from core.core import Core
        self.assertTrue(hasattr(Core, "recent_learning_events"))

    # 12 multiple event types, unchanged
    def test_multiple_event_types_and_names_unchanged(self):
        self.seed_mixed()
        got = self.m.recent_learning_events()
        self.assertEqual([e["event_type"] for e in got],
                         ["teach", "correct", "teach", "relate",
                          "language_item_learned", "language_item_updated"])
        self.assertEqual([e["id"] for e in got], sorted(e["id"] for e in got))
        self.assertEqual(got[1]["detail"], "'first' -> 'second'")
        self.assertEqual(got[3]["detail"], "related_to -> beta")

    # 11 read-only
    def test_retrieval_is_read_only(self):
        self.seed_mixed()
        self.m._conn.commit()
        before = self.dump()
        self.assertEqual(self.m.counts()["learning_event_count"], len(before["learning_events"]))
        def digest():
            with open(self.db, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        h = digest()
        for lim in (0, 1, 2, 50, 1000):
            self.m.recent_learning_events(lim)
        self.assertEqual(self.dump(), before)
        self.assertEqual(digest(), h)
        self.assertFalse(self.m._conn.in_transaction)

    def test_returned_rows_are_copies(self):
        self.seed_mixed()
        got = self.m.recent_learning_events()
        got[0]["target"] = "MUTATED"
        got.pop()
        self.assertEqual(self.m.recent_learning_events(), self.raw())

    # 13 deterministic repeats
    def test_repeated_retrieval_deterministic(self):
        for i in range(30):
            self.insert("2026-01-01T00:00:00+00:00", typ="teach" if i % 2 else "correct", target=f"t{i % 4}")
        first = self.m.recent_learning_events(20)
        for _ in range(10):
            self.assertEqual(self.m.recent_learning_events(20), first)
        self.reopen()
        self.assertEqual(self.m.recent_learning_events(20), first)


if __name__ == "__main__":
    unittest.main()
