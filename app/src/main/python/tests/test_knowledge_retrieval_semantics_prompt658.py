"""Prompt 658 - Section 3: knowledge SEARCH / RESOLUTION / LISTING / RETRIEVAL semantics.

AUDIT of the existing retrieval contract. No architecture change, no fuzzy/semantic matching, no data
normalisation. Findings pinned here:

  R1  Resolution: exact-case always wins; a unique case-insensitive match resolves; several case-insensitive
      matches are "ambiguous" (record None, never an arbitrary pick); whitespace variants are distinct identities.
  R2  search() ranks by (whole-phrase name hit, token overlap, name, id) - never by timestamp or storage order.
  R3  Every reader reads the CURRENT persisted row; learning_events history never appears as knowledge.
  R4  Stubs and active/non-active rows are all returned (no status filtering) with their persisted status.
  R5  Non-ASCII: SQLite LOWER()/LIKE are ASCII-only and the query tokenizer is [A-Za-z0-9_'] only, so a
      Persian-only query yields no tokens (search -> []) and non-ASCII names resolve exact-case only. PINNED, unchanged.

Two genuine defects were found and fixed (regression tests below, class TestProdefect*):

  D1  LIKE wildcards were not escaped: "_" (a legal token character) matched ANY character, so search("a_b")
      returned "axb" and search("_") returned every row. Candidates now match the literal text only.
  D2  The 200-row candidate cap was applied in SQL BEFORE relevance ranking, so an exact-name record could be
      dropped when 200+ earlier-sorting rows merely mentioned the term. The cap is now applied AFTER ranking
      (still at most 200 rows returned); ordering rules are unchanged.
"""
import os
import tempfile
import unittest

from core.core import Core
from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem

TABLES = ("knowledge", "relationships", "learning_events")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "r.db")
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

    def names(self, term, **kw):
        return [r["name"] for r in self.k.search(term, **kw)]


class TestResolution(Base):
    def test_exact_wins_over_case_insensitive_for_every_variant(self):
        for n, d in (("python", "lower"), ("Python", "cap"), ("PYTHON", "upper")):
            self.k.learn(n, d)
        for n, d in (("python", "lower"), ("Python", "cap"), ("PYTHON", "upper")):
            self.assertEqual(self.k.resolve_name(n)["status"], "exact")
            self.assertEqual(self.k.find_by_name_case_insensitive(n)["description"], d)
            self.assertEqual(self.k.get(n)["description"], d)

    def test_unique_case_insensitive_match_is_deterministic(self):
        self.k.learn("Python", "lang")
        for _ in range(3):
            r = self.k.resolve_name("pYtHoN")
            self.assertEqual((r["status"], r["record"]["name"], r["candidates"]), ("case_insensitive", "Python", []))
            self.assertEqual(self.k.find_by_name_case_insensitive("PYTHON")["name"], "Python")
        self.assertIsNone(self.k.get("pYtHoN"))

    def test_ambiguous_never_resolves_and_lists_sorted_candidates_regardless_of_insert_order(self):
        for n in ("pYthon", "PYTHON", "Python"):
            self.k.learn(n, f"d-{n}")
        r = self.k.resolve_name("python")
        self.assertEqual(r["status"], "ambiguous")
        self.assertIsNone(r["record"])
        self.assertEqual(r["candidates"], ["PYTHON", "Python", "pYthon"])
        self.assertIsNone(self.k.find_by_name_case_insensitive("python"))

    def test_whitespace_variants_are_distinct_identities(self):
        self.k.learn("Python", "a")
        for v in (" Python", "Python ", "Py thon", "Python\t"):
            self.assertIsNone(self.k.get(v))
            self.assertEqual(self.k.resolve_name(v)["status"], "not_found")
            self.assertIsNone(self.k.find_by_name_case_insensitive(v))
        self.k.learn("Python ", "trailing")
        self.assertEqual(self.k.get("Python")["description"], "a")
        self.assertEqual(self.k.get("Python ")["description"], "trailing")
        self.assertEqual(self.k.resolve_name("python ")["status"], "case_insensitive")
        self.assertEqual(self.k.resolve_name("python ")["record"]["name"], "Python ")

    def test_non_string_and_missing_names_not_found_and_write_nothing(self):
        self.k.learn("A", "x")
        before = self.snap()
        for bad in (None, 5, b"A", ["A"], "", "nope"):
            self.assertEqual(self.k.resolve_name(bad)["status"], "not_found")
            self.assertIsNone(self.k.find_by_name_case_insensitive(bad))
        self.assertEqual(self.snap(), before)

    def test_public_helpers_agree_with_one_resolution_path(self):
        for n in ("Cat", "cat", "DOG", "Bird"):
            self.k.learn(n, n.lower())
        for q in ("Cat", "cat", "CAT", "dog", "bird", "BIRD", "fish", "Dog"):
            r = self.k.resolve_name(q)
            self.assertIs(r["record"] is None, self.k.find_by_name_case_insensitive(q) is None)
            if r["status"] in ("exact", "case_insensitive"):
                self.assertEqual(self.k.find_by_name_case_insensitive(q), r["record"])
            if r["status"] == "exact":
                self.assertEqual(self.k.get(q), r["record"])
            else:
                self.assertIsNone(self.k.get(q))
        self.assertEqual(self.k.resolve_name("CAT")["status"], "ambiguous")


