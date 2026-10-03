"""Prompt 651 - Section 3: knowledge state-transition audit (version/status/timestamps/events).

AUDIT, not a redesign. Finding: no genuine state-transition defect; NO production
change. Existing transition contract (asserted below, with a controlled clock):

  T1 New knowledge: version 1, created_at == updated_at, status as requested
     ("active" by default; relate() stubs are "stub").
  T2 A genuine change (any of description/kind/status/source/confidence/
     source_text/learning_method, using None-preserving effective values) does
     version+1 and moves updated_at forward exactly once; created_at, id, name
     never change. An exact repeat is a TRUE no-op: no write, no version bump,
     same updated_at, no event.
  T3 status is a plain persisted field: learn()/teach() default status "active",
     correct() status None -> "active"; an explicit status (e.g. "stub",
     "deprecated") is stored and counts as a change. Stub -> taught keeps the row
     (id/created_at), version+1, status "active".
  T4 Events exist only for real transitions (teach/correct/relate); a no-op writes
     none. Knowledge + event commit atomically: if the event insert fails the
     knowledge write rolls back completely.
  T5 relate() never mutates an existing endpoint record; only NEW endpoints get
     stubs. Relationship rows have no version: updated_at moves only when an
     effective value changes; created_at is stable.
  T6 Intentionally DIFFERENT repeat semantics (unchanged): the language item and
     language relationship stores treat EVERY repeat as a real update (version+1,
     updated_at moves, an "..._updated" event) even if identical.
  T7 Rejected operations (blank names/descriptions, ambiguous or unknown
     correction targets, invalid relate args) change nothing.
"""
import os
import tempfile
import unittest
from unittest import mock

from memory.memory_system import MemorySystem
import memory.memory_system as memory_mod
import knowledge.knowledge_system as knowledge_mod
import language_intelligence.language_learning_store as lang_mod
import language_intelligence.language_relationships as langrel_mod
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.language_relationships import LanguageRelationshipStore, item_ref

TABLES = ("knowledge", "relationships", "language_learning_items",
          "language_item_relationships", "learning_events")


class Clock:
    """Strictly increasing controlled clock (ISO-8601 UTC strings, same format as production)."""
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f"2026-01-01T00:00:{self.n:02d}.000000+00:00"

    def last(self):
        return f"2026-01-01T00:00:{self.n:02d}.000000+00:00"


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        for mod in (memory_mod, knowledge_mod, lang_mod, langrel_mod):
            p = mock.patch.object(mod, "_now", self.clock)
            p.start()
            self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "m.db")
        self._open()

    def _open(self):
        self.m = MemorySystem(self.db)
        self.k = KnowledgeSystem(self.m)
        self.ls = LearningSystem(ConceptSystem(self.k), self.k, memory=self.m)
        self.ll = LanguageLearningStore(self.m)
        self.lr = LanguageRelationshipStore(self.m, self.ll, self.k)

    def tearDown(self):
        self.m._conn.close()
        self.tmp.cleanup()

    def reopen(self):
        self.m._conn.close()
        self._open()

    def snap(self):
        return {t: self.m.query(f"SELECT * FROM {t} ORDER BY id") for t in TABLES}

    def events(self, *types):
        return [e for e in self.m.query("SELECT * FROM learning_events ORDER BY id")
                if not types or e["event_type"] in types]

    def rec(self, name):
        return self.k.get(name)


