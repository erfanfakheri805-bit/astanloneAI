"""Prompt 665 - Section 3: NEW learning operations against inactive knowledge.

Contract pinned here:
- Natural-language learning (learn_from_text) only writes relationships; an inactive record is never
  modified, versioned, re-timestamped or reactivated.
- teach()/correct() (explicit, by name) reactivate deterministically on the same record.
- The conversational "not X, I mean Y" path selects its target IMPLICITLY (by description text); an
  inactive record is not a candidate there (Prompt 665 fix), so it is never silently reactivated.
- relate() to an inactive endpoint stores/updates the relationship (rows are never disabled) and leaves
  the endpoint inactive.
- Failures roll back status/version/description/relationships/events atomically.
"""
import os
import tempfile
import unittest
from unittest import mock

from core.core import Core
from language_intelligence.learned_knowledge_context import select_learned_knowledge

TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items",
          "language_item_relationships")
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

    def snap(self):
        return {t: self.m.query(f"SELECT * FROM {t} ORDER BY id") for t in TABLES}

    def ev(self, *types):
        return [e for e in self.m.query("SELECT * FROM learning_events ORDER BY id")
                if not types or e["event_type"] in types]

    def sel(self, msg="Tell me about Python", terms=("python",)):
        return select_learned_knowledge(msg, self.k, candidate_terms=list(terms))

    def inactive_python(self, desc="a snake", rel=False):
        self.ls.teach("Python", desc, source="user", confidence=0.6, source_text="st", learning_method="ael")
        if rel:
            self.ls.relate("Python", "Reptile", "is_a", source="user", confidence=0.5)
        self.ls.set_status("Python", "inactive")
        return self.k.get("Python")

    def assert_untouched(self, before):
        after = self.k.get("Python")
        self.assertEqual(after, before)
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='python'")), 1)


class NaturalLanguage(Base):
    def test_A_same_concept(self):
        b = self.inactive_python("a programming language")
        n = len(self.ev())
        res = self.core.learn_from_text("Python is a language.")
        self.assertTrue(res.success)
        self.assert_untouched(b)
        self.assertEqual([e["event_type"] for e in self.ev()][n:], ["relate"])   # relationship event only
        self.assertFalse(self.sel().selected)

    def test_B_updated_description_text_does_not_edit_record(self):
        b = self.inactive_python("a snake")
        self.core.learn_from_text("Python is a programming language.")
        self.assert_untouched(b)
        self.assertEqual(self.k.get("Python")["description"], "a snake")

    def test_C_related_concept(self):
        b = self.inactive_python()
        self.core.learn_from_text("Snake is an animal.")
        self.assert_untouched(b)
        self.assertEqual(self.k.get("Snake")["status"], "stub")

    def test_D_repeated_identical_input_is_noop(self):
        b = self.inactive_python()
        self.core.learn_from_text("Python is a language.")
        s = self.snap()
        self.core.learn_from_text("Python is a language.")
        self.assert_untouched(b)
        self.assertEqual(self.snap()["knowledge"], s["knowledge"])
        self.assertEqual(self.snap()["relationships"], s["relationships"])
        self.assertEqual(len(self.ev("relate")), len([e for e in s["learning_events"] if e["event_type"] == "relate"]))

    def test_E_inactive_with_relationships(self):
        b = self.inactive_python(rel=True)
        rels = self.m.query("SELECT * FROM relationships ORDER BY id")
        self.core.learn_from_text("Python is a language.")
        self.assert_untouched(b)
        after = self.m.query("SELECT * FROM relationships ORDER BY id")
        self.assertEqual(after[:len(rels)], rels)          # existing rows untouched, only additions
        self.assertFalse(self.sel().selected)

    def test_nl_source_and_no_reactivation_across_reload(self):
        b = self.inactive_python()
        self.core.learn_from_text("Python is a language.")
        s = self.snap()
        self.reopen()
        self.assertEqual(self.snap(), s)
        self.assert_untouched(b)
        self.assertFalse(self.sel().selected)