class TestSearchOrdering(Base):
    def test_exact_name_hit_outranks_partial_and_description_only(self):
        self.k.learn("Aardvark", "mentions python somewhere")
        self.k.learn("Monty Python Show", "comedy")
        self.k.learn("python", "the language")
        self.k.learn("Zeta", "python python python")
        self.assertEqual(self.names("python"), ["Monty Python Show", "python", "Aardvark", "Zeta"])

    def test_overlap_then_name_then_id_for_equal_relevance(self):
        self.k.learn("beta", "red green")
        self.k.learn("alpha", "red")
        self.k.learn("gamma", "red green blue")
        self.assertEqual(self.names("red green"), ["beta", "gamma", "alpha"])
        self.assertEqual(self.names("red"), ["alpha", "beta", "gamma"])

    def test_equal_timestamps_and_reversed_insertion_do_not_change_order(self):
        for n in ("m1", "m3", "m2"):
            self.k.learn(n, "shared words here")
        self.m._run("UPDATE knowledge SET created_at='T', updated_at='T'")
        first = self.names("shared words")
        self.assertEqual(first, ["m1", "m2", "m3"])
        other = os.path.join(self.tmp, "o.db")
        m2 = MemorySystem(other)
        k2 = KnowledgeSystem(m2)
        for n in ("m2", "m3", "m1"):
            k2.learn(n, "shared words here")
        m2._run("UPDATE knowledge SET created_at='T', updated_at='T'")
        self.assertEqual([r["name"] for r in k2.search("shared words")], first)

    def test_newer_update_never_promotes_a_row(self):
        self.k.learn("b", "topic")
        self.k.learn("a", "topic")
        before = self.names("topic")
        self.k.learn("b", "topic", kind="thing")   # real update, newer timestamp
        self.assertEqual(self.names("topic"), before)
        self.assertEqual(before, ["a", "b"])

    def test_case_variants_order_by_binary_name_then_stable(self):
        for n in ("python", "Python", "PYTHON"):
            self.k.learn(n, "x")
        self.assertEqual(self.names("python"), ["PYTHON", "Python", "python"])

    def test_similar_names_and_descriptions_are_deterministic(self):
        for i in range(12):
            self.k.learn(f"item {i:02d}", "very similar description text")
        runs = {tuple(self.names("similar description")) for _ in range(5)}
        self.assertEqual(len(runs), 1)
        self.assertEqual(list(runs)[0], tuple(f"item {i:02d}" for i in range(12)))

    def test_limit_takes_the_top_of_the_same_ranking(self):
        for i in range(30):
            self.k.learn(f"n{i:02d}", "kw")
        full = self.names("kw", limit=30)
        self.assertEqual(self.names("kw"), full[:20])
        self.assertEqual(self.names("kw", limit=3), full[:3])

    def test_empty_or_tokenless_queries_return_empty(self):
        self.k.learn("A", "b")
        for q in ("", "   ", None, "%", "!!!"):
            self.assertEqual(self.k.search(q), [])


