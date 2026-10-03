"""Prompt 657 - Section 3: end-of-lifecycle / status behavior of knowledge records.

AUDIT, not a feature. Findings pinned here (no production change was needed):

  S1  There is NO retirement / deactivation / archive / delete API for knowledge. `status` is a plain persisted TEXT
      column. Production writes it in exactly one place, KnowledgeSystem.learn() (INSERT / UPDATE), reached via
        - learn(status=...)        direct KnowledgeSystem call (default "active"; any string is stored, unvalidated)
        - correct(status=...)      KnowledgeSystem.correct(): None -> "active"
        - _relate()                creates missing endpoints with status "stub"
      LearningSystem.teach()/correct()/NL learning can only produce "active" (teach/correct) or "stub" (relate).
      Non-active values other than "stub" are reachable ONLY by calling KnowledgeSystem directly (tests use
      "deprecated", an existing test convention; nothing here endorses or adds a status value).
  S2  Three states are different and never conflated:
        non-active existing : row present, same id, resolvable, listed, searchable, relationship-bearing
        non-existent        : get() None, resolve not_found, correct() returns None, nothing is created
        historically changed: learning_events rows exist for the name; says nothing about current status
  S3  A status change is an ordinary mutation: version + 1, updated_at moves, id/created_at/provenance stay; the same
      effective values again are a no-op. Direct KnowledgeSystem calls write no events (L4); LearningSystem.teach /
      correct write their usual events, and a status-only correct logs "'d' -> 'd'" (L2, preserved).
  S4  Relationships are attached to exact names and are never redirected, duplicated, deleted or status-filtered.
  S5  Readers (get / all / search / recall / resolve_name / select_learned_knowledge) do not filter by status; a
      bare stub with no description and no edge is not "usable" for learned-knowledge context (Prompt 637/638).
"""
import os
import re
import tempfile
import unittest
from unittest import mock

from core.core import Core
from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from language_intelligence.learned_knowledge_context import select_learned_knowledge, STATUS_SELECTED, STATUS_NOT_FOUND
from language_intelligence.language_relationships import concept_ref, item_ref

TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items",
          "language_item_relationships", "sqlite_sequence")
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEP = "deprecated"                    # existing test convention for a non-active, non-stub status


class Boom(RuntimeError):
    pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "l.db")
        self._open()

    def _open(self):
        self.core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m = self.core.knowledge, self.core.learning, self.core.memory

    def reopen(self):
        self.m._conn.close()
        self._open()

    def snap(self):
        return {t: [dict(r) for r in self.m.query(f"SELECT * FROM {t} ORDER BY 1, 2")] for t in TABLES}

    def rec(self, name):
        return self.k.get(name)

    def events(self, *types):
        return [e for e in self.m.query("SELECT * FROM learning_events ORDER BY id")
                if not types or e["event_type"] in types]

    def seed_inactive(self, name="Old", desc="legacy fact", status=DEP):
        """A taught record that is then moved to a non-active status through the only path that can do it."""
        self.ls.teach(name, desc, source="user", confidence=0.6, source_text="seed", learning_method="ael")
        self.k.learn(name, desc, status=status, source="user")
        return self.rec(name)


