"""Prompt 664 - Section 3: inactive knowledge is not CURRENT usable knowledge for learned-knowledge selection.

select_learned_knowledge / Core.select_learned_knowledge / Core._attach_learned_knowledge (context) skip records
whose stored status is explicitly "inactive". Raw retrieval APIs (get/resolve_name/all/search/relationships_for/
recall) are unchanged. Selection/context are read-only. teach/correct still reactivate; NL learning untouched.
"""
import os
import tempfile
import unittest
from types import SimpleNamespace

from core.core import Core
from language_intelligence.learned_knowledge_context import select_learned_knowledge

TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items",
          "language_item_relationships")
MSG = "Tell me about Python"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "c.db")
        self._open()

    def _open(self):
        self.core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m = self.core.knowledge, self.core.learning, self.core.memory

    def reopen(self):
        self.m._conn.close()
        self._open()

    def tearDown(self):
        try:
            self.m._conn.close()
        except Exception:
            pass

    def snap(self):
        return {t: self.m.query(f"SELECT * FROM {t} ORDER BY id") for t in TABLES}

    def sel(self, msg=MSG, terms=("python",)):
        return select_learned_knowledge(msg, self.k, candidate_terms=list(terms))

    def ctx(self, msg=MSG):
        u = SimpleNamespace(learned_knowledge_context=None)
        self.core._attach_learned_knowledge(u, msg)
        return u.learned_knowledge_context

    def teach_py(self, conf=None):
        self.ls.teach("Python", "a programming language", source="user", confidence=conf)


