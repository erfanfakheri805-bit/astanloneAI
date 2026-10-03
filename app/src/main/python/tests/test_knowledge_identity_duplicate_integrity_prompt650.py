"""Prompt 650 - Section 3: knowledge identity / duplicate-prevention audit.

AUDIT, not a redesign of concept matching. Finding: no genuine identity defect;
NO production change. Existing identity contract (asserted below):

  I1 WRITE identity is the EXACT, case-sensitive, byte-for-byte name.
     KnowledgeSystem.learn()/LearningSystem.teach()/relate() never fold case or
     whitespace: "Python", "python", " Python " are three distinct records
     (blank/non-string names are rejected). Exact repeats are no-ops.
  I2 RESOLUTION (correct(), resolve_name(), find_by_name_case_insensitive()):
     exact match wins; else exactly one case-insensitive match; several ->
     "ambiguous" (correct() raises ValueError, writes nothing; finders return
     None). Whitespace variants are NOT matched ("not_found").
  I3 Relationship endpoints are exact names: an existing exact endpoint is reused
     (no stub); a missing one - including a case/whitespace variant of an
     existing record - gets a stub (status "stub", source=source_type or
     "inferred"). This is intentional (see find_by_name_case_insensitive docs).
  I4 A stub is upgraded in place by teach()/learn() of the same exact name (same
     row id, version+1, status "active"); relationships stay attached; source is
     replaced per P2, the stub's source_text/learning_method/confidence are kept.
  I5 Natural-language learning strips surrounding whitespace, then resolves exact
     first, then a UNIQUE case-insensitive match, so it reuses the existing
     canonical name. Repeats are no-ops.
Documented limitation (intentional, unchanged): when a NL candidate is ambiguous
case-insensitively AND is not itself an exact name (e.g. "PYTHON" vs stored
"Python" + "python"), nothing is chosen and it becomes its own new (stub) identity,
exactly as learn("PYTHON") would.
"""
import os
import tempfile
import unittest

from core.core import Core
from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "m.db")
        self._open()

    def _open(self):
        self.m = MemorySystem(self.db)
        self.k = KnowledgeSystem(self.m)
        self.ls = LearningSystem(ConceptSystem(self.k), self.k, memory=self.m)

    def tearDown(self):
        self.m._conn.close()
        self.tmp.cleanup()

    def reopen(self):
        self.m._conn.close()
        self._open()

    def names(self):
        return [r["name"] for r in self.m.query("SELECT name FROM knowledge ORDER BY id")]

    def rows(self, t):
        return self.m.query(f"SELECT * FROM {t} ORDER BY id")

    def events(self, *types):
        return [e for e in self.rows("learning_events") if not types or e["event_type"] in types]


class ExactAndCaseIdentity(Base):
    def test_exact_repeat_is_noop_no_duplicate_no_event(self):
        self.ls.teach("Python", "a snake", source="user")
        before, n = self.rows("knowledge"), len(self.events())
        self.ls.teach("Python", "a snake", source="user")
        self.k.learn("Python", "a snake", source="user")
        self.assertEqual(self.rows("knowledge"), before)
        self.assertEqual(len(self.events()), n)

    def test_case_and_whitespace_variants_are_distinct_identities_on_write(self):
        for n in ("Python", "python", "PYTHON", " Python ", "Python\t"):
            self.ls.teach(n, f"d:{n!r}")
        self.assertEqual(self.names(), ["Python", "python", "PYTHON", " Python ", "Python\t"])
        self.assertEqual({r["version"] for r in self.rows("knowledge")}, {1})
        self.assertEqual(len(self.events("teach")), 5)
        self.assertEqual(self.k.get("python")["description"], "d:'python'")

    def test_blank_and_non_string_names_rejected_nothing_written(self):
        for bad in ("", "   ", None, 5):
            with self.assertRaises(ValueError):
                self.k.learn(bad, "d")
        self.assertEqual(self.rows("knowledge"), [])

    def test_existing_versus_new_concept(self):
        self.ls.teach("Python", "a snake")
        self.ls.teach("Python", "a language")                 # existing -> update
        self.ls.teach("Ruby", "a gem")                         # new -> new row
        self.assertEqual(self.names(), ["Python", "Ruby"])
        self.assertEqual([r["version"] for r in self.rows("knowledge")], [2, 1])


