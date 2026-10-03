"""Prompt 661 - Section 3: consistency between the knowledge retrieval APIs.

APIs under test (all read-only, all over the one `knowledge` / `relationships` store):
  KnowledgeSystem.get / resolve_name / find_by_name_case_insensitive / search / all / relationships_for
  language_intelligence.learned_knowledge_context.select_learned_knowledge
  LearningSystem.recall / LearningSystem.search (thin public wrappers)

Pinned: every API observes the same current stored row (identity + every field it exposes), history
(learning_events) never leaks in as current knowledge, ambiguity never selects a record, retrieval is
strictly read-only (also for invalid input), and everything survives close/reopen.
Intentional differences (not "fixed"): get()/relationships_for() are exact-case; resolve_name() is
exact -> unique case-insensitive; search() is token/substring overlap, independent of resolve_name
ambiguity; select_learned_knowledge() needs learned content (description or relationships).
"""
import copy
import os
import re
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem, _SEARCH_MAX_ROWS
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem
from language_intelligence.learned_knowledge_context import (
    select_learned_knowledge, STATUS_SELECTED, STATUS_AMBIGUOUS, STATUS_NOT_FOUND)

TABLES = ("knowledge", "relationships", "learning_events")
FIELDS = ("id", "name", "description", "kind", "status", "source", "source_text", "confidence",
          "learning_method", "version", "created_at", "updated_at")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "c.db")
        self._open()

    def _open(self):
        self.m = MemorySystem(self.db)
        self.k = KnowledgeSystem(self.m)
        self.l = LearningSystem(ConceptSystem(self.k), self.k, memory=self.m)

    def reopen(self):
        self.m._conn.close()
        self._open()

    def snap(self):
        return {t: [dict(r) for r in self.m.query(f"SELECT * FROM {t} ORDER BY id")] for t in TABLES}

    def stored(self, name):
        """Ground truth: the raw row straight from SQL."""
        r = self.m.query_one("SELECT * FROM knowledge WHERE name = ?", (name,))
        return dict(r) if r else None

    def observe_all(self, name, message=None):
        """Assert every API that can see `name` (exact stored name) returns the SAME stored row."""
        truth = self.stored(name)
        self.assertIsNotNone(truth, name)
        self.assertEqual(dict(self.k.get(name)), truth)
        res = self.k.resolve_name(name)
        self.assertEqual(res["status"], "exact")
        self.assertEqual(dict(res["record"]), truth)
        self.assertEqual(dict(self.k.find_by_name_case_insensitive(name)), truth)
        in_all = [dict(r) for r in self.k.all() if r["name"] == name]
        self.assertEqual(in_all, [truth])
        in_kind = [dict(r) for r in self.k.all(truth["kind"]) if r["name"] == name]
        self.assertEqual(in_kind, [truth])
        for r in self.k.all():
            if r["name"] == name:
                for f in FIELDS:
                    self.assertEqual(r[f], truth[f], f)
        if truth["description"]:
            hits = [dict(r) for r in self.k.search(name) if r["name"] == name]
            self.assertEqual(hits, [truth])
        rec = self.l.recall(name)
        if rec is not None:
            base = rec.get("concept", rec) if isinstance(rec, dict) else rec
            if isinstance(base, dict) and "name" in base:
                for f in FIELDS:
                    if f in base:
                        self.assertEqual(base[f], truth[f], f)
        sel = self.learned(message or f"tell me about {name}")
        rels = self.k.relationships_for(name)
        if truth["description"] or rels["outgoing"] or rels["incoming"]:
            if sel.status == STATUS_SELECTED and sel.record["name"] == name:
                self.assertEqual(dict(sel.record), truth)
                self.assertEqual(sel.relationships, rels)

    def learned(self, message):
        # single-word names are only looked up via caller-supplied candidate terms (existing contract)
        terms = [w.lower() for w in re.findall(r"[A-Za-z0-9_']+", message)] if isinstance(message, str) else None
        return select_learned_knowledge(message, self.k, candidate_terms=terms)


