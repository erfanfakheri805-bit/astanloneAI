"""
Planning - Adaptive Plan Analyzer
====================================
`AdaptivePlanAnalyzer` answers exactly one question - "given what this
project's own records already say about a Goal and one of its Plans,
what observable, already-recorded facts explain why that Plan has not
(yet) satisfied that Goal?" - and nothing broader than that:

    GOAL (planning/goal.py) + PLAN (planning/plan.py)
        -> [already executed, or partially executed, by
            execution/plan_execution_controller.py - unchanged]
        -> GoalCompletionEvaluator.evaluate  (planning/goal_completion.py:
           read-only "has this Plan already satisfied this Goal?")
        -> AdaptivePlanAnalyzer.analyze(goal_id, plan_id)
        -> a single, structured analysis result naming the *blockers*
           that already-recorded state shows

This is a second, narrower read-only inspector sitting next to
`GoalCompletionEvaluator` (planning/goal_completion.py), never a
replacement for it - `analyze`/`analyze_plan` both call straight into
`GoalCompletionEvaluator.evaluate`/`evaluate_plan` for the base
goal/plan verification and step classification (completed/failed/
blocked/remaining), and never re-derive that logic. What this module
adds on top is *why*: for every step that isn't COMPLETED, it inspects
the same already-existing capability/dependency/execution records this
project's own `PlanManager`, `PreflightValidator`,
`CapabilityHandlerRegistry`, `ExecutionHistory`, and `ExecutionEventLog`
already keep, and turns what it finds there into a small set of
structured `Blocker` records.

It never runs a step, never calls a capability handler, never creates
or mutates a Goal/Plan/PlanStep, never retries anything, never creates
a new Plan, and never accesses the network or an external AI API. It
only ever reads already-recorded state from the collaborators handed
to its constructor, and turns that state into a small, fixed
vocabulary of blocker types via fixed, deterministic rules - the same
"no fake intelligence" convention already documented by
`reasoning/reasoning_result.py` and `planning/goal_completion.py`.

Every fact this module reports is already sitting in the existing data
model:
  - `Goal`/`Plan`/`PlanStep` (planning/goal.py, planning/plan.py);
  - the step classification and Goal-satisfaction state already
    computed by `GoalCompletionEvaluator` (planning/goal_completion.py);
  - dependency resolution, via the exact same
    `PlanManager._unresolved_dependencies` helper `PreflightValidator`
    (execution/preflight.py) and `StepExecutionPreparation`
    (execution/step_execution_preparation.py) already call directly;
  - capability/handler readiness, via
    `CapabilityHandlerRegistry.check_execution_readiness`
    (execution/capability_handlers.py) when a registry is supplied, or
    a small, read-only capability-registry lookup (the same shape
    `PlanManager._capability_registry_lookup` already uses) when only
    a bare `capability_system` is supplied;
  - recorded execution outcomes, via `ExecutionHistory`
    (execution/execution_history.py) and `ExecutionEventLog`
    (execution/execution_event_log.py), both entirely optional.

Nothing here invents a blocker. A blocker is only ever reported when
the underlying, already-stored state actually shows it (a step really
is FAILED, a dependency really doesn't resolve, a capability really
isn't registered, ...); when a collaborator needed to check something
(e.g. `capability_system` for capability availability) wasn't supplied,
this module adds a warning explaining what couldn't be checked rather
than guessing at an answer - same "no evidence, no answer" rule
`GoalCompletionEvaluator` already applies via `STATE_UNKNOWN`.
"""

import itertools

from .goal_manager import GoalManager
from .plan_manager import PlanManager
from .goal_completion import (
    GoalCompletionEvaluator,
    STATE_SATISFIED,
    STATE_BLOCKED,
    STATE_FAILED,
    STATE_UNKNOWN,
)
from .plan import STATUS_COMPLETED

# ----------------------------------------------------------------------
# Controlled vocabularies (requirements 9, 11)
# ----------------------------------------------------------------------
ANALYSIS_COMPLETE = "COMPLETE"
ANALYSIS_INCOMPLETE = "INCOMPLETE"
ANALYSIS_BLOCKED = "BLOCKED"
ANALYSIS_FAILED = "FAILED"
ANALYSIS_UNKNOWN = "UNKNOWN"

ALL_ANALYSIS_STATUSES = (
    ANALYSIS_COMPLETE, ANALYSIS_INCOMPLETE, ANALYSIS_BLOCKED,
    ANALYSIS_FAILED, ANALYSIS_UNKNOWN,
)

BLOCKER_MISSING_STEP = "MISSING_STEP"
BLOCKER_FAILED_STEP = "FAILED_STEP"
BLOCKER_BLOCKED_STEP = "BLOCKED_STEP"
BLOCKER_MISSING_CAPABILITY = "MISSING_CAPABILITY"
BLOCKER_UNAVAILABLE_CAPABILITY = "UNAVAILABLE_CAPABILITY"
BLOCKER_MISSING_HANDLER = "MISSING_HANDLER"
BLOCKER_UNRESOLVED_DEPENDENCY = "UNRESOLVED_DEPENDENCY"
BLOCKER_MISSING_INPUT = "MISSING_INPUT"
BLOCKER_MISSING_OUTPUT = "MISSING_OUTPUT"
BLOCKER_EXECUTION_FAILURE = "EXECUTION_FAILURE"
BLOCKER_GOAL_NOT_SATISFIED = "GOAL_NOT_SATISFIED"
# Self-upgrade-request-only blocker (Prompt 358): the supplied
# SelfUpgradeRequest itself is missing/malformed - never reported for
# Goal/Plan analysis (`analyze`/`analyze_plan`), only for
# `analyze_self_upgrade_request` below. Added to the same fixed
# vocabulary rather than a second, parallel one (requirement 8: "do
# not create duplicate planning or analysis systems").
BLOCKER_INVALID_REQUEST = "INVALID_REQUEST"

