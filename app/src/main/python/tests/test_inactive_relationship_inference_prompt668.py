"""Prompt 668 - Section 3: relationships to/from inactive knowledge must not provide CURRENT inference.

Defect found: every ReasoningEngine read (direct relation answers, IS_A description fallback,
transitive DEPENDS_ON/PART_OF closure, rule premises, traverse/find_path, contradiction scans,
relationship summaries used by Core) consumed raw relationships_for() rows, so an active subject could
answer through an inactive endpoint and a multi-hop chain could pass through inactive knowledge.
Fix (read/inference boundary only): KnowledgeSystem.current_relationships_for() (new, read-only) and
ReasoningEngine._current_rels(). Stored rows, relate(), set_status() and raw relationships_for() unchanged.
"""
import os
import tempfile
import unittest

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
        self.r = self.core.reasoning

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

    def rel(self, a, b, t):
        self.k.relate(a, b, t)

    def reason(self, q):
        return self.r.reason(q)

    def chain(self):
        self.teach("A", "B", "C")
        self.rel("A", "B", "DEPENDS_ON")
        self.rel("B", "C", "DEPENDS_ON")


class ActiveActive(Base):
    def test_multi_hop_active_chain_answers(self):
        self.chain()
        r = self.reason("Does A depend on C?")
        self.assertEqual((r.status, r.answer), ("answered", "A depends on C (inferred)."))
        self.assertEqual(len(r.supporting_relationships), 2)

    def test_rule_inference_active(self):
        self.teach("Python", "Language", "Dev")
        self.rel("Python", "Language", "IS_A")
        self.rel("Language", "Dev", "USED_FOR")
        r = self.reason("What is Python used for?")
        self.assertEqual((r.status, r.answer), ("answered", "Python is used for Dev (inferred)."))

    def test_direct_is_a_active_stub_and_legacy(self):
        self.rel("Snake", "Reptile", "IS_A")  # both stubs
        self.assertEqual(self.reason("What is Snake?").answer, "Snake is a Reptile.")
        self.m._run("UPDATE knowledge SET status = 'legacy-x' WHERE name = 'Reptile'")
        self.assertEqual(self.reason("What is Snake?").answer, "Snake is a Reptile.")
        self.assertEqual(self.k.current_relationships_for("Snake"), self.k.relationships_for("Snake"))


