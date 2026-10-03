"""Prompt 675 - Section 3: knowledge snapshot / reload / stale-state integrity.

Audit result (docs/section3_knowledge_snapshot_reload_stale_state_prompt675.md): every CURRENT consumer
reads through to SQLite on each call (KnowledgeSystem/Core/ReasoningEngine/select_learned_knowledge keep no
cache, memo or retained resolver/relationship list; the only per-call dict is local to current_relationships_for).
The only retained attributes are per-turn diagnostics (Core.last_*, LanguageIntelligenceCore.last_*) and the
diagnostic statistics counter - none is read back as current knowledge. NO genuine defect, no production change.

These tests pin that on the real production paths, within ONE Core lifetime and across close/reopen.
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

    def ans(self, q="Tell me about Python"):
        return self.core.reason(q).answer

    def chat(self, text="tell me about python"):
        return self.core.process_input(text)

    def outs(self, s):
        return sorted(r["to_name"] for r in s.relationships["outgoing"])

    def base(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.teach("Code", "text", source="user")
        self.k.relate("Python", "Code", "USED_FOR")


class NoRetainedCurrentState(Base):
    def test_knowledge_owners_hold_no_cache(self):
        for obj in (self.k, self.ls, self.core.reasoning):
            for name, value in vars(obj).items():
                low = name.lower()
                self.assertFalse(any(w in low for w in ("cache", "memoiz", "resolved", "snapshot")), (obj, name))
        self.assertEqual(sorted(vars(self.k)), ["memory"])

    def test_current_relationship_read_is_repeatable_and_read_only(self):
        self.base()
        before = self.snap()
        a = self.k.current_relationships_for("Python")
        b = self.k.current_relationships_for("Python")
        self.assertEqual(a, b)
        self.assertEqual(before, self.snap())


class SameProcessTransitions(Base):
    def test_active_inactive_active_all_consumers_immediate(self):
        self.base()
        self.assertEqual(self.ans(), "a language")
        self.assertIn("a language", self.chat())
        self.assertTrue(self.sel().selected)
        self.off("Python")
        self.assertIsNone(self.ans())
        self.assertNotIn("a language", self.chat())
        self.assertFalse(self.sel().selected)
        self.assertEqual(self.k.resolve_current_name("Python")["status"], "inactive")
        self.on("Python")
        self.assertEqual(self.ans(), "a language")
        self.assertIn("a language", self.chat())
        self.assertTrue(self.sel().selected)

    def test_description_correction_immediate(self):
        self.base()
        self.assertEqual(self.ans(), "a language")
        self.ls.correct("Python", "a snake-named language", source="user")
        self.assertEqual(self.ans(), "a snake-named language")
        self.assertIn("a snake-named language", self.chat())
        self.assertEqual(self.sel().record["description"], "a snake-named language")

    def test_relationship_creation_immediate(self):
        self.base()
        self.assertEqual(self.outs(self.sel()), ["Code"])
        self.ls.teach("Tool", "a tool", source="user")
        self.k.relate("Python", "Tool", "USES")
        self.assertEqual(self.outs(self.sel()), ["Code", "Tool"])
        self.assertIn("Tool", str(self.k.current_relationships_for("Python")["outgoing"]))

    def test_stub_to_taught_immediate(self):
        self.k.relate("Snake", "Reptile", "IS_A")
        self.assertEqual(self.k.get("Snake")["description"] in (None, ""), True)
        self.ls.teach("Snake", "a legless reptile", source="user")
        self.assertEqual(self.ans("Tell me about Snake"), "a legless reptile")
        self.assertEqual(self.sel("Tell me about Snake", ("snake",)).record["description"], "a legless reptile")
        self.assertEqual(self.outs(self.sel("Tell me about Snake", ("snake",))), ["Reptile"])

    def test_teach_reactivates_inactive(self):
        self.base()
        self.off("Python")
        self.assertIsNone(self.ans())
        self.ls.teach("Python", "a language again", source="user")
        self.assertEqual(self.ans(), "a language again")
        self.assertTrue(self.sel().selected)

    def test_inactive_endpoint_traversal_and_reactivation(self):
        self.base()
        self.ls.teach("Bytes", "raw data", source="user")
        self.k.relate("Code", "Bytes", "MADE_OF")
        self.assertEqual(self.outs(self.sel()), ["Code"])
        self.off("Code")  # inactive TARGET
        self.assertEqual(self.k.current_relationships_for("Python")["outgoing"], [])
        self.assertEqual(self.k.current_relationships_for("Code"), {"outgoing": [], "incoming": []})
        self.assertEqual(self.k.current_relationships_for("Bytes")["incoming"], [])  # multi-hop through inactive
        self.on("Code")  # reactivation
        self.assertEqual([r["to_name"] for r in self.k.current_relationships_for("Python")["outgoing"]], ["Code"])
        self.assertEqual([r["from_name"] for r in self.k.current_relationships_for("Bytes")["incoming"]], ["Code"])
        self.off("Python")  # inactive SOURCE
        self.assertEqual([r["from_name"] for r in self.k.current_relationships_for("Code")["incoming"]], [])
        self.assertEqual([r["to_name"] for r in self.k.current_relationships_for("Code")["outgoing"]], ["Bytes"])

    def test_multi_hop_reasoning_follows_status(self):
        for n, d in (("A", "a"), ("B", "b"), ("C", "c")):
            self.ls.teach(n, d, source="user")
        self.k.relate("A", "B", "DEPENDS_ON")
        self.k.relate("B", "C", "DEPENDS_ON")
        q = "Does A depend on C?"
        self.assertEqual(self.ans(q), "A depends on C (inferred).")
        self.off("B")  # middle hop inactive: the inferred chain must vanish immediately
        self.assertIsNone(self.ans(q))
        self.on("B")
        self.assertEqual(self.ans(q), "A depends on C (inferred).")
        self.off("C")  # far endpoint inactive
        self.assertIsNone(self.ans(q))
        self.reopen()
        self.assertIsNone(self.ans(q))
        self.on("C")
        self.reopen()
        self.assertEqual(self.ans(q), "A depends on C (inferred).")

    def test_many_operations_one_lifetime_match_fresh_core(self):
        self.base()
        self.off("Code")
        self.ls.correct("Python", "v2", source="user")
        self.on("Code")
        self.ls.teach("Tool", "a tool", source="user")
        self.k.relate("Python", "Tool", "USES")
        self.off("Tool")
        live = (self.ans(), self.outs(self.sel()), self.chat())
        self.reopen()
        self.assertEqual((self.ans(), self.outs(self.sel()), self.chat()), live)


class CloseReopen(Base):
    def test_state_after_reopen_matches_persisted(self):
        self.base()
        self.off("Python")
        self.reopen()
        self.assertIsNone(self.ans())
        self.assertFalse(self.sel().selected)
        self.assertNotIn("a language", self.chat())
        self.on("Python")
        self.reopen()
        self.assertEqual(self.ans(), "a language")
        self.assertIn("a language", self.chat())
        self.assertEqual(self.outs(self.sel()), ["Code"])
        self.ls.correct("Python", "fixed", source="user")
        self.reopen()
        self.assertEqual(self.sel().record["description"], "fixed")

    def test_per_turn_diagnostics_do_not_leak_across_reopen(self):
        self.base()
        self.core.understand_language("Tell me about Python")
        self.reopen()
        self.assertIsNone(self.core.last_learned_knowledge_gate)
        self.assertIsNone(self.core.last_learned_knowledge_gate_trace)

    def test_gate_attachment_reflects_latest_state_each_turn(self):
        self.base()
        self.assertIsNotNone(self.core.understand_language("Tell me about Python").learned_knowledge_context)
        self.off("Python")
        self.assertIsNone(self.core.understand_language("Tell me about Python").learned_knowledge_context)
        self.assertIsNone(self.core.last_learned_knowledge_gate)  # reset per turn, not stale
        self.on("Python")
        ctx = self.core.understand_language("Tell me about Python").learned_knowledge_context
        self.assertIn("a language", str(ctx))


class CaseVariants(Base):
    def test_exact_and_unique_case_insensitive(self):
        self.ls.teach("Python", "the language", source="user")
        self.assertEqual(self.k.resolve_current_name("Python")["status"], "exact")
        self.assertEqual(self.k.resolve_current_name("python")["status"], "case_insensitive")

    def test_ambiguous_current_variants_then_one_goes_inactive(self):
        self.ls.teach("Python", "the language", source="user")
        self.ls.teach("python", "the snake", source="user")
        self.assertEqual(self.k.resolve_current_name("PYTHON")["status"], "ambiguous")
        self.assertIsNone(self.ans("Tell me about PYTHON"))
        self.off("python")  # ambiguity clears immediately in the same lifetime
        r = self.k.resolve_current_name("PYTHON")
        self.assertEqual((r["status"], r["record"]["name"]), ("case_insensitive", "Python"))
        self.on("python")
        self.assertEqual(self.k.resolve_current_name("PYTHON")["status"], "ambiguous")

    def test_inactive_variant_only(self):
        self.ls.teach("Python", "the language", source="user")
        self.off("Python")
        self.assertEqual(self.k.resolve_current_name("python")["status"], "inactive")
        self.reopen()
        self.assertEqual(self.k.resolve_current_name("python")["status"], "inactive")


class FailedMutations(Base):
    def test_rejected_status_changes_nothing(self):
        self.base()
        before = self.snap()
        with self.assertRaises(ValueError):
            self.ls.set_status("Python", "bogus")
        self.assertEqual(before, self.snap())
        self.assertEqual(self.ans(), "a language")
        self.assertTrue(self.sel().selected)

    def test_correct_unknown_name_changes_nothing(self):
        self.base()
        before = self.snap()
        try:
            self.ls.correct("Nope", "x", source="user")
        except Exception:
            pass
        self.assertEqual(before, self.snap())
        self.assertIsNone(self.ans("Tell me about Nope"))

    def test_rolled_back_relationship_leaves_no_stale_state(self):
        self.base()
        self.ls.teach("Tool", "a tool", source="user")
        before = self.snap()
        real_run = self.m._run
        calls = {"n": 0}

        def flaky(sql, params=()):
            if sql.lstrip().upper().startswith("INSERT INTO LEARNING_EVENTS") or "learning_events" in sql.lower() and sql.lstrip().upper().startswith("INSERT"):
                calls["n"] += 1
                raise RuntimeError("boom")
            return real_run(sql, params)

        self.m._run = flaky
        try:
            with self.assertRaises(Exception):
                self.ls.relate("Python", "Tool", "USES")
        finally:
            self.m._run = real_run
        self.assertGreaterEqual(calls["n"], 1)
        self.assertEqual(before, self.snap())
        self.assertEqual(self.outs(self.sel()), ["Code"])
        self.assertEqual(self.ans(), "a language")


class RawVsCurrent(Base):
    def test_raw_apis_keep_returning_inactive(self):
        self.base()
        self.off("Python")
        self.assertEqual(self.k.get("Python")["status"], "inactive")
        self.assertEqual(self.k.resolve_name("python")["status"], "case_insensitive")
        self.assertEqual(self.k.find_by_name_case_insensitive("python")["name"], "Python")
        self.assertEqual([r["to_name"] for r in self.k.relationships_for("Python")["outgoing"]], ["Code"])
        self.assertEqual(self.k.current_relationships_for("Python"), {"outgoing": [], "incoming": []})
        self.assertIn("Python", [r["name"] for r in self.k.all()])
        self.assertIsNotNone(self.ls.recall("Python"))
        self.on("Python")
        self.assertEqual(self.k.resolve_name("python")["status"], "case_insensitive")

    def test_ael_ask_stays_raw_and_tracks_persisted_state(self):
        self.base()
        self.off("Python")
        self.assertIn("a language", self.core.process_input("ASK Python"))  # documented raw recall
        self.ls.correct("Python", "fixed", source="user")
        self.assertIn("fixed", self.core.process_input("ASK Python"))
        self.reopen()
        self.assertIn("fixed", self.core.process_input("ASK Python"))

    def test_read_only_consumers_write_nothing(self):
        self.base()
        self.off("Code")
        before = self.snap()
        self.ans()
        self.sel()
        self.core.reason("Is Python used for Code?")
        self.k.resolve_current_name("python")
        self.k.current_relationships_for("Python")
        self.core.understand_language("Tell me about Python")
        self.assertEqual(before, self.snap())


if __name__ == "__main__":
    unittest.main()
