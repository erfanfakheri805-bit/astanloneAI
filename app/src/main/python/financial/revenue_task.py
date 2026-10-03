"""
Revenue Task
======================
`RevenueTask` is a small, standalone data record representing one unit
of work tied to a `RevenueOpportunity` (financial/revenue_opportunity.py):

    RevenueOpportunity -> RevenueTask -> [Planning/Execution: not built yet]

This stage only defines the *shape* of a task - it does NOT implement
any planner, scheduler, or execution stage. In particular this module:

- Does NOT claim or guarantee that completing this task will make
  money.
- Does NOT execute anything, contact customers, make purchases,
  transfer money, access bank accounts, or create any financial
  transaction.
- Does NOT access websites, send messages, or publish content.
- Is NOT connected to RevenueOpportunityManager, a planner, or any
  other system - it is a plain, standalone record for now.

Same "construction never raises, is_valid() is a plain boolean check"
convention already used by `RevenueOpportunity`
(financial/revenue_opportunity.py), `RevenueStrategy`
(financial/revenue_strategy.py), and `FinancialGoal`
(financial/financial_goal.py): a caller can freely build a RevenueTask
from untrusted/partial input and then call `is_valid()` to decide
whether it is fit to use, rather than having to wrap construction in a
try/except.
"""

from datetime import datetime, timezone

