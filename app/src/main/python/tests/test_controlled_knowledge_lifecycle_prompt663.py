"""Prompt 663 - Section 3: controlled knowledge lifecycle API (retire / reactivate).

KnowledgeSystem.set_status(name, status, source=None, source_text=None, learning_method=None)
LearningSystem.set_status(...)   -> same operation + one "status" learning event on a real change
Statuses writable: "active", "inactive". "stub" stays relate()-only. Nothing is deleted; retrieval APIs,
teach/correct and NL learning keep their existing behavior (teach/correct still write "active").
"""
import os
import tempfile
import unittest
from unittest import mock

from core.core import Core
from knowledge.knowledge_system import LIFECYCLE_STATUSES
from language_intelligence.learned_knowledge_context import select_learned_knowledge

TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items",
          "language_item_relationships")


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


class Transitions(Base):
    def test_vocabulary(self):
        self.assertEqual(LIFECYCLE_STATUSES, {"active", "inactive"})

    def test_active_inactive_active(self):
        self.ls.teach("Python", "a language", source="user", confidence=0.7, source_text="st", learning_method="m")
        r0 = self.k.get("Python")
        r1 = self.ls.set_status("Python", "inactive")
        self.assertEqual((r1["status"], r1["version"]), ("inactive", 2))
        for f in ("id", "name", "created_at", "description", "kind", "source", "confidence", "source_text",
                  "learning_method"):
            self.assertEqual(r1[f], r0[f], f)
        self.assertGreaterEqual(r1["updated_at"], r0["updated_at"])
        self.assertNotEqual(r1["updated_at"], r0["updated_at"])
        r2 = self.ls.set_status("Python", "active")
        self.assertEqual((r2["status"], r2["version"], r2["id"], r2["description"]), ("active", 3, r0["id"], "a language"))
        self.assertEqual(self.k.get("Python"), self.m.query_one("SELECT * FROM knowledge WHERE name='Python'"))

    def test_events_old_new_status_and_provenance(self):
        self.ls.teach("A", "d", source="user")
        self.ls.set_status("A", "inactive")
        self.ls.set_status("A", "active", source="curator", source_text="restored")
        evs = self.ev("status")
        self.assertEqual([(e["target"], e["detail"], e["source"]) for e in evs], [
            ("A", "'active' -> 'inactive'", "user"),            # persisted source (none supplied)
            ("A", "'inactive' -> 'active'", "curator")])        # explicitly supplied, persisted
        r = self.k.get("A")
        self.assertEqual((r["source"], r["source_text"]), ("curator", "restored"))
        self.assertEqual([e["event_type"] for e in self.ev()], ["teach", "status", "status"])
        self.assertEqual(self.ev()[0]["detail"], "d")           # older history untouched

    def test_noop_writes_nothing(self):
        self.ls.teach("A", "d", source="user")
        s = self.snap()
        self.assertEqual(self.ls.set_status("A", "active")["version"], 1)
        self.assertEqual(self.ls.set_status("A", "active", source="other", source_text="x")["source"], "user")
        self.assertEqual(self.snap(), s)
        self.ls.set_status("A", "inactive")
        s = self.snap()
        self.assertEqual(self.ls.set_status("a", "inactive")["version"], 2)
        self.assertEqual(self.snap(), s)

    def test_direct_knowledge_call_writes_no_event(self):
        self.ls.teach("A", "d", source="user")
        n = len(self.ev())
        r = self.k.set_status("A", "inactive")
        self.assertEqual((r["status"], r["version"]), ("inactive", 2))
        self.assertEqual(len(self.ev()), n)                      # L4: direct KnowledgeSystem calls log nothing

    def test_case_insensitive_resolution(self):
        self.ls.teach("Python", "d", source="user")
        r = self.ls.set_status("python", "inactive")
        self.assertEqual(r["name"], "Python")
        self.assertEqual(self.ev("status")[0]["target"], "Python")
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge")), 1)

    def test_multiple_transitions_version_and_events(self):
        self.ls.teach("A", "d", source="user")
        for st in ("inactive", "active", "inactive", "inactive", "active", "active", "inactive"):
            self.ls.set_status("A", st)
        self.assertEqual(self.k.get("A")["version"], 1 + 5)
        self.assertEqual(len(self.ev("status")), 5)
        details = [e["detail"] for e in self.ev("status")]
        for prev, cur in zip(details, details[1:]):             # old status of each = new status of previous
            self.assertEqual(prev.split(" -> ")[1], cur.split(" -> ")[0])
        self.assertEqual(self.k.get("A")["status"], "inactive")

    def test_legacy_status_can_be_moved(self):
        self.k.learn("L", "d", status="deprecated")
        r = self.ls.set_status("L", "active")
        self.assertEqual((r["status"], r["version"]), ("active", 2))
        self.assertEqual(self.ev("status")[0]["detail"], "'deprecated' -> 'active'")