class TestIdentity(Base):
    def test_teach_exact_and_unique_case_insensitive(self):
        self.l.teach("Python", "a language", source="user")
        self.observe_all("Python")
        r = self.k.resolve_name("python")
        self.assertEqual((r["status"], r["record"]["name"]), ("case_insensitive", "Python"))
        self.assertEqual(self.k.find_by_name_case_insensitive("PYTHON")["id"], self.stored("Python")["id"])
        self.assertIsNone(self.k.get("python"))
        sel = self.learned("what is python")
        self.assertEqual((sel.status, sel.record["id"]), (STATUS_SELECTED, self.stored("Python")["id"]))

    def test_conversational_correction_keeps_identity(self):
        self.l.teach("Python", "a snake", source="user")
        before = self.stored("Python")
        out = self.l.correct("python", "a language", source="user_correction")
        self.assertEqual(out["id"], before["id"])
        after = self.stored("Python")
        self.assertEqual(after["description"], "a language")
        self.assertEqual(after["version"], before["version"] + 1)
        self.assertEqual(len(self.k.all()), 1)
        self.observe_all("Python")
        self.assertEqual(self.k.resolve_name("PYTHON")["record"]["description"], "a language")
        self.assertEqual(self.learned("about python").record["description"], "a language")
        # the superseded description is history only
        for r in self.k.search("snake"):
            self.fail("historical description leaked into search")
        self.assertEqual(self.learned("snake").status, STATUS_NOT_FOUND)
        self.assertTrue(any("snake" in (e["detail"] or "") for e in self.m.query("SELECT * FROM learning_events")))

    def test_stub_then_taught(self):
        self.k.relate("Django", "Python", "built_with", source_type="ael")
        stub = self.stored("Django")
        self.assertEqual(stub["status"], "stub")
        self.observe_all("Django")
        self.assertEqual([r["id"] for r in self.k.search("Django")], [stub["id"]])  # name-matched stub is searchable
        self.l.teach("Django", "a web framework", source="user")
        up = self.stored("Django")
        self.assertEqual((up["id"], up["created_at"], up["version"]), (stub["id"], stub["created_at"], stub["version"] + 1))
        self.observe_all("Django")
        self.assertEqual([r["id"] for r in self.k.search("Django")], [stub["id"]])
        sel = self.learned("django please")
        self.assertEqual((sel.status, sel.record["id"]), (STATUS_SELECTED, stub["id"]))
        rels = self.k.relationships_for("Django")
        self.assertEqual(sel.relationships, rels)
        self.assertEqual(len(rels["outgoing"]), 1)

    def test_relationship_created_identity(self):
        self.l.teach("A", "alpha")
        self.l.relate("A", "B", "likes", source="user", confidence=0.5, source_text="A likes B")
        self.observe_all("A")
        self.observe_all("B")
        sel = self.learned("tell me about b")
        self.assertEqual(sel.status, STATUS_SELECTED)  # stub with an incoming relationship carries learned content
        self.assertEqual(sel.record["id"], self.stored("B")["id"])
        self.assertEqual(sel.relationships["incoming"][0]["from_name"], "A")

    def test_natural_language_learning_provenance(self):
        self.k.learn("Rust", "a systems language", source="understanding_engine", confidence=0.7,
                     source_text="Rust is a systems language", learning_method="natural_language_understanding")
        self.observe_all("Rust")
        row = self.learned("rust").record
        for f in ("source", "source_text", "confidence", "learning_method", "version"):
            self.assertEqual(row[f], self.stored("Rust")[f])

    def test_ambiguous_case_insensitive(self):
        self.k.learn("Go", "a language")
        self.k.learn("GO", "a board game")
        self.k.learn("go", "a verb")
        before = self.snap()
        for q, st in (("Go", "exact"), ("GO", "exact"), ("go", "exact")):
            self.assertEqual(self.k.resolve_name(q)["status"], st)
            self.assertEqual(self.k.get(q)["name"], q)
        for q in ("gO",):
            res = self.k.resolve_name(q)
            self.assertEqual(res["status"], "ambiguous")
            self.assertIsNone(res["record"])
            self.assertEqual(res["candidates"], ["GO", "Go", "go"])
            self.assertIsNone(self.k.find_by_name_case_insensitive(q))
            self.assertIsNone(self.k.get(q))
        self.assertEqual(len(self.k.all()), 3)
        # search is independent of resolve_name ambiguity: all three are found
        self.assertEqual(sorted(r["name"] for r in self.k.search("gO")), ["GO", "Go", "go"])
        # the learned-knowledge context never silently picks one for an ambiguous lookup
        sel = self.learned("what is gO")
        self.assertEqual(sel.status, STATUS_AMBIGUOUS)
        self.assertEqual(sel.candidates, ["GO", "Go", "go"])
        self.assertIsNone(sel.to_context())
        # correct()/learn-by-ambiguous name are rejected without a write
        with self.assertRaises(ValueError):
            self.k.correct("gO", "x")
        with self.assertRaises(ValueError):
            self.l.correct("gO", "x")
        self.assertEqual(self.snap(), before)

    def test_exact_case_wins_over_case_variants(self):
        self.k.learn("Java", "island/language")
        self.k.learn("java", "coffee")
        self.assertEqual(self.k.resolve_name("java")["record"]["description"], "coffee")
        self.assertEqual(self.learned("about java").record["description"], "coffee")
        self.assertEqual(self.learned("about Java").record["description"], "island/language")

    def test_whitespace_distinct_names(self):
        self.k.learn("New York", "city")
        self.k.learn("New  York", "double space")
        self.k.learn("New York ", "trailing")
        self.assertEqual(len(self.k.all()), 3)
        for n in ("New York", "New  York", "New York "):
            self.observe_all(n)
            self.assertEqual(self.k.resolve_name(n)["status"], "exact")
        self.assertIsNone(self.k.get(" New York"))
        self.assertEqual(self.k.resolve_name(" New York")["status"], "not_found")
        # distinct whitespace never collapses into case-insensitive candidates
        self.assertEqual(self.k.resolve_name("new york")["record"]["name"], "New York")
        self.assertEqual(self.k.resolve_name("new  york")["record"]["name"], "New  York")