class Resolution(Base):
    def test_exact_wins_over_case_insensitive(self):
        self.ls.teach("Python", "a"); self.ls.teach("python", "b")
        res = self.k.resolve_name("python")
        self.assertEqual((res["status"], res["record"]["name"]), ("exact", "python"))

    def test_single_case_insensitive_match_and_whitespace_not_matched(self):
        self.ls.teach("Python", "a")
        self.assertEqual(self.k.resolve_name("PYTHON")["status"], "case_insensitive")
        self.assertEqual(self.k.find_by_name_case_insensitive("pYTHON")["name"], "Python")
        for ws in (" Python", "Python ", "Py thon"):
            self.assertEqual(self.k.resolve_name(ws)["status"], "not_found")
            self.assertIsNone(self.k.find_by_name_case_insensitive(ws))

    def test_ambiguous_never_chosen_and_candidates_deterministic(self):
        self.ls.teach("Python", "a"); self.ls.teach("python", "b")
        res = self.k.resolve_name("PYTHON")
        self.assertEqual((res["status"], res["record"], sorted(res["candidates"])),
                         ("ambiguous", None, ["Python", "python"]))
        self.assertIsNone(self.k.find_by_name_case_insensitive("PYTHON"))
        self.assertEqual(self.k.resolve_name("PYTHON"), res)

    def test_resolution_reads_do_not_write(self):
        self.ls.teach("Python", "a")
        before = self.rows("knowledge"), self.rows("learning_events")
        self.k.resolve_name("PYTHON"); self.k.find_by_name_case_insensitive("python")
        self.k.get("python"); self.k.search("py")
        self.assertEqual((self.rows("knowledge"), self.rows("learning_events")), before)


class Correction(Base):
    def test_case_insensitive_correction_updates_existing_record(self):
        self.ls.teach("Python", "a snake", source="user", confidence=0.6)
        row_id = self.k.get("Python")["id"]
        r = self.ls.correct("pYTHON", "a language")
        self.assertEqual((r["name"], r["id"], r["version"], r["description"]),
                         ("Python", row_id, 2, "a language"))
        self.assertEqual(self.names(), ["Python"])                      # no competing record
        self.assertEqual(self.k.get("Python")["confidence"], 0.6)
        ev = self.events("correct")
        self.assertEqual([(e["target"], e["detail"]) for e in ev], [("Python", "'a snake' -> 'a language'")])

    def test_exact_name_wins_correction_target(self):
        self.ls.teach("Python", "a"); self.ls.teach("python", "b")
        self.ls.correct("python", "B2")
        self.assertEqual((self.k.get("Python")["description"], self.k.get("python")["description"]), ("a", "B2"))
        self.assertEqual(self.k.get("Python")["version"], 1)

    def test_ambiguous_correction_raises_and_writes_nothing(self):
        self.ls.teach("Python", "a"); self.ls.teach("python", "b")
        before, ev = self.rows("knowledge"), self.rows("learning_events")
        with self.assertRaises(ValueError):
            self.ls.correct("PYTHON", "x")
        with self.assertRaises(ValueError):
            self.k.correct("PYTHON", "x")
        self.assertEqual((self.rows("knowledge"), self.rows("learning_events")), (before, ev))

    def test_unknown_and_whitespace_variant_correction_creates_nothing(self):
        self.ls.teach("Python", "a")
        before, ev = self.rows("knowledge"), self.rows("learning_events")
        self.assertIsNone(self.ls.correct("Ruby", "x"))
        self.assertIsNone(self.ls.correct(" Python", "x"))
        self.assertEqual((self.rows("knowledge"), self.rows("learning_events")), (before, ev))

    def test_identical_correction_noop(self):
        self.ls.teach("Python", "a")
        self.ls.correct("PYTHON", "b")
        before, n = self.rows("knowledge"), len(self.events())
        self.ls.correct("python", "b")
        self.assertEqual(self.rows("knowledge"), before)
        self.assertEqual(len(self.events()), n)


