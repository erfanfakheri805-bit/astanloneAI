"""Prompt 669 - Section 3: AEL ASK vs the current-knowledge lifecycle.

Audit result: AEL ASK is an EXPLICIT, exact-name RAW RECALL (contract A), not a current-answer path.
Flow: AEL parser -> AELInterpreter._execute_ask -> LearningSystem.recall(name) ->
ConceptSystem.get_with_relations -> KnowledgeSystem.get + raw relationships_for; the reply is a literal
listing "<name>: <description>" plus one "  A REL B" line per STORED row. It performs no inference, no
name resolution (exact case only) and no answer synthesis. The only interpreted output - the contradiction
NOTE lines - already uses the current-only path (Prompt 668). Production code is therefore unchanged.
"""
import os
import tempfile
import unittest

from core.core import Core

TABLES = ("knowledge", "relationships", "learning_events")


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

    def ask(self, n):
        return self.core.process_input(f"ASK {n}")


class ActiveOutput(Base):
    def test_active_subject_active_endpoint_exact_output(self):
        self.teach("Python", "Indent")
        self.k.relate("Python", "Indent", "USES")
        self.assertEqual(self.ask("Python"),
                         "[AEL OK] Python: Python description\n  Python USES Indent")
        self.assertEqual(self.ask("Indent"),
                         "[AEL OK] Indent: Indent description\n  Python USES Indent")

    def test_unknown_and_case_sensitive_name(self):
        self.teach("Python")
        self.assertEqual(self.ask("Nope"), "[AEL OK] I don't know anything about 'Nope' yet.")
        self.assertEqual(self.ask("python"), "[AEL OK] I don't know anything about 'python' yet.")

    def test_stub_and_legacy_status_unchanged(self):
        self.k.relate("Snake", "Reptile", "IS_A")  # both stubs
        self.assertEqual(self.ask("Snake"), "[AEL OK] Snake: (no description yet)\n  Snake IS_A Reptile")
        self.m._run("UPDATE knowledge SET status = 'legacy-x' WHERE name = 'Reptile'")
        self.assertEqual(self.ask("Reptile"), "[AEL OK] Reptile: (no description yet)\n  Snake IS_A Reptile")


class InactiveIsRawRecall(Base):
    def setUp(self):
        super().setUp()
        self.teach("Python", "Indent")
        self.k.relate("Python", "Indent", "USES")

    def test_inactive_endpoint_row_still_listed_as_stored_data(self):
        self.off("Indent")
        self.assertEqual(self.ask("Python"), "[AEL OK] Python: Python description\n  Python USES Indent")

    def test_inactive_target_source_and_subject_are_raw_readable(self):
        self.off("Indent")
        self.assertEqual(self.ask("Indent"), "[AEL OK] Indent: Indent description\n  Python USES Indent")
        self.on("Indent")
        self.off("Python")
        self.assertEqual(self.ask("Python"), "[AEL OK] Python: Python description\n  Python USES Indent")
        self.assertEqual(self.ask("Indent"), "[AEL OK] Indent: Indent description\n  Python USES Indent")

    def test_recall_equals_raw_retrieval_and_is_not_filtered(self):
        self.off("Indent")
        info = self.ls.recall("Python")
        self.assertEqual(info["relationships"], self.k.relationships_for("Python"))
        self.assertEqual(self.k.current_relationships_for("Python"), {"outgoing": [], "incoming": []})
        self.assertEqual(info["status"], "active")

    def test_raw_recall_versus_current_inference(self):
        self.off("Indent")
        self.assertIn("Python USES Indent", self.ask("Python"))          # raw stored row
        r = self.r.reason("What does Python use?")                        # current inference
        self.assertEqual((r.status, r.answer), ("unknown", None))
        self.assertNotIn("Indent", self.core.process_input("What does Python use?"))

    def test_multi_hop_is_not_traversed_by_ask(self):
        self.teach("A", "B", "C")
        self.k.relate("A", "B", "DEPENDS_ON")
        self.k.relate("B", "C", "DEPENDS_ON")
        self.off("B")
        out = self.ask("A")
        self.assertEqual(out, "[AEL OK] A: A description\n  A DEPENDS_ON B")   # one stored hop, no chain
        self.assertNotIn("C", out.replace("A description", ""))
        self.assertEqual(self.r.reason("Does A depend on C?").status, "unknown")
        self.on("B")
        self.assertEqual(self.r.reason("Does A depend on C?").status, "answered")
        self.assertEqual(self.ask("A"), out)