class ConversationalCorrection(Base):
    def test_implicit_target_inactive_not_reactivated(self):
        b = self.inactive_python("a snake")
        s = self.snap()
        self.core.process_input(CORR)
        self.assert_untouched(b)
        self.assertEqual(self.ev("correct"), [])
        self.assertEqual(self.snap()["knowledge"], s["knowledge"])
        self.assertFalse(self.sel().selected)

    def test_active_target_still_corrected(self):
        self.ls.teach("Python", "a snake", source="user", confidence=0.6)
        self.core.process_input(CORR)
        r = self.k.get("Python")
        self.assertEqual((r["status"], r["version"], r["description"]),
                         ("active", 2, "a programming language"))
        self.assertEqual(len(self.ev("correct")), 1)

    def test_active_and_inactive_match_only_active_is_target(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.teach("Cobra", "a snake", source="user")
        self.ls.set_status("Cobra", "inactive")
        self.core.process_input(CORR)
        self.assertEqual(self.k.get("Python")["description"], "a programming language")
        c = self.k.get("Cobra")
        self.assertEqual((c["status"], c["description"], c["version"]), ("inactive", "a snake", 2))

    def test_reactivate_then_correction_applies(self):
        self.inactive_python("a snake")
        self.ls.set_status("Python", "active")
        self.core.process_input(CORR)
        self.assertEqual(self.k.get("Python")["description"], "a programming language")


class ExplicitTeachCorrect(Base):
    def test_teach_reactivates_same_record_deterministically(self):
        b = self.inactive_python("a snake", rel=True)
        rid = b["id"]
        n = len(self.ev())
        r = self.ls.teach("Python", "a programming language", source="user")
        self.assertEqual((r["id"], r["status"], r["version"], r["description"]),
                         (rid, "active", b["version"] + 1, "a programming language"))
        self.assertEqual(r["confidence"], 0.6)               # None keeps stored provenance
        self.assertEqual((r["source_text"], r["learning_method"]), ("st", "ael"))
        self.assertEqual([e["event_type"] for e in self.ev()][n:], ["teach"])
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='python'")), 1)
        self.assertTrue(self.sel().selected)                 # immediately selectable (Prompt 664)
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)

    def test_teach_identical_same_desc_still_reactivates_once(self):
        self.inactive_python("a snake")
        r = self.ls.teach("Python", "a snake", source="user")
        self.assertEqual((r["status"], r["version"]), ("active", 3))
        r2 = self.ls.teach("Python", "a snake", source="user")     # now a true no-op
        self.assertEqual(r2["version"], 3)
        self.assertEqual(len(self.ev("teach")), 2)

    def test_correct_reactivates_same_record_with_history(self):
        b = self.inactive_python("a snake", rel=True)
        n = len(self.ev())
        r = self.ls.correct("Python", "a programming language")
        self.assertEqual((r["id"], r["status"], r["version"], r["description"]),
                         (b["id"], "active", b["version"] + 1, "a programming language"))
        self.assertEqual(r["source"], "user")                # None keeps stored source
        new = self.ev()[n:]
        self.assertEqual([e["event_type"] for e in new], ["correct"])
        self.assertEqual(new[0]["detail"], "'a snake' -> 'a programming language'")
        self.assertEqual(new[0]["source"], "user")
        self.assertEqual(self.k.get("Python")["description"], "a programming language")
        self.assertTrue(self.sel().selected)
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)

    def test_correct_case_variant_resolves_same_record(self):
        self.inactive_python("a snake")
        self.ls.correct("python", "a programming language")
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='python'")), 1)
        self.assertEqual(self.k.get("Python")["status"], "active")


