"""Prompt 649 - Section 3: provenance semantics across Knowledge / Learning paths.

AUDIT, not a provenance redesign. Finding: no genuine contradiction or accidental
provenance loss; NO production change. Existing semantics (asserted below):

  P1 KnowledgeSystem.learn(): source is a plain argument defaulting to "user" and
     is REPLACED on every update (omitted == "user"); confidence / source_text /
     learning_method are None-preserving. New rows: confidence None -> 1.0.
  P2 LearningSystem.teach(): same as P1 with default source "ael" (omitted source
     on a re-teach replaces the stored source with "ael"; the other three are kept).
  P3 correct() (Knowledge and Learning): source None == KEEP the stored source;
     explicit source replaces; confidence/source_text/learning_method None-preserving;
     status None -> "active". Identical correction is a no-op (no version, no event).
     Unknown name -> None, nothing written.
  P4 relate() (Knowledge & Learning): relationship provenance columns
     (source_type/source_text/learning_method/confidence) are None-preserving;
     LearningSystem.relate() default source is "ael" (so an omitted source on
     that API is the value "ael"), KnowledgeSystem.relate() default is None (keep).
     Stub concepts auto-created by relate() take source=source_type or "inferred",
     status "stub", plus the relation's source_text/learning_method; a later
     teach() replaces source but (None-preserving) keeps that stub source_text.
  P5 Natural-language learning (learn_from_understanding): source
     "understanding_engine" (or the explicit `source`), learning_method
     "natural_language_understanding", source_text = original text.
  P6 Events: teach logs the persisted source (== the argument); correct/relate/
     language events log the PERSISTED source. Event only when state changed.
  P7 Language stores: source/source_context/learning_method/confidence are all
     None-preserving on update (unlike P1/P2).
  P8 `LearningSystem.learn()` does not exist; the equivalent paths are teach()
     and learn_from_understanding().
Intentional differences (documented, not unified): P1/P2 replace source when omitted,
P3/P4(Knowledge)/P7 keep it; teach() logs the argument (equal to persisted), others log persisted.
"""
import hashlib
import os
import tempfile
import unittest

from core.core import Core
from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.language_relationships import LanguageRelationshipStore, item_ref

PROV = ("source", "confidence", "source_text", "learning_method")
REL_PROV = ("source_type", "confidence", "source_text", "learning_method")


class Base(unittest.TestCase):
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

    def prov(self, name):
        r = self.k.get(name)
        return tuple(r[c] for c in PROV)

    def rel(self, f, t, rt):
        return self.m.query_one("SELECT * FROM relationships WHERE from_name=? AND to_name=? AND relation_type=?",
                                (f, t, rt))

    def rprov(self, f, t, rt):
        r = self.rel(f, t, rt)
        return tuple(r[c] for c in REL_PROV)

    def events(self, *types):
        return [e for e in self.m.query("SELECT * FROM learning_events ORDER BY id")
                if not types or e["event_type"] in types]


