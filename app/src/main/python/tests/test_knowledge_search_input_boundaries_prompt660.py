"""Prompt 660 - Section 3: KnowledgeSystem.search() input / boundary semantics.

Contract (pinned):
  term   : str or None. None / "" / whitespace / token-less str -> []. Any other type -> TypeError (no coercion).
  limit  : None (= the 200-row cap, Prompt 658) or an int >= 0; 0 -> []; positive -> top-N of the ranking, capped at 200.
           bool / float / str / other -> TypeError; negative int -> ValueError (never reinterpreted).
  Validation runs BEFORE any query, for every term (so an invalid limit is rejected even with a blank term).

Genuine input-boundary defects fixed (validation only; ranking/retrieval of valid input untouched):
  B1  a negative limit silently sliced from the END of the ranking (limit=-1 dropped only the last row).
  B2  non-string terms were decided by truthiness: 0 / False / 0.0 / [] / b"" returned [] while 5 / b"x" / ["x"]
      raised TypeError; bool limits were silently accepted as 0/1.
"""
import os
import tempfile
import unittest

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from learning.learning_system import LearningSystem

TABLES = ("knowledge", "relationships", "learning_events")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "b.db")
        self._open()
        for i in range(5):
            self.k.learn(f"n{i}", "kw")

    def _open(self):
        self.m = MemorySystem(self.db)
        self.k = KnowledgeSystem(self.m)
        self.l = LearningSystem(ConceptSystem(self.k), self.k, memory=self.m)

    def reopen(self):
        self.m._conn.close()
        self._open()

    def snap(self):
        return {t: [dict(r) for r in self.m.query(f"SELECT * FROM {t} ORDER BY id")] for t in TABLES}

    def names(self, term, *a, **kw):
        return [r["name"] for r in self.k.search(term, *a, **kw)]


class TestLimit(Base):
    def test_none_zero_positive(self):
        full = ["n0", "n1", "n2", "n3", "n4"]
        self.assertEqual(self.names("kw", limit=None), full)
        self.assertEqual(self.names("kw", limit=0), [])
        self.assertEqual(self.names("kw", limit=1), full[:1])
        self.assertEqual(self.names("kw", limit=3), full[:3])
        self.assertEqual(self.names("kw", limit=5), full)
        self.assertEqual(self.names("kw", limit=6), full)          # larger than result count
        self.assertEqual(self.names("kw"), full)                   # default 20

    def test_negative_limit_is_rejected_not_reinterpreted(self):   # B1
        for bad in (-1, -2, -5, -99, -(10 ** 9)):
            with self.assertRaises(ValueError) as cm:
                self.k.search("kw", limit=bad)
            self.assertIn(str(bad), str(cm.exception))

    def test_non_int_limits_raise_typeerror(self):                 # B2
        for bad in (True, False, 2.0, 1.5, float("nan"), "3", "", b"3", [1], (1,), {}, object()):
            with self.assertRaises(TypeError, msg=repr(bad)):
                self.k.search("kw", limit=bad)

    def test_int_subclass_that_is_not_bool_is_accepted(self):
        class MyInt(int):
            pass
        self.assertEqual(self.names("kw", limit=MyInt(2)), ["n0", "n1"])

    def test_limit_validation_runs_before_the_query_even_for_blank_terms(self):
        for term in (None, "", "   ", "!!!", "kw"):
            with self.assertRaises(ValueError):
                self.k.search(term, limit=-1)
            with self.assertRaises(TypeError):
                self.k.search(term, limit=True)

    def test_cap_still_200_and_none_means_cap(self):
        for i in range(230):
            self.k.learn(f"b{i:03d}", "kw")
        want = self.names("kw", limit=None)
        self.assertEqual(len(want), 200)
        self.assertEqual(self.names("kw", limit=200), want)
        self.assertEqual(self.names("kw", limit=201), want)
        self.assertEqual(self.names("kw", limit=10 ** 6), want)
        self.assertEqual(self.names("kw", limit=7), want[:7])
        self.assertEqual(self.names("kw"), want[:20])


