"""Prompt 662 - Section 3: learning-event history vs authoritative current state.

AUDIT with focused regression coverage. No replay engine, no schema change, events never authoritative.
Current knowledge/relationship rows are the source of truth; learning_events are historical records and
only the fields the existing event contract records are asserted (teach: name/new description/persisted
source; correct: stored name/"old -> new"/persisted source; relate: from_name/"rel -> to"/persisted
relationship source; language_*: canonical target/source_context/persisted source).
Ordering identity is learning_events.id (never the timestamp).
"""
import ast
import os
import tempfile
import unittest
from unittest import mock

from core.core import Core
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.language_relationships import (
    LanguageRelationshipStore, item_ref, concept_ref)

TABLES = ("knowledge", "relationships", "learning_events",
          "language_learning_items", "language_item_relationships")


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
        self.ll = LanguageLearningStore(self.m)
        self.lr = LanguageRelationshipStore(self.m, self.ll, self.k)

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

    def sig(self, *types):
        return [(e["event_type"], e["target"], e["detail"], e["source"]) for e in self.ev(*types)]

    def rel(self, a, b, r):
        return self.m.query_one("SELECT * FROM relationships WHERE from_name=? AND to_name=? AND relation_type=?",
                                (a, b, r))

    def boom_event(self, when=lambda *a, **k: True):
        real = self.m.add_learning_event

        def inner(*a, **k):
            if when(*a, **k):
                raise Boom("event insert failed")
            return real(*a, **k)
        return mock.patch.object(self.m, "add_learning_event", side_effect=inner)


