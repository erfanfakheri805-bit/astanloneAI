"""Prompt 633 - Section 3: explicit correction of an existing knowledge
record updates that logical record in place (no competing duplicate),
keeps provenance/version semantics, is idempotent, never creates or
persists rejected input, and survives a fresh instance."""
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


class TestCorrection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "m.db")
        self.m, self.k, self.l = _stack(self.db)
        self.l.teach("Python", "a snake", source="user", confidence=0.6,
                     source_text="Python is a snake.", learning_method="ael")
        self.l.teach("Rust", "a systems language")
        self.l.relate("Python", "Language", "IS_A")

    def test_correction_updates_same_record_and_retrieval(self):
        rows_before = len(self.k.all())
        e = self.l.correct("Python", "a programming language")
        self.assertEqual(e["description"], "a programming language")
        self.assertEqual(self.k.get("Python")["description"], "a programming language")
        self.assertNotEqual(self.k.get("Python")["description"], "a snake")
        self.assertEqual(self.k.search("snake"), [])
        self.assertEqual(len(self.k.all()), rows_before)  # no competing record

    def test_case_insensitive_name_resolves_to_existing_record(self):
        rows_before = len(self.k.all())
        e = self.l.correct("python", "a programming language")
        self.assertEqual(e["name"], "Python")
        self.assertIsNone(self.k.get("python"))
        self.assertEqual(len(self.k.all()), rows_before)

    def test_version_and_provenance_semantics(self):
        before = self.k.get("Python")
        e = self.l.correct("Python", "a programming language")
        self.assertEqual(e["version"], before["version"] + 1)
        self.assertEqual(e["created_at"], before["created_at"])
        self.assertEqual(e["id"], before["id"])
        # not supplied -> existing provenance/confidence preserved
        self.assertEqual((e["confidence"], e["source_text"], e["learning_method"]),
                         (0.6, "Python is a snake.", "ael"))
        # supplied -> replaced
        e2 = self.l.correct("Python", "a programming language, created by Guido",
                            confidence=0.95, source_text="Correction from user.",
                            learning_method="explicit_correction")
        self.assertEqual((e2["confidence"], e2["source_text"], e2["learning_method"]),
                         (0.95, "Correction from user.", "explicit_correction"))
        self.assertEqual(e2["version"], before["version"] + 2)

    def test_old_value_kept_in_learning_event_history(self):
        self.l.correct("Python", "a programming language")
        ev = [x for x in self.m.recent_learning_events() if x["event_type"] == "correct"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["target"], "Python")
        self.assertIn("a snake", ev[0]["detail"])
        self.assertIn("a programming language", ev[0]["detail"])

    def test_identical_repeat_is_idempotent(self):
        self.l.correct("Python", "a programming language")
        v = self.k.get("Python")
        n_events = len(self.m.recent_learning_events())
        e = self.l.correct("Python", "a programming language")
        self.assertEqual(e["version"], v["version"])
        self.assertEqual(e["updated_at"], v["updated_at"])
        self.assertEqual(len(self.m.recent_learning_events()), n_events)
        # an identical repeat that only differs in name case is also a no-op
        self.assertEqual(self.l.correct("PYTHON", "a programming language")["version"], v["version"])

    def test_unrelated_knowledge_and_state_unchanged(self):
        self.m.log_message("user", "hi")
        self.m.set_state("k", "v")
        rust, msgs = self.k.get("Rust"), self.m.recent_messages()
        rels = self.m.query("SELECT * FROM relationships ORDER BY id")
        state = self.m.get_state("k")
        self.l.correct("Python", "a programming language")
        self.assertEqual(self.k.get("Rust"), rust)
        self.assertEqual(self.m.recent_messages(), msgs)
        self.assertEqual(self.m.query("SELECT * FROM relationships ORDER BY id"), rels)
        self.assertEqual(self.m.get_state("k"), state)
        self.assertEqual(self.k.get("Language")["status"], "stub")

    def test_corrected_record_survives_fresh_memory_and_core(self):
        self.l.correct("python", "a programming language")
        self.m._conn.close()
        _, k2, _ = _stack(self.db)
        self.assertEqual(k2.get("Python")["description"], "a programming language")
        skills = os.path.join(self.tmp, "s")
        c = Core(memory_db_path=self.db, skill_definitions_dir=skills)
        c.learning.correct("Rust", "a memory-safe systems language")
        c.memory._conn.close()
        c2 = Core(memory_db_path=self.db, skill_definitions_dir=skills)
        self.assertEqual(c2.knowledge.get("Rust")["description"], "a memory-safe systems language")
        self.assertIn("memory-safe", c2.reason("What is Rust?").answer)

    def test_rejected_input_creates_nothing(self):
        before = self.k.all()
        events = len(self.m.recent_learning_events())
        for name, desc in (("", "x"), ("  ", "x"), (None, "x"), (5, "x"),
                           ("Python", ""), ("Python", "   "), ("Python", None)):
            with self.assertRaises(ValueError):
                self.l.correct(name, desc)
        self.assertEqual(self.k.all(), before)
        self.assertEqual(len(self.m.recent_learning_events()), events)

    def test_unknown_name_is_not_created(self):
        before = self.k.all()
        self.assertIsNone(self.l.correct("Zorblax", "something"))
        self.assertIsNone(self.k.correct("Zorblax", "something"))
        self.assertEqual(self.k.all(), before)

    def test_ambiguous_case_variants_rejected_but_exact_wins(self):
        self.k.learn("python", "a snake (lowercase record)")
        with self.assertRaises(ValueError):
            self.k.correct("PYTHON", "x")
        e = self.k.correct("python", "a lowercase-record correction")
        self.assertEqual(e["name"], "python")
        self.assertEqual(self.k.get("Python")["description"], "a snake")

    def test_learn_and_teach_behavior_unchanged(self):
        # learn() keeps exact, case-sensitive identity (documented)
        self.k.learn("python", "distinct record")
        self.assertEqual(self.k.get("Python")["description"], "a snake")
        self.assertEqual(self.l.teach("Python", "changed")["version"], 2)


if __name__ == "__main__":
    unittest.main()
