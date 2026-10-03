"""Prompt 659 - Section 3: KnowledgeSystem.search() RELEVANCE AND ORDERING.

AUDIT of the ranking contract as implemented (no production change was needed). The contract, exactly:

  candidates : rows where name/description LIKE-contains (literal, ASCII-case-insensitive) ANY query token, or
               the whole query phrase. Token = [A-Za-z0-9_'] run, lower-cased.
  rank key   : (T1, T2, name, id)
     T1 = whole query phrase is a case-insensitive SUBSTRING of the NAME  (one tier: 0 = hit first)
     T2 = number of query tokens in tokens(name) | tokens(description)   (set union: a token found in both name
          and description counts ONCE; more shared tokens first)
     then stored name (code-point order), then id. Never timestamp, version, insertion order, or history.
  cap        : min(limit, 200) applied AFTER ranking; limit=None means 200.

Consequences pinned here (these are the contract, not endorsements):
  C1  There is no separate exact-name / prefix / name-token tier. An exact-name record and a name that merely
      CONTAINS the phrase share T1 and are separated by T2 then name order.
  C2  A description-only phrase match gets no phrase bonus; it is ranked purely by T2.
  C3  A row that matched only via LIKE substring (e.g. token "cat" inside "concatenate") has T2 = 0 and ranks
      after every T2 >= 1 row of the same T1 tier, but is still returned.
  C4  Non-ASCII text contributes no tokens; the phrase bonus is Python str.lower() based.
  C5  limit follows Python slicing for values <= 200 (limit=0 -> []; a negative limit slices from the end).
      Pre-existing, unchanged.
"""
import os
import random
import subprocess
import sys
import tempfile
import unittest

from core.core import Core
from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem

TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items")
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


class TestTiers(Base):
    def test_exact_name_gets_the_phrase_tier_over_description_only_matches(self):
        self.k.learn("Aardvark", "about python")
        self.k.learn("python", "the language")
        self.k.learn("Zeta", "python python")
        self.assertEqual(self.names("python"), ["python", "Aardvark", "Zeta"])

    def test_no_separate_exact_prefix_or_token_tier_within_name_hits(self):     # C1
        self.k.learn("Monty Python Show", "comedy")
        self.k.learn("python", "the language")
        self.k.learn("Pythonic", "style")
        self.k.learn("Xpython", "odd")
        # all four contain the phrase (T1 tie); only exact-token names have T2=1; then name order
        self.assertEqual(self.names("python"), ["Monty Python Show", "python", "Pythonic", "Xpython"])

    def test_token_membership_beats_substring_only_inside_the_phrase_tier(self):
        for n in ("pyx", "xpy", "py"):
            self.k.learn(n, "d")
        self.assertEqual(self.names("py"), ["py", "pyx", "xpy"])          # py: T2=1; pyx/xpy: T2=0

    def test_name_hit_outranks_any_amount_of_description_overlap(self):
        self.k.learn("zz alpha", "unrelated")
        self.k.learn("aa", "alpha beta gamma alpha beta gamma")
        # whole phrase "alpha beta gamma" is NOT in "zz alpha" -> no T1 for either; overlap decides
        self.assertEqual(self.names("alpha beta gamma"), ["aa", "zz alpha"])
        self.assertEqual(self.names("alpha"), ["zz alpha", "aa"])         # phrase in name -> T1 beats T2 tie

    def test_description_only_phrase_match_has_no_bonus(self):              # C2
        self.k.learn("b", "hello world")
        self.k.learn("a", "hello there world")
        self.assertEqual(self.names("hello world"), ["a", "b"])           # both T2=2, name order; phrase in b's desc irrelevant

    def test_name_and_description_match_counts_once(self):
        self.k.learn("kiwi", "kiwi kiwi kiwi fruit")                      # token in both name+desc
        self.k.learn("apple", "kiwi fruit")
        self.k.learn("zed kiwi", "x")
        # phrase-in-name tier: kiwi, zed kiwi (T2 1 each, name order); apple T1 miss
        self.assertEqual(self.names("kiwi"), ["kiwi", "zed kiwi", "apple"])
        # two-token query: kiwi's union {kiwi,fruit} = 2 ; apple's {apple,kiwi,fruit} = 2 -> name order
        self.assertEqual(self.names("kiwi fruit"), ["apple", "kiwi", "zed kiwi"])

    def test_whole_phrase_must_be_contiguous_and_case_insensitive(self):
        self.k.learn("Hello World", "x")
        self.k.learn("world hello", "y")
        self.k.learn("hello big world", "z")
        self.assertEqual(self.names("HELLO world"), ["Hello World", "hello big world", "world hello"])

    def test_query_whitespace_is_not_normalised_for_the_phrase_tier(self):
        self.k.learn("python", "x")
        self.k.learn("a py thon", "python")
        self.assertEqual(self.names("python"), ["python", "a py thon"])
        # " python" (leading space) is not a substring of "python": no T1 for it; ranks by T2 then name
        self.assertEqual(self.names(" python"), ["a py thon", "python"])

    def test_substring_only_candidates_are_returned_but_rank_last(self):    # C3
        self.k.learn("concatenate", "join strings")
        self.k.learn("zebra", "cat")
        got = self.names("cat")
        self.assertEqual(got, ["concatenate", "zebra"])   # concatenate: phrase in name (T1); zebra: T1 miss, T2=1
        self.k.learn("aaa", "concatenate things")         # T1 miss, T2 0 (substring only)
        self.assertEqual(self.names("cat"), ["concatenate", "zebra", "aaa"])

    def test_unrelated_partial_matches_do_not_displace_exact_query_match(self):
        for i in range(30):
            self.k.learn(f"a{i:02d}", "mentions widget in passing")
        self.k.learn("widget", "the thing")
        self.assertEqual(self.names("widget")[0], "widget")


