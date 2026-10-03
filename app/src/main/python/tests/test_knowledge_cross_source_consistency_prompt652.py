"""Prompt 652 - Section 3: current-knowledge consistency across learning/correction sources.

AUDIT, not a redesign. Finding: no genuine defect; NO production change. Verified
(existing semantics, nothing normalized):

  C1 One logical record per exact name survives every cross-source sequence
     (NL relate-stub -> teach -> conversational correction -> re-teach -> NL again):
     id/name/created_at never change; version is +1 per real change; updated_at
     moves only on real change.
  C2 Field ownership per source (None-preserving fields keep the older value):
       NL (relate stub)   source "understanding_engine", method "natural_language_understanding"
       teach()            replaces source (default "ael"); keeps older source_text/method/confidence
       correct()          keeps source unless given (Core passes "user_correction" +
                          method "explicit_correction" + the correction sentence as source_text)
       NL on an EXISTING record only touches the relationship row, never the record.
  C3 Current readers (get/all/search/resolve_name/relationships_for/get_with_relations)
     always reflect the latest persisted row. learning_events keep HISTORICAL values
     (e.g. a teach event's detail is the old description) and are never current state.
  C4 Failure at any point (event insert failing) leaves knowledge, relationships and
     events unchanged; natural-language learning reports it in result.errors.
  C5 Language-store items (separate tables) never alter knowledge records.
"""
import os
import tempfile
import unittest
from unittest import mock

from core.core import Core
from language_intelligence.language_learning_store import LanguageLearningStore

REC = ("id", "name", "version", "status", "description", "source", "confidence",
       "source_text", "learning_method", "created_at", "updated_at")


