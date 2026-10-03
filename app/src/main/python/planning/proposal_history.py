"""
Planning - Proposal History
==============================
`ProposalHistory` is a small, in-memory record of every proposal
change that `ProposalApplier` (planning/proposal_applier.py) has
already *successfully* applied to a `Plan`:

    PlanProposal.proposal_id + ProposedChange
        -> ProposalApplier.apply_change  (mutates the Plan, returns a
           structured result dict - see proposal_applier.py)
        -> ProposalHistory.record(...)   (this module: stores that
           outcome, if and only if it succeeded)

This stage only stores and retrieves the small result dicts
`ProposalApplier.apply_change` already returns - it does not decide
*whether* to apply a change, does not call `ProposalApplier` itself,
does not touch the filesystem, a database, the shell, the network, or
any Android API, and does not itself change a `Plan` or `PlanStep` in
any way. History here means "what was already successfully applied",
never "what should be applied next" - nothing here schedules,
retries, or triggers a future application. `ProposalApplier` itself
is untouched by this module: recording is something a caller does
*after* calling `apply_change`, by handing the result to
`ProposalHistory.record`, not something `ProposalApplier` does on its
own.

Deliberately independent from persistent storage (matches the
in-memory-only convention `execution/execution_history.py` and
`planning/plan_manager.py` already follow for their own histories):
this history lives only in this process's RAM and is cleared on
process restart. A future stage may back this with real (e.g.
SQLite) persistence; that is explicitly out of scope here.

Only a *successful* `apply_change` result (`result["success"] is
True`) is ever recorded - a failed/rejected change (a duplicate, an
unknown step, a cycle, and so on) leaves no trace here, since a
history of applied changes should reflect only what actually changed
the plan. Each stored record is a small, plain dict - `proposal_id`,
`change_type`, `target_step_id`, a defensively-copied `result`, and
an ISO-8601 UTC `timestamp` - same "plain data in, plain data out"
convention `execution_result.py`/`proposal_applier.py` already
follow. `get_all`/`get_for_proposal`/`get_latest_for_step` always
return fresh copies of the stored records (via `copy.deepcopy`), so a
caller mutating a record it read back can never corrupt this
history's own state.
"""

import copy
from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class ProposalHistory:
    """Not thread-safe (matches the rest of this project - see
    ExecutionHistory/PlanManager/GoalManager's own notes). Safe to use
    one instance per Core / per conversation session, or to share one
    across several callers that should log to the same history.

    Storage is a single ordered list of small record dicts, in the
    order `record()` accepted them - simplest possible shape for a
    module this small; no id-keyed lookup structure is needed since
    nothing here deduplicates or looks up a single record by id.
    """

    def __init__(self):
        self._records = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record(self, proposal_id, change_type, target_step_id, result):
        """Record one already-applied change, but only if `result`
        (the structured dict `ProposalApplier.apply_change` returns)
        reports success.

        Returns a copy of the stored record dict on success, or None
        if nothing was recorded (never raises for a failed/rejected
        `result` - it is simply not stored, same "safe, report-don't-
        raise" convention the rest of this planning package already
        follows for expected/unexceptional cases).
        """
        if not isinstance(result, dict) or result.get("success") is not True:
            return None

        record = {
            "proposal_id": proposal_id,
            "change_type": change_type,
            "target_step_id": target_step_id,
            "result": copy.deepcopy(result),
            "timestamp": _now_iso(),
        }
        self._records.append(record)
        return copy.deepcopy(record)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_all(self):
        """Every recorded change, oldest-first (insertion order), as
        fresh copies - mutating an entry in the returned list never
        affects this history's own stored state."""
        return [copy.deepcopy(record) for record in self._records]

    def get_for_proposal(self, proposal_id):
        """Every recorded change whose `proposal_id` matches, oldest-
        first, as fresh copies. An unknown or never-used `proposal_id`
        simply returns [] - never raises, same "read-only reporting"
        convention as PlanManager.get_ready_step_ids/ExecutionHistory.
        list_for_plan."""
        return [
            copy.deepcopy(record) for record in self._records
            if record["proposal_id"] == proposal_id
        ]

    def get_latest_for_step(self, step_id):
        """The most recently recorded successful change whose
        `target_step_id` matches `step_id`, as a fresh copy, or `None`
        if no such change is recorded (including an unknown
        `step_id`, or an otherwise-empty history) - never raises, same
        convention as `ExecutionHistory.latest_for_step`. "Most
        recently recorded" means last in `self._records`' own
        insertion order (the same order `record()` appended them in,
        which is also the order their `timestamp`s were stamped in),
        not a re-sort by the stored `timestamp` string."""
        for record in reversed(self._records):
            if record["target_step_id"] == step_id:
                return copy.deepcopy(record)
        return None

    def count_for_proposal(self, proposal_id):
        """The number of successful changes recorded for
        `proposal_id`, as a plain `int` - the same records
        `get_for_proposal` would return, but as a count rather than
        the records themselves (so a caller that only wants "how
        many" never has to copy/discard record data it doesn't need).
        An unknown or never-used `proposal_id` (including an
        otherwise-empty history) returns `0` rather than raising."""
        return sum(1 for record in self._records if record["proposal_id"] == proposal_id)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------
    def clear(self):
        """Discard every recorded change. Only this history's own
        records are affected - no Plan, PlanStep, or other module's
        state is touched."""
        self._records = []

    def __len__(self):
        return len(self._records)
