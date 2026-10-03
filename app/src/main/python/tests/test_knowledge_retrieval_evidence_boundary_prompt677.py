"""Prompt 677 - Section 3: knowledge retrieval vs CURRENT answer-evidence boundary integrity.

Audit (docs/section3_knowledge_retrieval_evidence_boundary_prompt677.md): every production retrieval layer was
traced to its final consumer. Raw layers (get/all/search/resolve_name/find_by_name_case_insensitive/
relationships_for/recall/AEL ASK/MeaningResolver.resolve) intentionally keep returning inactive rows; current
layers (resolve_current_name/find_current_by_name_case_insensitive/current_relationships_for, Core fallback,
ReasoningEngine, learned-knowledge selection/context, MeaningResolver.resolve_current) do not.

Genuine cross-boundary defect found and fixed (1):
  ReasoningEngine.check_consistency() with no name enumerated RAW knowledge.all() and only then applied its
  max_entities budget. Explicitly inactive records (Prompt 663) filled the budget, so a real contradiction among
  ACTIVE records was left unchecked while the result still said "consistent", and inactive names were reported
  as "checked". Fix: inactive records are excluded from the enumeration BEFORE the cap (an explicit `name`
  argument is unchanged; all() is unchanged).

Everything else is asserted unchanged. Tests use real Core production paths only.
"""
import os
import tempfile
import unittest

from core.core import Core
from language_intelligence.learned_knowledge_context import select_learned_knowledge

TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items",
          "language_item_relationships")
NOT_KNOWN = "I don't have enough information to answer that yet."
EN = "en"


def item(key):
    return {"language": EN, "item_type": "word", "key": key}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "c.db")
        self._open()

    def _open(self):
        self.core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m, self.r = (self.core.knowledge, self.core.learning,
                                            self.core.memory, self.core.reasoning)

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

    def teach(self, *names):
        for n in names:
            self.ls.teach(n, f"{n} description", source="user")

    def off(self, n):
        self.ls.set_status(n, "inactive")

    def on(self, n):
        self.ls.set_status(n, "active")

    def best(self, text):
        found = self.core._find_best_known_concept(text)
        return found["name"] if found else None

    def sel(self, msg, terms):
        return select_learned_knowledge(msg, self.k, candidate_terms=list(terms))

    def ctx(self, msg):
        class U:
            learned_knowledge_context = None
        u = U()
        self.core._attach_learned_knowledge(u, msg)
        return u.learned_knowledge_context

    def chain(self):
        self.teach("A", "B", "C")
        self.k.relate("A", "B", "DEPENDS_ON")
        self.k.relate("B", "C", "DEPENDS_ON")

    def link(self, word, concept):
        self.core.learn_language_item(EN, "word", word, meaning=None)
        self.core.relate_language_items(item(word), {"concept": concept}, "means")

    @staticmethod
    def names(rows, key):
        return [r[key] for r in rows]