class CrossSource(unittest.TestCase):
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

    def rec(self, name):
        r = self.k.get(name)
        return {c: r[c] for c in REC} if r else None

    def rows(self, name):
        return self.m.query("SELECT * FROM knowledge WHERE LOWER(name)=LOWER(?) ORDER BY id", (name,))

    def snap(self):
        return {t: self.m.query(f"SELECT * FROM {t} ORDER BY id")
                for t in ("knowledge", "relationships", "learning_events",
                          "language_learning_items", "language_item_relationships")}

    def events(self, *types):
        return [e for e in self.m.query("SELECT * FROM learning_events ORDER BY id")
                if not types or e["event_type"] in types]

    def lifecycle(self):
        """NL stub -> teach -> conversational correction -> re-teach -> NL again; returns records per step."""
        steps = {}
        self.core.learn_from_text("Python is a language.")
        steps["nl"] = self.rec("Python")
        self.ls.teach("Python", "a snake", source="user", confidence=0.6)
        steps["teach"] = self.rec("Python")
        self.core.process_input("not a snake, I mean a programming language.")
        steps["correct"] = self.rec("Python")
        self.ls.teach("Python", "a programming language")
        steps["reteach"] = self.rec("Python")
        self.core.learn_from_text("python is a language.")
        steps["nl2"] = self.rec("Python")
        return steps

    # ---- C1/C2/3: identity, versions, provenance across sources ----------------
    def test_full_sequence_state_per_step(self):
        s = self.lifecycle()
        # NL-created stub
        self.assertEqual((s["nl"]["version"], s["nl"]["status"], s["nl"]["description"], s["nl"]["source"],
                          s["nl"]["learning_method"], s["nl"]["source_text"], s["nl"]["confidence"]),
                         (1, "stub", None, "understanding_engine", "natural_language_understanding",
                          "Python is a language.", 1.0))
        # teach upgrades the same identity: source replaced, stub source_text/method kept, confidence given
        self.assertEqual((s["teach"]["id"], s["teach"]["created_at"], s["teach"]["version"], s["teach"]["status"],
                          s["teach"]["description"], s["teach"]["source"], s["teach"]["confidence"],
                          s["teach"]["source_text"], s["teach"]["learning_method"]),
                         (s["nl"]["id"], s["nl"]["created_at"], 2, "active", "a snake", "user", 0.6,
                          "Python is a language.", "natural_language_understanding"))
        # conversational correction (Core -> LearningSystem.correct)
        self.assertEqual((s["correct"]["version"], s["correct"]["description"], s["correct"]["source"],
                          s["correct"]["learning_method"], s["correct"]["source_text"], s["correct"]["confidence"]),
                         (3, "a programming language", "user_correction", "explicit_correction",
                          "not a snake, I mean a programming language.", 0.6))
        # re-teach with default source: source follows teach's default, rest preserved
        self.assertEqual((s["reteach"]["version"], s["reteach"]["source"], s["reteach"]["source_text"],
                          s["reteach"]["learning_method"], s["reteach"]["confidence"]),
                         (4, "ael", "not a snake, I mean a programming language.", "explicit_correction", 0.6))
        # NL on an existing record (case variant) never touches the record
        self.assertEqual(s["nl2"], s["reteach"])
        for a, b in zip(list(s.values())[:-1], list(s.values())[1:]):
            self.assertEqual((a["id"], a["name"], a["created_at"]), (b["id"], b["name"], b["created_at"]))
            self.assertLessEqual(a["updated_at"], b["updated_at"])
        ups = [s[k]["updated_at"] for k in ("nl", "teach", "correct", "reteach")]
        self.assertEqual(ups, sorted(set(ups)))                      # strictly increasing on real changes
        self.assertEqual(len(self.rows("python")), 1)                # no duplicate current record

    def test_repeated_cross_source_ops_follow_each_apis_noop_rules(self):
        s = self.lifecycle()
        before = self.snap()
        self.ls.teach("Python", "a programming language")            # same source as stored (ael): no-op
        self.ls.correct("PYTHON", "a programming language")           # source None keeps stored: no-op
        self.core.learn_from_text("python is a language.")            # identical edge state: no-op
        self.assertEqual(self.snap(), before)
        # teach with a different explicit source is a real update (provenance is part of state)
        self.ls.teach("Python", "a programming language", source="user")
        self.assertEqual(self.rec("Python")["version"], s["reteach"]["version"] + 1)
        # ... and correcting with the same description but another source is a real change too
        self.ls.correct("Python", "a programming language", source="user_correction")
        self.assertEqual(self.rec("Python")["version"], s["reteach"]["version"] + 2)
        self.assertEqual(self.rec("Python")["source"], "user_correction")

    # ---- C3: current readers vs history ----------------------------------------
    def test_current_readers_see_latest_state_events_keep_history(self):
        self.lifecycle()
        cur = self.k.get("Python")["description"]
        self.assertEqual(cur, "a programming language")
        self.assertEqual([r["name"] for r in self.k.search("snake")], [])          # old text not current
        self.assertEqual([r["name"] for r in self.k.search("programming")], ["Python"])
        self.assertEqual(self.k.resolve_name("python")["record"]["description"], cur)
        self.assertEqual(self.ls.recall("Python")["description"], cur)
        self.assertEqual([r["description"] for r in self.k.all() if r["name"] == "Python"], [cur])
        hist = [(e["event_type"], e["detail"], e["source"]) for e in self.events("teach", "correct")]
        self.assertEqual(hist, [("teach", "a snake", "user"),
                                ("correct", "'a snake' -> 'a programming language'", "user_correction"),
                                ("teach", "a programming language", "ael")])
        self.assertNotEqual(hist[0][1], cur)                                        # history != current
        self.assertNotEqual(self.events("teach")[0]["source"], self.rec("Python")["source"])

    def test_events_correspond_to_each_real_transition_only(self):
        self.lifecycle()
        self.assertEqual([(e["event_type"], e["target"]) for e in self.events()
                          if not e["event_type"].startswith("language_")],
                         [("relate", "Python"), ("teach", "Python"), ("correct", "Python"),
                          ("teach", "Python"), ("relate", "Python")])
        # last relate event is the NL text refresh of the same edge (source_text changed), not a new edge
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 1)

    # ---- relationships resolve against the current record ---------------------------
    def test_relationships_track_current_record_through_updates(self):
        self.lifecycle()
        rel = self.k.relationships_for("Python")
        self.assertEqual([(r["from_name"], r["to_name"], r["relation_type"]) for r in rel["outgoing"]],
                         [("Python", "language", "IS_A")])
        self.assertEqual(self.k.relationships_for("language")["incoming"][0]["from_name"], "Python")
        full = self.ls.recall("Python")
        self.assertEqual(full["relationships"]["outgoing"][0]["to_name"], "language")
        for r in self.m.query("SELECT * FROM relationships"):
            self.assertIsNotNone(self.k.get(r["from_name"]))
            self.assertIsNotNone(self.k.get(r["to_name"]))
        # unrelated endpoint record untouched by all of the above except its own NL stub creation
        lang = self.rec("language")
        self.assertEqual((lang["version"], lang["status"], lang["source"]), (1, "stub", "understanding_engine"))

    # ---- C8: case-sensitive identity / ambiguity ------------------------------------
    def test_ambiguity_deterministic_and_never_mutates_arbitrary_record(self):
        self.lifecycle()
        self.ls.teach("python", "lowercase python", source="user")
        before = self.snap()
        self.assertEqual(self.k.resolve_name("PYTHON")["status"], "ambiguous")
        with self.assertRaises(ValueError):
            self.ls.correct("PYTHON", "x")
        with self.assertRaises(ValueError):
            self.k.correct("PYTHON", "x")
        self.assertEqual(self.snap(), before)
        r = self.core.learn_from_text("python is a language.")      # exact candidate resolves exactly
        self.assertEqual(r.learned_items[0]["subject"], "python")
        self.assertEqual([x["description"] for x in self.rows("python")],
                         ["a programming language", "lowercase python"])
        self.assertEqual(self.rec("Python")["version"], 4)          # the other record untouched

    # ---- C4/11: failure atomicity across sources ----------------------------------------
    def test_failed_operation_at_every_step_leaves_state_and_history_unchanged(self):
        self.core.learn_from_text("Python is a language.")
        ops = {
            "teach": lambda: self.ls.teach("Python", "a snake", source="user", confidence=0.6),
            "correct": lambda: self.ls.correct("Python", "something else", source="user_correction"),
            "relate": lambda: self.ls.relate("Python", "Snake", "related_to", source="user"),
        }
        for label, op in ops.items():
            before = self.snap()
            with mock.patch.object(self.m, "add_learning_event", side_effect=RuntimeError("inject")):
                with self.assertRaises(RuntimeError, msg=label):
                    op()
            self.assertEqual(self.snap(), before, label)
            self.assertFalse(self.m._conn.in_transaction)
        op = ops["teach"]; op()                                     # then really apply, stage by stage
        for label in ("correct", "relate"):
            before = self.snap()
            with mock.patch.object(self.m, "add_learning_event", side_effect=RuntimeError("inject")):
                with self.assertRaises(RuntimeError):
                    ops[label]()
            self.assertEqual(self.snap(), before, label)
            ops[label]()
        self.assertEqual(self.rec("Python")["description"], "something else")

    def test_failed_natural_language_learning_on_existing_record_changes_nothing(self):
        self.lifecycle()
        before = self.snap()
        with mock.patch.object(self.m, "add_learning_event", side_effect=RuntimeError("inject")):
            r = self.core.learn_from_text("Python is a snake.")     # would create a new edge + stub
            self.assertFalse(r.success)
            self.assertTrue(any("inject" in e for e in r.errors))
        self.assertEqual(self.snap(), before)
        r = self.core.learn_from_text("Python is a snake.")
        self.assertTrue(r.success)
        self.assertEqual(len(self.rows("snake")), 1)                # its new object concept, own stub
        self.assertEqual(self.rec("Python")["version"], 4)

    def test_rejected_correction_after_cross_source_history_changes_nothing(self):
        self.lifecycle()
        before = self.snap()
        with self.assertRaises(ValueError):
            self.ls.correct("Python", "   ")
        self.assertIsNone(self.ls.correct("Ghost", "x"))
        self.assertEqual(self.snap(), before)

    # ---- C5: language store isolation ----------------------------------------------------
    def test_language_store_does_not_alter_current_knowledge(self):
        self.lifecycle()
        before = self.snap()["knowledge"]
        LanguageLearningStore(self.m).learn_item("en", "word", "Python", meaning="a language word",
                                                 source="user")
        self.assertEqual(self.snap()["knowledge"], before)
        self.assertEqual(self.rec("Python")["description"], "a programming language")

    # ---- persistence -----------------------------------------------------------------
    def test_reopen_state_identical_and_sequence_continues(self):
        s = self.lifecycle()
        before = self.snap()
        self.reopen()
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.rec("Python"), s["nl2"])
        self.ls.teach("Python", "a programming language")            # still a no-op after reopen
        self.assertEqual(self.snap(), before)
        self.ls.correct("python", "the Python language")
        r = self.rec("Python")
        self.assertEqual((r["id"], r["version"], r["source"]), (s["nl2"]["id"], 5, "ael"))
        self.assertEqual(len(self.rows("python")), 1)


if __name__ == "__main__":
    unittest.main()
