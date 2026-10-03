"""Prompt 639 - Section 3: correcting a knowledge item leaves the current
retrieval / learned-knowledge-context layers consistent.

Documented data-model facts these tests pin down (no schema change):
  * `relationships` reference knowledge items by NAME (from_name/to_name);
    a correction updates the knowledge row in place and never renames it, so
    every relationship stays attached to the corrected item untouched.
  * Relationship rows hold no text derived from the item's description
    (only their own provenance, e.g. the sentence that stated the
    relationship), so there is no dependent relationship content to update.
    That provenance is history of what was said, is left as stored, and no
    relationship is inferred from corrected text.
  * The superseded description exists only in `learning_events` (history).
"""
import os
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from language_intelligence.learned_knowledge_context import (
    select_learned_knowledge, STATUS_SELECTED, STATUS_AMBIGUOUS)
from core.core import Core


def _dump(m):
    return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("knowledge", "relationships", "learning_events")}


class TestCorrectionConsistency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = MemorySystem(os.path.join(self.tmp, "m.db"))
        self.k = KnowledgeSystem(self.m)
        self.l = LearningSystem(ConceptSystem(self.k), self.k, memory=self.m)
        self.l.teach("Python", "a snake", source="user", confidence=0.6,
                     source_text="Python is a snake.", learning_method="ael")
        self.l.teach("Rust", "a systems language")
        self.l.relate("Python", "Reptile", "IS_A", source_text="Python is a snake.",
                      learning_method="ael", confidence=0.8)
        self.l.relate("Rust", "Python", "COMPARED_TO")

    def ctx(self, message, terms):
        return select_learned_knowledge(message, self.k, candidate_terms=terms)

    def rels(self):
        return [dict(r) for r in self.m.query("SELECT * FROM relationships ORDER BY id")]

    # --- current retrieval / context -----------------------------------
    def test_corrected_description_is_current_everywhere(self):
        self.l.correct("Python", "a programming language")
        self.assertEqual(self.k.get("Python")["description"], "a programming language")
        self.assertEqual(self.k.find_by_name_case_insensitive("PYTHON")["description"],
                         "a programming language")
        self.assertEqual(self.l.recall("Python")["description"], "a programming language")
        s = self.ctx("What is Python?", ["python"])
        self.assertEqual((s.status, s.record["description"]), (STATUS_SELECTED, "a programming language"))
        self.assertEqual([r["name"] for r in self.k.search("programming")], ["Python"])

    def test_old_description_is_not_a_current_item_or_context(self):
        self.l.correct("Python", "a programming language")
        self.assertEqual(self.k.search("snake"), [])
        self.assertNotIn("a snake", [r["description"] for r in self.k.all()])
        ctx = self.ctx("Python", ["python"]).to_context()
        self.assertEqual(ctx["record"]["description"], "a programming language")
        # The old sentence survives ONLY as stored provenance (source_text of
        # the record / of the relationship it stated), which corrections keep
        # unless the caller supplies new provenance - it is never a
        # description / current-fact field. (Known limitation, see report.)
        self.assertEqual(ctx["record"]["source_text"], "Python is a snake.")
        descriptions = [v for k_, v in ctx["record"].items() if k_ == "description"]
        self.assertEqual(descriptions, ["a programming language"])
        self.assertEqual(sum(1 for r in self.k.all() if r["name"] == "Python"), 1)

    def test_history_remains_available_as_history(self):
        self.l.correct("Python", "a programming language", source="user_correction")
        ev = [e for e in self.m.recent_learning_events() if e["event_type"] == "correct"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["target"], "Python")
        self.assertIn("a snake", ev[0]["detail"])
        self.assertIn("a programming language", ev[0]["detail"])
        self.assertTrue(any(e["event_type"] == "teach" and "a snake" in (e["detail"] or "")
                            for e in self.m.recent_learning_events()))

    def test_core_level_reasoning_and_context_use_corrected_value(self):
        core = Core(memory_db_path=os.path.join(self.tmp, "core.db"))
        core.learning.teach("Python", "a snake", source_text="Python is a snake.")
        core.learning.correct("Python", "a programming language", source="user_correction",
                              source_text="No, Python is a language.",
                              learning_method="explicit_correction")
        s = core.select_learned_knowledge("What is Python?")
        self.assertEqual(s.record["description"], "a programming language")
        self.assertEqual(s.record["source_text"], "No, Python is a language.")
        self.assertNotIn("snake", repr(s.to_context()))

    # --- relationships --------------------------------------------------------
    def test_relationships_keep_stable_references_and_rows(self):
        before_rels, before_id = self.rels(), self.k.get("Python")["id"]
        self.l.correct("Python", "a programming language")
        self.assertEqual(self.rels(), before_rels)  # not deleted/recreated/rewritten
        self.assertEqual(self.k.get("Python")["id"], before_id)
        rel = self.k.relationships_for("Python")
        self.assertEqual([(r["relation_type"], r["to_name"]) for r in rel["outgoing"]],
                         [("IS_A", "Reptile")])
        self.assertEqual([(r["relation_type"], r["from_name"]) for r in rel["incoming"]],
                         [("COMPARED_TO", "Rust")])
        self.assertEqual(self.l.recall("Python")["relationships"], rel)

    def test_case_insensitive_correction_keeps_relationships(self):
        before_rels = self.rels()
        self.l.correct("python", "a programming language")
        self.assertEqual(self.rels(), before_rels)
        self.assertEqual(self.k.get("Python")["description"], "a programming language")
        self.assertIsNone(self.k.get("python"))

    def test_no_relationships_inferred_from_corrected_text(self):
        n = len(self.rels()); names = [r["name"] for r in self.k.all()]
        self.l.correct("Python", "a programming language created by Guido, similar to Rust")
        self.assertEqual(len(self.rels()), n)
        self.assertEqual([r["name"] for r in self.k.all()], names)  # no new stubs either

    def test_relationship_context_still_available_after_correction(self):
        self.l.correct("Python", "a programming language")
        rels = self.ctx("Python", ["python"]).relationships
        self.assertEqual(rels["outgoing"][0]["source_text"], "Python is a snake.")  # its own provenance, untouched
        self.assertEqual(rels["incoming"][0]["from_name"], "Rust")

    # --- provenance & versions -------------------------------------------------
    def test_omitted_provenance_unchanged(self):
        before = self.k.get("Python")
        e = self.l.correct("Python", "a programming language")
        self.assertEqual((e["source"], e["confidence"], e["source_text"], e["learning_method"]),
                         (before["source"], before["confidence"], before["source_text"],
                          before["learning_method"]))
        self.assertEqual((e["id"], e["created_at"], e["version"]),
                         (before["id"], before["created_at"], before["version"] + 1))

    def test_explicit_provenance_updates_follow_existing_semantics(self):
        e = self.l.correct("Python", "a programming language", source="user_correction",
                           confidence=0.95, source_text="No, it's a language.",
                           learning_method="explicit_correction")
        self.assertEqual((e["source"], e["confidence"], e["source_text"], e["learning_method"]),
                         ("user_correction", 0.95, "No, it's a language.", "explicit_correction"))
        ctx = self.ctx("Python", ["python"]).record
        self.assertEqual(ctx, self.k.get("Python"))

    def test_identical_correction_is_a_noop(self):
        self.l.correct("Python", "a programming language")
        state, events = _dump(self.m), len(self.m.recent_learning_events(100))
        changes = self.m._conn.total_changes
        e = self.l.correct("Python", "a programming language")
        self.l.correct("PYTHON", "a programming language")
        self.assertEqual(e, self.k.get("Python"))
        self.assertEqual(self.m._conn.total_changes, changes)
        self.assertEqual(_dump(self.m), state)
        self.assertEqual(len(self.m.recent_learning_events(100)), events)

    # --- determinism / ambiguity ---------------------------------------------------
    def test_ordering_and_ambiguity_stay_deterministic_after_correction(self):
        self.k.learn("python", "lowercase record")
        self.l.correct("Python", "a programming language")
        self.assertEqual([r["name"] for r in self.k.all()],
                         sorted(r["name"] for r in self.k.all()))
        s = self.ctx("Tell me about PYTHON", ["python"])
        self.assertEqual((s.status, s.candidates), (STATUS_AMBIGUOUS, ["Python", "python"]))
        with self.assertRaises(ValueError):
            self.l.correct("PYTHON", "x")
        self.assertEqual(self.k.get("python")["description"], "lowercase record")
        self.assertEqual(self.ctx("about Python", ["python"]).record["description"],
                         "a programming language")
        first = self.ctx("Python", ["python"]).to_dict()
        self.assertEqual(first, self.ctx("Python", ["python"]).to_dict())

    # --- writes / events ---------------------------------------------------------------
    def test_exactly_one_event_and_one_row_change_per_correction(self):
        events, rows = len(self.m.recent_learning_events(100)), len(self.k.all())
        rels = self.rels()
        self.l.correct("Python", "a programming language")
        self.assertEqual(len(self.m.recent_learning_events(100)), events + 1)
        self.assertEqual(len(self.k.all()), rows)
        self.assertEqual(self.rels(), rels)
        # reads after the correction write nothing
        before, changes = _dump(self.m), self.m._conn.total_changes
        self.k.get("Python"); self.k.search("programming"); self.k.all()
        self.ctx("Python", ["python"]).to_context(); self.l.recall("Python")
        self.assertEqual(self.m._conn.total_changes, changes)
        self.assertEqual(_dump(self.m), before)

    def test_unknown_or_rejected_correction_writes_nothing(self):
        before = _dump(self.m)
        self.assertIsNone(self.l.correct("Nothing", "x"))
        with self.assertRaises(ValueError):
            self.l.correct("Python", "   ")
        self.assertEqual(_dump(self.m), before)

    def test_correcting_relationship_created_stub_keeps_its_relationships(self):
        self.assertEqual(self.k.get("Reptile")["status"], "stub")
        rels = self.rels()
        e = self.l.correct("Reptile", "a cold-blooded animal")
        self.assertEqual(e["description"], "a cold-blooded animal")
        self.assertEqual(self.rels(), rels)
        self.assertEqual(self.ctx("Reptile", ["reptile"]).record["description"], "a cold-blooded animal")


if __name__ == "__main__":
    unittest.main()