# ----------------------------------------------------------------------------------------------------------
class RawVersusCurrentContracts(Base):
    def setUp(self):
        super().setUp()
        self.teach("Old", "Live")
        self.k.relate("Live", "Old", "USES")
        self.k.relate("Old", "Live", "USES")
        self.off("Old")

    def test_raw_apis_still_return_inactive_rows(self):
        self.assertEqual(self.k.get("Old")["status"], "inactive")
        self.assertIn("Old", self.names(self.k.all(), "name"))
        self.assertIn("Old", self.names(self.k.search("Old description"), "name"))
        self.assertEqual(self.k.resolve_name("Old")["status"], "exact")
        self.assertEqual(self.k.find_by_name_case_insensitive("old")["name"], "Old")
        raw = self.k.relationships_for("Live")
        self.assertEqual(self.names(raw["outgoing"], "to_name"), ["Old"])
        self.assertEqual(self.names(raw["incoming"], "from_name"), ["Old"])
        self.assertEqual(self.k.relationships_for("Old")["outgoing"][0]["to_name"], "Live")

    def test_current_apis_never_return_inactive_rows(self):
        cur = self.k.resolve_current_name("Old")
        self.assertEqual((cur["status"], cur["record"], cur["candidates"]), ("inactive", None, []))
        self.assertEqual(self.k.resolve_current_name("old")["status"], "inactive")
        self.assertIsNone(self.k.find_current_by_name_case_insensitive("Old"))
        self.assertEqual(self.k.current_relationships_for("Live"), {"outgoing": [], "incoming": []})
        self.assertEqual(self.k.current_relationships_for("Old"), {"outgoing": [], "incoming": []})

    def test_raw_and_current_agree_for_active_records(self):
        self.assertEqual(self.k.resolve_name("Live")["record"], self.k.resolve_current_name("Live")["record"])
        self.assertEqual(self.k.resolve_current_name("live")["status"], "case_insensitive")
        self.assertEqual(self.k.find_current_by_name_case_insensitive("live"), self.k.get("Live"))

    def test_recall_is_raw_and_does_not_feed_current_answers(self):
        recalled = self.ls.recall("Live")
        self.assertEqual(self.names(recalled["relationships"]["outgoing"], "to_name"), ["Old"])   # raw
        self.assertEqual(self.ls.recall("Old")["status"], "inactive")
        # ...while every current consumer of the same records ignores the inactive endpoint
        self.assertIsNone(self.r.summarize_relationships("Live"))
        self.assertEqual(self.r.reason("What does Live use?").status, "unknown")
        self.assertEqual(self.r.reason("What is Old?").status, "unknown")

    def test_lookup_is_raw_by_contract(self):
        self.assertEqual(self.r.lookup("Old")["status"], "inactive")
        self.assertEqual(self.r.lookup("Old"), self.k.get("Old"))

    def test_ael_ask_is_raw_recall(self):
        out = self.core.process_input("ASK Live")
        self.assertIn("Live USES Old", out)
        self.assertIn("Old description", self.core.process_input("ASK Old"))


class StubAndLegacyStatus(Base):
    def test_stub_and_legacy_status_are_current(self):
        self.teach("Real")
        self.k.relate("Real", "Ghost", "USES")                          # Ghost is a stub
        self.k.learn("Legacy", "legacy description", status="deprecated")
        self.k.relate("Real", "Legacy", "USES")
        self.assertEqual(self.k.get("Ghost")["status"], "stub")
        self.assertEqual(self.k.resolve_current_name("Ghost")["status"], "exact")
        self.assertEqual(self.k.resolve_current_name("Legacy")["status"], "exact")
        rows = self.k.current_relationships_for("Real")["outgoing"]
        self.assertEqual(sorted(self.names(rows, "to_name")), ["Ghost", "Legacy"])
        self.assertEqual(self.best("Tell me about Legacy"), "Legacy")
        self.assertEqual(self.r.reason("What is Legacy?").answer, "legacy description")
        self.assertEqual(self.sel("about Legacy", ("legacy",)).status, "SELECTED")

    def test_stub_with_no_content_is_not_learned_evidence(self):
        self.k.relate("Real", "Ghost", "USES")
        self.assertEqual(self.sel("Tell me about Ghost", ("ghost",)).status, "SELECTED")   # has a relationship
        self.assertEqual(self.k.get("Ghost")["description"], None)


# ----------------------------------------------------------------------------------------------------------
class CoreConversationalFallback(Base):
    def test_inactive_concept_is_not_current_answer_evidence(self):
        self.teach("Zed")
        self.assertIn("Zed description", self.core.process_input("Tell me about Zed"))
        self.off("Zed")
        reply = self.core.process_input("Tell me about Zed")
        self.assertTrue(reply.startswith(NOT_KNOWN))
        self.assertNotIn("Zed description", reply)
        self.assertIsNone(self.best("Tell me about Zed"))

    def test_search_fallback_by_description_word_is_current_only(self):
        self.ls.teach("Zed", "a rare gizmo", source="user")
        self.assertEqual(self.best("what is a gizmo"), "Zed")
        self.off("Zed")
        self.assertIsNone(self.best("what is a gizmo"))
        self.assertIn("Zed", self.names(self.k.search("gizmo"), "name"))         # raw search unchanged

    def test_reactivation_restores_current_answer_immediately(self):
        self.teach("Zed")
        self.off("Zed")
        self.assertIsNone(self.best("Tell me about Zed"))
        self.on("Zed")
        self.assertEqual(self.best("Tell me about Zed"), "Zed")
        self.assertIn("Zed description", self.core.process_input("Tell me about Zed"))

    def test_teach_and_correct_reactivate_explicitly(self):
        self.teach("Zed")
        self.off("Zed")
        self.ls.teach("Zed", "zed again", source="user")
        self.assertEqual(self.k.get("Zed")["status"], "active")
        self.assertIn("zed again", self.core.process_input("Tell me about Zed"))
        self.off("Zed")
        self.ls.correct("Zed", "zed corrected", source="user")
        self.assertEqual(self.k.get("Zed")["status"], "active")
        self.assertIn("zed corrected", self.core.process_input("Tell me about Zed"))

    def test_related_inactive_endpoint_does_not_reach_the_reply(self):
        self.teach("Zed", "Yak")
        self.k.relate("Zed", "Yak", "USES")
        self.off("Zed")
        self.on("Zed")
        self.off("Yak")
        self.assertIsNone(self.r.summarize_relationships("Zed"))
        self.assertNotIn("Yak", self.core.process_input("Tell me about Zed"))


