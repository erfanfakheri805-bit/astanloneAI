"""Prompt 643 - Section 3: natural-language learning integrity.

Inspection result: production code UNCHANGED. The existing pipeline
(Core.learn_from_text -> understand() -> LearningSystem.learn_from_understanding
-> LearningSystem.relate) already satisfies the requirements; this file is
regression coverage + documentation.

Existing behaviour pinned here:
* Non-learning input (questions, greetings, unrelated statements, fragments,
  blank) yields success=True with the warning "no_learnable_candidates" and
  writes nothing (no knowledge, relationship, event rows).
* A valid fact (e.g. "Python is a language.") persists ONE relationship
  (IS_A, confidence 0.85, source "understanding_engine", learning_method
  "natural_language_understanding", source_text = the original text). Its two
  endpoint concepts are created as status="stub" rows with description None:
  the relationship API explicitly requires endpoints to exist.
* Re-learning the identical text is a true no-op (no rows, versions,
  timestamps or events change).
* Explicit corrections are handled by Core.process_input (Prompt 634), not
  learn_from_text; a correction updates the existing record and creates no
  new knowledge row.
* AEL TEACH/RELATE keep their own semantics (source "ael").

Documented limitations (contracts preserved, nothing changed):
  L1. A cosmetic variant of the same fact ("python is a language",
      no trailing period, different casing) resolves to the same concepts and
      the same relationship, but its source_text differs, so under the
      Prompt 636/641 metadata semantics it is a real provenance refresh:
      relationship.source_text/updated_at move and one "relate" event is
      logged. No duplicate row is created.
  L2. NL-learned concepts are stubs (description None) until taught.
  L3. Repeating an identical correction leaves knowledge untouched but
      bumps the language_learning_items row version/updated_at and logs a
      "language_item_updated" event (Section 2 language store behaviour).
  L4. learn_from_text() does not apply corrections
      ("not a snake, I mean ..." -> no_learnable_candidates there).
"""
import os
import tempfile
import unittest

from core.core import Core


def _core(tmp, name="c.db"):
    return Core(memory_db_path=os.path.join(tmp, name),
                skill_definitions_dir=os.path.join(tmp, "skills"))


def _tables(core):
    m = core.memory
    return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("knowledge", "relationships", "learning_events", "language_learning_items")}


class TestNaturalLanguageLearningIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.core = _core(self.tmp)

    def _learn(self, text):
        return self.core.learn_from_text(text)

    # ---- valid learning ----------------------------------------------
    def test_valid_learning_produces_expected_knowledge_and_provenance(self):
        r = self._learn("Python is a language.")
        self.assertTrue(r.success)
        self.assertEqual([(i["subject"], i["relation"], i["object"]) for i in r.learned_items],
                         [("Python", "IS_A", "language")])
        self.assertEqual(sorted(r.created_concepts), ["Python", "language"])
        t = _tables(self.core)
        self.assertEqual(len(t["relationships"]), 1)
        rel = t["relationships"][0]
        self.assertEqual((rel["from_name"], rel["relation_type"], rel["to_name"]),
                         ("Python", "IS_A", "language"))
        self.assertEqual(rel["confidence"], 0.85)
        self.assertEqual(rel["source_type"], "understanding_engine")
        self.assertEqual(rel["source_text"], "Python is a language.")
        self.assertEqual(rel["learning_method"], "natural_language_understanding")
        for k in t["knowledge"]:
            self.assertEqual(k["status"], "stub")          # L2
            self.assertIsNone(k["description"])
            self.assertEqual(k["source"], "understanding_engine")
            self.assertEqual(k["source_text"], "Python is a language.")
            self.assertEqual(k["learning_method"], "natural_language_understanding")
            self.assertEqual(k["version"], 1)
        self.assertEqual([(e["event_type"], e["target"], e["source"]) for e in t["learning_events"]],
                         [("relate", "Python", "understanding_engine")])

    def test_explicit_source_is_not_replaced_by_generic_value(self):
        r = self.core.learning.learn_from_understanding(
            self.core.understand("Python is a language."), source="custom_source")
        self.assertTrue(r.success)
        rel = _tables(self.core)["relationships"][0]
        self.assertEqual(rel["source_type"], "custom_source")
        self.assertEqual(rel["source_text"], "Python is a language.")

    def test_existing_taught_knowledge_is_not_overwritten_by_nl_learning(self):
        self.core.learning.teach("Python", "a snake", source="ael", confidence=0.6,
                                 source_text="Python is a snake.", learning_method="ael")
        before = self.core.knowledge.get("Python")
        self._learn("Python is a language.")
        after = self.core.knowledge.get("Python")
        self.assertEqual(after, before)                     # description/source/version untouched
        self.assertEqual(len([k for k in self.core.knowledge.all() if k["name"] == "Python"]), 1)

    # ---- repeated learning ---------------------------------------------
    def test_repeated_identical_nl_learning_is_true_noop(self):
        self._learn("Python is a language.")
        before = _tables(self.core)
        for _ in range(3):
            r = self._learn("Python is a language.")
            self.assertTrue(r.success)
            self.assertEqual(r.created_concepts, [])
            self.assertEqual(r.created_relationships, [])
        self.assertEqual(_tables(self.core), before)

    def test_cosmetic_variant_refreshes_metadata_without_duplicates_L1(self):
        self._learn("Python is a language.")
        self._learn("python is a language")
        t = _tables(self.core)
        self.assertEqual(len(t["knowledge"]), 2)
        self.assertEqual(len(t["relationships"]), 1)
        self.assertEqual(t["relationships"][0]["source_text"], "python is a language")
        self.assertEqual(t["relationships"][0]["confidence"], 0.85)
        self.assertEqual([k["version"] for k in t["knowledge"]], [1, 1])
        # the same variant again is a no-op
        before = _tables(self.core)
        self._learn("python is a language")
        self.assertEqual(_tables(self.core), before)

    # ---- non-learning / incomplete / blank input -----------------------
    def _assert_rejected(self, text):
        before = _tables(self.core)
        r = self._learn(text)
        self.assertTrue(r.success, text)
        self.assertEqual(r.learned_items, [], text)
        self.assertEqual(r.created_concepts, [], text)
        self.assertIn("no_learnable_candidates", r.warnings, text)
        self.assertEqual(_tables(self.core), before, text)   # rows, versions, timestamps, events

    def test_rejected_inputs_write_nothing_on_empty_store(self):
        for text in ("What is Python?", "Tell me about Python", "Hello", "Hi there, how are you?",
                     "The weather is nice today.", "Python is", "is a language", "Python is a",
                     "a is b", "Python", "Remember that", "?", "", "   ", "\n"):
            self._assert_rejected(text)
        t = _tables(self.core)
        self.assertEqual((t["knowledge"], t["relationships"], t["learning_events"]), ([], [], []))

    def test_rejected_inputs_leave_existing_rows_unchanged(self):
        self._learn("Python is a language.")
        self.core.learning.teach("Rust", "a systems language")
        for text in ("What is Python?", "Hello", "Python is", "", "   ", "The weather is nice today."):
            self._assert_rejected(text)

    def test_no_empty_names_descriptions_or_placeholder_rows(self):
        for text in ("Python is", "is a language", "", "   ", "?", "Python is a"):
            self._learn(text)
        self.assertEqual(self.core.knowledge.all(), [])

    def test_process_input_non_learning_and_blank_create_no_knowledge(self):
        before = _tables(self.core)
        for text in ("Hello", "What is Python?", "", "   "):
            self.core.process_input(text)
        after = _tables(self.core)
        for k in ("knowledge", "relationships", "learning_events"):
            self.assertEqual(after[k], before[k])

    # ---- correction vs learning ------------------------------------------
    def test_correction_updates_existing_record_and_is_not_new_learning(self):
        self.core.learning.teach("Python", "a snake", confidence=0.6,
                                 source_text="Python is a snake.", learning_method="ael")
        before_rows = len(self.core.knowledge.all())
        reply = self.core.process_input("not a snake, I mean a programming language.")
        self.assertIn("CORRECTION", reply.upper())
        rec = self.core.knowledge.get("Python")
        self.assertEqual(rec["description"], "a programming language")
        self.assertEqual(rec["source"], "user_correction")
        self.assertEqual(rec["learning_method"], "explicit_correction")
        self.assertEqual(rec["version"], 2)
        self.assertEqual(len(self.core.knowledge.all()), before_rows)
        self.assertEqual(self.core.knowledge.search("snake"), [])
        ev = [e for e in _tables(self.core)["learning_events"] if e["event_type"] == "correct"]
        self.assertEqual(len(ev), 1)

    def test_repeated_correction_leaves_knowledge_untouched_L3(self):
        self.core.learning.teach("Python", "a snake")
        self.core.process_input("not a snake, I mean a programming language.")
        before = _tables(self.core)
        self.core.process_input("not a snake, I mean a programming language.")
        after = _tables(self.core)
        self.assertEqual(after["knowledge"], before["knowledge"])
        self.assertEqual(after["relationships"], before["relationships"])
        self.assertEqual([e for e in after["learning_events"] if e["event_type"] == "correct"],
                         [e for e in before["learning_events"] if e["event_type"] == "correct"])

    def test_learn_from_text_does_not_treat_correction_as_new_knowledge_L4(self):
        self.core.learning.teach("Python", "a snake")
        before = _tables(self.core)
        r = self._learn("not a snake, I mean a programming language.")
        self.assertEqual(r.learned_items, [])
        self.assertEqual(_tables(self.core), before)

    # ---- AEL remains intact -----------------------------------------------
    def test_ael_teach_and_relate_semantics_intact(self):
        self.core.process_input("TEACH Rust IS a systems language")
        rec = self.core.knowledge.get("Rust")
        self.assertEqual((rec["description"], rec["source"], rec["version"]),
                         ("a systems language", "ael", 1))
        before = _tables(self.core)
        self.core.process_input("TEACH Rust IS a systems language")       # no-op
        self.assertEqual(_tables(self.core)["knowledge"], before["knowledge"])
        self.assertEqual(_tables(self.core)["learning_events"], before["learning_events"])
        self.core.process_input("RELATE Rust TO Language AS is_a")
        self.core.process_input("RELATE Rust TO Language AS is_a")        # no duplicate
        t = _tables(self.core)
        self.assertEqual(len(t["relationships"]), 1)
        self.assertEqual(len([e for e in t["learning_events"] if e["event_type"] == "relate"]), 1)

    def test_ael_invalid_input_creates_nothing(self):
        before = _tables(self.core)
        for text in ("TEACH Rust IS", "TEACH IS x", "RELATE Rust TO", 'TEACH "" "x"'):
            self.core.process_input(text)
        after = _tables(self.core)
        for k in ("knowledge", "relationships", "learning_events"):
            self.assertEqual(after[k], before[k])

    def test_nl_and_ael_relationship_coexist_without_cross_change(self):
        self.core.process_input("RELATE Rust TO Language AS is_a")
        ael_rel = [dict(r) for r in self.core.memory.query("SELECT * FROM relationships ORDER BY id")]
        self._learn("Python is a language.")
        rels = [dict(r) for r in self.core.memory.query("SELECT * FROM relationships ORDER BY id")]
        self.assertEqual(rels[0], ael_rel[0])
        self.assertEqual(len(rels), 2)

    # ---- persistence ---------------------------------------------------------
    def test_valid_learning_survives_reopen_and_repeat_is_still_noop(self):
        self._learn("Python is a language.")
        self.core.memory._conn.close()
        core2 = _core(self.tmp)
        before = _tables(core2)
        self.assertEqual(len(before["relationships"]), 1)
        self.assertEqual(before["relationships"][0]["source_text"], "Python is a language.")
        core2.learn_from_text("Python is a language.")
        self.assertEqual(_tables(core2), before)
        core2.memory._conn.close()

    def test_rejected_input_leaves_no_persistent_artifacts(self):
        for text in ("What is Python?", "Hello", "Python is", "", "   "):
            self._learn(text)
        self.core.memory._conn.close()
        core2 = _core(self.tmp)
        t = _tables(core2)
        self.assertEqual((t["knowledge"], t["relationships"], t["learning_events"]), ([], [], []))
        core2.memory._conn.close()

    # ---- preview mode ------------------------------------------------------------
    def test_auto_commit_false_writes_nothing(self):
        before = _tables(self.core)
        r = self.core.learn_from_text("Python is a language.", auto_commit=False)
        self.assertEqual(r.learned_items, [])
        self.assertEqual(_tables(self.core), before)


if __name__ == "__main__":
    unittest.main()