class TestCurrentStateAfterMutations(Base):
    def _check(self, name):
        self.observe_all(name)

    def test_create_update_noop(self):
        self.l.teach("X", "one", source="user", confidence=0.4, source_text="s", learning_method="m")
        self._check("X")
        v1 = self.stored("X")
        self.l.teach("X", "two", source="user", confidence=0.4, source_text="s", learning_method="m")
        self._check("X")
        v2 = self.stored("X")
        self.assertEqual((v2["description"], v2["version"]), ("two", 2))
        events = self.snap()["learning_events"]
        self.l.teach("X", "two", source="user", confidence=0.4, source_text="s", learning_method="m")  # no-op
        self.assertEqual(self.stored("X"), v2)
        self.assertEqual(self.snap()["learning_events"], events)
        self._check("X")
        self.assertEqual(self.k.search("one"), [])  # old value is history only
        self.assertEqual([r["description"] for r in self.k.search("two")], ["two"])

    def test_relationship_update_and_noop(self):
        self.l.teach("A", "a")
        self.l.teach("B", "b")
        self.l.relate("A", "B", "r", source="user", confidence=0.3)
        rel1 = self.k.relationships_for("A")
        self.assertEqual(self.learned("about a").relationships, rel1)
        self.l.relate("A", "B", "r", source="user", confidence=0.3)  # no-op
        self.assertEqual(self.k.relationships_for("A"), rel1)
        self.l.relate("A", "B", "r", source="user", confidence=0.9)  # update
        rel2 = self.k.relationships_for("A")
        self.assertEqual(rel2["outgoing"][0]["confidence"], 0.9)
        self.assertEqual(rel2["outgoing"][0]["id"], rel1["outgoing"][0]["id"])
        self.assertEqual(self.learned("about a").relationships, rel2)
        self.assertEqual(self.learned("about b").relationships, self.k.relationships_for("B"))
        self.assertEqual(self.k.relationships_for("B")["incoming"], rel2["outgoing"])
        # relationship updates never touch either knowledge row
        self.assertEqual(self.stored("A")["version"], 1)
        self.assertEqual(self.stored("B")["version"], 1)

    def test_failed_and_rejected_mutations_are_invisible(self):
        self.l.teach("Keep", "kept")
        self.k.learn("Ab", "1")
        self.k.learn("AB", "2")
        before = self.snap()
        for call in (lambda: self.k.learn("", "x"), lambda: self.k.learn(None, "x"),
                     lambda: self.k.correct("Keep", ""), lambda: self.k.correct("   ", "x"),
                     lambda: self.k.correct("ab", "x"), lambda: self.k.relate("", "B", "r"),
                     lambda: self.k.relate("A", "B", None), lambda: self.l.teach("", "x")):
            with self.assertRaises((ValueError, TypeError)):
                call()
        self.assertIsNone(self.k.correct("Missing", "x"))          # never creates knowledge
        self.assertIsNone(self.l.correct("Missing", "x"))
        self.assertEqual(self.snap(), before)
        self.assertIsNone(self.k.get("Missing"))
        self.assertEqual(self.k.resolve_name("Missing")["status"], "not_found")
        self.observe_all("Keep")

    def test_all_kind_and_search_reflect_current_state(self):
        self.k.learn("P", "d", kind="person")
        self.k.learn("C", "d", kind="concept")
        self.k.learn("Q", "d", kind="person")
        self.assertEqual([r["name"] for r in self.k.all("person")], ["P", "Q"])
        self.assertEqual([r["name"] for r in self.k.all()], ["C", "P", "Q"])
        self.assertEqual(self.k.all("nothing"), [])
        self.k.learn("P", "d", kind="concept")  # kind update
        self.assertEqual([r["name"] for r in self.k.all("person")], ["Q"])
        self.assertEqual([r["name"] for r in self.k.all("concept")], ["C", "P"])
        self.observe_all("P")

    def test_relationship_ordering_contract(self):
        for to, rt in (("Z", "b"), ("Y", "b"), ("X", "a")):
            self.l.relate("S", to, rt, source="user")
        out = self.k.relationships_for("S")["outgoing"]
        self.assertEqual([(r["relation_type"], r["to_name"]) for r in out], [("a", "X"), ("b", "Y"), ("b", "Z")])
        self.l.relate("Q", "S", "z", source="user")
        self.l.relate("P", "S", "z", source="user")
        inc = self.k.relationships_for("S")["incoming"]
        self.assertEqual([(r["relation_type"], r["from_name"]) for r in inc], [("z", "P"), ("z", "Q")])
        self.assertEqual(self.learned("about s").relationships, self.k.relationships_for("S"))
        # relationships_for is exact-case (its contract); it does not resolve case variants
        self.assertEqual(self.k.relationships_for("s"), {"outgoing": [], "incoming": []})