class Inventory(Base):
    def test_no_retirement_or_deletion_api_exists(self):
        banned = re.compile(r"retire|deactivat|archiv|delete|remove|forget|purge|expire|disable|prune|gc$|garbage",
                            re.I)
        for obj in (self.k, self.ls, ConceptSystem(self.k), self.core):
            names = [n for n in dir(obj) if not n.startswith("__")]
            hits = [n for n in names if banned.search(n) and callable(getattr(obj, n, None))]
            knowledge_hits = [n for n in hits if "knowledge" in n.lower() or "concept" in n.lower()
                              or type(obj) is not Core]
            self.assertEqual(knowledge_hits, [], f"{type(obj).__name__} exposes a lifecycle-end API: {knowledge_hits}")

    def test_knowledge_rows_are_written_only_by_knowledge_system_and_never_deleted(self):
        writers, deleters = set(), set()
        for d, _, fs in os.walk(PY_ROOT):
            if os.sep + "tests" in d or "__pycache__" in d:
                continue
            for f in fs:
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    text = fh.read()
                rel = os.path.relpath(os.path.join(d, f), PY_ROOT).replace(os.sep, "/")
                if re.search(r"(UPDATE\s+knowledge\b|INSERT\s+INTO\s+knowledge\b)", text, re.I):
                    writers.add(rel)
                if re.search(r"DELETE\s+FROM\s+knowledge\b", text, re.I):
                    deleters.add(rel)
        self.assertEqual(writers, {"knowledge/knowledge_system.py"})
        self.assertEqual(deleters, set())

    def test_status_defaults_and_reachable_values_through_learning_system(self):
        self.ls.teach("A", "a", source="user")
        self.ls.relate("A", "B", "is_a", source="user")
        self.core.learn_from_text("Python is a language.")
        self.assertEqual(self.rec("A")["status"], "active")
        self.assertEqual(self.rec("B")["status"], "stub")
        self.assertEqual(self.rec("Python")["status"], "stub")
        self.assertEqual({r["status"] for r in self.k.all()}, {"active", "stub"})
        # LearningSystem can never produce anything else, even when asked to "correct" or re-teach a stub
        self.ls.correct("B", "now described")
        self.ls.teach("Python", "a language", source="user")
        st = {r["name"]: r["status"] for r in self.k.all()}
        self.assertEqual([n for n in ("A", "B", "Python") if st[n] != "active"], [])
        self.assertEqual(set(st.values()), {"active", "stub"})          # the untouched NL stub ("language") stays a stub
        self.assertTrue(all(v in ("active", "stub") for v in st.values()))

    def test_schema_status_is_plain_text_default_active(self):
        cols = {r["name"]: r for r in self.m.query("PRAGMA table_info(knowledge)")}
        self.assertEqual(cols["status"]["type"], "TEXT")
        self.assertEqual(cols["status"]["dflt_value"], "'active'")
        self.assertEqual(self.m.query("SELECT sql FROM sqlite_master WHERE name='knowledge'")[0]["sql"].count("CHECK"), 0)


class ThreeStatesAreDistinct(Base):
    def test_nonactive_vs_nonexistent_vs_historically_changed(self):
        self.ls.teach("Hist", "v1", source="user")
        self.ls.correct("Hist", "v2")                                   # historically changed, currently active
        self.ls.relate("Edge", "Other", "is_a", source="user")          # non-active (stub), no events of its own
        self.seed_inactive("Old")                                        # non-active with history
        # non-existent
        self.assertIsNone(self.rec("Ghost"))
        self.assertEqual(self.k.resolve_name("Ghost"), {"status": "not_found", "record": None, "candidates": []})
        self.assertEqual([e for e in self.events() if e["target"] == "Ghost"], [])
        before = self.snap()
        self.assertIsNone(self.ls.correct("Ghost", "x"))                # correction never creates
        self.assertIsNone(self.k.correct("Ghost", "x"))
        self.assertIsNone(self.rec("Ghost"))
        self.assertEqual(self.snap(), before)
        # non-active but existing (stub AND deprecated) - resolvable, listed, identifiable
        for name, status in (("Edge", "stub"), ("Other", "stub"), ("Old", DEP)):
            r = self.k.resolve_name(name)
            self.assertEqual((r["status"], r["record"]["name"], r["record"]["status"]), ("exact", name, status))
            self.assertIn(name, [x["name"] for x in self.k.all()])
        # historically changed: events exist, current status is independent of that fact
        self.assertEqual(len(self.events("teach", "correct")), 3)       # Hist teach+correct, Old teach
        self.assertEqual(self.rec("Hist")["status"], "active")
        self.assertEqual([e for e in self.events() if e["target"] == "Edge" and e["event_type"] != "relate"], [])
        self.assertEqual(self.rec("Edge")["status"], "stub")            # non-active with NO teach/correct history
        self.assertEqual(self.rec("Old")["status"], DEP)                # non-active WITH teach history

    def test_nonactive_record_is_not_a_different_identity_for_any_reader(self):
        old = self.seed_inactive("Old")
        self.ls.relate("Old", "New", "replaced_by", source="user")
        self.assertEqual(self.k.get("Old")["id"], old["id"])
        for got in (self.k.find_by_name_case_insensitive("OLD"), self.k.resolve_name("old")["record"],
                    self.k.search("legacy")[0], self.ls.recall("Old"), [r for r in self.k.all() if r["name"] == "Old"][0]):
            self.assertEqual((got["id"], got["name"], got["status"], got["version"]),
                             (old["id"], "Old", DEP, self.rec("Old")["version"]))
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='old'")), 1)
        self.assertEqual(len(self.k.all(kind="concept")), 2)            # Old + New, status never filters
        self.assertEqual(self.ls.recall("Old")["relationships"]["outgoing"][0]["to_name"], "New")