class RelationshipEndpointsAndStubs(Base):
    def test_existing_endpoints_reused_no_stubs(self):
        self.ls.teach("Python", "a language"); self.ls.teach("Language", "x")
        self.ls.relate("Python", "Language", "is_a", source="user")
        self.assertEqual(self.names(), ["Python", "Language"])
        self.assertEqual([r["version"] for r in self.rows("knowledge")], [1, 1])
        self.assertEqual({r["status"] for r in self.rows("knowledge")}, {"active"})

    def test_missing_endpoint_gets_stub_and_variant_endpoint_is_separate_stub(self):
        self.ls.teach("Python", "a language")
        self.ls.relate("python", "Language", "is_a", source="user", source_text="t", learning_method="lm")
        rows = {r["name"]: r for r in self.rows("knowledge")}
        self.assertEqual(sorted(rows), ["Language", "Python", "python"])   # I3: intentional
        self.assertEqual((rows["python"]["status"], rows["Language"]["status"], rows["Python"]["status"]),
                         ("stub", "stub", "active"))
        self.assertEqual(rows["Python"]["version"], 1)                    # existing record untouched
        rel = self.rows("relationships")
        self.assertEqual([(r["from_name"], r["to_name"]) for r in rel], [("python", "Language")])

    def test_stub_without_source_type_is_inferred(self):
        self.k.relate("a", "b", "is_a")
        self.assertEqual([(r["name"], r["source"], r["status"]) for r in self.rows("knowledge")],
                         [("a", "inferred", "stub"), ("b", "inferred", "stub")])

    def test_repeat_relate_never_duplicates_edges_or_stubs(self):
        for _ in range(3):
            self.ls.relate("a", "b", "is_a", source="user")
        self.assertEqual(len(self.rows("relationships")), 1)
        self.assertEqual(self.names(), ["a", "b"])
        self.assertEqual(len(self.events("relate")), 1)

    def test_stub_to_taught_lifecycle_upgrades_same_identity(self):
        self.ls.relate("Python", "Language", "is_a", source="user", confidence=0.7,
                       source_text="Python is a language.", learning_method="lm")
        stub = self.k.get("Python")
        rel_before = self.rows("relationships")
        self.assertEqual((stub["status"], stub["version"], stub["description"]), ("stub", 1, None))
        taught = self.ls.teach("Python", "a programming language")
        self.assertEqual(taught["id"], stub["id"])                          # same identity
        self.assertEqual((taught["status"], taught["version"], taught["description"]),
                         ("active", 2, "a programming language"))
        self.assertEqual(self.names(), ["Python", "Language"])              # not duplicated
        self.assertEqual(self.rows("relationships"), rel_before)             # edges untouched
        # provenance: source replaced by teach()'s default; stub's source_text/method/confidence kept
        self.assertEqual((taught["source"], taught["source_text"], taught["learning_method"], taught["confidence"]),
                         ("ael", "Python is a language.", "lm", stub["confidence"]))
        self.assertEqual(self.k.relationships_for("Python")["outgoing"][0]["to_name"], "Language")
        self.assertEqual([(e["event_type"], e["target"]) for e in self.events()],
                         [("relate", "Python"), ("teach", "Python")])
        self.assertEqual(self.events("teach")[0]["source"], taught["source"])

    def test_stub_upgraded_by_correction_too(self):
        self.ls.relate("Python", "Language", "is_a", source="user")
        r = self.ls.correct("python", "a language")                         # single CI match: the stub
        self.assertEqual((r["name"], r["status"], r["version"]), ("Python", "active", 2))
        self.assertEqual(self.names(), ["Python", "Language"])
        self.assertEqual(self.events("correct")[0]["detail"], "None -> 'a language'")

    def test_repeat_teach_after_upgrade_is_noop(self):
        self.ls.relate("Python", "Language", "is_a", source="user")
        self.ls.teach("Python", "x"); before, n = self.rows("knowledge"), len(self.events())
        self.ls.teach("Python", "x")
        self.assertEqual(self.rows("knowledge"), before)
        self.assertEqual(len(self.events()), n)