ALL_BLOCKER_TYPES = (
    BLOCKER_MISSING_STEP, BLOCKER_FAILED_STEP, BLOCKER_BLOCKED_STEP,
    BLOCKER_MISSING_CAPABILITY, BLOCKER_UNAVAILABLE_CAPABILITY,
    BLOCKER_MISSING_HANDLER, BLOCKER_UNRESOLVED_DEPENDENCY,
    BLOCKER_MISSING_INPUT, BLOCKER_MISSING_OUTPUT,
    BLOCKER_EXECUTION_FAILURE, BLOCKER_GOAL_NOT_SATISFIED,
    BLOCKER_INVALID_REQUEST,
)

SEVERITY_LOW = "low"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"
SEVERITY_CRITICAL = "critical"

ALL_SEVERITIES = (SEVERITY_LOW, SEVERITY_MEDIUM, SEVERITY_HIGH, SEVERITY_CRITICAL)

# Fixed severity for each blocker type - never guessed per-instance,
# always the same severity for the same kind of observed problem
# (requirement 9: deterministic).
_SEVERITY_BY_BLOCKER_TYPE = {
    BLOCKER_MISSING_STEP: SEVERITY_HIGH,
    BLOCKER_FAILED_STEP: SEVERITY_CRITICAL,
    BLOCKER_BLOCKED_STEP: SEVERITY_HIGH,
    BLOCKER_MISSING_CAPABILITY: SEVERITY_HIGH,
    BLOCKER_UNAVAILABLE_CAPABILITY: SEVERITY_HIGH,
    BLOCKER_MISSING_HANDLER: SEVERITY_HIGH,
    BLOCKER_UNRESOLVED_DEPENDENCY: SEVERITY_MEDIUM,
    BLOCKER_MISSING_INPUT: SEVERITY_MEDIUM,
    BLOCKER_MISSING_OUTPUT: SEVERITY_MEDIUM,
    BLOCKER_EXECUTION_FAILURE: SEVERITY_CRITICAL,
    BLOCKER_GOAL_NOT_SATISFIED: SEVERITY_HIGH,
    BLOCKER_INVALID_REQUEST: SEVERITY_CRITICAL,
}


class Blocker:
    """One structured, read-only record of a single observed reason a
    Plan has not satisfied its Goal. Purely a data record - same
    "plain data in, plain data out, nothing hidden" convention the
    rest of this project already follows (see
    execution/execution_result.py's own module docstring). Nothing
    here decides *to* do anything about the blocker it describes; it
    only names what was already observed.
    """

    __slots__ = (
        "blocker_id", "type", "description", "source", "step_id",
        "severity", "evidence",
    )

    def __init__(
        self, blocker_id, type, description, source, step_id=None,
        severity=None, evidence=None,
    ):
        if type not in ALL_BLOCKER_TYPES:
            raise ValueError(f"Unknown blocker type: {type!r}")
        resolved_severity = severity if severity is not None else _SEVERITY_BY_BLOCKER_TYPE[type]
        if resolved_severity not in ALL_SEVERITIES:
            raise ValueError(f"Unknown blocker severity: {resolved_severity!r}")

        self.blocker_id = blocker_id
        self.type = type
        self.description = description
        self.source = source
        self.step_id = step_id
        self.severity = resolved_severity
        self.evidence = list(evidence) if evidence else []

    def __repr__(self):
        return (
            f"Blocker(blocker_id={self.blocker_id!r}, type={self.type!r}, "
            f"step_id={self.step_id!r}, severity={self.severity!r})"
        )

    def to_dict(self):
        return {
            "blocker_id": self.blocker_id,
            "type": self.type,
            "description": self.description,
            "source": self.source,
            "step_id": self.step_id,
            "severity": self.severity,
            "evidence": list(self.evidence),
        }


# Analysis-status derived directly from GoalCompletionEvaluator's own
# STATE_* vocabulary - a simple relabeling, never a re-derivation of
# *when* a Goal counts as satisfied/failed/blocked (requirement: "do
# not invent blockers" applies equally to not inventing a second,
# disagreeing notion of completion).
_ANALYSIS_STATUS_BY_STATE = {
    STATE_SATISFIED: ANALYSIS_COMPLETE,
    STATE_FAILED: ANALYSIS_FAILED,
    STATE_BLOCKED: ANALYSIS_BLOCKED,
    STATE_UNKNOWN: ANALYSIS_UNKNOWN,
    # STATE_NOT_SATISFIED / STATE_PARTIALLY_SATISFIED both fall
    # through to INCOMPLETE - see analyze()'s own final mapping step,
    # which also downgrades COMPLETE to INCOMPLETE if any blocker was
    # actually observed despite the evaluator reporting SATISFIED
    # (e.g. a COMPLETED step missing its declared output).
}


