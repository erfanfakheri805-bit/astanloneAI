"""Prompt 635 - Section 3: provenance/source metadata integrity for
persisted knowledge.

Gap found: LearningSystem.correct() (the wrapper virtually every
caller uses, including Core._apply_resolved_correction_to_knowledge)
defaulted `source="user"` instead of `source=None`. KnowledgeSystem.
correct() already documents and implements "None = keep what is
stored" for source/confidence/source_text/learning_method - the same
"don't overwrite what's already there unless explicitly told to"
policy KnowledgeSystem.learn() uses for confidence/source_text/
learning_method. Because the wrapper's default was the literal string
"user" rather than None, every call to `learning.correct(name, desc)`
that didn't pass `source=` explicitly silently clobbered the record's
real provenance (e.g. "ael") with "user" - even though nothing about
the call asked for that. This was invisible to the Prompt 633 tests
only because their fixture happened to teach with source="user" in
the first place, so the accidental overwrite matched the original
value by coincidence.

Fix: LearningSystem.correct()'s `source` parameter now defaults to
None, so an unspecified source falls through to KnowledgeSystem.
correct()'s existing preserve-if-None semantics. Any caller that
wants a specific source attributed to the correction (Core's explicit-
correction path passes source="user_correction") is completely
unaffected - this only stops an *unspecified* source from being
treated as if it had been explicitly supplied.
"""
import os
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from core.core import Core


def _stack(db):
    m = MemorySystem(db)
    k = KnowledgeSystem(m)
    return m, k, LearningSystem(ConceptSystem(k), k, memory=m)


class TestKnowledgeProvenanceIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "m.db")
        self.m, self.k, self.l = _stack(self.db)

    # ------------------------------------------------------------------
    # 1. new learned knowledge has correct provenance
    # ------------------------------------------------------------------
    def test_new_learned_knowledge_has_correct_provenance(self):
        e = self.l.teach("Python", "a snake", source="ael", confidence=0.6,
                          source_text="Python is a snake.", learning_method="ael")
        self.assertEqual(e["source"], "ael")
        self.assertEqual(e["confidence"], 0.6)
        self.assertEqual(e["source_text"], "Python is a snake.")
        self.assertEqual(e["learning_method"], "ael")
        self.assertEqual(e["version"], 1)

    # ------------------------------------------------------------------
    # 2. explicit correction has correct provenance
    # ------------------------------------------------------------------
    def test_explicit_correction_gets_its_own_supplied_provenance(self):
        self.l.teach("Python", "a snake", source="ael", confidence=0.6,
                     source_text="Python is a snake.", learning_method="ael")
        e = self.l.correct("Python", "a programming language", source="user_correction",
                            confidence=0.95, source_text="Correction from user.",
                            learning_method="explicit_correction")
        self.assertEqual(e["source"], "user_correction")
        self.assertEqual(e["confidence"], 0.95)
        self.assertEqual(e["source_text"], "Correction from user.")
        self.assertEqual(e["learning_method"], "explicit_correction")

    def test_core_correction_pipeline_source_is_user_correction(self):
        skills = os.path.join(self.tmp, "s")
        core = Core(memory_db_path=os.path.join(self.tmp, "c.db"), skill_definitions_dir=skills)
        core.learning.teach("Python", "a snake", confidence=0.6,
                             source_text="Python is a snake.", learning_method="ael")
        core.process_input("not a snake, I mean a programming language.")
        rec = core.knowledge.get("Python")
        self.assertEqual(rec["source"], "user_correction")
        self.assertEqual(rec["learning_method"], "explicit_correction")

    # ------------------------------------------------------------------
    # 3. provenance survives database reload
    # ------------------------------------------------------------------
    def test_provenance_survives_reload(self):
        self.l.teach("Python", "a snake", source="ael", confidence=0.6,
                     source_text="Python is a snake.", learning_method="ael")
        self.l.correct("Python", "a programming language", source="user_correction",
                        confidence=0.95, source_text="Correction from user.",
                        learning_method="explicit_correction")
        self.m._conn.close()
        _, k2, _ = _stack(self.db)
        r = k2.get("Python")
        self.assertEqual((r["source"], r["confidence"], r["source_text"], r["learning_method"]),
                          ("user_correction", 0.95, "Correction from user.", "explicit_correction"))

    # ------------------------------------------------------------------
    # 4. idempotent re-learning preserves provenance
    # ------------------------------------------------------------------
    def test_idempotent_relearn_preserves_provenance(self):
        e1 = self.l.teach("Python", "a snake", source="ael", confidence=0.6,
                           source_text="Python is a snake.", learning_method="ael")
        e2 = self.l.teach("Python", "a snake", source="ael")
        self.assertEqual(e2["version"], e1["version"])
        self.assertEqual(e2["updated_at"], e1["updated_at"])
        self.assertEqual((e2["confidence"], e2["source_text"], e2["learning_method"]),
                          (0.6, "Python is a snake.", "ael"))

    def test_idempotent_recorrect_preserves_provenance_and_does_not_default_to_user(self):
        self.l.teach("Python", "a snake", source="ael", confidence=0.6,
                     source_text="Python is a snake.", learning_method="ael")
        e1 = self.l.correct("Python", "a programming language")
        # source not supplied on correction -> existing ("ael") preserved,
        # NOT silently overwritten to a hardcoded "user".
        self.assertEqual(e1["source"], "ael")
        e2 = self.l.correct("Python", "a programming language")
        self.assertEqual(e2["version"], e1["version"])
        self.assertEqual(e2["source"], "ael")

    # ------------------------------------------------------------------
    # 5. explicitly supplied provenance replaces it according to
    #    existing semantics
    # ------------------------------------------------------------------
    def test_supplied_provenance_replaces_on_correct(self):
        self.l.teach("Python", "a snake", source="ael", confidence=0.6,
                     source_text="Python is a snake.", learning_method="ael")
        e = self.l.correct("Python", "a programming language", source="user_correction",
                            confidence=0.9, source_text="a new source text",
                            learning_method="explicit_correction")
        self.assertEqual((e["source"], e["confidence"], e["source_text"], e["learning_method"]),
                          ("user_correction", 0.9, "a new source text", "explicit_correction"))

    def test_supplied_provenance_replaces_on_learn(self):
        self.l.teach("Python", "a snake", source="ael", confidence=0.6,
                     source_text="Python is a snake.", learning_method="ael")
        e = self.l.teach("Python", "a snake", source="ael", confidence=0.9,
                          source_text="new text", learning_method="natural_language_understanding")
        self.assertEqual((e["confidence"], e["source_text"], e["learning_method"]),
                          (0.9, "new text", "natural_language_understanding"))

    # ------------------------------------------------------------------
    # 6. invalid learning does not leave partial data
    # ------------------------------------------------------------------
    def test_invalid_learn_leaves_no_partial_record(self):
        for name in ("", "   ", None, 5):
            with self.assertRaises(ValueError):
                self.k.learn(name, "x")
        self.assertEqual(self.k.all(), [])

    def test_invalid_correct_leaves_existing_record_untouched(self):
        before = self.l.teach("Python", "a snake", source="ael", confidence=0.6,
                               source_text="Python is a snake.", learning_method="ael")
        for name, desc in (("", "x"), ("Python", ""), ("Python", "   "), ("Python", None)):
            with self.assertRaises(ValueError):
                self.l.correct(name, desc)
        after = self.k.get("Python")
        self.assertEqual(before, after)

    def test_unknown_target_correction_creates_nothing(self):
        before = self.k.all()
        self.assertIsNone(self.l.correct("Zorblax", "something"))
        self.assertEqual(self.k.all(), before)

    # ------------------------------------------------------------------
    # 7. unrelated knowledge remains unchanged
    # ------------------------------------------------------------------
    def test_unrelated_knowledge_untouched_by_correction(self):
        self.l.teach("Python", "a snake", source="ael")
        rust = self.l.teach("Rust", "a systems language", source="ael", confidence=0.8,
                             source_text="Rust is a systems language.", learning_method="ael")
        self.l.correct("Python", "a programming language", source="user_correction")
        self.assertEqual(self.k.get("Rust"), rust)

    # ------------------------------------------------------------------
    # 8. existing valid records remain backward compatible
    # ------------------------------------------------------------------
    def test_existing_valid_record_retains_values_when_untouched(self):
        e = self.l.teach("Go", "a language", source="ael", confidence=0.7,
                          source_text="Go is a language.", learning_method="ael")
        fetched = self.k.get("Go")
        self.assertEqual(dict(fetched), dict(e))

    def test_stub_record_absent_provenance_not_fabricated(self):
        # relate() auto-creates a stub with no description/source_text/
        # learning_method unless the caller supplies them - the
        # architecture intentionally permits this to be absent.
        self.l.relate("Alpha", "Beta", "IS_A", source="ael")
        stub = self.k.get("Alpha")
        self.assertIsNone(stub["description"])
        self.assertIsNone(stub["source_text"])
        self.assertIsNone(stub["learning_method"])
        self.assertEqual(stub["status"], "stub")


if __name__ == "__main__":
    unittest.main()
