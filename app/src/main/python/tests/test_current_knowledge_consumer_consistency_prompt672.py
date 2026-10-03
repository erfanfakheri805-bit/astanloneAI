"""Prompt 672 - Section 3: current-knowledge consumer consistency (audit of every production consumer).

Audit result (see docs/section3_current_knowledge_consumer_consistency_prompt672.md): every consumer was
already at an appropriate boundary EXCEPT one genuine defect, fixed at its use boundary only:

  Core._find_best_known_concept (the conversational "Here's what I know about X" fallback, presented as
  CURRENT knowledge): when a term was AMBIGUOUS among current case-only duplicates (Prompt 637), the
  KnowledgeSystem.search() fallback then silently picked one of them anyway (ranking tie -> name order),
  although ReasoningEngine reported the same question as unknown. Ambiguous current case-variants are now
  skipped there (exact-case text still wins; inactive records never count).

Everything else is asserted unchanged: raw APIs, AEL ASK raw recall, explicit teach/correct/set_status,
Prompt 664 (inactive case-sibling keeps the context AMBIGUOUS), Prompt 665/666 (NL learning resolves onto an
inactive record without duplicating or reactivating it), Prompt 667-670 boundaries.
"""
import os
import tempfile
import unittest

from core.core import Core
from language_intelligence.learned_knowledge_context import select_learned_knowledge

TABLES = ("knowledge", "relationships", "learning_events")
NOT_KNOWN = "I don't have enough information to answer that yet."


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "c.db")
        self._open()

    def _open(self):
        self.core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m, self.r = self.core.knowledge, self.core.learning, self.core.memory, self.core.reasoning

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

    def best(self, text):
        found = self.core._find_best_known_concept(text)
        return found["name"] if found else None

    def sel(self, msg, terms):
        return select_learned_knowledge(msg, self.k, candidate_terms=list(terms))


class ActiveConsumedNormally(Base):
    def test_active_knowledge_reaches_every_consumer(self):
        self.ls.teach("Python", "a language", source="user")
        self.assertEqual(self.best("Tell me about python"), "Python")
        self.assertIn("a language", self.core.process_input("Tell me about python"))
        self.assertEqual(self.r.reason("What is Python?").answer, "a language")
        self.assertEqual(self.sel("Tell me about Python", ("python",)).status, "SELECTED")
        self.assertIn("a language", self.core.process_input("ASK Python"))


class InactiveAtEveryBoundary(Base):
    def setUp(self):
        super().setUp()
        self.ls.teach("Snake", "a reptile", source="user")
        self.ls.set_status("Snake", "inactive")

    def test_core_conversation_fallback(self):
        self.assertIsNone(self.best("Tell me about Snake"))
        self.assertNotIn("reptile", self.core.process_input("Tell me about Snake"))

    def test_core_search_fallback_by_description_word(self):
        self.ls.teach("Zed", "unrelated", source="user")
        self.assertIsNone(self.best("reptile facts"))

    def test_reasoning_lookup_and_reason(self):
        self.assertEqual(self.r.reason("What is Snake?").status, "unknown")
        self.assertEqual(self.r.reason("Snake").status, "unknown")
        self.assertEqual(self.k.resolve_current_name("Snake")["status"], "inactive")

    def test_learned_knowledge_context(self):
        self.assertEqual(self.sel("Tell me about Snake", ("snake",)).status, "NOT_FOUND")

    def test_raw_apis_keep_their_contract(self):
        self.assertEqual(self.k.get("Snake")["status"], "inactive")
        self.assertEqual([x["name"] for x in self.k.all()], ["Snake"])
        self.assertEqual([x["name"] for x in self.k.search("reptile")], ["Snake"])
        self.assertEqual(self.k.find_by_name_case_insensitive("snake")["name"], "Snake")
        self.assertEqual(self.k.resolve_name("snake")["status"], "case_insensitive")
        self.assertEqual(self.r.lookup("Snake")["status"], "inactive")   # raw lookup() unchanged
        self.assertEqual(self.core.concepts.get_with_relations("Snake")["status"], "inactive")
        self.assertEqual(self.ls.recall("Snake")["status"], "inactive")
        self.assertEqual([x["name"] for x in self.ls.search("reptile")], ["Snake"])

    def test_ael_ask_is_intentionally_raw_recall(self):
        self.assertIn("reptile", self.core.process_input("ASK Snake"))     # Prompt 669 contract