class NaturalLanguage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "c.db")
        self.core = self._core()

    def _core(self):
        return Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))

    def names(self):
        return [r["name"] for r in self.core.memory.query("SELECT name FROM knowledge ORDER BY id")]

    def snap(self):
        return {t: self.core.memory.query(f"SELECT * FROM {t} ORDER BY id")
                for t in ("knowledge", "relationships", "learning_events")}

    def test_nl_reuses_existing_concept_case_insensitively(self):
        self.core.learning.teach("Python", "a snake", source="user")
        for text in ("python is a language.", "PYTHON is a language.", "  Python is a language."):
            r = self.core.learn_from_text(text)
            self.assertTrue(r.success, text)
            self.assertEqual(r.learned_items[0]["subject"], "Python")
            self.assertNotIn("Python", r.created_concepts)
        self.assertEqual(self.names(), ["Python", "language"])
        self.assertEqual(len(self.snap()["relationships"]), 1)
        k = self.core.knowledge.get("Python")
        self.assertEqual((k["status"], k["version"], k["description"]), ("active", 1, "a snake"))

    def test_repeated_nl_learning_is_noop(self):
        self.core.learn_from_text("Python is a language.")
        before = self.snap()
        for _ in range(3):
            self.core.learn_from_text("Python is a language.")
        self.assertEqual(self.snap(), before)
        self.assertEqual(len(before["learning_events"]), 1)

    def test_nl_stub_then_taught_then_nl_again_same_identity(self):
        self.core.learn_from_text("Python is a language.")
        stub_id = self.core.knowledge.get("Python")["id"]
        self.core.learning.teach("Python", "a programming language")
        self.core.learn_from_text("python is a language.")
        k = self.core.knowledge.get("Python")
        self.assertEqual((k["id"], k["status"], k["version"]), (stub_id, "active", 2))
        self.assertEqual(self.names(), ["Python", "language"])
        self.assertEqual(len(self.snap()["relationships"]), 1)

    def test_nl_ambiguous_candidate_not_chosen_becomes_own_identity_documented(self):
        self.core.learning.teach("Python", "a"); self.core.learning.teach("python", "b")
        before = self.snap()["knowledge"]
        r = self.core.learn_from_text("PYTHON is a language.")
        self.assertEqual(r.created_concepts.count("PYTHON"), 1)
        after = self.snap()["knowledge"]
        self.assertEqual(after[:2], before)                                  # neither variant touched
        self.assertEqual([x["name"] for x in after], ["Python", "python", "PYTHON", "language"])
        # an exact candidate among ambiguous variants still resolves exactly
        r = self.core.learn_from_text("python is a language.")
        self.assertEqual(r.learned_items[0]["subject"], "python")
        self.assertEqual(len(self.snap()["knowledge"]), 4)

    def test_correction_of_existing_concept_via_conversation_keeps_identity(self):
        self.core.learning.teach("Python", "a snake", confidence=0.6, source_text="Python is a snake.",
                                 learning_method="ael")
        self.core.process_input("not a snake, I mean a programming language.")
        self.assertEqual(self.names(), ["Python"])
        k = self.core.knowledge.get("Python")
        self.assertEqual((k["version"], k["description"], k["source"]), (2, "a programming language",
                                                                       "user_correction"))
        self.assertEqual([e["event_type"] for e in self.snap()["learning_events"]
                          if e["event_type"] in ("teach", "correct")], ["teach", "correct"])

    def test_reopen_preserves_identity_and_no_duplicates_appear(self):
        self.core.learning.teach("Python", "a snake")
        self.core.learn_from_text("Ruby is a language.")
        before = self.snap()
        self.core.memory._conn.close()
        self.core = self._core()
        self.assertEqual(self.snap(), before)
        self.core.learn_from_text("Ruby is a language.")
        self.core.learning.teach("Python", "a snake")
        self.assertEqual(self.snap(), before)
        # a case variant in NL text resolves to the persisted identity: no new rows/ids. (Its
        # different source_text is a real provenance change, so the same edge is refreshed.)
        self.core.learn_from_text("ruby is a language.")
        after = self.snap()
        self.assertEqual([r["id"] for r in after["knowledge"]], [r["id"] for r in before["knowledge"]])
        self.assertEqual([r["id"] for r in after["relationships"]], [r["id"] for r in before["relationships"]])
        self.assertEqual(self.names(), ["Python", "Ruby", "language"])


class Persistence(Base):
    def test_reopen_identity_resolution_and_row_counts(self):
        self.ls.teach("Python", "a"); self.ls.teach("python", "b")
        self.ls.relate("Ruby", "Language", "is_a", source="user")
        before = (self.rows("knowledge"), self.rows("relationships"), self.rows("learning_events"))
        self.reopen()
        self.assertEqual((self.rows("knowledge"), self.rows("relationships"), self.rows("learning_events")), before)
        self.assertEqual(self.k.resolve_name("PYTHON")["status"], "ambiguous")
        self.assertEqual(self.k.resolve_name("ruby")["status"], "case_insensitive")
        self.ls.teach("Ruby", "a gem")                                       # upgrade the persisted stub
        self.assertEqual(self.names(), ["Python", "python", "Ruby", "Language"])
        self.assertEqual(len(self.rows("relationships")), 1)

    def test_events_correspond_to_actual_mutations(self):
        self.ls.teach("Python", "a", source="user")
        self.ls.teach("Python", "a", source="user")            # no-op
        self.ls.teach("python", "b", source="user")             # distinct identity -> event
        self.ls.correct("Python", "a2")                          # exact -> event
        self.ls.correct("Python", "a2")                          # no-op
        self.ls.relate("Python", "X", "is_a", source="user")
        self.ls.relate("Python", "X", "is_a", source="user")    # no-op
        got = [(e["event_type"], e["target"]) for e in self.events()]
        self.assertEqual(got, [("teach", "Python"), ("teach", "python"), ("correct", "Python"),
                               ("relate", "Python")])
        for e in self.events("teach", "correct"):
            self.assertIsNotNone(self.k.get(e["target"]))


if __name__ == "__main__":
    unittest.main()
