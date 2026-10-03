"""
Learning Analyzer
===================
`LearningAnalyzer` is a small, stateless summarizer for a batch of
`LearningRecord` objects (learning/learning_record.py):

    [LearningRecord, ...] -> LearningAnalyzer.analyze() -> summary dict
    LearningRecordStore -> LearningAnalyzer.analyze_store() -> summary dict
    [LearningRecord, ...] -> LearningAnalyzer.get_pattern_success_rate()
        -> success rate float

This is deliberately observation only - it computes a few plain
numbers about a batch of records a caller already has (e.g. from
`LearningRecordStore.get_all()`/`find_by_pattern()`), and nothing else.
It never mutates a record, never touches `LearningRecordStore`'s own
internal state, never decides *whether* something should be learned
(that is `learning/learning_decision.py`'s job), and never changes a
plan, skill, capability, or any other part of this project on its own
initiative - same "read-only, no side effects" boundary
`LearningRecordStore`'s own read methods (`get_all`, `find_by_pattern`,
`get_pattern_confidence`, ...) already keep.
"""


class LearningAnalyzer:
    """Stateless: holds no data of its own between calls, so a single
    instance can safely be shared/reused across callers, or a fresh
    one created per call - both behave identically."""

    def analyze(self, records):
        """Summarize `records` (an iterable of `LearningRecord`
        objects) into a plain dict:

            {
                "total_records": <int>,
                "average_confidence": <float>,
                "highest_confidence": <float>,
            }

        Any entry that isn't a `LearningRecord` reporting `is_valid()`
        is silently ignored - never raises for a malformed batch, same
        "ignore what's invalid rather than fail the whole calculation"
        convention `LearningRecordStore.get_pattern_confidence` already
        follows for its own average. `total_records` counts only the
        valid records actually used in the averages, not the raw
        length of `records`.

        `records=None` or an empty/all-invalid list both yield
        `{"total_records": 0, "average_confidence": 0.0,
        "highest_confidence": 0.0}` - never raises. Never mutates any
        record and never reads or writes any `LearningRecordStore`.
        """
        from .learning_record import LearningRecord

        confidences = [
            record.confidence
            for record in (records or [])
            if isinstance(record, LearningRecord) and record.is_valid()
        ]

        if not confidences:
            return {
                "total_records": 0,
                "average_confidence": 0.0,
                "highest_confidence": 0.0,
            }

        return {
            "total_records": len(confidences),
            "average_confidence": sum(confidences) / len(confidences),
            "highest_confidence": max(confidences),
        }

    def analyze_store(self, store):
        """Convenience wrapper: read every record currently in `store`
        via its own `get_all()` (already returning safe copies - see
        `LearningRecordStore.get_all`) and run them through `analyze`.
        Returns the exact same summary dict `analyze` would return for
        that list - the normal zero-value summary when `store` is
        empty.

        Never mutates `store` or any record; only ever calls
        `store.get_all()`. Not connected to plans, execution,
        capabilities, or self-upgrade - it only knows how to read a
        `LearningRecordStore` and summarize what it returns."""
        return self.analyze(store.get_all())

    def get_pattern_success_rate(self, records, pattern):
        """The success rate - a plain `float` between `0.0` and `1.0`
        - among the valid `records` whose `pattern` exactly matches
        `pattern`:

            success_rate = successful / (successful + failed)

        Only records that are actual `LearningRecord` instances
        reporting `is_valid()` and whose `pattern` matches are
        considered at all (same "ignore what's invalid" convention
        `analyze`/`LearningRecordStore.get_pattern_confidence` already
        follow). Among those, only an `outcome` of exactly
        `"success"` or exactly `"failure"` counts toward the rate -
        any other outcome value is ignored entirely (neither helps nor
        hurts the rate).

        Returns `0.0` - never raises - when there are no matching
        success/failure records at all (including for an empty/`None`
        `records`, or a `pattern` that matches nothing). This is pure
        observation: it never mutates a record or `LearningRecordStore`,
        and never predicts or changes any future behavior."""
        from .learning_record import LearningRecord

        successes = 0
        failures = 0
        for record in (records or []):
            if not isinstance(record, LearningRecord) or not record.is_valid():
                continue
            if record.pattern != pattern:
                continue
            if record.outcome == "success":
                successes += 1
            elif record.outcome == "failure":
                failures += 1

        total = successes + failures
        if total == 0:
            return 0.0
        return successes / total

    def get_pattern_report(self, records, pattern):
        """A small read-only report about `pattern` within `records`:

            {
                "pattern": <the pattern argument, unchanged>,
                "total_records": <int>,
                "success_count": <int>,
                "failure_count": <int>,
                "success_rate": <float, 0.0-1.0>,
                "average_confidence": <float>,
            }

        Same filtering as `get_pattern_success_rate`: only actual
        `LearningRecord` instances reporting `is_valid()` whose
        `pattern` matches `pattern` exactly are considered, and among
        those only an `outcome` of exactly `"success"` or exactly
        `"failure"` counts - `total_records`, `success_count`,
        `failure_count`, and `average_confidence` are all computed
        over that same success/failure subset (any other outcome is
        ignored entirely, same as `get_pattern_success_rate`).
        `success_rate` reuses `get_pattern_success_rate` directly.

        Returns all-zero counts/rates (with `pattern` still set) for
        an empty/`None` `records`, or a `pattern` that matches no
        success/failure records - never raises. Pure observation: does
        not mutate any record or `LearningRecordStore`, and does not
        predict or change any future behavior."""
        from .learning_record import LearningRecord

        matching = []
        for record in (records or []):
            if not isinstance(record, LearningRecord) or not record.is_valid():
                continue
            if record.pattern != pattern:
                continue
            if record.outcome in ("success", "failure"):
                matching.append(record)

        success_count = sum(1 for record in matching if record.outcome == "success")
        failure_count = sum(1 for record in matching if record.outcome == "failure")

        if not matching:
            average_confidence = 0.0
        else:
            average_confidence = sum(record.confidence for record in matching) / len(matching)

        return {
            "pattern": pattern,
            "total_records": len(matching),
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": self.get_pattern_success_rate(records, pattern),
            "average_confidence": average_confidence,
        }

    def is_pattern_reliable(self, records, pattern, min_confidence=0.7, min_records=2):
        """Plain `bool`: whether `pattern` looks reliable within
        `records`, based on `get_pattern_report`.

        `True` only when both hold:
          1. `get_pattern_report(records, pattern)["total_records"] >=
             min_records` (enough valid success/failure records for
             `pattern` - not just a nonzero count)
          2. that report's `average_confidence >= min_confidence`

        `False` otherwise - including for an empty/`None` `records` or
        a `pattern` with fewer than `min_records` matching
        success/failure records, same "no/not enough data means
        nothing to call reliable" stance as `get_pattern_success_rate`'s
        `0.0` default.

        `min_confidence` must be a plain number (not `bool`) between
        `0.0` and `1.0` inclusive; anything else raises `ValueError`.
        `min_records` must be a plain `int` (not `bool`) `>= 1`;
        anything else raises `ValueError`. The default `min_records=2`
        keeps a single record from counting as reliable on its own -
        existing callers that only passed `records`/`pattern`/
        `min_confidence` keep working unchanged since both new-ish
        parameters are keyword-defaulted.

        Pure observation, same as `get_pattern_report`: never mutates
        a record or `LearningRecordStore`, and never itself decides to
        change any plan, skill, or future behavior - it only answers
        the yes/no reliability question a caller can choose to act on
        elsewhere."""
        if isinstance(min_confidence, bool) or not isinstance(min_confidence, (int, float)):
            raise ValueError("min_confidence must be a number between 0.0 and 1.0")
        if not (0.0 <= min_confidence <= 1.0):
            raise ValueError("min_confidence must be between 0.0 and 1.0")

        if isinstance(min_records, bool) or not isinstance(min_records, int):
            raise ValueError("min_records must be an integer >= 1")
        if min_records < 1:
            raise ValueError("min_records must be an integer >= 1")

        report = self.get_pattern_report(records, pattern)

        if report["total_records"] < min_records:
            return False
        return report["average_confidence"] >= min_confidence

    def is_pattern_learned(self, records, pattern, min_confidence=0.7, min_records=2):
        """Plain `bool`: whether `pattern` has been "learned" - i.e.
        has enough evidence and confidence behind it - within
        `records`.

        Same yes/no question as `is_pattern_reliable`, with one extra
        validation: `pattern` must be a non-empty string (empty/
        whitespace-only strings and non-string values raise
        `ValueError`, same "must be a non-empty string" convention
        `LearningRecord.is_valid()` already uses for its own
        `pattern` field). `min_confidence` and `min_records` keep the
        exact validation and meaning `is_pattern_reliable` already
        gives them, and the True/False decision itself is delegated
        straight to `is_pattern_reliable` - no confidence/record
        counting logic is duplicated here.

        `True` only when both hold:
          1. the pattern has at least `min_records` valid
             success/failure records
          2. their average confidence is >= `min_confidence`

        `False` otherwise, including for an empty/`None` `records` or
        a `pattern` with no/insufficient matching success/failure
        records. Pure observation, same as `is_pattern_reliable`:
        never mutates a record or `LearningRecordStore`, and never
        itself changes any capability, skill, plan, or other
        behavior - it only reports whether the evidence bar is met."""
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern must be a non-empty string")

        return self.is_pattern_reliable(
            records, pattern, min_confidence=min_confidence, min_records=min_records,
        )

    def get_pattern_learning_status(
        self, records, pattern, min_confidence=0.7, min_records=2,
    ):
        """A small read-only status report combining `get_pattern_report`,
        `is_pattern_reliable`, and `is_pattern_learned` for `pattern`
        within `records`:

            {
                "pattern": <the pattern argument, unchanged>,
                "record_count": <int>,
                "average_confidence": <float>,
                "success_count": <int>,
                "failure_count": <int>,
                "is_reliable": <bool>,
                "is_learned": <bool>,
            }

        Same evidence as `get_pattern_report`: only valid
        `LearningRecord` instances whose `pattern` matches exactly and
        whose `outcome` is exactly `"success"` or `"failure"` count -
        `record_count`, `average_confidence`, `success_count`, and
        `failure_count` are `get_pattern_report`'s `total_records`,
        `average_confidence`, `success_count`, and `failure_count`
        under their names here, computed once and reused rather than
        recalculated. `is_reliable` and `is_learned` are the exact
        `bool` results of calling `is_pattern_reliable` and
        `is_pattern_learned` with the same `records`, `pattern`,
        `min_confidence`, and `min_records` - no confidence/evidence
        counting logic is duplicated here.

        Same validation as `is_pattern_learned`: `pattern` must be a
        non-empty string, `min_confidence` a plain number between
        `0.0` and `1.0`, and `min_records` a plain `int >= 1` -
        anything else raises `ValueError`.

        Returns a fresh dict on every call (never a shared/cached
        object) with all-zero counts and `is_reliable`/`is_learned`
        both `False` for an empty/`None` `records` or a `pattern`
        that matches no success/failure records. Pure observation:
        never mutates a record or `LearningRecordStore`, never
        creates a learning record, and never itself changes any
        capability, skill, plan, or other system behavior."""
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern must be a non-empty string")

        report = self.get_pattern_report(records, pattern)
        is_reliable = self.is_pattern_reliable(
            records, pattern, min_confidence=min_confidence, min_records=min_records,
        )
        is_learned = self.is_pattern_learned(
            records, pattern, min_confidence=min_confidence, min_records=min_records,
        )

        return {
            "pattern": pattern,
            "record_count": report["total_records"],
            "average_confidence": report["average_confidence"],
            "success_count": report["success_count"],
            "failure_count": report["failure_count"],
            "is_reliable": is_reliable,
            "is_learned": is_learned,
        }

    def find_learned_patterns(self, records, min_confidence=0.7, min_records=2):
        """A sorted `list` of pattern names (plain `str`s) among
        `records` that satisfy `is_pattern_learned`.

        Same evidence as `get_pattern_report`/`is_pattern_learned`:
        only valid `LearningRecord` instances with an `outcome` of
        exactly `"success"` or `"failure"` are grouped by their exact
        `pattern`; anything else (invalid records, other outcome
        values) is ignored and never contributes a pattern name to
        the result. Each distinct pattern found this way is then
        checked with `is_pattern_learned(records, pattern,
        min_confidence=min_confidence, min_records=min_records)` -
        the same evidence-count/confidence decision `is_pattern_learned`
        already makes is reused as-is, not recomputed here. A pattern
        is only included when that call returns `True`.

        The result contains each qualifying pattern exactly once, in
        alphabetical order - deterministic regardless of `records`'
        original ordering. Returns `[]` when `records` is empty/`None`
        or no pattern qualifies.

        `min_confidence` must be a plain number between `0.0` and
        `1.0`; `min_records` must be a plain `int >= 1` - same
        validation `is_pattern_learned`/`is_pattern_reliable` already
        apply, raising `ValueError` for anything else (checked up
        front, even when no pattern would otherwise be examined).

        Pure observation: never mutates a record or
        `LearningRecordStore`, never creates a learning record, and
        never itself changes any capability, skill, plan, or other
        system behavior."""
        from .learning_record import LearningRecord

        if isinstance(min_confidence, bool) or not isinstance(min_confidence, (int, float)):
            raise ValueError("min_confidence must be a number between 0.0 and 1.0")
        if not (0.0 <= min_confidence <= 1.0):
            raise ValueError("min_confidence must be between 0.0 and 1.0")

        if isinstance(min_records, bool) or not isinstance(min_records, int):
            raise ValueError("min_records must be an integer >= 1")
        if min_records < 1:
            raise ValueError("min_records must be an integer >= 1")

        candidate_patterns = set()
        for record in (records or []):
            if not isinstance(record, LearningRecord) or not record.is_valid():
                continue
            if record.outcome not in ("success", "failure"):
                continue
            candidate_patterns.add(record.pattern)

        learned = [
            pattern
            for pattern in sorted(candidate_patterns)
            if self.is_pattern_learned(
                records, pattern, min_confidence=min_confidence, min_records=min_records,
            )
        ]
        return learned

    def get_learned_pattern_summary(self, records, min_confidence=0.7, min_records=2):
        """A small read-only summary of the patterns
        `find_learned_patterns` currently considers learned within
        `records`:

            {
                "learned_patterns": [...],
                "count": <int>,
                "min_confidence": <the min_confidence argument, unchanged>,
                "min_records": <the min_records argument, unchanged>,
            }

        `learned_patterns` is exactly `find_learned_patterns(records,
        min_confidence=min_confidence, min_records=min_records)` -
        the same unique, alphabetically sorted pattern list, computed
        once and reused rather than recalculated (no learned-pattern
        detection logic is duplicated here). `count` is always
        `len(learned_patterns)`.

        Same validation as `find_learned_patterns` (delegated to it,
        not repeated): `min_confidence` must be a plain number between
        `0.0` and `1.0`, and `min_records` a plain `int >= 1` -
        anything else raises `ValueError`.

        Returns a fresh dict on every call (never a shared/cached
        object) with an empty `learned_patterns` list and `count: 0`
        for an empty/`None` `records` or when no pattern qualifies.
        Pure observation: never mutates a record or
        `LearningRecordStore`, never creates a learning record, never
        persists anything, and never itself changes any capability,
        skill, plan, execution, or other system behavior."""
        learned_patterns = self.find_learned_patterns(
            records, min_confidence=min_confidence, min_records=min_records,
        )

        return {
            "learned_patterns": learned_patterns,
            "count": len(learned_patterns),
            "min_confidence": min_confidence,
            "min_records": min_records,
        }

    def get_learned_pattern_details(self, records, min_confidence=0.7, min_records=2):
        """A `list` of small read-only detail dicts, one per pattern
        `find_learned_patterns` currently considers learned within
        `records`:

            [
                {
                    "pattern": <str>,
                    "record_count": <int>,
                    "success_count": <int>,
                    "failure_count": <int>,
                    "success_rate": <float, 0.0-1.0>,
                    "average_confidence": <float>,
                },
                ...
            ]

        The learned-pattern list itself is exactly
        `find_learned_patterns(records, min_confidence=min_confidence,
        min_records=min_records)` - unique pattern names, already
        alphabetically sorted, so the result here keeps that same
        order and each pattern appears only once. Each entry's counts
        and rates come straight from `get_pattern_report(records,
        pattern)` (`total_records` renamed `record_count` to match
        this method's own field name; `success_count`, `failure_count`,
        `success_rate`, and `average_confidence` unchanged) - the same
        valid success/failure evidence records `get_pattern_report`/
        `get_pattern_success_rate` already use, with no counting or
        confidence math repeated here.

        Same validation as `find_learned_patterns` (delegated to it,
        not repeated): `min_confidence` must be a plain number between
        `0.0` and `1.0`, and `min_records` a plain `int >= 1` -
        anything else raises `ValueError`.

        Returns a fresh list of fresh dicts on every call (never
        shared/cached) - `[]` for an empty/`None` `records` or when no
        pattern qualifies. Pure observation: never mutates a record or
        `LearningRecordStore`, never creates a learning record, never
        persists anything, and never itself changes any capability,
        skill, plan, execution, or other system behavior."""
        learned_patterns = self.find_learned_patterns(
            records, min_confidence=min_confidence, min_records=min_records,
        )

        details = []
        for pattern in learned_patterns:
            report = self.get_pattern_report(records, pattern)
            details.append({
                "pattern": report["pattern"],
                "record_count": report["total_records"],
                "success_count": report["success_count"],
                "failure_count": report["failure_count"],
                "success_rate": report["success_rate"],
                "average_confidence": report["average_confidence"],
            })
        return details

    def find_highest_confidence_learned_pattern(
        self, records, min_confidence=0.7, min_records=2,
    ):
        """The detail dict (same shape `get_learned_pattern_details`
        returns) of the learned pattern with the highest
        `average_confidence` among `records`, or `None` if no pattern
        qualifies.

        Built entirely on `get_learned_pattern_details(records,
        min_confidence=min_confidence, min_records=min_records)` - no
        evidence counting, confidence averaging, or success-rate math
        is repeated here. That list is already unique per pattern and
        alphabetically sorted, so picking the entry with the highest
        `average_confidence` via a plain left-to-right max naturally
        keeps the alphabetically first pattern whenever two or more
        share the same top confidence - no separate tie-break logic
        needed.

        Same validation as `get_learned_pattern_details` (delegated to
        it, not repeated): `min_confidence` must be a plain number
        between `0.0` and `1.0`, and `min_records` a plain `int >= 1`
        - anything else raises `ValueError`.

        Returns `None` for an empty/`None` `records` or when no
        pattern is learned. Otherwise returns a fresh dict (one of the
        fresh dicts `get_learned_pattern_details` already builds this
        call, never a shared/cached object) - pure observation, same
        as `get_learned_pattern_details`: never mutates a record or
        `LearningRecordStore`, never creates a learning record, never
        persists anything, and never itself changes any capability,
        skill, plan, execution, or other system behavior."""
        details = self.get_learned_pattern_details(
            records, min_confidence=min_confidence, min_records=min_records,
        )

        if not details:
            return None

        return max(details, key=lambda entry: entry["average_confidence"])

    def rank_learned_patterns(self, records, min_confidence=0.7, min_records=2):
        """A `list` of the same detail dicts `get_learned_pattern_details`
        returns for `records`, re-ordered by rank instead of by name:

            1. `average_confidence` descending (most confident first)
            2. `pattern` ascending when `average_confidence` ties

        Built entirely on `get_learned_pattern_details(records,
        min_confidence=min_confidence, min_records=min_records)` - the
        same unique-per-pattern list of dicts (`pattern`,
        `record_count`, `success_count`, `failure_count`,
        `success_rate`, `average_confidence`), only re-sorted; no
        evidence counting, confidence averaging, or success-rate math
        is repeated here.

        Same validation as `get_learned_pattern_details` (delegated to
        it, not repeated): `min_confidence` must be a plain number
        between `0.0` and `1.0`, and `min_records` a plain `int >= 1`
        - anything else raises `ValueError`.

        Returns `[]` for an empty/`None` `records` or when no pattern
        is learned. Otherwise returns a fresh list (of the fresh dicts
        `get_learned_pattern_details` already built this call, never
        shared/cached) in rank order. Pure observation, same as
        `get_learned_pattern_details`: never mutates a record or
        `LearningRecordStore`, never creates a learning record, never
        persists anything, and never itself changes any capability,
        skill, plan, execution, or other system behavior."""
        details = self.get_learned_pattern_details(
            records, min_confidence=min_confidence, min_records=min_records,
        )

        return sorted(
            details, key=lambda entry: (-entry["average_confidence"], entry["pattern"]),
        )

    def get_top_learned_patterns(
        self, records, limit=5, min_confidence=0.7, min_records=2,
    ):
        """The first `limit` detail dicts (same shape
        `rank_learned_patterns` returns) from `rank_learned_patterns`
        for `records`.

        Built entirely on `rank_learned_patterns(records,
        min_confidence=min_confidence, min_records=min_records)` - the
        same rank order (highest `average_confidence` first, then
        `pattern` ascending on ties) is kept as-is; this method only
        truncates that already-ranked list to at most `limit` entries,
        so no ranking or evidence/confidence math is repeated here.

        Returns every learned pattern (fewer than `limit` entries)
        when fewer than `limit` patterns qualify, and `[]` for an
        empty/`None` `records` or when no pattern is learned.

        `limit` must be a plain `int >= 1`; `min_confidence` and
        `min_records` keep the exact validation
        `rank_learned_patterns`/`get_learned_pattern_details` already
        apply. Anything invalid raises `ValueError`.

        Returns a fresh list (of the fresh dicts `rank_learned_patterns`
        already built this call, never shared/cached). Pure
        observation, same as `rank_learned_patterns`: never mutates a
        record or `LearningRecordStore`, never creates a learning
        record, never persists anything, and never itself changes any
        capability, skill, plan, execution, or other system behavior."""
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer >= 1")
        if limit < 1:
            raise ValueError("limit must be an integer >= 1")

        ranked = self.rank_learned_patterns(
            records, min_confidence=min_confidence, min_records=min_records,
        )

        return ranked[:limit]

    def filter_learned_patterns_by_success_rate(
        self, records, min_success_rate=0.5, min_confidence=0.7, min_records=2,
    ):
        """A `list` of the same detail dicts `get_learned_pattern_details`
        returns for `records`, kept only where `success_rate >=
        min_success_rate`.

        Built entirely on `get_learned_pattern_details(records,
        min_confidence=min_confidence, min_records=min_records)` - the
        same unique-per-pattern, alphabetically ordered list of dicts
        (`pattern`, `record_count`, `success_count`, `failure_count`,
        `success_rate`, `average_confidence`); only already-learned
        patterns are ever considered (learning eligibility itself is
        not recalculated here), and the existing alphabetical order is
        preserved for the entries that remain - this method only
        filters that list by `success_rate`, nothing else is
        recomputed.

        `min_success_rate` must be a plain number (not `bool`) between
        `0.0` and `1.0` inclusive; `min_confidence` and `min_records`
        keep the exact validation `get_learned_pattern_details`
        already applies. Anything invalid raises `ValueError`.

        Returns `[]` for an empty/`None` `records`, when no pattern is
        learned, or when no learned pattern meets `min_success_rate`.
        Otherwise returns a fresh list (of the fresh dicts
        `get_learned_pattern_details` already built this call, never
        shared/cached). Pure observation, same as
        `get_learned_pattern_details`: never mutates a record or
        `LearningRecordStore`, never creates a learning record, never
        persists anything, and never itself changes any capability,
        skill, plan, execution, or other system behavior."""
        if isinstance(min_success_rate, bool) or not isinstance(min_success_rate, (int, float)):
            raise ValueError("min_success_rate must be a number between 0.0 and 1.0")
        if not (0.0 <= min_success_rate <= 1.0):
            raise ValueError("min_success_rate must be between 0.0 and 1.0")

        details = self.get_learned_pattern_details(
            records, min_confidence=min_confidence, min_records=min_records,
        )

        return [
            entry for entry in details if entry["success_rate"] >= min_success_rate
        ]

    def find_reliable_successful_patterns(
        self, records, min_success_rate=0.7, min_confidence=0.7, min_records=2,
    ):
        """A `list` of the same detail dicts `get_learned_pattern_details`
        returns for `records`, kept only where the pattern satisfies
        `is_pattern_learned` AND its `success_rate >= min_success_rate`,
        ordered by rank instead of by name:

            1. `average_confidence` descending (most confident first)
            2. `pattern` ascending when `average_confidence` ties

        Built entirely on `filter_learned_patterns_by_success_rate(
        records, min_success_rate=min_success_rate,
        min_confidence=min_confidence, min_records=min_records)` -
        which already applies `is_pattern_learned`'s evidence/
        confidence requirements via `get_learned_pattern_details` and
        the `success_rate` cutoff itself - only re-sorted here; no
        evidence counting, confidence averaging, success-rate math, or
        learning-eligibility check is repeated in this method. Same
        evidence as always: only valid `LearningRecord`s with an
        `outcome` of exactly `"success"` or `"failure"` count, grouped
        by exact `pattern` - invalid records, other outcomes, and
        unrelated patterns are all ignored by the methods this
        delegates to.

        Same validation as `filter_learned_patterns_by_success_rate`
        (delegated to it, not repeated): `min_success_rate` and
        `min_confidence` must each be a plain number between `0.0` and
        `1.0`, and `min_records` a plain `int >= 1` - anything else
        raises `ValueError`.

        Returns `[]` for an empty/`None` `records` or when no pattern
        qualifies. Otherwise returns a fresh list (of the fresh dicts
        already built this call, never shared/cached), in rank order.
        Pure observation: never mutates a record or
        `LearningRecordStore`, never creates a learning record, never
        persists anything, and never itself changes any capability,
        skill, plan, execution, or other system behavior - no
        automatic decision-making is introduced."""
        qualifying = self.filter_learned_patterns_by_success_rate(
            records,
            min_success_rate=min_success_rate,
            min_confidence=min_confidence,
            min_records=min_records,
        )

        return sorted(
            qualifying, key=lambda entry: (-entry["average_confidence"], entry["pattern"]),
        )

    def find_relevant_learned_patterns(
        self, records, pattern_prefix,
        min_success_rate=0.7, min_confidence=0.7, min_records=2,
    ):
        """A `list` of the same detail dicts `get_learned_pattern_details`
        returns for `records`, kept only where the pattern's name
        starts with the exact `pattern_prefix` AND the pattern already
        satisfies `find_reliable_successful_patterns` (i.e. it is
        learned, per `is_pattern_learned`, and its `success_rate >=
        min_success_rate`), ordered by rank:

            1. `average_confidence` descending (most confident first)
            2. `success_rate` descending when `average_confidence` ties
            3. `pattern` ascending when both of the above tie

        This is a small decision-support lookup: a caller who already
        knows a pattern family (e.g. `"network."`, `"ui.button."`)
        can ask "what has this system reliably learned in that
        family?" and get back only the entries worth surfacing.

        Built entirely on `find_reliable_successful_patterns(records,
        min_success_rate=min_success_rate, min_confidence=min_confidence,
        min_records=min_records)` - which already applies
        `is_pattern_learned`'s evidence/confidence requirements (via
        `get_learned_pattern_details`) and the `success_rate` cutoff;
        this method only narrows that list to patterns whose exact
        `pattern` string starts with `pattern_prefix` (via plain
        `str.startswith` - no wildcards, no case-folding) and then
        re-sorts it. No evidence counting, confidence averaging,
        success-rate math, or learning-eligibility check is repeated
        here.

        `pattern_prefix` must be a non-empty string (empty/
        whitespace-only strings and non-string values raise
        `ValueError`, same "must be a non-empty string" convention
        `is_pattern_learned` already uses for its own `pattern`
        argument). `min_success_rate`, `min_confidence`, and
        `min_records` keep the exact validation
        `find_reliable_successful_patterns` already applies (delegated
        to it, not repeated): `min_success_rate` and `min_confidence`
        must each be a plain number between `0.0` and `1.0`, and
        `min_records` a plain `int >= 1` - anything else raises
        `ValueError`.

        Returns `[]` for an empty/`None` `records`, when no pattern
        qualifies, or when no qualifying pattern's name starts with
        `pattern_prefix`. Otherwise returns a fresh list (of the fresh
        dicts `find_reliable_successful_patterns` already built this
        call, never shared/cached), in rank order. Never mutates
        `records` or any record.

        Pure retrieval/analysis, same as every other method on this
        class: it does not execute anything, does not change any
        capability, skill, or plan, does not create a learning record,
        does not persist anything, and does not itself make any
        autonomous decision - it only reports what a caller could
        choose to act on elsewhere."""
        if not isinstance(pattern_prefix, str) or not pattern_prefix.strip():
            raise ValueError("pattern_prefix must be a non-empty string")

        qualifying = self.find_reliable_successful_patterns(
            records,
            min_success_rate=min_success_rate,
            min_confidence=min_confidence,
            min_records=min_records,
        )

        matching = [
            entry for entry in qualifying
            if entry["pattern"].startswith(pattern_prefix)
        ]

        return sorted(
            matching,
            key=lambda entry: (
                -entry["average_confidence"],
                -entry["success_rate"],
                entry["pattern"],
            ),
        )

    def find_best_relevant_learned_pattern(
        self, records, pattern_prefix,
        min_success_rate=0.7, min_confidence=0.7, min_records=2,
    ):
        """The single best matching learned-pattern detail dict (same
        shape `get_learned_pattern_details` returns) among the
        patterns `find_relevant_learned_patterns` currently returns
        for `records`/`pattern_prefix`, or `None` if none qualify.

        "Best" is decided by this order, each step only breaking ties
        left by the one before it:

          1. highest `average_confidence`
          2. highest `success_rate`
          3. highest `record_count`
          4. `pattern` name, alphabetically first

        Built entirely on `find_relevant_learned_patterns(records,
        pattern_prefix, min_success_rate=min_success_rate,
        min_confidence=min_confidence, min_records=min_records)` - the
        same pattern-prefix match, learning/reliability requirements,
        and `success_rate` cutoff it already applies (which in turn
        delegates to `find_reliable_successful_patterns` and
        `get_learned_pattern_details`). Only a pattern that method
        already returns can ever be selected here; no evidence
        counting, confidence averaging, success-rate math, or
        prefix matching is repeated in this method - it only picks one
        entry from that list by the ranking above (`record_count` is
        the one field `find_relevant_learned_patterns`'s own sort
        doesn't use as a tie-break, so this method applies it before
        falling back to `pattern`).

        Same validation as `find_relevant_learned_patterns` (delegated
        to it, not repeated): `pattern_prefix` must be a non-empty
        string; `min_success_rate` and `min_confidence` must each be a
        plain number between `0.0` and `1.0`; `min_records` must be a
        plain `int >= 1` - anything else raises `ValueError`.

        Returns `None` for an empty/`None` `records`, when no pattern
        is learned, or when no learned pattern's name starts with
        `pattern_prefix`. Otherwise returns a fresh dict (one of the
        fresh dicts `find_relevant_learned_patterns` already built
        this call, never a shared/cached object). Never mutates
        `records` or any record.

        Pure retrieval/analysis, same as every other method on this
        class: it does not execute anything, does not change any
        capability, skill, or plan, does not create a learning record,
        does not persist anything, and does not itself make any
        autonomous decision - it only reports the single entry a
        caller could choose to act on elsewhere."""
        candidates = self.find_relevant_learned_patterns(
            records,
            pattern_prefix,
            min_success_rate=min_success_rate,
            min_confidence=min_confidence,
            min_records=min_records,
        )

        if not candidates:
            return None

        return sorted(
            candidates,
            key=lambda entry: (
                -entry["average_confidence"],
                -entry["success_rate"],
                -entry["record_count"],
                entry["pattern"],
            ),
        )[0]

    def get_relevant_learning_context(
        self, records, pattern_prefix,
        min_success_rate=0.7, min_confidence=0.7, min_records=2,
    ):
        """A small read-only structured summary combining
        `find_relevant_learned_patterns` and
        `find_best_relevant_learned_pattern` for
        `records`/`pattern_prefix`:

            {
                "pattern_prefix": <the pattern_prefix argument, unchanged>,
                "match_count": <int>,
                "best_pattern": <detail dict, or None>,
                "patterns": [<detail dict>, ...],
            }

        `patterns` is exactly `find_relevant_learned_patterns(records,
        pattern_prefix, min_success_rate=min_success_rate,
        min_confidence=min_confidence, min_records=min_records)` - the
        same prefix-matched, rank-ordered list of detail dicts,
        computed once and reused rather than recalculated.
        `match_count` is always `len(patterns)`. `best_pattern` is
        exactly `find_best_relevant_learned_pattern(records,
        pattern_prefix, min_success_rate=min_success_rate,
        min_confidence=min_confidence, min_records=min_records)` - the
        same single best-ranked entry (or `None`) that method already
        picks. No prefix matching, evidence counting, confidence
        averaging, success-rate math, or ranking logic is duplicated
        here - this method only assembles the results those two
        methods already compute into one small dict.

        Same validation as `find_relevant_learned_patterns`/
        `find_best_relevant_learned_pattern` (delegated to them, not
        repeated): `pattern_prefix` must be a non-empty string;
        `min_success_rate` and `min_confidence` must each be a plain
        number between `0.0` and `1.0`; `min_records` must be a plain
        `int >= 1` - anything else raises `ValueError`.

        Returns a fresh dict on every call (never a shared/cached
        object) with `match_count: 0`, `best_pattern: None`, and
        `patterns: []` for an empty/`None` `records` or when no
        learned pattern's name starts with `pattern_prefix`. Never
        mutates `records` or any record.

        Pure retrieval/analysis, same as every other method on this
        class: it does not execute anything, does not change any
        capability, skill, or plan, does not create a learning record,
        does not persist anything, and does not itself make any
        autonomous decision - it only assembles context a caller could
        choose to act on elsewhere."""
        patterns = self.find_relevant_learned_patterns(
            records,
            pattern_prefix,
            min_success_rate=min_success_rate,
            min_confidence=min_confidence,
            min_records=min_records,
        )

        best_pattern = self.find_best_relevant_learned_pattern(
            records,
            pattern_prefix,
            min_success_rate=min_success_rate,
            min_confidence=min_confidence,
            min_records=min_records,
        )

        return {
            "pattern_prefix": pattern_prefix,
            "match_count": len(patterns),
            "best_pattern": best_pattern,
            "patterns": patterns,
        }