class TestTieBreaking(Base):
    def test_ties_break_by_name_codepoint_then_id_not_timestamp_or_insertion(self):
        for n in ("m", "B", "b", "a", "é", "Z"):
            self.k.learn(n, "shared token")
        self.m._run("UPDATE knowledge SET created_at='T', updated_at='T'")
        self.assertEqual(self.names("shared token"), ["B", "Z", "a", "b", "m", "é"])

    def test_touching_records_never_reorders(self):
        for n in ("c", "a", "b"):
            self.k.learn(n, "topic")
        first = self.names("topic")
        self.k.learn("c", "topic", kind="thing")
        self.k.learn("a", "topic", confidence=0.1)
        self.assertEqual(self.names("topic"), first)
        self.assertEqual(first, ["a", "b", "c"])

    def test_identical_descriptions_are_ordered_by_name_across_insertion_orders(self):
        results = set()
        for order in ((0, 1, 2, 3, 4), (4, 3, 2, 1, 0), (2, 0, 4, 1, 3)):
            db = os.path.join(self.tmp, f"o{''.join(map(str, order))}.db")
            k = KnowledgeSystem(MemorySystem(db))
            for i in order:
                k.learn(f"n{i}", "identical description")
            results.add(tuple(r["name"] for r in k.search("identical description")))
        self.assertEqual(results, {("n0", "n1", "n2", "n3", "n4")})

    def test_repeated_calls_and_reopen_are_identical(self):
        for i in range(15):
            self.k.learn(f"r{i % 5}x{i}", f"w{i % 3} common")
        want = self.k.search("common w1")
        for _ in range(3):
            self.assertEqual(self.k.search("common w1"), want)
        self.reopen()
        self.assertEqual(self.k.search("common w1"), want)
        self.reopen()
        self.assertEqual(self.k.search("common w1"), want)

    def test_ordering_independent_of_hash_seed(self):
        code = (
            "import os,sys,tempfile;sys.path.insert(0,%r)\n"
            "from memory.memory_system import MemorySystem\n"
            "from knowledge.knowledge_system import KnowledgeSystem\n"
            "k=KnowledgeSystem(MemorySystem(os.path.join(tempfile.mkdtemp(),'h.db')))\n"
            "for n,d in [('delta','red green blue'),('alpha','red green'),('gamma','red blue green yellow'),"
            "('beta','blue'),('red','x'),('Epsilon','green red'),('zeta red green blue','')]:\n"
            "    k.learn(n,d)\n"
            "print(','.join(r['name'] for r in k.search('red green blue')))\n" % PY_ROOT)
        outs = set()
        for seed in ("0", "1", "42", "12345", "random"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            outs.add(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                                    check=True).stdout.strip())
        self.assertEqual(len(outs), 1, outs)


