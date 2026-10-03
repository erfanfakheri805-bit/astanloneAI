"""Prompt 666 - Section 3: no learning operation silently targets an inactive record it was not told to.

Audit result pinned here (production unchanged in this prompt; the Prompt 665 guard in
Core._apply_resolved_correction_to_knowledge is the only implicit-target selector that writes):
- conversational correction: implicit (description-text) target; inactive records are never candidates
- NL learning: resolves names to existing records (case-insensitive) but writes relationships only
- explicit teach(name)/correct(name)/set_status(name): unchanged
- ambiguity never picks a record; no duplicate is created because an implicit lookup declined an inactive record
"""
import os
import tempfile
import unittest
from unittest import mock

from core.core import Core
from language_intelligence.learned_knowledge_context import select_learned_knowledge

TABLES = ("knowledge", "relationships", "learning_events")
CORR = "not a snake, I mean a programming language."


class Boom(RuntimeError):
    pass


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

    def snap(self, tables=TABLES):
        # The Section 2 correction-storage event ("language_item_learned") is written for every
        # resolved correction regardless of knowledge targeting; only knowledge-side state is compared.
        out = {t: self.m.query(f"SELECT * FROM {t} ORDER BY id") for t in tables}
        out["learning_events"] = [e for e in out.get("learning_events", [])
                                  if e["event_type"] != "language_item_learned"]
        return out

    def names(self):
        return sorted((r["name"], r["status"], r["version"]) for r in self.k.all())

    def ev(self, *types):
        return [e for e in self.m.query("SELECT * FROM learning_events ORDER BY id")
                if not types or e["event_type"] in types]

    def sel(self, msg="Tell me about Python", terms=("python",)):
        return select_learned_knowledge(msg, self.k, candidate_terms=list(terms))