class KnowledgeLearn(Base):
    def test_new_knowledge_stores_exact_provenance(self):
        r = self.k.learn("a", "d", source="custom", confidence=0.4, source_text="st", learning_method="lm")
        self.assertEqual((r["source"], r["confidence"], r["source_text"], r["learning_method"], r["version"]),
                         ("custom", 0.4, "st", "lm", 1))

    def test_new_knowledge_defaults(self):
        r = self.k.learn("a", "d")
        self.assertEqual((r["source"], r["confidence"], r["source_text"], r["learning_method"]),
                         ("user", 1.0, None, None))

    def test_relearn_omitted_metadata_preserved_source_follows_argument(self):
        self.k.learn("a", "d1", source="custom", confidence=0.4, source_text="st", learning_method="lm")
        r = self.k.learn("a", "d2")                       # P1: source omitted == "user"
        self.assertEqual((r["source"], r["confidence"], r["source_text"], r["learning_method"], r["version"]),
                         ("user", 0.4, "st", "lm", 2))

    def test_explicit_replacement_of_all_provenance(self):
        self.k.learn("a", "d", source="s1", confidence=0.4, source_text="st", learning_method="lm")
        r = self.k.learn("a", "d", source="s2", confidence=0.9, source_text="st2", learning_method="lm2")
        self.assertEqual((r["source"], r["confidence"], r["source_text"], r["learning_method"], r["version"]),
                         ("s2", 0.9, "st2", "lm2", 2))

    def test_noop_repeat_and_omitted_metadata_repeat(self):
        a = self.k.learn("a", "d", source="s", confidence=0.4, source_text="st", learning_method="lm")
        b = self.k.learn("a", "d", source="s")            # omitted metadata == unchanged
        c = self.k.learn("a", "d", source="s", confidence=0.4, source_text="st", learning_method="lm")
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertEqual(b["version"], 1)
        self.assertEqual(b["updated_at"], a["updated_at"])

    def test_knowledge_correct_provenance_contract(self):
        self.k.learn("a", "d1", source="s1", confidence=0.4, source_text="st", learning_method="lm")
        r = self.k.correct("A", "d2")                     # omitted -> keep everything
        self.assertEqual((r["source"], r["confidence"], r["source_text"], r["learning_method"], r["version"]),
                         ("s1", 0.4, "st", "lm", 2))
        r = self.k.correct("a", "d3", source="s2", learning_method="lm2")
        self.assertEqual((r["source"], r["confidence"], r["source_text"], r["learning_method"], r["version"]),
                         ("s2", 0.4, "st", "lm2", 3))
        self.assertEqual(self.k.correct("a", "d3", source="s2"), r)   # identical -> no-op
        self.assertIsNone(self.k.correct("ghost", "x"))
        self.assertIsNone(self.k.get("ghost"))


class LearningTeachCorrect(Base):
    def test_teach_new_and_omitted_defaults(self):
        self.ls.teach("b", "x", source_text="st", learning_method="lm", confidence=0.5)
        self.assertEqual(self.prov("b"), ("ael", 0.5, "st", "lm"))

    def test_reteach_omitted_source_follows_default_others_preserved(self):
        self.ls.teach("b", "x", source="user", source_text="st", learning_method="lm", confidence=0.5)
        self.ls.teach("b", "y")
        self.assertEqual(self.prov("b"), ("ael", 0.5, "st", "lm"))      # P2
        self.assertEqual(self.k.get("b")["version"], 2)

    def test_reteach_explicit_source_replacement(self):
        self.ls.teach("b", "x", source="ael", source_text="st", learning_method="lm")
        self.ls.teach("b", "x", source="user", source_text="new")
        self.assertEqual(self.prov("b"), ("user", 1.0, "new", "lm"))

    def test_identical_reteach_noop_no_event(self):
        self.ls.teach("b", "x", source="user", confidence=0.5, source_text="st", learning_method="lm")
        before, n = self.k.get("b"), len(self.events())
        self.ls.teach("b", "x", source="user", confidence=0.5, source_text="st", learning_method="lm")
        self.ls.teach("b", "x", source="user")
        self.assertEqual(self.k.get("b"), before)
        self.assertEqual(len(self.events()), n)

    def test_correct_omitted_source_keeps_stored(self):
        self.ls.teach("b", "x", source="user", source_text="st", learning_method="lm", confidence=0.5)
        self.ls.correct("b", "y")
        self.assertEqual(self.prov("b"), ("user", 0.5, "st", "lm"))
        self.assertEqual(self.events("correct")[-1]["source"], "user")

    def test_correct_explicit_source_and_method(self):
        self.ls.teach("b", "x", source="user", source_text="st", learning_method="lm", confidence=0.5)
        self.ls.correct("B", "y", source="user_correction", source_text="fix", learning_method="explicit_correction")
        self.assertEqual(self.prov("b"), ("user_correction", 0.5, "fix", "explicit_correction"))
        self.assertEqual(self.events("correct")[-1]["source"], "user_correction")

    def test_correct_confidence_explicit_replaces_omitted_keeps(self):
        self.ls.teach("b", "x", confidence=0.5)
        self.ls.correct("b", "y")
        self.assertEqual(self.k.get("b")["confidence"], 0.5)
        self.ls.correct("b", "z", confidence=0.8)
        self.assertEqual(self.k.get("b")["confidence"], 0.8)

    def test_correct_noop_and_unknown(self):
        self.ls.teach("b", "x", source="user")
        self.ls.correct("b", "y", source="user_correction")
        before, n = self.k.get("b"), len(self.events())
        self.ls.correct("b", "y", source="user_correction")
        self.ls.correct("b", "y")
        self.assertEqual(self.k.get("b"), before)
        self.assertEqual(len(self.events()), n)
        self.assertIsNone(self.ls.correct("ghost", "x", source="user_correction"))
        self.assertEqual(len(self.events()), n)

    def test_teach_event_source_equals_persisted_source(self):
        self.ls.teach("b", "x")
        self.ls.teach("b", "y", source="user")
        self.ls.teach("b", "y", source="user", source_text="only provenance changed")
        ev = self.events("teach")
        self.assertEqual([e["source"] for e in ev], ["ael", "user", "user"])
        self.assertEqual(ev[-1]["source"], self.k.get("b")["source"])

    def test_teach_none_source_persisted_and_logged_consistently(self):
        self.ls.teach("c", "x", source=None)
        self.assertIsNone(self.k.get("c")["source"])
        self.assertIsNone(self.events("teach")[-1]["source"])

    def test_learning_system_has_no_learn_method(self):
        self.assertFalse(hasattr(LearningSystem, "learn"))                # P8
        self.assertTrue(hasattr(LearningSystem, "learn_from_understanding"))