class TestRankingStabilityAcrossLifecycle(Base):
    def test_teach_correct_ranking_follows_current_text_only(self):
        self.l.teach("Alpha", "fruit basket")
        self.l.teach("Beta", "fruit")
        self.assertEqual(self.names("fruit basket"), ["Alpha", "Beta"])
        self.l.correct("Alpha", "vegetable")
        self.assertEqual(self.names("fruit basket"), ["Beta"])
        self.assertEqual(self.names("vegetable"), ["Alpha"])
        self.l.correct("alpha", "fruit basket")                # case-insensitive correct, back again
        self.assertEqual(self.names("fruit basket"), ["Alpha", "Beta"])

    def test_history_volume_never_influences_ranking(self):
        # X has a long history, Y none; final state identical -> same ordering as a clean DB
        self.l.teach("X", "w0")
        for i in range(1, 8):
            self.l.correct("X", f"w{i}")
        self.l.correct("X", "topic")
        self.l.teach("Y", "topic")
        clean = KnowledgeSystem(MemorySystem(os.path.join(self.tmp, "clean.db")))
        clean.learn("Y", "topic"); clean.learn("X", "topic")
        self.assertEqual(self.names("topic"), [r["name"] for r in clean.search("topic")])
        self.assertEqual(self.names("topic"), ["X", "Y"])
        events = self.m.query("SELECT detail FROM learning_events")
        self.assertTrue(events and any("w3" in (e["detail"] or "") for e in events))
        self.assertEqual(self.names("w3"), [])                 # obsolete text is history only
        self.assertEqual(self.names("teach"), [])
        self.assertEqual(self.names("correct"), [])

    def test_relationship_creation_does_not_change_ranking_and_stubs_rank_by_name_only(self):
        self.l.teach("Dog", "an animal that barks")
        self.l.teach("Cat", "an animal that meows")
        before = self.names("animal")
        self.l.relate("Dog", "Puppy", "parent_of")             # creates stub Puppy
        self.l.relate("Cat", "Kitten", "parent_of")
        self.assertEqual(self.names("animal"), before)         # stubs have no text -> not candidates for it
        got = self.k.search("puppy")
        self.assertEqual([(r["name"], r["status"]) for r in got], [("Puppy", "stub")])
        self.assertEqual(self.names("Kitten Puppy"), ["Kitten", "Puppy"])   # T2 1 each, name order

    def test_stub_to_taught_upgrade_moves_only_by_its_new_text(self):
        self.l.relate("Dog", "Puppy", "parent_of")
        self.l.teach("Zoo", "puppy display")
        self.assertEqual(self.names("puppy"), ["Puppy", "Zoo"])              # T1 name hit first
        pid = self.k.get("Puppy")["id"]
        self.l.teach("Puppy", "a young dog")
        self.assertEqual(self.k.get("Puppy")["id"], pid)
        self.assertEqual(self.names("puppy"), ["Puppy", "Zoo"])              # still T1
        self.assertEqual(self.names("young dog"), ["Puppy", "Dog"])   # Puppy T2=2; Dog matches via name token "dog"
        self.assertEqual(self.names("display"), ["Zoo"])

    def test_natural_language_learning_ranking_and_state(self):
        core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.m._conn.close()
        core.learn_from_text("Python is a language.")
        core.learning.teach("Python", "a programming language", source="user")
        core.learning.teach("Language", "a means of communication", source="user")
        ks = core.knowledge
        got = [r["name"] for r in ks.search("language")]
        # "language" phrase in names: Language (T2 1), also "language"-named stub; then desc-only Python
        self.assertEqual(got[0].lower(), "language")
        self.assertIn("Python", got)
        again = [r["name"] for r in ks.search("language")]
        self.assertEqual(got, again)
        core.memory._conn.close()
        self._open()
        self.assertEqual(self.names("language"), got)

    def test_cross_source_updates_keep_one_row_and_ranking_by_current_text(self):
        self.k.learn("X", "first", source="user")
        self.k.learn("X", "second topic", source="nl")
        self.l.correct("x", "third topic", source="corr")
        self.k.learn("W", "topic")
        self.assertEqual(self.names("topic"), ["W", "X"])
        self.assertEqual(self.names("second"), [])
        self.assertEqual(self.m.query_one("SELECT COUNT(*) c FROM knowledge WHERE LOWER(name)='x'")["c"], 1)


