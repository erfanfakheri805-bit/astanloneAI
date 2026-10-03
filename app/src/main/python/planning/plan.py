"""
Planning - Plan
=================
`Plan` and `PlanStep` are the lightweight, structured records the
future Planning Engine will operate on:

    GOAL (planning/goal.py) -> ... -> PLAN -> [Planning Engine: not built yet]

This stage only defines the *shape* of a plan and its steps, and how
one is created for an existing Goal - it does not decide how to
achieve a goal, does not generate steps automatically, and does not
execute anything. Those responsibilities belong to the Planning
Engine itself, in a later stage (see PlanManager's module docstring).

Same convention already used by Goal (planning/goal.py),
UnderstandingResult (understanding/result.py), LearningResult
(learning/learning_result.py), and ContextEntry
(context/context_entry.py): a plain, JSON-shaped record with a
`to_dict()` method, rather than formatted text, so a caller (a UI, a
test, the eventual Planning Engine) gets everything it needs without
re-deriving anything from a message string.
"""

from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_structured_data(value, _path="value", _active=None):
    """Recursively validate that `value` is made only of JSON-safe
    building blocks (None, bool, int, float, str, list/tuple, dict
    with string keys) and return a plain, defensively-copied version
    of it (tuples become lists, so a caller mutating their own
    original list/tuple afterwards can never reach back into stored
    state). Raises TypeError - and stores nothing - the first time it
    finds anything else (an arbitrary object, a non-string dict key,
    or a container that contains itself), so PlanStep.input_data/
    output_data (see PlanStep.set_input/set_output below) can never
    silently hold something that isn't safe to serialize.

    This is the one place that decides "is this safe structured
    data?" - PlanManager.set_step_input/get_step_output (see
    plan_manager.py) and PlanStep.set_input/set_output all funnel
    through this single check rather than each re-implementing it."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple, dict)):
        # `_active` holds the ids of the containers currently being walked (Prompt 706): a container that reaches
        # itself is rejected with TypeError, as documented above, instead of recursing until RecursionError.
        # Shared, non-cyclic references are fine (an id is removed again once its container is finished).
        active = set() if _active is None else _active
        if id(value) in active:
            raise TypeError(
                f"Structured data at {_path} contains itself; a container "
                "that contains itself cannot be safely serialized."
            )
        active.add(id(value))
        try:
            if isinstance(value, dict):
                result = {}
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise TypeError(
                            f"Structured data at {_path} has a non-string key "
                            f"({key!r}); only string keys are allowed."
                        )
                    result[key] = ensure_structured_data(item, f"{_path}[{key!r}]", active)
                return result
            return [ensure_structured_data(item, f"{_path}[{i}]", active) for i, item in enumerate(value)]
        finally:
            active.discard(id(value))
    raise TypeError(
        f"Structured data at {_path} contains a {type(value).__name__}, "
        "which cannot be safely serialized. Only None, bool, int, float, "
        "str, list/tuple, and dict (with string keys) are allowed."
    )


# Small, fixed vocabulary for plan/step status (same STATUS_* pattern
# used by planning/goal.py and reasoning/reasoning_result.py) so
# callers can branch on it reliably instead of comparing against
# free-form strings. Plan and PlanStep share the base lifecycle
# below - a plan's own status only ever needs to describe the same
# lifecycle its steps go through.
STATUS_PENDING = "pending"        # created, not yet started
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

ALL_STATUSES = (
    STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED,
)

# PlanStep additionally recognizes READY/BLOCKED - dependency-aware
# states that only make sense for an individual step (whether *its*
# dependencies are resolved), not for a Plan as a whole. These are
# never assigned automatically by PlanStep itself; PlanManager's
# dependency-aware helpers (see plan_manager.py) are what compute
# them, and only when explicitly asked to - creating a PlanStep never
# does this on its own (see PlanStep.__init__ below).
STATUS_READY = "ready"            # no unresolved dependencies; not started
STATUS_BLOCKED = "blocked"        # at least one unresolved dependency

ALL_STEP_STATUSES = (
    STATUS_PENDING, STATUS_READY, STATUS_BLOCKED, STATUS_IN_PROGRESS,
    STATUS_COMPLETED, STATUS_FAILED,
)


class PlanStep:
    """One step within a Plan. Purely a data record - PlanManager
    decides when/how steps get created (see plan_manager.py); nothing
    here infers steps from a goal or checks off execution."""

    __slots__ = (
        "step_id", "description", "dependencies", "required_capabilities",
        "expected_output", "status", "input_data", "output_data",
    )

    def __init__(
        self,
        step_id,
        description,
        dependencies=None,
        required_capabilities=None,
        expected_output=None,
        status=STATUS_PENDING,
        input_data=None,
        output_data=None,
    ):
        if status not in ALL_STEP_STATUSES:
            raise ValueError(f"Unknown step status: {status!r}")

        self.step_id = step_id
        self.description = description
        # Always plain lists (never None) so callers can iterate/index
        # immediately without a None check - same convention as
        # Goal.requirements/metadata.
        self.dependencies = list(dependencies) if dependencies else []
        self.required_capabilities = list(required_capabilities) if required_capabilities else []
        self.expected_output = expected_output
        self.status = status
        # Optional, structured input/output data for this step (added
        # this stage - see module docstring's data-flow layer). Both
        # default to None (no input/output recorded yet) rather than
        # an empty dict/list, so a caller/test can tell "never set"
        # apart from "explicitly set to an empty structure". Anything
        # assigned here - at construction or later via set_input/
        # set_output - is funneled through ensure_structured_data so
        # this step can never end up holding an arbitrary, unsafe-to-
        # serialize Python object.
        self.input_data = ensure_structured_data(input_data) if input_data is not None else None
        self.output_data = ensure_structured_data(output_data) if output_data is not None else None

    def __repr__(self):
        return (
            f"PlanStep(step_id={self.step_id!r}, status={self.status!r}, "
            f"description={self.description!r})"
        )

    def to_dict(self):
        return {
            "step_id": self.step_id,
            "description": self.description,
            "dependencies": list(self.dependencies),
            "required_capabilities": list(self.required_capabilities),
            "expected_output": self.expected_output,
            "status": self.status,
            "input_data": self.input_data,
            "output_data": self.output_data,
        }

    # ------------------------------------------------------------------
    # Structured input/output (data-flow layer)
    # ------------------------------------------------------------------
    # Small, symmetric get/set pair for each of input_data/output_data -
    # same "safe setter, plain getter" shape as set_status/status
    # above. Neither of these decides *when* a step should receive
    # input or produce output, and neither passes data to any other
    # step - that's explicitly out of scope for this stage (see module
    # docstring); a caller (PlanManager, the future Execution Engine)
    # decides when to call these.
    def set_input(self, data):
        """Safely set this step's `input_data`. Raises TypeError - and
        leaves `input_data` untouched - if `data` contains anything
        that isn't safe, JSON-shaped structured data (see
        ensure_structured_data). `data=None` is allowed and simply
        clears any previously-set input."""
        self.input_data = ensure_structured_data(data) if data is not None else None
        return self

    def set_output(self, data):
        """Safely set this step's `output_data`. Same contract as
        set_input, for the step's output side."""
        self.output_data = ensure_structured_data(data) if data is not None else None
        return self

    def get_input(self):
        """This step's currently stored `input_data`, or None if none
        has been set."""
        return self.input_data

    def get_output(self):
        """This step's currently stored `output_data`, or None if none
        has been set."""
        return self.output_data

    def set_status(self, new_status):
        """Update this step's status in place, after checking it
        against ALL_STEP_STATUSES. Raises ValueError (and leaves the
        step's current status untouched) for anything else - the same
        "never silently accept junk" guard __init__ already applies
        to the initial status. Callers that need this dependency-
        aware (BLOCKED/READY) should go through PlanManager (see
        plan_manager.py) rather than pass those in directly here."""
        if new_status not in ALL_STEP_STATUSES:
            raise ValueError(f"Unknown step status: {new_status!r}")
        self.status = new_status
        return self