class ReasoningEvidence(Base):
    def test_inactive_subject_is_unknown_and_contributes_no_fact(self):
        self.teach("Zed")
        self.assertEqual(self.r.reason("What is Zed?").answer, "Zed description")
        self.off("Zed")
        res = self.r.reason("What is Zed?")
        self.assertEqual((res.status, res.answer, res.supporting_facts), ("unknown", None, []))
        self.on("Zed")
        self.assertEqual(self.r.reason("What is Zed?").answer, "Zed description")

    def test_endpoint_matrix_direct_relation(self):
        for src_on in (True, False):
            for dst_on in (True, False):
                with self.subTest(source_active=src_on, target_active=dst_on):
                    self.tearDown()
                    self.setUp()                                  # fresh database per combination
                    self.teach("S", "T")
                    self.k.relate("S", "T", "USES")
                    if not src_on:
                        self.off("S")
                    if not dst_on:
                        self.off("T")
                    res = self.r.reason("What does S use?")
                    if src_on and dst_on:
                        self.assertEqual((res.status, res.answer), ("answered", "S uses T."))
                    else:
                        self.assertEqual((res.status, res.answer), ("unknown", None))
                    # the stored row and the raw read are unaffected by the lifecycle
                    self.assertEqual(len(self.k.relationships_for("S")["outgoing"]), 1)
                    cur = self.k.current_relationships_for("S")
                    self.assertEqual(len(cur["outgoing"]), 1 if (src_on and dst_on) else 0)
                    cur_t = self.k.current_relationships_for("T")
                    self.assertEqual(len(cur_t["incoming"]), 1 if (src_on and dst_on) else 0)

    def test_multi_hop_through_inactive_middle_endpoint(self):
        self.chain()
        self.assertEqual(self.r.reason("Does A depend on C?").answer, "A depends on C (inferred).")
        self.off("B")
        self.assertEqual(self.r.reason("Does A depend on C?").status, "unknown")
        self.assertEqual(self.r.traverse("A"), [])
        self.assertIsNone(self.r.find_path("A", "C"))
        self.assertEqual(len(self.k.relationships_for("A")["outgoing"]), 1)          # raw row still stored
        self.on("B")
        self.assertEqual(self.r.reason("Does A depend on C?").answer, "A depends on C (inferred).")
        self.assertEqual(len(self.r.find_path("A", "C")), 2)

    def test_active_alternative_path_still_used(self):
        self.chain()
        self.teach("D")
        self.k.relate("A", "D", "DEPENDS_ON")
        self.k.relate("D", "C", "DEPENDS_ON")
        self.off("B")
        path = self.r.find_path("A", "C")
        self.assertEqual([h["to"] for h in path], ["D", "C"])

    def test_ambiguous_current_name_is_never_silently_selected(self):
        self.k.learn("Python", "upper")
        self.k.learn("PYTHON", "lower")
        res = self.r.reason("What is python?")
        self.assertEqual((res.status, res.answer, res.supporting_facts), ("unknown", None, []))
        self.assertEqual(self.k.resolve_current_name("python")["candidates"], ["PYTHON", "Python"])

    def test_contradiction_only_from_current_rows(self):
        self.teach("Q", "X")
        self.k.relate("Q", "X", "IS_A")
        self.k.relate("Q", "X", "IS_NOT_A")
        self.assertEqual(len(self.r.contradictions_for("Q")), 1)
        self.off("X")
        self.assertEqual(self.r.contradictions_for("Q"), [])
        self.assertTrue(self.r.check_consistency("Q")["consistent"])
        self.on("X")
        self.assertEqual(len(self.r.contradictions_for("Q")), 1)


