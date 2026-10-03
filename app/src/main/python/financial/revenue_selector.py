"""
Revenue Opportunity Selector
==============================
`RevenueOpportunitySelector` chooses which already-discovered
`RevenueOpportunity` records (financial/revenue_opportunity.py) look
most worth pursuing, out of a set a caller hands it:

    RevenueOpportunity records -> RevenueOpportunitySelector.select()
        -> SelectionResult -> [Work Planning / Execution: not built yet]

This is one step in the eventual, much larger pipeline described for
this project's long-term direction:

    GOAL -> FIND OPPORTUNITIES -> CREATE STRATEGIES -> PLAN WORK ->
    USE TOOLS -> EXECUTE -> MEASURE REVENUE -> LEARN -> IMPROVE -> REPEAT

This stage only *chooses among already-structured data*. It does NOT
claim or guarantee that a selected opportunity will actually generate
any income - every `SelectionResult.reason` this module produces says
so explicitly. It also never does any of the following:

- execute an opportunity, or a business, in any way
- access a bank, transfer money, or make a purchase
- contact a customer, publish content, or access a website
- bypass a permission or hack a system
- fabricate money, fabricate revenue, or create a fake transaction

Selection is built entirely on top of the deterministic ranking
already implemented by `RevenueOpportunityPlanner.rank_opportunities`
(financial/revenue_opportunity_planner.py) - the same four factors
(confidence, then risk_level, then effort_level, then estimated_income
as a tiebreaker), the same documented ordering, and the same "no
random selection, no hidden combined score" guarantees. This module
does not reimplement or duplicate that ranking logic - it only decides
how many top-ranked opportunities to keep, records why each excluded
one was excluded, and packages the result as a `SelectionResult`.
"""

import copy

from .revenue_opportunity import RevenueOpportunity
from .revenue_opportunity_planner import RevenueOpportunityPlanner


class SelectionResult:
    """Plain, JSON-shaped record of one `select()` /
    `select_for_goal()` call - same "structured record, not formatted
    text" convention already used by `ReasoningResult`
    (reasoning/reasoning_result.py).

    - `selected_opportunities`: plain list (never None) of the chosen
      `RevenueOpportunity` records, deep-copied, most-promising-first.
    - `rejected_opportunities`: plain list (never None) of
      `{"opportunity_id": ..., "reason": ...}` dicts - one entry per
      opportunity that was considered but not selected, each with a
      specific, human-readable reason (invalid, goal mismatch, or
      ranked below the cutoff). Never bare opportunity objects, so a
      caller never has to re-derive why something was left out.
    - `reason`: a single overall, human-readable explanation of how
      this selection was made. Always states plainly that this is an
      estimate-based ranking, not a guarantee of income.
    - `confidence`: the mean `confidence` of `selected_opportunities`
      (0.0 if none were selected) - a deterministic summary of how
      confident the selection *as a whole* is, computed the same way
      every time from the same inputs.
    - `warnings`: plain list (never None) of short, human-readable
      notes about anything unusual in the input (an empty list, all
      entries invalid, a limit of zero, etc).
    """

    def __init__(self):
        self.selected_opportunities = []
        self.rejected_opportunities = []
        self.reason = ""
        self.confidence = 0.0
        self.warnings = []

    def __repr__(self):
        return (
            f"SelectionResult(selected={len(self.selected_opportunities)}, "
            f"rejected={len(self.rejected_opportunities)}, "
            f"confidence={self.confidence:.4f})"
        )

    def to_dict(self):
        return {
            "selected_opportunities": [o.to_dict() for o in self.selected_opportunities],
            "rejected_opportunities": list(self.rejected_opportunities),
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
            "warnings": list(self.warnings),
        }


def _describe(opportunity):
    """A short, human-readable label for an opportunity used in
    rejection reasons and warnings - falls back gracefully for
    malformed input instead of raising."""
    opportunity_id = getattr(opportunity, "opportunity_id", None)
    if isinstance(opportunity_id, str) and opportunity_id.strip():
        return opportunity_id
    return repr(opportunity)


_NO_GUARANTEE_NOTE = (
    "This selection is based only on each opportunity's own stored "
    "estimates (confidence, estimated income, effort level, and risk "
    "level) and does not guarantee that any selected opportunity will "
    "actually generate income."
)