class Invalid(Base):
    def test_invalid_requests_fail_safely(self):
        self.ls.teach("A", "d", source="user")
        self.ls.teach("Dup", "1", source="user")
        self.k.learn("dup", "2")
        self.ls.relate("S", "T", "is_a", source="user")
        s = self.snap()
        cases = [("", "inactive"), ("   ", "inactive"), (None, "inactive"), (5, "inactive"), (["A"], "inactive"),
                 ("A", "bogus"), ("A", "stub"), ("A", "ACTIVE"), ("A", ""), ("A", None), ("A", 1), ("A", ["active"]),
                 ("DUP", "inactive"), ("S", "inactive"), ("S", "active")]
        for name, st in cases:
            for target in (self.ls, self.k):
                with self.assertRaises(ValueError, msg=(name, st)):
                    target.set_status(name, st)
        self.assertEqual(self.snap(), s)

    def test_unknown_name_creates_nothing(self):
        s = self.snap()
        self.assertIsNone(self.ls.set_status("Nope", "inactive"))
        self.assertIsNone(self.k.set_status("Nope", "active"))
        self.assertEqual(self.snap(), s)
        self.assertIsNone(self.k.get("Nope"))

    def test_stub_still_becomes_active_only_by_teaching(self):
        self.ls.relate("S", "T", "is_a", source="user")
        self.ls.teach("S", "now real", source="user")
        self.assertEqual(self.k.get("S")["status"], "active")
        self.assertEqual(self.ls.set_status("S", "inactive")["status"], "inactive")
        self.assertEqual(self.k.get("T")["status"], "stub")


class Atomicity(Base):
    def _boom(self):
        return mock.patch.object(self.m, "add_learning_event", side_effect=Boom("event"))

    def test_event_failure_rolls_back(self):
        self.ls.teach("A", "d", source="user")
        s = self.snap()
        with self._boom():
            with self.assertRaises(Boom):
                self.ls.set_status("A", "inactive")
        self.assertEqual(self.snap(), s)
        self.assertEqual((self.k.get("A")["status"], self.k.get("A")["version"]), ("active", 1))
        self.ls.set_status("A", "inactive")                       # no version gap afterwards
        self.assertEqual(self.k.get("A")["version"], 2)

    def test_mutation_failure_leaves_no_event(self):
        self.ls.teach("A", "d", source="user")
        s = self.snap()
        real = self.m._run

        def run(sql, params=()):
            if sql.startswith("UPDATE knowledge"):
                raise Boom("update")
            return real(sql, params)
        with mock.patch.object(self.m, "_run", side_effect=run):
            with self.assertRaises(Boom):
                self.ls.set_status("A", "inactive")
        self.assertEqual(self.snap(), s)

    def test_failure_after_update_before_commit(self):
        self.ls.teach("A", "d", source="user")
        s = self.snap()
        real = self.m._run

        def run(sql, params=()):
            cur = real(sql, params)
            if sql.startswith("UPDATE knowledge"):
                raise Boom("after update")
            return cur
        with mock.patch.object(self.m, "_run", side_effect=run):
            with self.assertRaises(Boom):
                self.ls.set_status("A", "inactive")
        self.assertEqual(self.snap(), s)


class Preservation(Base):
    def test_relationships_and_history_preserved_through_cycle(self):
        self.ls.teach("A", "d", source="user")
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.5)
        self.ls.relate("C", "A", "part_of", source="user")
        rels = self.m.query("SELECT * FROM relationships ORDER BY id")
        hist = self.ev()
        self.ls.set_status("A", "inactive")
        self.ls.set_status("A", "active")
        self.assertEqual(self.m.query("SELECT * FROM relationships ORDER BY id"), rels)
        self.assertEqual(self.ev()[:len(hist)], hist)
        self.assertEqual(len(self.k.relationships_for("A")["outgoing"]), 1)
        self.assertEqual(len(self.k.relationships_for("A")["incoming"]), 1)

    def test_close_reopen(self):
        self.ls.teach("A", "d", source="user")
        self.ls.set_status("A", "inactive")
        s = self.snap()
        for _ in range(2):
            self.reopen()
            self.assertEqual(self.snap(), s)
            self.assertEqual(self.k.get("A")["status"], "inactive")
            self.assertEqual(self.k.get("A")["version"], 2)
        self.ls.set_status("A", "active")
        self.assertEqual(self.k.get("A")["version"], 3)


class InteractionsAfterRetirement(Base):
    def setUp(self):
        super().setUp()
        self.ls.teach("Python", "a programming language", source="user")
        self.ls.relate("Python", "Code", "used_for", source="user")
        self.ls.set_status("Python", "inactive")

    def test_retrieval_unchanged_and_read_only(self):
        s = self.snap()
        self.assertEqual(self.k.get("Python")["status"], "inactive")
        self.assertEqual(self.k.resolve_name("python")["status"], "case_insensitive")
        self.assertEqual(self.k.resolve_name("Python")["status"], "exact")
        self.assertIn("Python", [r["name"] for r in self.k.all()])
        self.assertIn("Python", [r["name"] for r in self.k.search("programming language")])
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)
        self.assertEqual(self.ls.recall("Python")["status"], "inactive")
        sel = select_learned_knowledge("Tell me about Python", self.k, candidate_terms=["Python"])
        self.assertFalse(sel.selected)                             # Prompt 664: inactive is not current-use knowledge
        self.assertEqual(self.snap(), s)

    def test_teach_reactivates_existing_behavior(self):
        self.ls.teach("Python", "a programming language", source="user")   # same values but status active
        r = self.k.get("Python")
        self.assertEqual((r["status"], r["version"]), ("active", 3))
        self.assertEqual([e["event_type"] for e in self.ev()], ["teach", "relate", "status", "teach"])

    def test_correct_reactivates_existing_behavior(self):
        self.ls.correct("Python", "a scripting language")
        r = self.k.get("Python")
        self.assertEqual((r["status"], r["version"], r["description"]), ("active", 3, "a scripting language"))
        self.assertEqual(self.ev("correct")[0]["detail"], "'a programming language' -> 'a scripting language'")

    def test_status_only_correct_reactivation_logs_unchanged_detail(self):
        self.ls.correct("Python", "a programming language")                # L2, preserved
        self.assertEqual(self.k.get("Python")["status"], "active")
        self.assertEqual(self.ev("correct")[0]["detail"],
                         "'a programming language' -> 'a programming language'")

    def test_nl_learning_does_not_touch_inactive_record(self):
        before = self.k.get("Python")
        res = self.core.learn_from_text("Python is a language.")
        self.assertTrue(res.success)
        after = self.k.get("Python")
        self.assertEqual((after["status"], after["version"], after["updated_at"]),
                         (before["status"], before["version"], before["updated_at"]))
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='python'")), 1)

    def test_relate_to_inactive_endpoint_keeps_it_inactive(self):
        self.ls.relate("Python", "Snake", "not_a", source="user")
        self.assertEqual(self.k.get("Python")["status"], "inactive")
        self.assertEqual(self.k.get("Python")["version"], 2)


if __name__ == "__main__":
    unittest.main()
