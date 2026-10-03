"""
Revenue Learning Pattern Store
=================================
`RevenueLearningPatternStore` is a small, in-memory record of every
`RevenueLearningPattern` (financial/revenue_learning_pattern.py) that
has been handed to it so far - same "id-keyed dict plus an ordered
list of ids" shape `financial/revenue_learning_store.py`'s own
`RevenueLearningRecordStore` already uses for `RevenueLearningRecord`.

This stage only stores and retrieves already-built
`RevenueLearningPattern` objects via `add_pattern()`, `get_pattern()`,
`get_all()`, `has_pattern()` (a plain, read-only membership check),
`count()` (a plain, read-only count), `get_for_task()` and
`get_for_opportunity()` (plain, read-only lookups by `task_id`/
`opportunity_id`), `get_task_pattern_summaries()` (a plain,
read-only mapping of `get_for_task()`'s own results through each
pattern's own `get_summary()`), `get_opportunity_pattern_summaries()`
(the same mapping, keyed on `opportunity_id` via
`get_for_opportunity()` instead of `task_id`), `get_latest_for_task()` and
`get_latest_for_opportunity()` (plain, read-only lookups of the most
recently added pattern for a `task_id`/`opportunity_id`),
`get_latest_task_pattern_summary()` (a plain, read-only mapping of
`get_latest_for_task()`'s own result through its `get_summary()`),
`get_latest_opportunity_pattern_summary()` (the same mapping, keyed
on `opportunity_id` via `get_latest_for_opportunity()` instead of
`task_id`),
`get_highest_reliability_for_task()` and
`get_highest_reliability_for_opportunity()` (plain, read-only
lookups of the highest-`reliability` pattern for a `task_id`/
`opportunity_id`, ties broken by insertion order),
`get_reliable_patterns()` (a plain, read-only filter of every stored
pattern at or above a given `reliability` threshold),
`get_reliable_for_task()` (a plain, read-only filter of every stored
pattern for a given `task_id` that is at or above a given
`reliability` threshold), `get_reliable_for_opportunity()` (the same
filter keyed on `opportunity_id` instead of `task_id`),
`get_best_reliable_for_task()` (a plain, read-only lookup of the
highest-`reliability` pattern for a `task_id` that also meets a
`reliability` threshold, ties broken by insertion order),
`get_best_reliable_task_pattern_summary()` (a plain, read-only
mapping of `get_best_reliable_for_task()`'s own result through its
`get_summary()`),
`get_best_reliable_for_opportunity()` (the same lookup keyed on
`opportunity_id` instead of `task_id`),
`get_best_reliable_opportunity_pattern_summary()` (a plain,
read-only mapping of `get_best_reliable_for_opportunity()`'s own
result through its `get_summary()`),
`count_reliable_for_task()` (a plain, read-only count of
`get_reliable_for_task()`'s own result),
`has_reliable_for_task()` (a plain, read-only boolean check of
whether `count_reliable_for_task()`'s own result is greater than
`0`),
`count_reliable_for_opportunity()` (the same count keyed on
`opportunity_id` instead of `task_id`),
`has_reliable_for_opportunity()` (a plain, read-only boolean check of
whether `count_reliable_for_opportunity()`'s own result is greater
than `0`),
`get_average_reliability_for_task()` (a plain, read-only arithmetic
mean of the `reliability` values of `get_for_task()`'s own result,
`0.0` when there are none),
`get_average_reliability_for_opportunity()` (the same arithmetic
mean keyed on `opportunity_id` instead of `task_id`),
`get_max_reliability_for_task()` (a plain, read-only maximum of the
`reliability` values of `get_for_task()`'s own result, `0.0` when
there are none - distinct from `get_highest_reliability_for_task()`
above, which returns the pattern itself rather than a plain `float`),
`get_max_reliability_for_opportunity()` (the same maximum keyed on
`opportunity_id` instead of `task_id` - likewise distinct from
`get_highest_reliability_for_opportunity()` above),
`get_task_reliability_summary()` (a plain, read-only dict combining
`get_for_task()`'s own `pattern_count`, `average_reliability`, and
`highest_reliability` for a `task_id`),
`get_opportunity_reliability_summary()` (the same dict keyed on
`opportunity_id` via `get_for_opportunity()` instead of `task_id`),
`is_task_reliable()` (a plain, read-only boolean check of whether
any of `get_for_task()`'s own result meets a `reliability`
threshold - same shape as `has_reliable_for_task()`),
`is_opportunity_reliable()` (the same boolean check keyed on
`opportunity_id` via `get_for_opportunity()` instead of `task_id`),
`get_task_reliability_status()` (a plain, read-only dict combining
`get_for_task()`'s own `pattern_count`, `highest_reliability`, and
`is_reliable` for a `task_id`),
`get_opportunity_reliability_status()` (the same dict keyed on
`opportunity_id` via `get_for_opportunity()` instead of `task_id`),
`count_successful_for_task()` (a plain, read-only count of
`get_for_task()`'s own result whose `successful_records` is greater
than `0`),
`count_successful_for_opportunity()` (the same count keyed on
`opportunity_id` via `get_for_opportunity()` instead of `task_id`),
`count_failed_for_task()` (a plain, read-only count of
`get_for_task()`'s own result whose `failed_records` is greater than
`0` - same shape as `count_successful_for_task()`, checking
`failed_records` instead of `successful_records`),
`count_failed_for_opportunity()` (the same count keyed on
`opportunity_id` via `get_for_opportunity()` instead of `task_id`),
`get_task_outcome_summary()` (a plain, read-only dict combining
`get_for_task()`'s own `pattern_count`, `successful_pattern_count`,
`failed_pattern_count`, `total_successful_records`, and
`total_failed_records` for a `task_id`),
`get_opportunity_outcome_summary()` (the same dict keyed on
`opportunity_id` via `get_for_opportunity()` instead of `task_id`),
`has_successful_pattern_for_task()` (a plain, read-only boolean check
of whether `count_successful_for_task()`'s own result is greater
than `0`),
`has_successful_pattern_for_opportunity()` (the same boolean check
keyed on `opportunity_id` via `count_successful_for_opportunity()`
instead of `task_id`),
`has_failed_pattern_for_task()` (a plain, read-only boolean check of
whether `count_failed_for_task()`'s own result is greater than `0` -
same shape as `has_successful_pattern_for_task()`, checking
`count_failed_for_task()` instead of `count_successful_for_task()`),
`has_failed_pattern_for_opportunity()` (the same boolean check keyed
on `opportunity_id` via `count_failed_for_opportunity()` instead of
`task_id`),
`get_task_learning_status()` (a plain, read-only dict combining
`get_for_task()`'s own `pattern_count`, a `has_success` flag, a
`has_failure` flag, and a `status` label of `"NO_DATA"`, `"SUCCESS"`,
`"FAILED"`, or `"MIXED"` for a `task_id`),
`get_opportunity_learning_status()` (the same dict keyed on
`opportunity_id` via `get_for_opportunity()` instead of `task_id`),
`get_latest_successful_for_task()` (a plain, read-only lookup of the
most recently added `get_for_task()` result whose
`successful_records` is greater than `0`),
`get_latest_successful_for_opportunity()` (the same lookup keyed on
`opportunity_id` via `get_for_opportunity()` instead of `task_id`),
`get_latest_failed_for_task()` (a plain, read-only lookup of the
most recently added `get_for_task()` result whose `failed_records`
is greater than `0` - same shape as `get_latest_successful_for_task()`),
`get_latest_failed_for_opportunity()` (the same lookup keyed on
`opportunity_id` via `get_for_opportunity()` instead of `task_id`),
`get_success_rate_for_task()` (a plain, read-only aggregate success
rate - `successful_records` summed across `get_for_task()`'s own
result, divided by that sum plus the summed `failed_records`, `0.0`
when both sums are `0`),
`get_success_rate_for_opportunity()` (the same aggregate success
rate keyed on `opportunity_id` via `get_for_opportunity()` instead
of `task_id`),
`get_total_records_for_task()` (a plain, read-only sum of
`successful_records` plus `failed_records` across `get_for_task()`'s
own result, `0` when there are none),
`get_total_records_for_opportunity()` (the same sum keyed on
`opportunity_id` via `get_for_opportunity()` instead of `task_id`),
`get_task_learning_summary()` (a plain, read-only dict combining
`get_for_task()`'s own `pattern_count`,
`get_total_records_for_task()`'s own `total_records`, and
`get_success_rate_for_task()`'s own `success_rate` for a `task_id`),
`get_opportunity_learning_summary()` (the same dict keyed on
`opportunity_id` via `get_for_opportunity()`,
`get_total_records_for_opportunity()`, and
`get_success_rate_for_opportunity()` instead of `task_id`),
`get_learning_summary_for_pattern()` (a plain, read-only dict built
from a single stored pattern's own `total_records`,
`success_rate`, `reliability`, and `is_reliable()`, looked up via
`get_pattern()`, `None` when no pattern has that `pattern_id`),
`get_reliable_pattern_summary_for_opportunity()` (a plain,
read-only dict combining `get_for_opportunity()`'s own
`pattern_count`, `count_reliable_for_opportunity()`'s own
`reliable_pattern_count`, and `has_reliable_for_opportunity()`'s own
`has_reliable_pattern` for an `opportunity_id` and
`min_reliability`),
`get_reliable_pattern_summary_for_task()` (the same dict keyed on
`task_id` via `get_for_task()`, `count_reliable_for_task()`, and
`has_reliable_for_task()` instead of `opportunity_id`),
`get_most_reliable_for_opportunity()` (a plain, read-only lookup of
the highest-`reliability` pattern among `get_for_opportunity()`'s
own result, ties broken by insertion order - same result as
`get_highest_reliability_for_opportunity()` above),
`get_most_reliable_for_task()` (the same lookup keyed on `task_id`
via `get_for_task()` instead of `opportunity_id` - same result as
`get_highest_reliability_for_task()` above),
`get_pattern_reliability_report()` (a plain, read-only dict built
from a single stored pattern's own `task_id`, `opportunity_id`,
`reliability`, `total_records`, `successful_records`,
`failed_records`, and `is_reliable()`, looked up via
`get_pattern()`, `None` when no pattern has that `pattern_id`),
`get_pattern_reliability_reports_for_task()` (a plain, read-only
list of `get_pattern_reliability_report()` results for every
pattern in `get_for_task()`'s own result, in the same insertion
order, an empty list when there are none),
`get_pattern_reliability_reports_for_opportunity()` (the same list
keyed on `opportunity_id` via `get_for_opportunity()` instead of
`task_id`),
`get_mixed_patterns()` (a plain, read-only filter of `get_all()`'s
own result down to patterns with both a `successful_records` and a
`failed_records` greater than `0`),
`count_mixed_patterns()` (a plain, read-only count of
`get_mixed_patterns()`'s own result),
`get_success_only_patterns()` (a plain, read-only filter of
`get_all()`'s own result down to patterns with a `successful_records`
greater than `0` and a `failed_records` of exactly `0` - same shape
as `get_mixed_patterns()`, checking for a purely successful record
split instead of a mixed one),
`get_failure_only_patterns()` (a plain, read-only filter of
`get_all()`'s own result down to patterns with a `failed_records`
greater than `0` and a `successful_records` of exactly `0` - same
shape as `get_success_only_patterns()`, checking for a purely
failed record split instead of a purely successful one),
`get_no_outcome_patterns()` (a plain, read-only filter of
`get_all()`'s own result down to patterns with a `successful_records`
of exactly `0` and a `failed_records` of exactly `0` - same shape as
`get_success_only_patterns()` and `get_failure_only_patterns()`,
checking for an entirely empty record split instead of a purely
successful or purely failed one),
`get_patterns_with_outcomes()` (a plain, read-only filter of
`get_all()`'s own result down to patterns with a `successful_records`
greater than `0` or a `failed_records` greater than `0` - the
complement of `get_no_outcome_patterns()`),
`get_reliable_patterns_with_outcomes()` (a plain, read-only filter of
`get_patterns_with_outcomes()`'s own result down to patterns whose
`reliability` also meets a `min_reliability` threshold, defaulting to
`0.7` - reusing this store's own existing `get_reliable_patterns()`
threshold-handling logic),
`get_most_reliable_pattern()` (a plain, read-only lookup of the
highest-`reliability` pattern among every stored pattern, ties
broken by insertion order - same shape as
`get_highest_reliability_for_task()`, considering the whole store
instead of one `task_id`),
`get_least_reliable_pattern_with_outcomes()` (a plain, read-only
lookup of the lowest-`reliability` pattern among
`get_patterns_with_outcomes()`'s own result, ties broken by
insertion order - the same shape as `get_most_reliable_pattern()`,
scanning for the lowest `reliability` instead of the highest, and
restricted to patterns with an outcome instead of the whole store),
`get_average_reliability_with_outcomes()` (a plain, read-only
arithmetic mean of the `reliability` values of
`get_patterns_with_outcomes()`'s own result, `0.0` when there are
none - same shape as `get_average_reliability_for_task()`,
considering patterns with an outcome instead of a `task_id` match),
`get_overall_success_rate_with_outcomes()` (a plain, read-only
aggregate success rate - `successful_records` summed across
`get_patterns_with_outcomes()`'s own result, divided by that sum
plus the summed `failed_records`, `0.0` when both sums are `0` -
same shape as `get_success_rate_for_task()`, considering patterns
with an outcome instead of a `task_id` match),
`get_overall_pattern_summary()` (a plain, read-only dict combining
the `len()` of `get_all()`, `get_patterns_with_outcomes()`,
`get_success_only_patterns()`, `get_failure_only_patterns()`,
`get_mixed_patterns()`, and `get_no_outcome_patterns()` into
`pattern_count`/`patterns_with_outcomes`/`success_only_count`/
`failure_only_count`/`mixed_count`/`no_outcome_count`),
`has_usable_learning_data()` (a plain, read-only boolean check of
whether `get_patterns_with_outcomes()`'s own result is non-empty -
same shape as `has_reliable_for_task()`, checking for any outcome
at all instead of a reliability threshold),
`has_reliable_learning_data()` (a plain, read-only boolean check of
whether `get_reliable_patterns_with_outcomes()`'s own result is
non-empty, given a `min_reliability` threshold defaulting to `0.7` -
same shape as `has_usable_learning_data()`, additionally requiring
the threshold to be met),
`get_learning_data_status()` (a plain, read-only dict combining
`has_usable_learning_data()`, `has_reliable_learning_data()`, and
the `len()` of `get_all()`, `get_patterns_with_outcomes()`, and
`get_reliable_patterns_with_outcomes()` into
`has_usable_data`/`has_reliable_data`/`pattern_count`/
`patterns_with_outcomes`/`reliable_pattern_count`, given a
`min_reliability` threshold defaulting to `0.7`),
`get_reliable_successful_patterns()` (a plain, read-only filter of
`get_success_only_patterns()`'s own result down to patterns whose
`reliability` also meets a `min_reliability` threshold, defaulting
to `0.7` - same shape as `get_reliable_patterns_with_outcomes()`,
restricted to success-only patterns instead of every pattern with
an outcome),
`get_reliable_failure_patterns()` (a plain, read-only filter of
`get_failure_only_patterns()`'s own result down to patterns whose
`reliability` also meets a `min_reliability` threshold, defaulting
to `0.7` - same shape as `get_reliable_successful_patterns()`,
restricted to failure-only patterns instead of success-only
patterns),
and `clear()`
(removes every stored pattern from this store, without touching the
`RevenueLearningPattern` objects themselves). It does NOT:

- Learn anything, infer a pattern, or feed a pattern into
  `learning/learning_system.py`, `learning/learning_analyzer.py`, or
  any other learning component - storing a pattern here is not a
  decision or a behavior change in its own right.
- Change any `RevenueTask`, `RevenueOpportunity`, `RevenueStrategy`,
  or `RevenueLearningRecordStore`'s own state, or trigger any future
  execution, retry, or strategy change.
- Persist itself anywhere (no filesystem, database, or network I/O),
  run any code (no `eval`/`exec`/`subprocess`/shell), or call out to
  any external AI service.

Deliberately independent from persistent storage - same "lives only in
this process's RAM, cleared on process restart" convention
`RevenueLearningRecordStore` already follows for its own records. A
future stage may add more behavior; that is explicitly out of scope
here.
"""