class RevenueOpportunitySelector:
    """Stateless (holds no data between calls): every method takes
    what it needs as arguments and returns a fresh result, so a single
    instance - or a fresh one per call - behaves identically. Same
    "no hidden state driving a decision" spirit as
    `RevenueOpportunityPlanner`.

    An internal `RevenueOpportunityPlanner` is used purely for its
    already-deterministic `rank_opportunities` - this class never
    calls any of the planner's generation methods and never creates,
    stores, or mutates a `RevenueOpportunity` of its own.
    """

    def __init__(self, planner=None):
        self._planner = planner if planner is not None else RevenueOpportunityPlanner()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def select(self, opportunities, limit=1):
        """Choose up to `limit` of the most promising opportunities in
        `opportunities`, using only `RevenueOpportunityPlanner`'s
        deterministic ranking (confidence, then risk_level, then
        effort_level, then estimated_income).

        Returns a `SelectionResult`. Never raises - entries that
        aren't a valid `RevenueOpportunity` are recorded in
        `rejected_opportunities` with a reason instead of causing a
        failure. `limit <= 0` selects nothing (a warning is recorded
        explaining why).
        """
        return self._select(opportunities, limit=limit, goal_id=None)

    def select_for_goal(self, opportunities, goal_id, limit=1):
        """Same as `select`, but first restricts consideration to
        opportunities whose `goal_id` exactly matches `goal_id`.
        Opportunities for a different goal are recorded in
        `rejected_opportunities` with an explicit "different goal"
        reason rather than being silently dropped.
        """
        return self._select(opportunities, limit=limit, goal_id=goal_id)

    def _select(self, opportunities, limit, goal_id):
        result = SelectionResult()
        opportunities = list(opportunities) if opportunities else []

        if not opportunities:
            result.reason = (
                "No opportunities were provided, so none could be selected. "
                + _NO_GUARANTEE_NOTE
            )
            result.warnings.append("The opportunities list was empty.")
            return result

        # Step 1: split out anything that isn't even a valid
        # RevenueOpportunity, or (for select_for_goal) doesn't belong
        # to the requested goal - both recorded with a specific reason,
        # neither ever raises.
        in_scope = []
        for opportunity in opportunities:
            if not isinstance(opportunity, RevenueOpportunity) or not opportunity.is_valid():
                result.rejected_opportunities.append({
                    "opportunity_id": _describe(opportunity),
                    "reason": "excluded: not a valid RevenueOpportunity record.",
                })
                continue
            if goal_id is not None and opportunity.goal_id != goal_id:
                result.rejected_opportunities.append({
                    "opportunity_id": opportunity.opportunity_id,
                    "reason": f"excluded: belongs to a different goal ({opportunity.goal_id!r}).",
                })
                continue
            in_scope.append(opportunity)

        if not in_scope:
            result.reason = (
                "No valid opportunities were available to select from. "
                + _NO_GUARANTEE_NOTE
            )
            result.warnings.append(
                "None of the provided opportunities were eligible for selection."
            )
            return result

        # Step 2: deterministic ranking - delegated entirely to
        # RevenueOpportunityPlanner, never reimplemented here.
        ranked = self._planner.rank_opportunities(in_scope)

        # Step 3: keep the top `limit`, record why the rest were left out.
        if limit is None or limit <= 0:
            result.warnings.append(
                f"limit was {limit!r} (<= 0), so no opportunities were selected."
            )
            selected, remainder = [], ranked
        else:
            selected, remainder = ranked[:limit], ranked[limit:]
            if limit > len(ranked):
                result.warnings.append(
                    f"Only {len(ranked)} valid opportunity(ies) were available; "
                    f"requested limit was {limit}."
                )

        for rank, opportunity in enumerate(remainder, start=len(selected) + 1):
            result.rejected_opportunities.append({
                "opportunity_id": opportunity.opportunity_id,
                "reason": (
                    f"ranked #{rank} of {len(ranked)} valid opportunities - "
                    "below the requested selection limit."
                ),
            })

        result.selected_opportunities = [copy.deepcopy(o) for o in selected]
        result.confidence = (
            round(sum(o.confidence for o in selected) / len(selected), 4) if selected else 0.0
        )
        result.reason = (
            (
                f"Selected {len(selected)} of {len(ranked)} valid opportunity(ies), "
                "ranked deterministically by confidence, then risk level, then "
                "effort level, then estimated income (see "
                "RevenueOpportunityPlanner.rank_opportunities). "
            )
            + _NO_GUARANTEE_NOTE
        )
        return result

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------
    def inspect(self, opportunities):
        """A transparent, read-only report on `opportunities` - what
        would happen if they were ranked, without actually selecting
        or limiting anything.

        Returns a plain list (never None), in the same order as
        `opportunities`, of dicts:

            {
                "opportunity_id": str,
                "valid": bool,
                "rank": int or None,       # 1-based rank among the
                                            # valid entries, by the same
                                            # deterministic ranking
                                            # `select()` uses; None if
                                            # not valid
                "confidence": float or None,
                "estimated_income": number or None,
                "effort_level": str or None,
                "risk_level": str or None,
                "reason": str,             # why it's valid/invalid
            }

        Never raises, and never itself claims any opportunity will
        generate income - it only reports the stored factors as-is.
        """
        opportunities = list(opportunities) if opportunities else []

        valid_opportunities = [
            o for o in opportunities if isinstance(o, RevenueOpportunity) and o.is_valid()
        ]
        ranked = self._planner.rank_opportunities(valid_opportunities)
        rank_by_id = {o.opportunity_id: i + 1 for i, o in enumerate(ranked)}

        report = []
        for opportunity in opportunities:
            if not isinstance(opportunity, RevenueOpportunity):
                report.append({
                    "opportunity_id": _describe(opportunity),
                    "valid": False,
                    "rank": None,
                    "confidence": None,
                    "estimated_income": None,
                    "effort_level": None,
                    "risk_level": None,
                    "reason": "Not a RevenueOpportunity instance.",
                })
                continue

            if not opportunity.is_valid():
                report.append({
                    "opportunity_id": _describe(opportunity),
                    "valid": False,
                    "rank": None,
                    "confidence": None,
                    "estimated_income": None,
                    "effort_level": None,
                    "risk_level": None,
                    "reason": "Failed RevenueOpportunity.is_valid().",
                })
                continue

            report.append({
                "opportunity_id": opportunity.opportunity_id,
                "valid": True,
                "rank": rank_by_id.get(opportunity.opportunity_id),
                "confidence": opportunity.confidence,
                "estimated_income": opportunity.estimated_income,
                "effort_level": opportunity.effort_level,
                "risk_level": opportunity.risk_level,
                "reason": "Valid; ranked by confidence, risk level, effort level, and estimated income.",
            })

        return report