class TestCurrentRowRetrieval(Base):
    def test_search_and_readers_return_the_persisted_current_row(self):
        self.l.teach("Python", "a snake", source="user", confidence=0.4, source_text="s1", learning_method="ael")
        self.l.correct("Python", "a programming language", source="nl", confidence=0.9,
                       source_text="s2", learning_method="natural_language_understanding")
        row = self.m.query_one("SELECT * FROM knowledge WHERE name='Python'")
        for got in (self.k.get("Python"), self.k.find_by_name_case_insensitive("python"),
                    self.k.search("programming")[0], self.k.all()[0], self.l.search("programming")[0],
                    self.l.recall("Python")):
            for f in ("id", "name", "kind", "description", "status", "source", "confidence", "source_text",
                      "learning_method", "version", "created_at", "updated_at"):
                self.assertEqual(got[f], row[f], f)
        self.assertEqual(self.names("snake"), [])
        self.assertNotIn("snake", " ".join(r["description"] or "" for r in self.k.all()))

    def test_history_events_never_contaminate_current_search(self):
        self.l.teach("Python", "a snake")
        self.l.correct("Python", "a programming language")
        self.assertTrue(any("snake" in (e["detail"] or "") for e in
                            self.m.query("SELECT * FROM learning_events")))
        self.assertEqual(self.names("snake"), [])
        self.assertEqual(self.names("correct"), [])
        self.assertEqual(self.names("teach"), [])
        self.assertEqual(self.names("Python"), ["Python"])

    def test_stub_and_active_are_both_returned_with_persisted_status(self):
        self.l.teach("Dog", "an animal", source="user")
        self.l.relate("Dog", "Puppy", "parent_of")
        self.assertEqual(self.k.get("Puppy")["status"], "stub")
        by = {r["name"]: r for r in self.k.search("Puppy Dog")}
        self.assertEqual(by["Puppy"]["status"], "stub")
        self.assertIsNone(by["Puppy"]["description"])
        self.assertEqual(by["Dog"]["status"], "active")
        self.assertEqual([r["name"] for r in self.k.search("Puppy Dog")], ["Dog", "Puppy"])
        self.assertEqual({r["name"] for r in self.k.all()}, {"Dog", "Puppy"})
        # stub upgrade is in place: same id, now active, still one row
        pid = by["Puppy"]["id"]
        self.l.teach("Puppy", "a young dog", source="user")
        up = self.k.get("Puppy")
        self.assertEqual((up["id"], up["status"]), (pid, "active"))
        self.assertEqual(self.names("Puppy").count("Puppy"), 1)

    def test_nonactive_status_is_visible_not_filtered(self):
        self.k.learn("Old", "legacy fact", status="deprecated")
        self.assertEqual(self.k.search("legacy")[0]["status"], "deprecated")
        self.assertEqual(self.k.resolve_name("old")["record"]["status"], "deprecated")

    def test_relationships_are_deterministic_and_match_current_endpoint_identities(self):
        self.l.teach("Hub", "center", source="user")
        for to, rel in (("Zed", "b_rel"), ("Amy", "b_rel"), ("Mid", "a_rel")):
            self.l.relate("Hub", to, rel)
        self.l.relate("Zed", "Hub", "c_rel")
        self.l.relate("Amy", "Hub", "c_rel")
        rels = self.k.relationships_for("Hub")
        self.assertEqual([(r["relation_type"], r["to_name"]) for r in rels["outgoing"]],
                         [("a_rel", "Mid"), ("b_rel", "Amy"), ("b_rel", "Zed")])
        self.assertEqual([(r["relation_type"], r["from_name"]) for r in rels["incoming"]],
                         [("c_rel", "Amy"), ("c_rel", "Zed")])
        for r in rels["outgoing"] + rels["incoming"]:
            for endpoint in (r["from_name"], r["to_name"]):
                self.assertIsNotNone(self.k.get(endpoint))          # every edge endpoint is a current row
        self.assertEqual(rels, self.k.relationships_for("Hub"))
        self.assertEqual(self.l.recall("Hub")["relationships"], rels)
        # relationships attach to exact names only: a case variant has no edges and is not redirected
        self.assertEqual(self.k.relationships_for("hub"), {"outgoing": [], "incoming": []})

    def test_relationship_provenance_and_confidence_match_persisted_row(self):
        self.l.relate("A", "B", "likes", confidence=0.7, source_text="A likes B", learning_method="ael")
        row = self.m.query_one("SELECT * FROM relationships WHERE from_name='A'")
        got = self.k.relationships_for("A")["outgoing"][0]
        self.assertEqual(got, row)
        self.assertEqual(self.k.relationships_for("B")["incoming"][0], row)
        self.l.relate("A", "B", "likes", confidence=0.2)             # refresh
        row = self.m.query_one("SELECT * FROM relationships WHERE from_name='A'")
        self.assertEqual(self.k.relationships_for("A")["outgoing"][0], row)
        self.assertEqual(row["confidence"], 0.2)

    def test_search_provenance_and_confidence_survive_cross_source_updates(self):
        self.k.learn("X", "first", source="user", confidence=0.3, source_text="t", learning_method="ael")
        self.k.learn("X", "second", source="nl", confidence=None)                 # cross-source, keep confidence
        self.l.correct("x", "third", source="corr", confidence=0.8)               # case-insensitive correct
        row = self.m.query_one("SELECT * FROM knowledge WHERE name='X'")
        self.assertEqual(self.m.query_one("SELECT COUNT(*) c FROM knowledge")["c"], 1)
        got = self.k.search("third")[0]
        self.assertEqual(got, row)
        self.assertEqual((got["source"], got["confidence"], got["source_text"], got["learning_method"]),
                         ("corr", 0.8, "t", "ael"))
        self.assertEqual(self.names("second"), [])


