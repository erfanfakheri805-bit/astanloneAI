"""
Revenue Opportunity
======================
`RevenueOpportunity` is a small, standalone data record representing
one concrete, structured possibility for working toward a
`FinancialGoal` (financial/financial_goal.py), usually surfaced from a
`RevenueStrategy` (financial/revenue_strategy.py):

    FinancialGoal + RevenueStrategy -> ... -> RevenueOpportunity
        -> [Work Planning / Execution: not built yet]

This is one step in the eventual, much larger pipeline described for
this project's long-term direction:

    GOAL -> FIND OPPORTUNITIES -> CREATE STRATEGIES -> PLAN WORK ->
    USE TOOLS -> EXECUTE -> MEASURE REVENUE -> LEARN -> IMPROVE -> REPEAT

This stage only defines the *shape* of an opportunity - it does NOT
implement any later stage in that pipeline. In particular this module
(and its planner, revenue_opportunity_planner.py):

- Does NOT claim or guarantee that any opportunity will make money -
  `estimated_income` and `confidence` are estimates only.
- Does NOT execute businesses, contact customers, make purchases,
  transfer money, access bank accounts, or create any financial
  transaction.
- Does NOT access websites, send messages, or publish content.
- Does NOT hack systems, bypass permissions, or impersonate anyone.
- Does NOT conceal financial activity in any way.

A RevenueOpportunity only records a *candidate, structured
possibility* - so a later planning/execution stage (not part of this
stage) has something concrete to evaluate, choose from, and, if a
human or a future authorized stage decides to, act on.

Same "construction never raises, is_valid() is a plain boolean check"
convention already used by `RevenueStrategy`
(financial/revenue_strategy.py) and `FinancialGoal`
(financial/financial_goal.py): a caller can freely build a
RevenueOpportunity from untrusted/partial input and then call
`is_valid()` to decide whether it is fit to use, rather than having to
wrap construction in a try/except.
"""

from datetime import datetime, timezone

from .revenue_task import RevenueTask


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Small, fixed vocabulary for opportunity status (matches the STATUS_*
# pattern already used by financial/revenue_strategy.py and
# financial/financial_goal.py) so callers can branch on it reliably
# instead of comparing against free-form strings. An opportunity starts
# life as DISCOVERED - nothing in this module or in
# revenue_opportunity_planner.py ever moves it further along on its
# own; that always requires an explicit `update_status` call from a
# caller (see revenue_opportunity_manager.py).
STATUS_DISCOVERED = "DISCOVERED"
STATUS_PROPOSED = "PROPOSED"
STATUS_SELECTED = "SELECTED"
STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_REJECTED = "REJECTED"

ALL_STATUSES = (
    STATUS_DISCOVERED, STATUS_PROPOSED, STATUS_SELECTED, STATUS_ACTIVE,
    STATUS_COMPLETED, STATUS_FAILED, STATUS_REJECTED,
)

DEFAULT_STATUS = STATUS_DISCOVERED

# Fixed, three-level vocabulary for `effort_level` and `risk_level`.
# Unlike `revenue_model` (an open reference vocabulary - see
# financial/revenue_strategy.py), these two ARE a closed enum: the
# (deterministic, transparent) ranking done by
# revenue_opportunity_planner.py's `rank_opportunities` depends on
# being able to order these values unambiguously.
LEVEL_LOW = "LOW"
LEVEL_MEDIUM = "MEDIUM"
LEVEL_HIGH = "HIGH"

ALL_LEVELS = (LEVEL_LOW, LEVEL_MEDIUM, LEVEL_HIGH)

DEFAULT_EFFORT_LEVEL = LEVEL_MEDIUM
DEFAULT_RISK_LEVEL = LEVEL_MEDIUM

# Safe, structured-data-only types allowed inside the structured
# fields (`required_capabilities`, `required_tools`, `required_inputs`,
# `expected_outputs`, `metadata`). Same convention as
# financial/revenue_strategy.py's own `_is_safe_structured_value`.
_SAFE_SCALAR_TYPES = (str, int, float, bool, type(None))


def _is_safe_structured_value(value):
    """True if `value` is made only of plain, structured data (str,
    int, float, bool, None, list/tuple, dict with string keys) -
    recursively. No functions, class instances, or other objects that
    could carry behavior."""
    if isinstance(value, _SAFE_SCALAR_TYPES):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_safe_structured_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_safe_structured_value(val)
            for key, val in value.items()
        )
    return False