class TestOrderingContracts(Base):
    def test_search_ranking_and_cap_and_validation_preserved(self):
        self.k.learn("alpha beta", "x")
        self.k.learn("beta", "alpha beta gamma")
        self.k.learn("zeta", "beta")
        names = [r["name"] for r in self.k.search("beta")]
        self.assertEqual(names, ["alpha beta", "beta", "zeta"])
        self.assertEqual([r["name"] for r in self.k.search("beta", limit=1)], ["alpha beta"])
        self.assertEqual(self.k.search("beta", limit=0), [])
        for bad in (-1,):
            with self.assertRaises(ValueError):
                self.k.search("beta", limit=bad)
        for bad in (True, "1", 1.0):
            with self.assertRaises(TypeError):
                self.k.search("beta", limit=bad)
        with self.assertRaises(TypeError):
            self.k.search(5)
        self.assertEqual(self.k.search(None), [])
        for i in range(_SEARCH_MAX_ROWS + 15):
            self.k.learn(f"cap{i:04d}", "capword")
        self.assertEqual(len(self.k.search("capword", limit=None)), _SEARCH_MAX_ROWS)
        self.assertEqual(len(self.k.search("capword", limit=10 ** 6)), _SEARCH_MAX_ROWS)
        self.assertEqual([r["name"] for r in self.k.search("capword", limit=None)][:3], ["cap0000", "cap0001", "cap0002"])

    def test_all_ordering_is_name_then_id(self):
        for n in ("b", "B", "a", "A", "_", "1"):
            self.k.learn(n, "d")
        got = [r["name"] for r in self.k.all()]
        self.assertEqual(got, sorted(got))
        self.assertEqual(got, [r["name"] for r in sorted(self.k.all(), key=lambda r: (r["name"], r["id"]))])

    def test_search_results_are_the_same_rows_as_get(self):
        self.k.learn("Tool", "hammer kind", kind="thing", source="user", confidence=0.2, source_text="s", learning_method="m")
        for r in self.k.search("hammer"):
            self.assertEqual(dict(r), dict(self.k.get(r["name"])))


