"""
Planning - Proposal Pattern Analyzer
========================================
`ProposalPatternAnalyzer` is a small, read-only reporting step
downstream of `ProposalHistory` (planning/proposal_history.py):

    ProposalHistory.get_all()  (every already-applied, successful
        change - see proposal_history.py)
        -> ProposalPatternAnalyzer.analyze(history)  (this module:
           tally that same data into simple counts - nothing more)

This is deliberately just counting, not pattern *learning* in any
predictive sense - no scoring, no ranking, no trend detection, no
suggestion of what to propose next. It inspects the already-recorded,
already-successful records `ProposalHistory` exposes and returns
three plain counts: how many there are in total, how many of each
`change_type`, and how many targeted each `target_step_id`
(`analyze`), plus three small convenience reads over that same
tally - which single `change_type` occurred most often
(`most_frequent_change_type`, ties broken by first-encountered order
for a deterministic answer), the full `{change_type: count}` map on
its own (`get_change_type_counts`), and that same map narrowed to one
step (`get_step_change_counts`) - and one small composed summary
(`get_summary`) that reuses `get_change_type_counts` and
`most_frequent_change_type` rather than re-deriving either. Same
"plain data in, plain data out" convention the rest of this planning
package already follows (see proposal_history.py, execution_result.py).

Never mutates `history`, any `Plan`/`PlanStep`, or anything else -
`analyze` only reads via `ProposalHistory.get_all()` (which already
returns defensive copies, so nothing here could corrupt the history
even by accident) and builds a fresh dict of its own. Never executes
anything, never talks to the network or an external AI API, and never
applies, schedules, or recommends a change - same "inert, read-only"
boundary `GoalCompletionEvaluator` (planning/goal_completion.py)
already draws around judging a Plan's status from existing data.
"""


class ProposalPatternAnalyzer:
    """Stateless - holds no collaborators and no instance state - so a
    single shared instance (or a fresh one per call) both work
    identically. `analyze` is the only public method."""

    def analyze(self, history):
        """Return simple, deterministic statistics over every
        successful record currently in `history` (a `ProposalHistory`
        instance): `total_successful_changes` (int), `by_change_type`
        (dict of `change_type` -> count), and `by_target_step_id`
        (dict of `target_step_id` -> count).

        `history.get_all()` already returns only successful,
        already-applied records (see `ProposalHistory.record`), so
        every record counted here is one - this module does no
        success/failure filtering of its own.

        An empty history (or a history with no records yet) returns
        valid zero/empty statistics rather than raising or returning
        None: `total_successful_changes` is `0` and both count dicts
        are `{}`.
        """
        records = history.get_all()

        by_change_type = {}
        by_target_step_id = {}
        for record in records:
            change_type = record.get("change_type")
            target_step_id = record.get("target_step_id")
            by_change_type[change_type] = by_change_type.get(change_type, 0) + 1
            by_target_step_id[target_step_id] = by_target_step_id.get(target_step_id, 0) + 1

        return {
            "total_successful_changes": len(records),
            "by_change_type": by_change_type,
            "by_target_step_id": by_target_step_id,
        }

    def most_frequent_change_type(self, history):
        """Return the `change_type` with the highest count among
        `history`'s successful records (same `analyze`/`by_change_type`
        tally, computed fresh here rather than requiring a caller to
        have called `analyze` first).

        Ties: whichever `change_type` was first *encountered* while
        walking `history.get_all()` in its own (insertion) order - not
        alphabetical or otherwise re-sorted - wins, so the result is
        deterministic for a given history. `dict.get`-based counting
        preserves each key's first-seen position, and `max` over that
        dict only replaces the current leader on a strictly greater
        count, so the first-seen key among equal-count types is what
        `max` already returns - no separate tie-breaking step needed.

        An empty history (or one with no successful records) returns
        `None` rather than raising."""
        records = history.get_all()
        if not records:
            return None

        by_change_type = {}
        for record in records:
            change_type = record.get("change_type")
            by_change_type[change_type] = by_change_type.get(change_type, 0) + 1

        return max(by_change_type, key=by_change_type.get)

    def get_change_type_counts(self, history):
        """Return `{change_type: count}` over every successful record
        currently in `history` - the same tally `analyze`'s
        `by_change_type` already computes, exposed here directly for a
        caller that only wants that one dict rather than the full
        `analyze` result.

        An empty history (or one with no successful records) returns
        `{}` rather than raising."""
        records = history.get_all()

        counts = {}
        for record in records:
            change_type = record.get("change_type")
            counts[change_type] = counts.get(change_type, 0) + 1
        return counts

    def get_step_change_counts(self, history, step_id):
        """Return `{change_type: count}` over every successful record
        in `history` whose `target_step_id` equals `step_id` - the
        same per-`change_type` tally `get_change_type_counts` computes,
        narrowed here to one step.

        A `step_id` with no recorded successful changes (including an
        unknown one, or an otherwise-empty `history`) returns `{}`
        rather than raising."""
        records = history.get_all()

        counts = {}
        for record in records:
            if record.get("target_step_id") != step_id:
                continue
            change_type = record.get("change_type")
            counts[change_type] = counts.get(change_type, 0) + 1
        return counts

    def get_summary(self, history):
        """Return `{total_successful_changes, change_type_counts,
        most_frequent_change_type}` for `history` - a single small
        dict composed from this class's own existing methods
        (`get_change_type_counts` for the count map,
        `most_frequent_change_type` for the tie-broken leader) rather
        than re-deriving either tally here.

        An empty history (or one with no successful records) returns
        `{"total_successful_changes": 0, "change_type_counts": {},
        "most_frequent_change_type": None}` rather than raising."""
        change_type_counts = self.get_change_type_counts(history)
        return {
            "total_successful_changes": sum(change_type_counts.values()),
            "change_type_counts": change_type_counts,
            "most_frequent_change_type": self.most_frequent_change_type(history),
        }
