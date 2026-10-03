"""Prompt 642 - Section 3: learning deduplication / stability.

Inspection result: production code UNCHANGED. Existing behaviour already
satisfies every requirement (Prompt 632 learn()/teach() no-op, 633/635
correct(), 636 relate()); this file is regression coverage + documentation.

Existing semantics pinned here:
* Identity = exact-case name; one current row per name.
* learn()/teach() no-op iff description, kind, status, source and the
  EFFECTIVE confidence/source_text/learning_method (None = keep stored)
  all match. No-op => no version bump, no updated_at change, no event.
* Comparison is exact: whitespace/casing differences in a description are
  a real update (not normalized - by design, not changed here).
* teach() logs a "teach" event only when the version changed;
  correct() logs a "correct" event only when the version changed.
* Confidence compares with ==, so 1 / 1.0 are the same value.
* Invalid names/descriptions raise ValueError and write nothing.

Documented limitations (contracts preserved):
  L1. teach()'s source defaults to "ael" and is always applied (Prompt 641).
  L2. correct() re-activates a non-"active" status (status=None -> "active"),
      so correcting a stub/other-status record with an identical description
      is a REAL change (version bump) and logs a "correct" event whose detail
      shows identical old/new description ('x' -> 'x').
  L3. Name identity is case-sensitive for learn()/teach(): "a" and "A" are
      two rows (correct() is the case-insensitive path).
  L4. Events do not record confidence/source_text/status changes in detail.
"""
import os
import tempfile
import time
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from language_intelligence.learned_knowledge_context import select_learned_knowledge
from core.core import Core


def _stack(db):
    m = MemorySystem(db)
    k = KnowledgeSystem(m)
    return m, k, LearningSystem(ConceptSystem(k), k, memory=m)


def _dump(m):
    return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("knowledge", "relationships", "learning_events")}


