"""
Self-Upgrade Request
=======================
`SelfUpgradeRequest` is a small, standalone data record representing
one request to consider a self-upgrade:

    SOME CALLER -> SelfUpgradeRequest -> [analysis/execution: not built yet]

This stage only defines the *shape* of a self-upgrade request - it
does NOT analyze it, approve it, execute it, or connect it to
`self_upgrade.upgrade_system.UpgradeSystem`, `agent.code_change_
upgrade_result`, or `agent.code_change_upgrade_state` (both unchanged
by this module - requirements 6, 7: "do not execute upgrades yet",
"do not modify existing upgrade behavior"). It is a plain, standalone
record for now, not wired into any manager, planner, or execution
stage.

Same "construction never raises, is_valid() is a plain boolean check"
convention already used by `RevenueTask`
(financial/revenue_task.py), `RevenueOpportunity`
(financial/revenue_opportunity.py), and `FinancialGoal`
(financial/financial_goal.py) - a caller can freely build a
`SelfUpgradeRequest` from untrusted/partial input and then call
`is_valid()` to decide whether it is fit to use, rather than having to
wrap construction in a try/except (requirement 8: reuse existing
project conventions and naming patterns). Same "plain, JSON-shaped
`to_dict()` record" convention already used by `Goal`
(planning/goal.py), `RevenueTask`, and `UnderstandingResult`
(understanding/result.py) - see `to_dict()` below (requirement 5:
"make the model serializable").
"""

from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Small, fixed vocabulary for request status (requirement 3) - same
# STATUS_* pattern already used throughout this project (see
# financial/revenue_task.py, planning/goal.py). A request starts life
# as REQUESTED - nothing in this module ever moves it further along
# on its own (requirement 6: no execution happens here); that always
# requires an explicit change by a future caller.
STATUS_REQUESTED = "REQUESTED"
STATUS_ANALYZING = "ANALYZING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_REJECTED = "REJECTED"

ALL_STATUSES = (
    STATUS_REQUESTED, STATUS_ANALYZING, STATUS_COMPLETED, STATUS_FAILED, STATUS_REJECTED,
)

DEFAULT_STATUS = STATUS_REQUESTED


class SelfUpgradeRequest:
    """One request to consider a self-upgrade - captured but not yet
    analyzed or acted on. Purely a data record: construction never
    raises (unlike e.g. `execution.execution_result.ExecutionResult`)
    so a caller can freely build a `SelfUpgradeRequest` from untrusted/
    partial data and then use `is_valid()` to decide whether it is fit
    to use.
    """

    __slots__ = (
        "request_id", "goal", "requested_capability", "reason", "status", "created_at",
    )

    def __init__(
        self,
        request_id,
        goal,
        requested_capability,
        reason=None,
        status=DEFAULT_STATUS,
        created_at=None,
    ):
        self.request_id = request_id
        self.goal = goal
        self.requested_capability = requested_capability
        self.reason = reason if reason is not None else ""
        self.status = status
        self.created_at = created_at if created_at is not None else _now_iso()

    def __repr__(self):
        return (
            f"SelfUpgradeRequest(request_id={self.request_id!r}, "
            f"goal={self.goal!r}, requested_capability={self.requested_capability!r}, "
            f"status={self.status!r})"
        )

    # ------------------------------------------------------------------
    # Validation (requirement 4)
    # ------------------------------------------------------------------
    def is_valid(self):
        """Plain boolean check - never raises. A request is valid when:
        - request_id is a non-empty string
        - goal is a non-empty string (requirement 4)
        - requested_capability is a non-empty string (requirement 4)
        - reason is a string (may be empty - not required non-empty)
        - status is one of the supported values (see ALL_STATUSES)

        This intentionally says nothing about whether the requested
        upgrade is actually a good idea, safe, or will ever be acted
        on - only whether the record is well-formed enough to use.
        """
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            return False
        if not isinstance(self.goal, str) or not self.goal.strip():
            return False
        if not isinstance(self.requested_capability, str) or not self.requested_capability.strip():
            return False
        if not isinstance(self.reason, str):
            return False
        if self.status not in ALL_STATUSES:
            return False
        return True

    # ------------------------------------------------------------------
    # Serialization (requirement 5)
    # ------------------------------------------------------------------
    def to_dict(self):
        """Structured (JSON-shaped) representation - the general-
        purpose serialization for this record. Every value is read
        directly off this instance's own fields, unchanged."""
        return {
            "request_id": self.request_id,
            "goal": self.goal,
            "requested_capability": self.requested_capability,
            "reason": self.reason,
            "status": self.status,
            "created_at": self.created_at,
        }
