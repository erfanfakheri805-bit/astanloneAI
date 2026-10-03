"""Prompt 644 - Section 3: learning-event history integrity.

Inspection result. Existing event lifecycle (unchanged):
  teach()   -> "teach"  event iff the persisted version changed
               (target=name, detail=new description, source=persisted source)
  correct() -> "correct" event iff the persisted version changed
               (target=stored name, detail="'old' -> 'new'")
  relate()  -> "relate" event iff the relationship row changed/was created
               (target=from_name, detail="<relation> -> <to_name>")
  learn()/KnowledgeSystem.* write no events themselves.

Two genuine inconsistencies were found and fixed (narrowly):
  F1. correct() logged the raw `source` ARGUMENT (None when omitted) instead
      of the persisted source (correct() keeps the stored source when None).
      relate() had the same argument-vs-persisted mismatch when source=None.
      Events now log the persisted source. Record semantics are unchanged.
  F2. A REJECTED relate() (blank/non-string endpoint, or relation_type None)
      could leave orphan stub knowledge rows with no history: stubs were
      created for the valid endpoint before the invalid one raised. Inputs
      are now validated before any write; ValueError is raised and nothing is
      persisted. (relation_type None previously failed with sqlite3.
      IntegrityError after the stubs had been written; it is now ValueError.
      An empty-string relation_type is still accepted - existing contract.)

Remaining limitations (documented, not changed):
  L1. Stub concepts auto-created by relate() have no event of their own;
      the "relate" event on from_name covers them.
  L2. teach()/correct() events do not carry confidence/source_text/status
      changes; a status-only correct() logs "'x' -> 'x'".
  L3. Events are separate writes from the knowledge write (no shared
      transaction).
"""
import os
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from core.core import Core


def _stack(db):
    m = MemorySystem(db)
    k = KnowledgeSystem(m)
    return m, k, LearningSystem(ConceptSystem(k), k, memory=m)


def _events(m):
    return [dict(r) for r in m.query("SELECT * FROM learning_events ORDER BY id")]


def _sig(m):
    return [(e["event_type"], e["target"], e["detail"], e["source"]) for e in _events(m)]


def _dump(m):
    return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("knowledge", "relationships", "learning_events")}


class TestLearningEventHistoryIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "m.db")
        self.m, self.k, self.l = _stack(self.db)

    # 1. creation
    def test_creation_logs_one_teach_event_matching_persisted_state(self):
        r = self.l.teach("Python", "a snake", source="wiki", confidence=0.6,
                         source_text="t", learning_method="ael")
        self.assertEqual(_sig(self.m), [("teach", "Python", "a snake", "wiki")])
        rec = self.k.get("Python")
        ev = _events(self.m)[0]
        self.assertEqual((ev["target"], ev["detail"], ev["source"]),
                         (rec["name"], rec["description"], rec["source"]))
        self.assertEqual(r["version"], 1)

    # 2. genuine update
    def test_genuine_update_logs_one_event_with_new_persisted_values(self):
        self.l.teach("Python", "a snake", source="wiki")
        self.l.teach("Python", "a language", source="book")
        self.assertEqual(_sig(self.m), [("teach", "Python", "a snake", "wiki"),
                                         ("teach", "Python", "a language", "book")])
        rec = self.k.get("Python")
        self.assertEqual((rec["description"], rec["source"], rec["version"]), ("a language", "book", 2))
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge")), 1)

    # 3. exact no-op learning
    def test_exact_noop_learn_and_teach_add_no_event(self):
        self.k.learn("Rust", "sys", source="s")            # learn() itself never logs
        self.assertEqual(_events(self.m), [])
        self.l.teach("Python", "a snake", source="wiki")
        n = len(_events(self.m))
        before = _dump(self.m)
        self.l.teach("Python", "a snake", source="wiki")
        self.k.learn("Python", "a snake", source="wiki")
        self.assertEqual(len(_events(self.m)), n)
        self.assertEqual(_dump(self.m), before)

    # 4/5. relationships
    def test_relationship_create_noop_and_change(self):
        self.l.relate("A", "B", "is_a", source="ael", confidence=0.5, source_text="x")
        self.assertEqual(_sig(self.m), [("relate", "A", "is_a -> B", "ael")])
        before = _dump(self.m)
        self.l.relate("A", "B", "is_a", source="ael", confidence=0.5, source_text="x")
        self.l.relate("A", "B", "is_a", source="ael")            # omitted metadata = same
        self.assertEqual(_dump(self.m), before)                  # no-op: no event, no churn
        self.l.relate("A", "B", "is_a", source="ael", confidence=0.9)   # genuine change
        self.assertEqual(_sig(self.m), [("relate", "A", "is_a -> B", "ael")] * 2)
        rel = self.m.query("SELECT * FROM relationships")
        self.assertEqual(len(rel), 1)
        self.assertEqual((rel[0]["confidence"], rel[0]["source_text"]), (0.9, "x"))

    def test_relate_event_source_is_persisted_source_F1(self):
        self.l.relate("A", "B", "is_a", source="wiki", confidence=0.5)
        self.l.relate("A", "B", "is_a", source=None, confidence=0.7)   # keeps stored source
        rel = self.m.query_one("SELECT * FROM relationships")
        self.assertEqual(rel["source_type"], "wiki")
        self.assertEqual([e["source"] for e in _events(self.m)], ["wiki", "wiki"])

    # 6. genuine correction
    def test_genuine_correction_logs_old_and_new(self):
        self.l.teach("Python", "a snake", source="wiki", confidence=0.6)
        self.l.correct("Python", "a language", source="user_correction")
        self.assertEqual(_sig(self.m)[-1],
                         ("correct", "Python", "'a snake' -> 'a language'", "user_correction"))
        self.assertEqual(len(_events(self.m)), 2)

    def test_correct_event_source_is_persisted_source_when_omitted_F1(self):
        self.l.teach("Python", "a snake", source="wiki")
        self.l.correct("Python", "a language")            # source omitted
        rec = self.k.get("Python")
        self.assertEqual(rec["source"], "wiki")           # record semantics unchanged
        self.assertEqual(_events(self.m)[-1]["source"], "wiki")

    def test_correction_via_case_insensitive_name_logs_stored_name(self):
        self.l.teach("Python", "a snake", source="wiki")
        self.l.correct("python", "a language")
        self.assertEqual(_events(self.m)[-1]["target"], "Python")

    # 7. repeated correction no-op
    def test_repeated_correction_adds_no_second_correct_event(self):
        self.l.teach("Python", "a snake", source="wiki")
        self.l.correct("Python", "a language")
        before = _dump(self.m)
        self.l.correct("Python", "a language")
        self.l.correct("python", "a language")
        self.assertEqual(_dump(self.m), before)
        self.assertEqual(len([e for e in _events(self.m) if e["event_type"] == "correct"]), 1)

    def test_repeated_core_correction_adds_no_second_knowledge_correct_event(self):
        core = Core(memory_db_path=os.path.join(self.tmp, "c.db"),
                    skill_definitions_dir=os.path.join(self.tmp, "s"))
        core.learning.teach("Python", "a snake")
        core.process_input("not a snake, I mean a programming language.")
        n = len([e for e in _events(core.memory) if e["event_type"] == "correct"])
        core.process_input("not a snake, I mean a programming language.")
        self.assertEqual(len([e for e in _events(core.memory) if e["event_type"] == "correct"]), n)
        self.assertEqual(n, 1)
        self.assertEqual(core.knowledge.get("Python")["version"], 2)

    # 8. rejected input
    def test_rejected_operations_create_no_events_or_rows(self):
        self.l.teach("Python", "a snake", source="wiki")
        before = _dump(self.m)
        for bad in ("", "  ", None, 5):
            with self.assertRaises(ValueError):
                self.l.teach(bad, "x")
            with self.assertRaises(ValueError):
                self.l.correct(bad, "x")
        for bad in ("", "  ", None):
            with self.assertRaises(ValueError):
                self.l.correct("Python", bad)
        self.assertIsNone(self.l.correct("Missing", "x"))
        self.assertEqual(_dump(self.m), before)

    def test_rejected_relate_leaves_no_orphan_stub_or_event_F2(self):
        self.l.teach("Python", "a snake", source="wiki")
        before = _dump(self.m)
        for args in (("New1", "", "is_a"), ("", "New2", "is_a"), (None, "New3", "is_a"),
                     ("New4", None, "is_a"), ("  ", "New5", "is_a"), ("New6", 5, "is_a"),
                     ("New7", "New8", None)):
            with self.assertRaises(ValueError, msg=str(args)):
                self.l.relate(*args)
        self.assertEqual(_dump(self.m), before)   # no stubs, no relationships, no events

    def test_empty_relation_type_string_contract_unchanged(self):
        self.assertTrue(self.l.relate("A", "B", "")["created"])

    def test_non_learning_natural_language_creates_no_events(self):
        core = Core(memory_db_path=os.path.join(self.tmp, "c2.db"),
                    skill_definitions_dir=os.path.join(self.tmp, "s2"))
        for text in ("What is Python?", "Hello", "Python is", "", "   "):
            core.learn_from_text(text)
        self.assertEqual(_events(core.memory), [])
        self.assertEqual(core.knowledge.all(), [])

    # 9. deterministic ordering
    def test_event_order_is_deterministic_for_sequential_operations(self):
        def run(db):
            m, k, l = _stack(db)
            l.teach("A", "a1", source="s")
            l.teach("B", "b1", source="s")
            l.relate("A", "B", "is_a", source="s")
            l.correct("A", "a2")
            l.teach("A", "a2", source="other")
            l.teach("A", "a2", source="other")     # no-op
            return _sig(m), [e["id"] for e in _events(m)], m
        s1, ids1, m1 = run(os.path.join(self.tmp, "x1.db"))
        s2, ids2, m2 = run(os.path.join(self.tmp, "x2.db"))
        self.assertEqual(s1, s2)
        self.assertEqual(ids1, sorted(ids1))
        self.assertEqual(ids1, list(range(1, len(ids1) + 1)))
        self.assertEqual([e["event_type"] for e in _events(m1)],
                         ["teach", "teach", "relate", "correct", "teach"])
        self.assertEqual([dict(e) for e in m1.recent_learning_events(50)], _events(m1))
        self.assertEqual([e["id"] for e in m1.recent_learning_events(2)], ids1[-2:])

    # 10/11/12. persisted-state correspondence, provenance & version semantics
    def test_events_reflect_persisted_state_and_version_semantics(self):
        self.l.teach("Python", "a snake", source="wiki", confidence=0.6,
                     source_text="t", learning_method="ael")
        r1 = self.k.get("Python")
        self.l.correct("Python", "a language")
        r2 = self.k.get("Python")
        self.assertEqual((r2["version"], r2["source"], r2["confidence"], r2["source_text"],
                          r2["learning_method"]), (2, "wiki", 0.6, "t", "ael"))
        self.assertEqual((r2["created_at"], r2["id"]), (r1["created_at"], r1["id"]))
        self.assertGreater(r2["updated_at"], r1["updated_at"])
        ev = _events(self.m)[-1]
        self.assertEqual(ev["detail"], f"{r1['description']!r} -> {r2['description']!r}")
        self.assertEqual(ev["source"], r2["source"])
        # every event count equals the number of persisted version bumps (1 create + 1 update)
        self.assertEqual(len(_events(self.m)), r2["version"])

    def test_history_is_not_current_knowledge(self):
        self.l.teach("Python", "a snake")
        self.l.correct("Python", "a language")
        self.assertEqual([r["name"] for r in self.k.all()], ["Python"])
        self.assertEqual(self.k.search("snake"), [])

    # 13. persistence
    def test_event_history_identical_after_reopen(self):
        self.l.teach("A", "a1", source="s")
        self.l.relate("A", "B", "is_a", source="s", confidence=0.4)
        self.l.correct("A", "a2")
        self.l.teach("A", "a2", source="t")
        before = _events(self.m)
        self.m._conn.close()
        m2, k2, l2 = _stack(self.db)
        self.assertEqual(_events(m2), before)
        # no-ops after reopen still add nothing; a real change appends exactly one
        l2.teach("A", "a2", source="t")
        l2.correct("A", "a2")
        l2.relate("A", "B", "is_a", source="s", confidence=0.4)
        self.assertEqual(_events(m2), before)
        l2.correct("A", "a3")
        after = _events(m2)
        self.assertEqual(after[:-1], before)
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(after[-1]["id"], before[-1]["id"] + 1)

    def test_rejected_relate_persists_nothing_across_reopen_F2(self):
        with self.assertRaises(ValueError):
            self.l.relate("Solo", "", "is_a")
        self.m._conn.close()
        m2, k2, _ = _stack(self.db)
        self.assertEqual(k2.all(), [])
        self.assertEqual(_events(m2), [])


if __name__ == "__main__":
    unittest.main()
