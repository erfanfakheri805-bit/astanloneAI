"""Prompt 637 - Section 3: deterministic, read-only retrieval of CURRENT
knowledge records (exact lookup, filtering, stable ordering)."""
import os
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem


def _stack(db):
    m = MemorySystem(db)
    k = KnowledgeSystem(m)
    return m, k, LearningSystem(ConceptSystem(k), k, memory=m)


def _dump(m):
    return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("knowledge", "relationships", "learning_events")}


class TestCurrentKnowledgeRetrieval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m, self.k, self.l = _stack(os.path.join(self.tmp, "m.db"))

    # --- current state -------------------------------------------------
    def test_learned_item_returns_current_value(self):
        self.l.teach("Python", "a snake")
        rec = self.k.get("Python")
        self.assertEqual(rec["description"], "a snake")
        self.assertEqual(self.k.find_by_name_case_insensitive("Python")["description"], "a snake")
        self.assertEqual([r["name"] for r in self.k.search("snake")], ["Python"])

    def test_retrieval_after_correction_returns_corrected_value(self):
        self.l.teach("Python", "a snake")
        self.l.correct("Python", "a programming language")
        self.assertEqual(self.k.get("Python")["description"], "a programming language")
        self.assertEqual(self.k.find_by_name_case_insensitive("python")["description"],
                         "a programming language")
        self.assertEqual(self.k.search("snake"), [])
        self.assertEqual([r["name"] for r in self.k.search("programming")], ["Python"])

    def test_history_events_are_not_current_knowledge_items(self):
        self.l.teach("Python", "a snake")
        self.l.correct("Python", "a programming language")
        events = self.m.query("SELECT * FROM learning_events WHERE target = 'Python'")
        self.assertGreaterEqual(len(events), 2)  # history exists...
        self.assertEqual([r["name"] for r in self.k.all()], ["Python"])  # ...but is not returned
        self.assertEqual(len(self.k.search("Python")), 1)
        self.assertEqual(len(self.k.search("correct")), 0)

    # --- exact / case-insensitive lookup --------------------------------
    def test_exact_name_lookup_is_deterministic(self):
        self.k.learn("python", "lowercase record")
        self.k.learn("Python", "capitalised record")
        for _ in range(5):
            self.assertEqual(self.k.get("Python")["description"], "capitalised record")
            self.assertEqual(self.k.get("python")["description"], "lowercase record")
            # exact-case match wins even when the case-insensitive lookup is asked
            self.assertEqual(self.k.find_by_name_case_insensitive("Python")["description"],
                             "capitalised record")
            self.assertEqual(self.k.find_by_name_case_insensitive("python")["description"],
                             "lowercase record")
        self.assertEqual(self.k.resolve_name("Python")["status"], "exact")

    def test_single_case_insensitive_match_is_resolved(self):
        self.k.learn("Python", "a language")
        self.assertEqual(self.k.find_by_name_case_insensitive("PYTHON")["name"], "Python")
        r = self.k.resolve_name("pYtHoN")
        self.assertEqual((r["status"], r["record"]["name"], r["candidates"]),
                         ("case_insensitive", "Python", []))
        self.assertIsNone(self.k.get("PYTHON"))  # get() stays exact-case

    def test_ambiguous_case_insensitive_lookup_selects_nothing(self):
        self.k.learn("python", "lowercase record")
        self.k.learn("Python", "capitalised record")
        self.assertIsNone(self.k.find_by_name_case_insensitive("PYTHON"))
        r = self.k.resolve_name("PYTHON")
        self.assertEqual((r["status"], r["record"], r["candidates"]),
                         ("ambiguous", None, ["Python", "python"]))
        with self.assertRaises(ValueError):
            self.k.correct("PYTHON", "something else")
        self.assertEqual(self.k.get("Python")["description"], "capitalised record")
        self.assertEqual(self.k.get("python")["description"], "lowercase record")

    def test_case_insensitive_correction_keeps_stored_status_and_is_idempotent(self):
        self.k.learn("Python", "a snake", status="active")
        self.l.correct("Python", "a language")
        v = self.k.get("Python")
        self.assertEqual(v["status"], "active")
        again = self.l.correct("PYTHON", "a language")
        self.assertEqual((again["version"], again["status"], again["updated_at"]),
                         (v["version"], "active", v["updated_at"]))

    def test_unknown_and_invalid_names_return_nothing(self):
        self.assertIsNone(self.k.find_by_name_case_insensitive("Nope"))
        self.assertEqual(self.k.resolve_name("Nope")["status"], "not_found")
        self.assertIsNone(self.k.find_by_name_case_insensitive(None))
        self.assertEqual(self.k.resolve_name("")["status"], "not_found")

    # --- determinism / ordering ------------------------------------------
    def test_repeated_identical_retrievals_are_identical(self):
        for n, d in (("Beta", "shared word"), ("Alpha", "shared word"), ("Gamma", "shared word")):
            self.l.teach(n, d)
        self.l.relate("Alpha", "Beta", "IS_A")
        first = (self.k.all(), self.k.search("shared"), self.k.relationships_for("Alpha"),
                 self.k.find_by_name_case_insensitive("alpha"))
        for _ in range(5):
            self.assertEqual(first, (self.k.all(), self.k.search("shared"),
                                     self.k.relationships_for("Alpha"),
                                     self.k.find_by_name_case_insensitive("alpha")))

    def test_multi_record_ordering_is_deterministic_and_not_timestamp_or_insert_based(self):
        for n in ("Gamma", "Beta", "Alpha"):  # deliberately not alphabetical
            self.l.teach(n, "shared word")
        self.assertEqual([r["name"] for r in self.k.search("shared")], ["Alpha", "Beta", "Gamma"])
        self.assertEqual([r["name"] for r in self.k.all()], ["Alpha", "Beta", "Gamma"])
        # Touching a record (newest updated_at) must not reorder ties.
        self.l.correct("Gamma", "shared word again")
        self.assertEqual([r["name"] for r in self.k.search("shared")], ["Alpha", "Beta", "Gamma"])

    def test_search_still_ranks_by_relevance_first(self):
        self.l.teach("Zebra", "indentation matters")
        self.l.teach("Alpha", "indentation and python")
        self.l.teach("Python", "a language")
        names = [r["name"] for r in self.k.search("python indentation")]
        self.assertEqual(names[0], "Alpha")  # 2-word overlap beats name-only ties
        self.assertEqual(set(names), {"Alpha", "Python", "Zebra"})

    def test_kind_filter_preserved_and_ordered(self):
        self.k.learn("Zed", "a thing", kind="concept")
        self.k.learn("Bob", "a person", kind="entity")
        self.k.learn("Amy", "a person", kind="entity")
        self.assertEqual([r["name"] for r in self.k.all(kind="entity")], ["Amy", "Bob"])
        self.assertEqual([r["name"] for r in self.k.all(kind="concept")], ["Zed"])
        self.assertEqual(self.k.all(kind="missing"), [])

    def test_relationship_ordering_is_deterministic(self):
        for n in ("Python", "Zeta", "Alpha", "Beta"):
            self.l.teach(n, f"{n} description")
        self.l.relate("Python", "Zeta", "IS_A")
        self.l.relate("Python", "Beta", "PART_OF")
        self.l.relate("Python", "Alpha", "IS_A")
        self.l.relate("Beta", "Zeta", "IS_A")
        out = self.k.relationships_for("Python")["outgoing"]
        self.assertEqual([(r["relation_type"], r["to_name"]) for r in out],
                         [("IS_A", "Alpha"), ("IS_A", "Zeta"), ("PART_OF", "Beta")])
        inc = self.k.relationships_for("Zeta")["incoming"]
        self.assertEqual([(r["relation_type"], r["from_name"]) for r in inc],
                         [("IS_A", "Beta"), ("IS_A", "Python")])

    def test_existing_relationship_knowledge_remains_retrievable(self):
        self.l.teach("Python", "a language")
        self.l.relate("Python", "Language", "IS_A", source_text="Python is a language")
        rels = self.k.relationships_for("Python")
        self.assertEqual([(r["to_name"], r["relation_type"]) for r in rels["outgoing"]],
                         [("Language", "IS_A")])
        self.assertEqual(self.k.relationships_for("Language")["incoming"][0]["from_name"], "Python")
        self.assertEqual(self.k.get("Language")["status"], "stub")
        self.assertIsNotNone(self.l.recall("Python"))

    # --- read-only guarantee ------------------------------------------------
    def test_retrieval_performs_no_writes_and_creates_no_events_or_stubs(self):
        self.l.teach("Python", "a snake")
        self.l.teach("python", "a language")
        self.l.correct("Python", "a reptile")
        self.l.relate("Python", "Animal", "IS_A")
        before = _dump(self.m)
        changes = self.m._conn.total_changes
        self.k.get("Python"); self.k.get("Missing")
        self.k.find_by_name_case_insensitive("PYTHON"); self.k.find_by_name_case_insensitive("Missing")
        self.k.resolve_name("PYTHON"); self.k.resolve_name("Missing")
        self.k.search("python reptile"); self.k.search("nothing-here")
        self.k.all(); self.k.all(kind="concept")
        self.k.relationships_for("Python"); self.k.relationships_for("Missing")
        self.l.recall("Python"); self.l.search("python")
        self.assertEqual(self.m._conn.total_changes, changes)  # no INSERT/UPDATE/DELETE at all
        after = _dump(self.m)
        self.assertEqual(before, after)  # incl. updated_at/version/metadata
        self.assertEqual(len(after["learning_events"]), len(before["learning_events"]))
        self.assertIsNone(self.k.get("Missing"))  # no stub created
        self.assertEqual(len(after["knowledge"]), len(before["knowledge"]))


if __name__ == "__main__":
    unittest.main()
