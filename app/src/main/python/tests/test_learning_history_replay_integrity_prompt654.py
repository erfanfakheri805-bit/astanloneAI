"""Prompt 654 - Section 3: learning-history replay / reconstruction integrity.

AUDIT, not event sourcing. The replay helper below lives in THIS FILE ONLY; no production replay code exists
or was added. It walks learning_events in id order and rebuilds, per knowledge record, exactly what the
CURRENT event contract records, then compares that to the live rows (which stay authoritative):

  teach     target=name        detail=NEW description        source=persisted source
  correct   target=stored name detail="<repr old> -> <repr new>"  source=persisted source
  relate    target=from_name   detail="<relation> -> <to>"   source=persisted relationship source_type
  language_*                   separate tables; never describe knowledge rows

Reconstructable (asserted): description, version, source, relationship edges, per-record ordering.
Intentionally NOT reconstructable (documented, asserted as limitations, no schema invented):
  L1 stub concepts created by relate()/NL have no event of their own (stub v1 is implied by the relate event);
  L2 teach/correct events carry no confidence / source_text / learning_method / status / kind values;
  L3 relate events carry no confidence / source_text / learning_method values, so a metadata-only refresh is
     an event with an unchanged detail;
  L4 direct KnowledgeSystem.learn()/relate() calls (below LearningSystem) write no events by design;
  L5 language events carry source_context only (no meaning/examples diff).
"""
import ast
import os
import tempfile
import unittest
from unittest import mock

from core.core import Core
from language_intelligence.language_relationships import concept_ref, item_ref


class Boom(RuntimeError):
    pass


def replay(events):
    """Rebuild {name: {description, version, source, stub}} and the edge set from the event contract."""
    state, edges, seen_ids = {}, set(), []
    for e in sorted(events, key=lambda r: r["id"]):
        seen_ids.append(e["id"])
        t, name, detail, src = e["event_type"], e["target"], e["detail"], e["source"]
        if t == "teach":
            if name in state:
                state[name].update(description=detail, source=src, version=state[name]["version"] + 1, stub=False)
            else:
                state[name] = {"description": detail, "version": 1, "source": src, "stub": False}
        elif t == "correct":
            prefix = repr(state[name]["description"]) + " -> "
            assert detail.startswith(prefix), f"correct event old value != replayed state: {detail!r}"
            new = ast.literal_eval(detail[len(prefix):])
            state[name].update(description=new, source=src, version=state[name]["version"] + 1)
        elif t == "relate":
            rel, _, to = detail.partition(" -> ")
            for n in (name, to):
                if n not in state:                     # L1: stub implied by the relate event
                    state[n] = {"description": None, "version": 1, "source": src or "inferred", "stub": True}
            edges.add((name, rel, to))
    assert seen_ids == sorted(set(seen_ids))
    return state, edges


