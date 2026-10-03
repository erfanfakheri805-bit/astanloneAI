"""
Revenue Learning Analysis
============================
`RevenueLearningAnalyzer` computes a small, read-only statistical
summary over a batch of already-built `RevenueLearningRecord` objects
(financial/revenue_learning.py) - either supplied directly
(`analyze()`) or read from an existing `RevenueLearningRecordStore`
(financial/revenue_learning_store.py) via `analyze_store()`.

Same "read-only reporting over already-recorded data" shape
`financial/revenue_task_result_history.py`'s own
`get_overall_result_summary()` already uses for `RevenueTaskResult`s -
this module is that same idea one layer up, over
`RevenueLearningRecord`s. It deliberately does NOT:

- Learn anything, infer a pattern beyond simple counting/aggregation
  of the record data it is given, or feed itself into
  `learning/learning_system.py`, `learning/learning_analyzer.py`, or
  any other learning component - this is a plain statistical summary,
  not a decision or a behavior change in its own right.
- Change any `RevenueTask`, `RevenueOpportunity`, `RevenueStrategy`,
  or `RevenueLearningRecordStore`'s own state, or trigger any future
  execution, retry, or strategy change.
- Persist itself anywhere (no filesystem, database, or network I/O),
  run any code (no `eval`/`exec`/`subprocess`/shell), or call out to
  any external AI service.
"""

from .revenue_learning import RevenueLearningRecord


def _empty_analysis():
    return {
        "total_records": 0,
        "successful_records": 0,
        "failed_records": 0,
        "success_rate": 0.0,
        "unique_task_count": 0,
        "unique_opportunity_count": 0,
        "latest_learning_id": None,
        "latest_task_id": None,
        "latest_opportunity_id": None,
        "latest_status": None,
        "has_data": False,
    }


class RevenueLearningAnalyzer:
    """Stateless - holds no data of its own between calls. Every
    method is a plain, read-only computation over whatever records it
    is handed (or reads from a store), never anything it remembers
    from a previous call."""

    def analyze(self, records):
        """A read-only statistical summary over `records` (a list of
        already-built `RevenueLearningRecord` objects), as a plain
        `dict`:

            {
                "total_records": <int>,
                "successful_records": <int>,
                "failed_records": <int>,
                "success_rate": <float, 0.0-1.0>,
                "unique_task_count": <int>,
                "unique_opportunity_count": <int>,
                "latest_learning_id": <str or None>,
                "latest_task_id": <str or None>,
                "latest_opportunity_id": <str or None>,
                "latest_status": <str or None>,
                "has_data": <bool>,
            }

        Only entries in `records` that are both an actual
        `RevenueLearningRecord` instance and pass that record's own
        `is_valid()` check are counted - anything else (a `None`, a
        plain dict, a string, an invalid/malformed record) is safely
        skipped rather than raising, so a caller can hand this a
        list of untrusted/partial data straight from elsewhere and
        still get a sensible summary back. `records` itself, and
        every record inside it, is only ever read - never mutated,
        reordered, or replaced.

        `total_records` counts only the valid records found (not the
        length of the raw `records` list, which may contain invalid
        entries). `successful_records` counts valid records whose
        `success` is exactly `True` (via `is_successful()`);
        `failed_records` counts valid records whose `success` is
        exactly `False` (via `is_failed()`) - a record whose
        `success` is neither (which `is_valid()` already prevents)
        would count toward neither. `success_rate` is
        `successful_records / total_records`, or `0.0` when there are
        no valid records (avoiding a division by zero) - always a
        plain `float` in the inclusive range 0.0-1.0.

        `unique_task_count`/`unique_opportunity_count` are the number
        of distinct, valid (non-empty string) `task_id`/
        `opportunity_id` values seen across the valid records - every
        valid record is already required to carry both (`is_valid()`
        confirms this), so this is simply a count of distinct values.

        `latest_learning_id`/`latest_task_id`/`latest_opportunity_id`/
        `latest_status` describe the *last valid record encountered
        in `records`' own given order* - this never re-sorts by
        `created_at`, and an invalid entry anywhere in `records` is
        simply skipped when looking for "latest", never mistaken for
        it. `has_data` is `True` exactly when `total_records > 0`.

        An empty or entirely-invalid `records` list (including
        `None`, or anything else that isn't a list at all) safely
        returns a zero-result summary - `has_data=False`, all counts
        `0`, `success_rate=0.0`, and every `latest_*` field `None` -
        rather than raising."""
        if not isinstance(records, (list, tuple)):
            return _empty_analysis()

        valid_records = [
            record for record in records
            if isinstance(record, RevenueLearningRecord) and record.is_valid()
        ]
        total_records = len(valid_records)

        if total_records == 0:
            return _empty_analysis()

        successful_records = sum(1 for record in valid_records if record.is_successful())
        failed_records = sum(1 for record in valid_records if record.is_failed())

        unique_task_ids = set()
        unique_opportunity_ids = set()
        for record in valid_records:
            unique_task_ids.add(record.task_id)
            unique_opportunity_ids.add(record.opportunity_id)

        latest = valid_records[-1]

        return {
            "total_records": total_records,
            "successful_records": successful_records,
            "failed_records": failed_records,
            "success_rate": float(successful_records) / total_records,
            "unique_task_count": len(unique_task_ids),
            "unique_opportunity_count": len(unique_opportunity_ids),
            "latest_learning_id": latest.learning_id,
            "latest_task_id": latest.task_id,
            "latest_opportunity_id": latest.opportunity_id,
            "latest_status": latest.result_status,
            "has_data": True,
        }

    def analyze_store(self, store):
        """The same read-only statistical summary `analyze()`
        produces, computed over every record currently held by
        `store` (a `RevenueLearningRecordStore` - financial/
        revenue_learning_store.py), read through that store's own
        `get_all()` (which already returns fresh, independent copies -
        this method never reaches into the store's internal
        collections directly). Only this call's own local list of
        copies is inspected; `store` itself is never modified.

        Returns a zero-result summary (same shape `analyze([])`
        returns) when `store` is not an object that exposes a
        `get_all()` method, rather than raising."""
        get_all = getattr(store, "get_all", None)
        if not callable(get_all):
            return _empty_analysis()

        records = get_all()
        return self.analyze(records)
