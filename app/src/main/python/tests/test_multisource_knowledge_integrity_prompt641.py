"""Prompt 641 - Section 3: multi-source knowledge integrity.

Inspection result (production code unchanged - existing behaviour already
satisfies the requirements; these are regression tests + documentation):

* One CURRENT knowledge row per exact name. Learning the same name from
  another source updates that row in place (version bump); it never adds
  a second row.
* KnowledgeSystem.learn() semantics: `source` is ALWAYS replaced by the
  value passed (learn() defaults "user", LearningSystem.teach() defaults
  "ael"); `confidence` / `source_text` / `learning_method` keep the stored
  value when omitted (None). correct() keeps the stored source when
  `source` is None.
* Identical repeat (same effective values) is a true no-op: no version
  bump, no timestamp churn, no learning event.

Documented limitations (public contract preserved, nothing redesigned):
  L1. teach()'s default source="ael" means an OMITTED source on teach()
      replaces a stored source with "ael" (source is not None-preserving
      in learn()/teach(); it is in correct()).
  L2. Superseded sources/source_text are not kept anywhere except, for
      `source`, the learning_events.source column of the earlier event.
      source_text/learning_method changes are not in the event payload.
  L3. (Resolved in Prompt 644) A correct() event's `source` column used to
      record the raw argument (None when omitted); it now records the
      persisted source, which correct() preserves when omitted.
  L4. A source_text-only change bumps version and logs a teach event whose
      detail (the description) is identical to the previous event's.
"""
import os
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from language_intelligence.learned_knowledge_context import (
    select_learned_knowledge, STATUS_SELECTED)


def _stack(db):
    m = MemorySystem(db)
    k = KnowledgeSystem(m)
    return m, k, LearningSystem(ConceptSystem(k), k, memory=m)


def _dump(m):
    return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("knowledge", "relationships", "learning_events")}


class TestMultiSourceKnowledgeIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "m.db")
        self.m, self.k, self.l = _stack(self.db)

    def _base(self):
        return self.l.teach("Python", "a language", source="wiki", confidence=0.7,
                            source_text="From wiki.", learning_method="ael")

    def _events(self, target="Python"):
        return self.m.query("SELECT * FROM learning_events WHERE target = ? ORDER BY id", (target,))

    def _rows(self, name="Python"):
        return self.m.query("SELECT * FROM knowledge WHERE name = ?", (name,))

    # 1. same knowledge, same source -> true no-op
    def test_same_knowledge_same_source_is_noop(self):
        e1 = self._base()
        e2 = self.l.teach("Python", "a language", source="wiki")
        self.assertEqual(e2["version"], e1["version"])
        self.assertEqual(e2["updated_at"], e1["updated_at"])
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(len(self._events()), 1)

    def test_true_noop_with_identical_full_provenance_adds_no_event(self):
        self._base()
        self.l.teach("Python", "a language", source="wiki", confidence=0.7,
                     source_text="From wiki.", learning_method="ael")
        self.assertEqual(len(self._events()), 1)

    # 2. different source -> in-place update, no duplicate row
    def test_same_knowledge_different_source_updates_in_place(self):
        e1 = self._base()
        e2 = self.l.teach("Python", "a language", source="book")
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(e2["id"], e1["id"])
        self.assertEqual(e2["version"], e1["version"] + 1)
        self.assertEqual(e2["source"], "book")
        self.assertEqual(e2["created_at"], e1["created_at"])
        # omitted metadata is preserved
        self.assertEqual((e2["confidence"], e2["source_text"], e2["learning_method"]),
                         (0.7, "From wiki.", "ael"))

    # 3. different source_text
    def test_same_knowledge_different_source_text(self):
        e1 = self._base()
        e2 = self.l.teach("Python", "a language", source="wiki", source_text="From a book.")
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(e2["version"], e1["version"] + 1)
        self.assertEqual(e2["source_text"], "From a book.")
        self.assertEqual(e2["source"], "wiki")

    # 4. omitted provenance
    def test_omitted_optional_provenance_preserved_on_learn(self):
        self.k.learn("Rust", "a language", source="wiki", confidence=0.6,
                     source_text="R text", learning_method="ael")
        r = self.k.learn("Rust", "a systems language", source="wiki")
        self.assertEqual((r["confidence"], r["source_text"], r["learning_method"]),
                         (0.6, "R text", "ael"))
        self.assertEqual(r["version"], 2)

    def test_omitted_source_on_teach_uses_documented_default_L1(self):
        self._base()
        r = self.l.teach("Python", "a language")
        self.assertEqual(r["source"], "ael")  # existing contract: source always replaced
        self.assertEqual(r["source_text"], "From wiki.")
        self.assertEqual(len(self._rows()), 1)

    # 5. explicit provenance follows current semantics
    def test_explicit_provenance_replaces(self):
        self._base()
        r = self.l.teach("Python", "a language", source="book", confidence=0.9,
                         source_text="B", learning_method="nlu")
        self.assertEqual((r["source"], r["confidence"], r["source_text"], r["learning_method"]),
                         ("book", 0.9, "B", "nlu"))

    # 6. correction
    def test_correction_preserves_provenance_when_omitted(self):
        self._base()
        r = self.l.correct("Python", "a programming language")
        self.assertEqual((r["source"], r["confidence"], r["source_text"], r["learning_method"]),
                         ("wiki", 0.7, "From wiki.", "ael"))
        self.assertEqual(len(self._rows()), 1)

    def test_correction_explicit_provenance_updates(self):
        self._base()
        r = self.l.correct("Python", "a programming language", source="user_correction",
                           confidence=0.95, source_text="Correction.",
                           learning_method="explicit_correction")
        self.assertEqual((r["source"], r["confidence"], r["source_text"], r["learning_method"]),
                         ("user_correction", 0.95, "Correction.", "explicit_correction"))
        self.assertEqual(len(self._rows()), 1)

    def test_identical_correction_is_noop(self):
        self._base()
        c1 = self.l.correct("Python", "a programming language")
        n = len(self._events())
        c2 = self.l.correct("Python", "a programming language")
        self.assertEqual(c2["version"], c1["version"])
        self.assertEqual(len(self._events()), n)

    # 7. no duplicate current rows, many sources
    def test_many_sources_never_duplicate_current_row(self):
        for s in ("wiki", "book", "user", "ael", "web"):
            self.l.teach("Python", "a language", source=s)
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(len([r for r in self.k.all() if r["name"] == "Python"]), 1)
        self.assertEqual(self.k.get("Python")["source"], "web")

    # 8. events
    def test_real_source_change_logs_one_event_with_new_source(self):
        self._base()
        self.l.teach("Python", "a language", source="book")
        ev = self._events()
        self.assertEqual([e["event_type"] for e in ev], ["teach", "teach"])
        self.assertEqual([e["source"] for e in ev], ["wiki", "book"])

    def test_source_text_only_change_event_limitation_L2_L4(self):
        self._base()
        self.l.teach("Python", "a language", source="wiki", source_text="Other text")
        ev = self._events()
        self.assertEqual(len(ev), 2)
        self.assertEqual(ev[0]["detail"], ev[1]["detail"])
        self.assertNotIn("Other text", repr([dict(e) for e in ev]))

    def test_correction_event_source_is_persisted_source_L3(self):
        self._base()
        self.l.correct("Python", "a programming language")
        ev = self._events()[-1]
        self.assertEqual(ev["event_type"], "correct")
        self.assertEqual(ev["source"], "wiki")  # Prompt 644: persisted source
        self.assertEqual(self.k.get("Python")["source"], "wiki")

    # 9. retrieval/context: current only, read-only
    def test_retrieval_exposes_only_current_record(self):
        self._base()
        self.l.teach("Python", "a language", source="book", source_text="From book.")
        cur = self.k.get("Python")
        self.assertEqual((cur["source"], cur["source_text"]), ("book", "From book."))
        self.assertEqual([r["name"] for r in self.k.search("Python")], ["Python"])
        self.assertEqual(self.k.search("Python")[0]["source"], "book")
        self.assertEqual(self.k.find_by_name_case_insensitive("python")["source"], "book")
        self.assertEqual(self.l.recall("Python")["source"], "book")

    def test_context_exposes_current_provenance_only(self):
        self._base()
        self.l.teach("Python", "a language", source="book", source_text="From book.")
        s = select_learned_knowledge("Tell me about Python", self.k, candidate_terms=["python"])
        self.assertEqual(s.status, STATUS_SELECTED)
        self.assertEqual(s.record, self.k.get("Python"))
        text = repr(s.to_context())
        self.assertNotIn("From wiki.", text)
        self.assertNotIn("wiki", text)

    def test_historical_events_are_not_current_knowledge(self):
        self._base()
        self.l.correct("Python", "a programming language")
        names = [r["name"] for r in self.k.all()]
        self.assertEqual(names, ["Python"])
        old = [e for e in self._events() if "a language" in (e["detail"] or "")]
        self.assertTrue(old)
        self.assertEqual(self.k.search("language")[0]["description"], "a programming language")

    def test_retrieval_and_context_are_read_only_and_deterministic(self):
        self._base()
        self.l.teach("Python", "a language", source="book")
        before = _dump(self.m)
        outs = []
        for _ in range(3):
            self.k.get("Python")
            self.k.search("Python language")
            self.k.all()
            self.k.resolve_name("python")
            self.l.recall("Python")
            s = select_learned_knowledge("Python?", self.k, candidate_terms=["python"])
            outs.append(repr(s.to_context()))
        self.assertEqual(len(set(outs)), 1)
        self.assertEqual(_dump(self.m), before)

    # 10. relationships
    def test_relationships_intact_and_idempotent_across_sources(self):
        self._base()
        self.l.teach("Snake", "an animal", source="wiki")
        self.l.relate("Python", "Snake", "related_to", source="wiki", confidence=0.5,
                      source_text="rel text", learning_method="ael")
        self.l.relate("Snake", "Animal", "is_a", source="wiki")
        rel_before = [dict(r) for r in self.m.query("SELECT * FROM relationships ORDER BY id")]
        n_events = len(self.m.query("SELECT * FROM learning_events WHERE event_type = 'relate'"))

        self.l.teach("Python", "a language", source="book")            # new source
        self.l.teach("Python", "a language", source="book", source_text="x")  # new text
        self.l.correct("Python", "a programming language", source="user_correction")

        rel_after = [dict(r) for r in self.m.query("SELECT * FROM relationships ORDER BY id")]
        self.assertEqual(rel_after, rel_before)  # no dup, no reset, no rewrite of any row
        self.assertEqual(len(self.m.query(
            "SELECT * FROM learning_events WHERE event_type = 'relate'")), n_events)

        # Prompt 636 idempotency still holds afterwards
        self.l.relate("Python", "Snake", "related_to", source="wiki", confidence=0.5,
                      source_text="rel text", learning_method="ael")
        self.assertEqual([dict(r) for r in self.m.query(
            "SELECT * FROM relationships ORDER BY id")], rel_before)
        self.assertEqual(len(self.m.query(
            "SELECT * FROM learning_events WHERE event_type = 'relate'")), n_events)

    def test_relate_omitted_metadata_preserved_after_source_change(self):
        self._base()
        self.l.relate("Python", "Snake", "related_to", source="wiki", confidence=0.5,
                      source_text="rel text", learning_method="ael")
        self.l.teach("Python", "a language", source="book")
        self.l.relate("Python", "Snake", "related_to", source="wiki")
        r = self.m.query_one("SELECT * FROM relationships WHERE from_name='Python'")
        self.assertEqual((r["confidence"], r["source_text"], r["learning_method"]),
                         (0.5, "rel text", "ael"))

    # 11. persistence
    def test_multisource_behaviour_survives_reopen(self):
        self._base()
        self.l.teach("Python", "a language", source="book", source_text="From book.")
        self.l.relate("Python", "Snake", "related_to", source="wiki", confidence=0.5)
        self.l.correct("Python", "a programming language", source="user_correction",
                       source_text="Correction.", learning_method="explicit_correction")
        self.m._conn.close()

        m2, k2, l2 = _stack(self.db)
        r = k2.get("Python")
        self.assertEqual((r["source"], r["source_text"], r["learning_method"], r["confidence"],
                          r["description"], r["version"]),
                         ("user_correction", "Correction.", "explicit_correction", 0.7,
                          "a programming language", 3))
        self.assertEqual(len(m2.query("SELECT * FROM knowledge WHERE name='Python'")), 1)
        n_ev = len(m2.query("SELECT * FROM learning_events"))
        # true no-ops after reopen remain no-ops
        l2.teach("Python", "a programming language", source="user_correction")
        l2.correct("Python", "a programming language")
        self.assertEqual(len(m2.query("SELECT * FROM learning_events")), n_ev)
        self.assertEqual(k2.get("Python")["version"], 3)
        self.assertEqual(len(m2.query("SELECT * FROM relationships")), 1)
        # new source after reopen still updates in place
        l2.teach("Python", "a programming language", source="web")
        self.assertEqual(k2.get("Python")["source"], "web")
        self.assertEqual(len(m2.query("SELECT * FROM knowledge WHERE name='Python'")), 1)


if __name__ == "__main__":
    unittest.main()