class KnowledgeCreationAndUpdate(Base):
    def test_teach_creates_row_and_event(self):
        self.ls.teach("Python", "a language", source="user", confidence=0.7,
                      source_text="Python is a language", learning_method="ael")
        r = self.k.get("Python")
        self.assertEqual((r["version"], r["status"], r["description"], r["source"], r["confidence"]),
                         (1, "active", "a language", "user", 0.7))
        self.assertEqual(self.sig(), [("teach", "Python", "a language", "user")])

    def test_stub_to_taught_transition(self):
        self.ls.relate("Cat", "Animal", "is_a", source="user")
        self.assertEqual(self.k.get("Cat")["status"], "stub")
        self.assertEqual(self.k.get("Cat")["version"], 1)
        self.assertEqual([e["event_type"] for e in self.ev()], ["relate"])   # L1: no stub event
        self.ls.teach("Cat", "a feline", source="user")
        r = self.k.get("Cat")
        self.assertEqual((r["status"], r["version"], r["description"]), ("active", 2, "a feline"))
        self.assertEqual(self.sig("teach"), [("teach", "Cat", "a feline", "user")])
        # the untouched stub endpoint stays a stub with no event of its own
        self.assertEqual((self.k.get("Animal")["status"], self.k.get("Animal")["version"]), ("stub", 1))

    def test_nl_learning_creates_stub_rows_and_relate_event(self):
        self.core.learn_from_text("Python is a language.")
        evs = self.ev()
        self.assertEqual(len(evs), 1)
        e = evs[0]
        self.assertEqual(e["event_type"], "relate")
        rel, _, to = e["detail"].partition(" -> ")
        row = self.rel(e["target"], to, rel)
        self.assertIsNotNone(row)
        self.assertEqual(e["source"], row["source_type"])
        self.assertEqual(row["learning_method"], "natural_language_understanding")
        for n in (e["target"], to):
            self.assertEqual(self.k.get(n)["version"], 1)

    def test_update_events_and_noops(self):
        self.ls.teach("A", "one", source="user", confidence=0.5)
        self.ls.teach("A", "one", source="user")                       # identical no-op
        self.ls.teach("A", "one", source="user", confidence=0.5)       # identical (explicit) no-op
        self.assertEqual(self.k.get("A")["version"], 1)
        self.assertEqual(len(self.ev()), 1)
        self.ls.teach("A", "two", source="user")                       # description
        self.ls.teach("A", "two", source="user", confidence=0.9)       # confidence only
        self.ls.teach("A", "two", source="user", confidence=0.9, source_text="s")  # source_text only
        self.ls.teach("A", "two", source="other", confidence=0.9)      # source only
        r = self.k.get("A")
        self.assertEqual((r["version"], r["description"], r["source"], r["confidence"], r["source_text"]),
                         (5, "two", "other", 0.9, "s"))
        self.assertEqual(self.sig(), [
            ("teach", "A", "one", "user"), ("teach", "A", "two", "user"), ("teach", "A", "two", "user"),
            ("teach", "A", "two", "user"), ("teach", "A", "two", "other")])
        self.assertEqual(r["version"], len(self.ev("teach")))          # 1 event per real mutation here

    def test_history_is_historical_not_rewritten(self):
        self.ls.teach("A", "one", source="user")
        before = self.ev()
        self.ls.teach("A", "two", source="user2")
        self.ls.correct("A", "three")
        after = self.ev()
        self.assertEqual(after[0], before[0])                           # first event untouched
        self.assertEqual(self.k.get("A")["description"], "three")
        self.assertEqual(after[0]["detail"], "one")
        self.assertEqual(after[1]["detail"], "two")
        self.assertEqual(after[2]["detail"], "'two' -> 'three'")
        self.assertEqual(after[2]["source"], "user2")                   # persisted source kept by correct()

    def test_correct_contract(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.correct("python", "a language")                          # case-insensitive resolution
        self.assertEqual(self.k.get("Python")["version"], 2)
        self.assertIsNone(self.k.get("python"))
        self.assertEqual(self.sig("correct"), [("correct", "Python", "'a snake' -> 'a language'", "user")])
        self.ls.correct("Python", "a language")                          # no-op
        self.assertEqual(self.k.get("Python")["version"], 2)
        self.assertEqual(len(self.ev("correct")), 1)
        n = len(self.ev())
        self.assertIsNone(self.ls.correct("Nope", "x"))                  # never creates
        with self.assertRaises(ValueError):
            self.ls.correct("Python", "  ")
        self.assertEqual((len(self.ev()), self.k.get("Nope")), (n, None))

    def test_status_change_via_correct_supported_and_l2_limit(self):
        self.ls.relate("S", "T", "is_a", source="user")
        self.ls.correct("S", "now defined")
        r = self.k.get("S")
        self.assertEqual((r["status"], r["version"]), ("active", 2))
        self.assertEqual(self.sig("correct"), [("correct", "S", "None -> 'now defined'", "user")])

    def test_invalid_teach_leaves_nothing(self):
        s = self.snap()
        for bad in ("", "   ", None, 5):
            with self.assertRaises(Exception):
                self.ls.teach(bad, "x")
        self.assertEqual(self.snap(), s)


class RelationshipLifecycle(Base):
    def test_create_update_repeat(self):
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.4, source_text="t1")
        row = self.rel("A", "B", "is_a")
        self.assertEqual((row["confidence"], row["source_type"], row["source_text"]), (0.4, "user", "t1"))
        self.assertEqual(self.sig(), [("relate", "A", "is_a -> B", "user")])
        s = self.snap()
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.4, source_text="t1")   # exact repeat
        self.ls.relate("A", "B", "is_a", source="user")                                     # None keeps stored
        self.assertEqual(self.snap(), s)
        self.ls.relate("A", "B", "is_a", source="user2", confidence=0.9)                    # real update
        row = self.rel("A", "B", "is_a")
        self.assertEqual((row["confidence"], row["source_type"], row["source_text"]), (0.9, "user2", "t1"))
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 1)
        self.assertEqual(self.sig()[-1], ("relate", "A", "is_a -> B", "user2"))
        self.assertEqual(len(self.ev("relate")), 2)

    def test_stubs_untouched_by_relationship_updates(self):
        self.ls.relate("A", "B", "is_a", source="user")
        vs = (self.k.get("A")["version"], self.k.get("B")["version"])
        self.ls.relate("A", "B", "is_a", source="user2", confidence=0.3)
        self.assertEqual((self.k.get("A")["version"], self.k.get("B")["version"]), vs)
        self.assertEqual(vs, (1, 1))                                     # relationship != knowledge version

    def test_existing_endpoints_not_restubbed(self):
        self.ls.teach("A", "real", source="user")
        self.ls.relate("A", "B", "is_a", source="user")
        self.assertEqual((self.k.get("A")["status"], self.k.get("A")["version"]), ("active", 1))
        self.assertEqual(self.k.get("B")["status"], "stub")

    def test_endpoint_teach_then_correct_then_relate_update(self):
        self.ls.relate("A", "B", "part_of", source="user")
        self.ls.teach("B", "the b", source="user")
        self.ls.correct("B", "the better b")
        self.ls.relate("A", "B", "part_of", source="user", confidence=0.8)
        self.assertEqual((self.k.get("B")["version"], self.k.get("B")["description"]), (3, "the better b"))
        self.assertEqual(self.rel("A", "B", "part_of")["confidence"], 0.8)
        self.assertEqual([e["event_type"] for e in self.ev()], ["relate", "teach", "correct", "relate"])
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 1)
        self.assertEqual(self.ev()[1]["detail"], "the b")                # history retains old value

    def test_invalid_relations_leave_no_artifacts(self):
        s = self.snap()
        for args in (("", "B", "r"), ("A", "  ", "r"), (None, "B", "r"), ("A", "B", None)):
            with self.assertRaises(Exception):
                self.ls.relate(*args, source="user")
        self.assertEqual(self.snap(), s)                                 # no orphan stubs, no events

    def test_failed_relate_rolls_back_stubs_and_row(self):
        s = self.snap()
        with self.boom_event():
            with self.assertRaises(Boom):
                self.ls.relate("X", "Y", "is_a", source="user")
        self.assertEqual(self.snap(), s)

    def test_failed_relate_update_rolls_back(self):
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.1)
        s = self.snap()
        with self.boom_event():
            with self.assertRaises(Boom):
                self.ls.relate("A", "B", "is_a", source="user", confidence=0.9)
        self.assertEqual(self.snap(), s)

    def test_failure_between_stub_and_edge_rolls_back(self):
        s = self.snap()
        real = self.m._run

        def run(sql, params=()):
            if sql.startswith("INSERT INTO relationships"):
                raise Boom("edge insert")
            return real(sql, params)
        with mock.patch.object(self.m, "_run", side_effect=run):
            with self.assertRaises(Boom):
                self.ls.relate("P", "Q", "is_a", source="user")
        self.assertEqual(self.snap(), s)