class TestRetrievalStability(Base):
    def _seed(self):
        for n, d in (("Python", "a language"), ("python", "a snake"), ("Rust", "a language"), ("Go", "language")):
            self.l.teach(n, d, source="user")
        self.l.relate("Python", "Rust", "similar_to")
        self.l.relate("Python", "Perl", "similar_to")

    def _view(self):
        return {"search": self.k.search("language"), "all": self.k.all(), "rels": self.k.relationships_for("Python"),
                "res": self.k.resolve_name("PYTHON"), "one": self.k.resolve_name("go")}

    def test_reopen_gives_identical_ordering_and_content(self):
        self._seed()
        before = self._view()
        for _ in range(2):
            self.reopen()
            self.assertEqual(self._view(), before)

    def test_failed_mutations_do_not_alter_search(self):
        self._seed()
        before, snap = self._view(), self.snap()
        for call in (lambda: self.k.learn("", "x"), lambda: self.k.learn(None, "x"),
                     lambda: self.k.correct("PYTHON", "x"),         # ambiguous
                     lambda: self.k.correct("Python", ""),
                     lambda: self.k.relate("A", "", "r"), lambda: self.k.relate("A", "B", None),
                     lambda: self.l.correct("PYTHON", "x")):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(self._view(), before)
        self.assertEqual(self.snap(), snap)

    def test_ambiguous_and_missing_operations_do_not_alter_search(self):
        self._seed()
        before, snap = self._view(), self.snap()
        self.assertIsNone(self.k.correct("nonexistent", "x"))
        self.assertIsNone(self.l.correct("nonexistent", "x"))
        self.k.resolve_name("PYTHON"); self.k.find_by_name_case_insensitive("PYTHON")
        self.assertEqual(self._view(), before)
        self.assertEqual(self.snap(), snap)

    def test_noop_operations_do_not_alter_retrieval_state(self):
        self._seed()
        before, snap = self._view(), self.snap()
        self.k.learn("Rust", "a language", source="user")                       # identical repeat
        self.l.teach("Rust", "a language", source="user")
        self.l.relate("Python", "Rust", "similar_to")
        self.k.correct("rust", "a language")                                    # identical correction via CI
        self.assertEqual(self._view(), before)
        self.assertEqual(self.snap(), snap)

    def test_reads_never_write(self):
        self._seed()
        snap = self.snap()
        for q in ("language", "python", "Perl", "zzz", "_", "پایتون"):
            self.k.search(q)
        self.k.all(); self.k.all(kind="concept"); self.k.relationships_for("Python"); self.l.recall("Python")
        self.assertEqual(self.snap(), snap)

    def test_core_stack_and_bare_stack_see_the_same_retrieval(self):
        self._seed()
        want = self._view()
        self.m._conn.close()
        core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        got = {"search": core.knowledge.search("language"), "all": core.knowledge.all(),
               "rels": core.knowledge.relationships_for("Python"), "res": core.knowledge.resolve_name("PYTHON"),
               "one": core.knowledge.resolve_name("go")}
        core.memory._conn.close()
        self.assertEqual(got, want)
        self._open()