from .revenue_learning_pattern import RevenueLearningPattern


class RevenueLearningPatternStore:
    """Not thread-safe (matches the rest of this project - see
    `RevenueLearningRecordStore`'s own note). Safe to use one instance
    per Core / per conversation session, or to share one across
    several callers that should store to the same store.

    Storage is two small, always-in-sync structures - a dict keyed by
    `pattern_id` for O(1) lookup/duplicate-detection, and a list of
    `pattern_id`s in the order `add_pattern()` first accepted them,
    for order-preserving iteration - same shape
    `RevenueLearningRecordStore` already uses.
    """

    def __init__(self):
        self._by_pattern_id = {}
        self._order = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def add_pattern(self, pattern):
        """Store `pattern` (a `RevenueLearningPattern`) in this store
        and return it unchanged on success, or `None` - storing
        nothing - on rejection. Never raises, and never modifies
        `pattern` in any way (this store's own state is the only
        thing that changes on a successful call).

        Rejected (returns `None`, leaves this store's own state
        completely unchanged) when:
        - `pattern` is not an actual `RevenueLearningPattern` instance
        - `pattern` fails its own `is_valid()` check (financial/
          revenue_learning_pattern.py)
        - `pattern.pattern_id` is already stored in this store (a
          duplicate id never overwrites, or is silently dropped in
          favor of, the already-stored pattern under that same id -
          the first pattern stored under a given id always wins)

        On success, `pattern` is appended to this store's own
        insertion-order record - it is never inserted anywhere else,
        never re-ordered, and never stored a second time under the
        same id."""
        if not isinstance(pattern, RevenueLearningPattern):
            return None
        if not pattern.is_valid():
            return None
        if pattern.pattern_id in self._by_pattern_id:
            return None

        self._by_pattern_id[pattern.pattern_id] = pattern
        self._order.append(pattern.pattern_id)
        return pattern

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_pattern(self, pattern_id):
        """The stored `RevenueLearningPattern` whose `pattern_id`
        exactly matches `pattern_id`, or `None` if no such pattern is
        stored (including an unknown, empty, or `None` `pattern_id`) -
        never raises."""
        return self._by_pattern_id.get(pattern_id)

    def get_all(self):
        """Every stored `RevenueLearningPattern`, oldest-first
        (insertion order), as a new list on every call - never a
        reference to this store's own internal collection, so
        mutating the returned list can never affect this store's own
        stored state."""
        return [self._by_pattern_id[pattern_id] for pattern_id in self._order]

    def get_for_task(self, task_id):
        """Every stored `RevenueLearningPattern` whose `task_id`
        exactly matches `task_id`, oldest-first (insertion order), as
        a new list on every call - never a reference to this store's
        own internal collection, so mutating the returned list (or
        appending/removing from it) can never affect this store's own
        stored state. Never modifies any stored pattern.

        Returns an empty list - never raises - when no stored pattern
        has that `task_id`, including for an unknown, empty, `None`,
        or any other non-matching `task_id` (comparison is a plain
        `==` against each stored pattern's own `task_id`, so a
        `task_id` of an unusual/unhashable type simply matches
        nothing rather than erroring)."""
        return [
            self._by_pattern_id[pattern_id]
            for pattern_id in self._order
            if self._by_pattern_id[pattern_id].task_id == task_id
        ]

    def get_task_pattern_summaries(self, task_id):
        """A short, structured summary for every stored
        `RevenueLearningPattern` whose `task_id` exactly matches
        `task_id`, oldest-first (insertion order) - built by calling
        `get_for_task()` (this store's own existing task-pattern
        lookup) and then each matching pattern's own `get_summary()`
        (financial/revenue_learning_pattern.py).

        Always a new list on every call, holding a new dict per
        pattern (exactly what `get_summary()` itself already
        returns) - never a reference to this store's own internal
        collection, and never a reference to any stored pattern's own
        state, so mutating the returned list, or any dict inside it,
        can never affect this store or any stored pattern. Never
        modifies this store or any stored pattern.

        Returns an empty list - never raises - when no stored pattern
        has that `task_id`, including for an unknown, empty, `None`,
        or any other non-matching `task_id` - same "matches nothing
        rather than erroring" behavior `get_for_task()` already
        provides, since this method simply maps `get_summary()` over
        whatever `get_for_task()` returns."""
        return [pattern.get_summary() for pattern in self.get_for_task(task_id)]

    def get_opportunity_pattern_summaries(self, opportunity_id):
        """A short, structured summary for every stored
        `RevenueLearningPattern` whose `opportunity_id` exactly
        matches `opportunity_id`, oldest-first (insertion order) -
        built by calling `get_for_opportunity()` (this store's own
        existing opportunity-pattern lookup) and then each matching
        pattern's own `get_summary()` (financial/
        revenue_learning_pattern.py).

        Always a new list on every call, holding a new dict per
        pattern (exactly what `get_summary()` itself already
        returns) - never a reference to this store's own internal
        collection, and never a reference to any stored pattern's own
        state, so mutating the returned list, or any dict inside it,
        can never affect this store or any stored pattern. Never
        modifies this store or any stored pattern.

        Returns an empty list - never raises - when no stored pattern
        has that `opportunity_id`, including for an unknown, empty,
        `None`, or any other non-matching `opportunity_id` - same
        "matches nothing rather than erroring" behavior
        `get_for_opportunity()` already provides, since this method
        simply maps `get_summary()` over whatever
        `get_for_opportunity()` returns - same shape as
        `get_task_pattern_summaries()`, keyed on `opportunity_id`
        instead of `task_id`."""
        return [
            pattern.get_summary()
            for pattern in self.get_for_opportunity(opportunity_id)
        ]

    def get_latest_for_task(self, task_id):
        """The most recently added stored `RevenueLearningPattern`
        whose `task_id` exactly matches `task_id` - "most recently
        added" meaning last in this store's own insertion-order
        record, exactly as `get_for_task()` already orders its
        results, not `created_at` or any other field. Read-only -
        never modifies this store or any stored pattern.

        Returns `None` - never raises - when no stored pattern has
        that `task_id`, including for an unknown, empty, `None`, or
        any other non-matching `task_id` (comparison is the same
        plain `==` `get_for_task()` uses, so an unusual/unhashable
        `task_id` simply matches nothing rather than erroring)."""
        latest = None
        for pattern_id in self._order:
            pattern = self._by_pattern_id[pattern_id]
            if pattern.task_id == task_id:
                latest = pattern
        return latest

    def get_latest_task_pattern_summary(self, task_id):
        """A short, structured summary of the most recently added
        stored `RevenueLearningPattern` whose `task_id` exactly
        matches `task_id` - built by calling `get_latest_for_task()`
        (this store's own existing latest-for-task lookup) and then
        that pattern's own `get_summary()` (financial/
        revenue_learning_pattern.py). Read-only - never modifies this
        store or any stored pattern.

        Always a new dict on every call (exactly what `get_summary()`
        itself already returns) - never a reference to any stored
        pattern's own state, so mutating the returned dict can never
        affect this store or any stored pattern.

        Returns `None` - never raises - when no stored pattern has
        that `task_id`, including for an unknown, empty, `None`, or
        any other non-matching `task_id` - same "matches nothing
        rather than erroring" behavior `get_latest_for_task()`
        already provides, since this method simply calls
        `get_summary()` on whatever `get_latest_for_task()`
        returns."""
        pattern = self.get_latest_for_task(task_id)
        if pattern is None:
            return None
        return pattern.get_summary()

    def get_highest_reliability_for_task(self, task_id):
        """The stored `RevenueLearningPattern` whose `task_id` exactly
        matches `task_id` and whose `reliability` is the highest among
        all such matches. Read-only - never modifies this store or
        any stored pattern.

        When several matching patterns share the same highest
        `reliability`, the earliest one in this store's own
        insertion-order record wins (a strict `>` comparison is used
        while scanning in insertion order, so a later pattern only
        replaces the current best when its `reliability` is strictly
        greater).

        Returns `None` - never raises - when no stored pattern has
        that `task_id`, including for an unknown, empty, `None`, or
        any other non-matching `task_id` (comparison is the same
        plain `==` `get_for_task()` uses, so an unusual/unhashable
        `task_id` simply matches nothing rather than erroring)."""
        best = None
        for pattern_id in self._order:
            pattern = self._by_pattern_id[pattern_id]
            if pattern.task_id != task_id:
                continue
            if best is None or pattern.reliability > best.reliability:
                best = pattern
        return best

    def get_for_opportunity(self, opportunity_id):
        """Every stored `RevenueLearningPattern` whose
        `opportunity_id` exactly matches `opportunity_id`,
        oldest-first (insertion order), as a new list on every call -
        never a reference to this store's own internal collection, so
        mutating the returned list (or appending/removing from it)
        can never affect this store's own stored state. Never
        modifies any stored pattern.

        Returns an empty list - never raises - when no stored pattern
        has that `opportunity_id`, including for an unknown, empty,
        `None`, or any other non-matching `opportunity_id`
        (comparison is a plain `==` against each stored pattern's own
        `opportunity_id`, so an `opportunity_id` of an
        unusual/unhashable type simply matches nothing rather than
        erroring) - same shape as `get_for_task()`, keyed on
        `opportunity_id` instead of `task_id`."""
        return [
            self._by_pattern_id[pattern_id]
            for pattern_id in self._order
            if self._by_pattern_id[pattern_id].opportunity_id == opportunity_id
        ]

    def get_latest_for_opportunity(self, opportunity_id):
        """The most recently added stored `RevenueLearningPattern`
        whose `opportunity_id` exactly matches `opportunity_id` -
        "most recently added" meaning last in this store's own
        insertion-order record, exactly as `get_for_opportunity()`
        already orders its results, not `created_at` or any other
        field. Read-only - never modifies this store or any stored
        pattern.

        Returns `None` - never raises - when no stored pattern has
        that `opportunity_id`, including for an unknown, empty,
        `None`, or any other non-matching `opportunity_id`
        (comparison is the same plain `==` `get_for_opportunity()`
        uses, so an unusual/unhashable `opportunity_id` simply
        matches nothing rather than erroring) - same shape as
        `get_latest_for_task()`, keyed on `opportunity_id` instead of
        `task_id`."""
        latest = None
        for pattern_id in self._order:
            pattern = self._by_pattern_id[pattern_id]
            if pattern.opportunity_id == opportunity_id:
                latest = pattern
        return latest

    def get_latest_opportunity_pattern_summary(self, opportunity_id):
        """A short, structured summary of the most recently added
        stored `RevenueLearningPattern` whose `opportunity_id`
        exactly matches `opportunity_id` - built by calling
        `get_latest_for_opportunity()` (this store's own existing
        latest-for-opportunity lookup) and then that pattern's own
        `get_summary()` (financial/revenue_learning_pattern.py).
        Read-only - never modifies this store or any stored pattern.

        Always a new dict on every call (exactly what `get_summary()`
        itself already returns) - never a reference to any stored
        pattern's own state, so mutating the returned dict can never
        affect this store or any stored pattern.

        Returns `None` - never raises - when no stored pattern has
        that `opportunity_id`, including for an unknown, empty,
        `None`, or any other non-matching `opportunity_id` - same
        "matches nothing rather than erroring" behavior
        `get_latest_for_opportunity()` already provides, since this
        method simply calls `get_summary()` on whatever
        `get_latest_for_opportunity()` returns - same shape as
        `get_latest_task_pattern_summary()`, keyed on
        `opportunity_id` instead of `task_id`."""
        pattern = self.get_latest_for_opportunity(opportunity_id)
        if pattern is None:
            return None
        return pattern.get_summary()

    def get_highest_reliability_for_opportunity(self, opportunity_id):
        """The stored `RevenueLearningPattern` whose `opportunity_id`
        exactly matches `opportunity_id` and whose `reliability` is
        the highest among all such matches. Read-only - never
        modifies this store or any stored pattern.

        When several matching patterns share the same highest
        `reliability`, the earliest one in this store's own
        insertion-order record wins (a strict `>` comparison is used
        while scanning in insertion order, so a later pattern only
        replaces the current best when its `reliability` is strictly
        greater) - same tie-breaking rule as
        `get_highest_reliability_for_task()`.

        Returns `None` - never raises - when no stored pattern has
        that `opportunity_id`, including for an unknown, empty,
        `None`, or any other non-matching `opportunity_id`
        (comparison is the same plain `==` `get_for_opportunity()`
        uses, so an unusual/unhashable `opportunity_id` simply
        matches nothing rather than erroring)."""
        best = None
        for pattern_id in self._order:
            pattern = self._by_pattern_id[pattern_id]
            if pattern.opportunity_id != opportunity_id:
                continue
            if best is None or pattern.reliability > best.reliability:
                best = pattern
        return best

    def get_reliable_patterns(self, min_reliability=0.7):
        """Every stored `RevenueLearningPattern` whose `reliability`
        is greater than or equal to `min_reliability`, oldest-first
        (insertion order), as a new list on every call - never a
        reference to this store's own internal collection, so
        mutating the returned list can never affect this store's own
        stored state. Never modifies any stored pattern.

        `min_reliability` defaults to `0.7` and is meant to be a
        number between `0.0` and `1.0` inclusive (matching
        `RevenueLearningPattern.reliability`'s own range), with both
        boundary values themselves included in the comparison (a
        pattern with `reliability == min_reliability` is returned).
        No artificial maximum is imposed on how many patterns can be
        returned.

        Returns an empty list - never raises - when no stored pattern
        meets the threshold, when this store is empty, or when
        `min_reliability` is not a valid number (`None`, a string, a
        list, `NaN`, or any other non-numeric/invalid value) - an
        invalid threshold simply matches nothing rather than
        erroring."""
        try:
            threshold = float(min_reliability)
        except (TypeError, ValueError):
            return []
        if threshold != threshold:  # NaN never compares equal to itself
            return []
        return [
            self._by_pattern_id[pattern_id]
            for pattern_id in self._order
            if self._by_pattern_id[pattern_id].reliability >= threshold
        ]

    def get_reliable_for_task(self, task_id, min_reliability=0.7):
        """Every stored `RevenueLearningPattern` whose `task_id`
        exactly matches `task_id` and whose `reliability` is greater
        than or equal to `min_reliability`, oldest-first (insertion
        order), as a new list on every call - never a reference to
        this store's own internal collection, so mutating the
        returned list can never affect this store's own stored
        state. Never modifies any stored pattern.

        `min_reliability` defaults to `0.7` and is meant to be a
        number between `0.0` and `1.0` inclusive (matching
        `RevenueLearningPattern.reliability`'s own range), with both
        boundary values themselves included in the comparison (a
        pattern with `reliability == min_reliability` is returned).
        No artificial maximum is imposed on how many patterns can be
        returned.

        Returns an empty list - never raises - when no stored
        pattern has that `task_id`, when no matching pattern meets
        the threshold, when this store is empty, when `task_id` is
        unknown, empty, `None`, or any other non-matching/unusual
        (e.g. unhashable) value (comparison is the same plain `==`
        `get_for_task()` uses, so it simply matches nothing rather
        than erroring), or when `min_reliability` is not a valid
        number (`None`, a string, a list, `NaN`, or any other
        non-numeric/invalid value) - an invalid threshold simply
        matches nothing rather than erroring."""
        try:
            threshold = float(min_reliability)
        except (TypeError, ValueError):
            return []
        if threshold != threshold:  # NaN never compares equal to itself
            return []
        return [
            self._by_pattern_id[pattern_id]
            for pattern_id in self._order
            if self._by_pattern_id[pattern_id].task_id == task_id
            and self._by_pattern_id[pattern_id].reliability >= threshold
        ]

    def get_reliable_for_opportunity(self, opportunity_id, min_reliability=0.7):
        """Every stored `RevenueLearningPattern` whose
        `opportunity_id` exactly matches `opportunity_id` and whose
        `reliability` is greater than or equal to `min_reliability`,
        oldest-first (insertion order), as a new list on every call -
        never a reference to this store's own internal collection, so
        mutating the returned list can never affect this store's own
        stored state. Never modifies any stored pattern.

        `min_reliability` defaults to `0.7` and is meant to be a
        number between `0.0` and `1.0` inclusive (matching
        `RevenueLearningPattern.reliability`'s own range), with both
        boundary values themselves included in the comparison (a
        pattern with `reliability == min_reliability` is returned).
        No artificial maximum is imposed on how many patterns can be
        returned.

        Returns an empty list - never raises - when no stored
        pattern has that `opportunity_id`, when no matching pattern
        meets the threshold, when this store is empty, when
        `opportunity_id` is unknown, empty, `None`, or any other
        non-matching/unusual (e.g. unhashable) value (comparison is
        the same plain `==` `get_for_opportunity()` uses, so it
        simply matches nothing rather than erroring), or when
        `min_reliability` is not a valid number (`None`, a string, a
        list, `NaN`, or any other non-numeric/invalid value) - an
        invalid threshold simply matches nothing rather than
        erroring - same shape as `get_reliable_for_task()`, keyed on
        `opportunity_id` instead of `task_id`."""
        try:
            threshold = float(min_reliability)
        except (TypeError, ValueError):
            return []
        if threshold != threshold:  # NaN never compares equal to itself
            return []
        return [
            self._by_pattern_id[pattern_id]
            for pattern_id in self._order
            if self._by_pattern_id[pattern_id].opportunity_id == opportunity_id
            and self._by_pattern_id[pattern_id].reliability >= threshold
        ]

    def get_best_reliable_for_task(self, task_id, min_reliability=0.7):
        """The stored `RevenueLearningPattern` whose `task_id`
        exactly matches `task_id`, whose `reliability` is greater
        than or equal to `min_reliability`, and whose `reliability`
        is the highest among all such matches. Read-only - never
        modifies this store or any stored pattern.

        When several matching reliable patterns share the same
        highest `reliability`, the earliest one in this store's own
        insertion-order record wins (a strict `>` comparison is used
        while scanning in insertion order, so a later pattern only
        replaces the current best when its `reliability` is strictly
        greater) - same tie-breaking rule as
        `get_highest_reliability_for_task()`.

        `min_reliability` defaults to `0.7` and is meant to be a
        number between `0.0` and `1.0` inclusive (matching
        `RevenueLearningPattern.reliability`'s own range), with both
        boundary values themselves included in the comparison (a
        pattern with `reliability == min_reliability` is eligible).

        Returns `None` - never raises - when no stored pattern has
        that `task_id`, when no matching pattern meets the
        threshold, when this store is empty, when `task_id` is
        unknown, empty, `None`, or any other non-matching/unusual
        (e.g. unhashable) value (comparison is the same plain `==`
        `get_for_task()` uses, so it simply matches nothing rather
        than erroring), or when `min_reliability` is not a valid
        number (`None`, a string, a list, `NaN`, or any other
        non-numeric/invalid value) - an invalid threshold simply
        matches nothing rather than erroring."""
        try:
            threshold = float(min_reliability)
        except (TypeError, ValueError):
            return None
        if threshold != threshold:  # NaN never compares equal to itself
            return None
        best = None
        for pattern_id in self._order:
            pattern = self._by_pattern_id[pattern_id]
            if pattern.task_id != task_id:
                continue
            if pattern.reliability < threshold:
                continue
            if best is None or pattern.reliability > best.reliability:
                best = pattern
        return best

    def get_best_reliable_task_pattern_summary(self, task_id, min_reliability=0.7):
        """A short, structured summary of the stored
        `RevenueLearningPattern` returned by
        `get_best_reliable_for_task()` (this store's own existing
        best-reliable-for-task lookup) for `task_id` and
        `min_reliability` - built by calling that pattern's own
        `get_summary()` (financial/revenue_learning_pattern.py).
        Read-only - never modifies this store or any stored pattern.

        Always a new dict on every call (exactly what `get_summary()`
        itself already returns) - never a reference to any stored
        pattern's own state, so mutating the returned dict can never
        affect this store or any stored pattern.

        `min_reliability` defaults to `0.7` and behaves exactly as it
        does in `get_best_reliable_for_task()` - the same threshold,
        tie-breaking, and invalid-value handling apply here, since
        this method simply calls `get_summary()` on whatever
        `get_best_reliable_for_task()` returns.

        Returns `None` - never raises - in every case
        `get_best_reliable_for_task()` itself returns `None`
        (no matching `task_id`, no matching pattern meeting the
        threshold, an empty store, or an invalid `task_id`/
        `min_reliability`)."""
        pattern = self.get_best_reliable_for_task(task_id, min_reliability)
        if pattern is None:
            return None
        return pattern.get_summary()

    def get_best_reliable_for_opportunity(self, opportunity_id, min_reliability=0.7):
        """The stored `RevenueLearningPattern` whose `opportunity_id`
        exactly matches `opportunity_id`, whose `reliability` is
        greater than or equal to `min_reliability`, and whose
        `reliability` is the highest among all such matches.
        Read-only - never modifies this store or any stored pattern.

        When several matching reliable patterns share the same
        highest `reliability`, the earliest one in this store's own
        insertion-order record wins (a strict `>` comparison is used
        while scanning in insertion order, so a later pattern only
        replaces the current best when its `reliability` is strictly
        greater) - same tie-breaking rule as
        `get_best_reliable_for_task()` and
        `get_highest_reliability_for_opportunity()`.

        `min_reliability` defaults to `0.7` and is meant to be a
        number between `0.0` and `1.0` inclusive (matching
        `RevenueLearningPattern.reliability`'s own range), with both
        boundary values themselves included in the comparison (a
        pattern with `reliability == min_reliability` is eligible).

        Returns `None` - never raises - when no stored pattern has
        that `opportunity_id`, when no matching pattern meets the
        threshold, when this store is empty, when `opportunity_id`
        is unknown, empty, `None`, or any other non-matching/unusual
        (e.g. unhashable) value (comparison is the same plain `==`
        `get_for_opportunity()` uses, so it simply matches nothing
        rather than erroring), or when `min_reliability` is not a
        valid number (`None`, a string, a list, `NaN`, or any other
        non-numeric/invalid value) - an invalid threshold simply
        matches nothing rather than erroring - same shape as
        `get_best_reliable_for_task()`, keyed on `opportunity_id`
        instead of `task_id`."""
        try:
            threshold = float(min_reliability)
        except (TypeError, ValueError):
            return None
        if threshold != threshold:  # NaN never compares equal to itself
            return None
        best = None
        for pattern_id in self._order:
            pattern = self._by_pattern_id[pattern_id]
            if pattern.opportunity_id != opportunity_id:
                continue
            if pattern.reliability < threshold:
                continue
            if best is None or pattern.reliability > best.reliability:
                best = pattern
        return best

    def get_best_reliable_opportunity_pattern_summary(
        self, opportunity_id, min_reliability=0.7
    ):
        """A short, structured summary of the stored
        `RevenueLearningPattern` returned by
        `get_best_reliable_for_opportunity()` (this store's own
        existing best-reliable-for-opportunity lookup) for
        `opportunity_id` and `min_reliability` - built by calling
        that pattern's own `get_summary()` (financial/
        revenue_learning_pattern.py). Read-only - never modifies this
        store or any stored pattern.

        Always a new dict on every call (exactly what `get_summary()`
        itself already returns) - never a reference to any stored
        pattern's own state, so mutating the returned dict can never
        affect this store or any stored pattern.

        `min_reliability` defaults to `0.7` and behaves exactly as it
        does in `get_best_reliable_for_opportunity()` - the same
        threshold, tie-breaking, and invalid-value handling apply
        here, since this method simply calls `get_summary()` on
        whatever `get_best_reliable_for_opportunity()` returns.

        Returns `None` - never raises - in every case
        `get_best_reliable_for_opportunity()` itself returns `None`
        (no matching `opportunity_id`, no matching pattern meeting
        the threshold, an empty store, or an invalid
        `opportunity_id`/`min_reliability`) - same shape as
        `get_best_reliable_task_pattern_summary()`, keyed on
        `opportunity_id` instead of `task_id`."""
        pattern = self.get_best_reliable_for_opportunity(
            opportunity_id, min_reliability
        )
        if pattern is None:
            return None
        return pattern.get_summary()

    def has_pattern(self, pattern_id):
        """`True` if a pattern with exactly `pattern_id` is stored,
        `False` otherwise - including for an unknown, empty, `None`,
        or unhashable (e.g. a list or dict) `pattern_id`. A plain,
        read-only membership check - never raises, and never modifies
        this store's own state (matches this store's `pattern_id in
        self._by_pattern_id` check inside `add_pattern()`, exposed
        here as its own method)."""
        try:
            return pattern_id in self._by_pattern_id
        except TypeError:
            # Unhashable pattern_id (e.g. a list/dict) - can never
            # have been stored as a key, so simply not found.
            return False

    def __len__(self):
        return len(self._order)

    def count(self):
        """The current number of stored `RevenueLearningPattern`
        objects - `0` when this store is empty. A plain, read-only
        count - never raises, and never modifies this store's own
        state. No artificial maximum is imposed; this simply reports
        `len(self._order)` (matches `__len__`, exposed here as its
        own method)."""
        return len(self._order)

    def count_reliable_for_task(self, task_id, min_reliability=0.7):
        """The number of stored `RevenueLearningPattern` objects
        whose `task_id` exactly matches `task_id` and whose
        `reliability` is greater than or equal to `min_reliability` -
        built by calling this store's own existing
        `get_reliable_for_task()` and counting its result. A plain,
        read-only count - never raises, and never modifies this
        store's own state or any stored pattern.

        `min_reliability` defaults to `0.7` and behaves exactly as it
        does in `get_reliable_for_task()` - the same threshold and
        invalid-value handling apply here, since this method simply
        reports `len()` of whatever `get_reliable_for_task()`
        returns.

        Returns `0` - never raises - in every case
        `get_reliable_for_task()` itself returns an empty list (no
        matching `task_id`, no matching pattern meeting the
        threshold, an empty store, or an invalid `task_id`/
        `min_reliability`)."""
        return len(self.get_reliable_for_task(task_id, min_reliability))

    def has_reliable_for_task(self, task_id, min_reliability=0.7):
        """`True` if at least one stored `RevenueLearningPattern`
        whose `task_id` exactly matches `task_id` has a `reliability`
        greater than or equal to `min_reliability`, `False` otherwise -
        built by calling this store's own existing
        `count_reliable_for_task()` and checking whether it is
        greater than `0`. A plain, read-only check - never raises,
        and never modifies this store's own state or any stored
        pattern.

        `min_reliability` defaults to `0.7` and behaves exactly as it
        does in `count_reliable_for_task()` - the same threshold and
        invalid-value handling apply here.

        Returns `False` - never raises - in every case
        `count_reliable_for_task()` itself returns `0` (no matching
        `task_id`, no matching pattern meeting the threshold, an
        empty store, or an invalid `task_id`/`min_reliability`)."""
        return self.count_reliable_for_task(task_id, min_reliability) > 0

    def count_reliable_for_opportunity(self, opportunity_id, min_reliability=0.7):
        """The number of stored `RevenueLearningPattern` objects
        whose `opportunity_id` exactly matches `opportunity_id` and
        whose `reliability` is greater than or equal to
        `min_reliability` - built by calling this store's own
        existing `get_reliable_for_opportunity()` and counting its
        result. A plain, read-only count - never raises, and never
        modifies this store's own state or any stored pattern.

        `min_reliability` defaults to `0.7` and behaves exactly as it
        does in `get_reliable_for_opportunity()` - the same threshold
        and invalid-value handling apply here, since this method
        simply reports `len()` of whatever
        `get_reliable_for_opportunity()` returns.

        Returns `0` - never raises - in every case
        `get_reliable_for_opportunity()` itself returns an empty list
        (no matching `opportunity_id`, no matching pattern meeting
        the threshold, an empty store, or an invalid
        `opportunity_id`/`min_reliability`) - same shape as
        `count_reliable_for_task()`, keyed on `opportunity_id`
        instead of `task_id`."""
        return len(
            self.get_reliable_for_opportunity(opportunity_id, min_reliability)
        )

    def has_reliable_for_opportunity(self, opportunity_id, min_reliability=0.7):
        """`True` if at least one stored `RevenueLearningPattern`
        whose `opportunity_id` exactly matches `opportunity_id` has a
        `reliability` greater than or equal to `min_reliability`,
        `False` otherwise - built by calling this store's own
        existing `count_reliable_for_opportunity()` and checking
        whether it is greater than `0`. A plain, read-only check -
        never raises, and never modifies this store's own state or
        any stored pattern.

        `min_reliability` defaults to `0.7` and behaves exactly as it
        does in `count_reliable_for_opportunity()` - the same
        threshold and invalid-value handling apply here - same shape
        as `has_reliable_for_task()`, keyed on `opportunity_id`
        instead of `task_id`.

        Returns `False` - never raises - in every case
        `count_reliable_for_opportunity()` itself returns `0` (no
        matching `opportunity_id`, no matching pattern meeting the
        threshold, an empty store, or an invalid `opportunity_id`/
        `min_reliability`)."""
        return self.count_reliable_for_opportunity(opportunity_id, min_reliability) > 0

    def get_average_reliability_for_task(self, task_id):
        """The arithmetic mean of the `reliability` values of every
        stored `RevenueLearningPattern` whose `task_id` exactly
        matches `task_id` - built by calling this store's own
        existing `get_for_task()` and averaging the `reliability` of
        its result. A plain, read-only calculation - never raises,
        and never modifies this store's own state or any stored
        pattern.

        Always a `float`. Returns `0.0` - never raises - in every
        case `get_for_task()` itself returns an empty list (no
        matching `task_id`, an empty store, or an invalid/unusual
        `task_id`)."""
        patterns = self.get_for_task(task_id)
        if not patterns:
            return 0.0
        return sum(pattern.reliability for pattern in patterns) / len(patterns)

    def get_average_reliability_for_opportunity(self, opportunity_id):
        """The arithmetic mean of the `reliability` values of every
        stored `RevenueLearningPattern` whose `opportunity_id`
        exactly matches `opportunity_id` - built by calling this
        store's own existing `get_for_opportunity()` and averaging
        the `reliability` of its result. A plain, read-only
        calculation - never raises, and never modifies this store's
        own state or any stored pattern - same shape as
        `get_average_reliability_for_task()`, keyed on
        `opportunity_id` instead of `task_id`.

        Always a `float`. Returns `0.0` - never raises - in every
        case `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`)."""
        patterns = self.get_for_opportunity(opportunity_id)
        if not patterns:
            return 0.0
        return sum(pattern.reliability for pattern in patterns) / len(patterns)

    def get_max_reliability_for_task(self, task_id):
        """The highest `reliability` value among every stored
        `RevenueLearningPattern` whose `task_id` exactly matches
        `task_id` - built by calling this store's own existing
        `get_for_task()` and taking the maximum `reliability` of its
        result. A plain, read-only calculation - never raises, and
        never modifies this store's own state or any stored pattern.

        Always a `float`. Returns `0.0` - never raises - in every
        case `get_for_task()` itself returns an empty list (no
        matching `task_id`, an empty store, or an invalid/unusual
        `task_id`)."""
        patterns = self.get_for_task(task_id)
        if not patterns:
            return 0.0
        return max(pattern.reliability for pattern in patterns)

    def get_max_reliability_for_opportunity(self, opportunity_id):
        """The highest `reliability` value among every stored
        `RevenueLearningPattern` whose `opportunity_id` exactly
        matches `opportunity_id` - built by calling this store's own
        existing `get_for_opportunity()` and taking the maximum
        `reliability` of its result. A plain, read-only calculation -
        never raises, and never modifies this store's own state or
        any stored pattern - same shape as
        `get_max_reliability_for_task()`, keyed on `opportunity_id`
        instead of `task_id`.

        Always a `float`. Returns `0.0` - never raises - in every
        case `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`)."""
        patterns = self.get_for_opportunity(opportunity_id)
        if not patterns:
            return 0.0
        return max(pattern.reliability for pattern in patterns)

    def get_task_reliability_summary(self, task_id):
        """A short, structured summary of every stored
        `RevenueLearningPattern` whose `task_id` exactly matches
        `task_id` - built by calling this store's own existing
        `get_for_task()` and reducing its result to a `pattern_count`,
        an `average_reliability`, and a `highest_reliability`. A
        plain, read-only calculation - never raises, and never
        modifies this store's own state or any stored pattern.

        Always a new `dict` on every call, with exactly these keys:
        - `task_id`: `task_id` as given
        - `pattern_count`: `len()` of `get_for_task()`'s own result
        - `average_reliability`: the arithmetic mean of those
          patterns' `reliability` values (same as
          `get_average_reliability_for_task()`)
        - `highest_reliability`: the highest of those patterns'
          `reliability` values (same as
          `get_max_reliability_for_task()`)

        When `get_for_task()` itself returns an empty list (no
        matching `task_id`, an empty store, or an invalid/unusual
        `task_id`), `pattern_count` is `0` and both
        `average_reliability` and `highest_reliability` are `0.0`."""
        patterns = self.get_for_task(task_id)
        if not patterns:
            return {
                "task_id": task_id,
                "pattern_count": 0,
                "average_reliability": 0.0,
                "highest_reliability": 0.0,
            }
        reliabilities = [pattern.reliability for pattern in patterns]
        return {
            "task_id": task_id,
            "pattern_count": len(patterns),
            "average_reliability": sum(reliabilities) / len(reliabilities),
            "highest_reliability": max(reliabilities),
        }

    def get_opportunity_reliability_summary(self, opportunity_id):
        """A short, structured summary of every stored
        `RevenueLearningPattern` whose `opportunity_id` exactly
        matches `opportunity_id` - built by calling this store's own
        existing `get_for_opportunity()` and reducing its result to a
        `pattern_count`, an `average_reliability`, and a
        `highest_reliability`. A plain, read-only calculation - never
        raises, and never modifies this store's own state or any
        stored pattern - same shape as `get_task_reliability_summary()`,
        keyed on `opportunity_id` instead of `task_id`.

        Always a new `dict` on every call, with exactly these keys:
        - `opportunity_id`: `opportunity_id` as given
        - `pattern_count`: `len()` of `get_for_opportunity()`'s own
          result
        - `average_reliability`: the arithmetic mean of those
          patterns' `reliability` values (same as
          `get_average_reliability_for_opportunity()`)
        - `highest_reliability`: the highest of those patterns'
          `reliability` values (same as
          `get_max_reliability_for_opportunity()`)

        When `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`), `pattern_count` is `0` and
        both `average_reliability` and `highest_reliability` are
        `0.0`."""
        patterns = self.get_for_opportunity(opportunity_id)
        if not patterns:
            return {
                "opportunity_id": opportunity_id,
                "pattern_count": 0,
                "average_reliability": 0.0,
                "highest_reliability": 0.0,
            }
        reliabilities = [pattern.reliability for pattern in patterns]
        return {
            "opportunity_id": opportunity_id,
            "pattern_count": len(patterns),
            "average_reliability": sum(reliabilities) / len(reliabilities),
            "highest_reliability": max(reliabilities),
        }

    def is_task_reliable(self, task_id, min_reliability=0.7):
        """`True` if at least one stored `RevenueLearningPattern`
        whose `task_id` exactly matches `task_id` has a `reliability`
        greater than or equal to `min_reliability`, `False` otherwise -
        built by calling this store's own existing `get_for_task()`
        and checking whether any of its result meets the threshold. A
        plain, read-only check - never raises, and never modifies
        this store's own state or any stored pattern - same shape as
        `has_reliable_for_task()`.

        `min_reliability` defaults to `0.7`.

        Returns `False` - never raises - in every case `get_for_task()`
        itself returns an empty list (no matching `task_id`, no
        matching pattern meeting the threshold, an empty store, or an
        invalid `task_id`)."""
        patterns = self.get_for_task(task_id)
        return any(pattern.reliability >= min_reliability for pattern in patterns)

    def is_opportunity_reliable(self, opportunity_id, min_reliability=0.7):
        """`True` if at least one stored `RevenueLearningPattern`
        whose `opportunity_id` exactly matches `opportunity_id` has a
        `reliability` greater than or equal to `min_reliability`,
        `False` otherwise - built by calling this store's own
        existing `get_for_opportunity()` and checking whether any of
        its result meets the threshold. A plain, read-only check -
        never raises, and never modifies this store's own state or
        any stored pattern - same shape as `is_task_reliable()`, keyed
        on `opportunity_id` instead of `task_id`.

        `min_reliability` defaults to `0.7`.

        Returns `False` - never raises - in every case
        `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, no matching pattern meeting the
        threshold, an empty store, or an invalid `opportunity_id`)."""
        patterns = self.get_for_opportunity(opportunity_id)
        return any(pattern.reliability >= min_reliability for pattern in patterns)

    def get_task_reliability_status(self, task_id, min_reliability=0.7):
        """A short, structured status of every stored
        `RevenueLearningPattern` whose `task_id` exactly matches
        `task_id` - built by calling this store's own existing
        `get_for_task()` and reducing its result to a `pattern_count`,
        a `highest_reliability`, and an `is_reliable` flag. A plain,
        read-only calculation - never raises, and never modifies this
        store's own state or any stored pattern.

        Always a new `dict` on every call, with exactly these keys:
        - `task_id`: `task_id` as given
        - `pattern_count`: `len()` of `get_for_task()`'s own result
        - `highest_reliability`: the highest of those patterns'
          `reliability` values (same as
          `get_max_reliability_for_task()`)
        - `is_reliable`: `True` if at least one of those patterns has
          a `reliability` greater than or equal to `min_reliability`,
          `False` otherwise (same as `is_task_reliable()`)

        `min_reliability` defaults to `0.7` and behaves exactly as it
        does in `is_task_reliable()`.

        When `get_for_task()` itself returns an empty list (no
        matching `task_id`, an empty store, or an invalid/unusual
        `task_id`), `pattern_count` is `0`, `highest_reliability` is
        `0.0`, and `is_reliable` is `False`."""
        patterns = self.get_for_task(task_id)
        if not patterns:
            return {
                "task_id": task_id,
                "pattern_count": 0,
                "highest_reliability": 0.0,
                "is_reliable": False,
            }
        reliabilities = [pattern.reliability for pattern in patterns]
        return {
            "task_id": task_id,
            "pattern_count": len(patterns),
            "highest_reliability": max(reliabilities),
            "is_reliable": any(
                reliability >= min_reliability for reliability in reliabilities
            ),
        }

    def get_opportunity_reliability_status(self, opportunity_id, min_reliability=0.7):
        """A short, structured status of every stored
        `RevenueLearningPattern` whose `opportunity_id` exactly
        matches `opportunity_id` - built by calling this store's own
        existing `get_for_opportunity()` and reducing its result to a
        `pattern_count`, a `highest_reliability`, and an `is_reliable`
        flag. A plain, read-only calculation - never raises, and
        never modifies this store's own state or any stored pattern -
        same shape as `get_task_reliability_status()`, keyed on
        `opportunity_id` instead of `task_id`.

        Always a new `dict` on every call, with exactly these keys:
        - `opportunity_id`: `opportunity_id` as given
        - `pattern_count`: `len()` of `get_for_opportunity()`'s own
          result
        - `highest_reliability`: the highest of those patterns'
          `reliability` values (same as
          `get_max_reliability_for_opportunity()`)
        - `is_reliable`: `True` if at least one of those patterns has
          a `reliability` greater than or equal to `min_reliability`,
          `False` otherwise (same as `is_opportunity_reliable()`)

        `min_reliability` defaults to `0.7` and behaves exactly as it
        does in `is_opportunity_reliable()`.

        When `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`), `pattern_count` is `0`,
        `highest_reliability` is `0.0`, and `is_reliable` is
        `False`."""
        patterns = self.get_for_opportunity(opportunity_id)
        if not patterns:
            return {
                "opportunity_id": opportunity_id,
                "pattern_count": 0,
                "highest_reliability": 0.0,
                "is_reliable": False,
            }
        reliabilities = [pattern.reliability for pattern in patterns]
        return {
            "opportunity_id": opportunity_id,
            "pattern_count": len(patterns),
            "highest_reliability": max(reliabilities),
            "is_reliable": any(
                reliability >= min_reliability for reliability in reliabilities
            ),
        }

    def count_successful_for_task(self, task_id):
        """The number of stored `RevenueLearningPattern`s whose
        `task_id` exactly matches `task_id` and whose
        `successful_records` is greater than `0` - built by calling
        this store's own existing `get_for_task()` and counting how
        many of its result meet that condition. A plain, read-only
        calculation - never raises, and never modifies this store's
        own state or any stored pattern.

        Always an `int`. Returns `0` - never raises - in every case
        `get_for_task()` itself returns an empty list (no matching
        `task_id`, an empty store, or an invalid/unusual `task_id`),
        as well as when every matching pattern has a
        `successful_records` of `0`."""
        patterns = self.get_for_task(task_id)
        return sum(1 for pattern in patterns if pattern.successful_records > 0)

    def count_successful_for_opportunity(self, opportunity_id):
        """The number of stored `RevenueLearningPattern`s whose
        `opportunity_id` exactly matches `opportunity_id` and whose
        `successful_records` is greater than `0` - built by calling
        this store's own existing `get_for_opportunity()` and
        counting how many of its result meet that condition. A plain,
        read-only calculation - never raises, and never modifies this
        store's own state or any stored pattern - same shape as
        `count_successful_for_task()`, keyed on `opportunity_id`
        instead of `task_id`.

        Always an `int`. Returns `0` - never raises - in every case
        `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`), as well as when every
        matching pattern has a `successful_records` of `0`."""
        patterns = self.get_for_opportunity(opportunity_id)
        return sum(1 for pattern in patterns if pattern.successful_records > 0)

    def count_failed_for_task(self, task_id):
        """The number of stored `RevenueLearningPattern`s whose
        `task_id` exactly matches `task_id` and whose `failed_records`
        is greater than `0` - built by calling this store's own
        existing `get_for_task()` and counting how many of its result
        meet that condition. A plain, read-only calculation - never
        raises, and never modifies this store's own state or any
        stored pattern - same shape as `count_successful_for_task()`,
        checking `failed_records` instead of `successful_records`.

        Always an `int`. Returns `0` - never raises - in every case
        `get_for_task()` itself returns an empty list (no matching
        `task_id`, an empty store, or an invalid/unusual `task_id`),
        as well as when every matching pattern has a `failed_records`
        of `0`."""
        patterns = self.get_for_task(task_id)
        return sum(1 for pattern in patterns if pattern.failed_records > 0)

    def count_failed_for_opportunity(self, opportunity_id):
        """The number of stored `RevenueLearningPattern`s whose
        `opportunity_id` exactly matches `opportunity_id` and whose
        `failed_records` is greater than `0` - built by calling this
        store's own existing `get_for_opportunity()` and counting how
        many of its result meet that condition. A plain, read-only
        calculation - never raises, and never modifies this store's
        own state or any stored pattern - same shape as
        `count_failed_for_task()`, keyed on `opportunity_id` instead
        of `task_id`.

        Always an `int`. Returns `0` - never raises - in every case
        `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`), as well as when every
        matching pattern has a `failed_records` of `0`."""
        patterns = self.get_for_opportunity(opportunity_id)
        return sum(1 for pattern in patterns if pattern.failed_records > 0)

    def get_task_outcome_summary(self, task_id):
        """A short, structured summary of every stored
        `RevenueLearningPattern` whose `task_id` exactly matches
        `task_id` - built by calling this store's own existing
        `get_for_task()` and reducing its result to a `pattern_count`,
        a `successful_pattern_count`, a `failed_pattern_count`, a
        `total_successful_records`, and a `total_failed_records`. A
        plain, read-only calculation - never raises, and never
        modifies this store's own state or any stored pattern.

        Always a new `dict` on every call, with exactly these keys:
        - `task_id`: `task_id` as given
        - `pattern_count`: `len()` of `get_for_task()`'s own result
        - `successful_pattern_count`: how many of those patterns have
          a `successful_records` greater than `0` (same as
          `count_successful_for_task()`)
        - `failed_pattern_count`: how many of those patterns have a
          `failed_records` greater than `0` (same as
          `count_failed_for_task()`)
        - `total_successful_records`: the sum of those patterns'
          `successful_records` values
        - `total_failed_records`: the sum of those patterns'
          `failed_records` values

        When `get_for_task()` itself returns an empty list (no
        matching `task_id`, an empty store, or an invalid/unusual
        `task_id`), every numeric field is `0`."""
        patterns = self.get_for_task(task_id)
        if not patterns:
            return {
                "task_id": task_id,
                "pattern_count": 0,
                "successful_pattern_count": 0,
                "failed_pattern_count": 0,
                "total_successful_records": 0,
                "total_failed_records": 0,
            }
        return {
            "task_id": task_id,
            "pattern_count": len(patterns),
            "successful_pattern_count": sum(
                1 for pattern in patterns if pattern.successful_records > 0
            ),
            "failed_pattern_count": sum(
                1 for pattern in patterns if pattern.failed_records > 0
            ),
            "total_successful_records": sum(
                pattern.successful_records for pattern in patterns
            ),
            "total_failed_records": sum(
                pattern.failed_records for pattern in patterns
            ),
        }

    def get_opportunity_outcome_summary(self, opportunity_id):
        """A short, structured summary of every stored
        `RevenueLearningPattern` whose `opportunity_id` exactly
        matches `opportunity_id` - built by calling this store's own
        existing `get_for_opportunity()` and reducing its result to a
        `pattern_count`, a `successful_pattern_count`, a
        `failed_pattern_count`, a `total_successful_records`, and a
        `total_failed_records`. A plain, read-only calculation - never
        raises, and never modifies this store's own state or any
        stored pattern - same shape as `get_task_outcome_summary()`,
        keyed on `opportunity_id` instead of `task_id`.

        Always a new `dict` on every call, with exactly these keys:
        - `opportunity_id`: `opportunity_id` as given
        - `pattern_count`: `len()` of `get_for_opportunity()`'s own
          result
        - `successful_pattern_count`: how many of those patterns have
          a `successful_records` greater than `0` (same as
          `count_successful_for_opportunity()`)
        - `failed_pattern_count`: how many of those patterns have a
          `failed_records` greater than `0` (same as
          `count_failed_for_opportunity()`)
        - `total_successful_records`: the sum of those patterns'
          `successful_records` values
        - `total_failed_records`: the sum of those patterns'
          `failed_records` values

        When `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`), every numeric field is
        `0`."""
        patterns = self.get_for_opportunity(opportunity_id)
        if not patterns:
            return {
                "opportunity_id": opportunity_id,
                "pattern_count": 0,
                "successful_pattern_count": 0,
                "failed_pattern_count": 0,
                "total_successful_records": 0,
                "total_failed_records": 0,
            }
        return {
            "opportunity_id": opportunity_id,
            "pattern_count": len(patterns),
            "successful_pattern_count": sum(
                1 for pattern in patterns if pattern.successful_records > 0
            ),
            "failed_pattern_count": sum(
                1 for pattern in patterns if pattern.failed_records > 0
            ),
            "total_successful_records": sum(
                pattern.successful_records for pattern in patterns
            ),
            "total_failed_records": sum(
                pattern.failed_records for pattern in patterns
            ),
        }

    def has_successful_pattern_for_task(self, task_id):
        """`True` if at least one stored `RevenueLearningPattern`
        whose `task_id` exactly matches `task_id` has a
        `successful_records` greater than `0`, `False` otherwise -
        built by calling this store's own existing
        `count_successful_for_task()` and checking whether it is
        greater than `0`. A plain, read-only check - never raises,
        and never modifies this store's own state or any stored
        pattern.

        Returns `False` - never raises - in every case
        `count_successful_for_task()` itself returns `0` (no matching
        `task_id`, no matching pattern with a `successful_records`
        greater than `0`, an empty store, or an invalid/unusual
        `task_id`)."""
        return self.count_successful_for_task(task_id) > 0

    def has_successful_pattern_for_opportunity(self, opportunity_id):
        """`True` if at least one stored `RevenueLearningPattern`
        whose `opportunity_id` exactly matches `opportunity_id` has a
        `successful_records` greater than `0`, `False` otherwise -
        built by calling this store's own existing
        `count_successful_for_opportunity()` and checking whether it
        is greater than `0`. A plain, read-only check - never raises,
        and never modifies this store's own state or any stored
        pattern - same shape as `has_successful_pattern_for_task()`,
        keyed on `opportunity_id` instead of `task_id`.

        Returns `False` - never raises - in every case
        `count_successful_for_opportunity()` itself returns `0` (no
        matching `opportunity_id`, no matching pattern with a
        `successful_records` greater than `0`, an empty store, or an
        invalid/unusual `opportunity_id`)."""
        return self.count_successful_for_opportunity(opportunity_id) > 0

    def has_failed_pattern_for_task(self, task_id):
        """`True` if at least one stored `RevenueLearningPattern`
        whose `task_id` exactly matches `task_id` has a
        `failed_records` greater than `0`, `False` otherwise - built
        by calling this store's own existing
        `count_failed_for_task()` and checking whether it is greater
        than `0`. A plain, read-only check - never raises, and never
        modifies this store's own state or any stored pattern - same
        shape as `has_successful_pattern_for_task()`, checking
        `count_failed_for_task()` instead of
        `count_successful_for_task()`.

        Returns `False` - never raises - in every case
        `count_failed_for_task()` itself returns `0` (no matching
        `task_id`, no matching pattern with a `failed_records`
        greater than `0`, an empty store, or an invalid/unusual
        `task_id`)."""
        return self.count_failed_for_task(task_id) > 0

    def has_failed_pattern_for_opportunity(self, opportunity_id):
        """`True` if at least one stored `RevenueLearningPattern`
        whose `opportunity_id` exactly matches `opportunity_id` has a
        `failed_records` greater than `0`, `False` otherwise - built
        by calling this store's own existing
        `count_failed_for_opportunity()` and checking whether it is
        greater than `0`. A plain, read-only check - never raises,
        and never modifies this store's own state or any stored
        pattern - same shape as `has_failed_pattern_for_task()`, keyed
        on `opportunity_id` instead of `task_id`.

        Returns `False` - never raises - in every case
        `count_failed_for_opportunity()` itself returns `0` (no
        matching `opportunity_id`, no matching pattern with a
        `failed_records` greater than `0`, an empty store, or an
        invalid/unusual `opportunity_id`)."""
        return self.count_failed_for_opportunity(opportunity_id) > 0

    def get_task_learning_status(self, task_id):
        """A short, structured status of every stored
        `RevenueLearningPattern` whose `task_id` exactly matches
        `task_id` - built by calling this store's own existing
        `get_for_task()` and reducing its result to a `pattern_count`,
        a `has_success` flag, a `has_failure` flag, and a `status`
        label. A plain, read-only calculation - never raises, and
        never modifies this store's own state or any stored pattern.

        Always a new `dict` on every call, with exactly these keys:
        - `task_id`: `task_id` as given
        - `pattern_count`: `len()` of `get_for_task()`'s own result
        - `has_success`: `True` if at least one of those patterns has
          a `successful_records` greater than `0` (same as
          `has_successful_pattern_for_task()`)
        - `has_failure`: `True` if at least one of those patterns has
          a `failed_records` greater than `0` (same as
          `has_failed_pattern_for_task()`)
        - `status`: `"NO_DATA"` when `pattern_count` is `0`,
          `"SUCCESS"` when `has_success` is `True` and `has_failure`
          is `False`, `"FAILED"` when `has_failure` is `True` and
          `has_success` is `False`, otherwise `"MIXED"` (both
          `has_success` and `has_failure` are `True`)

        When `get_for_task()` itself returns an empty list (no
        matching `task_id`, an empty store, or an invalid/unusual
        `task_id`), `pattern_count` is `0`, both `has_success` and
        `has_failure` are `False`, and `status` is `"NO_DATA"`."""
        patterns = self.get_for_task(task_id)
        if not patterns:
            return {
                "task_id": task_id,
                "pattern_count": 0,
                "has_success": False,
                "has_failure": False,
                "status": "NO_DATA",
            }
        has_success = any(pattern.successful_records > 0 for pattern in patterns)
        has_failure = any(pattern.failed_records > 0 for pattern in patterns)
        if has_success and has_failure:
            status = "MIXED"
        elif has_success:
            status = "SUCCESS"
        elif has_failure:
            status = "FAILED"
        else:
            status = "NO_DATA"
        return {
            "task_id": task_id,
            "pattern_count": len(patterns),
            "has_success": has_success,
            "has_failure": has_failure,
            "status": status,
        }

    def get_opportunity_learning_status(self, opportunity_id):
        """A short, structured status of every stored
        `RevenueLearningPattern` whose `opportunity_id` exactly
        matches `opportunity_id` - built by calling this store's own
        existing `get_for_opportunity()` and reducing its result to a
        `pattern_count`, a `has_success` flag, a `has_failure` flag,
        and a `status` label. A plain, read-only calculation - never
        raises, and never modifies this store's own state or any
        stored pattern - same shape as `get_task_learning_status()`,
        keyed on `opportunity_id` instead of `task_id`.

        Always a new `dict` on every call, with exactly these keys:
        - `opportunity_id`: `opportunity_id` as given
        - `pattern_count`: `len()` of `get_for_opportunity()`'s own
          result
        - `has_success`: `True` if at least one of those patterns has
          a `successful_records` greater than `0` (same as
          `has_successful_pattern_for_opportunity()`)
        - `has_failure`: `True` if at least one of those patterns has
          a `failed_records` greater than `0` (same as
          `has_failed_pattern_for_opportunity()`)
        - `status`: `"NO_DATA"` when `pattern_count` is `0`,
          `"SUCCESS"` when `has_success` is `True` and `has_failure`
          is `False`, `"FAILED"` when `has_failure` is `True` and
          `has_success` is `False`, otherwise `"MIXED"` (both
          `has_success` and `has_failure` are `True`)

        When `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`), `pattern_count` is `0`,
        both `has_success` and `has_failure` are `False`, and
        `status` is `"NO_DATA"`."""
        patterns = self.get_for_opportunity(opportunity_id)
        if not patterns:
            return {
                "opportunity_id": opportunity_id,
                "pattern_count": 0,
                "has_success": False,
                "has_failure": False,
                "status": "NO_DATA",
            }
        has_success = any(pattern.successful_records > 0 for pattern in patterns)
        has_failure = any(pattern.failed_records > 0 for pattern in patterns)
        if has_success and has_failure:
            status = "MIXED"
        elif has_success:
            status = "SUCCESS"
        elif has_failure:
            status = "FAILED"
        else:
            status = "NO_DATA"
        return {
            "opportunity_id": opportunity_id,
            "pattern_count": len(patterns),
            "has_success": has_success,
            "has_failure": has_failure,
            "status": status,
        }

    def get_latest_successful_for_task(self, task_id):
        """The most recently added stored `RevenueLearningPattern`
        whose `task_id` exactly matches `task_id` and whose
        `successful_records` is greater than `0` - built by calling
        this store's own existing `get_for_task()` (already
        oldest-first, insertion-order) and taking the last matching
        result. Read-only - never modifies this store or any stored
        pattern.

        Returns `None` - never raises - when `get_for_task()` returns
        no pattern with a `successful_records` greater than `0`
        (including no matching `task_id`, an empty store, or an
        invalid/unusual `task_id`)."""
        latest = None
        for pattern in self.get_for_task(task_id):
            if pattern.successful_records > 0:
                latest = pattern
        return latest

    def get_latest_successful_for_opportunity(self, opportunity_id):
        """The most recently added stored `RevenueLearningPattern`
        whose `opportunity_id` exactly matches `opportunity_id` and
        whose `successful_records` is greater than `0` - built by
        calling this store's own existing `get_for_opportunity()`
        (already oldest-first, insertion-order) and taking the last
        matching result. Read-only - never modifies this store or any
        stored pattern - same shape as
        `get_latest_successful_for_task()`, keyed on `opportunity_id`
        instead of `task_id`.

        Returns `None` - never raises - when `get_for_opportunity()`
        returns no pattern with a `successful_records` greater than
        `0` (including no matching `opportunity_id`, an empty store,
        or an invalid/unusual `opportunity_id`)."""
        latest = None
        for pattern in self.get_for_opportunity(opportunity_id):
            if pattern.successful_records > 0:
                latest = pattern
        return latest

    def get_latest_failed_for_task(self, task_id):
        """The most recently added stored `RevenueLearningPattern`
        whose `task_id` exactly matches `task_id` and whose
        `failed_records` is greater than `0` - built by calling this
        store's own existing `get_for_task()` (already oldest-first,
        insertion-order) and taking the last matching result.
        Read-only - never modifies this store or any stored pattern -
        same shape as `get_latest_successful_for_task()`, checking
        `failed_records` instead of `successful_records`.

        Returns `None` - never raises - when `get_for_task()` returns
        no pattern with a `failed_records` greater than `0`
        (including no matching `task_id`, an empty store, or an
        invalid/unusual `task_id`)."""
        latest = None
        for pattern in self.get_for_task(task_id):
            if pattern.failed_records > 0:
                latest = pattern
        return latest

    def get_latest_failed_for_opportunity(self, opportunity_id):
        """The most recently added stored `RevenueLearningPattern`
        whose `opportunity_id` exactly matches `opportunity_id` and
        whose `failed_records` is greater than `0` - built by calling
        this store's own existing `get_for_opportunity()` (already
        oldest-first, insertion-order) and taking the last matching
        result. Read-only - never modifies this store or any stored
        pattern - same shape as `get_latest_failed_for_task()`, keyed
        on `opportunity_id` instead of `task_id`.

        Returns `None` - never raises - when `get_for_opportunity()`
        returns no pattern with a `failed_records` greater than `0`
        (including no matching `opportunity_id`, an empty store, or
        an invalid/unusual `opportunity_id`)."""
        latest = None
        for pattern in self.get_for_opportunity(opportunity_id):
            if pattern.failed_records > 0:
                latest = pattern
        return latest

    def get_success_rate_for_task(self, task_id):
        """The aggregate success rate across every stored
        `RevenueLearningPattern` whose `task_id` exactly matches
        `task_id` - built by calling this store's own existing
        `get_for_task()`, summing `successful_records` and
        `failed_records` across its result, and dividing the
        successful sum by the two sums added together. A plain,
        read-only calculation - never raises, and never modifies this
        store's own state or any stored pattern.

        Always a `float` between `0.0` and `1.0`. Returns `0.0` -
        never raises - when the summed `successful_records` and
        `failed_records` total `0` (including when `get_for_task()`
        itself returns an empty list - no matching `task_id`, an
        empty store, or an invalid/unusual `task_id`)."""
        patterns = self.get_for_task(task_id)
        successful = sum(pattern.successful_records for pattern in patterns)
        failed = sum(pattern.failed_records for pattern in patterns)
        total = successful + failed
        if total == 0:
            return 0.0
        return successful / total

    def get_success_rate_for_opportunity(self, opportunity_id):
        """The aggregate success rate across every stored
        `RevenueLearningPattern` whose `opportunity_id` exactly
        matches `opportunity_id` - built by calling this store's own
        existing `get_for_opportunity()`, summing
        `successful_records` and `failed_records` across its result,
        and dividing the successful sum by the two sums added
        together. A plain, read-only calculation - never raises, and
        never modifies this store's own state or any stored pattern -
        same shape as `get_success_rate_for_task()`, keyed on
        `opportunity_id` instead of `task_id`.

        Always a `float` between `0.0` and `1.0`. Returns `0.0` -
        never raises - when the summed `successful_records` and
        `failed_records` total `0` (including when
        `get_for_opportunity()` itself returns an empty list - no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`)."""
        patterns = self.get_for_opportunity(opportunity_id)
        successful = sum(pattern.successful_records for pattern in patterns)
        failed = sum(pattern.failed_records for pattern in patterns)
        total = successful + failed
        if total == 0:
            return 0.0
        return successful / total

    def get_total_records_for_task(self, task_id):
        """The total record count across every stored
        `RevenueLearningPattern` whose `task_id` exactly matches
        `task_id` - built by calling this store's own existing
        `get_for_task()` and summing `successful_records` and
        `failed_records` across its result. A plain, read-only
        calculation - never raises, and never modifies this store's
        own state or any stored pattern.

        Always an `int`. Returns `0` - never raises - when
        `get_for_task()` itself returns an empty list (no matching
        `task_id`, an empty store, or an invalid/unusual `task_id`)."""
        patterns = self.get_for_task(task_id)
        return sum(pattern.successful_records for pattern in patterns) + sum(
            pattern.failed_records for pattern in patterns
        )

    def get_total_records_for_opportunity(self, opportunity_id):
        """The total record count across every stored
        `RevenueLearningPattern` whose `opportunity_id` exactly
        matches `opportunity_id` - built by calling this store's own
        existing `get_for_opportunity()` and summing
        `successful_records` and `failed_records` across its result.
        A plain, read-only calculation - never raises, and never
        modifies this store's own state or any stored pattern - same
        shape as `get_total_records_for_task()`, keyed on
        `opportunity_id` instead of `task_id`.

        Always an `int`. Returns `0` - never raises - when
        `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`)."""
        patterns = self.get_for_opportunity(opportunity_id)
        return sum(pattern.successful_records for pattern in patterns) + sum(
            pattern.failed_records for pattern in patterns
        )

    def get_task_learning_summary(self, task_id):
        """A short, structured summary of every stored
        `RevenueLearningPattern` whose `task_id` exactly matches
        `task_id` - built by calling this store's own existing
        `get_for_task()`, `get_total_records_for_task()`, and
        `get_success_rate_for_task()`. A plain, read-only
        calculation - never raises, and never modifies this store's
        own state or any stored pattern.

        Always a new `dict` on every call, with exactly these keys:
        - `task_id`: `task_id` as given
        - `pattern_count`: `len()` of `get_for_task()`'s own result
        - `total_records`: `get_total_records_for_task()`'s own
          result
        - `success_rate`: `get_success_rate_for_task()`'s own result
          (`0.0` when `total_records` is `0`)

        When `get_for_task()` itself returns an empty list (no
        matching `task_id`, an empty store, or an invalid/unusual
        `task_id`), `pattern_count` and `total_records` are `0` and
        `success_rate` is `0.0`."""
        patterns = self.get_for_task(task_id)
        return {
            "task_id": task_id,
            "pattern_count": len(patterns),
            "total_records": self.get_total_records_for_task(task_id),
            "success_rate": self.get_success_rate_for_task(task_id),
        }

    def get_opportunity_learning_summary(self, opportunity_id):
        """A short, structured summary of every stored
        `RevenueLearningPattern` whose `opportunity_id` exactly
        matches `opportunity_id` - built by calling this store's own
        existing `get_for_opportunity()`,
        `get_total_records_for_opportunity()`, and
        `get_success_rate_for_opportunity()`. A plain, read-only
        calculation - never raises, and never modifies this store's
        own state or any stored pattern - same shape as
        `get_task_learning_summary()`, keyed on `opportunity_id`
        instead of `task_id`.

        Always a new `dict` on every call, with exactly these keys:
        - `opportunity_id`: `opportunity_id` as given
        - `pattern_count`: `len()` of `get_for_opportunity()`'s own
          result
        - `total_records`: `get_total_records_for_opportunity()`'s
          own result
        - `success_rate`: `get_success_rate_for_opportunity()`'s own
          result (`0.0` when `total_records` is `0`)

        When `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`), `pattern_count` and
        `total_records` are `0` and `success_rate` is `0.0`."""
        patterns = self.get_for_opportunity(opportunity_id)
        return {
            "opportunity_id": opportunity_id,
            "pattern_count": len(patterns),
            "total_records": self.get_total_records_for_opportunity(
                opportunity_id
            ),
            "success_rate": self.get_success_rate_for_opportunity(
                opportunity_id
            ),
        }

    def get_learning_summary_for_pattern(self, pattern_id):
        """A short, structured summary of the single stored
        `RevenueLearningPattern` whose `pattern_id` exactly matches
        `pattern_id` - built by calling this store's own existing
        `get_pattern()` and reading that pattern's own
        `total_records`, `success_rate`, `reliability`, and
        `is_reliable()` (financial/revenue_learning_pattern.py, using
        its default threshold). Read-only - never modifies this store
        or the pattern.

        Returns a new `dict` on success, with exactly these keys:
        - `pattern_id`: `pattern_id` as given
        - `total_records`: the pattern's own `total_records`
        - `success_rate`: the pattern's own `success_rate`
        - `reliability`: the pattern's own `reliability`
        - `is_reliable`: the pattern's own `is_reliable()` result,
          using its default `min_reliability` threshold

        Returns `None` - never raises - when `get_pattern()` itself
        returns `None` (no stored pattern with that `pattern_id`,
        including for an unknown, empty, `None`, or any other
        non-matching `pattern_id`)."""
        pattern = self.get_pattern(pattern_id)
        if pattern is None:
            return None
        return {
            "pattern_id": pattern_id,
            "total_records": pattern.total_records,
            "success_rate": pattern.success_rate,
            "reliability": pattern.reliability,
            "is_reliable": pattern.is_reliable(),
        }

    def get_reliable_pattern_summary_for_opportunity(
        self, opportunity_id, min_reliability=0.7
    ):
        """A short, structured summary of how many stored
        `RevenueLearningPattern`s whose `opportunity_id` exactly
        matches `opportunity_id` meet a `reliability` threshold -
        built by calling this store's own existing
        `get_for_opportunity()`, `count_reliable_for_opportunity()`,
        and `has_reliable_for_opportunity()`. A plain, read-only
        calculation - never raises, and never modifies this store's
        own state or any stored pattern.

        Always a new `dict` on every call, with exactly these keys:
        - `opportunity_id`: `opportunity_id` as given
        - `pattern_count`: `len()` of `get_for_opportunity()`'s own
          result
        - `reliable_pattern_count`:
          `count_reliable_for_opportunity()`'s own result
        - `min_reliability`: `min_reliability` as given
        - `has_reliable_pattern`: `has_reliable_for_opportunity()`'s
          own result (`True` exactly when `reliable_pattern_count` is
          greater than `0`)

        When `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`), `pattern_count` and
        `reliable_pattern_count` are `0` and `has_reliable_pattern` is
        `False`."""
        patterns = self.get_for_opportunity(opportunity_id)
        return {
            "opportunity_id": opportunity_id,
            "pattern_count": len(patterns),
            "reliable_pattern_count": self.count_reliable_for_opportunity(
                opportunity_id, min_reliability
            ),
            "min_reliability": min_reliability,
            "has_reliable_pattern": self.has_reliable_for_opportunity(
                opportunity_id, min_reliability
            ),
        }

    def get_reliable_pattern_summary_for_task(
        self, task_id, min_reliability=0.7
    ):
        """A short, structured summary of how many stored
        `RevenueLearningPattern`s whose `task_id` exactly matches
        `task_id` meet a `reliability` threshold - built by calling
        this store's own existing `get_for_task()`,
        `count_reliable_for_task()`, and `has_reliable_for_task()`. A
        plain, read-only calculation - never raises, and never
        modifies this store's own state or any stored pattern - same
        shape as `get_reliable_pattern_summary_for_opportunity()`,
        keyed on `task_id` instead of `opportunity_id`.

        Always a new `dict` on every call, with exactly these keys:
        - `task_id`: `task_id` as given
        - `pattern_count`: `len()` of `get_for_task()`'s own result
        - `reliable_pattern_count`: `count_reliable_for_task()`'s own
          result
        - `min_reliability`: `min_reliability` as given
        - `has_reliable_pattern`: `has_reliable_for_task()`'s own
          result (`True` exactly when `reliable_pattern_count` is
          greater than `0`)

        When `get_for_task()` itself returns an empty list (no
        matching `task_id`, an empty store, or an invalid/unusual
        `task_id`), `pattern_count` and `reliable_pattern_count` are
        `0` and `has_reliable_pattern` is `False`."""
        patterns = self.get_for_task(task_id)
        return {
            "task_id": task_id,
            "pattern_count": len(patterns),
            "reliable_pattern_count": self.count_reliable_for_task(
                task_id, min_reliability
            ),
            "min_reliability": min_reliability,
            "has_reliable_pattern": self.has_reliable_for_task(
                task_id, min_reliability
            ),
        }

    def get_most_reliable_for_opportunity(self, opportunity_id):
        """The stored `RevenueLearningPattern` whose `opportunity_id`
        exactly matches `opportunity_id` and whose `reliability` is
        the highest among all such matches - built by scanning this
        store's own existing `get_for_opportunity()` result (already
        insertion-order) and keeping the pattern with the highest
        `reliability` seen so far. Read-only - never modifies this
        store or any stored pattern - same result as
        `get_highest_reliability_for_opportunity()`.

        When several matching patterns share the same highest
        `reliability`, the earliest one in `get_for_opportunity()`'s
        own insertion-order result wins (a strict `>` comparison is
        used while scanning, so a later pattern only replaces the
        current best when its `reliability` is strictly greater).

        Returns `None` - never raises - when `get_for_opportunity()`
        itself returns an empty list (no matching `opportunity_id`,
        an empty store, or an invalid/unusual `opportunity_id`)."""
        best = None
        for pattern in self.get_for_opportunity(opportunity_id):
            if best is None or pattern.reliability > best.reliability:
                best = pattern
        return best

    def get_most_reliable_for_task(self, task_id):
        """The stored `RevenueLearningPattern` whose `task_id`
        exactly matches `task_id` and whose `reliability` is the
        highest among all such matches - built by scanning this
        store's own existing `get_for_task()` result (already
        insertion-order) and keeping the pattern with the highest
        `reliability` seen so far. Read-only - never modifies this
        store or any stored pattern - same result as
        `get_highest_reliability_for_task()`, and same shape as
        `get_most_reliable_for_opportunity()`, keyed on `task_id`
        instead of `opportunity_id`.

        When several matching patterns share the same highest
        `reliability`, the earliest one in `get_for_task()`'s own
        insertion-order result wins (a strict `>` comparison is used
        while scanning, so a later pattern only replaces the current
        best when its `reliability` is strictly greater).

        Returns `None` - never raises - when `get_for_task()` itself
        returns an empty list (no matching `task_id`, an empty store,
        or an invalid/unusual `task_id`)."""
        best = None
        for pattern in self.get_for_task(task_id):
            if best is None or pattern.reliability > best.reliability:
                best = pattern
        return best

    def get_pattern_reliability_report(self, pattern_id):
        """A short, structured reliability report for the single
        stored `RevenueLearningPattern` whose `pattern_id` exactly
        matches `pattern_id` - built by calling this store's own
        existing `get_pattern()` and reading that pattern's own
        `task_id`, `opportunity_id`, `reliability`, `total_records`,
        `successful_records`, `failed_records`, and `is_reliable()`
        (financial/revenue_learning_pattern.py, using its default
        threshold). Read-only - never modifies this store or the
        pattern.

        Returns a new `dict` on success, with exactly these keys:
        - `pattern_id`: `pattern_id` as given
        - `task_id`: the pattern's own `task_id`
        - `opportunity_id`: the pattern's own `opportunity_id`
        - `reliability`: the pattern's own `reliability`
        - `total_records`: the pattern's own `total_records`
        - `successful_records`: the pattern's own `successful_records`
        - `failed_records`: the pattern's own `failed_records`
        - `is_reliable`: the pattern's own `is_reliable()` result,
          using its default `min_reliability` threshold

        Returns `None` - never raises - when `get_pattern()` itself
        returns `None` (no stored pattern with that `pattern_id`,
        including for an unknown, empty, `None`, or any other
        non-matching `pattern_id`)."""
        pattern = self.get_pattern(pattern_id)
        if pattern is None:
            return None
        return {
            "pattern_id": pattern_id,
            "task_id": pattern.task_id,
            "opportunity_id": pattern.opportunity_id,
            "reliability": pattern.reliability,
            "total_records": pattern.total_records,
            "successful_records": pattern.successful_records,
            "failed_records": pattern.failed_records,
            "is_reliable": pattern.is_reliable(),
        }

    def get_pattern_reliability_reports_for_task(self, task_id):
        """A list of reliability reports for every stored
        `RevenueLearningPattern` whose `task_id` exactly matches
        `task_id` - built by calling this store's own existing
        `get_for_task()` (already insertion-order) and mapping each
        of its results through `get_pattern_reliability_report()`.
        Read-only - never modifies this store or any stored pattern.

        Always a new `list`, in the same insertion order
        `get_for_task()` itself already returns. Returns an empty
        `list` - never raises - when `get_for_task()` itself returns
        an empty list (no matching `task_id`, an empty store, or an
        invalid/unusual `task_id`)."""
        return [
            self.get_pattern_reliability_report(pattern.pattern_id)
            for pattern in self.get_for_task(task_id)
        ]

    def get_pattern_reliability_reports_for_opportunity(self, opportunity_id):
        """A list of reliability reports for every stored
        `RevenueLearningPattern` whose `opportunity_id` exactly
        matches `opportunity_id` - built by calling this store's own
        existing `get_for_opportunity()` (already insertion-order)
        and mapping each of its results through
        `get_pattern_reliability_report()`. Read-only - never
        modifies this store or any stored pattern - same shape as
        `get_pattern_reliability_reports_for_task()`, keyed on
        `opportunity_id` instead of `task_id`.

        Always a new `list`, in the same insertion order
        `get_for_opportunity()` itself already returns. Returns an
        empty `list` - never raises - when `get_for_opportunity()`
        itself returns an empty list (no matching `opportunity_id`,
        an empty store, or an invalid/unusual `opportunity_id`)."""
        return [
            self.get_pattern_reliability_report(pattern.pattern_id)
            for pattern in self.get_for_opportunity(opportunity_id)
        ]

    def get_mixed_patterns(self):
        """Every stored `RevenueLearningPattern` whose
        `successful_records` is greater than `0` and whose
        `failed_records` is also greater than `0` - built by
        filtering this store's own existing `get_all()` (already
        insertion-order). Read-only - never modifies this store or
        any stored pattern.

        Always a new `list`, in the same insertion order `get_all()`
        itself already returns - never a reference to this store's
        own internal collection, so mutating the returned list can
        never affect this store's own stored state. Returns an empty
        `list` - never raises - when this store is empty or no stored
        pattern has both a `successful_records` and a `failed_records`
        greater than `0`."""
        return [
            pattern
            for pattern in self.get_all()
            if pattern.successful_records > 0 and pattern.failed_records > 0
        ]

    def count_mixed_patterns(self):
        """The number of stored `RevenueLearningPattern`s whose
        `successful_records` is greater than `0` and whose
        `failed_records` is also greater than `0` - built by calling
        this store's own existing `get_mixed_patterns()` and taking
        its `len()`. A plain, read-only calculation - never raises,
        and never modifies this store's own state or any stored
        pattern.

        Always an `int`. Returns `0` - never raises - when this store
        is empty or no stored pattern has both a `successful_records`
        and a `failed_records` greater than `0`."""
        return len(self.get_mixed_patterns())

    def get_success_only_patterns(self):
        """Every stored `RevenueLearningPattern` whose
        `successful_records` is greater than `0` and whose
        `failed_records` is exactly `0` - built by filtering this
        store's own existing `get_all()` (already insertion-order).
        Read-only - never modifies this store or any stored pattern -
        same shape as `get_mixed_patterns()`, checking for a purely
        successful record split instead of a mixed one.

        Always a new `list`, in the same insertion order `get_all()`
        itself already returns - never a reference to this store's
        own internal collection, so mutating the returned list can
        never affect this store's own stored state. Returns an empty
        `list` - never raises - when this store is empty or no stored
        pattern has a `successful_records` greater than `0` with a
        `failed_records` of exactly `0`."""
        return [
            pattern
            for pattern in self.get_all()
            if pattern.successful_records > 0 and pattern.failed_records == 0
        ]

    def get_failure_only_patterns(self):
        """Every stored `RevenueLearningPattern` whose
        `failed_records` is greater than `0` and whose
        `successful_records` is exactly `0` - built by filtering
        this store's own existing `get_all()` (already
        insertion-order). Read-only - never modifies this store or
        any stored pattern - same shape as
        `get_success_only_patterns()`, checking for a purely failed
        record split instead of a purely successful one.

        Always a new `list`, in the same insertion order `get_all()`
        itself already returns - never a reference to this store's
        own internal collection, so mutating the returned list can
        never affect this store's own stored state. Returns an empty
        `list` - never raises - when this store is empty or no stored
        pattern has a `failed_records` greater than `0` with a
        `successful_records` of exactly `0`."""
        return [
            pattern
            for pattern in self.get_all()
            if pattern.failed_records > 0 and pattern.successful_records == 0
        ]

    def get_no_outcome_patterns(self):
        """Every stored `RevenueLearningPattern` whose
        `successful_records` is exactly `0` and whose
        `failed_records` is also exactly `0` - built by filtering
        this store's own existing `get_all()` (already
        insertion-order). Read-only - never modifies this store or
        any stored pattern - same shape as
        `get_success_only_patterns()` and `get_failure_only_patterns()`,
        checking for an entirely empty record split instead of a
        purely successful or purely failed one.

        Always a new `list`, in the same insertion order `get_all()`
        itself already returns - never a reference to this store's
        own internal collection, so mutating the returned list can
        never affect this store's own stored state. Returns an empty
        `list` - never raises - when this store is empty or no stored
        pattern has both a `successful_records` and a `failed_records`
        of exactly `0`."""
        return [
            pattern
            for pattern in self.get_all()
            if pattern.successful_records == 0 and pattern.failed_records == 0
        ]

    def get_patterns_with_outcomes(self):
        """Every stored `RevenueLearningPattern` whose
        `successful_records` is greater than `0` or whose
        `failed_records` is greater than `0` - built by filtering
        this store's own existing `get_all()` (already
        insertion-order). Read-only - never modifies this store or
        any stored pattern - the complement of
        `get_no_outcome_patterns()`.

        Always a new `list`, in the same insertion order `get_all()`
        itself already returns - never a reference to this store's
        own internal collection, so mutating the returned list can
        never affect this store's own stored state. Returns an empty
        `list` - never raises - when this store is empty or every
        stored pattern has both a `successful_records` and a
        `failed_records` of exactly `0`."""
        return [
            pattern
            for pattern in self.get_all()
            if pattern.successful_records > 0 or pattern.failed_records > 0
        ]

    def get_reliable_patterns_with_outcomes(self, min_reliability=0.7):
        """Every stored `RevenueLearningPattern` from this store's
        own existing `get_patterns_with_outcomes()` (a
        `successful_records` greater than `0` or a `failed_records`
        greater than `0`) whose `reliability` is also greater than or
        equal to `min_reliability`, in the same insertion order
        `get_patterns_with_outcomes()` itself already returns. Read-
        only - never modifies this store or any stored pattern.

        `min_reliability` defaults to `0.7` and follows this store's
        own existing `get_reliable_patterns()` threshold handling: a
        number between `0.0` and `1.0` inclusive (matching
        `RevenueLearningPattern.reliability`'s own range), with both
        boundary values themselves included in the comparison (a
        pattern with `reliability == min_reliability` is returned);
        an invalid threshold (`None`, a string, a list, `NaN`, or any
        other non-numeric/invalid value) simply matches nothing
        rather than erroring.

        Always a new `list` - never a reference to this store's own
        internal collection, so mutating the returned list can never
        affect this store's own stored state. Returns an empty
        `list` - never raises - when this store is empty, when no
        stored pattern has any outcome recorded, when no matching
        pattern meets the threshold, or when `min_reliability` is
        invalid."""
        try:
            threshold = float(min_reliability)
        except (TypeError, ValueError):
            return []
        if threshold != threshold:  # NaN never compares equal to itself
            return []
        return [
            pattern
            for pattern in self.get_patterns_with_outcomes()
            if pattern.reliability >= threshold
        ]

    def get_most_reliable_pattern(self):
        """The stored `RevenueLearningPattern` whose `reliability` is
        the highest among every stored pattern - built by scanning
        this store's own existing `get_all()` (already
        insertion-order). Considers all stored patterns, regardless
        of `task_id`, `opportunity_id`, or outcome. Read-only - never
        modifies this store or any stored pattern.

        When several patterns share the same highest `reliability`,
        the earliest one in `get_all()`'s own insertion-order result
        wins (a strict `>` comparison is used while scanning, so a
        later pattern only replaces the current best when its
        `reliability` is strictly greater) - same tie-break
        convention as `get_highest_reliability_for_task()` and
        `get_highest_reliability_for_opportunity()`.

        Returns `None` - never raises - when this store is empty."""
        best = None
        for pattern in self.get_all():
            if best is None or pattern.reliability > best.reliability:
                best = pattern
        return best

    def get_least_reliable_pattern_with_outcomes(self):
        """The `RevenueLearningPattern` whose `reliability` is the
        lowest among this store's own existing
        `get_patterns_with_outcomes()` result (a `successful_records`
        greater than `0` or a `failed_records` greater than `0`) -
        built by scanning that result in its own insertion order.
        Read-only - never modifies this store or any stored pattern.

        When several matching patterns share the same lowest
        `reliability`, the earliest one in
        `get_patterns_with_outcomes()`'s own insertion-order result
        wins (a strict `<` comparison is used while scanning, so a
        later pattern only replaces the current best when its
        `reliability` is strictly lower) - the same tie-break
        convention `get_most_reliable_pattern()` and
        `get_highest_reliability_for_task()` use, applied to the
        lowest value instead of the highest.

        Returns `None` - never raises - when this store is empty or
        when `get_patterns_with_outcomes()` itself returns an empty
        list (no stored pattern has any outcome recorded)."""
        worst = None
        for pattern in self.get_patterns_with_outcomes():
            if worst is None or pattern.reliability < worst.reliability:
                worst = pattern
        return worst

    def get_average_reliability_with_outcomes(self):
        """The arithmetic mean of the `reliability` values of this
        store's own existing `get_patterns_with_outcomes()` result (a
        `successful_records` greater than `0` or a `failed_records`
        greater than `0`) - built by calling that method and
        averaging the `reliability` of its result, each value used
        exactly as stored. A plain, read-only calculation - never
        raises, and never modifies this store's own state or any
        stored pattern - same shape as
        `get_average_reliability_for_task()`, considering patterns
        with an outcome instead of a `task_id` match.

        Always a `float`. Returns `0.0` - never raises - when this
        store is empty or when `get_patterns_with_outcomes()` itself
        returns an empty list (no stored pattern has any outcome
        recorded)."""
        patterns = self.get_patterns_with_outcomes()
        if not patterns:
            return 0.0
        return sum(pattern.reliability for pattern in patterns) / len(patterns)

    def get_overall_success_rate_with_outcomes(self):
        """The aggregate success rate across this store's own
        existing `get_patterns_with_outcomes()` result (a
        `successful_records` greater than `0` or a `failed_records`
        greater than `0`) - built by calling that method, summing
        `successful_records` and `failed_records` across its result,
        and dividing the successful sum by the two sums added
        together. A plain, read-only calculation - never raises, and
        never modifies this store's own state or any stored pattern -
        same shape as `get_success_rate_for_task()`, considering
        patterns with an outcome instead of a `task_id` match.

        Always a `float` between `0.0` and `1.0`. Returns `0.0` -
        never raises - when the summed `successful_records` and
        `failed_records` total `0` (including when this store is
        empty or when `get_patterns_with_outcomes()` itself returns
        an empty list - no stored pattern has any outcome
        recorded)."""
        patterns = self.get_patterns_with_outcomes()
        successful = sum(pattern.successful_records for pattern in patterns)
        failed = sum(pattern.failed_records for pattern in patterns)
        total = successful + failed
        if total == 0:
            return 0.0
        return successful / total

    def get_overall_pattern_summary(self):
        """A short, structured summary of every stored
        `RevenueLearningPattern` - built by calling this store's own
        existing `get_all()`, `get_patterns_with_outcomes()`,
        `get_success_only_patterns()`, `get_failure_only_patterns()`,
        `get_mixed_patterns()`, and `get_no_outcome_patterns()`, and
        reducing each of their results to a plain count via `len()`.
        A plain, read-only calculation - never raises, and never
        modifies this store's own state or any stored pattern.

        Always a new `dict` on every call, with exactly these keys:
        - `pattern_count`: `len()` of `get_all()`'s own result
        - `patterns_with_outcomes`: `len()` of
          `get_patterns_with_outcomes()`'s own result
        - `success_only_count`: `len()` of
          `get_success_only_patterns()`'s own result
        - `failure_only_count`: `len()` of
          `get_failure_only_patterns()`'s own result
        - `mixed_count`: `len()` of `get_mixed_patterns()`'s own
          result
        - `no_outcome_count`: `len()` of
          `get_no_outcome_patterns()`'s own result

        Every value is `0` - never raises - when this store is
        empty."""
        return {
            "pattern_count": len(self.get_all()),
            "patterns_with_outcomes": len(self.get_patterns_with_outcomes()),
            "success_only_count": len(self.get_success_only_patterns()),
            "failure_only_count": len(self.get_failure_only_patterns()),
            "mixed_count": len(self.get_mixed_patterns()),
            "no_outcome_count": len(self.get_no_outcome_patterns()),
        }

    def has_usable_learning_data(self):
        """`True` if at least one stored `RevenueLearningPattern` has
        a `successful_records` greater than `0` or a `failed_records`
        greater than `0`, `False` otherwise - built by calling this
        store's own existing `get_patterns_with_outcomes()` and
        checking whether its result is non-empty. A plain, read-only
        check - never raises, and never modifies this store's own
        state or any stored pattern.

        Always a real `bool`. Returns `False` - never raises - when
        this store is empty or when `get_patterns_with_outcomes()`
        itself returns an empty list (no stored pattern has any
        outcome recorded)."""
        return bool(self.get_patterns_with_outcomes())

    def has_reliable_learning_data(self, min_reliability=0.7):
        """`True` if at least one stored `RevenueLearningPattern` has
        a `successful_records` greater than `0` or a `failed_records`
        greater than `0`, and a `reliability` greater than or equal
        to `min_reliability`, `False` otherwise - built by calling
        this store's own existing `get_reliable_patterns_with_outcomes()`
        and checking whether its result is non-empty. A plain,
        read-only check - never raises, and never modifies this
        store's own state or any stored pattern.

        `min_reliability` defaults to `0.7` and follows this store's
        own existing `get_reliable_patterns_with_outcomes()`
        threshold handling - the same threshold and invalid-value
        handling apply here - same shape as `has_usable_learning_data()`,
        additionally requiring the threshold to be met.

        Always a real `bool`. Returns `False` - never raises - when
        this store is empty, when no stored pattern has any outcome
        recorded, when no matching pattern meets the threshold, or
        when `min_reliability` is invalid."""
        return bool(self.get_reliable_patterns_with_outcomes(min_reliability))

    def get_learning_data_status(self, min_reliability=0.7):
        """A short, structured status of this store's own overall
        learning data - built by calling this store's own existing
        `has_usable_learning_data()`, `has_reliable_learning_data()`,
        `get_all()`, `get_patterns_with_outcomes()`, and
        `get_reliable_patterns_with_outcomes()`, and reducing them to
        two booleans and three counts. A plain, read-only
        calculation - never raises, and never modifies this store's
        own state or any stored pattern.

        Always a new `dict` on every call, with exactly these keys:
        - `has_usable_data`: this store's own existing
          `has_usable_learning_data()` result
        - `has_reliable_data`: this store's own existing
          `has_reliable_learning_data(min_reliability)` result
        - `pattern_count`: `len()` of `get_all()`'s own result
        - `patterns_with_outcomes`: `len()` of
          `get_patterns_with_outcomes()`'s own result
        - `reliable_pattern_count`: `len()` of
          `get_reliable_patterns_with_outcomes(min_reliability)`'s
          own result

        `min_reliability` defaults to `0.7` and follows this store's
        own existing `get_reliable_patterns_with_outcomes()`
        threshold handling for both `has_reliable_data` and
        `reliable_pattern_count` - the same threshold and
        invalid-value handling apply here.

        Every count is `0` and both booleans are `False` - never
        raises - when this store is empty."""
        return {
            "has_usable_data": self.has_usable_learning_data(),
            "has_reliable_data": self.has_reliable_learning_data(
                min_reliability
            ),
            "pattern_count": len(self.get_all()),
            "patterns_with_outcomes": len(self.get_patterns_with_outcomes()),
            "reliable_pattern_count": len(
                self.get_reliable_patterns_with_outcomes(min_reliability)
            ),
        }

    def get_reliable_successful_patterns(self, min_reliability=0.7):
        """Every stored `RevenueLearningPattern` from this store's
        own existing `get_success_only_patterns()` (a
        `successful_records` greater than `0` and a `failed_records`
        of exactly `0`) whose `reliability` is also greater than or
        equal to `min_reliability`, in the same insertion order
        `get_success_only_patterns()` itself already returns. Read-
        only - never modifies this store or any stored pattern.

        `min_reliability` defaults to `0.7` and follows this store's
        own existing `get_reliable_patterns_with_outcomes()`
        threshold handling: a number between `0.0` and `1.0`
        inclusive (matching `RevenueLearningPattern.reliability`'s
        own range), with both boundary values themselves included in
        the comparison (a pattern with `reliability ==
        min_reliability` is returned); an invalid threshold (`None`,
        a string, a list, `NaN`, or any other non-numeric/invalid
        value) simply matches nothing rather than erroring.

        Always a new `list` - never a reference to this store's own
        internal collection, so mutating the returned list can never
        affect this store's own stored state. Returns an empty
        `list` - never raises - when this store is empty, when no
        stored pattern is success-only, when no matching pattern
        meets the threshold, or when `min_reliability` is invalid."""
        try:
            threshold = float(min_reliability)
        except (TypeError, ValueError):
            return []
        if threshold != threshold:  # NaN never compares equal to itself
            return []
        return [
            pattern
            for pattern in self.get_success_only_patterns()
            if pattern.reliability >= threshold
        ]

    def get_reliable_failure_patterns(self, min_reliability=0.7):
        """Every stored `RevenueLearningPattern` from this store's
        own existing `get_failure_only_patterns()` (a
        `failed_records` greater than `0` and a `successful_records`
        of exactly `0`) whose `reliability` is also greater than or
        equal to `min_reliability`, in the same insertion order
        `get_failure_only_patterns()` itself already returns. Read-
        only - never modifies this store or any stored pattern - same
        shape as `get_reliable_successful_patterns()`, restricted to
        failure-only patterns instead of success-only patterns.

        `min_reliability` defaults to `0.7` and follows this store's
        own existing `get_reliable_patterns_with_outcomes()`
        threshold handling: a number between `0.0` and `1.0`
        inclusive (matching `RevenueLearningPattern.reliability`'s
        own range), with both boundary values themselves included in
        the comparison (a pattern with `reliability ==
        min_reliability` is returned); an invalid threshold (`None`,
        a string, a list, `NaN`, or any other non-numeric/invalid
        value) simply matches nothing rather than erroring.

        Always a new `list` - never a reference to this store's own
        internal collection, so mutating the returned list can never
        affect this store's own stored state. Returns an empty
        `list` - never raises - when this store is empty, when no
        stored pattern is failure-only, when no matching pattern
        meets the threshold, or when `min_reliability` is invalid."""
        try:
            threshold = float(min_reliability)
        except (TypeError, ValueError):
            return []
        if threshold != threshold:  # NaN never compares equal to itself
            return []
        return [
            pattern
            for pattern in self.get_failure_only_patterns()
            if pattern.reliability >= threshold
        ]

    def get_reliable_mixed_patterns(self, min_reliability=0.7):
        """Every stored `RevenueLearningPattern` from this store's
        own existing `get_mixed_patterns()` (a `successful_records`
        greater than `0` and a `failed_records` also greater than
        `0`) whose `reliability` is also greater than or equal to
        `min_reliability`, in the same insertion order
        `get_mixed_patterns()` itself already returns. Read-only -
        never modifies this store or any stored pattern - same shape
        as `get_reliable_successful_patterns()` and
        `get_reliable_failure_patterns()`, restricted to mixed
        patterns instead of success-only or failure-only patterns.

        `min_reliability` defaults to `0.7` and follows this store's
        own existing `get_reliable_patterns_with_outcomes()`
        threshold handling: a number between `0.0` and `1.0`
        inclusive (matching `RevenueLearningPattern.reliability`'s
        own range), with both boundary values themselves included in
        the comparison (a pattern with `reliability ==
        min_reliability` is returned); an invalid threshold (`None`,
        a string, a list, `NaN`, or any other non-numeric/invalid
        value) simply matches nothing rather than erroring.

        Always a new `list` - never a reference to this store's own
        internal collection, so mutating the returned list can never
        affect this store's own stored state. Returns an empty
        `list` - never raises - when this store is empty, when no
        stored pattern is mixed, when no matching pattern meets the
        threshold, or when `min_reliability` is invalid."""
        try:
            threshold = float(min_reliability)
        except (TypeError, ValueError):
            return []
        if threshold != threshold:  # NaN never compares equal to itself
            return []
        return [
            pattern
            for pattern in self.get_mixed_patterns()
            if pattern.reliability >= threshold
        ]

    def get_pattern_record_count(self, pattern_id):
        """The total outcome-record count for the stored
        `RevenueLearningPattern` whose `pattern_id` exactly matches
        `pattern_id` - built by calling this store's own existing
        `get_pattern()` and summing its `successful_records` and
        `failed_records`. Read-only - never modifies this store or
        any stored pattern.

        Always a plain `int`. Returns `0` - never raises - when no
        stored pattern has that `pattern_id` (including an unknown,
        empty, `None`, or any other non-matching `pattern_id`,
        following `get_pattern()`'s own matching rules), and also
        when the matching pattern has no outcome records (both
        `successful_records` and `failed_records` are `0`)."""
        pattern = self.get_pattern(pattern_id)
        if pattern is None:
            return 0
        return pattern.successful_records + pattern.failed_records

    def get_task_outcome_counts(self, task_id):
        """A short, structured dict of the raw outcome-record totals
        for every stored `RevenueLearningPattern` whose `task_id`
        exactly matches `task_id` - built by calling this store's
        own existing `get_for_task()` and summing `successful_records`
        and `failed_records` across its result. A plain, read-only
        calculation - never raises, and never modifies this store's
        own state or any stored pattern.

        Always a new `dict` on every call, with exactly these keys:
        - `task_id`: `task_id` as given
        - `successful_records`: the sum of `get_for_task()`'s own
          result's `successful_records` values
        - `failed_records`: the sum of `get_for_task()`'s own
          result's `failed_records` values
        - `total_records`: `successful_records` plus `failed_records`

        When `get_for_task()` itself returns an empty list (no
        matching `task_id`, an empty store, or an invalid/unusual
        `task_id`), every numeric field is `0`."""
        patterns = self.get_for_task(task_id)
        successful_records = sum(
            pattern.successful_records for pattern in patterns
        )
        failed_records = sum(pattern.failed_records for pattern in patterns)
        return {
            "task_id": task_id,
            "successful_records": successful_records,
            "failed_records": failed_records,
            "total_records": successful_records + failed_records,
        }

    def get_opportunity_outcome_counts(self, opportunity_id):
        """A short, structured dict of the raw outcome-record totals
        for every stored `RevenueLearningPattern` whose
        `opportunity_id` exactly matches `opportunity_id` - built by
        calling this store's own existing `get_for_opportunity()` and
        summing `successful_records` and `failed_records` across its
        result. A plain, read-only calculation - never raises, and
        never modifies this store's own state or any stored pattern -
        same shape as `get_task_outcome_counts()`, keyed on
        `opportunity_id` instead of `task_id`.

        Always a new `dict` on every call, with exactly these keys:
        - `opportunity_id`: `opportunity_id` as given
        - `successful_records`: the sum of `get_for_opportunity()`'s
          own result's `successful_records` values
        - `failed_records`: the sum of `get_for_opportunity()`'s own
          result's `failed_records` values
        - `total_records`: `successful_records` plus `failed_records`

        When `get_for_opportunity()` itself returns an empty list (no
        matching `opportunity_id`, an empty store, or an
        invalid/unusual `opportunity_id`), every numeric field is
        `0`."""
        patterns = self.get_for_opportunity(opportunity_id)
        successful_records = sum(
            pattern.successful_records for pattern in patterns
        )
        failed_records = sum(pattern.failed_records for pattern in patterns)
        return {
            "opportunity_id": opportunity_id,
            "successful_records": successful_records,
            "failed_records": failed_records,
            "total_records": successful_records + failed_records,
        }

    def get_most_observed_pattern(self):
        """The stored `RevenueLearningPattern` with the highest total
        outcome-record count among every stored pattern that has any
        outcome records at all - built by scanning this store's own
        existing `get_patterns_with_outcomes()` (already
        insertion-order) and comparing each pattern's
        `successful_records` plus `failed_records`. Considers all
        matching patterns, regardless of `task_id` or
        `opportunity_id`. Read-only - never modifies this store or
        any stored pattern.

        When several patterns share the same highest total record
        count, the earliest one in `get_patterns_with_outcomes()`'s
        own insertion-order result wins (a strict `>` comparison is
        used while scanning, so a later pattern only replaces the
        current best when its total is strictly greater) - same
        tie-break convention as `get_most_reliable_pattern()`.

        Returns `None` - never raises - when this store is empty or
        no stored pattern has any outcome records (every pattern has
        both a `successful_records` and a `failed_records` of exactly
        `0`)."""
        best = None
        best_total = None
        for pattern in self.get_patterns_with_outcomes():
            total = pattern.successful_records + pattern.failed_records
            if best is None or total > best_total:
                best = pattern
                best_total = total
        return best

    def get_least_observed_pattern_with_outcomes(self):
        """The stored `RevenueLearningPattern` with the lowest total
        outcome-record count among every stored pattern that has any
        outcome records at all - built by scanning this store's own
        existing `get_patterns_with_outcomes()` (already
        insertion-order) and comparing each pattern's
        `successful_records` plus `failed_records`. Considers all
        matching patterns, regardless of `task_id` or
        `opportunity_id`. Read-only - never modifies this store or
        any stored pattern - same shape as
        `get_most_observed_pattern()`, selecting the lowest total
        instead of the highest.

        When several patterns share the same lowest total record
        count, the earliest one in `get_patterns_with_outcomes()`'s
        own insertion-order result wins (a strict `<` comparison is
        used while scanning, so a later pattern only replaces the
        current worst when its total is strictly lower) - the same
        tie-break convention `get_most_observed_pattern()` and
        `get_least_reliable_pattern_with_outcomes()` use, applied to
        the lowest value instead of the highest.

        Returns `None` - never raises - when this store is empty or
        no stored pattern has any outcome records (every pattern has
        both a `successful_records` and a `failed_records` of exactly
        `0`)."""
        worst = None
        worst_total = None
        for pattern in self.get_patterns_with_outcomes():
            total = pattern.successful_records + pattern.failed_records
            if worst is None or total < worst_total:
                worst = pattern
                worst_total = total
        return worst

    def get_low_reliability_observed_patterns(
        self, min_records=2, max_reliability=0.5
    ):
        """Every stored `RevenueLearningPattern` whose total outcome-
        record count (`successful_records` plus `failed_records`) is
        greater than or equal to `min_records` and whose `reliability`
        is also less than or equal to `max_reliability` - built by
        filtering this store's own existing `get_all()` (already
        insertion-order). Read-only - never modifies this store or
        any stored pattern.

        `min_records` defaults to `2` and is treated as an integer
        threshold (an inclusive lower bound on the total record
        count); `max_reliability` defaults to `0.5` and follows this
        store's own existing `get_reliable_patterns_with_outcomes()`
        threshold handling: a number between `0.0` and `1.0`
        inclusive (matching `RevenueLearningPattern.reliability`'s
        own range), with the boundary value itself included in the
        comparison (a pattern with `reliability == max_reliability`
        is returned); an invalid `max_reliability` (`None`, a string,
        a list, `NaN`, or any other non-numeric/invalid value) simply
        matches nothing rather than erroring - same for an invalid
        `min_records` (`None`, a string, a list, `NaN`, or any other
        non-numeric/invalid value).

        Always a new `list`, in the same insertion order `get_all()`
        itself already returns - never a reference to this store's
        own internal collection, so mutating the returned list can
        never affect this store's own stored state. Returns an empty
        `list` - never raises - when this store is empty, when no
        stored pattern meets both thresholds, or when `min_records`
        or `max_reliability` is invalid."""
        try:
            records_threshold = int(min_records)
        except (TypeError, ValueError):
            return []
        try:
            reliability_threshold = float(max_reliability)
        except (TypeError, ValueError):
            return []
        if reliability_threshold != reliability_threshold:  # NaN check
            return []
        return [
            pattern
            for pattern in self.get_all()
            if (pattern.successful_records + pattern.failed_records)
            >= records_threshold
            and pattern.reliability <= reliability_threshold
        ]

    def get_high_confidence_observed_patterns(
        self, min_records=2, min_reliability=0.7
    ):
        """Every stored `RevenueLearningPattern` whose total outcome-
        record count (`successful_records` plus `failed_records`) is
        greater than or equal to `min_records` and whose `reliability`
        is also greater than or equal to `min_reliability` - built by
        filtering this store's own existing `get_all()` (already
        insertion-order). Read-only - never modifies this store or
        any stored pattern - same shape as
        `get_low_reliability_observed_patterns()`, requiring a
        reliability at or above a threshold instead of at or below
        one.

        `min_records` defaults to `2` and is treated as an integer
        threshold (an inclusive lower bound on the total record
        count); `min_reliability` defaults to `0.7` and follows this
        store's own existing `get_reliable_patterns_with_outcomes()`
        threshold handling: a number between `0.0` and `1.0`
        inclusive (matching `RevenueLearningPattern.reliability`'s
        own range), with the boundary value itself included in the
        comparison (a pattern with `reliability == min_reliability`
        is returned); an invalid `min_reliability` (`None`, a string,
        a list, `NaN`, or any other non-numeric/invalid value) simply
        matches nothing rather than erroring - same for an invalid
        `min_records` (`None`, a string, a list, `NaN`, or any other
        non-numeric/invalid value).

        Always a new `list`, in the same insertion order `get_all()`
        itself already returns - never a reference to this store's
        own internal collection, so mutating the returned list can
        never affect this store's own stored state. Returns an empty
        `list` - never raises - when this store is empty, when no
        stored pattern meets both thresholds, or when `min_records`
        or `min_reliability` is invalid."""
        try:
            records_threshold = int(min_records)
        except (TypeError, ValueError):
            return []
        try:
            reliability_threshold = float(min_reliability)
        except (TypeError, ValueError):
            return []
        if reliability_threshold != reliability_threshold:  # NaN check
            return []
        return [
            pattern
            for pattern in self.get_all()
            if (pattern.successful_records + pattern.failed_records)
            >= records_threshold
            and pattern.reliability >= reliability_threshold
        ]

    # ------------------------------------------------------------------
    # Clearing
    # ------------------------------------------------------------------
    def clear(self):
        """Remove every stored `RevenueLearningPattern` from this
        store. After this call, `count()` returns `0`, `get_all()`
        returns an empty list, and `has_pattern()`/`get_pattern()`
        behave exactly as they do for any other empty store. Never
        raises, including when this store is already empty. Only
        this store's own `pattern_id -> pattern` mapping and
        insertion-order record are reset - the `RevenueLearningPattern`
        objects that were stored are themselves left completely
        untouched (this store never owned or mutated them in the
        first place; it only ever held references to them)."""
        self._by_pattern_id.clear()
        self._order.clear()
