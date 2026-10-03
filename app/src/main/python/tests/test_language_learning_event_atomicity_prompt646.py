"""Prompt 646 - Section 3: language-learning mutation + event atomicity.

Inspection result: LanguageLearningStore.learn_item() and
LanguageRelationshipStore.relate() wrote their row and their learning event
as two separately committed statements (same gap Prompt 645 fixed for
Knowledge/Learning). Fix: both now run inside the existing Prompt 645
MemorySystem._atomic() scope - no new abstraction, no schema/signature/event
change. Neither store has exact-repeat short-circuiting (a repeat always
updates + logs); that existing behaviour is preserved and pinned below.

Failures are injected deterministically at MemorySystem.add_learning_event /
MemorySystem._run.
"""
import os
import tempfile
import unittest
from unittest import mock

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.language_relationships import (
    LanguageRelationshipStore, item_ref, concept_ref)

TABLES = ("language_learning_items", "language_item_relationships", "knowledge", "learning_events")


class Boom(RuntimeError):
    pass


def _stack(db):
    m = MemorySystem(db)
    k = KnowledgeSystem(m)
    ll = LanguageLearningStore(m)
    return m, k, ll, LanguageRelationshipStore(m, ll, k)


def _dump(m):
    return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")] for t in TABLES}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "m.db")
        self.m, self.k, self.ll, self.rel = _stack(self.db)

    def tearDown(self):
        self.m._conn.close()
        self.tmp.cleanup()

    def reopen(self):
        self.m._conn.close()
        self.m, self.k, self.ll, self.rel = _stack(self.db)
        return self.m

    def events(self):
        return [(e["event_type"], e["target"], e["detail"], e["source"])
                for e in _dump(self.m)["learning_events"]]

    def two_items(self):
        self.ll.learn_item("fa", "word", "سلام", source="user")
        self.ll.learn_item("en", "word", "hello", source="user")
        return item_ref("fa", "word", "سلام"), item_ref("en", "word", "hello")

    @staticmethod
    def fail_event(m):
        return mock.patch.object(type(m), "add_learning_event", side_effect=Boom("event"))

    @staticmethod
    def fail_event_after_write(m):
        orig = type(m).add_learning_event

        def _f(self, *a, **kw):
            orig(self, *a, **kw)
            raise Boom("after event")
        return mock.patch.object(type(m), "add_learning_event", _f)

    @staticmethod
    def fail_sql(m, needle, after=False):
        orig = type(m)._run

        def _run(self, sql, params=()):
            if needle in sql and not after:
                raise Boom("sql")
            cur = orig(self, sql, params)
            if needle in sql and after:
                raise Boom("sql after")
            return cur
        return mock.patch.object(type(m), "_run", _run)


class ItemTests(Base):
    def test_1_create_and_update_persist_item_and_event(self):
        it = self.ll.learn_item("fa", "word", "سلام", meaning={"m": "hi"}, source="user", source_context="ctx")
        self.assertEqual(it["version"], 1)
        it = self.ll.learn_item("fa", "word", "سلام", meaning={"m": "hello"}, source="user", source_context="ctx2")
        self.assertEqual(it["version"], 2)
        self.assertEqual(self.events(), [
            ("language_item_learned", "persian:word:سلام", "ctx", "user"),
            ("language_item_updated", "persian:word:سلام", "ctx2", "user")])

    def test_3_event_failure_rolls_back_create(self):
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.ll.learn_item("fa", "word", "سلام")
        d = _dump(self.m)
        self.assertEqual((d["language_learning_items"], d["learning_events"]), ([], []))
        with self.fail_event_after_write(self.m), self.assertRaises(Boom):
            self.ll.learn_item("fa", "word", "سلام")
        d = _dump(self.m)
        self.assertEqual((d["language_learning_items"], d["learning_events"]), ([], []))

    def test_3_event_failure_rolls_back_update(self):
        self.ll.learn_item("fa", "word", "x", meaning={"a": 1}, source="user")
        before = _dump(self.m)
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.ll.learn_item("fa", "word", "x", meaning={"a": 2})
        self.assertEqual(_dump(self.m), before)
        self.assertEqual(self.ll.get_item("fa", "word", "x")["version"], 1)

    def test_4_item_write_failure_leaves_no_orphan_event(self):
        for after in (False, True):
            with self.fail_sql(self.m, "INSERT INTO language_learning_items", after), self.assertRaises(Boom):
                self.ll.learn_item("fa", "word", "x")
        self.ll.learn_item("fa", "word", "x")
        before = _dump(self.m)
        for after in (False, True):
            with self.fail_sql(self.m, "UPDATE language_learning_items", after), self.assertRaises(Boom):
                self.ll.learn_item("fa", "word", "x", meaning={"z": 1})
        self.assertEqual(_dump(self.m), before)

    def test_6_repeat_behaviour_unchanged(self):
        # Existing contract: a repeat is an update (version+1) with one event.
        self.ll.learn_item("fa", "word", "x", meaning={"a": 1}, source="user")
        self.ll.learn_item("fa", "word", "x", meaning={"a": 1}, source="user")
        self.assertEqual(self.ll.get_item("fa", "word", "x")["version"], 2)
        self.assertEqual(len(self.events()), 2)
        # invalid input writes nothing
        n = _dump(self.m)
        with self.assertRaises(ValueError):
            self.ll.learn_item("fa", "word", "   ")
        self.assertEqual(_dump(self.m), n)

    def test_memoryless_store_unchanged(self):
        ll = LanguageLearningStore(None)
        with self.assertRaises(Exception):
            ll.learn_item("fa", "word", "x")  # needs storage, as before
        self.assertEqual(self.ll._atomic().__class__.__name__, "_GeneratorContextManager")