class LanguageLifecycle(Base):
    def test_learn_item_events_and_semantics(self):
        it = self.ll.learn_item("en", "word", "Run", meaning="move fast", source="teacher", source_context="ctx1")
        self.assertEqual(it["version"], 1)
        self.ll.learn_item("en", "word", "Run", meaning="move fast", source="teacher", source_context="ctx1")
        self.assertEqual(self.ll.get_item("en", "word", "Run")["version"], 2)   # repeat = real update (by design)
        self.ll.learn_item("en", "word", "Run")                                 # omitted source/context
        it = self.ll.get_item("en", "word", "Run")
        self.assertEqual((it["version"], it["source"], it["meaning"]), (3, "teacher", "move fast"))
        evs = self.ev()
        self.assertEqual([(e["event_type"], e["target"], e["detail"], e["source"]) for e in evs], [
            ("language_item_learned", "english:word:Run", "ctx1", "teacher"),
            ("language_item_updated", "english:word:Run", "ctx1", "teacher"),
            ("language_item_updated", "english:word:Run", None, "teacher")])       # L3: None context, persisted source
        self.assertEqual(it["version"], len(evs))

    def test_language_relationship_events(self):
        self.ll.learn_item("en", "word", "cold", source="t")
        self.ll.learn_item("en", "word", "hot", source="t")
        n = len(self.ev())
        a, b = item_ref("en", "word", "cold"), item_ref("en", "word", "hot")
        r = self.lr.relate(a, b, "antonym", source="t", source_context="c")
        self.assertTrue(r["created"])
        r2 = self.lr.relate(b, a, "antonym", source=None)
        self.assertFalse(r2["created"])
        evs = self.ev()[n:]
        self.assertEqual([e["event_type"] for e in evs],
                         ["language_relationship_learned", "language_relationship_updated"])
        self.assertEqual(evs[1]["source"], "t")                                  # persisted source
        self.assertEqual(len(self.m.query("SELECT * FROM language_item_relationships")), 1)
        # knowledge tables never touched
        self.assertEqual(self.m.query("SELECT * FROM knowledge"), [])

    def test_language_relationship_failures_leave_nothing(self):
        self.ll.learn_item("en", "word", "cold", source="t")
        a = item_ref("en", "word", "cold")
        s = self.snap()
        with self.assertRaises(Exception):
            self.lr.relate(a, item_ref("en", "word", "missing"), "antonym")
        with self.assertRaises(Exception):
            self.lr.relate(a, a, "synonym")
        self.assertEqual(self.snap(), s)

    def test_language_failure_rollback(self):
        s = self.snap()
        with self.boom_event():
            with self.assertRaises(Boom):
                self.ll.learn_item("en", "word", "x", meaning="m", source="t")
        self.assertEqual(self.snap(), s)
        self.ll.learn_item("en", "word", "x", meaning="m", source="t")
        self.ll.learn_item("en", "word", "y", source="t")
        s = self.snap()
        with self.boom_event():
            with self.assertRaises(Boom):
                self.ll.learn_item("en", "word", "x", meaning="changed", source="t2")
            with self.assertRaises(Boom):
                self.lr.relate(item_ref("en", "word", "x"), item_ref("en", "word", "y"), "synonym", source="t")
        self.assertEqual(self.snap(), s)


