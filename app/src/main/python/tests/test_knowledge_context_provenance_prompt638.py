"""Prompt 638 - Section 3: the knowledge -> learned-knowledge-context path
uses CURRENT knowledge, preserves stored provenance, resolves names with the
Prompt 637 deterministic behaviour, and is read-only."""
import os
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from language_intelligence.learned_knowledge_context import (
    select_learned_knowledge, STATUS_SELECTED, STATUS_NOT_FOUND, STATUS_AMBIGUOUS)
from core.core import Core


def _dump(m):
    return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("knowledge", "relationships", "learning_events")}


class TestKnowledgeContextProvenance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = MemorySystem(os.path.join(self.tmp, "m.db"))
        self.k = KnowledgeSystem(self.m)
        self.l = LearningSystem(ConceptSystem(self.k), self.k, memory=self.m)

    def sel(self, message, terms=None):
        return select_learned_knowledge(message, self.k, candidate_terms=terms)

    # --- current state -------------------------------------------------
    def test_current_corrected_knowledge_is_used(self):
        self.l.teach("Python", "a snake")
        self.l.correct("Python", "a programming language")
        s = self.sel("What is Python?", ["what", "python"])
        self.assertEqual(s.status, STATUS_SELECTED)
        self.assertEqual(s.record["description"], "a programming language")

    def test_superseded_values_are_not_in_context(self):
        self.l.teach("Python", "a snake")
        self.l.correct("Python", "a programming language")
        ctx = self.sel("Tell me about Python", ["python"]).to_context()
        self.assertNotIn("snake", repr(ctx))
        self.assertEqual(self.sel("snake", ["snake"]).status, STATUS_NOT_FOUND)
        self.assertEqual(self.sel("What is a snake?", ["snake"]).status, STATUS_NOT_FOUND)
        # history still exists, but only as history
        self.assertTrue(any("snake" in (e["detail"] or "")
                            for e in self.m.query("SELECT * FROM learning_events")))

    def test_same_item_is_not_duplicated_across_lookup_paths(self):
        self.l.teach("Machine Learning", "learning from data")
        s = self.sel("machine learning and Machine Learning", ["machine", "learning"])
        self.assertEqual(s.status, STATUS_SELECTED)
        self.assertEqual(s.record["name"], "Machine Learning")

    # --- provenance -------------------------------------------------------
    def test_provenance_and_source_text_preserved(self):
        self.l.teach("Python", "a language", source="user", confidence=0.7,
                     source_text="Python is a language.", learning_method="ael")
        rec = self.sel("Tell me about Python", ["python"]).record
        self.assertEqual((rec["source"], rec["source_text"], rec["learning_method"], rec["confidence"]),
                         ("user", "Python is a language.", "ael", 0.7))
        stored = self.k.get("Python")
        self.assertEqual(rec, stored)  # exactly the stored row

    def test_correction_provenance_is_what_is_stored(self):
        self.l.teach("Python", "a snake", source="user", source_text="Python is a snake.",
                     learning_method="ael")
        self.l.correct("Python", "a language", source="user_correction",
                       source_text="No, Python is a language.", learning_method="explicit_correction")
        rec = self.sel("Python?", ["python"]).record
        self.assertEqual((rec["source"], rec["source_text"], rec["learning_method"]),
                         ("user_correction", "No, Python is a language.", "explicit_correction"))

    def test_missing_provenance_stays_missing(self):
        self.k.learn("Rust", "a systems language", source="user")  # no source_text / learning_method
        rec = self.sel("Tell me about Rust", ["rust"]).record
        self.assertIsNone(rec["source_text"])
        self.assertIsNone(rec["learning_method"])
        self.assertEqual(rec["source"], "user")

    def test_relationship_provenance_preserved(self):
        self.l.teach("Python", "a language")
        self.l.relate("Python", "Language", "IS_A", source_text="Python is a language",
                      learning_method="ael", confidence=0.9)
        rel = self.sel("Python", ["python"]).relationships["outgoing"][0]
        self.assertEqual((rel["source_text"], rel["learning_method"], rel["confidence"]),
                         ("Python is a language", "ael", 0.9))

    # --- ambiguity ----------------------------------------------------------
    def test_ambiguous_case_insensitive_name_is_not_silently_selected(self):
        self.k.learn("python", "lowercase record")
        self.k.learn("Python", "capitalised record")
        s = self.sel("Tell me about PYTHON", ["python"])
        self.assertEqual(s.status, STATUS_AMBIGUOUS)
        self.assertEqual(s.candidates, ["Python", "python"])
        self.assertIsNone(s.record)
        self.assertIsNone(s.to_context())

    def test_exact_case_in_message_resolves_between_case_variants(self):
        self.k.learn("python", "lowercase record")
        self.k.learn("Python", "capitalised record")
        s = self.sel("Tell me about Python", ["python"])
        self.assertEqual((s.status, s.record["description"]), (STATUS_SELECTED, "capitalised record"))
        s = self.sel("tell me about python", ["python"])
        self.assertEqual((s.status, s.record["description"]), (STATUS_SELECTED, "lowercase record"))

    def test_ambiguous_duplicates_without_content_are_ignored(self):
        self.k.learn("ghost", None, status="stub")
        self.k.learn("Ghost", None, status="stub")
        self.assertEqual(self.sel("GHOST", ["ghost"]).status, STATUS_NOT_FOUND)

    def test_single_case_insensitive_match_still_resolves(self):
        self.l.teach("Python", "a language")
        s = self.sel("what is PYTHON", ["python"])
        self.assertEqual((s.status, s.record["name"]), (STATUS_SELECTED, "Python"))

    # --- determinism ---------------------------------------------------------
    def test_multiple_items_ambiguity_ordering_is_deterministic(self):
        for n in ("Zebra", "Mango", "Apple"):
            self.l.teach(n, f"{n} fact")
        outs = [self.sel("Zebra Mango Apple", ["zebra", "mango", "apple"]) for _ in range(4)]
        for s in outs:
            self.assertEqual(s.status, STATUS_AMBIGUOUS)
            self.assertEqual(s.candidates, ["Apple", "Mango", "Zebra"])

    def test_relationship_ordering_in_context_is_fixed(self):
        for n in ("Python", "Zeta", "Alpha"):
            self.l.teach(n, f"{n} fact")
        self.l.relate("Python", "Zeta", "IS_A")
        self.l.relate("Python", "Alpha", "IS_A")
        out = self.sel("Python", ["python"]).relationships["outgoing"]
        self.assertEqual([r["to_name"] for r in out], ["Alpha", "Zeta"])

    def test_repeated_construction_is_stable(self):
        self.l.teach("Python", "a language", source_text="s", learning_method="ael")
        self.l.relate("Python", "Language", "IS_A")
        first = self.sel("What is Python?", ["what", "python"]).to_dict()
        for _ in range(5):
            self.assertEqual(first, self.sel("What is Python?", ["what", "python"]).to_dict())

    # --- read-only ------------------------------------------------------------
    def test_context_construction_performs_no_writes(self):
        self.k.learn("python", "lower")
        self.k.learn("Python", "upper")
        self.l.teach("Java", "a language")
        self.l.correct("Java", "a coffee-named language")
        self.l.relate("Java", "Language", "IS_A")
        before, changes = _dump(self.m), self.m._conn.total_changes
        for msg, terms in (("Python", ["python"]), ("PYTHON", ["python"]), ("Java", ["java"]),
                           ("Unknown thing", ["unknown", "thing"]), ("Language", ["language"]),
                           ("Ghostword", ["ghostword"])):
            self.sel(msg, terms).to_context()
        self.assertEqual(self.m._conn.total_changes, changes)
        self.assertEqual(_dump(self.m), before)
        self.assertIsNone(self.k.get("Ghostword"))  # no stub created

    def test_core_selection_performs_no_writes(self):
        core = Core(memory_db_path=os.path.join(self.tmp, "core.db"))
        core.learning.teach("Python", "a language", source_text="Python is a language.")
        before = _dump(core.memory)
        s = core.select_learned_knowledge("What is Python?")
        s2 = core.select_learned_knowledge("What is Python?")
        self.assertEqual(s.to_dict(), s2.to_dict())
        self.assertEqual(s.record["source_text"], "Python is a language.")
        self.assertEqual(_dump(core.memory), before)

    # --- unknown / empty ---------------------------------------------------------
    def test_unknown_and_empty_preserve_existing_behaviour(self):
        self.assertEqual(self.sel("Tell me about Nothing", ["nothing"]).status, STATUS_NOT_FOUND)
        self.assertIsNone(self.sel("Tell me about Nothing", ["nothing"]).to_context())
        self.assertEqual(self.sel("", []).status, STATUS_NOT_FOUND)
        self.assertEqual(self.sel(None).status, STATUS_NOT_FOUND)
        self.assertEqual(self.sel("Python").status, STATUS_NOT_FOUND)  # empty knowledge base

    def test_relationship_backed_knowledge_remains_available(self):
        self.k.learn("Language", None, status="stub")  # no description, but a relationship
        self.k.learn("Python", "a programming language")
        self.l.relate("Python", "Language", "IS_A")
        s = self.sel("Tell me about Language", ["language"])
        self.assertEqual(s.status, STATUS_SELECTED)
        self.assertIsNone(s.record["description"])
        self.assertEqual(s.relationships["incoming"][0]["from_name"], "Python")


if __name__ == "__main__":
    unittest.main()