class Plan:
    """A lightweight, structured plan attached to one existing Goal.

    `steps`, `dependencies`, `required_capabilities`, `expected_outputs`,
    and `warnings` are always plain lists (never None) so callers can
    iterate/index them immediately without a None check - same
    convention as Goal.requirements/metadata. `dependencies` here are
    plan-level (e.g. other plan/goal ids this plan depends on) and are
    distinct from a PlanStep's own `dependencies`, which are scoped to
    that single step.
    """

    __slots__ = (
        "plan_id", "goal_id", "steps", "dependencies", "required_capabilities",
        "expected_outputs", "status", "confidence", "warnings", "created_at",
        "metadata",
    )

    def __init__(
        self,
        plan_id,
        goal_id,
        steps=None,
        dependencies=None,
        required_capabilities=None,
        expected_outputs=None,
        status=STATUS_PENDING,
        confidence=0.0,
        warnings=None,
        created_at=None,
        metadata=None,
    ):
        if status not in ALL_STATUSES:
            raise ValueError(f"Unknown plan status: {status!r}")

        self.plan_id = plan_id
        self.goal_id = goal_id
        self.steps = list(steps) if steps else []
        self.dependencies = list(dependencies) if dependencies else []
        self.required_capabilities = list(required_capabilities) if required_capabilities else []
        self.expected_outputs = list(expected_outputs) if expected_outputs else []
        self.status = status
        self.confidence = max(0.0, min(1.0, confidence))
        self.warnings = list(warnings) if warnings else []
        self.created_at = created_at if created_at is not None else _now_iso()
        self.metadata = dict(metadata) if metadata else {}

    def __repr__(self):
        return (
            f"Plan(plan_id={self.plan_id!r}, goal_id={self.goal_id!r}, "
            f"status={self.status!r}, steps={len(self.steps)}, "
            f"confidence={self.confidence:.2f})"
        )

    def to_dict(self):
        """Structured (JSON-shaped) representation - used both as the
        general-purpose serialization and as PlanManager's debugging
        view (see PlanManager.describe_plan)."""
        return {
            "plan_id": self.plan_id,
            "goal_id": self.goal_id,
            "steps": [s.to_dict() for s in self.steps],
            "dependencies": list(self.dependencies),
            "required_capabilities": list(self.required_capabilities),
            "expected_outputs": list(self.expected_outputs),
            "status": self.status,
            "confidence": round(self.confidence, 4),
            "warnings": list(self.warnings),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }
