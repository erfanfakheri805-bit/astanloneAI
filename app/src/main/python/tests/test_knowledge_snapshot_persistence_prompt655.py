"""Prompt 655 - Section 3: current-knowledge snapshot consistency across save -> close -> reopen -> continue.

AUDIT, not a redesign. Every test pins EXISTING persistence behavior; nothing here required a production change.
The live knowledge/relationship/language rows stay authoritative; learning_events stay historical.

  P1  Reopening (repeatedly, via MemorySystem or Core) is read-only for every knowledge-related table: same ids,
      names, descriptions, versions, status, source, confidence, source_text, learning_method, created_at and
      updated_at (compared verbatim - timestamps are never normalized), same events, same AUTOINCREMENT counters.
  P2  Relationships, language items and language relationships survive reload with no loss, duplication or
      redirection; current readers return the same values before close and after reload.
  P3  Operations after reload continue from the persisted state: version +1 per real change, new ids continue,
      created_at/id never move, stub -> taught -> corrected is one identity across reloads.
  P4  Exact no-ops stay no-ops after reload; failed atomic ops after reload leave state AND events unchanged
      (also after a further reload); an uncommitted atomic scope is never persisted by close().
  P5  Ambiguous names resolve/raise identically after reload and never mutate.
  P6  Language stores keep their intentionally different repeat semantics after reload.

Documented limitation (out of scope, unchanged): Core construction re-enables built-in capabilities, which touches
the `capabilities` table's updated_at on every open. That table is not knowledge/learning state and is excluded
from the snapshots below; a bare MemorySystem reopen does not touch it.
"""
import os
import tempfile
import unittest
from unittest import mock

from core.core import Core
from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from language_intelligence.language_relationships import concept_ref, item_ref
from tests.test_learning_history_replay_integrity_prompt654 import replay

TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items",
          "language_item_relationships", "sqlite_sequence")


class Boom(RuntimeError):
    pass