class Provenance(Base):
    def test_event_fields_match_persisted_rows(self):
        self.ls.teach("A", "d1", source="s1", source_text="st", learning_method="m1", confidence=0.3)
        self.ls.teach("A", "d2")                                      # default source "ael" replaces
        self.ls.correct("A", "d3", source="user_correction")
        self.ls.correct("A", "d4")                                    # keeps persisted source
        self.ls.relate("A", "B", "is_a", source="s9", source_text="x", learning_method="lm")
        self.assertEqual(self.sig(), [
            ("teach", "A", "d1", "s1"), ("teach", "A", "d2", "ael"),
            ("correct", "A", "'d2' -> 'd3'", "user_correction"),
            ("correct", "A", "'d3' -> 'd4'", "user_correction"),
            ("relate", "A", "is_a -> B", "s9")])
        r = self.k.get("A")
        self.assertEqual((r["source"], r["description"], r["source_text"], r["learning_method"]),
                         ("user_correction", "d4", "st", "m1"))       # None-preserving fields survive
        # chain of correct events is continuous with current state
        cs = self.ev("correct")
        self.assertEqual(ast.literal_eval(cs[-1]["detail"].split(" -> ", 1)[1]), r["description"])


class VersionAndOrdering(Base):
    def test_version_counts_real_mutations_across_paths(self):
        self.ls.relate("V", "W", "is_a", source="u")                  # stub v1
        self.ls.teach("V", "a", source="u")                           # v2
        self.ls.teach("V", "a", source="u")                           # no-op
        self.ls.correct("V", "b")                                     # v3
        self.ls.correct("V", "b")                                     # no-op
        self.ls.teach("V", "b", source="u", confidence=0.2)           # v4
        with self.boom_event():
            with self.assertRaises(Boom):
                self.ls.teach("V", "z", source="u")                   # rollback: no gap
        self.ls.teach("V", "c", source="u")                           # v5
        self.assertEqual(self.k.get("V")["version"], 5)
        self.assertEqual(len(self.ev("teach", "correct")), 4)         # stub v1 has no own event (L1)
        self.assertEqual(self.k.get("W")["version"], 1)

    def test_event_order_deterministic_with_equal_timestamps(self):
        with mock.patch("memory.memory_system._now", return_value="2026-01-01T00:00:00+00:00"):
            for i in range(6):
                self.ls.teach("T", f"d{i}", source="u")
        evs = self.ev()
        self.assertEqual(len({e["created_at"] for e in evs}), 1)
        ids = [e["id"] for e in evs]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual([e["detail"] for e in evs], [f"d{i}" for i in range(6)])
        self.assertEqual([e["detail"] for e in self.m.recent_learning_events(6)], [f"d{i}" for i in range(6)])
        self.assertEqual([e["id"] for e in self.m.recent_learning_events(3)], ids[-3:])

    def test_failed_ops_leave_no_id_gap_or_reuse(self):
        self.ls.teach("A", "1", source="u")
        with self.boom_event():
            with self.assertRaises(Boom):
                self.ls.teach("A", "2", source="u")
        self.ls.teach("A", "3", source="u")
        ids = [e["id"] for e in self.ev()]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertEqual(len(ids), 2)