class CaseVariantsAndAmbiguity(Base):
    def test_ambiguous_current_variants_are_never_silently_chosen(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")
        self.assertIsNone(self.best("Tell me about python"))               # defect fixed (was 'PYTHON')
        self.assertEqual(self.r.reason("What is python?").status, "unknown")   # reasoning agrees
        self.assertEqual(self.k.resolve_current_name("python")["status"], "ambiguous")
        self.assertNotIn("upper", self.core.process_input("Tell me about python"))
        self.assertNotIn("lower", self.core.process_input("Tell me about python"))

    def test_ambiguous_multiword_variants_search_fallback(self):
        self.ls.teach("Machine Learning", "A", source="user")
        self.ls.teach("machine learning", "B", source="user")
        self.assertEqual(self.best("explain machine learning basics"), "machine learning")   # exact-case text wins
        self.assertEqual(self.best("explain Machine Learning basics"), "Machine Learning")
        self.assertIsNone(self.best("explain MACHINE LEARNING basics"))

    def test_exact_case_still_wins_over_variants(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("python", "lower", source="user")
        self.assertEqual(self.best("Tell me about python"), "python")

    def test_inactive_variant_neither_wins_nor_creates_ambiguity_in_core(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")
        self.ls.set_status("Python", "inactive")
        self.assertEqual(self.best("Tell me about python"), "PYTHON")
        self.assertEqual(self.k.resolve_current_name("python")["status"], "case_insensitive")

    def test_prompt664_inactive_sibling_keeps_context_conservatively_ambiguous(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.teach("python", "a snake", source="user")
        self.ls.set_status("python", "inactive")
        s = self.sel("about pYthon", ("python",))
        self.assertEqual((s.status, s.candidates), ("AMBIGUOUS", ["Python"]))
        self.ls.set_status("Python", "inactive")
        self.assertEqual(self.sel("about pYthon", ("python",)).status, "NOT_FOUND")

    def test_ambiguity_disappears_when_one_variant_retired_and_returns_on_reactivation(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")
        self.assertIsNone(self.best("Tell me about python"))
        self.ls.set_status("Python", "inactive")
        self.assertEqual(self.best("Tell me about python"), "PYTHON")
        self.ls.set_status("Python", "active")
        self.assertIsNone(self.best("Tell me about python"))


class InactiveRelationshipEndpoints(Base):
    def chain(self):
        for n in "ABC":
            self.ls.teach(n, f"desc {n}", source="user")
        self.ls.relate("A", "B", "DEPENDS_ON", source="user")
        self.ls.relate("B", "C", "DEPENDS_ON", source="user")

    def test_multi_hop_and_direct(self):
        self.chain()
        self.assertEqual(self.r.reason("Does A depend on C?").status, "answered")
        self.ls.set_status("B", "inactive")
        self.assertEqual(self.r.reason("Does A depend on C?").status, "unknown")
        self.assertEqual(self.r.reason("Does A depend on B?").status, "unknown")
        self.assertEqual(self.r.traverse("A", max_hops=3), [])
        self.ls.set_status("B", "active")
        self.assertEqual(self.r.reason("Does A depend on C?").status, "answered")

    def test_current_relationships_only_but_raw_rows_kept(self):
        self.chain()
        self.ls.set_status("B", "inactive")
        self.assertEqual(self.k.current_relationships_for("A")["outgoing"], [])
        self.assertEqual(len(self.k.relationships_for("A")["outgoing"]), 1)
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 2)

    def test_learned_context_relationship_rows_are_current_only(self):
        self.chain()
        self.ls.set_status("C", "inactive")
        s = self.sel("Tell me about B", ("b",))
        self.assertEqual(s.status, "SELECTED")
        self.assertEqual(s.relationships["outgoing"], [])
        self.assertEqual(self.k.relationships_for("B")["outgoing"][0]["to_name"], "C")

    def test_generated_answer_evidence_context_carries_no_inactive_row(self):
        for n, d in (("Python", "a language"), ("Code", "text"), ("Tool", "a tool")):
            self.ls.teach(n, d, source="user")
        self.k.relate("Python", "Code", "USED_FOR")
        self.k.relate("Python", "Tool", "USES")
        self.ls.set_status("Code", "inactive")

        class U:
            learned_knowledge_context = None
        u = U()
        self.core._attach_learned_knowledge(u, "Tell me about Python")   # the path feeding generation + the gate
        ctx = u.learned_knowledge_context
        self.assertIsNotNone(ctx)
        self.assertEqual([r["to_name"] for r in ctx["relationships"]["outgoing"]], ["Tool"])
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 2)   # stored rows untouched
        # a stub whose only evidence is an inactive endpoint is never selected/gated (Prompt 670 gate rule)
        self.k.relate("Snake", "Code", "USES")
        u2 = U()
        self.core._attach_learned_knowledge(u2, "Tell me about Snake")
        self.assertIsNone(u2.learned_knowledge_context)

    def test_ael_ask_shows_raw_rows_by_contract(self):
        self.chain()
        self.ls.set_status("B", "inactive")
        self.assertIn("A DEPENDS_ON B", " ".join(self.core.process_input("ASK A").split()))


class ExplicitOperationsKeepTheirSemantics(Base):
    def test_teach_and_correct_reactivate_and_set_status_is_explicit(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.ls.set_status("Snake", "inactive")
        self.ls.teach("Snake", "a reptile v2", source="user")
        self.assertEqual(self.k.get("Snake")["status"], "active")
        self.ls.set_status("Snake", "inactive")
        self.ls.correct("Snake", "a reptile v3", source="user")
        self.assertEqual(self.k.get("Snake")["status"], "active")
        self.ls.set_status("Snake", "inactive")
        self.assertEqual(self.k.get("Snake")["status"], "inactive")

    def test_implicit_correction_scan_does_not_choose_or_reactivate_inactive(self):
        self.ls.teach("Old", "the color is red", source="user")
        self.ls.set_status("Old", "inactive")
        before = self.snap()
        out = self.core._apply_resolved_correction_to_knowledge(
            {"original_expression": "red", "corrected_expression": "blue", "language": "english"})
        self.assertIsNone(out)
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.k.get("Old")["status"], "inactive")
        self.ls.set_status("Old", "active")
        out = self.core._apply_resolved_correction_to_knowledge(
            {"original_expression": "red", "corrected_expression": "blue", "language": "english"})
        self.assertIsNotNone(out)
        self.assertIn("blue", self.k.get("Old")["description"])

    def test_natural_language_learning_onto_inactive_record_is_prompt666_behavior(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.set_status("Python", "inactive")
        n = len(self.k.all())
        self.core.learn_from_text("python uses indentation")
        self.assertEqual(self.k.get("Python")["status"], "inactive")        # not reactivated
        self.assertIsNone(self.k.get("python"))                              # no duplicate
        self.assertEqual(len(self.k.all()), n + 1)                           # only the new object concept


class ReadOnlyConsumersAndPersistence(Base):
    def test_read_only_consumers_write_nothing_and_log_no_events(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.teach("Snake", "a reptile", source="user")
        self.ls.teach("Python2", "x", source="user")
        self.ls.relate("Python", "Snake", "USES", source="user")
        self.ls.set_status("Snake", "inactive")
        before = self.snap()
        self.best("Tell me about Snake")
        self.best("Tell me about python")
        self.r.reason("What does Python use?")
        self.r.reason("What is Snake?")
        self.r.check_consistency()
        self.sel("Tell me about Python", ("python",))
        self.k.resolve_current_name("snake")
        self.k.current_relationships_for("Python")
        self.ls.recall("Snake")
        self.ls.search("reptile")
        self.core.process_input("ASK Snake")
        self.assertEqual(self.snap(), before)

    def test_close_reopen_and_transitions(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.set_status("Python", "inactive")
        self.reopen()
        self.assertIsNone(self.best("Tell me about Python"))
        self.assertEqual(self.r.reason("What is Python?").status, "unknown")
        self.ls.set_status("Python", "active")
        self.reopen()
        self.assertEqual(self.best("Tell me about Python"), "Python")
        self.assertEqual(self.r.reason("What is Python?").status, "answered")
        self.ls.set_status("Python", "inactive")
        self.assertIsNone(self.best("Tell me about Python"))

    def test_stub_and_legacy_status_stay_current(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.relate("Python", "Ghost", "USES", source="user")          # Ghost becomes a stub
        self.assertEqual(self.k.get("Ghost")["status"], "stub")
        self.assertEqual(len(self.k.current_relationships_for("Python")["outgoing"]), 1)
        with self.m._lock, self.m._conn:
            self.m._conn.execute("UPDATE knowledge SET status = 'legacy-x' WHERE name = 'Ghost'")
        self.assertEqual(len(self.k.current_relationships_for("Python")["outgoing"]), 1)
        self.assertEqual(self.k.resolve_current_name("Ghost")["status"], "exact")
        with self.m._lock, self.m._conn:
            self.m._conn.execute("UPDATE knowledge SET description = 'legacy desc' WHERE name = 'Ghost'")
        self.assertEqual(self.best("Tell me about Ghost"), "Ghost")


if __name__ == "__main__":
    unittest.main()