class RevenueOpportunity:
    """One concrete, structured possibility for working toward a
    FinancialGoal - captured but not yet acted on. Purely a data
    record: construction never raises (unlike e.g. ExecutionResult) so
    a caller can freely build a RevenueOpportunity from untrusted/
    partial data and then use `is_valid()` to decide whether it is fit
    to use.

    `strategy_id` may be `None` - an opportunity does not have to be
    traced back to an existing `RevenueStrategy` to be recorded (a
    future discovery stage may surface opportunities directly).

    `required_capabilities`, `required_tools`, `required_inputs`, and
    `expected_outputs` are always plain lists (never None); `metadata`
    is always a plain dict (never None) - same "no None checks needed
    by callers" convention as RevenueStrategy's own list/dict fields
    (financial/revenue_strategy.py).
    """

    __slots__ = (
        "opportunity_id", "goal_id", "strategy_id", "name", "description",
        "revenue_model", "required_capabilities", "required_tools",
        "required_inputs", "expected_outputs", "estimated_income",
        "currency", "time_period", "effort_level", "risk_level",
        "confidence", "status", "created_at", "metadata", "task_ids",
    )

    def __init__(
        self,
        opportunity_id,
        goal_id,
        strategy_id=None,
        name=None,
        description=None,
        revenue_model=None,
        required_capabilities=None,
        required_tools=None,
        required_inputs=None,
        expected_outputs=None,
        estimated_income=None,
        currency=None,
        time_period=None,
        effort_level=DEFAULT_EFFORT_LEVEL,
        risk_level=DEFAULT_RISK_LEVEL,
        confidence=0.0,
        status=DEFAULT_STATUS,
        created_at=None,
        metadata=None,
        task_ids=None,
    ):
        self.opportunity_id = opportunity_id
        self.goal_id = goal_id
        self.strategy_id = strategy_id
        self.name = name
        self.description = description
        self.revenue_model = revenue_model
        self.required_capabilities = (
            list(required_capabilities) if required_capabilities else []
        )
        self.required_tools = list(required_tools) if required_tools else []
        self.required_inputs = list(required_inputs) if required_inputs else []
        self.expected_outputs = list(expected_outputs) if expected_outputs else []
        self.estimated_income = estimated_income
        self.currency = currency
        self.time_period = time_period
        self.effort_level = effort_level
        self.risk_level = risk_level
        self.confidence = confidence
        self.status = status
        self.created_at = created_at if created_at is not None else _now_iso()
        self.metadata = dict(metadata) if metadata else {}
        if task_ids is None:
            self.task_ids = []
        elif isinstance(task_ids, (list, tuple)):
            self.task_ids = list(task_ids)
        else:
            self.task_ids = []

    def __repr__(self):
        return (
            f"RevenueOpportunity(opportunity_id={self.opportunity_id!r}, "
            f"goal_id={self.goal_id!r}, strategy_id={self.strategy_id!r}, "
            f"name={self.name!r}, status={self.status!r})"
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def is_valid(self):
        """Plain boolean check - never raises. An opportunity is valid
        when:
        - opportunity_id and goal_id are non-empty strings
        - strategy_id is either None or a non-empty string
        - name and description are non-empty strings
        - estimated_income is numeric (int/float, not bool) and >= 0
        - currency and time_period are non-empty strings
        - effort_level and risk_level are each one of LOW/MEDIUM/HIGH
        - confidence is a number between 0.0 and 1.0 (inclusive)
        - status is one of the supported values (see ALL_STATUSES)
        - required_capabilities, required_tools, required_inputs,
          expected_outputs, and metadata contain only safe, structured
          data (see `_is_safe_structured_value`)

        `revenue_model` is intentionally not restricted to a fixed set
        - same reasoning as RevenueStrategy.is_valid()
        (financial/revenue_strategy.py).

        This intentionally says nothing about whether the opportunity
        would actually pay off - only whether the record is well-formed
        enough to use.
        """
        if not isinstance(self.opportunity_id, str) or not self.opportunity_id.strip():
            return False
        if not isinstance(self.goal_id, str) or not self.goal_id.strip():
            return False

        if self.strategy_id is not None:
            if not isinstance(self.strategy_id, str) or not self.strategy_id.strip():
                return False

        for field in (self.name, self.description):
            if not isinstance(field, str) or not field.strip():
                return False

        if isinstance(self.estimated_income, bool):
            return False
        if not isinstance(self.estimated_income, (int, float)):
            return False
        if self.estimated_income < 0:
            return False

        if not isinstance(self.currency, str) or not self.currency.strip():
            return False
        if not isinstance(self.time_period, str) or not self.time_period.strip():
            return False

        if self.effort_level not in ALL_LEVELS:
            return False
        if self.risk_level not in ALL_LEVELS:
            return False

        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            return False
        if not (0.0 <= self.confidence <= 1.0):
            return False

        if self.status not in ALL_STATUSES:
            return False

        for structured_field in (
            self.required_capabilities,
            self.required_tools,
            self.required_inputs,
            self.expected_outputs,
            self.metadata,
        ):
            if not _is_safe_structured_value(structured_field):
                return False

        return True

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def get_required_capabilities(self):
        """A plain list (never None) of capabilities this opportunity
        would need. This stage never checks whether they exist or
        grants/uses any of them."""
        return list(self.required_capabilities)

    def get_required_tools(self):
        """A plain list (never None) of tools this opportunity would
        need. This stage never installs, invokes, or otherwise touches
        any of them."""
        return list(self.required_tools)

    def get_expected_outputs(self):
        """A plain list (never None) of outputs this opportunity is
        expected to produce. Purely descriptive - nothing here is
        produced or verified by this stage."""
        return list(self.expected_outputs)

    def get_estimated_income(self):
        """The requested/estimated income, exactly as stored - never a
        promise or guarantee that this amount will actually be
        earned."""
        return self.estimated_income

    def get_task_ids(self):
        """A new list (never None, and never the opportunity's own
        internal list) of the task IDs currently tracked against this
        opportunity - a safe copy, so mutating the returned list never
        affects this opportunity. This stage only tracks these IDs; it
        never creates, loads, executes, or otherwise looks up the
        tasks themselves."""
        return list(self.task_ids)

    def has_tasks(self):
        """True only when task_ids contains at least one valid,
        non-empty string ID, False otherwise (including when
        task_ids is empty or contains only invalid entries). A plain,
        read-only check - never modifies task_ids or any other
        field."""
        return any(
            isinstance(task_id, str) and task_id.strip()
            for task_id in self.task_ids
        )

    def can_accept_task(self, task):
        """True only when `task` is a valid RevenueTask instance (see
        RevenueTask.is_valid()) that has a valid, non-empty
        opportunity_id (see RevenueTask.has_opportunity()) matching
        this opportunity's own opportunity_id exactly (see
        RevenueTask.belongs_to_opportunity()) - False otherwise,
        including when `task` is not a RevenueTask at all. A plain,
        read-only, in-memory check reusing RevenueTask's own
        validation/helper methods rather than duplicating that logic
        - never modifies `task` or this opportunity, never assigns
        the task, never creates a task, never performs a database
        lookup or other lookup, and never executes anything."""
        if not isinstance(task, RevenueTask):
            return False
        if not task.is_valid():
            return False
        if not task.has_opportunity():
            return False
        return task.belongs_to_opportunity(self.opportunity_id)

    def attach_task(self, task):
        """Attach an existing RevenueTask to this opportunity by
        recording its task_id in task_ids - reusing can_accept_task()
        to reject `task` (returning False, without modifying
        task_ids) when it is not a valid RevenueTask, is invalid, or
        does not belong to this opportunity. Also returns False,
        without modifying task_ids, when `task.task_id` is already
        present (no duplicate IDs). On success, appends only
        task.task_id - never the task object itself - to task_ids and
        returns True. Never creates a task, never executes a task,
        never modifies `task` itself, and never performs a database
        or network operation."""
        if not self.can_accept_task(task):
            return False
        if task.task_id in self.task_ids:
            return False
        self.task_ids.append(task.task_id)
        return True

    def remove_task(self, task_id):
        """Remove `task_id` from task_ids if it is present, returning
        True in that case. Returns False, without modifying task_ids,
        when `task_id` is not a non-empty string or is not currently
        present. Never modifies any other field on this opportunity,
        and never touches the referenced RevenueTask itself (this
        stage only tracks IDs, never full task objects) - no
        database or network operation, no task execution or
        creation."""
        if not isinstance(task_id, str) or not task_id.strip():
            return False
        if task_id not in self.task_ids:
            return False
        self.task_ids.remove(task_id)
        return True

    def has_task(self, task_id):
        """True only when `task_id` is a non-empty string that is
        currently present in task_ids, False otherwise - including
        for an empty/whitespace-only string, a non-string value, or
        an ID that simply isn't attached. A plain, read-only
        membership check against the existing task_ids list - never
        modifies task_ids or any other field on this opportunity, and
        never touches the referenced RevenueTask itself."""
        if not isinstance(task_id, str) or not task_id.strip():
            return False
        return task_id in self.task_ids

    def get_task_id(self, task_id):
        """The matching stored task ID when `task_id` is currently
        attached (per has_task()), otherwise None - including when
        `task_id` is invalid or empty. Since a matching stored ID is
        always equal to `task_id` itself, this simply returns
        `task_id` when has_task(task_id) is True, reusing that
        existing check rather than re-deriving the membership logic.
        A plain, read-only lookup - never modifies task_ids or any
        other field on this opportunity, never loads or inspects any
        RevenueTask object, and never creates, removes, or executes
        any task."""
        if not self.has_task(task_id):
            return None
        return task_id

    def get_attached_task_ids(self):
        """A new list of every valid, non-empty string task ID
        currently stored in task_ids - the same "valid" rule
        has_tasks() and get_task_count() already apply - with any
        invalid/empty entries left out. Always a fresh list, never a
        reference to the opportunity's own internal task_ids (so
        mutating the result can never affect this opportunity). A
        plain, read-only check - never modifies task_ids or any
        other field on this opportunity, never loads or inspects any
        RevenueTask object, and never creates, removes, or executes
        any task."""
        return [
            task_id
            for task_id in self.task_ids
            if isinstance(task_id, str) and task_id.strip()
        ]

    def get_task_count(self):
        """The number of valid, non-empty string task IDs currently
        stored in task_ids - 0 when there are none. Only counts
        entries that are non-empty strings (the same rule has_tasks()
        already applies), ignoring any invalid/empty entries that may
        be present. A plain, read-only check - never modifies
        task_ids or any other field on this opportunity, never
        creates, removes, or executes any task."""
        return sum(
            1
            for task_id in self.task_ids
            if isinstance(task_id, str) and task_id.strip()
        )

    def get_task_summary(self):
        """A small structured (JSON-shaped) summary of this
        opportunity's attached task IDs: opportunity_id exactly as
        stored, task_count and has_tasks (from get_task_count() and
        has_tasks() respectively), and task_ids - a new list from
        get_task_ids(), so mutating either the returned dict or its
        task_ids list never affects this opportunity. Built entirely
        from the existing helper methods rather than re-deriving any
        logic. A plain, read-only check - only ever looks at the
        stored task ID strings, never inspects or loads any
        RevenueTask object, never modifies this opportunity's
        task_ids or any other field, and never creates, removes, or
        executes any task."""
        return {
            "opportunity_id": self.opportunity_id,
            "task_count": self.get_task_count(),
            "has_tasks": self.has_tasks(),
            "task_ids": self.get_task_ids(),
        }

    def get_adjacent_task_ids(self, task_id):
        """A new dict of the task IDs immediately before and after
        `task_id` in task_ids, or None when `task_id` is invalid or
        not currently attached. `task_id` is trimmed of leading/
        trailing whitespace before lookup. Built entirely from
        existing helper methods - has_task() to check attachment,
        get_previous_task_id() and get_next_task_id() for the
        neighbors - rather than re-deriving any of that logic.

        On success, returns a dict with:
        - previous_task_id: from get_previous_task_id(), None when
          `task_id` is the first (valid) task
        - next_task_id: from get_next_task_id(), None when `task_id`
          is the last (valid) task

        A plain, read-only check - never modifies task_ids or any
        other field on this opportunity, never inspects or loads any
        RevenueTask object, and never creates, removes, moves, or
        executes any task."""
        if not isinstance(task_id, str):
            return None
        stripped = task_id.strip()
        if not self.has_task(stripped):
            return None
        return {
            "previous_task_id": self.get_previous_task_id(stripped),
            "next_task_id": self.get_next_task_id(stripped),
        }

    def get_last_task_id(self):
        """The last valid, non-empty string task ID in task_ids
        (leading/trailing whitespace trimmed), or None when there are
        no valid task IDs at all. Non-string values, empty strings,
        and whitespace-only strings are ignored. Built on top of
        get_valid_task_ids() rather than re-deriving that filtering/
        trimming logic. A plain, read-only check - never modifies
        task_ids or any other field on this opportunity, never
        inspects or loads any RevenueTask object, and never creates,
        removes, moves, or executes any task."""
        valid_ids = self.get_valid_task_ids()
        return valid_ids[-1] if valid_ids else None

    def get_first_task_id(self):
        """The first valid, non-empty string task ID in task_ids
        (leading/trailing whitespace trimmed), or None when there are
        no valid task IDs at all. Non-string values, empty strings,
        and whitespace-only strings are ignored. Built on top of
        get_valid_task_ids() rather than re-deriving that filtering/
        trimming logic. A plain, read-only check - never modifies
        task_ids or any other field on this opportunity, never
        inspects or loads any RevenueTask object, and never creates,
        removes, moves, or executes any task."""
        valid_ids = self.get_valid_task_ids()
        return valid_ids[0] if valid_ids else None

    def get_previous_task_id(self, task_id):
        """The previous valid, non-empty string task ID that precedes
        `task_id` in task_ids, or None when `task_id` is invalid,
        not currently attached, is the first task, or none of the
        preceding entries before it are valid. `task_id` is trimmed
        of leading/trailing whitespace before lookup, and its current
        position is found via get_task_index() rather than
        re-deriving that lookup. Starting just before that position,
        this scans backward through task_ids and returns the first
        valid, non-empty string entry found - so a run of invalid
        entries immediately preceding `task_id` is skipped rather
        than returned.

        A plain, read-only lookup - never modifies task_ids or any
        other field on this opportunity, never inspects or loads any
        RevenueTask object, and never creates, removes, moves, or
        executes any task."""
        if not isinstance(task_id, str):
            return None
        stripped = task_id.strip()
        if not stripped:
            return None

        index = self.get_task_index(stripped)
        if index == -1:
            return None

        for candidate in reversed(self.task_ids[:index]):
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        return None

    def get_next_task_id(self, task_id):
        """The next valid, non-empty string task ID that follows
        `task_id` in task_ids, or None when `task_id` is invalid,
        not currently attached, is the last task, or none of the
        remaining entries after it are valid. `task_id` is trimmed of
        leading/trailing whitespace before lookup, and its current
        position is found via get_task_index() rather than
        re-deriving that lookup. Starting just after that position,
        this scans forward through task_ids and returns the first
        valid, non-empty string entry found - so a run of invalid
        entries immediately following `task_id` is skipped rather
        than returned.

        A plain, read-only lookup - never modifies task_ids or any
        other field on this opportunity, never inspects or loads any
        RevenueTask object, and never creates, removes, moves, or
        executes any task."""
        if not isinstance(task_id, str):
            return None
        stripped = task_id.strip()
        if not stripped:
            return None

        index = self.get_task_index(stripped)
        if index == -1:
            return None

        for candidate in self.task_ids[index + 1:]:
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        return None

    def get_task_validation_report(self):
        """A new, structured (JSON-shaped), read-only validation
        report for this opportunity's attached task IDs, built on top
        of check_task_attachment_consistency() rather than
        re-deriving any of that logic.

        Returns a dict with:
        - opportunity_id: this opportunity's own opportunity_id
        - task_count: the total number of stored task IDs
        - valid_task_count: how many entries are valid, non-empty
          strings (duplicates included)
        - invalid_task_count: how many entries are not valid,
          non-empty strings
        - duplicate_count: how many valid entries repeat an ID seen
          earlier in task_ids
        - valid: True only when there are no invalid task IDs and no
          duplicate task IDs (also True when task_ids is empty)
        - issues: a new list (never a reference to any internal
          state) of the same descriptive issue strings reported by
          check_task_attachment_consistency()

        Completely read-only - never modifies task_ids, opportunity_id,
        or any other field on this opportunity, and never inspects or
        loads any RevenueTask object (only the stored ID values
        themselves are checked)."""
        consistency = self.check_task_attachment_consistency()
        return {
            "opportunity_id": consistency["opportunity_id"],
            "task_count": consistency["task_count"],
            "valid_task_count": consistency["valid_task_count"],
            "invalid_task_count": consistency["invalid_task_count"],
            "duplicate_count": consistency["duplicate_count"],
            "valid": consistency["valid"],
            "issues": list(consistency["issues"]),
        }

    def get_task_status(self):
        """A new, structured (JSON-shaped), read-only status summary
        for this opportunity's attached task collection. Built on top
        of get_task_readiness() (which itself is built from
        has_tasks(), get_valid_task_ids(), and
        check_task_attachment_consistency()) rather than re-deriving
        any of that logic.

        Returns a dict with:
        - opportunity_id: this opportunity's own opportunity_id
        - has_tasks: from get_task_readiness()
        - task_count: from get_task_readiness()
        - valid_task_count: from get_task_readiness()
        - invalid_task_count: from get_task_readiness()
        - ready: from get_task_readiness()
        - status: one of "NO_TASKS", "INVALID_TASKS", or "READY",
          determined deterministically:
            * no valid task ID at all -> "NO_TASKS"
            * at least one valid task ID, but invalid and/or
              duplicate task IDs are present -> "INVALID_TASKS"
            * at least one valid task ID and no invalid/duplicate
              task IDs -> "READY"

        Completely read-only - never modifies task_ids or any other
        field on this opportunity, and never inspects or loads any
        RevenueTask object."""
        readiness = self.get_task_readiness()

        if not readiness["has_tasks"]:
            status = "NO_TASKS"
        elif not readiness["ready"]:
            status = "INVALID_TASKS"
        else:
            status = "READY"

        return {
            "opportunity_id": self.opportunity_id,
            "has_tasks": readiness["has_tasks"],
            "task_count": readiness["task_count"],
            "valid_task_count": readiness["valid_task_count"],
            "invalid_task_count": readiness["invalid_task_count"],
            "ready": readiness["ready"],
            "status": status,
        }

    def get_task_readiness(self):
        """A new, structured (JSON-shaped), read-only readiness report
        for this opportunity's attached task IDs. Built from existing
        helper methods - has_tasks(), get_task_count(),
        get_valid_task_ids(), and check_task_attachment_consistency()
        - rather than re-deriving any of that logic.

        The opportunity is only considered ready when it has at least
        one valid task ID (has_tasks()), there are no invalid task
        IDs, and there are no duplicate task IDs (both per
        check_task_attachment_consistency()).

        Returns a dict with:
        - opportunity_id: this opportunity's own opportunity_id
        - ready: True only when all three readiness conditions above
          hold
        - has_tasks: from has_tasks()
        - task_count: the total number of stored task IDs (valid or
          not), from len(task_ids)
        - valid_task_count: the number of valid, unique task IDs,
          from len(get_valid_task_ids())
        - invalid_task_count: from
          check_task_attachment_consistency()'s invalid_task_count
        - issues: a new list (never a reference to any internal
          state) of the same descriptive issue strings reported by
          check_task_attachment_consistency()

        Completely read-only and deterministic, based only on local
        data - never modifies task_ids or any other field on this
        opportunity, and never inspects or loads any RevenueTask
        object."""
        consistency = self.check_task_attachment_consistency()
        ready = (
            self.has_tasks()
            and consistency["invalid_task_count"] == 0
            and consistency["duplicate_count"] == 0
        )
        return {
            "opportunity_id": self.opportunity_id,
            "ready": ready,
            "has_tasks": self.has_tasks(),
            "task_count": len(self.task_ids),
            "valid_task_count": len(self.get_valid_task_ids()),
            "invalid_task_count": consistency["invalid_task_count"],
            "issues": list(consistency["issues"]),
        }

    def get_valid_task_ids(self):
        """A new list (never a reference to task_ids) of the valid,
        unique task IDs currently stored in task_ids: only non-empty
        string entries are kept (after stripping leading/trailing
        whitespace), non-string and empty/whitespace-only entries are
        dropped, duplicates are removed while keeping the first
        occurrence, and the original relative order is preserved.
        Purely a read-only inspection - never modifies task_ids or
        any other field on this opportunity (unlike
        normalize_task_ids(), which applies this same result back
        onto task_ids), and never inspects or loads any RevenueTask
        object."""
        seen = set()
        valid_ids = []
        for task_id in self.task_ids:
            if not isinstance(task_id, str):
                continue
            stripped = task_id.strip()
            if not stripped:
                continue
            if stripped in seen:
                continue
            seen.add(stripped)
            valid_ids.append(stripped)
        return valid_ids

    def check_task_attachment_consistency(self):
        """A new, structured (JSON-shaped), read-only consistency
        report for the task IDs currently stored in task_ids - never
        modifies task_ids or any other field, and never inspects,
        loads, creates, modifies, or executes any RevenueTask object
        (only the stored ID values themselves are checked). A task ID
        is valid when it is a string and is non-empty after trimming
        whitespace - the same rule already used elsewhere (e.g.
        has_tasks(), validate_task_ids()).

        Walks task_ids once, in order, and for each entry:
        - a non-string entry is counted invalid and adds an
          "invalid_task_id_type" issue
        - a string that is empty/whitespace-only after trimming is
          counted invalid and adds an "empty_task_id" issue
        - a valid, non-empty (trimmed) string that has already been
          seen is still counted as valid, but also counted as a
          duplicate and adds a "duplicate_task_id" issue
        - a valid, non-empty (trimmed) string seen for the first time
          is counted valid with no issue

        Returns a dict with:
        - opportunity_id: this opportunity's own opportunity_id
        - valid: True only when there are no invalid entries and no
          duplicates (also True when task_ids is empty)
        - task_count: the total number of stored task IDs
        - valid_task_count: how many entries are valid, non-empty
          strings (duplicates included)
        - invalid_task_count: how many entries are not valid,
          non-empty strings
        - duplicate_count: how many valid entries repeat an ID seen
          earlier in task_ids
        - issues: a new list (never a reference to any internal
          state) of simple descriptive issue strings, one per problem
          found, in the order encountered
        """
        seen = set()
        issues = []
        valid_task_count = 0
        invalid_task_count = 0
        duplicate_count = 0

        for index, task_id in enumerate(self.task_ids):
            if not isinstance(task_id, str):
                invalid_task_count += 1
                issues.append(
                    f"invalid_task_id_type at index {index}: {task_id!r}"
                )
                continue

            stripped = task_id.strip()
            if not stripped:
                invalid_task_count += 1
                issues.append(f"empty_task_id at index {index}")
                continue

            valid_task_count += 1
            if stripped in seen:
                duplicate_count += 1
                issues.append(
                    f"duplicate_task_id at index {index}: {stripped}"
                )
            else:
                seen.add(stripped)

        return {
            "opportunity_id": self.opportunity_id,
            "valid": invalid_task_count == 0 and duplicate_count == 0,
            "task_count": len(self.task_ids),
            "valid_task_count": valid_task_count,
            "invalid_task_count": invalid_task_count,
            "duplicate_count": duplicate_count,
            "issues": issues,
        }

    def get_task_reference(self, task_id):
        """A new, structured (JSON-shaped) reference dict for one
        attached task ID, or None when `task_id` is invalid or not
        currently attached. `task_id` is trimmed of leading/trailing
        whitespace before lookup. Built entirely from existing helper
        methods - has_task() to check attachment, get_task_id() for
        the matching stored ID, and get_task_index() for its current
        position - rather than re-deriving any of that logic.

        On success, returns a dict with:
        - opportunity_id: this opportunity's own opportunity_id
        - task_id: the matching stored task ID (from get_task_id())
        - index: its current zero-based position (from
          get_task_index())
        - attached: always True (this is only returned when the
          task ID is currently attached)

        A plain, read-only check - never inspects or loads any
        RevenueTask object, never creates, removes, moves, or
        executes any task, and never modifies task_ids or any other
        field on this opportunity."""
        if not isinstance(task_id, str):
            return None
        stripped = task_id.strip()
        if not self.has_task(stripped):
            return None
        return {
            "opportunity_id": self.opportunity_id,
            "task_id": self.get_task_id(stripped),
            "index": self.get_task_index(stripped),
            "attached": True,
        }

    def move_task(self, task_id, new_index):
        """Move an already-attached task ID to a different zero-based
        position within task_ids. `task_id` must be a non-empty
        string (leading/trailing whitespace is trimmed before
        lookup); `new_index` must be a plain int (bool is rejected,
        since it is not a genuine index). Returns False, without
        modifying task_ids, when `task_id` is invalid or not
        currently attached, when `new_index` is not a plain int, or
        when `new_index` is outside the valid range of existing
        positions (0 through len(task_ids) - 1). Moving a task to its
        current position is a no-op that still returns True and
        leaves task_ids unchanged. On a real move, every other task
        ID keeps its relative order. Modifies only task_ids - never
        any other field on this opportunity, and never inspects or
        loads any RevenueTask object."""
        if not isinstance(task_id, str):
            return False
        stripped = task_id.strip()
        if not stripped:
            return False
        if isinstance(new_index, bool) or not isinstance(new_index, int):
            return False
        if stripped not in self.task_ids:
            return False
        if not (0 <= new_index < len(self.task_ids)):
            return False

        current_index = self.task_ids.index(stripped)
        if current_index == new_index:
            return True

        self.task_ids.pop(current_index)
        self.task_ids.insert(new_index, stripped)
        return True

    def get_task_overview(self):
        """A new, structured (JSON-shaped) overview dict of this
        opportunity's attached task IDs: opportunity_id exactly as
        stored, task_count and has_tasks (from get_task_count() and
        has_tasks() respectively), task_ids - a safe copy from
        get_task_ids() - and first_task_id/last_task_id, the first
        and last valid, non-empty string task IDs (per
        get_attached_task_ids()), or None when there are none. Built
        entirely from existing helper methods rather than re-deriving
        any logic. A plain, read-only check - never inspects or loads
        any RevenueTask object, and never modifies task_ids or any
        other field on this opportunity."""
        valid_task_ids = self.get_attached_task_ids()
        return {
            "opportunity_id": self.opportunity_id,
            "task_count": self.get_task_count(),
            "has_tasks": self.has_tasks(),
            "task_ids": self.get_task_ids(),
            "first_task_id": valid_task_ids[0] if valid_task_ids else None,
            "last_task_id": valid_task_ids[-1] if valid_task_ids else None,
        }

    def get_task_snapshot(self):
        """A new, structured (JSON-shaped), read-only snapshot dict of
        this opportunity's currently attached task IDs. Built entirely
        from existing helper methods - get_valid_task_ids(),
        get_task_count(), get_first_task_id(), and get_last_task_id()
        - rather than re-deriving any of that logic.

        Returns a dict with:
        - opportunity_id: this opportunity's own opportunity_id
        - task_ids: a new, independent list from get_valid_task_ids()
          (never a reference to this opportunity's own internal
          task_ids list), so mutating the returned dict or its
          task_ids list can never affect this opportunity
        - task_count: from get_task_count()
        - first_task_id: from get_first_task_id(), None when there
          are no valid task IDs
        - last_task_id: from get_last_task_id(), None when there are
          no valid task IDs

        Completely read-only - never modifies task_ids or any other
        field on this opportunity, never inspects or loads any
        RevenueTask object, and never creates, removes, moves, or
        executes any task."""
        return {
            "opportunity_id": self.opportunity_id,
            "task_ids": self.get_valid_task_ids(),
            "task_count": self.get_task_count(),
            "first_task_id": self.get_first_task_id(),
            "last_task_id": self.get_last_task_id(),
        }

    def get_task_attachment_status(self, task_id):
        """A new, structured (JSON-shaped), read-only attachment status
        dict for one task ID, or None when `task_id` is invalid or
        empty. `task_id` is trimmed of leading/trailing whitespace
        before lookup. Built entirely from existing helper methods -
        has_task() to determine attachment, get_task_index() for the
        current position - rather than re-deriving any of that logic.

        Unlike get_adjacent_task_ids() and get_task_reference(), this
        always returns a dict for a well-formed `task_id`, whether or
        not it is currently attached.

        On success, returns a dict with:
        - opportunity_id: this opportunity's own opportunity_id
        - task_id: the trimmed task_id that was looked up
        - attached: True when the task ID is currently present in
          task_ids (per has_task()), False otherwise
        - index: its current zero-based position (from
          get_task_index()) when attached, -1 when not attached

        A plain, read-only check - never modifies task_ids or any
        other field on this opportunity, never inspects or loads any
        RevenueTask object, and never creates, removes, moves, or
        executes any task."""
        if not isinstance(task_id, str):
            return None
        stripped = task_id.strip()
        if not stripped:
            return None
        attached = self.has_task(stripped)
        return {
            "opportunity_id": self.opportunity_id,
            "task_id": stripped,
            "attached": attached,
            "index": self.get_task_index(stripped) if attached else -1,
        }

    def get_task_positions(self):
        """A new dict mapping each valid, non-empty (trimmed) string
        task ID currently stored in task_ids to its zero-based
        position in the current order. Non-string entries and empty/
        whitespace-only strings are ignored - the same "valid" rule
        used elsewhere (e.g. has_tasks(), get_valid_task_ids()). When
        the same valid ID appears more than once, the position of its
        first occurrence is kept.

        Always a fresh dict, never a reference to any internal state
        - mutating the result can never affect this opportunity. A
        plain, read-only check - never modifies task_ids or any other
        field on this opportunity, never inspects or loads any
        RevenueTask object, and never creates, removes, moves, or
        executes any task."""
        positions = {}
        for index, task_id in enumerate(self.task_ids):
            if not isinstance(task_id, str):
                continue
            stripped = task_id.strip()
            if not stripped:
                continue
            if stripped in positions:
                continue
            positions[stripped] = index
        return positions

    def get_task_id_at(self, index):
        """The valid, non-empty (trimmed) string task ID at zero-based
        position `index` among this opportunity's valid task IDs (per
        get_valid_task_ids()), or None when `index` is not a plain
        int (bool is rejected, since it is not a genuine index), is
        negative, or falls outside the range of currently valid task
        IDs.

        Built on top of get_valid_task_ids() rather than re-deriving
        that filtering/trimming logic - so `index` refers to a
        position among the valid task IDs only, the same ordering
        used by get_first_task_id() and get_last_task_id().

        A plain, read-only lookup - never modifies task_ids or any
        other field on this opportunity, never inspects or loads any
        RevenueTask object, and never creates, removes, moves, or
        executes any task."""
        if isinstance(index, bool) or not isinstance(index, int):
            return None
        if index < 0:
            return None
        valid_ids = self.get_valid_task_ids()
        if index >= len(valid_ids):
            return None
        return valid_ids[index]

    def is_valid_task_index(self, index):
        """True only when `index` is a plain int (bool is rejected,
        since it is not a genuine index), is not negative, and points
        to an existing valid task ID among this opportunity's valid
        task IDs (per get_valid_task_ids()) - False otherwise,
        including for a negative index, an index at or beyond
        get_task_count(), or a non-int value.

        Built on top of get_task_id_at() rather than re-deriving the
        index-bounds logic - an index is valid exactly when
        get_task_id_at(index) resolves to a real task ID instead of
        None.

        A plain, read-only check - never modifies task_ids or any
        other field on this opportunity, never inspects or loads any
        RevenueTask object, and never creates, removes, moves, or
        executes any task."""
        if isinstance(index, bool) or not isinstance(index, int):
            return False
        if index < 0:
            return False
        return self.get_task_id_at(index) is not None

    def get_task_range(self, start_index, end_index):
        """A new list of the valid, non-empty (trimmed) string task
        IDs (per get_valid_task_ids()) lying within
        [start_index, end_index) - `end_index` is exclusive, matching
        normal Python slice behavior. `start_index` and `end_index`
        must each be a plain int (bool is rejected, since it is not a
        genuine index); a non-int value for either, a negative value
        for either (never accesses tasks from the end), or a range
        where start_index >= end_index all result in an empty list.
        An empty task list, or a range that contains no valid task
        IDs, also results in an empty list.

        Built from is_valid_task_index() and get_task_id_at() rather
        than re-deriving any bounds/validity logic - walks the
        requested positions in order and stops as soon as a position
        is no longer a valid task index, so the result never runs
        past the end of the valid task IDs even when `end_index` is
        larger than the number of valid task IDs.

        Always a fresh, independent list - never a reference to this
        opportunity's own internal task_ids or to any list returned
        by another helper. A plain, read-only check - never modifies
        task_ids or any other field on this opportunity, never
        inspects or loads any RevenueTask object, and never creates,
        removes, moves, or executes any task."""
        if isinstance(start_index, bool) or not isinstance(start_index, int):
            return []
        if isinstance(end_index, bool) or not isinstance(end_index, int):
            return []
        if start_index < 0 or end_index < 0:
            return []
        if start_index >= end_index:
            return []

        result = []
        for index in range(start_index, end_index):
            if not self.is_valid_task_index(index):
                break
            result.append(self.get_task_id_at(index))
        return result

    def get_task_index(self, task_id):
        """The zero-based index of `task_id` within task_ids, or -1
        when it is not present - including when `task_id` is not a
        non-empty string (after stripping leading/trailing
        whitespace when it is a string). Leading/trailing whitespace
        on a string `task_id` is trimmed before the lookup, matching
        the exact stored entries in task_ids. A plain, read-only
        lookup - never modifies task_ids or any other field on this
        opportunity, and never inspects or loads any RevenueTask
        object."""
        if not isinstance(task_id, str):
            return -1
        stripped = task_id.strip()
        if not stripped:
            return -1
        try:
            return self.task_ids.index(stripped)
        except ValueError:
            return -1

    def remove_task_ids(self, task_ids):
        """Remove multiple attached task IDs from this opportunity at
        once. Accepts only a list of task IDs (a tuple or any other
        non-list value is rejected): when `task_ids` is None or not
        a list, returns False without modifying the existing
        task_ids. Otherwise, each candidate ID is considered only
        when it is a non-empty string after stripping leading/
        trailing whitespace; invalid values, IDs that are not
        currently attached, and repeated occurrences of the same ID
        within the given list are silently ignored. The remaining
        task_ids keep their original relative order. Always returns
        True on success. Deterministic and purely local - never
        inspects or loads any RevenueTask object, never performs a
        database or network operation, and never modifies any other
        field on this opportunity."""
        if not isinstance(task_ids, list):
            return False
        to_remove = set()
        for candidate in task_ids:
            if not isinstance(candidate, str):
                continue
            stripped = candidate.strip()
            if not stripped:
                continue
            to_remove.add(stripped)
        self.task_ids = [
            task_id for task_id in self.task_ids if task_id not in to_remove
        ]
        return True

    def add_task_ids(self, task_ids):
        """Add multiple existing task IDs to this opportunity at once.
        Accepts only a list of task IDs (a tuple or any other
        non-list value is rejected): when `task_ids` is None or not
        a list, returns False without modifying the existing
        task_ids. Otherwise, each candidate ID is kept only when it
        is a non-empty string after stripping leading/trailing
        whitespace; invalid values, duplicates within the given list,
        and IDs already attached to this opportunity are silently
        ignored. Newly added IDs are appended in the order they
        appear in `task_ids`, and only task ID strings are stored -
        never full RevenueTask objects. Always returns True on
        success. Deterministic and purely local - never inspects or
        loads any RevenueTask object, never performs a database or
        network operation, and never modifies any other field on
        this opportunity."""
        if not isinstance(task_ids, list):
            return False
        existing = set(self.task_ids)
        for candidate in task_ids:
            if not isinstance(candidate, str):
                continue
            stripped = candidate.strip()
            if not stripped:
                continue
            if stripped in existing:
                continue
            existing.add(stripped)
            self.task_ids.append(stripped)
        return True

    def normalize_task_ids(self):
        """Normalize task_ids in place: keep only non-empty string
        task IDs (after stripping leading/trailing whitespace),
        dropping non-string and empty/whitespace-only entries, and
        remove duplicates while preserving first-occurrence order.
        The normalized result is stored back into task_ids. Always
        returns True. Deterministic and purely local - never
        inspects or loads any RevenueTask object, never performs a
        database or network operation, and never modifies any other
        field on this opportunity.

        Example: [" task_1 ", "task_2", "task_1", "", "   ", 123]
        becomes ["task_1", "task_2"].
        """
        seen = set()
        normalized = []
        for task_id in self.task_ids:
            if not isinstance(task_id, str):
                continue
            stripped = task_id.strip()
            if not stripped:
                continue
            if stripped in seen:
                continue
            seen.add(stripped)
            normalized.append(stripped)
        self.task_ids = normalized
        return True

    def validate_task_ids(self):
        """A structured (JSON-shaped), read-only validation summary of
        the task IDs currently stored in task_ids - never modifies
        task_ids or any other field, and never inspects or loads any
        RevenueTask object (only the stored ID values themselves are
        checked). A task ID is valid when it is a string and is
        non-empty after trimming whitespace - the same rule already
        used by has_tasks(), get_attached_task_ids(), and
        get_task_count().

        Returns a dict with:
        - valid: True only when every stored task ID is valid (also
          True when task_ids is empty - there are no invalid entries)
        - total: the total number of stored task IDs, valid or not
        - valid_count: how many of them are valid
        - invalid_count: how many of them are invalid
        - invalid_ids: a new list (never a reference to task_ids) of
          the invalid entries themselves, in their original order and
          exactly as stored
        """
        invalid_ids = [
            task_id
            for task_id in self.task_ids
            if not (isinstance(task_id, str) and task_id.strip())
        ]
        total = len(self.task_ids)
        invalid_count = len(invalid_ids)
        valid_count = total - invalid_count
        return {
            "valid": invalid_count == 0,
            "total": total,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "invalid_ids": invalid_ids,
        }

    def can_work_on_tasks(self):
        """True only when this opportunity has at least one valid,
        non-empty string task ID currently attached - False when
        task_ids is empty or contains only invalid/empty entries.
        Reuses has_tasks() and get_task_count() rather than
        re-deriving the "valid task ID" rule. A plain, read-only
        check over the stored task ID strings - never inspects or
        executes any RevenueTask object, and never modifies task_ids
        or any other field on this opportunity."""
        return self.has_tasks() and self.get_task_count() > 0

    def clear_tasks(self):
        """Remove every task ID from task_ids, leaving it as an empty
        list, and return True - including when task_ids is already
        empty (a no-op that still returns True rather than raising).
        Only clears the stored task_ids list: never modifies any
        other field on this opportunity, and never touches any
        referenced RevenueTask object itself (this stage only tracks
        IDs, never full task objects) - no database or network
        operation, no task execution, creation, or deletion."""
        self.task_ids = []
        return True

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self):
        """Structured (JSON-shaped) representation - used both as the
        general-purpose serialization and as
        RevenueOpportunityManager's debugging view."""
        return {
            "opportunity_id": self.opportunity_id,
            "goal_id": self.goal_id,
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "revenue_model": self.revenue_model,
            "required_capabilities": list(self.required_capabilities),
            "required_tools": list(self.required_tools),
            "required_inputs": list(self.required_inputs),
            "expected_outputs": list(self.expected_outputs),
            "estimated_income": self.estimated_income,
            "currency": self.currency,
            "time_period": self.time_period,
            "effort_level": self.effort_level,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "status": self.status,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "task_ids": list(self.task_ids),
        }
