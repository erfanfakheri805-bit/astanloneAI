"""Prompt 676 - Section 3: current-knowledge mutations vs the learning-event history.

Audit result (docs/section3_learning_event_mutation_consistency_prompt676.md): NO genuine defect, no production
change. Every real LearningSystem mutation (teach / correct / set_status / relate, and the NL and conversational
paths that call them) writes exactly one event in the same transaction; true no-ops, rejected operations and
rolled-back operations write none; direct KnowledgeSystem mutations write none (documented). These tests pin the
gaps not already pinned by Prompts 632-675, on real production paths only.
"""
import os
import tempfile
import unittest

from core.core import Core

KNOWLEDGE_EVENTS = ("teach", "correct", "status", "relate")  # language_* events are the separate language history
CORR = "not a snake, I mean a programming language."


class Base(unittest.TestCase):
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

    def tearDown(self):
        try:
            self.m._conn.close()
        except Exception:
            pass

    def ev(self, kind=None):
        rows = self.m.query("SELECT * FROM learning_events ORDER BY id")
        return [r for r in rows if (kind is None and r["event_type"] in KNOWLEDGE_EVENTS) or r["event_type"] == kind]

    def n(self):
        return len(self.ev())

    def tables(self):
        return {t: self.m.query(f"SELECT * FROM {t} ORDER BY id") for t in ("knowledge", "relationships", "learning_events")}

    def shape(self, kind=None):
        return [(e["event_type"], e["target"], e["source"]) for e in self.ev(kind)]


class EventSequences(Base):
    def test_teach_correct_status_sequence_exact_history(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.teach("Python", "a snake", source="user")                       # identical repeat
        self.ls.correct("Python", "a language")                                 # omitted source -> persisted "user"
        self.ls.correct("Python", "a language")                                 # identical -> no-op
        self.ls.set_status("Python", "inactive")
        self.ls.set_status("Python", "inactive")                                # no-op
        self.ls.set_status("Python", "active")
        self.assertEqual(self.shape(), [("teach", "Python", "user"), ("correct", "Python", "user"),
                                        ("status", "Python", "user"), ("status", "Python", "user")])
        e = self.ev()
        self.assertEqual(e[0]["detail"], "a snake")
        self.assertEqual(e[1]["detail"], "'a snake' -> 'a language'")
        self.assertEqual(e[2]["detail"], "'active' -> 'inactive'")
        self.assertEqual(e[3]["detail"], "'inactive' -> 'active'")
        self.assertEqual([x["id"] for x in e], sorted(x["id"] for x in e))
        self.assertEqual(self.k.get("Python")["version"], 4)  # 1 event per real version bump

    def test_stub_teach_correct_sequence(self):
        self.ls.relate("Snake", "Reptile", "IS_A", source="user")               # stubs: no knowledge events
        self.assertEqual(self.shape(), [("relate", "Snake", "user")])
        self.assertEqual(self.k.get("Snake")["status"], "stub")
        self.ls.teach("Snake", "a legless reptile", source="user")              # stub -> taught
        self.assertEqual(self.k.get("Snake")["status"], "active")
        self.assertEqual(self.k.get("Snake")["version"], 2)
        self.ls.correct("Snake", "a limbless reptile")
        self.assertEqual(self.shape(), [("relate", "Snake", "user"), ("teach", "Snake", "user"),
                                        ("correct", "Snake", "user")])
        self.assertEqual(self.k.get("Reptile")["version"], 1)                   # untouched stub, no event

    def test_correct_on_stub_logs_none_to_description(self):
        self.ls.relate("Snake", "Reptile", "IS_A", source="user")
        self.ls.correct("Snake", "a reptile")
        self.assertEqual(self.ev("correct")[0]["detail"], "None -> 'a reptile'")
        self.assertEqual(self.k.get("Snake")["status"], "active")

    def test_relationship_create_repeat_change_sequence(self):
        self.ls.teach("A", "a", source="user")
        self.ls.teach("B", "b", source="user")
        base = self.n()
        self.assertTrue(self.ls.relate("A", "B", "USES", source="user", confidence=0.5)["created"])
        self.assertFalse(self.ls.relate("A", "B", "USES", source="user", confidence=0.5)["created"])
        self.assertFalse(self.ls.relate("A", "B", "USES", source="user")["created"])     # None keeps confidence
        self.assertEqual(self.n(), base + 1)
        self.assertFalse(self.ls.relate("A", "B", "USES", source="user", confidence=0.9)["created"])  # real change
        self.assertEqual(self.n(), base + 2)
        self.assertEqual([e["detail"] for e in self.ev("relate")], ["USES -> B", "USES -> B"])
        row = self.m.query("SELECT * FROM relationships")[0]
        self.assertEqual(row["confidence"], 0.9)
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 1)

    def test_rejected_then_successful_mutation_leaves_no_gap(self):
        self.ls.teach("A", "a", source="user")
        last = self.ev()[-1]["id"]
        with self.assertRaises(ValueError):
            self.ls.teach("   ", "x")
        with self.assertRaises(ValueError):
            self.ls.set_status("A", "bogus")
        with self.assertRaises(ValueError):
            self.ls.correct("A", "   ")
        with self.assertRaises(ValueError):
            self.ls.relate("A", "", "USES")
        with self.assertRaises(ValueError):
            self.ls.relate("A", "B", None)
        self.assertEqual(self.ev()[-1]["id"], last)
        self.assertIsNone(self.k.get("B"))                                       # no orphan stub
        self.ls.correct("A", "a2")
        self.assertEqual(self.ev()[-1]["id"], last + 1)                          # no id consumed by rejections


