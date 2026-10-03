"""Prompt 670 - Section 3: learned_knowledge_context vs the current lifecycle.

Trace: Core._attach_learned_knowledge -> select_learned_knowledge -> Prompt 502 gate (relationship rows are
reliability EVIDENCE) -> understanding.learned_knowledge_context -> ResponseGenerationContext ->
InferenceRequest.generation_context.to_dict() -> a configured local-model backend, whose generated text is
returned directly as the reply. Rows are therefore not merely informational: a row to an inactive endpoint
could reach a generated current answer and could count as gate evidence.
Defect fixed at that boundary: the context's rows are CURRENT-only (KnowledgeSystem.current_relationships_for).
Stored rows, raw relationships_for(), recall/ASK, set_status, teach/correct and Prompt 664 entry selection are
unchanged.
"""
import os
import tempfile
import unittest

from core.core import Core
from language_intelligence.learned_knowledge_context import select_learned_knowledge

TABLES = ("knowledge", "relationships", "learning_events")


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

    def off(self, n):
        self.ls.set_status(n, "inactive")

    def on(self, n):
        self.ls.set_status(n, "active")

    def sel(self, msg="Tell me about Python", terms=("python",)):
        return select_learned_knowledge(msg, self.k, candidate_terms=list(terms))

    def base(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.teach("Code", "text", source="user")
        self.ls.teach("Tool", "a tool", source="user")
        self.k.relate("Python", "Code", "USED_FOR")
        self.k.relate("Python", "Tool", "USES")

    def outs(self, s):
        return sorted(r["to_name"] for r in s.relationships["outgoing"])


class ContextRows(Base):
    def test_active_with_active_endpoints_unchanged(self):
        self.base()
        s = self.sel()
        self.assertTrue(s.selected)
        self.assertEqual(self.outs(s), ["Code", "Tool"])
        self.assertEqual(s.relationships, self.k.relationships_for("Python"))

    def test_inactive_endpoint_row_omitted_from_context(self):
        self.base()
        self.off("Code")
        s = self.sel()
        self.assertTrue(s.selected)
        self.assertEqual(self.outs(s), ["Tool"])
        self.assertNotIn("Code", str(s.to_context()["relationships"]))
        self.assertEqual(s.record["description"], "a language")

    def test_incoming_row_from_inactive_source_omitted(self):
        self.base()
        self.ls.teach("Ruby", "another", source="user")
        self.k.relate("Ruby", "Python", "SIMILAR_TO")
        self.off("Ruby")
        s = self.sel()
        self.assertEqual([r["from_name"] for r in s.relationships["incoming"]], [])
        self.on("Ruby")
        self.assertEqual([r["from_name"] for r in self.sel().relationships["incoming"]], ["Ruby"])

    def test_inactive_entry_still_excluded(self):
        self.base()
        self.off("Python")
        self.assertFalse(self.sel().selected)

    def test_stub_with_only_inactive_rows_has_no_current_content(self):
        self.ls.teach("Code", "text", source="user")
        self.k.relate("Snake", "Code", "USES")  # Snake is a stub, no description
        self.assertTrue(self.sel("Tell me about Snake", ("snake",)).selected)
        self.off("Code")
        self.assertFalse(self.sel("Tell me about Snake", ("snake",)).selected)
        self.on("Code")
        self.assertTrue(self.sel("Tell me about Snake", ("snake",)).selected)

    def test_stub_and_legacy_status_unchanged(self):
        self.k.relate("Snake", "Reptile", "IS_A")
        s = self.sel("Tell me about Snake", ("snake",))
        self.assertEqual(self.outs(s), ["Reptile"])
        self.m._run("UPDATE knowledge SET status = 'legacy-x' WHERE name = 'Reptile'")
        self.assertEqual(self.outs(self.sel("Tell me about Snake", ("snake",))), ["Reptile"])

    def test_missing_helper_falls_back_to_raw(self):
        self.base()

        class Raw:
            def __init__(s, k):
                s.k = k

            def find_by_name_case_insensitive(s, n):
                return s.k.find_by_name_case_insensitive(n)

            def relationships_for(s, n):
                return s.k.relationships_for(n)

            def get(s, n):
                return s.k.get(n)

        out = select_learned_knowledge("Tell me about Python", Raw(self.k), candidate_terms=["python"])
        self.assertEqual(self.outs(out), ["Code", "Tool"])


class Transitions(Base):
    def test_active_inactive_active_immediate(self):
        self.base()
        seen = []
        for step in (None, "off", "on"):
            if step == "off":
                self.off("Code")
            elif step == "on":
                self.on("Code")
            seen.append(self.outs(self.sel()))
        self.assertEqual(seen, [["Code", "Tool"], ["Tool"], ["Code", "Tool"]])

    def test_reopen_same_semantics(self):
        self.base()
        self.off("Code")
        self.reopen()
        self.assertEqual(self.outs(self.sel()), ["Tool"])
        self.on("Code")
        self.reopen()
        self.assertEqual(self.outs(self.sel()), ["Code", "Tool"])


class GateEvidence(Base):
    def test_inactive_rows_do_not_count_as_gate_evidence(self):
        # Stub entry whose only evidence would be a row to an inactive endpoint: not selected, so never gated.
        self.ls.teach("Code", "text", source="user")
        self.k.relate("Snake", "Code", "USES")
        self.off("Code")
        self.assertIsNone(self._attach("Tell me about Snake"))

    def _attach(self, msg):
        class U:
            learned_knowledge_context = None
        u = U()
        self.core._attach_learned_knowledge(u, msg)
        return u.learned_knowledge_context

    def test_core_attach_carries_current_rows_only(self):
        self.base()
        self.off("Code")
        ctx = self._attach("Tell me about Python")
        self.assertIsNotNone(ctx)
        self.assertEqual(sorted(r["to_name"] for r in ctx["relationships"]["outgoing"]), ["Tool"])
        self.on("Code")
        ctx = self._attach("Tell me about Python")
        self.assertEqual(sorted(r["to_name"] for r in ctx["relationships"]["outgoing"]), ["Code", "Tool"])


class Preserved(Base):
    def test_no_mutation_or_learning_events(self):
        self.base()
        self.off("Code")
        before = self.snap()
        self.sel()
        self._attach_ok()
        self.core.select_learned_knowledge("Tell me about Python")
        self.assertEqual(self.snap(), before)

    def _attach_ok(self):
        class U:
            learned_knowledge_context = None
        self.core._attach_learned_knowledge(U(), "Tell me about Python")

    def test_raw_apis_and_rows_preserved(self):
        self.base()
        self.off("Code")
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 2)
        self.assertEqual(len(self.ls.recall("Python")["relationships"]["outgoing"]), 2)
        self.assertEqual(self.m.query("SELECT COUNT(*) AS n FROM relationships")[0]["n"], 2)

    def test_prompt669_ask_stays_raw(self):
        self.base()
        self.off("Code")
        out = self.core.process_input("ASK Python")
        self.assertIn("Python USED_FOR Code", out)
        self.assertIn("Python USES Tool", out)

    def test_prompt668_reasoning_stays_current_only(self):
        self.base()
        self.off("Code")
        r = self.core.reasoning.reason("What is Python used for?")
        self.assertEqual((r.status, r.answer), ("unknown", None))
        self.on("Code")
        self.assertEqual(self.core.reasoning.reason("What is Python used for?").status, "answered")

    def test_prompt664_entry_selection_unchanged(self):
        self.base()
        self.off("Python")
        self.assertFalse(self.sel().selected)
        self.on("Python")
        self.assertTrue(self.sel().selected)

    def test_conversation_path_unaffected(self):
        self.base()
        out = self.core.process_input("Tell me about Python")
        self.assertIn("a language", out)


if __name__ == "__main__":
    unittest.main()