class CreationAndVersioning(Base):
    def test_creation_initial_state(self):
        r = self.ls.teach("a", "d", source="user")
        self.assertEqual((r["version"], r["status"]), (1, "active"))
        self.assertEqual(r["created_at"], r["updated_at"])
        self.assertEqual([e["event_type"] for e in self.events()], ["teach"])

    def test_exact_noop_changes_nothing(self):
        self.ls.teach("a", "d", source="user", confidence=0.5, source_text="s", learning_method="m")
        before = self.snap()
        for _ in range(3):
            self.ls.teach("a", "d", source="user", confidence=0.5, source_text="s", learning_method="m")
            self.k.learn("a", "d", source="user")               # omitted metadata == unchanged
        self.assertEqual(self.snap(), before)

    def test_genuine_update_increments_once_and_moves_updated_at(self):
        first = self.ls.teach("a", "d1", source="user")
        second = self.ls.teach("a", "d2", source="user")
        self.assertEqual((second["version"], second["created_at"], second["id"]),
                         (2, first["created_at"], first["id"]))
        self.assertGreater(second["updated_at"], first["updated_at"])
        third = self.ls.teach("a", "d2", source="other")          # provenance-only change is a change
        self.assertEqual(third["version"], 3)
        self.assertGreater(third["updated_at"], second["updated_at"])
        self.assertEqual(len(self.events("teach")), 3)

    def test_each_field_change_counts_once(self):
        cur = dict(description="d", kind="concept", status="active", source="s", confidence=0.5,
                   source_text="t", learning_method="m")
        self.k.learn("a", **cur)
        version = 1
        for change in ({"description": "d2"}, {"kind": "thing"}, {"source": "s2"}, {"confidence": 0.9},
                       {"source_text": "t2"}, {"learning_method": "m2"}, {"status": "deprecated"}):
            cur.update(change)
            before = self.rec("a")
            r = self.k.learn("a", **cur)
            version += 1
            self.assertEqual(r["version"], version, change)
            self.assertGreater(r["updated_at"], before["updated_at"], change)
            self.assertEqual(r["created_at"], before["created_at"], change)
            self.assertEqual(self.k.learn("a", **cur), r)              # repeat: no-op

    def test_timestamps_monotonic_and_created_at_stable(self):
        self.ls.teach("a", "d0", source="user")
        created = self.rec("a")["created_at"]
        stamps = [self.rec("a")["updated_at"]]
        for i in range(1, 6):
            self.ls.teach("a", f"d{i}", source="user")
            stamps.append(self.rec("a")["updated_at"])
        self.assertEqual(stamps, sorted(set(stamps)))              # strictly increasing
        self.assertEqual(self.rec("a")["created_at"], created)
        self.assertEqual(self.rec("a")["version"], 6)

    def test_reads_do_not_touch_state(self):
        self.ls.teach("a", "d", source="user")
        self.ls.relate("a", "b", "is_a", source="user")
        before = self.snap()
        self.k.get("a"); self.k.all(); self.k.search("d"); self.k.resolve_name("A")
        self.k.relationships_for("a"); self.ls.recall("a"); self.ls.search("d")
        self.assertEqual(self.snap(), before)


class Correction(Base):
    def test_genuine_correction_increments_and_logs(self):
        self.ls.teach("a", "d1", source="user", confidence=0.6)
        before = self.rec("a")
        r = self.ls.correct("A", "d2")
        self.assertEqual((r["version"], r["description"], r["confidence"], r["source"]),
                         (2, "d2", 0.6, "user"))
        self.assertEqual((r["created_at"], r["id"]), (before["created_at"], before["id"]))
        self.assertGreater(r["updated_at"], before["updated_at"])
        e = self.events("correct")
        self.assertEqual([(x["target"], x["detail"], x["source"], x["created_at"] >= before["updated_at"])
                          for x in e], [("a", "'d1' -> 'd2'", "user", True)])

    def test_repeated_correction_contract(self):
        self.ls.teach("a", "d1", source="user")
        self.ls.correct("a", "d2")
        before, n = self.snap(), len(self.events())
        self.ls.correct("a", "d2")                                   # identical -> true no-op
        self.ls.correct("A", "d2")
        self.assertEqual(self.snap(), before)
        self.ls.correct("a", "d3"); self.ls.correct("a", "d2")       # flip-flop = 2 real changes
        self.assertEqual((self.rec("a")["version"], len(self.events("correct"))), (4, 3))
        self.assertEqual(len(self.events()), n + 2)

    def test_correction_status_contract(self):
        self.k.learn("a", "d", status="deprecated")
        r = self.k.correct("a", "d")                                  # status None -> "active": a change
        self.assertEqual((r["status"], r["version"]), ("active", 2))
        r = self.k.correct("a", "d", status="deprecated")
        self.assertEqual((r["status"], r["version"]), ("deprecated", 3))
        r = self.k.correct("a", "d", status="deprecated")
        self.assertEqual(r["version"], 3)                             # identical -> no-op

    def test_status_only_correction_logs_event_with_unchanged_description(self):
        self.k.learn("a", "d", status="stub", source="user")
        self.ls.correct("a", "d")                                     # documented L2 (Prompt 647)
        self.assertEqual(self.events("correct")[0]["detail"], "'d' -> 'd'")
        self.assertEqual(self.rec("a")["status"], "active")


