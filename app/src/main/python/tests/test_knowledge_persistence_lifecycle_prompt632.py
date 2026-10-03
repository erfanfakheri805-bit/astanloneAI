"""Prompt 632 - Section 3: explicitly learned knowledge lifecycle:
learn -> validated record -> persistent storage -> retrieval from a
fresh MemorySystem/Core on the same db file. Rejected input is never
persisted; an identical repeat is not a second write."""
import os
import sqlite3
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


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "m.db")

    def test_learned_record_survives_fresh_instance(self):
        m, k, l = _stack(self.db)
        l.teach("Python", "a programming language", source="user",
                confidence=0.9, source_text="Python is a programming language.",
                learning_method="ael")
        l.relate("Python", "Language", "IS_A")
        m._conn.close()
        m2, k2, l2 = _stack(self.db)
        r = k2.get("Python")
        self.assertEqual(r["description"], "a programming language")
        self.assertEqual((r["source"], r["confidence"], r["learning_method"]), ("user", 0.9, "ael"))
        self.assertEqual(r["source_text"], "Python is a programming language.")
        self.assertEqual(l2.recall("Python")["relationships"]["outgoing"][0]["to_name"], "Language")
        self.assertTrue(any(e["target"] == "Python" for e in m2.recent_learning_events()))

    def test_fresh_core_retrieves_taught_knowledge(self):
        skills = os.path.join(self.tmp, "s")
        c1 = Core(memory_db_path=self.db, skill_definitions_dir=skills)
        c1.knowledge.learn("Rust", "A systems programming language.")
        c1.memory._conn.close()
        c2 = Core(memory_db_path=self.db, skill_definitions_dir=skills)
        self.assertEqual(c2.knowledge.get("Rust")["description"], "A systems programming language.")
        self.assertIn("systems programming language", c2.reason("What is Rust?").answer)

    def test_learned_knowledge_distinct_from_transient_state(self):
        m, k, l = _stack(self.db)
        l.teach("Python", "a language")
        m.log_message("user", "hello there")
        m.set_state("scratch", "1")
        self.assertEqual([r["name"] for r in k.all()], ["Python"])

    def test_blank_or_invalid_names_rejected_and_not_persisted(self):
        m, k, l = _stack(self.db)
        for bad in ("", "   ", "\t\n", None, 42):
            with self.assertRaises(ValueError):
                k.learn(bad, "x")
            with self.assertRaises(ValueError):
                l.teach(bad, "x")
        with self.assertRaises(ValueError):
            k.relate("", "Python", "IS_A")
        self.assertEqual(k.all(), [])
        self.assertEqual(m.recent_learning_events(), [])
        self.assertEqual(m.query("SELECT COUNT(*) AS n FROM relationships")[0]["n"], 0)

    def test_stub_none_description_still_allowed(self):
        _, k, _ = _stack(self.db)
        k.relate("A", "B", "USES")
        self.assertEqual(k.get("A")["status"], "stub")

    def test_identical_repeat_is_not_a_second_write(self):
        m, k, l = _stack(self.db)
        e1 = l.teach("Python", "a language")
        e2 = l.teach("Python", "a language")
        self.assertEqual((e1["version"], e2["version"]), (1, 1))
        self.assertEqual(e2["updated_at"], e1["updated_at"])
        self.assertEqual(len(m.recent_learning_events()), 1)
        self.assertEqual(len(k.all()), 1)

    def test_changed_repeat_still_updates_and_logs(self):
        m, k, l = _stack(self.db)
        l.teach("Python", "a language")
        e = l.teach("Python", "a general-purpose language")
        self.assertEqual(e["version"], 2)
        self.assertEqual(e["description"], "a general-purpose language")
        self.assertEqual(len(m.recent_learning_events()), 2)
        l.teach("Python", "a general-purpose language", confidence=0.5)
        self.assertEqual(k.get("Python")["version"], 3)

    def test_reteach_without_provenance_keeps_existing_provenance(self):
        _, k, l = _stack(self.db)
        l.teach("Python", "a language", source_text="orig", learning_method="ael", confidence=0.7)
        e = l.teach("Python", "a language", source_text=None, learning_method=None, confidence=None)
        self.assertEqual(e["version"], 1)
        self.assertEqual((e["source_text"], e["learning_method"], e["confidence"]), ("orig", "ael", 0.7))

    def test_ael_teach_valid_persists_and_repeat_is_idempotent(self):
        skills = os.path.join(self.tmp, "s")
        core = Core(memory_db_path=self.db, skill_definitions_dir=skills)
        for _ in range(2):
            results = core.ael.run("TEACH Zig IS a systems language")
            self.assertTrue(all(r.success for r in results))
        self.assertEqual(core.knowledge.get("Zig")["version"], 1)
        core.memory._conn.close()
        core2 = Core(memory_db_path=self.db, skill_definitions_dir=skills)
        self.assertEqual(core2.knowledge.get("Zig")["description"], "a systems language")

    def test_repeated_relation_still_single_edge_after_restart(self):
        m, k, l = _stack(self.db)
        self.assertTrue(l.relate("A", "B", "USES")["created"])
        self.assertFalse(l.relate("A", "B", "USES")["created"])
        m._conn.close()
        _, k2, _ = _stack(self.db)
        self.assertEqual(len(k2.relationships_for("A")["outgoing"]), 1)


if __name__ == "__main__":
    unittest.main()
