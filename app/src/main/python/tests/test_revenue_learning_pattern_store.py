"""
Tests for RevenueLearningPatternStore
(financial/revenue_learning_pattern_store.py).

Covers: add_pattern() (valid patterns, invalid types, invalid/failed
is_valid() patterns, duplicate pattern_ids), get_pattern() (matching
id, unknown id), get_all() (empty store, insertion order,
returned-list independence), has_pattern() (existing pattern,
missing pattern, empty/invalid id, read-only behavior), count()
(empty/one/multiple patterns, read-only behavior), clear() (multiple
patterns, empty store, repeated calls, read-only w.r.t. the pattern
objects themselves), get_for_task()/get_for_opportunity()
(matching task/opportunity, no match, multiple patterns for one
task/opportunity, insertion order, empty/invalid id,
returned-list independence), get_latest_for_task() (latest
pattern, no match, multiple patterns for one task, correct
latest-pattern selection by insertion order, empty/invalid task id,
read-only behavior), get_latest_for_opportunity() (latest
pattern, no match, multiple patterns for one opportunity, correct
latest-pattern selection by insertion order, empty/invalid
opportunity id, read-only behavior), and
get_highest_reliability_for_task() (highest-reliability selection,
no match, multiple patterns for one task, equal-reliability tie
broken by insertion order, empty/invalid task id, read-only
behavior), get_highest_reliability_for_opportunity()
(highest-reliability selection, no match, multiple patterns for one
opportunity, equal-reliability tie broken by insertion order,
empty/invalid opportunity id, read-only behavior), and
get_reliable_patterns() (default threshold, custom threshold, all
patterns reliable, no reliable patterns, boundary values 0.0 and
1.0, insertion order, invalid threshold, read-only behavior), and
get_reliable_for_task() (matching task + reliable pattern, matching
task + unreliable pattern, multiple patterns mixed by task/
reliability, custom threshold, no matching task, empty/invalid task
id, insertion order, invalid threshold, read-only behavior), and
get_reliable_for_opportunity() (matching opportunity + reliable
pattern, matching opportunity + unreliable pattern, multiple
patterns mixed by opportunity/reliability, custom threshold, no
matching opportunity, empty/invalid opportunity id, insertion order,
invalid threshold, read-only behavior), and
get_best_reliable_for_task() (best reliable pattern, unreliable
patterns ignored, multiple reliable patterns, equal-reliability tie
broken by insertion order, no reliable pattern, empty/invalid task
id, invalid threshold, read-only behavior),
get_best_reliable_for_opportunity() (same coverage, keyed on
opportunity_id instead of task_id), and
get_task_pattern_summaries() (matching task summaries, no matching
task, multiple patterns, insertion order, summary values,
empty/invalid task id, read-only behavior), and
get_opportunity_pattern_summaries() (same coverage, keyed on
opportunity_id instead of task_id), and
get_latest_task_pattern_summary() (no pattern, latest matching
pattern's summary, summary contents, read-only behavior), and
get_latest_opportunity_pattern_summary() (same coverage, keyed on
opportunity_id instead of task_id), and
get_best_reliable_task_pattern_summary() (no reliable pattern, best
reliable pattern's summary, summary contents, below-threshold
pattern excluded, read-only behavior), and
get_best_reliable_opportunity_pattern_summary() (same coverage,
keyed on opportunity_id instead of task_id), and
count_reliable_for_task() (no patterns, all reliable patterns
counted, below-threshold patterns excluded, different task ids not
mixed, read-only behavior), and count_reliable_for_opportunity()
(same coverage, keyed on opportunity_id instead of task_id), and
has_reliable_for_task() (no patterns, at least one reliable pattern,
below-threshold patterns, different task ids not mixed, read-only
behavior).

This stage only stores and retrieves already-built
RevenueLearningPattern objects - it does not learn anything, does not
execute anything, and does not persist anything.

Run directly:
    python -m unittest tests.test_revenue_learning_pattern_store -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_learning_pattern_store import RevenueLearningPatternStore
from financial.revenue_learning_pattern import RevenueLearningPattern


def _make_pattern(**overrides):
    fields = dict(
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        total_records=4,
        successful_records=3,
        failed_records=1,
        success_rate=0.75,
        reliability=0.75,
        pattern_id="pattern-test-1",
    )
    fields.update(overrides)
    return RevenueLearningPattern(**fields)


# ----------------------------------------------------------------------
# 1. Adding a valid pattern
# ----------------------------------------------------------------------
class TestAddingAValidPattern(unittest.TestCase):
    def test_add_pattern_returns_the_same_pattern_on_success(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern()
        self.assertIs(store.add_pattern(pattern), pattern)

    def test_add_pattern_increases_store_length(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(len(store), 0)
        store.add_pattern(_make_pattern())
        self.assertEqual(len(store), 1)

    def test_multiple_distinct_patterns_all_accepted(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1")
        p2 = _make_pattern(pattern_id="p-2")
        self.assertIs(store.add_pattern(p1), p1)
        self.assertIs(store.add_pattern(p2), p2)
        self.assertEqual(len(store), 2)


# ----------------------------------------------------------------------
# 2. Rejecting invalid input
# ----------------------------------------------------------------------
class TestInvalidInputs(unittest.TestCase):
    def test_none_is_rejected(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.add_pattern(None))
        self.assertEqual(len(store), 0)

    def test_plain_dict_is_rejected(self):
        store = RevenueLearningPatternStore()
        fake = {"pattern_id": "p-1", "task_id": "task-a"}
        self.assertIsNone(store.add_pattern(fake))
        self.assertEqual(len(store), 0)

    def test_string_is_rejected(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.add_pattern("not a pattern"))
        self.assertEqual(len(store), 0)

    def test_pattern_failing_is_valid_is_rejected(self):
        store = RevenueLearningPatternStore()
        # successful_records + failed_records != total_records
        pattern = _make_pattern(total_records=10)
        self.assertFalse(pattern.is_valid())
        self.assertIsNone(store.add_pattern(pattern))
        self.assertEqual(len(store), 0)

    def test_empty_pattern_id_is_rejected(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="")
        self.assertIsNone(store.add_pattern(pattern))
        self.assertEqual(len(store), 0)

    def test_never_raises_on_invalid_input(self):
        store = RevenueLearningPatternStore()
        try:
            store.add_pattern(None)
            store.add_pattern(123)
            store.add_pattern({"not": "a pattern"})
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"store raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 3. Duplicate pattern ID protection
# ----------------------------------------------------------------------
class TestDuplicatePatternIds(unittest.TestCase):
    def test_second_add_with_same_id_is_rejected(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(pattern_id="dup-1")
        second = _make_pattern(pattern_id="dup-1", reliability=0.1)
        self.assertIs(store.add_pattern(first), first)
        self.assertIsNone(store.add_pattern(second))
        self.assertEqual(len(store), 1)

    def test_original_pattern_is_kept_on_duplicate(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(pattern_id="dup-2", reliability=0.9)
        second = _make_pattern(pattern_id="dup-2", reliability=0.1)
        store.add_pattern(first)
        store.add_pattern(second)
        stored = store.get_pattern("dup-2")
        self.assertEqual(stored.reliability, 0.9)


# ----------------------------------------------------------------------
# 4. Retrieving by pattern ID
# ----------------------------------------------------------------------
class TestGetPattern(unittest.TestCase):
    def test_returns_the_matching_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1")
        store.add_pattern(pattern)
        fetched = store.get_pattern("p-1")
        self.assertEqual(fetched.pattern_id, "p-1")

    def test_unknown_pattern_id_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_pattern("no-such-id"))

    def test_none_pattern_id_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        self.assertIsNone(store.get_pattern(None))


# ----------------------------------------------------------------------
# 5. Retrieving all patterns
# ----------------------------------------------------------------------
class TestGetAll(unittest.TestCase):
    def test_empty_store_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_all(), [])

    def test_returns_every_stored_pattern(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1")
        p2 = _make_pattern(pattern_id="p-2")
        store.add_pattern(p1)
        store.add_pattern(p2)
        all_patterns = store.get_all()
        self.assertEqual(len(all_patterns), 2)
        self.assertEqual([p.pattern_id for p in all_patterns], ["p-1", "p-2"])

    def test_preserves_insertion_order(self):
        store = RevenueLearningPatternStore()
        ids = ["p-3", "p-1", "p-2"]
        for pattern_id in ids:
            store.add_pattern(_make_pattern(pattern_id=pattern_id))
        self.assertEqual([p.pattern_id for p in store.get_all()], ids)

    def test_rejected_duplicate_does_not_disturb_order(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        store.add_pattern(_make_pattern(pattern_id="p-2"))
        store.add_pattern(_make_pattern(pattern_id="p-1"))  # duplicate, rejected
        self.assertEqual([p.pattern_id for p in store.get_all()], ["p-1", "p-2"])

    def test_returns_a_new_list_each_call(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        first = store.get_all()
        second = store.get_all()
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_mutating_returned_list_does_not_affect_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        patterns = store.get_all()
        patterns.append(_make_pattern(pattern_id="fake"))
        patterns.clear()
        self.assertEqual(len(store), 1)
        self.assertEqual(len(store.get_all()), 1)


# ----------------------------------------------------------------------
# 6. has_pattern()
# ----------------------------------------------------------------------
class TestHasPattern(unittest.TestCase):
    def test_existing_pattern_returns_true(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        self.assertTrue(store.has_pattern("p-1"))

    def test_missing_pattern_returns_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        self.assertFalse(store.has_pattern("no-such-id"))

    def test_empty_string_id_returns_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        self.assertFalse(store.has_pattern(""))

    def test_none_id_returns_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        self.assertFalse(store.has_pattern(None))

    def test_non_string_id_returns_false_safely(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        self.assertFalse(store.has_pattern(123))
        self.assertFalse(store.has_pattern(["p-1"]))

    def test_empty_store_returns_false(self):
        store = RevenueLearningPatternStore()
        self.assertFalse(store.has_pattern("p-1"))

    def test_does_not_modify_the_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        before = store.get_all()
        store.has_pattern("p-1")
        store.has_pattern("no-such-id")
        store.has_pattern(None)
        after = store.get_all()
        self.assertEqual(len(store), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )

    def test_never_raises_on_unusual_input(self):
        store = RevenueLearningPatternStore()
        try:
            store.has_pattern(None)
            store.has_pattern(123)
            store.has_pattern(["not", "hashable-safe?"])
            store.has_pattern({"a": 1})
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"has_pattern raised unexpectedly: {exc}")


# ----------------------------------------------------------------------
# 7. count()
# ----------------------------------------------------------------------
class TestCount(unittest.TestCase):
    def test_empty_store_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.count(), 0)

    def test_store_with_one_pattern_returns_one(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        self.assertEqual(store.count(), 1)

    def test_store_with_multiple_patterns_returns_correct_count(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        store.add_pattern(_make_pattern(pattern_id="p-2"))
        store.add_pattern(_make_pattern(pattern_id="p-3"))
        self.assertEqual(store.count(), 3)

    def test_count_increases_as_patterns_are_added(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.count(), 0)
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        self.assertEqual(store.count(), 1)
        store.add_pattern(_make_pattern(pattern_id="p-2"))
        self.assertEqual(store.count(), 2)
        # rejected duplicate must not affect count
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        self.assertEqual(store.count(), 2)

    def test_count_does_not_modify_the_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        before = store.get_all()
        store.count()
        store.count()
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )

    def test_count_matches_len(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        store.add_pattern(_make_pattern(pattern_id="p-2"))
        self.assertEqual(store.count(), len(store))


# ----------------------------------------------------------------------
# 8. clear()
# ----------------------------------------------------------------------
class TestClear(unittest.TestCase):
    def test_clearing_a_store_with_multiple_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        store.add_pattern(_make_pattern(pattern_id="p-2"))
        store.add_pattern(_make_pattern(pattern_id="p-3"))
        store.clear()
        self.assertEqual(store.count(), 0)
        self.assertEqual(store.get_all(), [])
        self.assertFalse(store.has_pattern("p-1"))
        self.assertFalse(store.has_pattern("p-2"))
        self.assertFalse(store.has_pattern("p-3"))

    def test_clearing_an_empty_store_is_safe(self):
        store = RevenueLearningPatternStore()
        try:
            store.clear()
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"clear() raised unexpectedly on empty store: {exc}")
        self.assertEqual(store.count(), 0)
        self.assertEqual(store.get_all(), [])

    def test_count_after_clear(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        store.add_pattern(_make_pattern(pattern_id="p-2"))
        self.assertEqual(store.count(), 2)
        store.clear()
        self.assertEqual(store.count(), 0)
        self.assertEqual(len(store), 0)

    def test_get_all_after_clear(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        store.add_pattern(_make_pattern(pattern_id="p-2"))
        store.clear()
        self.assertEqual(store.get_all(), [])
        # store remains usable after clear
        store.add_pattern(_make_pattern(pattern_id="p-3"))
        self.assertEqual([p.pattern_id for p in store.get_all()], ["p-3"])

    def test_calling_clear_multiple_times_is_safe(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        store.clear()
        store.clear()
        store.clear()
        self.assertEqual(store.count(), 0)
        self.assertEqual(store.get_all(), [])

    def test_clear_does_not_mutate_the_pattern_objects(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1")
        store.add_pattern(pattern)
        store.clear()
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 9. get_for_task()
# ----------------------------------------------------------------------
class TestGetForTask(unittest.TestCase):
    def test_matching_task_returns_the_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", task_id="task-a")
        store.add_pattern(pattern)
        results = store.get_for_task("task-a")
        self.assertEqual(len(results), 1)
        self.assertIs(results[0], pattern)

    def test_no_matching_task_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertEqual(store.get_for_task("task-does-not-exist"), [])

    def test_empty_store_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_for_task("task-a"), [])

    def test_multiple_patterns_for_same_task(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", task_id="task-a")
        p2 = _make_pattern(pattern_id="p-2", task_id="task-a")
        other = _make_pattern(pattern_id="p-3", task_id="task-b")
        store.add_pattern(p1)
        store.add_pattern(p2)
        store.add_pattern(other)
        results = store.get_for_task("task-a")
        self.assertEqual(len(results), 2)
        self.assertIn(p1, results)
        self.assertIn(p2, results)
        self.assertNotIn(other, results)

    def test_preserves_insertion_order(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-3", task_id="task-a"))
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-b"))
        store.add_pattern(_make_pattern(pattern_id="p-2", task_id="task-a"))
        results = store.get_for_task("task-a")
        self.assertEqual([p.pattern_id for p in results], ["p-3", "p-2"])

    def test_empty_string_task_id_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertEqual(store.get_for_task(""), [])

    def test_none_task_id_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertEqual(store.get_for_task(None), [])

    def test_unusual_task_id_never_raises(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        try:
            self.assertEqual(store.get_for_task(123), [])
            self.assertEqual(store.get_for_task(["task-a"]), [])
            self.assertEqual(store.get_for_task({"a": 1}), [])
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_for_task() raised unexpectedly: {exc}")

    def test_returns_a_new_list_each_call(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        first = store.get_for_task("task-a")
        second = store.get_for_task("task-a")
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_mutating_returned_list_does_not_affect_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        results = store.get_for_task("task-a")
        results.append(_make_pattern(pattern_id="fake", task_id="task-a"))
        results.clear()
        self.assertEqual(store.count(), 1)
        self.assertEqual(len(store.get_for_task("task-a")), 1)

    def test_does_not_modify_stored_patterns(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", task_id="task-a")
        store.add_pattern(pattern)
        store.get_for_task("task-a")
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 10. get_for_opportunity()
# ----------------------------------------------------------------------
class TestGetForOpportunity(unittest.TestCase):
    def test_matching_opportunity_returns_the_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        store.add_pattern(pattern)
        results = store.get_for_opportunity("opp-a")
        self.assertEqual(len(results), 1)
        self.assertIs(results[0], pattern)

    def test_no_matching_opportunity_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertEqual(store.get_for_opportunity("opp-does-not-exist"), [])

    def test_empty_store_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_for_opportunity("opp-a"), [])

    def test_multiple_patterns_for_same_opportunity(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        p2 = _make_pattern(pattern_id="p-2", opportunity_id="opp-a")
        other = _make_pattern(pattern_id="p-3", opportunity_id="opp-b")
        store.add_pattern(p1)
        store.add_pattern(p2)
        store.add_pattern(other)
        results = store.get_for_opportunity("opp-a")
        self.assertEqual(len(results), 2)
        self.assertIn(p1, results)
        self.assertIn(p2, results)
        self.assertNotIn(other, results)

    def test_preserves_insertion_order(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-3", opportunity_id="opp-a"))
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-b"))
        store.add_pattern(_make_pattern(pattern_id="p-2", opportunity_id="opp-a"))
        results = store.get_for_opportunity("opp-a")
        self.assertEqual([p.pattern_id for p in results], ["p-3", "p-2"])

    def test_empty_string_opportunity_id_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertEqual(store.get_for_opportunity(""), [])

    def test_none_opportunity_id_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertEqual(store.get_for_opportunity(None), [])

    def test_unusual_opportunity_id_never_raises(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        try:
            self.assertEqual(store.get_for_opportunity(123), [])
            self.assertEqual(store.get_for_opportunity(["opp-a"]), [])
            self.assertEqual(store.get_for_opportunity({"a": 1}), [])
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_for_opportunity() raised unexpectedly: {exc}")

    def test_returns_a_new_list_each_call(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        first = store.get_for_opportunity("opp-a")
        second = store.get_for_opportunity("opp-a")
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_mutating_returned_list_does_not_affect_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        results = store.get_for_opportunity("opp-a")
        results.append(_make_pattern(pattern_id="fake", opportunity_id="opp-a"))
        results.clear()
        self.assertEqual(store.count(), 1)
        self.assertEqual(len(store.get_for_opportunity("opp-a")), 1)

    def test_does_not_modify_stored_patterns(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        store.add_pattern(pattern)
        store.get_for_opportunity("opp-a")
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 11. get_latest_for_task()
# ----------------------------------------------------------------------
class TestGetLatestForTask(unittest.TestCase):
    def test_returns_the_latest_pattern_for_a_task(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", task_id="task-a")
        store.add_pattern(pattern)
        self.assertIs(store.get_latest_for_task("task-a"), pattern)

    def test_no_matching_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertIsNone(store.get_latest_for_task("task-does-not-exist"))

    def test_empty_store_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_latest_for_task("task-a"))

    def test_multiple_patterns_for_same_task(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", task_id="task-a")
        p2 = _make_pattern(pattern_id="p-2", task_id="task-a")
        p3 = _make_pattern(pattern_id="p-3", task_id="task-a")
        store.add_pattern(p1)
        store.add_pattern(p2)
        store.add_pattern(p3)
        self.assertIs(store.get_latest_for_task("task-a"), p3)

    def test_correct_latest_pattern_selection_among_multiple_tasks(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        store.add_pattern(_make_pattern(pattern_id="p-2", task_id="task-b"))
        latest_a = _make_pattern(pattern_id="p-3", task_id="task-a")
        store.add_pattern(latest_a)
        store.add_pattern(_make_pattern(pattern_id="p-4", task_id="task-b"))
        self.assertIs(store.get_latest_for_task("task-a"), latest_a)

    def test_uses_insertion_order_not_reliability_or_created_at(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        second = _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.1)
        store.add_pattern(first)
        store.add_pattern(second)
        # second was added last, so it's "latest" regardless of its
        # lower reliability value.
        self.assertIs(store.get_latest_for_task("task-a"), second)

    def test_empty_string_task_id_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertIsNone(store.get_latest_for_task(""))

    def test_none_task_id_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertIsNone(store.get_latest_for_task(None))

    def test_unusual_task_id_never_raises(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        try:
            self.assertIsNone(store.get_latest_for_task(123))
            self.assertIsNone(store.get_latest_for_task(["task-a"]))
            self.assertIsNone(store.get_latest_for_task({"a": 1}))
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_latest_for_task() raised unexpectedly: {exc}")

    def test_does_not_modify_the_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        store.add_pattern(_make_pattern(pattern_id="p-2", task_id="task-a"))
        before = store.get_all()
        store.get_latest_for_task("task-a")
        store.get_latest_for_task("no-such-task")
        store.get_latest_for_task(None)
        after = store.get_all()
        self.assertEqual(store.count(), 2)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )

    def test_does_not_modify_stored_patterns(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", task_id="task-a")
        store.add_pattern(pattern)
        store.get_latest_for_task("task-a")
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 12. get_latest_for_opportunity()
# ----------------------------------------------------------------------
class TestGetLatestForOpportunity(unittest.TestCase):
    def test_returns_the_latest_pattern_for_an_opportunity(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        store.add_pattern(pattern)
        self.assertIs(store.get_latest_for_opportunity("opp-a"), pattern)

    def test_no_matching_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertIsNone(store.get_latest_for_opportunity("opp-does-not-exist"))

    def test_empty_store_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_latest_for_opportunity("opp-a"))

    def test_multiple_patterns_for_same_opportunity(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        p2 = _make_pattern(pattern_id="p-2", opportunity_id="opp-a")
        p3 = _make_pattern(pattern_id="p-3", opportunity_id="opp-a")
        store.add_pattern(p1)
        store.add_pattern(p2)
        store.add_pattern(p3)
        self.assertIs(store.get_latest_for_opportunity("opp-a"), p3)

    def test_correct_latest_pattern_selection_among_multiple_opportunities(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        store.add_pattern(_make_pattern(pattern_id="p-2", opportunity_id="opp-b"))
        latest_a = _make_pattern(pattern_id="p-3", opportunity_id="opp-a")
        store.add_pattern(latest_a)
        store.add_pattern(_make_pattern(pattern_id="p-4", opportunity_id="opp-b"))
        self.assertIs(store.get_latest_for_opportunity("opp-a"), latest_a)

    def test_uses_insertion_order_not_reliability_or_created_at(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        second = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.1
        )
        store.add_pattern(first)
        store.add_pattern(second)
        # second was added last, so it's "latest" regardless of its
        # lower reliability value.
        self.assertIs(store.get_latest_for_opportunity("opp-a"), second)

    def test_empty_string_opportunity_id_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertIsNone(store.get_latest_for_opportunity(""))

    def test_none_opportunity_id_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertIsNone(store.get_latest_for_opportunity(None))

    def test_unusual_opportunity_id_never_raises(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        try:
            self.assertIsNone(store.get_latest_for_opportunity(123))
            self.assertIsNone(store.get_latest_for_opportunity(["opp-a"]))
            self.assertIsNone(store.get_latest_for_opportunity({"a": 1}))
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_latest_for_opportunity() raised unexpectedly: {exc}")

    def test_does_not_modify_the_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        store.add_pattern(_make_pattern(pattern_id="p-2", opportunity_id="opp-a"))
        before = store.get_all()
        store.get_latest_for_opportunity("opp-a")
        store.get_latest_for_opportunity("no-such-opportunity")
        store.get_latest_for_opportunity(None)
        after = store.get_all()
        self.assertEqual(store.count(), 2)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )

    def test_does_not_modify_stored_patterns(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        store.add_pattern(pattern)
        store.get_latest_for_opportunity("opp-a")
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 13. get_highest_reliability_for_task()
# ----------------------------------------------------------------------
class TestGetHighestReliabilityForTask(unittest.TestCase):
    def test_returns_the_highest_reliability_pattern(self):
        store = RevenueLearningPatternStore()
        low = _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.2)
        high = _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.9)
        mid = _make_pattern(pattern_id="p-3", task_id="task-a", reliability=0.5)
        store.add_pattern(low)
        store.add_pattern(high)
        store.add_pattern(mid)
        self.assertIs(store.get_highest_reliability_for_task("task-a"), high)

    def test_no_matching_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertIsNone(
            store.get_highest_reliability_for_task("task-does-not-exist")
        )

    def test_empty_store_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_highest_reliability_for_task("task-a"))

    def test_multiple_patterns_for_same_task(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.3)
        p2 = _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.7)
        other_task = _make_pattern(
            pattern_id="p-3", task_id="task-b", reliability=0.99
        )
        store.add_pattern(p1)
        store.add_pattern(p2)
        store.add_pattern(other_task)
        self.assertIs(store.get_highest_reliability_for_task("task-a"), p2)

    def test_equal_reliability_tie_broken_by_insertion_order(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.5)
        second = _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.5)
        store.add_pattern(first)
        store.add_pattern(second)
        # Both share the same reliability - the earliest one added wins.
        self.assertIs(store.get_highest_reliability_for_task("task-a"), first)

    def test_empty_string_task_id_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertIsNone(store.get_highest_reliability_for_task(""))

    def test_none_task_id_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertIsNone(store.get_highest_reliability_for_task(None))

    def test_unusual_task_id_never_raises(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        try:
            self.assertIsNone(store.get_highest_reliability_for_task(123))
            self.assertIsNone(store.get_highest_reliability_for_task(["task-a"]))
            self.assertIsNone(store.get_highest_reliability_for_task({"a": 1}))
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(
                f"get_highest_reliability_for_task() raised unexpectedly: {exc}"
            )

    def test_does_not_modify_the_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.2)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.8)
        )
        before = store.get_all()
        store.get_highest_reliability_for_task("task-a")
        store.get_highest_reliability_for_task("no-such-task")
        store.get_highest_reliability_for_task(None)
        after = store.get_all()
        self.assertEqual(store.count(), 2)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )

    def test_does_not_modify_stored_patterns(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.6)
        store.add_pattern(pattern)
        store.get_highest_reliability_for_task("task-a")
        self.assertEqual(pattern.task_id, "task-a")
        self.assertEqual(pattern.reliability, 0.6)
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 14. get_highest_reliability_for_opportunity()
# ----------------------------------------------------------------------
class TestGetHighestReliabilityForOpportunity(unittest.TestCase):
    def test_returns_the_highest_reliability_pattern(self):
        store = RevenueLearningPatternStore()
        low = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.2
        )
        high = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.9
        )
        mid = _make_pattern(
            pattern_id="p-3", opportunity_id="opp-a", reliability=0.5
        )
        store.add_pattern(low)
        store.add_pattern(high)
        store.add_pattern(mid)
        self.assertIs(
            store.get_highest_reliability_for_opportunity("opp-a"), high
        )

    def test_no_matching_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertIsNone(
            store.get_highest_reliability_for_opportunity("opp-does-not-exist")
        )

    def test_empty_store_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_highest_reliability_for_opportunity("opp-a"))

    def test_multiple_patterns_for_same_opportunity(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.3
        )
        p2 = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.7
        )
        other_opportunity = _make_pattern(
            pattern_id="p-3", opportunity_id="opp-b", reliability=0.99
        )
        store.add_pattern(p1)
        store.add_pattern(p2)
        store.add_pattern(other_opportunity)
        self.assertIs(store.get_highest_reliability_for_opportunity("opp-a"), p2)

    def test_equal_reliability_tie_broken_by_insertion_order(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.5
        )
        second = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.5
        )
        store.add_pattern(first)
        store.add_pattern(second)
        # Both share the same reliability - the earliest one added wins.
        self.assertIs(
            store.get_highest_reliability_for_opportunity("opp-a"), first
        )

    def test_empty_string_opportunity_id_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertIsNone(store.get_highest_reliability_for_opportunity(""))

    def test_none_opportunity_id_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertIsNone(store.get_highest_reliability_for_opportunity(None))

    def test_unusual_opportunity_id_never_raises(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        try:
            self.assertIsNone(store.get_highest_reliability_for_opportunity(123))
            self.assertIsNone(
                store.get_highest_reliability_for_opportunity(["opp-a"])
            )
            self.assertIsNone(
                store.get_highest_reliability_for_opportunity({"a": 1})
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(
                "get_highest_reliability_for_opportunity() raised "
                f"unexpectedly: {exc}"
            )

    def test_does_not_modify_the_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.2)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", opportunity_id="opp-a", reliability=0.8)
        )
        before = store.get_all()
        store.get_highest_reliability_for_opportunity("opp-a")
        store.get_highest_reliability_for_opportunity("no-such-opportunity")
        store.get_highest_reliability_for_opportunity(None)
        after = store.get_all()
        self.assertEqual(store.count(), 2)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )

    def test_does_not_modify_stored_patterns(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.6
        )
        store.add_pattern(pattern)
        store.get_highest_reliability_for_opportunity("opp-a")
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertEqual(pattern.reliability, 0.6)
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 15. get_reliable_patterns()
# ----------------------------------------------------------------------
class TestGetReliablePatterns(unittest.TestCase):
    def test_default_threshold(self):
        store = RevenueLearningPatternStore()
        reliable = _make_pattern(pattern_id="p-1", reliability=0.8)
        unreliable = _make_pattern(pattern_id="p-2", reliability=0.5)
        store.add_pattern(reliable)
        store.add_pattern(unreliable)
        results = store.get_reliable_patterns()
        self.assertEqual(results, [reliable])

    def test_custom_threshold(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", reliability=0.3)
        p2 = _make_pattern(pattern_id="p-2", reliability=0.6)
        store.add_pattern(p1)
        store.add_pattern(p2)
        self.assertEqual(store.get_reliable_patterns(min_reliability=0.4), [p2])
        self.assertEqual(
            store.get_reliable_patterns(min_reliability=0.2), [p1, p2]
        )

    def test_all_patterns_reliable(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", reliability=0.8)
        p2 = _make_pattern(pattern_id="p-2", reliability=0.9)
        store.add_pattern(p1)
        store.add_pattern(p2)
        self.assertEqual(store.get_reliable_patterns(min_reliability=0.7), [p1, p2])

    def test_no_reliable_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", reliability=0.1))
        store.add_pattern(_make_pattern(pattern_id="p-2", reliability=0.2))
        self.assertEqual(store.get_reliable_patterns(min_reliability=0.7), [])

    def test_empty_store_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_reliable_patterns(), [])

    def test_boundary_value_zero(self):
        store = RevenueLearningPatternStore()
        zero = _make_pattern(pattern_id="p-1", reliability=0.0)
        nonzero = _make_pattern(pattern_id="p-2", reliability=0.4)
        store.add_pattern(zero)
        store.add_pattern(nonzero)
        results = store.get_reliable_patterns(min_reliability=0.0)
        self.assertEqual(results, [zero, nonzero])

    def test_boundary_value_one(self):
        store = RevenueLearningPatternStore()
        perfect = _make_pattern(pattern_id="p-1", reliability=1.0)
        almost = _make_pattern(pattern_id="p-2", reliability=0.99)
        store.add_pattern(perfect)
        store.add_pattern(almost)
        results = store.get_reliable_patterns(min_reliability=1.0)
        self.assertEqual(results, [perfect])

    def test_preserves_insertion_order(self):
        store = RevenueLearningPatternStore()
        p3 = _make_pattern(pattern_id="p-3", reliability=0.8)
        p1 = _make_pattern(pattern_id="p-1", reliability=0.9)
        p2 = _make_pattern(pattern_id="p-2", reliability=0.75)
        store.add_pattern(p3)
        store.add_pattern(p1)
        store.add_pattern(p2)
        results = store.get_reliable_patterns(min_reliability=0.7)
        self.assertEqual([p.pattern_id for p in results], ["p-3", "p-1", "p-2"])

    def test_invalid_threshold_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", reliability=0.9))
        try:
            self.assertEqual(store.get_reliable_patterns(min_reliability=None), [])
            self.assertEqual(
                store.get_reliable_patterns(min_reliability="high"), []
            )
            self.assertEqual(
                store.get_reliable_patterns(min_reliability=["0.7"]), []
            )
            self.assertEqual(
                store.get_reliable_patterns(min_reliability={"x": 1}), []
            )
            self.assertEqual(
                store.get_reliable_patterns(min_reliability=float("nan")), []
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_reliable_patterns() raised unexpectedly: {exc}")

    def test_returns_a_new_list_each_call(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", reliability=0.9))
        first = store.get_reliable_patterns()
        second = store.get_reliable_patterns()
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_mutating_returned_list_does_not_affect_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", reliability=0.9))
        results = store.get_reliable_patterns()
        results.append(_make_pattern(pattern_id="fake", reliability=1.0))
        results.clear()
        self.assertEqual(store.count(), 1)
        self.assertEqual(len(store.get_reliable_patterns()), 1)

    def test_does_not_modify_stored_patterns(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", reliability=0.9)
        store.add_pattern(pattern)
        store.get_reliable_patterns()
        self.assertEqual(pattern.reliability, 0.9)
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 16. get_reliable_for_task()
# ----------------------------------------------------------------------
class TestGetReliableForTask(unittest.TestCase):
    def test_matching_task_and_reliable_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.8
        )
        store.add_pattern(pattern)
        self.assertEqual(store.get_reliable_for_task("task-a"), [pattern])

    def test_matching_task_but_unreliable_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.5
        )
        store.add_pattern(pattern)
        self.assertEqual(store.get_reliable_for_task("task-a"), [])

    def test_multiple_patterns_mixed_reliability_and_task(self):
        store = RevenueLearningPatternStore()
        reliable_a = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        unreliable_a = _make_pattern(
            pattern_id="p-2", task_id="task-a", reliability=0.4
        )
        reliable_b = _make_pattern(
            pattern_id="p-3", task_id="task-b", reliability=0.95
        )
        store.add_pattern(reliable_a)
        store.add_pattern(unreliable_a)
        store.add_pattern(reliable_b)
        self.assertEqual(
            store.get_reliable_for_task("task-a"), [reliable_a]
        )

    def test_custom_reliability_threshold(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.3)
        p2 = _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.6)
        store.add_pattern(p1)
        store.add_pattern(p2)
        self.assertEqual(
            store.get_reliable_for_task("task-a", min_reliability=0.4), [p2]
        )
        self.assertEqual(
            store.get_reliable_for_task("task-a", min_reliability=0.2),
            [p1, p2],
        )

    def test_no_matching_task_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        self.assertEqual(store.get_reliable_for_task("task-z"), [])

    def test_empty_or_invalid_task_id_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        try:
            self.assertEqual(store.get_reliable_for_task(""), [])
            self.assertEqual(store.get_reliable_for_task(None), [])
            self.assertEqual(store.get_reliable_for_task(123), [])
            self.assertEqual(store.get_reliable_for_task(["task-a"]), [])
            self.assertEqual(store.get_reliable_for_task({"a": 1}), [])
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_reliable_for_task() raised unexpectedly: {exc}")

    def test_preserves_insertion_order(self):
        store = RevenueLearningPatternStore()
        p3 = _make_pattern(pattern_id="p-3", task_id="task-a", reliability=0.8)
        p1 = _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        p2 = _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.75)
        store.add_pattern(p3)
        store.add_pattern(p1)
        store.add_pattern(p2)
        results = store.get_reliable_for_task("task-a", min_reliability=0.7)
        self.assertEqual(
            [p.pattern_id for p in results], ["p-3", "p-1", "p-2"]
        )

    def test_invalid_threshold_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        try:
            self.assertEqual(
                store.get_reliable_for_task("task-a", min_reliability=None), []
            )
            self.assertEqual(
                store.get_reliable_for_task("task-a", min_reliability="high"),
                [],
            )
            self.assertEqual(
                store.get_reliable_for_task(
                    "task-a", min_reliability=["0.7"]
                ),
                [],
            )
            self.assertEqual(
                store.get_reliable_for_task(
                    "task-a", min_reliability=float("nan")
                ),
                [],
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get_reliable_for_task() raised unexpectedly: {exc}")

    def test_returns_a_new_list_each_call(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        first = store.get_reliable_for_task("task-a")
        second = store.get_reliable_for_task("task-a")
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_mutating_returned_list_does_not_affect_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        results = store.get_reliable_for_task("task-a")
        results.append(
            _make_pattern(pattern_id="fake", task_id="task-a", reliability=1.0)
        )
        results.clear()
        self.assertEqual(store.count(), 1)
        self.assertEqual(len(store.get_reliable_for_task("task-a")), 1)

    def test_does_not_modify_stored_patterns_or_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_reliable_for_task("task-a")
        store.get_reliable_for_task("no-such-task")
        store.get_reliable_for_task(None)
        after = store.get_all()
        self.assertEqual(pattern.reliability, 0.9)
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )


# ----------------------------------------------------------------------
# 17. get_reliable_for_opportunity()
# ----------------------------------------------------------------------
class TestGetReliableForOpportunity(unittest.TestCase):
    def test_matching_opportunity_and_reliable_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.8
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_reliable_for_opportunity("opp-a"), [pattern]
        )

    def test_matching_opportunity_but_unreliable_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.5
        )
        store.add_pattern(pattern)
        self.assertEqual(store.get_reliable_for_opportunity("opp-a"), [])

    def test_multiple_patterns_mixed_reliability_and_opportunity(self):
        store = RevenueLearningPatternStore()
        reliable_a = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        unreliable_a = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.4
        )
        reliable_b = _make_pattern(
            pattern_id="p-3", opportunity_id="opp-b", reliability=0.95
        )
        store.add_pattern(reliable_a)
        store.add_pattern(unreliable_a)
        store.add_pattern(reliable_b)
        self.assertEqual(
            store.get_reliable_for_opportunity("opp-a"), [reliable_a]
        )

    def test_custom_reliability_threshold(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.3
        )
        p2 = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.6
        )
        store.add_pattern(p1)
        store.add_pattern(p2)
        self.assertEqual(
            store.get_reliable_for_opportunity("opp-a", min_reliability=0.4),
            [p2],
        )
        self.assertEqual(
            store.get_reliable_for_opportunity("opp-a", min_reliability=0.2),
            [p1, p2],
        )

    def test_no_matching_opportunity_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        self.assertEqual(store.get_reliable_for_opportunity("opp-z"), [])

    def test_empty_or_invalid_opportunity_id_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        try:
            self.assertEqual(store.get_reliable_for_opportunity(""), [])
            self.assertEqual(store.get_reliable_for_opportunity(None), [])
            self.assertEqual(store.get_reliable_for_opportunity(123), [])
            self.assertEqual(
                store.get_reliable_for_opportunity(["opp-a"]), []
            )
            self.assertEqual(
                store.get_reliable_for_opportunity({"a": 1}), []
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(
                f"get_reliable_for_opportunity() raised unexpectedly: {exc}"
            )

    def test_preserves_insertion_order(self):
        store = RevenueLearningPatternStore()
        p3 = _make_pattern(
            pattern_id="p-3", opportunity_id="opp-a", reliability=0.8
        )
        p1 = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        p2 = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.75
        )
        store.add_pattern(p3)
        store.add_pattern(p1)
        store.add_pattern(p2)
        results = store.get_reliable_for_opportunity(
            "opp-a", min_reliability=0.7
        )
        self.assertEqual(
            [p.pattern_id for p in results], ["p-3", "p-1", "p-2"]
        )

    def test_invalid_threshold_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        try:
            self.assertEqual(
                store.get_reliable_for_opportunity(
                    "opp-a", min_reliability=None
                ),
                [],
            )
            self.assertEqual(
                store.get_reliable_for_opportunity(
                    "opp-a", min_reliability="high"
                ),
                [],
            )
            self.assertEqual(
                store.get_reliable_for_opportunity(
                    "opp-a", min_reliability=["0.7"]
                ),
                [],
            )
            self.assertEqual(
                store.get_reliable_for_opportunity(
                    "opp-a", min_reliability=float("nan")
                ),
                [],
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(
                f"get_reliable_for_opportunity() raised unexpectedly: {exc}"
            )

    def test_returns_a_new_list_each_call(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        first = store.get_reliable_for_opportunity("opp-a")
        second = store.get_reliable_for_opportunity("opp-a")
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_mutating_returned_list_does_not_affect_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        results = store.get_reliable_for_opportunity("opp-a")
        results.append(
            _make_pattern(
                pattern_id="fake", opportunity_id="opp-a", reliability=1.0
            )
        )
        results.clear()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            len(store.get_reliable_for_opportunity("opp-a")), 1
        )

    def test_does_not_modify_stored_patterns_or_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_reliable_for_opportunity("opp-a")
        store.get_reliable_for_opportunity("no-such-opportunity")
        store.get_reliable_for_opportunity(None)
        after = store.get_all()
        self.assertEqual(pattern.reliability, 0.9)
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )


# ----------------------------------------------------------------------
# 18. get_best_reliable_for_task()
# ----------------------------------------------------------------------
class TestGetBestReliableForTask(unittest.TestCase):
    def test_best_reliable_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.8
        )
        store.add_pattern(pattern)
        self.assertIs(store.get_best_reliable_for_task("task-a"), pattern)

    def test_unreliable_patterns_are_ignored(self):
        store = RevenueLearningPatternStore()
        unreliable = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.5
        )
        store.add_pattern(unreliable)
        self.assertIsNone(store.get_best_reliable_for_task("task-a"))

    def test_multiple_reliable_patterns_returns_highest(self):
        store = RevenueLearningPatternStore()
        low = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.7
        )
        high = _make_pattern(
            pattern_id="p-2", task_id="task-a", reliability=0.95
        )
        mid = _make_pattern(
            pattern_id="p-3", task_id="task-a", reliability=0.8
        )
        unreliable = _make_pattern(
            pattern_id="p-4", task_id="task-a", reliability=0.3
        )
        other_task = _make_pattern(
            pattern_id="p-5", task_id="task-b", reliability=0.99
        )
        store.add_pattern(low)
        store.add_pattern(high)
        store.add_pattern(mid)
        store.add_pattern(unreliable)
        store.add_pattern(other_task)
        self.assertIs(store.get_best_reliable_for_task("task-a"), high)

    def test_equal_reliability_tie_broken_by_insertion_order(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.8
        )
        second = _make_pattern(
            pattern_id="p-2", task_id="task-a", reliability=0.8
        )
        store.add_pattern(first)
        store.add_pattern(second)
        # Both share the same reliability - the earliest one added wins.
        self.assertIs(store.get_best_reliable_for_task("task-a"), first)

    def test_no_reliable_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.5)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-b", reliability=0.9)
        )
        self.assertIsNone(store.get_best_reliable_for_task("task-a"))
        self.assertIsNone(store.get_best_reliable_for_task("task-z"))

    def test_empty_or_invalid_task_id_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        try:
            self.assertIsNone(store.get_best_reliable_for_task(""))
            self.assertIsNone(store.get_best_reliable_for_task(None))
            self.assertIsNone(store.get_best_reliable_for_task(123))
            self.assertIsNone(store.get_best_reliable_for_task(["task-a"]))
            self.assertIsNone(store.get_best_reliable_for_task({"a": 1}))
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(
                f"get_best_reliable_for_task() raised unexpectedly: {exc}"
            )

    def test_custom_reliability_threshold(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.5)
        p2 = _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.3)
        store.add_pattern(p1)
        store.add_pattern(p2)
        self.assertIs(
            store.get_best_reliable_for_task("task-a", min_reliability=0.4),
            p1,
        )
        self.assertIsNone(
            store.get_best_reliable_for_task("task-a", min_reliability=0.6)
        )

    def test_invalid_threshold_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        try:
            self.assertIsNone(
                store.get_best_reliable_for_task(
                    "task-a", min_reliability=None
                )
            )
            self.assertIsNone(
                store.get_best_reliable_for_task(
                    "task-a", min_reliability="high"
                )
            )
            self.assertIsNone(
                store.get_best_reliable_for_task(
                    "task-a", min_reliability=["0.7"]
                )
            )
            self.assertIsNone(
                store.get_best_reliable_for_task(
                    "task-a", min_reliability=float("nan")
                )
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(
                f"get_best_reliable_for_task() raised unexpectedly: {exc}"
            )

    def test_does_not_modify_the_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.2)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.8)
        )
        before = store.get_all()
        store.get_best_reliable_for_task("task-a")
        store.get_best_reliable_for_task("no-such-task")
        store.get_best_reliable_for_task(None)
        after = store.get_all()
        self.assertEqual(store.count(), 2)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )

    def test_does_not_modify_stored_patterns(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.6
        )
        store.add_pattern(pattern)
        store.get_best_reliable_for_task("task-a")
        self.assertEqual(pattern.task_id, "task-a")
        self.assertEqual(pattern.reliability, 0.6)
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 19. get_best_reliable_for_opportunity()
# ----------------------------------------------------------------------
class TestGetBestReliableForOpportunity(unittest.TestCase):
    def test_best_reliable_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.8
        )
        store.add_pattern(pattern)
        self.assertIs(
            store.get_best_reliable_for_opportunity("opp-a"), pattern
        )

    def test_unreliable_patterns_are_ignored(self):
        store = RevenueLearningPatternStore()
        unreliable = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.5
        )
        store.add_pattern(unreliable)
        self.assertIsNone(store.get_best_reliable_for_opportunity("opp-a"))

    def test_multiple_reliable_patterns_returns_highest(self):
        store = RevenueLearningPatternStore()
        low = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.7
        )
        high = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.95
        )
        mid = _make_pattern(
            pattern_id="p-3", opportunity_id="opp-a", reliability=0.8
        )
        unreliable = _make_pattern(
            pattern_id="p-4", opportunity_id="opp-a", reliability=0.3
        )
        other_opportunity = _make_pattern(
            pattern_id="p-5", opportunity_id="opp-b", reliability=0.99
        )
        store.add_pattern(low)
        store.add_pattern(high)
        store.add_pattern(mid)
        store.add_pattern(unreliable)
        store.add_pattern(other_opportunity)
        self.assertIs(store.get_best_reliable_for_opportunity("opp-a"), high)

    def test_equal_reliability_tie_broken_by_insertion_order(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.8
        )
        second = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.8
        )
        store.add_pattern(first)
        store.add_pattern(second)
        # Both share the same reliability - the earliest one added wins.
        self.assertIs(store.get_best_reliable_for_opportunity("opp-a"), first)

    def test_no_reliable_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.5
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-b", reliability=0.9
            )
        )
        self.assertIsNone(store.get_best_reliable_for_opportunity("opp-a"))
        self.assertIsNone(store.get_best_reliable_for_opportunity("opp-z"))

    def test_empty_or_invalid_opportunity_id_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        try:
            self.assertIsNone(store.get_best_reliable_for_opportunity(""))
            self.assertIsNone(store.get_best_reliable_for_opportunity(None))
            self.assertIsNone(store.get_best_reliable_for_opportunity(123))
            self.assertIsNone(
                store.get_best_reliable_for_opportunity(["opp-a"])
            )
            self.assertIsNone(
                store.get_best_reliable_for_opportunity({"a": 1})
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(
                "get_best_reliable_for_opportunity() raised "
                f"unexpectedly: {exc}"
            )

    def test_custom_reliability_threshold(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.5
        )
        p2 = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.3
        )
        store.add_pattern(p1)
        store.add_pattern(p2)
        self.assertIs(
            store.get_best_reliable_for_opportunity(
                "opp-a", min_reliability=0.4
            ),
            p1,
        )
        self.assertIsNone(
            store.get_best_reliable_for_opportunity(
                "opp-a", min_reliability=0.6
            )
        )

    def test_invalid_threshold_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        try:
            self.assertIsNone(
                store.get_best_reliable_for_opportunity(
                    "opp-a", min_reliability=None
                )
            )
            self.assertIsNone(
                store.get_best_reliable_for_opportunity(
                    "opp-a", min_reliability="high"
                )
            )
            self.assertIsNone(
                store.get_best_reliable_for_opportunity(
                    "opp-a", min_reliability=["0.7"]
                )
            )
            self.assertIsNone(
                store.get_best_reliable_for_opportunity(
                    "opp-a", min_reliability=float("nan")
                )
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(
                "get_best_reliable_for_opportunity() raised "
                f"unexpectedly: {exc}"
            )

    def test_does_not_modify_the_store(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.2
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-a", reliability=0.8
            )
        )
        before = store.get_all()
        store.get_best_reliable_for_opportunity("opp-a")
        store.get_best_reliable_for_opportunity("no-such-opportunity")
        store.get_best_reliable_for_opportunity(None)
        after = store.get_all()
        self.assertEqual(store.count(), 2)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )

    def test_does_not_modify_stored_patterns(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.6
        )
        store.add_pattern(pattern)
        store.get_best_reliable_for_opportunity("opp-a")
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertEqual(pattern.reliability, 0.6)
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 20. get_task_pattern_summaries()
# ----------------------------------------------------------------------
class TestGetTaskPatternSummaries(unittest.TestCase):
    def test_matching_task_summaries(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", task_id="task-a")
        store.add_pattern(pattern)
        summaries = store.get_task_pattern_summaries("task-a")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0], pattern.get_summary())

    def test_no_matching_task_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertEqual(
            store.get_task_pattern_summaries("task-does-not-exist"), []
        )

    def test_empty_store_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_task_pattern_summaries("task-a"), [])

    def test_multiple_patterns_for_same_task(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", task_id="task-a")
        p2 = _make_pattern(pattern_id="p-2", task_id="task-a")
        other = _make_pattern(pattern_id="p-3", task_id="task-b")
        store.add_pattern(p1)
        store.add_pattern(p2)
        store.add_pattern(other)
        summaries = store.get_task_pattern_summaries("task-a")
        self.assertEqual(len(summaries), 2)
        self.assertIn(p1.get_summary(), summaries)
        self.assertIn(p2.get_summary(), summaries)
        self.assertNotIn(other.get_summary(), summaries)

    def test_preserves_insertion_order(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-3", task_id="task-a"))
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-b"))
        store.add_pattern(_make_pattern(pattern_id="p-2", task_id="task-a"))
        summaries = store.get_task_pattern_summaries("task-a")
        self.assertEqual(
            [s["pattern_id"] for s in summaries], ["p-3", "p-2"]
        )

    def test_summary_values_match_the_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            opportunity_id="opp-a",
            total_records=10,
            successful_records=8,
            failed_records=2,
            success_rate=0.8,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        summaries = store.get_task_pattern_summaries("task-a")
        self.assertEqual(summaries[0], {
            "pattern_id": "p-1",
            "task_id": "task-a",
            "opportunity_id": "opp-a",
            "total_records": 10,
            "successful_records": 8,
            "failed_records": 2,
            "success_rate": 0.8,
            "reliability": 0.8,
        })

    def test_empty_string_task_id_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertEqual(store.get_task_pattern_summaries(""), [])

    def test_none_task_id_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertEqual(store.get_task_pattern_summaries(None), [])

    def test_unusual_task_id_never_raises(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        try:
            self.assertEqual(store.get_task_pattern_summaries(123), [])
            self.assertEqual(
                store.get_task_pattern_summaries(["task-a"]), []
            )
            self.assertEqual(
                store.get_task_pattern_summaries({"a": 1}), []
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(
                f"get_task_pattern_summaries() raised unexpectedly: {exc}"
            )

    def test_returns_a_new_list_each_call(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", task_id="task-a"))
        self.assertIsNot(
            store.get_task_pattern_summaries("task-a"),
            store.get_task_pattern_summaries("task-a"),
        )

    def test_mutating_returned_list_does_not_affect_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", task_id="task-a")
        store.add_pattern(pattern)
        summaries = store.get_task_pattern_summaries("task-a")
        summaries.append({"pattern_id": "fake"})
        summaries[0]["pattern_id"] = "changed"
        self.assertEqual(store.count(), 1)
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertEqual(
            store.get_task_pattern_summaries("task-a"),
            [pattern.get_summary()],
        )

    def test_does_not_modify_stored_patterns_or_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", task_id="task-a")
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_task_pattern_summaries("task-a")
        store.get_task_pattern_summaries("no-such-task")
        store.get_task_pattern_summaries(None)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 20. get_opportunity_pattern_summaries()
# ----------------------------------------------------------------------
class TestGetOpportunityPatternSummaries(unittest.TestCase):
    def test_matching_opportunity_summaries(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        store.add_pattern(pattern)
        summaries = store.get_opportunity_pattern_summaries("opp-a")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0], pattern.get_summary())

    def test_no_matching_opportunity_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertEqual(
            store.get_opportunity_pattern_summaries("opp-does-not-exist"), []
        )

    def test_empty_store_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_opportunity_pattern_summaries("opp-a"), [])

    def test_multiple_patterns_for_same_opportunity(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        p2 = _make_pattern(pattern_id="p-2", opportunity_id="opp-a")
        other = _make_pattern(pattern_id="p-3", opportunity_id="opp-b")
        store.add_pattern(p1)
        store.add_pattern(p2)
        store.add_pattern(other)
        summaries = store.get_opportunity_pattern_summaries("opp-a")
        self.assertEqual(len(summaries), 2)
        self.assertIn(p1.get_summary(), summaries)
        self.assertIn(p2.get_summary(), summaries)
        self.assertNotIn(other.get_summary(), summaries)

    def test_preserves_insertion_order(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-3", opportunity_id="opp-a"))
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-b"))
        store.add_pattern(_make_pattern(pattern_id="p-2", opportunity_id="opp-a"))
        summaries = store.get_opportunity_pattern_summaries("opp-a")
        self.assertEqual(
            [s["pattern_id"] for s in summaries], ["p-3", "p-2"]
        )

    def test_summary_values_match_the_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            opportunity_id="opp-a",
            total_records=10,
            successful_records=8,
            failed_records=2,
            success_rate=0.8,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        summaries = store.get_opportunity_pattern_summaries("opp-a")
        self.assertEqual(summaries[0], {
            "pattern_id": "p-1",
            "task_id": "task-a",
            "opportunity_id": "opp-a",
            "total_records": 10,
            "successful_records": 8,
            "failed_records": 2,
            "success_rate": 0.8,
            "reliability": 0.8,
        })

    def test_empty_string_opportunity_id_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertEqual(store.get_opportunity_pattern_summaries(""), [])

    def test_none_opportunity_id_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertEqual(store.get_opportunity_pattern_summaries(None), [])

    def test_unusual_opportunity_id_never_raises(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        try:
            self.assertEqual(store.get_opportunity_pattern_summaries(123), [])
            self.assertEqual(
                store.get_opportunity_pattern_summaries(["opp-a"]), []
            )
            self.assertEqual(
                store.get_opportunity_pattern_summaries({"a": 1}), []
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(
                f"get_opportunity_pattern_summaries() raised unexpectedly: {exc}"
            )

    def test_returns_a_new_list_each_call(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", opportunity_id="opp-a"))
        self.assertIsNot(
            store.get_opportunity_pattern_summaries("opp-a"),
            store.get_opportunity_pattern_summaries("opp-a"),
        )

    def test_mutating_returned_list_does_not_affect_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        store.add_pattern(pattern)
        summaries = store.get_opportunity_pattern_summaries("opp-a")
        summaries.append({"pattern_id": "fake"})
        summaries[0]["pattern_id"] = "changed"
        self.assertEqual(store.count(), 1)
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertEqual(
            store.get_opportunity_pattern_summaries("opp-a"),
            [pattern.get_summary()],
        )

    def test_does_not_modify_stored_patterns_or_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_opportunity_pattern_summaries("opp-a")
        store.get_opportunity_pattern_summaries("no-such-opportunity")
        store.get_opportunity_pattern_summaries(None)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 21. get_latest_task_pattern_summary()
# ----------------------------------------------------------------------
class TestGetLatestTaskPatternSummary(unittest.TestCase):
    def test_no_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_latest_task_pattern_summary("task-a"))

    def test_latest_matching_task_pattern_returns_its_summary(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", task_id="task-a")
        p2 = _make_pattern(pattern_id="p-2", task_id="task-a")
        store.add_pattern(p1)
        store.add_pattern(p2)
        self.assertEqual(
            store.get_latest_task_pattern_summary("task-a"), p2.get_summary()
        )

    def test_summary_contains_expected_task_id_and_pattern_id(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", task_id="task-a")
        store.add_pattern(pattern)
        summary = store.get_latest_task_pattern_summary("task-a")
        self.assertEqual(summary["task_id"], "task-a")
        self.assertEqual(summary["pattern_id"], "p-1")

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", task_id="task-a")
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_latest_task_pattern_summary("task-a")
        store.get_latest_task_pattern_summary("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 22. get_latest_opportunity_pattern_summary()
# ----------------------------------------------------------------------
class TestGetLatestOpportunityPatternSummary(unittest.TestCase):
    def test_no_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(
            store.get_latest_opportunity_pattern_summary("opp-a")
        )

    def test_latest_matching_opportunity_pattern_returns_its_summary(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        p2 = _make_pattern(pattern_id="p-2", opportunity_id="opp-a")
        store.add_pattern(p1)
        store.add_pattern(p2)
        self.assertEqual(
            store.get_latest_opportunity_pattern_summary("opp-a"),
            p2.get_summary(),
        )

    def test_summary_contains_expected_opportunity_id_and_pattern_id(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        store.add_pattern(pattern)
        summary = store.get_latest_opportunity_pattern_summary("opp-a")
        self.assertEqual(summary["opportunity_id"], "opp-a")
        self.assertEqual(summary["pattern_id"], "p-1")

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", opportunity_id="opp-a")
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_latest_opportunity_pattern_summary("opp-a")
        store.get_latest_opportunity_pattern_summary("no-such-opportunity")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


# ----------------------------------------------------------------------
# 23. get_best_reliable_task_pattern_summary()
# ----------------------------------------------------------------------
class TestGetBestReliableTaskPatternSummary(unittest.TestCase):
    def test_no_reliable_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        unreliable = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.5
        )
        store.add_pattern(unreliable)
        self.assertIsNone(
            store.get_best_reliable_task_pattern_summary("task-a")
        )

    def test_best_reliable_task_pattern_returns_its_summary(self):
        store = RevenueLearningPatternStore()
        low = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.7
        )
        high = _make_pattern(
            pattern_id="p-2", task_id="task-a", reliability=0.95
        )
        store.add_pattern(low)
        store.add_pattern(high)
        self.assertEqual(
            store.get_best_reliable_task_pattern_summary("task-a"),
            high.get_summary(),
        )

    def test_summary_contains_expected_task_id_and_pattern_id(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        summary = store.get_best_reliable_task_pattern_summary("task-a")
        self.assertEqual(summary["task_id"], "task-a")
        self.assertEqual(summary["pattern_id"], "p-1")

    def test_pattern_below_threshold_is_not_returned(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.6
        )
        store.add_pattern(pattern)
        self.assertIsNone(
            store.get_best_reliable_task_pattern_summary(
                "task-a", min_reliability=0.7
            )
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_best_reliable_task_pattern_summary("task-a")
        store.get_best_reliable_task_pattern_summary("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetBestReliableOpportunityPatternSummary(unittest.TestCase):
    def test_no_reliable_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        unreliable = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.5
        )
        store.add_pattern(unreliable)
        self.assertIsNone(
            store.get_best_reliable_opportunity_pattern_summary("opp-a")
        )

    def test_best_reliable_opportunity_pattern_returns_its_summary(self):
        store = RevenueLearningPatternStore()
        low = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.7
        )
        high = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.95
        )
        store.add_pattern(low)
        store.add_pattern(high)
        self.assertEqual(
            store.get_best_reliable_opportunity_pattern_summary("opp-a"),
            high.get_summary(),
        )

    def test_summary_contains_expected_opportunity_id_and_pattern_id(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        summary = store.get_best_reliable_opportunity_pattern_summary("opp-a")
        self.assertEqual(summary["opportunity_id"], "opp-a")
        self.assertEqual(summary["pattern_id"], "p-1")

    def test_pattern_below_threshold_is_not_returned(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.6
        )
        store.add_pattern(pattern)
        self.assertIsNone(
            store.get_best_reliable_opportunity_pattern_summary(
                "opp-a", min_reliability=0.7
            )
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_best_reliable_opportunity_pattern_summary("opp-a")
        store.get_best_reliable_opportunity_pattern_summary("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestCountReliableForTask(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.count_reliable_for_task("task-a"), 0)

    def test_all_reliable_patterns_are_counted(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.7)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.9)
        )
        self.assertEqual(store.count_reliable_for_task("task-a"), 2)

    def test_patterns_below_threshold_are_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.5)
        )
        self.assertEqual(store.count_reliable_for_task("task-a"), 1)

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-b", reliability=0.9)
        )
        self.assertEqual(store.count_reliable_for_task("task-a"), 1)
        self.assertEqual(store.count_reliable_for_task("task-b"), 1)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.count_reliable_for_task("task-a")
        store.count_reliable_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestCountReliableForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.count_reliable_for_opportunity("opp-a"), 0)

    def test_all_reliable_patterns_are_counted(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.7
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-a", reliability=0.9
            )
        )
        self.assertEqual(store.count_reliable_for_opportunity("opp-a"), 2)

    def test_patterns_below_threshold_are_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-a", reliability=0.5
            )
        )
        self.assertEqual(store.count_reliable_for_opportunity("opp-a"), 1)

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-b", reliability=0.9
            )
        )
        self.assertEqual(store.count_reliable_for_opportunity("opp-a"), 1)
        self.assertEqual(store.count_reliable_for_opportunity("opp-b"), 1)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.count_reliable_for_opportunity("opp-a")
        store.count_reliable_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestHasReliableForTask(unittest.TestCase):
    def test_no_patterns_returns_false(self):
        store = RevenueLearningPatternStore()
        self.assertFalse(store.has_reliable_for_task("task-a"))

    def test_at_least_one_reliable_pattern_returns_true(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        self.assertTrue(store.has_reliable_for_task("task-a"))

    def test_patterns_below_threshold_return_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.5)
        )
        self.assertFalse(store.has_reliable_for_task("task-a"))

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        self.assertTrue(store.has_reliable_for_task("task-a"))
        self.assertFalse(store.has_reliable_for_task("task-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.has_reliable_for_task("task-a")
        store.has_reliable_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestHasReliableForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_false(self):
        store = RevenueLearningPatternStore()
        self.assertFalse(store.has_reliable_for_opportunity("opp-a"))

    def test_at_least_one_reliable_pattern_returns_true(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        self.assertTrue(store.has_reliable_for_opportunity("opp-a"))

    def test_patterns_below_threshold_return_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.5
            )
        )
        self.assertFalse(store.has_reliable_for_opportunity("opp-a"))

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        self.assertTrue(store.has_reliable_for_opportunity("opp-a"))
        self.assertFalse(store.has_reliable_for_opportunity("opp-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.has_reliable_for_opportunity("opp-a")
        store.has_reliable_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetAverageReliabilityForTask(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_average_reliability_for_task("task-a"), 0.0)

    def test_one_pattern_returns_its_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.8)
        )
        self.assertEqual(
            store.get_average_reliability_for_task("task-a"), 0.8
        )

    def test_multiple_patterns_return_the_correct_mean(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.6)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-3", task_id="task-a", reliability=0.3)
        )
        self.assertAlmostEqual(
            store.get_average_reliability_for_task("task-a"), 0.6
        )

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-b", reliability=0.1)
        )
        self.assertEqual(
            store.get_average_reliability_for_task("task-a"), 0.9
        )
        self.assertEqual(
            store.get_average_reliability_for_task("task-b"), 0.1
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_average_reliability_for_task("task-a")
        store.get_average_reliability_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetAverageReliabilityForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_average_reliability_for_opportunity("opp-a"), 0.0
        )

    def test_one_pattern_returns_its_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.8
            )
        )
        self.assertEqual(
            store.get_average_reliability_for_opportunity("opp-a"), 0.8
        )

    def test_multiple_patterns_return_the_correct_mean(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.6
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-a", reliability=0.9
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3", opportunity_id="opp-a", reliability=0.3
            )
        )
        self.assertAlmostEqual(
            store.get_average_reliability_for_opportunity("opp-a"), 0.6
        )

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-b", reliability=0.1
            )
        )
        self.assertEqual(
            store.get_average_reliability_for_opportunity("opp-a"), 0.9
        )
        self.assertEqual(
            store.get_average_reliability_for_opportunity("opp-b"), 0.1
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_average_reliability_for_opportunity("opp-a")
        store.get_average_reliability_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetMaxReliabilityForTask(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_max_reliability_for_task("task-a"), 0.0)

    def test_one_pattern_returns_its_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.8)
        )
        self.assertEqual(store.get_max_reliability_for_task("task-a"), 0.8)

    def test_multiple_patterns_return_the_highest_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.6)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-3", task_id="task-a", reliability=0.3)
        )
        self.assertEqual(store.get_max_reliability_for_task("task-a"), 0.9)

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-b", reliability=0.1)
        )
        self.assertEqual(store.get_max_reliability_for_task("task-a"), 0.9)
        self.assertEqual(store.get_max_reliability_for_task("task-b"), 0.1)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_max_reliability_for_task("task-a")
        store.get_max_reliability_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetMaxReliabilityForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_max_reliability_for_opportunity("opp-a"), 0.0
        )

    def test_one_pattern_returns_its_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.8
            )
        )
        self.assertEqual(
            store.get_max_reliability_for_opportunity("opp-a"), 0.8
        )

    def test_multiple_patterns_return_the_highest_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.6
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-a", reliability=0.9
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3", opportunity_id="opp-a", reliability=0.3
            )
        )
        self.assertEqual(
            store.get_max_reliability_for_opportunity("opp-a"), 0.9
        )

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-b", reliability=0.1
            )
        )
        self.assertEqual(
            store.get_max_reliability_for_opportunity("opp-a"), 0.9
        )
        self.assertEqual(
            store.get_max_reliability_for_opportunity("opp-b"), 0.1
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_max_reliability_for_opportunity("opp-a")
        store.get_max_reliability_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetTaskReliabilitySummary(unittest.TestCase):
    def test_no_patterns_returns_correct_empty_summary(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_task_reliability_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 0,
                "average_reliability": 0.0,
                "highest_reliability": 0.0,
            },
        )

    def test_one_pattern_returns_correct_values(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.8)
        )
        self.assertEqual(
            store.get_task_reliability_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "average_reliability": 0.8,
                "highest_reliability": 0.8,
            },
        )

    def test_multiple_patterns_return_correct_count_average_and_highest(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.6)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-3", task_id="task-a", reliability=0.3)
        )
        summary = store.get_task_reliability_summary("task-a")
        self.assertEqual(summary["task_id"], "task-a")
        self.assertEqual(summary["pattern_count"], 3)
        self.assertAlmostEqual(summary["average_reliability"], 0.6)
        self.assertEqual(summary["highest_reliability"], 0.9)

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-b", reliability=0.1)
        )
        self.assertEqual(
            store.get_task_reliability_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "average_reliability": 0.9,
                "highest_reliability": 0.9,
            },
        )
        self.assertEqual(
            store.get_task_reliability_summary("task-b"),
            {
                "task_id": "task-b",
                "pattern_count": 1,
                "average_reliability": 0.1,
                "highest_reliability": 0.1,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_task_reliability_summary("task-a")
        store.get_task_reliability_summary("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetOpportunityReliabilitySummary(unittest.TestCase):
    def test_no_patterns_returns_correct_empty_summary(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_opportunity_reliability_summary("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 0,
                "average_reliability": 0.0,
                "highest_reliability": 0.0,
            },
        )

    def test_one_pattern_returns_correct_values(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.8)
        )
        self.assertEqual(
            store.get_opportunity_reliability_summary("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "average_reliability": 0.8,
                "highest_reliability": 0.8,
            },
        )

    def test_multiple_patterns_return_correct_count_average_and_highest(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.6)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", opportunity_id="opp-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-3", opportunity_id="opp-a", reliability=0.3)
        )
        summary = store.get_opportunity_reliability_summary("opp-a")
        self.assertEqual(summary["opportunity_id"], "opp-a")
        self.assertEqual(summary["pattern_count"], 3)
        self.assertAlmostEqual(summary["average_reliability"], 0.6)
        self.assertEqual(summary["highest_reliability"], 0.9)

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", opportunity_id="opp-b", reliability=0.1)
        )
        self.assertEqual(
            store.get_opportunity_reliability_summary("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "average_reliability": 0.9,
                "highest_reliability": 0.9,
            },
        )
        self.assertEqual(
            store.get_opportunity_reliability_summary("opp-b"),
            {
                "opportunity_id": "opp-b",
                "pattern_count": 1,
                "average_reliability": 0.1,
                "highest_reliability": 0.1,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_opportunity_reliability_summary("opp-a")
        store.get_opportunity_reliability_summary("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestIsTaskReliable(unittest.TestCase):
    def test_no_patterns_returns_false(self):
        store = RevenueLearningPatternStore()
        self.assertFalse(store.is_task_reliable("task-a"))

    def test_a_reliable_pattern_returns_true(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        self.assertTrue(store.is_task_reliable("task-a"))

    def test_patterns_below_threshold_return_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.5)
        )
        self.assertFalse(store.is_task_reliable("task-a"))

    def test_multiple_patterns_return_true_when_one_meets_threshold(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.2)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.4)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-3", task_id="task-a", reliability=0.9)
        )
        self.assertTrue(store.is_task_reliable("task-a"))

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        self.assertTrue(store.is_task_reliable("task-a"))
        self.assertFalse(store.is_task_reliable("task-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.is_task_reliable("task-a")
        store.is_task_reliable("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestIsOpportunityReliable(unittest.TestCase):
    def test_no_patterns_returns_false(self):
        store = RevenueLearningPatternStore()
        self.assertFalse(store.is_opportunity_reliable("opp-a"))

    def test_a_reliable_pattern_returns_true(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.9)
        )
        self.assertTrue(store.is_opportunity_reliable("opp-a"))

    def test_patterns_below_threshold_return_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.5)
        )
        self.assertFalse(store.is_opportunity_reliable("opp-a"))

    def test_multiple_patterns_return_true_when_one_meets_threshold(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.2)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", opportunity_id="opp-a", reliability=0.4)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-3", opportunity_id="opp-a", reliability=0.9)
        )
        self.assertTrue(store.is_opportunity_reliable("opp-a"))

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.9)
        )
        self.assertTrue(store.is_opportunity_reliable("opp-a"))
        self.assertFalse(store.is_opportunity_reliable("opp-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.is_opportunity_reliable("opp-a")
        store.is_opportunity_reliable("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetTaskReliabilityStatus(unittest.TestCase):
    def test_no_patterns_returns_correct_status(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_task_reliability_status("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 0,
                "highest_reliability": 0.0,
                "is_reliable": False,
            },
        )

    def test_one_reliable_pattern_returns_correct_values(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.8)
        )
        self.assertEqual(
            store.get_task_reliability_status("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "highest_reliability": 0.8,
                "is_reliable": True,
            },
        )

    def test_patterns_below_threshold_return_is_reliable_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.5)
        )
        status = store.get_task_reliability_status("task-a")
        self.assertFalse(status["is_reliable"])

    def test_multiple_patterns_correctly_calculate_highest_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.6)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-3", task_id="task-a", reliability=0.3)
        )
        status = store.get_task_reliability_status("task-a")
        self.assertEqual(status["task_id"], "task-a")
        self.assertEqual(status["pattern_count"], 3)
        self.assertEqual(status["highest_reliability"], 0.9)
        self.assertTrue(status["is_reliable"])

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-b", reliability=0.1)
        )
        self.assertEqual(
            store.get_task_reliability_status("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "highest_reliability": 0.9,
                "is_reliable": True,
            },
        )
        self.assertEqual(
            store.get_task_reliability_status("task-b"),
            {
                "task_id": "task-b",
                "pattern_count": 1,
                "highest_reliability": 0.1,
                "is_reliable": False,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_task_reliability_status("task-a")
        store.get_task_reliability_status("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetOpportunityReliabilityStatus(unittest.TestCase):
    def test_no_patterns_returns_correct_status(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_opportunity_reliability_status("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 0,
                "highest_reliability": 0.0,
                "is_reliable": False,
            },
        )

    def test_one_reliable_pattern_returns_correct_values(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.8)
        )
        self.assertEqual(
            store.get_opportunity_reliability_status("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "highest_reliability": 0.8,
                "is_reliable": True,
            },
        )

    def test_patterns_below_threshold_return_is_reliable_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.5)
        )
        status = store.get_opportunity_reliability_status("opp-a")
        self.assertFalse(status["is_reliable"])

    def test_multiple_patterns_correctly_calculate_highest_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.6)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", opportunity_id="opp-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-3", opportunity_id="opp-a", reliability=0.3)
        )
        status = store.get_opportunity_reliability_status("opp-a")
        self.assertEqual(status["opportunity_id"], "opp-a")
        self.assertEqual(status["pattern_count"], 3)
        self.assertEqual(status["highest_reliability"], 0.9)
        self.assertTrue(status["is_reliable"])

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", opportunity_id="opp-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", opportunity_id="opp-b", reliability=0.1)
        )
        self.assertEqual(
            store.get_opportunity_reliability_status("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "highest_reliability": 0.9,
                "is_reliable": True,
            },
        )
        self.assertEqual(
            store.get_opportunity_reliability_status("opp-b"),
            {
                "opportunity_id": "opp-b",
                "pattern_count": 1,
                "highest_reliability": 0.1,
                "is_reliable": False,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_opportunity_reliability_status("opp-a")
        store.get_opportunity_reliability_status("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestCountSuccessfulForTask(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.count_successful_for_task("task-a"), 0)

    def test_one_successful_pattern_returns_one(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertEqual(store.count_successful_for_task("task-a"), 1)

    def test_multiple_successful_patterns_are_counted_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=2,
                successful_records=1,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                task_id="task-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertEqual(store.count_successful_for_task("task-a"), 2)

    def test_patterns_with_zero_successful_records_are_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertEqual(store.count_successful_for_task("task-a"), 0)

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertEqual(store.count_successful_for_task("task-a"), 1)
        self.assertEqual(store.count_successful_for_task("task-b"), 0)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.count_successful_for_task("task-a")
        store.count_successful_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestCountSuccessfulForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.count_successful_for_opportunity("opp-a"), 0)

    def test_one_successful_pattern_returns_one(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertEqual(store.count_successful_for_opportunity("opp-a"), 1)

    def test_multiple_successful_patterns_are_counted_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=1,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertEqual(store.count_successful_for_opportunity("opp-a"), 2)

    def test_patterns_with_zero_successful_records_are_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertEqual(store.count_successful_for_opportunity("opp-a"), 0)

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-b",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertEqual(store.count_successful_for_opportunity("opp-a"), 1)
        self.assertEqual(store.count_successful_for_opportunity("opp-b"), 0)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.count_successful_for_opportunity("opp-a")
        store.count_successful_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestCountFailedForTask(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.count_failed_for_task("task-a"), 0)

    def test_one_failed_pattern_returns_one(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertEqual(store.count_failed_for_task("task-a"), 1)

    def test_multiple_failed_patterns_are_counted_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=2,
                successful_records=1,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                task_id="task-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertEqual(store.count_failed_for_task("task-a"), 2)

    def test_patterns_with_zero_failed_records_are_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertEqual(store.count_failed_for_task("task-a"), 0)

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertEqual(store.count_failed_for_task("task-a"), 1)
        self.assertEqual(store.count_failed_for_task("task-b"), 0)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.count_failed_for_task("task-a")
        store.count_failed_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestCountFailedForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.count_failed_for_opportunity("opp-a"), 0)

    def test_one_failed_pattern_returns_one(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertEqual(store.count_failed_for_opportunity("opp-a"), 1)

    def test_multiple_failed_patterns_are_counted_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=1,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertEqual(store.count_failed_for_opportunity("opp-a"), 2)

    def test_patterns_with_zero_failed_records_are_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertEqual(store.count_failed_for_opportunity("opp-a"), 0)

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-b",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertEqual(store.count_failed_for_opportunity("opp-a"), 1)
        self.assertEqual(store.count_failed_for_opportunity("opp-b"), 0)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.count_failed_for_opportunity("opp-a")
        store.count_failed_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetTaskOutcomeSummary(unittest.TestCase):
    def test_no_patterns_returns_correct_empty_summary(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_task_outcome_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 0,
                "successful_pattern_count": 0,
                "failed_pattern_count": 0,
                "total_successful_records": 0,
                "total_failed_records": 0,
            },
        )

    def test_one_successful_pattern_returns_correct_values(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_task_outcome_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "successful_pattern_count": 1,
                "failed_pattern_count": 0,
                "total_successful_records": 4,
                "total_failed_records": 0,
            },
        )

    def test_one_failed_pattern_returns_correct_values(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_task_outcome_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "successful_pattern_count": 0,
                "failed_pattern_count": 1,
                "total_successful_records": 0,
                "total_failed_records": 3,
            },
        )

    def test_multiple_patterns_aggregate_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                task_id="task-a",
                total_records=5,
                successful_records=5,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_task_outcome_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 3,
                "successful_pattern_count": 2,
                "failed_pattern_count": 2,
                "total_successful_records": 8,
                "total_failed_records": 3,
            },
        )

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertEqual(
            store.get_task_outcome_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "successful_pattern_count": 1,
                "failed_pattern_count": 1,
                "total_successful_records": 3,
                "total_failed_records": 1,
            },
        )
        self.assertEqual(
            store.get_task_outcome_summary("task-b"),
            {
                "task_id": "task-b",
                "pattern_count": 1,
                "successful_pattern_count": 0,
                "failed_pattern_count": 1,
                "total_successful_records": 0,
                "total_failed_records": 2,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_task_outcome_summary("task-a")
        store.get_task_outcome_summary("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetOpportunityOutcomeSummary(unittest.TestCase):
    def test_no_patterns_returns_correct_empty_summary(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_opportunity_outcome_summary("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 0,
                "successful_pattern_count": 0,
                "failed_pattern_count": 0,
                "total_successful_records": 0,
                "total_failed_records": 0,
            },
        )

    def test_one_successful_pattern_returns_correct_values(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_opportunity_outcome_summary("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "successful_pattern_count": 1,
                "failed_pattern_count": 0,
                "total_successful_records": 4,
                "total_failed_records": 0,
            },
        )

    def test_one_failed_pattern_returns_correct_values(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_opportunity_outcome_summary("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "successful_pattern_count": 0,
                "failed_pattern_count": 1,
                "total_successful_records": 0,
                "total_failed_records": 3,
            },
        )

    def test_multiple_patterns_aggregate_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                opportunity_id="opp-a",
                total_records=5,
                successful_records=5,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_opportunity_outcome_summary("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 3,
                "successful_pattern_count": 2,
                "failed_pattern_count": 2,
                "total_successful_records": 8,
                "total_failed_records": 3,
            },
        )

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-b",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertEqual(
            store.get_opportunity_outcome_summary("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "successful_pattern_count": 1,
                "failed_pattern_count": 1,
                "total_successful_records": 3,
                "total_failed_records": 1,
            },
        )
        self.assertEqual(
            store.get_opportunity_outcome_summary("opp-b"),
            {
                "opportunity_id": "opp-b",
                "pattern_count": 1,
                "successful_pattern_count": 0,
                "failed_pattern_count": 1,
                "total_successful_records": 0,
                "total_failed_records": 2,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_opportunity_outcome_summary("opp-a")
        store.get_opportunity_outcome_summary("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestHasSuccessfulPatternForTask(unittest.TestCase):
    def test_no_patterns_returns_false(self):
        store = RevenueLearningPatternStore()
        self.assertFalse(store.has_successful_pattern_for_task("task-a"))

    def test_a_successful_pattern_returns_true(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertTrue(store.has_successful_pattern_for_task("task-a"))

    def test_patterns_with_zero_successful_records_return_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertFalse(store.has_successful_pattern_for_task("task-a"))

    def test_multiple_patterns_return_true_when_one_is_successful(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                task_id="task-a",
                total_records=4,
                successful_records=1,
                failed_records=3,
            )
        )
        self.assertTrue(store.has_successful_pattern_for_task("task-a"))

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertTrue(store.has_successful_pattern_for_task("task-a"))
        self.assertFalse(store.has_successful_pattern_for_task("task-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.has_successful_pattern_for_task("task-a")
        store.has_successful_pattern_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestHasSuccessfulPatternForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_false(self):
        store = RevenueLearningPatternStore()
        self.assertFalse(store.has_successful_pattern_for_opportunity("opp-a"))

    def test_a_successful_pattern_returns_true(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertTrue(store.has_successful_pattern_for_opportunity("opp-a"))

    def test_patterns_with_zero_successful_records_return_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertFalse(store.has_successful_pattern_for_opportunity("opp-a"))

    def test_multiple_patterns_return_true_when_one_is_successful(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=1,
                failed_records=3,
            )
        )
        self.assertTrue(store.has_successful_pattern_for_opportunity("opp-a"))

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-b",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertTrue(store.has_successful_pattern_for_opportunity("opp-a"))
        self.assertFalse(store.has_successful_pattern_for_opportunity("opp-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.has_successful_pattern_for_opportunity("opp-a")
        store.has_successful_pattern_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestHasFailedPatternForTask(unittest.TestCase):
    def test_no_patterns_returns_false(self):
        store = RevenueLearningPatternStore()
        self.assertFalse(store.has_failed_pattern_for_task("task-a"))

    def test_a_failed_pattern_returns_true(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertTrue(store.has_failed_pattern_for_task("task-a"))

    def test_patterns_with_zero_failed_records_return_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertFalse(store.has_failed_pattern_for_task("task-a"))

    def test_multiple_patterns_return_true_when_one_has_failures(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertTrue(store.has_failed_pattern_for_task("task-a"))

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertTrue(store.has_failed_pattern_for_task("task-a"))
        self.assertFalse(store.has_failed_pattern_for_task("task-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.has_failed_pattern_for_task("task-a")
        store.has_failed_pattern_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestHasFailedPatternForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_false(self):
        store = RevenueLearningPatternStore()
        self.assertFalse(store.has_failed_pattern_for_opportunity("opp-a"))

    def test_a_failed_pattern_returns_true(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertTrue(store.has_failed_pattern_for_opportunity("opp-a"))

    def test_patterns_with_zero_failed_records_return_false(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertFalse(store.has_failed_pattern_for_opportunity("opp-a"))

    def test_multiple_patterns_return_true_when_one_has_failures(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertTrue(store.has_failed_pattern_for_opportunity("opp-a"))

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-b",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertTrue(store.has_failed_pattern_for_opportunity("opp-a"))
        self.assertFalse(store.has_failed_pattern_for_opportunity("opp-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.has_failed_pattern_for_opportunity("opp-a")
        store.has_failed_pattern_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetTaskLearningStatus(unittest.TestCase):
    def test_no_patterns_returns_no_data(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_task_learning_status("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 0,
                "has_success": False,
                "has_failure": False,
                "status": "NO_DATA",
            },
        )

    def test_only_successful_patterns_return_success(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_task_learning_status("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "has_success": True,
                "has_failure": False,
                "status": "SUCCESS",
            },
        )

    def test_only_failed_patterns_return_failed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_task_learning_status("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "has_success": False,
                "has_failure": True,
                "status": "FAILED",
            },
        )

    def test_both_successful_and_failed_patterns_return_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_task_learning_status("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 2,
                "has_success": True,
                "has_failure": True,
                "status": "MIXED",
            },
        )

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_task_learning_status("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "has_success": True,
                "has_failure": False,
                "status": "SUCCESS",
            },
        )
        self.assertEqual(
            store.get_task_learning_status("task-b"),
            {
                "task_id": "task-b",
                "pattern_count": 1,
                "has_success": False,
                "has_failure": True,
                "status": "FAILED",
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_task_learning_status("task-a")
        store.get_task_learning_status("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetOpportunityLearningStatus(unittest.TestCase):
    def test_no_patterns_returns_no_data(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_opportunity_learning_status("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 0,
                "has_success": False,
                "has_failure": False,
                "status": "NO_DATA",
            },
        )

    def test_only_successful_patterns_return_success(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_opportunity_learning_status("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "has_success": True,
                "has_failure": False,
                "status": "SUCCESS",
            },
        )

    def test_only_failed_patterns_return_failed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_opportunity_learning_status("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "has_success": False,
                "has_failure": True,
                "status": "FAILED",
            },
        )

    def test_both_successful_and_failed_patterns_return_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_opportunity_learning_status("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 2,
                "has_success": True,
                "has_failure": True,
                "status": "MIXED",
            },
        )

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-b",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_opportunity_learning_status("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "has_success": True,
                "has_failure": False,
                "status": "SUCCESS",
            },
        )
        self.assertEqual(
            store.get_opportunity_learning_status("opp-b"),
            {
                "opportunity_id": "opp-b",
                "pattern_count": 1,
                "has_success": False,
                "has_failure": True,
                "status": "FAILED",
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_opportunity_learning_status("opp-a")
        store.get_opportunity_learning_status("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetLatestSuccessfulForTask(unittest.TestCase):
    def test_no_patterns_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_latest_successful_for_task("task-a"))

    def test_patterns_without_successful_records_are_ignored(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertIsNone(store.get_latest_successful_for_task("task-a"))

    def test_one_successful_pattern_returns_that_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        store.add_pattern(pattern)
        self.assertIs(store.get_latest_successful_for_task("task-a"), pattern)

    def test_multiple_successful_patterns_return_the_latest_one(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        latest = _make_pattern(
            pattern_id="p-3",
            task_id="task-a",
            total_records=3,
            successful_records=3,
            failed_records=0,
        )
        store.add_pattern(latest)
        self.assertIs(store.get_latest_successful_for_task("task-a"), latest)

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        pattern_a = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        store.add_pattern(pattern_a)
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertIs(store.get_latest_successful_for_task("task-a"), pattern_a)
        self.assertIsNone(store.get_latest_successful_for_task("task-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_latest_successful_for_task("task-a")
        store.get_latest_successful_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetLatestSuccessfulForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_latest_successful_for_opportunity("opp-a"))

    def test_patterns_without_successful_records_are_ignored(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertIsNone(store.get_latest_successful_for_opportunity("opp-a"))

    def test_one_successful_pattern_returns_that_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        store.add_pattern(pattern)
        self.assertIs(
            store.get_latest_successful_for_opportunity("opp-a"), pattern
        )

    def test_multiple_successful_patterns_return_the_latest_one(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        latest = _make_pattern(
            pattern_id="p-3",
            opportunity_id="opp-a",
            total_records=3,
            successful_records=3,
            failed_records=0,
        )
        store.add_pattern(latest)
        self.assertIs(
            store.get_latest_successful_for_opportunity("opp-a"), latest
        )

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        pattern_a = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        store.add_pattern(pattern_a)
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-b",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertIs(
            store.get_latest_successful_for_opportunity("opp-a"), pattern_a
        )
        self.assertIsNone(store.get_latest_successful_for_opportunity("opp-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_latest_successful_for_opportunity("opp-a")
        store.get_latest_successful_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetLatestFailedForTask(unittest.TestCase):
    def test_no_patterns_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_latest_failed_for_task("task-a"))

    def test_patterns_without_failed_records_are_ignored(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertIsNone(store.get_latest_failed_for_task("task-a"))

    def test_one_failed_pattern_returns_that_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=0,
            failed_records=4,
        )
        store.add_pattern(pattern)
        self.assertIs(store.get_latest_failed_for_task("task-a"), pattern)

    def test_multiple_failed_patterns_return_the_latest_one(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        latest = _make_pattern(
            pattern_id="p-3",
            task_id="task-a",
            total_records=3,
            successful_records=0,
            failed_records=3,
        )
        store.add_pattern(latest)
        self.assertIs(store.get_latest_failed_for_task("task-a"), latest)

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        pattern_a = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=0,
            failed_records=4,
        )
        store.add_pattern(pattern_a)
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertIs(store.get_latest_failed_for_task("task-a"), pattern_a)
        self.assertIsNone(store.get_latest_failed_for_task("task-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=0,
            failed_records=4,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_latest_failed_for_task("task-a")
        store.get_latest_failed_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetLatestFailedForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_latest_failed_for_opportunity("opp-a"))

    def test_patterns_without_failed_records_are_ignored(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertIsNone(store.get_latest_failed_for_opportunity("opp-a"))

    def test_one_failed_pattern_returns_that_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=0,
            failed_records=4,
        )
        store.add_pattern(pattern)
        self.assertIs(
            store.get_latest_failed_for_opportunity("opp-a"), pattern
        )

    def test_multiple_failed_patterns_return_the_latest_one(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        latest = _make_pattern(
            pattern_id="p-3",
            opportunity_id="opp-a",
            total_records=3,
            successful_records=0,
            failed_records=3,
        )
        store.add_pattern(latest)
        self.assertIs(
            store.get_latest_failed_for_opportunity("opp-a"), latest
        )

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        pattern_a = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=0,
            failed_records=4,
        )
        store.add_pattern(pattern_a)
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-b",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertIs(
            store.get_latest_failed_for_opportunity("opp-a"), pattern_a
        )
        self.assertIsNone(store.get_latest_failed_for_opportunity("opp-b"))

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=0,
            failed_records=4,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_latest_failed_for_opportunity("opp-a")
        store.get_latest_failed_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetSuccessRateForTask(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_success_rate_for_task("task-a"), 0.0)

    def test_only_successful_records_returns_one(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(store.get_success_rate_for_task("task-a"), 1.0)

    def test_only_failed_records_returns_zero(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        self.assertEqual(store.get_success_rate_for_task("task-a"), 0.0)

    def test_mixed_records_calculate_the_correct_rate(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertEqual(store.get_success_rate_for_task("task-a"), 0.75)

    def test_multiple_patterns_are_aggregated_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=6,
                successful_records=1,
                failed_records=5,
            )
        )
        # successful: 3 + 1 = 4, failed: 1 + 5 = 6, total: 10
        self.assertEqual(store.get_success_rate_for_task("task-a"), 0.4)

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertEqual(store.get_success_rate_for_task("task-a"), 1.0)
        self.assertEqual(store.get_success_rate_for_task("task-b"), 0.0)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_success_rate_for_task("task-a")
        store.get_success_rate_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetSuccessRateForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_success_rate_for_opportunity("opp-a"), 0.0)

    def test_only_successful_records_returns_one(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(store.get_success_rate_for_opportunity("opp-a"), 1.0)

    def test_only_failed_records_returns_zero(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        self.assertEqual(store.get_success_rate_for_opportunity("opp-a"), 0.0)

    def test_mixed_records_calculate_the_correct_rate(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertEqual(store.get_success_rate_for_opportunity("opp-a"), 0.75)

    def test_multiple_patterns_are_aggregated_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=6,
                successful_records=1,
                failed_records=5,
            )
        )
        # successful: 3 + 1 = 4, failed: 1 + 5 = 6, total: 10
        self.assertEqual(store.get_success_rate_for_opportunity("opp-a"), 0.4)

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-b",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertEqual(store.get_success_rate_for_opportunity("opp-a"), 1.0)
        self.assertEqual(store.get_success_rate_for_opportunity("opp-b"), 0.0)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_success_rate_for_opportunity("opp-a")
        store.get_success_rate_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetTotalRecordsForTask(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_total_records_for_task("task-a"), 0)

    def test_successful_records_are_counted(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(store.get_total_records_for_task("task-a"), 4)

    def test_failed_records_are_counted(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(store.get_total_records_for_task("task-a"), 3)

    def test_multiple_patterns_are_aggregated_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=6,
                successful_records=1,
                failed_records=5,
            )
        )
        # 3 + 1 + 1 + 5 = 10
        self.assertEqual(store.get_total_records_for_task("task-a"), 10)

    def test_mixed_pattern_records_are_counted(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=5,
                successful_records=3,
                failed_records=2,
            )
        )
        self.assertEqual(store.get_total_records_for_task("task-a"), 5)

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=2,
                successful_records=1,
                failed_records=1,
            )
        )
        self.assertEqual(store.get_total_records_for_task("task-a"), 4)
        self.assertEqual(store.get_total_records_for_task("task-b"), 2)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_total_records_for_task("task-a")
        store.get_total_records_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetTotalRecordsForOpportunity(unittest.TestCase):
    def test_no_patterns_returns_zero(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_total_records_for_opportunity("opp-a"), 0)

    def test_successful_records_are_counted(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(store.get_total_records_for_opportunity("opp-a"), 4)

    def test_failed_records_are_counted(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(store.get_total_records_for_opportunity("opp-a"), 3)

    def test_multiple_patterns_are_aggregated_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=6,
                successful_records=1,
                failed_records=5,
            )
        )
        # 3 + 1 + 1 + 5 = 10
        self.assertEqual(store.get_total_records_for_opportunity("opp-a"), 10)

    def test_mixed_pattern_records_are_counted(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=5,
                successful_records=3,
                failed_records=2,
            )
        )
        self.assertEqual(store.get_total_records_for_opportunity("opp-a"), 5)

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-b",
                total_records=2,
                successful_records=1,
                failed_records=1,
            )
        )
        self.assertEqual(store.get_total_records_for_opportunity("opp-a"), 4)
        self.assertEqual(store.get_total_records_for_opportunity("opp-b"), 2)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_total_records_for_opportunity("opp-a")
        store.get_total_records_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetTaskLearningSummary(unittest.TestCase):
    def test_no_patterns_returns_correct_empty_summary(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_task_learning_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 0,
                "total_records": 0,
                "success_rate": 0.0,
            },
        )

    def test_successful_records_produce_correct_values(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_task_learning_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "total_records": 4,
                "success_rate": 1.0,
            },
        )

    def test_failed_records_produce_correct_values(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_task_learning_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "total_records": 3,
                "success_rate": 0.0,
            },
        )

    def test_multiple_patterns_are_aggregated_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=6,
                successful_records=1,
                failed_records=5,
            )
        )
        # successful: 3 + 1 = 4, failed: 1 + 5 = 6, total: 10
        self.assertEqual(
            store.get_task_learning_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 2,
                "total_records": 10,
                "success_rate": 0.4,
            },
        )

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=2,
                successful_records=0,
                failed_records=2,
            )
        )
        self.assertEqual(
            store.get_task_learning_summary("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "total_records": 4,
                "success_rate": 1.0,
            },
        )
        self.assertEqual(
            store.get_task_learning_summary("task-b"),
            {
                "task_id": "task-b",
                "pattern_count": 1,
                "total_records": 2,
                "success_rate": 0.0,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_task_learning_summary("task-a")
        store.get_task_learning_summary("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetOpportunityLearningSummary(unittest.TestCase):
    def test_no_patterns_returns_correct_empty_summary(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_opportunity_learning_summary("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 0,
                "total_records": 0,
                "success_rate": 0.0,
            },
        )

    def test_one_pattern_produces_correct_values(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_opportunity_learning_summary("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "total_records": 4,
                "success_rate": 1.0,
            },
        )

    def test_multiple_patterns_are_aggregated_correctly(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=6,
                successful_records=1,
                failed_records=5,
            )
        )
        # successful: 3 + 1 = 4, failed: 1 + 5 = 6, total: 10
        self.assertEqual(
            store.get_opportunity_learning_summary("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 2,
                "total_records": 10,
                "success_rate": 0.4,
            },
        )

    def test_correct_aggregate_success_rate_with_failed_only(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        summary = store.get_opportunity_learning_summary("opp-a")
        self.assertEqual(summary["total_records"], 3)
        self.assertEqual(summary["success_rate"], 0.0)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_opportunity_learning_summary("opp-a")
        store.get_opportunity_learning_summary("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetLearningSummaryForPattern(unittest.TestCase):
    def test_existing_pattern_returns_summary(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            success_rate=0.75,
            reliability=0.75,
        )
        store.add_pattern(pattern)
        self.assertIsNotNone(store.get_learning_summary_for_pattern("p-1"))

    def test_missing_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        self.assertIsNone(
            store.get_learning_summary_for_pattern("no-such-pattern")
        )
        self.assertIsNone(
            RevenueLearningPatternStore().get_learning_summary_for_pattern(
                "p-1"
            )
        )

    def test_correct_values(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            success_rate=0.75,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_learning_summary_for_pattern("p-1"),
            {
                "pattern_id": "p-1",
                "total_records": 4,
                "success_rate": 0.75,
                "reliability": 0.8,
                "is_reliable": True,
            },
        )

    def test_correct_values_when_unreliable(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=1,
            failed_records=3,
            success_rate=0.25,
            reliability=0.25,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_learning_summary_for_pattern("p-1"),
            {
                "pattern_id": "p-1",
                "total_records": 4,
                "success_rate": 0.25,
                "reliability": 0.25,
                "is_reliable": False,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            success_rate=0.75,
            reliability=0.75,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_learning_summary_for_pattern("p-1")
        store.get_learning_summary_for_pattern("no-such-pattern")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetReliablePatternSummaryForOpportunity(unittest.TestCase):
    def test_no_patterns(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_reliable_pattern_summary_for_opportunity("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 0,
                "reliable_pattern_count": 0,
                "min_reliability": 0.7,
                "has_reliable_pattern": False,
            },
        )

    def test_patterns_below_the_threshold(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.5
            )
        )
        self.assertEqual(
            store.get_reliable_pattern_summary_for_opportunity("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "reliable_pattern_count": 0,
                "min_reliability": 0.7,
                "has_reliable_pattern": False,
            },
        )

    def test_patterns_meeting_the_threshold(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        self.assertEqual(
            store.get_reliable_pattern_summary_for_opportunity("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 1,
                "reliable_pattern_count": 1,
                "min_reliability": 0.7,
                "has_reliable_pattern": True,
            },
        )

    def test_mixed_reliable_and_unreliable_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-a", reliability=0.3
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3", opportunity_id="opp-a", reliability=0.8
            )
        )
        self.assertEqual(
            store.get_reliable_pattern_summary_for_opportunity("opp-a"),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 3,
                "reliable_pattern_count": 2,
                "min_reliability": 0.7,
                "has_reliable_pattern": True,
            },
        )

    def test_custom_min_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.5
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-a", reliability=0.2
            )
        )
        self.assertEqual(
            store.get_reliable_pattern_summary_for_opportunity(
                "opp-a", min_reliability=0.4
            ),
            {
                "opportunity_id": "opp-a",
                "pattern_count": 2,
                "reliable_pattern_count": 1,
                "min_reliability": 0.4,
                "has_reliable_pattern": True,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_reliable_pattern_summary_for_opportunity("opp-a")
        store.get_reliable_pattern_summary_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetReliablePatternSummaryForTask(unittest.TestCase):
    def test_no_patterns(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_reliable_pattern_summary_for_task("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 0,
                "reliable_pattern_count": 0,
                "min_reliability": 0.7,
                "has_reliable_pattern": False,
            },
        )

    def test_patterns_below_the_threshold(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.5)
        )
        self.assertEqual(
            store.get_reliable_pattern_summary_for_task("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "reliable_pattern_count": 0,
                "min_reliability": 0.7,
                "has_reliable_pattern": False,
            },
        )

    def test_patterns_meeting_the_threshold(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        self.assertEqual(
            store.get_reliable_pattern_summary_for_task("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 1,
                "reliable_pattern_count": 1,
                "min_reliability": 0.7,
                "has_reliable_pattern": True,
            },
        )

    def test_mixed_reliable_and_unreliable_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.3)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-3", task_id="task-a", reliability=0.8)
        )
        self.assertEqual(
            store.get_reliable_pattern_summary_for_task("task-a"),
            {
                "task_id": "task-a",
                "pattern_count": 3,
                "reliable_pattern_count": 2,
                "min_reliability": 0.7,
                "has_reliable_pattern": True,
            },
        )

    def test_custom_min_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.5)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.2)
        )
        self.assertEqual(
            store.get_reliable_pattern_summary_for_task(
                "task-a", min_reliability=0.4
            ),
            {
                "task_id": "task-a",
                "pattern_count": 2,
                "reliable_pattern_count": 1,
                "min_reliability": 0.4,
                "has_reliable_pattern": True,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_reliable_pattern_summary_for_task("task-a")
        store.get_reliable_pattern_summary_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetMostReliableForOpportunity(unittest.TestCase):
    def test_no_matching_patterns_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_most_reliable_for_opportunity("opp-a"))

    def test_one_matching_pattern_returns_that_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.6
        )
        store.add_pattern(pattern)
        self.assertIs(
            store.get_most_reliable_for_opportunity("opp-a"), pattern
        )

    def test_multiple_patterns_highest_reliability_selected(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.4
            )
        )
        best = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(best)
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3", opportunity_id="opp-a", reliability=0.5
            )
        )
        self.assertIs(store.get_most_reliable_for_opportunity("opp-a"), best)

    def test_deterministic_tie_handling(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.8
        )
        second = _make_pattern(
            pattern_id="p-2", opportunity_id="opp-a", reliability=0.8
        )
        store.add_pattern(first)
        store.add_pattern(second)
        # Both share the highest reliability - the earliest stored
        # pattern wins.
        self.assertIs(store.get_most_reliable_for_opportunity("opp-a"), first)

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        pattern_a = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern_a)
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-b", reliability=0.2
            )
        )
        self.assertIs(
            store.get_most_reliable_for_opportunity("opp-a"), pattern_a
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_most_reliable_for_opportunity("opp-a")
        store.get_most_reliable_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetMostReliableForTask(unittest.TestCase):
    def test_no_matching_patterns_returns_none(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_most_reliable_for_task("task-a"))

    def test_one_matching_pattern_returns_that_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.6
        )
        store.add_pattern(pattern)
        self.assertIs(store.get_most_reliable_for_task("task-a"), pattern)

    def test_multiple_patterns_highest_reliability_selected(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.4)
        )
        best = _make_pattern(
            pattern_id="p-2", task_id="task-a", reliability=0.9
        )
        store.add_pattern(best)
        store.add_pattern(
            _make_pattern(pattern_id="p-3", task_id="task-a", reliability=0.5)
        )
        self.assertIs(store.get_most_reliable_for_task("task-a"), best)

    def test_deterministic_tie_handling(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.8
        )
        second = _make_pattern(
            pattern_id="p-2", task_id="task-a", reliability=0.8
        )
        store.add_pattern(first)
        store.add_pattern(second)
        # Both share the highest reliability - the earliest stored
        # pattern wins.
        self.assertIs(store.get_most_reliable_for_task("task-a"), first)

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        pattern_a = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern_a)
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-b", reliability=0.2)
        )
        self.assertIs(store.get_most_reliable_for_task("task-a"), pattern_a)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_most_reliable_for_task("task-a")
        store.get_most_reliable_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetPatternReliabilityReport(unittest.TestCase):
    def test_missing_pattern_returns_none(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1"))
        self.assertIsNone(
            store.get_pattern_reliability_report("no-such-pattern")
        )
        self.assertIsNone(
            RevenueLearningPatternStore().get_pattern_reliability_report(
                "p-1"
            )
        )

    def test_valid_pattern_returns_a_report(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1")
        store.add_pattern(pattern)
        self.assertIsNotNone(store.get_pattern_reliability_report("p-1"))

    def test_correct_reliability_values(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
            success_rate=0.75,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_pattern_reliability_report("p-1"),
            {
                "pattern_id": "p-1",
                "task_id": "task-a",
                "opportunity_id": "opp-a",
                "reliability": 0.8,
                "total_records": 4,
                "successful_records": 3,
                "failed_records": 1,
                "is_reliable": True,
            },
        )

    def test_reliable_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", reliability=0.9))
        report = store.get_pattern_reliability_report("p-1")
        self.assertTrue(report["is_reliable"])

    def test_unreliable_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(_make_pattern(pattern_id="p-1", reliability=0.2))
        report = store.get_pattern_reliability_report("p-1")
        self.assertFalse(report["is_reliable"])

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", reliability=0.9)
        store.add_pattern(pattern)
        before = store.get_all()
        store.get_pattern_reliability_report("p-1")
        store.get_pattern_reliability_report("no-such-pattern")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetPatternReliabilityReportsForTask(unittest.TestCase):
    def test_no_matching_patterns_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_pattern_reliability_reports_for_task("task-a"), []
        )

    def test_one_matching_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.8)
        )
        reports = store.get_pattern_reliability_reports_for_task("task-a")
        self.assertEqual(len(reports), 1)
        self.assertEqual(
            reports[0], store.get_pattern_reliability_report("p-1")
        )

    def test_multiple_matching_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.8)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.3)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-3", task_id="task-b", reliability=0.5)
        )
        reports = store.get_pattern_reliability_reports_for_task("task-a")
        self.assertEqual(len(reports), 2)
        self.assertEqual(
            [r["pattern_id"] for r in reports], ["p-1", "p-2"]
        )

    def test_insertion_order_is_preserved(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(pattern_id="p-2", task_id="task-a", reliability=0.3)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-1", task_id="task-a", reliability=0.9)
        )
        store.add_pattern(
            _make_pattern(pattern_id="p-3", task_id="task-a", reliability=0.5)
        )
        reports = store.get_pattern_reliability_reports_for_task("task-a")
        self.assertEqual(
            [r["pattern_id"] for r in reports], ["p-2", "p-1", "p-3"]
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", task_id="task-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_pattern_reliability_reports_for_task("task-a")
        second_call = store.get_pattern_reliability_reports_for_task("task-a")
        self.assertIsNot(first_call, second_call)
        store.get_pattern_reliability_reports_for_task("no-such-task")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertTrue(pattern.is_valid())


class TestGetPatternReliabilityReportsForOpportunity(unittest.TestCase):
    def test_no_matching_patterns_returns_empty_list(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_pattern_reliability_reports_for_opportunity("opp-a"),
            [],
        )

    def test_one_matching_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.8
            )
        )
        reports = store.get_pattern_reliability_reports_for_opportunity(
            "opp-a"
        )
        self.assertEqual(len(reports), 1)
        self.assertEqual(
            reports[0], store.get_pattern_reliability_report("p-1")
        )

    def test_multiple_matching_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.8
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-a", reliability=0.3
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3", opportunity_id="opp-b", reliability=0.5
            )
        )
        reports = store.get_pattern_reliability_reports_for_opportunity(
            "opp-a"
        )
        self.assertEqual(len(reports), 2)
        self.assertEqual([r["pattern_id"] for r in reports], ["p-1", "p-2"])

    def test_insertion_order_is_preserved(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2", opportunity_id="opp-a", reliability=0.3
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3", opportunity_id="opp-a", reliability=0.5
            )
        )
        reports = store.get_pattern_reliability_reports_for_opportunity(
            "opp-a"
        )
        self.assertEqual(
            [r["pattern_id"] for r in reports], ["p-2", "p-1", "p-3"]
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1", opportunity_id="opp-a", reliability=0.9
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_pattern_reliability_reports_for_opportunity(
            "opp-a"
        )
        second_call = store.get_pattern_reliability_reports_for_opportunity(
            "opp-a"
        )
        self.assertIsNot(first_call, second_call)
        store.get_pattern_reliability_reports_for_opportunity("no-such-opp")
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertTrue(pattern.is_valid())


class TestGetMixedPatterns(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_mixed_patterns(), [])

    def test_only_successful_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(store.get_mixed_patterns(), [])

    def test_only_failed_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        self.assertEqual(store.get_mixed_patterns(), [])

    def test_mixed_patterns(self):
        store = RevenueLearningPatternStore()
        mixed = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(mixed)
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(store.get_mixed_patterns(), [mixed])

    def test_insertion_order_is_preserved(self):
        store = RevenueLearningPatternStore()
        second = _make_pattern(
            pattern_id="p-2",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        first = _make_pattern(
            pattern_id="p-1",
            total_records=6,
            successful_records=1,
            failed_records=5,
        )
        store.add_pattern(second)
        store.add_pattern(first)
        self.assertEqual(store.get_mixed_patterns(), [second, first])

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_mixed_patterns()
        second_call = store.get_mixed_patterns()
        self.assertIsNot(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestCountMixedPatterns(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.count_mixed_patterns(), 0)

    def test_no_mixed_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(store.count_mixed_patterns(), 0)

    def test_one_mixed_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertEqual(store.count_mixed_patterns(), 1)

    def test_multiple_mixed_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                total_records=6,
                successful_records=1,
                failed_records=5,
            )
        )
        self.assertEqual(store.count_mixed_patterns(), 2)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        store.count_mixed_patterns()
        store.count_mixed_patterns()
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetSuccessOnlyPatterns(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_success_only_patterns(), [])

    def test_no_success_only_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(store.get_success_only_patterns(), [])

    def test_one_success_only_pattern(self):
        store = RevenueLearningPatternStore()
        success_only = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        store.add_pattern(success_only)
        self.assertEqual(store.get_success_only_patterns(), [success_only])

    def test_multiple_success_only_patterns(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=2,
            successful_records=2,
            failed_records=0,
        )
        store.add_pattern(first)
        store.add_pattern(second)
        self.assertEqual(store.get_success_only_patterns(), [first, second])

    def test_mixed_and_failed_patterns_are_excluded(self):
        store = RevenueLearningPatternStore()
        success_only = _make_pattern(
            pattern_id="p-2",
            total_records=2,
            successful_records=2,
            failed_records=0,
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(success_only)
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(store.get_success_only_patterns(), [success_only])

    def test_insertion_order_is_preserved(self):
        store = RevenueLearningPatternStore()
        second = _make_pattern(
            pattern_id="p-2",
            total_records=2,
            successful_records=2,
            failed_records=0,
        )
        first = _make_pattern(
            pattern_id="p-1",
            total_records=5,
            successful_records=5,
            failed_records=0,
        )
        store.add_pattern(second)
        store.add_pattern(first)
        self.assertEqual(store.get_success_only_patterns(), [second, first])

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_success_only_patterns()
        second_call = store.get_success_only_patterns()
        self.assertIsNot(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetFailureOnlyPatterns(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_failure_only_patterns(), [])

    def test_no_failure_only_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(store.get_failure_only_patterns(), [])

    def test_one_failure_only_pattern(self):
        store = RevenueLearningPatternStore()
        failure_only = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=0,
            failed_records=4,
        )
        store.add_pattern(failure_only)
        self.assertEqual(store.get_failure_only_patterns(), [failure_only])

    def test_multiple_failure_only_patterns(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=0,
            failed_records=4,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=2,
            successful_records=0,
            failed_records=2,
        )
        store.add_pattern(first)
        store.add_pattern(second)
        self.assertEqual(store.get_failure_only_patterns(), [first, second])

    def test_successful_and_mixed_patterns_are_excluded(self):
        store = RevenueLearningPatternStore()
        failure_only = _make_pattern(
            pattern_id="p-2",
            total_records=2,
            successful_records=0,
            failed_records=2,
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(failure_only)
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertEqual(store.get_failure_only_patterns(), [failure_only])

    def test_insertion_order_is_preserved(self):
        store = RevenueLearningPatternStore()
        second = _make_pattern(
            pattern_id="p-2",
            total_records=2,
            successful_records=0,
            failed_records=2,
        )
        first = _make_pattern(
            pattern_id="p-1",
            total_records=5,
            successful_records=0,
            failed_records=5,
        )
        store.add_pattern(second)
        store.add_pattern(first)
        self.assertEqual(store.get_failure_only_patterns(), [second, first])

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=0,
            failed_records=4,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_failure_only_patterns()
        second_call = store.get_failure_only_patterns()
        self.assertIsNot(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetNoOutcomePatterns(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_no_outcome_patterns(), [])

    def test_one_no_outcome_pattern(self):
        store = RevenueLearningPatternStore()
        no_outcome = _make_pattern(
            pattern_id="p-1",
            total_records=0,
            successful_records=0,
            failed_records=0,
        )
        store.add_pattern(no_outcome)
        self.assertEqual(store.get_no_outcome_patterns(), [no_outcome])

    def test_multiple_no_outcome_patterns(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=0,
            successful_records=0,
            failed_records=0,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=0,
            successful_records=0,
            failed_records=0,
        )
        store.add_pattern(first)
        store.add_pattern(second)
        self.assertEqual(store.get_no_outcome_patterns(), [first, second])

    def test_successful_patterns_are_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(store.get_no_outcome_patterns(), [])

    def test_failed_patterns_are_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        self.assertEqual(store.get_no_outcome_patterns(), [])

    def test_mixed_patterns_are_excluded(self):
        store = RevenueLearningPatternStore()
        no_outcome = _make_pattern(
            pattern_id="p-2",
            total_records=0,
            successful_records=0,
            failed_records=0,
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(no_outcome)
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-4",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        self.assertEqual(store.get_no_outcome_patterns(), [no_outcome])

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=0,
            successful_records=0,
            failed_records=0,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_no_outcome_patterns()
        second_call = store.get_no_outcome_patterns()
        self.assertIsNot(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetPatternsWithOutcomes(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_patterns_with_outcomes(), [])

    def test_no_patterns_with_outcomes(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        self.assertEqual(store.get_patterns_with_outcomes(), [])

    def test_successful_only_pattern_included(self):
        store = RevenueLearningPatternStore()
        success_only = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        store.add_pattern(success_only)
        self.assertEqual(store.get_patterns_with_outcomes(), [success_only])

    def test_failed_only_pattern_included(self):
        store = RevenueLearningPatternStore()
        failure_only = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=0,
            failed_records=4,
        )
        store.add_pattern(failure_only)
        self.assertEqual(store.get_patterns_with_outcomes(), [failure_only])

    def test_mixed_pattern_included(self):
        store = RevenueLearningPatternStore()
        mixed = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(mixed)
        self.assertEqual(store.get_patterns_with_outcomes(), [mixed])

    def test_no_outcome_pattern_excluded(self):
        store = RevenueLearningPatternStore()
        no_outcome = _make_pattern(
            pattern_id="p-1",
            total_records=0,
            successful_records=0,
            failed_records=0,
        )
        mixed = _make_pattern(
            pattern_id="p-2",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(no_outcome)
        store.add_pattern(mixed)
        self.assertEqual(store.get_patterns_with_outcomes(), [mixed])

    def test_insertion_order_is_preserved(self):
        store = RevenueLearningPatternStore()
        second = _make_pattern(
            pattern_id="p-2",
            total_records=4,
            successful_records=0,
            failed_records=4,
        )
        first = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
        )
        no_outcome = _make_pattern(
            pattern_id="p-3",
            total_records=0,
            successful_records=0,
            failed_records=0,
        )
        third = _make_pattern(
            pattern_id="p-4",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(second)
        store.add_pattern(first)
        store.add_pattern(no_outcome)
        store.add_pattern(third)
        self.assertEqual(
            store.get_patterns_with_outcomes(), [second, first, third]
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_patterns_with_outcomes()
        second_call = store.get_patterns_with_outcomes()
        self.assertIsNot(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetReliablePatternsWithOutcomes(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_reliable_patterns_with_outcomes(), [])

    def test_no_patterns_with_outcomes(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.9,
            )
        )
        self.assertEqual(store.get_reliable_patterns_with_outcomes(), [])

    def test_reliable_pattern_included(self):
        store = RevenueLearningPatternStore()
        reliable = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.8,
        )
        store.add_pattern(reliable)
        self.assertEqual(
            store.get_reliable_patterns_with_outcomes(), [reliable]
        )

    def test_unreliable_pattern_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.5,
            )
        )
        self.assertEqual(store.get_reliable_patterns_with_outcomes(), [])

    def test_no_outcome_pattern_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.95,
            )
        )
        self.assertEqual(store.get_reliable_patterns_with_outcomes(), [])

    def test_mixed_patterns(self):
        store = RevenueLearningPatternStore()
        reliable_with_outcome = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
            reliability=0.9,
        )
        unreliable_with_outcome = _make_pattern(
            pattern_id="p-2",
            total_records=4,
            successful_records=0,
            failed_records=4,
            reliability=0.3,
        )
        reliable_no_outcome = _make_pattern(
            pattern_id="p-3",
            total_records=0,
            successful_records=0,
            failed_records=0,
            reliability=0.9,
        )
        store.add_pattern(reliable_with_outcome)
        store.add_pattern(unreliable_with_outcome)
        store.add_pattern(reliable_no_outcome)
        self.assertEqual(
            store.get_reliable_patterns_with_outcomes(),
            [reliable_with_outcome],
        )

    def test_custom_min_reliability(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.5,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_reliable_patterns_with_outcomes(min_reliability=0.4),
            [pattern],
        )
        self.assertEqual(
            store.get_reliable_patterns_with_outcomes(min_reliability=0.6),
            [],
        )

    def test_insertion_order_is_preserved(self):
        store = RevenueLearningPatternStore()
        second = _make_pattern(
            pattern_id="p-2",
            total_records=4,
            successful_records=0,
            failed_records=4,
            reliability=0.75,
        )
        first = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
            reliability=0.8,
        )
        excluded = _make_pattern(
            pattern_id="p-3",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.2,
        )
        store.add_pattern(second)
        store.add_pattern(first)
        store.add_pattern(excluded)
        self.assertEqual(
            store.get_reliable_patterns_with_outcomes(), [second, first]
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_reliable_patterns_with_outcomes()
        second_call = store.get_reliable_patterns_with_outcomes()
        self.assertIsNot(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetMostReliablePattern(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_most_reliable_pattern())

    def test_one_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", reliability=0.6)
        store.add_pattern(pattern)
        self.assertEqual(store.get_most_reliable_pattern(), pattern)

    def test_multiple_patterns(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(pattern_id="p-1", reliability=0.4)
        p2 = _make_pattern(pattern_id="p-2", reliability=0.6)
        p3 = _make_pattern(pattern_id="p-3", reliability=0.5)
        store.add_pattern(p1)
        store.add_pattern(p2)
        store.add_pattern(p3)
        self.assertEqual(store.get_most_reliable_pattern(), p2)

    def test_highest_reliability_selected_regardless_of_task_or_opportunity(
        self,
    ):
        store = RevenueLearningPatternStore()
        low = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            opportunity_id="opp-a",
            reliability=0.3,
        )
        highest = _make_pattern(
            pattern_id="p-2",
            task_id="task-b",
            opportunity_id="opp-b",
            reliability=0.95,
        )
        store.add_pattern(low)
        store.add_pattern(highest)
        self.assertEqual(store.get_most_reliable_pattern(), highest)

    def test_deterministic_tie_handling(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(pattern_id="p-1", reliability=0.8)
        second = _make_pattern(pattern_id="p-2", reliability=0.8)
        store.add_pattern(first)
        store.add_pattern(second)
        self.assertEqual(store.get_most_reliable_pattern(), first)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(pattern_id="p-1", reliability=0.7)
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_most_reliable_pattern()
        second_call = store.get_most_reliable_pattern()
        self.assertEqual(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetLeastReliablePatternWithOutcomes(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_least_reliable_pattern_with_outcomes())

    def test_only_no_outcome_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.2,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.9,
            )
        )
        self.assertIsNone(store.get_least_reliable_pattern_with_outcomes())

    def test_one_pattern_with_outcomes(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
            reliability=0.6,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_least_reliable_pattern_with_outcomes(), pattern
        )

    def test_multiple_patterns(self):
        store = RevenueLearningPatternStore()
        p1 = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
            reliability=0.7,
        )
        p2 = _make_pattern(
            pattern_id="p-2",
            total_records=4,
            successful_records=0,
            failed_records=4,
            reliability=0.3,
        )
        p3 = _make_pattern(
            pattern_id="p-3",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.5,
        )
        store.add_pattern(p1)
        store.add_pattern(p2)
        store.add_pattern(p3)
        self.assertEqual(
            store.get_least_reliable_pattern_with_outcomes(), p2
        )

    def test_lowest_reliability_selected_ignoring_no_outcome_patterns(self):
        store = RevenueLearningPatternStore()
        no_outcome_lowest = _make_pattern(
            pattern_id="p-1",
            total_records=0,
            successful_records=0,
            failed_records=0,
            reliability=0.1,
        )
        lowest_with_outcome = _make_pattern(
            pattern_id="p-2",
            total_records=4,
            successful_records=0,
            failed_records=4,
            reliability=0.4,
        )
        higher_with_outcome = _make_pattern(
            pattern_id="p-3",
            total_records=4,
            successful_records=4,
            failed_records=0,
            reliability=0.9,
        )
        store.add_pattern(no_outcome_lowest)
        store.add_pattern(lowest_with_outcome)
        store.add_pattern(higher_with_outcome)
        self.assertEqual(
            store.get_least_reliable_pattern_with_outcomes(),
            lowest_with_outcome,
        )

    def test_deterministic_tie_handling(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.4,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=4,
            successful_records=0,
            failed_records=4,
            reliability=0.4,
        )
        store.add_pattern(first)
        store.add_pattern(second)
        self.assertEqual(
            store.get_least_reliable_pattern_with_outcomes(), first
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.5,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_least_reliable_pattern_with_outcomes()
        second_call = store.get_least_reliable_pattern_with_outcomes()
        self.assertEqual(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetAverageReliabilityWithOutcomes(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_average_reliability_with_outcomes(), 0.0)

    def test_no_outcome_patterns_only(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.9,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.1,
            )
        )
        self.assertEqual(store.get_average_reliability_with_outcomes(), 0.0)

    def test_one_pattern_with_outcomes(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
                reliability=0.6,
            )
        )
        self.assertEqual(
            store.get_average_reliability_with_outcomes(), 0.6
        )

    def test_multiple_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
                reliability=0.8,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=4,
                successful_records=0,
                failed_records=4,
                reliability=0.4,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.95,
            )
        )
        self.assertAlmostEqual(
            store.get_average_reliability_with_outcomes(), 0.6
        )

    def test_correct_arithmetic_mean(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.3,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.6,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.9,
            )
        )
        self.assertAlmostEqual(
            store.get_average_reliability_with_outcomes(), 0.6
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.5,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_average_reliability_with_outcomes()
        second_call = store.get_average_reliability_with_outcomes()
        self.assertEqual(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertEqual(pattern.reliability, 0.5)
        self.assertTrue(pattern.is_valid())


class TestGetOverallSuccessRateWithOutcomes(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_overall_success_rate_with_outcomes(), 0.0
        )

    def test_no_outcome_records(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_overall_success_rate_with_outcomes(), 0.0
        )

    def test_only_successful_records(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_overall_success_rate_with_outcomes(), 1.0
        )

    def test_only_failed_records(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_overall_success_rate_with_outcomes(), 0.0
        )

    def test_mixed_successful_and_failed_records(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_overall_success_rate_with_outcomes(), 0.75
        )

    def test_correct_aggregate_success_rate(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=6,
                successful_records=1,
                failed_records=5,
            )
        )
        # successful = 3 + 1 = 4; failed = 1 + 5 = 6; total = 10
        self.assertAlmostEqual(
            store.get_overall_success_rate_with_outcomes(), 0.4
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_overall_success_rate_with_outcomes()
        second_call = store.get_overall_success_rate_with_outcomes()
        self.assertEqual(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertEqual(pattern.successful_records, 3)
        self.assertEqual(pattern.failed_records, 1)
        self.assertTrue(pattern.is_valid())


class TestGetOverallPatternSummary(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_overall_pattern_summary(),
            {
                "pattern_count": 0,
                "patterns_with_outcomes": 0,
                "success_only_count": 0,
                "failure_only_count": 0,
                "mixed_count": 0,
                "no_outcome_count": 0,
            },
        )

    def test_only_no_outcome_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_overall_pattern_summary(),
            {
                "pattern_count": 2,
                "patterns_with_outcomes": 0,
                "success_only_count": 0,
                "failure_only_count": 0,
                "mixed_count": 0,
                "no_outcome_count": 2,
            },
        )

    def test_only_successful_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_overall_pattern_summary(),
            {
                "pattern_count": 2,
                "patterns_with_outcomes": 2,
                "success_only_count": 2,
                "failure_only_count": 0,
                "mixed_count": 0,
                "no_outcome_count": 0,
            },
        )

    def test_only_failed_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_overall_pattern_summary(),
            {
                "pattern_count": 2,
                "patterns_with_outcomes": 2,
                "success_only_count": 0,
                "failure_only_count": 2,
                "mixed_count": 0,
                "no_outcome_count": 0,
            },
        )

    def test_mixed_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=6,
                successful_records=1,
                failed_records=5,
            )
        )
        self.assertEqual(
            store.get_overall_pattern_summary(),
            {
                "pattern_count": 2,
                "patterns_with_outcomes": 2,
                "success_only_count": 0,
                "failure_only_count": 0,
                "mixed_count": 2,
                "no_outcome_count": 0,
            },
        )

    def test_combined_pattern_types(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-4",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_overall_pattern_summary(),
            {
                "pattern_count": 4,
                "patterns_with_outcomes": 3,
                "success_only_count": 1,
                "failure_only_count": 1,
                "mixed_count": 1,
                "no_outcome_count": 1,
            },
        )

    def test_correct_aggregate_counts(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=2,
                successful_records=2,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-4",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-5",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        summary = store.get_overall_pattern_summary()
        self.assertEqual(summary["pattern_count"], 5)
        self.assertEqual(summary["patterns_with_outcomes"], 4)
        self.assertEqual(summary["success_only_count"], 2)
        self.assertEqual(summary["failure_only_count"], 1)
        self.assertEqual(summary["mixed_count"], 1)
        self.assertEqual(summary["no_outcome_count"], 1)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_overall_pattern_summary()
        second_call = store.get_overall_pattern_summary()
        self.assertIsNot(first_call, second_call)
        self.assertEqual(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestHasUsableLearningData(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        result = store.has_usable_learning_data()
        self.assertFalse(result)
        self.assertIsInstance(result, bool)

    def test_only_no_outcome_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        self.assertFalse(store.has_usable_learning_data())

    def test_successful_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        result = store.has_usable_learning_data()
        self.assertTrue(result)
        self.assertIsInstance(result, bool)

    def test_failed_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        self.assertTrue(store.has_usable_learning_data())

    def test_mixed_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertTrue(store.has_usable_learning_data())

    def test_combined_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        self.assertFalse(store.has_usable_learning_data())
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                total_records=4,
                successful_records=0,
                failed_records=4,
            )
        )
        self.assertTrue(store.has_usable_learning_data())

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.has_usable_learning_data()
        second_call = store.has_usable_learning_data()
        self.assertEqual(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestHasReliableLearningData(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        result = store.has_reliable_learning_data()
        self.assertFalse(result)
        self.assertIsInstance(result, bool)

    def test_no_outcome_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.9,
            )
        )
        self.assertFalse(store.has_reliable_learning_data())

    def test_unreliable_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.4,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=4,
                successful_records=0,
                failed_records=4,
                reliability=0.2,
            )
        )
        self.assertFalse(store.has_reliable_learning_data())

    def test_one_reliable_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
                reliability=0.8,
            )
        )
        result = store.has_reliable_learning_data()
        self.assertTrue(result)
        self.assertIsInstance(result, bool)

    def test_multiple_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.95,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.3,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                total_records=4,
                successful_records=0,
                failed_records=4,
                reliability=0.75,
            )
        )
        self.assertTrue(store.has_reliable_learning_data())

    def test_custom_min_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.5,
            )
        )
        self.assertFalse(
            store.has_reliable_learning_data(min_reliability=0.6)
        )
        self.assertTrue(
            store.has_reliable_learning_data(min_reliability=0.4)
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.has_reliable_learning_data()
        second_call = store.has_reliable_learning_data()
        self.assertEqual(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetLearningDataStatus(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_learning_data_status(),
            {
                "has_usable_data": False,
                "has_reliable_data": False,
                "pattern_count": 0,
                "patterns_with_outcomes": 0,
                "reliable_pattern_count": 0,
            },
        )

    def test_only_no_outcome_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.9,
            )
        )
        self.assertEqual(
            store.get_learning_data_status(),
            {
                "has_usable_data": False,
                "has_reliable_data": False,
                "pattern_count": 1,
                "patterns_with_outcomes": 0,
                "reliable_pattern_count": 0,
            },
        )

    def test_usable_but_unreliable_data(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.4,
            )
        )
        self.assertEqual(
            store.get_learning_data_status(),
            {
                "has_usable_data": True,
                "has_reliable_data": False,
                "pattern_count": 1,
                "patterns_with_outcomes": 1,
                "reliable_pattern_count": 0,
            },
        )

    def test_reliable_data(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
                reliability=0.8,
            )
        )
        self.assertEqual(
            store.get_learning_data_status(),
            {
                "has_usable_data": True,
                "has_reliable_data": True,
                "pattern_count": 1,
                "patterns_with_outcomes": 1,
                "reliable_pattern_count": 1,
            },
        )

    def test_custom_min_reliability(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.5,
            )
        )
        self.assertEqual(
            store.get_learning_data_status(min_reliability=0.6),
            {
                "has_usable_data": True,
                "has_reliable_data": False,
                "pattern_count": 1,
                "patterns_with_outcomes": 1,
                "reliable_pattern_count": 0,
            },
        )
        self.assertEqual(
            store.get_learning_data_status(min_reliability=0.4),
            {
                "has_usable_data": True,
                "has_reliable_data": True,
                "pattern_count": 1,
                "patterns_with_outcomes": 1,
                "reliable_pattern_count": 1,
            },
        )

    def test_correct_counts(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
                reliability=0.9,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=4,
                successful_records=0,
                failed_records=4,
                reliability=0.3,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-3",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.95,
            )
        )
        status = store.get_learning_data_status()
        self.assertTrue(status["has_usable_data"])
        self.assertTrue(status["has_reliable_data"])
        self.assertEqual(status["pattern_count"], 3)
        self.assertEqual(status["patterns_with_outcomes"], 2)
        self.assertEqual(status["reliable_pattern_count"], 1)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_learning_data_status()
        second_call = store.get_learning_data_status()
        self.assertIsNot(first_call, second_call)
        self.assertEqual(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetReliableSuccessfulPatterns(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_reliable_successful_patterns(), [])

    def test_success_only_but_unreliable_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
                reliability=0.4,
            )
        )
        self.assertEqual(store.get_reliable_successful_patterns(), [])

    def test_reliable_success_only_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_reliable_successful_patterns(), [pattern]
        )

    def test_failed_pattern_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=0,
                failed_records=4,
                reliability=0.9,
            )
        )
        self.assertEqual(store.get_reliable_successful_patterns(), [])

    def test_mixed_pattern_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.9,
            )
        )
        self.assertEqual(store.get_reliable_successful_patterns(), [])

    def test_multiple_matching_patterns(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
            reliability=0.8,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=2,
            successful_records=2,
            failed_records=0,
            reliability=0.75,
        )
        unreliable = _make_pattern(
            pattern_id="p-3",
            total_records=2,
            successful_records=2,
            failed_records=0,
            reliability=0.3,
        )
        store.add_pattern(first)
        store.add_pattern(unreliable)
        store.add_pattern(second)
        self.assertEqual(
            store.get_reliable_successful_patterns(), [first, second]
        )

    def test_custom_min_reliability(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
            reliability=0.5,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_reliable_successful_patterns(min_reliability=0.6),
            [],
        )
        self.assertEqual(
            store.get_reliable_successful_patterns(min_reliability=0.4),
            [pattern],
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=4,
            failed_records=0,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_reliable_successful_patterns()
        second_call = store.get_reliable_successful_patterns()
        self.assertIsNot(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetReliableFailurePatterns(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_reliable_failure_patterns(), [])

    def test_failure_only_but_unreliable_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=0,
                failed_records=4,
                reliability=0.4,
            )
        )
        self.assertEqual(store.get_reliable_failure_patterns(), [])

    def test_reliable_failure_only_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=0,
            failed_records=4,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_reliable_failure_patterns(), [pattern]
        )

    def test_successful_pattern_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
                reliability=0.9,
            )
        )
        self.assertEqual(store.get_reliable_failure_patterns(), [])

    def test_mixed_pattern_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.9,
            )
        )
        self.assertEqual(store.get_reliable_failure_patterns(), [])

    def test_multiple_matching_patterns(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=0,
            failed_records=4,
            reliability=0.8,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=2,
            successful_records=0,
            failed_records=2,
            reliability=0.75,
        )
        unreliable = _make_pattern(
            pattern_id="p-3",
            total_records=2,
            successful_records=0,
            failed_records=2,
            reliability=0.3,
        )
        store.add_pattern(first)
        store.add_pattern(unreliable)
        store.add_pattern(second)
        self.assertEqual(
            store.get_reliable_failure_patterns(), [first, second]
        )

    def test_custom_min_reliability(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=0,
            failed_records=4,
            reliability=0.5,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_reliable_failure_patterns(min_reliability=0.6),
            [],
        )
        self.assertEqual(
            store.get_reliable_failure_patterns(min_reliability=0.4),
            [pattern],
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=0,
            failed_records=4,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_reliable_failure_patterns()
        second_call = store.get_reliable_failure_patterns()
        self.assertIsNot(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetReliableMixedPatterns(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_reliable_mixed_patterns(), [])

    def test_mixed_pattern_below_threshold(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=2,
                failed_records=2,
                reliability=0.4,
            )
        )
        self.assertEqual(store.get_reliable_mixed_patterns(), [])

    def test_reliable_mixed_pattern(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=2,
            failed_records=2,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_reliable_mixed_patterns(), [pattern]
        )

    def test_success_only_pattern_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
                reliability=0.9,
            )
        )
        self.assertEqual(store.get_reliable_mixed_patterns(), [])

    def test_failure_only_pattern_excluded(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=0,
                failed_records=4,
                reliability=0.9,
            )
        )
        self.assertEqual(store.get_reliable_mixed_patterns(), [])

    def test_multiple_matching_patterns(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.8,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=2,
            successful_records=1,
            failed_records=1,
            reliability=0.75,
        )
        unreliable = _make_pattern(
            pattern_id="p-3",
            total_records=2,
            successful_records=1,
            failed_records=1,
            reliability=0.3,
        )
        store.add_pattern(first)
        store.add_pattern(unreliable)
        store.add_pattern(second)
        self.assertEqual(
            store.get_reliable_mixed_patterns(), [first, second]
        )

    def test_custom_min_reliability(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=2,
            failed_records=2,
            reliability=0.5,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_reliable_mixed_patterns(min_reliability=0.6),
            [],
        )
        self.assertEqual(
            store.get_reliable_mixed_patterns(min_reliability=0.4),
            [pattern],
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=2,
            failed_records=2,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_reliable_mixed_patterns()
        second_call = store.get_reliable_mixed_patterns()
        self.assertIsNot(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetPatternRecordCount(unittest.TestCase):
    def test_missing_pattern(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(store.get_pattern_record_count("missing"), 0)

    def test_pattern_with_no_records(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
                reliability=0.0,
            )
        )
        self.assertEqual(store.get_pattern_record_count("p-1"), 0)

    def test_successful_records_only(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=4,
                failed_records=0,
                reliability=0.9,
            )
        )
        self.assertEqual(store.get_pattern_record_count("p-1"), 4)

    def test_failed_records_only(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=3,
                successful_records=0,
                failed_records=3,
                reliability=0.9,
            )
        )
        self.assertEqual(store.get_pattern_record_count("p-1"), 3)

    def test_mixed_records(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=5,
                successful_records=3,
                failed_records=2,
                reliability=0.6,
            )
        )
        self.assertEqual(store.get_pattern_record_count("p-1"), 5)

    def test_correct_total_with_multiple_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=2,
                successful_records=2,
                failed_records=0,
                reliability=0.9,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=7,
                successful_records=4,
                failed_records=3,
                reliability=0.5,
            )
        )
        self.assertEqual(store.get_pattern_record_count("p-1"), 2)
        self.assertEqual(store.get_pattern_record_count("p-2"), 7)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=5,
            successful_records=3,
            failed_records=2,
            reliability=0.6,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_pattern_record_count("p-1")
        second_call = store.get_pattern_record_count("p-1")
        after = store.get_all()
        self.assertEqual(first_call, second_call)
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertEqual(pattern.successful_records, 3)
        self.assertEqual(pattern.failed_records, 2)
        self.assertTrue(pattern.is_valid())


class TestGetTaskOutcomeCounts(unittest.TestCase):
    def test_no_matching_patterns(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_task_outcome_counts("task-a"),
            {
                "task_id": "task-a",
                "successful_records": 0,
                "failed_records": 0,
                "total_records": 0,
            },
        )

    def test_one_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertEqual(
            store.get_task_outcome_counts("task-a"),
            {
                "task_id": "task-a",
                "successful_records": 3,
                "failed_records": 1,
                "total_records": 4,
            },
        )

    def test_multiple_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-a",
                total_records=6,
                successful_records=1,
                failed_records=5,
            )
        )
        self.assertEqual(
            store.get_task_outcome_counts("task-a"),
            {
                "task_id": "task-a",
                "successful_records": 4,
                "failed_records": 6,
                "total_records": 10,
            },
        )

    def test_successful_records_only(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_task_outcome_counts("task-a"),
            {
                "task_id": "task-a",
                "successful_records": 4,
                "failed_records": 0,
                "total_records": 4,
            },
        )

    def test_failed_records_only(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_task_outcome_counts("task-a"),
            {
                "task_id": "task-a",
                "successful_records": 0,
                "failed_records": 3,
                "total_records": 3,
            },
        )

    def test_mixed_pattern_records(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=5,
                successful_records=3,
                failed_records=2,
            )
        )
        self.assertEqual(
            store.get_task_outcome_counts("task-a"),
            {
                "task_id": "task-a",
                "successful_records": 3,
                "failed_records": 2,
                "total_records": 5,
            },
        )

    def test_different_task_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                task_id="task-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                task_id="task-b",
                total_records=2,
                successful_records=1,
                failed_records=1,
            )
        )
        self.assertEqual(
            store.get_task_outcome_counts("task-a"),
            {
                "task_id": "task-a",
                "successful_records": 3,
                "failed_records": 1,
                "total_records": 4,
            },
        )
        self.assertEqual(
            store.get_task_outcome_counts("task-b"),
            {
                "task_id": "task-b",
                "successful_records": 1,
                "failed_records": 1,
                "total_records": 2,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            task_id="task-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_task_outcome_counts("task-a")
        second_call = store.get_task_outcome_counts("task-a")
        after = store.get_all()
        self.assertIsNot(first_call, second_call)
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.task_id, "task-a")
        self.assertEqual(pattern.successful_records, 3)
        self.assertEqual(pattern.failed_records, 1)
        self.assertTrue(pattern.is_valid())


class TestGetOpportunityOutcomeCounts(unittest.TestCase):
    def test_no_matching_patterns(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_opportunity_outcome_counts("opp-a"),
            {
                "opportunity_id": "opp-a",
                "successful_records": 0,
                "failed_records": 0,
                "total_records": 0,
            },
        )

    def test_one_pattern(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        self.assertEqual(
            store.get_opportunity_outcome_counts("opp-a"),
            {
                "opportunity_id": "opp-a",
                "successful_records": 3,
                "failed_records": 1,
                "total_records": 4,
            },
        )

    def test_multiple_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-a",
                total_records=6,
                successful_records=1,
                failed_records=5,
            )
        )
        self.assertEqual(
            store.get_opportunity_outcome_counts("opp-a"),
            {
                "opportunity_id": "opp-a",
                "successful_records": 4,
                "failed_records": 6,
                "total_records": 10,
            },
        )

    def test_successful_records_only(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=4,
                failed_records=0,
            )
        )
        self.assertEqual(
            store.get_opportunity_outcome_counts("opp-a"),
            {
                "opportunity_id": "opp-a",
                "successful_records": 4,
                "failed_records": 0,
                "total_records": 4,
            },
        )

    def test_failed_records_only(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=3,
                successful_records=0,
                failed_records=3,
            )
        )
        self.assertEqual(
            store.get_opportunity_outcome_counts("opp-a"),
            {
                "opportunity_id": "opp-a",
                "successful_records": 0,
                "failed_records": 3,
                "total_records": 3,
            },
        )

    def test_mixed_pattern_records(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=5,
                successful_records=3,
                failed_records=2,
            )
        )
        self.assertEqual(
            store.get_opportunity_outcome_counts("opp-a"),
            {
                "opportunity_id": "opp-a",
                "successful_records": 3,
                "failed_records": 2,
                "total_records": 5,
            },
        )

    def test_different_opportunity_ids_are_not_mixed(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                opportunity_id="opp-a",
                total_records=4,
                successful_records=3,
                failed_records=1,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                opportunity_id="opp-b",
                total_records=2,
                successful_records=1,
                failed_records=1,
            )
        )
        self.assertEqual(
            store.get_opportunity_outcome_counts("opp-a"),
            {
                "opportunity_id": "opp-a",
                "successful_records": 3,
                "failed_records": 1,
                "total_records": 4,
            },
        )
        self.assertEqual(
            store.get_opportunity_outcome_counts("opp-b"),
            {
                "opportunity_id": "opp-b",
                "successful_records": 1,
                "failed_records": 1,
                "total_records": 2,
            },
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            opportunity_id="opp-a",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_opportunity_outcome_counts("opp-a")
        second_call = store.get_opportunity_outcome_counts("opp-a")
        after = store.get_all()
        self.assertIsNot(first_call, second_call)
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.opportunity_id, "opp-a")
        self.assertEqual(pattern.successful_records, 3)
        self.assertEqual(pattern.failed_records, 1)
        self.assertTrue(pattern.is_valid())


class TestGetMostObservedPattern(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(store.get_most_observed_pattern())

    def test_only_no_outcome_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        self.assertIsNone(store.get_most_observed_pattern())

    def test_one_pattern_with_outcomes(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        self.assertIs(store.get_most_observed_pattern(), pattern)

    def test_multiple_patterns(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=2,
            successful_records=1,
            failed_records=1,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=5,
            successful_records=3,
            failed_records=2,
        )
        no_outcome = _make_pattern(
            pattern_id="p-3",
            total_records=0,
            successful_records=0,
            failed_records=0,
        )
        store.add_pattern(first)
        store.add_pattern(no_outcome)
        store.add_pattern(second)
        self.assertIs(store.get_most_observed_pattern(), second)

    def test_highest_total_records_selection(self):
        store = RevenueLearningPatternStore()
        low = _make_pattern(
            pattern_id="p-1",
            total_records=3,
            successful_records=3,
            failed_records=0,
        )
        high = _make_pattern(
            pattern_id="p-2",
            total_records=9,
            successful_records=2,
            failed_records=7,
        )
        store.add_pattern(low)
        store.add_pattern(high)
        self.assertIs(store.get_most_observed_pattern(), high)

    def test_deterministic_tie_handling(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=5,
            successful_records=3,
            failed_records=2,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=5,
            successful_records=1,
            failed_records=4,
        )
        store.add_pattern(first)
        store.add_pattern(second)
        self.assertIs(store.get_most_observed_pattern(), first)

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_most_observed_pattern()
        second_call = store.get_most_observed_pattern()
        after = store.get_all()
        self.assertIs(first_call, second_call)
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetLeastObservedPatternWithOutcomes(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertIsNone(
            store.get_least_observed_pattern_with_outcomes()
        )

    def test_only_no_outcome_patterns(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        store.add_pattern(
            _make_pattern(
                pattern_id="p-2",
                total_records=0,
                successful_records=0,
                failed_records=0,
            )
        )
        self.assertIsNone(
            store.get_least_observed_pattern_with_outcomes()
        )

    def test_one_pattern_with_outcomes(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        self.assertIs(
            store.get_least_observed_pattern_with_outcomes(), pattern
        )

    def test_multiple_patterns(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=6,
            successful_records=4,
            failed_records=2,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=2,
            successful_records=1,
            failed_records=1,
        )
        no_outcome = _make_pattern(
            pattern_id="p-3",
            total_records=0,
            successful_records=0,
            failed_records=0,
        )
        store.add_pattern(first)
        store.add_pattern(no_outcome)
        store.add_pattern(second)
        self.assertIs(
            store.get_least_observed_pattern_with_outcomes(), second
        )

    def test_lowest_total_records_selection(self):
        store = RevenueLearningPatternStore()
        high = _make_pattern(
            pattern_id="p-1",
            total_records=9,
            successful_records=2,
            failed_records=7,
        )
        low = _make_pattern(
            pattern_id="p-2",
            total_records=3,
            successful_records=3,
            failed_records=0,
        )
        store.add_pattern(high)
        store.add_pattern(low)
        self.assertIs(
            store.get_least_observed_pattern_with_outcomes(), low
        )

    def test_deterministic_tie_handling(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=5,
            successful_records=3,
            failed_records=2,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=5,
            successful_records=1,
            failed_records=4,
        )
        store.add_pattern(first)
        store.add_pattern(second)
        self.assertIs(
            store.get_least_observed_pattern_with_outcomes(), first
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_least_observed_pattern_with_outcomes()
        second_call = store.get_least_observed_pattern_with_outcomes()
        after = store.get_all()
        self.assertIs(first_call, second_call)
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetLowReliabilityObservedPatterns(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_low_reliability_observed_patterns(), []
        )

    def test_insufficient_record_count(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=1,
                successful_records=1,
                failed_records=0,
                reliability=0.2,
            )
        )
        self.assertEqual(
            store.get_low_reliability_observed_patterns(), []
        )

    def test_reliability_above_threshold(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=3,
                failed_records=1,
                reliability=0.9,
            )
        )
        self.assertEqual(
            store.get_low_reliability_observed_patterns(), []
        )

    def test_pattern_meeting_both_conditions(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=3,
            successful_records=1,
            failed_records=2,
            reliability=0.4,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_low_reliability_observed_patterns(), [pattern]
        )

    def test_multiple_matching_patterns(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=2,
            successful_records=1,
            failed_records=1,
            reliability=0.3,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=5,
            successful_records=2,
            failed_records=3,
            reliability=0.5,
        )
        not_matching = _make_pattern(
            pattern_id="p-3",
            total_records=1,
            successful_records=1,
            failed_records=0,
            reliability=0.1,
        )
        store.add_pattern(first)
        store.add_pattern(not_matching)
        store.add_pattern(second)
        self.assertEqual(
            store.get_low_reliability_observed_patterns(),
            [first, second],
        )

    def test_custom_thresholds(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=3,
            successful_records=1,
            failed_records=2,
            reliability=0.6,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_low_reliability_observed_patterns(
                min_records=5, max_reliability=0.6
            ),
            [],
        )
        self.assertEqual(
            store.get_low_reliability_observed_patterns(
                min_records=3, max_reliability=0.6
            ),
            [pattern],
        )

    def test_insertion_order_preserved(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=2,
            failed_records=2,
            reliability=0.2,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=3,
            successful_records=1,
            failed_records=2,
            reliability=0.1,
        )
        store.add_pattern(second)
        store.add_pattern(first)
        self.assertEqual(
            store.get_low_reliability_observed_patterns(),
            [second, first],
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=3,
            successful_records=1,
            failed_records=2,
            reliability=0.4,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_low_reliability_observed_patterns()
        second_call = store.get_low_reliability_observed_patterns()
        self.assertIsNot(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


class TestGetHighConfidenceObservedPatterns(unittest.TestCase):
    def test_empty_store(self):
        store = RevenueLearningPatternStore()
        self.assertEqual(
            store.get_high_confidence_observed_patterns(), []
        )

    def test_insufficient_record_count(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=1,
                successful_records=1,
                failed_records=0,
                reliability=0.9,
            )
        )
        self.assertEqual(
            store.get_high_confidence_observed_patterns(), []
        )

    def test_reliability_below_threshold(self):
        store = RevenueLearningPatternStore()
        store.add_pattern(
            _make_pattern(
                pattern_id="p-1",
                total_records=4,
                successful_records=1,
                failed_records=3,
                reliability=0.3,
            )
        )
        self.assertEqual(
            store.get_high_confidence_observed_patterns(), []
        )

    def test_pattern_meeting_both_conditions(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=3,
            successful_records=2,
            failed_records=1,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_high_confidence_observed_patterns(), [pattern]
        )

    def test_multiple_matching_patterns(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=2,
            successful_records=1,
            failed_records=1,
            reliability=0.9,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=5,
            successful_records=4,
            failed_records=1,
            reliability=0.7,
        )
        not_matching = _make_pattern(
            pattern_id="p-3",
            total_records=1,
            successful_records=1,
            failed_records=0,
            reliability=0.95,
        )
        store.add_pattern(first)
        store.add_pattern(not_matching)
        store.add_pattern(second)
        self.assertEqual(
            store.get_high_confidence_observed_patterns(),
            [first, second],
        )

    def test_custom_thresholds(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=3,
            successful_records=2,
            failed_records=1,
            reliability=0.5,
        )
        store.add_pattern(pattern)
        self.assertEqual(
            store.get_high_confidence_observed_patterns(
                min_records=5, min_reliability=0.5
            ),
            [],
        )
        self.assertEqual(
            store.get_high_confidence_observed_patterns(
                min_records=3, min_reliability=0.5
            ),
            [pattern],
        )

    def test_insertion_order_preserved(self):
        store = RevenueLearningPatternStore()
        first = _make_pattern(
            pattern_id="p-1",
            total_records=4,
            successful_records=3,
            failed_records=1,
            reliability=0.9,
        )
        second = _make_pattern(
            pattern_id="p-2",
            total_records=3,
            successful_records=2,
            failed_records=1,
            reliability=0.95,
        )
        store.add_pattern(second)
        store.add_pattern(first)
        self.assertEqual(
            store.get_high_confidence_observed_patterns(),
            [second, first],
        )

    def test_does_not_change_the_store(self):
        store = RevenueLearningPatternStore()
        pattern = _make_pattern(
            pattern_id="p-1",
            total_records=3,
            successful_records=2,
            failed_records=1,
            reliability=0.8,
        )
        store.add_pattern(pattern)
        before = store.get_all()
        first_call = store.get_high_confidence_observed_patterns()
        second_call = store.get_high_confidence_observed_patterns()
        self.assertIsNot(first_call, second_call)
        after = store.get_all()
        self.assertEqual(store.count(), 1)
        self.assertEqual(
            [p.pattern_id for p in before], [p.pattern_id for p in after]
        )
        self.assertEqual(pattern.pattern_id, "p-1")
        self.assertTrue(pattern.is_valid())


if __name__ == "__main__":
    unittest.main()