class Transitions(Base):
    def test_active_to_nonactive_and_back_preserve_identity_provenance_and_edges(self):
        self.ls.teach("Old", "fact", source="user", confidence=0.6, source_text="st", learning_method="ael")
        self.ls.relate("Old", "New", "replaced_by", source="user", confidence=0.4)
        active = self.rec("Old")
        edge = self.m.query("SELECT * FROM relationships")[0]
        ev_before = self.events()
        dep = self.k.learn("Old", "fact", status=DEP, source="user")                    # active -> inactive
        self.assertEqual((dep["id"], dep["created_at"], dep["version"], dep["status"]),
                         (active["id"], active["created_at"], active["version"] + 1, DEP))
        self.assertGreaterEqual(dep["updated_at"], active["updated_at"])
        for f in ("description", "kind", "source", "confidence", "source_text", "learning_method", "name"):
            self.assertEqual(dep[f], active[f], f)
        self.assertEqual(self.events(), ev_before)                                      # L4: direct call, no event
        back = self.k.correct("Old", "fact")                                            # inactive -> active
        self.assertEqual((back["id"], back["status"], back["version"]), (active["id"], "active", active["version"] + 2))
        for f in ("description", "kind", "source", "confidence", "source_text", "learning_method", "created_at"):
            self.assertEqual(back[f], active[f], f)
        self.assertEqual(self.m.query("SELECT * FROM relationships")[0], edge)          # edge verbatim throughout
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE name='Old'")), 1)

    def test_repeated_transition_is_noop(self):
        old = self.seed_inactive()
        before, n = self.snap(), len(self.events())
        for _ in range(3):
            r = self.k.learn("Old", "legacy fact", status=DEP, source="user")
            self.assertEqual(r, old)
            self.assertEqual(self.k.correct("Old", "legacy fact", status=DEP), old)
            self.assertEqual(self.k.correct("OLD", "legacy fact", status=DEP), old)     # unique ci-match, same values
        self.assertEqual(self.snap(), before)
        self.assertEqual(len(self.events()), n)

    def test_flip_flop_is_real_each_time(self):
        old = self.seed_inactive()
        v = old["version"]
        for i in range(3):
            self.k.correct("Old", "legacy fact")                       # -> active
            self.k.correct("Old", "legacy fact", status=DEP)           # -> deprecated
            v += 2
            self.assertEqual(self.rec("Old")["version"], v)
        self.assertEqual((self.rec("Old")["status"], self.rec("Old")["id"]), (DEP, old["id"]))
        self.assertEqual(len(self.events()), 1)                        # still only the seed teach: L4

    def test_teach_of_inactive_record_reactivates_in_place_with_teach_event(self):
        old = self.seed_inactive()
        n = len(self.events())
        r = self.ls.teach("Old", "legacy fact", source="user")         # same text: only the status differs
        self.assertEqual((r["id"], r["status"], r["version"]), (old["id"], "active", old["version"] + 1))
        self.assertEqual((r["confidence"], r["source_text"], r["learning_method"]),
                         (old["confidence"], old["source_text"], old["learning_method"]))
        ev = self.events()
        self.assertEqual(len(ev), n + 1)
        self.assertEqual((ev[-1]["event_type"], ev[-1]["target"], ev[-1]["detail"]), ("teach", "Old", "legacy fact"))
        again = self.snap()
        self.ls.teach("Old", "legacy fact", source="user")             # now an exact no-op
        self.assertEqual(self.snap(), again)

    def test_correction_of_inactive_record_updates_one_row_and_logs_real_change(self):
        old = self.seed_inactive()
        n = len(self.events())
        r = self.ls.correct("old", "new text")                          # case-insensitive unique resolve
        self.assertEqual((r["id"], r["name"], r["status"], r["version"], r["description"]),
                         (old["id"], "Old", "active", old["version"] + 1, "new text"))
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='old'")), 1)
        ev = self.events()
        self.assertEqual((len(ev), ev[-1]["event_type"], ev[-1]["target"], ev[-1]["detail"]),
                         (n + 1, "correct", "Old", "'legacy fact' -> 'new text'"))

    def test_status_only_correction_keeps_documented_event_semantics(self):
        self.seed_inactive()
        self.ls.correct("Old", "legacy fact")                           # status-only: deprecated -> active
        last = self.events()[-1]
        self.assertEqual((last["event_type"], last["detail"], last["source"]), ("correct", "'legacy fact' -> 'legacy fact'", "user"))
        self.assertEqual(self.rec("Old")["status"], "active")
        n = len(self.events())
        self.ls.correct("Old", "legacy fact")                           # nothing left to change -> no phantom event
        self.assertEqual(len(self.events()), n)

    def test_stub_upgrade_is_the_supported_inactive_to_active_path_and_no_duplicate(self):
        self.ls.relate("Cat", "Animal", "is_a", source="user", source_text="t", learning_method="m")
        stub = self.rec("Cat")
        r = self.ls.teach("Cat", "a feline", source="user")
        self.assertEqual((r["id"], r["created_at"], r["status"], r["version"]), (stub["id"], stub["created_at"], "active", 2))
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='cat'")), 1)
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 1)
        self.assertEqual([e["event_type"] for e in self.events()], ["relate", "teach"])     # stub itself had none (L1)