class TestPersistedRowsOnly(Base):
    def test_results_are_exact_copies_of_persisted_rows(self):
        self.l.teach("A", "shared", source="user", confidence=0.5, source_text="s", learning_method="ael")
        self.l.teach("B", "shared")
        self.l.relate("A", "C", "r")
        rows = {r["name"]: r for r in self.m.query("SELECT * FROM knowledge")}
        for got in self.k.search("shared c a b"):
            self.assertEqual(got, rows[got["name"]])
        self.assertTrue(all(r["name"] in rows for r in self.k.search("a b c shared")))
        got = self.k.search("shared")
        got[0]["description"] = "MUTATED"                     # caller mutation must not leak
        self.assertEqual(self.k.search("shared")[0]["description"], "shared")
        self.assertEqual(self.m.query_one("SELECT description FROM knowledge WHERE name='A'")["description"], "shared")


class TestWildcardsAndCap(Base):
    def test_percent_and_underscore_stay_literal(self):
        self.k.learn("axb", "plain")
        self.k.learn("a_b", "under")
        self.k.learn("100% sure", "pct")
        self.k.learn("100 sure", "no pct")
        self.assertEqual(self.names("a_b"), ["a_b"])
        self.assertEqual(self.names("_"), ["a_b"])
        self.assertEqual(self.names("100% sure")[0], "100% sure")
        self.assertEqual(self.names("%"), [])

    def _oracle(self, term):
        """Independent re-implementation of the documented contract over ALL rows."""
        import re
        tok = lambda s: {m.lower() for m in re.findall(r"[A-Za-z0-9_']+", s or "")}
        q = tok(term)
        out = []
        for r in self.m.query("SELECT * FROM knowledge"):
            n, d = r["name"], r["description"] or ""
            if not (any(t in n.lower() or t in d.lower() for t in q) or term.lower() in n.lower()
                    or term.lower() in d.lower()):
                continue
            out.append(((0 if term.lower() in n.lower() else 1), -len(q & (tok(n) | tok(d))), n, r["id"]))
        return [k[2] for k in sorted(out)]

    def test_cap_applies_after_ranking_and_keeps_highest_ranked_200(self):
        rnd = random.Random(659)
        words = ["red", "green", "blue", "gold"]
        for i in range(700):
            desc = " ".join(rnd.sample(words, rnd.randint(1, 3)))
            name = f"{rnd.choice('abcdefghij')}{i:03d}" if i % 7 else f"zz red {i:03d}"
            self.k.learn(name, desc)
        for term in ("red green blue", "red", "gold blue"):
            want = self._oracle(term)
            self.assertGreater(len(want), 200, term)
            got = self.names(term, limit=1000)
            self.assertEqual(len(got), 200)
            self.assertEqual(got, want[:200], term)
            self.assertEqual(self.names(term, limit=None), want[:200])
            self.assertEqual(self.names(term), want[:20])
            self.assertEqual(self.names(term, limit=200), want[:200])
        self.reopen()
        self.assertEqual(self.names("red", limit=None), self._oracle("red")[:200])

    def test_low_ranked_late_alphabet_rows_are_the_ones_dropped(self):
        for i in range(210):
            self.k.learn(f"a{i:03d}", "alpha")                  # T2=1
        self.k.learn("zz", "alpha beta")                         # T2=2, sorts last alphabetically
        got = self.names("alpha beta", limit=None)
        self.assertEqual(len(got), 200)
        self.assertEqual(got[0], "zz")
        self.assertNotIn("a209", got)                            # lowest tier + latest names fall off the end

    def test_limit_semantics(self):                                # C5
        for i in range(25):
            self.k.learn(f"n{i:02d}", "kw")
        full = self.names("kw", limit=None)
        self.assertEqual(len(full), 25)
        self.assertEqual(self.names("kw", limit=0), [])
        self.assertEqual(self.names("kw", limit=1), full[:1])
        self.assertEqual(self.names("kw", limit=500), full)
        self.assertEqual(self.names("kw"), full[:20])


