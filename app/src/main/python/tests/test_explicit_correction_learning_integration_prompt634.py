"""Prompt 634 - Section 3: the existing explicit-correction signal
("not X, I mean Y", detected/structured by Section 2) reaches
LearningSystem.correct() and corrects the ONE matching stored knowledge
record in place. No match / ambiguous / invalid input writes nothing;
ordinary statements are never treated as corrections."""
import os
import tempfile
import unittest

from core.core import Core
from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem


def _core(tmp, db="c.db"):
    return Core(memory_db_path=os.path.join(tmp, db), skill_definitions_dir=os.path.join(tmp, "s"))


def _corrections(core):
    return [e for e in core.memory.recent_learning_events() if e["event_type"] == "correct"]


class TestExplicitCorrectionIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.core = _core(self.tmp)
        self.core.learning.teach("Python", "a snake", confidence=0.6,
                                 source_text="Python is a snake.", learning_method="ael")
        self.core.learning.teach("Rust", "a systems language")

    def test_signal_reaches_correct_and_updates_in_place(self):
        rows = len(self.core.knowledge.all())
        reply = self.core.process_input("not a snake, I mean a programming language.")
        self.assertIn("[CORRECTION ACKNOWLEDGED]", reply)  # Section 2 reply unchanged
        rec = self.core.knowledge.get("Python")
        self.assertEqual(rec["description"], "a programming language")
        self.assertEqual(rec["version"], 2)
        self.assertEqual(len(self.core.knowledge.all()), rows)  # no competing record
        self.assertEqual(self.core.knowledge.search("snake"), [])

    def test_provenance_and_history(self):
        self.core.process_input("not a snake, I mean a programming language.")
        rec = self.core.knowledge.get("Python")
        self.assertEqual(rec["source"], "user_correction")
        self.assertEqual(rec["learning_method"], "explicit_correction")
        self.assertEqual(rec["source_text"], "not a snake, I mean a programming language.")
        self.assertEqual(rec["confidence"], 0.6)  # confidence semantics preserved
        ev = _corrections(self.core)
        self.assertEqual(len(ev), 1)
        self.assertIn("a snake", ev[0]["detail"])
        self.assertIn("a programming language", ev[0]["detail"])

    def test_identical_correction_is_noop(self):
        self.core.process_input("not a snake, I mean a programming language.")
        before = self.core.knowledge.get("Python")
        self.core.process_input("not a snake, I mean a programming language.")
        self.assertEqual(self.core.knowledge.get("Python"), before)  # 'a snake' no longer present
        self.assertEqual(len(_corrections(self.core)), 1)

    def test_unknown_target_creates_nothing(self):
        before = self.core.knowledge.all()
        events = len(self.core.memory.recent_learning_events())
        reply = self.core.process_input("not dgo, I mean dog.")
        self.assertIn("[CORRECTION ACKNOWLEDGED]", reply)
        self.assertEqual(self.core.knowledge.all(), before)
        self.assertEqual(_corrections(self.core), [])
        self.assertIsNone(self.core.knowledge.get("dog"))

    def test_ambiguous_target_writes_nothing(self):
        self.core.learning.teach("Cobra", "a snake")
        before = self.core.knowledge.all()
        self.core.process_input("not a snake, I mean a programming language.")
        self.assertEqual(self.core.knowledge.all(), before)
        self.assertEqual(_corrections(self.core), [])

    def test_invalid_or_unresolved_correction_writes_nothing(self):
        before = self.core.knowledge.all()
        c = self.core
        for cu in ({"original_expression": "a snake", "corrected_expression": None},
                   {"original_expression": "a snake", "corrected_expression": "   "},
                   {"original_expression": "", "corrected_expression": "x"},
                   {"original_expression": None, "corrected_expression": "x"},
                   {"original_expression": "a snake", "corrected_expression": 5}):
            self.assertIsNone(c._apply_resolved_correction_to_knowledge(cu))
        self.assertEqual(c.knowledge.all(), before)
        self.assertEqual(_corrections(c), [])

    def test_ordinary_statements_are_not_corrections(self):
        before = self.core.knowledge.get("Python")
        for text in ("Python is a snake", "not a snake", "I mean a programming language",
                     "Python is not a snake", "What is Python?"):
            self.core.process_input(text)
        self.assertEqual(self.core.knowledge.get("Python")["description"], "a snake")
        self.assertEqual(self.core.knowledge.get("Python")["version"], before["version"])
        self.assertEqual(_corrections(self.core), [])

    def test_normal_teaching_unchanged(self):
        self.core.learning.teach("Go", "a language")
        self.assertEqual(self.core.knowledge.get("Go")["source"], "ael")
        self.assertEqual(self.core.learning.teach("Go", "a language")["version"], 1)
        self.core.process_input("Dogs are animals.")
        self.assertEqual(_corrections(self.core), [])

    def test_unrelated_knowledge_untouched(self):
        rust = self.core.knowledge.get("Rust")
        self.core.process_input("not a snake, I mean a programming language.")
        self.assertEqual(self.core.knowledge.get("Rust"), rust)

    def test_corrected_knowledge_survives_fresh_core(self):
        self.core.process_input("not a snake, I mean a programming language.")
        self.core.memory._conn.close()
        c2 = _core(self.tmp)
        self.assertEqual(c2.knowledge.get("Python")["description"], "a programming language")
        self.assertEqual(len(_corrections(c2)), 1)
        self.assertIn("programming language", c2.reason("What is Python?").answer)

    def test_section2_correction_state_still_published(self):
        self.core.process_input("not dgo, I mean dog.")
        u = self.core.get_last_language_understanding()
        self.assertEqual(u.correction_understanding["status"], "RESOLVED")
        self.assertEqual(u.correction_understanding["original_expression"], "dgo")
        self.assertTrue(self.core.last_correction_learning_handoff_result.accepted)


if __name__ == "__main__":
    unittest.main()