class RelationshipsAroundInactiveRecords(Base):
    def test_relate_with_inactive_endpoints_reuses_them_and_does_not_reactivate_or_bump(self):
        old = self.seed_inactive("Old")
        stub_b = self.k.learn("B", None, status="stub")
        before = {r["name"]: r for r in self.k.all()}
        self.ls.relate("Old", "B", "replaced_by", source="user")
        self.ls.relate("B", "Old", "replaces", source="user")
        after = {r["name"]: r for r in self.k.all()}
        self.assertEqual(after, before)                                  # endpoints verbatim: status, version, ts
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge")), 2)    # nothing auto-created next to them
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 2)

    def test_edges_survive_every_status_transition_verbatim(self):
        self.ls.teach("A", "a", source="user")
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.7, source_text="s")
        self.ls.relate("C", "A", "part_of", source="user")
        edges = self.m.query("SELECT * FROM relationships ORDER BY id")
        for step in (lambda: self.k.learn("A", "a", status=DEP, source="user"),
                     lambda: self.k.learn("A", "a", status="stub", source="user"),
                     lambda: self.ls.teach("A", "a", source="user"),
                     lambda: self.k.correct("A", "a", status=DEP),
                     lambda: self.ls.correct("A", "a2")):
            step()
            self.assertEqual(self.m.query("SELECT * FROM relationships ORDER BY id"), edges)
        self.assertEqual([r["to_name"] for r in self.k.relationships_for("A")["outgoing"]], ["B"])
        self.assertEqual([r["from_name"] for r in self.k.relationships_for("A")["incoming"]], ["C"])

    def test_edge_refresh_on_inactive_endpoint_touches_only_the_edge(self):
        self.ls.teach("A", "a", source="user")
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.7)
        self.k.learn("A", "a", status=DEP, source="user")
        before = self.snap()
        self.ls.relate("A", "B", "is_a", source="user", confidence=0.2)
        after = self.snap()
        self.assertEqual(after["knowledge"], before["knowledge"])
        self.assertEqual(len(after["relationships"]), 1)
        self.assertEqual(after["relationships"][0]["confidence"], 0.2)
        self.assertEqual(len(after["learning_events"]), len(before["learning_events"]) + 1)