class ConversationalCorrectionTargets(Base):
    def test_inactive_only_match_writes_nothing_and_creates_no_duplicate(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.set_status("Python", "inactive")
        s = self.snap()
        self.core.process_input(CORR)
        self.assertEqual(self.snap(), s)                       # knowledge / relationships / events identical
        self.assertEqual(self.ev("correct"), [])

    def test_two_active_matches_stay_ambiguous_even_with_inactive_third(self):
        for n in ("Python", "Cobra", "Viper"):
            self.ls.teach(n, "a snake", source="user")
        self.ls.set_status("Viper", "inactive")
        s = self.snap()
        self.core.process_input(CORR)
        self.assertEqual(self.snap(), s)                       # ambiguous: nothing chosen

    def test_single_active_among_inactives_is_only_target(self):
        for n in ("Python", "Cobra", "Viper"):
            self.ls.teach(n, "a snake", source="user")
        self.ls.set_status("Cobra", "inactive")
        self.ls.set_status("Viper", "inactive")
        self.core.process_input(CORR)
        self.assertEqual(self.k.get("Python")["description"], "a programming language")
        for n in ("Cobra", "Viper"):
            r = self.k.get(n)
            self.assertEqual((r["status"], r["description"], r["version"]), ("inactive", "a snake", 2))
        self.assertEqual(len(self.ev("correct")), 1)

    def test_correction_target_after_explicit_reactivation_and_reload(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.set_status("Python", "inactive")
        self.core.process_input(CORR)
        self.reopen()
        self.assertEqual(self.k.get("Python")["status"], "inactive")
        self.ls.set_status("Python", "active")
        self.core.process_input(CORR)
        self.assertEqual(self.k.get("Python")["description"], "a programming language")
        self.reopen()
        self.assertEqual(self.k.get("Python")["status"], "active")

    def test_active_target_correction_is_atomic(self):
        self.ls.teach("Python", "a snake", source="user")
        s = self.snap()
        real = self.m.add_learning_event

        def ev(event_type, *a, **kw):
            if event_type == "correct":
                raise Boom("e")
            return real(event_type, *a, **kw)
        with mock.patch.object(self.m, "add_learning_event", side_effect=ev):
            with self.assertRaises(Boom):          # existing behavior: only ValueError is absorbed
                self.core.process_input(CORR)
        self.assertEqual(self.snap(), s)
        self.assertEqual(self.k.get("Python")["description"], "a snake")

    def test_inactive_target_never_attempts_a_write(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.set_status("Python", "inactive")
        real = self.m.add_learning_event
        seen = []

        def ev(event_type, *a, **kw):
            seen.append(event_type)
            return real(event_type, *a, **kw)
        with mock.patch.object(self.m, "add_learning_event", side_effect=ev):
            self.core.process_input(CORR)
        self.assertNotIn("correct", seen)
        self.assertEqual(self.k.get("Python")["status"], "inactive")


class NaturalLanguageResolution(Base):
    def test_case_variant_reference_resolves_to_inactive_record_no_duplicate(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.set_status("Python", "inactive")
        before = self.k.get("Python")
        res = self.core.learn_from_text("python is a language.")
        self.assertEqual(res.learned_items[0]["subject"], "Python")     # existing canonical record
        self.assertEqual(self.k.get("Python"), before)                   # untouched, still inactive
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='python'")), 1)
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)

    def test_ambiguous_case_duplicates_never_pick_a_record(self):
        self.ls.teach("Python", "a", source="user")
        self.ls.teach("python", "b", source="user")
        self.ls.set_status("python", "inactive")
        before = {n: self.k.get(n) for n in ("Python", "python")}
        self.core.learn_from_text("PYTHON is a language.")
        for n, rec in before.items():
            self.assertEqual(self.k.get(n), rec)                         # neither existing record touched
            self.assertEqual(self.k.relationships_for(n)["outgoing"], [])
        self.assertEqual(self.k.get("PYTHON")["status"], "stub")        # existing Prompt 637 behavior

    def test_both_endpoints_inactive(self):
        self.ls.teach("Python", "a", source="user")
        self.ls.teach("Snake", "b", source="user")
        self.ls.set_status("Python", "inactive")
        self.ls.set_status("Snake", "inactive")
        b = self.names()
        res = self.core.learn_from_text("Python is a Snake.")
        self.assertTrue(res.success)
        self.assertEqual(self.names(), b)                                # no status/version/row change
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)

    def test_related_concept_of_inactive_record_stays_unlinked_to_lifecycle(self):
        self.ls.teach("Python", "a", source="user")
        self.ls.set_status("Python", "inactive")
        self.core.learn_from_text("Snake is an animal.")
        self.assertEqual(self.k.get("Python")["status"], "inactive")
        self.assertEqual(self.k.get("Python")["version"], 2)


class ExplicitOperationsUnchanged(Base):
    def setUp(self):
        super().setUp()
        self.ls.teach("Python", "a snake", source="user")
        self.ls.set_status("Python", "inactive")

    def test_explicit_teach_reactivates_named_record_only(self):
        self.ls.teach("Cobra", "another", source="user")
        self.ls.teach("Python", "a language", source="user")
        self.assertEqual(self.k.get("Python")["status"], "active")
        self.assertEqual(self.k.get("Cobra")["version"], 1)

    def test_explicit_correct_case_variant_reactivates_same_record(self):
        self.ls.correct("python", "a language")
        self.assertEqual((self.k.get("Python")["status"], self.k.get("Python")["version"]), ("active", 3))
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='python'")), 1)

    def test_ambiguous_explicit_correct_raises_and_writes_nothing(self):
        self.ls.teach("python", "x", source="user")
        s = self.snap()
        with self.assertRaises(ValueError):
            self.ls.correct("PYTHON", "y")
        self.assertEqual(self.snap(), s)

    def test_set_status_is_only_lifecycle_control_and_noop_is_silent(self):
        n = len(self.ev())
        self.ls.set_status("Python", "inactive")
        self.assertEqual(len(self.ev()), n)
        self.ls.set_status("Python", "active")
        self.assertEqual(len(self.ev("status")), 2)


class SelectionNeverFeedsMutation(Base):
    def test_selection_and_context_are_read_only_for_inactive_and_active(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.relate("Python", "Reptile", "is_a", source="user")
        for state in ("inactive", "active"):
            self.ls.set_status("Python", state)
            s = self.snap()
            self.core.select_learned_knowledge("Tell me about Python")
            self.sel()
            class U: learned_knowledge_context = None
            self.core._attach_learned_knowledge(U(), "Tell me about Python")
            self.assertEqual(self.snap(), s)
        self.assertEqual(self.sel().status, "SELECTED")

    def test_full_cycle_no_hidden_transition(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.set_status("Python", "inactive")
        self.core.learn_from_text("Python is a language.")
        self.core.process_input(CORR)
        self.core.select_learned_knowledge("Tell me about Python")
        self.ls.relate("Python", "Code", "used_for", source="user")
        r = self.k.get("Python")
        self.assertEqual((r["status"], r["version"], r["description"]), ("inactive", 2, "a snake"))
        self.reopen()
        r = self.k.get("Python")
        self.assertEqual((r["status"], r["version"], r["description"]), ("inactive", 2, "a snake"))
        self.assertEqual([e["event_type"] for e in self.ev("status", "correct", "teach")],
                         ["teach", "status"])


if __name__ == "__main__":
    unittest.main()
