"""Prompt 667 - Section 3: inactive knowledge must not surface as CURRENT conversational knowledge.

Defect found and fixed at the read/use boundary (raw retrieval APIs unchanged):
- Core._find_best_known_concept (conversational fallback "Here's what I know about ...") used
  find_by_name_case_insensitive()/search(), which return inactive rows.
- ReasoningEngine._reason used find_by_name_case_insensitive(), so an inactive description / IS_A /
  relationship could answer "What is X?" / "Tell me about X".
Fix: KnowledgeSystem.resolve_current_name()/find_current_by_name_case_insensitive() (new, read-only)
and an inactive filter on the search fallback. Only status == "inactive" is excluded; active, stub and
legacy statuses behave as before.
"""
import os
import tempfile
import unittest
from unittest import mock

from core.core import Core

TABLES = ("knowledge", "relationships", "learning_events")
NOT_KNOWN = "I don't have enough information to answer that yet."


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

    def teach(self, name, desc="a programming language"):
        self.ls.teach(name, desc, source="user")

    def off(self, name):
        self.ls.set_status(name, "inactive")

    def on(self, name):
        self.ls.set_status(name, "active")

    def ask(self, text):
        return self.core.process_input(text)


class ActiveOnly(Base):
    def test_active_available_everywhere(self):
        self.teach("Python")
        self.assertIn("a programming language", self.ask("Tell me about Python"))
        self.assertEqual(self.core._find_best_known_concept("Tell me about Python")["name"], "Python")
        r = self.core.reason("What is Python?")
        self.assertEqual((r.status, r.answer), ("answered", "a programming language"))
        self.assertEqual(self.k.resolve_current_name("python")["status"], "case_insensitive")
        self.assertEqual(self.k.resolve_current_name("Python")["status"], "exact")

    def test_search_fallback_finds_active_by_description(self):
        self.teach("Python", "a language with indentation")
        best = self.core._find_best_known_concept("what has indentation")
        self.assertEqual(best["name"], "Python")


class InactiveOnly(Base):
    def setUp(self):
        super().setUp()
        self.teach("Python", "a programming language")
        self.off("Python")

    def test_conversational_fallback_does_not_claim_inactive_knowledge(self):
        for q in ("Tell me about Python", "What is Python?", "python"):
            out = self.ask(q)
            self.assertNotIn("a programming language", out)
            self.assertNotIn("Here's what I know", out)
            self.assertIn(NOT_KNOWN, out)

    def test_find_best_known_concept_returns_none(self):
        self.assertIsNone(self.core._find_best_known_concept("Tell me about Python"))
        self.assertIsNone(self.core._find_best_known_concept("python"))

    def test_search_route_by_description_text_is_excluded(self):
        self.assertIsNone(self.core._find_best_known_concept("a programming language"))

    def test_reasoning_unknown_no_description_no_relationship_answer(self):
        self.ls.relate("Python", "Language", "IS_A") if hasattr(self.ls, "relate") else self.k.relate(
            "Python", "Language", "IS_A")
        for q in ("What is Python?", "Tell me about Python", "python"):
            r = self.core.reason(q, use_context=False) if q != "Tell me about Python" else \
                self.core.reasoning.reason(q, request_forms=True)
            self.assertEqual(r.status, "unknown", q)
            self.assertIsNone(r.answer)
            self.assertEqual(r.supporting_facts, [])
            self.assertEqual(r.supporting_relationships, [])
            self.assertEqual(r.contradictions, [])
            self.assertEqual(r.unknowns, [f"'{q if q == 'python' else 'Python'}' is not in the knowledge base yet."])

    def test_relation_query_on_inactive_subject_is_unknown(self):
        self.k.relate("Python", "Indentation", "USES")
        r = self.core.reason("What does Python use?")
        self.assertEqual(r.status, "unknown")
        self.assertIsNone(r.answer)

    def test_resolve_current_name_distinguishes_inactive_from_not_found(self):
        self.assertEqual(self.k.resolve_current_name("Python")["status"], "inactive")
        self.assertEqual(self.k.resolve_current_name("python")["status"], "inactive")
        self.assertEqual(self.k.resolve_current_name("Nope")["status"], "not_found")
        self.assertIsNone(self.k.resolve_current_name("Python")["record"])
        self.assertIsNone(self.k.find_current_by_name_case_insensitive("Python"))

    def test_non_string_names_are_not_found(self):
        for bad in (None, 5, b"x", ["Python"]):
            self.assertEqual(self.k.resolve_current_name(bad),
                             {"status": "not_found", "record": None, "candidates": []})