class Sequences(Base):
    SEQS = {
        "a-i": ["inactive"], "i-i": ["inactive", "inactive"],
        "i-a": ["inactive", "active"], "a-i-a": ["inactive", "active"],
    }

    def _prep(self, seq):
        self.ls.teach("Python", "a snake", source="user")
        for st in seq:
            self.ls.set_status("Python", st)
        return self.k.get("Python")

    def test_inactive_sequences_then_operations_no_hidden_transition(self):
        for name, seq in (("a-i", ["inactive"]), ("i-i", ["inactive", "inactive"])):
            with self.subTest(seq=name):
                self.setUp()
                b = self._prep(seq)
                self.assertEqual(b["status"], "inactive")
                self.assertEqual(b["version"], 2)                      # inactive->inactive is a no-op
                self.assertEqual(len(self.ev("status")), 1)
                self.core.learn_from_text("Python is a language.")     # NL
                self.ls.relate("Python", "Code", "used_for", source="user")   # relationship
                self.core.process_input(CORR)                          # implicit correction
                self.assertEqual(self.k.get("Python")["status"], "inactive")
                self.assertEqual(self.k.get("Python")["version"], 2)
                self.assertFalse(self.sel().selected)
                self.ls.teach("Python", "a language", source="user")   # explicit
                self.assertEqual(self.k.get("Python")["status"], "active")
                self.assertTrue(self.sel().selected)

    def test_active_sequences_then_operations_stay_active(self):
        for name, seq in (("i-a", ["inactive", "active"]), ("a-i-a", ["inactive", "active"]),
                          ("plain-active", [])):
            with self.subTest(seq=name):
                self.setUp()
                self._prep(seq)
                self.core.learn_from_text("Python is a language.")
                self.ls.relate("Python", "Code", "used_for", source="user")
                self.assertEqual(self.k.get("Python")["status"], "active")
                self.assertTrue(self.sel().selected)
                self.ls.correct("Python", "a scripting language")
                self.assertEqual(self.k.get("Python")["status"], "active")

    def test_correct_after_inactive_sequence(self):
        self._prep(["inactive"])
        self.ls.correct("Python", "a language")
        self.assertEqual(self.k.get("Python")["status"], "active")
        self.assertEqual(self.sel().record["description"], "a language")


class Relationships(Base):
    def setUp(self):
        super().setUp()
        self.b = self.inactive_python()

    def test_new_relationship_keeps_endpoint_inactive(self):
        n = len(self.ev())
        out = self.ls.relate("Python", "Code", "used_for", source="user", confidence=0.4,
                             source_text="rt", learning_method="lm")
        self.assertTrue(out["created"])
        self.assertEqual(self.k.get("Python"), self.b)
        self.assertEqual([e["event_type"] for e in self.ev()][n:], ["relate"])
        row = self.m.query_one("SELECT * FROM relationships WHERE from_name='Python' AND to_name='Code'")
        self.assertEqual((row["confidence"], row["source_type"], row["source_text"], row["learning_method"]),
                         (0.4, "user", "rt", "lm"))
        self.assertFalse(self.sel().selected)

    def test_incoming_relationship_to_inactive_endpoint(self):
        self.ls.relate("Code", "Python", "uses", source="user")
        self.assertEqual(self.k.get("Python"), self.b)
        self.assertEqual(len(self.k.relationships_for("Python")["incoming"]), 1)

    def test_repeat_is_noop_without_event(self):
        self.ls.relate("Python", "Code", "used_for", source="user", confidence=0.4)
        s = self.snap()
        out = self.ls.relate("Python", "Code", "used_for", source="user", confidence=0.4)
        self.assertFalse(out["created"])
        self.assertEqual(self.snap(), s)

    def test_metadata_update_event_and_endpoint_untouched(self):
        self.ls.relate("Python", "Code", "used_for", source="user", confidence=0.4)
        n = len(self.ev())
        self.ls.relate("Python", "Code", "used_for", source="user", confidence=0.9)
        self.assertEqual(self.k.get("Python"), self.b)
        self.assertEqual([e["event_type"] for e in self.ev()][n:], ["relate"])
        self.assertEqual(self.m.query_one("SELECT confidence FROM relationships WHERE to_name='Code'")["confidence"], 0.9)
        self.assertEqual(len(self.m.query("SELECT * FROM relationships WHERE to_name='Code'")), 1)

    def test_relationships_not_disabled_by_inactive_endpoint(self):
        self.ls.relate("Python", "Code", "used_for", source="user")
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)
        self.assertEqual(len(self.ls.recall("Python")["relationships"]["outgoing"]), 1)