from .revenue_task_result import RevenueTaskResult


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Small, fixed vocabulary for task status (same STATUS_* pattern
# already used elsewhere in financial/). A task starts life as
# PENDING - nothing in this module ever moves it further along on its
# own; that always requires an explicit change by a future caller.
STATUS_PENDING = "PENDING"
STATUS_READY = "READY"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_BLOCKED = "BLOCKED"
STATUS_CANCELLED = "CANCELLED"

ALL_STATUSES = (
    STATUS_PENDING, STATUS_READY, STATUS_IN_PROGRESS, STATUS_COMPLETED,
    STATUS_FAILED, STATUS_BLOCKED, STATUS_CANCELLED,
)

DEFAULT_STATUS = STATUS_PENDING

# Small, fixed vocabulary for task priority (same closed-enum pattern
# as STATUS_*). A task defaults to NORMAL - nothing in this module
# ever changes it on its own.
PRIORITY_LOW = "LOW"
PRIORITY_NORMAL = "NORMAL"
PRIORITY_HIGH = "HIGH"
PRIORITY_CRITICAL = "CRITICAL"

ALL_PRIORITIES = (PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH, PRIORITY_CRITICAL)

DEFAULT_PRIORITY = PRIORITY_NORMAL

# Fixed table of allowed status transitions (from_status -> set of
# permitted to_statuses). Used only by is_valid_transition() below -
# this stage never performs a transition automatically; it only lets
# a caller check whether a particular from/to pair is allowed.
_ALLOWED_TRANSITIONS = {
    STATUS_PENDING: frozenset((STATUS_READY, STATUS_BLOCKED, STATUS_CANCELLED)),
    STATUS_READY: frozenset((STATUS_IN_PROGRESS, STATUS_BLOCKED, STATUS_CANCELLED)),
    STATUS_IN_PROGRESS: frozenset((STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED)),
    STATUS_BLOCKED: frozenset((STATUS_READY, STATUS_CANCELLED)),
}

# `estimated_duration` is the task's estimated duration in minutes -
# an open, non-negative number (not a closed vocabulary like status/
# priority). Defaults to 0 (no estimate yet).
DEFAULT_ESTIMATED_DURATION = 0

# Safe, structured-data-only types allowed inside `metadata`. Same
# convention as RevenueOpportunity's own `_is_safe_structured_value`.
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


class RevenueTask:
    """One unit of work tied to a RevenueOpportunity - captured but not
    yet planned or executed. Purely a data record: construction never
    raises (unlike e.g. ExecutionResult) so a caller can freely build a
    RevenueTask from untrusted/partial data and then use `is_valid()`
    to decide whether it is fit to use.

    `dependencies` is always a plain list (never None, and never a
    shared default) and `metadata` is always a plain dict (never
    None) - same "no None checks needed by callers" convention as
    RevenueOpportunity's own dict/list fields
    (financial/revenue_opportunity.py).
    """

    __slots__ = (
        "task_id", "opportunity_id", "name", "description", "status",
        "priority", "estimated_duration", "dependencies", "created_at",
        "metadata", "result",
    )

    def __init__(
        self,
        task_id,
        opportunity_id,
        name=None,
        description=None,
        status=DEFAULT_STATUS,
        priority=DEFAULT_PRIORITY,
        estimated_duration=DEFAULT_ESTIMATED_DURATION,
        dependencies=None,
        created_at=None,
        metadata=None,
    ):
        self.task_id = task_id
        self.opportunity_id = opportunity_id
        self.name = name
        self.description = description
        self.status = status
        self.priority = priority
        self.estimated_duration = estimated_duration
        if dependencies is None:
            self.dependencies = []
        elif isinstance(dependencies, (list, tuple)):
            self.dependencies = list(dependencies)
        else:
            self.dependencies = dependencies
        self.created_at = created_at if created_at is not None else _now_iso()
        self.metadata = dict(metadata) if metadata else {}
        # The latest RevenueTaskResult attached to this task, if any -
        # see set_result()/get_result()/has_result()/clear_result()
        # below. None until a caller explicitly attaches one; this
        # stage never creates or attaches a result on its own (no
        # automatic creation, no automatic attachment on
        # completion/failure).
        self.result = None

    def __repr__(self):
        return (
            f"RevenueTask(task_id={self.task_id!r}, "
            f"opportunity_id={self.opportunity_id!r}, "
            f"name={self.name!r}, status={self.status!r})"
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def is_valid(self):
        """Plain boolean check - never raises. A task is valid when:
        - task_id is a non-empty string
        - opportunity_id is a non-empty string
        - name is a non-empty string
        - status is one of the supported values (see ALL_STATUSES)
        - priority is one of the supported values (see ALL_PRIORITIES)
        - estimated_duration is numeric (int/float, not bool) and >= 0
        - dependencies is a list of non-empty strings (task IDs)
        - metadata contains only safe, structured data (see
          `_is_safe_structured_value`)

        This intentionally says nothing about whether the task will
        actually get done or pay off - only whether the record is
        well-formed enough to use.
        """
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            return False
        if not isinstance(self.opportunity_id, str) or not self.opportunity_id.strip():
            return False
        if not isinstance(self.name, str) or not self.name.strip():
            return False
        if self.status not in ALL_STATUSES:
            return False
        if self.priority not in ALL_PRIORITIES:
            return False

        if isinstance(self.estimated_duration, bool):
            return False
        if not isinstance(self.estimated_duration, (int, float)):
            return False
        if self.estimated_duration < 0:
            return False

        if not isinstance(self.dependencies, list):
            return False
        for dependency_id in self.dependencies:
            if not isinstance(dependency_id, str) or not dependency_id.strip():
                return False

        if not _is_safe_structured_value(self.metadata):
            return False

        return True

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def get_dependencies(self):
        """A plain list (never None) of task IDs this task depends on -
        a safe copy, so mutating the returned list does not affect this
        task. This stage never resolves, checks, or acts on these
        dependencies in any way."""
        return list(self.dependencies)

    def has_dependencies(self):
        """True if this task has at least one dependency, False if the
        dependency list is empty. Purely a length check - it does not
        resolve dependencies or verify that the referenced tasks
        actually exist."""
        return len(self.dependencies) > 0

    def is_completed(self):
        """True only when status is exactly STATUS_COMPLETED. A plain
        status check - never changes the status."""
        return self.status == STATUS_COMPLETED

    def is_failed(self):
        """True only when status is exactly STATUS_FAILED. A plain
        status check - never changes the status."""
        return self.status == STATUS_FAILED

    def is_ready(self):
        """True only when status is exactly STATUS_READY. A plain
        status check - never changes the status and does not inspect
        dependencies."""
        return self.status == STATUS_READY

    def can_start(self):
        """True only when status is exactly STATUS_READY (see
        is_ready()), False for every other status. A plain status
        check - never changes the status, never executes the task,
        and never checks external systems, capabilities, tools, or
        dependencies."""
        return self.is_ready()

    def is_startable(self):
        """True only when both can_start() and has_opportunity() are
        True, False otherwise. A plain, in-memory combination of the
        two existing checks - never changes the status or
        opportunity_id, never performs a database lookup, never loads
        or creates a RevenueOpportunity, never executes anything, and
        never checks external tools or capabilities."""
        return self.can_start() and self.has_opportunity()

    def get_startability_status(self):
        """A small structured (JSON-shaped) summary combining
        is_startable(), is_ready(), and has_opportunity() - each value
        comes straight from calling that existing method, never
        re-derived. Never modifies this task, never changes its
        status, never performs a database lookup, never loads or
        creates a RevenueOpportunity, and never executes anything."""
        return {
            "startable": self.is_startable(),
            "ready": self.is_ready(),
            "has_opportunity": self.has_opportunity(),
        }

    def get_status_summary(self):
        """A small structured (JSON-shaped) summary of this task's
        identity and current status - task_id, opportunity_id, status,
        and priority exactly as stored, plus is_startable() and
        is_final() each called straight through, never re-derived.
        Never modifies this task, never changes its status, never
        performs a database lookup, never loads or creates a
        RevenueOpportunity, and never executes anything."""
        return {
            "task_id": self.task_id,
            "opportunity_id": self.opportunity_id,
            "status": self.status,
            "priority": self.priority,
            "startable": self.is_startable(),
            "final": self.is_final(),
        }

    def get_dependency_status(self, completed_task_ids=None):
        """A new, structured (JSON-shaped), read-only summary of
        whether this task's dependencies are satisfied.

        This task's own dependencies (from get_dependencies()) and
        `completed_task_ids` are each normalized the same way before
        comparison: only string entries are kept, leading/trailing
        whitespace is trimmed, empty/whitespace-only entries are
        dropped, and duplicates are removed (first occurrence kept,
        original relative order preserved for this task's own
        dependencies). `completed_task_ids` may be None, in which
        case it is treated as an empty collection.

        When this task has no valid dependency IDs, returns:
        - has_dependencies: False
        - total: 0
        - completed: 0
        - remaining: [] (a new, empty list)
        - ready: True

        Otherwise, returns:
        - has_dependencies: True
        - total: the number of valid, unique dependency IDs
        - completed: how many of them are present in the normalized
          `completed_task_ids`
        - remaining: a new list (never a reference to this task's own
          dependencies) of the dependency IDs not present in the
          normalized `completed_task_ids`, in their original relative
          order
        - ready: True only when `remaining` is empty (every
          dependency is completed)

        Completely read-only - never modifies this task's
        dependencies or any other field, never changes this task's
        status, never calls transition_to(), and never executes
        anything (no subprocess, shell command, network access,
        external AI API, or file execution)."""
        normalized_dependencies = []
        seen_dependencies = set()
        for dependency_id in self.get_dependencies():
            if not isinstance(dependency_id, str):
                continue
            stripped = dependency_id.strip()
            if not stripped or stripped in seen_dependencies:
                continue
            seen_dependencies.add(stripped)
            normalized_dependencies.append(stripped)

        if not normalized_dependencies:
            return {
                "has_dependencies": False,
                "total": 0,
                "completed": 0,
                "remaining": [],
                "ready": True,
            }

        normalized_completed = set()
        if completed_task_ids:
            for completed_id in completed_task_ids:
                if not isinstance(completed_id, str):
                    continue
                stripped = completed_id.strip()
                if stripped:
                    normalized_completed.add(stripped)

        remaining = [
            dependency_id
            for dependency_id in normalized_dependencies
            if dependency_id not in normalized_completed
        ]
        completed_count = len(normalized_dependencies) - len(remaining)

        return {
            "has_dependencies": True,
            "total": len(normalized_dependencies),
            "completed": completed_count,
            "remaining": remaining,
            "ready": len(remaining) == 0,
        }

    def get_readiness_report(self, completed_task_ids=None):
        """A new, structured (JSON-shaped), read-only readiness report
        combining this task's status, opportunity, and dependency
        state. `completed_task_ids` is passed straight through to
        get_dependency_status() (None is treated there as an empty
        collection).

        Built entirely from existing helper methods - has_opportunity(),
        has_dependencies(), get_dependency_status(), can_start(), and
        is_startable() - rather than re-deriving any of that logic.

        Returns a dict with:
        - task_id: this task's own task_id, exactly as stored
        - status: this task's own status, exactly as stored
        - has_opportunity: from has_opportunity()
        - has_dependencies: from has_dependencies()
        - dependencies_ready: the "ready" value from
          get_dependency_status(completed_task_ids) - True when this
          task has no dependencies or all of them are completed
        - startable: from is_startable()
        - ready: True only when can_start() is True, has_opportunity()
          is True, and dependencies_ready is True - False otherwise

        Completely read-only - never changes this task's status,
        never modifies dependencies or opportunity_id, never calls
        transition_to(), and never executes anything (no subprocess,
        shell command, network access, external AI API, or arbitrary
        code execution). Always a fresh dict, never a reference to
        this task's own internal state."""
        dependency_status = self.get_dependency_status(completed_task_ids)
        dependencies_ready = dependency_status["ready"]
        ready = (
            self.can_start()
            and self.has_opportunity()
            and dependencies_ready
        )
        return {
            "task_id": self.task_id,
            "status": self.status,
            "has_opportunity": self.has_opportunity(),
            "has_dependencies": self.has_dependencies(),
            "dependencies_ready": dependencies_ready,
            "startable": self.is_startable(),
            "ready": ready,
        }

    def is_cancelled(self):
        """True only when status is exactly STATUS_CANCELLED. A plain
        status check - never changes the status."""
        return self.status == STATUS_CANCELLED

    def is_in_progress(self):
        """True only when status is exactly STATUS_IN_PROGRESS. A plain
        status check - never changes the status."""
        return self.status == STATUS_IN_PROGRESS

    def is_pending(self):
        """True only when status is exactly STATUS_PENDING. A plain
        status check - never changes the status."""
        return self.status == STATUS_PENDING

    def is_blocked(self):
        """True only when status is exactly STATUS_BLOCKED. A plain
        status check - never changes the status and does not inspect
        dependencies."""
        return self.status == STATUS_BLOCKED

    def is_active(self):
        """True when status is STATUS_READY or STATUS_IN_PROGRESS,
        False for every other status. A plain status check - never
        changes the status."""
        return self.status in (STATUS_READY, STATUS_IN_PROGRESS)

    def is_final(self):
        """True when status is STATUS_COMPLETED, STATUS_FAILED, or
        STATUS_CANCELLED, False for every other status. A plain status
        check - never changes the status."""
        return self.status in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED)

    def is_open(self):
        """True when the task is not in a final state (see
        is_final()) - i.e. status is PENDING, READY, IN_PROGRESS, or
        BLOCKED. False for COMPLETED, FAILED, or CANCELLED. A plain
        status check - never changes the status."""
        return not self.is_final()

    def get_status(self):
        """The current status, exactly as stored - never modifies it,
        computes a new one, or inspects dependencies."""
        return self.status

    def set_status(self, status):
        """Update this task's status to `status` if it is one of the
        existing supported values (see ALL_STATUSES), returning True
        in that case. If `status` is not a supported value, this
        task's status is left unchanged and False is returned. Uses
        the same status validation rule as is_valid() - never
        introduces a new status, never touches any other field
        (dependencies, priority, opportunity_id, etc.), never performs
        a database operation, and never executes anything or triggers
        another system."""
        if status not in ALL_STATUSES:
            return False
        self.status = status
        return True

    def change_status(self, old_status, new_status):
        """Compare-and-set style status change: only updates the
        status when `old_status` matches this task's current status
        exactly. Returns False, without modifying anything, when
        `old_status` does not match the current status. Otherwise
        delegates to set_status(new_status) - reusing its existing
        validation - and returns whatever set_status() returns (True
        for a valid `new_status`, False for an invalid one, leaving
        the status unchanged in that case too). Never touches any
        other field, never performs a database or network operation,
        and never executes anything or triggers another system."""
        if old_status != self.status:
            return False
        return self.set_status(new_status)

    def can_change_status(self, new_status):
        """True when `new_status` is one of the existing supported
        status values (see ALL_STATUSES), False otherwise. A plain,
        read-only membership check - the same rule set_status() and
        is_valid() already apply - that never modifies this task's
        status or any other field. This only validates that
        `new_status` is a recognized status value; it says nothing
        about whether transitioning to it from the task's current
        status would be a logically allowed transition. Never checks
        external systems, never performs a database or network
        operation, and never executes anything."""
        return new_status in ALL_STATUSES

    def is_valid_transition(self, new_status):
        """True when moving from this task's CURRENT status to
        `new_status` is one of the allowed transitions in
        _ALLOWED_TRANSITIONS, False otherwise - including when
        `new_status` is not a recognized status at all (see
        can_change_status()) or is equal to the current status (a
        same-status "transition" is never considered valid here). A
        plain, read-only lookup against the fixed transition table -
        never modifies this task's status or any other field, never
        performs the transition itself, never checks external
        systems, never performs a database or network operation, and
        never executes anything."""
        if not self.can_change_status(new_status):
            return False
        return new_status in _ALLOWED_TRANSITIONS.get(self.status, frozenset())

    def transition_to(self, new_status):
        """Perform the transition to `new_status` if
        is_valid_transition(new_status) says it is allowed - reusing
        that existing check (and, through it, the same
        _ALLOWED_TRANSITIONS table) rather than duplicating any
        transition logic. On success, updates this task's status to
        `new_status` and returns True. On failure, leaves the status
        - and every other field (opportunity_id, dependencies,
        priority, metadata, etc.) - completely unmodified and returns
        False. Never performs the transition automatically on its
        own, never triggers execution or any other system, never
        performs a database or network operation, and never executes
        external code."""
        if not self.is_valid_transition(new_status):
            return False
        self.status = new_status
        return True

    def get_transition_status(self, new_status):
        """A small structured (JSON-shaped) summary of whether moving
        to `new_status` would be allowed: this task's current status,
        the supplied `new_status` exactly as given, and `valid` -
        the result of is_valid_transition(new_status), called
        straight through rather than re-derived. A plain, read-only
        check - never calls transition_to(), never modifies this
        task's status or any other field, never performs a database
        or network operation, and never executes anything."""
        return {
            "current_status": self.status,
            "target_status": new_status,
            "valid": self.is_valid_transition(new_status),
        }

    def get_allowed_transitions(self):
        """A plain list of the statuses this task's CURRENT status may
        transition to, per the existing transition rules. Built by
        checking is_valid_transition() for each recognized status in
        turn (the same fixed ALL_STATUSES order used throughout this
        module) rather than duplicating a second transition table -
        so it always stays in lockstep with is_valid_transition() and
        transition_to(). Returns a fresh list on every call (never a
        reference to shared/internal state, so mutating the result
        cannot affect this task or any other call), and is empty for
        a task whose current status has no allowed transitions (e.g.
        COMPLETED, FAILED, CANCELLED). Never modifies this task's
        status or any other field, never performs the transition
        itself, never performs a database or network operation, and
        never executes anything."""
        return [
            status for status in ALL_STATUSES if self.is_valid_transition(status)
        ]

    def get_completion_status(self):
        """A small structured (JSON-shaped) summary of this task's
        completion state: the current status plus completed, failed,
        cancelled, final, and open - each value coming straight from
        calling is_completed(), is_failed(), is_cancelled(),
        is_final(), and is_open() respectively, never re-derived. A
        plain, read-only check - never modifies this task's status or
        any other field, never performs a transition, never performs
        a database or network operation, and never executes
        anything."""
        return {
            "status": self.status,
            "completed": self.is_completed(),
            "failed": self.is_failed(),
            "cancelled": self.is_cancelled(),
            "final": self.is_final(),
            "open": self.is_open(),
        }

    def belongs_to_opportunity(self, opportunity_id):
        """True when `opportunity_id` exactly matches this task's own
        opportunity_id, False otherwise. A plain, in-memory comparison
        - never modifies this task or the supplied id, never looks up
        the opportunity, and never touches storage."""
        return self.opportunity_id == opportunity_id

    def get_opportunity_id(self):
        """This task's opportunity_id, exactly as stored - never
        modifies it, never looks it up, and never loads or creates a
        RevenueOpportunity."""
        return self.opportunity_id

    def has_opportunity(self):
        """True when opportunity_id is a non-empty string (the same
        rule is_valid() applies to this field), False when it is
        empty, missing, or otherwise invalid. A plain, in-memory check
        - never modifies opportunity_id, never performs a lookup, and
        never loads or creates a RevenueOpportunity."""
        return isinstance(self.opportunity_id, str) and bool(self.opportunity_id.strip())

    def set_opportunity_id(self, opportunity_id):
        """Update this task's opportunity_id to `opportunity_id` if it
        is a non-empty string (the same rule has_opportunity() and
        is_valid() already apply to this field), returning True in
        that case. If `opportunity_id` is empty, missing, or not a
        string, this task's opportunity_id is left unchanged and
        False is returned. Never touches any other field (status,
        dependencies, priority, metadata, etc.), never performs a
        database lookup, never validates that the opportunity
        actually exists, never loads or creates a RevenueOpportunity,
        and never triggers execution or any other system."""
        if not isinstance(opportunity_id, str) or not opportunity_id.strip():
            return False
        self.opportunity_id = opportunity_id
        return True

    def get_opportunity_reference(self):
        """A small structured (JSON-shaped) summary of this task's
        existing Opportunity reference: opportunity_id exactly as
        stored, and has_opportunity - the result of has_opportunity(),
        called straight through rather than re-derived. A plain,
        read-only check - never accesses RevenueOpportunityManager,
        never performs a database lookup, never loads or creates a
        RevenueOpportunity, never verifies that the opportunity
        actually exists, and never modifies this task's status or any
        other field (dependencies, priority, metadata, etc.)."""
        return {
            "opportunity_id": self.opportunity_id,
            "has_opportunity": self.has_opportunity(),
        }

    # ------------------------------------------------------------------
    # Result attachment
    # ------------------------------------------------------------------
    def set_result(self, result):
        """Attach `result` (a RevenueTaskResult -
        financial/revenue_task_result.py) to this task as its latest
        result, returning True on success.

        Rejects (returns False, leaving any previously attached
        result unchanged) unless ALL of the following hold:
        - `result` is a RevenueTaskResult instance
        - `result.task_id` exactly matches this task's task_id
        - `result.opportunity_id` exactly matches this task's
          opportunity_id

        Deliberately does NOT require `result.is_valid()` - callers
        that want that guarantee can check it themselves before
        calling this method - but it also does not repair, normalize,
        or otherwise modify `result` in any way: the exact object
        passed in is stored as-is (never copied here; get_result()
        below is responsible for how it is handed back out).

        Never changes this task's status or any other field
        (priority, dependencies, metadata, etc.), never performs a
        database or network operation, and never executes anything."""
        if not isinstance(result, RevenueTaskResult):
            return False
        if result.task_id != self.task_id:
            return False
        if result.opportunity_id != self.opportunity_id:
            return False
        self.result = result
        return True

    def get_result(self):
        """The RevenueTaskResult currently attached to this task, or
        None if none is attached. Returns the same convention already
        used elsewhere in this module for object-valued fields:
        exactly the stored object (never a copy) is returned, so the
        result's own methods (to_dict(), is_valid(), etc.) remain
        directly usable, and its identity is preserved. Never
        modifies this task or the attached result, and never executes
        anything."""
        return self.result

    def has_result(self):
        """True only when a valid RevenueTaskResult is currently
        attached to this task (see set_result()), False when none is
        attached or the attached object is not a valid
        RevenueTaskResult. A plain, read-only check - never modifies
        this task or the attached result, and never executes
        anything."""
        return (
            isinstance(self.result, RevenueTaskResult) and self.result.is_valid()
        )

    def clear_result(self):
        """Remove any RevenueTaskResult currently attached to this
        task. Safe to call even when no result is attached (a no-op
        in that case). Never changes this task's status or any other
        field (priority, dependencies, metadata, etc.), never performs
        a database or network operation, and never executes
        anything."""
        self.result = None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self):
        """Structured (JSON-shaped) representation of this task.

        `result` is represented as `result.to_dict()` - already a
        fresh, independent copy per RevenueTaskResult.to_dict()'s own
        convention (financial/revenue_task_result.py) - when a valid
        result is attached, or None otherwise. Never modifies the
        attached result."""
        return {
            "task_id": self.task_id,
            "opportunity_id": self.opportunity_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "estimated_duration": self.estimated_duration,
            "dependencies": list(self.dependencies),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "result": self.result.to_dict() if self.has_result() else None,
        }

    def to_reference_dict(self):
        """A small, new dictionary with just this task's reference
        fields - task_id, opportunity_id, name, and status, each
        exactly as stored. A lighter-weight alternative to to_dict()
        for callers that only need to identify/reference this task,
        not its full record. Always a fresh dict, never the task's
        own internal state, so mutating the result never affects this
        task. Never modifies this task's status or any other field
        (dependencies, priority, metadata, etc.), never performs a
        database lookup, never loads or creates a RevenueOpportunity,
        and never executes anything."""
        return {
            "task_id": self.task_id,
            "opportunity_id": self.opportunity_id,
            "name": self.name,
            "status": self.status,
        }

    def to_execution_reference(self):
        """A new, structured (JSON-shaped) description of this task
        intended for a future execution system to consume - task_id,
        opportunity_id, name, description, status, priority, and
        estimated_duration exactly as stored, dependencies from
        get_dependencies() (a fresh, independent list), and
        startable/final from is_startable() and is_final()
        respectively, each called straight through rather than
        re-derived.

        Always a fresh dict, never a reference to this task's own
        internal state, so mutating the result (including its
        dependencies list) never affects this task. Purely
        descriptive: does NOT execute anything, does not run any
        command, tool, file, network request, subprocess, or external
        AI service, and does not modify this task's status or any
        other field."""
        return {
            "task_id": self.task_id,
            "opportunity_id": self.opportunity_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "estimated_duration": self.estimated_duration,
            "dependencies": self.get_dependencies(),
            "startable": self.is_startable(),
            "final": self.is_final(),
        }