class TestReadOnlyAndFailureIsolation(Base):
    def setUp(self):
        super().setUp()
        self.l.teach("Alpha", "first thing", source="user")
        self.l.teach("Beta", "second thing", source="user")
        self.l.relate("Alpha", "Beta", "r", source="user")
        self.k.relate("Stub", "Alpha", "r2", source_type="ael")
        self.k.learn("Dup", "1")
        self.k.learn("DUP", "2")

    def _exercise_all(self):
        for q in ("Alpha", "alpha", "ALPHA", "Beta", "Stub", "dup", "Dup", "nope", "", "  ", "Alpha "):
            self.k.get(q)
            self.k.resolve_name(q)
            self.k.find_by_name_case_insensitive(q)
            self.k.relationships_for(q)
            self.k.search(q)
            self.k.search(q, limit=0)
            self.k.search(q, limit=None)
            self.l.recall(q) if q.strip() else None
            self.l.search(q)
        self.k.all()
        self.k.all("concept")
        self.k.all("missing")
        for msg in ("tell me about alpha", "alpha and beta", "dup", "stub", "nothing here", "", None, 5):
            self.learned(msg)
            select_learned_knowledge(msg, self.k, candidate_terms=["alpha", "dup", 3, None])

    def test_retrieval_is_read_only(self):
        before = self.snap()
        self._exercise_all()
        self.assertEqual(self.snap(), before)  # versions, updated_at, events, relationships all identical

    def test_invalid_inputs_do_not_write(self):
        before = self.snap()
        for call in (lambda: self.k.search(5), lambda: self.k.search("a", limit=-1), lambda: self.k.search("a", limit=True),
                     lambda: self.k.search(["a"]), lambda: self.k.search(b"a")):
            with self.assertRaises((TypeError, ValueError)):
                call()
        for bad in (None, 5, ["Alpha"], b"Alpha", object()):
            self.assertEqual(self.k.resolve_name(bad)["status"], "not_found")
            self.assertIsNone(self.k.find_by_name_case_insensitive(bad))
        self.assertEqual(self.snap(), before)

    def test_returned_rows_are_detached_copies(self):
        before = self.snap()
        rec = self.k.get("Alpha")
        rec["description"] = "tampered"
        for r in self.k.search("first"):
            r["description"] = "tampered"
        sel = self.learned("alpha")
        sel.record["description"] = "tampered"
        sel.to_dict()["record"]["description"] = "tampered"
        ctx = sel.to_context()
        ctx["record"]["name"] = "tampered"
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.k.get("Alpha")["description"], "first thing")
        self.assertEqual(self.learned("alpha").record["description"], "first thing")

    def test_candidate_terms_and_message_not_mutated(self):
        terms = ["alpha", "beta"]
        keep = copy.deepcopy(terms)
        msg = "tell me about alpha"
        select_learned_knowledge(msg, self.k, candidate_terms=terms)
        self.assertEqual((terms, msg), (keep, "tell me about alpha"))