class Relationships(Base):
    def test_relate_new_provenance_and_stubs(self):
        self.ls.relate("p", "q", "is_a", source="user", confidence=0.7, source_text="t1", learning_method="l1")
        self.assertEqual(self.rprov("p", "q", "is_a"), ("user", 0.7, "t1", "l1"))
        for n in "pq":
            r = self.k.get(n)
            self.assertEqual((r["status"], r["source"], r["source_text"], r["learning_method"]),
                             ("stub", "user", "t1", "l1"))
        self.assertEqual(self.events("relate")[-1]["source"], "user")

    def test_knowledge_relate_stub_source_inferred_when_omitted(self):
        self.k.relate("p", "q", "is_a")
        self.assertEqual(self.k.get("p")["source"], "inferred")
        self.assertEqual(self.rprov("p", "q", "is_a"), (None, None, None, None))

    def test_learning_relate_omitted_source_is_ael_others_preserved(self):
        self.ls.relate("p", "q", "is_a", source="user", confidence=0.7, source_text="t1", learning_method="l1")
        self.ls.relate("p", "q", "is_a")                                  # P4: default source "ael"
        self.assertEqual(self.rprov("p", "q", "is_a"), ("ael", 0.7, "t1", "l1"))
        self.assertEqual(self.events("relate")[-1]["source"], "ael")

    def test_knowledge_relate_omitted_provenance_all_preserved(self):
        self.ls.relate("p", "q", "is_a", source="user", confidence=0.7, source_text="t1", learning_method="l1")
        self.k.relate("p", "q", "is_a")
        self.assertEqual(self.rprov("p", "q", "is_a"), ("user", 0.7, "t1", "l1"))

    def test_relate_explicit_replacement_and_event_matches_persisted(self):
        self.ls.relate("p", "q", "is_a", source="user", source_text="t1", learning_method="l1")
        self.ls.relate("p", "q", "is_a", source="import", confidence=0.2, source_text="t2", learning_method="l2")
        self.assertEqual(self.rprov("p", "q", "is_a"), ("import", 0.2, "t2", "l2"))
        self.assertEqual(self.events("relate")[-1]["source"], self.rel("p", "q", "is_a")["source_type"])

    def test_relate_repeat_noop(self):
        self.ls.relate("p", "q", "is_a", source="user", confidence=0.7, source_text="t1", learning_method="l1")
        row, n = self.rel("p", "q", "is_a"), len(self.events())
        self.ls.relate("p", "q", "is_a", source="user", confidence=0.7, source_text="t1", learning_method="l1")
        self.ls.relate("p", "q", "is_a", source="user")
        self.assertEqual(self.rel("p", "q", "is_a"), row)
        self.assertEqual(len(self.events()), n)

    def test_taught_stub_replaces_source_keeps_stub_source_text(self):
        self.ls.relate("p", "q", "is_a", source="user", source_text="t1", learning_method="l1")
        self.ls.teach("p", "real")                                        # documented, intentional
        r = self.k.get("p")
        self.assertEqual((r["status"], r["source"], r["source_text"], r["learning_method"]),
                         ("active", "ael", "t1", "l1"))