class TestNonAscii(Base):
    def test_persian_names_resolve_exact_case_and_are_listed(self):
        self.k.learn("پایتون", "زبان برنامه نویسی")
        self.assertEqual(self.k.resolve_name("پایتون")["status"], "exact")
        self.assertEqual(self.k.find_by_name_case_insensitive("پایتون")["description"], "زبان برنامه نویسی")
        self.assertEqual([r["name"] for r in self.k.all()], ["پایتون"])
        self.assertEqual(self.k.resolve_name("پایتو")["status"], "not_found")
        self.assertEqual(self.k.resolve_name("پایتون ")["status"], "not_found")

    def test_persian_only_query_has_no_tokens_current_semantics_pinned(self):
        self.k.learn("پایتون", "زبان")
        self.assertEqual(self.k.search("پایتون"), [])

    def test_mixed_query_matches_only_via_ascii_tokens_and_persian_text_round_trips(self):
        self.k.learn("Python", "پایتون یک زبان است")
        self.k.learn("Other", "unrelated")
        got = self.k.search("Python پایتون")
        self.assertEqual([r["name"] for r in got], ["Python"])
        self.assertEqual(got[0]["description"], "پایتون یک زبان است")
        self.reopen()
        self.assertEqual(self.k.search("Python پایتون")[0]["description"], "پایتون یک زبان است")

    def test_non_ascii_case_folding_is_not_broadened(self):
        self.k.learn("Émile", "x")
        self.assertEqual(self.k.resolve_name("émile")["status"], "not_found")   # SQLite LOWER is ASCII-only
        self.assertEqual(self.k.resolve_name("Émile")["status"], "exact")


class TestProdefectWildcardEscaping(Base):
    """D1 regression: LIKE metacharacters in the query must match literally."""

    def test_underscore_in_query_is_literal_not_a_wildcard(self):
        self.k.learn("axb", "plain")
        self.k.learn("a_b", "under")
        self.assertEqual(self.names("a_b"), ["a_b"])

    def test_bare_underscore_matches_only_literal_underscore(self):
        self.k.learn("Zed", "zzz")
        self.k.learn("snake_case", "style")
        self.k.learn("has_desc", "x")
        self.k.learn("plain", "with_underscore inside")
        self.assertEqual(self.names("_"), ["has_desc", "snake_case", "plain"])   # name hits first, then description-only

    def test_percent_and_backslash_are_literal_in_the_phrase(self):
        self.k.learn("50% off", "sale")
        self.k.learn("50 off", "sale")
        self.k.learn("path\\x", "backslash")
        self.assertIn("50% off", self.names("50% off"))
        self.assertEqual(self.names("path\\x")[0], "path\\x")   # no crash, literal phrase still hits

    def test_ordinary_queries_unchanged(self):
        self.k.learn("Python", "a language")
        self.k.learn("Rust", "a language too")
        self.assertEqual(self.names("language"), ["Python", "Rust"])
        self.assertEqual(self.names("python"), ["Python"])


class TestProdefectCandidateCap(Base):
    """D2 regression: the 200-row cap must not drop the best match, and stays deterministic."""

    def _flood(self, n=250):
        for i in range(n):
            self.k.learn(f"a{i:03d}", "mentions zebra here")

    def test_exact_name_record_survives_the_cap(self):
        self._flood()
        self.k.learn("zebra", "the animal")
        got = self.names("zebra")
        self.assertEqual(got[0], "zebra")
        self.assertEqual(len(got), 20)

    def test_cap_is_still_at_most_200_and_deterministic(self):
        self._flood()
        self.k.learn("zebra", "the animal")
        big = self.names("zebra", limit=1000)
        self.assertEqual(len(big), 200)
        self.assertEqual(big[0], "zebra")
        self.assertEqual(big[1:], [f"a{i:03d}" for i in range(199)])       # ties: name order, stable
        self.assertEqual(self.names("zebra", limit=1000), big)
        self.reopen()
        self.assertEqual(self.names("zebra", limit=1000), big)

    def test_higher_overlap_late_in_alphabet_beats_early_weak_matches(self):
        for i in range(210):
            self.k.learn(f"a{i:03d}", "alpha")
        self.k.learn("zz", "alpha beta gamma")
        self.assertEqual(self.names("alpha beta gamma")[0], "zz")

    def test_under_cap_results_identical_to_before(self):
        for i in range(5):
            self.k.learn(f"a{i}", "zebra")
        self.k.learn("zebra", "x")
        self.assertEqual(self.names("zebra"), ["zebra", "a0", "a1", "a2", "a3", "a4"])


if __name__ == "__main__":
    unittest.main()