class TestReload(Base):
    def build(self):
        self.l.teach("Python", "a language", source="user", confidence=0.8, source_text="py", learning_method="teach")
        self.l.correct("python", "a great language", source="user_correction")
        self.k.relate("Flask", "Python", "built_with", source_type="ael")
        self.l.teach("Flask", "a microframework", source="user")
        self.k.learn("Go", "a"), self.k.learn("GO", "b")
        self.k.learn("A  B", "ws")

    def observe_state(self):
        out = {
            "all": [dict(r) for r in self.k.all()],
            "get": {n: (dict(self.k.get(n)) if self.k.get(n) else None) for n in ("Python", "python", "Flask", "Go", "gO", "A  B")},
            "resolve": {n: (r["status"], r["record"]["id"] if r["record"] else None, r["candidates"])
                        for n in ("Python", "python", "FLASK", "gO", "Go", "a  b", "zzz")
                        for r in [self.k.resolve_name(n)]},
            "search": [dict(r) for r in self.k.search("language framework microframework")],
            "rels": {n: self.k.relationships_for(n) for n in ("Python", "Flask")},
            "ctx": {msg: (s.status, s.record and dict(s.record), s.relationships, s.candidates)
                    for msg in ("about python", "about flask", "what is gO", "nothing")
                    for s in [self.learned(msg)]},
        }
        return copy.deepcopy(out)

    def test_same_state_after_reopen_and_fresh_instances(self):
        self.build()
        first = self.observe_state()
        snap = self.snap()
        self.reopen()
        self.assertEqual(self.observe_state(), first)
        fresh_k = KnowledgeSystem(MemorySystem(self.db))
        self.assertEqual([dict(r) for r in fresh_k.all()], first["all"])
        self.assertEqual(select_learned_knowledge("about python", fresh_k, candidate_terms=["python"]).status, STATUS_SELECTED)
        self.assertEqual(select_learned_knowledge("what is gO", fresh_k, candidate_terms=["go"]).status, STATUS_AMBIGUOUS)
        self.assertEqual(self.snap(), snap)
        self.observe_all("Python")
        self.observe_all("Flask")

    def test_mutation_then_reload_matches(self):
        self.build()
        self.l.correct("FLASK", "a WSGI microframework", source="user_correction")
        expected = dict(self.stored("Flask"))
        self.reopen()
        self.assertEqual(dict(self.k.get("Flask")), expected)
        self.assertEqual(dict(self.k.resolve_name("flask")["record"]), expected)
        self.assertEqual(dict(self.learned("about flask").record), expected)
        self.assertEqual([r["id"] for r in self.k.search("WSGI")], [expected["id"]])


class TestCoreWrapper(Base):
    def test_core_concept_lookup_uses_same_records(self):
        try:
            from core.core import Core
        except Exception as exc:  # pragma: no cover - environment dependent
            self.skipTest(f"Core unavailable: {exc}")
        core = Core.__new__(Core)
        core.knowledge = self.k
        self.k.learn("Indentation", "how python groups code")
        m = core._find_best_known_concept("tell me about indentation")
        self.assertEqual(dict(m), self.stored("Indentation"))
        m2 = core._find_best_known_concept("how python groups")   # falls back to search
        self.assertEqual(dict(m2), self.stored("Indentation"))
        before = self.snap()
        core._find_best_known_concept("zzz nothing")
        self.assertEqual(self.snap(), before)


if __name__ == "__main__":
    unittest.main()