class Persist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "p.db")
        self._open()

    def _open(self):
        self.core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m = self.core.knowledge, self.core.learning, self.core.memory

    def reopen(self):
        self.m._conn.close()
        self._open()

    def snap(self, m=None):
        m = m or self.m
        return {t: [dict(r) for r in m.query(f"SELECT * FROM {t} ORDER BY 1, 2")] for t in TABLES}

    def events(self, *types):
        return [e for e in self.m.query("SELECT * FROM learning_events ORDER BY id")
                if not types or e["event_type"] in types]

    def readers(self):
        """Every current reader, evaluated now (values, not references)."""
        return {
            "get": {n: self.k.get(n) for n in ("Cat", "Animal", "Python", "python")},
            "all": self.k.all(),
            "search": self.k.search("feline"),
            "resolve": {n: self.k.resolve_name(n) for n in ("cat", "PYTHON", "Animal", "nothing")},
            "rels": {n: self.k.relationships_for(n) for n in ("Cat", "Animal", "Python", "language")},
            "recall": {n: self.ls.recall(n) for n in ("Cat", "Animal")},
            "lang_items": self.core.language_learning.find_items("feline"),
            "lang_rels": self.core.language_relationships.relationships_for(concept_ref("Cat")),
            "recent": self.core.recent_learning_events(200),
        }

    def build(self):
        ll = self.core.language_learning
        self.ls.teach("Cat", "a feline", source="user", confidence=0.5, source_text="cats", learning_method="ael")
        self.ls.relate("Cat", "Animal", "is_a", source="user", confidence=0.9)     # stub Animal
        self.ls.teach("Cat", "a small feline", source="user", confidence=0.7)
        self.ls.correct("cat", "a small domestic feline", source="user_correction")
        self.ls.teach("Animal", "a living being")                                  # stub -> taught
        self.ls.correct("Animal", "a living organism")
        self.core.learn_from_text("Python is a language.")                         # NL: stubs + edge
        self.ls.teach("Python", "a snake", source="user")
        self.ls.teach("python", "lowercase python")                                # ambiguous pair (exact names)
        self.core.process_input("not a snake, I mean a programming language.")     # conversational correction
        ll.learn_item("english", "word", "feline", meaning="cat-like", source="user", source_context="ctx",
                      confidence=0.6)
        ll.learn_item("english", "word", "feline", meaning="cat-like", source="user", source_context="ctx")
        self.core.relate_language_items(item_ref("english", "word", "feline"), concept_ref("Cat"),
                                        "concept_to_expression", metadata={"n": 1}, source="user")

    # ---- P1: reopen is read-only and lossless -----------------------------------------------------------
    def test_full_snapshot_identical_after_reopen_and_reopen_writes_nothing(self):
        self.build()
        before = self.snap()
        self.assertGreater(len(before["knowledge"]), 4)
        for _ in range(3):                                   # repeated reopen must stay a fixed point
            self.reopen()
            self.assertEqual(self.snap(), before)
        n_events = len(before["learning_events"])
        self.assertEqual(len(self.events()), n_events)       # reopen created no events
        self.assertEqual([r["version"] for r in self.snap()["knowledge"]],
                         [r["version"] for r in before["knowledge"]])

    def test_bare_memory_system_reopen_is_byte_for_byte_read_only(self):
        self.build()
        self.m._conn.close()
        m1 = MemorySystem(self.db)
        a = self.snap(m1)
        cap_a = m1.query("SELECT * FROM capabilities ORDER BY id")
        cfg_a = m1.query("SELECT * FROM config ORDER BY 1")
        m1._conn.close()
        m2 = MemorySystem(self.db)
        self.assertEqual(self.snap(m2), a)
        self.assertEqual(m2.query("SELECT * FROM capabilities ORDER BY id"), cap_a)   # untouched by bare reopen
        self.assertEqual(m2.query("SELECT * FROM config ORDER BY 1"), cfg_a)
        m2._conn.close()
        self._open()

    def test_timestamps_are_stored_and_returned_verbatim(self):
        self.build()
        before = {r["name"]: (r["created_at"], r["updated_at"]) for r in self.k.all()}
        self.reopen()
        after = {r["name"]: (r["created_at"], r["updated_at"]) for r in self.k.all()}
        self.assertEqual(before, after)
        for c, u in after.values():
            self.assertTrue(c.endswith("+00:00") and u.endswith("+00:00"))     # no normalization
            self.assertLessEqual(c, u)

    # ---- P2: readers, relationships, language persistence ------------------------------------------------
    def test_every_current_reader_identical_across_reload(self):
        self.build()
        before = self.readers()
        self.reopen()
        self.assertEqual(self.readers(), before)
        # relationships: no loss / duplication / redirection
        edges = [(r["from_name"], r["relation_type"], r["to_name"])
                 for r in self.m.query("SELECT * FROM relationships ORDER BY id")]
        self.assertEqual(len(edges), len(set(edges)))
        self.assertIn(("Cat", "is_a", "Animal"), edges)
        self.assertEqual(self.k.relationships_for("Cat")["outgoing"][0]["to_name"], "Animal")
        self.assertEqual(self.k.relationships_for("Animal")["incoming"][0]["from_name"], "Cat")

    def test_history_order_and_replay_survive_reload(self):
        self.build()
        ids = [e["id"] for e in self.events()]
        self.assertEqual(ids, list(range(1, len(ids) + 1)))
        state_before = replay(self.events())
        self.reopen()
        self.assertEqual([e["id"] for e in self.events()], ids)
        self.assertEqual(replay(self.events()), state_before)
        self.assertEqual(self.core.recent_learning_events(500), self.events())
        live = {r["name"]: r for r in self.k.all()}
        for name, s in state_before[0].items():
            self.assertEqual((s["description"], s["version"], s["source"]),
                             (live[name]["description"], live[name]["version"], live[name]["source"]), name)

    def test_readers_never_return_stale_preclose_values(self):
        self.build()
        old = dict(self.k.get("Cat"))
        self.reopen()
        self.ls.correct("Cat", "post-reload text")
        new = self.k.get("Cat")
        self.assertNotEqual(new["description"], old["description"])
        self.assertEqual(new["version"], old["version"] + 1)
        for get in (lambda: self.k.get("Cat"), lambda: self.ls.recall("Cat"), lambda: [r for r in self.k.all() if r["name"] == "Cat"][0],
                    lambda: self.k.resolve_name("cat")["record"],
                    lambda: self.k.find_by_name_case_insensitive("CAT"), lambda: self.k.search("post-reload")[0]):
            self.assertEqual(get()["description"], "post-reload text")
        self.assertEqual(self.k.search("small domestic"), [])                    # old text gone from live search
        self.reopen()
        self.assertEqual(self.k.get("Cat"), new)

    # ---- P3: continue lifecycle after reload -------------------------------------------------------------
    def test_operations_after_reload_continue_from_persisted_state(self):
        self.build()
        before = {r["name"]: r for r in self.k.all()}
        last_event = self.events()[-1]["id"]
        max_id = max(r["id"] for r in before.values())
        self.reopen()
        self.ls.teach("Cat", "reloaded teach", source="ael")
        self.ls.correct("CAT", "reloaded correct")
        self.ls.relate("Cat", "Animal", "is_a", source="user", confidence=0.2)      # metadata refresh
        self.core.learn_from_text("Python is a language.")                           # NL on existing identity
        self.ls.relate("Cat", "Fresh", "likes", source="user")                       # new stub
        cat = self.k.get("Cat")
        self.assertEqual((cat["id"], cat["created_at"], cat["version"], cat["description"]),
                         (before["Cat"]["id"], before["Cat"]["created_at"], before["Cat"]["version"] + 2,
                          "reloaded correct"))
        self.assertEqual(self.k.get("Fresh")["id"], max_id + 1)                      # counters continue, no reuse
        self.assertEqual(self.k.get("Fresh")["status"], "stub")
        evs = self.events()
        self.assertEqual(evs[last_event]["id"], last_event + 1)                       # first post-reload event
        self.assertEqual([e["id"] for e in evs], list(range(1, len(evs) + 1)))
        edges = self.m.query("SELECT * FROM relationships WHERE from_name='Cat' AND to_name='Animal'")
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["confidence"], 0.2)
        self.reopen()
        self.assertEqual(self.k.get("Cat"), cat)

    def test_stub_taught_corrected_is_one_identity_across_reloads(self):
        self.ls.relate("Cat", "Animal", "is_a")
        stub = dict(self.k.get("Cat"))
        self.reopen()
        self.ls.teach("Cat", "a feline", source="user")
        taught = dict(self.k.get("Cat"))
        self.reopen()
        self.ls.correct("cat", "a small feline")
        self.reopen()
        final = self.k.get("Cat")
        self.assertEqual((final["id"], final["name"], final["created_at"]),
                         (stub["id"], "Cat", stub["created_at"]))
        self.assertEqual((stub["version"], taught["version"], final["version"]), (1, 2, 3))
        self.assertEqual((stub["status"], taught["status"], final["status"]), ("stub", "active", "active"))
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='cat'")), 1)
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 1)
        self.assertEqual(self.k.relationships_for("Cat")["outgoing"][0]["to_name"], "Animal")

    # ---- P4: no-ops, atomicity, uncommitted scopes ---------------------------------------------------------
    def test_noops_stay_noops_after_reload(self):
        self.build()
        self.ls.teach("Python", "a programming language")       # settle into a known state before the reload
        self.reopen()
        before = self.snap()
        cur = self.k.get("Python")
        self.ls.teach("Python", cur["description"], source=cur["source"])
        self.ls.correct("Cat", self.k.get("Cat")["description"])
        self.ls.relate("Cat", "Animal", "is_a", source=self.k.relationships_for("Cat")["outgoing"][0]["source_type"])
        self.assertEqual(self.snap(), before)
        self.reopen()
        self.assertEqual(self.snap(), before)

    def test_failed_atomic_ops_after_reload_leave_state_and_history_unchanged(self):
        self.build()
        self.reopen()
        before = self.snap()
        with mock.patch.object(type(self.m), "add_learning_event", side_effect=Boom("e")):
            for op in (lambda: self.ls.teach("Cat", "zzz", source="q"),
                       lambda: self.ls.correct("Cat", "yyy"),
                       lambda: self.ls.relate("Cat", "Brand", "likes"),
                       lambda: self.ls.relate("Cat", "Animal", "is_a", confidence=0.01),
                       lambda: self.core.language_learning.learn_item("english", "word", "feline", meaning="x"),
                       lambda: self.core.relate_language_items(item_ref("english", "word", "feline"),
                                                               concept_ref("Cat"), "concept_to_expression",
                                                               metadata={"n": 9})):
                with self.assertRaises(Boom):
                    op()
        self.assertEqual(self.snap(), before)
        self.reopen()
        self.assertEqual(self.snap(), before)
        self.ls.teach("Cat", "works afterwards", source="ael")                        # store still usable
        self.assertEqual(self.events()[-1]["id"], len(before["learning_events"]) + 1)

    def test_uncommitted_atomic_scope_is_not_persisted_by_close(self):
        self.build()
        before = self.snap()
        scope = self.m._atomic()
        scope.__enter__()
        self.k.learn("Ghost", "never committed", source="x")
        self.m.add_learning_event("teach", "Ghost", detail="never committed", source="x")
        self.m._conn.close()                                                            # simulated crash: no commit
        try:
            scope.gen.close()                                                           # discard the dead scope quietly
        except Exception:
            pass
        self._open()
        self.assertEqual(self.snap(), before)
        self.assertIsNone(self.k.get("Ghost"))

    # ---- P5: ambiguity ----------------------------------------------------------------------------------------
    def test_ambiguous_resolution_is_deterministic_after_reload(self):
        self.ls.teach("Python", "a")
        self.ls.teach("python", "b")
        self.ls.teach("PYTHON", "c")
        first = self.k.resolve_name("pYthon")
        self.reopen()
        again = self.k.resolve_name("pYthon")
        self.assertEqual(first, again)
        self.assertEqual((again["status"], again["candidates"]), ("ambiguous", ["PYTHON", "Python", "python"]))
        self.assertIsNone(self.k.find_by_name_case_insensitive("pYthon"))
        self.assertEqual(self.k.resolve_name("python")["status"], "exact")            # exact case always wins
        before = self.snap()
        with self.assertRaises(ValueError):
            self.ls.correct("pYthon", "x")
        self.assertEqual(self.snap(), before)
        self.ls.correct("python", "b2")                                                # exact name still works
        self.assertEqual([self.k.get(n)["description"] for n in ("Python", "python", "PYTHON")], ["a", "b2", "c"])

    # ---- P6: language persistence with their own repeat semantics --------------------------------------------------
    def test_language_items_and_relationships_persist_with_own_repeat_semantics(self):
        self.build()
        ll, lr = self.core.language_learning, self.core.language_relationships
        item = ll.get_item("english", "word", "feline")
        rel = lr.relationships_for(concept_ref("Cat"))[0]
        self.assertEqual((item["version"], rel["version"]), (2, 1))
        self.reopen()
        ll, lr = self.core.language_learning, self.core.language_relationships
        self.assertEqual(ll.get_item("english", "word", "Feline"), item)                # identity survives reload
        self.assertEqual(lr.relationships_for(concept_ref("Cat"))[0], rel)              # verbatim, same id/version
        self.assertEqual(len(lr.relationships_for(concept_ref("Cat"))), 1)
        # repeats after reload are REAL updates (unlike knowledge no-ops): version+1, event, created False
        again = ll.learn_item("english", "word", "feline", meaning="cat-like", source="user", source_context="ctx")
        self.assertEqual((again["id"], again["version"], again["created_at"]), (item["id"], 3, item["created_at"]))
        r2 = self.core.relate_language_items(item_ref("english", "word", "feline"), concept_ref("Cat"),
                                             "concept_to_expression", source="user")
        self.assertEqual((r2["created"], r2["id"], r2["version"]), (False, rel["id"], 2))
        self.assertEqual(len(self.events("language_item_updated")), 2)        # build repeat + post-reload repeat
        self.assertEqual(len(self.events("language_relationship_updated")), 1)
        self.assertEqual(len(self.m.query("SELECT * FROM language_item_relationships")), 1)
        # the concept endpoint keeps its identity through knowledge lifecycle + reload
        self.ls.correct("Cat", "after language link")
        self.reopen()
        self.assertEqual(len(self.core.language_relationships.relationships_for(concept_ref("Cat"))), 1)
        self.assertEqual(self.k.get("Cat")["description"], "after language link")

    def test_core_and_bare_stack_see_the_same_persisted_state(self):
        self.build()
        core_view = self.readers()["all"], self.snap()
        self.m._conn.close()
        m = MemorySystem(self.db)
        k = KnowledgeSystem(m)
        ls = LearningSystem(ConceptSystem(k), k, memory=m)
        self.assertEqual(k.all(), core_view[0])
        self.assertEqual(self.snap(m), core_view[1])
        ls.teach("Bare", "written by the bare stack", source="user")
        m._conn.close()
        self._open()
        self.assertEqual(self.k.get("Bare")["description"], "written by the bare stack")
        self.assertEqual(self.events()[-1]["target"], "Bare")


if __name__ == "__main__":
    unittest.main()