class InactiveEndpoints(Base):
    def test_active_to_inactive_direct_relation_unavailable(self):
        self.teach("A", "B")
        self.rel("A", "B", "USES")
        self.assertEqual(self.reason("Does A use B?").status, "answered")
        self.off("B")
        r = self.reason("Does A use B?")
        self.assertEqual(r.status, "unknown")
        self.assertIsNone(r.answer)
        self.assertEqual(r.supporting_relationships, [])
        r = self.reason("What does A use?")
        self.assertEqual((r.status, r.answer), ("unknown", None))

    def test_inactive_source_to_active_target(self):
        self.teach("A", "B")
        self.rel("A", "B", "USES")
        self.off("A")
        self.assertEqual(self.reason("What does A use?").status, "unknown")
        self.assertEqual(self.r.traverse("A"), [])
        self.assertIsNone(self.r.summarize_relationships("B"))  # incoming row from inactive A
        self.assertEqual(self.k.current_relationships_for("B"), {"outgoing": [], "incoming": []})

    def test_inactive_to_inactive(self):
        self.teach("A", "B")
        self.rel("A", "B", "USES")
        self.off("A")
        self.off("B")
        self.assertEqual(self.reason("What does A use?").status, "unknown")
        self.assertEqual(self.r.traverse("A"), [])
        self.assertEqual(self.r.traverse("B"), [])

    def test_direct_is_a_description_fallback_needs_current_target(self):
        self.teach("Lang")
        self.rel("Snake", "Lang", "IS_A")  # Snake is an active-status stub with no description
        self.assertEqual(self.reason("What is Snake?").answer, "Snake is a Lang.")
        self.off("Lang")
        r = self.reason("What is Snake?")
        self.assertEqual((r.status, r.answer), ("unknown", None))
        self.assertEqual(r.supporting_relationships, [])
        self.on("Lang")
        self.assertEqual(self.reason("What is Snake?").answer, "Snake is a Lang.")

    def test_inactive_intermediate_breaks_chain(self):
        self.chain()
        self.off("B")
        r = self.reason("Does A depend on C?")
        self.assertEqual((r.status, r.answer), ("unknown", None))
        self.assertEqual(r.supporting_relationships, [])
        self.assertEqual(self.r.traverse("A", max_hops=3), [])
        self.assertIsNone(self.r.find_path("A", "C"))

    def test_inactive_source_of_chain(self):
        self.chain()
        self.off("A")
        self.assertEqual(self.reason("Does A depend on C?").status, "unknown")
        self.assertIsNone(self.r.find_path("A", "C"))

    def test_inactive_target_of_chain(self):
        self.chain()
        self.off("C")
        self.assertEqual(self.reason("Does A depend on C?").status, "unknown")
        self.assertIsNone(self.r.find_path("A", "C"))
        self.assertEqual([h["to"] for h in self.r.traverse("A", max_hops=3)], ["B"])

    def test_rule_premise_through_inactive_node(self):
        self.teach("Python", "Language", "Dev")
        self.rel("Python", "Language", "IS_A")
        self.rel("Language", "Dev", "USED_FOR")
        self.off("Language")
        self.assertEqual(self.reason("What is Python used for?").status, "unknown")
        self.on("Language")
        self.off("Dev")
        self.assertEqual(self.reason("What is Python used for?").status, "unknown")

    def test_active_alternative_path_still_used(self):
        self.teach("A", "B", "C", "D")
        for a, b in (("A", "B"), ("B", "C"), ("A", "D"), ("D", "C")):
            self.rel(a, b, "DEPENDS_ON")
        self.off("B")
        r = self.reason("Does A depend on C?")
        self.assertEqual((r.status, r.answer), ("answered", "A depends on C (inferred)."))
        used = {(x["from_name"], x["to_name"]) for x in r.supporting_relationships}
        self.assertEqual(used, {("A", "D"), ("D", "C")})
        self.assertEqual([s["to"] for s in self.r.find_path("A", "C")], ["D", "C"])

    def test_all_paths_inactive_is_unknown_not_fabricated(self):
        self.teach("A", "B", "C", "D")
        for a, b in (("A", "B"), ("B", "C"), ("A", "D"), ("D", "C")):
            self.rel(a, b, "DEPENDS_ON")
        self.off("B")
        self.off("D")
        r = self.reason("Does A depend on C?")
        self.assertEqual((r.status, r.answer), ("unknown", None))

    def test_generic_and_summary_ignore_inactive_endpoints(self):
        self.teach("B", "C")
        self.rel("Stub", "B", "USES")
        self.rel("Stub", "C", "USES")
        self.off("B")
        summary = self.r.summarize_relationships("Stub")
        self.assertIn("C", summary)
        self.assertNotIn("B", summary.replace("Stub", ""))
        self.off("C")
        self.assertIsNone(self.r.summarize_relationships("Stub"))
        self.assertEqual(self.reason("Stub").status, "unknown")

    def test_core_answer_does_not_use_inactive_endpoint(self):
        self.chain()
        self.assertIn("A depends on C", self.core.process_input("Does A depend on C?"))
        self.off("B")
        out = self.core.process_input("Does A depend on C?")
        self.assertNotIn("A depends on C", out)  # only C's own (active) description may surface
        self.teach("X")
        self.rel("Stub", "X", "USES")
        self.off("X")
        out = self.core.process_input("Tell me about Stub")
        self.assertNotIn("learned through relationships", out)