class ActiveAndInactiveTogether(Base):
    def test_active_wins_over_inactive_different_names_via_search(self):
        self.teach("Cobra", "a snake with a hood")
        self.teach("Viper", "a snake with fangs")
        self.off("Cobra")
        best = self.core._find_best_known_concept("snake")
        self.assertEqual(best["name"], "Viper")

    def test_inactive_exact_case_does_not_shadow_active_case_variant(self):
        self.teach("Python", "a programming language")
        self.teach("python", "a snake")
        self.off("python")
        best = self.core._find_best_known_concept("Tell me about python")
        self.assertEqual(best["name"], "Python")
        self.assertEqual(self.k.resolve_current_name("python")["status"], "case_insensitive")
        self.assertIn("a programming language", self.ask("Tell me about python"))
        self.assertNotIn("a snake", self.ask("Tell me about python"))

    def test_inactive_case_variant_does_not_create_ambiguity(self):
        self.teach("Python", "a programming language")
        self.teach("PYTHON", "shouting")
        self.off("PYTHON")
        res = self.k.resolve_current_name("pYtHoN")
        self.assertEqual((res["status"], res["record"]["name"]), ("case_insensitive", "Python"))

    def test_reasoning_uses_active_record_when_inactive_variant_exists(self):
        self.teach("Python", "a programming language")
        self.teach("python", "a snake")
        self.off("python")
        r = self.core.reason("What is python?")
        self.assertEqual((r.status, r.answer), ("answered", "a programming language"))


class ActiveAmbiguityUnchanged(Base):
    def test_two_active_case_variants_stay_ambiguous(self):
        self.teach("Python", "a programming language")
        self.teach("python", "a snake")
        res = self.k.resolve_current_name("PYTHON")
        self.assertEqual(res["status"], "ambiguous")
        self.assertIsNone(res["record"])
        self.assertEqual(res["candidates"], ["Python", "python"])
        self.assertIsNone(self.k.find_current_by_name_case_insensitive("PYTHON"))
        # same outcome as the raw path for the active-only ambiguity
        self.assertEqual(self.k.resolve_name("PYTHON")["status"], "ambiguous")

    def test_inactive_third_does_not_change_active_ambiguity(self):
        self.teach("Python", "a programming language")
        self.teach("python", "a snake")
        self.teach("PYTHON", "shouting")
        self.off("PYTHON")
        res = self.k.resolve_current_name("pYThOn")
        self.assertEqual((res["status"], res["candidates"]), ("ambiguous", ["Python", "python"]))

    def test_exact_active_still_wins_over_case_variants(self):
        self.teach("Python", "a programming language")
        self.teach("python", "a snake")
        self.assertEqual(self.k.resolve_current_name("python")["record"]["description"], "a snake")

    def test_reasoning_ambiguity_behaves_as_before(self):
        self.teach("Python", "a programming language")
        self.teach("python", "a snake")
        r = self.core.reason("What is PYTHON?")
        self.assertEqual(r.status, "unknown")           # nothing silently chosen (unchanged)
        self.assertIsNone(r.answer)


class StubAndLegacyStatuses(Base):
    def test_stub_remains_current(self):
        self.k.relate("Python", "Language", "IS_A")
        self.assertEqual(self.k.get("Language")["status"], "stub")
        self.assertEqual(self.k.resolve_current_name("language")["record"]["status"], "stub")
        self.assertEqual(self.core._find_best_known_concept("Tell me about Language")["name"], "Language")

    def test_stub_with_relationships_answers_as_before(self):
        self.k.relate("Python", "Language", "IS_A")
        out = self.ask("Tell me about Language")
        self.assertIn("Language", out)
        self.assertNotIn(NOT_KNOWN, out)

    def test_legacy_status_remains_current(self):
        self.k.learn("Fortran", "an old language", status="deprecated")
        self.assertEqual(self.k.resolve_current_name("fortran")["record"]["status"], "deprecated")
        self.assertIn("an old language", self.ask("Tell me about Fortran"))
        self.assertEqual(self.core.reason("What is Fortran?").answer, "an old language")


class Lifecycle(Base):
    def test_active_to_inactive_to_active(self):
        self.teach("Python")
        self.assertIn("a programming language", self.ask("Tell me about Python"))
        self.off("Python")
        self.assertNotIn("a programming language", self.ask("Tell me about Python"))
        self.assertEqual(self.core.reason("What is Python?").status, "unknown")
        self.on("Python")
        self.assertIn("a programming language", self.ask("Tell me about Python"))
        self.assertEqual(self.core.reason("What is Python?").answer, "a programming language")

    def test_teach_reactivates_and_is_current_again(self):
        self.teach("Python", "a snake")
        self.off("Python")
        self.teach("Python", "a programming language")
        self.assertEqual(self.k.get("Python")["status"], "active")
        self.assertIn("a programming language", self.ask("Tell me about Python"))

    def test_correct_reactivates_and_is_current_again(self):
        self.teach("Python", "a snake")
        self.off("Python")
        self.ls.correct("Python", "a programming language")
        self.assertIn("a programming language", self.ask("Tell me about Python"))

    def test_nl_learning_leaves_inactive_inactive_and_invisible(self):
        self.teach("Python", "a programming language")
        self.off("Python")
        self.core.learn_from_text("Python is a language.")
        self.assertEqual(self.k.get("Python")["status"], "inactive")
        self.assertNotIn("a programming language", self.ask("Tell me about Python"))
        self.assertEqual(self.core.reason("What is Python?").status, "unknown")

    def test_reload_keeps_inactive_invisible_and_active_visible(self):
        self.teach("Python", "a programming language")
        self.teach("Ruby", "another language")
        self.off("Python")
        self.reopen()
        self.assertIsNone(self.core._find_best_known_concept("Tell me about Python"))
        self.assertNotIn("a programming language", self.ask("Tell me about Python"))
        self.assertEqual(self.core.reason("What is Python?").status, "unknown")
        self.assertIn("another language", self.ask("Tell me about Ruby"))
        self.on("Python")
        self.reopen()
        self.assertIn("a programming language", self.ask("Tell me about Python"))