class SourceSemantics(Base):
    def test_correct_omitted_vs_explicit_source(self):
        self.ls.teach("Python", "v1", source="user", source_text="orig", confidence=0.7)
        self.ls.correct("Python", "v2")
        r = self.k.get("Python")
        self.assertEqual((r["source"], r["source_text"], r["confidence"]), ("user", "orig", 0.7))
        self.ls.correct("Python", "v3", source="user_correction", source_text="fix")
        r = self.k.get("Python")
        self.assertEqual((r["source"], r["source_text"]), ("user_correction", "fix"))
        self.assertEqual([e["source"] for e in self.ev("correct")], ["user", "user_correction"])

    def test_identical_effective_metadata_is_no_event_but_changed_metadata_is_one_event(self):
        self.ls.teach("Python", "v1", source="user", source_text="orig")
        n = self.n()
        self.ls.correct("Python", "v1", source="user", source_text="orig")       # effective values equal
        self.ls.teach("Python", "v1", source="user")                             # None source_text keeps stored
        self.assertEqual(self.n(), n)
        self.assertEqual(self.k.get("Python")["version"], 1)
        self.ls.correct("Python", "v1", source_text="new")                       # real (metadata) mutation
        self.assertEqual(self.n(), n + 1)                                        # documented L2: detail unchanged
        self.assertEqual(self.ev()[-1]["detail"], "'v1' -> 'v1'")
        self.assertEqual(self.k.get("Python")["version"], 2)

    def test_teach_event_source_is_the_persisted_source(self):
        self.ls.teach("Python", "v1")                                            # default "ael"
        self.ls.teach("Python", "v1", source="user")                             # real source change
        self.assertEqual([e["source"] for e in self.ev("teach")], ["ael", "user"])
        self.assertEqual(self.k.get("Python")["source"], "user")

    def test_set_status_source_semantics(self):
        self.ls.teach("Python", "v1", source="user", source_text="orig")
        self.ls.set_status("Python", "inactive")
        self.ls.set_status("Python", "active", source="curator", source_text="restored")
        r = self.k.get("Python")
        self.assertEqual((r["source"], r["source_text"]), ("curator", "restored"))
        self.assertEqual([e["source"] for e in self.ev("status")], ["user", "curator"])
        n = self.n()
        self.ls.set_status("Python", "active", source="someone_else")            # no-op: source NOT refreshed
        self.assertEqual(self.n(), n)
        self.assertEqual(self.k.get("Python")["source"], "curator")


class Reactivation(Base):
    def test_teach_and_correct_reactivate_with_one_event_each(self):
        self.ls.teach("Python", "v1", source="user")
        self.ls.set_status("Python", "inactive")
        n = self.n()
        self.ls.teach("Python", "v1", source="user")                             # same description, reactivates
        self.assertEqual((self.n(), self.k.get("Python")["status"]), (n + 1, "active"))
        self.assertEqual(self.ev()[-1]["event_type"], "teach")
        self.ls.set_status("Python", "inactive")
        n = self.n()
        self.ls.correct("Python", "v1")                                          # same description, reactivates
        self.assertEqual((self.n(), self.k.get("Python")["status"]), (n + 1, "active"))
        self.assertEqual(self.ev()[-1]["event_type"], "correct")

    def test_relate_never_reactivates_or_logs_status(self):
        self.ls.teach("A", "a", source="user")
        self.ls.teach("B", "b", source="user")
        self.ls.set_status("B", "inactive")
        self.ls.relate("A", "B", "USES", source="user")
        self.assertEqual(self.k.get("B")["status"], "inactive")
        self.assertEqual([e["event_type"] for e in self.ev()], ["teach", "teach", "status", "relate"])


