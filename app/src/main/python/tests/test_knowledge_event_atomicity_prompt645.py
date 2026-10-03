"""Prompt 645 - Section 3: knowledge mutation + learning event atomicity.

Inspection result: MemorySystem._run() committed every statement on its own,
so a knowledge/relationship write and its learning event (a second _run) were
two separate commits - a genuine integrity gap (documented as L3 in Prompt
644). Fix: MemorySystem._atomic() (minimal re-entrant transaction scope),
used by LearningSystem.teach/correct/relate and KnowledgeSystem.relate.

All failures are injected deterministically at the persistence boundary
(MemorySystem.add_learning_event / MemorySystem._run); no timing or crashes.
"""
import os
import tempfile
import unittest
from unittest import mock

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem


class Boom(RuntimeError):
    pass


def _stack(db):
    m = MemorySystem(db)
    k = KnowledgeSystem(m)
    return m, k, LearningSystem(ConceptSystem(k), k, memory=m)


def _dump(m):
    return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("knowledge", "relationships", "learning_events")}


class AtomicityBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "m.db")
        self.m, self.k, self.ls = _stack(self.db)

    def tearDown(self):
        self.m._conn.close()
        self.tmp.cleanup()

    def reopen(self):
        self.m._conn.close()
        self.m, self.k, self.ls = _stack(self.db)
        return self.m

    @staticmethod
    def fail_event(m):
        return mock.patch.object(type(m), "add_learning_event", side_effect=Boom("event"))

    @staticmethod
    def fail_event_after_write(m):
        orig = type(m).add_learning_event

        def _after(self, *a, **kw):
            orig(self, *a, **kw)      # event row written inside the txn...
            raise Boom("after event")  # ...then failure
        return mock.patch.object(type(m), "add_learning_event", _after)

    @staticmethod
    def fail_sql(m, needle):
        orig = type(m)._run

        def _run(self, sql, params=()):
            if needle in sql:
                raise Boom("sql")
            return orig(self, sql, params)
        return mock.patch.object(type(m), "_run", _run)

    @staticmethod
    def fail_sql_after(m, needle):
        orig = type(m)._run

        def _run(self, sql, params=()):
            cur = orig(self, sql, params)
            if needle in sql:
                raise Boom("sql after")
            return cur
        return mock.patch.object(type(m), "_run", _run)


class SuccessPaths(AtomicityBase):
    def test_1_teach_persists_knowledge_and_event(self):
        e = self.ls.teach("Python", "a language", source="user")
        self.assertEqual(e["version"], 1)
        d = _dump(self.m)
        self.assertEqual(len(d["knowledge"]), 1)
        self.assertEqual([(x["event_type"], x["target"], x["detail"], x["source"])
                          for x in d["learning_events"]], [("teach", "Python", "a language", "user")])

    def test_2_relate_persists_relationship_and_event(self):
        r = self.ls.relate("A", "B", "is_a", source="user", confidence=0.5)
        self.assertTrue(r["created"])
        d = _dump(self.m)
        self.assertEqual(len(d["relationships"]), 1)
        self.assertEqual({x["name"] for x in d["knowledge"]}, {"A", "B"})
        self.assertEqual([(x["event_type"], x["target"], x["detail"]) for x in d["learning_events"]],
                         [("relate", "A", "is_a -> B")])

    def test_correct_persists_both_and_event_order(self):
        self.ls.teach("X", "old", source="user")
        self.ls.correct("X", "new", source="user_correction")
        ev = _dump(self.m)["learning_events"]
        self.assertEqual([x["event_type"] for x in ev], ["teach", "correct"])
        self.assertEqual(ev[1]["detail"], "'old' -> 'new'")
        self.assertEqual(self.k.get("X")["version"], 2)


class FailurePaths(AtomicityBase):
    def test_3a_event_failure_rolls_back_teach_insert(self):
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.ls.teach("X", "d")
        d = _dump(self.m)
        self.assertEqual((d["knowledge"], d["learning_events"]), ([], []))

    def test_3b_event_failure_rolls_back_teach_update(self):
        self.ls.teach("X", "d1")
        before = _dump(self.m)
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.ls.teach("X", "d2")
        self.assertEqual(_dump(self.m), before)
        self.assertEqual(self.k.get("X")["version"], 1)

    def test_3c_event_failure_rolls_back_correct(self):
        self.ls.teach("X", "d1")
        before = _dump(self.m)
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.ls.correct("X", "d2")
        self.assertEqual(_dump(self.m), before)

    def test_3d_event_failure_rolls_back_relate_and_stubs(self):
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.ls.relate("A", "B", "is_a")
        d = _dump(self.m)
        self.assertEqual((d["knowledge"], d["relationships"], d["learning_events"]), ([], [], []))

    def test_3e_event_failure_rolls_back_relationship_refresh(self):
        self.ls.relate("A", "B", "is_a", confidence=0.1)
        before = _dump(self.m)
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.ls.relate("A", "B", "is_a", confidence=0.9)
        self.assertEqual(_dump(self.m), before)

    def test_4a_failure_after_event_write_leaves_no_partial_state(self):
        with self.fail_event_after_write(self.m), self.assertRaises(Boom):
            self.ls.teach("X", "d")
        d = _dump(self.m)
        self.assertEqual((d["knowledge"], d["learning_events"]), ([], []))

    def test_4b_knowledge_write_failure_leaves_no_event(self):
        with self.fail_sql(self.m, "INSERT INTO knowledge"), self.assertRaises(Boom):
            self.ls.teach("X", "d")
        with self.fail_sql_after(self.m, "INSERT INTO knowledge"), self.assertRaises(Boom):
            self.ls.teach("Y", "d")
        d = _dump(self.m)
        self.assertEqual((d["knowledge"], d["learning_events"]), ([], []))

    def test_4c_relationship_write_failure_leaves_no_event_or_stubs(self):
        with self.fail_sql_after(self.m, "INSERT INTO relationships"), self.assertRaises(Boom):
            self.ls.relate("A", "B", "is_a")
        d = _dump(self.m)
        self.assertEqual((d["knowledge"], d["relationships"], d["learning_events"]), ([], [], []))

    def test_4d_knowledge_relate_alone_is_atomic_with_its_stubs(self):
        with self.fail_sql(self.m, "INSERT INTO relationships"), self.assertRaises(Boom):
            self.k.relate("A", "B", "is_a")
        d = _dump(self.m)
        self.assertEqual((d["knowledge"], d["relationships"]), ([], []))

    def test_correct_knowledge_failure_leaves_no_event(self):
        self.ls.teach("X", "d1")
        before = _dump(self.m)
        with self.fail_sql(self.m, "UPDATE knowledge"), self.assertRaises(Boom):
            self.ls.correct("X", "d2")
        self.assertEqual(_dump(self.m), before)

    def test_9_connection_usable_after_failure_and_no_leaked_scope(self):
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.ls.teach("X", "d")
        self.assertEqual(self.m._atomic_depth, 0)
        self.ls.teach("X", "d")   # normal write afterwards commits
        self.assertFalse(self.m._conn.in_transaction)
        d = _dump(self.reopen())
        self.assertEqual((len(d["knowledge"]), len(d["learning_events"])), (1, 1))


