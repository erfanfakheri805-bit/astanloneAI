"""Prompt 647 - Section 3: learning-history reconstructability / audit.

AUDIT, not event sourcing. Existing event model (unchanged):
  teach()                      "teach"   target=name  detail=new description  source=persisted source
  correct()                    "correct" target=stored name  detail="'old' -> 'new'"  source=persisted source
  LearningSystem.relate()      "relate"  target=from_name  detail="<rel> -> <to>"  source=persisted source_type
  learn_item()  create/update  "language_item_learned"/"language_item_updated"
                               target="<canonical lang>:<type>:<key>"  detail=source_context  source=persisted source
  LanguageRelationshipStore    "language_relationship_learned"/"..._updated"
                               target="<from> -[<rel>]<->|-> <to>"  detail=source_context  source=persisted source
Event-bearing operations are exactly those that change persisted state; exact
no-ops (teach / correct / relate repeats) write nothing. The two language
stores intentionally treat every repeat as a real update (version+1 + event).

Defect found (Prompt 644 F1 pattern, remaining in the language stores):
learn_item()/relate() logged the source ARGUMENT, so an update that omitted
`source` (None = keep stored value) recorded source=None while the persisted
row kept its real source. Events now record the persisted source. Nothing else
changed.

Documented limitations (schema intentionally lacks them; not expanded):
  L1. Stub concepts auto-created by relate() have no event of their own.
  L2. teach()/correct() events carry no confidence/source_text/status deltas;
      a status- or confidence-only change logs an event with an unchanged
      description ("'x' -> 'x'" for correct).
  L3. Language events carry source_context only as `detail` (no meaning/
      examples diff); a None source_context logs detail=None even though the
      stored context is kept.
  L4. KnowledgeSystem.learn()/relate() called directly (not via
      LearningSystem) write no events by design.
"""
import os
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.language_relationships import (
    LanguageRelationshipStore, item_ref, concept_ref)

TABLES = ("knowledge", "relationships", "language_learning_items",
          "language_item_relationships", "learning_events")


def _dump(m):
    return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")] for t in TABLES}


class Audit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "m.db")
        self._open()

    def _open(self):
        self.m = MemorySystem(self.db)
        self.k = KnowledgeSystem(self.m)
        self.ls = LearningSystem(ConceptSystem(self.k), self.k, memory=self.m)
        self.ll = LanguageLearningStore(self.m)
        self.lr = LanguageRelationshipStore(self.m, self.ll, self.k)

    def tearDown(self):
        self.m._conn.close()
        self.tmp.cleanup()

    def reopen(self):
        self.m._conn.close()
        self._open()

    def ev(self, *types):
        rows = self.m.query("SELECT * FROM learning_events ORDER BY id")
        return [r for r in rows if not types or r["event_type"] in types]

    def sig(self, *types):
        return [(e["event_type"], e["target"], e["detail"], e["source"]) for e in self.ev(*types)]

    # ---- replay checks: history must explain state, never contradict it ----
    def check_consistency(self):
        events = self.ev()
        ids = [e["id"] for e in events]
        self.assertEqual(ids, sorted(ids))
        stamps = [e["created_at"] for e in events]
        self.assertEqual(stamps, sorted(stamps))                     # append-only chronology
        by = lambda types: [e for e in events if e["event_type"] in types]
        # knowledge: every teach/correct targets an existing record; for records
        # created by teach(), version == number of teach+correct events on it.
        known = {r["name"]: r for r in self.m.query("SELECT * FROM knowledge")}
        teached = {e["target"] for e in by(("teach",))}
        for e in by(("teach", "correct")):
            self.assertIn(e["target"], known)
        for name in teached:
            n = len([e for e in by(("teach", "correct")) if e["target"] == name])
            first_teach_created = self._first_event_created_record.get(name, True)
            if first_teach_created:
                self.assertEqual(known[name]["version"], n, name)
        # knowledge relationships: every relate event names a stored edge
        for e in by(("relate",)):
            rel, to = e["detail"].split(" -> ", 1)
            row = self.m.query_one("SELECT * FROM relationships WHERE from_name=? AND to_name=? "
                                   "AND relation_type=?", (e["target"], to, rel))
            self.assertIsNotNone(row, e)
        for r in self.m.query("SELECT * FROM relationships"):
            self.assertTrue([e for e in by(("relate",)) if e["target"] == r["from_name"]
                             and e["detail"] == f"{r['relation_type']} -> {r['to_name']}"], r)
        # language items: version == number of learned/updated events for that key
        for it in self.m.query("SELECT * FROM language_learning_items"):
            target = f"{it['language']}:{it['item_type']}:{it['item_key']}"
            mine = [e for e in by(("language_item_learned", "language_item_updated")) if e["target"] == target]
            self.assertEqual(it["version"], len(mine), target)
            self.assertEqual(mine[0]["event_type"], "language_item_learned")
            self.assertTrue(all(e["event_type"] == "language_item_updated" for e in mine[1:]))
            self.assertEqual(mine[-1]["source"], it["source"], target)      # provenance matches
        for e in by(("language_item_learned", "language_item_updated")):
            lang, typ, key = e["target"].split(":", 2)
            self.assertIsNotNone(self.m.query_one(
                "SELECT 1 AS x FROM language_learning_items WHERE language=? AND item_type=? AND item_key=?",
                (lang, typ, key)), e)
        # language relationships: version == events for that label
        for r in self.m.query("SELECT * FROM language_item_relationships"):
            label = self.label(r)
            mine = [e for e in by(("language_relationship_learned", "language_relationship_updated"))
                    if e["target"] == label]
            self.assertEqual(r["version"], len(mine), label)
            self.assertEqual(mine[0]["event_type"], "language_relationship_learned")
            self.assertEqual(mine[-1]["source"], r["source"], label)

    _first_event_created_record = {}

    def label(self, r):
        def end(item_id, concept):
            if item_id is not None:
                i = self.m.query_one("SELECT * FROM language_learning_items WHERE id=?", (item_id,))
                return f"{i['language']}:{i['item_type']}:{i['item_key']}"
            return f"concept:{concept}"
        arrow = "<->" if r["symmetric"] else "->"
        return f"{end(r['from_item_id'], r['from_concept'])} -[{r['relation_type']}]{arrow} " \
               f"{end(r['to_item_id'], r['to_concept'])}"


