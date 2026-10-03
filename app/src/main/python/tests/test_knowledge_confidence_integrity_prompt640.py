"""Prompt 640 - Section 3: integrity of confidence/evidence metadata on
persistent knowledge. Pins the EXISTING semantics (no production change):

  * KnowledgeSystem.learn(): confidence=None on an UPDATE keeps the stored
    value; a brand-new entry with None is stored at the documented 1.0
    default (an existing KnowledgeSystem policy, also applied to
    relate()-created stubs). An explicit value replaces the stored one.
  * correct()/teach()/relate() pass `confidence` straight through with the
    same "None = keep what is stored" policy. relationships never get a
    default: a missing relationship confidence stays NULL.
  * There is no confidence validation at storage; the existing validation
    lives in the consumers: the learned-knowledge gate treats a value that
    is not a number in [0.0, 1.0] as invalid evidence (None -> its
    documented 1.0 display/decision fallback), and the NL learning decision
    rejects too-low confidence.
  * learning_events record the description transition only - they never
    carry, and are never read as, current confidence.
"""
import os
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from learning.learned_knowledge_gate import (
    evaluate_learned_knowledge_gate, STATUS_PASSED, STATUS_REJECTED,
    REASON_NO_EVIDENCE, REASON_INSUFFICIENT_RELIABILITY)
from language_intelligence.learned_knowledge_context import select_learned_knowledge


def _stack(db):
    m = MemorySystem(db)
    k = KnowledgeSystem(m)
    return m, k, LearningSystem(ConceptSystem(k), k, memory=m)


def _dump(m):
    return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("knowledge", "relationships", "learning_events")}


class TestConfidenceIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "m.db")
        self.m, self.k, self.l = _stack(self.db)

    def conf(self, name="Python"):
        return self.k.get(name)["confidence"]

    def ctx(self, message="Python", terms=("python",)):
        return select_learned_knowledge(message, self.k, candidate_terms=list(terms))

    # --- preservation ------------------------------------------------------
    def test_relearning_without_confidence_preserves_it(self):
        self.l.teach("Python", "a snake", confidence=0.6)
        self.l.teach("Python", "a language")           # omitted
        self.k.learn("Python", "a language", source="ael")  # omitted, direct API
        self.assertEqual(self.conf(), 0.6)

    def test_explicit_confidence_replaces_stored_value(self):
        self.l.teach("Python", "a snake", confidence=0.6)
        before = self.k.get("Python")
        self.l.teach("Python", "a snake", confidence=0.9)  # only confidence differs
        after = self.k.get("Python")
        self.assertEqual(after["confidence"], 0.9)
        self.assertEqual(after["version"], before["version"] + 1)
        self.assertEqual(after["description"], "a snake")

    def test_explicit_zero_is_honoured_not_treated_as_missing(self):
        self.l.teach("Python", "a snake", confidence=0.6)
        self.l.teach("Python", "a snake", confidence=0.0)
        self.assertEqual(self.conf(), 0.0)

    def test_identical_effective_relearn_is_noop_without_event(self):
        self.l.teach("Python", "a snake", confidence=0.6, source_text="s", learning_method="ael")
        state, changes = _dump(self.m), self.m._conn.total_changes
        self.l.teach("Python", "a snake", confidence=0.6, source_text="s", learning_method="ael")
        self.l.teach("Python", "a snake")  # omitted confidence == same effective value
        self.assertEqual(self.m._conn.total_changes, changes)
        self.assertEqual(_dump(self.m), state)

    # --- correction lifecycle -----------------------------------------------------
    def test_correction_preserves_confidence_when_omitted(self):
        self.l.teach("Python", "a snake", confidence=0.6)
        self.l.correct("Python", "a language")
        self.l.correct("python", "a programming language")  # case-insensitive path
        self.assertEqual(self.conf(), 0.6)

    def test_explicit_correction_confidence_follows_existing_semantics(self):
        self.l.teach("Python", "a snake", confidence=0.6)
        e = self.l.correct("Python", "a language", confidence=0.95)
        self.assertEqual(e["confidence"], 0.95)
        e = self.l.correct("Python", "a language")  # later omit -> keeps 0.95
        self.assertEqual(e["confidence"], 0.95)
        e = self.l.correct("Python", "a language", confidence=0.0)
        self.assertEqual(e["confidence"], 0.0)

    def test_identical_correction_is_noop_and_does_not_reset_confidence(self):
        self.l.teach("Python", "a snake", confidence=0.6)
        self.l.correct("Python", "a language", confidence=0.8)
        state, changes = _dump(self.m), self.m._conn.total_changes
        self.l.correct("Python", "a language")
        self.l.correct("PYTHON", "a language", confidence=0.8)
        self.assertEqual(self.m._conn.total_changes, changes)
        self.assertEqual(_dump(self.m), state)
        self.assertEqual(self.conf(), 0.8)

    def test_correction_history_intact_and_never_current_confidence(self):
        self.l.teach("Python", "a snake", confidence=0.6)
        self.l.correct("Python", "a language", confidence=0.95)
        events = self.m.recent_learning_events()
        self.assertEqual([e["event_type"] for e in events], ["teach", "correct"])
        self.assertIn("a snake", events[1]["detail"])
        # events hold the description transition only - no confidence column
        self.assertNotIn("confidence", events[1].keys())
        self.assertNotIn("0.6", events[1]["detail"])
        self.assertEqual(self.conf(), 0.95)
        self.assertEqual(self.ctx().record["confidence"], 0.95)

    # --- missing confidence is not fabricated ----------------------------------------
    def test_missing_confidence_not_fabricated_on_relationships(self):
        self.l.teach("Python", "a language")
        self.l.relate("Python", "Language", "IS_A")           # none supplied
        rel = self.k.relationships_for("Python")["outgoing"][0]
        self.assertIsNone(rel["confidence"])
        self.assertIsNone(self.ctx().relationships["outgoing"][0]["confidence"])

    def test_new_knowledge_default_is_the_documented_policy_and_stable(self):
        # Existing KnowledgeSystem policy: a NEW entry with no confidence is
        # stored at 1.0. It is applied once, at creation, and never re-applied.
        self.l.teach("Python", "a language")
        self.assertEqual(self.conf(), 1.0)
        self.l.teach("Python", "a language", confidence=0.4)
        self.l.teach("Python", "a better language")
        self.assertEqual(self.conf(), 0.4)  # not reset to the default

    def test_provenance_none_stays_none_while_confidence_persists(self):
        self.l.teach("Python", "a language", confidence=0.5)
        rec = self.ctx().record
        self.assertEqual(rec["confidence"], 0.5)
        self.assertIsNone(rec["source_text"])
        self.assertIsNone(rec["learning_method"])

    # --- context / retrieval ----------------------------------------------------------
    def test_context_exposes_stored_confidence_exactly(self):
        self.l.teach("Python", "a language", confidence=0.73)
        self.l.relate("Python", "Language", "IS_A", confidence=0.42)
        s = self.ctx()
        self.assertEqual(s.record["confidence"], 0.73)
        self.assertEqual(s.relationships["outgoing"][0]["confidence"], 0.42)
        self.assertEqual(s.record, self.k.get("Python"))

    def test_repeated_retrieval_does_not_modify_anything(self):
        self.l.teach("Python", "a language", confidence=0.73)
        self.l.relate("Python", "Language", "IS_A", confidence=0.42)
        before, changes = _dump(self.m), self.m._conn.total_changes
        for _ in range(3):
            self.k.get("Python"); self.k.search("language"); self.k.all()
            self.k.relationships_for("Python"); self.ctx().to_context()
            evaluate_learned_knowledge_gate(self.ctx())
        self.assertEqual(self.m._conn.total_changes, changes)
        self.assertEqual(_dump(self.m), before)

    def test_knowledge_confidence_column_is_not_null_by_schema(self):
        # Schema fact (unchanged): a knowledge row can never hold "missing"
        # confidence, which is why a new entry without one is stored at the
        # documented 1.0 default. Relationship confidence is nullable.
        self.k.learn("Java", "a language")
        with self.assertRaises(Exception):
            self.m._run("UPDATE knowledge SET confidence = NULL WHERE name = 'Java'")
        self.assertEqual(self.k.get("Java")["confidence"], 1.0)

    def test_consumer_fallback_for_missing_confidence_is_preserved(self):
        # The gate's intentional fallback: a None confidence counts as 1.0 for
        # the decision only (AEL RELATE without confidence stays usable) and is
        # never written back.
        self.l.teach("Python", "a language")
        self.l.relate("Python", "Language", "IS_A")  # relationship confidence NULL
        s = self.ctx()
        self.assertIsNone(s.relationships["outgoing"][0]["confidence"])
        before = _dump(self.m)
        g = evaluate_learned_knowledge_gate(s)
        self.assertEqual(g.status, STATUS_PASSED)
        self.assertEqual(g.average_confidence, 1.0)
        self.assertIsNone(self.k.relationships_for("Python")["outgoing"][0]["confidence"])
        self.assertEqual(_dump(self.m), before)

    # --- relationships (Prompt 636 intact) -----------------------------------------------
    def test_relationship_confidence_idempotency_intact(self):
        self.l.teach("Python", "a language")
        self.l.relate("Python", "Language", "IS_A", confidence=0.8, source_text="t", learning_method="ael")
        state, changes = _dump(self.m), self.m._conn.total_changes
        self.l.relate("Python", "Language", "IS_A", confidence=0.8, source_text="t", learning_method="ael")
        self.l.relate("Python", "Language", "IS_A")  # omitted -> same effective values
        self.assertEqual(self.m._conn.total_changes, changes)
        self.assertEqual(_dump(self.m), state)
        # a genuinely different value updates in place, no duplicate row
        self.l.relate("Python", "Language", "IS_A", confidence=0.5)
        rels = self.k.relationships_for("Python")["outgoing"]
        self.assertEqual([(r["confidence"], r["source_text"]) for r in rels], [(0.5, "t")])
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 1)

    def test_correcting_description_does_not_touch_relationship_confidence(self):
        self.l.teach("Python", "a snake")
        self.l.relate("Python", "Reptile", "IS_A", confidence=0.8)
        rels = _dump(self.m)["relationships"]
        self.l.correct("Python", "a language", confidence=0.9)
        self.assertEqual(_dump(self.m)["relationships"], rels)

    # --- events / writes -----------------------------------------------------------------
    def test_no_duplicate_events_for_noops_and_one_per_real_change(self):
        n = lambda: len(self.m.recent_learning_events(1000))
        self.l.teach("Python", "a snake", confidence=0.6); self.assertEqual(n(), 1)
        self.l.teach("Python", "a snake", confidence=0.6); self.assertEqual(n(), 1)
        self.l.teach("Python", "a snake", confidence=0.7); self.assertEqual(n(), 2)
        self.l.correct("Python", "a language"); self.assertEqual(n(), 3)
        self.l.correct("Python", "a language"); self.assertEqual(n(), 3)
        self.l.relate("Python", "Language", "IS_A", confidence=0.5); self.assertEqual(n(), 4)
        self.l.relate("Python", "Language", "IS_A", confidence=0.5); self.assertEqual(n(), 4)

    # --- validation (existing architecture only) --------------------------------------------
    def test_storage_layer_has_no_confidence_validation_and_stores_as_given(self):
        for value in (0.0, 1.0, 0.25):
            self.k.learn(f"K{value}", "d", confidence=value)
            self.assertEqual(self.k.get(f"K{value}")["confidence"], value)
        self.k.learn("Wide", "d", confidence=1.5)  # existing behaviour: not rejected here
        self.assertEqual(self.k.get("Wide")["confidence"], 1.5)

    def test_gate_validation_matches_existing_rules(self):
        for value, expect in ((0.0, STATUS_REJECTED), (0.69, STATUS_REJECTED),
                              (0.7, STATUS_PASSED), (1.0, STATUS_PASSED)):
            with self.subTest(value=value):
                self.k.learn(f"C{value}", "d", confidence=value)
                s = select_learned_knowledge(f"c{value}", self.k, candidate_terms=[f"c{value}"])
                self.assertEqual(evaluate_learned_knowledge_gate(s).status, expect)
        for bad in (1.5, -0.1):
            with self.subTest(bad=bad):
                name = f"bad{str(bad).replace('.', '_').replace('-', 'm')}"
                self.k.learn(name, "d", confidence=bad)
                s = select_learned_knowledge(name, self.k, candidate_terms=[name])
                g = evaluate_learned_knowledge_gate(s)
                self.assertEqual((g.status, g.reason), (STATUS_REJECTED, REASON_NO_EVIDENCE))

    # --- persistence -----------------------------------------------------------------------
    def test_restart_persistence_retains_confidence(self):
        self.l.teach("Python", "a snake", confidence=0.6, source_text="s", learning_method="ael")
        self.l.correct("Python", "a language", confidence=0.95)
        self.l.relate("Python", "Language", "IS_A", confidence=0.42)
        self.l.relate("Python", "Other", "IS_A")
        self.m._conn.close()
        m2, k2, l2 = _stack(self.db)
        rec = k2.get("Python")
        self.assertEqual((rec["confidence"], rec["description"], rec["source_text"]),
                         (0.95, "a language", "s"))
        l2.correct("Python", "a programming language")  # omitted after restart
        self.assertEqual(k2.get("Python")["confidence"], 0.95)
        rels = {r["to_name"]: r["confidence"] for r in k2.relationships_for("Python")["outgoing"]}
        self.assertEqual(rels, {"Language": 0.42, "Other": None})


if __name__ == "__main__":
    unittest.main()