class NoOpsAndCompat(AtomicityBase):
    def test_5_idempotent_repeats_write_nothing(self):
        self.ls.teach("X", "d", source="user", confidence=0.7)
        self.ls.relate("X", "Y", "is_a", source="user", confidence=0.7)
        before = _dump(self.m)
        writes = []
        orig = type(self.m)._run

        def spy(mem, sql, params=()):
            writes.append(sql)
            return orig(mem, sql, params)
        with mock.patch.object(type(self.m), "_run", spy):
            self.ls.teach("X", "d", source="user", confidence=0.7)
            self.ls.relate("X", "Y", "is_a", source="user", confidence=0.7)
        self.assertEqual(_dump(self.m), before)
        self.assertFalse([w for w in writes if w.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))])

    def test_6_correction_behaviour_intact(self):
        self.ls.teach("Python", "old", source="user", confidence=0.9)
        e = self.ls.correct("python", "new", source="user_correction")
        self.assertEqual((e["name"], e["description"], e["version"], e["source"], e["confidence"]),
                         ("Python", "new", 2, "user_correction", 0.9))
        self.assertIsNone(self.ls.correct("Nope", "x"))
        self.assertEqual(len(self.k.all()), 1)
        n = len(_dump(self.m)["learning_events"])
        self.ls.correct("Python", "new", source="user_correction")   # identical -> no-op
        self.assertEqual(len(_dump(self.m)["learning_events"]), n)
        with self.assertRaises(ValueError):
            self.ls.correct("Python", "  ")

    def test_7_relationship_behaviour_intact(self):
        self.assertTrue(self.ls.relate("A", "B", "is_a", source="user")["created"])
        self.assertFalse(self.ls.relate("A", "B", "is_a", source="user")["created"])
        r = self.ls.relate("A", "B", "is_a", source="user", confidence=0.4)
        self.assertFalse(r["created"])
        self.assertEqual(self.k.relationships_for("A")["outgoing"][0]["confidence"], 0.4)
        self.assertEqual(len(self.k.relationships_for("A")["outgoing"]), 1)
        self.assertEqual([e["event_type"] for e in _dump(self.m)["learning_events"]], ["relate", "relate"])
        with self.assertRaises(ValueError):
            self.ls.relate("", "B", "is_a")
        self.assertEqual({x["name"] for x in self.k.all()}, {"A", "B"})

    def test_8_reopen_preserves_atomic_result(self):
        self.ls.teach("X", "d", source="user")
        self.ls.relate("X", "Y", "is_a", source="user")
        before = _dump(self.m)
        d = _dump(self.reopen())
        self.assertEqual(d, before)
        self.assertEqual(len(d["learning_events"]), 2)

    def test_nested_atomic_joins_outer_and_rolls_back_together(self):
        with self.assertRaises(Boom):
            with self.m._atomic():
                self.ls.teach("X", "d")       # inner scope joins outer
                raise Boom("outer")
        d = _dump(self.m)
        self.assertEqual((d["knowledge"], d["learning_events"]), ([], []))

    def test_memoryless_learning_system_unchanged(self):
        m = MemorySystem(os.path.join(self.tmp.name, "n.db"))
        k = KnowledgeSystem(m)
        ls = LearningSystem(ConceptSystem(k), k)
        self.assertEqual(ls.teach("X", "d")["version"], 1)
        self.assertEqual(m.query("SELECT * FROM learning_events"), [])
        m._conn.close()

    def test_9_no_orphans_after_mixed_failures(self):
        self.ls.teach("Keep", "ok")
        for ctx, call in (
            (self.fail_event(self.m), lambda: self.ls.teach("A", "d")),
            (self.fail_event(self.m), lambda: self.ls.relate("B", "C", "r")),
            (self.fail_sql(self.m, "INSERT INTO knowledge"), lambda: self.ls.teach("D", "d")),
        ):
            with ctx, self.assertRaises(Boom):
                call()
        d = _dump(self.reopen())
        self.assertEqual([x["name"] for x in d["knowledge"]], ["Keep"])
        self.assertEqual([x["target"] for x in d["learning_events"]], ["Keep"])
        self.assertEqual(d["relationships"], [])


if __name__ == "__main__":
    unittest.main()
