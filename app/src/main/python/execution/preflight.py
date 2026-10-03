"""
Execution - Preflight Validation
===================================
`PreflightValidator` is a small, read-only checkpoint that runs *before*
a PlanStep is actually executed:

    PLAN (planning/plan.py) -> READY PlanStep -> PreflightValidator
        -> PreflightResult -> ExecutionEngine (execution_engine.py)
        [only if valid] -> handler -> ExecutionResult

This stage only decides whether a step is currently safe to run - it
never runs anything itself, never changes a PlanStep's status, never
creates/enables/installs/executes a capability, and never touches the
filesystem, shell, network, or any Android API. Those responsibilities
stay exactly where they already were: PlanManager owns status writes
(planning/plan_manager.py, untouched by this module), and
ExecutionEngine owns actually calling a handler
(execution/execution_engine.py).

Deliberately built entirely on PlanManager's own, already-existing
logic rather than a second copy of it (requirement 5 - "do not
duplicate dependency or capability rules"):
  - dependency resolution reuses PlanManager._unresolved_dependencies -
    the exact same helper refresh_step_status/refresh_after_step_change/
    check_plan_readiness already share;
  - capability availability reuses
    PlanManager._unavailable_capabilities - the exact same helper those
    same methods already share.
This validator never re-derives "is this dependency satisfied?" or "is
this capability available?" on its own; it only asks PlanManager.

Same "plain data in, plain data out, nothing hidden" convention the
rest of this project already follows - see execution_result.py's
module docstring: `validate_step` returns a `PreflightResult`, a
plain, JSON-shaped record with a `to_dict()` method, rather than a
bare bool or a formatted message.
"""

from planning.plan import STATUS_READY
from planning.plan_manager import PlanManager

# Fixed vocabulary for a failed check's `check` name (requirement 7 -
# "each failed check should identify: check name, reason") - so a
# caller can branch on *which* check failed reliably, instead of
# string-matching a message. Order below is also the order checks are
# evaluated in `validate_step`.
CHECK_PLAN_EXISTS = "plan_exists"
CHECK_STEP_EXISTS = "step_exists"
CHECK_STEP_READY = "step_ready"
CHECK_DEPENDENCIES_SATISFIED = "dependencies_satisfied"
CHECK_CAPABILITIES_AVAILABLE = "capabilities_available"


class PreflightResult:
    """The outcome of one `validate_step` call. Purely a data record -
    nothing here decides *to* execute anything or writes a PlanStep's
    status; see module docstring.

    `failed_checks` is always a plain list of
    `{"check": <CHECK_* name>, "reason": <str>}` dicts (never None), and
    `warnings` is always a plain list of strings (never None) - same
    "callers can iterate immediately, no None check" convention as
    Plan.warnings/ExecutionResult.metadata. `valid` is True only when
    `failed_checks` is empty; adding a failed check always flips it to
    False (see `add_failed_check`) so the two can never disagree."""

    __slots__ = ("plan_id", "step_id", "valid", "failed_checks", "warnings")

    def __init__(self, plan_id, step_id, valid=True, failed_checks=None, warnings=None):
        self.plan_id = plan_id
        self.step_id = step_id
        self.failed_checks = list(failed_checks) if failed_checks else []
        self.warnings = list(warnings) if warnings else []
        # Never trust a caller-supplied `valid=True` if failed_checks
        # were also supplied - `valid` always reflects the *actual*
        # presence/absence of a failed check, never a claim someone
        # made independently of it.
        self.valid = valid and not self.failed_checks

    def __repr__(self):
        return (
            f"PreflightResult(plan_id={self.plan_id!r}, step_id={self.step_id!r}, "
            f"valid={self.valid!r}, failed_checks={len(self.failed_checks)}, "
            f"warnings={len(self.warnings)})"
        )

    def add_failed_check(self, check, reason):
        """Record one failed check (`check` should be one of the
        CHECK_* constants above) and its human-readable `reason`.
        Always leaves `valid` False afterwards - a PreflightResult
        with any failed check is never valid, no matter what was
        passed to `__init__`."""
        self.failed_checks.append({"check": check, "reason": reason})
        self.valid = False
        return self

    def add_warning(self, warning):
        """Record a non-blocking `warning` string - something worth a
        caller's attention that doesn't, on its own, make this step
        unsafe to run (see `validate_step`'s capability_system note).
        Never affects `valid`."""
        self.warnings.append(warning)
        return self

    def to_dict(self):
        """Structured (JSON-shaped) representation - the general-
        purpose serialization for a UI, a test, or ExecutionEngine.
        See module docstring for the convention this follows."""
        return {
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "valid": self.valid,
            "failed_checks": [dict(fc) for fc in self.failed_checks],
            "warnings": list(self.warnings),
        }