class TestUnsupportedAndNonAscii(Base):
    def test_blank_and_tokenless_queries_return_empty(self):
        self.k.learn("A", "b")
        for q in (None, "", " ", "\t\n", "%", "!!!", "---", "پایتون", "  پایتون  "):
            self.assertEqual(self.k.search(q), [], repr(q))

    def test_non_string_query_current_behaviour(self):
        self.k.learn("A", "b")
        with self.assertRaises(TypeError):
            self.k.search(5)

    def test_persian_text_gives_no_tokens_but_round_trips_and_orders_by_codepoint(self):
        self.k.learn("مرغ", "پرنده")
        self.k.learn("Bird", "پرنده و animal")
        self.k.learn("Ant", "animal")
        self.assertEqual(self.names("animal پرنده"), ["Ant", "Bird"])       # ASCII token only
        self.assertEqual(self.k.search("animal")[1]["description"], "پرنده و animal")
        self.k.learn("زرد animal", "x")
        self.k.learn("Zed animal", "x")
        # phrase-in-name tier first, in code-point order (ASCII before Persian); then the rest by name
        self.assertEqual(self.names("animal"), ["Zed animal", "زرد animal", "Ant", "Bird"])

    def test_phrase_bonus_uses_python_lower_for_non_ascii_names_with_ascii_tokens(self):   # C4
        self.k.learn("Café menu", "x")
        self.k.learn("Aaa", "cafe menu talk")
        self.assertEqual(self.names("café menu"), ["Café menu", "Aaa"])
        self.assertEqual(self.names("CAFÉ menu"), ["Café menu", "Aaa"])

    def test_non_ascii_case_folding_not_broadened_in_resolution(self):
        self.k.learn("Émile", "x")
        self.assertEqual(self.k.resolve_name("émile")["status"], "not_found")


class TestSearchIsReadOnly(Base):
    def test_search_never_writes_anything(self):
        self.l.teach("Python", "a language", source="user", confidence=0.7)
        self.l.relate("Python", "Rust", "similar_to")
        self.l.correct("Python", "a programming language")
        self.k.learn("Old", "legacy", status="deprecated")
        snap = self.snap()
        for q in ("python", "language", "rust", "zzz", "_", "%", "", None, "پایتون", "a b c d e f",
                  "programming language legacy"):
            self.k.search(q)
            self.k.search(q, limit=None)
            self.l.search(q)
        self.assertEqual(self.snap(), snap)
        self.reopen()
        self.assertEqual(self.snap(), snap)

    def test_search_results_identical_after_reopen_for_a_varied_dataset(self):
        rnd = random.Random(7)
        for i in range(60):
            self.k.learn(f"Item {rnd.randint(0, 999):03d}-{i}", " ".join(rnd.choices(["a", "b", "c", "d"], k=4)))
        self.l.relate("Item 1", "Item 2", "r")
        qs = ("a b", "c", "item", "d a c", "Item 1")
        before = {q: (self.k.search(q), self.k.search(q, limit=None)) for q in qs}
        for _ in range(2):
            self.reopen()
            self.assertEqual({q: (self.k.search(q), self.k.search(q, limit=None)) for q in qs}, before)


if __name__ == "__main__":
    unittest.main()
