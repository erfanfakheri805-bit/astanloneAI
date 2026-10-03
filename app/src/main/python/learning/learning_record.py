"""
Learning Record
================
`LearningRecord` is a small, standalone data record for one thing the
system has noticed: a `pattern` observed from some `source`, together
with the `outcome` that followed and a `confidence` for how much to
trust that observation.

This is deliberately the *shape only* - same "plain, JSON-shaped record
with a to_dict()" convention already used by LearningResult
(learning/learning_result.py), LearningDecision
(learning/learning_decision.py), and LearningInput
(learning/learning_input.py). Nothing here persists a record anywhere,
feeds it into LearningSystem/LearningDecisionEngine, or changes any
plan, proposal, or capability - it is a container a future stage can
choose to read, store, or act on.

`is_valid()` is a plain boolean check (never raises), matching how a
caller would want to filter a batch of candidate records before doing
anything with them; it does not mutate the record or raise on bad
input.
"""

import itertools
from datetime import datetime, timezone

# Safe, structured-data-only types allowed inside `metadata`. Anything
# else (functions, class instances, file handles, etc.) is rejected by
# is_valid() so `metadata` always stays plain and JSON-shaped - never a
# place to smuggle in something that could be called or executed later.
_SAFE_SCALAR_TYPES = (str, int, float, bool, type(None))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Same "always assign an id, never leave one dangling" convention used
# by execution/execution_result.py's _generate_execution_id and
# planning/plan_manager.py's counters: a single, process-wide,
# monotonically increasing counter as the default id source.
_id_counter = itertools.count(1)


def _generate_record_id():
    return f"learning-record-{next(_id_counter)}"


def _is_safe_metadata_value(value):
    """True if `value` is made only of plain, structured data (str,
    int, float, bool, None, list/tuple, dict with string keys) -
    recursively. No functions, class instances, or other objects that
    could carry behavior."""
    if isinstance(value, _SAFE_SCALAR_TYPES):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_safe_metadata_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_safe_metadata_value(val)
            for key, val in value.items()
        )
    return False


class LearningRecord:
    """One observed (source, pattern, outcome) triple with a
    confidence score. Purely a data record: construction never raises
    (unlike e.g. ExecutionResult) so a caller can freely build a
    LearningRecord from untrusted/partial data and then use
    `is_valid()` to decide whether it is fit to use, rather than having
    to wrap construction in a try/except.

    `metadata` is always a plain dict (never None), same convention as
    Goal.metadata / Plan.metadata / ExecutionResult.metadata.
    """

    __slots__ = (
        "record_id", "source", "pattern", "outcome", "confidence",
        "created_at", "metadata",
    )

    def __init__(
        self,
        source,
        pattern,
        outcome,
        confidence,
        record_id=None,
        created_at=None,
        metadata=None,
    ):
        self.record_id = record_id if record_id is not None else _generate_record_id()
        self.source = source
        self.pattern = pattern
        self.outcome = outcome
        self.confidence = confidence
        self.created_at = created_at if created_at is not None else _now_iso()
        self.metadata = metadata if metadata is not None else {}

    def __repr__(self):
        return (
            f"LearningRecord({self.record_id!r}, source={self.source!r}, "
            f"pattern={self.pattern!r}, outcome={self.outcome!r}, "
            f"confidence={self.confidence!r})"
        )

    def is_valid(self):
        """Plain boolean check - never raises. A record is valid when:
        - source, pattern, and outcome are all non-empty strings
        - confidence is a number between 0.0 and 1.0 (inclusive)
        - metadata is a dict containing only safe structured data
        """
        for field in (self.source, self.pattern, self.outcome):
            if not isinstance(field, str) or not field.strip():
                return False

        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            return False
        if not (0.0 <= self.confidence <= 1.0):
            return False

        if not isinstance(self.metadata, dict):
            return False
        if not _is_safe_metadata_value(self.metadata):
            return False

        return True

    def to_dict(self):
        return {
            "record_id": self.record_id,
            "source": self.source,
            "pattern": self.pattern,
            "outcome": self.outcome,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