class PreflightValidator:
    """Not thread-safe (matches the rest of the project - see
    PlanManager/ExecutionEngine's own notes). Safe to use one instance
    per Core / per conversation session, wired to that session's own
    PlanManager - same relationship ExecutionEngine already has (see
    execution_engine.py)."""

    def __init__(self, plan_manager):
        if not isinstance(plan_manager, PlanManager):
            raise TypeError("PreflightValidator requires a PlanManager instance.")
        self._plan_manager = plan_manager

    def validate_step(self, plan_id, step_id, capability_system=None):
        """Check whether the PlanStep named by `plan_id`/`step_id` is
        currently safe to execute, and return a fully-populated
        PreflightResult describing the outcome. Read-only throughout -
        never writes a PlanStep's status, never registers/enables/
        disables/executes a capability, and never calls a handler.

        `capability_system` is optional (defaults to None), matching
        PlanManager._unavailable_capabilities' own contract: omitting
        it skips the capability check entirely (a warning is added
        instead - see below) rather than treating every required
        capability as unavailable.

        Checks run, in order:
          1. `plan_id` names a known plan (CHECK_PLAN_EXISTS). If not,
             validation stops here - there's no plan/step to check
             anything else about - and this is the only failed check
             in the result.
          2. `step_id` names a known step within that plan
             (CHECK_STEP_EXISTS). If not, validation stops here for
             the same reason.
          3. Once a real step is in hand, every remaining check is
             evaluated independently (never short-circuited by an
             earlier one), so a single PreflightResult can report
             several problems at once:
               - the step's *current* status (as PlanManager already
                 tracks it - never recomputed or second-guessed here)
                 is STATUS_READY (CHECK_STEP_READY);
               - every dependency is resolved, via
                 PlanManager._unresolved_dependencies (
                 CHECK_DEPENDENCIES_SATISFIED);
               - every required capability is available, via
                 PlanManager._unavailable_capabilities (
                 CHECK_CAPABILITIES_AVAILABLE) - skipped (and a
                 warning added) when `capability_system` is None and
                 the step actually requires at least one capability,
                 since that check can't meaningfully be answered
                 without a registry to check against.

        `result.valid` is True only when no check above failed."""
        result = PreflightResult(plan_id, step_id)

        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            return result.add_failed_check(
                CHECK_PLAN_EXISTS, f"Unknown plan_id: {plan_id!r}"
            )

        step = self._plan_manager.get_step(plan_id, step_id)
        if step is None:
            return result.add_failed_check(
                CHECK_STEP_EXISTS,
                f"Unknown step_id {step_id!r} in plan_id {plan_id!r}",
            )

        if step.status != STATUS_READY:
            result.add_failed_check(
                CHECK_STEP_READY,
                f"Step {step_id!r} is not READY (current status: {step.status!r}).",
            )

        # Reuses PlanManager's own dependency logic - never a second
        # copy of it (requirement 5).
        unresolved = self._plan_manager._unresolved_dependencies(plan, step)
        if unresolved:
            result.add_failed_check(
                CHECK_DEPENDENCIES_SATISFIED,
                f"Step {step_id!r} has unresolved dependencies: {unresolved!r}.",
            )

        if capability_system is None:
            if step.required_capabilities:
                result.add_warning(
                    f"Step {step_id!r} requires capabilities "
                    f"{list(step.required_capabilities)!r}, but no "
                    "capability_system was supplied, so availability "
                    "was not checked."
                )
        else:
            # Reuses PlanManager's own capability-registry logic -
            # never a second copy of it (requirement 5).
            missing_caps = self._plan_manager._unavailable_capabilities(
                step, capability_system
            )
            if missing_caps:
                result.add_failed_check(
                    CHECK_CAPABILITIES_AVAILABLE,
                    f"Step {step_id!r} requires unavailable capabilities: "
                    f"{missing_caps!r}.",
                )

        return result