class CheckConsistencyEnumerationDefect(Base):
    """The Prompt 677 defect: raw all() (which includes inactive rows) fed the max_entities budget."""

    def contradictory_pair(self):
        self.teach("Q", "X")
        self.k.relate("Q", "X", "IS_A")
        self.k.relate("Q", "X", "IS_NOT_A")

    def test_inactive_records_do_not_crowd_out_active_ones(self):
        for i in range(6):
            n = f"A{i}"
            self.teach(n)
            self.off(n)
        self.contradictory_pair()
        res = self.r.check_consistency(max_entities=3)
        self.assertEqual(res["checked"], ["Q", "X"])
        self.assertFalse(res["consistent"])
        self.assertEqual(len(res["contradictions"]), 1)

    def test_default_budget_of_200_inactive_records(self):
        for i in range(200):
            n = f"A{i:03d}"
            self.teach(n)
            self.off(n)
        self.contradictory_pair()
        res = self.r.check_consistency()
        self.assertIn("Q", res["checked"])
        self.assertFalse(res["consistent"])

    def test_checked_lists_only_current_records(self):
        self.teach("A", "B", "C")
        self.off("B")
        self.assertEqual(self.r.check_consistency()["checked"], ["A", "C"])
        self.on("B")
        self.assertEqual(self.r.check_consistency()["checked"], ["A", "B", "C"])

    def test_budget_still_bounds_current_records(self):
        self.teach("A", "B", "C", "D")
        self.assertEqual(self.r.check_consistency(max_entities=2)["checked"], ["A", "B"])
        self.off("A")
        self.assertEqual(self.r.check_consistency(max_entities=2)["checked"], ["B", "C"])

    def test_explicit_name_is_checked_as_asked(self):
        self.contradictory_pair()
        self.off("Q")
        res = self.r.check_consistency("Q")
        self.assertEqual((res["checked"], res["consistent"]), (["Q"], True))    # no current rows for an inactive Q

    def test_stub_and_legacy_status_are_enumerated(self):
        self.teach("Real")
        self.k.relate("Real", "Ghost", "USES")
        self.k.learn("Legacy", "d", status="deprecated")
        self.assertEqual(self.r.check_consistency()["checked"], ["Ghost", "Legacy", "Real"])

    def test_all_is_unchanged_and_check_is_read_only(self):
        self.teach("A", "B")
        self.off("B")
        before = self.snap()
        self.r.check_consistency()
        self.assertEqual(self.names(self.k.all(), "name"), ["A", "B"])
        self.assertEqual(self.snap(), before)


# ----------------------------------------------------------------------------------------------------------
class LearnedKnowledgeEvidence(Base):
    def test_inactive_entry_is_not_selected_and_not_attached(self):
        self.teach("Python")
        self.assertEqual(self.sel("Tell me about Python", ("python",)).status, "SELECTED")
        self.off("Python")
        self.assertEqual(self.sel("Tell me about Python", ("python",)).status, "NOT_FOUND")
        self.assertIsNone(self.ctx("Tell me about Python"))

    def test_context_relationship_rows_are_current_only(self):
        self.teach("Python", "Code", "Tool")
        self.k.relate("Python", "Code", "USED_FOR")
        self.k.relate("Python", "Tool", "USES")
        self.off("Code")
        ctx = self.ctx("Tell me about Python")
        self.assertEqual(self.names(ctx["relationships"]["outgoing"], "to_name"), ["Tool"])
        self.assertNotIn("Code", str(ctx["relationships"]))
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 2)
        self.on("Code")
        self.assertEqual(len(self.ctx("Tell me about Python")["relationships"]["outgoing"]), 2)

    def test_stub_whose_only_evidence_is_inactive_is_not_evidence(self):
        self.teach("Code")
        self.k.relate("Snake", "Code", "USES")
        self.assertIsNotNone(self.ctx("Tell me about Snake"))
        self.off("Code")
        self.assertIsNone(self.ctx("Tell me about Snake"))

    def test_ambiguous_active_variants_are_ambiguous_not_selected(self):
        self.k.learn("Python", "upper")
        self.k.learn("PYTHON", "lower")
        s = self.sel("about python", ("python",))
        self.assertEqual((s.status, s.candidates, s.record), ("AMBIGUOUS", ["PYTHON", "Python"], None))
        self.assertIsNone(self.ctx("about python"))

    def test_exact_case_and_unique_case_insensitive_selection(self):
        self.k.learn("Python", "upper")
        self.assertEqual(self.sel("about Python", ("python",)).record["name"], "Python")
        self.assertEqual(self.sel("about pYthon", ("python",)).record["name"], "Python")

    def test_prompt664_inactive_case_sibling_stays_conservative(self):
        self.k.learn("Python", "a language")
        self.k.learn("python", "a snake")
        self.off("python")
        s = self.sel("about pYthon", ("python",))
        self.assertEqual((s.status, s.candidates), ("AMBIGUOUS", ["Python"]))
        self.assertEqual(self.sel("about Python", ("python",)).record["name"], "Python")   # exact case wins
        self.off("Python")
        self.assertEqual(self.sel("about pYthon", ("python",)).status, "NOT_FOUND")