class NaturalLanguageAndCorrection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.core = Core(memory_db_path=os.path.join(self.tmp, "c.db"),
                         skill_definitions_dir=os.path.join(self.tmp, "s"))

    def test_nl_learning_provenance(self):
        r = self.core.learn_from_text("Python is a language.")
        self.assertTrue(r.success)
        rel = self.core.memory.query_one("SELECT * FROM relationships")
        self.assertEqual((rel["source_type"], rel["learning_method"], rel["source_text"], rel["confidence"]),
                         ("understanding_engine", "natural_language_understanding",
                          "Python is a language.", 0.85))
        for n in ("Python", "language"):
            k = self.core.knowledge.get(n)
            self.assertEqual((k["source"], k["learning_method"], k["source_text"]),
                             ("understanding_engine", "natural_language_understanding", "Python is a language."))
        ev = self.core.memory.recent_learning_events()
        self.assertEqual([(e["event_type"], e["source"]) for e in ev], [("relate", "understanding_engine")])
        self.assertEqual(ev[0]["source"], rel["source_type"])

    def test_nl_learning_repeat_is_noop_and_explicit_source_kept(self):
        self.core.learn_from_text("Python is a language.")
        rel, n = self.core.memory.query_one("SELECT * FROM relationships"), len(self.core.memory.recent_learning_events())
        self.core.learn_from_text("Python is a language.")
        self.assertEqual(self.core.memory.query_one("SELECT * FROM relationships"), rel)
        self.assertEqual(len(self.core.memory.recent_learning_events()), n)
        self.core.learning.learn_from_understanding(self.core.understand("Rust is a language."), source="custom")
        self.assertEqual(self.core.memory.query_one(
            "SELECT * FROM relationships WHERE from_name='Rust'")["source_type"], "custom")

    def test_nl_learning_does_not_erase_taught_provenance(self):
        self.core.learning.teach("Python", "a snake", source="user", confidence=0.6,
                                 source_text="Python is a snake.", learning_method="ael")
        self.core.learn_from_text("Python is a language.")
        k = self.core.knowledge.get("Python")
        self.assertEqual((k["source"], k["confidence"], k["source_text"], k["learning_method"], k["description"]),
                         ("user", 0.6, "Python is a snake.", "ael", "a snake"))

    def test_explicit_correction_provenance_and_confidence(self):
        self.core.learning.teach("Python", "a snake", source="user", confidence=0.6,
                                 source_text="Python is a snake.", learning_method="ael")
        self.core.process_input("not a snake, I mean a programming language.")
        k = self.core.knowledge.get("Python")
        self.assertEqual((k["source"], k["learning_method"], k["source_text"], k["confidence"], k["version"]),
                         ("user_correction", "explicit_correction",
                          "not a snake, I mean a programming language.", 0.6, 2))
        ev = [e for e in self.core.memory.recent_learning_events() if e["event_type"] == "correct"]
        self.assertEqual([e["source"] for e in ev], ["user_correction"])