class StatusTargets(Base):
    def test_status_unknown_stub_ambiguous_case_insensitive(self):
        self.assertIsNone(self.ls.set_status("Ghost", "inactive"))
        self.assertEqual(self.n(), 0)
        self.assertIsNone(self.k.get("Ghost"))
        self.ls.relate("Snake", "Reptile", "IS_A", source="user")
        n = self.n()
        with self.assertRaises(ValueError):
            self.ls.set_status("Snake", "inactive")                              # stub
        self.ls.teach("Python", "the language", source="user")
        self.ls.set_status("python", "inactive")                                 # unique case-insensitive
        self.assertEqual(self.ev()[-1]["target"], "Python")                      # stored name, not the argument
        self.assertIsNone(self.k.get("python"))
        self.ls.teach("python", "the snake", source="user")                      # explicit new case variant
        n = self.n()
        before = self.tables()
        with self.assertRaises(ValueError):
            self.ls.set_status("PYTHON", "inactive")                             # ambiguous
        with self.assertRaises(ValueError):
            self.ls.correct("PYTHON", "x")
        self.assertEqual((self.n(), self.tables()), (n, before))

    def test_correct_case_variants_target_stored_name(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.correct("python", "a language")
        self.assertEqual(self.ev("correct")[0]["target"], "Python")
        self.assertIsNone(self.k.get("python"))
        self.assertIsNone(self.ls.correct("Unknown", "x"))
        self.assertEqual(self.n(), 2)


class NaturalLanguageAndConversation(Base):
    def test_nl_learning_one_relate_event_per_new_or_changed_fact(self):
        self.core.learn_from_text("Python is a language.")
        first = self.ev()
        self.assertEqual([e["event_type"] for e in first], ["relate"])
        self.core.learn_from_text("Python is a language.")                       # identical repeat: no event
        self.assertEqual(self.ev(), first)
        for name in ("Python", "language"):
            self.assertEqual(self.k.get(name)["version"], 1)                     # stubs: no event of their own

    def test_nl_preview_and_unlearnable_write_nothing(self):
        before = self.tables()
        self.core.learn_from_text("Is Python a language?")
        self.assertEqual(self.tables(), before)

    def test_conversational_correction_one_correct_event(self):
        self.ls.teach("Python", "a snake", source="user", confidence=0.6)
        self.core.process_input(CORR)
        corr = self.ev("correct")
        self.assertEqual(len(corr), 1)
        self.assertEqual((corr[0]["target"], corr[0]["source"]), ("Python", "user_correction"))
        self.assertEqual(corr[0]["detail"], "'a snake' -> 'a programming language'")
        n = self.n()
        self.core.process_input(CORR)                                            # nothing left to correct
        self.assertEqual(self.n(), n)

    def test_conversational_correction_inactive_target_writes_no_knowledge_event(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.set_status("Python", "inactive")
        before = self.ev()
        rows = self.m.query("SELECT * FROM knowledge ORDER BY id")
        self.core.process_input(CORR)
        self.assertEqual(self.ev(), before)                                      # knowledge history unchanged
        self.assertEqual(self.m.query("SELECT * FROM knowledge ORDER BY id"), rows)

    def test_correction_language_history_is_separate_from_knowledge_history(self):
        self.ls.teach("Python", "a snake", source="user")
        self.core.process_input(CORR)
        kinds = {e["event_type"] for e in self.m.query("SELECT * FROM learning_events")}
        self.assertLessEqual({"teach", "correct"}, kinds)
        extra = kinds - set(KNOWLEDGE_EVENTS)
        self.assertTrue(all(k.startswith("language_") for k in extra), extra)

    def test_nl_then_correction_history_order(self):
        self.core.learn_from_text("Python is a snake.")
        self.ls.teach("Python", "a snake", source="user")
        self.core.process_input(CORR)
        self.assertEqual([e["event_type"] for e in self.ev()], ["relate", "teach", "correct"])


class Atomicity(Base):
    def _fail_events(self):
        real = self.m.add_learning_event

        def boom(*a, **k):
            raise RuntimeError("event write failed")
        self.m.add_learning_event = boom
        return real

    def test_event_failure_rolls_back_every_mutation_kind(self):
        self.ls.teach("A", "a", source="user")
        self.ls.teach("B", "b", source="user")
        base = self.tables()
        real = self._fail_events()
        try:
            for call in (lambda: self.ls.teach("A", "a2", source="user"),
                         lambda: self.ls.teach("New", "n", source="user"),
                         lambda: self.ls.correct("A", "a3"),
                         lambda: self.ls.set_status("A", "inactive"),
                         lambda: self.ls.relate("A", "B", "USES", source="user"),
                         lambda: self.ls.relate("A", "Fresh", "USES", source="user")):
                with self.assertRaises(RuntimeError):
                    call()
                self.assertEqual(self.tables(), base)                            # no orphan row / stub / edge
        finally:
            self.m.add_learning_event = real
        self.ls.teach("A", "a2", source="user")                                  # system fully usable afterwards
        self.assertEqual(self.ev()[-1]["detail"], "a2")

    def test_mutation_failure_leaves_no_orphan_event(self):
        self.ls.teach("A", "a", source="user")
        base = self.tables()
        real = self.k.learn

        def boom(*a, **k):
            raise RuntimeError("write failed")
        self.k.learn = boom
        try:
            for call in (lambda: self.ls.teach("A", "a2", source="user"),
                         lambda: self.ls.correct("A", "a3"),
                         lambda: self.ls.set_status("A", "inactive")):
                with self.assertRaises(RuntimeError):
                    call()
        finally:
            self.k.learn = real
        self.assertEqual(self.tables(), base)

    def test_nl_persist_failure_reports_error_and_leaves_state(self):
        base = self.tables()
        real = self.m.add_learning_event
        self.m.add_learning_event = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
        try:
            res = self.core.learn_from_text("Python is a language.")
        finally:
            self.m.add_learning_event = real
        self.assertFalse(res.success)
        self.assertEqual(self.tables(), base)


class DirectKnowledgeSystemNoEvents(Base):
    def test_direct_mutations_change_rows_but_write_no_events(self):
        k = self.k
        k.learn("Python", "a snake", source="user")
        k.learn("Python", "a language", source="user")
        k.correct("Python", "a fine language")
        k.set_status("Python", "inactive")
        k.set_status("Python", "active")
        k.relate("Python", "Code", "USED_FOR", source_type="user")
        k.relate("Python", "Code", "USED_FOR", confidence=0.4)
        self.assertEqual(self.ev(), [])
        self.assertEqual(k.get("Python")["version"], 5)
        self.assertEqual(k.get("Code")["status"], "stub")
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 1)

    def test_reads_write_no_events_or_rows(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.relate("Python", "Code", "USED_FOR", source="user")
        before = self.tables()
        self.k.get("Python"); self.k.all(); self.k.search("lang"); self.k.resolve_name("python")
        self.k.resolve_current_name("python"); self.k.relationships_for("Python")
        self.k.current_relationships_for("Python"); self.ls.recall("Python"); self.ls.search("lang")
        self.core.reason("Tell me about Python")
        self.core.understand_language("Tell me about Python")
        self.m.recent_learning_events()
        self.assertEqual(self.tables(), before)

    def test_learning_system_has_no_learn_method(self):
        self.assertFalse(hasattr(self.ls, "learn"))                              # only teach/correct/relate/set_status


class Reopen(Base):
    def test_history_and_state_identical_across_reopens(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.correct("Python", "a language")
        self.ls.set_status("Python", "inactive")
        self.ls.relate("Python", "Code", "USED_FOR", source="user")
        self.core.learn_from_text("Ruby is a language.")
        snap = self.tables()
        self.reopen()
        self.assertEqual(self.tables(), snap)
        self.reopen()
        self.assertEqual(self.tables(), snap)                                    # reload writes no events
        self.ls.set_status("Python", "inactive")                                 # still a no-op after reopen
        self.assertEqual(self.tables(), snap)
        self.ls.set_status("Python", "active")                                   # next real change continues the id chain
        self.assertEqual(self.ev("status")[-1]["id"], snap["learning_events"][-1]["id"] + 1)


if __name__ == "__main__":
    unittest.main()