class Atomicity(Base):
    def _boom_event(self):
        return mock.patch.object(self.m, "add_learning_event", side_effect=Boom("event"))

    def _fail_on(self, prefix, after=False):
        real = self.m._run

        def run(sql, params=()):
            if not after and sql.startswith(prefix):
                raise Boom("before")
            cur = real(sql, params)
            if after and sql.startswith(prefix):
                raise Boom("after")
            return cur
        return mock.patch.object(self.m, "_run", side_effect=run)

    def test_teach_reactivation_rollback(self):
        b = self.inactive_python(rel=True)
        s = self.snap()
        with self._boom_event():
            with self.assertRaises(Boom):
                self.ls.teach("Python", "new", source="user")
        self.assertEqual(self.snap(), s)
        self.assertEqual(self.k.get("Python"), b)
        for after in (False, True):
            with self._fail_on("UPDATE knowledge", after):
                with self.assertRaises(Boom):
                    self.ls.teach("Python", "new", source="user")
            self.assertEqual(self.snap(), s)
        self.assertEqual(self.ls.teach("Python", "new", source="user")["version"], b["version"] + 1)  # no gap

    def test_correct_reactivation_rollback(self):
        b = self.inactive_python(rel=True)
        s = self.snap()
        with self._boom_event():
            with self.assertRaises(Boom):
                self.ls.correct("Python", "new")
        self.assertEqual(self.snap(), s)
        for after in (False, True):
            with self._fail_on("UPDATE knowledge", after):
                with self.assertRaises(Boom):
                    self.ls.correct("Python", "new")
            self.assertEqual(self.snap(), s)
        self.assertEqual(self.k.get("Python"), b)
        self.assertEqual(self.ls.correct("Python", "new")["version"], b["version"] + 1)

    def test_relationship_learning_rollback(self):
        b = self.inactive_python(rel=True)
        s = self.snap()
        with self._boom_event():
            with self.assertRaises(Boom):
                self.ls.relate("Python", "Code", "used_for", source="user")
        self.assertEqual(self.snap(), s)
        for after in (False, True):
            with self._fail_on("INSERT INTO relationships", after):
                with self.assertRaises(Boom):
                    self.ls.relate("Python", "Code", "used_for", source="user")
            self.assertEqual(self.snap(), s)
        self.assertEqual(self.k.get("Python"), b)

    def test_relationship_metadata_update_rollback(self):
        self.inactive_python()
        self.ls.relate("Python", "Code", "used_for", source="user", confidence=0.4)
        s = self.snap()
        with self._boom_event():
            with self.assertRaises(Boom):
                self.ls.relate("Python", "Code", "used_for", source="user", confidence=0.9)
        self.assertEqual(self.snap(), s)

    def test_nl_learning_against_inactive_failure_leaves_no_partial_state(self):
        b = self.inactive_python(rel=True)
        s = self.snap()
        with self._boom_event():
            res = self.core.learn_from_text("Python is a language.")   # NL reports persist errors, never raises
        self.assertFalse(res.success)
        for t in ("knowledge", "relationships", "learning_events"):
            self.assertEqual(self.snap()[t], s[t], t)
        self.assertEqual(self.k.get("Python"), b)


class ReloadAndReadOnly(Base):
    def test_teach_and_correct_reactivation_persist(self):
        for op in ("teach", "correct"):
            with self.subTest(op=op):
                self.setUp()
                self.inactive_python()
                if op == "teach":
                    self.ls.teach("Python", "x", source="user")
                else:
                    self.ls.correct("Python", "x")
                s = self.snap()
                self.reopen()
                self.assertEqual(self.snap(), s)
                self.assertEqual(self.k.get("Python")["status"], "active")
                self.assertTrue(self.sel().selected)

    def test_inactive_persists_and_reload_makes_no_events(self):
        self.inactive_python(rel=True)
        self.core.learn_from_text("Python is a language.")
        s = self.snap()
        self.reopen()
        self.assertEqual(self.snap(), s)
        self.assertFalse(self.sel().selected)
        self.assertEqual(self.snap(), s)

    def test_events_only_for_real_mutations(self):
        self.inactive_python()
        n = len(self.ev())
        self.ls.set_status("Python", "inactive")                      # no-op
        self.ls.correct("Nope", "x")                                  # unknown: nothing
        self.assertEqual(len(self.ev()), n)
        self.ls.set_status("Python", "active")
        self.assertEqual([e["detail"] for e in self.ev("status")][-1], "'inactive' -> 'active'")


if __name__ == "__main__":
    unittest.main()
