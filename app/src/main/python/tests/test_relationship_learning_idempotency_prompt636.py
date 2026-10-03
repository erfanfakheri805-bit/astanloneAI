"""Prompt 636 - Section 3: an EXACTLY identical repeated relationship
(same from/to/relation_type and same *effective* confidence/source/
source_text/learning_method - None still means "leave what's stored
alone") is now a true no-op, at both layers:

  - KnowledgeSystem.relate(): no UPDATE at all - updated_at and every
    other column stay untouched (previously a repeat, even an
    identical one, still refreshed updated_at).
  - LearningSystem.relate(): no second "relate" learning event
    (previously logged one on every call regardless of whether
    anything actually changed).

A repeat that supplies a genuinely different effective value for any
one of those fields still updates the row in place (existing
behaviour preserved) and still logs a learning event.
"""
import os
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from reasoning.reasoning_engine import ReasoningEngine


def _stack(db, with_reasoning=False):
    m = MemorySystem(db)
    k = KnowledgeSystem(m)
    reasoning = ReasoningEngine(k) if with_reasoning else None
    return m, k, LearningSystem(ConceptSystem(k), k, memory=m, reasoning_engine=reasoning)


def _relation_events(m):
    return [e for e in m.recent_learning_events() if e["event_type"] == "relate"]


def _row(m, from_name, to_name, relation_type):
    return m.query_one(
        "SELECT * FROM relationships WHERE from_name = ? AND to_name = ? AND relation_type = ?",
        (from_name, to_name, relation_type),
    )