class RelationshipsWithInactiveEndpoints(Base):
    def test_active_subject_with_inactive_object_no_longer_answers(self):
        # Prompt 668 supersedes the Prompt 667 limitation: a relationship whose endpoint is inactive
        # does not provide current inference (rows stay stored; reactivation restores the answer).
        self.teach("Python", "a programming language")
        self.teach("Indentation", "leading whitespace")
        self.k.relate("Python", "Indentation", "USES")
        self.off("Indentation")
        r = self.core.reason("What does Python use?")
        self.assertEqual(r.status, "unknown")
        self.assertEqual(self.k.get("Indentation")["status"], "inactive")   # untouched
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)  # row still stored
        self.on("Indentation")
        r = self.core.reason("What does Python use?")
        self.assertEqual(r.status, "answered")
        self.assertIn("Indentation", r.answer)


class RawApisUnchanged(Base):
    def test_raw_retrieval_still_exposes_inactive(self):
        self.teach("Python", "a programming language")
        self.k.relate("Python", "Language", "IS_A")
        self.off("Python")
        self.assertEqual(self.k.get("Python")["status"], "inactive")
        self.assertEqual(self.k.find_by_name_case_insensitive("python")["name"], "Python")
        self.assertEqual(self.k.resolve_name("python")["status"], "case_insensitive")
        self.assertEqual([r["name"] for r in self.k.search("programming")], ["Python"])
        self.assertIn("Python", [r["name"] for r in self.k.all()])
        self.assertEqual(self.k.relationships_for("Python")["outgoing"][0]["to_name"], "Language")
        self.assertEqual(self.core.reasoning.lookup("Python")["status"], "inactive")

    def test_resolve_name_shape_unchanged(self):
        self.teach("Python")
        self.assertEqual(set(self.k.resolve_name("Python")), {"status", "record", "candidates"})
        self.assertEqual(set(self.k.resolve_current_name("Python")), {"status", "record", "candidates"})


class ReadOnly(Base):
    def test_reads_write_nothing_and_add_no_events(self):
        self.teach("Python", "a programming language")
        self.teach("Ruby", "another language")
        self.k.relate("Ruby", "Language", "IS_A")
        self.off("Python")
        before = self.snap()
        for q in ("Tell me about Python", "What is Python?", "python", "Tell me about Ruby",
                  "What is Ruby?", "What does Python use?"):
            self.core._find_best_known_concept(q)
            self.core.reason(q)
        self.k.resolve_current_name("Python")
        self.k.find_current_by_name_case_insensitive("ruby")
        self.assertEqual(self.snap(), before)

    def test_conversational_reads_create_no_learning_events(self):
        self.teach("Python", "a programming language")
        self.off("Python")
        n = len(self.m.query("SELECT * FROM learning_events"))
        rows = self.snap()["knowledge"]
        self.ask("Tell me about Python")
        self.ask("What is Python?")
        self.assertEqual(len(self.m.query("SELECT * FROM learning_events")), n)
        self.assertEqual(self.snap()["knowledge"], rows)


class FailurePaths(Base):
    def test_reasoning_failure_in_current_lookup_never_raises(self):
        self.teach("Python")
        with mock.patch.object(self.k, "resolve_current_name", side_effect=RuntimeError("boom")):
            r = self.core.reason("What is Python?")
        self.assertEqual(r.status, "unknown")
        self.assertTrue(any("boom" in w for w in r.warnings))
        self.assertIsNone(r.answer)

    def test_search_failure_propagates_unchanged_from_find_best(self):
        with mock.patch.object(self.k, "search", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.core._find_best_known_concept("zzzz qqqq")

    def test_search_input_boundaries_unchanged(self):
        with self.assertRaises(TypeError):
            self.k.search(5)
        self.assertEqual(self.k.search("", limit=None), [])


if __name__ == "__main__":
    unittest.main()
