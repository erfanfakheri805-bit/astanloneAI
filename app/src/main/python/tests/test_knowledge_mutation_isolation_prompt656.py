"""Prompt 656 - Section 3: mutation isolation.

AUDIT, not a redesign. Every test pins EXISTING behavior; a mutation of one knowledge record / relationship /
concept must leave every unrelated row (knowledge, relationships, learning_events, language tables) equal
state-for-state, timestamps and provenance compared verbatim.

  M1  teach / correct / relate / stub-upgrade / NL learning touch only their own target (rows + events + versions).
  M2  No-ops, failed atomic ops and ambiguous identities mutate nothing at all (any candidate or bystander).
  M3  Isolation survives close/reopen, and independent scenarios give the same final state in either order.
  M4  Documented shared metadata is preserved: sqlite_sequence counters advance with inserts; a relate() that
      creates a stub legitimately adds a NEW row (never edits an existing one); Core open touches only the
      unrelated `capabilities` table.

Concurrency: true concurrent writers are NOT supported/implemented (one connection + RLock-style lock, _atomic is
a re-entrant single-connection scope). Nothing here spawns threads/processes; a second sequential connection is
used only to show committed state is visible.
"""
import os
import tempfile
import unittest
from unittest import mock

from core.core import Core
from memory.memory_system import MemorySystem
from language_intelligence.language_relationships import concept_ref, item_ref

TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items",
          "language_item_relationships")


class Boom(RuntimeError):
    pass


class Isolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "i.db")
        self._open()
        self.seed()

    def _open(self):
        self.core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m = self.core.knowledge, self.core.learning, self.core.memory

    def reopen(self):
        self.m._conn.close()
        self._open()

    def seed(self):
        ls = self.ls
        ls.teach("Cat", "a feline", source="user", confidence=0.5, source_text="cats", learning_method="ael")
        ls.teach("Dog", "a canine", source="ael", confidence=0.8, source_text="dogs", learning_method="ael")
        ls.teach("Tree", "a plant", source="document", confidence=0.3, source_text="trees")
        ls.teach("River", "flowing water", source="user", confidence=0.95)
        ls.relate("Cat", "Animal", "is_a", source="user", confidence=0.9, source_text="cat animal")   # stub Animal
        ls.relate("Dog", "Animal", "is_a", source="ael", confidence=0.7)
        ls.relate("Tree", "Plant", "is_a", source="document", confidence=0.6)                         # stub Plant
        ls.relate("River", "Sea", "flows_to", source="user", confidence=0.4, learning_method="ael")   # stub Sea
        ls.relate("Cat", "Dog", "chases", source="user", confidence=0.2)
        self.core.language_learning.learn_item("english", "word", "feline", meaning="cat-like", source="user",
                                               source_context="ctx", confidence=0.6)
        self.core.relate_language_items(item_ref("english", "word", "feline"), concept_ref("Cat"),
                                        "concept_to_expression", metadata={"n": 1}, source="user")

    # ---- helpers ------------------------------------------------------------------------------------
    def snap(self, m=None):
        m = m or self.m
        return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")] for t in TABLES}

    @staticmethod
    def krows(snap):
        return {r["name"]: r for r in snap["knowledge"]}

    @staticmethod
    def edges(snap):
        return {(r["from_name"], r["relation_type"], r["to_name"]): r for r in snap["relationships"]}

    def assert_only_knowledge_changed(self, before, after, names):
        b, a = self.krows(before), self.krows(after)
        self.assertEqual(set(b) - set(a), set())                      # nothing deleted
        for n in b:
            if n not in names:
                self.assertEqual(a[n], b[n], f"unrelated knowledge record {n} mutated")   # incl. version, ts
        for n in names:
            if n in b:
                self.assertEqual((a[n]["id"], a[n]["created_at"]), (b[n]["id"], b[n]["created_at"]))
        self.assertEqual(after["relationships"], before["relationships"])
        self.assertEqual(after["language_learning_items"], before["language_learning_items"])
        self.assertEqual(after["language_item_relationships"], before["language_item_relationships"])

    def assert_events_appended_only(self, before, after, targets, n):
        old = before["learning_events"]
        self.assertEqual(after["learning_events"][:len(old)], old)     # history is append-only, old rows verbatim
        new = after["learning_events"][len(old):]
        self.assertEqual(len(new), n)
        for e in new:
            self.assertIn(e["target"], targets)

    # ---- M1 -----------------------------------------------------------------------------------------
    def test_teach_mutates_only_its_record(self):
        before = self.snap()
        self.ls.teach("Cat", "a small feline", source="user", confidence=0.7)
        after = self.snap()
        self.assert_only_knowledge_changed(before, after, {"Cat"})
        b, a = self.krows(before)["Cat"], self.krows(after)["Cat"]
        self.assertEqual(a["version"], b["version"] + 1)
        self.assertEqual((a["description"], a["confidence"]), ("a small feline", 0.7))
        self.assertEqual((a["source_text"], a["learning_method"]), (b["source_text"], b["learning_method"]))
        self.assert_events_appended_only(before, after, {"Cat"}, 1)
        self.assertEqual(after["learning_events"][-1]["event_type"], "teach")
        for n in ("Dog", "Tree", "River", "Animal", "Plant", "Sea"):
            self.assertEqual(self.krows(after)[n]["version"], self.krows(before)[n]["version"])

    def test_correct_mutates_only_its_record_relationships_and_events(self):
        before = self.snap()
        self.ls.correct("cat", "a small domestic feline", source="user_correction")     # case-insensitive resolve
        after = self.snap()
        self.assert_only_knowledge_changed(before, after, {"Cat"})
        self.assertEqual(self.krows(after)["Cat"]["version"], self.krows(before)["Cat"]["version"] + 1)
        self.assertEqual(self.krows(after)["Cat"]["name"], "Cat")
        self.assert_events_appended_only(before, after, {"Cat"}, 1)
        self.assertEqual(after["learning_events"][-1]["event_type"], "correct")
        self.assertEqual(self.k.relationships_for("Cat"), self.k.relationships_for("Cat"))

    def test_relationship_update_touches_only_that_row(self):
        before = self.snap()
        self.ls.relate("Cat", "Animal", "is_a", source="user", confidence=0.99)
        after = self.snap()
        e_b, e_a = self.edges(before), self.edges(after)
        target = ("Cat", "is_a", "Animal")
        self.assertEqual(len(e_a), len(e_b))
        for key, row in e_b.items():
            if key != target:
                self.assertEqual(e_a[key], row, f"unrelated relationship {key} mutated")
        self.assertEqual(e_a[target]["confidence"], 0.99)
        self.assertEqual((e_a[target]["id"], e_a[target]["created_at"]), (e_b[target]["id"], e_b[target]["created_at"]))
        self.assertGreaterEqual(e_a[target]["updated_at"], e_b[target]["updated_at"])
        self.assertEqual(after["knowledge"], before["knowledge"])                        # no knowledge row moved at all
        self.assertEqual(after["language_item_relationships"], before["language_item_relationships"])
        self.assert_events_appended_only(before, after, {"Cat"}, 1)
        self.assertEqual(after["learning_events"][-1]["event_type"], "relate")

    def test_new_relationship_adds_a_row_and_never_edits_existing_ones(self):
        before = self.snap()
        self.ls.relate("Dog", "Cat", "fears", source="user", confidence=0.1)             # both endpoints exist
        after = self.snap()
        self.assertEqual(after["knowledge"], before["knowledge"])
        self.assertEqual(after["relationships"][:len(before["relationships"])], before["relationships"])
        self.assertEqual(len(after["relationships"]), len(before["relationships"]) + 1)
        self.assert_events_appended_only(before, after, {"Dog"}, 1)

    def test_stub_upgrade_leaves_other_stubs_and_records_alone(self):
        before = self.snap()
        stub = self.krows(before)["Animal"]
        self.assertEqual(stub["status"], "stub")
        self.ls.teach("Animal", "a living being", source="user")
        after = self.snap()
        self.assert_only_knowledge_changed(before, after, {"Animal"})
        up = self.krows(after)["Animal"]
        self.assertEqual((up["id"], up["created_at"], up["version"], up["status"]),
                         (stub["id"], stub["created_at"], stub["version"] + 1, "active"))
        for n in ("Plant", "Sea"):
            self.assertEqual(self.krows(after)[n], self.krows(before)[n])
            self.assertEqual(self.krows(after)[n]["status"], "stub")
        self.assert_events_appended_only(before, after, {"Animal"}, 1)

    def test_natural_language_learning_for_one_concept_does_not_touch_others(self):
        before = self.snap()
        self.core.learn_from_text("Python is a language.")
        after = self.snap()
        b, a = self.krows(before), self.krows(after)
        for n in b:
            self.assertEqual(a[n], b[n], f"pre-existing record {n} mutated by NL learning of another concept")
        self.assertEqual(after["relationships"][:len(before["relationships"])], before["relationships"])
        self.assertEqual(after["language_learning_items"], before["language_learning_items"])
        self.assertEqual(after["language_item_relationships"], before["language_item_relationships"])
        new_names = set(a) - set(b)
        self.assertTrue(new_names)
        self.assertLessEqual(new_names, {"Python", "language", "Language"})
        old = before["learning_events"]
        self.assertEqual(after["learning_events"][:len(old)], old)
        for e in after["learning_events"][len(old):]:
            self.assertNotIn(e["target"], b)                                            # events only for NL targets

    def test_conversational_correction_only_touches_its_own_target(self):
        self.core.learn_from_text("Python is a language.")
        self.ls.teach("Python", "a snake", source="user")
        before = self.snap()
        self.core.process_input("not a snake, I mean a programming language.")
        after = self.snap()
        b, a = self.krows(before), self.krows(after)
        changed = {n for n in b if a[n] != b[n]}
        self.assertLessEqual(changed, {"Python", "language", "Language"})
        for n in ("Cat", "Dog", "Tree", "River", "Animal", "Plant", "Sea"):
            self.assertEqual(a[n], b[n])
        old = before["learning_events"]
        self.assertEqual(after["learning_events"][:len(old)], old)
        for e in after["learning_events"][len(old):]:
            self.assertNotIn(e["target"], ("Cat", "Dog", "Tree", "River", "Animal", "Plant", "Sea"))

    def test_versions_and_timestamps_change_only_on_the_mutated_record(self):
        before = self.krows(self.snap())
        for n in ("Dog", "Tree"):
            self.ls.teach(n, f"new {n}", source="user")
        self.ls.correct("River", "moving water")
        after = self.krows(self.snap())
        for n, row in before.items():
            if n in ("Dog", "Tree", "River"):
                self.assertEqual(after[n]["version"], row["version"] + 1)
                self.assertGreaterEqual(after[n]["updated_at"], row["updated_at"])
            else:
                self.assertEqual((after[n]["version"], after[n]["created_at"], after[n]["updated_at"]),
                                 (row["version"], row["created_at"], row["updated_at"]), n)

    def test_provenance_of_unrelated_records_is_untouched(self):
        keys = ("source", "confidence", "source_text", "learning_method", "status", "kind", "description")
        before = {n: {k: r[k] for k in keys} for n, r in self.krows(self.snap()).items()}
        self.ls.teach("Cat", "x", source="other", confidence=0.01, source_text="zz", learning_method="nl")
        self.ls.correct("Tree", "y", source="user_correction", confidence=0.2)
        after = {n: {k: r[k] for k in keys} for n, r in self.krows(self.snap()).items()}
        for n in before:
            if n not in ("Cat", "Tree"):
                self.assertEqual(after[n], before[n], n)
        self.assertEqual(after["Cat"]["source_text"], "zz")
        self.assertEqual(after["Tree"]["source_text"], before["Tree"]["source_text"])   # None keeps stored value

    # ---- M2 -----------------------------------------------------------------------------------------
    def test_exact_noops_mutate_nothing(self):
        before = self.snap()
        c, t = self.k.get("Cat"), self.k.get("Tree")
        self.ls.teach("Cat", c["description"], source=c["source"])
        self.ls.correct("Tree", t["description"])
        rel = self.edges(before)[("Cat", "is_a", "Animal")]
        self.ls.relate("Cat", "Animal", "is_a", source=rel["source_type"])
        self.assertEqual(self.snap(), before)

    def test_failed_operations_do_not_partially_mutate_anything(self):
        before = self.snap()
        with mock.patch.object(type(self.m), "add_learning_event", side_effect=Boom("e")):
            for op in (lambda: self.ls.teach("Cat", "zzz", source="q"),
                       lambda: self.ls.teach("NewOne", "brand new"),
                       lambda: self.ls.correct("Dog", "yyy"),
                       lambda: self.ls.relate("Cat", "Brand", "likes"),
                       lambda: self.ls.relate("Tree", "Plant", "is_a", confidence=0.01),
                       lambda: self.core.learn_from_text("Python is a language.")):
                try:
                    op()
                except Boom:
                    pass
        self.assertEqual(self.snap(), before)
        self.reopen()
        self.assertEqual(self.snap(), before)

    def test_invalid_inputs_are_rejected_without_writing(self):
        before = self.snap()
        for op in (lambda: self.ls.teach("", "d"), lambda: self.ls.teach(None, "d"),
                   lambda: self.ls.correct("Cat", ""), lambda: self.ls.correct("", "d"),
                   lambda: self.ls.relate("Cat", "", "is_a"), lambda: self.ls.relate("", "Dog", "is_a"),
                   lambda: self.ls.relate("Cat", "Dog", None)):
            with self.assertRaises(ValueError):
                op()
        self.assertIsNone(self.ls.correct("NoSuchRecord", "d"))                          # correct never creates
        self.assertEqual(self.snap(), before)

    def test_ambiguous_identity_mutates_no_candidate_and_no_bystander(self):
        self.ls.teach("Python", "a")
        self.ls.teach("python", "b")
        self.ls.teach("PYTHON", "c")
        before = self.snap()
        self.assertEqual(self.k.resolve_name("pYthon")["status"], "ambiguous")
        with self.assertRaises(ValueError):
            self.ls.correct("pYthon", "changed")
        self.assertIsNone(self.k.find_by_name_case_insensitive("pYthon"))
        self.assertEqual(self.snap(), before)                                             # nothing, incl. events
        self.ls.correct("python", "b2")                                                    # exact name still isolated
        after = self.snap()
        self.assert_only_knowledge_changed(before, after, {"python"})
        self.assertEqual([self.k.get(n)["description"] for n in ("Python", "python", "PYTHON")], ["a", "b2", "c"])
        self.assert_events_appended_only(before, after, {"python"}, 1)

    # ---- M3 -----------------------------------------------------------------------------------------
    def test_isolation_holds_across_reopen(self):
        self.reopen()
        before = self.snap()
        self.ls.teach("Dog", "a loyal canine", source="user")
        self.reopen()
        after = self.snap()
        self.assert_only_knowledge_changed(before, after, {"Dog"})
        self.assert_events_appended_only(before, after, {"Dog"}, 1)
        self.reopen()
        self.assertEqual(self.snap(), after)

    def test_second_connection_sees_committed_change_and_unchanged_bystanders(self):
        before = self.snap()
        self.ls.correct("River", "moving water")
        m2 = MemorySystem(self.db)
        try:
            self.assertEqual(self.snap(m2), self.snap())
            self.assert_only_knowledge_changed(before, self.snap(m2), {"River"})
        finally:
            m2._conn.close()

    def _scenarios(self):
        return [lambda: self.ls.teach("Cat", "a small feline", source="user", confidence=0.7),
                lambda: self.ls.correct("Tree", "a woody plant", source="user_correction"),
                lambda: self.ls.relate("River", "Sea", "flows_to", source="user", confidence=0.9),
                lambda: self.ls.teach("Animal", "a living being", source="user"),
                lambda: self.ls.teach("Cat", "a small feline", source="user", confidence=0.7)]   # exact no-op

    def _final(self):
        s = self.snap()
        return {"k": {r["name"]: {k: v for k, v in r.items() if k not in ("id", "created_at", "updated_at")}
                      for r in s["knowledge"]},
                "e": sorted((e["event_type"], e["target"], e["detail"], e["source"]) for e in s["learning_events"]),
                "r": {key: {k: v for k, v in r.items() if k not in ("id", "created_at", "updated_at")}
                      for key, r in self.edges(s).items()}}

    def test_independent_scenarios_in_alternating_order_reach_the_same_final_state(self):
        ops = self._scenarios()
        for op in ops:
            op()
        forward = self._final()
        # fresh database, reverse order
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "j.db")
        self.m._conn.close()
        self._open()
        self.seed()
        for op in reversed(self._scenarios()):
            op()
        self.assertEqual(self._final(), forward)
        # fresh database, alternating (outer-in) order
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "k.db")
        self.m._conn.close()
        self._open()
        self.seed()
        ops = self._scenarios()
        for i in (0, 4, 1, 3, 2):
            ops[i]()
        self.assertEqual(self._final(), forward)

    # ---- M4: documented shared metadata is preserved ---------------------------------------------------
    def test_shared_counters_only_advance_with_real_inserts(self):
        def seq():
            return {r["name"]: r["seq"] for r in self.m.query("SELECT * FROM sqlite_sequence")}
        s0 = seq()
        self.ls.teach("Cat", "changed", source="user")                                   # update: no new ids
        self.ls.relate("Cat", "Animal", "is_a", confidence=0.11)                         # update: no new ids
        self.ls.teach("Cat", "changed", source="user")                                   # no-op
        s1 = seq()
        self.assertEqual({k: v for k, v in s1.items() if k != "learning_events"},
                         {k: v for k, v in s0.items() if k != "learning_events"})
        self.assertEqual(s1["learning_events"], s0["learning_events"] + 2)
        self.ls.teach("Brand", "new", source="user")
        self.assertEqual(seq()["knowledge"], s1["knowledge"] + 1)

    def test_relate_creating_a_stub_adds_only_new_rows(self):
        before = self.snap()
        self.ls.relate("Cat", "Newcomer", "likes", source="user")
        after = self.snap()
        b, a = self.krows(before), self.krows(after)
        self.assertEqual(set(a) - set(b), {"Newcomer"})
        for n in b:
            self.assertEqual(a[n], b[n], n)                                               # existing endpoints untouched
        self.assertEqual(a["Newcomer"]["status"], "stub")
        self.assertEqual(after["relationships"][:len(before["relationships"])], before["relationships"])
        self.assert_events_appended_only(before, after, {"Cat"}, 1)

    def test_language_layer_is_isolated_from_knowledge_mutation_and_back(self):
        before = self.snap()
        self.core.language_learning.learn_item("english", "word", "canine", meaning="dog-like", source="user")
        after = self.snap()
        self.assertEqual(after["knowledge"], before["knowledge"])
        self.assertEqual(after["relationships"], before["relationships"])
        self.assertEqual(after["language_item_relationships"], before["language_item_relationships"])
        self.assertEqual(after["language_learning_items"][:len(before["language_learning_items"])],
                         before["language_learning_items"])
        mid = self.snap()
        self.ls.teach("Dog", "man's best friend", source="user")
        end = self.snap()
        self.assertEqual(end["language_learning_items"], mid["language_learning_items"])
        self.assertEqual(end["language_item_relationships"], mid["language_item_relationships"])

    def test_core_open_touches_only_the_unrelated_capabilities_table(self):
        before = self.snap()
        self.reopen()
        self.assertEqual(self.snap(), before)


if __name__ == "__main__":
    unittest.main()