class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "h.db")
        self._open()

    def _open(self):
        self.core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m = self.core.knowledge, self.core.learning, self.core.memory

    def reopen(self):
        self.m._conn.close()
        self._open()

    def events(self, *types):
        return [e for e in self.m.query("SELECT * FROM learning_events ORDER BY id")
                if not types or e["event_type"] in types]

    def snap(self):
        return {t: [dict(r) for r in self.m.query(f"SELECT * FROM {t} ORDER BY id")]
                for t in ("knowledge", "relationships", "learning_events",
                          "language_learning_items", "language_item_relationships")}

    def assert_replay_matches_live(self):
        state, edges = replay(self.events())
        live = {r["name"]: r for r in self.m.query("SELECT * FROM knowledge")}
        # only records the event model can see (L4: direct learn() writes have no events)
        for name, s in state.items():
            self.assertIn(name, live)
            self.assertEqual((s["description"], s["version"], s["source"]),
                             (live[name]["description"], live[name]["version"], live[name]["source"]), name)
            self.assertEqual(s["stub"], live[name]["status"] == "stub", name)
        self.assertEqual(set(state), set(live))     # no event-less record in these scenarios
        live_edges = {(r["from_name"], r["relation_type"], r["to_name"])
                      for r in self.m.query("SELECT * FROM relationships")}
        self.assertEqual(edges, live_edges)
        return state, edges

    def scenario(self):
        self.ls.teach("Cat", "a feline", source="user", confidence=0.5)          # create via teach
        self.ls.relate("Cat", "Animal", "is_a", source="user")                   # stub Animal
        self.ls.teach("Cat", "a small feline", source="user", confidence=0.7)
        self.ls.correct("cat", "a small domestic feline", source="user_correction")
        self.ls.teach("Animal", "a living being", source="ael")                  # stub -> taught
        self.ls.correct("Animal", "a living organism")                           # source None: keep
        self.ls.relate("Dog", "Animal", "is_a")                                  # new stub Dog, default source
        self.core.learn_from_text("Python is a language.")                       # NL: two stubs + edge
        self.ls.teach("Python", "a snake", source="user")
        self.core.process_input("not a snake, I mean a programming language.")   # conversational correction
        self.ls.teach("Python", "a programming language")                        # re-teach, default source

    # ---- 1-3, 6, 11: replay explains every reconstructable transition ------------------------------
    def test_replay_of_mixed_sequence_equals_live_state(self):
        self.scenario()
        state, edges = self.assert_replay_matches_live()
        self.assertEqual(state["Cat"]["version"], 3)                 # teach(create) + teach + correct
        self.assertEqual(self.k.get("Cat")["description"], "a small domestic feline")
        self.assertEqual(len(edges), 3)

    def test_version_equals_state_changing_events_plus_implied_stub_creation(self):
        self.scenario()
        for r in self.m.query("SELECT * FROM knowledge"):
            n = len(self.events("teach", "correct") and
                    [e for e in self.events("teach", "correct") if e["target"] == r["name"]])
            first = [e for e in self.events() if e["target"] == r["name"] or
                     (e["event_type"] == "relate" and r["name"] in (e["target"], e["detail"].partition(" -> ")[2]))]
            created_by_teach = bool(first) and first[0]["event_type"] == "teach"
            self.assertEqual(r["version"], n + (0 if created_by_teach else 1), r["name"])

    # ---- 4/5: deterministic ordering ----------------------------------------------------------------
    def test_ordering_is_by_id_with_equal_or_manual_timestamps(self):
        for stamp in (lambda: "2026-01-01T00:00:00+00:00",):                    # all equal
            with mock.patch("memory.memory_system._now", stamp):
                self.ls.teach("A", "1")
                self.ls.correct("A", "2")
                self.ls.teach("A", "3", source="x")
                self.ls.relate("A", "B", "r")
        ev = self.events()
        self.assertEqual([e["id"] for e in ev], list(range(1, len(ev) + 1)))
        self.assertEqual(len({e["created_at"] for e in ev}), 1)
        self.assertEqual([e["id"] for e in self.m.recent_learning_events(50)], [e["id"] for e in ev])
        state, _ = replay(ev)
        self.assertEqual((state["A"]["description"], state["A"]["version"]), ("3", 3))

    def test_manual_descending_timestamps_do_not_change_replay(self):
        stamps = iter(f"2026-01-01T00:00:{59 - i:02d}+00:00" for i in range(60))
        with mock.patch("memory.memory_system._now", lambda: next(stamps)):
            self.ls.teach("A", "1")
            self.ls.correct("A", "2")
            self.ls.teach("A", "3", source="x")
        ev = self.events()
        self.assertEqual([e["created_at"] for e in ev], sorted((e["created_at"] for e in ev), reverse=True))
        state, _ = replay(ev)                                    # id order, not timestamp order
        self.assertEqual(state["A"]["description"], self.k.get("A")["description"])
        self.assertEqual([e["id"] for e in self.m.recent_learning_events(50)], [1, 2, 3])

    def test_rollback_leaves_no_id_gap_and_replay_continues(self):
        self.ls.teach("A", "1")
        with mock.patch.object(type(self.m), "add_learning_event", side_effect=Boom("e")):
            with self.assertRaises(Boom):
                self.ls.teach("A", "2")
        self.ls.teach("A", "3", source="y")
        self.assertEqual([e["id"] for e in self.events()], [1, 2])
        self.assert_replay_matches_live()

    # ---- 7-9: no phantom transitions ----------------------------------------------------------------
    def test_noops_write_no_events_and_no_state(self):
        self.scenario()
        before = self.snap()
        self.ls.teach("Python", "a programming language")                       # same source as stored (ael)
        self.ls.correct("PYTHON", "a programming language")                     # source None keeps stored
        self.ls.correct("Cat", "a small domestic feline", source="user_correction")
        self.ls.relate("Cat", "Animal", "is_a", source="user")                  # identical effective values
        self.assertEqual(self.snap(), before)
        self.assert_replay_matches_live()
        # LearningSystem.relate() defaults source="ael" (like teach()): omitting it is a REAL source change,
        # so it refreshes the edge AND logs one event carrying the persisted source (existing contract).
        n = len(self.events("relate"))
        self.ls.relate("Cat", "Animal", "is_a")
        self.assertEqual(len(self.events("relate")), n + 1)
        self.assertEqual(self.events("relate")[-1]["source"], "ael")
        self.assertEqual(self.k.relationships_for("Cat")["outgoing"][0]["source_type"], "ael")
        self.ls.relate("Cat", "Animal", "is_a")                                 # now identical: true no-op
        self.assertEqual(len(self.events("relate")), n + 1)
        self.assert_replay_matches_live()

    def test_failed_atomic_ops_leave_no_event_and_no_state(self):
        self.scenario()
        before = self.snap()
        with mock.patch.object(type(self.m), "add_learning_event", side_effect=Boom("e")):
            for op in (lambda: self.ls.teach("Cat", "zzz", source="q"),
                       lambda: self.ls.correct("Cat", "yyy"),
                       lambda: self.ls.relate("Cat", "Fresh", "likes"),
                       lambda: self.ls.relate("Cat", "Animal", "is_a", confidence=0.1)):
                with self.assertRaises(Boom):
                    op()
        self.assertEqual(self.snap(), before)
        self.reopen()
        self.assertEqual(self.snap(), before)
        self.assert_replay_matches_live()

    def test_rejected_and_ambiguous_ops_write_nothing(self):
        self.ls.teach("Python", "a")
        self.ls.teach("python", "b")
        before = self.snap()
        with self.assertRaises(ValueError):
            self.ls.correct("PYTHON", "x")                                      # ambiguous
        self.assertIsNone(self.ls.correct("Nothing", "x"))                      # unknown: never creates
        for bad in (("", "d"), (None, "d"), ("  ", "d")):
            with self.assertRaises(ValueError):
                self.ls.teach(*bad)
        with self.assertRaises(ValueError):
            self.ls.correct("Python", "   ")
        for bad in (("", "B", "r"), ("A", None, "r"), ("A", "B", None)):
            with self.assertRaises(ValueError):
                self.ls.relate(*bad)
        self.assertEqual(self.snap(), before)
        self.assert_replay_matches_live()

    # ---- 10, 11: correction history and provenance --------------------------------------------------
    def test_correction_events_preserve_old_and_new_and_persisted_source(self):
        self.ls.teach("X", "old -> arrow", source="user")                       # description containing ' -> '
        self.ls.correct("X", "new \"quoted\" 'text'")                           # source None: keeps 'user'
        self.ls.correct("x", "third", source="user_correction")
        c = self.events("correct")
        self.assertEqual([e["source"] for e in c], ["user", "user_correction"])   # PERSISTED source, never None
        self.assertNotEqual(c[0]["detail"].split(" -> ", 1)[0], repr("old -> arrow"))  # naive split is unsafe...
        state, _ = replay(self.events())                                        # ...repr-prefix replay is exact
        self.assertEqual(state["X"]["description"], "third")
        self.assertEqual(self.k.get("X")["source"], "user_correction")
        self.assert_replay_matches_live()

    def test_event_source_matches_persisted_source_per_record(self):
        self.scenario()
        live = {r["name"]: r["source"] for r in self.m.query("SELECT * FROM knowledge")}
        last_src = {}
        for e in self.events("teach", "correct"):
            last_src[e["target"]] = e["source"]
        for name, src in last_src.items():
            self.assertEqual(src, live[name], name)

    # ---- 12: relationship events vs knowledge-record events -----------------------------------------
    def test_relate_events_never_mutate_endpoint_descriptions(self):
        self.ls.teach("A", "desc-a", source="user")
        self.ls.teach("B", "desc-b", source="user")
        self.ls.relate("A", "B", "is_a")
        self.ls.relate("A", "B", "is_a", confidence=0.3)                        # metadata refresh: event, no record change
        rel = self.events("relate")
        self.assertEqual(len(rel), 2)
        self.assertEqual({e["detail"] for e in rel}, {"is_a -> B"})
        self.assertEqual({e["target"] for e in rel}, {"A"})
        self.assertEqual([self.k.get(n)["version"] for n in ("A", "B")], [1, 1])
        self.assertEqual([self.k.get(n)["description"] for n in ("A", "B")], ["desc-a", "desc-b"])
        state, edges = self.assert_replay_matches_live()
        self.assertEqual(edges, {("A", "is_a", "B")})
        # a description that LOOKS like a relate detail is still a teach event (type decides, not text)
        self.ls.teach("C", "is_a -> B")
        state, edges = replay(self.events())
        self.assertEqual(state["C"]["description"], "is_a -> B")
        self.assertEqual(edges, {("A", "is_a", "B")})

    # ---- 13: language stores keep their own (intentional) update semantics -----------------------------
    def test_language_events_are_separate_and_follow_their_own_repeat_semantics(self):
        self.ls.teach("Cat", "c", source="user")
        ll = self.core.language_learning
        ll.learn_item("english", "word", "feline", meaning="m", source="user", source_context="ctx1")
        ll.learn_item("english", "word", "feline", meaning="m", source="user", source_context="ctx1")   # repeat = update
        ll.learn_item("english", "word", "Feline", meaning="m2")                # None source keeps stored
        ev = self.events("language_item_learned", "language_item_updated")
        self.assertEqual([e["event_type"] for e in ev],
                         ["language_item_learned", "language_item_updated", "language_item_updated"])
        self.assertEqual({e["target"] for e in ev[:2]}, {"english:word:feline"})
        self.assertEqual(ev[2]["source"], "user")                               # persisted source, not None
        item = ll.get_item("english", "word", "feline")
        self.assertEqual(item["version"], len(ev))                              # every repeat is a real update
        r1 = self.core.relate_language_items(item_ref("english", "word", "feline"), concept_ref("Cat"),
                                             "concept_to_expression", source="user")
        r2 = self.core.relate_language_items(item_ref("english", "word", "feline"), concept_ref("Cat"),
                                             "concept_to_expression")
        lr = self.events("language_relationship_learned", "language_relationship_updated")
        self.assertEqual([e["event_type"] for e in lr],
                         ["language_relationship_learned", "language_relationship_updated"])
        self.assertEqual((r1["created"], r2["created"], r2["version"]), (True, False, 2))
        self.assertEqual(lr[1]["source"], "user")
        # language events never enter knowledge replay
        state, edges = self.assert_replay_matches_live()
        self.assertEqual(state["Cat"]["version"], 1)
        self.assertEqual(edges, set())

    # ---- 14: history stays historical; live rows are authoritative ---------------------------------------
    def test_stale_event_data_never_leaks_into_current_readers(self):
        self.ls.teach("Cat", "v1", source="user")
        self.ls.correct("Cat", "v2")
        self.ls.teach("Cat", "v3", source="ael")
        teach_details = [e["detail"] for e in self.events("teach")]
        self.assertEqual(teach_details, ["v1", "v3"])
        self.assertEqual(self.events("correct")[0]["detail"], "'v1' -> 'v2'")
        # a naive 'newest teach event' would be wrong after a later correct(); the live row is right
        self.ls.correct("Cat", "v4")
        self.assertEqual(self.events("teach")[-1]["detail"], "v3")
        for reader in (lambda: self.k.get("Cat"), lambda: self.ls.recall("Cat"),
                       lambda: self.k.find_by_name_case_insensitive("cat"),
                       lambda: self.k.resolve_name("cat")["record"],
                       lambda: self.k.search("Cat")[0], lambda: self.k.all()[0]):
            self.assertEqual(reader()["description"], "v4")
        self.assertNotIn("v1", [r["description"] for r in self.k.all()])
        self.assertEqual(self.core.recent_learning_events(50), self.events())   # history reader: id order, all rows

    def test_metadata_only_changes_are_the_documented_limitation(self):
        self.ls.teach("A", "same", source="user", confidence=0.2)
        self.ls.teach("A", "same", source="user", confidence=0.9)               # confidence-only real change
        ev = self.events("teach")
        self.assertEqual([e["detail"] for e in ev], ["same", "same"])           # L2: no confidence in the event
        self.assertEqual(self.k.get("A")["version"], 2)                         # ...but version still counts it
        self.assertEqual(self.k.get("A")["confidence"], 0.9)
        self.assertNotIn("confidence", ev[0])
        self.assert_replay_matches_live()                                       # description/version/source still replay
        self.ls.relate("A", "B", "r", confidence=0.4, source_text="s1")
        self.ls.relate("A", "B", "r", confidence=0.6, source_text="s2")
        self.assertEqual([(e["detail"], e["source"]) for e in self.events("relate")],
                         [("r -> B", "ael")] * 2)                                # L3: refresh indistinguishable in-event

    def test_direct_layer_writes_are_outside_the_event_contract(self):
        self.k.learn("Raw", "direct", source="x")                               # L4: below LearningSystem
        self.k.relate("Raw", "Raw2", "r")
        self.assertEqual(self.events(), [])
        self.assertEqual(self.k.get("Raw")["version"], 1)

    # ---- 16: reopen ------------------------------------------------------------------------------------
    def test_reopen_preserves_history_state_and_replay(self):
        self.scenario()
        before = self.snap()
        state_before = self.assert_replay_matches_live()
        self.reopen()
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.assert_replay_matches_live(), state_before)
        # history keeps growing monotonically after reopen
        last = self.events()[-1]["id"]
        self.ls.correct("Cat", "after reopen")
        self.assertEqual(self.events()[-1]["id"], last + 1)
        self.assert_replay_matches_live()
        self.reopen()
        self.assert_replay_matches_live()

    def test_replay_is_deterministic_and_read_only(self):
        self.scenario()
        before = self.snap()
        a = replay(self.events())
        b = replay(list(reversed(self.events())))                              # input order must not matter
        self.assertEqual(a, b)
        self.assertEqual(self.snap(), before)


if __name__ == "__main__":
    unittest.main()