class ReadersDoNotFilterByStatus(Base):
    def test_all_search_recall_and_context_selection_see_inactive_records(self):
        self.seed_inactive("Python", "a snake")
        self.assertEqual([r["status"] for r in self.k.search("snake")], [DEP])
        self.assertEqual(self.ls.recall("Python")["status"], DEP)
        s = select_learned_knowledge("what is Python", self.k, ["python"])
        self.assertEqual((s.status, s.record["status"], s.record["description"]), (STATUS_SELECTED, DEP, "a snake"))
        # a bare stub (no description, no edge) is not usable content; the SAME stub with an edge is (Prompt 637/638)
        self.k.learn("Bare", None, status="stub")
        self.assertEqual(select_learned_knowledge("what is Bare", self.k, ["bare"]).status, STATUS_NOT_FOUND)
        self.ls.relate("Bare", "Other", "is_a", source="user")
        self.assertEqual(select_learned_knowledge("what is Bare", self.k, ["bare"]).status, STATUS_SELECTED)
        self.assertEqual(self.rec("Bare")["status"], "stub")

    def test_language_endpoint_keeps_resolving_after_status_transitions(self):
        self.ls.teach("Cat", "a feline", source="user")
        self.core.language_learning.learn_item("english", "word", "feline", meaning="cat-like", source="user",
                                               source_context="c")
        self.core.relate_language_items(item_ref("english", "word", "feline"), concept_ref("Cat"),
                                        "concept_to_expression", source="user")
        rel = self.core.language_relationships.relationships_for(concept_ref("Cat"))
        items = self.m.query("SELECT * FROM language_learning_items")
        self.k.learn("Cat", "a feline", status=DEP, source="user")
        self.ls.teach("Cat", "a feline", source="user")
        self.assertEqual(self.core.language_relationships.relationships_for(concept_ref("Cat")), rel)
        self.assertEqual(self.m.query("SELECT * FROM language_learning_items"), items)


class NaturalLanguagePaths(Base):
    def test_nl_relations_reuse_inactive_records_without_mutating_them(self):
        self.k.learn("Cat", "a feline", status=DEP, source="user")
        cat = self.rec("Cat")
        self.core.learn_from_text("Cat is an animal.")
        self.assertEqual(self.rec("Cat"), cat)                           # endpoint untouched: no reactivation, no bump
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='cat'")), 1)
        edge = self.m.query("SELECT * FROM relationships")[0]
        self.assertEqual((edge["from_name"], edge["to_name"]), ("Cat", "animal"))
        self.assertEqual(self.rec("animal")["status"], "stub")

    def test_conversational_correction_goes_through_the_same_correct_contract(self):
        self.ls.teach("Python", "a snake", source="user")
        self.k.learn("Python", "a snake", status=DEP, source="user")
        v = self.rec("Python")["version"]
        self.core.process_input("not a snake, I mean a programming language.")
        r = self.rec("Python")
        self.assertEqual((r["status"], r["version"], r["description"]), ("active", v + 1, "a programming language"))
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge WHERE LOWER(name)='python'")), 1)
        last = self.events("correct")[-1]
        self.assertEqual((last["target"], last["detail"], last["source"]),
                         ("Python", "'a snake' -> 'a programming language'", "user_correction"))

    def test_nl_on_unrelated_concept_leaves_inactive_records_alone(self):
        old = self.seed_inactive("Old")
        before = self.snap()
        self.core.learn_from_text("Python is a language.")
        after = self.snap()
        self.assertEqual({r["name"]: r for r in after["knowledge"]}["Old"], old)
        self.assertEqual(after["learning_events"][:len(before["learning_events"])], before["learning_events"])