class Candidates(Base):
    def test_active_selected(self):
        self.teach_py()
        self.assertTrue(self.sel().selected)
        self.assertEqual(self.core.select_learned_knowledge(MSG).status, "SELECTED")

    def test_inactive_excluded_everywhere(self):
        self.teach_py()
        self.ls.set_status("Python", "inactive")
        s = self.sel()
        self.assertEqual(s.status, "NOT_FOUND")
        self.assertIsNone(s.to_context())
        self.assertEqual(self.core.select_learned_knowledge(MSG).status, "NOT_FOUND")
        self.assertIsNone(self.ctx())

    def test_inactive_low_and_high_confidence(self):
        for conf in (0.1, 1.0):
            with self.subTest(conf=conf):
                self.setUp()
                self.teach_py(conf)
                self.ls.set_status("Python", "inactive")
                self.assertFalse(self.sel().selected)
                self.assertIsNone(self.ctx())
                self.ls.set_status("Python", "active")
                self.assertTrue(self.sel().selected)

    def test_active_and_inactive_for_same_query(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.teach("machine learning", "a field", source="user")
        self.ls.set_status("Python", "inactive")
        msg = "Python and machine learning"
        s = select_learned_knowledge(msg, self.k, candidate_terms=["python", "machine"])
        self.assertEqual(s.status, "SELECTED")
        self.assertEqual(s.record["name"], "machine learning")
        self.ls.set_status("Python", "active")
        self.assertEqual(select_learned_knowledge(msg, self.k, ["python", "machine"]).status, "AMBIGUOUS")

    def test_inactive_only_candidate_and_ambiguity_excludes_inactive(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.teach("Cobra", "a snake", source="user")
        self.ls.set_status("Python", "inactive")
        s = select_learned_knowledge("Python Cobra", self.k, ["python", "cobra"])
        self.assertEqual((s.status, s.record["name"]), ("SELECTED", "Cobra"))

    def test_case_duplicates_inactive_not_a_candidate(self):
        self.k.learn("Python", "a language", source="user")
        self.k.learn("python", "a snake", source="user")
        s = select_learned_knowledge("about pYthon", self.k, ["python"])
        self.assertEqual(s.status, "AMBIGUOUS")
        self.ls.set_status("python", "inactive")
        s = select_learned_knowledge("about pYthon", self.k, ["python"])
        self.assertEqual(s.candidates, ["Python"])           # inactive never listed as a candidate
        self.ls.set_status("Python", "inactive")
        self.assertEqual(select_learned_knowledge("about pYthon", self.k, ["python"]).status, "NOT_FOUND")

    def test_stubs(self):
        self.ls.relate("Python", "Snake", "is_a", source="user")   # both endpoints are stubs
        self.assertEqual(self.k.get("Snake")["status"], "stub")
        s = self.sel("Tell me about Snake", ("snake",))
        self.assertTrue(s.selected)                                # active-side behavior unchanged: stub with relationship
        with self.assertRaises(ValueError):
            self.ls.set_status("Snake", "inactive")                # stub cannot be made inactive via API
        self.k.learn("Ghost", "", source="user", status="inactive")   # inactive stub-like, no content
        self.assertEqual(select_learned_knowledge("Ghost", self.k, ["ghost"]).status, "NOT_FOUND")
        self.k.learn("Ghost2", "", source="user", status="inactive")
        self.ls.relate("Ghost2", "Snake", "is_a", source="user")
        self.assertFalse(select_learned_knowledge("Ghost2", self.k, ["ghost2"]).selected)

    def test_other_statuses_unchanged(self):
        self.k.learn("Legacy", "old fact", source="user", status="deprecated")
        self.assertTrue(select_learned_knowledge("Legacy", self.k, ["legacy"]).selected)


class NLAndMutations(Base):
    def setUp(self):
        super().setUp()
        self.teach_py()
        self.ls.set_status("Python", "inactive")

    def test_nl_same_concept_leaves_inactive_and_unselected(self):
        v = self.k.get("Python")
        self.core.learn_from_text("Python is a language.")
        self.assertEqual(self.k.get("Python")["version"], v["version"])
        self.assertEqual(self.k.get("Python")["status"], "inactive")
        self.assertFalse(self.sel().selected)

    def test_nl_related_concept(self):
        self.core.learn_from_text("Snake is an animal.")
        self.assertEqual(self.k.get("Python")["status"], "inactive")
        self.assertFalse(self.sel().selected)
        self.assertTrue(self.sel("Tell me about Snake", ("snake",)).selected)

    def test_teach_reactivates_and_selects(self):
        self.ls.teach("Python", "a programming language", source="user")
        self.assertEqual(self.k.get("Python")["status"], "active")
        self.assertTrue(self.sel().selected)
        self.assertIsNotNone(self.ctx() or self.sel().to_context())

    def test_correct_reactivates_and_selects(self):
        self.ls.correct("Python", "a scripting language")
        self.assertEqual(self.k.get("Python")["status"], "active")
        self.assertEqual(self.sel().record["description"], "a scripting language")


class Relationships(Base):
    def test_active_with_inactive_endpoint_keeps_stored_rows_but_context_is_current_only(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.teach("Code", "text", source="user")
        self.ls.relate("Python", "Code", "used_for", source="user")
        self.ls.set_status("Code", "inactive")
        before = self.snap()["relationships"]
        s = self.sel()
        self.assertTrue(s.selected)
        self.assertEqual(len(s.relationships["outgoing"]), 0)   # Prompt 670: context rows are current-only
        self.assertFalse(self.sel("Tell me about Code", ("code",)).selected)
        self.assertEqual(len(self.k.relationships_for("Code")["incoming"]), 1)   # rows kept, not disabled
        self.assertEqual(self.snap()["relationships"], before)

    def test_inactive_source_with_relationship_excluded_rows_preserved(self):
        self.ls.teach("Python", "", source="user")
        self.ls.relate("Python", "Code", "used_for", source="user")
        self.assertTrue(self.sel().selected)
        self.ls.set_status("Python", "inactive")
        self.assertFalse(self.sel().selected)
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)


class Lifecycle(Base):
    def test_transitions_no_stale_state(self):
        self.teach_py()
        seq = []
        for target in ("inactive", "active", "inactive", "active"):
            self.ls.set_status("Python", target)
            seq.append((self.sel().selected, self.ctx() is not None))
        self.assertEqual(seq, [(False, False), (True, True), (False, False), (True, True)])

    def test_repeated_calls_stable(self):
        self.teach_py()
        self.ls.set_status("Python", "inactive")
        for _ in range(3):
            self.assertFalse(self.sel().selected)


class ReloadAndReadOnly(Base):
    def test_reload_consistency_and_no_events(self):
        self.teach_py()
        self.ls.set_status("Python", "inactive")
        self.ls.teach("Cobra", "a snake", source="user")
        s0 = self.snap()
        self.reopen()
        self.assertEqual(self.snap(), s0)                      # no reload-generated rows
        self.assertFalse(self.sel().selected)
        self.assertIsNone(self.ctx())
        self.assertTrue(self.sel("Cobra", ("cobra",)).selected)
        self.assertEqual(self.snap(), s0)
        self.ls.set_status("Python", "active")
        self.reopen()
        self.assertTrue(self.sel().selected)
        self.assertIsNotNone(self.ctx())

    def test_read_only(self):
        self.teach_py()
        self.ls.relate("Python", "Code", "used_for", source="user")
        for state in ("active", "inactive"):
            self.ls.set_status("Python", state)
            s = self.snap()
            self.sel()
            self.core.select_learned_knowledge(MSG)
            self.ctx()
            self.assertEqual(self.snap(), s)

    def test_raw_retrieval_still_exposes_inactive(self):
        self.teach_py()
        self.ls.set_status("Python", "inactive")
        s = self.snap()
        self.assertEqual(self.k.get("Python")["status"], "inactive")
        self.assertEqual(self.k.resolve_name("Python")["status"], "exact")
        self.assertIn("Python", [r["name"] for r in self.k.all()])
        self.assertIn("Python", [r["name"] for r in self.k.search("programming language")])
        self.assertEqual(self.ls.recall("Python")["status"], "inactive")
        self.assertEqual(self.snap(), s)


if __name__ == "__main__":
    unittest.main()