class StubLifecycle(Base):
    def test_stub_creation_and_upgrade_preserve_identity(self):
        self.ls.relate("a", "b", "is_a", source="user", source_text="t", learning_method="m")
        stub, other = self.rec("a"), self.rec("b")
        self.assertEqual((stub["version"], stub["status"], stub["created_at"] == stub["updated_at"]),
                         (1, "stub", True))
        taught = self.ls.teach("a", "real", source="user")
        self.assertEqual((taught["id"], taught["created_at"], taught["version"], taught["status"]),
                         (stub["id"], stub["created_at"], 2, "active"))
        self.assertGreater(taught["updated_at"], stub["updated_at"])
        self.assertEqual(self.rec("b"), other)                        # sibling stub untouched
        self.assertEqual([e["event_type"] for e in self.events()], ["relate", "teach"])
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 1)

    def test_stub_upgrade_by_repeat_is_noop(self):
        self.ls.relate("a", "b", "is_a", source="user")
        self.ls.teach("a", "real", source="user")
        before = self.snap()
        self.ls.teach("a", "real", source="user")
        self.assertEqual(self.snap(), before)


class RelationshipIsolation(Base):
    def test_relate_does_not_mutate_existing_endpoints_or_bystanders(self):
        self.ls.teach("a", "da", source="user"); self.ls.teach("b", "db", source="user")
        self.ls.teach("z", "dz", source="user")
        before = {n: self.rec(n) for n in "abz"}
        self.ls.relate("a", "b", "is_a", source="user", confidence=0.7, source_text="t", learning_method="m")
        self.ls.relate("a", "b", "is_a", source="user2")             # relationship update
        self.ls.relate("a", "c", "part_of", source="user")           # new stub only for c
        for n in "abz":
            self.assertEqual(self.rec(n), before[n], n)
        self.assertEqual(self.rec("c")["status"], "stub")

    def test_relationship_row_timestamps_and_noop(self):
        self.ls.relate("a", "b", "is_a", source="user", confidence=0.7)
        r1 = self.m.query_one("SELECT * FROM relationships")
        self.ls.relate("a", "b", "is_a", source="user", confidence=0.7)     # true no-op
        self.assertEqual(self.m.query_one("SELECT * FROM relationships"), r1)
        self.ls.relate("a", "b", "is_a", source="user", confidence=0.9)     # real change
        r2 = self.m.query_one("SELECT * FROM relationships")
        self.assertEqual((r2["created_at"], r2["id"], r2["confidence"]), (r1["created_at"], r1["id"], 0.9))
        self.assertGreater(r2["updated_at"], r1["updated_at"])
        self.assertEqual(len(self.events("relate")), 2)

    def test_stub_creation_versions(self):
        self.k.relate("a", "b", "is_a")
        self.assertEqual([r["version"] for r in self.m.query("SELECT * FROM knowledge ORDER BY id")], [1, 1])
        self.k.relate("a", "b", "is_a", confidence=0.4)
        self.assertEqual([r["version"] for r in self.m.query("SELECT * FROM knowledge ORDER BY id")], [1, 1])