class TestRelationshipIdempotency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "m.db")
        self.m, self.k, self.l = _stack(self.db)

    # ------------------------------------------------------------------
    # 1. First creation
    # ------------------------------------------------------------------
    def test_first_creation_works(self):
        outcome = self.l.relate("Python", "Language", "IS_A", confidence=0.8,
                                 source_text="Python is a language.", learning_method="ael")
        self.assertTrue(outcome["created"])
        row = _row(self.m, "Python", "Language", "IS_A")
        self.assertIsNotNone(row)
        self.assertEqual(row["confidence"], 0.8)
        self.assertEqual(len(_relation_events(self.m)), 1)

    # ------------------------------------------------------------------
    # 2-6. Exact repeat is a true no-op
    # ------------------------------------------------------------------
    def test_exact_repeat_creates_no_second_row(self):
        self.l.relate("Python", "Language", "IS_A", confidence=0.8,
                       source_text="txt", learning_method="ael")
        self.l.relate("Python", "Language", "IS_A", confidence=0.8,
                       source_text="txt", learning_method="ael")
        rows = self.m.query(
            "SELECT * FROM relationships WHERE from_name = ? AND to_name = ? AND relation_type = ?",
            ("Python", "Language", "IS_A"),
        )
        self.assertEqual(len(rows), 1)

    def test_exact_repeat_does_not_change_updated_at(self):
        self.l.relate("Python", "Language", "IS_A", confidence=0.8,
                       source_text="txt", learning_method="ael")
        before = _row(self.m, "Python", "Language", "IS_A")
        outcome = self.l.relate("Python", "Language", "IS_A", confidence=0.8,
                                 source_text="txt", learning_method="ael")
        after = _row(self.m, "Python", "Language", "IS_A")
        self.assertFalse(outcome["created"])
        self.assertEqual(after["updated_at"], before["updated_at"])
        self.assertEqual(dict(after), dict(before))

    def test_exact_repeat_does_not_change_confidence(self):
        self.l.relate("Python", "Language", "IS_A", confidence=0.8)
        self.l.relate("Python", "Language", "IS_A", confidence=0.8)
        self.assertEqual(_row(self.m, "Python", "Language", "IS_A")["confidence"], 0.8)

    def test_exact_repeat_does_not_change_provenance(self):
        self.l.relate("Python", "Language", "IS_A", source="ael", source_text="orig",
                       learning_method="ael")
        self.l.relate("Python", "Language", "IS_A", source="ael", source_text="orig",
                       learning_method="ael")
        row = _row(self.m, "Python", "Language", "IS_A")
        self.assertEqual((row["source_type"], row["source_text"], row["learning_method"]),
                          ("ael", "orig", "ael"))

    def test_exact_repeat_creates_no_additional_learning_event(self):
        self.l.relate("Python", "Language", "IS_A", confidence=0.8,
                       source_text="txt", learning_method="ael")
        self.assertEqual(len(_relation_events(self.m)), 1)
        self.l.relate("Python", "Language", "IS_A", confidence=0.8,
                       source_text="txt", learning_method="ael")
        self.assertEqual(len(_relation_events(self.m)), 1)

    # ------------------------------------------------------------------
    # 7. Omitted/None metadata preserves existing metadata, still a no-op
    # ------------------------------------------------------------------
    def test_omitted_metadata_preserves_existing_and_is_noop(self):
        self.l.relate("Python", "Language", "IS_A", confidence=0.8,
                       source_text="orig text", learning_method="ael")
        before = _row(self.m, "Python", "Language", "IS_A")
        n_events = len(_relation_events(self.m))
        # No confidence/source_text/learning_method supplied at all.
        outcome = self.l.relate("Python", "Language", "IS_A")
        after = _row(self.m, "Python", "Language", "IS_A")
        self.assertFalse(outcome["created"])
        self.assertEqual(dict(after), dict(before))
        self.assertEqual(len(_relation_events(self.m)), n_events)

    # ------------------------------------------------------------------
    # 8-11. A genuinely different effective value is a real update
    # ------------------------------------------------------------------
    def test_changing_confidence_causes_real_update(self):
        self.l.relate("Python", "Language", "IS_A", confidence=0.8)
        before = _row(self.m, "Python", "Language", "IS_A")
        n_events = len(_relation_events(self.m))
        self.l.relate("Python", "Language", "IS_A", confidence=0.95)
        after = _row(self.m, "Python", "Language", "IS_A")
        self.assertEqual(after["confidence"], 0.95)
        self.assertNotEqual(after["updated_at"], before["updated_at"])
        self.assertEqual(len(_relation_events(self.m)), n_events + 1)

    def test_changing_source_causes_real_update(self):
        self.l.relate("Python", "Language", "IS_A", source="ael")
        n_events = len(_relation_events(self.m))
        self.l.relate("Python", "Language", "IS_A", source="user")
        after = _row(self.m, "Python", "Language", "IS_A")
        self.assertEqual(after["source_type"], "user")
        self.assertEqual(len(_relation_events(self.m)), n_events + 1)

    def test_changing_source_text_causes_real_update(self):
        self.l.relate("Python", "Language", "IS_A", source_text="a")
        n_events = len(_relation_events(self.m))
        self.l.relate("Python", "Language", "IS_A", source_text="b")
        after = _row(self.m, "Python", "Language", "IS_A")
        self.assertEqual(after["source_text"], "b")
        self.assertEqual(len(_relation_events(self.m)), n_events + 1)

    def test_changing_learning_method_causes_real_update(self):
        self.l.relate("Python", "Language", "IS_A", learning_method="ael")
        n_events = len(_relation_events(self.m))
        self.l.relate("Python", "Language", "IS_A", learning_method="natural_language_understanding")
        after = _row(self.m, "Python", "Language", "IS_A")
        self.assertEqual(after["learning_method"], "natural_language_understanding")
        self.assertEqual(len(_relation_events(self.m)), n_events + 1)

    # ------------------------------------------------------------------
    # 12. Updated relationship still has exactly one logical edge
    # ------------------------------------------------------------------
    def test_updated_relationship_still_single_edge(self):
        self.l.relate("Python", "Language", "IS_A", confidence=0.8)
        self.l.relate("Python", "Language", "IS_A", confidence=0.95)
        self.l.relate("Python", "Language", "IS_A")  # no-op repeat
        rows = self.m.query(
            "SELECT * FROM relationships WHERE from_name = ? AND to_name = ? AND relation_type = ?",
            ("Python", "Language", "IS_A"),
        )
        self.assertEqual(len(rows), 1)

    # ------------------------------------------------------------------
    # 13. Stub concept creation still works
    # ------------------------------------------------------------------
    def test_stub_concept_creation_still_works(self):
        self.assertIsNone(self.k.get("Alpha"))
        self.l.relate("Alpha", "Beta", "USES")
        alpha = self.k.get("Alpha")
        beta = self.k.get("Beta")
        self.assertEqual(alpha["status"], "stub")
        self.assertEqual(beta["status"], "stub")
        self.assertIsNone(alpha["description"])

    # ------------------------------------------------------------------
    # 14. Contradiction detection unchanged
    # ------------------------------------------------------------------
    def test_contradiction_detection_unchanged(self):
        m, k, l = _stack(os.path.join(self.tmp, "r.db"), with_reasoning=True)
        l.relate("Fire", "Water", "OPPOSITE_OF")
        outcome = l.relate("Water", "Fire", "OPPOSITE_OF")
        # relationship is still stored either way - contradiction only
        # surfaces the conflict, never blocks/resolves it.
        self.assertIsNotNone(_row(m, "Water", "Fire", "OPPOSITE_OF"))

    def test_contradiction_flagged_and_not_auto_resolved(self):
        m, k, l = _stack(os.path.join(self.tmp, "r2.db"), with_reasoning=True)
        l.relate("A", "B", "IS_A")
        outcome = l.relate("B", "A", "IS_NOT_A")
        if outcome["contradiction"] is not None:
            # both relationships remain stored - no automatic resolution
            self.assertIsNotNone(_row(m, "A", "B", "IS_A"))
            self.assertIsNotNone(_row(m, "B", "A", "IS_NOT_A"))

    # ------------------------------------------------------------------
    # Direct KnowledgeSystem.relate() no-op behaviour (below the
    # learning-event layer)
    # ------------------------------------------------------------------
    def test_knowledge_relate_direct_noop_no_write(self):
        self.k.relate("X", "Y", "IS_A", confidence=0.5, source_type="ael")
        before = _row(self.m, "X", "Y", "IS_A")
        created = self.k.relate("X", "Y", "IS_A", confidence=0.5, source_type="ael")
        after = _row(self.m, "X", "Y", "IS_A")
        self.assertFalse(created)
        self.assertEqual(dict(before), dict(after))

    def test_knowledge_relate_returns_true_only_on_actual_insert(self):
        self.assertTrue(self.k.relate("M", "N", "IS_A"))
        self.assertFalse(self.k.relate("M", "N", "IS_A"))
        self.assertFalse(self.k.relate("M", "N", "IS_A", confidence=0.99))


if __name__ == "__main__":
    unittest.main()