class RelationshipTests(Base):
    def test_2_relate_persists_row_and_event(self):
        a, b = self.two_items()
        r = self.rel.relate(a, b, "translation", source="user", source_context="c1")
        self.assertTrue(r["created"])
        r2 = self.rel.relate(a, b, "translation", source="user", source_context="c2", confidence=0.5)
        self.assertFalse(r2["created"])
        self.assertEqual(r2["version"], 2)
        types = [e[0] for e in self.events() if e[0].startswith("language_relationship")]
        self.assertEqual(types, ["language_relationship_learned", "language_relationship_updated"])
        self.assertEqual(len(_dump(self.m)["language_item_relationships"]), 1)

    def test_2b_concept_endpoint(self):
        self.k.learn("Greeting", "a greeting")
        a, _ = self.two_items()
        self.assertTrue(self.rel.relate(a, concept_ref("Greeting"), "means")["created"])

    def test_3_event_failure_rolls_back_relationship(self):
        a, b = self.two_items()
        before = _dump(self.m)
        for ctx in (self.fail_event(self.m), self.fail_event_after_write(self.m)):
            with ctx, self.assertRaises(Boom):
                self.rel.relate(a, b, "translation", source="user")
            self.assertEqual(_dump(self.m), before)

    def test_3_event_failure_rolls_back_refresh(self):
        a, b = self.two_items()
        self.rel.relate(a, b, "translation", confidence=0.2)
        before = _dump(self.m)
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.rel.relate(a, b, "translation", confidence=0.9)
        self.assertEqual(_dump(self.m), before)

    def test_4_relationship_write_failure_leaves_no_orphan_event(self):
        a, b = self.two_items()
        before = _dump(self.m)
        for after in (False, True):
            with self.fail_sql(self.m, "INSERT INTO language_item_relationships", after), self.assertRaises(Boom):
                self.rel.relate(a, b, "translation")
            self.assertEqual(_dump(self.m), before)
        self.rel.relate(a, b, "translation")
        before = _dump(self.m)
        for after in (False, True):
            with self.fail_sql(self.m, "UPDATE language_item_relationships", after), self.assertRaises(Boom):
                self.rel.relate(a, b, "translation", confidence=0.1)
            self.assertEqual(_dump(self.m), before)

    def test_5_rejected_relate_leaves_no_partial_or_stub_state(self):
        a, b = self.two_items()
        before = _dump(self.m)
        with self.assertRaises(ValueError):
            self.rel.relate(a, item_ref("en", "word", "missing"), "translation")
        with self.assertRaises(ValueError):
            self.rel.relate(a, a, "translation")
        with self.assertRaises(ValueError):
            self.rel.relate(a, concept_ref("NoSuchConcept"), "means")
        self.rel.relate(a, b, "translation", symmetric=True)
        snap = _dump(self.m)
        with self.assertRaises(ValueError):
            self.rel.relate(a, b, "translation", symmetric=False)   # symmetric conflict
        self.assertEqual(_dump(self.m), snap)
        self.assertEqual(before["knowledge"], snap["knowledge"])     # no stubs ever created

    def test_6_repeat_behaviour_unchanged(self):
        a, b = self.two_items()
        self.rel.relate(a, b, "translation", confidence=0.5)
        self.rel.relate(a, b, "translation", confidence=0.5)
        self.assertEqual(self.rel.relationships_for(a)[0]["version"], 2)
        self.assertEqual(len(_dump(self.m)["language_item_relationships"]), 1)


class OrderingReopenOrphans(Base):
    def test_7_event_ordering_deterministic(self):
        a, b = self.two_items()
        self.rel.relate(a, b, "translation")
        self.ll.learn_item("fa", "word", "سلام", meaning={"m": 1})
        self.assertEqual([e[0] for e in self.events()], [
            "language_item_learned", "language_item_learned",
            "language_relationship_learned", "language_item_updated"])
        ids = [e["id"] for e in _dump(self.m)["learning_events"]]
        self.assertEqual(ids, sorted(ids))

    def test_8_reopen_preserves_success_and_failure_results(self):
        a, b = self.two_items()
        self.rel.relate(a, b, "translation", source="user")
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.ll.learn_item("fa", "word", "extra")
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.rel.relate(a, b, "synonym")
        before = _dump(self.m)
        d = _dump(self.reopen())
        self.assertEqual(d, before)
        self.assertEqual(len(d["language_learning_items"]), 2)
        self.assertEqual(len(d["language_item_relationships"]), 1)
        self.assertEqual(len(d["learning_events"]), 3)

    def test_9_no_orphans_and_connection_healthy_after_failures(self):
        a, b = self.two_items()
        with self.fail_event(self.m), self.assertRaises(Boom):
            self.ll.learn_item("fa", "word", "orphan")
        with self.fail_sql(self.m, "INSERT INTO language_item_relationships"), self.assertRaises(Boom):
            self.rel.relate(a, b, "translation")
        self.assertEqual(self.m._atomic_depth, 0)
        self.assertFalse(self.m._conn.in_transaction)
        d = _dump(self.reopen())
        keys = {i["item_key"] for i in d["language_learning_items"]}
        self.assertEqual(keys, {"سلام", "hello"})
        self.assertEqual(d["language_item_relationships"], [])
        self.assertEqual({e["target"] for e in d["learning_events"]}, {"persian:word:سلام", "english:word:hello"})
        self.assertTrue(self.ll.learn_item("fa", "word", "orphan"))   # still usable


if __name__ == "__main__":
    unittest.main()