class Contradictions(Base):
    def setUp(self):
        super().setUp()
        self.teach("X")
        self.rel("Q", "X", "IS_A")
        self.rel("Q", "X", "IS_NOT_A")

    def test_contradiction_detected_when_active(self):
        self.assertEqual(len(self.r.contradictions_for("Q")), 1)
        self.assertEqual(len(self.reason("Q").contradictions), 1)
        self.assertIsNotNone(self.r.check_new_relationship("Q", "IS_A", "X"))

    def test_inactive_endpoint_contributes_no_contradiction(self):
        self.off("X")
        self.assertEqual(self.r.contradictions_for("Q"), [])
        self.assertTrue(self.r.check_consistency("Q")["consistent"])
        self.assertIsNone(self.r.check_new_relationship("Q", "IS_A", "X"))
        r = self.reason("Q")
        self.assertEqual(r.contradictions, [])
        self.assertNotEqual(r.status, "contradiction")
        self.assertEqual(self.reason("Does Q use X?").contradictions, [])

    def test_contradiction_returns_on_reactivation(self):
        self.off("X")
        self.on("X")
        self.assertEqual(len(self.r.contradictions_for("Q")), 1)


class Transitions(Base):
    def test_active_inactive_active_no_stale_inference(self):
        self.chain()
        seen = []
        for step in (None, "off", "on", "off", "on"):
            if step == "off":
                self.off("B")
            elif step == "on":
                self.on("B")
            seen.append(self.reason("Does A depend on C?").status)
        self.assertEqual(seen, ["answered", "unknown", "answered", "unknown", "answered"])

    def test_reactivation_restores_without_recreating_relationships(self):
        self.chain()
        before = self.m.query("SELECT * FROM relationships ORDER BY id")
        self.off("B")
        self.assertEqual(self.reason("Does A depend on C?").status, "unknown")
        self.on("B")
        self.assertEqual(self.reason("Does A depend on C?").status, "answered")
        self.assertEqual(self.m.query("SELECT * FROM relationships ORDER BY id"), before)

    def test_close_reopen_keeps_current_state_semantics(self):
        self.chain()
        self.off("B")
        self.reopen()
        self.assertEqual(self.reason("Does A depend on C?").status, "unknown")
        self.on("B")
        self.reopen()
        self.assertEqual(self.reason("Does A depend on C?").status, "answered")


class StorageAndRawApis(Base):
    def test_raw_relationship_api_unchanged_and_rows_kept(self):
        self.chain()
        self.off("B")
        raw = self.k.relationships_for("A")
        self.assertEqual([(x["to_name"], x["relation_type"]) for x in raw["outgoing"]], [("B", "DEPENDS_ON")])
        self.assertEqual([x["from_name"] for x in self.k.relationships_for("C")["incoming"]], ["B"])
        self.assertEqual(self.k.current_relationships_for("A"), {"outgoing": [], "incoming": []})
        self.assertEqual(self.m.query("SELECT COUNT(*) AS n FROM relationships")[0]["n"], 2)

    def test_relate_to_inactive_endpoint_still_stores(self):
        self.teach("A", "B")
        self.off("B")
        self.assertTrue(self.k.relate("A", "B", "USES"))
        self.assertEqual(len(self.k.relationships_for("A")["outgoing"]), 1)

    def test_reads_do_not_mutate_or_learn(self):
        self.chain()
        self.off("B")
        before = self.snap()
        for q in ("Does A depend on C?", "What does A depend on?", "A", "What is A?"):
            self.reason(q)
        self.r.traverse("A")
        self.r.find_path("A", "C")
        self.r.contradictions_for("A")
        self.r.summarize_relationships("A")
        self.k.current_relationships_for("A")
        self.core.process_input("Does A depend on C?")
        after = self.snap()
        self.assertEqual({t: after[t] for t in ("knowledge", "relationships")},
                         {t: before[t] for t in ("knowledge", "relationships")})
        self.assertEqual(after["learning_events"], before["learning_events"])

    def test_missing_endpoint_record_is_kept(self):
        self.m._run("PRAGMA foreign_keys = OFF")
        self.m._run("INSERT INTO relationships (from_name, to_name, relation_type, created_at, updated_at) "
                    "VALUES ('Ghost', 'Nowhere', 'USES', 'x', 'x')")
        self.assertEqual(len(self.k.current_relationships_for("Ghost")["outgoing"]), 1)

    def test_ambiguity_semantics_unchanged(self):
        self.teach("Foo", "foo")
        self.assertEqual(self.k.resolve_current_name("FOO")["status"], "ambiguous")
        self.off("foo")
        self.assertEqual(self.k.resolve_current_name("FOO")["status"], "case_insensitive")


if __name__ == "__main__":
    unittest.main()