class TestTerm(Base):
    def test_none_and_blank_return_empty(self):
        for q in (None, "", " ", "\t\n ", "%", "!!!", "پایتون"):
            self.assertEqual(self.k.search(q), [], repr(q))

    def test_normal_string_and_str_subclass(self):
        class S(str):
            pass
        self.assertEqual(len(self.k.search("kw")), 5)
        self.assertEqual(self.names(S("kw")), self.names("kw"))

    def test_every_non_string_term_raises_typeerror_regardless_of_truthiness(self):   # B2
        for bad in (0, 1, 5, -1, 0.0, 1.5, False, True, [], ["kw"], (), ("kw",), {}, {"kw"}, b"", b"kw",
                    bytearray(b"kw"), object(), 5j):
            with self.assertRaises(TypeError, msg=repr(bad)):
                self.k.search(bad)

    def test_no_string_coercion_of_non_strings(self):
        self.k.learn("5", "five")
        with self.assertRaises(TypeError):
            self.k.search(5)
        self.assertEqual(self.names("5"), ["5"])


class TestCombinations(Base):
    def test_blank_terms_with_valid_limits(self):
        for term in ("", None, "  "):
            for lim in (None, 0, 1, 50):
                self.assertEqual(self.k.search(term, limit=lim), [], (term, lim))

    def test_unsupported_term_with_any_limit_raises_typeerror(self):
        for lim in (None, 0, 3):
            with self.assertRaises(TypeError):
                self.k.search(5, limit=lim)

    def test_valid_term_matrix(self):
        self.assertEqual(self.names("kw", limit=0), [])
        with self.assertRaises(ValueError):
            self.k.search("kw", limit=-1)
        self.assertEqual(len(self.names("kw", limit=99)), 5)
        self.assertEqual(len(self.names("kw", limit=None)), 5)

    def test_positional_limit_and_keyword_limit_are_equivalent(self):
        self.assertEqual(self.k.search("kw", 2), self.k.search("kw", limit=2))
        with self.assertRaises(ValueError):
            self.k.search("kw", -1)

    def test_learning_system_search_wrapper_uses_the_same_validation(self):
        self.assertEqual(self.l.search("kw"), self.k.search("kw"))
        self.assertEqual(self.l.search(None), [])
        with self.assertRaises(TypeError):
            self.l.search(5)


class TestReadOnlyAndRegression(Base):
    def test_search_including_rejected_calls_never_writes(self):
        self.l.teach("Python", "a language", source="user", confidence=0.7)
        self.l.relate("Python", "Rust", "similar_to")
        self.l.correct("Python", "a programming language")
        snap = self.snap()
        calls = [("kw", {}), ("kw", {"limit": 0}), ("kw", {"limit": None}), ("", {}), (None, {"limit": 3}),
                 ("_", {}), ("%", {}), ("python", {"limit": 500})]
        for term, kw in calls:
            self.k.search(term, **kw)
        for term, kw in ((5, {}), ("kw", {"limit": -1}), ("kw", {"limit": True}), ("kw", {"limit": "2"}),
                         (["kw"], {}), (0, {})):
            with self.assertRaises((TypeError, ValueError)):
                self.k.search(term, **kw)
        self.assertEqual(self.snap(), snap)
        self.reopen()
        self.assertEqual(self.snap(), snap)

    def test_valid_results_unchanged_across_reopen_and_repeats(self):
        want = [self.k.search(q, limit=l) for q in ("kw", "n1", "n") for l in (None, 0, 2, 20)]
        for _ in range(2):
            self.reopen()
            self.assertEqual([self.k.search(q, limit=l) for q in ("kw", "n1", "n") for l in (None, 0, 2, 20)],
                             want)

    def test_prior_ranking_and_wildcard_contracts_preserved(self):
        self.k.learn("axb", "plain")
        self.k.learn("a_b", "under")
        self.assertEqual(self.names("a_b"), ["a_b"])
        self.assertEqual(self.names("%"), [])
        self.k.learn("kw", "the keyword")
        self.assertEqual(self.names("kw")[0], "kw")                 # phrase-in-name tier first
        self.assertEqual(self.names("kw"), self.names("kw", limit=None))

    def test_history_events_still_excluded(self):
        self.l.teach("Old", "snake"); self.l.correct("Old", "language")
        self.assertEqual(self.names("snake"), [])
        self.assertEqual(self.names("language"), ["Old"])


if __name__ == "__main__":
    unittest.main()