class FailureAmbiguityNoop(Base):
    def test_failed_lifecycle_operations_change_nothing(self):
        self.seed_inactive("Old")
        self.ls.relate("Old", "New", "replaced_by", source="user")
        before = self.snap()
        with mock.patch.object(type(self.m), "add_learning_event", side_effect=Boom("e")):
            for op in (lambda: self.ls.teach("Old", "legacy fact", source="user"),      # reactivation
                       lambda: self.ls.correct("Old", "legacy fact"),                    # status-only correct
                       lambda: self.ls.correct("Old", "other"),
                       lambda: self.ls.relate("Old", "Brand", "x")):
                with self.assertRaises(Boom):
                    op()
        self.assertEqual(self.snap(), before)
        self.reopen()
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.rec("Old")["status"], DEP)

    def test_invalid_lifecycle_calls_write_nothing(self):
        self.seed_inactive("Old")
        before = self.snap()
        for op in (lambda: self.k.learn("", "d", status=DEP), lambda: self.k.learn(None, "d"),
                   lambda: self.k.correct("Old", ""), lambda: self.k.correct("", "d"),
                   lambda: self.ls.correct("Old", "   ")):
            with self.assertRaises(ValueError):
                op()
        self.assertEqual(self.snap(), before)

    def test_case_variants_cannot_cause_an_unintended_lifecycle_mutation(self):
        self.ls.teach("Python", "a", source="user")
        self.ls.teach("python", "b", source="user")
        self.k.learn("Python", "a", status=DEP, source="user")
        before = self.snap()
        with self.assertRaises(ValueError):
            self.k.correct("pYthon", "a", status="active")
        with self.assertRaises(ValueError):
            self.ls.correct("PYTHON", "zzz")
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.k.resolve_name("pYthon")["status"], "ambiguous")
        self.k.correct("python", "b2")                                   # exact name: only that record moves
        after = {r["name"]: r for r in self.k.all()}
        self.assertEqual(after["Python"], {r["name"]: r for r in before["knowledge"]}["Python"])
        self.assertEqual((after["python"]["description"], after["Python"]["status"]), ("b2", DEP))
        n = len(self.m.query("SELECT * FROM knowledge"))
        self.assertIsNone(self.k.correct("Pythonn", "x"))                # near-miss is non-existent, not a lifecycle op
        self.assertEqual(len(self.m.query("SELECT * FROM knowledge")), n)

    def test_noop_lifecycle_operations_create_no_events_or_writes(self):
        self.seed_inactive("Old")
        self.ls.teach("Old", "legacy fact", source="user")               # reactivate (real)
        before = self.snap()
        for op in (lambda: self.ls.teach("Old", "legacy fact", source="user"),
                   lambda: self.ls.correct("Old", "legacy fact"),
                   lambda: self.ls.correct("old", "legacy fact"),
                   lambda: self.k.learn("Old", "legacy fact", status="active", source="user")):
            op()
        self.assertEqual(self.snap(), before)