class TestLearningDeduplicationStability(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "m.db")
        self.m, self.k, self.l = _stack(self.db)

    def _ev(self, target="A", etype=None):
        rows = self.m.query("SELECT * FROM learning_events WHERE target = ? ORDER BY id", (target,))
        return [r for r in rows if etype is None or r["event_type"] == etype]

    def _rows(self, name="A"):
        return self.m.query("SELECT * FROM knowledge WHERE name = ?", (name,))

    def _base(self):
        return self.l.teach("A", "desc", source="s", confidence=0.5,
                            source_text="txt", learning_method="ael")

    # ---- repeated identical operations are true no-ops -------------------
    def test_repeated_identical_learn_is_noop(self):
        r1 = self.k.learn("A", "desc", source="s", confidence=0.5, source_text="t", learning_method="m")
        time.sleep(0.01)
        before = _dump(self.m)
        r2 = self.k.learn("A", "desc", source="s", confidence=0.5, source_text="t", learning_method="m")
        r3 = self.k.learn("A", "desc", source="s")  # omitted optional metadata = effective same
        self.assertEqual((r2["version"], r2["updated_at"]), (r1["version"], r1["updated_at"]))
        self.assertEqual(r3, r1)
        self.assertEqual(_dump(self.m), before)
        self.assertEqual(len(self._rows()), 1)

    def test_repeated_identical_teach_is_noop_no_event(self):
        r1 = self._base()
        time.sleep(0.01)
        before = _dump(self.m)
        for _ in range(3):
            r = self.l.teach("A", "desc", source="s", confidence=0.5,
                             source_text="txt", learning_method="ael")
            self.assertEqual((r["version"], r["updated_at"]), (r1["version"], r1["updated_at"]))
        self.l.teach("A", "desc", source="s")  # omitted metadata
        self.assertEqual(_dump(self.m), before)
        self.assertEqual(len(self._ev(etype="teach")), 1)

    def test_repeated_identical_correction_is_noop(self):
        self._base()
        c1 = self.l.correct("A", "new desc")
        time.sleep(0.01)
        before = _dump(self.m)
        c2 = self.l.correct("A", "new desc")
        c3 = self.l.correct("a", "new desc")  # case-insensitive resolution, same effective state
        self.assertEqual((c2["version"], c2["updated_at"]), (c1["version"], c1["updated_at"]))
        self.assertEqual(c3["version"], c1["version"])
        self.assertEqual(_dump(self.m), before)
        self.assertEqual(len(self._ev(etype="correct")), 1)

    def test_repeated_source_operation_follows_existing_semantics(self):
        self._base()
        n = len(self._ev())
        v = self.k.get("A")["version"]
        self.l.teach("A", "desc", source="s")           # same explicit source -> no-op
        self.assertEqual((self.k.get("A")["version"], len(self._ev())), (v, n))
        self.l.teach("A", "desc", source="other")       # different source -> real
        self.assertEqual((self.k.get("A")["version"], len(self._ev())), (v + 1, n + 1))
        self.l.teach("A", "desc", source="other")       # repeat -> no-op
        self.assertEqual((self.k.get("A")["version"], len(self._ev())), (v + 1, n + 1))
        self.l.teach("A", "desc")                       # omitted -> default "ael" (L1) real once
        self.assertEqual(self.k.get("A")["source"], "ael")
        self.assertEqual((self.k.get("A")["version"], len(self._ev())), (v + 2, n + 2))
        self.l.teach("A", "desc")                       # repeat of the default -> no-op
        self.assertEqual((self.k.get("A")["version"], len(self._ev())), (v + 2, n + 2))

    def test_confidence_int_float_equivalence_is_noop(self):
        self.l.teach("A", "d", source="s", confidence=1)
        v = self.k.get("A")["version"]
        self.l.teach("A", "d", source="s", confidence=1.0)
        self.assertEqual(self.k.get("A")["version"], v)

    # ---- real changes stay real ------------------------------------------
    def _assert_real(self, fn, expected_event_delta=1):
        self._base()
        time.sleep(0.01)
        b = self.k.get("A")
        n = len(self._ev())
        fn()
        a = self.k.get("A")
        self.assertEqual(a["version"], b["version"] + 1)
        self.assertNotEqual(a["updated_at"], b["updated_at"])
        self.assertEqual(a["created_at"], b["created_at"])
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(self._ev()), n + expected_event_delta)
        self.assertEqual(len(self._rows()), 1)
        return b, a

    def test_real_description_change(self):
        b, a = self._assert_real(lambda: self.l.teach(
            "A", "other", source="s", confidence=0.5, source_text="txt", learning_method="ael"))
        self.assertEqual(a["description"], "other")
        self.assertEqual(self._ev(etype="teach")[-1]["detail"], "other")

    def test_real_confidence_change(self):
        b, a = self._assert_real(lambda: self.l.teach("A", "desc", source="s", confidence=0.9))
        self.assertEqual(a["confidence"], 0.9)
        self.assertEqual((a["source_text"], a["learning_method"]), ("txt", "ael"))

    def test_real_source_change(self):
        b, a = self._assert_real(lambda: self.l.teach("A", "desc", source="other"))
        self.assertEqual(a["source"], "other")
        self.assertEqual(self._ev(etype="teach")[-1]["source"], "other")

    def test_real_source_text_and_method_change(self):
        self._assert_real(lambda: self.l.teach("A", "desc", source="s", source_text="new text"))
        self.m.query("SELECT 1")
        v = self.k.get("A")["version"]
        self.l.teach("A", "desc", source="s", learning_method="nlu")
        self.assertEqual(self.k.get("A")["version"], v + 1)

    def test_real_correction_change_increments_once(self):
        self._base()
        n = len(self._ev(etype="correct"))
        self.l.correct("A", "corrected")
        self.assertEqual(len(self._ev(etype="correct")), n + 1)
        self.assertEqual(self.k.get("A")["version"], 2)

    def test_whitespace_and_case_are_not_normalized(self):
        self._base()
        v = self.k.get("A")["version"]
        self.l.teach("A", "desc ", source="s")
        self.assertEqual(self.k.get("A")["version"], v + 1)
        self.l.teach("A", "Desc ", source="s")
        self.assertEqual(self.k.get("A")["version"], v + 2)
        self.assertEqual(len(self._rows()), 1)

    def test_name_identity_is_case_sensitive_for_teach_L3(self):
        self._base()
        self.l.teach("a", "desc", source="s")
        self.assertEqual(len(self.k.all()), 2)

    def test_correction_of_stub_status_is_real_change_L2(self):
        self.k.learn("B", "bee", source="ael", status="stub")
        v = self.k.get("B")["version"]
        self.l.correct("B", "bee")
        self.assertEqual(self.k.get("B")["version"], v + 1)
        self.assertEqual(self.k.get("B")["status"], "active")
        self.l.correct("B", "bee")
        self.assertEqual(self.k.get("B")["version"], v + 1)

    # ---- events / history ------------------------------------------------
    def test_no_duplicate_events_and_history_not_current(self):
        self._base()
        self.l.teach("A", "desc", source="s")
        self.l.correct("A", "new desc")
        self.l.correct("A", "new desc")
        self.assertEqual([e["event_type"] for e in self._ev()], ["teach", "correct"])
        self.assertEqual([r["name"] for r in self.k.all()], ["A"])
        self.assertEqual(self.k.get("A")["description"], "new desc")
        self.assertEqual([r["description"] for r in self.k.search("desc")], ["new desc"])
        sel = select_learned_knowledge("A?", self.k, candidate_terms=["a"])
        self.assertEqual(sel.record["description"], "new desc")
        # an event's target/detail text never becomes a knowledge row
        self.assertEqual(self.k.search("Python"), [])

    # ---- relationships ---------------------------------------------------
    def test_relationships_unchanged_by_repeated_learning(self):
        self._base()
        self.l.relate("A", "B", "is_a", source="s", confidence=0.4, source_text="r", learning_method="ael")
        self.l.relate("C", "D", "part_of", source="s")
        rel = [dict(r) for r in self.m.query("SELECT * FROM relationships ORDER BY id")]
        rel_ev = len(self.m.query("SELECT * FROM learning_events WHERE event_type='relate'"))
        for _ in range(3):
            self.l.teach("A", "desc", source="s", confidence=0.5, source_text="txt", learning_method="ael")
            self.l.correct("A", "desc")
        self.l.teach("A", "changed", source="s")
        self.l.correct("A", "changed again")
        self.assertEqual([dict(r) for r in self.m.query("SELECT * FROM relationships ORDER BY id")], rel)
        # 636 idempotency still intact
        self.l.relate("A", "B", "is_a", source="s", confidence=0.4, source_text="r", learning_method="ael")
        self.l.relate("A", "B", "is_a", source="s")
        self.assertEqual([dict(r) for r in self.m.query("SELECT * FROM relationships ORDER BY id")], rel)
        self.assertEqual(len(self.m.query("SELECT * FROM learning_events WHERE event_type='relate'")), rel_ev)

    def test_stub_promotion_by_teach_is_single_real_change(self):
        self.l.relate("A", "B", "is_a", source="ael")
        self.assertEqual(self.k.get("B")["status"], "stub")
        self.l.teach("B", "bee", source="ael")
        v, n = self.k.get("B")["version"], len(self._ev("B"))
        self.l.teach("B", "bee", source="ael")
        self.assertEqual((self.k.get("B")["version"], len(self._ev("B"))), (v, n))
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 1)

    def test_repeated_natural_language_learning_is_noop(self):
        core = Core(memory_db_path=os.path.join(self.tmp, "c.db"),
                    skill_definitions_dir=os.path.join(self.tmp, "s"))
        core.learn_from_text("Python is a language.")
        before = _dump(core.memory)
        core.learn_from_text("Python is a language.")
        self.assertEqual(_dump(core.memory), before)

    # ---- retrieval stability & read-only ----------------------------------
    def test_current_retrieval_stable_and_read_only(self):
        self._base()
        self.l.teach("A", "desc", source="s")
        before = _dump(self.m)
        outs = set()
        for _ in range(3):
            self.k.get("A"); self.k.all(); self.k.search("desc")
            outs.add(repr((self.k.get("A"), self.k.search("desc"), self.k.all())))
            select_learned_knowledge("A?", self.k, candidate_terms=["a"]).to_context()
        self.assertEqual(len(outs), 1)
        self.assertEqual(_dump(self.m), before)

    # ---- invalid input ---------------------------------------------------
    def test_invalid_input_behaviour_unchanged_and_writes_nothing(self):
        self._base()
        before = _dump(self.m)
        for bad in ("", "   ", None, 5):
            with self.assertRaises(ValueError):
                self.l.teach(bad, "x")
            with self.assertRaises(ValueError):
                self.k.learn(bad, "x")
            with self.assertRaises(ValueError):
                self.l.correct(bad, "x")
        for bad in ("", "   ", None):
            with self.assertRaises(ValueError):
                self.l.correct("A", bad)
        self.assertIsNone(self.l.correct("Missing", "x"))
        self.assertEqual(_dump(self.m), before)
        z = self.l.teach("Z", None)   # None description on teach remains accepted
        self.assertIsNone(z["description"])
        n = len(self._ev("Z"))
        self.l.teach("Z", None)
        self.assertEqual(len(self._ev("Z")), n)

    # ---- persistence -----------------------------------------------------
    def test_noop_and_real_change_behaviour_survive_reopen(self):
        self._base()
        self.l.relate("A", "B", "is_a", source="s", confidence=0.4)
        self.l.correct("A", "new desc")
        self.m._conn.close()

        m2, k2, l2 = _stack(self.db)
        before = _dump(m2)
        l2.teach("A", "new desc", source="s")
        l2.correct("A", "new desc")
        l2.relate("A", "B", "is_a", source="s", confidence=0.4)
        self.assertEqual(_dump(m2), before)
        self.assertEqual(len(m2.query("SELECT * FROM knowledge WHERE name='A'")), 1)

        n = len(m2.query("SELECT * FROM learning_events"))
        l2.teach("A", "new desc", source="s", confidence=0.8)   # real change after reopen
        self.assertEqual(len(m2.query("SELECT * FROM learning_events")), n + 1)
        self.assertEqual(k2.get("A")["version"], 3)
        m2._conn.close()

        m3, k3, l3 = _stack(self.db)
        b3 = _dump(m3)
        l3.teach("A", "new desc", source="s", confidence=0.8)
        self.assertEqual(_dump(m3), b3)
        self.assertEqual(k3.get("A")["confidence"], 0.8)


if __name__ == "__main__":
    unittest.main()