class Atomicity(Base):
    def test_teach_correct_event_failures(self):
        self.ls.teach("A", "one", source="u")
        s = self.snap()
        with self.boom_event():
            for fn in (lambda: self.ls.teach("A", "two", source="u"),
                       lambda: self.ls.teach("New", "x", source="u"),
                       lambda: self.ls.correct("A", "two")):
                with self.assertRaises(Boom):
                    fn()
        self.assertEqual(self.snap(), s)

    def test_mutation_failure_leaves_no_event(self):
        self.ls.teach("A", "one", source="u")
        s = self.snap()
        real = self.m._run

        def run(sql, params=()):
            if sql.startswith("UPDATE knowledge"):
                raise Boom("update")
            return real(sql, params)
        with mock.patch.object(self.m, "_run", side_effect=run):
            with self.assertRaises(Boom):
                self.ls.teach("A", "two", source="u")
        self.assertEqual(self.snap(), s)

    def test_nl_learning_failure_reports_error_and_leaves_state(self):
        s = self.snap()
        with self.boom_event():
            res = self.core.learn_from_text("Python is a language.")
        self.assertFalse(res.success)
        self.assertTrue(res.errors)
        self.assertEqual(self.snap(), s)


class ReopenAndCrossSource(Base):
    def test_close_reopen_no_reload_events(self):
        self.ls.teach("A", "one", source="u")
        self.ls.relate("A", "B", "is_a", source="u")
        self.ls.correct("A", "two")
        self.ll.learn_item("en", "word", "run", source="t")
        s = self.snap()
        for _ in range(2):
            self.reopen()
            self.assertEqual(self.snap(), s)
            self.assertEqual([e["id"] for e in self.ev()], sorted(e["id"] for e in self.ev()))

    def test_nl_teach_correct_reteach_nl_repeat(self):
        self.core.learn_from_text("Python is a language.")
        ne = len(self.ev())
        self.ls.teach("Python", "a snake", source="user", confidence=0.6)
        self.ls.correct("Python", "a programming language")
        self.ls.teach("Python", "a snake", source="user")
        self.core.learn_from_text("Python is a language.")            # NL repeat: relationship only
        r = self.k.get("Python")
        self.assertEqual((r["description"], r["version"], r["source"]), ("a snake", 4, "user"))
        self.assertEqual([e["event_type"] for e in self.ev()][ne:], ["teach", "correct", "teach"])
        self.assertEqual(len(self.ev("relate")), 1)                   # repeat identical -> no second event
        self.assertEqual(self.ev("teach")[0]["detail"], "a snake")
        self.assertEqual(self.ev("correct")[0]["detail"], "'a snake' -> 'a programming language'")
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='python'")), 1)
        s = self.snap()
        self.reopen()
        self.assertEqual(self.snap(), s)


if __name__ == "__main__":
    unittest.main()