class CaseVariantMatrix(Base):
    def test_one_active_variant(self):
        self.k.learn("Snake", "reptile")
        self.assertEqual(self.k.resolve_current_name("Snake")["status"], "exact")
        self.assertEqual(self.k.resolve_current_name("snake")["record"]["name"], "Snake")
        self.assertEqual(self.best("Tell me about snake"), "Snake")

    def test_multiple_active_variants(self):
        self.k.learn("Snake", "one")
        self.k.learn("SNAKE", "two")
        self.assertEqual(self.k.resolve_current_name("Snake")["status"], "exact")           # exact case wins
        self.assertEqual(self.k.resolve_current_name("snake")["status"], "ambiguous")
        self.assertIsNone(self.k.resolve_current_name("snake")["record"])
        self.assertIsNone(self.k.find_current_by_name_case_insensitive("snake"))
        self.assertIsNone(self.best("Tell me about snake"))
        reply = self.core.process_input("Tell me about snake")
        self.assertTrue(reply.startswith(NOT_KNOWN))
        # raw resolution reports the same ambiguity (nothing is silently chosen there either)
        self.assertEqual(self.k.resolve_name("snake")["status"], "ambiguous")

    def test_active_plus_inactive_variant(self):
        self.k.learn("Snake", "one")
        self.k.learn("SNAKE", "two")
        self.off("SNAKE")
        cur = self.k.resolve_current_name("snake")
        self.assertEqual((cur["status"], cur["record"]["name"]), ("case_insensitive", "Snake"))
        self.assertEqual(self.k.resolve_name("snake")["status"], "ambiguous")               # raw stays ambiguous
        self.assertEqual(self.best("Tell me about snake"), "Snake")
        self.assertEqual(self.r.reason("What is snake?").answer, "one")
        self.on("SNAKE")
        self.assertIsNone(self.best("Tell me about snake"))

    def test_exact_case_request_for_inactive_variant_does_not_win(self):
        self.k.learn("Snake", "one")
        self.k.learn("snake", "two")
        self.off("snake")
        cur = self.k.resolve_current_name("snake")
        self.assertEqual((cur["status"], cur["record"]["name"]), ("case_insensitive", "Snake"))
        self.assertEqual(self.k.resolve_name("snake")["record"]["name"], "snake")           # raw exact wins

    def test_all_variants_inactive(self):
        self.k.learn("Snake", "one")
        self.k.learn("SNAKE", "two")
        self.off("Snake")
        self.off("SNAKE")
        self.assertEqual(self.k.resolve_current_name("snake")["status"], "inactive")
        self.assertIsNone(self.best("Tell me about snake"))
        self.assertEqual(self.r.reason("What is snake?").status, "unknown")

    def test_ambiguity_is_deterministic(self):
        for n in ("Zeta", "ZETA", "zeta"):
            self.k.learn(n, n)
        first = self.k.resolve_current_name("ZeTa")
        for _ in range(3):
            self.assertEqual(self.k.resolve_current_name("ZeTa"), first)
        self.assertEqual(first["candidates"], ["ZETA", "Zeta", "zeta"])


class MeaningResolutionCurrentPath(Base):
    def understood(self, message):
        return {x["expression"]: x for x in self.core.understand_language(message).learned_meanings}

    def test_current_conversation_excludes_inactive_concept_while_explicit_lookup_is_raw(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        self.assertEqual(self.understood("Tell me about the viper please")["viper"]["status"], "RESOLVED")
        self.off("Snake")
        got = self.understood("Tell me about the viper please")["viper"]
        self.assertEqual((got["status"], got["meanings"]), ("NOT_FOUND", []))
        self.assertNotIn("reptile", str(self.core.understand_language("Tell me about the viper please").to_dict()))
        raw = self.core.resolve_language_meaning("viper", language=EN)                # explicit lookup stays raw
        self.assertEqual(raw.status, "RESOLVED")
        self.assertIn("reptile", str(raw.to_dict()))
        self.on("Snake")
        self.assertEqual(self.understood("Tell me about the viper please")["viper"]["status"], "RESOLVED")


# ----------------------------------------------------------------------------------------------------------
class SameProcessMutationAndReload(Base):
    def all_views(self):
        """One tuple of every current-layer view of the A -> B -> C chain."""
        return (
            self.r.reason("Does A depend on C?").status,
            self.r.reason("What is B?").status,
            self.best("Tell me about B"),
            self.sel("Tell me about B", ("b",)).status,
            len(self.k.current_relationships_for("A")["outgoing"]),
            self.k.resolve_current_name("B")["status"],
        )

    def test_no_stale_result_survives_a_mutation(self):
        self.chain()
        on = ("answered", "answered", "B", "SELECTED", 1, "exact")
        off = ("unknown", "unknown", None, "NOT_FOUND", 0, "inactive")
        self.assertEqual(self.all_views(), on)
        self.off("B")
        self.assertEqual(self.all_views(), off)
        self.on("B")
        self.assertEqual(self.all_views(), on)
        self.off("B")
        self.ls.teach("B", "B revived", source="user")                                # explicit teach reactivates
        self.assertEqual(self.all_views(), on)

    def test_relationship_added_after_read_is_seen(self):
        self.teach("A", "B")
        self.assertIsNone(self.r.summarize_relationships("A"))
        self.k.relate("A", "B", "USES")
        self.assertEqual(self.r.summarize_relationships("A"), "A uses B.")
        self.off("B")
        self.assertIsNone(self.r.summarize_relationships("A"))

    def test_close_reopen_preserves_current_versus_raw(self):
        self.chain()
        self.off("B")
        self.reopen()
        self.assertEqual(self.all_views(), ("unknown", "unknown", None, "NOT_FOUND", 0, "inactive"))
        self.assertEqual(self.k.get("B")["status"], "inactive")
        self.assertEqual(len(self.k.relationships_for("A")["outgoing"]), 1)
        self.on("B")
        self.reopen()
        self.assertEqual(self.all_views(), ("answered", "answered", "B", "SELECTED", 1, "exact"))

    def test_close_reopen_check_consistency(self):
        for i in range(4):
            self.teach(f"A{i}")
            self.off(f"A{i}")
        self.teach("Q", "X")
        self.k.relate("Q", "X", "IS_A")
        self.k.relate("Q", "X", "IS_NOT_A")
        self.reopen()
        res = self.r.check_consistency(max_entities=2)
        self.assertEqual((res["checked"], res["consistent"]), (["Q", "X"], False))


class ReadOnlyRetrieval(Base):
    def test_every_retrieval_layer_is_read_only_and_creates_no_events(self):
        self.chain()
        self.k.learn("Python", "upper")
        self.k.learn("PYTHON", "lower")
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        self.off("B")
        self.off("Snake")
        before = self.snap()
        events = len(self.m.query("SELECT * FROM learning_events"))
        for name in ("A", "B", "Python", "python", "Nope"):
            self.k.get(name)
            self.k.resolve_name(name)
            self.k.resolve_current_name(name)
            self.k.find_by_name_case_insensitive(name)
            self.k.find_current_by_name_case_insensitive(name)
            self.k.relationships_for(name)
            self.k.current_relationships_for(name)
            self.ls.recall(name)
            self.r.lookup(name)
            self.r.summarize_relationships(name)
            self.r.contradictions_for(name)
        self.k.all()
        self.k.search("description")
        self.ls.search("reptile")
        self.r.check_consistency()
        self.r.reason("Does A depend on C?")
        self.r.reason("What is Python?")
        self.r.traverse("A")
        self.r.find_path("A", "C")
        self.best("Tell me about python")
        self.sel("Tell me about A", ("a",))
        self.ctx("Tell me about A")
        self.core.process_input("Tell me about A")
        self.core.process_input("ASK B")
        self.core.understand_language("Tell me about the viper please")
        self.core.resolve_language_meaning("viper", language=EN)
        self.assertEqual(self.snap(), before)
        self.assertEqual(len(self.m.query("SELECT * FROM learning_events")), events)


if __name__ == "__main__":
    unittest.main()