class LanguagePaths(Base):
    def test_language_item_none_preserving_provenance(self):
        self.ll.learn_item("en", "word", "hello", meaning="greeting", confidence=0.6, source="user",
                           source_context="c1", learning_method="lm")
        it = self.ll.learn_item("en", "word", "hello", meaning="greeting!")
        self.assertEqual((it["source"], it["confidence"], it["source_context"], it["learning_method"]),
                         ("user", 0.6, "c1", "lm"))
        self.assertEqual(self.events("language_item_updated")[-1]["source"], "user")
        it = self.ll.learn_item("en", "word", "hello", source="import", source_context="c2", learning_method="lm2")
        self.assertEqual((it["source"], it["source_context"], it["learning_method"]), ("import", "c2", "lm2"))
        self.assertEqual(self.events("language_item_updated")[-1]["source"], "import")

    def test_language_relationship_none_preserving_provenance(self):
        self.ll.learn_item("fa", "word", "salam", meaning="hi")
        self.ll.learn_item("en", "word", "hello", meaning="hi")
        a, b = item_ref("fa", "word", "salam"), item_ref("en", "word", "hello")
        self.lr.relate(a, b, "translation", source="user", source_context="c1", confidence=0.5, learning_method="lm")
        self.lr.relate(a, b, "translation")
        row = self.m.query_one("SELECT * FROM language_item_relationships")
        self.assertEqual((row["source"], row["source_context"], row["confidence"], row["learning_method"]),
                         ("user", "c1", 0.5, "lm"))
        self.assertEqual(self.events("language_relationship_updated")[-1]["source"], "user")


class ReopenAndReadOnly(Base):
    def seed(self):
        self.ls.teach("b", "x", source="user", confidence=0.5, source_text="st", learning_method="lm")
        self.ls.correct("b", "y", source="user_correction", learning_method="explicit_correction")
        self.ls.relate("b", "c", "is_a", source="user", confidence=0.7, source_text="t1", learning_method="l1")
        self.ll.learn_item("en", "word", "hello", meaning="m", source="user", source_context="c", learning_method="lm")

    def snapshot(self):
        return {t: self.m.query(f"SELECT * FROM {t} ORDER BY id")
                for t in ("knowledge", "relationships", "language_learning_items", "learning_events")}

    def test_reopen_preserves_provenance_exactly(self):
        self.seed()
        before = self.snapshot()
        self.reopen()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.prov("b"), ("user_correction", 0.5, "st", "explicit_correction"))
        self.assertEqual(self.rprov("b", "c", "is_a"), ("user", 0.7, "t1", "l1"))
        self.reopen()
        self.assertEqual(self.snapshot(), before)

    def test_reads_do_not_mutate_provenance(self):
        self.seed()
        self.m._conn.commit()
        before = self.snapshot()
        def h():
            with open(self.db, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        digest = h()
        self.k.get("b"); self.k.all(); self.k.search("y"); self.k.resolve_name("B")
        self.k.find_by_name_case_insensitive("B"); self.k.relationships_for("b")
        self.ls.recall("b"); self.ls.search("y")
        self.ll.get_item("en", "word", "hello"); self.m.recent_learning_events()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(h(), digest)

    def test_event_sources_never_contradict_persisted_rows(self):
        self.seed()
        self.ls.correct("b", "z")                                         # omitted source
        self.ls.relate("b", "c", "is_a")                                  # omitted source (-> ael)
        self.ll.learn_item("en", "word", "hello")                         # omitted source
        last = {}
        for e in self.events():
            last[(e["event_type"], e["target"])] = e["source"]
        self.assertEqual(last[("correct", "b")], self.k.get("b")["source"])
        self.assertEqual(last[("relate", "b")], self.rel("b", "c", "is_a")["source_type"])
        it = self.ll.get_item("en", "word", "hello")
        self.assertEqual(last[("language_item_updated", f"{it['language']}:word:hello")], it["source"])


if __name__ == "__main__":
    unittest.main()