class RejectedAndAmbiguous(Base):
    def test_rejected_operations_change_nothing(self):
        self.ls.teach("a", "d", source="user")
        before = self.snap()
        cases = [lambda: self.ls.teach("", "d"), lambda: self.ls.teach("  ", "d"),
                 lambda: self.k.learn(None, "d"), lambda: self.k.correct("a", "  "),
                 lambda: self.k.correct("", "x"), lambda: self.ls.relate("", "b", "is_a"),
                 lambda: self.ls.relate("a", "", "is_a"), lambda: self.k.relate("a", "new", None)]
        for c in cases:
            with self.assertRaises(ValueError):
                c()
        self.assertIsNone(self.ls.correct("ghost", "x"))
        self.assertEqual(self.snap(), before)

    def test_ambiguous_correction_mutates_nothing(self):
        self.ls.teach("Py", "a", source="user"); self.ls.teach("py", "b", source="user")
        before = self.snap()
        with self.assertRaises(ValueError):
            self.ls.correct("PY", "x")
        self.assertEqual(self.snap(), before)

    def test_event_failure_rolls_back_teach_correct_relate(self):
        self.ls.teach("a", "d", source="user")
        before = self.snap()
        with mock.patch.object(self.m, "add_learning_event", side_effect=RuntimeError("inject")):
            with self.assertRaises(RuntimeError):
                self.ls.teach("a", "d2", source="user")             # update
            with self.assertRaises(RuntimeError):
                self.ls.teach("new", "d", source="user")            # create
            with self.assertRaises(RuntimeError):
                self.ls.correct("a", "d3")
            with self.assertRaises(RuntimeError):
                self.ls.relate("a", "b", "is_a", source="user")     # stub + edge
        self.assertEqual(self.snap(), before)
        self.assertFalse(self.m._conn.in_transaction)
        self.ls.teach("a", "d2", source="user")                       # store still healthy
        self.assertEqual(self.rec("a")["version"], 2)


class IntentionalDifferentRepeatSemantics(Base):
    def test_language_item_repeat_is_a_real_update(self):
        a = self.ll.learn_item("en", "word", "hi", meaning="m", source="user")
        b = self.ll.learn_item("en", "word", "hi", meaning="m", source="user")     # identical repeat
        self.assertEqual((a["version"], b["version"], b["created_at"]), (1, 2, a["created_at"]))
        self.assertGreater(b["updated_at"], a["updated_at"])
        self.assertEqual([e["event_type"] for e in self.events()],
                         ["language_item_learned", "language_item_updated"])

    def test_language_relationship_repeat_is_a_real_update(self):
        self.ll.learn_item("en", "word", "hi", meaning="m"); self.ll.learn_item("fa", "word", "salam", meaning="m")
        a, b = item_ref("fa", "word", "salam"), item_ref("en", "word", "hi")
        self.lr.relate(a, b, "translation", source="user")
        r1 = self.m.query_one("SELECT * FROM language_item_relationships")
        self.lr.relate(a, b, "translation", source="user")
        r2 = self.m.query_one("SELECT * FROM language_item_relationships")
        self.assertEqual((r1["version"], r2["version"], r2["created_at"]), (1, 2, r1["created_at"]))
        self.assertGreater(r2["updated_at"], r1["updated_at"])
        self.assertEqual([e["event_type"] for e in self.events("language_relationship_learned",
                                                              "language_relationship_updated")],
                         ["language_relationship_learned", "language_relationship_updated"])


class EventStateConsistencyAndReopen(Base):
    def scenario(self):
        self.ls.teach("a", "d1", source="user", confidence=0.6)
        self.ls.teach("a", "d1", source="user")                       # no-op
        self.ls.correct("a", "d2")
        self.ls.relate("a", "b", "is_a", source="user")
        self.ls.teach("b", "db", source="user")                       # stub -> taught
        self.ls.correct("A", "d2")                                    # no-op
        self.ls.teach("a", "d3", source="user")

    def test_versions_equal_teach_plus_correct_events(self):
        self.scenario()
        for name in ("a", "b"):
            n = len([e for e in self.events("teach", "correct") if e["target"] == name])
            self.assertEqual(self.rec(name)["version"], n if name == "a" else n + 1, name)   # b: stub v1 + teach
        self.assertEqual([(e["event_type"], e["target"]) for e in self.events()],
                         [("teach", "a"), ("correct", "a"), ("relate", "a"), ("teach", "b"), ("teach", "a")])
        stamps = [e["created_at"] for e in self.events()]
        self.assertEqual(stamps, sorted(stamps))
        self.assertLessEqual(self.rec("a")["updated_at"], stamps[-1])

    def test_reopen_state_identical_and_transitions_continue(self):
        self.scenario()
        before = self.snap()
        self.reopen()
        self.assertEqual(self.snap(), before)
        self.ls.teach("a", "d3", source="user")                       # still a no-op after reopen
        self.assertEqual(self.snap(), before)
        self.ls.teach("a", "d4", source="user")
        self.assertEqual(self.rec("a")["version"], before["knowledge"][0]["version"] + 1)


if __name__ == "__main__":
    unittest.main()