class ContradictionNote(Base):
    def setUp(self):
        super().setUp()
        self.teach("Python", "Lang")
        self.k.relate("Python", "Lang", "IS_A")
        self.k.relate("Python", "Lang", "IS_NOT_A")
        self.note = "  NOTE: conflicting info toward 'Lang' - both 'IS_A' and 'IS_NOT_A' are recorded."

    def test_note_present_when_current(self):
        out = self.ask("Python")
        self.assertTrue(out.endswith(self.note))
        self.assertIn("Python IS_A Lang", out)
        self.assertIn("Python IS_NOT_A Lang", out)

    def test_note_dropped_but_raw_rows_kept_when_endpoint_inactive(self):
        self.off("Lang")
        out = self.ask("Python")
        self.assertNotIn("NOTE", out)
        self.assertIn("Python IS_A Lang", out)
        self.assertIn("Python IS_NOT_A Lang", out)

    def test_note_dropped_when_subject_inactive_and_returns_on_reactivation(self):
        self.off("Python")
        self.assertNotIn("NOTE", self.ask("Python"))
        self.on("Python")
        self.assertIn(self.note, self.ask("Python"))


class TransitionsAndReload(Base):
    def test_output_transitions_active_inactive_active(self):
        self.teach("Python", "Lang")
        self.k.relate("Python", "Lang", "IS_A")
        self.k.relate("Python", "Lang", "IS_NOT_A")
        outs = []
        for step in (None, "off", "on"):
            if step == "off":
                self.off("Lang")
            elif step == "on":
                self.on("Lang")
            outs.append(self.ask("Python"))
        self.assertEqual(outs[0], outs[2])
        self.assertIn("NOTE", outs[0])
        self.assertNotIn("NOTE", outs[1])
        self.assertEqual([l for l in outs[0].splitlines() if "NOTE" not in l], outs[1].splitlines())

    def test_close_reopen_same_semantics(self):
        self.teach("Python", "Lang")
        self.k.relate("Python", "Lang", "IS_A")
        self.k.relate("Python", "Lang", "IS_NOT_A")
        self.off("Lang")
        self.reopen()
        out = self.ask("Python")
        self.assertIn("Python IS_A Lang", out)
        self.assertNotIn("NOTE", out)
        self.on("Lang")
        self.reopen()
        self.assertIn("NOTE", self.ask("Python"))


class ReadOnlyAndRawApis(Base):
    def test_ask_never_mutates_or_learns(self):
        self.teach("Python", "Lang")
        self.k.relate("Python", "Lang", "IS_A")
        self.k.relate("Python", "Lang", "IS_NOT_A")
        self.off("Lang")
        before = self.snap()
        for n in ("Python", "Lang", "Nope", "python"):
            self.ask(n)
        self.assertEqual(self.snap(), before)

    def test_raw_apis_and_stored_rows_preserved(self):
        self.teach("Python", "Indent")
        self.k.relate("Python", "Indent", "USES")
        self.off("Indent")
        self.assertEqual(self.k.get("Indent")["status"], "inactive")
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)
        self.assertEqual(self.ls.recall("Indent")["description"], "Indent description")
        self.assertEqual(self.m.query("SELECT COUNT(*) AS n FROM relationships")[0]["n"], 1)

    def test_ask_output_contract_shape(self):
        self.teach("Python")
        results = self.core.ael.run("ASK Python")
        self.assertEqual(len(results), 1)
        self.assertEqual(set(results[0].to_dict()), {"instruction", "success", "message"})
        self.assertTrue(results[0].success)


if __name__ == "__main__":
    unittest.main()