class KnowledgeHistory(Audit):
    def test_create_update(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.teach("Python", "a language", source="user")
        self.assertEqual(self.sig(), [("teach", "Python", "a snake", "user"),
                                      ("teach", "Python", "a language", "user")])
        self.assertEqual(self.k.get("Python")["version"], 2)
        self.check_consistency()

    def test_update_event_identifies_change_and_provenance(self):
        self.ls.teach("X", "d1", source="ael")
        self.ls.teach("X", "d2", source="user")          # source changes with the update
        self.assertEqual(self.sig()[-1], ("teach", "X", "d2", "user"))
        self.assertEqual(self.k.get("X")["source"], "user")
        self.check_consistency()

    def test_create_correction(self):
        self.ls.teach("Python", "old", source="user")
        self.ls.correct("python", "new")                  # case-insensitive resolution, source omitted
        c = self.sig("correct")
        self.assertEqual(c, [("correct", "Python", "'old' -> 'new'", "user")])   # stored name + persisted source
        self.assertEqual(self.k.get("Python")["version"], 2)
        self.ls.correct("Python", "newer", source="user_correction")
        self.assertEqual(self.sig("correct")[-1], ("correct", "Python", "'new' -> 'newer'", "user_correction"))
        self.assertEqual(self.k.get("Python")["source"], "user_correction")
        self.check_consistency()

    def test_create_relationship_and_update(self):
        self.ls.teach("A", "a", source="user")
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.4)
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.9)   # genuine refresh
        self.assertEqual(self.sig("relate"), [("relate", "A", "is_a -> B", "user")] * 2)
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 1)
        self.check_consistency()

    def test_relate_omitted_source_logs_persisted_source(self):
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.4)
        self.ls.relate("A", "B", "is_a", source=None, confidence=0.8)
        self.assertEqual(self.sig("relate")[-1][3], "user")
        self.check_consistency()

    def test_noops_add_no_events(self):
        self.ls.teach("A", "a", source="user", confidence=0.7)
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.7)
        self.ls.correct("A", "a2", source="user")
        n, state = len(self.ev()), _dump(self.m)
        self.ls.teach("A", "a2", source="user", confidence=0.7)          # identical to current state
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.7)  # exact repeat
        self.ls.correct("A", "a2", source="user")                        # identical correction
        self.assertEqual(len(self.ev()), n)
        self.assertEqual(_dump(self.m), state)
        self.check_consistency()

    def test_stub_has_no_own_event_L1(self):
        self.ls.relate("A", "B", "is_a", source="user")
        self.assertEqual(len(self.ev()), 1)
        self.assertEqual({r["name"] for r in self.m.query("SELECT * FROM knowledge")}, {"A", "B"})
        self.ls.teach("B", "now real", source="user")     # stub -> taught: real update, real event
        self.assertEqual(self.sig("teach"), [("teach", "B", "now real", "user")])
        self.assertEqual(self.k.get("B")["version"], 2)   # stub v1 (no event) + teach v2

    def test_status_only_correction_documented_L2(self):
        self.ls.teach("A", "same", source="user")
        self.ls.correct("A", "same", source="user", confidence=0.3)       # confidence-only change
        self.assertEqual(self.k.get("A")["version"], 2)
        self.assertEqual(self.sig("correct")[-1][2], "'same' -> 'same'")

    def test_direct_knowledge_calls_write_no_events_L4(self):
        self.k.learn("Direct", "x")
        self.k.relate("Direct", "Other", "is_a")
        self.assertEqual(self.ev(), [])


