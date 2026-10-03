"""Prompt 653 - Section 3: current relationship consistency across knowledge lifecycle changes.

AUDIT, not a redesign. Relationships reference endpoints by exact knowledge NAME (identity), never by
description/source/confidence/status, so lifecycle changes of an endpoint never redirect or duplicate an edge.
Every test pins EXISTING semantics; nothing here required a production change.

  R1  stub -> teach -> correct -> re-teach keeps the SAME relationship row (id/created_at/version/metadata).
  R2  Changing description/source/confidence/status of an endpoint never duplicates or redirects an edge.
  R3  Relationship reads (relationships_for / recall / language relationships_for) expose the CURRENT endpoint
      record; learning_events keep history and are not current state.
  R4  relate() repeats: created True only for a new row; identical repeat = true no-op (no write, no event);
      metadata change = row refresh + one event, created False.
  R5  Failed mutations (event insert failing, invalid/ambiguous endpoints) are fully atomic.
  R6  Case-sensitive writes: relate("python", ...) never resolves to "Python"; NL learning resolves
      deterministically and ambiguity mutates nothing.
  R7  Cross-source (NL / teach / correct / relate / language store) never creates duplicate relationship rows.
  R8  Language relationships to a concept endpoint survive knowledge lifecycle and keep their own
      repeat/update contract (created False + version bump on restatement).
"""
import os
import tempfile
import unittest
from unittest import mock

from core.core import Core
from language_intelligence.language_relationships import concept_ref, item_ref


class Boom(RuntimeError):
    pass


EDGE_COLS = ("id", "from_name", "to_name", "relation_type", "created_at", "updated_at", "confidence",
             "source_type", "source_text", "learning_method")


class RelLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "r.db")
        self._open()

    def _open(self):
        self.core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m = self.core.knowledge, self.core.learning, self.core.memory

    def reopen(self):
        self.m._conn.close()
        self._open()

    def edges(self):
        return [{c: r[c] for c in EDGE_COLS} for r in self.m.query("SELECT * FROM relationships ORDER BY id")]

    def snap(self):
        return {t: [dict(r) for r in self.m.query(f"SELECT * FROM {t} ORDER BY id")]
                for t in ("knowledge", "relationships", "learning_events",
                          "language_learning_items", "language_item_relationships")}

    def events(self, *types):
        return [e for e in self.m.query("SELECT * FROM learning_events ORDER BY id")
                if not types or e["event_type"] in types]

    # ---- R1: identity survives stub -> taught -> corrected --------------------------------
    def test_edge_survives_stub_teach_correct_reteach(self):
        self.assertTrue(self.ls.relate("Cat", "Animal", "is_a", confidence=0.7,
                                       source_text="cats are animals")["created"])
        e0 = self.edges()
        self.assertEqual(len(e0), 1)
        self.assertEqual(self.k.get("Cat")["status"], "stub")
        self.assertEqual(self.k.get("Animal")["status"], "stub")

        self.ls.teach("Cat", "a small feline", source="user", confidence=0.9)      # stub -> taught
        self.assertEqual(self.k.get("Cat")["status"], "active")
        self.ls.correct("CAT", "a small domestic feline", source="user_correction")   # ci correct
        self.ls.teach("Animal", "a living being")                                     # other endpoint
        self.ls.correct("animal", "a living organism")
        self.ls.teach("Cat", "a small domestic feline", source="ael")                # re-teach

        self.assertEqual(self.edges(), e0)                                 # same row, byte-identical
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge")), 2)   # no stub duplicates
        cat = self.k.get("Cat")
        self.assertEqual(cat["version"], 4)   # stub v1, teach, correct, re-teach (source ael) = 3 real changes
        self.assertEqual(cat["description"], "a small domestic feline")
        self.assertEqual(self.k.get("Animal")["description"], "a living organism")

    def test_reads_show_current_endpoint_not_history(self):
        self.ls.relate("Cat", "Animal", "is_a")
        self.ls.teach("Cat", "old text")
        self.ls.correct("Cat", "new text")
        rec = self.ls.recall("Cat")
        self.assertEqual(rec["description"], "new text")
        self.assertEqual([r["to_name"] for r in rec["relationships"]["outgoing"]], ["Animal"])
        inc = self.ls.recall("Animal")["relationships"]["incoming"]
        self.assertEqual([r["from_name"] for r in inc], ["Cat"])
        self.assertEqual(self.k.relationships_for("Cat")["outgoing"], rec["relationships"]["outgoing"])
        # history retains old values; current readers never do
        detail = [e["detail"] for e in self.events("teach", "correct")]
        self.assertIn("old text", detail[0])
        self.assertIn("'old text' -> 'new text'", detail[1])
        self.assertEqual(self.k.get("Cat")["description"], "new text")

    def test_metadata_status_confidence_changes_never_touch_edges(self):
        self.ls.relate("A", "B", "likes", confidence=0.5, source="user", source_text="s")
        e0 = self.edges()
        self.k.learn("A", "d", kind="concept", source="x", status="deprecated", confidence=0.1)
        self.k.learn("B", "d2", kind="concept", source="y", status="active", confidence=0.2)
        self.assertEqual(self.edges(), e0)
        self.assertEqual(len(self.k.all()), 2)

    # ---- R4: relate() repeat/update/no-op contract ----------------------------------------
    def test_relate_created_contract_and_noop_across_lifecycle(self):
        self.assertIs(self.k.relate("A", "B", "r", confidence=0.4, source_type="user"), True)
        self.k.learn("A", "desc")                                # endpoint lifecycle change in between
        before = self.snap()
        self.assertIs(self.k.relate("A", "B", "r"), False)                   # None args: no-op
        self.assertIs(self.k.relate("A", "B", "r", confidence=0.4), False)   # same effective value: no-op
        self.assertEqual(self.snap(), before)

        self.assertIs(self.k.relate("A", "B", "r", confidence=0.8), False)   # real change: refresh, not created
        e = self.edges()
        self.assertEqual(len(e), 1)
        self.assertEqual((e[0]["confidence"], e[0]["source_type"]), (0.8, "user"))
        self.assertEqual(e[0]["created_at"], before["relationships"][0]["created_at"])
        self.assertGreater(e[0]["updated_at"], before["relationships"][0]["updated_at"])

    def test_learning_layer_events_follow_actual_state(self):
        self.assertTrue(self.ls.relate("A", "B", "r", confidence=0.4)["created"])
        self.ls.teach("A", "x")
        self.assertEqual(len(self.events("relate")), 1)
        self.assertFalse(self.ls.relate("A", "B", "r")["created"])                 # no-op: no event
        self.assertFalse(self.ls.relate("A", "B", "r", confidence=0.4)["created"])  # no-op: no event
        self.assertEqual(len(self.events("relate")), 1)
        self.assertFalse(self.ls.relate("A", "B", "r", confidence=0.9)["created"])  # real refresh: one event
        self.assertEqual(len(self.events("relate")), 2)
        self.assertEqual(len(self.edges()), 1)
        self.assertEqual(self.events("relate")[-1]["source"], "ael")

    # ---- R5: atomicity ----------------------------------------------------------------------
    def test_failed_relate_is_atomic_for_new_and_existing_edges(self):
        self.ls.relate("A", "B", "r", confidence=0.4)
        self.ls.teach("A", "desc")
        before = self.snap()
        with mock.patch.object(type(self.m), "add_learning_event", side_effect=Boom("e")):
            with self.assertRaises(Boom):
                self.ls.relate("A", "B", "r", confidence=0.9)        # refresh fails
            with self.assertRaises(Boom):
                self.ls.relate("A", "NewStub", "r")                   # create + stub fails
            with self.assertRaises(Boom):
                self.ls.teach("B", "desc-b")                          # endpoint upgrade fails
            with self.assertRaises(Boom):
                self.ls.correct("A", "changed")
        self.assertEqual(self.snap(), before)
        self.reopen()
        self.assertEqual(self.snap(), before)

    def test_invalid_endpoints_mutate_nothing(self):
        self.ls.relate("A", "B", "r")
        before = self.snap()
        for args in (("", "B", "r"), ("A", "  ", "r"), (None, "B", "r"), ("A", 3, "r"), ("A", "B", None)):
            with self.assertRaises(ValueError):
                self.ls.relate(*args)
            with self.assertRaises(ValueError):
                self.k.relate(*args)
        self.assertEqual(self.snap(), before)

    # ---- R6: case identity / ambiguity --------------------------------------------------------
    def test_case_variants_are_distinct_identities_for_relate(self):
        self.ls.relate("Python", "Language", "is_a")
        self.assertTrue(self.ls.relate("python", "Language", "is_a")["created"])   # documented: exact names
        self.assertEqual(len(self.edges()), 2)
        self.assertEqual({r["name"] for r in self.k.all()}, {"Python", "python", "Language"})
        # correct() on an ambiguous name raises and mutates nothing (edges included)
        before = self.snap()
        with self.assertRaises(ValueError):
            self.ls.correct("PYTHON", "x")
        self.assertEqual(self.snap(), before)
        # exact correct hits only its own record; the other edge is untouched
        self.ls.correct("python", "lowercase python")
        self.assertIsNone(self.k.get("Python")["description"])
        self.assertEqual(self.k.get("python")["description"], "lowercase python")
        self.assertEqual(self.edges(), [{c: r[c] for c in EDGE_COLS} for r in before["relationships"]])

    def test_nl_learning_reuses_case_insensitive_unique_endpoint_without_duplicates(self):
        self.ls.teach("Python", "a language")
        self.core.learn_from_text("Python is a language.")
        n1 = len(self.edges())
        self.core.learn_from_text("python is a language.")      # same identity via unique ci match
        self.core.learn_from_text("Python is a language.")
        self.assertEqual(len(self.edges()), n1)
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='python'")), 1)
        self.assertEqual(self.k.get("Python")["description"], "a language")   # NL never rewrites the record

    def test_nl_ambiguous_endpoint_mutates_no_edge(self):
        self.ls.teach("Python", "a")
        self.ls.teach("python", "b")
        before = self.snap()
        self.assertEqual(self.k.resolve_name("PYTHON")["status"], "ambiguous")
        self.core.learn_from_text("PYTHON is a language.")
        after = self.snap()
        # Existing semantics: an ambiguous name is never silently redirected to Python/python; the exact
        # written name becomes its own new identity. Existing records/edges are untouched.
        self.assertEqual(after["knowledge"][:2], before["knowledge"])
        self.assertEqual({r["from_name"] for r in after["relationships"]}, {"PYTHON"})
        self.assertEqual(self.k.relationships_for("Python"), {"outgoing": [], "incoming": []})
        self.assertEqual(self.k.relationships_for("python"), {"outgoing": [], "incoming": []})

    # ---- R7: cross-source, no duplicate rows ---------------------------------------------------
    def test_cross_source_updates_never_duplicate_relationship_rows(self):
        self.core.learn_from_text("Python is a language.")
        edges0 = self.edges()
        self.assertEqual(len(edges0), 1)
        self.ls.teach("Python", "a snake", source="user", confidence=0.6)
        self.core.process_input("not a snake, I mean a programming language.")
        self.ls.teach("Python", "a programming language")
        self.ls.teach("language", "a system of communication")
        self.core.learn_from_text("python is a language.")
        self.core.learn_from_text("Python is a language.")
        ident = lambda es: [(x["id"], x["from_name"], x["to_name"], x["relation_type"], x["created_at"]) for x in es]
        self.assertEqual(ident(self.edges()), ident(edges0))    # same row; NL restatements with a new
        self.assertEqual(len(self.edges()), 1)                   # source_text only refresh metadata (contract)
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge")), 2)
        e = edges0[0]
        self.assertEqual(self.k.relationships_for("Python")["outgoing"][0]["id"], e["id"])
        self.assertEqual(self.k.relationships_for("language")["incoming"][0]["id"], e["id"])

    # ---- R8: language relationships with concept endpoints --------------------------------------
    def test_language_relationship_to_concept_survives_knowledge_lifecycle(self):
        self.ls.relate("Cat", "Animal", "is_a")           # creates concept stubs
        item = self.core.language_learning.learn_item("english", "word", "feline", meaning="cat-like")
        r1 = self.core.relate_language_items(item_ref("english", "word", "feline"), concept_ref("Cat"),
                                             "concept_to_expression", metadata={"n": 1})
        self.assertTrue(r1["created"])
        self.ls.teach("Cat", "a small feline")            # stub -> taught
        self.ls.correct("Cat", "a domestic feline")
        r2 = self.core.relate_language_items(item_ref("english", "word", "feline"), concept_ref("Cat"),
                                             "concept_to_expression", metadata={"n": 1})
        self.assertFalse(r2["created"])                   # created contract: restatement is not creation
        self.assertEqual(r2["id"], r1["id"])
        self.assertEqual(r2["version"], r1["version"] + 1)   # documented intentional repeat/update semantics
        self.assertEqual(r2["created_at"], r1["created_at"])
        self.assertEqual(len(self.m.query("SELECT * FROM language_item_relationships")), 1)
        rels = self.core.language_relationships.relationships_for(concept_ref("Cat"))
        self.assertEqual([r["id"] for r in rels], [r1["id"]])
        self.assertEqual(self.k.get("Cat")["description"], "a domestic feline")
        self.assertEqual(len(self.edges()), 1)            # the knowledge edge is untouched by the language store

    def test_language_relationship_metadata_and_failure_atomicity(self):
        self.ls.teach("Cat", "c")
        self.core.language_learning.learn_item("english", "word", "feline")
        ref_i, ref_c = item_ref("english", "word", "feline"), concept_ref("Cat")
        r1 = self.core.relate_language_items(ref_i, ref_c, "concept_to_expression", metadata={"a": 1})
        self.ls.correct("Cat", "c2")
        r2 = self.core.relate_language_items(ref_i, ref_c, "concept_to_expression")     # None metadata: keep
        self.assertEqual(r2["metadata"], {"a": 1})
        r3 = self.core.relate_language_items(ref_i, ref_c, "concept_to_expression", metadata={"a": 2})
        self.assertEqual(r3["metadata"], {"a": 2})
        self.assertEqual((r3["id"], r3["version"]), (r1["id"], r1["version"] + 2))
        before = self.snap()
        with mock.patch.object(type(self.m), "add_learning_event", side_effect=Boom("e")):
            with self.assertRaises(Boom):
                self.core.relate_language_items(ref_i, ref_c, "concept_to_expression", metadata={"a": 3})
        self.assertEqual(self.snap(), before)
        for bad in (concept_ref("Missing"), concept_ref("cat"), item_ref("english", "word", "nope")):
            with self.assertRaises(ValueError):
                self.core.relate_language_items(ref_i, bad, "concept_to_expression")
        self.assertEqual(self.snap(), before)                # no auto-created endpoint, no mutation

    def test_language_store_never_changes_knowledge_records_or_edges(self):
        self.ls.relate("Cat", "Animal", "is_a")
        self.ls.teach("Cat", "c")
        self.core.language_learning.learn_item("english", "word", "feline")
        before = self.snap()
        self.core.relate_language_items(item_ref("english", "word", "feline"), concept_ref("Cat"),
                                        "concept_to_expression")
        after = self.snap()
        self.assertEqual(after["knowledge"], before["knowledge"])
        self.assertEqual(after["relationships"], before["relationships"])


if __name__ == "__main__":
    unittest.main()