class HistoryAndPersistence(Base):
    def test_events_stay_historical_and_direct_transitions_add_none(self):
        self.ls.teach("A", "v1", source="user")
        self.ls.correct("A", "v2")
        hist = self.events()
        self.k.learn("A", "v2", status=DEP)
        self.k.correct("A", "v2")
        self.k.learn("A", "v2", status="stub")
        self.assertEqual(self.events(), hist)                                            # history untouched (L4)
        live = self.rec("A")
        self.assertEqual((live["status"], live["description"]), ("stub", "v2"))          # live row stays authoritative
        # version is NOT reconstructable from events once direct status transitions happened (documented L4)
        self.assertGreater(live["version"], len(hist) + 1)
        self.assertEqual([e["detail"] for e in hist], ["v1", "'v1' -> 'v2'"])

    def test_history_of_reactivated_record_is_appended_never_rewritten(self):
        self.seed_inactive("Old")
        first = self.events()
        self.ls.teach("Old", "legacy fact", source="user")
        self.ls.correct("Old", "changed")
        ev = self.events()
        self.assertEqual(ev[:len(first)], first)
        self.assertEqual([e["event_type"] for e in ev], ["teach", "teach", "correct"])
        self.assertTrue(all(e["target"] == "Old" for e in ev))
        self.assertEqual([e["id"] for e in ev], list(range(1, len(ev) + 1)))

    def test_lifecycle_state_survives_reopen_exactly_and_continues(self):
        self.seed_inactive("Old")
        self.ls.relate("Old", "New", "replaced_by", source="user")
        self.ls.relate("Stubby", "Other", "is_a", source="user")
        before = self.snap()
        for _ in range(2):
            self.reopen()
            self.assertEqual(self.snap(), before)
        self.assertEqual((self.rec("Old")["status"], self.rec("Stubby")["status"]), (DEP, "stub"))
        v = self.rec("Old")["version"]
        r = self.ls.teach("Old", "legacy fact", source="user")                          # reactivate after reopen
        self.assertEqual((r["status"], r["version"]), ("active", v + 1))
        self.reopen()
        self.assertEqual(self.rec("Old")["status"], "active")
        self.assertEqual(len(self.m.query("SELECT * FROM relationships")), 2)
        before2 = self.snap()
        self.reopen()
        self.assertEqual(self.snap(), before2)

    def test_bare_stack_sees_same_lifecycle_state(self):
        self.seed_inactive("Old")
        self.m._conn.close()
        m = MemorySystem(self.db)
        k = KnowledgeSystem(m)
        ls = LearningSystem(ConceptSystem(k), k, memory=m)
        self.assertEqual(k.get("Old")["status"], DEP)
        ls.teach("Old", "legacy fact", source="user")
        m._conn.close()
        self._open()
        self.assertEqual(self.rec("Old")["status"], "active")

    def test_independent_lifecycle_sequences_are_order_independent(self):
        def scenario_a(s):
            s.ls.teach("A", "a", source="user"); s.k.learn("A", "a", status=DEP, source="user")
            s.ls.teach("A", "a", source="user")

        def scenario_b(s):
            s.ls.relate("B", "C", "is_a", source="user"); s.ls.teach("B", "b", source="user")
            s.ls.correct("B", "b2")

        def final(s):
            st = s.snap()
            return ({r["name"]: {k: v for k, v in r.items() if k not in ("id", "created_at", "updated_at")}
                     for r in st["knowledge"]},
                    sorted((e["event_type"], e["target"], e["detail"], e["source"]) for e in st["learning_events"]),
                    sorted((r["from_name"], r["relation_type"], r["to_name"]) for r in st["relationships"]))
        scenario_a(self); scenario_b(self)
        one = final(self)
        self.m._conn.close()
        self.db = os.path.join(tempfile.mkdtemp(), "o.db"); self._open()
        scenario_b(self); scenario_a(self)
        self.assertEqual(final(self), one)


if __name__ == "__main__":
    unittest.main()