class AdaptivePlanAnalyzer:
    """Not thread-safe (matches the rest of this project - see
    GoalCompletionEvaluator/AgentLoop's own notes). Safe to use one
    instance per Core / per conversation session.

    `goal_manager` and `plan_manager` are required - same collaborators
    `GoalCompletionEvaluator` itself already requires. Every other
    collaborator is optional and purely additive: omitting one simply
    means the corresponding evidence can't be gathered (a warning is
    added instead), never that this raises or guesses.

      - `goal_completion_evaluator`: reused as-is if given; otherwise a
        new `GoalCompletionEvaluator` is built from `goal_manager`/
        `plan_manager` - never a second, disagreeing implementation of
        goal-completion logic.
      - `capability_system`: the project's
        `capabilities.capability_system.CapabilitySystem` (or anything
        exposing the same `.all()` registry lookup) - used to tell a
        missing (unregistered) capability apart from an unavailable
        (registered but disabled) one.
      - `capability_handlers`: an `execution.capability_handlers.
        CapabilityHandlerRegistry` - when given, its own read-only
        `check_execution_readiness` is reused directly rather than a
        second copy of that logic.
      - `executable_capabilities`: an `execution.executable_registry.
        ExecutableCapabilityRegistry` - passed straight through to
        `check_execution_readiness` when both it and
        `capability_handlers` are given.
      - `execution_history` / `event_log`: `execution.execution_history.
        ExecutionHistory` / `execution.execution_event_log.
        ExecutionEventLog` - when given, used to attach concrete
        `ExecutionResult`/`ExecutionEvent` evidence to FAILED-step
        blockers.
    """

    def __init__(
        self,
        goal_manager,
        plan_manager,
        goal_completion_evaluator=None,
        capability_system=None,
        capability_handlers=None,
        executable_capabilities=None,
        execution_history=None,
        event_log=None,
    ):
        if not isinstance(goal_manager, GoalManager):
            raise TypeError("AdaptivePlanAnalyzer requires a GoalManager instance.")
        if not isinstance(plan_manager, PlanManager):
            raise TypeError("AdaptivePlanAnalyzer requires a PlanManager instance.")
        if goal_completion_evaluator is not None and not isinstance(
            goal_completion_evaluator, GoalCompletionEvaluator
        ):
            raise TypeError(
                "AdaptivePlanAnalyzer's goal_completion_evaluator must be a "
                "GoalCompletionEvaluator instance."
            )

        # Optional collaborators are validated lazily against their own
        # modules only when actually supplied, to avoid a hard import
        # cycle between planning/ and execution/ for callers that never
        # pass them (planning/ has never imported execution/ before
        # this module - see planning/goal_completion.py's own
        # docstring, which is careful about the same thing).
        if capability_handlers is not None:
            from execution.capability_handlers import CapabilityHandlerRegistry
            if not isinstance(capability_handlers, CapabilityHandlerRegistry):
                raise TypeError(
                    "AdaptivePlanAnalyzer's capability_handlers must be a "
                    "CapabilityHandlerRegistry instance."
                )
        if executable_capabilities is not None:
            from execution.executable_registry import ExecutableCapabilityRegistry
            if not isinstance(executable_capabilities, ExecutableCapabilityRegistry):
                raise TypeError(
                    "AdaptivePlanAnalyzer's executable_capabilities must be an "
                    "ExecutableCapabilityRegistry instance."
                )
        if execution_history is not None:
            from execution.execution_history import ExecutionHistory
            if not isinstance(execution_history, ExecutionHistory):
                raise TypeError(
                    "AdaptivePlanAnalyzer's execution_history must be an "
                    "ExecutionHistory instance."
                )
        if event_log is not None:
            from execution.execution_event_log import ExecutionEventLog
            if not isinstance(event_log, ExecutionEventLog):
                raise TypeError(
                    "AdaptivePlanAnalyzer's event_log must be an "
                    "ExecutionEventLog instance."
                )

        self._goal_manager = goal_manager
        self._plan_manager = plan_manager
        self._evaluator = (
            goal_completion_evaluator if goal_completion_evaluator is not None
            else GoalCompletionEvaluator(goal_manager, plan_manager)
        )
        self._capability_system = capability_system
        self._capability_handlers = capability_handlers
        self._executable_capabilities = executable_capabilities
        self._execution_history = execution_history
        self._event_log = event_log

    # ------------------------------------------------------------------
    # Result shaping (requirement 8)
    # ------------------------------------------------------------------
    def _result(
        self, goal_id, plan_id, goal_status, plan_status, analysis_status,
        blockers, completed_steps, incomplete_steps, failed_steps,
        blocked_steps, missing_capabilities, missing_handlers,
        unresolved_dependencies, missing_outputs, evidence, warnings,
    ):
        return {
            "goal_id": goal_id,
            "plan_id": plan_id,
            "goal_status": goal_status,
            "plan_status": plan_status,
            "analysis_status": analysis_status,
            "blockers": [b.to_dict() for b in blockers],
            "completed_steps": list(completed_steps),
            "incomplete_steps": list(incomplete_steps),
            "failed_steps": list(failed_steps),
            "blocked_steps": list(blocked_steps),
            "missing_capabilities": list(missing_capabilities),
            "missing_handlers": list(missing_handlers),
            "unresolved_dependencies": list(unresolved_dependencies),
            "missing_outputs": list(missing_outputs),
            "evidence": list(evidence),
            "warnings": list(warnings),
        }

    def _unknown_result(self, goal_id, plan_id, message):
        return self._result(
            goal_id, plan_id, STATE_UNKNOWN, None, ANALYSIS_UNKNOWN,
            [], [], [], [], [], [], [], [], [], [], [message],
        )

    @staticmethod
    def _merge(target_list, source_list):
        """Append every item of `source_list` not already present in
        `target_list`, preserving order - same "accumulate without
        duplicating" convention `AgentLoop._merge` already uses."""
        for item in source_list:
            if item not in target_list:
                target_list.append(item)

    # ------------------------------------------------------------------
    # Capability/handler readiness per step (requirement 6)
    # ------------------------------------------------------------------
    def _capability_registry_lookup(self):
        """Same read-only `{name: row}` shape
        `PlanManager._capability_registry_lookup` already builds - a
        single lookup, never a second copy of the registry contents,
        computed once per `analyze`/`analyze_plan` call rather than
        once per step. Returns `{}` when no `capability_system` was
        supplied."""
        if self._capability_system is None:
            return {}
        return {row["name"]: row for row in self._capability_system.all()}

    def _step_capability_readiness(self, step, registry_lookup):
        """Returns (missing_capabilities, unavailable_capabilities,
        missing_handlers, warnings) for one step's
        `required_capabilities`, using whichever collaborators are
        actually available:

          - when `capability_handlers` was supplied, its own read-only
            `check_execution_readiness` is reused directly (requirement
            "reuse existing ... logic wherever possible") - this
            already tells a missing (unregistered) capability apart
            from an unavailable (registered-but-disabled) one, and
            already checks handler registration (optionally via
            `executable_capabilities` too);
          - otherwise, when only `capability_system` was supplied, a
            small, read-only registry lookup (same shape
            `PlanManager._capability_registry_lookup` already uses)
            tells missing apart from unavailable, but handler
            registration can't be checked at all without a
            `CapabilityHandlerRegistry` - `missing_handlers` is always
            `[]` in that case;
          - when neither was supplied, nothing can be checked; a
            warning explains that, rather than guessing.

        Never calls a handler, never registers/enables/disables a
        capability or a handler - read-only throughout."""
        if not step.required_capabilities:
            return [], [], [], []

        if self._capability_handlers is not None:
            readiness = self._capability_handlers.check_execution_readiness(
                step, self._capability_system, self._executable_capabilities,
            )
            return (
                list(readiness.missing_capabilities),
                list(readiness.unavailable_capabilities),
                list(readiness.missing_handlers),
                list(readiness.warnings),
            )

        if self._capability_system is not None:
            missing = []
            unavailable = []
            for cap_name in step.required_capabilities:
                row = registry_lookup.get(cap_name)
                if row is None:
                    missing.append(cap_name)
                elif not bool(row["enabled"]):
                    unavailable.append(cap_name)
            return missing, unavailable, [], []

        return [], [], [], [
            f"Step {step.step_id!r} requires capabilities "
            f"{list(step.required_capabilities)!r}, but neither a "
            "capability_system nor a capability_handlers registry was "
            "supplied to AdaptivePlanAnalyzer, so capability/handler "
            "readiness was not checked."
        ]

    # ------------------------------------------------------------------
    # Blocker discovery (requirements 6, 7, 10, 11, 12)
    # ------------------------------------------------------------------
    def _find_blockers(self, plan, evaluation):
        """Inspect `plan`'s steps and `evaluation` (a
        `GoalCompletionEvaluator.evaluate`/`evaluate_plan` result) for
        every observable blocker this module knows how to name, and
        return `(blockers, missing_capabilities, missing_handlers,
        unresolved_dependencies, missing_outputs, warnings)`. Purely
        read-only - never touches `plan`, a `PlanStep`, a Goal, a
        capability, or a handler."""
        blockers = []
        missing_capabilities = []
        missing_handlers = []
        unresolved_dependencies = []
        missing_outputs = []
        warnings = []

        # Local, per-call id counter (requirement 9 - deterministic):
        # reset every call, so the same observed state always produces
        # the same blocker_ids, never a value that depends on how many
        # times this analyzer has been called before.
        next_id = itertools.count(1)

        def new_blocker_id():
            return f"blocker-{plan.plan_id}-{next(next_id)}"

        steps_by_id = {step.step_id: step for step in plan.steps}
        failed_step_ids = set(evaluation["failed_steps"])
        blocked_step_ids = set(evaluation["blocked_steps"])
        completed_step_ids = set(evaluation["completed_steps"])

        registry_lookup = self._capability_registry_lookup()

        for step in plan.steps:
            step_id = step.step_id

            # --- FAILED_STEP / EXECUTION_FAILURE --------------------
            if step_id in failed_step_ids:
                evidence = [f"Step {step_id!r} has status FAILED."]
                execution_result = None
                if self._execution_history is not None:
                    execution_result = self._execution_history.latest_for_step(
                        plan.plan_id, step_id
                    )
                    if execution_result is not None:
                        evidence.append(
                            f"ExecutionResult {execution_result.execution_id!r} "
                            f"recorded status={execution_result.status!r}, "
                            f"error={execution_result.error!r}."
                        )
                blockers.append(Blocker(
                    new_blocker_id(), BLOCKER_FAILED_STEP,
                    f"Step {step_id!r} ({step.description}) failed.",
                    source="goal_completion_evaluator",
                    step_id=step_id, evidence=evidence,
                ))
                if execution_result is not None and execution_result.status == "failed":
                    exec_evidence = list(evidence)
                    if self._event_log is not None:
                        error_events = [
                            event for event in self._event_log.list_for_step(plan.plan_id, step_id)
                            if event.is_error()
                        ]
                        for event in error_events:
                            exec_evidence.append(
                                f"ExecutionEvent {event.event_id!r} ({event.event_type}): "
                                f"{event.message}"
                            )
                    blockers.append(Blocker(
                        new_blocker_id(), BLOCKER_EXECUTION_FAILURE,
                        f"Step {step_id!r} has a recorded execution failure: "
                        f"{execution_result.error!r}.",
                        source="execution_history",
                        step_id=step_id, evidence=exec_evidence,
                    ))

            # --- MISSING_STEP / UNRESOLVED_DEPENDENCY ----------------
            if step_id not in completed_step_ids:
                for dep_id in step.dependencies:
                    dep_step = steps_by_id.get(dep_id)
                    if dep_step is None:
                        unresolved_dependencies.append({
                            "step_id": step_id, "dependency_id": dep_id,
                            "reason": "missing_step",
                        })
                        blockers.append(Blocker(
                            new_blocker_id(), BLOCKER_MISSING_STEP,
                            f"Step {step_id!r} depends on {dep_id!r}, which does "
                            "not exist in this plan.",
                            source="plan_manager.dependencies",
                            step_id=step_id,
                            evidence=[
                                f"Step {step_id!r} dependencies: "
                                f"{list(step.dependencies)!r}.",
                                f"No step with step_id {dep_id!r} exists in plan "
                                f"{plan.plan_id!r}.",
                            ],
                        ))
                    elif dep_step.status != STATUS_COMPLETED:
                        unresolved_dependencies.append({
                            "step_id": step_id, "dependency_id": dep_id,
                            "reason": "not_completed",
                        })
                        blockers.append(Blocker(
                            new_blocker_id(), BLOCKER_UNRESOLVED_DEPENDENCY,
                            f"Step {step_id!r} depends on {dep_id!r}, which is not "
                            "COMPLETED.",
                            source="plan_manager.dependencies",
                            step_id=step_id,
                            evidence=[
                                f"Dependency step {dep_id!r} currently has status "
                                f"{dep_step.status!r}.",
                            ],
                        ))

            # --- MISSING_CAPABILITY / UNAVAILABLE_CAPABILITY / -------
            # --- MISSING_HANDLER (only for steps not yet COMPLETED) --
            if step_id not in completed_step_ids and step.required_capabilities:
                (step_missing_caps, step_unavailable_caps, step_missing_handlers,
                 cap_warnings) = self._step_capability_readiness(step, registry_lookup)
                self._merge(warnings, cap_warnings)
                self._merge(missing_capabilities, step_missing_caps)
                self._merge(missing_capabilities, step_unavailable_caps)
                self._merge(missing_handlers, step_missing_handlers)

                for cap_name in step_missing_caps:
                    blockers.append(Blocker(
                        new_blocker_id(), BLOCKER_MISSING_CAPABILITY,
                        f"Step {step_id!r} requires capability {cap_name!r}, "
                        "which is not registered.",
                        source="capability_system",
                        step_id=step_id,
                        evidence=[f"Capability {cap_name!r} was not found in the capability registry."],
                    ))
                for cap_name in step_unavailable_caps:
                    blockers.append(Blocker(
                        new_blocker_id(), BLOCKER_UNAVAILABLE_CAPABILITY,
                        f"Step {step_id!r} requires capability {cap_name!r}, "
                        "which is registered but not enabled.",
                        source="capability_system",
                        step_id=step_id,
                        evidence=[f"Capability {cap_name!r} is registered but currently disabled."],
                    ))
                for cap_name in step_missing_handlers:
                    blockers.append(Blocker(
                        new_blocker_id(), BLOCKER_MISSING_HANDLER,
                        f"Step {step_id!r} requires capability {cap_name!r}, "
                        "which has no registered handler.",
                        source="capability_handlers",
                        step_id=step_id,
                        evidence=[f"No handler is registered for capability {cap_name!r}."],
                    ))

            # --- BLOCKED_STEP (summary) -------------------------------
            if step_id in blocked_step_ids:
                blocked_evidence = [f"Step {step_id!r} has status BLOCKED."]
                own_unresolved = [
                    entry for entry in unresolved_dependencies if entry["step_id"] == step_id
                ]
                if own_unresolved:
                    blocked_evidence.append(
                        f"Unresolved dependencies: {[e['dependency_id'] for e in own_unresolved]!r}."
                    )
                blockers.append(Blocker(
                    new_blocker_id(), BLOCKER_BLOCKED_STEP,
                    f"Step {step_id!r} ({step.description}) is BLOCKED.",
                    source="goal_completion_evaluator",
                    step_id=step_id, evidence=blocked_evidence,
                ))

            # --- MISSING_INPUT ----------------------------------------
            if (
                step_id not in completed_step_ids
                and step.dependencies
                and step.get_input() is None
            ):
                dep_statuses = [
                    steps_by_id.get(dep_id) for dep_id in step.dependencies
                ]
                all_resolved = all(
                    dep is not None and dep.status == STATUS_COMPLETED for dep in dep_statuses
                )
                if all_resolved:
                    blockers.append(Blocker(
                        new_blocker_id(), BLOCKER_MISSING_INPUT,
                        f"Step {step_id!r} has all dependencies COMPLETED but "
                        "no input_data has ever been recorded for it.",
                        source="plan.step",
                        step_id=step_id,
                        evidence=[
                            f"Dependencies {list(step.dependencies)!r} are all COMPLETED.",
                            f"Step {step_id!r}.input_data is None.",
                        ],
                    ))

            # --- MISSING_OUTPUT ----------------------------------------
            if (
                step_id in completed_step_ids
                and step.expected_output is not None
                and step.output_data is None
            ):
                missing_outputs.append({
                    "step_id": step_id, "expected_output": step.expected_output,
                })
                blockers.append(Blocker(
                    new_blocker_id(), BLOCKER_MISSING_OUTPUT,
                    f"Step {step_id!r} is COMPLETED and declares expected_output "
                    f"{step.expected_output!r}, but has no recorded output_data.",
                    source="plan.step",
                    step_id=step_id,
                    evidence=[
                        f"Step {step_id!r} status is COMPLETED.",
                        f"Step {step_id!r}.expected_output = {step.expected_output!r}.",
                        f"Step {step_id!r}.output_data is None.",
                    ],
                ))

        # --- GOAL_NOT_SATISFIED (plan-level, requirement: "plan --------
        # completion without goal satisfaction") -----------------------
        # `Plan.status` is only ever set at creation time or by an
        # explicit caller (see goal_completion.py's own module
        # docstring) - it is never auto-derived from step state. A Plan
        # explicitly marked COMPLETED whose steps do *not* actually
        # show the Goal as satisfied is exactly the discrepancy this
        # blocker names - already-observed evidence, never a guess.
        if plan.status == STATUS_COMPLETED and evaluation["status"] != STATE_SATISFIED:
            blockers.append(Blocker(
                new_blocker_id(), BLOCKER_GOAL_NOT_SATISFIED,
                f"Plan {plan.plan_id!r}.status is COMPLETED, but goal evaluation "
                f"reports {evaluation['status']!r}.",
                source="goal_completion_evaluator",
                step_id=None,
                evidence=[
                    f"Plan.status field currently records {plan.status!r}.",
                    f"Goal-completion evaluation currently reports "
                    f"{evaluation['status']!r} from step-level state.",
                ],
            ))

        return (
            blockers, missing_capabilities, missing_handlers,
            unresolved_dependencies, missing_outputs, warnings,
        )

    # ------------------------------------------------------------------
    # Shared analysis core (used by both analyze/analyze_plan)
    # ------------------------------------------------------------------
    def _analyze_plan_state(self, goal_id, plan, evaluation):
        blockers, missing_capabilities, missing_handlers, unresolved_dependencies, \
            missing_outputs, cap_warnings = self._find_blockers(plan, evaluation)

        evidence = list(evaluation["evidence"])
        warnings = list(evaluation["warnings"])
        self._merge(warnings, cap_warnings)
        if blockers:
            evidence.append(f"Found {len(blockers)} blocker(s) for plan {plan.plan_id!r}.")

        goal_status = evaluation["status"]
        analysis_status = _ANALYSIS_STATUS_BY_STATE.get(goal_status, ANALYSIS_INCOMPLETE)
        if analysis_status == ANALYSIS_COMPLETE and blockers:
            # The evaluator reports every step COMPLETED, but at least
            # one blocker (e.g. a missing declared output) was still
            # observed - never silently claim COMPLETE over an actual,
            # already-observed problem.
            analysis_status = ANALYSIS_INCOMPLETE

        return self._result(
            goal_id, plan.plan_id, goal_status, plan.status, analysis_status,
            blockers, evaluation["completed_steps"], evaluation["remaining_steps"],
            evaluation["failed_steps"], evaluation["blocked_steps"],
            missing_capabilities, missing_handlers, unresolved_dependencies,
            missing_outputs, evidence, warnings,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def analyze(self, goal_id, plan_id):
        """Analyze why the Plan `plan_id` has not (yet) satisfied the
        Goal `goal_id`, using only what `GoalManager`/`PlanManager`
        (and whichever optional collaborators were supplied to this
        analyzer) already have on record.

        Verifies, in order, before looking at any step-level state -
        the exact same checks, in the exact same order,
        `GoalCompletionEvaluator.evaluate` itself already performs
        (requirements 1, 2, 3):
          1. `goal_id` resolves to a real, stored Goal;
          2. `plan_id` resolves to a real, stored Plan;
          3. that Plan's own `goal_id` actually matches the requested
             `goal_id`.
        Each failure returns `analysis_status=UNKNOWN` with a warning
        explaining exactly which check failed, rather than raising -
        never raises for an unknown/mismatched id.

        Read-only throughout (requirement 12): never modifies the
        Goal, the Plan, any PlanStep, never executes a capability or a
        step, never retries anything, never creates a capability or a
        new Plan, never accesses the network, and never calls an
        external AI API.

        Returns the structured dict described in this module's
        docstring / requirement 8.
        """
        goal = self._goal_manager.get_goal(goal_id)
        if goal is None:
            return self._unknown_result(goal_id, plan_id, f"No Goal found for goal_id {goal_id!r}.")

        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            return self._unknown_result(goal_id, plan_id, f"No Plan found for plan_id {plan_id!r}.")

        if plan.goal_id != goal_id:
            return self._unknown_result(
                goal_id, plan_id,
                f"Plan {plan_id!r} belongs to goal_id {plan.goal_id!r}, not the "
                f"requested goal_id {goal_id!r}; refusing to analyze a plan "
                "against a goal it isn't attached to.",
            )

        evaluation = self._evaluator.evaluate(goal_id, plan_id)
        return self._analyze_plan_state(goal_id, plan, evaluation)

    def analyze_plan(self, plan_id):
        """Analyze `plan_id`'s own state independently of any Goal -
        useful when a caller only has a `plan_id` on hand, or wants a
        plan's blockers without re-validating the Goal relationship
        `analyze` already checks (requirement 15).

        Same read-only contract, same fixed vocabularies, and the same
        structured result shape as `analyze`; `goal_id` in the
        returned dict is the Plan's own recorded `goal_id` (or `None`
        if `plan_id` isn't known at all) rather than one supplied by
        the caller, since there's nothing here to cross-check it
        against - same convention
        `GoalCompletionEvaluator.evaluate_plan` already follows.
        """
        plan = self._plan_manager.get_plan(plan_id)
        if plan is None:
            return self._unknown_result(None, plan_id, f"No Plan found for plan_id {plan_id!r}.")

        evaluation = self._evaluator.evaluate_plan(plan_id)
        return self._analyze_plan_state(plan.goal_id, plan, evaluation)

    # ------------------------------------------------------------------
    # Self-upgrade request analysis (Prompt 358)
    # ------------------------------------------------------------------
    # This connects `self_upgrade.self_upgrade_request.SelfUpgradeRequest`
    # (Prompt 357 - a plain, standalone record, not yet analyzed or
    # acted on by anything) to this module's own, already-existing
    # read-only inspection machinery:
    #
    #   SelfUpgradeRequest -> AdaptivePlanAnalyzer.analyze_self_upgrade_request
    #       -> {request_id, goal, requested_capability,
    #           required_capabilities, affected_systems, blockers}
    #
    # Same read-only contract as `analyze`/`analyze_plan` above: never
    # modifies the request, never registers/enables/disables a
    # capability or a handler, never calls a handler, never creates or
    # executes a Self-Upgrade (`self_upgrade.upgrade_system.
    # UpgradeSystem` is never imported or touched here), and never
    # accesses the network or an external AI API. It only reads
    # already-recorded state from the collaborators this analyzer was
    # already constructed with (`capability_system`,
    # `capability_handlers`) - the exact same two, already-existing
    # registries `_step_capability_readiness` above already reads for
    # Plan steps - and turns what it finds there into the same fixed,
    # already-existing blocker vocabulary (`BLOCKER_MISSING_CAPABILITY`,
    # `BLOCKER_UNAVAILABLE_CAPABILITY`, `BLOCKER_MISSING_HANDLER`), plus
    # one new, request-only blocker type (`BLOCKER_INVALID_REQUEST`)
    # for a missing/malformed request itself.
    #
    # `required_capabilities` is always exactly `[requested_capability]`
    # - a `SelfUpgradeRequest` only ever names one capability
    # (requirement: "determine required_capabilities ... using only
    # existing project information" - there is no second, richer
    # capability-dependency record anywhere in this project to expand
    # that single name into more than itself, so this never guesses at
    # any implied/related capability).
    #
    # `affected_systems` is always the already-recorded module(s) that
    # actually implement the requested capability - read straight off
    # whatever real handler `capability_handlers.get(...)` already
    # returns (`handler.__module__`, or `handler.handler.__module__`
    # for a `Capability` object - see `_handler_module` below), never
    # a guessed/derived system name. When no `capability_handlers`
    # registry was supplied, or no handler is registered for the
    # requested capability, `affected_systems` is left empty and a
    # warning explains why - same "no evidence, no answer" rule the
    # rest of this module already follows.
    def _self_upgrade_validation_problems(self, request):
        """List every reason `request.is_valid()` returned False, in
        the exact same order/checks `SelfUpgradeRequest.is_valid`
        itself performs - a plain explanation of an already-computed
        verdict, never a second, disagreeing validity check (only
        called after `request.is_valid()` has already returned
        False)."""
        problems = []
        if not isinstance(request.request_id, str) or not request.request_id.strip():
            problems.append("request_id is missing or empty")
        if not isinstance(request.goal, str) or not request.goal.strip():
            problems.append("goal is missing or empty")
        if not isinstance(request.requested_capability, str) or not request.requested_capability.strip():
            problems.append("requested_capability is missing or empty")
        if not isinstance(request.reason, str):
            problems.append("reason is not a string")
        from self_upgrade.self_upgrade_request import ALL_STATUSES
        if request.status not in ALL_STATUSES:
            problems.append(f"status {request.status!r} is not a recognized status")
        return problems

    @staticmethod
    def _handler_module(handler):
        """The already-recorded module a registered capability handler
        actually lives in - `handler.__module__` for a plain callable,
        or `handler.handler.__module__` for a `Capability`
        (execution/capability.py) object, whose real callable lives on
        its own `.handler` attribute. Returns `None` if that can't be
        read (never guessed at)."""
        from execution.capability import Capability
        target = handler.handler if isinstance(handler, Capability) else handler
        return getattr(target, "__module__", None)

    def _self_upgrade_result(
        self, request_id, goal, requested_capability,
        required_capabilities, affected_systems, blockers, warnings,
    ):
        return {
            "request_id": request_id,
            "goal": goal,
            "requested_capability": requested_capability,
            "required_capabilities": list(required_capabilities),
            "affected_systems": list(affected_systems),
            "blockers": [b.to_dict() for b in blockers],
            "warnings": list(warnings),
        }

    def analyze_self_upgrade_request(self, request):
        """Analyze one `SelfUpgradeRequest` (self_upgrade/
        self_upgrade_request.py, Prompt 357) using only this project's
        already-existing capability registries - never executes, never
        approves, never rejects, and never mutates `request` or any
        capability/handler registration.

        If `request` isn't a `SelfUpgradeRequest`, or `request.is_valid()`
        is False (a missing/blank `request_id`/`goal`/
        `requested_capability`, a non-string `reason`, or an unknown
        `status`), this returns a single `BLOCKER_INVALID_REQUEST`
        blocker explaining exactly which check failed, and never
        guesses at `required_capabilities`/`affected_systems` for an
        incomplete request (requirement 5).

        For a valid request, returns the structured dict:
            {
                "request_id": str,
                "goal": str,
                "requested_capability": str,
                "required_capabilities": [requested_capability],
                "affected_systems": [<module names of any already-
                    registered handler for requested_capability>],
                "blockers": [Blocker.to_dict(), ...],
                "warnings": [str, ...],
            }
        with a `BLOCKER_MISSING_CAPABILITY`/`BLOCKER_UNAVAILABLE_CAPABILITY`
        blocker when `capability_system` was supplied and shows the
        requested capability isn't registered/enabled there, and a
        `BLOCKER_MISSING_HANDLER` blocker when `capability_handlers`
        was supplied and shows no handler registered for it - the same
        two, already-existing collaborators/vocabulary
        `_step_capability_readiness` already uses for Plan steps.
        """
        from self_upgrade.self_upgrade_request import SelfUpgradeRequest

        next_id = itertools.count(1)

        def new_blocker_id():
            request_id = getattr(request, "request_id", None) or "unknown"
            return f"blocker-self-upgrade-{request_id}-{next(next_id)}"

        if not isinstance(request, SelfUpgradeRequest):
            blocker = Blocker(
                new_blocker_id(), BLOCKER_INVALID_REQUEST,
                "The supplied object is not a SelfUpgradeRequest instance.",
                source="self_upgrade_request",
                evidence=[f"type(request) = {type(request).__name__!r}"],
            )
            return self._self_upgrade_result(None, None, None, [], [], [blocker], [])

        if not request.is_valid():
            problems = self._self_upgrade_validation_problems(request)
            blocker = Blocker(
                new_blocker_id(), BLOCKER_INVALID_REQUEST,
                "SelfUpgradeRequest is not valid: " + "; ".join(problems) + ".",
                source="self_upgrade_request.is_valid",
                evidence=list(problems),
            )
            return self._self_upgrade_result(
                request.request_id, request.goal, request.requested_capability,
                [], [], [blocker], [],
            )

        cap_name = request.requested_capability
        required_capabilities = [cap_name]
        affected_systems = []
        blockers = []
        warnings = []

        if self._capability_handlers is not None:
            handler = self._capability_handlers.get(cap_name)
            if handler is None:
                blockers.append(Blocker(
                    new_blocker_id(), BLOCKER_MISSING_HANDLER,
                    f"No handler is registered for capability {cap_name!r} in "
                    "the supplied capability_handlers registry.",
                    source="capability_handlers",
                    evidence=[f"capability_handlers.get({cap_name!r}) is None."],
                ))
            else:
                module = self._handler_module(handler)
                if module:
                    affected_systems.append(module)
        else:
            warnings.append(
                "No capability_handlers registry was supplied to "
                "AdaptivePlanAnalyzer, so affected_systems for capability "
                f"{cap_name!r} could not be determined."
            )

        if self._capability_system is not None:
            registry_lookup = self._capability_registry_lookup()
            row = registry_lookup.get(cap_name)
            if row is None:
                blockers.append(Blocker(
                    new_blocker_id(), BLOCKER_MISSING_CAPABILITY,
                    f"Capability {cap_name!r} is not registered in the "
                    "supplied capability_system.",
                    source="capability_system",
                    evidence=[f"{cap_name!r} not found in capability_system.all()."],
                ))
            elif not bool(row["enabled"]):
                blockers.append(Blocker(
                    new_blocker_id(), BLOCKER_UNAVAILABLE_CAPABILITY,
                    f"Capability {cap_name!r} is registered but not enabled "
                    "in the supplied capability_system.",
                    source="capability_system",
                    evidence=[f"capability_system row for {cap_name!r}: {dict(row)!r}"],
                ))
        else:
            warnings.append(
                "No capability_system was supplied to AdaptivePlanAnalyzer, "
                f"so it could not be verified whether capability {cap_name!r} "
                "is registered/enabled."
            )

        return self._self_upgrade_result(
            request.request_id, request.goal, request.requested_capability,
            required_capabilities, affected_systems, blockers, warnings,
        )