class LanguageHistory(Audit):
    def test_language_item_create_update(self):
        self.ll.learn_item("fa", "word", "سلام", meaning={"m": "hi"}, source="user", source_context="c1")
        self.ll.learn_item("fa", "word", "سلام", meaning={"m": "hello"}, source="user", source_context="c2")
        self.assertEqual(self.sig(), [("language_item_learned", "persian:word:سلام", "c1", "user"),
                                      ("language_item_updated", "persian:word:سلام", "c2", "user")])
        self.check_consistency()

    def test_language_item_omitted_source_logs_persisted_source(self):
        self.ll.learn_item("en", "word", "hello", source="user", source_context="c1")
        self.ll.learn_item("en", "word", "hello", meaning={"m": 1})       # source omitted -> stored kept
        self.assertEqual(self.ll.get_item("en", "word", "hello")["source"], "user")
        self.assertEqual(self.sig()[-1][3], "user")
        self.check_consistency()

    def test_language_item_repeat_is_a_real_update(self):
        self.ll.learn_item("en", "word", "hello", source="user")
        self.ll.learn_item("en", "word", "hello", source="user")          # existing contract: not a no-op
        self.assertEqual(self.ll.get_item("en", "word", "hello")["version"], 2)
        self.assertEqual([e["event_type"] for e in self.ev()],
                         ["language_item_learned", "language_item_updated"])
        self.check_consistency()

    def test_language_relationship_create_update(self):
        self.ll.learn_item("fa", "word", "سلام", source="user")
        self.ll.learn_item("en", "word", "hello", source="user")
        a, b = item_ref("fa", "word", "سلام"), item_ref("en", "word", "hello")
        self.lr.relate(a, b, "translation", source="user", source_context="r1")
        self.lr.relate(a, b, "translation", source="user", source_context="r2", confidence=0.5)
        self.assertEqual([e[0] for e in self.sig("language_relationship_learned",
                                                 "language_relationship_updated")],
                         ["language_relationship_learned", "language_relationship_updated"])
        self.assertEqual(len(self.m.query("SELECT * FROM language_item_relationships")), 1)
        self.check_consistency()

    def test_language_relationship_omitted_source_logs_persisted_source(self):
        self.ll.learn_item("fa", "word", "سلام", source="user")
        self.ll.learn_item("en", "word", "hello", source="user")
        a, b = item_ref("fa", "word", "سلام"), item_ref("en", "word", "hello")
        self.lr.relate(a, b, "translation", source="user")
        self.lr.relate(a, b, "translation", confidence=0.3)               # source omitted
        self.assertEqual(self.m.query_one("SELECT source FROM language_item_relationships")["source"], "user")
        self.assertEqual(self.sig("language_relationship_updated")[-1][3], "user")
        self.check_consistency()

    def test_concept_endpoint_relationship(self):
        self.k.learn("Greeting", "g")
        self.ll.learn_item("en", "word", "hello", source="user")
        self.lr.relate(item_ref("en", "word", "hello"), concept_ref("Greeting"), "means", source="user")
        self.check_consistency()


class Mixed(Audit):
    def test_full_sequence_ordering_and_reopen(self):
        self.ls.teach("Python", "snake", source="user")
        self.ls.teach("Python", "language", source="user")
        self.ls.correct("Python", "programming language", source="user_correction")
        self.ls.relate("Python", "Guido", "created_by", source="user")
        self.ll.learn_item("en", "word", "python", source="user")
        self.ll.learn_item("fa", "word", "پایتون", source="user")
        self.lr.relate(item_ref("en", "word", "python"), item_ref("fa", "word", "پایتون"),
                       "translation", source="user")
        self.ll.learn_item("en", "word", "python", meaning={"m": "x"})
        expected = ["teach", "teach", "correct", "relate", "language_item_learned",
                    "language_item_learned", "language_relationship_learned", "language_item_updated"]
        self.assertEqual([e["event_type"] for e in self.ev()], expected)
        self.check_consistency()
        before = _dump(self.m)
        self.reopen()
        self.assertEqual(_dump(self.m), before)          # state AND history survive reopen unchanged
        self.check_consistency()
        self.ls.teach("Python", "final", source="user")  # ids keep increasing after reopen
        self.assertEqual(self.ev()[-1]["id"], before["learning_events"][-1]["id"] + 1)
        self.check_consistency()

    def test_events_only_for_persisted_change_under_failed_ops(self):
        self.ls.teach("A", "a", source="user")
        with self.assertRaises(ValueError):
            self.ls.teach("", "x")
        with self.assertRaises(ValueError):
            self.ls.relate("A", "", "is_a")
        with self.assertRaises(ValueError):
            self.ll.learn_item("en", "word", "  ")
        self.assertEqual(len(self.ev()), 1)
        self.check_consistency()


if __name__ == "__main__":
    unittest.main()
